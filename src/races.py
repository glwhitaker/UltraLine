"""
Race list loaders.

load_curated_races() — data/curated_races.json, ~55 popular races with full
    course specs (distance, elevation gain/loss, surface, month). Used for
    the target race selector and auto-fill in the Streamlit UI.

load_races() — data/races.json, the full ~35k DUV race index. Kept for
    reference and future use; not currently shown in the UI.
"""

import json
from pathlib import Path

import streamlit as st

_CURATED_PATH = Path(__file__).resolve().parent.parent / "data" / "curated_races.json"
_DATA_PATH    = Path(__file__).resolve().parent.parent / "data" / "races.json"


@st.cache_data
def load_curated_races() -> list[dict]:
    """
    Load the curated race list from data/curated_races.json.

    Returns races sorted by region then name, ready for the target race
    selectbox. Each entry has: name, country, region, distance_mi,
    elevation_gain_ft, elevation_loss_ft, surface, typical_month.
    """
    with open(_CURATED_PATH) as f:
        races = json.load(f)
    return sorted(races, key=lambda r: (r["region"], r["name"].lower()))


@st.cache_data
def load_races(confirmed_only: bool = True) -> list[dict]:
    """Load the full DUV race index from data/races.json."""
    if not _DATA_PATH.exists():
        return []
    with open(_DATA_PATH) as f:
        races = json.load(f)
    if confirmed_only:
        races = [r for r in races if r.get("has_results")]
    return sorted(races, key=lambda r: r["name"].lower())


def curated_race_label(race: dict) -> str:
    """Display label for the curated selectbox: 'Name — Country (distance)'."""
    dist = f"{race['distance_mi']:.0f} mi"
    return f"{race['name']}  —  {race.get('country', '')}  ({dist})"


def race_label(race: dict) -> str:
    """Display label for the DUV race selectbox."""
    country = race.get("country", "")
    return f"{race['name']}  —  {country}" if country else race["name"]
