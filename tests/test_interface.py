"""Interface web : parcours complet avec le client de test Flask (sans réseau)."""

import io
import re

import pytest

from autopostule import envoi
from autopostule import interface as ui
from autopostule.cv_adapte import EXEMPLE_CV
from autopostule.interface.taches import Gestionnaire
from autopostule.stockage import Base

OFFRE = """Ingénieur DevOps H/F
Cloudy recrute en CDI un ingénieur DevOps.
Environnement : Linux, Docker, Kubernetes, Ansible, GitLab CI, Terraform.
Envoyez votre candidature à talents@cloudy.io"""


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "FICHIER_PREFERENCES", tmp_path / "prefs.json")
    for var in ui.SECRETS:
        monkeypatch.delenv(var, raising=False)
    gestionnaire = Gestionnaire()
    app = ui.creer_app(None, gestionnaire)
    app.config["TESTING"] = True
    c = app.test_client()
    c.jeton = app.config["JETON"]
    c.gestionnaire = gestionnaire
    c.dossier = tmp_path / "travail"
    return c


def poster(client, url, donnees=None, **kwargs):
    return client.post(url, data={"_jeton": client.jeton, **(donnees or {})}, **kwargs)


def attendre_tache(client, reponse):
    assert reponse.status_code == 302 and "/taches/" in reponse.location
    tache = client.gestionnaire.courante
    client.gestionnaire.attendre(tache)
    return tache


PROFIL = {
    "prenom": "Silvère", "nom": "Tchoudji", "genre": "M", "email": "silvere@mail.fr", "telephone": "07 50 00 19 16",
    "ville": "Cergy", "code_postal": "95000", "titre": "Administrateur systèmes", "annees_experience": "3",
    "disponibilite": "immédiatement", "metiers": ["devops", "administrateur_systeme"],
    "types_contrat": ["CDI", "CDD"], "regions": ["ile-de-france"], "effectif_min": "10", "effectif_max": "249",
    "publiees_depuis_jours": "7", "smtp_hote": "smtp.gmail.com", "smtp_port": "587", "securite": "starttls",
    "smtp_utilisateur": "silvere@mail.fr", "max_par_jour": "40", "validation_manuelle": "on",
    "chercher_email_rh": "on", "AUTOPOSTULE_SMTP_PASSWORD": "secret-app",
}


