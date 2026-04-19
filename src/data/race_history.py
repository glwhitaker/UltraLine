"""
Race history fetcher.

Pulls all available year-by-year results for a named race from DUV,
using the event IDs stored in data/races.json.

Writes each event to SQLite (data/ultraline.db) immediately after fetching,
so the scraper can be interrupted and resumed without re-fetching.

JSON files in data/race_history/ are still written for debugging and
offline inspection, but SQLite is the source of truth.
"""

import json
import logging
import re
import time
from pathlib import Path

from src.scrapers.duv import fetch_event_metadata, fetch_results
from src.data.db import (
    init_db,
    is_fetched,
    upsert_race_event,
    upsert_results,
    DB_PATH,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RACES_FILE = DATA_DIR / "races.json"
HISTORY_DIR = DATA_DIR / "race_history"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _load_race(race_name: str, races_file: Path = RACES_FILE) -> dict:
    races = json.loads(races_file.read_text())
    needle = race_name.lower().strip()
    for race in races:
        if race["name"].lower().strip() == needle:
            return race
    raise ValueError(f"Race not found in {races_file}: {race_name!r}")


def fetch_race_history(
    race_name: str,
    races_file: Path = RACES_FILE,
    db_path=DB_PATH,
    delay: float = 1.5,
    max_years=None,
    skip_empty: bool = True,
    resume: bool = True,
) -> dict:
    """
    Fetch full year-by-year result history for a named race.

    Args:
        race_name:  Exact name as it appears in races.json (case-insensitive).
        races_file: Path to races.json.
        db_path:    SQLite database path.
        delay:      Seconds between HTTP requests.
        max_years:  Cap on how many years to fetch (None = all).
        skip_empty: Skip event_ids that return zero rows.
        resume:     If True, skip event_ids already recorded in SQLite.

    Returns:
        History dict (same schema as before, sorted oldest-first).
    """
    init_db(db_path)
    race = _load_race(race_name, races_file)
    event_ids = race["duv_event_ids"]
    if max_years:
        event_ids = event_ids[:max_years]

    history = {
        "race_name": race["name"],
        "country":   race["country"],
        "years":     [],
    }

    for i, eid in enumerate(event_ids):
        if resume and is_fetched(eid, db_path):
            logger.info("[%d/%d] event_id=%d already in DB — skipping", i + 1, len(event_ids), eid)
            continue

        logger.info("[%d/%d] Fetching event_id=%d …", i + 1, len(event_ids), eid)

        # Register the event stub first so partial failures are recoverable
        upsert_race_event(
            eid,
            race_name=race["name"],
            country=race["country"],
            db_path=db_path,
        )

        meta = fetch_event_metadata(eid)
        time.sleep(delay)

        results = fetch_results(eid)
        time.sleep(delay)

        if skip_empty and not results:
            logger.warning("  event_id=%d returned 0 rows — skipping", eid)
            continue

        # Write to SQLite immediately
        upsert_race_event(
            eid,
            race_name=race["name"],
            country=meta.get("country", race["country"]),
            year=meta.get("year"),
            date_raw=meta.get("date_raw"),
            distance_value=meta.get("distance_value"),
            distance_unit=meta.get("distance_unit"),
            surface_type=meta.get("surface_type"),
            finisher_count=len(results),
            mark_fetched=True,
            db_path=db_path,
        )
        upsert_results(eid, results, db_path)

        year_entry = {
            "event_id":       eid,
            "year":           meta.get("year"),
            "date_raw":       meta.get("date_raw"),
            "finisher_count": len(results),
            "results":        results,
        }
        history["years"].append(year_entry)
        logger.info("  → %d finishers (year=%s)", len(results), meta.get("year"))

    # Sort years ascending so index[0] is oldest
    history["years"].sort(key=lambda y: (y["year"] or 0, y["event_id"]))
    return history


def save_race_history(history: dict, out_dir: Path = HISTORY_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug(history["race_name"])
    out_path = out_dir / f"{slug}.json"
    out_path.write_text(json.dumps(history, indent=2))
    logger.info("Saved → %s", out_path)
    return out_path


def load_race_history(race_name: str, history_dir: Path = HISTORY_DIR) -> dict:
    slug = _slug(race_name)
    path = history_dir / f"{slug}.json"
    if not path.exists():
        raise FileNotFoundError(f"No history file at {path}. Run fetch first.")
    return json.loads(path.read_text())
