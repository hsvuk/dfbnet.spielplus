"""Exportiert den Spielstand als JSON-Snapshot fuer den Import in hsv.teams.

Der Snapshot enthaelt alle Spiele der Datenbank (nicht nur das gelesene Fenster) und je Spiel
den alten Termin einer Verlegung (verlegt_von), damit hsv.teams Verlegungen nachvollziehen kann.
Die Datei wird atomar geschrieben, damit ein Import nie eine halbe Datei liest.
"""

import json
import logging
import os
from pathlib import Path

from config import ROOT_DIR

log = logging.getLogger("snapshot")

SNAPSHOT_PATH = ROOT_DIR / "data" / "spielplus_snapshot.json"
SNAPSHOT_VERSION = 1

SPIEL_FELDER = [
    "spiel_nr",
    "saison",
    "datum",
    "uhrzeit",
    "heimmannschaft",
    "gastmannschaft",
    "ergebnis",
    "wettbewerb",
    "staffel",
    "spielstaette",
    "spielstaette_nr",
    "sonderereignis",
    "status",
    "aktualisiert_am",
]


def _lese_spiele(conn) -> list[dict]:
    spalten = ", ".join(SPIEL_FELDER)
    zeilen = conn.execute(f"SELECT {spalten} FROM spiele ORDER BY saison, spiel_nr").fetchall()
    spiele = [dict(zip(SPIEL_FELDER, zeile)) for zeile in zeilen]

    # Letzte Verlegung je Spiel: alter Termin ist der Wert, den verlegt_von festhaelt.
    verlegt = conn.execute(
        """
        SELECT spiel_nr, saison, alter_wert FROM spiel_historie
        WHERE feld = 'verlegt_von'
        ORDER BY id
        """
    ).fetchall()
    letzte = {(nr, saison): alt for nr, saison, alt in verlegt}
    for spiel in spiele:
        spiel["verlegt_von"] = letzte.get((spiel["spiel_nr"], spiel["saison"]))
    return spiele


def schreibe_snapshot(conn, pfad: Path = SNAPSHOT_PATH) -> int:
    """Schreibt den Snapshot und gibt die Anzahl exportierter Spiele zurueck."""
    spiele = _lese_spiele(conn)
    daten = {"version": SNAPSHOT_VERSION, "spiele": spiele}

    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp_pfad = pfad.with_suffix(".json.tmp")
    tmp_pfad.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_pfad, pfad)

    log.info("Snapshot geschrieben: %d Spiele nach %s", len(spiele), pfad)
    return len(spiele)
