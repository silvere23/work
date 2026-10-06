"""Import des offres reçues par alerte e-mail (Indeed, LinkedIn, Welcome to the Jungle, Monster, Google...).

Ces plateformes interdisent qu'on les parcoure avec un robot, mais elles envoient elles-mêmes les offres par
e-mail à qui crée une alerte. L'outil lit ces e-mails dans la boîte de l'utilisateur (IMAP, en lecture seule)
ou dans des fichiers .eml, et en extrait l'intitulé, l'entreprise, le lieu et le lien de chaque offre.
"""

from __future__ import annotations

import email
import hashlib
import imaplib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from email import policy
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Iterable, Iterator

from bs4 import BeautifulSoup

from .offres import Offre, contrat_dans_texte, email_dans_texte, titre_propre
from .referentiel import METIERS, normaliser

# Expéditeur (domaine) -> plateforme, et motifs d'URL des liens vers une offre.
PLATEFORMES = {
    "Indeed": (("indeed.com", "indeed.fr", "indeedemail.com"), (r"/rc/clk", r"viewjob", r"/pagead/clk", r"[?&]jk=")),
    "LinkedIn": (("linkedin.com",), (r"/jobs/view/", r"/comm/jobs/view/")),
    "Welcome to the Jungle": (("welcometothejungle.com", "wttj.co"), (r"/jobs/",)),
    "Monster": (("monster.fr", "monster.com"), (r"/emploi/", r"job-openings", r"/offre-")),
    "Google": (("google.com",), (r"htl;jobs", r"jobs\.google", r"udm=8")),
    "HelloWork": (("hellowork.com", "regionsjob.com"), (r"/emplois/",)),
    "Apec": (("apec.fr",), (r"detail-offre",)),
    "Glassdoor": (("glassdoor.fr", "glassdoor.com"), (r"jobListing", r"job-listing")),
    "Jobteaser": (("jobteaser.com",), (r"/job-offers/",)),
    "Cadremploi": (("cadremploi.fr",), (r"/emploi/detail_offre",)),
    "France Travail": (("francetravail.fr", "pole-emploi.fr"), (r"/offres/recherche/detail/",)),
}

# Mots signalant un intitulé de poste (lien sans motif d'URL connu, ex. lien de suivi).
MOTS_POSTE = {
    "administrateur", "administratrice", "admin", "ingenieur", "ingenieure", "engineer", "technicien",
    "technicienne", "developpeur", "developpeuse", "developer", "devops", "sre", "cloud", "reseau", "reseaux",
    "systeme", "systemes", "network", "system", "support", "helpdesk", "analyste", "consultant", "consultante",
    "architecte", "securite", "cybersecurite", "soc", "chef de projet", "responsable", "it", "informatique",
    "infrastructure", "exploitation", "integrateur", "data", "alternance", "stage", "stagiaire",
}
LIENS_IGNORES = re.compile(
    r"d[ée]sabonn|unsubscribe|param[eè]tres|settings|pr[ée]f[ée]rences|voir (toutes|plus|tous)|see all|"
    r"view all|t[ée]l[ée]charg|download|app store|google play|confidentialit|privacy|aide|help|"
    r"mon compte|my account|modifier (l'|cette )?alerte|manage|g[ée]rer|cr[ée]er une alerte", re.I)
LIGNES_IGNOREES = re.compile(
    r"^(nouveau|new|candidature simplifi|easy apply|postuler|apply|il y a|publi[ée]e?|actively|"
    r"promu|promoted|sponsoris|\d+ (candidat|applicant)|r[ée]pond|voir|view|see)|€|\$|k€|/an|/mois|par an", re.I)
MOIS_IMAP = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass
class ResultatAlertes:
    messages: int
    offres: list[Offre]


def plateforme_de(expediteur: str) -> str | None:
    domaine = parseaddr(expediteur or "")[1].rsplit("@", 1)[-1].lower()
    for nom, (domaines, _) in PLATEFORMES.items():
        if any(domaine == d or domaine.endswith("." + d) for d in domaines):
            return nom
    return None


def _ressemble_a_un_poste(texte: str) -> bool:
    mots = set(re.split(r"[^a-z0-9]+", normaliser(texte)))
    if "chef" in mots and "projet" in mots:
        return True
    return bool(mots & MOTS_POSTE) or any(f" {normaliser(m)}" in f" {normaliser(texte)}"
                                          for metier in METIERS.values() for m in metier.intitules)


def _lignes(element) -> list[str]:
    return [" ".join(l.split()) for l in element.get_text("\n").split("\n") if l.strip()]


