"""
DUV (Deutsche Ultramarathon Vereinigung) scraper.
Source: https://statistik.d-u-v.org

Endpoints:
  GET /geteventlist.php
      ?year=all&dist=all&country=all&Language=EN&sort=1&page=<N>
      Returns 1,000 events per page. 115,688 total events (~116 pages).
      Columns: date | name (COUNTRY) | distance | finishers | IAU label

  GET /getresultevent.php?event=<event_id>&Language=EN
      Full results for one race-year instance.
      No cross-year links — each year is a fully independent record.

Data model:
  Each DUV event_id = one specific year's race instance.
  Races are grouped across years by normalizing the event name
  (stripping the trailing " (XXX)" country code).

  finishers > 0  →  results confirmed (no separate HTTP check needed).
"""

import re
import time
import logging
from collections import defaultdict

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://statistik.d-u-v.org"
EVENT_LIST_URL      = f"{BASE_URL}/geteventlist.php"
RESULT_EVENT_URL    = f"{BASE_URL}/getresultevent.php"
RESULT_PERSON_URL   = f"{BASE_URL}/getresultperson.php"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": BASE_URL,
}

logger = logging.getLogger(__name__)

# Regex to extract trailing country code: "Race Name (USA)" → ("Race Name", "USA")
_COUNTRY_RE = re.compile(r'^(.*?)\s*\(([A-Z]{2,4})\)\s*$')


def _get(url: str, params: dict = None, delay: float = 1.0):
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        time.sleep(delay)
        return resp
    except requests.RequestException as e:
        logger.warning("Request failed: %s — %s", url, e)
        return None


