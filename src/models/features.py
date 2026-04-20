"""
Feature engineering pipeline for Badwater finish time regression.

Input: badwater_model_data.parquet merged with per-race longitudinal history
       computed from athlete_results (requires DB access for time-aware lookups).

Output: (X: DataFrame, y: Series) ready for sklearn estimators.
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.db import connect, DB_PATH

logger = logging.getLogger(__name__)

FEATURE_COLS = [
    "year",
    "gender_encoded",
    "age_at_race",
    # performance_score omitted: DUV computes it from finish_time, so it leaks the target
    # "has_history",
    "career_race_count",
    "races_last_12_months",
    "days_since_last_race",
    "distance_step_up",
    "prior_badwater_count",
    "prior_badwater_avg_time_hrs",
    "avg_finish_time_100mi_hrs",
    "performance_trend",
]


def _load_athlete_history(db_path: Path = DB_PATH) -> pd.DataFrame:
    """Load full athlete_results table for time-aware feature computation."""
    sql = """
    SELECT athlete_id, year, distance_value, distance_unit,
           finish_time_seconds, race_name, dnf
    FROM athlete_results
    ORDER BY athlete_id, year
    """
    with connect(db_path) as conn:
        return pd.read_sql_query(sql, conn)


def _compute_longitudinal_features(
    row: pd.Series, history: pd.DataFrame
) -> pd.Series:
    """
    For a single Badwater result row, compute features from prior race history only
    (year strictly < race_year to avoid data leakage).
    """
    aid = row["athlete_id"]
    race_year = int(row["year"])

    prior = history[(history["athlete_id"] == aid) & (history["year"] < race_year)]

    if prior.empty:
        return pd.Series({
            # "has_history": 0,
            "career_race_count": 0,
            "races_last_12_months": 0,
            "days_since_last_race": np.nan,
            "distance_step_up": np.nan,
            "prior_badwater_count": 0,
            "prior_badwater_avg_time_hrs": np.nan,
            "avg_finish_time_100mi_hrs": np.nan,
            "performance_trend": np.nan,
        })

    last_race_year = prior["year"].max()
    days_since = (race_year - last_race_year) * 365

    races_last_12 = int((prior["year"] == race_year - 1).sum())

    max_prior_dist = prior.loc[
        prior["distance_unit"] == "mi", "distance_value"
    ].max()
    if pd.notna(max_prior_dist):
        distance_step_up = int(row["distance_value"] > max_prior_dist)
    else:
        distance_step_up = np.nan

    badwater_prior = prior[prior["race_name"].str.contains("Badwater", case=False, na=False)]
    prior_bw_count = len(badwater_prior)
    finished_bw = badwater_prior[badwater_prior["dnf"] == 0]
    prior_bw_avg = (
        finished_bw["finish_time_seconds"].mean() / 3600.0
        if not finished_bw.empty else np.nan
    )

    finishes_100mi = prior[
        (prior["distance_value"] == 100) &
        (prior["distance_unit"] == "mi") &
        (prior["dnf"] == 0)
    ]
    avg_100mi = (
        finishes_100mi["finish_time_seconds"].mean() / 3600.0
        if not finishes_100mi.empty else np.nan
    )

    # Performance trend: slope of finish_time_seconds over last 5 finishes at >=100mi
    long_finishes = prior[
        (prior["distance_unit"] == "mi") &
        (prior["distance_value"] >= 100) &
        (prior["dnf"] == 0)
    ].tail(5)
    if len(long_finishes) >= 3:
        slope = np.polyfit(
            range(len(long_finishes)),
            long_finishes["finish_time_seconds"].values,
            deg=1
        )[0]
        trend = slope / 3600.0  # hrs per race
    else:
        trend = np.nan

    return pd.Series({
        # "has_history": 1,
        "career_race_count": len(prior),
        "races_last_12_months": races_last_12,
        "days_since_last_race": days_since,
        "distance_step_up": distance_step_up,
        "prior_badwater_count": prior_bw_count,
        "prior_badwater_avg_time_hrs": prior_bw_avg,
        "avg_finish_time_100mi_hrs": avg_100mi,
        "performance_trend": trend,
    })


def build_feature_matrix(
    df: pd.DataFrame,
    db_path: Path = DB_PATH,
) -> tuple:
    """
    Build (X, y) from a Badwater model data DataFrame.

    Args:
        df: DataFrame from badwater_model_data.parquet (must have athlete_id, year,
            birth_year, gender, performance_score, finish_time_seconds, distance_value)
        db_path: SQLite path for longitudinal history lookup

    Returns:
        (X, y) where X is a DataFrame of FEATURE_COLS and y is finish_time_hours Series.
        Rows with null finish_time_seconds are dropped.
    """
    df = df.dropna(subset=["finish_time_seconds"]).copy()
    y = df["finish_time_seconds"] / 3600.0
    y.name = "finish_time_hours"

    df["gender_encoded"] = (df["gender"] == "F").astype(int)
    df["age_at_race"] = df["year"] - df["birth_year"]

    logger.info("Loading athlete career history from DB…")
    history = _load_athlete_history(db_path)

    logger.info("Computing longitudinal features for %d rows…", len(df))
    long_features = df.apply(
        lambda row: _compute_longitudinal_features(row, history), axis=1
    )
    df = pd.concat([df, long_features], axis=1)

    # Impute: counts → 0, continuous → column median
    count_cols = ["career_race_count", "races_last_12_months", "prior_badwater_count"]
    for col in count_cols:
        df[col] = df[col].fillna(0)

    continuous_cols = [
        "days_since_last_race", "distance_step_up",
        "prior_badwater_avg_time_hrs", "avg_finish_time_100mi_hrs",
        "performance_trend", "age_at_race", "performance_score",
    ]
    for col in continuous_cols:
        median = df[col].median()
        df[col] = df[col].fillna(median)

    X = df[FEATURE_COLS].copy()
    logger.info("Feature matrix: %d rows × %d cols", len(X), len(X.columns))
    return X, y
