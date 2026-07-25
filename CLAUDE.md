# dfbnet.spielplus

Automatisiertes tägliches Auslesen von DFBnet Spielplus (`https://www.dfbnet.org/spielplus/login.do`)
für einen Vereinsvertreter: Spielpläne/Ergebnismeldungen und Platzbelegung für das
Karl-Kleine-Stadion Höingen (Sportstätten-Nr. `2100290091`) werden lokal in SQLite gespeichert,
inkl. Änderungshistorie pro Spiel und Anomalie-Erkennung mit Benachrichtigung.

## Stack
- Python 3.13, venv unter `venv/`
- Playwright (Chromium, headless im Produktivbetrieb) für Login + Datenabfrage,
  da DFBnet Spielplus OAuth-Login (`auth.dfbnet.org`) + Angular-Frontend nutzt —
  ein reiner HTTP-Request-Login reicht nicht.
- SQLite (`data/spielplus.sqlite3`) als lokale Datenbank
- Windows Task Scheduler für den täglichen Lauf (`scripts/run_daily.bat`, 17:00 Uhr)
- `winotify` für Desktop-Toasts, `smtplib` (Google Workspace SMTP) für E-Mail-Alerts

## Struktur
- `src/config.py` — lädt `.env`, zentrale Konstanten (inkl. SMTP-Einstellungen)
- `src/login.py` — Playwright-Login-Flow
- `src/ergebnisse.py` — Ergebnismeldungen-Abfrage/Scraping, `BEKANNTE_STATUS`-Whitelist,
  `unbekannte_stati()` für Anomalie-Erkennung
- `src/platzbelegung.py` — CSV-Export parsen, Platzbelegung für konfigurierte Sportstätte filtern
- `src/db.py` — SQLite-Schema, Upsert-Funktionen, `diff_and_upsert_spiel()` (schreibt
  `spiel_historie` bei Änderungen an datum/uhrzeit/spielstaette/status), `anomalien`-Tabelle
- `src/notify.py` — Desktop-Toast (`benachrichtige_anomalien`) + E-Mail
  (`sende_email_anomalien`) bei neuen Anomalien, inkl. fertigem Copy-Paste-Prompt für Claude Code
- `src/run.py` — Orchestriert den kompletten Lauf, mit granularem Error-Handling und Logging
- `src/backfill.py` — historische Daten einlesen (iteriert in 90-Tage-Fenstern durch einen
  Zeitraum, da die Ergebnismeldungen-Abfrage nur je 3 Monate erlaubt); Aufruf:
  `venv\Scripts\python.exe src\backfill.py 01.07.2024 [ende_dd.mm.yyyy]`

## Zugangsdaten (`.env`, aus `.env.example` kopieren, nie committed, nie im Chat)
- `DFBNET_USERNAME` / `DFBNET_PASSWORD` — DFBnet-Login
- `SMTP_USER` = `app@hoeinger-sv.de` (Google Workspace), `SMTP_PASSWORD` = App-Passwort
  (nicht das normale Login-Passwort — erfordert 2-Faktor-Auth + App-Passwort-Erstellung unter
  myaccount.google.com/apppasswords)
- `NOTIFY_EMAIL_TO` = `uli.knieper@hoeinger-sv.de`

## Anomalie-/Historie-Konzept
- Jedes gescrapte Spiel hat `sonderereignis` (Text) und `status` (zusammengefasste Icon-Tooltips,
  z. B. "Spiel ist abgesetzt"). Werte außerhalb von `BEKANNTE_STATUS` (ergebnisse.py) gelten als
  Anomalie — Daten werden trotzdem gespeichert, nur zusätzlich gemeldet (kein Datenverlust).
- Änderungen an `datum`, `uhrzeit`, `spielstaette`, `status` gegenüber dem vorherigen DB-Stand
  landen automatisch in `spiel_historie` (unabhängig davon, ob der neue Wert bekannt ist).
- Bei jeder neuen Anomalie: Desktop-Toast (winotify) sofort + E-Mail an `NOTIFY_EMAIL_TO`.
  Bekannte, aber fachlich relevante Ereignisse (Absetzung, Verlegung) lösen aktuell bewusst
  KEINE Benachrichtigung aus — die landen nur in der Historie. Spätere Erweiterung möglich.
- Verworfener Ansatz: ein zweiter geplanter Cloud-Claude-Code-Task zum Erstellen einer sichtbaren
  Aufgabe — funktioniert nicht, da Cloud-Routinen keinen Zugriff auf lokale Dateien haben.
  Stattdessen E-Mail-Versand über Google Workspace SMTP (app@hoeinger-sv.de, App-Passwort).

## Stand
Voll funktionsfähig, End-to-End getestet inkl. Backfill von 2 Jahren echter Historendaten
(01.07.2024–heute, 331 Spiele, 125 Platzbelegungen, 327 Historie-Einträge, 0 offene Anomalien
nach Fixes). Login → Suche → Scraping → CSV-Export → Diff/Historie → DB-Upsert →
Anomalie-Check → Toast/E-Mail, headless, Duplikatsschutz.

- `Ergebnismeldung`: erreichbar über Hamburger-Menü, Button `#dfb-Menu-toggle` (NICHT per fester
  Pixel-Koordinate klicken — nach dem Scrollen zu Suchergebnissen verschiebt sich die Position,
  das hat beim Backfill-Test mehrere Fenster zum Scheitern gebracht).
- Spielstatus-Dropdown muss von Default "ohne Ergebnis" auf "alle Spiele" (`data-value="0"`)
  umgestellt werden, sonst fehlen Spiele mit Ergebnis.
- Tore: über `input[name='_kontext.spiele[N].ergebnis.toreHeim'/'toreGast']` auslesen — NICHT
  über `#toreHeim_N`/`#toreGast_N` (id), die ist bei Spielen mit Sonderwertung (z. B. Wertung nach
  Nichtantritt) doppelt vergeben (Hauptwertung + Sonderwertung teilen sich dieselbe id).
- Sonderereignis (td-Index 7): bei neueren/nicht bearbeitbaren Zeilen einfacher Text, bei
  bearbeitbaren (i. d. R. ältere) Zeilen ein Dropdown — dort NICHT `text_content()` der ganzen
  Zelle nehmen (klebt alle Optionen zusammen), sondern `input.dfb-Dropdown-combobox[value]`.
  "kein Sonderereignis" wird auf `""` normalisiert. Status-Icons (title-Attribut) = td-Index 8.
- `BEKANNTE_STATUS` (ergebnisse.py) enthält inzwischen auch: Annullierung, Ausfall,
  Nichtantritt Beide/Heim/Gast, Abbruch, Wertung der Spielinstanz, Sportgerichtsurteil —
  alle beim Backfill-Test über echte historische Daten entdeckt.
- Platzbelegung UND Spielstätte pro Spiel kommen aus dem CSV-Export (Button "Export" auf
  derselben Seite), nicht aus einem separaten "Spielstätten"-Menü. CSV ist UTF-16-kodiert,
  tab-getrennt (`platzbelegung.parse_csv`).
- Täglicher Task Scheduler-Eintrag `DFBnet Spielplus taeglich` (17:00 Uhr) ist eingerichtet.

Plan mit vollem Kontext: `C:\Users\Uli\.claude\plans\compiled-wandering-quill.md`
