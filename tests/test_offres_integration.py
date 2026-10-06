"""Parcours complet « offres » : fausses API France Travail / Adzuna / SIRENE, faux SMTP, via la CLI."""

import json
import threading
from email import message_from_bytes, policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from autopostule import cli, entreprises, envoi, offres
from autopostule.emails import EmailTrouve
from autopostule.sites import Prospecteur, ResultatScan
from autopostule.stockage import Base

OFFRES_FT = [
    {"id": "200AAA", "intitule": "Administrateur systèmes H/F", "typeContrat": "CDI",
     "description": "Windows Server, Active Directory, VMware, Veeam. Postulez à recrutement@nord-info.fr",
     "lieuTravail": {"libelle": "59 - LILLE", "codePostal": "59000"}, "entreprise": {"nom": "NORD INFO"},
     "dateCreation": "2026-10-05T08:00:00Z"},
    {"id": "200BBB", "intitule": "Administrateur systèmes et réseaux (F/H)", "typeContrat": "CDI",
     "description": "Linux, Ansible, Zabbix, Cisco, VLAN.", "lieuTravail": {"libelle": "59 - ROUBAIX"},
     "entreprise": {"nom": "ACME INFRA"}, "dateCreation": "2026-10-04T08:00:00Z"},
    {"id": "200CCC", "intitule": "Administrateur système Linux", "typeContrat": "CDI",
     "description": "Debian, Red Hat, PowerShell, Bash.", "lieuTravail": {"libelle": "62 - LENS"},
     "entreprise": {}, "dateCreation": "2026-10-03T08:00:00Z"},
    {"id": "200DDD", "intitule": "Boulanger H/F", "typeContrat": "CDI", "description": "Pétrissage",
     "lieuTravail": {"libelle": "59 - LILLE"}, "entreprise": {"nom": "PAIN"}},
]
OFFRES_ADZUNA = [  # doublon de 200AAA + une offre en CDD (filtrée car on cherche du CDI)
    {"id": "1", "title": "Administrateur Systèmes (H/F)", "company": {"display_name": "NORD INFO"},
     "location": {"area": ["France", "Hauts-de-France", "LILLE"]}, "contract_type": "permanent",
     "description": "Windows Server", "redirect_url": "https://www.adzuna.fr/land/ad/1"},
    {"id": "2", "title": "Administrateur systèmes", "company": {"display_name": "TEMPO"},
     "location": {"area": ["France", "Lille"]}, "contract_type": "contract",
     "description": "Windows Server, VMware", "redirect_url": "https://www.adzuna.fr/land/ad/2"},
]


class FausseApi(BaseHTTPRequestHandler):
    appels: list = []

    def log_message(self, *args):
        pass

    def _json(self, donnees, statut=200):
        corps = json.dumps(donnees).encode()
        self.send_response(statut)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        FausseApi.appels.append(("POST", self.path, {}))
        self._json({"access_token": "jeton", "expires_in": 1499})

    def do_GET(self):
        url = urlsplit(self.path)
        params = parse_qs(url.query)
        FausseApi.appels.append(("GET", url.path, params, self.headers.get("Authorization")))
        if url.path == "/ft/search":
            debut = int(params["range"][0].split("-")[0])
            self._json({"resultats": OFFRES_FT if debut == 0 else []}, 206)
        elif url.path.startswith("/adzuna/"):
            self._json({"results": OFFRES_ADZUNA if url.path.endswith("/1") else []})
        elif url.path == "/sirene":
            nom = params.get("q", [""])[0]
            resultats = [{"siren": "111222333", "nom_complet": "ACME INFRA", "activite_principale": "62.02A",
                          "siege": {"libelle_commune": "ROUBAIX", "departement": "59"}}] if "ACME" in nom else []
            self._json({"results": resultats, "total_pages": 1})
        else:
            self._json({}, 404)


@pytest.fixture()
def api(monkeypatch):
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FausseApi)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    monkeypatch.setattr(offres, "URL_JETON_FT", base + "/ft/token")
    monkeypatch.setattr(offres, "URL_OFFRES_FT", base + "/ft/search")
    monkeypatch.setattr(offres, "URL_ADZUNA", base + "/adzuna/{page}")
    monkeypatch.setattr(entreprises, "URL_API", base + "/sirene")
    monkeypatch.setattr(offres.time, "sleep", lambda *_: None)
    FausseApi.appels = []
    yield base
    httpd.shutdown()


