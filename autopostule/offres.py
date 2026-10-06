"""Récupération d'offres d'emploi récentes depuis des sources autorisées.

Sources :
- France Travail (API officielle « Offres d'emploi v2 ») : offres déposées chez France Travail et offres des
  sites emploi partenaires qu'il agrège. Inscription gratuite : https://francetravail.io
- Adzuna (API officielle) : agrégateur qui référence les offres de nombreux sites emploi et pages carrières.
  Clé gratuite : https://developer.adzuna.com
- Import manuel : URL d'une offre (lecture des données structurées schema.org/JobPosting publiées par la
  plupart des sites) ou fichier texte (copier-coller depuis n'importe quelle plateforme, LinkedIn compris).

LinkedIn, Indeed & co interdisent l'extraction automatisée dans leurs conditions d'utilisation : ils ne sont
pas interrogés directement.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Iterator

import requests
from bs4 import BeautifulSoup

from .emails import RE_EMAIL, classer
from .referentiel import (METIERS, REGIONS, Metier, normaliser, normaliser_contrat, toutes_les_competences)
from .web import Navigateur

URL_JETON_FT = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
URL_OFFRES_FT = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
URL_ADZUNA = "https://api.adzuna.com/v1/api/jobs/fr/search/{page}"

CONTRATS_FT = {"CDI": "CDI", "CDD": "CDD", "interim": "MIS", "freelance": "LIB"}
PUBLIEES_DEPUIS_FT = (1, 3, 7, 14, 31)  # seules valeurs acceptées par l'API

RE_MENTION_GENRE = re.compile(r"\s*[\(\[]?\s*\b(?:h\s*/\s*f|f\s*/\s*h|h\s*-\s*f|f\s*-\s*h|m\s*/\s*f|f\s*/\s*m)\b\s*[\)\]]?",
                              re.I)


@dataclass
class Offre:
    id: str
    source: str
    titre: str
    entreprise: str = ""
    description: str = ""
    url: str = ""
    email: str = ""
    ville: str = ""
    code_postal: str = ""
    departement: str = ""
    type_contrat: str = ""          # valeur normalisée : CDI, CDD, interim, alternance, stage, freelance
    date_publication: str = ""
    salaire: str = ""
    competences: list[str] = field(default_factory=list)
    reference: str = ""
    metier: str = ""

    @property
    def texte(self) -> str:
        return "\n".join([self.titre, self.description, " ; ".join(self.competences)])

    @property
    def cle_doublon(self) -> str:
        """Identifie une même offre publiée sur plusieurs sources."""
        base = "|".join(normaliser(x) for x in (titre_propre(self.titre), self.entreprise, self.ville))
        return hashlib.sha1(base.encode()).hexdigest()[:16]

    def en_dict(self) -> dict:
        return asdict(self)


def titre_propre(titre: str) -> str:
    """'Administrateur Systèmes H/F - CDI' -> 'Administrateur Systèmes'."""
    titre = RE_MENTION_GENRE.sub(" ", titre or "")
    titre = re.sub(r"\s[-–|]\s*(cdi|cdd|stage|alternance|interim|intérim|freelance)\b.*$", "", titre, flags=re.I)
    titre = re.sub(r"\((?:cdi|cdd|stage|alternance)\)", "", titre, flags=re.I)
    return " ".join(titre.split()).strip(" -–|,")


def texte_brut(html: str) -> str:
    if not html:
        return ""
    if "<" not in html:
        return html.strip()
    soup = BeautifulSoup(html, "html.parser")
    for br in soup.find_all(["br", "p", "li", "div", "h1", "h2", "h3"]):
        br.append("\n")
    return re.sub(r"\n\s*\n+", "\n\n", soup.get_text()).strip()


RE_CONTRAT_TEXTE = re.compile(r"\b(CDI|CDD|int[ée]rim|alternance|apprentissage|freelance|stage)\b", re.I)


def contrat_dans_texte(titre: str, texte: str = "") -> str:
    """Type de contrat d'après l'intitulé, sinon d'après le début du texte de l'offre."""
    for morceau in (titre, (texte or "")[:800]):
        if m := RE_CONTRAT_TEXTE.search(morceau or ""):
            return normaliser_contrat(m.group(1)) or ""
    return ""


def email_dans_texte(texte: str) -> str:
    """Première adresse de candidature exploitable citée dans le texte d'une offre."""
    meilleures = []
    for adresse in RE_EMAIL.findall(texte or ""):
        trouve = classer(adresse)
        if trouve:
            meilleures.append(trouve)
    meilleures.sort(key=lambda e: -e.score)
    return meilleures[0].email if meilleures else ""


