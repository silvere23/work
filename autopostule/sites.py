"""Découverte du site web d'une entreprise et recherche des adresses de contact RH sur ce site."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .emails import EmailTrouve, classer, domaine_racine, extraire_adresses
from .referentiel import normaliser
from .web import Navigateur, Page

FORMES_JURIDIQUES = {
    "sas", "sasu", "sarl", "eurl", "sa", "sca", "snc", "sci", "selarl", "scop", "groupe", "group",
    "france", "societe", "ste", "et", "de", "du", "des", "la", "le", "les", "l", "d",
}

MOTS_PAGES_UTILES = (
    "recrutement", "recrute", "carriere", "career", "jobs", "emploi", "rejoindre", "join", "talent",
    "candidature", "offres", "contact", "mentions", "legal", "a-propos", "about", "equipe", "qui-sommes",
)
MOTS_PAGES_RECRUTEMENT = ("recrut", "carriere", "career", "job", "emploi", "rejoindre", "join", "talent",
                          "candidat", "offre")
CHEMINS_PROBABLES = ("/contact", "/recrutement", "/carrieres", "/nous-rejoindre", "/mentions-legales",
                     "/contact/", "/jobs", "/careers")


def slugs_candidats(nom: str) -> list[str]:
    """Noms de domaine plausibles à partir de la raison sociale."""
    nom = re.sub(r"\(.*?\)", " ", nom)
    mots = [m for m in re.split(r"[^a-z0-9]+", normaliser(nom)) if m]
    utiles = [m for m in mots if m not in FORMES_JURIDIQUES] or mots
    candidats = ["".join(utiles), "-".join(utiles)]
    if len(utiles) > 1:
        candidats.append(utiles[0])
        candidats.append("".join(utiles[:2]))
    if len(utiles) > 2:
        candidats.append("".join(m[0] for m in utiles))  # sigle
    return [c for c in dict.fromkeys(candidats) if 2 < len(c) <= 63]


# Mots trop génériques pour identifier une entreprise à eux seuls (« informatique.com » n'est pas « Informatique Conseil »).
MOTS_GENERIQUES = {
    "informatique", "services", "service", "solutions", "solution", "conseil", "conseils", "systemes", "systeme",
    "technologies", "technology", "tech", "digital", "numerique", "data", "cloud", "network", "networks",
    "reseau", "reseaux", "consulting", "group", "international", "europe", "software", "logiciels", "telecom",
    "web", "net", "info", "infra", "it", "ingenierie", "engineering", "partners", "partenaires", "global",
}


def verifier_site(page: Page, nom: str, siren: str) -> str | None:
    """Confiance que la page appartient bien à l'entreprise : 'siren', 'nom', 'domaine', 'marque' ou None.

    - siren   : le SIREN figure sur la page (preuve la plus forte) ;
    - nom     : tous les mots distinctifs du nom sont dans le titre / l'en-tête ;
    - domaine : le domaine est exactement le nom de l'entreprise (mcabureautique.fr) et le titre en cite un mot ;
    - marque  : le domaine est le premier mot du nom, distinctif (oracle.com pour « Oracle Global Services »),
                et ce mot est dans le titre.
    """
    texte = page.html
    # SIREN écrit « 123456789 », « 123 456 789 » ou inclus dans un SIRET / n° de TVA (FR12 123456789)
    if siren and re.search(r"(?<!\d)" + r"[\s. ]?".join(siren) + r"(?:[\s. ]?\d{5})?(?!\d)", texte):
        return "siren"
    soup = BeautifulSoup(texte, "html.parser")
    titre = normaliser(soup.title.get_text() if soup.title else "")
    entete = normaliser(" ".join(t.get_text(" ") for t in soup.find_all(["h1", "header", "footer"])[:6]))
    mots = [m for m in re.split(r"[^a-z0-9]+", normaliser(nom)) if m and m not in FORMES_JURIDIQUES]
    if mots and all(m in titre or m in entete for m in mots):
        return "nom"
    if mots:
        etiquette = domaine_racine(urlsplit(page.url).netloc).split(".")[0]
        visible = f"{titre} {entete}"
        if etiquette in {"".join(mots), "-".join(mots)} and any(m in visible for m in mots):
            return "domaine"
        premier = mots[0]
        if etiquette == premier and len(premier) >= 5 and premier not in MOTS_GENERIQUES and premier in titre:
            return "marque"
    return None


@dataclass
class ResultatScan:
    site: str | None = None
    confiance: str | None = None
    emails: list[EmailTrouve] = field(default_factory=list)
    pages_visitees: int = 0


class Prospecteur:
    def __init__(self, navigateur: Navigateur, tlds: list[str] | tuple[str, ...] = (".fr", ".com"),
                 pages_max: int = 8):
        self.nav = navigateur
        self.tlds = tlds
        self.pages_max = pages_max

    # -- site web ----------------------------------------------------------- #

    def trouver_site(self, nom: str, siren: str) -> tuple[str | None, str | None, Page | None]:
        for slug in slugs_candidats(nom):
            for tld in self.tlds:
                for prefixe in ("https://www.", "https://"):
                    url = f"{prefixe}{slug}{tld}/"
                    page = self.nav.obtenir(url)
                    if not page:
                        continue
                    confiance = verifier_site(page, nom, siren)
                    if not confiance:
                        # le SIREN figure souvent dans les mentions légales plutôt qu'en page d'accueil
                        mentions = self._page_mentions(page)
                        if mentions and verifier_site(mentions, nom, siren) == "siren":
                            confiance = "siren"
                    if confiance:
                        return self._racine(page.url), confiance, page
                    break  # le domaine répond mais ne correspond pas : inutile d'essayer sans « www. »
        return None, None, None

    def _page_mentions(self, accueil: Page) -> Page | None:
        for lien in self._liens(accueil):
            if "mention" in lien or "legal" in lien:
                return self.nav.obtenir(lien)
        return None

    @staticmethod
    def _racine(url: str) -> str:
        p = urlsplit(url)
        return f"{p.scheme}://{p.netloc}/"

    # -- exploration -------------------------------------------------------- #

    def _liens(self, page: Page) -> list[str]:
        soup = BeautifulSoup(page.html, "html.parser")
        hote = urlsplit(page.url).netloc
        liens: list[str] = []
        for a in soup.find_all("a", href=True):
            url = urljoin(page.url, a["href"]).split("#")[0]
            if urlsplit(url).scheme not in ("http", "https"):
                continue
            if domaine_racine(urlsplit(url).netloc) != domaine_racine(hote):
                continue
            libelle = normaliser(a.get_text(" ") + " " + url)
            if any(mot in libelle.replace(" ", "-") for mot in MOTS_PAGES_UTILES):
                liens.append(url)
        # pages de recrutement en premier
        liens.sort(key=lambda u: 0 if any(m in u.lower() for m in MOTS_PAGES_RECRUTEMENT) else 1)
        return list(dict.fromkeys(liens))

    def explorer(self, site: str, accueil: Page | None = None) -> tuple[list[EmailTrouve], int]:
        domaine = urlsplit(site).netloc
        a_visiter: list[str] = []
        vues: set[str] = set()
        trouves: dict[str, EmailTrouve] = {}
        pages = 0

        def traiter(page: Page) -> None:
            nonlocal pages
            pages += 1
            vues.add(page.url.rstrip("/"))
            recrutement = any(m in page.url.lower() for m in MOTS_PAGES_RECRUTEMENT)
            for adresse in extraire_adresses(page.html):
                email = classer(adresse, domaine, page_recrutement=recrutement)
                if email and (adresse not in trouves or trouves[adresse].score < email.score):
                    trouves[adresse] = EmailTrouve(email.email, email.type, email.score, page.url)
            for lien in self._liens(page):
                if lien.rstrip("/") not in vues and lien not in a_visiter:
                    a_visiter.append(lien)

        accueil = accueil or self.nav.obtenir(site)
        if accueil:
            traiter(accueil)
        a_visiter.extend(urljoin(site, c) for c in CHEMINS_PROBABLES)

        while a_visiter and pages < self.pages_max:
            url = a_visiter.pop(0)
            if url.rstrip("/") in vues:
                continue
            vues.add(url.rstrip("/"))
            page = self.nav.obtenir(url)
            if page:
                traiter(page)
            # une adresse RH trouvée sur une page de recrutement suffit
            if any(e.type == "rh" and e.score >= 110 for e in trouves.values()):
                break

        return sorted(trouves.values(), key=lambda e: -e.score), pages

    def scanner(self, nom: str, siren: str, site_connu: str | None = None) -> ResultatScan:
        resultat = ResultatScan()
        accueil = None
        if site_connu:
            resultat.site, resultat.confiance = site_connu, "fourni"
        else:
            resultat.site, resultat.confiance, accueil = self.trouver_site(nom, siren)
        if resultat.site:
            resultat.emails, resultat.pages_visitees = self.explorer(resultat.site, accueil)
        return resultat


def mx_valide(domaine: str) -> bool | None:
    """True/False si le domaine accepte des e-mails ; None si la vérification est impossible."""
    try:
        import dns.resolver
    except ImportError:
        return None
    try:
        return len(dns.resolver.resolve(domaine, "MX", lifetime=5)) > 0
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        return False
    except Exception:
        return None
