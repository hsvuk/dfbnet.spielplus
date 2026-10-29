"""Gemeinsame Verarbeitung gescrapter Spiele + CSV-Export (genutzt von run.py und backfill.py).

Besonderheit von DFBnet: Wird ein Spiel verlegt, bleibt der alte Termin als eigene Zeile mit
derselben Spielnummer bestehen (Status "Verlegt-Spiel ..."), der neue Termin kommt als weitere
Zeile hinzu. Da die Abfrage nur ein 3-Monats-Fenster sieht, sind oft nur eine oder beide Zeilen
sichtbar. Hier wird je Spielnummer und Saison die aktuelle Zeile bestimmt, damit die Historie
keine Hin-und-her-Eintraege bekommt. Spielnummern werden ueber Saisons hinweg wiederverwendet
(verschiedene Spiele!), daher ist die Identitaet eines Spiels (Spielnummer, Saison).
"""

import logging
import traceback
from collections import defaultdict
from datetime import date, datetime

from db import diff_and_upsert_spiel, record_historie, saison_von_datum, upsert_platzbelegung
from platzbelegung import filter_platzbelegung

log = logging.getLogger("verarbeitung")

VERLEGT_PRAEFIX = "Verlegt-Spiel"
VERLEGT_VON = "verlegt_von"


def ist_verlegt(status: str | None) -> bool:
    return (status or "").startswith(VERLEGT_PRAEFIX)


def _csv_lookup(csv_rows: list[dict]) -> dict[tuple[str, str], tuple[str, str]]:
    """(Spielkennung, Spieldatum) -> (Spielstaette, Spielstaetten-Nr.)"""
    lookup = {}
    for row in csv_rows:
        kennung = row.get("Spielkennung", "").strip()
        if kennung:
            lookup[(kennung, row.get("Spieldatum", "").strip())] = (
                row.get("Spielstätte", "").strip(),
                row.get("Spielstätten-Nr.", "").strip(),
            )
    return lookup


def ergaenze_spielstaetten(spiele: list[dict], csv_rows: list[dict]) -> None:
    """Spielstaette je Spielnummer UND Datum zuordnen (Nummern koennen doppelt vorkommen).
    Bei verlegten Spielen steht in der CSV statt eines Ortes "verlegt auf ..." - das ist
    keine Spielstaette und wird geleert."""
    lookup = _csv_lookup(csv_rows)
    for spiel in spiele:
        staette, staette_nr = lookup.get((spiel["spiel_nr"], spiel["datum"]), ("", ""))
        if staette.lower().startswith("verlegt auf"):
            staette = ""
        spiel["spielstaette"] = staette
        spiel["spielstaette_nr"] = staette_nr


def _db_stand(conn, spiel_nr: str, saison: str) -> tuple[str, str] | None:
    return conn.execute(
        "SELECT datum, status FROM spiele WHERE spiel_nr = ? AND saison = ?", (spiel_nr, saison)
    ).fetchone()


def waehle_aktuelle_spiele(conn, spiele: list[dict]) -> tuple[list[dict], list[dict]]:
    """Liefert (aktuelle Zeilen, ueberholte Zeilen) je Spielnummer und Saison.

    Aktuell ist die Zeile ohne Status "Verlegt-Spiel". Eine verlegte Zeile gilt zusaetzlich
    als ueberholt, wenn die DB bereits einen aktiven Stand mit anderem Datum kennt (der neue
    Termin liegt dann ausserhalb des gelesenen Fensters)."""
    gruppen: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for spiel in spiele:
        gruppen[(spiel["spiel_nr"], spiel["saison"])].append(spiel)

    aktuell, ueberholt = [], []
    for (nr, saison), zeilen in gruppen.items():
        kandidaten = [z for z in zeilen if not ist_verlegt(z.get("status"))]
        if len(kandidaten) > 1:
            log.warning("Spiel %s (%s): %d aktuelle Zeilen, nehme die letzte.", nr, saison, len(kandidaten))
        gewaehlt = kandidaten[-1] if kandidaten else None
        if gewaehlt is None:
            # Nur verlegte Zeilen sichtbar (neuer Termin ausserhalb des Fensters): die mit dem
            # spaetesten Datum gilt, sofern die DB nicht schon einen aktiven Stand kennt.
            stand = _db_stand(conn, nr, saison)
            if stand is None or ist_verlegt(stand[1]):
                gewaehlt = max(zeilen, key=lambda z: _parse_datum(z["datum"]) or date.min)
            else:
                # DB kennt einen aktiven Stand: nur eine verlegte Zeile mit demselben Datum ist
                # eine echte Statusaenderung, alle anderen sind alte Termine.
                gleiche = [z for z in zeilen if z["datum"] == stand[0]]
                gewaehlt = gleiche[-1] if gleiche else None
        if gewaehlt is not None:
            aktuell.append(gewaehlt)
        ueberholt.extend(z for z in zeilen if z is not gewaehlt)
    return aktuell, ueberholt


