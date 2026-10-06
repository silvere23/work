"""Offres d'emploi, CV adapté, lettres sur offre, types de contrat."""

import sqlite3

import pytest

from autopostule import cv_adapte
from autopostule.config import contrats_vises, depuis_dict
from autopostule.cv import analyser
from autopostule.lettre import GenerateurLettres
from autopostule.offres import (Offre, contrat_accepte, convertir_adzuna, convertir_france_travail, deduire_metier,
                                est_pertinente, mots_cles, offre_depuis_html, offre_depuis_texte, titre_propre)
from autopostule.referentiel import METIERS, contrats_valides, libelle_contrats, normaliser_contrat
from autopostule.stockage import Base

FT = {
    "id": "190XKZB", "intitule": "Administrateur systèmes et réseaux H/F",
    "description": "Au sein de la DSI vous administrez Windows Server, Active Directory et VMware. "
                   "Connaissances Linux et Ansible appréciées. Kubernetes est un plus.",
    "dateCreation": "2026-10-04T09:12:00.000Z",
    "lieuTravail": {"libelle": "59 - LILLE", "codePostal": "59000"},
    "entreprise": {"nom": "NORD INFOGERANCE"},
    "typeContrat": "CDI", "salaire": {"libelle": "Annuel de 38000 Euros à 42000 Euros"},
    "competences": [{"libelle": "Administrer un serveur Windows Server", "exigence": "E"}],
    "contact": {"courriel": "Pour postuler, utiliser le lien : https://exemple"},
    "origineOffre": {"origine": "1", "urlOrigine": "https://candidat.francetravail.fr/offres/recherche/detail/190XKZB"},
}


# -- types de contrat ------------------------------------------------------ #

@pytest.mark.parametrize("valeur,attendu", [("cdi", "CDI"), ("Contrat à durée déterminée", "CDD"), ("MIS", "interim"),
                                            ("apprentissage", "alternance"), ("Stage", "stage"),
                                            ("freelance", "freelance"), ("permanent", "CDI"), ("n'importe", None)])
def test_normaliser_contrat(valeur, attendu):
    assert normaliser_contrat(valeur) == attendu


def test_contrats_valides_et_libelle():
    assert contrats_valides(["cdi", "CDD", "cdi"]) == ["CDI", "CDD"]
    assert libelle_contrats(["CDI", "CDD"]) == "CDI ou CDD"
    with pytest.raises(ValueError):
        contrats_valides(["CDX"])


def test_contrats_vises(tmp_path):
    assert contrats_vises(depuis_dict({"recherche": {"types_contrat": ["cdd", "interim"]}}, tmp_path)) == ["CDD", "interim"]
    assert contrats_vises(depuis_dict({"recherche": {"types_contrat": "CDI, CDD"}}, tmp_path)) == ["CDI", "CDD"]
    # ancien champ profil.type_contrat toujours pris en compte
    assert contrats_vises(depuis_dict({"profil": {"type_contrat": "alternance"}}, tmp_path)) == ["alternance"]
    assert contrats_vises(depuis_dict({}, tmp_path)) == []


# -- conversion et analyse des offres -------------------------------------- #

def test_titre_propre():
    assert titre_propre("Administrateur Systèmes H/F - CDI") == "Administrateur Systèmes"
    assert titre_propre("Ingénieur DevOps (F/H)") == "Ingénieur DevOps"


def test_convertir_france_travail():
    o = convertir_france_travail(FT)
    assert o.id == "ft:190XKZB" and o.reference == "190XKZB"
    assert (o.ville, o.departement, o.type_contrat) == ("LILLE", "59", "CDI")
    assert o.email == ""  # le champ courriel ne contient pas d'adresse
    assert o.entreprise == "NORD INFOGERANCE" and "38000" in o.salaire
    alternance = convertir_france_travail({**FT, "alternance": True, "contact": {"courriel": "rh@nord.fr"}})
    assert alternance.type_contrat == "alternance" and alternance.email == "rh@nord.fr"
    avec_mail = convertir_france_travail({**FT, "contact": {}, "description": "CV à jobs@nord-info.fr merci"})
    assert avec_mail.email == "jobs@nord-info.fr"


def test_convertir_adzuna():
    o = convertir_adzuna({"id": "42", "title": "<strong>DevOps</strong> Engineer H/F", "contract_type": "permanent",
                          "company": {"display_name": "Cloudy"}, "location": {"area": ["France", "Hauts-de-France", "Lille"]},
                          "redirect_url": "https://www.adzuna.fr/land/ad/42", "description": "Kubernetes, Terraform",
                          "salary_min": 45000, "salary_max": 55000, "created": "2026-10-05T10:00:00Z"})
    assert o.titre == "DevOps Engineer H/F" and o.type_contrat == "CDI" and o.ville == "Lille"
    assert o.salaire.startswith("45000")