def extraire_offres(html: str, plateforme: str, date: str = "") -> list[Offre]:
    """Offres présentes dans le HTML d'un e-mail d'alerte."""
    soup = BeautifulSoup(html or "", "html.parser")
    motifs = PLATEFORMES.get(plateforme, ((), ()))[1]
    offres: dict[str, Offre] = {}
    for lien in soup.find_all("a", href=True):
        url = lien["href"].strip()
        titre = " ".join(lien.get_text(" ").split())
        if not url.startswith("http") or not (8 <= len(titre) <= 140) or LIENS_IGNORES.search(titre):
            continue
        connu = any(re.search(m, url, re.I) for m in motifs)
        if not connu and not _ressemble_a_un_poste(titre):
            continue
        # le bloc qui entoure le lien contient en général : intitulé, entreprise, lieu
        bloc = lien
        for _ in range(6):
            if bloc.parent is None:
                break
            bloc = bloc.parent
            if len(" ".join(_lignes(bloc))) > len(titre) + 8:
                break
        toutes = [l for l in _lignes(bloc) if l != titre]
        if len(" ".join(toutes)) > 600:  # bloc trop large (tout l'e-mail) : pas de contexte fiable
            toutes = []
        lignes = [l for l in toutes if not LIGNES_IGNOREES.search(l) and len(l) <= 80]
        entreprise = lignes[0] if lignes else ""
        ville = lignes[1] if len(lignes) > 1 else ""
        if " · " in entreprise and not ville:
            entreprise, _, ville = entreprise.partition(" · ")
        if " - " in entreprise and not ville and len(entreprise.split(" - ")) == 2:
            entreprise, ville = (x.strip() for x in entreprise.split(" - "))
        contexte = " ".join(lignes[:4])
        cle = normaliser(f"{titre_propre(titre)}|{entreprise}")
        if cle in offres:
            continue
        offres[cle] = Offre(
            id="alerte:" + hashlib.sha1(f"{plateforme}|{cle}|{normaliser(ville)}".encode()).hexdigest()[:12],
            source=f"Alerte {plateforme}",
            titre=titre,
            entreprise=entreprise,
            description=f"{titre}\n{contexte}".strip(),
            url=url,
            ville=re.sub(r"\s*\(.*?\)\s*$", "", ville),
            email=email_dans_texte(contexte),
            type_contrat=contrat_dans_texte(titre, " ".join(toutes)),
            date_publication=date,
        )
    return list(offres.values())


def offres_du_message(message: email.message.EmailMessage) -> list[Offre]:
    plateforme = plateforme_de(message.get("From", ""))
    if not plateforme:
        return []
    corps = message.get_body(preferencelist=("html", "plain"))
    if corps is None:
        return []
    contenu = corps.get_content()
    if corps.get_content_type() == "text/plain":  # pas de HTML : liens bruts « Intitulé \n https://... »
        contenu = re.sub(r"(?m)^(.+)\n\s*(https?://\S+)", r'<p><a href="\2">\1</a></p>', contenu)
    date = ""
    if message.get("Date"):
        try:
            date = parsedate_to_datetime(message["Date"]).isoformat()
        except (TypeError, ValueError):
            pass
    return extraire_offres(contenu, plateforme, date)


def lire_fichiers(chemins: Iterable[Path]) -> ResultatAlertes:
    offres, n = [], 0
    for chemin in chemins:
        message = email.message_from_bytes(Path(chemin).read_bytes(), policy=policy.default)
        n += 1
        offres += offres_du_message(message)
    return ResultatAlertes(n, offres)


def date_imap(jour: datetime) -> str:
    return f"{jour.day:02d}-{MOIS_IMAP[jour.month - 1]}-{jour.year}"


def lire_boite(hote: str, utilisateur: str, mot_de_passe: str, jours: int = 7, dossier: str = "INBOX",
               port: int = 993) -> ResultatAlertes:
    """Lit (sans rien modifier) les alertes des plateformes connues reçues ces derniers jours."""
    depuis = date_imap(datetime.now() - timedelta(days=jours))
    numeros: set[bytes] = set()
    with imaplib.IMAP4_SSL(hote, port) as imap:
        imap.login(utilisateur, mot_de_passe)
        imap.select(f'"{dossier}"', readonly=True)
        for domaines, _ in PLATEFORMES.values():
            for domaine in domaines:
                statut, donnees = imap.search(None, "SINCE", depuis, "FROM", f'"{domaine}"')
                if statut == "OK" and donnees and donnees[0]:
                    numeros.update(donnees[0].split())
        offres: list[Offre] = []
        for numero in sorted(numeros, key=int):
            statut, donnees = imap.fetch(numero, "(BODY.PEEK[])")
            if statut != "OK":
                continue
            brut = next((d[1] for d in donnees if isinstance(d, tuple)), None)
            if brut:
                offres += offres_du_message(email.message_from_bytes(brut, policy=policy.default))
    return ResultatAlertes(len(numeros), offres)


def hote_imap(config) -> str:
    """imap.gmail.com pour smtp.gmail.com, etc. (modifiable : offres.alertes.imap_hote)."""
    reglage = (config["offres"].get("alertes") or {}).get("imap_hote")
    if reglage:
        return reglage
    smtp = config["envoi"].get("smtp_hote") or ""
    if smtp.startswith("smtp."):
        return "imap." + smtp[5:]
    if smtp == "smtp-mail.outlook.com":
        return "outlook.office365.com"
    return smtp.replace("smtp", "imap") or "imap.gmail.com"


def iterer(offres: list[Offre]) -> Iterator[Offre]:
    vues: set[str] = set()
    for offre in offres:
        if offre.id not in vues:
            vues.add(offre.id)
            yield offre
