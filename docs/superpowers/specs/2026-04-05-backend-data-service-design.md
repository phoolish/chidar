# ChiDar Iteration 2: Backend Data Service Design

**Date:** 2026-04-05
**Scope:** Server-side sync from Chicago SODA API, data enrichment, versioned JSON endpoint

---

## Overview

A Python-based data pipeline runs as a GitHub Actions cron job. It fetches raw camera data from the Chicago SODA API, enriches it with zone type and speed limit data, validates the output, diffs against the previously published dataset, and publishes a versioned `cameras.json` to GitHub Pages.

The Android app (Iteration 3) consumes the published JSON from a stable GitHub Pages URL.

---

## Repository Structure

```
data/
  sync.py              # main pipeline script (all stages)
  overrides.json       # manual speed limit overrides for park zone cameras
  requirements.txt     # requests, shapely, pytest
  tests/
    test_fetch.py
    test_enrich.py
    test_validate.py

.github/workflows/
  data-sync.yml        # daily cron + manual trigger
  data-ci.yml          # Python tests on PR (path-filtered) and on merge to main

docs/
  (gh-pages branch — cameras.json and manifest.json published here)
```

**Published URL:** `https://lphilbrook.github.io/chidar/cameras.json`

---

## Pipeline Stages

`sync.py` runs five stages in sequence. Any stage failure exits non-zero, skipping the publish step and leaving the live `cameras.json` untouched.

### 1. Fetch

- Pull raw camera records from SODA API dataset `4i42-qv3h` using `SOCRATA_APP_TOKEN` from environment
- Fetch Chicago Parks GeoJSON from the same portal (unauthenticated)
- Cache raw responses to disk so re-runs during development don't repeatedly hit the API

### 2. Enrich

For each camera:

- **Zone type:** Point-in-polygon check — is the camera's lat/lng inside a Chicago park boundary? If yes → `park`. If no → `school`. No other dataset needed; park polygon check is definitive.
- **Speed limit:**
  - `school` zone → always `20` MPH
  - `park` zone → query OSM Overpass API for nearest road's `maxspeed` tag. If OSM returns nothing → check `overrides.json`. If still nothing → log a warning and set `null` (never silently defaults)

### 3. Validate

- All required fields present on every record
- Lat/lng within Chicago bounds
- No `null` speed limits — pipeline fails if any park zone camera is unresolved
- Camera count within plausible range (warn if <100 or >250)

### 4. Diff

- Fetch currently published `cameras.json` from GitHub Pages
- Compare against newly generated data; report added, removed, and changed cameras
- Diff summary written to `manifest.json`
- If >15 cameras change in a single run → pipeline fails (likely bad API pull, not legitimate update)
- First run (no previous `cameras.json`): diff step is skipped

### 5. Write

Produce two files for publishing:

**`cameras.json`:**
```json
{
  "version": "1.0",
  "last_updated": "2026-04-05T06:00:00Z",
  "cameras": [
    {
      "id": "CHI-1234",
      "source_location_id": "1234",
      "latitude": 41.8781,
      "longitude": -87.6298,
      "speed_limit_mph": 30,
      "first_approach": "northbound",
      "second_approach": "southbound",
      "enforcement_zone": "school",
      "street": "S Western Ave",
      "cross_street": "W 47th St",
      "active": true,
      "go_live_date": "2023-01-15",
      "last_verified": "2026-04-05T06:00:00Z"
    }
  ]
}
```

**`manifest.json`:**
```json
{
  "generated_at": "2026-04-05T06:00:00Z",
  "camera_count": 162,
  "warnings": [],
  "diff": {
    "added": [],
    "removed": [],
    "changed": []
  }
}
```

- `id` = `"CHI-" + source_location_id` — stable, traceable, prefixed to avoid collisions
- `second_approach` is nullable
- `speed_limit_mph` is never null in valid published output — pipeline fails before publishing if any are unresolved
- Schema version bumps on breaking field changes; app ignores unrecognized fields for forward compatibility

---

## GitHub Actions Workflows

### `data-sync.yml`

```
triggers:
  - cron: daily at 6am UTC
  - workflow_dispatch (manual trigger)

steps:
  1. Checkout repo
  2. Set up Python
  3. Install dependencies (requirements.txt)
  4. Run sync.py (env: SOCRATA_APP_TOKEN from secret)
  5. Publish cameras.json + manifest.json to gh-pages (only on exit 0)
```

Failure leaves the live `cameras.json` untouched. GitHub Actions email notification handles alerting on failure.

### `data-ci.yml`

```
triggers:
  - pull_request (paths: data/**)  — only when data/ files change
  - push to main                   — always runs, no path filter

steps:
  1. Checkout repo
  2. Set up Python
  3. Install dependencies
  4. Run pytest data/tests/
```

---

## Enrichment Details

### Zone Type: Point-in-Polygon

- Source: Chicago Parks GeoJSON (Chicago Data Portal, free)
- Library: `shapely` — `Point.within(Polygon)`
- If camera is inside any park polygon → `park` zone
- Otherwise → `school` zone (default)

### Speed Limits: OSM Overpass API

- Query: find the nearest road way within 50m of the camera coordinates, return its `maxspeed` tag
- If found → use that value (convert from km/h if needed)
- If not found → check `overrides.json` keyed by `source_location_id`
- If still not found → `null` + warning logged; pipeline fails at validate stage
- `overrides.json` is manually curated and committed to the repo

---

## Testing Strategy

Tests are written before implementation (TDD). All tests are in `data/tests/` and run via `pytest`.

**`test_fetch.py`**
- Mock HTTP responses for SODA API and parks/schools datasets
- Assert raw records parsed correctly
- Assert app token sent in request header

**`test_enrich.py`**
- Point-in-polygon: camera inside park, outside park, on boundary
- OSM lookup: found, not found → override, not found → null + warning
- School zone always returns 20 MPH

**`test_validate.py`**
- Missing required fields → fails
- Lat/lng outside Chicago bounds → fails
- Null speed limit → fails
- Camera count out of range → warns
- Valid dataset → passes

---

## Configuration

| Variable | Source | Purpose |
|---|---|---|
| `SOCRATA_APP_TOKEN` | GitHub secret / local `.envrc` | SODA API authentication |

No other secrets required. OSM Overpass API is unauthenticated.

---

## Known Limitations

- **School calendar not integrated (v1):** School zone cameras only enforce on school days, but this pipeline has no awareness of the CPS calendar. The app will alert on all weekdays during school zone hours. Documented as a known false-positive source; CPS calendar integration is a v2 enhancement.
- **OSM coverage:** `maxspeed` tags may be missing for some park zone roads in Chicago. `overrides.json` is the fallback; the pipeline surfaces gaps explicitly rather than silently defaulting.

---

## Verification Criteria

- GitHub Action runs on cron and produces valid `cameras.json` accessible at the GitHub Pages URL
- Manual `workflow_dispatch` trigger works for on-demand runs
- Diff summary visible in GitHub Actions run summary
- Pipeline fails loudly (non-zero exit) on validation errors or safety threshold breach, leaving live data untouched
- All pytest tests pass in `data-ci.yml`
