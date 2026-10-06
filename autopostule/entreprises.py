"""Recherche d'entreprises via l'API publique « Recherche d'entreprises » (data.gouv.fr).

Documentation : https://recherche-entreprises.api.gouv.fr/docs/
API gratuite, sans clé, limitée à ~7 requêtes/seconde. Les données proviennent de la base SIRENE (INSEE).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterator

import requests

from .referentiel import Metier, normaliser, tranches_a_partir_de

URL_API = "https://recherche-entreprises.api.gouv.fr/search"
PAR_PAGE = 25  # maximum autorisé par l'API

# Natures juridiques exclues : entrepreneurs individuels, associations, administrations...
NATURES_EXCLUES_PREFIXES = ("1", "7", "9")


@dataclass
class CriteresRecherche:
    metier: Metier
    regions: list[str] = field(default_factory=list)       # codes INSEE région, ex : ["11", "32"]
    departements: list[str] = field(default_factory=list)  # ex : ["59", "62"]
    villes: list[str] = field(default_factory=list)        # filtre local sur la commune
    effectif_min: int = 0
    naf_supplementaires: list[str] = field(default_factory=list)
    limite: int = 200

    def parametres(self) -> dict[str, str]:
        naf = list(dict.fromkeys([*self.metier.naf, *self.naf_supplementaires]))
        params = {
            "activite_principale": ",".join(naf),
            "etat_administratif": "A",
            "per_page": str(PAR_PAGE),
        }
        if self.departements:
            params["departement"] = ",".join(self.departements)
        elif self.regions:
            params["region"] = ",".join(self.regions)
        if self.effectif_min > 0:
            params["tranche_effectif_salarie"] = ",".join(tranches_a_partir_de(self.effectif_min))
        return params


def convertir(resultat: dict, cle_metier: str) -> dict:
    """Transforme un résultat brut de l'API en enregistrement pour la base locale."""
    siege = resultat.get("siege") or {}
    return {
        "siren": resultat.get("siren"),
        "nom": resultat.get("nom_complet") or resultat.get("nom_raison_sociale") or "",
        "naf": resultat.get("activite_principale") or siege.get("activite_principale"),
        "adresse": siege.get("adresse"),
        "code_postal": siege.get("code_postal"),
        "ville": siege.get("libelle_commune"),
        "departement": siege.get("departement"),
        "region": siege.get("region"),
        "tranche_effectif": resultat.get("tranche_effectif_salarie") or siege.get("tranche_effectif_salarie"),
        "categorie": resultat.get("categorie_entreprise"),
        "nature_juridique": resultat.get("nature_juridique"),
        "metier": cle_metier,
    }


def garder(entreprise: dict, villes: list[str]) -> bool:
    if not entreprise.get("siren") or not entreprise.get("nom"):
        return False
    nature = str(entreprise.get("nature_juridique") or "")
    if nature.startswith(NATURES_EXCLUES_PREFIXES):
        return False
    if villes:
        commune = normaliser(entreprise.get("ville") or "")
        if not any(normaliser(v) == commune or commune.startswith(normaliser(v) + " ") for v in villes):
            return False
    return True


class ClientRechercheEntreprises:
    def __init__(self, session: requests.Session | None = None, pause: float = 0.2, timeout: float = 20):
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "autopostule/0.1 (recherche d'emploi)")
        self.pause = pause
        self.timeout = timeout

    def _page(self, params: dict, page: int) -> dict:
        for tentative in range(4):
            reponse = self.session.get(URL_API, params={**params, "page": page}, timeout=self.timeout)
            if reponse.status_code == 429:  # trop de requêtes : on attend puis on réessaie
                time.sleep(2 ** tentative)
                continue
            reponse.raise_for_status()
            return reponse.json()
        reponse.raise_for_status()
        return {}

    def rechercher(self, criteres: CriteresRecherche) -> Iterator[dict]:
        params = criteres.parametres()
        trouvees = 0
        page = 1
        while trouvees < criteres.limite:
            donnees = self._page(params, page)
            resultats = donnees.get("results") or []
            if not resultats:
                break
            for brut in resultats:
                entreprise = convertir(brut, criteres.metier.cle)
                if garder(entreprise, criteres.villes):
                    yield entreprise
                    trouvees += 1
                    if trouvees >= criteres.limite:
                        return
            if page >= int(donnees.get("total_pages") or page):
                break
            page += 1
            time.sleep(self.pause)