def _vermerke_alten_termin(conn, zeile: dict) -> None:
    """Haelt einen ueberholten Termin einmalig in der Historie fest, sofern er nicht schon
    als Datumsaenderung erfasst ist."""
    alt = f"{zeile['datum']} {zeile.get('uhrzeit') or ''}".strip()
    schon = conn.execute(
        """
        SELECT 1 FROM spiel_historie WHERE spiel_nr = ? AND saison = ?
          AND ((feld = 'datum' AND alter_wert = ?) OR (feld = ? AND alter_wert = ?))
        """,
        (zeile["spiel_nr"], zeile["saison"], zeile["datum"], VERLEGT_VON, alt),
    ).fetchone()
    if not schon:
        record_historie(conn, zeile["spiel_nr"], zeile["saison"], VERLEGT_VON, alt, zeile.get("sonderereignis") or "Verlegt-Spiel")


def _parse_datum(text: str) -> date | None:
    try:
        return datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        return None


def speichere(conn, spiele: list[dict], csv_rows: list[dict], von: date, bis: date) -> tuple[list[dict], list[dict], list[dict]]:
    """Schreibt Spiele, Historie und Platzbelegung. Gibt (aktuelle Spiele, Belegungen,
    Fehler-Anomalien) zurueck."""
    for spiel in spiele:
        spiel["saison"] = saison_von_datum(spiel["datum"])
    ergaenze_spielstaetten(spiele, csv_rows)
    aktuell, ueberholt = waehle_aktuelle_spiele(conn, spiele)
    fehler: list[dict] = []

    for spiel in aktuell:
        try:
            diff_and_upsert_spiel(conn, spiel)
        except Exception as exc:
            log.exception("Fehler beim Speichern von Spiel %s", spiel.get("spiel_nr"))
            detail = f"{exc}\n\nTraceback:\n{traceback.format_exc()}\n\nSpieldaten: {spiel!r}"
            fehler.append(
                {
                    "typ": "scraping_fehler",
                    "kontext": spiel.get("spiel_nr"),
                    "detail": detail,
                    "schritt": "DB-Speicherung (diff_and_upsert_spiel) in src/db.py",
                }
            )
    for zeile in ueberholt:
        _vermerke_alten_termin(conn, zeile)

    ueberholte_keys = {(z["spiel_nr"], z["datum"]) for z in ueberholt}
    status_je_spiel = {(s["spiel_nr"], s["datum"]): s.get("status") for s in aktuell}
    belegungen = []
    for eintrag in filter_platzbelegung(csv_rows):
        key = (eintrag["id"], eintrag["datum"])
        if key in ueberholte_keys:
            continue
        eintrag["spielstatus"] = status_je_spiel.get(key)
        eintrag["id"] = f"{eintrag['id']}/{saison_von_datum(eintrag['datum'])}"
        belegungen.append(eintrag)
        upsert_platzbelegung(conn, eintrag)

    _entferne_veraltete_belegungen(conn, {b["id"] for b in belegungen}, von, bis)
    return aktuell, belegungen, fehler


def _entferne_veraltete_belegungen(conn, aktuelle_ids: set[str], von: date, bis: date) -> None:
    """Belegungen im gelesenen Fenster, die im Export nicht mehr vorkommen, loeschen."""
    for beleg_id, datum in conn.execute("SELECT id, datum FROM platzbelegung").fetchall():
        d = _parse_datum(datum)
        if d is not None and von <= d <= bis and beleg_id not in aktuelle_ids:
            conn.execute("DELETE FROM platzbelegung WHERE id = ?", (beleg_id,))
