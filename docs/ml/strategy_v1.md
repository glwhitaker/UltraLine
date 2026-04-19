# ML Strategy: Data Analysis — Iteration 1

## Overview

This document defines the modeling strategy, feature set, data handling conventions, and evaluation workflow for UltraLine's predictive engine. The system is designed to be useful to any runner, with ultrarunners as the current focus. It is intended as a reference for implementation agents. Follow the constraints and ordering here unless explicitly overridden by the user.

---

## Data Strategy

### Primary Data Source
Public race results scraped from **DUV (Deutsche Ultramarathon Vereinigung)**, one of the most comprehensive ultramarathon results databases publicly available. This provides:
- Thousands of results across many races, distances, and years
- Athlete-level identifiers enabling cross-race longitudinal profiling
- Historical depth sufficient for population-level modeling
- **DNF data is not available from DUV.** Neither the event results page nor the athlete personal page exposes DNF records in a parseable form. DUV publishes finishers only. Any feature requiring DNF history must come from an alternative source.

### Secondary Data Source
Detailed fitness history for one elite ultramarathoner (training logs, physiological data). Used for individual model calibration and validation, not primary training.

### Data Collection Phases

**Phase 1 — Index (complete)**
A map of races and their DUV IDs across multiple years has been constructed. This serves as the reference index for all subsequent data pulls.

**Phase 2 — Anchor race deep pull (complete)**
Pull all available results for the anchor race (Badwater 135) — every finisher across all available years. Capture athlete IDs alongside results to enable longitudinal cross-referencing. Note: DNF records are not available from DUV; only finisher rows are published.

**Phase 3 — Data audit**
Before modeling, document the actual shape of the data: results per year, field population rates, DNF record structure, and any inconsistencies. This drives all subsequent feature and pipeline decisions.

**Phase 4 — Related race expansion**
Pull results from races that share athlete pools with Badwater 135 (e.g. Western States, Leadville, Moab 240). Used to build longitudinal athlete profiles from public data.

### Known Data Considerations
- DUV coverage skews European; Badwater 135 is American-centric and may have thinner coverage than European ultras
- Surface and course difficulty vary widely across events; race type encoding is important
- Result quality is uneven across self-reported events; audit for sparse fields before relying on them

---

## Modeling Architecture

### Core Pattern: Population Model + Individual Calibration

1. **Population model** — trained on the full public results dataset; learns general performance patterns across many runners and races
2. **Individual calibration** — when a specific athlete's detailed data is available, fine-tune or calibrate the population model to that athlete
3. **Fallback** — with no personal data, the population model alone produces reasonable predictions

This pattern mirrors how production fitness and health platforms handle personalization. It is appropriate given the data available and is the target architecture for UltraLine.

---

## Distinct Modeling Tasks

There are four separate prediction problems. Do not conflate them.

| Task | Type | Notes |
|---|---|---|
| **Pace decay prediction** | Regression | Predict sustainable pace for the next segment given distance, elevation, heat, and accumulated fatigue |
| **Finish time prediction** | Regression | Predict expected finish time given a runner profile and course |
| **DNF probability** | Classification | Given splits at intermediate checkpoints, predict probability of finishing; high operational value for crew decision-making |
| **Crew stop optimization** | Optimization (not ML) | Determine optimal stop duration and strategy at each crew access point; use `scipy` or similar operations research tooling |

---

## Model Selection

### Guiding Principle
Model choice matters less than clean data and well-engineered features. Do not reach for complexity before validating data quality.

### Recommended Progression (implement in order)

1. **Baseline** — predict mean pace / modal finish time / historical DNF rate; this is the performance floor all models must beat
2. **Linear Regression / Logistic Regression** — interpretable, fast, establishes feature importance for regression and classification tasks respectively
3. **Random Forest** — primary model; handles non-linear relationships and tabular data well; provides feature importance scores
4. **Gradient Boosting (XGBoost)** — optional step if further performance gains are needed

### Rationale for Avoiding Neural Networks at This Stage
While the public dataset is large in result count, it is relatively shallow in features per result. Neural networks require both volume and feature richness to generalize. A well-tuned Random Forest on tabular results data will outperform a neural network at this stage.

---

## Feature Set

### Population-Level Features (derivable from public results)
- `race_distance` — nominal distance of the event
- `race_type` — surface/format encoding (road, trail, track, etc.)
- `finishing_time` — target variable for finish time prediction
- `checkpoint_splits` — intermediate split times where available
- `dnf_flag` — boolean finish/DNF outcome (**not available from DUV**; omit or source elsewhere)
- `athlete_age_group` — where available in results
- `year` — race year; captures field evolution over time

### Longitudinal Athlete Features (derived by cross-referencing athlete IDs)
- `athlete_race_count` — total number of DUV-recorded races; proxy for experience level
- `races_last_12_months` — race frequency over the past year; volume signal
- `days_since_last_race` — days between most recent race and current race; freshness/recovery signal
- `distance_step_up` — boolean; is this race longer than the athlete's previous longest distance? Step-ups carry elevated risk
- `avg_finish_time_by_distance` — mean finish time for races at this distance; baseline performance expectation
- `performance_trend` — slope of finish time over last N races at similar distance; captures improvement or decline

### Segment-Level Features (for pace decay modeling)
- `distance_into_race` — cumulative distance at segment start
- `cumulative_elevation_gain` — total elevation gain to current segment
- `segment_grade` — grade (%) of the current segment
- `temperature` — ambient temperature at segment
- `wet_bulb_temperature` — heat stress proxy; prefer over dry bulb alone
- `time_of_day` — wall clock time
- `hours_since_race_start` — elapsed race time
- `rolling_avg_pace_n_miles` — average pace over last N miles (N is tunable)
- `heart_rate` — if available from device data
- `miles_to_next_crew_point`
- `miles_to_next_aid_station`

