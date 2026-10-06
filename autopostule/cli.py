"""Interface en ligne de commande : `autopostule <commande> [options]`."""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import sys
import textwrap
import webbrowser
from pathlib import Path

import os

from . import __version__
from . import cv_adapte
from . import offres as mod_offres
from .candidature import Atelier
from .config import EXEMPLE, ErreurConfig, charger, contrats_vises
from .cv import AnalyseCV, analyser_fichier
from .emails import classer
from .entreprises import ClientRechercheEntreprises, CriteresRecherche
from .envoi import envoyer_candidatures
from .referentiel import CONTRATS, METIERS, REGIONS, contrats_valides, libelle_contrats, trouver_metier, trouver_region
from .sites import Prospecteur, mx_valide
from .stockage import Base
from .web import Navigateur

TYPES_PAR_DEFAUT = ("rh", "generique")
ENV_EXEMPLE = """# Secrets - ne versionnez jamais ce fichier
# Gmail : https://myaccount.google.com/apppasswords (validation en 2 étapes requise)
AUTOPOSTULE_SMTP_PASSWORD=
# Facultatif, pour lettre.moteur: "ia" (https://console.anthropic.com/)
ANTHROPIC_API_KEY=
# Offres d'emploi France Travail (gratuit) : https://francetravail.io -> créer une application,
# API « Offres d'emploi v2 »
FRANCE_TRAVAIL_CLIENT_ID=
FRANCE_TRAVAIL_CLIENT_SECRET=
# Offres d'emploi Adzuna (gratuit) : https://developer.adzuna.com
ADZUNA_APP_ID=
ADZUNA_APP_KEY=
# Offres d'emploi Jooble (gratuit) : https://jooble.org/api/about
JOOBLE_API_KEY=
"""


# --------------------------------------------------------------------------- #
# Utilitaires
# --------------------------------------------------------------------------- #

def _base(config) -> Base:
    return Base(config.dossier_donnees / "autopostule.db")


def _analyse_cv(config, obligatoire: bool = False) -> AnalyseCV | None:
    try:
        return analyser_fichier(config.fichier_cv)
    except FileNotFoundError:
        if obligatoire:
            raise
        print(f"(CV non trouvé : {config.fichier_cv} - lettres générées sans les compétences du CV)")
        return None


def _appliquer_contrats(config, args) -> list[str]:
    """L'option -t/--contrat remplace recherche.types_contrat pour cette exécution."""
    if getattr(args, "contrat", None):
        config["recherche"]["types_contrat"] = contrats_valides(_liste(args.contrat))
    return contrats_vises(config)


def _liste(valeurs) -> list[str]:
    resultat: list[str] = []
    for v in valeurs or []:
        resultat.extend(x.strip() for x in str(v).split(",") if x.strip())
    return resultat


# --------------------------------------------------------------------------- #
# Commandes
# --------------------------------------------------------------------------- #

def cmd_init(args) -> int:
    dossier = Path(args.dossier).resolve()
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "cv").mkdir(exist_ok=True)
    config = dossier / "config.yaml"
    env = dossier / ".env"
    if config.exists() and not args.force:
        print(f"{config} existe déjà (utilisez --force pour l'écraser).")
    else:
        shutil.copy(EXEMPLE, config)
        print(f"Créé : {config}")
    if not env.exists():
        env.write_text(ENV_EXEMPLE, encoding="utf-8")
        print(f"Créé : {env}")
    print("\nÉtapes suivantes :\n  1. Déposez votre CV dans cv/ et renseignez config.yaml\n"
          "  2. Ajoutez votre mot de passe SMTP dans .env\n  3. autopostule cv")
    return 0


def cmd_interface(args) -> int:
    """Ouvre l'interface graphique dans le navigateur."""
    from .interface import lancer_serveur

    dossier = Path(args.dossier).expanduser() if args.dossier else None
    if dossier is None and Path(args.config).exists():
        dossier = Path(args.config).resolve().parent
    lancer_serveur(dossier, port=args.port, ouvrir=not args.sans_navigateur)
    return 0


def cmd_metiers(args) -> int:
    for m in METIERS.values():
        print(f"{m.cle:<26} {m.titre}")
        print(f"{'':<26} NAF : {', '.join(m.naf)}")
    return 0


def cmd_regions(args) -> int:
    for r in REGIONS.values():
        print(f"{r.cle:<30} {r.nom:<28} code {r.code:<3} dép. {', '.join(r.departements)}")
    return 0


