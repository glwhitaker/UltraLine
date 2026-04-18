"""
Race list loader.

Reads data/races.json (built by scripts/build_race_list.py) and exposes
a filtered, sorted list ready for use in Streamlit selectbox inputs.
"""

import json
from pathlib import Path

import streamlit as st

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "races.json"


@st.cache_data
def load_races(confirmed_only: bool = True) -> list[dict]:
    """
    Load races from data/races.json.

    Args:
        confirmed_only: If True (default), return only races where has_results=True.

    Returns:
        List of race dicts sorted alphabetically by name.
    """
    with open(_DATA_PATH) as f:
        races = json.load(f)

    if confirmed_only:
        races = [r for r in races if r.get("has_results")]

    return sorted(races, key=lambda r: r["name"].lower())


def race_label(race: dict) -> str:
    """Display label shown in the selectbox."""
    country = race.get("country", "")
    return f"{race['name']}  —  {country}" if country else race["name"]
