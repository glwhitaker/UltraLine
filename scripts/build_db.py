"""
One-time migration: load existing JSON race history files into SQLite.

Usage:
    python scripts/build_db.py                    # migrate all JSON files found
    python scripts/build_db.py --migrate-only     # same as above (explicit)
    python scripts/build_db.py --db data/alt.db   # write to a different DB path
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.db import init_db, upsert_race_event, upsert_results, DB_PATH

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HISTORY_DIR = Path(__file__).resolve().parents[1] / "data" / "race_history"


def migrate_json_file(path: Path, db_path: Path):
    logger.info("Migrating %s …", path.name)
    data = json.loads(path.read_text())
    race_name = data.get("race_name", path.stem)
    country   = data.get("country", "")
    total     = 0

    for year_entry in data.get("years", []):
        eid           = year_entry["event_id"]
        results       = year_entry.get("results", [])
        finisher_count = year_entry.get("finisher_count", len(results))

        upsert_race_event(
            eid,
            race_name=race_name,
            country=country,
            year=year_entry.get("year"),
            date_raw=year_entry.get("date_raw"),
            finisher_count=finisher_count,
            mark_fetched=True,
            db_path=db_path,
        )
        upsert_results(eid, results, db_path)
        total += len(results)

    logger.info("  → %d years, %d finishers", len(data.get("years", [])), total)
    return total


def main():
    parser = argparse.ArgumentParser(description="Migrate race history JSON files into SQLite")
    parser.add_argument("--db",           default=str(DB_PATH), help="SQLite database path")
    parser.add_argument("--migrate-only", action="store_true",  help="No-op flag (migration is the default)")
    args = parser.parse_args()

    db_path = Path(args.db)
    init_db(db_path)

    json_files = sorted(HISTORY_DIR.glob("*.json"))
    if not json_files:
        logger.warning("No JSON files found in %s", HISTORY_DIR)
        return

    grand_total = 0
    for path in json_files:
        grand_total += migrate_json_file(path, db_path)

    print(f"\nMigrated {len(json_files)} file(s), {grand_total} total finisher rows → {db_path}")


if __name__ == "__main__":
    main()
