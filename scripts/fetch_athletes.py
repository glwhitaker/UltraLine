"""
Fetch athlete personal histories for all athletes found in a given race.

Scrapes getresultperson.php for each unique athlete_id, capturing their full
DUV result history (all races, all years) including DNF flags.

Usage:
    python scripts/fetch_athletes.py --race "Badwater Ultramarathon"
    python scripts/fetch_athletes.py --race "Badwater Ultramarathon" --limit 50
    python scripts/fetch_athletes.py --race "Badwater Ultramarathon" --delay 2.0
    python scripts/fetch_athletes.py --race "Badwater Ultramarathon" --no-resume
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.db import (
    init_db,
    unfetched_athlete_ids,
    upsert_athlete,
    upsert_athlete_results,
    DB_PATH,
)
from src.scrapers.duv import fetch_athlete_history

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Fetch athlete histories for a race")
    parser.add_argument("--race",      required=True, help='Race name as in races.json')
    parser.add_argument("--limit",     type=int, default=None, help="Max athletes to fetch")
    parser.add_argument("--delay",     type=float, default=1.5, help="Seconds between requests")
    parser.add_argument("--no-resume", action="store_true",  help="Ignore already-fetched athletes")
    parser.add_argument("--db",        default=str(DB_PATH), help="SQLite database path")
    args = parser.parse_args()

    db_path = Path(args.db)
    init_db(db_path)

    if args.no_resume:
        from src.data.db import athlete_ids_for_race
        athlete_ids = athlete_ids_for_race(args.race, db_path)
    else:
        athlete_ids = unfetched_athlete_ids(args.race, db_path)

    if args.limit:
        athlete_ids = athlete_ids[: args.limit]

    total = len(athlete_ids)
    logger.info("%d athletes to fetch for %r", total, args.race)

    fetched, errors = 0, 0
    for i, aid in enumerate(athlete_ids):
        logger.info("[%d/%d] athlete_id=%d …", i + 1, total, aid)
        try:
            data = fetch_athlete_history(aid)
            time.sleep(args.delay)

            upsert_athlete(
                aid,
                name=data.get("name"),
                country=data.get("country"),
                birth_year=data.get("birth_year"),
                mark_fetched=True,
                db_path=db_path,
            )
            upsert_athlete_results(aid, data.get("results", []), db_path)

            result_count = len(data.get("results", []))
            dnf_count    = sum(1 for r in data.get("results", []) if r.get("dnf"))
            logger.info("  → %d races, %d DNFs", result_count, dnf_count)
            fetched += 1

        except Exception as exc:
            logger.error("  FAILED athlete_id=%d: %s", aid, exc)
            errors += 1

    print(f"\nDone. {fetched} athletes fetched, {errors} errors.")


if __name__ == "__main__":
    main()
