"""Jooble et import des alertes e-mail (Indeed, LinkedIn, Welcome to the Jungle, Google...)."""

from email.message import EmailMessage

import pytest

from autopostule import alertes, cli
from autopostule.offres import SourceJooble, convertir_jooble
from autopostule.stockage import Base

# Exemples d'e-mails d'alerte (structure simplifiée, inspirée des formats courants).
LINKEDIN = """<html><body><table>
<tr><td><a href="https://www.linkedin.com/comm/jobs/view/4012345678/?trk=eml">Ingénieur DevOps H/F</a>
  <p>Cloudy</p><p>Paris, Île-de-France (Hybride)</p><p>Candidature simplifiée</p></td></tr>
<tr><td><a href="https://www.linkedin.com/comm/jobs/view/4012345999/">Administrateur systèmes Linux</a>
  <p>Nordis · Lille</p></td></tr>
<tr><td><a href="https://www.linkedin.com/comm/jobs/search/?keywords=devops">Voir toutes les offres</a></td></tr>
<tr><td><a href="https://www.linkedin.com/comm/psettings/email-unsubscribe">Se désabonner</a></td></tr>
</table></body></html>"""

INDEED = """<html><body>
<div><a href="https://cts.indeed.com/v3/H4sIAAAAAAAA_abc">Technicien support informatique N2 (H/F)</a>
  <div>HelpLine Services</div><div>Nanterre (92)</div><div>CDD · 2 400 € par mois</div></div>
<div><a href="https://cts.indeed.com/v3/zzz">Voir plus d'offres</a></div>
</body></html>"""

WTTJ = """<html><body>
<a href="https://www.welcometothejungle.com/fr/companies/cyberseq/jobs/analyste-soc_paris">Analyste SOC - CDI</a>
<span>CyberSeq</span><span>Paris</span>
</body></html>"""

GOOGLE_TEXTE = """Nouvelles offres pour « administrateur réseau »

Administrateur réseau et sécurité
https://www.google.com/search?q=administrateur+reseau&ibp=htl;jobs#htivrt=jobs&htidocid=abc
Réseaux & Co - Lyon
"""


def courriel(expediteur: str, html: str | None = None, texte: str | None = None) -> EmailMessage:
    message = EmailMessage()
    message["From"] = expediteur
    message["To"] = "moi@gmail.com"
    message["Subject"] = "Nouvelles offres d'emploi"
    message["Date"] = "Mon, 05 Oct 2026 08:00:00 +0200"
    if html:
        message.set_content("Version texte")
        message.add_alternative(html, subtype="html")
    else:
        message.set_content(texte)
    return message


def test_plateforme_de():
    assert alertes.plateforme_de("LinkedIn <jobalerts-noreply@linkedin.com>") == "LinkedIn"
    assert alertes.plateforme_de("Indeed <alert@indeed.com>") == "Indeed"
    assert alertes.plateforme_de("Welcome to the Jungle <hello@news.welcometothejungle.com>") == "Welcome to the Jungle"
    assert alertes.plateforme_de("ami@gmail.com") is None


def test_alerte_linkedin():
    offres = alertes.offres_du_message(courriel("jobalerts-noreply@linkedin.com", LINKEDIN))
    assert [o.titre for o in offres] == ["Ingénieur DevOps H/F", "Administrateur systèmes Linux"]
    assert (offres[0].entreprise, offres[0].ville) == ("Cloudy", "Paris, Île-de-France")
    assert (offres[1].entreprise, offres[1].ville) == ("Nordis", "Lille")
    assert offres[0].source == "Alerte LinkedIn" and offres[0].url.startswith("https://www.linkedin.com/comm/jobs/view/")
    assert offres[0].date_publication.startswith("2026-10-05")


def test_alerte_indeed_liens_de_suivi():
    (offre,) = alertes.offres_du_message(courriel("Indeed <alert@indeed.com>", INDEED))
    assert offre.titre.startswith("Technicien support informatique")
    assert (offre.entreprise, offre.ville) == ("HelpLine Services", "Nanterre")
    assert offre.type_contrat == "CDD"


def test_alerte_wttj_et_google_texte():
    (wttj,) = alertes.offres_du_message(courriel("hello@welcometothejungle.com", WTTJ))
    assert wttj.titre == "Analyste SOC - CDI" and wttj.type_contrat == "CDI"
    (google,) = alertes.offres_du_message(courriel("Google <notify-noreply@google.com>", texte=GOOGLE_TEXTE))
    assert google.titre == "Administrateur réseau et sécurité" and "ibp=htl;jobs" in google.url


def test_expediteur_inconnu_ignore():
    assert alertes.offres_du_message(courriel("newsletter@exemple.fr", LINKEDIN)) == []


class FauxIMAP:
    boites: dict = {}

    def __init__(self, hote, port):
        assert hote == "imap.gmail.com" and port == 993

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def login(self, utilisateur, mdp):
        assert (utilisateur, mdp) == ("moi@gmail.com", "app-secret")

    def select(self, dossier, readonly=False):
        assert readonly is True  # jamais de modification de la boîte
        return "OK", [b"2"]

    def search(self, charset, *criteres):
        domaine = criteres[-1].strip('"')
        trouves = [n for n, m in FauxIMAP.boites.items() if domaine in m["From"]]
        return "OK", [b" ".join(trouves)]

    def fetch(self, numero, quoi):
        return "OK", [(b"1 (BODY[] {100}", bytes(FauxIMAP.boites[numero]))]


