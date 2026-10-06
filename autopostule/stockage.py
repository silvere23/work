"""Persistance SQLite : entreprises, e-mails trouvés, candidatures, liste d'exclusion."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS entreprises (
    siren TEXT PRIMARY KEY,
    nom TEXT NOT NULL,
    naf TEXT,
    adresse TEXT,
    code_postal TEXT,
    ville TEXT,
    departement TEXT,
    region TEXT,
    tranche_effectif TEXT,
    categorie TEXT,
    metier TEXT,
    site TEXT,
    site_confiance TEXT,
    statut_scan TEXT DEFAULT 'a_scanner',   -- a_scanner | scanne | sans_site | sans_email
    date_ajout TEXT,
    date_scan TEXT
);
CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    siren TEXT NOT NULL REFERENCES entreprises(siren),
    email TEXT NOT NULL,
    type TEXT,          -- rh | generique | nominatif | autre
    score INTEGER,
    source TEXT,
    date_ajout TEXT,
    UNIQUE (siren, email)
);
CREATE TABLE IF NOT EXISTS candidatures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    siren TEXT NOT NULL REFERENCES entreprises(siren),
    email TEXT NOT NULL,
    metier TEXT,
    objet TEXT,
    corps TEXT,
    lettre TEXT,
    lettre_pdf TEXT,
    moteur TEXT,
    statut TEXT DEFAULT 'brouillon',  -- brouillon | approuvee | envoyee | echec | ignoree
    erreur TEXT,
    date_creation TEXT,
    date_envoi TEXT,
    message_id TEXT
);
CREATE TABLE IF NOT EXISTS exclusions (
    valeur TEXT PRIMARY KEY,   -- e-mail, domaine ou SIREN
    raison TEXT,
    date_ajout TEXT
);
CREATE TABLE IF NOT EXISTS offres (
    id TEXT PRIMARY KEY,         -- ft:<id>, adzuna:<id>, manuel:<hash>
    source TEXT,
    titre TEXT,
    entreprise TEXT,
    description TEXT,
    url TEXT,
    email TEXT,
    ville TEXT,
    code_postal TEXT,
    departement TEXT,
    type_contrat TEXT,
    date_publication TEXT,
    salaire TEXT,
    competences TEXT,            -- JSON
    reference TEXT,
    metier TEXT,
    cle_doublon TEXT,
    siren TEXT,
    statut TEXT DEFAULT 'nouvelle',  -- nouvelle | preparee | a_postuler_sur_site | postulee_sur_site | ignoree
    dossier TEXT,
    date_ajout TEXT
);
CREATE INDEX IF NOT EXISTS idx_candidatures_statut ON candidatures(statut);
CREATE INDEX IF NOT EXISTS idx_offres_doublon ON offres(cle_doublon);
"""

MIGRATIONS = {"candidatures": {"offre_id": "TEXT", "cv_pdf": "TEXT"}}