def cmd_cv(args) -> int:
    config = charger(args.config)
    analyse = _analyse_cv(config, obligatoire=True)
    print(f"CV : {config.fichier_cv}  ({len(analyse.texte)} caractères extraits)")
    print(f"E-mail détecté    : {analyse.email or '-'}")
    print(f"Téléphone détecté : {analyse.telephone or '-'}")
    print(f"LinkedIn          : {analyse.linkedin or '-'}")
    print(f"\nCompétences reconnues ({len(analyse.competences)}) :")
    print(textwrap.fill(", ".join(analyse.competences) or "aucune", width=100, initial_indent="  ",
                        subsequent_indent="  "))
    print("\nAdéquation par métier :")
    for cle, score in sorted(analyse.scores_metiers.items(), key=lambda x: -x[1]):
        print(f"  {METIERS[cle].titre:<28} {'█' * score} {score}")
    manquants = config.verifier_profil()
    if manquants:
        print(f"\n⚠ Champs du profil à compléter dans config.yaml : {', '.join(manquants)}")
    exemples = config.valeurs_exemple()
    if exemples:
        print(f"\n⚠ Valeurs d'exemple à remplacer dans config.yaml (profil) : {', '.join(exemples)}"
              + (f"\n  Détecté dans votre CV : {analyse.email or ''} {analyse.telephone or ''}".rstrip()
                 if analyse.email or analyse.telephone else ""))
    if not config.profil.get("genre"):
        print("\nAstuce : indiquez genre: \"M\" ou \"F\" dans config.yaml pour éviter « motivé(e) » dans les lettres.")
    return 0


def rechercher(config, base: Base, metiers: list[str], regions: list[str], departements: list[str],
               villes: list[str], limite: int, effectif_min: int, effectif_max: int = 0) -> int:
    client = ClientRechercheEntreprises()
    nouvelles = 0
    codes_regions = [trouver_region(r).code for r in regions]
    for cle in metiers:
        metier = trouver_metier(cle)
        criteres = CriteresRecherche(
            metier=metier, regions=codes_regions, departements=departements, villes=villes,
            effectif_min=effectif_min, effectif_max=effectif_max, limite=limite,
            naf_supplementaires=_liste(config["recherche"].get("naf_supplementaires")),
        )
        print(f"Recherche « {metier.titre} » (NAF {', '.join(criteres.parametres()['activite_principale'].split(','))})")
        n = 0
        for entreprise in client.rechercher(criteres):
            n += 1
            if base.ajouter_entreprise(entreprise):
                nouvelles += 1
        print(f"  {n} entreprises trouvées")
    print(f"{nouvelles} nouvelles entreprises enregistrées.")
    return nouvelles


def cmd_rechercher(args) -> int:
    config = charger(args.config)
    r = config["recherche"]
    base = _base(config)
    rechercher(
        config, base,
        metiers=_liste(args.metier) or _liste(r.get("metiers")),
        regions=_liste(args.region) or ([] if args.departement else _liste(r.get("regions"))),
        departements=_liste(args.departement) or _liste(r.get("departements")),
        villes=_liste(args.ville) or _liste(r.get("villes")),
        limite=args.limite or int(r.get("limite") or 200),
        effectif_min=args.effectif_min if args.effectif_min is not None else int(r.get("effectif_min") or 0),
        effectif_max=args.effectif_max if args.effectif_max is not None else int(r.get("effectif_max") or 0),
    )
    return 0


def cmd_importer(args) -> int:
    """Importe une liste d'entreprises (CSV : nom, site, email, siren, ville, metier)."""
    config = charger(args.config)
    base = _base(config)
    metier_defaut = trouver_metier(args.metier).cle if args.metier else _liste(config["recherche"]["metiers"])[0]
    with open(args.fichier, newline="", encoding="utf-8-sig") as f:
        echantillon = f.read(4096)
        f.seek(0)
        dialecte = csv.Sniffer().sniff(echantillon, delimiters=",;\t")
        lecteur = csv.DictReader(f, dialect=dialecte)
        n = 0
        for ligne in lecteur:
            ligne = {(k or "").strip().lower(): (v or "").strip() for k, v in ligne.items()}
            if not ligne.get("nom"):
                continue
            siren = ligne.get("siren") or "csv-" + hashlib.sha1(ligne["nom"].lower().encode()).hexdigest()[:10]
            site = ligne.get("site") or None
            if site and not site.startswith("http"):
                site = "https://" + site
            base.ajouter_entreprise({
                "siren": siren, "nom": ligne["nom"], "ville": ligne.get("ville"), "naf": ligne.get("naf"),
                "metier": trouver_metier(ligne["metier"]).cle if ligne.get("metier") else metier_defaut,
                "site": site, "site_confiance": "fourni" if site else None,
            })
            if ligne.get("email"):
                email = classer(ligne["email"]) or None
                base.ajouter_email(siren, ligne["email"], email.type if email else "fourni", 120, "import")
                base.maj_scan(siren, "scanne")
            n += 1
    print(f"{n} entreprises importées depuis {args.fichier}.")
    return 0


