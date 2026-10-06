from datetime import date

import pytest

from autopostule.config import depuis_dict
from autopostule.cv import analyser
from autopostule.emails import classer, decoder_cfemail, domaine_racine, extraire_adresses
from autopostule.entreprises import CriteresRecherche, convertir, garder
from autopostule.lettre import GenerateurLettres, accorder, date_fr, ecrire_pdf, nom_court
from autopostule.referentiel import tranches_a_partir_de, trouver_metier, trouver_region
from autopostule.sites import slugs_candidats, verifier_site
from autopostule.web import Page

CV = """Jean Dupont - Administrateur systèmes et réseaux
jean.dupont@mail.fr - 06 12 34 56 78 - linkedin.com/in/jean-dupont
Compétences : Windows Server, Active Directory, GPO, Linux Debian, VMware vSphere, Proxmox,
PowerShell, Bash, Veeam, Zabbix, Cisco, VLAN, pfSense, Docker, Ansible, GLPI, ITIL.
"""


# -- référentiel ----------------------------------------------------------- #

@pytest.mark.parametrize("valeur,code", [("idf", "11"), ("Hauts de France", "32"), ("hauts-de-france", "32"),
                                         ("PACA", "93"), ("84", "84"), ("Île-de-France", "11")])
def test_trouver_region(valeur, code):
    assert trouver_region(valeur).code == code


def test_region_inconnue():
    with pytest.raises(ValueError):
        trouver_region("atlantide")


@pytest.mark.parametrize("valeur,cle", [("devops", "devops"), ("admin réseau", "administrateur_reseau"),
                                        ("sysadmin", "administrateur_systeme"), ("technicien", "technicien_informatique")])
def test_trouver_metier(valeur, cle):
    assert trouver_metier(valeur).cle == cle


def test_tranches():
    assert tranches_a_partir_de(10)[0] == "11"
    assert "03" not in tranches_a_partir_de(10)
    assert tranches_a_partir_de(0)[0] == "00"


# -- CV -------------------------------------------------------------------- #

def test_analyse_cv():
    a = analyser(CV)
    assert a.email == "jean.dupont@mail.fr"
    assert a.telephone == "06 12 34 56 78"
    assert "linkedin.com/in/jean-dupont" in a.linkedin
    for comp in ("Windows Server", "Active Directory", "VMware", "Proxmox", "Cisco", "Docker"):
        assert comp in a.competences
    assert a.metiers_suggeres[0] == "administrateur_systeme"
    assert a.competences_pour("administrateur_reseau")[:2] == ["Cisco", "VLAN"]


# -- e-mails --------------------------------------------------------------- #

HTML = """
<html><body>
<a href="mailto:recrutement@acme-it.fr?subject=Candidature">Postuler</a>
<p>Contact : contact [at] acme-it [dot] fr</p>
<p>Facturation : compta@acme-it.fr - logo@2x.png</p>
<a class="__cf_email__" data-cfemail="{cf}">[email protected]</a>
<p>Notre agence web : hello@agence-web.com</p>
<script>var x = "tracking@sentry.io";</script>
</body></html>
"""


def _cf(adresse: str, cle: int = 0x42) -> str:
    return f"{cle:02x}" + "".join(f"{ord(c) ^ cle:02x}" for c in adresse)


def test_extraction_emails():
    adresses = extraire_adresses(HTML.format(cf=_cf("jobs@acme-it.fr")))
    assert {"recrutement@acme-it.fr", "contact@acme-it.fr", "compta@acme-it.fr", "jobs@acme-it.fr"} <= adresses
    assert not any(a.endswith(".png") for a in adresses)
    assert "tracking@sentry.io" not in adresses


def test_decoder_cfemail():
    assert decoder_cfemail(_cf("rh@exemple.fr")) == "rh@exemple.fr"


@pytest.mark.parametrize("email,type_", [
    ("recrutement@acme.fr", "rh"), ("rh@acme.fr", "rh"), ("jobs@acme.fr", "rh"), ("careers@acme.fr", "rh"),
    ("recrutement-it@acme.fr", "rh"), ("contact@acme.fr", "generique"), ("jean.dupont@acme.fr", "nominatif"),
])
def test_classement(email, type_):
    assert classer(email, "www.acme.fr").type == type_


