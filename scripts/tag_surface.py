"""
Bulk-tag races in races.json and race_events (SQLite) with surface type.

Queries DUV's event list for each surface type (Road, Trail, Track, etc.)
and records which event_ids belong to which surface. Cross-references against
races.json to update each race entry with a 'surface' field, and updates
race_events.surface_type in SQLite.

Usage:
    python scripts/tag_surface.py                          # all surface types, all pages
    python scripts/tag_surface.py --surfaces Road Trail    # only road + trail
    python scripts/tag_surface.py --pages 10               # first 10 pages per surface (testing)
    python scripts/tag_surface.py --db-only                # update SQLite only, skip races.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.scrapers.duv import build_surface_index, DUV_SURFACE_FILTERS
from src.data.db import init_db, apply_surface_index, DB_PATH

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR   = Path(__file__).resolve().parents[1] / "data"
RACES_FILE = DATA_DIR / "races.json"


def update_races_json(surface_index: dict, races_file: Path = RACES_FILE) -> int:
    """
    Add/update the 'surface' field on each race in races.json.
    A race gets tagged if ANY of its duv_event_ids is in the surface_index.
    If a race spans multiple surface types (rare), all found types are recorded.
    Returns the number of races updated.
    """
    races = json.loads(races_file.read_text())
    updated = 0

    for race in races:
        surfaces = set()
        for eid in race.get("duv_event_ids", []):
            if eid in surface_index:
                surfaces.add(surface_index[eid])

        if surfaces:
            new_surface = surfaces.pop() if len(surfaces) == 1 else ",".join(sorted(surfaces))
            if race.get("surface") != new_surface:
                race["surface"] = new_surface
                updated += 1
        elif "surface" not in race:
            race["surface"] = None  # explicitly mark as unclassified

    races_file.write_text(json.dumps(races, indent=2))
    logger.info("races.json: %d races updated with surface type", updated)
    return updated


def main():
    parser = argparse.ArgumentParser(description="Tag races with DUV surface type")
    parser.add_argument(
        "--surfaces", nargs="+", default=DUV_SURFACE_FILTERS,
        help=f"Surface filters to query (default: all). Choices: {DUV_SURFACE_FILTERS}",
    )
    parser.add_argument("--pages",   type=int, default=None, help="Max pages per surface (default: all)")
    parser.add_argument("--delay",   type=float, default=1.0, help="Seconds between requests")
    parser.add_argument("--db",      default=str(DB_PATH),   help="SQLite database path")
    parser.add_argument("--db-only", action="store_true",    help="Skip races.json update")
    args = parser.parse_args()

    db_path = Path(args.db)
    init_db(db_path)

    logger.info("Building surface index for: %s", args.surfaces)
    surface_index = build_surface_index(
        surface_filters=args.surfaces,
        max_pages=args.pages,
        delay=args.delay,
    )
    logger.info("Surface index built: %d event_ids classified", len(surface_index))

    # Update SQLite
    db_updated = apply_surface_index(surface_index, db_path)
    print(f"SQLite: {db_updated} race_events rows updated")

    # Update races.json
    if not args.db_only:
        json_updated = update_races_json(surface_index)
        print(f"races.json: {json_updated} races updated")

    # Summary
    from collections import Counter
    counts = Counter(surface_index.values())
    print("\nSurface type breakdown:")
    for surface, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {surface:12s}: {count:,} events")


if __name__ == "__main__":
    main()
