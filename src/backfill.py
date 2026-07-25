"""Historische Daten einlesen: iteriert in ~3-Monats-Fenstern durch einen Zeitraum,
da die Ergebnismeldungen-Abfrage nur je 3 Monate erlaubt. Login einmalig, danach pro
Fenster: suchen, scrapen, CSV exportieren, in DB schreiben (Diff/Historie/Anomalien).

Aufruf: venv\\Scripts\\python.exe src\\backfill.py 01.07.2024 [ende_dd.mm.yyyy]
(Ende optional, Default = heute)
"""

import sys
import tempfile
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

from db import connect, diff_and_upsert_spiel, init_db, record_anomalie, upsert_platzbelegung
from ergebnisse import export_csv, goto_and_search, scrape_ergebnisse, unbekannte_stati
from login import login
from notify import benachrichtige_anomalien, sende_email_anomalien
from platzbelegung import filter_platzbelegung, parse_csv
from run import _spielstaetten_lookup

FENSTER_TAGE = 90


def zeitfenster(start: date, ende: date, schritt_tage: int = FENSTER_TAGE):
    aktuell = start
    while aktuell <= ende:
        fenster_ende = min(aktuell + timedelta(days=schritt_tage - 1), ende)
        yield aktuell, fenster_ende
        aktuell = fenster_ende + timedelta(days=1)


def run_backfill(start: date, ende: date, headless: bool = False) -> None:
    init_db()
    alle_anomalien: list[dict] = []
    gesamt_spiele = 0
    gesamt_belegungen = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_context(accept_downloads=True).new_page()

        print("Login...")
        login(page)

        for von, bis in zeitfenster(start, ende):
            print(f"Fenster {von:%d.%m.%Y} - {bis:%d.%m.%Y} ...")
            try:
                goto_and_search(page, von, bis)
                spiele = scrape_ergebnisse(page)

                with tempfile.TemporaryDirectory() as tmp_dir:
                    csv_path = Path(tmp_dir) / "spielplan.csv"
                    export_csv(page, csv_path)
                    csv_rows = parse_csv(csv_path)

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
                            detail = (
                                f"{exc}\n\nTraceback:\n{traceback.format_exc()}\n\n"
                                f"Spieldaten: {spiel!r}"
                            )
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
                        record_anomalie(conn, anomalie["typ"], anomalie["kontext"], anomalie["detail"])

                print(f"  {len(spiele)} Spiele, {len(belegungen)} Belegungen, {len(anomalien)} Anomalien")
                gesamt_spiele += len(spiele)
                gesamt_belegungen += len(belegungen)
                alle_anomalien.extend(anomalien)

            except Exception as exc:
                detail = f"{exc}\n\nTraceback:\n{traceback.format_exc()}"
                print(f"  FEHLER im Fenster {von}-{bis}: {exc}")
                with connect() as conn:
                    record_anomalie(conn, "scraping_fehler", f"Fenster {von}-{bis}", detail)
                alle_anomalien.append(
                    {
                        "typ": "scraping_fehler",
                        "kontext": f"Fenster {von}-{bis}",
                        "detail": detail,
                        "schritt": "backfill.run_backfill (Suche/Scraping fuer ein Zeitfenster)",
                    }
                )

        browser.close()

    print(
        f"\nFertig: {gesamt_spiele} Spiele, {gesamt_belegungen} Belegungen, "
        f"{len(alle_anomalien)} Anomalien insgesamt."
    )

    if alle_anomalien:
        benachrichtige_anomalien(alle_anomalien)
        sende_email_anomalien(alle_anomalien)


if __name__ == "__main__":
    start = datetime.strptime(sys.argv[1], "%d.%m.%Y").date()
    ende = datetime.strptime(sys.argv[2], "%d.%m.%Y").date() if len(sys.argv) > 2 else date.today()
    run_backfill(start, ende)
