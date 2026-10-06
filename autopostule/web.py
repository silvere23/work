"""Client HTTP « poli » : respect de robots.txt, délai entre requêtes, timeouts, taille max."""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

USER_AGENT = "Mozilla/5.0 (compatible; autopostule/0.1; candidature spontanee)"
TAILLE_MAX = 2_000_000  # octets


@dataclass
class Page:
    url: str
    statut: int
    html: str


def decoder(contenu: bytes, type_contenu: str = "") -> str:
    if "charset=" in type_contenu.lower():
        encodage = type_contenu.lower().split("charset=")[-1].split(";")[0].strip()
        try:
            return contenu.decode(encodage, errors="replace")
        except LookupError:
            pass
    try:
        return contenu.decode("utf-8")
    except UnicodeDecodeError:
        return contenu.decode("cp1252", errors="replace")


class Navigateur:
    def __init__(self, delai: float = 1.5, timeout: float = 15, session: requests.Session | None = None):
        self.delai = delai
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"})
        self._robots: dict[str, RobotFileParser | None] = {}
        self._derniere_requete: dict[str, float] = {}

    def _hote(self, url: str) -> str:
        parties = urlsplit(url)
        return f"{parties.scheme}://{parties.netloc}"

    def _attendre(self, hote: str) -> None:
        ecoule = time.monotonic() - self._derniere_requete.get(hote, 0.0)
        if ecoule < self.delai:
            time.sleep(self.delai - ecoule)
        self._derniere_requete[hote] = time.monotonic()

    def autorise(self, url: str) -> bool:
        hote = self._hote(url)
        if hote not in self._robots:
            parseur: RobotFileParser | None = RobotFileParser()
            try:
                r = self.session.get(hote + "/robots.txt", timeout=self.timeout)
                if r.status_code == 200:
                    parseur.parse(r.text.splitlines())
                elif r.status_code in (401, 403):
                    parseur.disallow_all = True
                else:
                    parseur = None  # pas de robots.txt : tout est autorisé
            except requests.RequestException:
                parseur = None
            self._robots[hote] = parseur
        parseur = self._robots[hote]
        return parseur is None or parseur.can_fetch(USER_AGENT, url)

    def obtenir(self, url: str) -> Page | None:
        """Télécharge une page HTML ; retourne None en cas d'erreur, de refus robots.txt ou de contenu non HTML."""
        if not self.autorise(url):
            return None
        self._attendre(self._hote(url))
        try:
            r = self.session.get(url, timeout=self.timeout, stream=True, allow_redirects=True)
            type_contenu = r.headers.get("Content-Type", "")
            if r.status_code >= 400 or ("html" not in type_contenu and "text" not in type_contenu):
                r.close()
                return None
            contenu = r.raw.read(TAILLE_MAX, decode_content=True)
            r.close()
            return Page(url=r.url, statut=r.status_code, html=decoder(contenu, type_contenu))
        except (requests.RequestException, OSError, LookupError):
            return None
