# ML Strategy: Data Analysis — Iteration 1 (amended)

## Overview

This document defines the modeling strategy, feature set, data handling conventions, and evaluation workflow for UltraLine's predictive engine. The system is designed to be useful to any runner, with ultrarunners as the current focus. It is intended as a reference for implementation agents. Follow the constraints and ordering here unless explicitly overridden by the user.

---

## Data Strategy

### Primary Data Source
Public race results scraped from **DUV (Deutsche Ultramarathon Vereinigung)**, one of the most comprehensive ultramarathon results databases publicly available. This provides:
- Thousands of results across many races, distances, and years
- Athlete-level identifiers enabling cross-race longitudinal profiling
- Historical depth sufficient for population-level modeling
- **DNF data is available from DUV at the athlete history level.** The event results page (`getresultevent.php`) publishes finishers only. However, the athlete personal page (`getresultperson.php`) does expose DNF and DNS records in each athlete's career history. These are parsed and stored in `athlete_results.dnf` (1 = DNF/DNS, 0 = finish). DNF data is therefore available as a longitudinal career feature but cannot be derived from event-level scraping alone.

### Secondary Data Source
Detailed fitness history for one elite ultramarathoner (training logs, physiological data). Used for individual model calibration and validation, not primary training.

### Data Collection Phases

**Phase 1 — Index (complete)**
A map of all DUV races and their event IDs across all available years has been constructed via paginated scraping of `geteventlist.php` (~116 pages, 115k+ events). Stored in `data/races.json`. This serves as the reference index for all subsequent data pulls.

**Phase 2 — Anchor race deep pull (complete)**
All available results for the anchor race (Badwater 135) have been pulled — every finisher across all available years — via `fetch_race_history.py`. Athlete IDs are captured alongside results and stored in SQLite (`race_events` and `results` tables) to enable longitudinal cross-referencing.

**Phase 3 — Full athlete career pull (complete)**
Rather than pulling results for specific related races, the full DUV career history for every athlete who has ever appeared in a Badwater result is fetched via `fetch_athletes.py`. This uses the athlete personal page (`getresultperson.php`) to retrieve every race that athlete has ever recorded on DUV — regardless of race name, distance, or country. Results are stored in `athlete_results`.

This approach is broader than a targeted related-race expansion. It captures Western States, Leadville, Moab 240, and any other race the athlete has run, without requiring those races to be explicitly named or their event IDs to be known in advance. The tradeoff is that `athlete_results` contains heterogeneous race data (varying distances, surfaces, and formats) that must be filtered carefully during feature engineering.

The scraper is resumable: `fetched_at` on the `athletes` table acts as a progress flag. Re-running `fetch_athletes.py` skips already-fetched athletes automatically.

**Phase 4 — Data audit**
Before expanding modeling beyond Badwater, document the actual shape of the data: results per year, field population rates, null rates per column, and surface/distance distribution in `athlete_results`. Known issues to audit for:
- Early Badwater years (pre-1990) have thin or missing finish time data
- Course distance was 146mi in early editions, not 135mi
- DUV coverage skews European; some American athletes may have sparse histories

**Phase 5 — GPX course feature derivation (planned)**
Parse GPX data for the anchor race course to derive segment-level features: grade, cumulative elevation gain, distance to crew points, distance to aid stations. This is the primary data source for pace decay modeling and cannot be derived from DUV results. Some infrastructure exists in `src/course.py`.

### Known Data Considerations
- `athlete_results` contains the full career history of each Badwater athlete — not filtered to any specific race or distance. Feature engineering must filter appropriately (e.g. `distance_value = 100 AND distance_unit = 'mi'` for 100-mile comparisons) and must use only pre-race history to avoid temporal leakage
- Surface and course difficulty vary widely across events in `athlete_results`; a road 100-miler and a mountain trail 100-miler are not directly comparable. Surface encoding will matter when using cross-race pace data as features
- `results` (event-level) and `athlete_results` (career-level) overlap in coverage — both contain finish times for many of the same races. They are complementary, not redundant: `results` has richer per-finish detail (place, age group, performance score); `athlete_results` has DNF flags and broader career coverage
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
- `dnf_flag` — boolean finish/DNF outcome; available from `athlete_results.dnf` (sourced from athlete personal page, not event results page)
- `athlete_age_group` — where available in results
- `year` — race year; captures field evolution over time

### Longitudinal Athlete Features (derived from `athlete_results`)
These features are computed per-athlete using only races prior to the race being predicted. This is enforced in `features.py` via strict `year < race_year` filtering. Violating this constraint introduces temporal leakage.

