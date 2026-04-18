"""
GPX course parser.

Returns a clean course profile from an uploaded GPX file with no Streamlit
dependencies — all outputs are plain pandas DataFrames and dicts.

Public API:
    parse_gpx(file_obj)          -> (points_df, summary)
    downsample(df, max_points)   -> points_df (thinned for map rendering)
    mile_markers(df)             -> markers_df
"""

import math
from typing import IO

import gpxpy
import gpxpy.geo
import numpy as np
import pandas as pd

_M_TO_FT = 3.28084
_M_TO_MI = 0.000621371


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def parse_gpx(file_obj: IO[bytes]) -> tuple[pd.DataFrame, dict]:
    """
    Parse a GPX file and return a course profile.

    Args:
        file_obj: File-like object (BytesIO). Do NOT pass a Streamlit
                  UploadedFile directly — read() the bytes first and wrap
                  in io.BytesIO so the result is cacheable.

    Returns:
        (points_df, summary)

        points_df columns:
            lat, lon              — WGS84 coordinates
            elevation_ft          — elevation in feet (ffill/bfill for gaps)
            distance_mi           — cumulative distance from start in miles
            grade_pct             — rise/run × 100, clipped to [−100, +100]

        summary keys:
            total_distance_mi
            min/max/avg_elevation_ft
            net_gain_ft, cumulative_gain_ft, cumulative_loss_ft
            max_uphill_grade_pct, max_downhill_grade_pct
            pct_uphill, pct_flat, pct_downhill
            longest_climb_distance_mi, longest_climb_gain_ft
            longest_descent_distance_mi, longest_descent_loss_ft
            num_points

    Raises:
        ValueError: if the GPX file contains no trackpoints or routes.
        gpxpy.gpx.GPXXMLSyntaxException: if the file is malformed XML.
    """
    gpx = gpxpy.parse(file_obj)

    # Flatten all tracks + segments + standalone routes
    raw_points = []
    for track in gpx.tracks:
        for segment in track.segments:
            raw_points.extend(segment.points)
    for route in gpx.routes:
        raw_points.extend(route.points)

    if not raw_points:
        raise ValueError("GPX file contains no trackpoints.")

    # Build arrays
    lats  = np.array([p.latitude  for p in raw_points], dtype=np.float64)
    lons  = np.array([p.longitude for p in raw_points], dtype=np.float64)
    elev_m = np.array(
        [p.elevation if p.elevation is not None else np.nan for p in raw_points],
        dtype=np.float64,
    )

    # Fill elevation gaps
    elev_series = pd.Series(elev_m).ffill().bfill()
    elev_m = elev_series.to_numpy()
    elev_ft = elev_m * _M_TO_FT

    # Cumulative distance (haversine, meters → miles)
    dist_mi = _cumulative_distance_mi(lats, lons)

    # Grade per point
    grade_pct = _compute_grade(elev_m, dist_mi)

    points_df = pd.DataFrame({
        "lat":         lats,
        "lon":         lons,
        "elevation_ft": elev_ft,
        "distance_mi": dist_mi,
        "grade_pct":   grade_pct,
    })

    summary = _build_summary(points_df)
    return points_df, summary


def downsample(df: pd.DataFrame, max_points: int = 2000) -> pd.DataFrame:
    """
    Thin a points DataFrame for map rendering.
    Uses uniform stride (iloc[::step]), always preserving first and last rows.
    Default of 2000 points is sufficient for folium route fidelity.
    """
    n = len(df)
    if n <= max_points:
        return df.copy()

    step = n // max_points
    indices = list(range(0, n, step))
    if indices[-1] != n - 1:
        indices.append(n - 1)
    return df.iloc[indices].reset_index(drop=True)


