"""Vereinsspielplan-Abfrage: Navigation, Suche und Scraping der Ergebnisliste.

Ablauf (verifiziert per sichtbarem Testlauf):
1. Hamburger-Menue (oben links) oeffnen, "Ergebnismeldung" klicken.
2. Spielstatus-Dropdown auf "alle Spiele" setzen (Standard ist "ohne Ergebnis").
3. Datum von/bis setzen (Format DD.MM.YYYY), "Suchen" klicken.
4. Ergebnis-Tabelle (erste <table> auf der Seite) auslesen.
"""

from datetime import date, timedelta

from playwright.sync_api import Page

MENU_BUTTON_SELECTOR = "#dfb-Menu-toggle"  # Hamburger-Icon oben links

# Aus der Legende der Ergebnismeldungen-Seite bekannte Status-Texte (Tooltip der Icons)
# bzw. Sonderereignis-Werte. Alles, was hier nicht auftaucht, wird als Anomalie gemeldet.
BEKANNTE_STATUS = {
    "Spiel ist geplant",
    "Spiel ist erfolgt",
    "Spiel ist freigegeben",
    "Spiel ist abgesetzt",
    "Spiel ist ausgefallen",
    "Spielstätte wurde gebucht",
    "Spielstätte wurde vorgemerkt",
    "Heimrecht getauscht",
    "Schiedsrichter ist geplant",
    "Spielfrei-Spiel",
    "Verlegt-Spiel",
    "Annullierung",
    "Ausfall",
    "Nichtantritt Beide",
    "Nichtantritt Heim",
    "Nichtantritt Gast",
    "Abbruch",
    "Wertung der Spielinstanz",
    "Sportgerichtsurteil",
    "",  # keine Icons/kein Sonderereignis gesetzt ("kein Sonderereignis" wird hierauf normalisiert)
}


