import logging
import socket
import tempfile
import time
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

from config import LOG_PATH
from db import connect, init_db, record_anomalie
from ergebnisse import (
    export_csv,
    goto_and_search,
    scrape_ergebnisse,
    taegliches_fenster,
    unbekannte_stati,
    zeitfenster,
)
from login import login
from notify import benachrichtige_anomalien, sende_email_anomalien
from platzbelegung import parse_csv
from snapshot import schreibe_snapshot
from verarbeitung import speichere

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("run")


# Wiederholungsversuche bei voruebergehenden Problemen (Portal langsam, Netzwerk noch nicht bereit)
MAX_VERSUCHE = 3
PAUSEN_SEKUNDEN = [60, 180]  # Wartezeit nach Versuch 1 bzw. 2
NETZWERK_WARTEZEIT_SEKUNDEN = 300
PAGE_TIMEOUT_MS = 60_000


def _netzwerk_verfuegbar(host: str = "www.dfbnet.org") -> bool:
    try:
        socket.getaddrinfo(host, 443)
        return True
    except OSError:
        return False


def _warte_auf_netzwerk() -> None:
    """Wartet bis zu NETZWERK_WARTEZEIT_SEKUNDEN auf DNS/Netzwerk (z. B. nach Standby)."""
    ende = time.monotonic() + NETZWERK_WARTEZEIT_SEKUNDEN
    while not _netzwerk_verfuegbar():
        if time.monotonic() >= ende:
            log.warning("Netzwerk nach %d s weiterhin nicht verfuegbar.", NETZWERK_WARTEZEIT_SEKUNDEN)
            return
        log.info("Netzwerk noch nicht verfuegbar, warte 15 s...")
        time.sleep(15)


def _hole_daten(headless: bool) -> tuple[list[dict], list[dict]]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            page = browser.new_context(accept_downloads=True).new_page()
            page.set_default_timeout(PAGE_TIMEOUT_MS)

            log.info("Login...")
            login(page)

            von, bis = taegliches_fenster()
            spiele: list[dict] = []
            csv_rows: list[dict] = []
            for fenster_von, fenster_bis in zeitfenster(von, bis):
                log.info("Fenster %s - %s ...", fenster_von.strftime("%d.%m.%Y"), fenster_bis.strftime("%d.%m.%Y"))
                goto_and_search(page, fenster_von, fenster_bis)
                spiele.extend(scrape_ergebnisse(page))

                with tempfile.TemporaryDirectory() as tmp_dir:
                    csv_path = Path(tmp_dir) / "spielplan.csv"
                    export_csv(page, csv_path)
                    csv_rows.extend(parse_csv(csv_path))
        finally:
            browser.close()
    return spiele, csv_rows


def main(headless: bool = True) -> int:
    init_db()

    spiele = csv_rows = None
    for versuch in range(1, MAX_VERSUCHE + 1):
        _warte_auf_netzwerk()
        try:
            log.info("Versuch %d/%d", versuch, MAX_VERSUCHE)
            spiele, csv_rows = _hole_daten(headless)
            break
        except Exception as exc:
            log.exception("Versuch %d/%d fehlgeschlagen", versuch, MAX_VERSUCHE)
            if versuch < MAX_VERSUCHE:
                pause = PAUSEN_SEKUNDEN[versuch - 1]
                log.info("Neuer Versuch in %d s...", pause)
                time.sleep(pause)
                continue

            detail = (
                f"{exc}\n\nAlle {MAX_VERSUCHE} Versuche fehlgeschlagen.\n\n"
                f"Traceback (letzter Versuch):\n{traceback.format_exc()}"
            )
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

    von, bis = taegliches_fenster()
    anomalien = unbekannte_stati(spiele)
    with connect() as conn:
        aktuelle_spiele, belegungen, fehler = speichere(conn, spiele, csv_rows, von, bis)
        schreibe_snapshot(conn)
        anomalien.extend(fehler)
        for anomalie in anomalien:
            log.warning("Anomalie: %s", anomalie["detail"])
            record_anomalie(conn, anomalie["typ"], anomalie["kontext"], anomalie["detail"])

    if anomalien:
        benachrichtige_anomalien(anomalien)
        sende_email_anomalien(anomalien)

    log.info(
        "Fertig: %d Spiele, %d Platzbelegungen gespeichert, %d Anomalien erkannt.",
        len(aktuelle_spiele),
        len(belegungen),
        len(anomalien),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