@pytest.mark.parametrize("email", ["noreply@acme.fr", "compta@acme.fr", "dpo@acme.fr", "hello@agence-web.com",
                                   "img@2x.png", "support@acme.fr"])
def test_emails_ignores(email):
    assert classer(email, "acme.fr") is None


def test_score_page_recrutement():
    assert classer("rh@acme.fr", "acme.fr", page_recrutement=True).score > classer("rh@acme.fr", "acme.fr").score


def test_domaine_racine():
    assert domaine_racine("www.carrieres.acme.fr") == "acme.fr"
    assert domaine_racine("acme.co.uk") == "acme.co.uk"


# -- entreprises ----------------------------------------------------------- #

BRUT = {
    "siren": "123456789", "nom_complet": "ACME INFRA SERVICES (ACME)", "activite_principale": "62.02A",
    "tranche_effectif_salarie": "12", "categorie_entreprise": "PME", "nature_juridique": "5710",
    "siege": {"adresse": "1 RUE DU TEST 59000 LILLE", "code_postal": "59000", "libelle_commune": "LILLE",
              "departement": "59", "region": "32"},
}


def test_convertir_et_filtrer():
    e = convertir(BRUT, "devops")
    assert e["ville"] == "LILLE" and e["departement"] == "59" and e["metier"] == "devops"
    assert garder(e, [])
    assert garder(e, ["Lille"])
    assert not garder(e, ["Roubaix"])
    assert not garder({**e, "nature_juridique": "1000"}, [])  # entrepreneur individuel


def test_parametres_api():
    c = CriteresRecherche(metier=trouver_metier("devops"), regions=["32"], effectif_min=10)
    p = c.parametres()
    assert "62.01Z" in p["activite_principale"] and p["region"] == "32"
    assert p["tranche_effectif_salarie"].startswith("11")
    c2 = CriteresRecherche(metier=trouver_metier("devops"), regions=["32"], departements=["59"])
    assert "region" not in c2.parametres() and c2.parametres()["departement"] == "59"


# -- sites ----------------------------------------------------------------- #

def test_slugs():
    slugs = slugs_candidats("ACME INFRA SERVICES SAS")
    assert slugs[0] == "acmeinfraservices" and "acme-infra-services" in slugs and "acme" in slugs


def test_verifier_site():
    page = Page("https://acme.fr/", 200, "<title>Accueil</title><footer>SIRET 123 456 789 00012</footer>")
    assert verifier_site(page, "Acme", "123456789") == "siren"
    page = Page("https://acme.fr/", 200, "<title>Acme Infra - infogérance</title>")
    assert verifier_site(page, "ACME INFRA SAS", "999999999") == "nom"
    page = Page("https://acme.fr/", 200, "<title>Boulangerie</title><p>tel 0123456789123</p>")
    assert verifier_site(page, "Acme Infra", "123456789") is None


# -- lettres --------------------------------------------------------------- #

def test_accorder():
    assert accorder("[motivé|motivée|motivé(e)]", "F") == "motivée"
    assert accorder("[motivé|motivée|motivé(e)]", "M") == "motivé"
    assert accorder("[motivé|motivée|motivé(e)]", "") == "motivé(e)"
    assert accorder("[heureux|heureuse]", None) == "heureux/heureuse"


def test_nom_court_et_date():
    assert nom_court("ACME INFRA SERVICES SAS (ACME)") == "Acme Infra Services"
    assert nom_court("IBM FRANCE") == "IBM France"
    assert date_fr(date(2026, 10, 6)) == "6 octobre 2026"


def _config(tmp_path, **lettre):
    return depuis_dict({
        "profil": {"prenom": "Jean", "nom": "Dupont", "genre": "M", "email": "jean@mail.fr",
                   "telephone": "0612345678", "ville": "Lille", "code_postal": "59000", "annees_experience": 3,
                   "titre": "Administrateur systèmes", "type_contrat": "CDI"},
        "lettre": {"moteur": "modele", **lettre},
        "donnees": {"dossier": str(tmp_path / "donnees")},
    }, tmp_path)