def _format(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def rolling_window(today: date | None = None) -> tuple[date, date]:
    """Rollierendes ~3-Monats-Fenster: 1 Monat zurueck bis 2 Monate voraus."""
    today = today or date.today()
    return today - timedelta(days=30), today + timedelta(days=60)


def goto_and_search(page: Page, von: date | None = None, bis: date | None = None) -> None:
    von_date, bis_date = rolling_window() if von is None or bis is None else (von, bis)

    page.locator(MENU_BUTTON_SELECTOR).click()
    page.wait_for_timeout(500)
    page.get_by_text("Ergebnismeldung", exact=True).click()
    page.wait_for_timeout(1500)

    status_combo = page.locator("input[role=combobox]").nth(1)
    owns = status_combo.get_attribute("aria-owns")
    status_combo.click(force=True)
    page.wait_for_timeout(200)
    page.locator(f"#{owns} li[data-value='0']").click()  # "alle Spiele"
    page.wait_for_timeout(200)

    date_inputs = page.locator("input[id^='dfb-Input-datepicker']")
    von_input, bis_input = date_inputs.nth(0), date_inputs.nth(1)
    von_input.click()
    von_input.press("Control+A")
    von_input.type(_format(von_date))
    page.keyboard.press("Escape")
    bis_input.click()
    bis_input.press("Control+A")
    bis_input.type(_format(bis_date))
    page.keyboard.press("Escape")

    page.get_by_text("Suchen", exact=False).first.click(force=True)
    page.wait_for_timeout(2000)


def _tore(row, index: int) -> str | None:
    # Nicht ueber die id ("toreHeim_N") ansprechen: bei Spielen mit Sonderwertung
    # (z. B. Wertung nach Nichtantritt) vergibt DFBnet dieselbe id doppelt fuer
    # Haupt- und Sonderwertungs-Tore. Der name ist eindeutig.
    heim = row.locator(f"input[name='_kontext.spiele[{index}].ergebnis.toreHeim']")
    gast = row.locator(f"input[name='_kontext.spiele[{index}].ergebnis.toreGast']")
    if heim.count() == 0 or gast.count() == 0:
        return None
    heim_wert, gast_wert = heim.input_value(), gast.input_value()
    if not heim_wert or not gast_wert:
        return None
    return f"{heim_wert}:{gast_wert}"


def _sonderereignis(row) -> str:
    """Liest die Sonderereignis-Spalte aus. Bei bearbeitbaren (aelteren) Zeilen ist das Feld
    ein Dropdown, dessen Kombobox-Eingabe das value-Attribut mit dem ausgewaehlten Text traegt
    (text_content() der ganzen Zelle wuerde stattdessen alle Optionen zusammenkleben).
    Bei nicht bearbeitbaren Zeilen steht der Text direkt in der Zelle."""
    zelle = row.locator("td").nth(7)
    combobox = zelle.locator("input.dfb-Dropdown-combobox")
    if combobox.count() > 0:
        wert = (combobox.first.get_attribute("value") or "").strip()
    else:
        wert = (zelle.text_content() or "").replace("\xa0", " ").strip()
    return "" if wert == "kein Sonderereignis" else wert


def _status(row) -> str:
    titles = row.locator("td").nth(8).locator("img[title]").all()
    texte = [t.get_attribute("title") or "" for t in titles]
    return "; ".join(t for t in texte if t)


def scrape_ergebnisse(page: Page) -> list[dict]:
    table = page.locator("table").nth(0)
    rows = table.locator("tbody tr")
    ergebnisse = []

    for i in range(rows.count()):
        row = rows.nth(i)
        spiel_nr = row.locator(".dfb-label").nth(0).text_content().strip()
        anstoss = row.locator(".dfb-label").nth(1).text_content().strip()
        datum, _, uhrzeit = anstoss.partition(" ")

        teams = row.locator("td").nth(3).locator("span.text-break")
        heim = teams.nth(0).text_content().strip() if teams.count() > 0 else ""
        gast = teams.nth(1).text_content().strip() if teams.count() > 1 else ""

        ms_art_spielklasse = row.locator("td").nth(5).locator(".dfb-label")
        wettbewerb = ms_art_spielklasse.nth(0).text_content().strip() if ms_art_spielklasse.count() > 0 else ""
        staffel = ms_art_spielklasse.nth(1).text_content().strip() if ms_art_spielklasse.count() > 1 else ""

        ergebnisse.append(
            {
                "spiel_nr": spiel_nr,
                "datum": datum,
                "uhrzeit": uhrzeit,
                "heimmannschaft": heim,
                "gastmannschaft": gast,
                "ergebnis": _tore(row, i),
                "wettbewerb": wettbewerb,
                "staffel": staffel,
                "sonderereignis": _sonderereignis(row),
                "status": _status(row),
            }
        )

    return ergebnisse


def unbekannte_stati(ergebnisse: list[dict]) -> list[dict]:
    """Prueft Sonderereignis/Status jedes Spiels gegen BEKANNTE_STATUS und gibt
    eine Liste von Anomalie-Beschreibungen zurueck (leer, wenn alles bekannt ist)."""
    anomalien = []
    for spiel in ergebnisse:
        for feld in ("sonderereignis", "status"):
            wert = spiel.get(feld, "")
            einzelwerte = [w.strip() for w in wert.split(";")] if wert else [""]
            for einzelwert in einzelwerte:
                if einzelwert not in BEKANNTE_STATUS:
                    anomalien.append(
                        {
                            "typ": "unbekannter_status",
                            "kontext": spiel["spiel_nr"],
                            "detail": (
                                f"Unbekannter Wert in Feld '{feld}': {einzelwert!r}\n"
                                f"Bekannte Werte (BEKANNTE_STATUS): {sorted(BEKANNTE_STATUS)}\n"
                                f"Spieldaten: {spiel!r}"
                            ),
                            "schritt": (
                                "Status-/Sonderereignis-Erkennung (BEKANNTE_STATUS-Liste) "
                                "in src/ergebnisse.py"
                            ),
                        }
                    )
    return anomalien


def export_csv(page: Page, target_path) -> None:
    with page.expect_download() as download_info:
        page.get_by_text("Export", exact=False).first.click(force=True)
    download_info.value.save_as(str(target_path))
