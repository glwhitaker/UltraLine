"""
Train finish time regression models for Badwater 135.

Steps:
  1. Load badwater_model_data.parquet
  2. Build feature matrix (features.py)
  3. Chronological train/val split (test set untouched until final eval)
  4. Baseline → Linear Regression → Random Forest
  5. Save best model to data/models/

Usage:
  python scripts/train_model.py
  python scripts/train_model.py --eval-test   # only once, at final evaluation
"""

import logging
import pickle
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.models.features import build_feature_matrix, FEATURE_COLS
from src.models.evaluate import regression_metrics, plot_feature_importance

logger = logging.getLogger(__name__)

TRAINING_DIR = Path(__file__).resolve().parents[2] / "data" / "training"
MODELS_DIR = Path(__file__).resolve().parents[2] / "data" / "models"
PARQUET = TRAINING_DIR / "badwater_ultramarathon_model_data.parquet"

# Chronological split boundaries
VAL_START_YEAR = 2017
TEST_START_YEAR = 2022


def _baseline_predict(y_train, X_val, gender_col_idx: int) -> np.ndarray:
    """Predict median finish time by gender from training set."""
    train_df = pd.DataFrame({"y": y_train})
    # gender_encoded: 0=M, 1=F
    # We need to reach back into the split — caller passes gender array
    return np.full(len(X_val), y_train.median())


def run_training(eval_test: bool = False, plots: bool = False):
    if not PARQUET.exists():
        raise FileNotFoundError(
            f"Parquet not found at {PARQUET}. "
            "Run: python scripts/export_training_data.py"
        )

    df = pd.read_parquet(PARQUET)
    logger.info("Loaded %d rows from %s", len(df), PARQUET)

    X, y = build_feature_matrix(df)
    years = df.loc[y.index, "year"]

    train_mask = years < VAL_START_YEAR
    val_mask = (years >= VAL_START_YEAR) & (years < TEST_START_YEAR)
    test_mask = years >= TEST_START_YEAR

    X_train, y_train = X[train_mask], y[train_mask]
    X_val, y_val = X[val_mask], y[val_mask]
    X_test, y_test = X[test_mask], y[test_mask]

    logger.info(
        "Split sizes — Train: %d  Val: %d  Test: %d",
        len(y_train), len(y_val), len(y_test)
    )

    # --- Step 1: Naive baseline (gender-stratified median) ---
    gender_train = X_train["gender_encoded"]
    median_M = y_train[gender_train == 0].median()
    median_F = y_train[gender_train == 1].median()
    baseline_preds = X_val["gender_encoded"].map({0: median_M, 1: median_F})
    print("\n=== Baseline (gender-median) ===")
    print(f"  Male median: {median_M:.2f} hrs  Female median: {median_F:.2f} hrs")
    regression_metrics(y_val, baseline_preds, label="Baseline")

    # --- Step 2: Ridge Regression (L2 regularization handles correlated features) ---
    lr = Pipeline([("scaler", StandardScaler()), ("model", Ridge(alpha=1.0, solver="sag", max_iter=10000))])
    lr.fit(X_train, y_train)
    with warnings.catch_warnings():
        # sklearn matmul on Apple Silicon can produce benign overflow warnings; predictions are valid
        warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*matmul.*")
        lr_preds = lr.predict(X_val)
    print("\n=== Ridge Regression ===")
    regression_metrics(y_val, lr_preds, label="Ridge")
    coefs = lr.named_steps["model"].coef_
    coef_df = pd.Series(coefs, index=FEATURE_COLS).sort_values(key=abs, ascending=False)
    print("  Coefficients (top 10, standardized scale):")
    print(coef_df.head(10).to_string())

    # --- Step 3: Random Forest ---
    rf = RandomForestRegressor(
        n_estimators=1000,
        max_depth=10,
        min_samples_leaf=5,
        max_features=0.5,
        random_state=42,
        n_jobs=-1
    )
    rf.fit(X_train, y_train)
    rf_preds = rf.predict(X_val)
    print("\n=== Random Forest ===")
    rf_metrics = regression_metrics(y_val, rf_preds, label="RF")
    imp_df = pd.Series(rf.feature_importances_, index=FEATURE_COLS).sort_values(ascending=False)
    print("  Feature importances:")
    print(imp_df.to_string())

    if plots:
        from src.models.evaluate import plot_residuals
        plot_feature_importance(
            FEATURE_COLS,
            rf.feature_importances_,
            label="Random Forest",
            out_dir=MODELS_DIR / "plots",
        )
        plot_residuals(y_val, rf_preds, label="Random Forest", out_dir=MODELS_DIR / "plots")

    # --- Save best model ---
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / "badwater_finish_time_rf.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(rf, f)
    logger.info("Model saved → %s", model_path)
    print(f"\nModel saved → {model_path}")

    # --- Final test eval (run once only) ---
    if eval_test:
        print("\n=== FINAL TEST SET EVALUATION ===")
        print("(This should only be run once at the end of model development)")
        rf_test_preds = rf.predict(X_test)
        regression_metrics(y_test, rf_test_preds, label="RF (TEST)")

    return rf, rf_metrics
