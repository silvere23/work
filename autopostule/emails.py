"""Extraction et classement des adresses e-mail publiées sur une page web."""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

RE_EMAIL = re.compile(r"(?<![\w.+-])[a-z0-9][a-z0-9._%+-]*@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,24}(?![\w-])", re.I)

# Obfuscations fréquentes : « jobs [at] societe [dot] fr », « rh(at)societe.fr », « rh @ societe . fr »
RE_OBFUSQUE = re.compile(
    r"([a-z0-9._%+-]+)\s*(?:\[\s*at\s*\]|\(\s*at\s*\)|\{\s*at\s*\}|\s+at\s+|\[\s*arobase\s*\]|\(\s*arobase\s*\)|\s@\s)\s*"
    r"([a-z0-9-]+(?:\s*(?:\.|\[\s*dot\s*\]|\(\s*dot\s*\)|\[\s*point\s*\]|\(\s*point\s*\)|\s+dot\s+)\s*[a-z0-9-]+)+)",
    re.I,
)
RE_POINT_OBFUSQUE = re.compile(r"\s*(?:\[\s*dot\s*\]|\(\s*dot\s*\)|\[\s*point\s*\]|\(\s*point\s*\)|\s+dot\s+)\s*", re.I)

PREFIXES_RH = (
    "recrutement", "recrutements", "recrute", "rh", "drh", "hr", "jobs", "job", "emploi", "emplois",
    "careers", "career", "carriere", "carrieres", "candidature", "candidatures", "candidat", "talent",
    "talents", "hiring", "recruitment", "recruiting", "recrutement.it", "stage", "stages", "alternance",
    "joinus", "join", "rejoindre", "nousrejoindre", "ressources.humaines", "ressourceshumaines", "people",
)
PREFIXES_GENERIQUES = ("contact", "info", "infos", "information", "hello", "bonjour", "accueil", "direction",
                       "secretariat", "agence", "office", "admin", "administration")
PREFIXES_EXCLUS = (
    "noreply", "no-reply", "no_reply", "donotreply", "ne-pas-repondre", "nepasrepondre", "mailer-daemon",
    "postmaster", "abuse", "webmaster", "hostmaster", "dpo", "rgpd", "gdpr", "privacy", "dataprotection",
    "compta", "comptabilite", "facturation", "factures", "facture", "invoice", "invoices", "billing",
    "support", "hotline", "helpdesk", "sav", "newsletter", "unsubscribe", "presse", "press", "media",
    "commercial", "sales", "vente", "ventes", "achats", "fournisseurs", "legal", "juridique", "security",
)
DOMAINES_EXCLUS = (
    "example.com", "example.fr", "exemple.fr", "exemple.com", "domain.com", "domaine.fr", "email.com",
    "sentry.io", "sentry-next.wixpress.com", "wixpress.com", "wix.com", "sentry.wixpress.com",
    "godaddy.com", "w3.org", "schema.org", "googleapis.com", "cloudflare.com", "jquery.com",
)
DOMAINES_WEBMAIL = ("gmail.com", "yahoo.fr", "yahoo.com", "hotmail.fr", "hotmail.com", "outlook.fr",
                    "outlook.com", "orange.fr", "wanadoo.fr", "free.fr", "sfr.fr", "laposte.net", "live.fr",
                    "icloud.com", "protonmail.com", "gmx.fr")
EXTENSIONS_FICHIERS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js", ".ico", ".pdf")

RE_NOMINATIF = re.compile(r"^[a-z]+[._-][a-z]+(?:[._-][a-z]+)?$|^[a-z]\.?[a-z]{3,}$")


@dataclass(frozen=True)
class EmailTrouve:
    email: str
    type: str      # rh | generique | nominatif | autre
    score: int
    source: str


