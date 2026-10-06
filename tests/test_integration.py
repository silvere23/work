"""Tests de bout en bout avec un faux site d'entreprise, une fausse API SIRENE et un faux serveur SMTP."""

import json
import threading
from email import message_from_bytes, policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from autopostule import cli, entreprises, envoi
from autopostule.config import charger
from autopostule.sites import Prospecteur
from autopostule.stockage import Base
from autopostule.web import Navigateur

PAGES = {
    "/robots.txt": "User-agent: *\nDisallow: /prive/\n",
    "/": """<html><head><title>Acme Infra</title></head><body>
            <a href="/nous-rejoindre">Nous rejoindre</a> <a href="/contact">Contact</a>
            <a href="/prive/annuaire">Annuaire</a> <a href="https://ailleurs.example/jobs">Partenaire</a>
            <footer>ACME INFRA SAS - SIREN 123 456 789</footer></body></html>""",
    "/contact": "<p>Écrivez-nous : contact@127.0.0.1.nip.io ou contact [at] acme [dot] test</p>",
    "/nous-rejoindre": '<h1>Carrières</h1><a href="mailto:recrutement@acme.test">recrutement@acme.test</a>'
                       "<p>Responsable : marie.martin@acme.test</p>",
    "/prive/annuaire": "<p>secret@acme.test</p>",
}

REPONSE_API = {
    "results": [
        {"siren": "123456789", "nom_complet": "ACME INFRA SAS", "activite_principale": "62.02A",
         "tranche_effectif_salarie": "12", "categorie_entreprise": "PME", "nature_juridique": "5710",
         "siege": {"adresse": "1 rue du Test 59000 LILLE", "code_postal": "59000", "libelle_commune": "LILLE",
                   "departement": "59", "region": "32"}},
        {"siren": "987654321", "nom_complet": "JEAN MARTIN", "activite_principale": "62.02A",
         "nature_juridique": "1000", "siege": {"libelle_commune": "LILLE", "departement": "59"}},
    ],
    "total_pages": 1,
}


class Gestionnaire(BaseHTTPRequestHandler):
    requetes: list[str] = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        Gestionnaire.requetes.append(self.path)
        chemin = urlsplit(self.path).path
        if chemin == "/search":
            Gestionnaire.parametres_api = parse_qs(urlsplit(self.path).query)
            corps, type_ = json.dumps(REPONSE_API), "application/json"
        elif chemin in PAGES:
            corps = PAGES[chemin]
            type_ = "text/plain" if chemin.endswith(".txt") else "text/html; charset=utf-8"
        else:
            self.send_response(404)
            self.end_headers()
            return
        donnees = corps.encode()
        self.send_response(200)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(donnees)))
        self.end_headers()
        self.wfile.write(donnees)


@pytest.fixture()
def serveur(monkeypatch):
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Gestionnaire)
    fil = threading.Thread(target=httpd.serve_forever, daemon=True)
    fil.start()
    Gestionnaire.requetes = []
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def aligner_domaine(monkeypatch):
    """Le faux site est servi sur 127.0.0.1 mais publie des adresses @acme.test : on les considère identiques."""
    from autopostule import emails

    origine = emails.domaine_racine
    monkeypatch.setattr(emails, "domaine_racine",
                        lambda h: "acme.test" if h.startswith("127.0.0.1") else origine(h))


def test_exploration_site(serveur):
    prospecteur = Prospecteur(Navigateur(delai=0), pages_max=8)
    # le domaine des adresses (acme.test) diffère de l'hôte de test : on vérifie la logique d'exploration
    emails, pages = prospecteur.explorer(serveur + "/")
    assert pages >= 2
    assert "/prive/annuaire" not in Gestionnaire.requetes  # robots.txt respecté
    assert not any("ailleurs.example" in r for r in Gestionnaire.requetes)  # pas de liens externes


