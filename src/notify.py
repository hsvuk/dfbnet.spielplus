"""Benachrichtigung bei neuen Anomalien: Desktop-Toast + E-Mail."""

import logging
import smtplib
from email.mime.text import MIMEText

from winotify import Notification

from config import NOTIFY_EMAIL_TO, ROOT_DIR, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER

log = logging.getLogger("notify")


def benachrichtige_anomalien(anomalien: list[dict]) -> None:
    if not anomalien:
        return

    anzahl = len(anomalien)
    beispiel = anomalien[0]["detail"]
    toast = Notification(
        app_id="DFBnet Spielplus",
        title=f"{anzahl} unbekannte(r) Wert(e) beim DFBnet-Abgleich",
        msg=f"{beispiel}" + (" ..." if anzahl > 1 else ""),
    )
    toast.show()


def _formatiere_email_text(anomalien: list[dict]) -> str:
    zeilen = [
        f"- [{a['typ']}] Spiel {a.get('kontext') or '-'}: {a['detail'].splitlines()[0]}"
        for a in anomalien
    ]
    zusammenfassung = (
        f"Beim DFBnet-Spielplus-Abgleich wurden {len(anomalien)} unbekannte "
        "Wert(e) gefunden, auf die das Programm noch nicht vorbereitet ist.\n\n"
        + "\n".join(zeilen)
    )

    return (
        zusammenfassung
        + "\n\n"
        + "=" * 70
        + "\nPROMPT FUER CLAUDE CODE (unten 1:1 kopieren und einfuegen):\n"
        + "=" * 70
        + "\n\n"
        + _formatiere_claude_prompt(anomalien)
    )


def _formatiere_claude_prompt(anomalien: list[dict]) -> str:
    bloecke = []
    for a in anomalien:
        bloecke.append(
            f"### Anomalie {a['typ']} (Spiel {a.get('kontext') or '-'})\n"
            f"Erkannt in Schritt: {a.get('schritt', 'unbekannt')}\n"
            f"Detail:\n{a['detail']}"
        )

    return (
        f"Im Projekt {ROOT_DIR} (lokale DFBnet-Spielplus-Automatisierung, Windows) ist beim "
        "taeglichen automatisierten Lauf von src/run.py ein Problem aufgetreten, auf das der "
        "Scraper noch nicht vorbereitet ist. Bitte Ursache analysieren, mir die noetige "
        "Codeaenderung erklaeren und nach meiner Bestaetigung umsetzen.\n\n"
        f"Anzahl Anomalien: {len(anomalien)}\n\n"
        + "\n\n".join(bloecke)
        + "\n\n"
        "Kontext zum Projekt (Architektur, bekannte Selektoren, DB-Schema) steht in "
        f"{ROOT_DIR}\\CLAUDE.md. Relevante Dateien je nach Anomalie-Typ:\n"
        "- 'unbekannter_status': src/ergebnisse.py (Konstante BEKANNTE_STATUS erweitern und "
        "pruefen, ob der neue Status sinnvoll in db.HISTORISIERTE_FELDER/Historie abgebildet ist)\n"
        "- 'scraping_fehler' bei DB-Speicherung: src/db.py (diff_and_upsert_spiel, Schema)\n"
        "- 'scraping_fehler' bei Login/Navigation/Scraping: src/login.py bzw. src/ergebnisse.py "
        "(Playwright-Selektoren, evtl. hat sich das DFBnet-Portal geaendert)\n\n"
        "Nach der Anpassung bitte mit einem manuellen Testlauf "
        "(venv\\Scripts\\python.exe src\\run.py) verifizieren."
    )


def sende_email_anomalien(anomalien: list[dict]) -> None:
    if not anomalien:
        return

    if not (SMTP_USER and SMTP_PASSWORD and NOTIFY_EMAIL_TO):
        log.warning(
            "E-Mail-Benachrichtigung uebersprungen: SMTP_USER/SMTP_PASSWORD/"
            "NOTIFY_EMAIL_TO nicht vollstaendig in .env gesetzt."
        )
        return

    nachricht = MIMEText(_formatiere_email_text(anomalien), "plain", "utf-8")
    nachricht["Subject"] = f"DFBnet Spielplus: {len(anomalien)} unbekannte(r) Wert(e) erkannt"
    nachricht["From"] = SMTP_USER
    nachricht["To"] = NOTIFY_EMAIL_TO

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(nachricht)
    except Exception:
        log.exception("E-Mail-Benachrichtigung fehlgeschlagen")
