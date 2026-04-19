"""
SQLite persistence layer for UltraLine race data.

Single database: data/ultraline.db
Four tables: race_events, results, athletes, athlete_results

All writes are idempotent (INSERT OR REPLACE / INSERT OR IGNORE).
`fetched_at` on race_events drives resume logic — NULL means not yet scraped.
"""

import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "ultraline.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS race_events (
    event_id        INTEGER PRIMARY KEY,
    race_name       TEXT NOT NULL,
    country         TEXT,
    year            INTEGER,
    date_raw        TEXT,
    distance_value  REAL,
    distance_unit   TEXT,
    surface_type    TEXT,
    finisher_count  INTEGER,
    fetched_at      TEXT
);

CREATE TABLE IF NOT EXISTS results (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id            INTEGER NOT NULL REFERENCES race_events(event_id),
    athlete_id          INTEGER,
    place               INTEGER,
    finish_time         TEXT,
    finish_time_seconds INTEGER,
    name                TEXT,
    city_or_club        TEXT,
    country             TEXT,
    birth_year          INTEGER,
    gender              TEXT,
    gender_place        INTEGER,
    age_group           TEXT,
    age_group_place     INTEGER,
    performance_score   REAL,
    performance_time    TEXT
);

CREATE INDEX IF NOT EXISTS idx_results_event   ON results(event_id);
CREATE INDEX IF NOT EXISTS idx_results_athlete ON results(athlete_id);

CREATE TABLE IF NOT EXISTS athletes (
    athlete_id  INTEGER PRIMARY KEY,
    name        TEXT,
    country     TEXT,
    birth_year  INTEGER,
    fetched_at  TEXT
);

CREATE TABLE IF NOT EXISTS athlete_results (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id          INTEGER NOT NULL REFERENCES athletes(athlete_id),
    event_id            INTEGER,
    race_name           TEXT,
    year                INTEGER,
    distance_value      REAL,
    distance_unit       TEXT,
    place               INTEGER,
    finish_time_seconds INTEGER,
    dnf                 INTEGER DEFAULT 0,
    fetched_at          TEXT
);

