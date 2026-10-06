"""Exécution des opérations longues (recherche, scan, préparation, envoi) en tâche de fond, avec journal."""

from __future__ import annotations

import io
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Callable


class _SortieParFil(io.TextIOBase):
    """Remplace sys.stdout : ce qu'écrit une tâche va dans son journal, le reste vers la console."""

    def __init__(self, originale):
        self.originale = originale
        self.journaux: dict[int, "Tache"] = {}

    def write(self, texte: str) -> int:
        tache = self.journaux.get(threading.get_ident())
        if tache is not None:
            tache.ecrire(texte)
        else:
            try:
                self.originale.write(texte)
            except (ValueError, OSError):  # console d'origine fermée : console système
                (sys.__stdout__ or io.StringIO()).write(texte)
        return len(texte)

    def flush(self) -> None:
        try:
            self.originale.flush()
        except (ValueError, OSError):
            pass


_sortie: _SortieParFil | None = None
_verrou_sortie = threading.Lock()


def _installer_sortie() -> _SortieParFil:
    global _sortie
    with _verrou_sortie:
        if _sortie is None:
            _sortie = _SortieParFil(sys.stdout)
            sys.stdout = _sortie
    return _sortie


@dataclass
class Tache:
    id: str
    titre: str
    etat: str = "en_cours"          # en_cours | terminee | erreur
    lignes: list[str] = field(default_factory=list)
    debut: float = field(default_factory=time.time)
    fin: float | None = None
    _tampon: str = ""

    def ecrire(self, texte: str) -> None:
        self._tampon += texte
        while "\n" in self._tampon:
            ligne, self._tampon = self._tampon.split("\n", 1)
            self.lignes.append(ligne)

    def en_dict(self) -> dict:
        lignes = self.lignes + ([self._tampon] if self._tampon else [])
        return {"id": self.id, "titre": self.titre, "etat": self.etat, "journal": lignes,
                "duree": round((self.fin or time.time()) - self.debut)}


class Gestionnaire:
    """Une seule tâche à la fois : les opérations partagent la base et respectent des délais réseau."""

    def __init__(self):
        self.taches: dict[str, Tache] = {}
        self.courante: Tache | None = None
        self._verrou = threading.Lock()

    def occupe(self) -> bool:
        return self.courante is not None and self.courante.etat == "en_cours"

    def lancer(self, titre: str, fonction: Callable[[], object]) -> Tache:
        with self._verrou:
            if self.occupe():
                raise RuntimeError(f"Une tâche est déjà en cours : {self.courante.titre}")
            tache = Tache(id=uuid.uuid4().hex[:10], titre=titre)
            self.taches[tache.id] = tache
            self.courante = tache
        sortie = _installer_sortie()

        def executer():
            sortie.journaux[threading.get_ident()] = tache
            try:
                fonction()
                tache.etat = "terminee"
            except Exception as erreur:  # le journal montre l'erreur à l'utilisateur
                tache.ecrire(f"\nErreur : {erreur}\n")
                tache.ecrire(traceback.format_exc(limit=3))
                tache.etat = "erreur"
            finally:
                tache.fin = time.time()
                sortie.journaux.pop(threading.get_ident(), None)

        threading.Thread(target=executer, daemon=True, name=f"tache-{tache.id}").start()
        return tache

    def attendre(self, tache: Tache, delai: float = 30) -> None:
        """Pour les tests : attend la fin d'une tâche."""
        limite = time.time() + delai
        while tache.etat == "en_cours" and time.time() < limite:
            time.sleep(0.05)