# --------------------------------------------------------------------------- #
# Analyse du contenu d'une offre
# --------------------------------------------------------------------------- #

def _contient(texte_normalise: str, terme: str) -> bool:
    motif = r"(?<![\w])" + re.escape(normaliser(terme)) + r"(?![\w])"
    return re.search(motif, texte_normalise) is not None


def mots_cles(offre: Offre, competences_supplementaires: list[str] | None = None) -> list[str]:
    """Compétences techniques citées par l'offre, de la plus fréquente à la moins fréquente."""
    texte = normaliser(offre.texte)
    vocabulaire = {normaliser(c): c for c in toutes_les_competences()}
    for c in competences_supplementaires or []:
        vocabulaire.setdefault(normaliser(c), c)
    scores = []
    for cle, libelle in vocabulaire.items():
        if len(cle) < 2 or not _contient(texte, libelle):
            continue
        occurrences = len(re.findall(r"(?<![\w])" + re.escape(cle) + r"(?![\w])", texte))
        dans_titre = _contient(normaliser(offre.titre), libelle)
        scores.append((occurrences + (5 if dans_titre else 0), libelle))
    scores.sort(key=lambda x: -x[0])
    return [libelle for _, libelle in scores]


def score_metier(offre: Offre, metier: Metier) -> int:
    titre = f" {normaliser(offre.titre)} "
    score = 6 if any(f" {normaliser(m).strip()}" in titre for m in metier.intitules) else 0
    texte = normaliser(offre.texte)
    score += sum(1 for c in metier.competences if _contient(texte, c))
    return score


def deduire_metier(offre: Offre, cibles: list[str]) -> tuple[str | None, int]:
    """Métier ciblé le plus proche de l'offre, et son score (0 = offre hors sujet)."""
    meilleurs = sorted(((score_metier(offre, METIERS[c]), c) for c in cibles), reverse=True)
    if not meilleurs or meilleurs[0][0] == 0:
        return None, 0
    return meilleurs[0][1], meilleurs[0][0]


def est_pertinente(offre: Offre, metier: Metier) -> bool:
    """L'intitulé correspond au métier, ou l'offre cite au moins 3 de ses compétences."""
    titre = f" {normaliser(offre.titre)} "
    if any(f" {normaliser(m).strip()}" in titre for m in metier.intitules):
        return True
    texte = normaliser(offre.texte)
    return sum(1 for c in metier.competences if _contient(texte, c)) >= 3


def contrat_accepte(offre: Offre, contrats: list[str]) -> bool:
    if not contrats:
        return True
    if offre.type_contrat:
        return offre.type_contrat in contrats
    titre = normaliser(offre.titre)
    return any(normaliser(c) in titre for c in contrats)


# --------------------------------------------------------------------------- #
# France Travail
# --------------------------------------------------------------------------- #