### Engineered Features (high priority)
- **Race volume and recency features** — ACWR is not applicable here; it requires continuous daily/weekly training load data and is designed for athletes training at high frequency. Ultramarathon athletes race infrequently (weeks to months between events), making the 7-day/28-day rolling window meaningless. Use `races_last_12_months`, `days_since_last_race`, and `distance_step_up` instead — these capture the same underlying concern (is the athlete fresh and adequately prepared?) from data that actually exists
- **Grade-adjusted pace** — apply a formula consistent with Strava's GAP metric; normalizes pace across elevation profiles
- **Heat stress thresholds** — pace/heat relationship is non-linear; performance degrades sharply past certain wet bulb thresholds; encode threshold crossings as binary features in addition to raw values
- **Checkpoint pace deltas** — rate of pace change between checkpoints; strong signal for both finish time and DNF prediction

> Feature engineering will likely yield more improvement than model switching. Prioritize this work over hyperparameter tuning.

---

## Data Splitting

### Split Ratios
- Training: ~70%
- Validation: ~15%
- Test: ~15%

### Critical Constraint: Chronological Split
This is time series data — order matters. **Do not use random splits.** Split chronologically: earlier race years train the model, later years validate and test. This mirrors real-world usage.

### Test Set Protocol
The test set is touched **once**, at the end, to report final performance. Do not evaluate on the test set during iterative development. Repeated evaluation against the test set introduces optimistic bias.

---

## Overfitting and Underfitting

### Definitions
- **Overfitting**: training error low, validation error substantially higher → model is memorizing noise
- **Underfitting**: both errors high → model is too simple

### Mitigations

| Tool | When to Apply |
|---|---|
| Cross-validation (K-fold) | Standard practice; use instead of a single train/val split for more stable estimates |
| Regularization | Linear models: Ridge (L2) or Lasso (L1); tree models: `max_depth`, `min_samples_leaf` |
| Early stopping | Gradient boosting only; stop adding trees when validation error plateaus |
| Feature pruning | Use Random Forest feature importances to drop low-signal features |

---

## Evaluation Metrics

### Regression Tasks (pace decay, finish time)

| Metric | Priority | Notes |
|---|---|---|
| **MAE (Mean Absolute Error)** | Primary | Interpretable as "off by X minutes"; most meaningful to the end user |
| **RMSE (Root Mean Squared Error)** | Secondary | Penalizes large errors more; useful if prediction blowouts are especially costly |
| **R²** | Sanity check | Values near 0 mean the model is no better than predicting the mean |

### Classification Task (DNF probability)

| Metric | Priority | Notes |
|---|---|---|
| **AUC-ROC** | Primary | Measures discrimination across all thresholds |
| **Precision / Recall** | Secondary | Evaluate based on cost asymmetry; missing a DNF risk may be more costly than a false alarm |
| **Calibration** | Sanity check | Predicted probabilities should reflect actual DNF rates |

Always evaluate on the validation set during development. Report final numbers on the test set once at the end.

---

## Hyperparameter Tuning

### Approach
1. Train with sklearn defaults first
2. Evaluate; if improvement is warranted, run `RandomizedSearchCV` over the parameter space below
3. Use Bayesian optimization (e.g., `Optuna`) if search space is large and compute allows

### Random Forest Parameters to Tune

| Parameter | Controls |
|---|---|
| `n_estimators` | Number of trees; more is generally better up to diminishing returns |
| `max_depth` | Tree depth; primary overfitting lever |
| `min_samples_leaf` | Minimum samples at leaf nodes; secondary overfitting lever |
| `max_features` | Features considered at each split |

> Do not tune hyperparameters before validating data quality and feature set. Tuning bad features is wasted effort.

---

## Implementation Workflow

Execute in this order. Do not skip ahead.

```
1. Anchor race data pull     → pull all Badwater 135 results from DUV; capture athlete IDs
2. Data audit                → document field population, result counts, DNF structure
3. Related race expansion    → pull results from races sharing the Badwater athlete pool
4. Longitudinal profiles     → cross-reference athlete IDs to build historical feature set
5. Baseline model            → predict mean / historical rate; record metrics
6. Logistic regression       → DNF classification baseline
7. Linear regression         → finish time and pace regression baseline
8. Random Forest             → train with defaults on both tasks; compare
9. Feature engineering       → add ACWR proxy, GAP, heat thresholds, checkpoint deltas; retrain
10. Cross-validation         → K-fold on best model for stable performance estimate
11. Hyperparameter tuning    → randomized search on best model
12. Individual calibration   → fine-tune population model on single-athlete fitness data
13. Final evaluation         → run on test set once; record and report metrics
14. Integration              → wire into app if performance is acceptable
```

---

## Libraries and Tooling

| Purpose | Library |
|---|---|
| Tabular ML (primary) | `scikit-learn` |
| Gradient boosting | `xgboost` |
| Hyperparameter optimization | `optuna` or `sklearn.model_selection.RandomizedSearchCV` |
| Crew stop optimization | `scipy.optimize` |
| Data manipulation | `pandas`, `numpy` |
| Evaluation and plotting | `matplotlib`, `seaborn` |

---

*This document reflects Iteration 1 strategy. Update when modeling assumptions change or new data sources are incorporated.*