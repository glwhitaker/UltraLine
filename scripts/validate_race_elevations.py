"""
Validate curated_races.json elevation consistency.

For every race, the constraint is:
    gain - loss == finish_elevation - start_elevation

For loop / out-and-back courses start == finish, so gain must equal loss.
For point-to-point courses the difference should match the net change.

Usage:
    python scripts/validate_race_elevations.py
    python scripts/validate_race_elevations.py --tolerance 300
"""

import argparse
import json
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "curated_races.json"


def validate(tolerance: int = 500):
    races = json.loads(DATA_PATH.read_text())

    flagged = []
    ok = []

    for r in races:
        gain        = r["elevation_gain_ft"]
        loss        = r["elevation_loss_ft"]
        start       = r["start_elevation_ft"]
        finish      = r["finish_elevation_ft"]
        net_data    = gain - loss
        net_expected = finish - start
        delta       = abs(net_data - net_expected)

        entry = {
            "name":         r["name"],
            "gain":         gain,
            "loss":         loss,
            "net_data":     net_data,
            "net_expected": net_expected,
            "delta":        delta,
            "start":        start,
            "finish":       finish,
        }

        if delta > tolerance:
            flagged.append(entry)
        else:
            ok.append(entry)

    print(f"\nElevation Consistency Report  (tolerance ±{tolerance} ft)")
    print(f"{'─' * 60}")
    print(f"  Passed : {len(ok)}")
    print(f"  Flagged: {len(flagged)}")
    print()

    if flagged:
        print("FLAGGED — gain/loss inconsistent with start/finish elevations:\n")
        for e in sorted(flagged, key=lambda x: -x["delta"]):
            print(f"  {e['name']}")
            print(f"    gain={e['gain']:,}  loss={e['loss']:,}  → net {e['net_data']:+,} ft")
            print(f"    start={e['start']:,}  finish={e['finish']:,}  → expected net {e['net_expected']:+,} ft")
            print(f"    delta = {e['delta']:,} ft")
            if e["net_expected"] != 0:
                suggested_loss = e["gain"] - e["net_expected"]
                print(f"    suggested fix: loss = {suggested_loss:,} ft  (if gain is correct)")
            print()
    else:
        print("All races passed.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tolerance", type=int, default=500,
                        help="Max acceptable |net_data - net_expected| in feet (default 500)")
    args = parser.parse_args()
    validate(args.tolerance)
