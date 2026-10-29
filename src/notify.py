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
    beispiel = anomalien[0]["detail"].splitlines()[0]
    toast = Notification(
        app_id="DFBnet Spielplus",
        title=_titel(anomalien),
        msg=f"{beispiel}" + (" ..." if anzahl > 1 else ""),
    )
    toast.show()


def _titel(anomalien: list[dict]) -> str:
    """Kurzer Titel, der technische Fehler von unbekannten Werten unterscheidet."""
    fehler = sum(1 for a in anomalien if a["typ"] == "scraping_fehler")
    unbekannt = len(anomalien) - fehler
    teile = []
    if fehler:
        teile.append(f"{fehler} technische(r) Fehler")
    if unbekannt:
        teile.append(f"{unbekannt} unbekannte(r) Wert(e)")
    return "DFBnet Spielplus: " + " und ".join(teile)


def _formatiere_email_text(anomalien: list[dict]) -> str:
    zeilen = [
        f"- [{a['typ']}] Spiel {a.get('kontext') or '-'}: {a['detail'].splitlines()[0]}"
        for a in anomalien
    ]
    fehler = [a for a in anomalien if a["typ"] == "scraping_fehler"]
    unbekannt = [a for a in anomalien if a["typ"] != "scraping_fehler"]
    absaetze = []
    if fehler:
        absaetze.append(
            f"{len(fehler)} technische(r) Fehler beim DFBnet-Spielplus-Abgleich (auch nach "
            "automatischen Wiederholungsversuchen). Moegliche Ursachen: Portal/Netzwerk "
            "dauerhaft nicht erreichbar oder Portal-Struktur geaendert."
        )
    if unbekannt:
        absaetze.append(
            f"{len(unbekannt)} unbekannte(r) Wert(e) gefunden, auf die das Programm noch "
            "nicht vorbereitet ist."
        )
    zusammenfassung = "\n".join(absaetze) + "\n\n" + "\n".join(zeilen)

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
        "taeglichen automatisierten Lauf von src/run.py ein Problem aufgetreten. Technische "
        "Fehler (scraping_fehler) wurden bereits mehrfach automatisch wiederholt (siehe "
        "logs/run.log); pruefe zuerst, ob es sich um ein voruebergehendes Netzwerk-/Portal-"
        "Problem oder eine geaenderte Portal-Struktur handelt, indem du einen manuellen "
        "Testlauf machst. Bitte Ursache analysieren, mir die noetige "
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
    nachricht["Subject"] = _titel(anomalien)
    nachricht["From"] = SMTP_USER
    nachricht["To"] = NOTIFY_EMAIL_TO

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(nachricht)
    except Exception:
        log.exception("E-Mail-Benachrichtigung fehlgeschlagen")