CREATE INDEX IF NOT EXISTS idx_athlete_results_athlete ON athlete_results(athlete_id);
CREATE INDEX IF NOT EXISTS idx_athlete_results_event   ON athlete_results(event_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect(db_path: Path = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate(conn, table: str, new_cols: list):
    """Add missing columns to an existing table."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for col, typedef in new_cols:
        if col not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
            logger.info("Migrated %s: added column %s", table, col)


def init_db(db_path: Path = DB_PATH):
    """Create tables and indexes if they don't exist. Safe to run repeatedly."""
    from src.scrapers.duv import _parse_distance_text

    with connect(db_path) as conn:
        conn.executescript(SCHEMA)

        _migrate(conn, "race_events", [
            ("surface_type",   "TEXT"),
            ("distance_value", "REAL"),
            ("distance_unit",  "TEXT"),
        ])
        _migrate(conn, "athlete_results", [
            ("distance_value", "REAL"),
            ("distance_unit",  "TEXT"),
        ])

        # Backfill distance_value/unit from existing raw distance text
        for table in ("race_events", "athlete_results"):
            rows = conn.execute(
                f"SELECT rowid, distance FROM {table} "
                f"WHERE distance IS NOT NULL AND distance_value IS NULL"
            ).fetchall()
            for row in rows:
                value, unit = _parse_distance_text(row[1])
                if value is not None:
                    conn.execute(
                        f"UPDATE {table} SET distance_value=?, distance_unit=? WHERE rowid=?",
                        (value, unit, row[0]),
                    )
            if rows:
                logger.info("Backfilled distance_value/unit for %d %s rows", len(rows), table)

    logger.info("Database initialised at %s", db_path)


def apply_surface_index(surface_index: dict, db_path: Path = DB_PATH):
    """
    Bulk-update race_events.surface_type from a surface_index dict
    (event_id → surface_type) as returned by build_surface_index().
    Only updates rows where surface_type is currently NULL.
    """
    with connect(db_path) as conn:
        updated = 0
        for event_id, surface_type in surface_index.items():
            cursor = conn.execute(
                "UPDATE race_events SET surface_type = ? WHERE event_id = ? AND surface_type IS NULL",
                (surface_type, event_id),
            )
            updated += cursor.rowcount
    logger.info("apply_surface_index: updated %d rows", updated)
    return updated


def is_fetched(event_id: int, db_path: Path = DB_PATH) -> bool:
    """Return True if race_events.fetched_at is non-NULL for this event_id."""
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT fetched_at FROM race_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        return bool(row and row["fetched_at"])


def upsert_race_event(
    event_id: int,
    race_name: str,
    country: str = None,
    year: int = None,
    date_raw: str = None,
    distance_value: float = None,
    distance_unit: str = None,
    surface_type: str = None,
    finisher_count: int = None,
    mark_fetched: bool = False,
    db_path: Path = DB_PATH,
):
    fetched_at = _now() if mark_fetched else None
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO race_events
                (event_id, race_name, country, year, date_raw,
                 distance_value, distance_unit, surface_type, finisher_count, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                race_name      = excluded.race_name,
                country        = excluded.country,
                year           = COALESCE(excluded.year,           race_events.year),
                date_raw       = COALESCE(excluded.date_raw,       race_events.date_raw),
                distance_value = COALESCE(excluded.distance_value, race_events.distance_value),
                distance_unit  = COALESCE(excluded.distance_unit,  race_events.distance_unit),
                surface_type   = COALESCE(excluded.surface_type,   race_events.surface_type),
                finisher_count = COALESCE(excluded.finisher_count, race_events.finisher_count),
                fetched_at     = COALESCE(excluded.fetched_at,     race_events.fetched_at)
            """,
            (event_id, race_name, country, year, date_raw,
             distance_value, distance_unit, surface_type, finisher_count, fetched_at),
        )


def upsert_results(event_id: int, results: list, db_path: Path = DB_PATH):
    """
    Bulk-insert finisher rows for an event.
    Clears existing rows for this event_id first (idempotent re-fetch).
    `results` is the list[dict] returned by fetch_results().
    """
    with connect(db_path) as conn:
        conn.execute("DELETE FROM results WHERE event_id = ?", (event_id,))
        conn.executemany(
            """
            INSERT INTO results (
                event_id, athlete_id, place, finish_time, finish_time_seconds,
                name, city_or_club, country, birth_year, gender, gender_place,
                age_group, age_group_place, performance_score, performance_time
            ) VALUES (
                :event_id, :athlete_id, :place, :finish_time, :finish_time_seconds,
                :name, :city_or_club, :country, :birth_year, :gender, :gender_place,
                :age_group, :age_group_place, :performance_score, :performance_time
            )
            """,
            results,
        )


def upsert_athlete(
    athlete_id: int,
    name: str = None,
    country: str = None,
    birth_year: int = None,
    mark_fetched: bool = False,
    db_path: Path = DB_PATH,
):
    fetched_at = _now() if mark_fetched else None
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO athletes (athlete_id, name, country, birth_year, fetched_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(athlete_id) DO UPDATE SET
                name       = COALESCE(excluded.name, athletes.name),
                country    = COALESCE(excluded.country, athletes.country),
                birth_year = COALESCE(excluded.birth_year, athletes.birth_year),
                fetched_at = COALESCE(excluded.fetched_at, athletes.fetched_at)
            """,
            (athlete_id, name, country, birth_year, fetched_at),
        )


def upsert_athlete_results(athlete_id: int, rows: list, db_path: Path = DB_PATH):
    """
    Bulk-insert athlete history rows.
    Clears existing rows for this athlete_id first (idempotent re-fetch).
    `rows` is the list[dict] returned by fetch_athlete_history().
    """
    with connect(db_path) as conn:
        conn.execute("DELETE FROM athlete_results WHERE athlete_id = ?", (athlete_id,))
        fetched_at = _now()
        conn.executemany(
            """
            INSERT INTO athlete_results (
                athlete_id, event_id, race_name, year,
                distance_value, distance_unit,
                place, finish_time_seconds, dnf, fetched_at
            ) VALUES (
                :athlete_id, :event_id, :race_name, :year,
                :distance_value, :distance_unit,
                :place, :finish_time_seconds, :dnf, :fetched_at
            )
            """,
            [{**r, "fetched_at": fetched_at} for r in rows],
        )


def athlete_ids_for_race(race_name: str, db_path: Path = DB_PATH) -> list:
    """Return distinct athlete_ids for all finishers of a given race (all years)."""
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT r.athlete_id
            FROM results r
            JOIN race_events e ON r.event_id = e.event_id
            WHERE e.race_name = ? AND r.athlete_id IS NOT NULL
            """,
            (race_name,),
        ).fetchall()
        return [row["athlete_id"] for row in rows]


def unfetched_athlete_ids(race_name: str, db_path: Path = DB_PATH) -> list:
    """Return athlete_ids for a race whose athlete history has not yet been scraped."""
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT r.athlete_id
            FROM results r
            JOIN race_events e ON r.event_id = e.event_id
            LEFT JOIN athletes a ON r.athlete_id = a.athlete_id
            WHERE e.race_name = ?
              AND r.athlete_id IS NOT NULL
              AND a.fetched_at IS NULL
            """,
            (race_name,),
        ).fetchall()
        return [row["athlete_id"] for row in rows]
