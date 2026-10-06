"""Chargement et validation de la configuration (config.yaml + .env)."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

EXEMPLE = Path(__file__).parent / "templates" / "config.exemple.yaml"


class ErreurConfig(Exception):
    pass


def _fusion(base: dict, ajout: dict) -> dict:
    resultat = copy.deepcopy(base)
    for cle, valeur in (ajout or {}).items():
        if isinstance(valeur, dict) and isinstance(resultat.get(cle), dict):
            resultat[cle] = _fusion(resultat[cle], valeur)
        else:
            resultat[cle] = valeur
    return resultat


@dataclass
class Config:
    donnees: dict[str, Any]
    chemin: Path

    def __getitem__(self, cle: str) -> dict[str, Any]:
        return self.donnees[cle]

    @property
    def profil(self) -> dict[str, Any]:
        return self.donnees["profil"]

    @property
    def racine(self) -> Path:
        return self.chemin.parent

    def chemin_relatif(self, valeur: str) -> Path:
        p = Path(valeur).expanduser()
        return p if p.is_absolute() else self.racine / p

    @property
    def dossier_donnees(self) -> Path:
        dossier = self.chemin_relatif(self.donnees["donnees"]["dossier"])
        dossier.mkdir(parents=True, exist_ok=True)
        return dossier

    @property
    def fichier_cv(self) -> Path:
        return self.chemin_relatif(self.donnees["cv"]["fichier"])

    @property
    def fichier_cv_structure(self) -> Path:
        return self.chemin_relatif(self.donnees["cv_adapte"].get("fichier") or "cv/cv.yaml")

    @property
    def mot_de_passe_smtp(self) -> str:
        mdp = os.environ.get("AUTOPOSTULE_SMTP_PASSWORD", "")
        if not mdp:
            raise ErreurConfig(
                "Mot de passe SMTP absent : définissez AUTOPOSTULE_SMTP_PASSWORD dans le fichier .env "
                "(pour Gmail, utilisez un « mot de passe d'application »)."
            )
        return mdp

    def verifier_profil(self) -> list[str]:
        manquants = [c for c in ("prenom", "nom", "email", "telephone") if not str(self.profil.get(c, "")).strip()]
        return manquants


def _defauts() -> dict:
    """Valeurs par défaut du fichier d'exemple, sans les données personnelles fictives (Jean Dupont...)."""
    defauts = yaml.safe_load(EXEMPLE.read_text(encoding="utf-8"))
    defauts["profil"] = {k: ("" if isinstance(v, str) else v) for k, v in defauts["profil"].items()}
    defauts["profil"]["annees_experience"] = 0
    defauts["envoi"]["smtp_utilisateur"] = ""
    defauts["recherche"]["types_contrat"] = []
    return defauts


def contrats_vises(config: "Config") -> list[str]:
    """Types de contrat recherchés (recherche.types_contrat, ou l'ancien champ profil.type_contrat)."""
    from .referentiel import contrats_valides

    valeurs = config["recherche"].get("types_contrat") or []
    if isinstance(valeurs, str):
        valeurs = [v.strip() for v in valeurs.split(",") if v.strip()]
    if not valeurs and config.profil.get("type_contrat"):
        valeurs = [config.profil["type_contrat"]]
    return contrats_valides(valeurs)


CONSEIL_WINDOWS = (
    "Astuce Windows : entre guillemets doubles, les « \\ » d'un chemin sont mal interprétés. Écrivez le chemin "
    "entre guillemets simples ('C:\\Users\\vous\\Downloads\\cv.pdf'), avec des « / » "
    "(\"C:/Users/vous/Downloads/cv.pdf\"), ou copiez le fichier dans le dossier cv/."
)


def lire_yaml(chemin: Path) -> dict:
    """Lit un fichier YAML (UTF-8, UTF-8 avec BOM ou ANSI Windows) avec un message d'erreur compréhensible."""
    brut = Path(chemin).read_bytes()
    try:
        texte = brut.decode("utf-8-sig")
    except UnicodeDecodeError:
        texte = brut.decode("cp1252", errors="replace")  # fichier enregistré en « ANSI » par le Bloc-notes
    try:
        return yaml.safe_load(texte) or {}
    except yaml.YAMLError as erreur:
        position = getattr(erreur, "problem_mark", None)
        ligne = f" (ligne {position.line + 1}, colonne {position.column + 1})" if position else ""
        extrait = ""
        if position:
            lignes = texte.splitlines()
            if position.line < len(lignes):
                extrait = f"\n  > {lignes[position.line].strip()}"
        conseil = f"\n{CONSEIL_WINDOWS}" if "\\" in extrait or "escape" in str(erreur) else ""
        raise ErreurConfig(f"Le fichier {chemin} est mal écrit{ligne}.{extrait}{conseil}") from None


def charger(chemin: str | Path = "config.yaml") -> Config:
    chemin = Path(chemin).resolve()
    if not chemin.exists():
        raise ErreurConfig(f"Fichier de configuration introuvable : {chemin}. Lancez `autopostule init`.")
    try:
        from dotenv import load_dotenv

        load_dotenv(chemin.parent / ".env")
    except ImportError:  # pragma: no cover - python-dotenv est une dépendance
        pass
    defauts = _defauts()
    utilisateur = lire_yaml(chemin)
    return Config(_fusion(defauts, utilisateur), chemin)


def depuis_dict(donnees: dict, racine: str | Path = ".") -> Config:
    """Construit une configuration en mémoire (tests, usage programmatique)."""
    defauts = _defauts()
    return Config(_fusion(defauts, donnees), Path(racine).resolve() / "config.yaml")