def test_lire_boite(monkeypatch):
    FauxIMAP.boites = {b"1": courriel("jobalerts-noreply@linkedin.com", LINKEDIN),
                       b"2": courriel("alert@indeed.com", INDEED)}
    monkeypatch.setattr(alertes.imaplib, "IMAP4_SSL", FauxIMAP)
    resultat = alertes.lire_boite("imap.gmail.com", "moi@gmail.com", "app-secret", jours=7)
    assert resultat.messages == 2 and len(resultat.offres) == 3


def test_hote_imap():
    from autopostule.config import depuis_dict

    assert alertes.hote_imap(depuis_dict({"envoi": {"smtp_hote": "smtp.gmail.com"}})) == "imap.gmail.com"
    assert alertes.hote_imap(depuis_dict({"envoi": {"smtp_hote": "smtp-mail.outlook.com"}})) == "outlook.office365.com"
    assert alertes.hote_imap(depuis_dict({"offres": {"alertes": {"imap_hote": "mail.moi.fr"}}})) == "mail.moi.fr"


def test_commande_alertes_fichiers(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cli.main(["init", str(tmp_path)])
    cfg = tmp_path / "config.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace('types_contrat: ["CDI"]', 'types_contrat: ["CDI", "CDD"]'),
                   encoding="utf-8")
    for nom, expediteur, html in [("a.eml", "jobalerts-noreply@linkedin.com", LINKEDIN),
                                  ("b.eml", "alert@indeed.com", INDEED)]:
        (tmp_path / nom).write_bytes(bytes(courriel(expediteur, html)))
    assert cli.main(["-c", str(cfg), "offres", "alertes", "--fichier", "a.eml", "--fichier", "b.eml"]) == 0
    sortie = capsys.readouterr().out
    assert "2 e-mail(s) d'alerte lu(s), 3 offre(s) trouvée(s), 3 nouvelle(s)" in sortie
    base = Base(tmp_path / "donnees" / "autopostule.db")
    metiers = {o["titre"]: o["metier"] for o in base.offres()}
    assert metiers["Ingénieur DevOps H/F"] == "devops"
    assert metiers["Technicien support informatique N2 (H/F)"] == "technicien_informatique"
    # deuxième import : aucun doublon
    cli.main(["-c", str(cfg), "offres", "alertes", "--fichier", "a.eml"])
    assert len(base.offres()) == 3
    # filtre de contrat : CDI seul -> l'offre CDD d'Indeed est écartée
    cli.main(["-c", str(cfg), "offres", "alertes", "--fichier", "b.eml", "-t", "CDI"])
    assert "écartée(s) (type de contrat)" in capsys.readouterr().out


# -- Jooble ---------------------------------------------------------------- #

class Reponse:
    def __init__(self, donnees, statut=200):
        self.donnees, self.status_code = donnees, statut

    def json(self):
        return self.donnees

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class SessionJooble:
    def __init__(self):
        self.appels = []

    def post(self, url, json=None, timeout=None):
        self.appels.append((url, json))
        return Reponse({"totalCount": 2, "jobs": [
            {"id": 77, "title": "<b>DevOps</b> Engineer (H/F)", "company": "Cloudy", "location": "Paris, Île-de-France",
             "snippet": "Kubernetes, Terraform, CDI", "salary": "50k€", "source": "indeed.fr",
             "type": "CDI", "link": "https://jooble.org/desc/77", "updated": "2099-01-01T00:00:00"},
            {"id": 78, "title": "Ancienne offre DevOps", "company": "Old", "location": "Paris",
             "snippet": "", "source": "monster.fr", "link": "https://jooble.org/desc/78", "updated": "2001-01-01T00:00:00"},
        ]})


def test_source_jooble():
    session = SessionJooble()
    offres = list(SourceJooble("cle-test", session=session).rechercher("devops", ["Île-de-France"], ["CDI"], 7, 10))
    assert session.appels[0][0] == "https://jooble.org/api/cle-test"
    assert session.appels[0][1]["keywords"] == "devops" and session.appels[0][1]["location"] == "Île-de-France"
    assert [o.id for o in offres] == ["jooble:77"]  # l'offre trop ancienne est écartée
    o = offres[0]
    assert (o.titre, o.entreprise, o.ville, o.type_contrat) == ("DevOps Engineer (H/F)", "Cloudy", "Paris", "CDI")
    assert o.source == "Jooble (indeed.fr)"


def test_convertir_jooble_contrat_dans_le_texte():
    o = convertir_jooble({"id": 1, "title": "Technicien support", "snippet": "Poste en CDD de 6 mois"})
    assert o.type_contrat == "CDD"


@pytest.mark.parametrize("texte,attendu", [("Administrateur systèmes", True), ("Chef de projet IT", True),
                                           ("Voir toutes les offres", False), ("Boulanger pâtissier", False)])
def test_ressemble_a_un_poste(texte, attendu):
    assert alertes._ressemble_a_un_poste(texte) is attendu or not attendu