def maintenant() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Base:
    def __init__(self, chemin: str | Path):
        self.chemin = Path(chemin)
        self.cx = sqlite3.connect(str(self.chemin))
        self.cx.row_factory = sqlite3.Row
        self.cx.executescript(SCHEMA)
        self._migrer()

    def _migrer(self) -> None:
        """Ajoute les colonnes apparues après la création d'une base existante."""
        for table, colonnes in MIGRATIONS.items():
            existantes = {ligne[1] for ligne in self.cx.execute(f"PRAGMA table_info({table})")}
            for nom, type_ in colonnes.items():
                if nom not in existantes:
                    self.cx.execute(f"ALTER TABLE {table} ADD COLUMN {nom} {type_}")
        self.cx.commit()

    def fermer(self) -> None:
        self.cx.close()

    # -- entreprises -------------------------------------------------------- #

    def ajouter_entreprise(self, e: dict) -> bool:
        """Insère une entreprise ; retourne False si elle existait déjà."""
        cur = self.cx.execute(
            """INSERT OR IGNORE INTO entreprises
               (siren, nom, naf, adresse, code_postal, ville, departement, region,
                tranche_effectif, categorie, metier, site, site_confiance, statut_scan, date_ajout)
               VALUES (:siren, :nom, :naf, :adresse, :code_postal, :ville, :departement, :region,
                       :tranche_effectif, :categorie, :metier, :site, :site_confiance, 'a_scanner', :date)""",
            {
                "site": None,
                "site_confiance": None,
                **{k: e.get(k) for k in (
                    "siren", "nom", "naf", "adresse", "code_postal", "ville", "departement", "region",
                    "tranche_effectif", "categorie", "metier", "site", "site_confiance")},
                "date": maintenant(),
            },
        )
        self.cx.commit()
        return cur.rowcount > 0

    def entreprise(self, siren: str) -> sqlite3.Row | None:
        return self.cx.execute("SELECT * FROM entreprises WHERE siren = ?", (siren,)).fetchone()

    def entreprises_a_scanner(self, limite: int | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM entreprises WHERE statut_scan = 'a_scanner' ORDER BY date_ajout"
        if limite:
            sql += f" LIMIT {int(limite)}"
        return self.cx.execute(sql).fetchall()

    def maj_scan(self, siren: str, statut: str, site: str | None = None, confiance: str | None = None) -> None:
        self.cx.execute(
            "UPDATE entreprises SET statut_scan = ?, site = COALESCE(?, site), "
            "site_confiance = COALESCE(?, site_confiance), date_scan = ? WHERE siren = ?",
            (statut, site, confiance, maintenant(), siren),
        )
        self.cx.commit()

    # -- e-mails ------------------------------------------------------------ #

    def ajouter_email(self, siren: str, email: str, type_: str, score: int, source: str) -> None:
        self.cx.execute(
            "INSERT OR IGNORE INTO emails (siren, email, type, score, source, date_ajout) VALUES (?,?,?,?,?,?)",
            (siren, email.lower(), type_, score, source, maintenant()),
        )
        self.cx.commit()

    def meilleur_email(self, siren: str) -> sqlite3.Row | None:
        return self.cx.execute(
            "SELECT * FROM emails WHERE siren = ? ORDER BY score DESC, id LIMIT 1", (siren,)
        ).fetchone()

    def emails(self, siren: str) -> list[sqlite3.Row]:
        return self.cx.execute("SELECT * FROM emails WHERE siren = ? ORDER BY score DESC", (siren,)).fetchall()

    # -- exclusions --------------------------------------------------------- #

    def exclure(self, valeur: str, raison: str = "") -> None:
        self.cx.execute(
            "INSERT OR REPLACE INTO exclusions (valeur, raison, date_ajout) VALUES (?,?,?)",
            (valeur.strip().lower(), raison, maintenant()),
        )
        self.cx.commit()

    def est_exclu(self, email: str, siren: str | None = None) -> bool:
        email = email.lower()
        domaine = email.rsplit("@", 1)[-1]
        valeurs = [email, domaine] + ([siren] if siren else [])
        marque = ",".join("?" * len(valeurs))
        return self.cx.execute(f"SELECT 1 FROM exclusions WHERE valeur IN ({marque})", valeurs).fetchone() is not None

    # -- candidatures ------------------------------------------------------- #

    def entreprises_sans_candidature(self, metier: str | None = None) -> list[sqlite3.Row]:
        sql = """SELECT e.* FROM entreprises e
                 WHERE e.statut_scan = 'scanne'
                   AND EXISTS (SELECT 1 FROM emails m WHERE m.siren = e.siren)
                   AND NOT EXISTS (SELECT 1 FROM candidatures c WHERE c.siren = e.siren
                                   AND c.statut != 'ignoree')"""
        params: list = []
        if metier:
            sql += " AND e.metier = ?"
            params.append(metier)
        return self.cx.execute(sql + " ORDER BY e.date_ajout", params).fetchall()

    def ajouter_candidature(self, c: dict) -> int:
        cur = self.cx.execute(
            """INSERT INTO candidatures (siren, email, metier, objet, corps, lettre, lettre_pdf, moteur,
                                         statut, date_creation, offre_id, cv_pdf)
               VALUES (:siren, :email, :metier, :objet, :corps, :lettre, :lettre_pdf, :moteur,
                       'brouillon', :date, :offre_id, :cv_pdf)""",
            {"offre_id": None, "cv_pdf": None, **c, "date": maintenant()},
        )
        self.cx.commit()
        return int(cur.lastrowid)

    def candidature(self, id_: int) -> sqlite3.Row | None:
        return self.cx.execute("SELECT * FROM candidatures WHERE id = ?", (id_,)).fetchone()

    def candidatures(self, statut: str | None = None) -> list[sqlite3.Row]:
        sql = """SELECT c.*, COALESCE(e.nom, o.entreprise, '?') AS entreprise,
                        COALESCE(e.ville, o.ville) AS ville, o.titre AS titre_offre
                 FROM candidatures c
                 LEFT JOIN entreprises e ON e.siren = c.siren
                 LEFT JOIN offres o ON o.id = c.offre_id"""
        if statut:
            return self.cx.execute(sql + " WHERE c.statut = ? ORDER BY c.id", (statut,)).fetchall()
        return self.cx.execute(sql + " ORDER BY c.id").fetchall()

    def changer_statut(self, ids: Iterable[int], statut: str, depuis: tuple[str, ...] | None = None) -> int:
        n = 0
        for id_ in ids:
            sql = "UPDATE candidatures SET statut = ? WHERE id = ?"
            params: list = [statut, id_]
            if depuis:
                sql += f" AND statut IN ({','.join('?' * len(depuis))})"
                params += list(depuis)
            n += self.cx.execute(sql, params).rowcount
        self.cx.commit()
        return n

    def marquer_envoyee(self, id_: int, message_id: str) -> None:
        self.cx.execute(
            "UPDATE candidatures SET statut = 'envoyee', date_envoi = ?, message_id = ?, erreur = NULL WHERE id = ?",
            (maintenant(), message_id, id_),
        )
        self.cx.commit()

    def marquer_echec(self, id_: int, erreur: str) -> None:
        self.cx.execute("UPDATE candidatures SET statut = 'echec', erreur = ? WHERE id = ?", (erreur[:500], id_))
        self.cx.commit()

    def envois_aujourdhui(self) -> int:
        debut = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
        return self.cx.execute(
            "SELECT COUNT(*) FROM candidatures WHERE statut = 'envoyee' AND date_envoi >= ?", (debut,)
        ).fetchone()[0]

    def deja_contacte(self, email: str, siren: str, jours: int) -> bool:
        """Vrai si l'entreprise ou l'adresse a déjà reçu une candidature dans les `jours` derniers jours."""
        limite = (datetime.now() - timedelta(days=jours)).isoformat(timespec="seconds")
        return self.cx.execute(
            "SELECT 1 FROM candidatures WHERE statut = 'envoyee' AND date_envoi >= ? AND (siren = ? OR email = ?)",
            (limite, siren, email.lower()),
        ).fetchone() is not None

    def deja_postule_offre(self, offre_id: str) -> bool:
        return self.cx.execute(
            "SELECT 1 FROM candidatures WHERE offre_id = ? AND statut = 'envoyee'", (offre_id,)
        ).fetchone() is not None

    # -- offres ------------------------------------------------------------- #

    def ajouter_offre(self, o: dict) -> bool:
        """Enregistre une offre ; False si elle est déjà connue (même id ou même offre sur une autre source)."""
        if self.cx.execute("SELECT 1 FROM offres WHERE id = ? OR cle_doublon = ?",
                           (o["id"], o.get("cle_doublon"))).fetchone():
            return False
        colonnes = ("id", "source", "titre", "entreprise", "description", "url", "email", "ville", "code_postal",
                    "departement", "type_contrat", "date_publication", "salaire", "reference", "metier",
                    "cle_doublon")
        valeurs = {c: o.get(c) for c in colonnes}
        valeurs["competences"] = json.dumps(o.get("competences") or [], ensure_ascii=False)
        valeurs["date_ajout"] = maintenant()
        self.cx.execute(
            f"INSERT INTO offres ({', '.join(valeurs)}) VALUES ({', '.join(':' + c for c in valeurs)})", valeurs)
        self.cx.commit()
        return True

    def offre(self, id_: str) -> sqlite3.Row | None:
        return self.cx.execute("SELECT * FROM offres WHERE id = ?", (id_,)).fetchone()

    def offres(self, statut: str | None = None, limite: int | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM offres"
        params: list = []
        if statut:
            sql += " WHERE statut = ?"
            params.append(statut)
        sql += " ORDER BY date_publication DESC, date_ajout DESC"
        if limite:
            sql += f" LIMIT {int(limite)}"
        return self.cx.execute(sql, params).fetchall()

    def maj_offre(self, id_: str, **champs) -> None:
        if champs:
            affectations = ", ".join(f"{c} = :{c}" for c in champs)
            self.cx.execute(f"UPDATE offres SET {affectations} WHERE id = :id", {**champs, "id": id_})
            self.cx.commit()

    # -- statistiques ------------------------------------------------------- #

    def statistiques(self) -> dict[str, int]:
        stats: dict[str, int] = {}
        stats["entreprises"] = self.cx.execute("SELECT COUNT(*) FROM entreprises").fetchone()[0]
        for statut, n in self.cx.execute("SELECT statut_scan, COUNT(*) FROM entreprises GROUP BY statut_scan"):
            stats[f"scan_{statut}"] = n
        stats["emails"] = self.cx.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
        for statut, n in self.cx.execute("SELECT statut, COUNT(*) FROM candidatures GROUP BY statut"):
            stats[f"candidatures_{statut}"] = n
        for statut, n in self.cx.execute("SELECT statut, COUNT(*) FROM offres GROUP BY statut"):
            stats[f"offres_{statut}"] = n
        stats["exclusions"] = self.cx.execute("SELECT COUNT(*) FROM exclusions").fetchone()[0]
        return stats
