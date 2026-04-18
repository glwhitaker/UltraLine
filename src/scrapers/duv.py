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
EVENT_LIST_URL = f"{BASE_URL}/geteventlist.php"
RESULT_EVENT_URL = f"{BASE_URL}/getresultevent.php"

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


def fetch_results(event_id: int) -> list[dict]:
    """
    Fetch finisher/DNF data for one DUV race-year instance.
    Returns a list of participant dicts parsed from the results table.
    """
    resp = _get(RESULT_EVENT_URL, params={"event": event_id, "Language": "EN"})
    if resp is None:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []

    for row in soup.select("tr.odd, tr.even"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        text = [c.get_text(strip=True) for c in cells]
        results.append(text)

    return results
