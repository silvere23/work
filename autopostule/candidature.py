"""Préparation des candidatures : CV adapté + lettre + adresse de destination, pour une offre ou une entreprise."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from . import cv_adapte
from .config import contrats_vises
from .cv import AnalyseCV, analyser_fichier
from .entreprises import ClientRechercheEntreprises
from .envoi import nom_fichier
from .ia import Redacteur
from .lettre import GenerateurLettres, ecrire_pdf
from .offres import Offre, deduire_metier, mots_cles, titre_propre
from .referentiel import METIERS
from .sites import Prospecteur
from .stockage import Base

TYPES_EMAILS_DEFAUT = ("rh", "generique")


@dataclass
class Resultat:
    statut: str              # preparee | a_postuler_sur_site | ignoree
    email: str = ""
    candidature_id: int | None = None
    dossier: Path | None = None
    manquantes: list[str] | None = None


class Atelier:
    def __init__(self, config, base: Base, analyse: AnalyseCV | None = None, journal=print):
        self.config = config
        self.base = base
        self.journal = journal
        if analyse is None:
            try:
                analyse = analyser_fichier(config.fichier_cv)
            except FileNotFoundError:
                journal(f"(CV non trouvé : {config.fichier_cv} - lettres générées sans les compétences du CV)")
        self.analyse = analyse
        self.cv_structure = cv_adapte.charger(config.fichier_cv_structure) if config["cv_adapte"].get("actif") else None
        if self.cv_structure is not None and cv_adapte.est_exemple(self.cv_structure):
            journal(f"⚠ {config.fichier_cv_structure} contient encore le parcours d'exemple (« Entreprise A »...) : "
                    f"il est ignoré pour ne pas envoyer de fausses expériences. Remplacez-le par votre parcours.")
            self.cv_structure = None
        elif config["cv_adapte"].get("actif") and self.cv_structure is None:
            journal(f"(CV structuré absent : {config.fichier_cv_structure} - le CV d'origine sera joint tel quel. "
                    f"Créez-le avec `autopostule cv-structure`.)")
        self.redacteur = Redacteur(config["lettre"].get("modele_ia") or "claude-opus-5-5")
        competences = cv_adapte.toutes_competences(self.cv_structure) if self.cv_structure else []
        missions = [m for e in (self.cv_structure or {}).get("experiences") or [] for m in e.get("missions") or []]
        self.generateur = GenerateurLettres(config, analyse, competences, self.redacteur, missions)
        self.contrats = contrats_vises(config)

    @property
    def competences_cv(self) -> list[str]:
        return list(self.generateur.competences_cv.values())

    # -- CV adapté ---------------------------------------------------------- #

    def cv_pour(self, titre_vise: str, mots: list[str], texte_offre: str, dossier: Path,
                suffixe: str) -> tuple[Path | None, list[str]]:
        if not self.cv_structure:
            return None, []
        reglages = self.config["cv_adapte"]
        accroche = None
        if reglages.get("moteur") == "ia":
            try:
                accroche = cv_adapte.accroche_ia(self.redacteur, self.cv_structure, titre_vise, texte_offre)
            except Exception as erreur:
                self.journal(f"  [IA indisponible pour le CV : {erreur} - accroche d'origine conservée]")
        resultat = cv_adapte.adapter(self.cv_structure, titre_vise, mots,
                                     titre_selon_offre=bool(reglages.get("titre_selon_offre", True)),
                                     accroche=accroche)
        p = self.config.profil
        nom = f"CV_{nom_fichier(p.get('prenom', ''))}_{nom_fichier(p.get('nom', ''))}_{suffixe[:40]}.pdf"
        return cv_adapte.ecrire_pdf(resultat.donnees, p, dossier / nom), resultat.manquantes

    def _lettre_pdf(self, lettre, dossier: Path, suffixe: str) -> str | None:
        if not self.config["lettre"].get("joindre_pdf", True):
            return None
        nom = f"Lettre_motivation_{nom_fichier(self.config.profil.get('nom', ''))}_{suffixe[:40]}.pdf"
        return str(ecrire_pdf(lettre.lettre, dossier / nom))

    # -- candidature spontanée ---------------------------------------------- #

    def preparer_spontanee(self, entreprise: dict, moteur: str | None = None) -> Resultat:
        meilleur = self.base.meilleur_email(entreprise["siren"])
        if not meilleur or self.base.est_exclu(meilleur["email"], entreprise["siren"]):
            return Resultat("ignoree")
        cle_metier = entreprise.get("metier") or self.config["recherche"]["metiers"][0]
        metier = METIERS[cle_metier]
        dossier = self.config.dossier_donnees / "lettres"
        suffixe = nom_fichier(entreprise["nom"])
        lettre = self.generateur.generer(entreprise, cle_metier, moteur, contrats=self.contrats)
        cv_pdf, _ = self.cv_pour(metier.titre_pour(self.config.profil.get("genre")), list(metier.competences),
                                 "", self.config.dossier_donnees / "cv_adaptes", suffixe)
        (dossier / f"{suffixe[:40]}_{entreprise['siren']}.txt").parent.mkdir(parents=True, exist_ok=True)
        (dossier / f"{suffixe[:40]}_{entreprise['siren']}.txt").write_text(lettre.lettre, encoding="utf-8")
        id_ = self.base.ajouter_candidature({
            "siren": entreprise["siren"], "email": meilleur["email"], "metier": cle_metier, "objet": lettre.objet,
            "corps": lettre.message, "lettre": lettre.lettre, "lettre_pdf": self._lettre_pdf(lettre, dossier, suffixe),
            "moteur": lettre.moteur, "cv_pdf": str(cv_pdf) if cv_pdf else None,
        })
        return Resultat("preparee", meilleur["email"], id_)

    # -- candidature sur offre ---------------------------------------------- #

    def _email_rh(self, offre: Offre, client: ClientRechercheEntreprises | None,
                  prospecteur: Prospecteur | None) -> tuple[str | None, str]:
        """Retrouve l'entreprise de l'offre (SIRENE) puis son adresse RH. Retourne (siren, email)."""
        if not offre.entreprise or client is None:
            return None, ""
        try:
            trouvee = client.par_nom(offre.entreprise, offre.departement)
        except Exception as erreur:
            self.journal(f"  ! recherche de l'entreprise « {offre.entreprise} » : {erreur}")
            return None, ""
        if not trouvee:
            return None, ""
        siren = trouvee["siren"]
        trouvee["metier"] = offre.metier
        self.base.ajouter_entreprise(trouvee)
        existant = self.base.meilleur_email(siren)
        if existant:
            return siren, existant["email"]
        if prospecteur is None or self.base.entreprise(siren)["statut_scan"] != "a_scanner":
            return siren, ""
        resultat = prospecteur.scanner(trouvee["nom"], siren)
        types = set(TYPES_EMAILS_DEFAUT) | (
            {"nominatif", "autre"} if self.config["scan"].get("inclure_emails_nominatifs") else set())
        retenus = [m for m in resultat.emails if m.type in types and not self.base.est_exclu(m.email, siren)]
        for m in retenus:
            self.base.ajouter_email(siren, m.email, m.type, m.score, m.source)
        self.base.maj_scan(siren, "scanne" if retenus else ("sans_email" if resultat.site else "sans_site"),
                           resultat.site, resultat.confiance)
        return siren, retenus[0].email if retenus else ""

    def preparer_offre(self, ligne, moteur: str | None = None, client: ClientRechercheEntreprises | None = None,
                       prospecteur: Prospecteur | None = None) -> Resultat:
        offre = offre_depuis_ligne(ligne)
        cibles = list(dict.fromkeys([offre.metier, *self.config["recherche"]["metiers"]] if offre.metier
                                    else self.config["recherche"]["metiers"]))
        cle_metier = offre.metier or deduire_metier(offre, cibles)[0] or cibles[0]
        mots = mots_cles(offre, self.competences_cv)

        email, siren = offre.email, None
        if not email and self.config["offres"].get("chercher_email_rh", True):
            siren, email = self._email_rh(offre, client, prospecteur)
        if email and self.base.est_exclu(email, siren):
            self.base.maj_offre(offre.id, statut="ignoree")
            return Resultat("ignoree", email)

        dossier = self.config.dossier_donnees / "offres" / nom_fichier(offre.id.replace(":", "_"))
        dossier.mkdir(parents=True, exist_ok=True)
        suffixe = nom_fichier(offre.entreprise or titre_propre(offre.titre))
        entreprise = dict(self.base.entreprise(siren)) if siren else {"siren": siren, "nom": offre.entreprise,
                                                                        "ville": offre.ville}
        offre_dict = offre.en_dict()
        lettre = self.generateur.generer(entreprise, cle_metier, moteur, offre=offre_dict, mots_cles=mots,
                                         contrats=self.contrats)
        cv_pdf, manquantes = self.cv_pour(titre_propre(offre.titre), mots, offre.texte, dossier, suffixe)
        lettre_pdf = self._lettre_pdf(lettre, dossier, suffixe)
        (dossier / "lettre.txt").write_text(lettre.lettre, encoding="utf-8")
        (dossier / "message.txt").write_text(f"Objet : {lettre.objet}\n\n{lettre.message}", encoding="utf-8")
        (dossier / "offre.txt").write_text(
            f"{offre.titre}\n{offre.entreprise} - {offre.ville} - {offre.type_contrat}\n{offre.url}\n\n"
            f"Compétences demandées présentes dans votre CV : {', '.join(m for m in mots if m not in manquantes)}\n"
            f"Compétences demandées absentes de votre CV : {', '.join(manquantes) or '-'}\n\n{offre.description}",
            encoding="utf-8")

        if not email:
            self.base.maj_offre(offre.id, statut="a_postuler_sur_site", dossier=str(dossier), metier=cle_metier)
            return Resultat("a_postuler_sur_site", dossier=dossier, manquantes=manquantes)

        if not siren:  # entreprise inconnue de SIRENE : enregistrement minimal pour le suivi
            siren = "offre-" + hashlib.sha1((offre.entreprise or offre.id).lower().encode()).hexdigest()[:10]
            self.base.ajouter_entreprise({"siren": siren, "nom": offre.entreprise or "Entreprise (offre)",
                                          "ville": offre.ville, "metier": cle_metier})
            self.base.maj_scan(siren, "offre")
        id_ = self.base.ajouter_candidature({
            "siren": siren, "email": email, "metier": cle_metier, "objet": lettre.objet, "corps": lettre.message,
            "lettre": lettre.lettre, "lettre_pdf": lettre_pdf, "moteur": lettre.moteur,
            "offre_id": offre.id, "cv_pdf": str(cv_pdf) if cv_pdf else None,
        })
        self.base.maj_offre(offre.id, statut="preparee", dossier=str(dossier), siren=siren, metier=cle_metier,
                            email=email)
        return Resultat("preparee", email, id_, dossier, manquantes)


def offre_depuis_ligne(ligne) -> Offre:
    donnees = dict(ligne)
    competences = json.loads(donnees.get("competences") or "[]")
    champs = {k: donnees.get(k) or "" for k in ("id", "source", "titre", "entreprise", "description", "url",
                                                 "email", "ville", "code_postal", "departement", "type_contrat",
                                                 "date_publication", "salaire", "reference", "metier")}
    return Offre(**champs, competences=competences)
