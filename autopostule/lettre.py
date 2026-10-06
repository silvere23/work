"""Génération de lettres de motivation adaptées à chaque entreprise (modèle Jinja2 ou IA Claude)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, StrictUndefined

from .cv import AnalyseCV
from .referentiel import METIERS, SECTEURS_NAF, Metier, borne_effectif, normaliser

DOSSIER_MODELES = Path(__file__).parent / "templates"
MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre")
RE_ACCORD = re.compile(r"\[([^\[\]|]+)\|([^\[\]|]+)(?:\|([^\[\]|]+))?\]")
SIGLES_JURIDIQUES = re.compile(r"\b(SAS|SASU|SARL|EURL|SA|SNC|SCOP)\b\.?", re.I)

# Termes reconnus dans le CV mais trop vagues pour être cités dans une lettre.
COMPETENCES_VAGUES = {normaliser(c) for c in ("support", "N1", "N2", "maintenance", "dépannage", "imprimantes",
                                              "ticketing", "LAN", "WAN", "routage", "switching", "sauvegarde",
                                              "Teams", "Outlook", "Wi-Fi", "Agile")}

# Modèles pour lesquels le paramètre serveur `fallbacks` est disponible.
MODELES_AVEC_FALLBACK = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}


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
    def __init__(self, config, analyse_cv: AnalyseCV | None = None):
        self.config = config
        self.profil = config.profil
        self.cv = analyse_cv
        chargeurs = []
        perso = config["lettre"].get("dossier_modeles")
        if perso:
            chargeurs.append(FileSystemLoader(str(config.chemin_relatif(perso))))
        chargeurs.append(FileSystemLoader(str(DOSSIER_MODELES)))
        self.env = Environment(loader=ChoiceLoader(chargeurs), undefined=StrictUndefined,
                               keep_trailing_newline=True, autoescape=False)
        self._client_ia = None

    # -- paragraphes (moteur « modele ») ------------------------------------ #

    def _competences(self, metier: Metier) -> list[str]:
        if not self.cv:
            return []
        trouvees = self.cv.competences_pour(metier.cle, maximum=50)
        return [c for c in trouvees if normaliser(c) not in COMPETENCES_VAGUES][:6]

    def paragraphes(self, entreprise: dict, metier: Metier) -> list[str]:
        p = self.profil
        nom = nom_court(entreprise["nom"])
        graine = f"{entreprise.get('siren')}-{metier.cle}"
        de_nom = ("d'" if normaliser(nom[:1]) in "aeiouyh" else "de ") + nom

        accroche = _variante(metier.accroches, graine + "a").format(entreprise=nom, de_entreprise=de_nom)

        annees = int(p.get("annees_experience") or 0)
        competences = self._competences(metier)
        missions = ", ainsi que ".join(metier.missions[:2])
        if annees >= 1:
            debut = _variante((
                f"[Fort|Forte|Fort(e)] de {annees} an{'s' if annees > 1 else ''} d'expérience en tant que "
                f"{_minuscule(p.get('titre') or metier.titre_pour(p.get('genre')))}, j'ai notamment pris en charge {missions}.",
                f"Au cours de mes {annees} année{'s' if annees > 1 else ''} d'expérience comme "
                f"{_minuscule(p.get('titre') or metier.titre_pour(p.get('genre')))}, j'ai assuré {missions}.",
            ), graine + "b")
        else:
            debut = (f"Récemment [diplômé|diplômée|diplômé(e)] et [formé|formée|formé(e)] au métier de "
                     f"{_minuscule(metier.titre_pour(p.get('genre')))}, j'ai pu travailler sur {missions} lors de mes projets et stages.")
        if competences:
            debut += f" Je maîtrise en particulier {_enumerer(competences)}."
        parcours = debut

        secteur = SECTEURS_NAF.get(entreprise.get("naf") or "", "le numérique")
        effectif = borne_effectif(entreprise.get("tranche_effectif"))
        categorie = (entreprise.get("categorie") or "").upper()
        if categorie in {"GE", "ETI"} or (effectif is not None and effectif >= 250):
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
        ville_e, ville_p = entreprise.get("ville") or "", p.get("ville") or ""
        proche = (normaliser(ville_e) and normaliser(ville_e) == normaliser(ville_p)) or (
            str(p.get("code_postal") or "")[:2] and str(p.get("code_postal"))[:2] == (entreprise.get("departement") or "")
        )
        if proche and ville_e:
            paragraphe_entreprise += f" Résidant à proximité, je peux facilement rejoindre vos locaux de {ville_e.title()}."

        dispo = p.get("disponibilite") or "rapidement"
        conclusion = (f"Disponible {dispo}, je serais [heureux|heureuse|heureux(se)] de vous présenter plus en "
                      f"détail ma motivation lors d'un entretien.")

        paragraphes = [accroche, parcours, paragraphe_entreprise]
        if self.config["lettre"].get("paragraphe_perso"):
            paragraphes.append(str(self.config["lettre"]["paragraphe_perso"]).strip())
        paragraphes.append(conclusion)
        return [accorder(x, p.get("genre")) for x in paragraphes]

    # -- moteur IA (Claude) ------------------------------------------------- #

    def corps_ia(self, entreprise: dict, metier: Metier, brouillon: str) -> str:
        import anthropic

        if self._client_ia is None:
            self._client_ia = anthropic.Anthropic()
        modele = self.config["lettre"].get("modele_ia") or "claude-opus-5-5"
        texte_cv = (self.cv.texte if self.cv else "")[:20000]
        consignes = (
            "Tu rédiges des lettres de motivation en français pour des candidatures spontanées dans "
            "l'informatique. Règles : n'invente aucune expérience, compétence, diplôme ou chiffre absent du CV ; "
            "ton professionnel, sobre et chaleureux ; 180 à 280 mots ; 3 ou 4 paragraphes ; pas d'en-tête, "
            "pas de « Madame, Monsieur », pas de formule de politesse finale ni de signature : uniquement les "
            "paragraphes du corps, séparés par une ligne vide. Adapte le propos à l'entreprise (secteur, taille, "
            "localisation) sans affirmer de faits non fournis à son sujet."
        )
        demande = (
            f"<cv>\n{texte_cv}\n</cv>\n\n"
            f"<candidat>\nNom : {self.profil.get('prenom')} {self.profil.get('nom')}\n"
            f"Genre grammatical : {self.profil.get('genre') or 'non précisé (écriture neutre)'}\n"
            f"Titre : {self.profil.get('titre')}\nExpérience : {self.profil.get('annees_experience')} an(s)\n"
            f"Contrat recherché : {self.profil.get('type_contrat')}\n"
            f"Disponibilité : {self.profil.get('disponibilite')}\nMobilité : {self.profil.get('mobilite')}\n"
            f"</candidat>\n\n"
            f"<poste>{metier.titre}</poste>\n\n"
            f"<entreprise>\nNom : {nom_court(entreprise['nom'])}\n"
            f"Activité : {SECTEURS_NAF.get(entreprise.get('naf') or '', 'informatique')}\n"
            f"Ville : {entreprise.get('ville')}\nCatégorie : {entreprise.get('categorie') or 'inconnue'}\n"
            f"</entreprise>\n\n"
            f"<brouillon>\n{brouillon}\n</brouillon>\n\n"
            "Réécris et personnalise le corps de cette lettre à partir du CV et des informations ci-dessus."
        )
        options = {}
        if modele in MODELES_AVEC_FALLBACK:
            options = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        reponse = self._client_ia.beta.messages.create(
            model=modele,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            system=consignes,
            messages=[{"role": "user", "content": demande}],
            **options,
        )
        if reponse.stop_reason == "refusal":
            raise RuntimeError("le modèle a refusé la demande")
        texte = "".join(b.text for b in reponse.content if b.type == "text").strip()
        if not texte:
            raise RuntimeError(f"réponse vide (stop_reason={reponse.stop_reason})")
        return texte

    # -- assemblage --------------------------------------------------------- #

    def generer(self, entreprise: dict, cle_metier: str, moteur: str | None = None) -> Lettre:
        metier = METIERS[cle_metier]
        moteur = moteur or self.config["lettre"].get("moteur") or "modele"
        paragraphes = self.paragraphes(entreprise, metier)
        corps = "\n\n".join(paragraphes)
        moteur_effectif = "modele"
        if moteur == "ia":
            try:
                corps = self.corps_ia(entreprise, metier, corps)
                moteur_effectif = "ia"
            except Exception as erreur:  # repli sur le modèle : la candidature ne doit pas être bloquée
                print(f"  [IA indisponible pour {entreprise['nom']} : {erreur} - modèle utilisé]")

        g = (self.profil.get("genre") or "").upper()[:1]
        contexte = {
            "profil": self.profil,
            "entreprise": {**entreprise, "nom_court": nom_court(entreprise["nom"])},
            "metier": metier,
            "titre": metier.titre_pour(self.profil.get("genre")),
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
        objet = (f"Candidature spontanée - {metier.titre_pour(self.profil.get('genre'))} - "
                 f"{self.profil.get('prenom', '')} {self.profil.get('nom', '')}").strip(" -")
        return Lettre(objet=objet, corps=corps, lettre=_nettoyer(lettre), message=_nettoyer(message),
                      moteur=moteur_effectif)


def _nettoyer(texte: str) -> str:
    texte = re.sub(r"[ \t]+\n", "\n", texte)
    return re.sub(r"\n{3,}", "\n\n", texte).strip() + "\n"


# --------------------------------------------------------------------------- #
# Export PDF
# --------------------------------------------------------------------------- #

POLICES_UNICODE = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "C:/Windows/Fonts/arial.ttf",
)
REMPLACEMENTS_LATIN1 = {"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...", "œ": "oe",
                        "Œ": "OE", "€": "EUR", "\u00a0": " ", "\u202f": " ", "•": "-"}


def ecrire_pdf(texte: str, chemin: Path) -> Path:
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_margins(22, 20, 22)
    pdf.set_auto_page_break(True, margin=20)
    pdf.add_page()
    police = next((p for p in POLICES_UNICODE if Path(p).exists()), None)
    if police:
        pdf.add_font("Lettre", "", police)
        pdf.set_font("Lettre", size=10.5)
    else:
        pdf.set_font("Helvetica", size=10.5)
        for avant, apres in REMPLACEMENTS_LATIN1.items():
            texte = texte.replace(avant, apres)
        texte = texte.encode("latin-1", errors="replace").decode("latin-1")
    largeur = pdf.w - pdf.l_margin - pdf.r_margin
    for ligne in texte.split("\n"):
        if ligne.strip():
            pdf.multi_cell(largeur, 5.2, ligne, new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.ln(3.5)
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(chemin))
    return chemin
