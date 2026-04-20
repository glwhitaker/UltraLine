#!/usr/bin/env python
"""
CLI entry point for training Badwater finish time regression models.

Usage:
  python scripts/train_model.py
  python scripts/train_model.py --eval-test   # run test set eval (once, at the end)
  python scripts/train_model.py --plots       # save residual + importance plots
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

from src.models.train import run_training


def main():
    parser = argparse.ArgumentParser(description="Train Badwater finish time model")
    parser.add_argument(
        "--eval-test",
        action="store_true",
        help="Also evaluate on held-out test set (use once at final evaluation only)",
    )
    parser.add_argument(
        "--plots",
        action="store_true",
        help="Save feature importance and residual plots to data/models/plots/",
    )
    args = parser.parse_args()
    run_training(eval_test=args.eval_test, plots=args.plots)


if __name__ == "__main__":
    main()