def scanner(config, base: Base, limite: int | None = None) -> int:
    s = config["scan"]
    navigateur = Navigateur(delai=float(s.get("delai_entre_requetes") or 1.5), timeout=float(s.get("timeout") or 15))
    prospecteur = Prospecteur(navigateur, tlds=s.get("tlds") or [".fr", ".com"],
                              pages_max=int(s.get("pages_max_par_site") or 8))
    types = set(TYPES_PAR_DEFAUT) | ({"nominatif", "autre"} if s.get("inclure_emails_nominatifs") else set())
    a_scanner = base.entreprises_a_scanner(limite)
    trouves = 0
    for i, e in enumerate(a_scanner, 1):
        print(f"[{i}/{len(a_scanner)}] {e['nom']} ({e['ville'] or '?'})", end=" ... ", flush=True)
        resultat = prospecteur.scanner(e["nom"], e["siren"], e["site"])
        if not resultat.site:
            base.maj_scan(e["siren"], "sans_site")
            print("site introuvable")
            continue
        retenus = [m for m in resultat.emails if m.type in types and not base.est_exclu(m.email, e["siren"])]
        if s.get("verifier_mx", True):
            domaines_ok = {}
            for m in retenus:
                d = m.email.rsplit("@", 1)[1]
                if d not in domaines_ok:
                    domaines_ok[d] = mx_valide(d) is not False
            retenus = [m for m in retenus if domaines_ok[m.email.rsplit("@", 1)[1]]]
        for m in retenus:
            base.ajouter_email(e["siren"], m.email, m.type, m.score, m.source)
        base.maj_scan(e["siren"], "scanne" if retenus else "sans_email", resultat.site, resultat.confiance)
        if retenus:
            trouves += 1
            print(f"{retenus[0].email} [{retenus[0].type}] ({resultat.site})")
        else:
            print(f"aucune adresse exploitable ({resultat.site}, {resultat.pages_visitees} pages)")
    print(f"\n{trouves}/{len(a_scanner)} entreprises avec une adresse de contact.")
    return trouves


def cmd_scanner(args) -> int:
    config = charger(args.config)
    scanner(config, _base(config), args.limite)
    return 0


def generer(config, base: Base, metier: str | None = None, moteur: str | None = None,
            limite: int | None = None) -> int:
    atelier = Atelier(config, base)
    n = 0
    for e in base.entreprises_sans_candidature(trouver_metier(metier).cle if metier else None):
        if limite and n >= limite:
            break
        resultat = atelier.preparer_spontanee(dict(e), moteur)
        if resultat.statut != "preparee":
            continue
        n += 1
        print(f"  #{resultat.candidature_id:<5} {e['nom'][:45]:<45} <{resultat.email}>")
    contrats = libelle_contrats(atelier.contrats)
    print(f"{n} candidatures spontanées préparées{f' ({contrats})' if contrats else ''} (statut « brouillon »).")
    return n


def cmd_generer(args) -> int:
    config = charger(args.config)
    _appliquer_contrats(config, args)
    generer(config, _base(config), args.metier, "ia" if args.ia else None, args.limite)
    return 0


def cmd_cv_structure(args) -> int:
    """Crée cv.yaml (CV structuré) à partir du CV existant, à compléter puis utilisé pour les CV adaptés."""
    config = charger(args.config)
    cible = config.fichier_cv_structure
    if cible.exists() and not args.force:
        print(f"{cible} existe déjà (--force pour le régénérer).")
        return 1
    analyse = _analyse_cv(config)
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(cv_adapte.modele_depuis_analyse(analyse, config.profil), encoding="utf-8")
    print(f"Créé : {cible}\nComplétez vos expériences, missions et formations, puis testez avec :\n"
          f"  autopostule offres voir <ID>   (aperçu du CV adapté à une offre)")
    return 0


# --------------------------------------------------------------------------- #
# Offres d'emploi
# --------------------------------------------------------------------------- #

def _sources(config, choix: list[str] | None = None) -> list:
    sources = []
    for nom in choix or _liste(config["offres"].get("sources")):
        if nom == "france_travail":
            identifiant, secret = os.environ.get("FRANCE_TRAVAIL_CLIENT_ID"), os.environ.get("FRANCE_TRAVAIL_CLIENT_SECRET")
            if identifiant and secret:
                sources.append(mod_offres.SourceFranceTravail(identifiant, secret))
            else:
                print("(France Travail ignoré : FRANCE_TRAVAIL_CLIENT_ID / _SECRET absents du fichier .env)")
        elif nom == "adzuna":
            identifiant, cle = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
            if identifiant and cle:
                sources.append(mod_offres.SourceAdzuna(identifiant, cle))
            else:
                print("(Adzuna ignoré : ADZUNA_APP_ID / ADZUNA_APP_KEY absents du fichier .env)")
        elif nom == "jooble":
            cle = os.environ.get("JOOBLE_API_KEY")
            if cle:
                sources.append(mod_offres.SourceJooble(cle))
            else:
                print("(Jooble ignoré : JOOBLE_API_KEY absent du fichier .env)")
        else:
            raise ValueError(f"Source d'offres inconnue : {nom!r} (france_travail, adzuna, jooble)")
    return sources


