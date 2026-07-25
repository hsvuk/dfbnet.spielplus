"""Platzbelegung fuer eine bestimmte Sportstaette, abgeleitet aus dem CSV-Export
des Vereinsspielplans (Spalte "Spielstaetten-Nr."). Der Export wird auf der
Ergebnismeldungen-Seite ausgeloest (siehe ergebnisse.export_csv) und enthaelt
je Spiel auch die zugeordnete Spielstaette mit Adresse.
"""

import csv
import io

from config import SPORTSTAETTE_NR


def parse_csv(path) -> list[dict]:
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-16")
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    return list(reader)


def filter_platzbelegung(csv_rows: list[dict]) -> list[dict]:
    belegungen = []
    for row in csv_rows:
        if row.get("Spielstätten-Nr.", "").strip() != SPORTSTAETTE_NR:
            continue

        spielkennung = row.get("Spielkennung", "").strip()
        datum = row.get("Spieldatum", "").strip()
        uhrzeit = row.get("Uhrzeit", "").strip()
        heim = row.get("Heimmannschaft", "").strip()
        gast = row.get("Gastmannschaft", "").strip()

        belegungen.append(
            {
                "id": spielkennung or f"{datum}_{uhrzeit}_{heim}",
                "sportstaette_nr": SPORTSTAETTE_NR,
                "datum": datum,
                "uhrzeit_von": uhrzeit,
                "uhrzeit_bis": None,
                "belegt_durch": f"{heim} - {gast}".strip(" -"),
            }
        )
    return belegungen