def test_parcours_interface(client, monkeypatch):
    # sans dossier : redirection vers le choix du dossier
    r = client.get("/")
    assert r.status_code == 302 and r.location.endswith("/dossier")
    assert "Dossier de travail" in client.get("/dossier").get_data(as_text=True)
    assert poster(client, "/dossier", {"chemin": str(client.dossier)}).status_code == 302
    assert (client.dossier / "config.yaml").exists() and (client.dossier / ".env").exists()

    # tableau de bord : alertes de démarrage
    page = client.get("/").get_data(as_text=True)
    assert "Profil incomplet" in page and "Aucun CV" in page and "Aucune source d" in page

    # profil + import du CV + secret
    cv = io.BytesIO("Silvère Tchoudji - Linux, Docker, Kubernetes, Ansible, Windows Server, GLPI".encode())
    r = poster(client, "/profil", {**PROFIL, "cv_fichier": (cv, "mon CV.txt")},
               content_type="multipart/form-data")
    assert r.status_code == 302
    page = client.get("/profil").get_data(as_text=True)
    assert 'value="Silvère"' in page and "renseigné" in page and "secret-app" not in page
    assert "AUTOPOSTULE_SMTP_PASSWORD=secret-app" in (client.dossier / ".env").read_text(encoding="utf-8")
    assert "Docker" in client.get("/cv-analyse").get_data(as_text=True)

    # CV structuré : création, puis remplacement de l'exemple par un vrai parcours
    poster(client, "/cv", {"action": "creer"})
    assert "parcours d'exemple" in client.get("/cv").get_data(as_text=True)
    vrai = EXEMPLE_CV.read_text(encoding="utf-8").replace("Entreprise A", "Nordis").replace(
        "Entreprise B", "Helpline").replace("Lycée Exemple", "Lycée Baggio")
    poster(client, "/cv", {"action": "enregistrer", "texte": vrai})
    assert "parcours d'exemple" not in client.get("/cv").get_data(as_text=True)
    assert poster(client, "/cv", {"action": "enregistrer", "texte": "a: [b"}).status_code == 200  # refusé
    apercu = poster(client, "/cv/apercu", {"titre": "Ingénieur DevOps", "mots": "Ansible, Linux"})
    assert apercu.data.startswith(b"%PDF")

    # offre copiée depuis LinkedIn
    r = poster(client, "/offres/ajouter", {"texte": OFFRE, "entreprise": "Cloudy", "ville": "Paris"})
    assert r.status_code == 302 and "/offres/manuel:" in r.location
    page = client.get(r.location).get_data(as_text=True)
    assert "Ingénieur DevOps" in page and "Kubernetes" in page and "Terraform" in page  # absente du CV

    # préparation (tâche de fond) -> candidature avec CV adapté
    tache = attendre_tache(client, poster(client, "/offres/preparer"))
    assert tache.etat == "terminee", tache.lignes
    b = Base(client.dossier / "donnees" / "autopostule.db")
    (c,) = b.candidatures()
    assert c["email"] == "talents@cloudy.io" and c["cv_pdf"]
    page = client.get(f"/candidatures/{c['id']}").get_data(as_text=True)
    assert "Candidature" in page and "Silvère" in page and "CV adapté (PDF)" in page
    assert client.get("/fichier", query_string={"chemin": c["cv_pdf"]}).data.startswith(b"%PDF")

    # approbation puis envoi d'essai et envoi réel (faux SMTP)
    poster(client, "/candidatures/action", {"action": "approuver", "ids": [str(c["id"])]})
    assert b.candidature(c["id"])["statut"] == "approuvee"
    tache = attendre_tache(client, poster(client, "/envoyer", {"mode": "test"}))
    assert any("simulée" in ligne for ligne in tache.lignes)
    envoyes = []

    class FauxSMTP:
        def __init__(self, *a, **k): pass
        def starttls(self, context=None): pass
        def login(self, utilisateur, mdp): assert mdp == "secret-app"
        def send_message(self, msg): envoyes.append(msg)
        def quit(self): pass

    monkeypatch.setattr(envoi.smtplib, "SMTP", FauxSMTP)
    tache = attendre_tache(client, poster(client, "/envoyer", {"mode": "reel"}))
    assert tache.etat == "terminee" and len(envoyes) == 1
    assert b.candidature(c["id"])["statut"] == "envoyee"

    # toutes les pages s'affichent
    for url in ["/", "/profil", "/cv", "/offres", "/offres?statut=postulee", "/entreprises", "/candidatures",
                "/candidatures?statut=envoyee", f"/taches/{tache.id}", f"/taches/{tache.id}.json"]:
        assert client.get(url).status_code == 200, url


def test_formulaire_sans_jeton_refuse(client):
    poster(client, "/dossier", {"chemin": str(client.dossier)})
    assert client.post("/candidatures/action", data={"action": "approuver_tout"}).status_code == 403
    assert client.post("/envoyer", data={"mode": "reel", "_jeton": "faux"}).status_code == 403


def test_fichier_hors_dossier_interdit(client, tmp_path):
    poster(client, "/dossier", {"chemin": str(client.dossier)})
    secret = tmp_path / "secret.txt"
    secret.write_text("x")
    assert client.get("/fichier", query_string={"chemin": str(secret)}).status_code == 404
    assert client.get("/fichier", query_string={"chemin": str(client.dossier / ".." / "secret.txt")}).status_code == 404


def test_envoi_bloque_si_valeurs_exemple(client):
    poster(client, "/dossier", {"chemin": str(client.dossier)})
    poster(client, "/profil", {**PROFIL, "email": "jean.dupont@example.com"})
    r = poster(client, "/envoyer", {"mode": "reel"})
    assert r.status_code == 302 and r.location.endswith("/profil")
    assert client.gestionnaire.courante is None
    page = client.get("/profil").get_data(as_text=True)
    assert "valeurs d&#39;exemple" in page or "valeurs d'exemple" in page


def test_une_seule_tache_a_la_fois(client):
    import threading

    poster(client, "/dossier", {"chemin": str(client.dossier)})
    feu = threading.Event()
    client.gestionnaire.lancer("longue", lambda: feu.wait(5))
    r = poster(client, "/entreprises/scanner", {}, headers={"Referer": "/entreprises"})
    assert r.status_code == 302
    assert "déjà en cours" in client.get("/entreprises").get_data(as_text=True)
    feu.set()


def test_dossier_existant_conserve(client):
    client.dossier.mkdir(parents=True)
    (client.dossier / "config.yaml").write_text('profil:\n  prenom: "Ancien"\n', encoding="utf-8")
    poster(client, "/dossier", {"chemin": str(client.dossier)})
    assert "Ancien" in (client.dossier / "config.yaml").read_text(encoding="utf-8")
    assert re.search(r"Bonjour\s+Ancien", client.get("/").get_data(as_text=True))