def test_generation_lettre(tmp_path):
    gen = GenerateurLettres(_config(tmp_path), analyser(CV))
    entreprise = convertir(BRUT, "administrateur_systeme")
    lettre = gen.generer(entreprise, "administrateur_systeme")
    assert "Acme Infra Services" in lettre.lettre
    assert "Objet : Candidature spontanée - Administrateur systèmes (CDI)" in lettre.lettre
    assert "Windows Server" in lettre.lettre          # compétence issue du CV
    assert "Lille" in lettre.lettre                   # proximité géographique
    assert "[" not in lettre.lettre and "(e)" not in lettre.lettre  # accords résolus (genre M)
    assert "Jean Dupont" in lettre.objet
    assert "ci-joint" in lettre.message
    # deux entreprises différentes => formulations potentiellement différentes, même entreprise => stable
    assert gen.generer(entreprise, "administrateur_systeme").lettre == lettre.lettre


def test_lettre_sans_pdf_met_la_lettre_dans_le_mail(tmp_path):
    gen = GenerateurLettres(_config(tmp_path, joindre_pdf=False), analyser(CV))
    lettre = gen.generer(convertir(BRUT, "devops"), "devops")
    assert lettre.corps.split("\n")[0] in lettre.message


def test_repli_si_ia_indisponible(tmp_path, monkeypatch):
    gen = GenerateurLettres(_config(tmp_path, moteur="ia"), analyser(CV))
    monkeypatch.setattr(gen, "corps_ia", lambda *a: (_ for _ in ()).throw(RuntimeError("pas de clé")))
    lettre = gen.generer(convertir(BRUT, "devops"), "devops")
    assert lettre.moteur == "modele" and "Acme" in lettre.lettre


def test_pdf(tmp_path):
    chemin = ecrire_pdf("Lettre avec accents : é è à ç œ – « test »\n\nDeuxième paragraphe.", tmp_path / "l.pdf")
    assert chemin.read_bytes().startswith(b"%PDF")


def test_pas_de_donnees_fictives_par_defaut(tmp_path):
    cfg = depuis_dict({"profil": {"prenom": "Awa"}}, tmp_path)
    assert cfg.profil["nom"] == "" and cfg.profil["adresse"] == "" and cfg.profil["annees_experience"] == 0
    assert cfg.verifier_profil() == ["nom", "email", "telephone"]


def test_titre_feminin(tmp_path):
    cfg = depuis_dict({"profil": {"prenom": "Awa", "nom": "Diallo", "genre": "F", "annees_experience": 2}}, tmp_path)
    lettre = GenerateurLettres(cfg, analyser("GLPI, ITIL, Intune, support")).generer(
        convertir(BRUT, "technicien_informatique"), "technicien_informatique")
    assert "Technicienne informatique" in lettre.objet
    assert "Forte de 2 ans" in lettre.lettre
    assert "support," not in lettre.lettre  # terme trop vague non cité


def test_elision(tmp_path):
    gen = GenerateurLettres(_config(tmp_path), analyser(CV))
    for siren in range(20):
        lettre = gen.generer({**convertir(BRUT, "devops"), "siren": str(siren), "tranche_effectif": "21"}, "devops")
        assert "de Acme" not in lettre.lettre


def test_config_chemin_windows_mal_echappe(tmp_path):
    from autopostule.config import ErreurConfig, charger

    fichier = tmp_path / "config.yaml"
    fichier.write_text('cv:\n  fichier: "C:\\Users\\moi\\Downloads\\CV.pdf"\n', encoding="utf-8")
    with pytest.raises(ErreurConfig) as erreur:
        charger(fichier)
    assert "ligne 2" in str(erreur.value) and "guillemets simples" in str(erreur.value)
    fichier.write_text("cv:\n  fichier: 'C:\\Users\\moi\\Downloads\\CV silvère.pdf'\n", encoding="utf-8")
    assert charger(fichier)["cv"]["fichier"] == "C:\\Users\\moi\\Downloads\\CV silvère.pdf"


def test_config_ansi_et_bom(tmp_path):
    from autopostule.config import charger

    fichier = tmp_path / "config.yaml"
    fichier.write_bytes("profil:\n  prenom: Silvère\n".encode("cp1252"))
    assert charger(fichier).profil["prenom"] == "Silvère"
    fichier.write_bytes("\ufeffprofil:\n  prenom: Silvère\n".encode("utf-8"))
    assert charger(fichier).profil["prenom"] == "Silvère"