def rechercher_offres(config, base: Base, args) -> int:
    r, o = config["recherche"], config["offres"]
    contrats = _appliquer_contrats(config, args)
    sources = _sources(config, _liste(getattr(args, "source", None)) or None)
    if not sources:
        print("Aucune source d'offres configurée : ajoutez vos identifiants dans .env (voir docs/GUIDE.md), "
              "ou importez des offres avec `autopostule offres ajouter`.")
        return 0
    metiers = [trouver_metier(m).cle for m in (_liste(args.metier) or _liste(r.get("metiers")))]
    departements = _liste(args.departement) or _liste(r.get("departements"))
    regions = [trouver_region(x).code for x in (_liste(args.region) or ([] if departements else _liste(r.get("regions"))))]
    jours = args.jours or int(o.get("publiees_depuis_jours") or 7)
    print(f"Offres publiées depuis {jours} jour(s){f', contrat : {libelle_contrats(contrats)}' if contrats else ''}")
    trouvees = mod_offres.collecter(sources, metiers, regions, departements,
                                    _liste(args.ville) or _liste(r.get("villes")), contrats, jours,
                                    args.limite or int(o.get("limite") or 100))
    nouvelles = sum(1 for offre in trouvees if base.ajouter_offre({**offre.en_dict(), "cle_doublon": offre.cle_doublon}))
    print(f"{len(trouvees)} offre(s) pertinente(s), dont {nouvelles} nouvelle(s).")
    return nouvelles


def importer_alertes(config, base: Base, jours: int | None = None, fichiers: list[str] | None = None) -> int:
    """Ajoute les offres reçues par alerte e-mail (Indeed, LinkedIn, Welcome to the Jungle, Monster, Google...)."""
    from . import alertes

    reglages = config["offres"].get("alertes") or {}
    jours = jours or int(reglages.get("jours") or config["offres"].get("publiees_depuis_jours") or 7)
    if fichiers:
        resultat = alertes.lire_fichiers([Path(f) for f in fichiers])
    else:
        hote = alertes.hote_imap(config)
        utilisateur = config["envoi"].get("smtp_utilisateur") or config.profil.get("email")
        print(f"Lecture des alertes des {jours} derniers jours dans {utilisateur} ({hote}, lecture seule)...")
        try:
            resultat = alertes.lire_boite(hote, utilisateur, config.mot_de_passe_smtp, jours,
                                          reglages.get("dossier") or "INBOX", int(reglages.get("imap_port") or 993))
        except (OSError, alertes.imaplib.IMAP4.error) as erreur:
            raise ValueError(f"lecture de la boîte e-mail impossible ({erreur}). Gmail : vérifiez que l'accès IMAP "
                             "est activé et utilisez le mot de passe d'application. Vous pouvez aussi enregistrer "
                             "les e-mails d'alerte (.eml) et utiliser --fichier.") from None
    contrats = contrats_vises(config)
    cibles = list(dict.fromkeys([*_liste(config["recherche"].get("metiers")), *METIERS]))
    nouvelles = ecartees = 0
    for offre in alertes.iterer(resultat.offres):
        if contrats and offre.type_contrat and offre.type_contrat not in contrats:
            ecartees += 1
            continue
        offre.metier = mod_offres.deduire_metier(offre, cibles)[0] or cibles[0]
        if base.ajouter_offre({**offre.en_dict(), "cle_doublon": offre.cle_doublon}):
            nouvelles += 1
            print(f"  + {offre.titre[:55]:<55} {offre.entreprise[:25]:<25} [{offre.source}]")
    print(f"{resultat.messages} e-mail(s) d'alerte lu(s), {len(resultat.offres)} offre(s) trouvée(s), "
          f"{nouvelles} nouvelle(s)" + (f", {ecartees} écartée(s) (type de contrat)" if ecartees else "") + ".")
    if resultat.messages and not resultat.offres:
        print("Aucune offre reconnue dans ces e-mails : envoyez un exemple (.eml) pour améliorer la détection.")
    return nouvelles


def cmd_offres_alertes(args) -> int:
    config = charger(args.config)
    _appliquer_contrats(config, args)
    importer_alertes(config, _base(config), args.jours, args.fichier)
    return 0


def cmd_offres_rechercher(args) -> int:
    config = charger(args.config)
    rechercher_offres(config, _base(config), args)
    return 0


def cmd_offres_ajouter(args) -> int:
    config = charger(args.config)
    base = _base(config)
    if args.url and not args.fichier:
        offre = mod_offres.offre_depuis_url(args.url)
    elif args.fichier:
        texte = Path(args.fichier).read_text(encoding="utf-8", errors="replace")
        offre = mod_offres.offre_depuis_texte(texte, args.titre or "", args.entreprise or "", args.url or "",
                                              args.ville or "", args.email or "", args.contrat or "")
    else:
        raise ValueError("indiquez --url ou --fichier")
    for champ in ("titre", "entreprise", "ville", "email"):
        if getattr(args, champ):
            setattr(offre, champ, getattr(args, champ))
    if args.contrat:
        offre.type_contrat = contrats_valides([args.contrat])[0]
    # offre choisie par l'utilisateur : on la compare à tous les métiers connus
    cibles = [trouver_metier(args.metier).cle] if args.metier else list(
        dict.fromkeys([*_liste(config["recherche"]["metiers"]), *METIERS]))
    offre.metier = mod_offres.deduire_metier(offre, cibles)[0] or cibles[0]
    if base.ajouter_offre({**offre.en_dict(), "cle_doublon": offre.cle_doublon}):
        print(f"Offre ajoutée : {offre.id}  {offre.titre} - {offre.entreprise or '?'} "
              f"[{offre.type_contrat or 'contrat ?'}] {'<' + offre.email + '>' if offre.email else '(pas d e-mail)'}")
    else:
        print("Offre déjà connue.")
    return 0