def mile_markers(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return one row per integer mile containing the nearest trackpoint.

    Columns: mile, lat, lon, elevation_ft
    """
    total_miles = df["distance_mi"].iloc[-1]
    miles = range(1, math.ceil(total_miles) + 1)

    rows = []
    for m in miles:
        if m > total_miles:
            break
        idx = (df["distance_mi"] - m).abs().idxmin()
        row = df.loc[idx]
        rows.append({
            "mile":         m,
            "lat":          row["lat"],
            "lon":          row["lon"],
            "elevation_ft": row["elevation_ft"],
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _cumulative_distance_mi(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Cumulative haversine distance in miles."""
    dist = np.zeros(len(lats))
    for i in range(1, len(lats)):
        seg_m = gpxpy.geo.haversine_distance(lats[i - 1], lons[i - 1], lats[i], lons[i])
        dist[i] = dist[i - 1] + seg_m * _M_TO_MI
    return dist


def _compute_grade(elev_m: np.ndarray, dist_mi: np.ndarray) -> np.ndarray:
    """
    Grade percentage per point. First point is 0.0.
    Segments shorter than 1 meter are skipped (reuse previous grade) to
    suppress GPS noise spikes from nearly-duplicate coordinates.
    """
    grade = np.zeros(len(elev_m))
    for i in range(1, len(elev_m)):
        seg_m = (dist_mi[i] - dist_mi[i - 1]) / _M_TO_MI
        if seg_m < 1.0:
            grade[i] = grade[i - 1]
            continue
        rise_m = elev_m[i] - elev_m[i - 1]
        grade[i] = (rise_m / seg_m) * 100.0

    return np.clip(grade, -100.0, 100.0)


def _build_summary(df: pd.DataFrame) -> dict:
    elev   = df["elevation_ft"]
    grade  = df["grade_pct"]
    dist   = df["distance_mi"]
    total  = dist.iloc[-1]

    # Elevation deltas between consecutive points
    elev_m_series = elev / _M_TO_FT
    delta = elev_m_series.diff().fillna(0.0)
    gain_ft = float(delta[delta > 0].sum() * _M_TO_FT)
    loss_ft = float(abs(delta[delta < 0].sum()) * _M_TO_FT)

    # Grade-based terrain breakdown (by distance share)
    seg_dist = dist.diff().fillna(0.0)
    uphill   = float(seg_dist[grade >  1.0].sum())
    downhill = float(seg_dist[grade < -1.0].sum())
    flat     = float(total - uphill - downhill)

    pct_up   = round(uphill   / total * 100, 1) if total else 0.0
    pct_down = round(downhill / total * 100, 1) if total else 0.0
    pct_flat = round(100.0 - pct_up - pct_down, 1)

    # Longest continuous climb / descent
    longest_climb   = _longest_run(df, direction="up")
    longest_descent = _longest_run(df, direction="down")

    return {
        "total_distance_mi":       round(total, 2),
        "min_elevation_ft":        round(float(elev.min()), 0),
        "max_elevation_ft":        round(float(elev.max()), 0),
        "avg_elevation_ft":        round(float(elev.mean()), 0),
        "net_gain_ft":             round(float(elev.iloc[-1] - elev.iloc[0]), 0),
        "cumulative_gain_ft":      round(gain_ft, 0),
        "cumulative_loss_ft":      round(loss_ft, 0),
        "max_uphill_grade_pct":    round(float(grade.max()), 1),
        "max_downhill_grade_pct":  round(float(grade.min()), 1),
        "pct_uphill":              pct_up,
        "pct_flat":                pct_flat,
        "pct_downhill":            pct_down,
        "longest_climb_distance_mi":  longest_climb["distance_mi"],
        "longest_climb_gain_ft":      longest_climb["gain_ft"],
        "longest_descent_distance_mi": longest_descent["distance_mi"],
        "longest_descent_loss_ft":     longest_descent["loss_ft"],
        "num_points":              len(df),
    }


def _longest_run(df: pd.DataFrame, direction: str) -> dict:
    """
    Find the longest continuous climb (direction='up') or descent (direction='down').
    'Continuous' means grade stays on the correct side of the ±1% flat threshold.
    Returns dict with distance_mi, gain_ft (climb) or loss_ft (descent).
    """
    grade = df["grade_pct"].to_numpy()
    dist  = df["distance_mi"].to_numpy()
    elev  = df["elevation_ft"].to_numpy()

    best_dist = 0.0
    best_elev_change = 0.0
    run_start = 0

    def is_active(g):
        return g > 1.0 if direction == "up" else g < -1.0

    in_run = False
    for i in range(len(grade)):
        if is_active(grade[i]):
            if not in_run:
                run_start = i
                in_run = True
        else:
            if in_run:
                run_dist = dist[i - 1] - dist[run_start]
                run_elev = abs(elev[i - 1] - elev[run_start])
                if run_dist > best_dist:
                    best_dist = run_dist
                    best_elev_change = run_elev
            in_run = False

    # Close any run that extends to the end
    if in_run:
        run_dist = dist[-1] - dist[run_start]
        run_elev = abs(elev[-1] - elev[run_start])
        if run_dist > best_dist:
            best_dist = run_dist
            best_elev_change = run_elev

    return {
        "distance_mi": round(best_dist, 2),
        "gain_ft":     round(best_elev_change, 0),
        "loss_ft":     round(best_elev_change, 0),
    }
