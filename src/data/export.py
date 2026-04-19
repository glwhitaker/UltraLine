"""
Parquet export layer.

Derives flat ML-ready feature matrices from SQLite and writes Parquet files
to data/training/. SQLite is the source of truth; these files are re-derivable.

Three exports:
  population_results.parquet  — one row per finisher; all races
  athlete_features.parquet    — one row per athlete; aggregated longitudinal features
  badwater_model_data.parquet — Badwater-specific join of results + athlete features
"""

import logging
from pathlib import Path

import pandas as pd

from src.data.db import connect, DB_PATH

logger = logging.getLogger(__name__)

TRAINING_DIR = Path(__file__).resolve().parents[2] / "data" / "training"


def export_population_results(db_path: Path = DB_PATH, out_dir: Path = TRAINING_DIR) -> Path:
    """
    One row per finisher across all races.
    Joins results with race_events to add race-level context.
    """
    sql = """
    SELECT
        r.event_id,
        e.race_name,
        e.country        AS race_country,
        e.year,
        e.distance_value,
        e.distance_unit,
        r.athlete_id,
        r.place,
        r.finish_time_seconds,
        r.name,
        r.country        AS athlete_country,
        r.birth_year,
        r.gender,
        r.gender_place,
        r.age_group,
        r.age_group_place,
        r.performance_score
    FROM results r
    JOIN race_events e ON r.event_id = e.event_id
    ORDER BY e.race_name, e.year, r.place
    """
    with connect(db_path) as conn:
        df = pd.read_sql_query(sql, conn)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "population_results.parquet"
    df.to_parquet(out_path, index=False)
    logger.info("population_results: %d rows → %s", len(df), out_path)
    return out_path


def export_athlete_features(db_path: Path = DB_PATH, out_dir: Path = TRAINING_DIR) -> Path:
    """
    One row per athlete with aggregated longitudinal features.
    Requires athlete_results to be populated (run fetch_athletes.py first).

    Features:
      athlete_race_count       — total races in DUV history
      dnf_count                — total DNFs
      finish_rate              — finishes / total races
      avg_finish_time_100mi    — mean finish_time_seconds for 100mi races
      recent_finish_rate_5     — finish rate over last 5 races (ACWR proxy)
      days_since_last_race     — from latest race year to most recent overall
    """
    sql = """
    SELECT
        a.athlete_id,
        a.name,
        a.country,
        a.birth_year,
        COUNT(ar.id)                                          AS athlete_race_count,
        SUM(ar.dnf)                                           AS dnf_count,
        ROUND(1.0 - (1.0 * SUM(ar.dnf) / COUNT(ar.id)), 4)   AS finish_rate,
        AVG(CASE WHEN ar.distance_unit = 'mi' AND ar.distance_value = 100 AND ar.dnf = 0
                 THEN ar.finish_time_seconds END)              AS avg_finish_time_100mi,
        MAX(ar.year)                                          AS last_race_year
    FROM athletes a
    LEFT JOIN athlete_results ar ON a.athlete_id = ar.athlete_id
    GROUP BY a.athlete_id
    """
    with connect(db_path) as conn:
        df = pd.read_sql_query(sql, conn)

    # Recent finish rate: last 5 races per athlete (requires per-row data)
    recent_sql = """
    SELECT athlete_id, dnf, year
    FROM athlete_results
    ORDER BY athlete_id, year DESC
    """
    with connect(db_path) as conn:
        recent_df = pd.read_sql_query(recent_sql, conn)

    if not recent_df.empty:
        recent_5 = (
            recent_df.groupby("athlete_id")
            .head(5)
            .groupby("athlete_id")["dnf"]
            .agg(recent_finish_rate_5=lambda x: round(1.0 - x.mean(), 4))
            .reset_index()
        )
        df = df.merge(recent_5, on="athlete_id", how="left")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "athlete_features.parquet"
    df.to_parquet(out_path, index=False)
    logger.info("athlete_features: %d rows → %s", len(df), out_path)
    return out_path


def export_model_data(
    race_name: str = "Badwater Ultramarathon",
    db_path: Path = DB_PATH,
    out_dir: Path = TRAINING_DIR,
) -> Path:
    """
    Race-specific ML-ready dataset: finisher rows joined with athlete features.
    One row per finisher. Suitable for finish time regression and DNF classification.
    """
    sql = """
    SELECT
        r.event_id,
        e.year,
        e.distance_value,
        e.distance_unit,
        r.athlete_id,
        r.place,
        r.finish_time_seconds,
        r.birth_year,
        r.gender,
        r.age_group,
        r.performance_score,
        -- Longitudinal athlete features (NULL if athlete history not yet fetched)
        af.athlete_race_count,
        af.dnf_count,
        af.finish_rate,
        af.avg_finish_time_100mi,
        af.last_race_year
    FROM results r
    JOIN race_events e ON r.event_id = e.event_id
    LEFT JOIN (
        SELECT
            a.athlete_id,
            COUNT(ar.id)                                        AS athlete_race_count,
            SUM(ar.dnf)                                         AS dnf_count,
            ROUND(1.0 - (1.0 * SUM(ar.dnf) / COUNT(ar.id)), 4) AS finish_rate,
            AVG(CASE WHEN ar.distance_unit = 'mi' AND ar.distance_value = 100 AND ar.dnf = 0
                     THEN ar.finish_time_seconds END)            AS avg_finish_time_100mi,
            MAX(ar.year)                                        AS last_race_year
        FROM athletes a
        LEFT JOIN athlete_results ar ON a.athlete_id = ar.athlete_id
        GROUP BY a.athlete_id
    ) af ON r.athlete_id = af.athlete_id
    WHERE e.race_name = ?
    ORDER BY e.year, r.place
    """
    with connect(db_path) as conn:
        df = pd.read_sql_query(sql, conn, params=(race_name,))

    # Derived features
    if not df.empty:
        # Age at race time (approximate)
        df["age_at_race"] = df["year"] - df["birth_year"]
        # Normalise finish time to hours
        df["finish_time_hours"] = df["finish_time_seconds"] / 3600.0

    out_dir.mkdir(parents=True, exist_ok=True)
    slug = race_name.lower().replace(" ", "_")
    out_path = out_dir / f"{slug}_model_data.parquet"
    df.to_parquet(out_path, index=False)
    logger.info("%s model data: %d rows → %s", race_name, len(df), out_path)
    return out_path
