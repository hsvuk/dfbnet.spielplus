import sqlite3
from contextlib import contextmanager

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS spiele (
    spiel_nr TEXT PRIMARY KEY,
    datum TEXT NOT NULL,
    uhrzeit TEXT,
    heimmannschaft TEXT,
    gastmannschaft TEXT,
    ergebnis TEXT,
    wettbewerb TEXT,
    staffel TEXT,
    spielstaette TEXT,
    spielstaette_nr TEXT,
    sonderereignis TEXT,
    status TEXT,
    aktualisiert_am TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS platzbelegung (
    id TEXT PRIMARY KEY,
    sportstaette_nr TEXT NOT NULL,
    datum TEXT NOT NULL,
    uhrzeit_von TEXT,
    uhrzeit_bis TEXT,
    belegt_durch TEXT,
    aktualisiert_am TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS spiel_historie (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spiel_nr TEXT NOT NULL,
    feld TEXT NOT NULL,
    alter_wert TEXT,
    neuer_wert TEXT,
    erkannt_am TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS anomalien (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    erkannt_am TEXT NOT NULL DEFAULT (datetime('now')),
    typ TEXT NOT NULL,
    kontext TEXT,
    detail TEXT,
    gemeldet INTEGER NOT NULL DEFAULT 0
);
"""

# Felder, deren Aenderung in spiel_historie protokolliert wird.
HISTORISIERTE_FELDER = ["datum", "uhrzeit", "spielstaette", "status"]


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    finally:
        conn.close()


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, coltype: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        for column in ("spielstaette", "spielstaette_nr", "sonderereignis", "status"):
            _add_column_if_missing(conn, "spiele", column, "TEXT")


def upsert_spiel(conn: sqlite3.Connection, spiel: dict) -> None:
    conn.execute(
        """
        INSERT INTO spiele (spiel_nr, datum, uhrzeit, heimmannschaft, gastmannschaft,
                             ergebnis, wettbewerb, staffel, spielstaette, spielstaette_nr,
                             sonderereignis, status, aktualisiert_am)
        VALUES (:spiel_nr, :datum, :uhrzeit, :heimmannschaft, :gastmannschaft,
                :ergebnis, :wettbewerb, :staffel, :spielstaette, :spielstaette_nr,
                :sonderereignis, :status, datetime('now'))
        ON CONFLICT(spiel_nr) DO UPDATE SET
            datum=excluded.datum,
            uhrzeit=excluded.uhrzeit,
            heimmannschaft=excluded.heimmannschaft,
            gastmannschaft=excluded.gastmannschaft,
            ergebnis=excluded.ergebnis,
            wettbewerb=excluded.wettbewerb,
            staffel=excluded.staffel,
            spielstaette=excluded.spielstaette,
            spielstaette_nr=excluded.spielstaette_nr,
            sonderereignis=excluded.sonderereignis,
            status=excluded.status,
            aktualisiert_am=datetime('now')
        """,
        spiel,
    )


def record_historie(conn: sqlite3.Connection, spiel_nr: str, feld: str, alter_wert, neuer_wert) -> None:
    conn.execute(
        """
        INSERT INTO spiel_historie (spiel_nr, feld, alter_wert, neuer_wert, erkannt_am)
        VALUES (?, ?, ?, ?, datetime('now'))
        """,
        (spiel_nr, feld, alter_wert, neuer_wert),
    )


def diff_and_upsert_spiel(conn: sqlite3.Connection, spiel: dict) -> None:
    """Vergleicht ueberwachte Felder mit dem bestehenden Stand, protokolliert Aenderungen
    in spiel_historie und upserted anschliessend den neuen Stand."""
    bestehend = conn.execute(
        "SELECT * FROM spiele WHERE spiel_nr = ?", (spiel["spiel_nr"],)
    ).fetchone()

    if bestehend is not None:
        spalten = [d[0] for d in conn.execute("SELECT * FROM spiele LIMIT 0").description]
        alter_stand = dict(zip(spalten, bestehend))
        for feld in HISTORISIERTE_FELDER:
            alt = alter_stand.get(feld)
            neu = spiel.get(feld)
            if alt != neu and (alt or neu):
                record_historie(conn, spiel["spiel_nr"], feld, alt, neu)

    upsert_spiel(conn, spiel)


def upsert_platzbelegung(conn: sqlite3.Connection, eintrag: dict) -> None:
    conn.execute(
        """
        INSERT INTO platzbelegung (id, sportstaette_nr, datum, uhrzeit_von, uhrzeit_bis,
                                    belegt_durch, aktualisiert_am)
        VALUES (:id, :sportstaette_nr, :datum, :uhrzeit_von, :uhrzeit_bis,
                :belegt_durch, datetime('now'))
        ON CONFLICT(id) DO UPDATE SET
            datum=excluded.datum,
            uhrzeit_von=excluded.uhrzeit_von,
            uhrzeit_bis=excluded.uhrzeit_bis,
            belegt_durch=excluded.belegt_durch,
            aktualisiert_am=datetime('now')
        """,
        eintrag,
    )


def record_anomalie(conn: sqlite3.Connection, typ: str, kontext: str | None, detail: str) -> None:
    conn.execute(
        """
        INSERT INTO anomalien (erkannt_am, typ, kontext, detail, gemeldet)
        VALUES (datetime('now'), ?, ?, ?, 0)
        """,
        (typ, kontext, detail),
    )


def offene_anomalien(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, erkannt_am, typ, kontext, detail FROM anomalien WHERE gemeldet = 0 ORDER BY id"
    ).fetchall()
    spalten = ["id", "erkannt_am", "typ", "kontext", "detail"]
    return [dict(zip(spalten, row)) for row in rows]


def markiere_gemeldet(conn: sqlite3.Connection, anomalie_ids: list[int]) -> None:
    conn.executemany("UPDATE anomalien SET gemeldet = 1 WHERE id = ?", [(i,) for i in anomalie_ids])
