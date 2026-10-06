"""Interface en ligne de commande : `autopostule <commande> [options]`."""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import sys
import textwrap
from pathlib import Path

from . import __version__
from .config import EXEMPLE, ErreurConfig, charger
from .cv import AnalyseCV, analyser_fichier
from .emails import classer
from .entreprises import ClientRechercheEntreprises, CriteresRecherche
from .envoi import envoyer_candidatures, nom_fichier
from .lettre import GenerateurLettres, ecrire_pdf
from .referentiel import METIERS, REGIONS, trouver_metier, trouver_region
from .sites import Prospecteur, mx_valide
from .stockage import Base
from .web import Navigateur

TYPES_PAR_DEFAUT = ("rh", "generique")
ENV_EXEMPLE = """# Secrets - ne versionnez jamais ce fichier
# Gmail : https://myaccount.google.com/apppasswords (validation en 2 étapes requise)
AUTOPOSTULE_SMTP_PASSWORD=
# Facultatif, pour lettre.moteur: "ia" (https://console.anthropic.com/)
ANTHROPIC_API_KEY=
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
    return 0


def rechercher(config, base: Base, metiers: list[str], regions: list[str], departements: list[str],
               villes: list[str], limite: int, effectif_min: int) -> int:
    client = ClientRechercheEntreprises()
    nouvelles = 0
    codes_regions = [trouver_region(r).code for r in regions]
    for cle in metiers:
        metier = trouver_metier(cle)
        criteres = CriteresRecherche(
            metier=metier, regions=codes_regions, departements=departements, villes=villes,
            effectif_min=effectif_min, limite=limite,
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
    analyse = _analyse_cv(config)
    generateur = GenerateurLettres(config, analyse)
    dossier = config.dossier_donnees / "lettres"
    n = 0
    for e in base.entreprises_sans_candidature(trouver_metier(metier).cle if metier else None):
        if limite and n >= limite:
            break
        meilleur = base.meilleur_email(e["siren"])
        if not meilleur or base.est_exclu(meilleur["email"], e["siren"]):
            continue
        entreprise = dict(e)
        lettre = generer_une(generateur, entreprise, e["metier"] or _liste(config["recherche"]["metiers"])[0],
                             moteur)
        pdf = None
        if config["lettre"].get("joindre_pdf", True):
            nom_pdf = (f"Lettre_motivation_{nom_fichier(config.profil['nom'])}_"
                       f"{nom_fichier(entreprise['nom'])[:40]}.pdf")
            pdf = str(ecrire_pdf(lettre.lettre, dossier / nom_pdf))
        (dossier / f"{nom_fichier(entreprise['nom'])[:40]}_{e['siren']}.txt").write_text(lettre.lettre, encoding="utf-8")
        id_ = base.ajouter_candidature({
            "siren": e["siren"], "email": meilleur["email"], "metier": e["metier"], "objet": lettre.objet,
            "corps": lettre.message, "lettre": lettre.lettre, "lettre_pdf": pdf, "moteur": lettre.moteur,
        })
        n += 1
        print(f"  #{id_:<5} {entreprise['nom'][:45]:<45} <{meilleur['email']}> [{lettre.moteur}]")
    print(f"{n} candidatures préparées (statut « brouillon »).")
    return n


def generer_une(generateur: GenerateurLettres, entreprise: dict, metier: str, moteur: str | None):
    (generateur.config.dossier_donnees / "lettres").mkdir(parents=True, exist_ok=True)
    return generateur.generer(entreprise, metier, moteur)


def cmd_generer(args) -> int:
    config = charger(args.config)
    generer(config, _base(config), args.metier, "ia" if args.ia else None, args.limite)
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
    """Chaîne complète : recherche -> scan -> lettres -> (approbation) -> envoi."""
    config = charger(args.config)
    base = _base(config)
    r = config["recherche"]
    print("=== 1/4 Recherche des entreprises ===")
    rechercher(
        config, base,
        metiers=_liste(args.metier) or _liste(r.get("metiers")),
        regions=_liste(args.region) or ([] if args.departement else _liste(r.get("regions"))),
        departements=_liste(args.departement) or _liste(r.get("departements")),
        villes=_liste(args.ville) or _liste(r.get("villes")),
        limite=args.limite or int(r.get("limite") or 200),
        effectif_min=int(r.get("effectif_min") or 0),
    )
    print("\n=== 2/4 Recherche des adresses e-mail ===")
    scanner(config, base, args.limite)
    print("\n=== 3/4 Rédaction des lettres ===")
    generer(config, base, moteur="ia" if args.ia else None)
    if config["envoi"].get("validation_manuelle", True) and not args.approuver_tout:
        print("\n=== 4/4 Envoi ===\nValidation manuelle activée : relisez avec `autopostule lister --statut brouillon`"
              " / `autopostule voir ID`, puis `autopostule approuver --tout` et `autopostule envoyer`.")
        return 0
    if args.approuver_tout:
        base.changer_statut([c["id"] for c in base.candidatures("brouillon")], "approuvee", depuis=("brouillon",))
    print("\n=== 4/4 Envoi ===")
    bilan = envoyer_candidatures(config, base, test=args.test)
    print(f"Bilan : {bilan}")
    return 0


# --------------------------------------------------------------------------- #
# Analyse des arguments
# --------------------------------------------------------------------------- #

def construire_parseur() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="autopostule",
        description="Candidatures spontanées automatisées pour les métiers de l'informatique.",
    )
    p.add_argument("--version", action="version", version=f"autopostule {__version__}")
    p.add_argument("-c", "--config", default="config.yaml", help="fichier de configuration (défaut : config.yaml)")
    sous = p.add_subparsers(dest="commande", required=True, metavar="COMMANDE")

    s = sous.add_parser("init", help="crée config.yaml et .env dans le dossier courant")
    s.add_argument("dossier", nargs="?", default=".")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_init)

    sous.add_parser("metiers", help="liste les métiers disponibles").set_defaults(func=cmd_metiers)
    sous.add_parser("regions", help="liste les régions et départements").set_defaults(func=cmd_regions)
    sous.add_parser("cv", help="analyse le CV (compétences, coordonnées, métiers adaptés)").set_defaults(func=cmd_cv)

    def filtres(sp):
        sp.add_argument("-m", "--metier", action="append", help="métier (répétable), ex : devops")
        sp.add_argument("-r", "--region", action="append", help="région (répétable), ex : hauts-de-france")
        sp.add_argument("-d", "--departement", action="append", help="département (répétable), ex : 59")
        sp.add_argument("-v", "--ville", action="append", help="ville du siège (répétable), ex : Lille")
        sp.add_argument("-n", "--limite", type=int, help="nombre maximum d'entreprises")

    s = sous.add_parser("rechercher", help="trouve des entreprises par métier et zone géographique")
    filtres(s)
    s.add_argument("--effectif-min", type=int, help="effectif minimum (ex : 10)")
    s.set_defaults(func=cmd_rechercher)

    s = sous.add_parser("importer", help="importe des entreprises depuis un CSV (nom, site, email, ...)")
    s.add_argument("fichier")
    s.add_argument("-m", "--metier")
    s.set_defaults(func=cmd_importer)

    s = sous.add_parser("scanner", help="trouve le site et les e-mails RH des entreprises enregistrées")
    s.add_argument("-n", "--limite", type=int)
    s.set_defaults(func=cmd_scanner)

    s = sous.add_parser("generer", help="rédige une lettre par entreprise ayant une adresse e-mail")
    s.add_argument("-m", "--metier")
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

    s = sous.add_parser("auto", help="enchaîne recherche, scan, lettres et envoi")
    filtres(s)
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
