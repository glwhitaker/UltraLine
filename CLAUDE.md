# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

UltraLine is a generalized ultramarathon race execution optimizer deployed as a Streamlit web app. Users upload a GPX course file, define aid stations, crew access points, and pacer eligibility rules, then input a runner profile and race goals. The app outputs a personalized pacing strategy and crew execution plan.

The core problem is constrained optimization: given a course profile (elevation, grade, distance), environmental conditions (temperature, humidity, wet bulb temperature, time of day), and logistical constraints (crew access points, pacer start mile, aid station spacing), minimize finish time while managing fatigue and resupply needs. The fatigue model accounts for grade-adjusted pace, heat stress, and cumulative workload decay over distance.

Initial focus race is **Badwater 135**, backed by a world-class ultramarathoner's personal GPS/HR/splits data across multiple finishes — the primary training and demo dataset.

## Tech Stack

| Layer | Libraries |
|---|---|
| Frontend | `streamlit`, `folium` + `streamlit-folium`, `plotly` |
| Data | `gpxpy`, `pandas`, `numpy` |
| Modeling | `scikit-learn` (fatigue/pace decay), `scipy` (constrained optimization) |
| Weather | NOAA API (historical + forecast by location/date) |
| Athlete data | Strava or Garmin export (GPS, HR) |
| External data | UltraSignup + DUV scraped for historical splits and DNF patterns |

Deployed via Streamlit Community Cloud from this GitHub repo.

## App Structure

**Sidebar** — all user inputs: GPX upload, runner profile (lactate threshold pace as mm:ss), race goals (finish time as hh:mm:ss), risk tolerance.

**Main panel tabs:**
- `Course Overview` — interactive folium map
- `Race Plan` — segment-by-segment pacing table

## Key Modules

- `course.py` — GPX parsing; returns clean course profile with elevation, grade per segment, and distance
- Additional modules TBD as the project develops

## Model Features

Features are grouped by source. Not all sources are implemented yet — this is the target feature set.

**Course Geometry** *(from GPX)*
- Total distance; min/max/average elevation
- Net and cumulative elevation gain/loss
- Grade % per segment; max uphill and downhill grade
- % course uphill / flat / downhill
- Longest continuous climb and descent (distance + gain/loss)
- Elevation at each aid station

**Aid Station & Crew Logistics** *(user input)*
- Mile marker, distance between, and elevation of each aid station
- Crew access points and distance between them
- Pacer eligibility mile marker; number of pacer swap opportunities
- Whether crew can leapfrog continuously or only at fixed points

**Environmental / Weather** *(NOAA API)*
- Temperature, humidity, wind speed/direction by segment
- Wet bulb temperature per segment (primary heat stress metric)
- Solar radiation / UV index
- Precipitation probability
- Sunrise/sunset times relative to race start; projected hours of darkness

**Surface & Terrain** *(user input or scraped)*
- Surface type per segment (paved, gravel, singletrack, technical)
- Trail technicality rating (runnable vs hike-mandatory)
- Exposure level (open/sunny vs shaded)

**Historical Race Data** *(scraped — UltraSignup, DUV)*
- DNF rate by year; historical finish times by competitive tier
- Aid station splits for top / median / back-of-pack finishers
- Common DNF locations on course
- Weather-vs-finish-time correlations year over year
- Historical pace decay curves (front-half vs back-half slowdown)

**Logistical** *(user input)*
- Race start time
- Cutoff times at each aid station
- Projected distance before heat peak; distance covered in darkness

## Development Notes

- Code should be modular and loosely coupled — the project is built iteratively
- Preferred deployment target: Streamlit Community Cloud
