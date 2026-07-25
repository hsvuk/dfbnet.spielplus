import logging
import tempfile
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

from config import LOG_PATH
from db import (
    connect,
    diff_and_upsert_spiel,
    init_db,
    record_anomalie,
    upsert_platzbelegung,
)
from ergebnisse import export_csv, goto_and_search, scrape_ergebnisse, unbekannte_stati
from login import login
from notify import benachrichtige_anomalien, sende_email_anomalien
from platzbelegung import filter_platzbelegung, parse_csv

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("run")


def _spielstaetten_lookup(csv_rows: list[dict]) -> dict[str, tuple[str, str]]:
    lookup = {}
    for row in csv_rows:
        spielkennung = row.get("Spielkennung", "").strip()
        if spielkennung:
            lookup[spielkennung] = (
                row.get("Spielstätte", "").strip(),
                row.get("Spielstätten-Nr.", "").strip(),
            )
    return lookup


def main(headless: bool = True) -> int:
    init_db()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            page = browser.new_context(accept_downloads=True).new_page()

            log.info("Login...")
            login(page)

            log.info("Vereinsspielplan suchen...")
            goto_and_search(page)

            log.info("Ergebnisse auslesen...")
            spiele = scrape_ergebnisse(page)

            log.info("CSV-Export fuer Spielstaetten/Platzbelegung...")
            with tempfile.TemporaryDirectory() as tmp_dir:
                csv_path = Path(tmp_dir) / "spielplan.csv"
                export_csv(page, csv_path)
                csv_rows = parse_csv(csv_path)

            browser.close()
    except Exception as exc:
        log.exception("Lauf fehlgeschlagen")
        detail = f"{exc}\n\nTraceback:\n{traceback.format_exc()}"
        fehler = [
            {
                "typ": "scraping_fehler",
                "kontext": None,
                "detail": detail,
                "schritt": "Login/Navigation/Scraping (siehe Traceback)",
            }
        ]
        with connect() as conn:
            record_anomalie(conn, "scraping_fehler", None, detail)
        benachrichtige_anomalien(fehler)
        sende_email_anomalien(fehler)
        return 1

    lookup = _spielstaetten_lookup(csv_rows)
    for spiel in spiele:
        spielstaette, spielstaette_nr = lookup.get(spiel["spiel_nr"], ("", ""))
        spiel["spielstaette"] = spielstaette
        spiel["spielstaette_nr"] = spielstaette_nr

    belegungen = filter_platzbelegung(csv_rows)
    anomalien = unbekannte_stati(spiele)

    with connect() as conn:
        for spiel in spiele:
            try:
                diff_and_upsert_spiel(conn, spiel)
            except Exception as exc:
                log.exception("Fehler beim Speichern von Spiel %s", spiel.get("spiel_nr"))
                detail = f"{exc}\n\nTraceback:\n{traceback.format_exc()}\n\nSpieldaten: {spiel!r}"
                anomalien.append(
                    {
                        "typ": "scraping_fehler",
                        "kontext": spiel.get("spiel_nr"),
                        "detail": detail,
                        "schritt": "DB-Speicherung (diff_and_upsert_spiel) in src/db.py",
                    }
                )

        for eintrag in belegungen:
            upsert_platzbelegung(conn, eintrag)

        for anomalie in anomalien:
            log.warning("Anomalie: %s", anomalie["detail"])
            record_anomalie(conn, anomalie["typ"], anomalie["kontext"], anomalie["detail"])

    if anomalien:
        benachrichtige_anomalien(anomalien)
        sende_email_anomalien(anomalien)

    log.info(
        "Fertig: %d Spiele, %d Platzbelegungen gespeichert, %d Anomalien erkannt.",
        len(spiele),
        len(belegungen),
        len(anomalien),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
