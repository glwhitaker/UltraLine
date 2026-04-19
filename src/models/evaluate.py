"""
Evaluation helpers for regression models.
"""

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

logger = logging.getLogger(__name__)


def regression_metrics(y_true, y_pred, label: str = "") -> dict:
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    r2 = r2_score(y_true, y_pred)
    prefix = f"[{label}] " if label else ""
    print(f"{prefix}MAE: {mae:.2f} hrs  RMSE: {rmse:.2f} hrs  R²: {r2:.3f}")
    return {"mae": mae, "rmse": rmse, "r2": r2}


def plot_residuals(y_true, y_pred, label: str = "", out_dir: Path = None):
    residuals = np.array(y_true) - np.array(y_pred)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))

    axes[0].scatter(y_pred, residuals, alpha=0.3, s=10)
    axes[0].axhline(0, color="red", linewidth=1)
    axes[0].set_xlabel("Predicted finish time (hrs)")
    axes[0].set_ylabel("Residual (hrs)")
    axes[0].set_title(f"{label} — Predicted vs Residual")

    axes[1].hist(residuals, bins=40, edgecolor="white")
    axes[1].set_xlabel("Residual (hrs)")
    axes[1].set_ylabel("Count")
    axes[1].set_title(f"{label} — Error Distribution")

    plt.tight_layout()
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"residuals_{label.lower().replace(' ', '_')}.png"
        plt.savefig(path, dpi=120)
        logger.info("Saved residual plot → %s", path)
    plt.show()


def plot_feature_importance(feature_names, importances, label: str = "", out_dir: Path = None):
    idx = np.argsort(importances)[::-1]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(range(len(importances)), importances[idx])
    ax.set_xticks(range(len(importances)))
    ax.set_xticklabels([feature_names[i] for i in idx], rotation=45, ha="right", fontsize=8)
    ax.set_title(f"{label} — Feature Importances")
    plt.tight_layout()
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"importances_{label.lower().replace(' ', '_')}.png"
        plt.savefig(path, dpi=120)
        logger.info("Saved importance plot → %s", path)
    plt.show()
