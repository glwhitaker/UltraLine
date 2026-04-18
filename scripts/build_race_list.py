"""
Build data/races.json from DUV (statistik.d-u-v.org).

115,688 events across ~116 pages. Results are confirmed via finisher count —
no per-race HTTP validation needed. Full build takes ~2 minutes.

Usage:
  python scripts/build_race_list.py               # full build
  python scripts/build_race_list.py --pages 5     # first 5 pages (~5k events), for testing
  python scripts/build_race_list.py --limit 100   # cap output to 100 races
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.scrapers.duv import fetch_all_events, group_into_races

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "races.json"


def build(max_pages: int = None, limit: int = None):
    logger.info("Fetching events from DUV...")
    events = fetch_all_events(max_pages=max_pages)
    logger.info("Fetched %d raw event instances", len(events))

    races = group_into_races(events)
    logger.info("Grouped into %d unique races", len(races))

    if limit:
        races = races[:limit]

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(races, f, indent=2)

    with_results = sum(1 for r in races if r["has_results"])
    logger.info("Saved %d races (%d with confirmed results) → %s", len(races), with_results, OUTPUT_PATH)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=None, help="Max pages to scrape (default: all)")
    parser.add_argument("--limit", type=int, default=None, help="Cap output races")
    args = parser.parse_args()
    build(max_pages=args.pages, limit=args.limit)