def preparer_offres(config, base: Base, moteur: str | None = None, limite: int | None = None) -> dict:
    atelier = Atelier(config, base)
    s = config["scan"]
    client = ClientRechercheEntreprises() if config["offres"].get("chercher_email_rh", True) else None
    prospecteur = Prospecteur(Navigateur(delai=float(s.get("delai_entre_requetes") or 1.5),
                                         timeout=float(s.get("timeout") or 15)),
                              tlds=s.get("tlds") or [".fr", ".com"], pages_max=int(s.get("pages_max_par_site") or 8))
    bilan = {"preparee": 0, "a_postuler_sur_site": 0, "ignoree": 0}
    for ligne in base.offres("nouvelle", limite):
        print(f"- {ligne['titre'][:50]:<50} {(ligne['entreprise'] or '?')[:25]:<25}", end=" ... ", flush=True)
        resultat = atelier.preparer_offre(ligne, moteur, client, prospecteur)
        bilan[resultat.statut] += 1
        if resultat.statut == "preparee":
            print(f"candidature #{resultat.candidature_id} -> {resultat.email}")
        elif resultat.statut == "a_postuler_sur_site":
            print(f"pas d'e-mail : dossier prêt, à envoyer sur le site ({ligne['url']})")
        else:
            print("ignorée (adresse exclue)")
    print(f"\n{bilan['preparee']} candidature(s) par e-mail préparée(s), {bilan['a_postuler_sur_site']} dossier(s) "
          f"à déposer sur le site de l'offre (`autopostule offres lister -s a_postuler_sur_site`).")
    return bilan


def cmd_offres_preparer(args) -> int:
    config = charger(args.config)
    _appliquer_contrats(config, args)
    preparer_offres(config, _base(config), "ia" if args.ia else None, args.limite)
    return 0


def cmd_offres_lister(args) -> int:
    config = charger(args.config)
    lignes = _base(config).offres(args.statut)
    for o in lignes:
        print(f"{o['id']:<22} {o['statut']:<20} {(o['date_publication'] or '')[:10]:<10} "
              f"{(o['type_contrat'] or '?'):<10} {o['titre'][:38]:<38} {(o['entreprise'] or '?')[:22]:<22} "
              f"{(o['ville'] or '')[:15]}")
    print(f"{len(lignes)} offre(s).")
    return 0


def cmd_offres_voir(args) -> int:
    config = charger(args.config)
    base = _base(config)
    ligne = base.offre(args.id)
    if not ligne:
        print(f"Offre {args.id} introuvable.")
        return 1
    from .candidature import offre_depuis_ligne

    offre = offre_depuis_ligne(ligne)
    atelier = Atelier(config, base, journal=lambda *_: None)
    mots = mod_offres.mots_cles(offre, atelier.competences_cv)
    connues = {k.lower() for k in atelier.competences_cv}
    print(f"{offre.titre}\n{offre.entreprise or '?'} - {offre.ville} - {offre.type_contrat or 'contrat ?'} - "
          f"{offre.salaire or 'salaire non précisé'}\nSource : {offre.source}  {offre.url}\n"
          f"E-mail : {offre.email or '-'}   Statut : {ligne['statut']}   Dossier : {ligne['dossier'] or '-'}")
    print(f"\nCompétences demandées que vous avez : {', '.join(m for m in mots if m.lower() in connues) or '-'}")
    print(f"Compétences demandées absentes du CV : {', '.join(m for m in mots if m.lower() not in connues) or '-'}")
    print("\n" + (offre.description[:3000] or ""))
    if args.apercu:
        dossier = config.dossier_donnees / "apercus"
        chemin, _ = atelier.cv_pour(mod_offres.titre_propre(offre.titre), mots, offre.texte, dossier, "apercu")
        print(f"\nAperçu du CV adapté : {chemin or 'cv.yaml absent (autopostule cv-structure)'}")
    return 0


def cmd_offres_ouvrir(args) -> int:
    config = charger(args.config)
    ligne = _base(config).offre(args.id)
    if not ligne:
        print(f"Offre {args.id} introuvable.")
        return 1
    print(f"Dossier de candidature : {ligne['dossier'] or '(préparez-le avec `autopostule offres preparer`)'}")
    print(f"Lien de l'offre : {ligne['url']}")
    if ligne["url"]:
        webbrowser.open(ligne["url"])
    return 0


def cmd_offres_statut(args, statut: str) -> int:
    config = charger(args.config)
    base = _base(config)
    for id_ in args.ids:
        base.maj_offre(id_, statut=statut)
    print(f"{len(args.ids)} offre(s) -> {statut}")
    return 0


