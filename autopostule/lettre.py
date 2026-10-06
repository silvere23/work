"""Génération de lettres de motivation adaptées à chaque entreprise (modèle Jinja2 ou IA Claude)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, StrictUndefined

from .config import contrats_vises
from .cv import AnalyseCV
from .ia import Redacteur
from .offres import titre_propre
from .pdfutil import Document
from .referentiel import METIERS, SECTEURS_NAF, Metier, borne_effectif, libelle_contrats, normaliser

DOSSIER_MODELES = Path(__file__).parent / "templates"
MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre")
RE_ACCORD = re.compile(r"\[([^\[\]|]+)\|([^\[\]|]+)(?:\|([^\[\]|]+))?\]")
SIGLES_JURIDIQUES = re.compile(r"\b(SAS|SASU|SARL|EURL|SA|SNC|SCOP)\b\.?", re.I)

# Termes reconnus dans le CV mais trop vagues pour être cités dans une lettre.
COMPETENCES_VAGUES = {normaliser(c) for c in ("support", "N1", "N2", "maintenance", "dépannage", "imprimantes",
                                              "ticketing", "LAN", "WAN", "routage", "switching", "sauvegarde",
                                              "Teams", "Outlook", "Wi-Fi", "Agile")}


def accorder(texte: str, genre: str | None) -> str:
    """Remplace « [masculin|féminin|inclusif] » selon le genre ('M', 'F' ou vide)."""
    genre = (genre or "").strip().upper()[:1]

    def choix(m: re.Match) -> str:
        masc, fem, inclusif = m.group(1), m.group(2), m.group(3)
        if genre == "M":
            return masc
        if genre == "F":
            return fem
        return inclusif or f"{masc}/{fem}"

    return RE_ACCORD.sub(choix, texte)


def date_fr(jour: date | None = None) -> str:
    jour = jour or date.today()
    return f"{jour.day} {MOIS[jour.month - 1]} {jour.year}"


def nom_court(nom: str) -> str:
    """'ACME SOLUTIONS SAS (ACME)' -> 'Acme Solutions'. Les sigles courts restent en majuscules."""
    nom = re.sub(r"\(.*?\)", "", nom)
    nom = SIGLES_JURIDIQUES.sub("", nom)
    nom = " ".join(nom.split()).strip(" -,")
    if nom.isupper():
        nom = " ".join(m if len(m) <= 3 else m.capitalize() for m in nom.split())
    return nom or "votre entreprise"


def _variante(options: tuple[str, ...] | list[str], graine: str) -> str:
    """Choix déterministe (même entreprise => même texte) mais varié d'une entreprise à l'autre."""
    if not options:
        return ""
    index = int(hashlib.sha256(graine.encode()).hexdigest(), 16) % len(options)
    return options[index]


def _minuscule(texte: str) -> str:
    """Première lettre en minuscule sauf pour un sigle (« DevOps », « SOC »...)."""
    if len(texte) > 1 and texte[1].isupper():
        return texte
    return texte[:1].lower() + texte[1:]


def _de(mot: str) -> str:
    """« de » ou « d' » devant un mot : d'administrateur, de technicien."""
    return ("d'" if normaliser(mot[:1]) in "aeiouyh" else "de ") + mot


def _que(mot: str) -> str:
    """« que » ou « qu' » : qu'administrateur, que technicien."""
    return ("qu'" if normaliser(mot[:1]) in "aeiouyh" else "que ") + mot


def _enumerer(elements: list[str]) -> str:
    if not elements:
        return ""
    if len(elements) == 1:
        return elements[0]
    return ", ".join(elements[:-1]) + " et " + elements[-1]


@dataclass
class Lettre:
    objet: str
    corps: str          # paragraphes entre « Madame, Monsieur, » et la formule de politesse
    lettre: str         # lettre complète (texte)
    message: str        # corps de l'e-mail
    moteur: str


class GenerateurLettres:
    def __init__(self, config, analyse_cv: AnalyseCV | None = None, competences_cv: list[str] | None = None,
                 redacteur: Redacteur | None = None, missions_cv: list[str] | None = None):
        self.config = config
        self.profil = config.profil
        self.cv = analyse_cv
        # compétences réellement présentes dans le CV (analyse du fichier + CV structuré)
        self.competences_cv = {normaliser(c): c for c in [*(analyse_cv.competences if analyse_cv else []),
                                                          *(competences_cv or [])]}
        self.missions_cv = [str(m).strip().rstrip(".") for m in missions_cv or [] if str(m).strip()]
        self.redacteur = redacteur or Redacteur(config["lettre"].get("modele_ia") or "claude-opus-5-5")
        chargeurs = []
        perso = config["lettre"].get("dossier_modeles")
        if perso:
            chargeurs.append(FileSystemLoader(str(config.chemin_relatif(perso))))
        chargeurs.append(FileSystemLoader(str(DOSSIER_MODELES)))
        self.env = Environment(loader=ChoiceLoader(chargeurs), undefined=StrictUndefined,
                               keep_trailing_newline=True, autoescape=False)

    # -- paragraphes (moteur « modele ») ------------------------------------ #

    def _competences(self, metier: Metier, mots_cles: list[str] | None = None) -> list[str]:
        """Compétences à citer : d'abord celles demandées par l'offre ET présentes dans le CV."""
        choisies: list[str] = []
        for c in mots_cles or []:
            if normaliser(c) in self.competences_cv and normaliser(c) not in COMPETENCES_VAGUES:
                choisies.append(self.competences_cv[normaliser(c)])
        if self.cv:
            for c in self.cv.competences_pour(metier.cle, maximum=50):
                if normaliser(c) not in COMPETENCES_VAGUES and c not in choisies:
                    choisies.append(c)
        return choisies[:6]

    def _realisations(self, mots: list[str], nombre: int = 2) -> list[str]:
        """Missions du CV structuré les plus en rapport avec l'offre (jamais de mission inventée)."""
        def score(mission: str) -> int:
            texte = f" {normaliser(mission)} "
            return sum(1 for m in mots if f" {normaliser(m)} " in texte or f" {normaliser(m)}," in texte)

        classees = sorted(self.missions_cv, key=score, reverse=True)
        return [m for m in classees if score(m) > 0][:nombre] or classees[:nombre]

    def paragraphes(self, entreprise: dict, metier: Metier, offre: dict | None = None,
                    mots_cles: list[str] | None = None, contrats: list[str] | None = None) -> list[str]:
        p = self.profil
        nom = nom_court(entreprise.get("nom") or "") if entreprise.get("nom") else "votre entreprise"
        graine = f"{entreprise.get('siren')}-{metier.cle}-{(offre or {}).get('id', '')}"
        de_nom = ("d'" if normaliser(nom[:1]) in "aeiouyh" else "de ") + nom
        titre = metier.titre_pour(p.get("genre"))

        if offre:
            intitule = titre_propre(offre.get("titre") or "") or titre
            poste = _minuscule(intitule)
            accroche = _variante((
                f"Votre offre {_de(poste)} a retenu toute mon attention : elle correspond "
                f"pleinement à mon parcours et au poste que je recherche.",
                f"C'est avec un vif intérêt que j'ai découvert votre annonce pour un poste {_de(poste)}, "
                f"à laquelle je souhaite répondre par la présente candidature.",
                f"Je vous propose ma candidature au poste {_de(poste)} : les missions décrites dans "
                f"votre annonce rejoignent précisément ce que je fais et ce que j'aime faire.",
            ), graine + "a")
        else:
            accroche = _variante(metier.accroches, graine + "a").format(entreprise=nom, de_entreprise=de_nom)

        annees = int(p.get("annees_experience") or 0)
        competences = self._competences(metier, mots_cles)
        missions = ", ainsi que ".join(metier.missions[:2])
        poste_actuel = _minuscule(p.get("titre") or titre)
        realisations = self._realisations(mots_cles or list(metier.competences))
        if annees >= 1 and realisations:
            parcours = (f"[Fort|Forte|Fort(e)] de {annees} an{'s' if annees > 1 else ''} d'expérience en tant "
                        f"{_que(poste_actuel)}, j'ai notamment mené les missions suivantes : "
                        f"{' ; '.join(_minuscule(r) for r in realisations)}.")
        elif annees >= 1:
            parcours = _variante((
                f"[Fort|Forte|Fort(e)] de {annees} an{'s' if annees > 1 else ''} d'expérience en tant "
                f"{_que(poste_actuel)}, j'ai notamment pris en charge {missions}.",
                f"Au cours de mes {annees} année{'s' if annees > 1 else ''} d'expérience comme "
                f"{poste_actuel}, j'ai assuré {missions}.",
            ), graine + "b")
        else:
            parcours = (f"Récemment [diplômé|diplômée|diplômé(e)] et [formé|formée|formé(e)] au métier de "
                        f"{_minuscule(titre)}, j'ai pu travailler sur {missions} lors de mes projets et stages.")
        demandees = [c for c in competences if normaliser(c) in {normaliser(m) for m in mots_cles or []}]
        if offre and len(demandees) >= 2:
            parcours += (f" Les compétences demandées dans votre annonce, notamment {_enumerer(demandees[:4])}, "
                         f"sont au cœur de mon parcours.")
            autres = [c for c in competences if c not in demandees[:4]][:3]
            if autres:
                parcours += f" Je maîtrise également {_enumerer(autres)}."
        elif competences:
            parcours += f" Je maîtrise en particulier {_enumerer(competences)}."

        secteur = SECTEURS_NAF.get(entreprise.get("naf") or "", "le numérique")
        effectif = borne_effectif(entreprise.get("tranche_effectif"))
        categorie = (entreprise.get("categorie") or "").upper()
        if offre and not entreprise.get("naf"):
            options = (
                f"Rejoindre {nom} sur ce poste serait pour moi l'occasion de mettre mon expérience au service "
                f"de vos projets et de continuer à progresser au sein de vos équipes.",
                "Je suis [convaincu|convaincue|convaincu(e)] de pouvoir rapidement m'intégrer à vos équipes et "
                "contribuer efficacement aux missions décrites dans votre annonce.",
            )
        elif categorie in {"GE", "ETI"} or (effectif is not None and effectif >= 250):
            options = (
                f"Intégrer un acteur reconnu de {secteur} tel que {nom} serait pour moi l'occasion d'évoluer "
                f"sur des environnements d'envergure, aux côtés d'équipes expérimentées.",
                f"La dimension {de_nom} et la diversité de ses projets dans {secteur} représentent exactement "
                f"le cadre dans lequel je souhaite progresser.",
            )
        elif effectif is not None and effectif < 50:
            options = (
                f"Rejoindre une structure à taille humaine comme {nom} me permettrait de m'investir pleinement "
                f"et d'apporter ma polyvalence à vos projets dans {secteur}.",
                f"J'apprécie particulièrement les équipes à taille humaine, où chacun contribue directement à "
                f"la réussite des projets : c'est ce que j'espère trouver chez {nom}.",
            )
        else:
            options = (
                f"Votre activité dans {secteur} et le dynamisme {de_nom} correspondent pleinement au projet "
                f"professionnel que je souhaite construire.",
                f"Le positionnement {de_nom} dans {secteur} m'intéresse tout particulièrement, et je suis "
                f"[convaincu|convaincue|convaincu(e)] de pouvoir rapidement contribuer à vos missions.",
            )
        paragraphe_entreprise = _variante(options, graine + "c")
        ville_e = (offre or {}).get("ville") or entreprise.get("ville") or ""
        dep_e = (offre or {}).get("departement") or entreprise.get("departement") or ""
        ville_p = p.get("ville") or ""
        proche = (normaliser(ville_e) and normaliser(ville_e) == normaliser(ville_p)) or (
            str(p.get("code_postal") or "")[:2] and str(p.get("code_postal"))[:2] == dep_e
        )
        if proche and ville_e:
            paragraphe_entreprise += f" Résidant à proximité, je peux facilement rejoindre vos locaux de {ville_e.title()}."

        dispo = p.get("disponibilite") or "rapidement"
        contrat = libelle_contrats([offre["type_contrat"]] if offre and offre.get("type_contrat") else contrats or [])
        conclusion = (f"Disponible {dispo}{f' pour un {contrat}' if contrat and contrat[0] in 'C' else ''}, je serais "
                      f"[heureux|heureuse|heureux(se)] de vous présenter plus en détail ma motivation lors d'un "
                      f"entretien.")

        paragraphes = [accroche, parcours, paragraphe_entreprise]
        if self.config["lettre"].get("paragraphe_perso"):
            paragraphes.append(str(self.config["lettre"]["paragraphe_perso"]).strip())
        paragraphes.append(conclusion)
        return [accorder(x, p.get("genre")) for x in paragraphes]

    # -- moteur IA (Claude) ------------------------------------------------- #

    def corps_ia(self, entreprise: dict, metier: Metier, brouillon: str, offre: dict | None = None,
                 contrats: list[str] | None = None) -> str:
        texte_cv = (self.cv.texte if self.cv else "")[:20000]
        consignes = (
            "Tu rédiges des lettres de motivation en français pour des candidatures dans l'informatique. "
            "Règles : n'invente aucune expérience, compétence, diplôme ou chiffre absent du CV ; quand une offre "
            "est fournie, réponds précisément à ses besoins en t'appuyant uniquement sur ce que le CV permet "
            "d'affirmer, et ne prétends pas maîtriser une compétence demandée absente du CV ; ton professionnel, "
            "sobre et chaleureux ; 180 à 280 mots ; 3 ou 4 paragraphes ; pas d'en-tête, pas de « Madame, "
            "Monsieur », pas de formule de politesse finale ni de signature : uniquement les paragraphes du "
            "corps, séparés par une ligne vide. N'affirme aucun fait sur l'entreprise qui ne soit pas fourni."
        )
        bloc_offre = ""
        if offre:
            bloc_offre = (f"<offre>\nIntitulé : {offre.get('titre')}\nContrat : {offre.get('type_contrat') or '?'}\n"
                          f"Lieu : {offre.get('ville') or '?'}\n{(offre.get('description') or '')[:8000]}\n</offre>\n\n")
        demande = (
            f"<cv>\n{texte_cv}\n</cv>\n\n"
            f"<candidat>\nNom : {self.profil.get('prenom')} {self.profil.get('nom')}\n"
            f"Genre grammatical : {self.profil.get('genre') or 'non précisé (écriture neutre)'}\n"
            f"Titre : {self.profil.get('titre')}\nExpérience : {self.profil.get('annees_experience')} an(s)\n"
            f"Contrat recherché : {libelle_contrats(contrats or []) or 'non précisé'}\n"
            f"Disponibilité : {self.profil.get('disponibilite')}\nMobilité : {self.profil.get('mobilite')}\n"
            f"</candidat>\n\n"
            f"<poste>{titre_propre((offre or {}).get('titre') or '') or metier.titre}</poste>\n\n"
            f"{bloc_offre}"
            f"<entreprise>\nNom : {nom_court(entreprise.get('nom') or '') or 'inconnu'}\n"
            f"Activité : {SECTEURS_NAF.get(entreprise.get('naf') or '', 'informatique')}\n"
            f"Ville : {entreprise.get('ville') or (offre or {}).get('ville')}\n"
            f"Catégorie : {entreprise.get('categorie') or 'inconnue'}\n</entreprise>\n\n"
            f"<brouillon>\n{brouillon}\n</brouillon>\n\n"
            "Réécris et personnalise le corps de cette lettre à partir du CV et des informations ci-dessus."
        )
        return self.redacteur.rediger(consignes, demande)

    # -- assemblage --------------------------------------------------------- #

    def generer(self, entreprise: dict, cle_metier: str, moteur: str | None = None, offre: dict | None = None,
                mots_cles: list[str] | None = None, contrats: list[str] | None = None) -> Lettre:
        metier = METIERS[cle_metier]
        contrats = contrats if contrats is not None else contrats_vises(self.config)
        moteur = moteur or self.config["lettre"].get("moteur") or "modele"
        paragraphes = self.paragraphes(entreprise, metier, offre, mots_cles, contrats)
        corps = "\n\n".join(paragraphes)
        moteur_effectif = "modele"
        if moteur == "ia":
            try:
                corps = self.corps_ia(entreprise, metier, corps, offre, contrats)
                moteur_effectif = "ia"
            except Exception as erreur:  # repli sur le modèle : la candidature ne doit pas être bloquée
                print(f"  [IA indisponible pour {entreprise.get('nom') or '?'} : {erreur} - modèle utilisé]")

        g = (self.profil.get("genre") or "").upper()[:1]
        titre = metier.titre_pour(self.profil.get("genre"))
        signataire = f"{self.profil.get('prenom', '')} {self.profil.get('nom', '')}".strip()
        if offre:
            intitule = titre_propre(offre.get("titre") or "") or titre
            reference = f" - réf. {offre['reference']}" if offre.get("reference") else ""
            objet_lettre = f"Candidature au poste {_de(intitule)}{reference}"
            objet = f"Candidature - {intitule}{reference} - {signataire}".strip(" -")
            contrat = libelle_contrats([offre["type_contrat"]]) if offre.get("type_contrat") else ""
        else:
            contrat = libelle_contrats(contrats)
            objet_lettre = f"Candidature spontanée - {titre}" + (f" ({contrat})" if contrat else "")
            objet = f"Candidature spontanée - {titre} - {signataire}".strip(" -")
        contexte = {
            "profil": self.profil,
            "entreprise": {"adresse": "", "ville": "", "naf": "", **entreprise, "nom": entreprise.get("nom") or "",
                           "nom_court": nom_court(entreprise["nom"]) if entreprise.get("nom") else "votre entreprise"},
            "metier": metier,
            "titre": titre,
            "offre": offre,
            "intitule": titre_propre(offre.get("titre") or "") if offre else titre,
            "source_offre": "France Travail" if offre and offre.get("source") == "France Travail" else "",
            "contrat": contrat,
            "objet_lettre": objet_lettre,
            "poste_de": _de(_minuscule(titre)),
            "date": date_fr(),
            "corps": corps,
            "e": "e" if g == "F" else ("" if g == "M" else "(e)"),
        }
        lettre = self.env.get_template("lettre.txt.j2").render(**contexte)
        joindre_pdf = bool(self.config["lettre"].get("joindre_pdf", True))
        resume = paragraphes[1] if len(paragraphes) > 1 else ""
        message = self.env.get_template("mail.txt.j2").render(
            **contexte, joindre_pdf=joindre_pdf, resume=resume, lettre_corps=corps
        )
        return Lettre(objet=objet, corps=corps, lettre=_nettoyer(lettre), message=_nettoyer(message),
                      moteur=moteur_effectif)


def _nettoyer(texte: str) -> str:
    texte = re.sub(r"[ \t]+\n", "\n", texte)
    return re.sub(r"\n{3,}", "\n\n", texte).strip() + "\n"


# --------------------------------------------------------------------------- #
# Export PDF
# --------------------------------------------------------------------------- #

def ecrire_pdf(texte: str, chemin: Path) -> Path:
    doc = Document()
    doc.police_(10.5)
    for ligne in texte.split("\n"):
        if ligne.strip():
            doc.paragraphe(ligne)
        else:
            doc.pdf.ln(3.5)
    return doc.enregistrer(chemin)