class FauxSMTP:
    envoyes: list = []

    def __init__(self, *a, **k):
        pass

    def starttls(self, context=None):
        pass

    def login(self, *a):
        pass

    def send_message(self, msg):
        FauxSMTP.envoyes.append(msg)

    def quit(self):
        pass


@pytest.fixture()
def projet(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cli.main(["init", str(tmp_path)])
    (tmp_path / "cv" / "mon_cv.txt").write_text("Jean Dupont - Windows Server, Active Directory, VMware, Linux",
                                                encoding="utf-8")
    config = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    config = config.replace('fichier: "cv/mon_cv.pdf"', 'fichier: "cv/mon_cv.txt"')
    config = config.replace('regions: ["ile-de-france"]', 'regions: ["hauts-de-france"]')
    config = config.replace('email: "jean.dupont@example.com"', 'email: "jean.dupont@mail.fr"')
    config = config.replace('telephone: "06 12 34 56 78"', 'telephone: "06 01 02 03 04"')
    config = config.replace("adresse: \"12 rue de l'Exemple\"", 'adresse: "3 rue des Tests"')
    config = config.replace('ville: "Paris"', 'ville: "Lille"').replace('code_postal: "75011"', 'code_postal: "59000"')
    (tmp_path / "config.yaml").write_text(config, encoding="utf-8")
    (tmp_path / ".env").write_text("AUTOPOSTULE_SMTP_PASSWORD=x\nFRANCE_TRAVAIL_CLIENT_ID=id\n"
                                   "FRANCE_TRAVAIL_CLIENT_SECRET=secret\nADZUNA_APP_ID=a\nADZUNA_APP_KEY=b\n",
                                   encoding="utf-8")
    for var in ("FRANCE_TRAVAIL_CLIENT_ID", "FRANCE_TRAVAIL_CLIENT_SECRET", "ADZUNA_APP_ID", "ADZUNA_APP_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(envoi.smtplib, "SMTP", FauxSMTP)
    monkeypatch.setattr(envoi.time, "sleep", lambda *_: None)  # pas de pause entre deux envois
    FauxSMTP.envoyes = []
    return tmp_path


def test_parcours_offres(projet, api, monkeypatch):
    cfg = str(projet / "config.yaml")
    assert cli.main(["-c", cfg, "cv-structure"]) == 0
    assert (projet / "cv" / "cv.yaml").exists()
    # on utilise le CV structuré d'exemple (parcours complet) pour le test
    from autopostule.cv_adapte import EXEMPLE_CV
    parcours = EXEMPLE_CV.read_text(encoding="utf-8").replace("Entreprise A", "Nordis").replace(
        "Entreprise B", "Helpline").replace("Lycée Exemple", "Lycée Baggio")
    (projet / "cv" / "cv.yaml").write_text(parcours, encoding="utf-8")

    # 1. recherche : CDI uniquement, offres de 7 jours, Hauts-de-France
    assert cli.main(["-c", cfg, "offres", "rechercher", "-m", "sysadmin", "-t", "CDI", "-j", "5"]) == 0
    appels_ft = [a for a in FausseApi.appels if a[1] == "/ft/search"]
    assert appels_ft[0][2]["typeContrat"] == ["CDI"] and appels_ft[0][2]["publieeDepuis"] == ["7"]
    assert appels_ft[0][2]["region"] == ["32"] and appels_ft[0][3] == "Bearer jeton"
    appels_adzuna = [a for a in FausseApi.appels if a[1].startswith("/adzuna/")]
    assert appels_adzuna[0][2]["permanent"] == ["1"] and appels_adzuna[0][2]["where"] == ["Hauts-de-France"]
    base = Base(projet / "donnees" / "autopostule.db")
    ids = {o["id"] for o in base.offres()}
    assert ids == {"ft:200AAA", "ft:200BBB", "ft:200CCC"}  # boulanger hors sujet, doublon et CDD écartés

    # 2. préparation : e-mail de l'offre / e-mail RH retrouvé sur le site / candidature à faire sur le site
    def faux_scan(self, nom, siren, site_connu=None):
        return ResultatScan(site="https://acme-infra.fr/", confiance="siren",
                            emails=[EmailTrouve("jobs@acme-infra.fr", "rh", 115, "https://acme-infra.fr/carrieres")])
    monkeypatch.setattr(Prospecteur, "scanner", faux_scan)
    assert cli.main(["-c", cfg, "offres", "preparer"]) == 0
    statuts = {o["id"]: o["statut"] for o in base.offres()}
    assert statuts == {"ft:200AAA": "preparee", "ft:200BBB": "preparee", "ft:200CCC": "a_postuler_sur_site"}
    destinataires = {c["offre_id"]: c["email"] for c in base.candidatures("brouillon")}
    assert destinataires == {"ft:200AAA": "recrutement@nord-info.fr", "ft:200BBB": "jobs@acme-infra.fr"}
    manuel = base.offre("ft:200CCC")
    fichiers = {p.name for p in (projet / "donnees" / "offres").glob("ft_200ccc/*")}
    assert manuel["dossier"] and "lettre.txt" in fichiers and any(f.startswith("CV_") for f in fichiers)

    # 3. le CV joint est adapté à l'offre
    c = next(c for c in base.candidatures("brouillon") if c["offre_id"] == "ft:200AAA")
    assert c["cv_pdf"].endswith(".pdf") and "nord_info" in c["cv_pdf"]
    assert "réf. 200AAA" in c["objet"] and "Windows Server" in c["lettre"]

    # 4. envoi
    cli.main(["-c", cfg, "approuver", "--tout"])
    assert cli.main(["-c", cfg, "envoyer", "--test"]) == 0
    eml = sorted((projet / "donnees" / "envois_test").glob("*.eml"))
    msg = message_from_bytes(eml[0].read_bytes(), policy=policy.default)
    pieces = [p.get_filename() for p in msg.iter_attachments()]
    assert pieces[0].startswith("CV_jean_dupont_") and pieces[1].startswith("Lettre_motivation_")
    assert cli.main(["-c", cfg, "envoyer", "--oui"]) == 0
    assert len(FauxSMTP.envoyes) == 2
    assert base.offre("ft:200AAA")["statut"] == "postulee"

    # 5. relancer la recherche ne recrée rien
    cli.main(["-c", cfg, "offres", "rechercher", "-m", "sysadmin", "-t", "CDI"])
    cli.main(["-c", cfg, "offres", "preparer"])
    assert len(base.candidatures()) == 2

    # 6. suivi des candidatures déposées à la main
    cli.main(["-c", cfg, "offres", "fait", "ft:200CCC"])
    assert base.offre("ft:200CCC")["statut"] == "postulee_sur_site"


def test_ajout_manuel_depuis_fichier(projet, tmp_path):
    cfg = str(projet / "config.yaml")
    texte = tmp_path / "offre_linkedin.txt"
    texte.write_text("Ingénieur DevOps H/F\nCloudy recrute en CDI.\nDocker, Kubernetes, Terraform, GitLab CI.\n"
                     "Contact : talents@cloudy.io", encoding="utf-8")
    assert cli.main(["-c", cfg, "offres", "ajouter", "--fichier", str(texte), "--entreprise", "Cloudy",
                     "--ville", "Lille"]) == 0
    base = Base(projet / "donnees" / "autopostule.db")
    (offre,) = base.offres()
    assert offre["metier"] == "devops" and offre["email"] == "talents@cloudy.io" and offre["type_contrat"] == "CDI"
    assert cli.main(["-c", cfg, "offres", "preparer"]) == 0
    (c,) = base.candidatures()
    assert c["email"] == "talents@cloudy.io" and "Ingénieur DevOps" in c["objet"]
    assert c["cv_pdf"] is None  # pas de cv.yaml : le CV d'origine sera joint


def test_contrat_invalide(projet, capsys):
    assert cli.main(["-c", str(projet / "config.yaml"), "offres", "rechercher", "-t", "CDX"]) == 2
    assert "Type de contrat inconnu" in capsys.readouterr().err


def test_envoi_bloque_avec_profil_exemple(projet, capsys):
    cfg = projet / "config.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace('email: "jean.dupont@mail.fr"',
                                                           'email: "jean.dupont@example.com"'), encoding="utf-8")
    assert cli.main(["-c", str(cfg), "envoyer", "--oui"]) == 1
    assert "valeurs d'exemple (email)" in capsys.readouterr().out
    assert FauxSMTP.envoyes == []