def cmd_lister(args) -> int:
    config = charger(args.config)
    lignes = _base(config).candidatures(args.statut)
    for c in lignes:
        print(f"#{c['id']:<5} {c['statut']:<10} {c['entreprise'][:40]:<40} {(c['ville'] or '')[:18]:<18} {c['email']}")
    print(f"{len(lignes)} candidature(s).")
    return 0


def cmd_voir(args) -> int:
    config = charger(args.config)
    c = _base(config).candidature(args.id)
    if not c:
        print(f"Candidature #{args.id} introuvable.")
        return 1
    print(f"À      : {c['email']}\nObjet  : {c['objet']}\nStatut : {c['statut']}\nPDF    : {c['lettre_pdf'] or '-'}")
    print("\n----- message -----\n" + c["corps"])
    print("----- lettre -----\n" + c["lettre"])
    return 0


def cmd_approuver(args) -> int:
    config = charger(args.config)
    base = _base(config)
    ids = [c["id"] for c in base.candidatures("brouillon")] if args.tout else args.ids
    n = base.changer_statut(ids, "approuvee", depuis=("brouillon", "echec"))
    print(f"{n} candidature(s) approuvée(s).")
    return 0


def cmd_ignorer(args) -> int:
    config = charger(args.config)
    n = _base(config).changer_statut(args.ids, "ignoree", depuis=("brouillon", "approuvee", "echec"))
    print(f"{n} candidature(s) ignorée(s).")
    return 0


def cmd_envoyer(args) -> int:
    config = charger(args.config)
    manquants = config.verifier_profil()
    if manquants:
        print(f"Profil incomplet ({', '.join(manquants)}) : complétez config.yaml avant d'envoyer.")
        return 1
    exemples = config.valeurs_exemple()
    if exemples and not args.test:
        print(f"Envoi bloqué : le profil contient encore des valeurs d'exemple ({', '.join(exemples)}). "
              f"Corrigez config.yaml, puis régénérez les brouillons (`autopostule ignorer ...` puis `generer`).")
        return 1
    base = _base(config)
    if not args.test and not args.oui:
        prets = len(base.candidatures("approuvee"))
        if not config["envoi"].get("validation_manuelle", True):
            prets += len(base.candidatures("brouillon"))
        reponse = input(f"Envoyer jusqu'à {min(prets, int(config['envoi']['max_par_jour']))} candidature(s) "
                        f"depuis {config['envoi']['smtp_utilisateur']} ? [o/N] ")
        if reponse.strip().lower() not in {"o", "oui", "y", "yes"}:
            print("Annulé.")
            return 0
    bilan = envoyer_candidatures(config, base, test=args.test, maximum=args.max)
    print(f"\nBilan : {bilan['envoyees']} envoyée(s), {bilan['echecs']} échec(s), {bilan['ignorees']} ignorée(s), "
          f"{bilan['restantes']} en attente (plafond).")
    if args.test:
        print(f"Mode test : messages écrits dans {config.dossier_donnees / 'envois_test'} (rien n'a été envoyé).")
    return 0


def cmd_exclure(args) -> int:
    config = charger(args.config)
    base = _base(config)
    for valeur in args.valeurs:
        base.exclure(valeur, args.raison or "")
        print(f"Exclu : {valeur}")
    return 0


def cmd_stats(args) -> int:
    config = charger(args.config)
    for cle, valeur in _base(config).statistiques().items():
        print(f"{cle:<28} {valeur}")
    return 0


def cmd_auto(args) -> int:
    """Chaîne complète : offres récentes + candidatures spontanées -> lettres et CV adaptés -> envoi."""
    config = charger(args.config)
    base = _base(config)
    r = config["recherche"]
    contrats = _appliquer_contrats(config, args)
    moteur = "ia" if args.ia else None
    if contrats:
        print(f"Type(s) de poste : {libelle_contrats(contrats)}")
    if args.mode in ("tout", "offres"):
        print("=== Offres d'emploi récentes ===")
        rechercher_offres(config, base, args)
        preparer_offres(config, base, moteur)
    if args.mode in ("tout", "spontanees"):
        print("\n=== Candidatures spontanées : entreprises ===")
        rechercher(
            config, base,
            metiers=_liste(args.metier) or _liste(r.get("metiers")),
            regions=_liste(args.region) or ([] if args.departement else _liste(r.get("regions"))),
            departements=_liste(args.departement) or _liste(r.get("departements")),
            villes=_liste(args.ville) or _liste(r.get("villes")),
            limite=args.limite or int(r.get("limite") or 200),
            effectif_min=int(r.get("effectif_min") or 0),
            effectif_max=int(r.get("effectif_max") or 0),
        )
        print("\n=== Candidatures spontanées : adresses e-mail ===")
        scanner(config, base, args.limite)
        print("\n=== Candidatures spontanées : lettres et CV ===")
        generer(config, base, moteur=moteur)
    if config["envoi"].get("validation_manuelle", True) and not args.approuver_tout:
        print("\n=== Envoi ===\nValidation manuelle activée : relisez avec `autopostule lister --statut brouillon`"
              " / `autopostule voir ID`, puis `autopostule approuver --tout` et `autopostule envoyer`.")
        return 0
    if args.approuver_tout:
        base.changer_statut([c["id"] for c in base.candidatures("brouillon")], "approuvee", depuis=("brouillon",))
    print("\n=== Envoi ===")
    bilan = envoyer_candidatures(config, base, test=args.test)
    print(f"Bilan : {bilan}")
    return 0


