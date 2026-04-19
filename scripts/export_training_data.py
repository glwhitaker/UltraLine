"""
Derive Parquet training matrices from SQLite.

Usage:
    python scripts/export_training_data.py
    python scripts/export_training_data.py --race "Western States 100 Mile Endurance Run"
    python scripts/export_training_data.py --db data/alt.db
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.export import export_population_results, export_athlete_features, export_model_data
from src.data.db import DB_PATH

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Export SQLite data to Parquet training matrices")
    parser.add_argument("--race", default="Badwater Ultramarathon", help="Race for model_data export")
    parser.add_argument("--db",   default=str(DB_PATH), help="SQLite database path")
    args = parser.parse_args()

    db_path = Path(args.db)

    p1 = export_population_results(db_path)
    p2 = export_athlete_features(db_path)
    p3 = export_model_data(args.race, db_path)

    print(f"\nExported:")
    print(f"  {p1}")
    print(f"  {p2}")
    print(f"  {p3}")


if __name__ == "__main__":
    main()
