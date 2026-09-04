# UltraLine Build Roadmap

## Purpose

This document is the authoritative implementation guide for UltraLine. Read it before writing any code. Steps are ordered chronologically; each step satisfies dependencies of those that follow. Do not skip ahead.

---

## Context and UX

UltraLine estimates a runner's finish time for an ultramarathon they haven't yet run. The experience:

1. Runner uploads a GPX file for a race they've already completed and enters their finish time — this is the calibration anchor.
2. Runner optionally inputs personal details: gender, age.
3. Runner specifies the target race via one of three modes:
   - **Mode A** — Upload a GPX file for the target race
   - **Mode B** — Select a race from the DUV race list (requires GPX upload alongside it; DUV provides no course geometry)
   - **Mode C** — Fill in a manual form: distance, elevation gain/loss, surface type, month of race
4. App outputs a predicted finish time (with a confidence range) and a segment-level pacing strategy.

The model is **generalized across ultramarathons**, not Badwater-specific. A Badwater-specific sub-model (`data/models/badwater_finish_time_rf.pkl`) can remain for the case where the target race is Badwater, but is not the primary model going forward.

---

## Current State (as of last audit)

| Component | Status |
|---|---|
| `app.py` sidebar: GPX upload | Wired — feeds Course Overview tab |
| `app.py` sidebar: race selector | Collected, not used downstream |
| `app.py` sidebar: LT pace, goal time | Collected, not used — **remove** |
| `app.py`: Generate button | No click handler — **stub** |
| Race Plan tab | Info text only — **stub** |
| `src/course.py` | Implemented — `parse_gpx`, `downsample`, `mile_markers` |
| `src/scrapers/duv.py` | Implemented — event and athlete history endpoints |
| `src/data/db.py` | Implemented — 4-table SQLite schema, idempotent upserts |
| `src/data/race_history.py` | Implemented — resumable multi-year race fetch |
| `src/models/features.py` | Implemented — Badwater-specific longitudinal features |
| `src/models/train.py` | Implemented — Badwater RF model |
| Model → UI connection | **Does not exist** |
| Cross-race estimation | **Does not exist** |

---

## Step 0 — Expand anchor race data: Western States

**No code changes required.** The existing scripts handle this natively. `unfetched_athlete_ids` deduplicates against `athletes.fetched_at`, so athletes already fetched from Badwater are skipped automatically.

Western States is already in `data/races.json` as:
```
"Western States 100 Mile Endurance Run"
```
with 49 historical event IDs.

**Run in order:**

```bash
# Pull all Western States finisher results into race_events + results tables (~2 min)
python scripts/fetch_race_history.py "Western States 100 Mile Endurance Run"

# Fetch career histories for all Western States athletes not already in DB
# (athletes shared with Badwater are automatically skipped via fetched_at)
python scripts/fetch_athletes.py --race "Western States 100 Mile Endurance Run"
```

**Rationale:** Badwater athletes are a self-selected elite, road-heavy population. Western States brings in trail-specialist athletes and broadens the cross-race training pairs. The two populations partially overlap (many elite ultrarunners have run both), which is fine — it adds new athletes without replacing existing data.

**Verify:**
```bash
sqlite3 data/ultraline.db "SELECT race_name, COUNT(*) FROM results JOIN race_events USING(event_id) GROUP BY race_name ORDER BY COUNT(*) DESC LIMIT 5;"
sqlite3 data/ultraline.db "SELECT COUNT(*) FROM athletes WHERE fetched_at IS NOT NULL;"
sqlite3 data/ultraline.db "SELECT COUNT(*) FROM athlete_results;"
```

---

## Step 1 — Redesign sidebar inputs

**File:** `app.py`

**Remove:**
- Lactate threshold pace inputs (`pace_minutes`, `pace_seconds`) — no downstream logic; doesn't fit new UX
- Goal finish time inputs (`goal_hours`, `goal_minutes`, `goal_seconds`) — same

**Add — Past race section (required):**
- GPX upload for a completed race (label: "GPX file for a race you've completed")
- Finish time for that race: hours + minutes + seconds number inputs

**Add — Personal info section (optional):**
- Gender selector (Male / Female / Prefer not to say)
- Birth year number input (used to compute age_at_race)

**Repurpose — Target race section:**
- Radio or tab group: "Select race" | "Upload GPX" | "Enter manually"
- Mode A: file uploader for target race GPX
- Mode B: existing DUV race selectbox + file uploader for that race's GPX
- Mode C: manual form — distance (mi), elevation gain (ft), elevation loss (ft), surface type dropdown (Road / Gravel / Trail / Technical), month of race (1–12)

The existing course visualization (Course Overview tab) should remain and should switch to display the **target race** GPX when provided, not the past race GPX.

**Wire the Generate button** — currently `run_button` is assigned but never referenced. Add a click handler block: `if run_button:` that calls the inference pipeline (built in Step 6).

