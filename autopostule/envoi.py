"""Envoi des candidatures par SMTP, avec plafond quotidien, délais aléatoires et mode test."""

from __future__ import annotations

import mimetypes
import random
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path
from typing import Callable

from .referentiel import normaliser
from .stockage import Base

ERREURS_FATALES = (smtplib.SMTPAuthenticationError, smtplib.SMTPSenderRefused)


def nom_fichier(texte: str) -> str:
    return "_".join(normaliser(texte).split()) or "document"


def construire_message(config, destinataire: str, objet: str, corps: str,
                       pieces_jointes: list[Path]) -> EmailMessage:
    profil = config.profil
    envoi = config["envoi"]
    expediteur = envoi.get("expediteur") or envoi.get("smtp_utilisateur") or profil["email"]
    msg = EmailMessage()
    msg["From"] = formataddr((f"{profil['prenom']} {profil['nom']}", expediteur))
    msg["To"] = destinataire
    msg["Subject"] = objet
    msg["Reply-To"] = profil.get("email") or expediteur
    msg["Message-ID"] = make_msgid(domain=expediteur.rsplit("@", 1)[-1])
    if envoi.get("copie_cachee_a_moi"):
        msg["Bcc"] = profil.get("email") or expediteur
    msg.set_content(corps)
    for chemin in pieces_jointes:
        chemin = Path(chemin)
        type_mime, _ = mimetypes.guess_type(chemin.name)
        principal, secondaire = (type_mime or "application/octet-stream").split("/", 1)
        msg.add_attachment(chemin.read_bytes(), maintype=principal, subtype=secondaire, filename=chemin.name)
    return msg


class Expediteur:
    """Ouvre une connexion SMTP (ou écrit des fichiers .eml en mode test)."""

    def __init__(self, config, test: bool = False, dossier_test: Path | None = None):
        self.config = config
        self.test = test
        self.dossier_test = dossier_test or (config.dossier_donnees / "envois_test")
        self.smtp: smtplib.SMTP | None = None

    def __enter__(self) -> "Expediteur":
        if self.test:
            self.dossier_test.mkdir(parents=True, exist_ok=True)
            return self
        e = self.config["envoi"]
        contexte = ssl.create_default_context()
        if str(e.get("securite", "starttls")).lower() == "ssl":
            self.smtp = smtplib.SMTP_SSL(e["smtp_hote"], int(e.get("smtp_port") or 465), context=contexte, timeout=30)
        else:
            self.smtp = smtplib.SMTP(e["smtp_hote"], int(e.get("smtp_port") or 587), timeout=30)
            self.smtp.starttls(context=contexte)
        self.smtp.login(e.get("smtp_utilisateur") or self.config.profil["email"], self.config.mot_de_passe_smtp)
        return self

    def __exit__(self, *exc) -> None:
        if self.smtp:
            try:
                self.smtp.quit()
            except smtplib.SMTPException:
                pass

    def envoyer(self, msg: EmailMessage, id_: int) -> str:
        if self.test:
            chemin = self.dossier_test / f"candidature_{id_:05d}.eml"
            chemin.write_bytes(bytes(msg))
            return f"test:{chemin.name}"
        assert self.smtp is not None
        self.smtp.send_message(msg)
        return msg["Message-ID"]


def envoyer_candidatures(config, base: Base, test: bool = False, maximum: int | None = None,
                         journal: Callable[[str], None] = print, attendre: Callable[[float], None] = time.sleep) -> dict:
    """Envoie les candidatures prêtes. Retourne un bilan {envoyees, echecs, ignorees, restantes}."""
    e = config["envoi"]
    statuts = ("approuvee",) if e.get("validation_manuelle", True) else ("approuvee", "brouillon")
    a_envoyer = [c for s in statuts for c in base.candidatures(s)]
    quota = int(e.get("max_par_jour") or 40) - (0 if test else base.envois_aujourdhui())
    if maximum is not None:
        quota = min(quota, maximum)
    bilan = {"envoyees": 0, "echecs": 0, "ignorees": 0, "restantes": 0}
    if quota <= 0:
        journal("Plafond quotidien atteint : aucune candidature envoyée aujourd'hui.")
        bilan["restantes"] = len(a_envoyer)
        return bilan

    cv = config.fichier_cv
    if not cv.exists():
        raise FileNotFoundError(f"CV introuvable : {cv}")
    nom_cv = f"CV_{nom_fichier(config.profil['prenom'])}_{nom_fichier(config.profil['nom'])}{cv.suffix}"
    jours = int(e.get("delai_recontact_jours") or 120)
    echecs_consecutifs = 0

    with Expediteur(config, test=test) as expediteur:
        for c in a_envoyer:
            if bilan["envoyees"] >= quota:
                bilan["restantes"] += 1
                continue
            if base.est_exclu(c["email"], c["siren"]) or (not test and base.deja_contacte(c["email"], c["siren"], jours)):
                base.changer_statut([c["id"]], "ignoree")
                bilan["ignorees"] += 1
                journal(f"  - ignorée (exclue ou déjà contactée) : {c['entreprise']} <{c['email']}>")
                continue

            pieces = [_copie_nommee(cv, nom_cv, config)]
            if c["lettre_pdf"] and Path(c["lettre_pdf"]).exists():
                pieces.append(Path(c["lettre_pdf"]))
            msg = construire_message(config, c["email"], c["objet"], c["corps"], pieces)

            if bilan["envoyees"] and not test:
                attendre(random.uniform(float(e.get("delai_min_s") or 60), float(e.get("delai_max_s") or 180)))
            try:
                identifiant = expediteur.envoyer(msg, c["id"])
            except ERREURS_FATALES as erreur:
                base.marquer_echec(c["id"], str(erreur))
                journal(f"Erreur d'authentification / expéditeur refusé : arrêt. ({erreur})")
                bilan["echecs"] += 1
                break
            except (smtplib.SMTPException, OSError) as erreur:
                base.marquer_echec(c["id"], str(erreur))
                bilan["echecs"] += 1
                echecs_consecutifs += 1
                journal(f"  x échec : {c['entreprise']} <{c['email']}> : {erreur}")
                if echecs_consecutifs >= 3:
                    journal("3 échecs consécutifs : arrêt par précaution (compte peut-être limité).")
                    break
                continue
            echecs_consecutifs = 0
            if test:
                journal(f"  ✓ [TEST] {c['entreprise']} <{c['email']}> -> {identifiant}")
            else:
                base.marquer_envoyee(c["id"], identifiant)
                journal(f"  ✓ envoyée : {c['entreprise']} <{c['email']}>")
            bilan["envoyees"] += 1
    return bilan


def _copie_nommee(cv: Path, nom: str, config) -> Path:
    """Le CV est joint sous un nom propre (« CV_jean_dupont.pdf ») quel que soit son nom d'origine."""
    cible = config.dossier_donnees / "pieces" / nom
    if not cible.exists() or cible.stat().st_mtime < cv.stat().st_mtime:
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_bytes(cv.read_bytes())
    return cible