- `career_race_count` — total prior DUV-recorded races; proxy for experience level
- `races_last_12_months` — race frequency over the prior year; volume signal
- `days_since_last_race` — days between most recent prior race and current race; freshness/recovery signal
- `distance_step_up` — boolean; is this race longer than the athlete's previous longest distance? Step-ups carry elevated risk
- `avg_finish_time_100mi_hrs` — mean finish time for prior 100-mile finishes across all races in `athlete_results`; strongest available pace signal
- `prior_badwater_count` — number of prior Badwater finishes; course-specific experience
- `prior_badwater_avg_time_hrs` — mean finish time for prior Badwater finishes; course-specific pace baseline
- `performance_trend` — slope of finish time over last 5 finishes at ≥100mi; captures improvement or decline
- `has_history` — binary flag; whether any prior race history exists for this athlete (low-signal; candidate for removal)

Note: ACWR (Acute:Chronic Workload Ratio) is not applicable here. It requires continuous daily/weekly training load data designed for high-frequency training. Ultramarathon athletes race infrequently; use `races_last_12_months`, `days_since_last_race`, and `distance_step_up` to capture the same underlying concerns from data that actually exists.

### Segment-Level Features (for pace decay modeling — requires GPX)
These features cannot be derived from DUV. They require GPX course data and, where available, live athlete device data.

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
- **Grade-adjusted pace** — apply a formula consistent with Strava's GAP metric; normalizes pace across elevation profiles; requires GPX
- **Heat stress thresholds** — pace/heat relationship is non-linear; performance degrades sharply past certain wet bulb thresholds; encode threshold crossings as binary features in addition to raw values
- **Checkpoint pace deltas** — rate of pace change between checkpoints; strong signal for both finish time and DNF prediction
- **Surface-normalized pace** — when computing `avg_finish_time_100mi_hrs` across heterogeneous `athlete_results`, consider normalizing by surface type to avoid treating road and trail 100-milers as equivalent

> Feature engineering will likely yield more improvement than model switching. Prioritize this work over hyperparameter tuning.

---

## Data Splitting

### Split Ratios
- Training: ~70%
- Validation: ~15%
- Test: ~15%

Current boundaries for Badwater finish time model:
- Train: years < 2017 (~1,105 rows after null drop)
- Val: 2017–2021 (~291 rows)
- Test: 2022–present (~333 rows)

### Critical Constraint: Chronological Split
This is time series data — order matters. **Do not use random splits.** Split chronologically: earlier race years train the model, later years validate and test. This mirrors real-world usage.

### Cross-Validation Note
Standard K-fold cross-validation randomly mixes folds and is **not appropriate** for time-series data. If cross-validation is used for more stable performance estimates, use `sklearn.model_selection.TimeSeriesSplit`, which respects chronological order.

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
| Cross-validation (TimeSeriesSplit) | Use instead of a single train/val split for more stable estimates; must be time-aware |
| Regularization | Linear models: Ridge (L2) or Lasso (L1); tree models: `max_depth`, `min_samples_leaf` |
| Early stopping | Gradient boosting only; stop adding trees when validation error plateaus |
| Feature pruning | Use Random Forest feature importances to drop low-signal features; `has_history` is a current candidate for removal |

---

## Evaluation Metrics

### Regression Tasks (pace decay, finish time)

| Metric | Priority | Notes |
|---|---|---|
| **MAE (Mean Absolute Error)** | Primary | Interpretable as "off by X hours/minutes"; most meaningful to the end user |
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
| `max_features` | Features considered at each split; reducing forces more feature diversity across trees |

> Do not tune hyperparameters before validating data quality and feature set. Tuning bad features is wasted effort.

---

## Implementation Workflow

Execute in this order. Do not skip ahead.

```
1. Anchor race data pull        → pull all Badwater 135 results from DUV; capture athlete IDs
                                   stored in: race_events, results tables
2. Full athlete career pull     → for every athlete_id in Badwater results, fetch their complete
                                   DUV history via getresultperson.php; stored in: athletes,
                                   athlete_results tables; resumable via fetched_at flag
3. Data audit                   → document field population, null rates, finish time coverage
                                   by year, distance/surface distribution in athlete_results
4. Export training data         → derive Parquet snapshots from SQLite via export_training_data.py;
                                   produces population_results, athlete_features, model_data
5. Baseline model               → predict gender-stratified median finish time; record metrics
6. Linear regression (Ridge)    → finish time regression with L2 regularization; record metrics
7. Random Forest                → train with defaults; compare to baseline and Ridge
8. Feature engineering          → add surface-normalized pace, expand longitudinal features;
                                   re-export and retrain
9. Cross-validation             → TimeSeriesSplit on best model for stable performance estimate
10. Hyperparameter tuning       → RandomizedSearchCV on best model
11. GPX course feature pipeline → parse course GPX; derive segment-level features for
                                   pace decay and DNF modeling
12. DNF probability model       → classification model using checkpoint splits + career features
13. Individual calibration      → fine-tune population model on single-athlete fitness data
14. Final evaluation            → run on test set once; record and report metrics
15. Integration                 → wire into app if performance is acceptable
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

*This document reflects Iteration 1 strategy (amended). Update when modeling assumptions change or new data sources are incorporated.*