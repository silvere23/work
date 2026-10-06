"""CV adapté à chaque offre : titre du poste visé, compétences et missions remises en avant selon l'offre.

Le CV structuré (cv.yaml) contient tout le parcours. Pour chaque candidature, l'outil :
- remplace le titre par l'intitulé du poste visé (sans « H/F ») ;
- place en tête les compétences demandées par l'offre (en gras) et les catégories les plus utiles ;
- ordonne les missions de chaque expérience par pertinence (l'ordre chronologique des postes est conservé) ;
- ajoute une ligne « Atouts pour ce poste » à l'accroche (ou la fait réécrire par Claude) ;
- liste les compétences demandées absentes du CV, pour information (elles ne sont jamais ajoutées).
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .cv import AnalyseCV
from .pdfutil import Document
from .referentiel import METIERS, normaliser

EXEMPLE_CV = Path(__file__).parent / "templates" / "cv.exemple.yaml"
COULEUR = (31, 78, 121)
GRIS = (90, 90, 90)


@dataclass
class CVAdapte:
    donnees: dict
    mises_en_avant: list[str] = field(default_factory=list)   # compétences de l'offre présentes dans le CV
    manquantes: list[str] = field(default_factory=list)       # compétences de l'offre absentes du CV


def charger(chemin: Path) -> dict | None:
    chemin = Path(chemin)
    if not chemin.exists():
        return None
    from .config import lire_yaml

    donnees = lire_yaml(chemin)
    donnees.setdefault("competences", {})
    donnees.setdefault("experiences", [])
    if isinstance(donnees["competences"], list):
        donnees["competences"] = {"Compétences": donnees["competences"]}
    return donnees


MARQUEURS_EXEMPLE = {"entreprise a", "entreprise b", "lycee exemple"}


def est_exemple(cv: dict) -> bool:
    """Vrai si le CV structuré contient encore le parcours fictif du modèle (« Entreprise A », « Lycée Exemple »)."""
    noms = [normaliser(str(e.get("entreprise") or "")) for e in cv.get("experiences") or []]
    noms += [normaliser(str(f.get("etablissement") or "")) for f in cv.get("formations") or []]
    return any(n in MARQUEURS_EXEMPLE for n in noms)


def toutes_competences(cv: dict) -> list[str]:
    return [c for liste in (cv.get("competences") or {}).values() for c in liste or []]


def _norm(texte: str) -> str:
    return normaliser(texte)


def _present(terme: str, texte_normalise: str) -> bool:
    return re.search(r"(?<![\w])" + re.escape(_norm(terme)) + r"(?![\w])", texte_normalise) is not None


def texte_integral(cv: dict) -> str:
    morceaux = [cv.get("titre", ""), cv.get("accroche", ""), *toutes_competences(cv)]
    for e in cv.get("experiences") or []:
        morceaux += [e.get("poste", ""), *(e.get("missions") or [])]
    morceaux += [str(x) for x in cv.get("certifications") or []]
    return "\n".join(str(m) for m in morceaux)


def adapter(cv: dict, titre_vise: str, mots_cles: list[str], titre_selon_offre: bool = True,
            accroche: str | None = None) -> CVAdapte:
    """Réorganise le CV pour une offre. `mots_cles` : compétences citées par l'offre, par importance."""
    cv = copy.deepcopy(cv)
    texte_cv = _norm(texte_integral(cv))
    rang = {_norm(m): i for i, m in enumerate(mots_cles)}

    def importance(terme: str) -> int | None:
        return rang.get(_norm(terme))

    # compétences : celles demandées d'abord (dans l'ordre d'importance de l'offre), catégories utiles d'abord
    categories = []
    for nom, liste in (cv.get("competences") or {}).items():
        liste = list(liste or [])
        demandees = sorted([c for c in liste if importance(c) is not None], key=importance)
        autres = [c for c in liste if importance(c) is None]
        categories.append((len(demandees), nom, demandees + autres))
    categories.sort(key=lambda x: -x[0])  # tri stable : l'ordre d'origine départage
    cv["competences"] = {nom: liste for _, nom, liste in categories}

    # missions : les plus pertinentes en premier, l'ordre chronologique des expériences est conservé
    for experience in cv.get("experiences") or []:
        missions = list(experience.get("missions") or [])
        experience["missions"] = sorted(
            missions, key=lambda m: -sum(1 for k in mots_cles if _present(k, _norm(m))))

    mises_en_avant = [m for m in mots_cles if _present(m, texte_cv)]
    manquantes = [m for m in mots_cles if not _present(m, texte_cv)]

    if titre_selon_offre and titre_vise:
        cv["titre"] = titre_vise
    if accroche:
        cv["accroche"] = accroche
    elif mises_en_avant:
        cv["accroche"] = (str(cv.get("accroche") or "").strip() + "\nAtouts pour ce poste : "
                          + ", ".join(mises_en_avant[:6]) + ".").strip()
    cv["_mises_en_avant"] = mises_en_avant
    return CVAdapte(cv, mises_en_avant, manquantes)


def accroche_ia(redacteur, cv: dict, titre_vise: str, texte_offre: str) -> str:
    consignes = (
        "Tu réécris l'accroche (résumé de 2 à 3 phrases, 60 mots maximum) d'un CV en français pour un poste "
        "précis. N'utilise que des faits présents dans le CV : n'ajoute aucune compétence, expérience, "
        "certification ou chiffre. Mets en avant ce qui répond le mieux à l'offre. Réponds uniquement par "
        "l'accroche, sans guillemets ni titre."
    )
    demande = (f"<cv>\n{yaml.safe_dump(cv, allow_unicode=True, sort_keys=False)[:15000]}\n</cv>\n\n"
               f"<poste_vise>{titre_vise}</poste_vise>\n\n<offre>\n{texte_offre[:8000]}\n</offre>")
    return redacteur.rediger(consignes, demande)