def test_exploration_classement(serveur, monkeypatch):
    aligner_domaine(monkeypatch)
    prospecteur = Prospecteur(Navigateur(delai=0), pages_max=8)
    emails, _ = prospecteur.explorer(serveur + "/")
    assert emails[0].email == "recrutement@acme.test" and emails[0].type == "rh"
    assert emails[0].source.endswith("/nous-rejoindre")
    assert "secret@acme.test" not in [e.email for e in emails]


class FauxSMTP:
    envoyes: list = []

    def __init__(self, hote, port, timeout=None):
        self.hote = hote

    def starttls(self, context=None):
        pass

    def login(self, utilisateur, mdp):
        assert mdp == "secret"

    def send_message(self, msg):
        FauxSMTP.envoyes.append(msg)

    def quit(self):
        pass


@pytest.fixture()
def projet(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cli.main(["init", str(tmp_path)])
    (tmp_path / "cv" / "mon_cv.txt").write_text(
        "Jean Dupont\nAdministrateur systèmes - Windows Server, Active Directory, VMware, Linux, Docker, Ansible\n",
        encoding="utf-8")
    config = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    config = config.replace('fichier: "cv/mon_cv.pdf"', 'fichier: "cv/mon_cv.txt"')
    config = config.replace("verifier_mx: true", "verifier_mx: false")
    config = config.replace('email: "jean.dupont@example.com"', 'email: "jean.dupont@mail.fr"')
    config = config.replace('telephone: "06 12 34 56 78"', 'telephone: "06 01 02 03 04"')
    config = config.replace("adresse: \"12 rue de l'Exemple\"", 'adresse: "3 rue des Tests"')
    (tmp_path / "config.yaml").write_text(config, encoding="utf-8")
    (tmp_path / ".env").write_text("AUTOPOSTULE_SMTP_PASSWORD=secret\n", encoding="utf-8")
    monkeypatch.setattr(envoi.smtplib, "SMTP", FauxSMTP)
    FauxSMTP.envoyes = []
    return tmp_path


def test_pipeline_complet(projet, serveur, monkeypatch, capsys):
    monkeypatch.setattr(entreprises, "URL_API", serveur + "/search")
    cfg = str(projet / "config.yaml")

    # 1. recherche : l'entrepreneur individuel est écarté
    assert cli.main(["-c", cfg, "rechercher", "-m", "devops", "-r", "hauts-de-france", "-v", "Lille"]) == 0
    assert Gestionnaire.parametres_api["region"] == ["32"]
    base = Base(projet / "donnees" / "autopostule.db")
    assert base.statistiques()["entreprises"] == 1

    # 2. scan : on fournit le site (le faux serveur ne peut pas être « deviné ») et on aligne le domaine
    base.maj_scan("123456789", "a_scanner", serveur + "/", "fourni")
    aligner_domaine(monkeypatch)
    assert cli.main(["-c", cfg, "scanner"]) == 0
    assert base.meilleur_email("123456789")["email"] == "recrutement@acme.test"
    emails = [e["email"] for e in base.emails("123456789")]
    assert "marie.martin@acme.test" not in emails  # nominatif exclu par défaut

    # 3. lettres
    assert cli.main(["-c", cfg, "generer"]) == 0
    brouillons = base.candidatures("brouillon")
    assert len(brouillons) == 1 and brouillons[0]["lettre_pdf"].endswith(".pdf")
    assert "Acme Infra" in brouillons[0]["lettre"]

    # 4. validation manuelle : rien ne part tant que ce n'est pas approuvé
    assert cli.main(["-c", cfg, "envoyer", "--oui"]) == 0
    assert FauxSMTP.envoyes == []

    # 5. mode test : fichier .eml, statut inchangé
    cli.main(["-c", cfg, "approuver", "--tout"])
    assert cli.main(["-c", cfg, "envoyer", "--test"]) == 0
    eml = list((projet / "donnees" / "envois_test").glob("*.eml"))
    assert len(eml) == 1
    msg = message_from_bytes(eml[0].read_bytes(), policy=policy.default)
    assert msg["To"] == "recrutement@acme.test"
    pieces = [p.get_filename() for p in msg.iter_attachments()]
    assert pieces[0] == "CV_jean_dupont.txt" and pieces[1].startswith("Lettre_motivation_")
    assert base.candidatures("approuvee")

    # 6. envoi réel (faux SMTP)
    assert cli.main(["-c", cfg, "envoyer", "--oui"]) == 0
    assert len(FauxSMTP.envoyes) == 1
    assert base.candidatures("envoyee")

    # 7. pas de doublon : une nouvelle génération ne recrée pas de candidature
    cli.main(["-c", cfg, "generer"])
    assert len(base.candidatures()) == 1


def test_plafond_et_exclusions(projet):
    config = charger(projet / "config.yaml")
    config["envoi"]["max_par_jour"] = 2
    base = Base(config.dossier_donnees / "autopostule.db")
    for i in range(4):
        siren = f"00000000{i}"
        base.ajouter_entreprise({"siren": siren, "nom": f"Societe {i}"})
        id_ = base.ajouter_candidature({"siren": siren, "email": f"rh@societe{i}.fr", "metier": "devops",
                                        "objet": "Candidature", "corps": "Bonjour", "lettre": "", "lettre_pdf": None,
                                        "moteur": "modele"})
        base.changer_statut([id_], "approuvee")
    base.exclure("societe0.fr", "a demandé STOP")
    bilan = envoi.envoyer_candidatures(config, base, journal=lambda *_: None, attendre=lambda *_: None)
    assert bilan == {"envoyees": 2, "echecs": 0, "ignorees": 1, "restantes": 1}
    assert [m["To"] for m in FauxSMTP.envoyes] == ["rh@societe1.fr", "rh@societe2.fr"]
    # le plafond du jour est atteint
    bilan = envoi.envoyer_candidatures(config, base, journal=lambda *_: None, attendre=lambda *_: None)
    assert bilan["envoyees"] == 0


def test_moteur_ia_avec_faux_serveur(tmp_path, monkeypatch):
    """Vérifie la requête envoyée à l'API Claude (sans réseau ni clé) et l'intégration de la réponse."""
    anthropic = pytest.importorskip("anthropic")
    from autopostule.config import depuis_dict
    from autopostule.cv import analyser
    from autopostule.entreprises import convertir
    from autopostule.lettre import GenerateurLettres

    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    recu = {}

    class FauxClaude(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            recu["chemin"] = self.path
            recu["entetes"] = dict(self.headers)
            recu["corps"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            reponse = json.dumps({
                "id": "msg_test", "type": "message", "role": "assistant", "model": recu["corps"]["model"],
                "content": [{"type": "text", "text": "Paragraphe personnalisé un.\n\nParagraphe deux."}],
                "stop_reason": "end_turn", "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 10},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(reponse)))
            self.end_headers()
            self.wfile.write(reponse)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FauxClaude)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        cfg = depuis_dict({"profil": {"prenom": "Jean", "nom": "Dupont"}, "lettre": {"moteur": "ia"}}, tmp_path)
        gen = GenerateurLettres(cfg, analyser("Docker Kubernetes Terraform"))
        gen.redacteur.client = anthropic.Anthropic(api_key="test", base_url=f"http://127.0.0.1:{httpd.server_port}",
                                                   max_retries=0)
        lettre = gen.generer(convertir({"siren": "1", "nom_complet": "ACME", "siege": {}}, "devops"), "devops")
    finally:
        httpd.shutdown()

    assert lettre.moteur == "ia"
    assert "Paragraphe personnalisé un." in lettre.lettre
    assert recu["corps"]["model"] == "claude-opus-5-5"
    assert recu["corps"]["thinking"] == {"type": "adaptive"}
    assert recu["corps"]["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in recu["entetes"].get("anthropic-beta", "")
    assert "Docker" in recu["corps"]["messages"][0]["content"]
