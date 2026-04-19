"""
CLI to pull year-by-year results for a named race and save to data/race_history/.

Usage:
    python scripts/fetch_race_history.py "Badwater Ultramarathon"
    python scripts/fetch_race_history.py "Badwater Ultramarathon" --years 5
    python scripts/fetch_race_history.py "Badwater Ultramarathon" --delay 2.0
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.race_history import fetch_race_history, save_race_history

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Fetch DUV race history for one race")
    parser.add_argument("race_name", help='Race name as in races.json, e.g. "Badwater Ultramarathon"')
    parser.add_argument("--years",  type=int, default=None, help="Max years to fetch (default: all)")
    parser.add_argument("--delay",  type=float, default=1.5, help="Seconds between requests (default: 1.5)")
    args = parser.parse_args()

    history = fetch_race_history(
        race_name=args.race_name,
        delay=args.delay,
        max_years=args.years,
    )
    out_path = save_race_history(history)

    total_finishers = sum(y["finisher_count"] for y in history["years"])
    print(f"\nDone. {len(history['years'])} years, {total_finishers} total finishers.")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
