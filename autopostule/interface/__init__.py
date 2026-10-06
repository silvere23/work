"""Interface web locale : `autopostule interface` ouvre l'application dans le navigateur.

Elle n'écoute que sur 127.0.0.1 (l'ordinateur de l'utilisateur) et protège chaque formulaire par un jeton
secret, pour qu'aucun autre site ouvert dans le navigateur ne puisse déclencher d'action.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
from pathlib import Path

import yaml
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_file, url_for

from .. import __version__, cv_adapte
from ..candidature import Atelier, offre_depuis_ligne
from ..cli import ENV_EXEMPLE, generer, importer_alertes, preparer_offres, rechercher, rechercher_offres, scanner
from ..config import EXEMPLE, ErreurConfig, charger, contrats_vises, lire_yaml
from ..cv import analyser_fichier
from ..envoi import envoyer_candidatures
from ..offres import mots_cles, offre_depuis_texte, offre_depuis_url, titre_propre, deduire_metier
from ..referentiel import CONTRATS, METIERS, REGIONS, contrats_valides, libelle_contrats, trouver_metier, trouver_region
from ..stockage import Base
from .taches import Gestionnaire

FICHIER_PREFERENCES = Path.home() / ".autopostule.json"
SECRETS = {
    "AUTOPOSTULE_SMTP_PASSWORD": "Mot de passe SMTP (Gmail : mot de passe d'application)",
    "FRANCE_TRAVAIL_CLIENT_ID": "France Travail - identifiant client",
    "FRANCE_TRAVAIL_CLIENT_SECRET": "France Travail - clé secrète",
    "ADZUNA_APP_ID": "Adzuna - Application ID",
    "ADZUNA_APP_KEY": "Adzuna - Application Key",
    "JOOBLE_API_KEY": "Jooble - clé API",
    "ANTHROPIC_API_KEY": "Claude (facultatif, rédaction par IA)",
}
STATUTS_CANDIDATURE = ["brouillon", "approuvee", "envoyee", "echec", "ignoree"]
STATUTS_OFFRE = ["nouvelle", "preparee", "postulee", "a_postuler_sur_site", "postulee_sur_site", "ignoree"]


# --------------------------------------------------------------------------- #
# Dossier de travail, configuration et secrets
# --------------------------------------------------------------------------- #

def dossier_memorise() -> Path | None:
    try:
        return Path(json.loads(FICHIER_PREFERENCES.read_text(encoding="utf-8"))["dossier"])
    except (OSError, ValueError, KeyError):
        return None


def memoriser_dossier(dossier: Path) -> None:
    try:
        FICHIER_PREFERENCES.write_text(json.dumps({"dossier": str(dossier)}), encoding="utf-8")
    except OSError:
        pass


def initialiser_dossier(dossier: Path) -> None:
    """Crée config.yaml (profil vierge), .env et cv/ dans le dossier, sans rien écraser."""
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "cv").mkdir(exist_ok=True)
    config = dossier / "config.yaml"
    if not config.exists():
        shutil.copy(EXEMPLE, config)
        donnees = lire_yaml(config)
        donnees["profil"] = {k: ("" if isinstance(v, str) else v) for k, v in donnees["profil"].items()}
        donnees["profil"]["annees_experience"] = 0
        donnees["envoi"]["smtp_utilisateur"] = ""
        ecrire_config(config, donnees)
    env = dossier / ".env"
    if not env.exists():
        env.write_text(ENV_EXEMPLE, encoding="utf-8")


def ecrire_config(chemin: Path, donnees: dict) -> None:
    entete = ("# Configuration autopostule - modifiable depuis l'interface (autopostule interface)\n"
              "# ou à la main. Les secrets sont dans le fichier .env.\n\n")
    chemin.write_text(entete + yaml.safe_dump(donnees, allow_unicode=True, sort_keys=False, width=110),
                      encoding="utf-8")


def lire_env(chemin: Path) -> dict[str, str]:
    valeurs: dict[str, str] = {}
    if chemin.exists():
        for ligne in chemin.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            if "=" in ligne and not ligne.lstrip().startswith("#"):
                cle, valeur = ligne.split("=", 1)
                valeurs[cle.strip()] = valeur.strip()
    return valeurs


def ecrire_env(chemin: Path, nouvelles: dict[str, str]) -> None:
    """Met à jour les clés données (les autres lignes et commentaires sont conservés)."""
    lignes = chemin.read_text(encoding="utf-8-sig", errors="replace").splitlines() if chemin.exists() else []
    restantes = dict(nouvelles)
    for i, ligne in enumerate(lignes):
        if "=" in ligne and not ligne.lstrip().startswith("#"):
            cle = ligne.split("=", 1)[0].strip()
            if cle in restantes:
                lignes[i] = f"{cle}={restantes.pop(cle)}"
    lignes += [f"{cle}={valeur}" for cle, valeur in restantes.items()]
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    os.environ.update(nouvelles)  # pris en compte immédiatement, sans redémarrer


def _entier(valeur, defaut: int = 0) -> int:
    try:
        return int(str(valeur).strip())
    except (TypeError, ValueError):
        return defaut


def _liste_texte(valeur: str) -> list[str]:
    return [v.strip() for v in (valeur or "").replace(";", ",").split(",") if v.strip()]


# --------------------------------------------------------------------------- #
# Application
# --------------------------------------------------------------------------- #

def creer_app(dossier: Path | None = None, gestionnaire: Gestionnaire | None = None) -> Flask:
    app = Flask(__name__)
    app.secret_key = secrets.token_hex(16)
    app.config["DOSSIER"] = Path(dossier).resolve() if dossier else dossier_memorise()
    app.config["JETON"] = secrets.token_urlsafe(24)
    app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024
    taches = gestionnaire or Gestionnaire()
    app.extensions["taches"] = taches

    # -- utilitaires de requête -------------------------------------------- #

    def chemin_config() -> Path:
        return app.config["DOSSIER"] / "config.yaml"

    def config():
        return charger(chemin_config())

    def base(cfg=None):
        cfg = cfg or config()
        return Base(cfg.dossier_donnees / "autopostule.db")

    def lancer(titre: str, fonction):
        try:
            tache = taches.lancer(titre, fonction)
        except RuntimeError as erreur:
            flash(str(erreur), "erreur")
            return redirect(request.referrer or url_for("accueil"))
        return redirect(url_for("tache", id_=tache.id))

    @app.context_processor
    def contexte():
        return {"jeton": app.config["JETON"], "version": __version__, "dossier": app.config["DOSSIER"],
                "tache_courante": taches.courante if taches.occupe() else None, "METIERS": METIERS,
                "REGIONS": REGIONS, "CONTRATS": CONTRATS, "libelle_contrats": libelle_contrats}

    @app.before_request
    def garde():
        if request.method == "POST":
            jeton = request.form.get("_jeton") or request.headers.get("X-Jeton")
            if not jeton or not secrets.compare_digest(jeton, app.config["JETON"]):
                abort(403, "Jeton de formulaire invalide : rechargez la page.")
        libres = {"dossier", "static", "choisir_dossier"}
        if request.endpoint not in libres and (not app.config["DOSSIER"] or not chemin_config().exists()):
            return redirect(url_for("dossier"))

    @app.errorhandler(ErreurConfig)
    def erreur_config(erreur):
        return render_template("erreur.html", message=str(erreur)), 500

    # -- dossier de travail ------------------------------------------------- #

    @app.get("/dossier")
    def dossier():
        propose = app.config["DOSSIER"] or (Path.home() / "autopostule")
        return render_template("dossier.html", propose=propose)

    @app.post("/dossier")
    def choisir_dossier():
        chemin = Path(request.form.get("chemin", "").strip().strip('"')).expanduser()
        if not str(chemin):
            flash("Indiquez un dossier.", "erreur")
            return redirect(url_for("dossier"))
        initialiser_dossier(chemin)
        app.config["DOSSIER"] = chemin.resolve()
        memoriser_dossier(app.config["DOSSIER"])
        flash(f"Dossier de travail : {app.config['DOSSIER']}", "ok")
        return redirect(url_for("accueil"))

    # -- tableau de bord ---------------------------------------------------- #

    @app.get("/")
    def accueil():
        cfg = config()
        b = base(cfg)
        stats = b.statistiques()
        env = lire_env(app.config["DOSSIER"] / ".env")
        alertes = []
        if cfg.verifier_profil():
            alertes.append(("Profil incomplet : " + ", ".join(cfg.verifier_profil()), "profil"))
        if cfg.valeurs_exemple():
            alertes.append(("Valeurs d'exemple à remplacer : " + ", ".join(cfg.valeurs_exemple()), "profil"))
        if not cfg.fichier_cv.exists():
            alertes.append(("Aucun CV : importez votre CV (PDF ou Word)", "profil"))
        structure = cv_adapte.charger(cfg.fichier_cv_structure)
        if structure is None:
            alertes.append(("CV structuré absent : nécessaire pour adapter le CV à chaque offre", "cv"))
        elif cv_adapte.est_exemple(structure):
            alertes.append(("CV structuré encore rempli avec l'exemple : remplacez par votre parcours", "cv"))
        if not (env.get("FRANCE_TRAVAIL_CLIENT_ID") or env.get("ADZUNA_APP_ID")):
            alertes.append(("Aucune source d'offres : ajoutez vos identifiants France Travail ou Adzuna", "profil"))
        if not env.get("AUTOPOSTULE_SMTP_PASSWORD"):
            alertes.append(("Mot de passe SMTP absent : nécessaire pour envoyer", "profil"))
        envois = b.envois_aujourdhui()
        return render_template("accueil.html", stats=stats, alertes=alertes, envois=envois,
                               max_jour=cfg["envoi"].get("max_par_jour"), contrats=contrats_vises(cfg),
                               profil=cfg.profil, metiers=cfg["recherche"].get("metiers") or [])

    # -- profil et réglages ------------------------------------------------- #

    @app.get("/profil")
    def profil():
        cfg = config()
        env = lire_env(app.config["DOSSIER"] / ".env")
        return render_template("profil.html", cfg=cfg.donnees, cv=cfg.fichier_cv if cfg.fichier_cv.exists() else None,
                               secrets_={k: (lib, bool(env.get(k))) for k, lib in SECRETS.items()},
                               contrats=contrats_vises(cfg))

    @app.post("/profil")
    def enregistrer_profil():
        f = request.form
        chemin = chemin_config()
        donnees = lire_yaml(chemin)
        for section in ("profil", "recherche", "offres", "envoi", "lettre", "cv", "cv_adapte"):
            donnees.setdefault(section, {})
        p = donnees["profil"]
        for cle in ("prenom", "nom", "genre", "email", "telephone", "adresse", "code_postal", "ville", "linkedin",
                    "github", "portfolio", "titre", "disponibilite", "mobilite"):
            p[cle] = f.get(cle, "").strip()
        p["annees_experience"] = _entier(f.get("annees_experience"))
        p["permis"] = bool(f.get("permis"))
        p.pop("type_contrat", None)
        r = donnees["recherche"]
        r["metiers"] = [m for m in f.getlist("metiers") if m in METIERS] or ["administrateur_systeme"]
        try:
            r["types_contrat"] = contrats_valides(f.getlist("types_contrat"))
        except ValueError as erreur:
            flash(str(erreur), "erreur")
        r["regions"] = [x for x in f.getlist("regions") if x in REGIONS]
        r["departements"] = _liste_texte(f.get("departements"))
        r["villes"] = _liste_texte(f.get("villes"))
        r["effectif_min"] = _entier(f.get("effectif_min"))
        r["effectif_max"] = _entier(f.get("effectif_max"))
        o = donnees["offres"]
        o["publiees_depuis_jours"] = _entier(f.get("publiees_depuis_jours"), 7)
        o["chercher_email_rh"] = bool(f.get("chercher_email_rh"))
        e = donnees["envoi"]
        for cle in ("smtp_hote", "securite", "smtp_utilisateur"):
            e[cle] = f.get(cle, "").strip()
        e["smtp_port"] = _entier(f.get("smtp_port"), 587)
        e["max_par_jour"] = max(1, _entier(f.get("max_par_jour"), 40))
        e["validation_manuelle"] = bool(f.get("validation_manuelle"))
        donnees["lettre"]["moteur"] = "ia" if f.get("lettre_ia") else "modele"
        donnees["lettre"]["paragraphe_perso"] = f.get("paragraphe_perso", "").strip()

        fichier = request.files.get("cv_fichier")
        if fichier and fichier.filename:
            extension = Path(fichier.filename).suffix.lower()
            if extension not in {".pdf", ".docx", ".txt", ".md"}:
                flash("Format de CV non pris en charge (PDF, DOCX, TXT ou MD).", "erreur")
            else:
                cible = app.config["DOSSIER"] / "cv" / f"mon_cv{extension}"
                cible.parent.mkdir(exist_ok=True)
                fichier.save(cible)
                donnees["cv"]["fichier"] = f"cv/mon_cv{extension}"
                flash(f"CV importé : {fichier.filename}", "ok")

        ecrire_config(chemin, donnees)
        nouveaux = {cle: f.get(cle, "").strip() for cle in SECRETS if f.get(cle, "").strip()}
        if nouveaux:
            ecrire_env(app.config["DOSSIER"] / ".env", nouveaux)
        flash("Réglages enregistrés.", "ok")
        return redirect(url_for("profil"))

    @app.get("/cv-analyse")
    def cv_analyse():
        cfg = config()
        try:
            analyse = analyser_fichier(cfg.fichier_cv)
        except (FileNotFoundError, ValueError) as erreur:
            flash(str(erreur), "erreur")
            return redirect(url_for("profil"))
        scores = sorted(((METIERS[c].titre, s) for c, s in analyse.scores_metiers.items()), key=lambda x: -x[1])
        return render_template("cv_analyse.html", analyse=analyse, scores=scores, profil=cfg.profil)

    # -- CV structuré ------------------------------------------------------- #

    @app.get("/cv")
    def cv():
        cfg = config()
        chemin = cfg.fichier_cv_structure
        texte = chemin.read_text(encoding="utf-8-sig", errors="replace") if chemin.exists() else ""
        structure = cv_adapte.charger(chemin) if chemin.exists() else None
        return render_template("cv.html", texte=texte, existe=chemin.exists(),
                               exemple=bool(structure and cv_adapte.est_exemple(structure)))

    @app.post("/cv")
    def enregistrer_cv():
        cfg = config()
        chemin = cfg.fichier_cv_structure
        chemin.parent.mkdir(parents=True, exist_ok=True)
        if request.form.get("action") == "creer":
            try:
                analyse = analyser_fichier(cfg.fichier_cv)
            except (FileNotFoundError, ValueError):
                analyse = None
            chemin.write_text(cv_adapte.modele_depuis_analyse(analyse, cfg.profil), encoding="utf-8")
            flash("CV structuré créé à partir de votre CV : complétez vos expériences et missions.", "ok")
            return redirect(url_for("cv"))
        texte = request.form.get("texte", "").replace("\r\n", "\n")
        try:
            yaml.safe_load(texte)
        except yaml.YAMLError as erreur:
            flash(f"Le CV structuré est mal écrit, il n'a pas été enregistré : {erreur}", "erreur")
            return render_template("cv.html", texte=texte, existe=True, exemple=False)
        chemin.write_text(texte, encoding="utf-8")
        flash("CV structuré enregistré.", "ok")
        return redirect(url_for("cv"))

    @app.post("/cv/apercu")
    def apercu_cv():
        cfg = config()
        structure = cv_adapte.charger(cfg.fichier_cv_structure)
        if not structure:
            flash("Créez d'abord le CV structuré.", "erreur")
            return redirect(url_for("cv"))
        titre = request.form.get("titre", "").strip() or cfg.profil.get("titre") or structure.get("titre", "")
        mots = _liste_texte(request.form.get("mots", ""))
        resultat = cv_adapte.adapter(structure, titre, mots)
        chemin = cv_adapte.ecrire_pdf(resultat.donnees, cfg.profil, cfg.dossier_donnees / "apercus" / "apercu_cv.pdf")
        return send_file(chemin, mimetype="application/pdf")

    # -- entreprises (candidatures spontanées) ------------------------------ #

    @app.get("/entreprises")
    def entreprises():
        cfg = config()
        b = base(cfg)
        statut = request.args.get("statut") or None
        sql = "SELECT * FROM entreprises WHERE statut_scan != 'offre'"
        params: list = []
        if statut:
            sql += " AND statut_scan = ?"
            params.append(statut)
        lignes = b.cx.execute(sql + " ORDER BY date_ajout DESC LIMIT 500", params).fetchall()
        emails = {e["siren"]: e for e in b.cx.execute(
            "SELECT siren, email, type, MAX(score) AS score FROM emails GROUP BY siren").fetchall()}
        return render_template("entreprises.html", lignes=lignes, emails=emails, statut=statut,
                               r=cfg["recherche"])

    @app.post("/entreprises/rechercher")
    def lancer_recherche_entreprises():
        f = request.form
        dossier_ = app.config["DOSSIER"]

        def travail():
            cfg = charger(dossier_ / "config.yaml")
            metiers = [trouver_metier(m).cle for m in f.getlist("metiers")] or cfg["recherche"]["metiers"]
            departements = _liste_texte(f.get("departements"))
            regions = [] if departements else (f.getlist("regions") or cfg["recherche"].get("regions") or [])
            for r in regions:
                trouver_region(r)
            rechercher(cfg, base(cfg), metiers=metiers, regions=regions, departements=departements,
                       villes=_liste_texte(f.get("villes")), limite=_entier(f.get("limite"), 30),
                       effectif_min=_entier(f.get("effectif_min"), cfg["recherche"].get("effectif_min") or 0),
                       effectif_max=_entier(f.get("effectif_max"), cfg["recherche"].get("effectif_max") or 0))
            print("\nÉtape suivante : « Chercher les e-mails RH ».")

        return lancer("Recherche d'entreprises", travail)

    @app.post("/entreprises/scanner")
    def lancer_scan():
        limite = _entier(request.form.get("limite"), 0) or None
        dossier_ = app.config["DOSSIER"]

        def travail():
            cfg = charger(dossier_ / "config.yaml")
            scanner(cfg, base(cfg), limite)

        return lancer("Recherche des e-mails RH", travail)

    @app.post("/entreprises/generer")
    def lancer_generation():
        moteur = "ia" if request.form.get("ia") else None
        dossier_ = app.config["DOSSIER"]

        def travail():
            cfg = charger(dossier_ / "config.yaml")
            generer(cfg, base(cfg), moteur=moteur)
            print("\nÉtape suivante : relisez les brouillons dans « Candidatures ».")

        return lancer("Préparation des candidatures spontanées", travail)

    # -- offres d'emploi ----------------------------------------------------- #

    @app.get("/offres")
    def offres():
        cfg = config()
        statut = request.args.get("statut") or None
        env = lire_env(app.config["DOSSIER"] / ".env")
        sources = {"france_travail": bool(env.get("FRANCE_TRAVAIL_CLIENT_ID")), "adzuna": bool(env.get("ADZUNA_APP_ID")),
                   "jooble": bool(env.get("JOOBLE_API_KEY"))}
        return render_template("offres.html", lignes=base(cfg).offres(statut, 500), statut=statut,
                               statuts=STATUTS_OFFRE, sources=sources, r=cfg["recherche"],
                               jours=cfg["offres"].get("publiees_depuis_jours") or 7, contrats=contrats_vises(cfg),
                               smtp=bool(env.get("AUTOPOSTULE_SMTP_PASSWORD")),
                               boite=cfg["envoi"].get("smtp_utilisateur") or cfg.profil.get("email"))

    @app.post("/offres/rechercher")
    def lancer_recherche_offres():
        f = request.form
        dossier_ = app.config["DOSSIER"]
        args = argparse.Namespace(
            metier=f.getlist("metiers") or None, region=f.getlist("regions") or None,
            departement=_liste_texte(f.get("departements")) or None, ville=_liste_texte(f.get("villes")) or None,
            contrat=f.getlist("types_contrat") or None, source=f.getlist("sources") or None,
            jours=_entier(f.get("jours")) or None, limite=_entier(f.get("limite")) or None)

        def travail():
            cfg = charger(dossier_ / "config.yaml")
            rechercher_offres(cfg, base(cfg), args)
            print("\nÉtape suivante : « Préparer les candidatures » (CV + lettre pour chaque offre).")

        return lancer("Recherche d'offres d'emploi", travail)

    @app.post("/offres/alertes")
    def lancer_import_alertes():
        dossier_ = app.config["DOSSIER"]
        jours = _entier(request.form.get("jours")) or None
        fichiers = []
        for fichier in request.files.getlist("fichiers"):
            if fichier and fichier.filename:
                cible = dossier_ / "donnees" / "alertes" / Path(fichier.filename).name
                cible.parent.mkdir(parents=True, exist_ok=True)
                fichier.save(cible)
                fichiers.append(str(cible))

        def travail():
            cfg = charger(dossier_ / "config.yaml")
            importer_alertes(cfg, base(cfg), jours, fichiers or None)
            print("\nÉtape suivante : « Préparer les nouvelles offres » (CV + lettre pour chaque offre).")

        return lancer("Import des alertes e-mail", travail)

    @app.post("/offres/ajouter")
    def ajouter_offre():
        f = request.form
        cfg = config()
        try:
            if f.get("url") and not f.get("texte", "").strip():
                offre = offre_depuis_url(f["url"].strip())
            elif f.get("texte", "").strip():
                offre = offre_depuis_texte(f["texte"], f.get("titre", ""), f.get("entreprise", ""),
                                           f.get("url", ""), f.get("ville", ""), f.get("email", ""),
                                           f.get("contrat", ""))
            else:
                raise ValueError("Collez le texte de l'offre ou indiquez son lien.")
        except ValueError as erreur:
            flash(str(erreur), "erreur")
            return redirect(url_for("offres"))
        for champ in ("titre", "entreprise", "ville", "email"):
            if f.get(champ, "").strip():
                setattr(offre, champ, f[champ].strip())
        if f.get("contrat"):
            offre.type_contrat = contrats_valides([f["contrat"]])[0]
        cibles = list(dict.fromkeys([*cfg["recherche"]["metiers"], *METIERS]))
        offre.metier = deduire_metier(offre, cibles)[0] or cibles[0]
        if base(cfg).ajouter_offre({**offre.en_dict(), "cle_doublon": offre.cle_doublon}):
            flash(f"Offre ajoutée : {offre.titre}", "ok")
            return redirect(url_for("offre", id_=offre.id))
        flash("Cette offre est déjà enregistrée.", "erreur")
        return redirect(url_for("offres"))

    @app.post("/offres/preparer")
    def lancer_preparation_offres():
        moteur = "ia" if request.form.get("ia") else None
        dossier_ = app.config["DOSSIER"]

        def travail():
            cfg = charger(dossier_ / "config.yaml")
            preparer_offres(cfg, base(cfg), moteur)
            print("\nÉtape suivante : relisez les brouillons dans « Candidatures ».")

        return lancer("Préparation des candidatures sur offres", travail)

    @app.get("/offres/<path:id_>")
    def offre(id_):
        cfg = config()
        b = base(cfg)
        ligne = b.offre(id_)
        if not ligne:
            abort(404)
        o = offre_depuis_ligne(ligne)
        atelier = Atelier(cfg, b, journal=lambda *_: None)
        mots = mots_cles(o, atelier.competences_cv)
        connues = {c.lower() for c in atelier.competences_cv}
        candidature = b.cx.execute("SELECT * FROM candidatures WHERE offre_id = ? ORDER BY id DESC",
                                   (id_,)).fetchone()
        fichiers = sorted(Path(ligne["dossier"]).glob("*.pdf")) if ligne["dossier"] else []
        return render_template("offre.html", o=o, ligne=ligne, titre=titre_propre(o.titre),
                               presentes=[m for m in mots if m.lower() in connues],
                               absentes=[m for m in mots if m.lower() not in connues],
                               candidature=candidature, fichiers=fichiers)

    @app.post("/offres/<path:id_>/statut")
    def statut_offre(id_):
        statut = request.form.get("statut")
        if statut in STATUTS_OFFRE:
            base().maj_offre(id_, statut=statut)
            flash("Statut mis à jour.", "ok")
        return redirect(url_for("offre", id_=id_))

    # -- candidatures -------------------------------------------------------- #

    @app.get("/candidatures")
    def candidatures():
        statut = request.args.get("statut") or None
        b = base()
        return render_template("candidatures.html", lignes=b.candidatures(statut), statut=statut,
                               statuts=STATUTS_CANDIDATURE)

    @app.get("/candidatures/<int:id_>")
    def candidature(id_):
        b = base()
        c = b.candidature(id_)
        if not c:
            abort(404)
        entreprise = b.entreprise(c["siren"])
        o = b.offre(c["offre_id"]) if c["offre_id"] else None
        return render_template("candidature.html", c=c, entreprise=entreprise, o=o)

    @app.post("/candidatures/action")
    def action_candidatures():
        b = base()
        action = request.form.get("action")
        ids = [int(i) for i in request.form.getlist("ids") if i.isdigit()]
        if action == "approuver_tout":
            ids = [c["id"] for c in b.candidatures("brouillon")]
            action = "approuver"
        if action == "approuver":
            n = b.changer_statut(ids, "approuvee", depuis=("brouillon", "echec"))
            flash(f"{n} candidature(s) approuvée(s).", "ok")
        elif action == "ignorer":
            n = b.changer_statut(ids, "ignoree", depuis=("brouillon", "approuvee", "echec"))
            flash(f"{n} candidature(s) écartée(s).", "ok")
        elif action == "brouillon":
            n = b.changer_statut(ids, "brouillon", depuis=("approuvee", "ignoree", "echec"))
            flash(f"{n} candidature(s) remise(s) en brouillon.", "ok")
        retour = request.form.get("retour")
        return redirect(retour if retour and retour.startswith("/") else url_for("candidatures"))

    @app.post("/envoyer")
    def lancer_envoi():
        cfg = config()
        test = request.form.get("mode") != "reel"
        if cfg.verifier_profil():
            flash("Profil incomplet : " + ", ".join(cfg.verifier_profil()), "erreur")
            return redirect(url_for("candidatures"))
        if not test and cfg.valeurs_exemple():
            flash("Envoi bloqué : le profil contient encore des valeurs d'exemple ("
                  + ", ".join(cfg.valeurs_exemple()) + "). Corrigez-les, puis régénérez les brouillons.", "erreur")
            return redirect(url_for("profil"))
        maximum = _entier(request.form.get("maximum")) or None
        dossier_ = app.config["DOSSIER"]

        def travail():
            c = charger(dossier_ / "config.yaml")
            bilan = envoyer_candidatures(c, base(c), test=test, maximum=maximum)
            print(f"\nBilan : {bilan['envoyees']} {'simulée(s)' if test else 'envoyée(s)'}, {bilan['echecs']} échec(s), "
                  f"{bilan['ignorees']} ignorée(s), {bilan['restantes']} en attente (plafond du jour).")
            if test:
                print(f"Mode test : messages enregistrés dans {c.dossier_donnees / 'envois_test'} - rien n'a été envoyé.")

        return lancer("Envoi (test)" if test else "Envoi des candidatures", travail)

    @app.post("/exclure")
    def exclure():
        valeur = request.form.get("valeur", "").strip()
        if valeur:
            base().exclure(valeur, request.form.get("raison", "via l'interface"))
            flash(f"« {valeur} » ne sera plus jamais contacté.", "ok")
        return redirect(request.referrer or url_for("candidatures"))

    # -- tâches et fichiers -------------------------------------------------- #

    @app.get("/taches/<id_>")
    def tache(id_):
        t = taches.taches.get(id_)
        if not t:
            abort(404)
        return render_template("tache.html", t=t)

    @app.get("/taches/<id_>.json")
    def tache_json(id_):
        t = taches.taches.get(id_)
        if not t:
            abort(404)
        return jsonify(t.en_dict())

    @app.get("/fichier")
    def fichier():
        """Sert un PDF généré (CV adapté, lettre) - uniquement à l'intérieur du dossier de travail."""
        chemin = Path(request.args.get("chemin", "")).resolve()
        racine = app.config["DOSSIER"].resolve()
        if racine not in chemin.parents or not chemin.is_file():
            abort(404)
        return send_file(chemin)

    return app


def lancer_serveur(dossier: Path | None, port: int = 8765, ouvrir: bool = True) -> None:
    import threading
    import webbrowser

    app = creer_app(dossier)
    adresse = f"http://127.0.0.1:{port}/"
    print(f"Interface autopostule : {adresse}\nGardez cette fenêtre ouverte ; fermez-la (ou Ctrl+C) pour arrêter.")
    if ouvrir:
        threading.Timer(1.0, lambda: webbrowser.open(adresse)).start()
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