def decoder_cfemail(code: str) -> str:
    """Décode la protection d'adresse e-mail de Cloudflare (attribut data-cfemail)."""
    try:
        cle = int(code[:2], 16)
        return "".join(chr(int(code[i:i + 2], 16) ^ cle) for i in range(2, len(code), 2))
    except ValueError:
        return ""


def extraire_adresses(html: str) -> set[str]:
    """Toutes les adresses présentes dans un document HTML (mailto, texte, obfuscations, Cloudflare)."""
    soup = BeautifulSoup(html, "html.parser")
    adresses: set[str] = set()

    for lien in soup.select("a[href^='mailto:'], a[href^='MAILTO:']"):
        cible = html_lib.unescape(lien.get("href", ""))[7:].split("?")[0]
        for morceau in cible.split(","):
            adresses.update(RE_EMAIL.findall(morceau))

    for element in soup.select("[data-cfemail]"):
        adresses.update(RE_EMAIL.findall(decoder_cfemail(element.get("data-cfemail", ""))))
    for lien in soup.select("a[href*='/cdn-cgi/l/email-protection#']"):
        adresses.update(RE_EMAIL.findall(decoder_cfemail(lien["href"].split("#", 1)[1])))

    for balise in soup(["script", "style", "noscript"]):
        balise.decompose()
    texte = soup.get_text(" ")
    adresses.update(RE_EMAIL.findall(texte))
    for local, domaine in RE_OBFUSQUE.findall(texte):
        candidat = f"{local}@{RE_POINT_OBFUSQUE.sub('.', domaine).replace(' ', '')}"
        if RE_EMAIL.fullmatch(candidat):
            adresses.add(candidat)

    propres = {a.strip(".").lower() for a in adresses}
    return {a for a in propres if not a.endswith(EXTENSIONS_FICHIERS)}


def domaine_racine(hote: str) -> str:
    """'www.carrieres.societe.fr' -> 'societe.fr' (approximation suffisante pour les .fr/.com)."""
    hote = hote.lower().split(":")[0]
    if hote.startswith("www."):
        hote = hote[4:]
    morceaux = hote.split(".")
    if len(morceaux) >= 3 and morceaux[-2] in {"co", "com", "gouv", "asso"}:
        return ".".join(morceaux[-3:])
    return ".".join(morceaux[-2:])


def classer(email: str, domaine_site: str | None = None, page_recrutement: bool = False) -> EmailTrouve | None:
    """Attribue un type et un score à une adresse, ou None si elle doit être ignorée."""
    email = email.lower()
    if "@" not in email:
        return None
    local, domaine = email.rsplit("@", 1)
    if email.endswith(EXTENSIONS_FICHIERS) or domaine in DOMAINES_EXCLUS or domaine.endswith(".wixpress.com"):
        return None
    local_base = local.split("+")[0]
    if any(local_base == p or local_base.startswith(p + ".") or local_base.startswith(p + "-")
           for p in PREFIXES_EXCLUS):
        return None
    if re.fullmatch(r"[0-9a-f]{16,}", local_base):  # identifiants techniques
        return None

    meme_domaine = bool(domaine_site) and domaine_racine(domaine) == domaine_racine(domaine_site)
    webmail = domaine in DOMAINES_WEBMAIL
    if domaine_site and not meme_domaine and not webmail:
        return None  # adresse d'un tiers (agence web, partenaire...)

    compact = local_base.replace("-", "").replace("_", "")
    if any(local_base == p or compact == p.replace(".", "") or local_base.startswith(p + ".")
           or local_base.startswith(p + "-") or local_base.endswith("." + p) or local_base.endswith("-" + p)
           for p in PREFIXES_RH):
        type_, score = "rh", 100
    elif local_base in PREFIXES_GENERIQUES:
        type_, score = "generique", 60
    elif RE_NOMINATIF.match(local_base):
        type_, score = "nominatif", 40
    else:
        type_, score = "autre", 30

    if page_recrutement:
        score += 15
    if webmail:
        score -= 20
    return EmailTrouve(email=email, type=type_, score=score, source="")