def test_offre_depuis_html_jobposting():
    html = """<html><head><script type="application/ld+json">
    {"@context": "https://schema.org", "@type": "JobPosting", "title": "Technicien support N2 (H/F)",
     "description": "<p>Support N2, GLPI, Intune. Candidature : recrutement@helpme.fr</p>",
     "hiringOrganization": {"@type": "Organization", "name": "HelpMe"}, "employmentType": "TEMPORARY",
     "jobLocation": {"@type": "Place", "address": {"addressLocality": "Amiens", "postalCode": "80000"}},
     "datePosted": "2026-10-01"}</script></head><body></body></html>"""
    o = offre_depuis_html(html, "https://helpme.fr/jobs/1")
    assert (o.titre, o.entreprise, o.ville, o.departement) == ("Technicien support N2 (H/F)", "HelpMe", "Amiens", "80")
    assert o.type_contrat == "CDD" and o.email == "recrutement@helpme.fr" and o.id.startswith("manuel:")


def test_offre_depuis_html_sans_donnees_structurees():
    o = offre_depuis_html("<html><title>x</title><h1>Ingénieur réseau CDI</h1><p>Cisco BGP</p></html>", "https://a.fr/o")
    assert o.titre == "Ingénieur réseau CDI" and o.type_contrat == "CDI" and "Cisco" in o.description


def test_mots_cles_et_metier():
    o = convertir_france_travail(FT)
    mots = mots_cles(o)
    assert mots[:3] == ["Windows Server", "Active Directory", "VMware"] or "Windows Server" in mots[:2]
    assert {"Linux", "Ansible", "Kubernetes"} <= set(mots)
    assert deduire_metier(o, ["devops", "administrateur_systeme"])[0] == "administrateur_systeme"
    assert est_pertinente(o, METIERS["administrateur_systeme"])
    hors_sujet = Offre(id="x", source="t", titre="Boulanger H/F", description="Pétrissage et cuisson")
    assert not est_pertinente(hors_sujet, METIERS["devops"])


def test_contrat_accepte():
    o = Offre(id="x", source="t", titre="Admin", type_contrat="CDD")
    assert contrat_accepte(o, ["CDD", "interim"]) and not contrat_accepte(o, ["CDI"]) and contrat_accepte(o, [])
    inconnu = Offre(id="y", source="t", titre="Admin systèmes - CDI")
    assert contrat_accepte(inconnu, ["CDI"]) and not contrat_accepte(inconnu, ["stage"])


def test_offre_depuis_texte():
    o = offre_depuis_texte("Ingénieur DevOps H/F\nEnvoyez votre CV à talents@cloudy.io\nDocker, Kubernetes",
                           entreprise="Cloudy", contrat="cdi")
    assert o.titre == "Ingénieur DevOps H/F" and o.email == "talents@cloudy.io" and o.type_contrat == "CDI"


# -- CV adapté ------------------------------------------------------------- #

def test_cv_adapte():
    cv = cv_adapte.charger(cv_adapte.EXEMPLE_CV)
    mots = mots_cles(convertir_france_travail(FT), cv_adapte.toutes_competences(cv))
    resultat = cv_adapte.adapter(cv, "Administrateur systèmes et réseaux", mots)
    d = resultat.donnees
    assert d["titre"] == "Administrateur systèmes et réseaux"
    assert list(d["competences"])[0] == "Systèmes"
    assert d["competences"]["Systèmes"][:2] == ["Windows Server", "Active Directory"]
    assert "Kubernetes" in resultat.manquantes          # signalé...
    assert "Kubernetes" not in str(d["competences"])    # ...mais jamais ajouté
    assert [e["entreprise"] for e in d["experiences"]] == ["Entreprise A", "Entreprise B"]  # chronologie conservée
    assert "Windows Server" in d["experiences"][0]["missions"][0]
    assert "Atouts pour ce poste" in d["accroche"]
    assert cv["titre"] == "Administrateur systèmes et réseaux" and "Atouts" not in cv["accroche"]  # original intact


def test_cv_adapte_titre_et_pdf(tmp_path):
    cv = cv_adapte.charger(cv_adapte.EXEMPLE_CV)
    resultat = cv_adapte.adapter(cv, "Ingénieur DevOps", ["Ansible", "Bash", "Docker"])
    assert resultat.donnees["titre"] == "Ingénieur DevOps"
    assert list(resultat.donnees["competences"])[0] == "Automatisation"
    garde = cv_adapte.adapter(cv, "Ingénieur DevOps", ["Ansible"], titre_selon_offre=False)
    assert garde.donnees["titre"] == cv["titre"]
    pdf = cv_adapte.ecrire_pdf(resultat.donnees, {"prenom": "Jean", "nom": "Dupont", "email": "j@d.fr"}, tmp_path / "cv.pdf")
    assert pdf.read_bytes().startswith(b"%PDF")