class SourceFranceTravail:
    nom = "France Travail"

    def __init__(self, client_id: str, client_secret: str, session: requests.Session | None = None,
                 url_jeton: str | None = None, url_offres: str | None = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = session or requests.Session()
        self.url_jeton = url_jeton or URL_JETON_FT
        self.url_offres = url_offres or URL_OFFRES_FT
        self._jeton: str | None = None
        self._expiration = 0.0

    def jeton(self) -> str:
        if self._jeton and time.monotonic() < self._expiration:
            return self._jeton
        r = self.session.post(
            self.url_jeton, params={"realm": "/partenaire"}, timeout=20,
            data={"grant_type": "client_credentials", "client_id": self.client_id,
                  "client_secret": self.client_secret, "scope": "api_offresdemploiv2 o2dsoffre"},
        )
        r.raise_for_status()
        donnees = r.json()
        self._jeton = donnees["access_token"]
        self._expiration = time.monotonic() + int(donnees.get("expires_in", 1400)) - 60
        return self._jeton

    def _requete(self, params: dict) -> list[dict]:
        for tentative in range(4):
            r = self.session.get(self.url_offres, params=params, timeout=30,
                                 headers={"Authorization": f"Bearer {self.jeton()}", "Accept": "application/json"})
            if r.status_code == 204:
                return []
            if r.status_code == 429:
                time.sleep(2 ** tentative)
                continue
            r.raise_for_status()
            return r.json().get("resultats") or []
        r.raise_for_status()
        return []

    def rechercher(self, requete: str, zones: list[tuple[str, str]], contrats: list[str], jours: int,
                   limite: int) -> Iterator[Offre]:
        """zones : [('region', '11'), ('departement', '59'), ...] ; une seule zone par appel API."""
        depuis = next((j for j in PUBLIEES_DEPUIS_FT if j >= jours), 31)
        params = {"motsCles": requete, "publieeDepuis": depuis, "sort": 1}
        codes = sorted({CONTRATS_FT[c] for c in contrats if c in CONTRATS_FT})
        if codes and len(codes) == len(contrats):
            params["typeContrat"] = ",".join(codes)
        for type_zone, code in zones or [("", "")]:
            p = dict(params)
            if type_zone:
                p[type_zone] = code
            debut, n = 0, 0
            while n < limite and debut < 3000:
                fin = min(debut + 149, debut + limite - n - 1)
                resultats = self._requete({**p, "range": f"{debut}-{fin}"})
                for brut in resultats:
                    yield convertir_france_travail(brut)
                    n += 1
                if len(resultats) < fin - debut + 1:
                    break
                debut = fin + 1
                time.sleep(0.2)


def convertir_france_travail(brut: dict) -> Offre:
    lieu = brut.get("lieuTravail") or {}
    libelle_lieu = lieu.get("libelle") or ""
    departement = ""
    if m := re.match(r"\s*(\d{2,3}|2A|2B)\s*-\s*(.*)", libelle_lieu):
        departement, ville = m.group(1), m.group(2)
    else:
        ville = libelle_lieu
    contact = brut.get("contact") or {}
    origine = brut.get("origineOffre") or {}
    contrat = normaliser_contrat(brut.get("typeContrat"))
    if brut.get("alternance") or normaliser_contrat(brut.get("natureContrat") or "") == "alternance":
        contrat = "alternance"
    description = brut.get("description") or ""
    email = contact.get("courriel") or ""
    email = email if RE_EMAIL.fullmatch(email.strip()) else email_dans_texte(email + " " + description)
    identifiant = str(brut.get("id") or "")
    return Offre(
        id=f"ft:{identifiant}",
        source="France Travail",
        titre=brut.get("intitule") or "",
        entreprise=(brut.get("entreprise") or {}).get("nom") or "",
        description=description,
        url=origine.get("urlOrigine") or contact.get("urlPostulation")
        or f"https://candidat.francetravail.fr/offres/recherche/detail/{identifiant}",
        email=email.strip().lower(),
        ville=ville.strip(),
        code_postal=lieu.get("codePostal") or "",
        departement=departement or (lieu.get("codePostal") or "")[:2],
        type_contrat=contrat or "",
        date_publication=brut.get("dateCreation") or "",
        salaire=(brut.get("salaire") or {}).get("libelle") or "",
        competences=[c.get("libelle", "") for c in brut.get("competences") or [] if c.get("libelle")],
        reference=identifiant,
    )


# --------------------------------------------------------------------------- #
# Adzuna
# --------------------------------------------------------------------------- #

class SourceAdzuna:
    nom = "Adzuna"

    def __init__(self, app_id: str, app_key: str, session: requests.Session | None = None, url: str | None = None):
        self.app_id = app_id
        self.app_key = app_key
        self.session = session or requests.Session()
        self.url = url or URL_ADZUNA

    def rechercher(self, requete: str, lieux: list[str], contrats: list[str], jours: int,
                   limite: int) -> Iterator[Offre]:
        params = {"app_id": self.app_id, "app_key": self.app_key, "what": requete, "results_per_page": 50,
                  "max_days_old": jours, "sort_by": "date", "content-type": "application/json"}
        if contrats == ["CDI"]:
            params["permanent"] = 1
        elif contrats == ["CDD"]:
            params["contract"] = 1
        for lieu in lieux or ["France"]:
            n, page, attentes = 0, 1, 0
            while n < limite:
                r = self.session.get(self.url.format(page=page), params={**params, "where": lieu}, timeout=30)
                if r.status_code == 429 and attentes < 3:
                    attentes += 1
                    time.sleep(3 * attentes)
                    continue
                r.raise_for_status()
                resultats = r.json().get("results") or []
                for brut in resultats:
                    yield convertir_adzuna(brut)
                    n += 1
                    if n >= limite:
                        break
                if len(resultats) < 50:
                    break
                page += 1
                time.sleep(0.5)


def convertir_adzuna(brut: dict) -> Offre:
    zone = (brut.get("location") or {}).get("area") or []
    contrat = {"permanent": "CDI", "contract": "CDD"}.get(brut.get("contract_type") or "", "")
    titre = texte_brut(brut.get("title") or "")
    if not contrat:
        contrat = normaliser_contrat(titre) or ""
    salaire = ""
    if brut.get("salary_min"):
        salaire = f"{int(brut['salary_min'])} - {int(brut.get('salary_max') or brut['salary_min'])} € / an"
    description = texte_brut(brut.get("description") or "")
    return Offre(
        id=f"adzuna:{brut.get('id')}",
        source="Adzuna",
        titre=titre,
        entreprise=(brut.get("company") or {}).get("display_name") or "",
        description=description,
        url=brut.get("redirect_url") or "",
        email=email_dans_texte(description),
        ville=zone[-1] if zone else (brut.get("location") or {}).get("display_name", ""),
        type_contrat=contrat,
        date_publication=brut.get("created") or "",
        salaire=salaire,
    )


# --------------------------------------------------------------------------- #
# Import manuel (URL ou texte)
# --------------------------------------------------------------------------- #

def _job_posting(html: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            donnees = json.loads(script.string or script.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        candidats = donnees if isinstance(donnees, list) else donnees.get("@graph", [donnees])
        for element in candidats:
            if isinstance(element, dict) and "JobPosting" in str(element.get("@type")):
                return element
    return None


def offre_depuis_html(html: str, url: str) -> Offre:
    """Lit une page d'offre : données schema.org/JobPosting si présentes, sinon titre + texte de la page."""
    jp = _job_posting(html)
    if jp:
        organisation = jp.get("hiringOrganization") or {}
        lieu = jp.get("jobLocation") or {}
        lieu = lieu[0] if isinstance(lieu, list) and lieu else lieu
        adresse = (lieu.get("address") or {}) if isinstance(lieu, dict) else {}
        types = jp.get("employmentType") or ""
        types = types if isinstance(types, list) else [types]
        correspondance = {"FULL_TIME": None, "PART_TIME": None, "CONTRACTOR": "freelance", "TEMPORARY": "CDD",
                          "INTERN": "stage", "PER_DIEM": "interim"}
        contrat = next((correspondance.get(t) or normaliser_contrat(t) for t in types
                        if correspondance.get(t) or normaliser_contrat(t)), None)
        description = texte_brut(jp.get("description") or "")
        titre = jp.get("title") or ""
        offre = Offre(
            id="", source="manuel", titre=titre,
            entreprise=organisation.get("name", "") if isinstance(organisation, dict) else str(organisation),
            description=description, url=url,
            ville=adresse.get("addressLocality", "") if isinstance(adresse, dict) else "",
            code_postal=adresse.get("postalCode", "") if isinstance(adresse, dict) else "",
            type_contrat=contrat or contrat_dans_texte(titre, description),
            date_publication=jp.get("datePosted", ""),
            email=email_dans_texte(description),
        )
    else:
        soup = BeautifulSoup(html, "html.parser")
        titre = (soup.find("h1") or soup.title or soup).get_text(" ").strip()[:200]
        for balise in soup(["script", "style", "noscript", "nav", "footer", "header"]):
            balise.decompose()
        description = re.sub(r"\n\s*\n+", "\n\n", soup.get_text("\n")).strip()[:15000]
        offre = Offre(id="", source="manuel", titre=titre, description=description, url=url,
                      type_contrat=contrat_dans_texte(titre, description), email=email_dans_texte(description))
    offre.departement = offre.code_postal[:2] if offre.code_postal else ""
    offre.id = "manuel:" + hashlib.sha1((url or offre.titre).encode()).hexdigest()[:12]
    return offre


def offre_depuis_url(url: str, navigateur: Navigateur | None = None) -> Offre:
    navigateur = navigateur or Navigateur(delai=0)
    if not navigateur.autorise(url):
        raise ValueError("ce site interdit la lecture automatique de ses pages (robots.txt). Copiez le texte de "
                         "l'offre dans un fichier et utilisez : autopostule offres ajouter --fichier offre.txt")
    page = navigateur.obtenir(url)
    if not page:
        raise ValueError(f"page inaccessible : {url}. Utilisez --fichier avec le texte de l'offre.")
    return offre_depuis_html(page.html, page.url)


def offre_depuis_texte(texte: str, titre: str = "", entreprise: str = "", url: str = "", ville: str = "",
                       email: str = "", contrat: str = "") -> Offre:
    lignes = [ligne.strip() for ligne in texte.splitlines() if ligne.strip()]
    titre = titre or (lignes[0][:200] if lignes else "Offre")
    graine = url or (titre + entreprise + texte[:500])
    return Offre(
        id="manuel:" + hashlib.sha1(graine.encode()).hexdigest()[:12], source="manuel", titre=titre,
        entreprise=entreprise, description=texte, url=url, ville=ville,
        email=(email or email_dans_texte(texte)).lower(),
        type_contrat=normaliser_contrat(contrat) or contrat_dans_texte(titre, texte),
    )


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def zones_france_travail(regions: list[str], departements: list[str]) -> list[tuple[str, str]]:
    if departements:
        return [("departement", d) for d in departements]
    return [("region", r.code) for r in regions_par_code(regions)]


def regions_par_code(codes: list[str]):
    return [r for r in REGIONS.values() if r.code in codes]


def lieux_adzuna(regions: list[str], departements: list[str], villes: list[str]) -> list[str]:
    if villes:
        return villes
    noms = [r.nom for r in regions_par_code(regions)]
    for d in departements:
        noms += [r.nom for r in REGIONS.values() if d in r.departements and r.nom not in noms]
    return noms or ["France"]


def collecter(sources: list, metiers: list[str], regions: list[str], departements: list[str], villes: list[str],
              contrats: list[str], jours: int, limite: int, journal=print) -> list[Offre]:
    """Interroge chaque source pour chaque métier, filtre (pertinence, contrat, ville) et dédoublonne."""
    vues: dict[str, Offre] = {}
    cles: set[str] = set()
    for cle_metier in metiers:
        metier = METIERS[cle_metier]
        for source in sources:
            n_source = 0
            for requete in metier.recherches:
                try:
                    if isinstance(source, SourceFranceTravail):
                        flux = source.rechercher(requete, zones_france_travail(regions, departements), contrats,
                                                 jours, limite)
                    else:
                        flux = source.rechercher(requete, lieux_adzuna(regions, departements, villes), contrats,
                                                 jours, limite)
                    for offre in flux:
                        if offre.id in vues or offre.cle_doublon in cles:
                            continue
                        if not est_pertinente(offre, metier) or not contrat_accepte(offre, contrats):
                            continue
                        if villes and not any(normaliser(v) in normaliser(offre.ville) for v in villes):
                            continue
                        offre.metier = cle_metier
                        vues[offre.id] = offre
                        cles.add(offre.cle_doublon)
                        n_source += 1
                except requests.RequestException as erreur:
                    journal(f"  ! {source.nom} « {requete} » : {erreur}")
            journal(f"  {source.nom:<15} {metier.titre:<28} {n_source} offre(s) retenue(s)")
    return list(vues.values())