# --------------------------------------------------------------------------- #
# Création d'un cv.yaml à partir du CV existant
# --------------------------------------------------------------------------- #

def modele_depuis_analyse(analyse: AnalyseCV | None, profil: dict) -> str:
    """cv.yaml de départ : compétences détectées dans le CV, rangées par métier ; parcours à compléter."""
    exemple = yaml.safe_load(EXEMPLE_CV.read_text(encoding="utf-8"))
    if analyse and analyse.competences:
        vues: set[str] = set()
        categories: dict[str, list[str]] = {}
        trouvees = {normaliser(c) for c in analyse.competences}
        for metier in sorted(METIERS.values(), key=lambda m: -analyse.scores_metiers.get(m.cle, 0)):
            liste = [c for c in metier.competences if normaliser(c) in trouvees and normaliser(c) not in vues]
            vues.update(normaliser(c) for c in liste)
            if liste:
                categories[metier.titre] = liste
        exemple["competences"] = categories
    exemple["titre"] = profil.get("titre") or exemple["titre"]
    entete = ("# CV structuré généré par `autopostule cv-structure`.\n"
              "# Compétences pré-remplies depuis votre CV ; COMPLÉTEZ expériences, missions et formations\n"
              "# (les valeurs d'exemple sont à remplacer). Renommez les catégories librement.\n\n")
    return entete + yaml.safe_dump(exemple, allow_unicode=True, sort_keys=False, width=110)


# --------------------------------------------------------------------------- #
# Rendu PDF
# --------------------------------------------------------------------------- #

def _gras(element: str, mises_en_avant: set[str]) -> str:
    texte = str(element).replace("*", "")
    return f"**{texte}**" if _norm(texte) in mises_en_avant else texte


def ecrire_pdf(cv: dict, profil: dict, chemin: Path) -> Path:
    doc = Document(marges=(16, 14, 16))
    pdf = doc.pdf
    mises_en_avant = {_norm(m) for m in cv.get("_mises_en_avant") or []}

    doc.police_(19, gras=True)
    pdf.set_text_color(20, 20, 20)
    doc.paragraphe(f"{profil.get('prenom', '')} {profil.get('nom', '')}".strip(), hauteur=9)
    doc.police_(13, gras=True)
    pdf.set_text_color(*COULEUR)
    doc.paragraphe(str(cv.get("titre") or profil.get("titre") or ""), hauteur=7)
    doc.police_(9)
    pdf.set_text_color(*GRIS)
    contact = [profil.get("telephone"), profil.get("email"),
               " ".join(str(x) for x in (profil.get("code_postal"), profil.get("ville")) if x),
               profil.get("linkedin"), profil.get("github"), profil.get("portfolio")]
    doc.paragraphe("  ·  ".join(str(c) for c in contact if c), hauteur=5)
    extras = []
    if profil.get("permis"):
        extras.append("Permis B")
    if profil.get("disponibilite"):
        extras.append(f"Disponible {profil['disponibilite']}")
    if profil.get("mobilite"):
        extras.append(f"Mobilité : {profil['mobilite']}")
    if extras:
        doc.paragraphe("  ·  ".join(extras), hauteur=5)
    pdf.ln(2)

    def section(titre: str) -> None:
        pdf.ln(2)
        doc.police_(11, gras=True)
        pdf.set_text_color(*COULEUR)
        doc.paragraphe(titre.upper(), hauteur=6)
        pdf.set_draw_color(*COULEUR)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(1.5)
        pdf.set_text_color(30, 30, 30)
        doc.police_(9.5)

    if cv.get("accroche"):
        section("Profil")
        for ligne in str(cv["accroche"]).strip().splitlines():
            doc.paragraphe(ligne, hauteur=4.8)

    if cv.get("competences"):
        section("Compétences")
        for categorie, liste in cv["competences"].items():
            if liste:
                valeurs = ", ".join(_gras(c, mises_en_avant) for c in liste)
                doc.paragraphe(f"**{categorie} :** {valeurs}", hauteur=4.8, markdown=True)

    if cv.get("experiences"):
        section("Expériences professionnelles")
        for e in cv["experiences"]:
            doc.police_(10, gras=True)
            entete = " - ".join(str(x) for x in (e.get("poste"), e.get("entreprise")) if x)
            doc.paragraphe(entete, hauteur=5.2)
            doc.police_(8.5)
            pdf.set_text_color(*GRIS)
            periode = " - ".join(str(x) for x in (e.get("debut"), e.get("fin")) if x)
            doc.paragraphe("  ·  ".join(x for x in (periode, str(e.get("lieu") or "")) if x), hauteur=4.4)
            pdf.set_text_color(30, 30, 30)
            doc.police_(9.5)
            for mission in e.get("missions") or []:
                doc.paragraphe(f"•  {str(mission)}", hauteur=4.8)
            pdf.ln(1.5)

    if cv.get("formations"):
        section("Formation")
        for f in cv["formations"]:
            ligne = " - ".join(str(x) for x in (f.get("annee"), f.get("diplome"), f.get("etablissement")) if x)
            doc.paragraphe(ligne, hauteur=4.8)

    for cle, titre in (("certifications", "Certifications"), ("langues", "Langues"),
                       ("centres_interet", "Centres d'intérêt")):
        if cv.get(cle):
            section(titre)
            doc.paragraphe(", ".join(_gras(c, mises_en_avant) for c in cv[cle]), hauteur=4.8, markdown=True)

    return doc.enregistrer(chemin)