def _parse_event_list_page(html: str) -> list[dict]:
    """
    Parse one page of geteventlist.php.
    Returns a list of raw event dicts.
    """
    soup = BeautifulSoup(html, "html.parser")
    events = []

    for row in soup.select("tr.odd, tr.even"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        link = row.find("a", href=re.compile(r"getresultevent\.php"))
        if not link:
            continue

        event_id_match = re.search(r"event=(\d+)", link["href"])
        if not event_id_match:
            continue

        date_raw   = cells[0].get_text(strip=True)
        name_raw   = cells[1].get_text(strip=True)
        dist_raw   = cells[2].get_text(strip=True)
        finish_raw = cells[3].get_text(strip=True)

        finishers = 0
        try:
            finishers = int(re.sub(r"[^\d]", "", finish_raw))
        except ValueError:
            pass

        # Extract year from date field (handles "28.-29.06.2025" and "12.04.2026")
        year_match = re.search(r"(\d{4})", date_raw)
        year = int(year_match.group(1)) if year_match else None

        events.append({
            "event_id":  int(event_id_match.group(1)),
            "date":      date_raw,
            "year":      year,
            "name_raw":  name_raw,
            "distance":  dist_raw,
            "finishers": finishers,
        })

    return events


def _parse_name_and_country(name_raw: str) -> tuple[str, str]:
    """
    Split "Western States 100 Mile Endurance Run (USA)" into
    ("Western States 100 Mile Endurance Run", "USA").
    Returns (name_raw, "") if no country suffix found.
    """
    m = _COUNTRY_RE.match(name_raw)
    if m:
        return m.group(1).strip(), m.group(2)
    return name_raw.strip(), ""


def fetch_event_list_page(page: int) -> list[dict]:
    """Fetch and parse one page of the DUV event list."""
    params = {
        "year":     "all",
        "dist":     "all",
        "country":  "all",
        "Language": "EN",
        "sort":     "1",
        "page":     page,
    }
    resp = _get(EVENT_LIST_URL, params=params)
    if resp is None:
        return []
    return _parse_event_list_page(resp.text)


def fetch_all_events(max_pages: int = None) -> list[dict]:
    """
    Scrape all pages of the DUV event list.
    Returns flat list of raw event dicts (one per race-year instance).

    Args:
        max_pages: Cap for testing (None = scrape everything).
    """
    all_events = []
    page = 1

    while True:
        if max_pages and page > max_pages:
            break

        logger.info("Fetching page %d...", page)
        events = fetch_event_list_page(page)

        if not events:
            logger.info("Empty page %d — done.", page)
            break

        all_events.extend(events)
        logger.info("  Page %d: %d events (total so far: %d)", page, len(events), len(all_events))
        page += 1

    return all_events


def group_into_races(events: list[dict]) -> list[dict]:
    """
    Group flat event list into races (one entry per recurring race,
    with all historical year instances collected).

    Grouping key: normalized name (lowercase, stripped).
    Most recent year first in duv_event_ids.

    Returns list of race dicts ready for races.json.
    """
    groups: dict[str, dict] = {}

    for ev in events:
        name, country = _parse_name_and_country(ev["name_raw"])
        key = name.lower().strip()

        if key not in groups:
            groups[key] = {
                "name":          name,
                "country":       country,
                "distances":     set(),
                "has_results":   False,
                "duv_event_ids": [],  # sorted most-recent-first after grouping
                "_years":        [],  # (year, event_id) for sorting
            }

        g = groups[key]
        g["distances"].add(ev["distance"])
        g["_years"].append((ev["year"] or 0, ev["event_id"]))
        if ev["finishers"] > 0:
            g["has_results"] = True

    # Finalize each group
    races = []
    for g in groups.values():
        g["_years"].sort(key=lambda x: x[0], reverse=True)
        g["duv_event_ids"] = [eid for _, eid in g["_years"]]
        g["distances"] = ", ".join(sorted(g["distances"]))
        del g["_years"]
        races.append(g)

    # Sort output alphabetically
    races.sort(key=lambda r: r["name"].lower())
    return races


def _parse_finish_time_seconds(time_str: str):
    """
    Convert "21:47:45 h" → total seconds, or None if unparseable.
    Handles HH:MM:SS and D+HH:MM:SS formats.
    """
    if not time_str:
        return None
    clean = time_str.replace(" h", "").strip()
    parts = clean.split(":")
    try:
        if len(parts) == 3:
            h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
            return h * 3600 + m * 60 + s
        if len(parts) == 4:  # D:HH:MM:SS rare format
            d, h, m, s = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
            return d * 86400 + h * 3600 + m * 60 + s
    except (ValueError, IndexError):
        pass
    return None


def _parse_result_row(cells, event_id: int):
    """
    Parse one <tr> of result cells into a structured dict.
    Expected column order (12 columns):
      0  place (overall)
      1  finish_time ("21:47:45 h")
      2  name
      3  city_or_club
      4  country (3-letter)
      5  birth_year
      6  gender (M/F)
      7  gender_place
      8  age_group (e.g. M45)
      9  age_group_place
      10 performance_score (DUV float score)
      11 performance_time ("19:47:11 h")
    Athlete ID extracted from runner=XXXXX link href.
    """
    if len(cells) < 10:
        return None

    text = [c.get_text(strip=True) for c in cells]

    athlete_id = None
    link = next((a for a in cells[2].find_all("a") if "runner=" in a.get("href", "")), None)
    if link:
        m = re.search(r"runner=(\d+)", link["href"])
        if m:
            athlete_id = int(m.group(1))

    def _int(val):
        try:
            return int(re.sub(r"[^\d]", "", val)) if val else None
        except ValueError:
            return None

    def _float(val):
        try:
            return float(val) if val else None
        except ValueError:
            return None

    finish_time = text[1] if len(text) > 1 else None
    perf_time   = text[11] if len(text) > 11 else None

    return {
        "event_id":            event_id,
        "place":               _int(text[0]),
        "finish_time":         finish_time,
        "finish_time_seconds": _parse_finish_time_seconds(finish_time),
        "name":                text[2] if len(text) > 2 else None,
        "city_or_club":        text[3].lstrip("*") if len(text) > 3 else None,
        "country":             text[4] if len(text) > 4 else None,
        "birth_year":          _int(text[5]) if len(text) > 5 else None,
        "gender":              text[6] if len(text) > 6 else None,
        "gender_place":        _int(text[7]) if len(text) > 7 else None,
        "age_group":           text[8] if len(text) > 8 else None,
        "age_group_place":     _int(text[9]) if len(text) > 9 else None,
        "performance_score":   _float(text[10]) if len(text) > 10 else None,
        "performance_time":    perf_time,
        "athlete_id":          athlete_id,
    }


# DUV surface filter param → normalized surface type name.
# Matches the `surface=` values accepted by geteventlist.php.
SURFACE_MAP = {
    "road":    "road",
    "trail":   "trail",
    "track":   "track",
    "stage":   "stage",
    "indoo":   "indoor",
    "indoor":  "indoor",
    "elim":    "elimination",
    "backy":   "backyard",
    "backyard":"backyard",
    "walk":    "walk",
}

# All surface filter values accepted by DUV's event list form.
DUV_SURFACE_FILTERS = ["Road", "Trail", "Track", "Stage", "Indoo", "Elim", "Backy", "Walk"]


def _parse_surface_from_distance(distance_text: str):
    """
    Extract normalized surface type from the DUV Distance field text.
    Examples:
      "135mi  road race"  → "road"
      "100mi  trail race" → "trail"
      "100km  track"      → "track"
      "100km  stage race" → "stage"
    Returns None if no known surface keyword found.
    """
    text_lower = distance_text.lower()
    for keyword, surface in SURFACE_MAP.items():
        if keyword in text_lower:
            return surface
    return None


def _parse_distance_text(distance_text: str):
    """
    Parse a DUV distance string into a (value, unit) tuple.

    Handles both event-page strings ("135mi  road race") and
    athlete-page strings ("100mi", "24h", "100km/3Etappen").

    Units recognised: mi, km, h
    Returns (None, None) if no match found.

    Examples:
      "135mi  road race"  → (135.0, "mi")
      "146mi  road race"  → (146.0, "mi")
      "100km  trail race" → (100.0, "km")
      "24h"               → (24.0,  "h")
      "100km/3Etappen"    → (100.0, "km")
      "50km"              → (50.0,  "km")
    """
    if not distance_text:
        return None, None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(km|mi|h)\b", distance_text, re.IGNORECASE)
    if m:
        return float(m.group(1)), m.group(2).lower()
    return None, None


def fetch_event_metadata(event_id: int) -> dict:
    """
    Fetch the result page for event_id and extract metadata:
    year, date_raw, distance_value, distance_unit, surface_type.
    Returns {} on failure.
    """
    resp = _get(RESULT_EVENT_URL, params={"event": event_id, "Language": "EN"})
    if resp is None:
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")
    metadata = {"event_id": event_id}

    # Parse structured header rows (Date:, Distance:, Event:, Finishers:)
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        label = cells[0].get_text(strip=True).rstrip(":")
        value = cells[1].get_text(strip=True)

        if label == "Date":
            m = re.search(r"\b(19|20)\d{2}\b", value)
            if m:
                metadata["year"] = int(m.group(0))
            metadata["date_raw"] = value

        elif label == "Distance":
            dist_value, dist_unit = _parse_distance_text(value)
            if dist_value is not None:
                metadata["distance_value"] = dist_value
                metadata["distance_unit"]  = dist_unit
            surface = _parse_surface_from_distance(value)
            if surface:
                metadata["surface_type"] = surface

    # Fallback year extraction if Date row not found
    if "year" not in metadata:
        for text in soup.stripped_strings:
            m = re.search(r"\b(19|20)\d{2}\b", text)
            if m:
                metadata.setdefault("year", int(m.group(0)))
                metadata.setdefault("date_raw", text)
                break

    return metadata


def build_surface_index(
    surface_filters=None,
    max_pages: int = None,
    delay: float = 1.0,
) -> dict:
    """
    Query DUV's event list for each surface type and return a mapping of
    event_id → surface_type for all events found.

    Used to bulk-tag races.json and race_events with surface classification
    without re-fetching individual event result pages.

    Args:
        surface_filters: List of DUV surface param values to query.
                         Defaults to all: Road, Trail, Track, Stage, Indoo, Elim, Backy, Walk.
        max_pages:       Cap pages per surface type (None = all).
        delay:           Seconds between requests.

    Returns:
        Dict mapping event_id (int) → surface_type (str).
    """
    if surface_filters is None:
        surface_filters = DUV_SURFACE_FILTERS

    surface_index = {}

    for surface_filter in surface_filters:
        normalized = SURFACE_MAP.get(surface_filter.lower(), surface_filter.lower())
        logger.info("Building surface index for: %s …", surface_filter)
        page = 1

        while True:
            if max_pages and page > max_pages:
                break

            params = {
                "year":     "all",
                "dist":     "all",
                "country":  "all",
                "Language": "EN",
                "sort":     "1",
                "surface":  surface_filter,
                "page":     page,
            }
            resp = _get(EVENT_LIST_URL, params=params, delay=delay)
            if resp is None:
                break

            events = _parse_event_list_page(resp.text)
            if not events:
                break

            for ev in events:
                surface_index[ev["event_id"]] = normalized

            logger.info("  %s page %d: %d events (index total: %d)",
                        surface_filter, page, len(events), len(surface_index))
            page += 1

    return surface_index


def fetch_results(event_id: int) -> list[dict]:
    """
    Fetch and parse finisher data for one DUV race-year instance.
    Returns a list of structured participant dicts.
    Note: DUV only publishes finisher rows; DNF data is not available via this endpoint.
    """
    resp = _get(RESULT_EVENT_URL, params={"event": event_id, "Language": "EN"})
    if resp is None:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []

    for row in soup.select("tr.odd, tr.even"):
        cells = row.find_all("td")
        parsed = _parse_result_row(cells, event_id)
        if parsed is not None:
            results.append(parsed)

    return results


def fetch_athlete_history(athlete_id: int) -> dict:
    """
    Fetch an athlete's full result history from their DUV personal page.

    Page structure: each race appears as two consecutive <tr> rows (not .odd/.even):
      Row A (date row):   [date_str, race_name (COUNTRY), distance]  — has event link
      Row B (result row): [result_value, athlete_name, club, overall_rank, gender_rank, cat_rank]

    result_value is:
      - "HH:MM:SS h"  for distance events (miles/km)
      - "NNN.NNN km"  for timed events (24h, 48h, etc.)
      - "DNF" / "DNS" for non-finishes

    Returns:
      {
        "athlete_id": int,
        "name": str,
        "country": str,
        "birth_year": int | None,
        "results": [
          {
            "athlete_id": int,
            "event_id": int | None,
            "race_name": str,
            "year": int | None,
            "distance": str,
            "place": int | None,
            "finish_time_seconds": int | None,
            "dnf": int,   # 1 if DNF/DNS, 0 otherwise
          },
          ...
        ]
      }
    """
    resp = _get(RESULT_PERSON_URL, params={"runner": athlete_id, "Language": "EN"})
    if resp is None:
        return {"athlete_id": athlete_id, "name": None, "country": None, "birth_year": None, "results": []}

    soup = BeautifulSoup(resp.text, "html.parser")
    all_rows = soup.find_all("tr")

    # Extract athlete metadata from header rows
    name, country, birth_year = None, None, None
    for row in all_rows:
        cells = row.find_all("td")
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True)
            value = cells[1].get_text(strip=True)
            if label == "Name:":
                name = value
            elif label == "Nationality:":
                country = value
            elif label == "Year of birth:":
                m = re.search(r"\d{4}", value)
                if m:
                    birth_year = int(m.group(0))

    # Parse race results: scan for "date rows" (3 cells + event link) followed by result row
    results = []
    i = 0
    while i < len(all_rows):
        row = all_rows[i]
        cells = row.find_all("td")
        event_link = row.find("a", href=re.compile(r"getresultevent\.php"))

        if event_link and len(cells) >= 3:
            # This is a date row
            date_str  = cells[0].get_text(strip=True)
            name_raw  = cells[1].get_text(strip=True)
            distance  = cells[2].get_text(strip=True)

            event_id = None
            m = re.search(r"event=(\d+)", event_link.get("href", ""))
            if m:
                event_id = int(m.group(1))

            year = None
            ym = re.search(r"\b(19|20)\d{2}\b", date_str)
            if ym:
                year = int(ym.group(0))

            race_name, _ = _parse_name_and_country(name_raw)

            # Look at next row for result
            place = None
            finish_time_seconds = None
            dnf = 0

            if i + 1 < len(all_rows):
                result_row = all_rows[i + 1]
                result_cells = result_row.find_all("td")
                if result_cells:
                    result_val = result_cells[0].get_text(strip=True)
                    if result_val.upper() in ("DNF", "DNS"):
                        dnf = 1
                    else:
                        finish_time_seconds = _parse_finish_time_seconds(result_val)

                    # Overall place from "Overall: N"
                    for cell in result_cells:
                        pm = re.search(r"Overall:\s*(\d+)", cell.get_text())
                        if pm:
                            place = int(pm.group(1))
                            break

                i += 1  # skip the result row on next iteration

            dist_value, dist_unit = _parse_distance_text(distance)
            results.append({
                "athlete_id":          athlete_id,
                "event_id":            event_id,
                "race_name":           race_name,
                "year":                year,
                "distance_value":      dist_value,
                "distance_unit":       dist_unit,
                "place":               place,
                "finish_time_seconds": finish_time_seconds,
                "dnf":                 dnf,
            })

        i += 1

    return {
        "athlete_id": athlete_id,
        "name":       name,
        "country":    country,
        "birth_year": birth_year,
        "results":    results,
    }
