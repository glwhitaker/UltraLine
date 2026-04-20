"""
Validation tests for DUV race history fetching and parsing.

Two test layers:
  Unit tests   — no network; validate parsing logic on synthetic / cached inputs.
  Integration  — live HTTP; marked @pytest.mark.integration; skipped by default.

Run all:        pytest tests/test_race_history.py -v
Run unit only:  pytest tests/test_race_history.py -v -m "not integration"
Run full suite: pytest tests/test_race_history.py -v -m integration
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.scrapers.duv import _parse_finish_time_seconds, _parse_result_row, fetch_results, fetch_event_metadata
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cells(values: list):
    """Build a list of fake td elements from plain strings."""
    html = "<table>" + "".join(f"<td>{v}</td>" for v in values) + "</table>"
    soup = BeautifulSoup(html, "html.parser")
    return soup.find_all("td")


def _make_cells_with_link(values: list, name_idx: int = 2, runner_id: int = 12345):
    """Build fake cells where the name cell contains a runner link."""
    parts = []
    for i, v in enumerate(values):
        if i == name_idx:
            parts.append(f'<td><a href="getresultperson.php?runner={runner_id}">{v}</a></td>')
        else:
            parts.append(f"<td>{v}</td>")
    html = "<table>" + "".join(parts) + "</table>"
    soup = BeautifulSoup(html, "html.parser")
    return soup.find_all("td")


# ---------------------------------------------------------------------------
# Unit: _parse_finish_time_seconds
# ---------------------------------------------------------------------------

class TestParseFinishTimeSeconds:
    def test_standard_hms(self):
        assert _parse_finish_time_seconds("21:47:45 h") == 21 * 3600 + 47 * 60 + 45

    def test_no_suffix(self):
        assert _parse_finish_time_seconds("21:47:45") == 21 * 3600 + 47 * 60 + 45

    def test_zero(self):
        assert _parse_finish_time_seconds("00:00:00 h") == 0

    def test_over_24h(self):
        assert _parse_finish_time_seconds("46:40:06 h") == 46 * 3600 + 40 * 60 + 6

    def test_empty_string(self):
        assert _parse_finish_time_seconds("") is None

    def test_none_input(self):
        assert _parse_finish_time_seconds(None) is None

    def test_garbage(self):
        assert _parse_finish_time_seconds("DNF") is None

    def test_four_part_format(self):
        # D:HH:MM:SS edge case
        assert _parse_finish_time_seconds("1:02:03:04") == 86400 + 2 * 3600 + 3 * 60 + 4


# ---------------------------------------------------------------------------
# Unit: _parse_result_row
# ---------------------------------------------------------------------------

SAMPLE_ROW_VALUES = [
    "1",            # place
    "21:47:45 h",   # finish_time
    "Holvik, Simen",# name
    "*Hundvaag",    # city_or_club
    "NOR",          # country
    "1977",         # birth_year
    "M",            # gender
    "1",            # gender_place
    "M45",          # age_group
    "1",            # age_group_place
    "9.968",        # performance_score
    "19:47:11 h",   # performance_time
]


class TestParseResultRow:
    def test_returns_dict_for_valid_row(self):
        cells = _make_cells_with_link(SAMPLE_ROW_VALUES, name_idx=2, runner_id=779063)
        result = _parse_result_row(cells, event_id=110363)
        assert result is not None
        assert isinstance(result, dict)

    def test_place_parsed_as_int(self):
        cells = _make_cells_with_link(SAMPLE_ROW_VALUES)
        r = _parse_result_row(cells, event_id=110363)
        assert r["place"] == 1

    def test_finish_time_preserved(self):
        cells = _make_cells_with_link(SAMPLE_ROW_VALUES)
        r = _parse_result_row(cells, event_id=110363)
        assert r["finish_time"] == "21:47:45 h"

    def test_finish_time_seconds_computed(self):
        cells = _make_cells_with_link(SAMPLE_ROW_VALUES)
        r = _parse_result_row(cells, event_id=110363)
        assert r["finish_time_seconds"] == 21 * 3600 + 47 * 60 + 45

    def test_name_extracted(self):
        cells = _make_cells_with_link(SAMPLE_ROW_VALUES, runner_id=779063)
        r = _parse_result_row(cells, event_id=110363)
        assert r["name"] == "Holvik, Simen"

    def test_city_star_stripped(self):
        cells = _make_cells_with_link(SAMPLE_ROW_VALUES)
        r = _parse_result_row(cells, event_id=110363)
        assert r["city_or_club"] == "Hundvaag"  # * prefix stripped

    def test_country(self):
        cells = _make_cells_with_link(SAMPLE_ROW_VALUES)
        r = _parse_result_row(cells, event_id=110363)
        assert r["country"] == "NOR"

    def test_birth_year_int(self):
        cells = _make_cells_with_link(SAMPLE_ROW_VALUES)
        r = _parse_result_row(cells, event_id=110363)
        assert r["birth_year"] == 1977

    def test_gender(self):
        cells = _make_cells_with_link(SAMPLE_ROW_VALUES)
        r = _parse_result_row(cells, event_id=110363)
        assert r["gender"] == "M"

    def test_age_group(self):
        cells = _make_cells_with_link(SAMPLE_ROW_VALUES)
        r = _parse_result_row(cells, event_id=110363)
        assert r["age_group"] == "M45"

    def test_performance_score_float(self):
        cells = _make_cells_with_link(SAMPLE_ROW_VALUES)
        r = _parse_result_row(cells, event_id=110363)
        assert r["performance_score"] == pytest.approx(9.968)

    def test_athlete_id_extracted_from_link(self):
        cells = _make_cells_with_link(SAMPLE_ROW_VALUES, runner_id=779063)
        r = _parse_result_row(cells, event_id=110363)
        assert r["athlete_id"] == 779063

    def test_event_id_stamped(self):
        cells = _make_cells_with_link(SAMPLE_ROW_VALUES)
        r = _parse_result_row(cells, event_id=999)
        assert r["event_id"] == 999

    def test_too_few_cells_returns_none(self):
        cells = _make_cells(["1", "21:47:45 h", "Name"])  # only 3 cells
        assert _parse_result_row(cells, event_id=1) is None

    def test_no_athlete_link_returns_none_athlete_id(self):
        cells = _make_cells(SAMPLE_ROW_VALUES)  # no link in name cell
        r = _parse_result_row(cells, event_id=1)
        assert r["athlete_id"] is None

    def test_female_gender(self):
        row = list(SAMPLE_ROW_VALUES)
        row[6] = "F"
        row[8] = "W45"
        cells = _make_cells_with_link(row)
        r = _parse_result_row(cells, event_id=1)
        assert r["gender"] == "F"
        assert r["age_group"] == "W45"


# ---------------------------------------------------------------------------
# Integration: live HTTP against DUV
# These hit the real DUV website — run only when explicitly requested.
# Known ground-truth values verified manually against statistik.d-u-v.org
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestBadwaterLiveData:
    """
    Known ground truth for Badwater Ultramarathon results.
    Verify these by visiting:
      https://statistik.d-u-v.org/getresultevent.php?event=<event_id>&Language=EN
    """

    # 2025 race (event_id 110363)
    EVENT_2025 = 110363
    EXPECTED_2025 = {
        "year": 2025,
        "finisher_count": 93,
        "winner_name": "Holvik, Simen",
        "winner_time": "21:47:45 h",
        "winner_country": "NOR",
        "winner_athlete_id": 779063,
    }

    # 2024 race (event_id 100294)
    EVENT_2024 = 100294
    EXPECTED_2024 = {
        "year": 2024,
        "finisher_count": 74,
        "winner_name": "Burke, Shaun",
        "winner_time": "23:29:00 h",
        "winner_country": "USA",
        "winner_athlete_id": 423993,
    }

    @pytest.fixture(scope="class")
    def results_2025(self):
        return fetch_results(self.EVENT_2025)

    @pytest.fixture(scope="class")
    def results_2024(self):
        return fetch_results(self.EVENT_2024)

    @pytest.fixture(scope="class")
    def meta_2025(self):
        return fetch_event_metadata(self.EVENT_2025)

    @pytest.fixture(scope="class")
    def meta_2024(self):
        return fetch_event_metadata(self.EVENT_2024)

    # --- Metadata ---

    def test_2025_year_extracted(self, meta_2025):
        assert meta_2025["year"] == self.EXPECTED_2025["year"]

    def test_2024_year_extracted(self, meta_2024):
        assert meta_2024["year"] == self.EXPECTED_2024["year"]

    # --- Finisher counts ---

    def test_2025_finisher_count(self, results_2025):
        assert len(results_2025) == self.EXPECTED_2025["finisher_count"], (
            f"Expected {self.EXPECTED_2025['finisher_count']} finishers, got {len(results_2025)}"
        )

    def test_2024_finisher_count(self, results_2024):
        assert len(results_2024) == self.EXPECTED_2024["finisher_count"]

    # --- Winner spot-checks ---

    def test_2025_winner_name(self, results_2025):
        assert results_2025[0]["name"] == self.EXPECTED_2025["winner_name"]

    def test_2025_winner_time(self, results_2025):
        assert results_2025[0]["finish_time"] == self.EXPECTED_2025["winner_time"]

    def test_2025_winner_country(self, results_2025):
        assert results_2025[0]["country"] == self.EXPECTED_2025["winner_country"]

    def test_2025_winner_athlete_id(self, results_2025):
        assert results_2025[0]["athlete_id"] == self.EXPECTED_2025["winner_athlete_id"]

    def test_2024_winner_name(self, results_2024):
        assert results_2024[0]["name"] == self.EXPECTED_2024["winner_name"]

    def test_2024_winner_time(self, results_2024):
        assert results_2024[0]["finish_time"] == self.EXPECTED_2024["winner_time"]

    # --- Data integrity: applies to any year's results ---

    def _check_integrity(self, results, label):
        assert len(results) > 0, f"{label}: no results returned"

        required_fields = [
            "event_id", "place", "finish_time", "finish_time_seconds",
            "name", "country", "birth_year", "gender",
            "gender_place", "age_group", "age_group_place",
            "performance_score", "athlete_id",
        ]

        for i, r in enumerate(results):
            for field in required_fields:
                assert field in r, f"{label}[{i}] missing field '{field}'"

        # Places are 1-based sequential integers
        places = [r["place"] for r in results]
        assert places[0] == 1, f"{label}: first place should be 1"
        assert places == sorted(places), f"{label}: places not in ascending order"

        # Finish times are monotonically non-decreasing
        times = [r["finish_time_seconds"] for r in results if r["finish_time_seconds"]]
        assert times == sorted(times), f"{label}: finish times not monotonically non-decreasing"

        # All finish times > 0
        for r in results:
            if r["finish_time_seconds"] is not None:
                assert r["finish_time_seconds"] > 0, f"{label}: non-positive finish time in {r}"

        # Gender is always M or F
        for r in results:
            assert r["gender"] in ("M", "F"), f"{label}: unexpected gender {r['gender']!r} in {r}"

        # Birth years are plausible (1930-2010)
        for r in results:
            if r["birth_year"] is not None:
                assert 1930 <= r["birth_year"] <= 2010, (
                    f"{label}: implausible birth_year {r['birth_year']} in {r}"
                )

        # Performance scores positive when present
        for r in results:
            if r["performance_score"] is not None:
                assert r["performance_score"] > 0, f"{label}: non-positive performance_score in {r}"

        # Athlete IDs are positive integers when present
        for r in results:
            if r["athlete_id"] is not None:
                assert isinstance(r["athlete_id"], int) and r["athlete_id"] > 0

        # Gender places are monotonically non-decreasing within gender
        for gender in ("M", "F"):
            gp = [r["gender_place"] for r in results if r["gender"] == gender and r["gender_place"]]
            assert gp == sorted(gp), f"{label}: {gender} gender_places not in order: {gp}"

    def test_2025_data_integrity(self, results_2025):
        self._check_integrity(results_2025, "2025")

    def test_2024_data_integrity(self, results_2024):
        self._check_integrity(results_2024, "2024")

    # --- Finish time ranges for Badwater 135 ---
    # Winner typically 21-26h; last finisher typically <48h (cutoff)

    def test_2025_finish_time_range(self, results_2025):
        winner_s = results_2025[0]["finish_time_seconds"]
        last_s   = results_2025[-1]["finish_time_seconds"]
        assert 18 * 3600 <= winner_s <= 30 * 3600, f"Winner time out of expected range: {winner_s}s"
        assert last_s <= 48 * 3600, f"Last finisher exceeded 48h cutoff: {last_s}s"

    def test_2024_finish_time_range(self, results_2024):
        winner_s = results_2024[0]["finish_time_seconds"]
        last_s   = results_2024[-1]["finish_time_seconds"]
        assert 18 * 3600 <= winner_s <= 30 * 3600
        assert last_s <= 48 * 3600