---

## Step 2 — Past race calibration pipeline

**New file:** `src/calibration.py`

Given a past race GPX and actual finish time, derive the runner's grade-adjusted effective pace. This is the primary individual calibration signal — it replaces LT pace.

**Logic:**
1. Parse past race GPX via `course.py` `parse_gpx()` — returns `points_df` with `distance_mi`, `grade_pct`, `elevation_ft`
2. Compute grade-adjusted distance (GAD) per segment: apply a GAP-style formula
   - Strava GAP approximation: `effective_distance = actual_distance × (1 + grade_pct / 100 × k)` where k ≈ 0.033 per % grade for uphill, 0.018 for downhill (tune empirically)
3. Sum GAD over the full course → `total_grade_adjusted_distance_mi`
4. `calibrated_pace_min_per_mi = finish_time_seconds / 60 / total_grade_adjusted_distance_mi`

**Returns:** A scalar `calibrated_pace_min_per_mi` (float). This is the feature fed into the cross-race model as the strongest individual signal.

**Expose:**
```python
def calibrate_from_result(gpx_file_obj, finish_time_seconds: int) -> float:
    """Returns flat-equivalent pace in min/mi."""
```

---

## Step 3 — Target race course features

Build a function that produces a standard course feature dict regardless of input mode.

**New file:** `src/course_features.py`

```python
def from_gpx(gpx_file_obj) -> dict:
    """Parse GPX via course.py and return course feature dict."""

def from_manual(distance_mi, gain_ft, loss_ft, surface: str, month: int) -> dict:
    """Build course feature dict from manual form inputs."""
```

**Course feature dict schema** (same structure for both functions):
```python
{
    "distance_mi":      float,
    "gain_ft":          float,
    "loss_ft":          float,
    "net_elevation_ft": float,   # gain_ft - loss_ft
    "surface":          str,     # "Road" | "Gravel" | "Trail" | "Technical"
    "month":            int,     # 1–12
    "difficulty_score": float,   # see Step 4
}
```

Mode B (DUV selector + GPX): call `from_gpx()` on the uploaded GPX; ignore DUV metadata for course geometry.

---

## Step 4 — Cross-race feature engineering

**File:** `src/models/cross_race_features.py` (new)

**Course difficulty score** — a single scalar normalizing across races. Computed from:
```
difficulty_score = distance_mi + (gain_ft / 100) + surface_penalty
```
where `surface_penalty`: Road=0, Gravel=0.5×distance_mi×0.05, Trail=distance_mi×0.12, Technical=distance_mi×0.20. These coefficients are initial estimates — treat as tunable.

**Features for the cross-race model:**

| Feature | Source | Notes |
|---|---|---|
| `calibrated_pace` | Step 2 | Individual calibration signal |
| `gender_encoded` | Sidebar | 0=M, 1=F, 0.5=unknown |
| `age_at_race` | Sidebar birth year | year_of_target_race - birth_year |
| `career_race_count` | `athlete_results` (DB) | Prior races for matched athlete, or 0 if no DB match |
| `past_distance_mi` | Past race GPX | Anchor race distance |
| `past_difficulty_score` | Step 4 | Difficulty of anchor race |
| `target_distance_mi` | Step 3 | Target race distance |
| `target_difficulty_score` | Step 4 | Difficulty of target race |
| `relative_difficulty` | Computed | `target_difficulty / past_difficulty` |
| `distance_delta_mi` | Computed | `target_distance - past_distance` |
| `distance_step_up` | Computed | 1 if target > past, else 0 |
| `surface_match` | Computed | 1 if same surface category, else 0 |
| `month_sin` | Step 3 | `sin(2π × month / 12)` — cyclical encoding |
| `month_cos` | Step 3 | `cos(2π × month / 12)` — cyclical encoding |

**Remove from feature set** (Badwater-specific, not generalizable):
- `prior_badwater_count`
- `prior_badwater_avg_time_hrs`
- `year` (was a Badwater field-evolution trend feature)

`career_race_count`, `races_last_12_months`, `days_since_last_race`, `performance_trend`, `avg_finish_time_100mi_hrs` remain if the athlete is matched in the DB; impute with column median otherwise.

---

## Step 5 — Build cross-race training pairs

**New script:** `scripts/build_cross_race_pairs.py`

Query `athlete_results` for all athletes with 2+ non-DNF finishes. For each athlete, enumerate all chronological pairs (Race A, Race B) where Race A year < Race B year and both have non-null `finish_time_seconds`.

**Output:** `data/training/cross_race_pairs.parquet`

**Schema:**
```
athlete_id, race_a_name, race_a_year, race_a_distance_mi, race_a_distance_unit,
race_a_surface, race_a_finish_time_seconds,
race_b_name, race_b_year, race_b_distance_mi, race_b_distance_unit,
race_b_surface, race_b_finish_time_seconds,
gender, birth_year
```