# --------------------------------------------------------------------------- #
# Analyse des arguments
# --------------------------------------------------------------------------- #

def construire_parseur() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="autopostule",
        description="Candidatures automatisées (offres récentes et candidatures spontanées) pour les métiers "
                    "de l'informatique.",
    )
    p.add_argument("--version", action="version", version=f"autopostule {__version__}")
    p.add_argument("-c", "--config", default="config.yaml", help="fichier de configuration (défaut : config.yaml)")
    sous = p.add_subparsers(dest="commande", required=True, metavar="COMMANDE")

    s = sous.add_parser("init", help="crée config.yaml et .env dans le dossier courant")
    s.add_argument("dossier", nargs="?", default=".")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_init)

    s = sous.add_parser("interface", help="ouvre l'interface graphique dans le navigateur")
    s.add_argument("--dossier", help="dossier de travail (défaut : le dernier utilisé, ou le dossier courant "
                                     "s'il contient config.yaml)")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--sans-navigateur", action="store_true", help="ne pas ouvrir le navigateur automatiquement")
    s.set_defaults(func=cmd_interface)

    sous.add_parser("metiers", help="liste les métiers disponibles").set_defaults(func=cmd_metiers)
    sous.add_parser("regions", help="liste les régions et départements").set_defaults(func=cmd_regions)
    sous.add_parser("cv", help="analyse le CV (compétences, coordonnées, métiers adaptés)").set_defaults(func=cmd_cv)

    s = sous.add_parser("cv-structure", help="crée cv.yaml, le CV structuré utilisé pour les CV adaptés")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_cv_structure)

    def option_contrat(sp):
        sp.add_argument("-t", "--contrat", action="append",
                        help=f"type de poste (répétable) : {', '.join(CONTRATS)} - remplace recherche.types_contrat")

    def filtres(sp):
        sp.add_argument("-m", "--metier", action="append", help="métier (répétable), ex : devops")
        sp.add_argument("-r", "--region", action="append", help="région (répétable), ex : hauts-de-france")
        sp.add_argument("-d", "--departement", action="append", help="département (répétable), ex : 59")
        sp.add_argument("-v", "--ville", action="append", help="ville du siège (répétable), ex : Lille")
        sp.add_argument("-n", "--limite", type=int, help="nombre maximum d'entreprises")

    s = sous.add_parser("rechercher", help="trouve des entreprises par métier et zone géographique")
    filtres(s)
    s.add_argument("--effectif-min", type=int, help="effectif minimum (ex : 10)")
    s.add_argument("--effectif-max", type=int,
                   help="effectif maximum (ex : 249 pour les PME, qui publient plus souvent une adresse RH)")
    s.set_defaults(func=cmd_rechercher)

    s = sous.add_parser("importer", help="importe des entreprises depuis un CSV (nom, site, email, ...)")
    s.add_argument("fichier")
    s.add_argument("-m", "--metier")
    s.set_defaults(func=cmd_importer)

    s = sous.add_parser("scanner", help="trouve le site et les e-mails RH des entreprises enregistrées")
    s.add_argument("-n", "--limite", type=int)
    s.set_defaults(func=cmd_scanner)

    s = sous.add_parser("generer", help="rédige lettre + CV adapté pour chaque entreprise ayant une adresse e-mail")
    s.add_argument("-m", "--metier")
    option_contrat(s)
    s.add_argument("--ia", action="store_true", help="personnalise avec Claude (ANTHROPIC_API_KEY requise)")
    s.add_argument("-n", "--limite", type=int)
    s.set_defaults(func=cmd_generer)

    s = sous.add_parser("lister", help="liste les candidatures")
    s.add_argument("-s", "--statut", choices=["brouillon", "approuvee", "envoyee", "echec", "ignoree"])
    s.set_defaults(func=cmd_lister)

    s = sous.add_parser("voir", help="affiche une candidature")
    s.add_argument("id", type=int)
    s.set_defaults(func=cmd_voir)

    s = sous.add_parser("approuver", help="valide des candidatures pour l'envoi")
    s.add_argument("ids", nargs="*", type=int)
    s.add_argument("--tout", action="store_true", help="approuve tous les brouillons")
    s.set_defaults(func=cmd_approuver)

    s = sous.add_parser("ignorer", help="écarte des candidatures")
    s.add_argument("ids", nargs="+", type=int)
    s.set_defaults(func=cmd_ignorer)

    s = sous.add_parser("envoyer", help="envoie les candidatures approuvées")
    s.add_argument("--test", action="store_true", help="n'envoie rien : écrit des fichiers .eml")
    s.add_argument("--max", type=int, help="nombre maximum d'envois pour cette exécution")
    s.add_argument("-y", "--oui", action="store_true", help="pas de confirmation interactive")
    s.set_defaults(func=cmd_envoyer)

    s = sous.add_parser("exclure", help="ne plus jamais contacter un e-mail, un domaine ou un SIREN")
    s.add_argument("valeurs", nargs="+")
    s.add_argument("--raison")
    s.set_defaults(func=cmd_exclure)

    sous.add_parser("stats", help="statistiques").set_defaults(func=cmd_stats)

    # -- offres d'emploi
    o = sous.add_parser("offres", help="offres d'emploi récentes : rechercher, ajouter, préparer, suivre")
    so = o.add_subparsers(dest="action", required=True, metavar="ACTION")

    s = so.add_parser("rechercher", help="récupère les offres récentes (France Travail, Adzuna)")
    filtres(s)
    option_contrat(s)
    s.add_argument("-j", "--jours", type=int, help="publiées depuis N jours (défaut : offres.publiees_depuis_jours)")
    s.add_argument("--source", action="append", choices=["france_travail", "adzuna", "jooble"])
    s.set_defaults(func=cmd_offres_rechercher)

    s = so.add_parser("alertes", help="importe les offres de vos alertes e-mail (Indeed, LinkedIn, Welcome to "
                                      "the Jungle, Monster, Google, HelloWork, Apec...)")
    s.add_argument("-j", "--jours", type=int, help="e-mails reçus depuis N jours (défaut : 7)")
    s.add_argument("--fichier", action="append", help="e-mail d'alerte enregistré (.eml), répétable ; "
                                                      "sans cette option, lecture de la boîte e-mail (IMAP)")
    option_contrat(s)
    s.set_defaults(func=cmd_offres_alertes)

    s = so.add_parser("ajouter", help="ajoute une offre trouvée ailleurs (LinkedIn, Indeed, site carrière...)")
    s.add_argument("--url", help="lien de l'offre (lecture automatique si le site l'autorise)")
    s.add_argument("--fichier", help="fichier texte contenant le texte copié de l'offre")
    s.add_argument("--titre")
    s.add_argument("--entreprise")
    s.add_argument("--ville")
    s.add_argument("--email", help="adresse de candidature indiquée dans l'offre")
    s.add_argument("--contrat", help=", ".join(CONTRATS))
    s.add_argument("-m", "--metier")
    s.set_defaults(func=cmd_offres_ajouter)

    s = so.add_parser("preparer", help="CV adapté + lettre pour chaque nouvelle offre ; trouve l'e-mail RH")
    s.add_argument("--ia", action="store_true", help="lettres rédigées par Claude")
    s.add_argument("-n", "--limite", type=int)
    option_contrat(s)
    s.set_defaults(func=cmd_offres_preparer)

    s = so.add_parser("lister", help="liste les offres")
    s.add_argument("-s", "--statut", choices=["nouvelle", "preparee", "postulee", "a_postuler_sur_site",
                                              "postulee_sur_site", "ignoree"])
    s.set_defaults(func=cmd_offres_lister)

    s = so.add_parser("voir", help="détail d'une offre et adéquation avec votre CV")
    s.add_argument("id")
    s.add_argument("--apercu", action="store_true", help="génère un aperçu du CV adapté")
    s.set_defaults(func=cmd_offres_voir)

    s = so.add_parser("ouvrir", help="ouvre l'offre dans le navigateur (candidature sur le site)")
    s.add_argument("id")
    s.set_defaults(func=cmd_offres_ouvrir)

    s = so.add_parser("fait", help="marque des offres comme postulées sur le site")
    s.add_argument("ids", nargs="+")
    s.set_defaults(func=lambda a: cmd_offres_statut(a, "postulee_sur_site"))

    s = so.add_parser("ignorer", help="écarte des offres")
    s.add_argument("ids", nargs="+")
    s.set_defaults(func=lambda a: cmd_offres_statut(a, "ignoree"))

    s = sous.add_parser("auto", help="enchaîne offres récentes, candidatures spontanées, lettres, CV et envoi")
    filtres(s)
    option_contrat(s)
    s.add_argument("--mode", choices=["tout", "offres", "spontanees"], default="tout")
    s.add_argument("-j", "--jours", type=int)
    s.add_argument("--source", action="append", choices=["france_travail", "adzuna", "jooble"])
    s.add_argument("--ia", action="store_true")
    s.add_argument("--test", action="store_true", help="envoi simulé (.eml)")
    s.add_argument("--approuver-tout", action="store_true",
                   help="approuve automatiquement les brouillons (sans relecture)")
    s.set_defaults(func=cmd_auto)
    return p


def main(argv: list[str] | None = None) -> int:
    args = construire_parseur().parse_args(argv)
    try:
        return args.func(args)
    except (ErreurConfig, FileNotFoundError, ValueError) as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrompu.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