def test_modele_cv_yaml():
    texte = cv_adapte.modele_depuis_analyse(analyser("Docker Kubernetes Terraform GLPI"), {"titre": "DevOps junior"})
    assert "Docker" in texte and "DevOps junior" in texte


# -- lettres --------------------------------------------------------------- #

def _config(tmp_path, **recherche):
    return depuis_dict({
        "profil": {"prenom": "Jean", "nom": "Dupont", "genre": "M", "email": "j@d.fr", "telephone": "0600000000",
                   "ville": "Lille", "code_postal": "59000", "annees_experience": 3, "titre": "Administrateur systèmes"},
        "recherche": recherche, "donnees": {"dossier": str(tmp_path / "donnees")},
    }, tmp_path)


def test_lettre_sur_offre(tmp_path):
    cv = cv_adapte.charger(cv_adapte.EXEMPLE_CV)
    gen = GenerateurLettres(_config(tmp_path, types_contrat=["CDI"]), None, cv_adapte.toutes_competences(cv))
    offre = convertir_france_travail(FT)
    lettre = gen.generer({"siren": None, "nom": offre.entreprise}, "administrateur_systeme",
                         offre=offre.en_dict(), mots_cles=mots_cles(offre, cv_adapte.toutes_competences(cv)))
    assert "Objet : Candidature au poste d'Administrateur systèmes et réseaux - réf. 190XKZB" in lettre.lettre
    assert "réf. 190XKZB" in lettre.objet and "Jean Dupont" in lettre.objet
    assert "Windows Server" in lettre.lettre and "compétences demandées" in lettre.lettre
    assert "Kubernetes" not in lettre.lettre       # absente du CV : jamais revendiquée
    assert "Lille" in lettre.lettre                # proximité
    assert "publiée sur France Travail" in lettre.message and "en CDI" in lettre.message
    assert "spontanée" not in lettre.lettre


def test_lettre_spontanee_types_contrat(tmp_path):
    gen = GenerateurLettres(_config(tmp_path, types_contrat=["CDI", "CDD"]), analyser("Docker Kubernetes"))
    lettre = gen.generer({"siren": "1", "nom": "ACME"}, "devops")
    assert "Candidature spontanée - Ingénieur DevOps (CDI ou CDD)" in lettre.lettre
    assert "en CDI ou CDD" in lettre.message


# -- stockage -------------------------------------------------------------- #

def test_migration_base_existante(tmp_path):
    chemin = tmp_path / "ancienne.db"
    cx = sqlite3.connect(chemin)
    cx.execute("CREATE TABLE candidatures (id INTEGER PRIMARY KEY, siren TEXT, email TEXT, metier TEXT, objet TEXT,"
               " corps TEXT, lettre TEXT, lettre_pdf TEXT, moteur TEXT, statut TEXT, erreur TEXT,"
               " date_creation TEXT, date_envoi TEXT, message_id TEXT)")
    cx.commit()
    cx.close()
    base = Base(chemin)
    colonnes = {ligne[1] for ligne in base.cx.execute("PRAGMA table_info(candidatures)")}
    assert {"offre_id", "cv_pdf"} <= colonnes


def test_offres_dedoublonnage(tmp_path):
    base = Base(tmp_path / "b.db")
    o = convertir_france_travail(FT)
    assert base.ajouter_offre({**o.en_dict(), "cle_doublon": o.cle_doublon})
    meme = Offre(id="adzuna:9", source="Adzuna", titre="Administrateur systèmes et réseaux (F/H)",
                 entreprise="NORD INFOGERANCE", ville="LILLE")
    assert meme.cle_doublon == o.cle_doublon
    assert not base.ajouter_offre({**meme.en_dict(), "cle_doublon": meme.cle_doublon})


def test_lettre_cite_les_missions_du_cv(tmp_path):
    cv = cv_adapte.charger(cv_adapte.EXEMPLE_CV)
    missions = [m for e in cv["experiences"] for m in e["missions"]]
    gen = GenerateurLettres(_config(tmp_path), None, cv_adapte.toutes_competences(cv), missions_cv=missions)
    offre = convertir_france_travail(FT)
    lettre = gen.generer({"nom": offre.entreprise}, "administrateur_systeme", offre=offre.en_dict(),
                         mots_cles=mots_cles(offre, cv_adapte.toutes_competences(cv)))
    assert "administration de 80 serveurs Windows Server" in lettre.lettre   # mission réelle du CV
    assert "en tant qu'administrateur" in lettre.lettre and "poste d'administrateur" in lettre.lettre