Note: `athlete_results` has `distance_value`, `distance_unit`, and `finish_time_seconds` but no GPX-derived elevation. The `difficulty_score` at this stage uses distance + surface only (no gain/loss). Elevation features enter when the user provides a GPX at inference time.

**Chronological split boundaries for this dataset:**
- Train: race_b_year < 2019
- Val: 2019–2021
- Test: 2022–present

Do not use random splits. This is longitudinal data; earlier pairs must train, later pairs must validate.

---

## Step 6 — Cross-race estimation model

**New file:** `src/models/cross_race_train.py`

Follow the same progression as `src/models/train.py`:
1. Baseline: predict Race B time as `calibrated_pace × target_distance_mi` (no model, just physics)
2. Ridge Regression: L2-regularized linear model with `StandardScaler`
3. Random Forest: 1000 estimators, `max_depth=10`, `min_samples_leaf=5`, `max_features=0.5`

Evaluate on validation set using MAE (primary) and RMSE (secondary). Report R² as sanity check. Do not touch the test set until final evaluation.

**Save best model:** `data/models/cross_race_finish_time_rf.pkl`

**New script:** `scripts/train_cross_race_model.py` — thin CLI wrapper (mirror `scripts/train_model.py` pattern)

---

## Step 7 — Inference pipeline and UI wiring

**New file:** `src/inference.py`

```python
def predict_finish_time(
    past_race_gpx,
    past_finish_time_seconds: int,
    target_course_features: dict,
    gender: str | None,
    birth_year: int | None,
) -> dict:
    """
    Returns {
        "predicted_hours": float,
        "low_hours": float,     # e.g. predicted × 0.90
        "high_hours": float,    # e.g. predicted × 1.10
        "features_used": dict,
    }
    """
```

Load model via `@st.cache_resource` in `app.py` to avoid reloading on every interaction.

**In `app.py`**, wire the Generate button:
```python
if run_button:
    result = predict_finish_time(...)
    st.metric("Predicted Finish Time", format_hours(result["predicted_hours"]))
    # ... render confidence range and pacing table
```

---

## Step 8 — Pacing strategy generation

**New file:** `src/pacing.py`

Given a predicted total finish time and a target race course (GPX or manual), generate a segment-level pacing plan.

**Logic:**
1. Compute grade-adjusted difficulty weight per segment (same GAP formula as Step 2)
2. Distribute total time proportionally across segments by difficulty weight
3. Apply a pace decay curve — front-half slightly faster, back-half slower. Parameterize by a decay factor derived from the runner's past race split pattern if available; otherwise use a population default (e.g., 5–8% second-half slowdown)
4. Return a DataFrame: `mile | estimated_pace_min_mi | estimated_clock_time | cumulative_distance_mi | elevation_ft`

**Requires:** Target race GPX (Modes A and B). Mode C (manual input) can only produce a coarse first-half/second-half split — state this limitation in the UI.

**Render in Race Plan tab:**
- Predicted finish time (metric, large)
- Confidence range (e.g. "likely between X and Y")
- Pacing table (st.dataframe)
- Optional: pace-over-distance line chart (Plotly)

---

## File Map

```
app.py                                  — Step 1, 7 (sidebar redesign, button wiring)
src/calibration.py                      — Step 2 (new)
src/course_features.py                  — Step 3 (new)
src/models/cross_race_features.py       — Step 4 (new)
src/inference.py                        — Step 7 (new)
src/pacing.py                           — Step 8 (new)
scripts/build_cross_race_pairs.py       — Step 5 (new)
scripts/train_cross_race_model.py       — Step 6 (new)
src/models/cross_race_train.py          — Step 6 (new)
src/models/features.py                  — Step 4 (update: remove Badwater-specific features)
data/training/cross_race_pairs.parquet  — Step 5 output
data/models/cross_race_finish_time_rf.pkl — Step 6 output
```

**Do not modify:**
- `src/course.py` — works as-is; called by calibration and course feature modules
- `src/scrapers/duv.py` — works as-is
- `src/data/db.py` — works as-is
- `src/data/race_history.py` — works as-is
- `data/models/badwater_finish_time_rf.pkl` — preserve; may be used as Badwater-specific sub-model later

---

## Dependency Order (summary)

```
Step 0  →  (no dependencies)
Step 1  →  (no dependencies; parallel with Step 0)
Step 2  →  Step 1 (needs past race GPX input to exist)
Step 3  →  Step 1 (needs target race input modes)
Step 4  →  Steps 2, 3 (defines features used in training and inference)
Step 5  →  Step 0 (needs Western States data in DB), Step 4 (feature schema)
Step 6  →  Step 5 (needs training pairs)
Step 7  →  Steps 2, 3, 6 (needs calibration, course features, trained model)
Step 8  →  Step 7 (needs finish time prediction to distribute)
```
