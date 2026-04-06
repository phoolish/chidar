# Backend Data Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python pipeline (GitHub Action cron) that fetches Chicago speed camera data from the SODA API, enriches it with zone type and speed limits, and publishes a versioned `cameras.json` to GitHub Pages.

**Architecture:** A single `data/sync.py` script runs five stages (fetch → enrich → validate → diff → write) and is invoked by `data-sync.yml` on a daily cron. A separate `data-ci.yml` runs pytest on PRs that touch `data/` and on every merge to main. Output is published to the `gh-pages` branch and served at a stable GitHub Pages URL.

**Tech Stack:** Python 3.12, requests, shapely (point-in-polygon), OSM Overpass API, peaceiris/actions-gh-pages

---

## File Map

**Create:**
- `data/sync.py` — all pipeline stages as importable functions + `main()`
- `data/overrides.json` — manual speed limit overrides keyed by `source_location_id`
- `data/requirements.txt` — `requests`, `shapely`, `pytest`
- `data/tests/__init__.py` — empty package marker
- `data/tests/test_fetch.py` — tests for `fetch_cameras`, `fetch_parks`
- `data/tests/test_enrich.py` — tests for `determine_zone_type`, `_parse_maxspeed`, `query_osm_speed_limit`, `get_speed_limit`, `enrich_cameras`
- `data/tests/test_validate.py` — tests for `validate_cameras`, `diff_cameras`, `write_output`
- `pytest.ini` — pytest config at repo root
- `.github/workflows/data-ci.yml` — Python CI workflow
- `.github/workflows/data-sync.yml` — daily cron sync workflow

**Modify:**
- `.gitignore` — add `data/.cache/` and `data/output/`

---

## Task 1: Project Scaffolding

**Files:**
- Create: `data/sync.py`
- Create: `data/overrides.json`
- Create: `data/requirements.txt`
- Create: `data/tests/__init__.py`
- Create: `pytest.ini`
- Modify: `.gitignore`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p data/tests
```

- [ ] **Step 2: Create `data/requirements.txt`**

```
requests>=2.31.0
shapely>=2.0.6
pytest>=7.4.0
```

- [ ] **Step 3: Create `data/overrides.json`**

```json
{}
```

- [ ] **Step 4: Create `data/tests/__init__.py`**

Empty file — required for pytest to treat the directory as a package.

```bash
touch data/tests/__init__.py
```

- [ ] **Step 5: Create `data/sync.py` skeleton**

```python
"""ChiDar data pipeline: fetch → enrich → validate → diff → write."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import requests
from shapely.geometry import Point, shape

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SODA_BASE_URL = "https://data.cityofchicago.org/resource"
CAMERAS_DATASET = "4i42-qv3h"
PARKS_DATASET = "ej32-qgdr"  # Chicago Park District Park Boundaries
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
PUBLISHED_URL = "https://phoolish.github.io/chidar/cameras.json"
DIFF_THRESHOLD = 15

CHICAGO_BOUNDS = {
    "lat_min": 41.6,
    "lat_max": 42.1,
    "lng_min": -88.0,
    "lng_max": -87.4,
}

# Fields that must be non-null on every published camera record
REQUIRED_FIELDS = [
    "id",
    "source_location_id",
    "latitude",
    "longitude",
    "first_approach",
    "enforcement_zone",
    "street",
    "active",
]

_SCRIPT_DIR = os.path.dirname(__file__)
OVERRIDES_PATH = os.path.join(_SCRIPT_DIR, "overrides.json")
OUTPUT_DIR = os.path.join(_SCRIPT_DIR, "output")
CACHE_DIR = os.path.join(_SCRIPT_DIR, ".cache")
```

- [ ] **Step 6: Create `pytest.ini` at the repo root**

```ini
[pytest]
pythonpath = data
testpaths = data/tests
```

This puts `data/` on the Python path so tests can `import sync` directly.

- [ ] **Step 7: Add entries to `.gitignore`**

Open `.gitignore` and append:

```
# Data pipeline
data/.cache/
data/output/
```

- [ ] **Step 8: Install dependencies locally**

```bash
pip install -r data/requirements.txt
```

- [ ] **Step 9: Commit**

```bash
git add data/ pytest.ini .gitignore
git commit -m "feat: scaffold data pipeline structure"
```

---

## Task 2: Fetch Cameras and Parks (TDD)

**Files:**
- Create: `data/tests/test_fetch.py`
- Modify: `data/sync.py`

- [ ] **Step 1: Write failing tests — create `data/tests/test_fetch.py`**

```python
from unittest.mock import Mock, patch
from sync import fetch_cameras, fetch_parks

SAMPLE_CAMERA = {
    "objectid": "1",
    "location_id": "1001",
    "address": "4900 N WESTERN AVE",
    "first_approach": "Northbound",
    "second_approach": "",
    "go_live_date": "2020-01-01T00:00:00.000",
    "latitude": "41.9751",
    "longitude": "-87.6886",
}


def _mock_response(data):
    m = Mock()
    m.json.return_value = data
    m.raise_for_status = Mock()
    return m


def test_fetch_cameras_sends_app_token():
    with patch("sync.requests.get", return_value=_mock_response([SAMPLE_CAMERA])) as mock_get:
        fetch_cameras("my-token")
        _, kwargs = mock_get.call_args
        assert kwargs.get("headers", {}).get("X-App-Token") == "my-token"


def test_fetch_cameras_returns_list_of_records():
    with patch("sync.requests.get", return_value=_mock_response([SAMPLE_CAMERA])):
        result = fetch_cameras("my-token")
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["location_id"] == "1001"


def test_fetch_parks_returns_feature_collection():
    sample_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]
                    ],
                },
                "properties": {"name": "Grant Park"},
            }
        ],
    }
    with patch("sync.requests.get", return_value=_mock_response(sample_geojson)):
        result = fetch_parks()
    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) == 1
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest data/tests/test_fetch.py -v
```

Expected: `ImportError: cannot import name 'fetch_cameras' from 'sync'`

- [ ] **Step 3: Implement `fetch_cameras` and `fetch_parks` in `data/sync.py`**

Add after the constants block:

```python
# ---------------------------------------------------------------------------
# Stage 1: Fetch
# ---------------------------------------------------------------------------

def fetch_cameras(app_token: str) -> list[dict]:
    """Fetch raw speed camera records from Chicago SODA API."""
    url = f"{SODA_BASE_URL}/{CAMERAS_DATASET}.json"
    response = requests.get(
        url,
        headers={"X-App-Token": app_token},
        params={"$limit": 1000},
    )
    response.raise_for_status()
    return response.json()


def fetch_parks() -> dict:
    """Fetch Chicago park boundaries as GeoJSON FeatureCollection."""
    url = f"{SODA_BASE_URL}/{PARKS_DATASET}.geojson"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest data/tests/test_fetch.py -v
```

Expected: 3 tests passing

- [ ] **Step 5: Commit**

```bash
git add data/sync.py data/tests/test_fetch.py
git commit -m "feat: add fetch_cameras and fetch_parks with tests"
```

---

## Task 3: Zone Type Determination (TDD)

**Files:**
- Create: `data/tests/test_enrich.py`
- Modify: `data/sync.py`

Shapely uses `Point(x, y)` = `Point(longitude, latitude)`. Zone type is determined solely by point-in-polygon against Chicago park boundaries. Not in a park → school zone.

- [ ] **Step 1: Write failing tests — create `data/tests/test_enrich.py`**

```python
from unittest.mock import Mock, patch
from sync import determine_zone_type

# A small park polygon centered around (lat=41.875, lng=-87.625)
PARK_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-87.63, 41.87],
                        [-87.62, 41.87],
                        [-87.62, 41.88],
                        [-87.63, 41.88],
                        [-87.63, 41.87],
                    ]
                ],
            },
            "properties": {},
        }
    ],
}

PARK_LAT, PARK_LNG = 41.875, -87.625    # clearly inside the polygon
SCHOOL_LAT, SCHOOL_LNG = 41.90, -87.70  # clearly outside


def test_determine_zone_type_inside_park():
    assert determine_zone_type(PARK_LAT, PARK_LNG, PARK_GEOJSON) == "park"


def test_determine_zone_type_outside_park():
    assert determine_zone_type(SCHOOL_LAT, SCHOOL_LNG, PARK_GEOJSON) == "school"


def test_determine_zone_type_empty_parks_returns_school():
    empty = {"type": "FeatureCollection", "features": []}
    assert determine_zone_type(PARK_LAT, PARK_LNG, empty) == "school"
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest data/tests/test_enrich.py -v
```

Expected: `ImportError: cannot import name 'determine_zone_type' from 'sync'`

- [ ] **Step 3: Implement `determine_zone_type` in `data/sync.py`**

Add after the fetch functions:

```python
# ---------------------------------------------------------------------------
# Stage 2: Enrich — zone type
# ---------------------------------------------------------------------------

def determine_zone_type(lat: float, lng: float, parks_geojson: dict) -> str:
    """Return 'park' if the coordinate falls inside a park polygon, else 'school'.

    Shapely Point(x, y) takes (longitude, latitude).
    """
    point = Point(lng, lat)
    for feature in parks_geojson["features"]:
        polygon = shape(feature["geometry"])
        if point.within(polygon):
            return "park"
    return "school"
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest data/tests/test_enrich.py -v
```

Expected: 3 tests passing

- [ ] **Step 5: Commit**

```bash
git add data/sync.py data/tests/test_enrich.py
git commit -m "feat: add determine_zone_type with shapely point-in-polygon"
```

---

## Task 4: OSM Speed Limit Lookup (TDD)

**Files:**
- Modify: `data/tests/test_enrich.py`
- Modify: `data/sync.py`

OSM `maxspeed` tags use various formats: `"30 mph"`, `"48 km/h"`, `"48"` (bare number = km/h per OSM convention). We normalize to integer MPH. The Overpass API query finds road ways within 50m of the camera coordinates.

- [ ] **Step 1: Update the import line in `data/tests/test_enrich.py`**

Change:
```python
from sync import determine_zone_type
```
To:
```python
from sync import determine_zone_type, _parse_maxspeed, query_osm_speed_limit
```

- [ ] **Step 2: Append failing tests to `data/tests/test_enrich.py`**

```python
def _mock_post(data):
    m = Mock()
    m.json.return_value = data
    m.raise_for_status = Mock()
    return m


def test_parse_maxspeed_mph_string():
    assert _parse_maxspeed("30 mph") == 30


def test_parse_maxspeed_mph_no_space():
    assert _parse_maxspeed("30mph") == 30


def test_parse_maxspeed_kmh_string():
    # 48 km/h rounds to 30 mph
    assert _parse_maxspeed("48 km/h") == 30


def test_parse_maxspeed_bare_number_treated_as_kmh():
    # OSM convention: unitless number is km/h
    assert _parse_maxspeed("48") == 30


def test_parse_maxspeed_invalid_string_returns_none():
    assert _parse_maxspeed("walk") is None


def test_query_osm_speed_limit_returns_mph_when_found():
    mock_data = {"elements": [{"tags": {"highway": "residential", "maxspeed": "30 mph"}}]}
    with patch("sync.requests.post", return_value=_mock_post(mock_data)):
        result = query_osm_speed_limit(41.8781, -87.6298)
    assert result == 30


def test_query_osm_speed_limit_returns_none_when_no_elements():
    mock_data = {"elements": []}
    with patch("sync.requests.post", return_value=_mock_post(mock_data)):
        result = query_osm_speed_limit(41.8781, -87.6298)
    assert result is None


def test_query_osm_speed_limit_returns_none_when_no_maxspeed_tag():
    mock_data = {"elements": [{"tags": {"highway": "residential"}}]}
    with patch("sync.requests.post", return_value=_mock_post(mock_data)):
        result = query_osm_speed_limit(41.8781, -87.6298)
    assert result is None
```

- [ ] **Step 3: Run tests — expect FAIL**

```bash
pytest data/tests/test_enrich.py -k "parse_maxspeed or osm" -v
```

Expected: `ImportError: cannot import name '_parse_maxspeed'`

- [ ] **Step 4: Implement `_parse_maxspeed` and `query_osm_speed_limit` in `data/sync.py`**

Add after `determine_zone_type`:

```python
# ---------------------------------------------------------------------------
# Stage 2: Enrich — speed limits
# ---------------------------------------------------------------------------

def _parse_maxspeed(maxspeed: str) -> int | None:
    """Parse an OSM maxspeed tag value to integer MPH.

    Handles: "30 mph", "30mph", "48 km/h", "48 kmh", "48" (bare = km/h).
    Returns None if the string cannot be parsed.
    """
    s = maxspeed.strip().lower().replace(" ", "")
    if "mph" in s:
        try:
            return int(s.replace("mph", ""))
        except ValueError:
            return None
    if "km/h" in s or "kmh" in s:
        try:
            kmh = int(s.replace("km/h", "").replace("kmh", ""))
            return round(kmh * 0.621371)
        except ValueError:
            return None
    # Bare number — OSM convention is km/h
    try:
        return round(int(s) * 0.621371)
    except ValueError:
        return None


def query_osm_speed_limit(lat: float, lng: float) -> int | None:
    """Query OSM Overpass API for the posted speed limit nearest to the coordinate.

    Searches for road ways within 50 metres with a maxspeed tag.
    Returns speed limit in MPH, or None if not found.
    """
    query = (
        "[out:json];"
        f"way(around:50,{lat},{lng})[highway][maxspeed];"
        "out tags;"
    )
    response = requests.post(OVERPASS_URL, data={"data": query})
    response.raise_for_status()
    elements = response.json().get("elements", [])
    if not elements:
        return None
    maxspeed = elements[0]["tags"].get("maxspeed")
    if not maxspeed:
        return None
    return _parse_maxspeed(maxspeed)
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
pytest data/tests/test_enrich.py -v
```

Expected: all tests passing

- [ ] **Step 6: Commit**

```bash
git add data/sync.py data/tests/test_enrich.py
git commit -m "feat: add OSM speed limit lookup and maxspeed parsing"
```

---

## Task 5: Speed Limit Resolution (TDD)

**Files:**
- Modify: `data/tests/test_enrich.py`
- Modify: `data/sync.py`

`get_speed_limit` orchestrates: school → always 20 MPH; park → try OSM, fall back to override, else None.

- [ ] **Step 1: Update the import line in `data/tests/test_enrich.py`**

Change:
```python
from sync import determine_zone_type, _parse_maxspeed, query_osm_speed_limit
```
To:
```python
from sync import determine_zone_type, _parse_maxspeed, query_osm_speed_limit, get_speed_limit
```

- [ ] **Step 2: Append failing tests to `data/tests/test_enrich.py`**

```python
def test_school_zone_always_returns_20_without_calling_osm():
    with patch("sync.query_osm_speed_limit") as mock_osm:
        result = get_speed_limit(SCHOOL_LAT, SCHOOL_LNG, "school", {}, "any-id")
    mock_osm.assert_not_called()
    assert result == 20


def test_park_zone_uses_osm_when_available():
    with patch("sync.query_osm_speed_limit", return_value=30):
        result = get_speed_limit(PARK_LAT, PARK_LNG, "park", {}, "loc-001")
    assert result == 30


def test_park_zone_falls_back_to_override_when_osm_returns_none():
    overrides = {"loc-001": 25}
    with patch("sync.query_osm_speed_limit", return_value=None):
        result = get_speed_limit(PARK_LAT, PARK_LNG, "park", overrides, "loc-001")
    assert result == 25


def test_park_zone_returns_none_when_neither_osm_nor_override():
    with patch("sync.query_osm_speed_limit", return_value=None):
        result = get_speed_limit(PARK_LAT, PARK_LNG, "park", {}, "loc-unknown")
    assert result is None
```

- [ ] **Step 3: Run tests — expect FAIL**

```bash
pytest data/tests/test_enrich.py -k "school_zone or park_zone" -v
```

Expected: `ImportError: cannot import name 'get_speed_limit'`

- [ ] **Step 4: Implement `get_speed_limit` in `data/sync.py`**

Add after `query_osm_speed_limit`:

```python
def get_speed_limit(
    lat: float,
    lng: float,
    zone_type: str,
    overrides: dict,
    source_location_id: str,
) -> int | None:
    """Resolve the speed limit for a camera.

    School zones: always 20 MPH (Chicago ordinance).
    Park zones: OSM Overpass → overrides.json → None.
    """
    if zone_type == "school":
        return 20
    osm = query_osm_speed_limit(lat, lng)
    if osm is not None:
        return osm
    return overrides.get(source_location_id)
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
pytest data/tests/test_enrich.py -v
```

Expected: all tests passing

- [ ] **Step 6: Commit**

```bash
git add data/sync.py data/tests/test_enrich.py
git commit -m "feat: add get_speed_limit with OSM and override fallback"
```

---

## Task 6: Camera Enrichment (TDD)

**Files:**
- Modify: `data/tests/test_enrich.py`
- Modify: `data/sync.py`

`enrich_cameras` maps each raw SODA record to the output schema. Empty string for `second_approach` becomes `None`. Direction strings are lowercased. `go_live_date` is truncated to `YYYY-MM-DD`.

- [ ] **Step 1: Update the import line in `data/tests/test_enrich.py`**

Change:
```python
from sync import determine_zone_type, _parse_maxspeed, query_osm_speed_limit, get_speed_limit
```
To:
```python
from sync import determine_zone_type, _parse_maxspeed, query_osm_speed_limit, get_speed_limit, enrich_cameras
```

- [ ] **Step 2: Append failing tests to `data/tests/test_enrich.py`**

```python
RAW_SCHOOL_CAMERA = {
    "location_id": "1234",
    "address": "4900 N WESTERN AVE",
    "first_approach": "Northbound",
    "second_approach": "",          # empty string → should become None
    "go_live_date": "2020-01-01T00:00:00.000",
    "latitude": str(SCHOOL_LAT),
    "longitude": str(SCHOOL_LNG),
}

RAW_PARK_CAMERA = {
    "location_id": "5678",
    "address": "100 S LAKE SHORE DR",
    "first_approach": "Southbound",
    "second_approach": "Northbound",
    "go_live_date": "2021-06-01T00:00:00.000",
    "latitude": str(PARK_LAT),
    "longitude": str(PARK_LNG),
}


def test_enrich_school_camera_structure():
    cameras, warnings = enrich_cameras([RAW_SCHOOL_CAMERA], PARK_GEOJSON, {})
    assert len(cameras) == 1
    cam = cameras[0]
    assert cam["id"] == "CHI-1234"
    assert cam["source_location_id"] == "1234"
    assert cam["latitude"] == SCHOOL_LAT
    assert cam["longitude"] == SCHOOL_LNG
    assert cam["enforcement_zone"] == "school"
    assert cam["speed_limit_mph"] == 20
    assert cam["first_approach"] == "northbound"
    assert cam["second_approach"] is None
    assert cam["street"] == "4900 N WESTERN AVE"
    assert cam["active"] is True
    assert cam["go_live_date"] == "2020-01-01"
    assert warnings == []


def test_enrich_park_camera_with_second_approach():
    with patch("sync.query_osm_speed_limit", return_value=30):
        cameras, warnings = enrich_cameras([RAW_PARK_CAMERA], PARK_GEOJSON, {})
    cam = cameras[0]
    assert cam["id"] == "CHI-5678"
    assert cam["enforcement_zone"] == "park"
    assert cam["speed_limit_mph"] == 30
    assert cam["second_approach"] == "northbound"
    assert warnings == []


def test_enrich_warns_when_speed_limit_unresolved():
    with patch("sync.query_osm_speed_limit", return_value=None):
        cameras, warnings = enrich_cameras([RAW_PARK_CAMERA], PARK_GEOJSON, {})
    assert cameras[0]["speed_limit_mph"] is None
    assert len(warnings) == 1
    assert "5678" in warnings[0]
```

- [ ] **Step 3: Run tests — expect FAIL**

```bash
pytest data/tests/test_enrich.py -k "enrich" -v
```

Expected: `ImportError: cannot import name 'enrich_cameras'`

- [ ] **Step 4: Implement `enrich_cameras` in `data/sync.py`**

Add after `get_speed_limit`:

```python
def enrich_cameras(
    raw_cameras: list[dict],
    parks_geojson: dict,
    overrides: dict,
) -> tuple[list[dict], list[str]]:
    """Map raw SODA records to the output schema with zone type and speed limits.

    Returns (cameras, warnings).
    warnings lists cameras where speed_limit_mph could not be resolved.
    """
    cameras: list[dict] = []
    warnings: list[str] = []

    for raw in raw_cameras:
        lat = float(raw["latitude"])
        lng = float(raw["longitude"])
        loc_id = raw["location_id"]
        zone_type = determine_zone_type(lat, lng, parks_geojson)
        speed_limit = get_speed_limit(lat, lng, zone_type, overrides, loc_id)

        if speed_limit is None:
            warnings.append(
                f"No speed limit resolved for camera {loc_id} "
                f"(lat={lat}, lng={lng}, zone={zone_type})"
            )

        raw_second = raw.get("second_approach") or None
        cameras.append(
            {
                "id": f"CHI-{loc_id}",
                "source_location_id": loc_id,
                "latitude": lat,
                "longitude": lng,
                "speed_limit_mph": speed_limit,
                "first_approach": (raw.get("first_approach") or "").lower() or None,
                "second_approach": raw_second.lower() if raw_second else None,
                "enforcement_zone": zone_type,
                "street": raw.get("address", ""),
                "cross_street": None,
                "active": True,
                "go_live_date": (raw.get("go_live_date") or "")[:10] or None,
                "last_verified": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )

    return cameras, warnings
```

- [ ] **Step 5: Run all enrich tests — expect PASS**

```bash
pytest data/tests/test_enrich.py -v
```

Expected: all tests passing

- [ ] **Step 6: Commit**

```bash
git add data/sync.py data/tests/test_enrich.py
git commit -m "feat: add enrich_cameras mapping SODA records to output schema"
```

---

## Task 7: Validation (TDD)

**Files:**
- Create: `data/tests/test_validate.py`
- Modify: `data/sync.py`

`validate_cameras` returns `(errors, warnings)`. Non-empty errors halt the pipeline. Count out-of-range is a warning; missing fields and null speed limits are errors.

- [ ] **Step 1: Write failing tests — create `data/tests/test_validate.py`**

```python
import json
import os
import tempfile
from unittest.mock import Mock, patch

import pytest

from sync import validate_cameras, DIFF_THRESHOLD

VALID_CAM = {
    "id": "CHI-0",
    "source_location_id": "0",
    "latitude": 41.88,
    "longitude": -87.63,
    "speed_limit_mph": 30,
    "first_approach": "northbound",
    "second_approach": None,
    "enforcement_zone": "school",
    "street": "123 N Main St",
    "cross_street": None,
    "active": True,
    "go_live_date": "2020-01-01",
    "last_verified": "2026-04-05T06:00:00Z",
}


def make_cameras(n: int = 150, **field_overrides) -> list[dict]:
    cams = []
    for i in range(n):
        cam = {**VALID_CAM, "id": f"CHI-{i}", "source_location_id": str(i)}
        cam.update(field_overrides)
        cams.append(cam)
    return cams


def test_valid_cameras_produce_no_errors_or_warnings():
    errors, warnings = validate_cameras(make_cameras(150))
    assert errors == []
    assert warnings == []


def test_null_speed_limit_is_error():
    errors, _ = validate_cameras(make_cameras(150, speed_limit_mph=None))
    assert any("speed_limit_mph" in e for e in errors)


def test_missing_required_field_is_error():
    cams = make_cameras(150)
    del cams[0]["first_approach"]
    errors, _ = validate_cameras(cams)
    assert any("first_approach" in e for e in errors)


def test_latitude_outside_chicago_is_error():
    errors, _ = validate_cameras(make_cameras(150, latitude=40.0))
    assert any("lat" in e.lower() or "latitude" in e.lower() for e in errors)


def test_longitude_outside_chicago_is_error():
    errors, _ = validate_cameras(make_cameras(150, longitude=-90.0))
    assert any("lng" in e.lower() or "longitude" in e.lower() for e in errors)


def test_low_camera_count_is_warning_not_error():
    errors, warnings = validate_cameras(make_cameras(50))
    assert errors == []
    assert any("low" in w.lower() or "100" in w for w in warnings)


def test_high_camera_count_is_warning_not_error():
    errors, warnings = validate_cameras(make_cameras(300))
    assert errors == []
    assert any("high" in w.lower() or "250" in w for w in warnings)
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest data/tests/test_validate.py -k "validate" -v
```

Expected: `ImportError: cannot import name 'validate_cameras'`

- [ ] **Step 3: Implement `validate_cameras` in `data/sync.py`**

Add after `enrich_cameras`:

```python
# ---------------------------------------------------------------------------
# Stage 3: Validate
# ---------------------------------------------------------------------------

def validate_cameras(cameras: list[dict]) -> tuple[list[str], list[str]]:
    """Validate enriched camera records.

    Returns (errors, warnings).
    Non-empty errors means the pipeline must abort before publishing.
    """
    errors: list[str] = []
    warnings: list[str] = []

    count = len(cameras)
    if count < 100:
        warnings.append(f"Camera count {count} is suspiciously low (expected >= 100)")
    elif count > 250:
        warnings.append(f"Camera count {count} is suspiciously high (expected <= 250)")

    for cam in cameras:
        cam_id = cam.get("id", "?")

        for field in REQUIRED_FIELDS:
            if cam.get(field) is None:
                errors.append(f"Camera {cam_id}: missing required field '{field}'")

        if cam.get("speed_limit_mph") is None:
            errors.append(f"Camera {cam_id}: speed_limit_mph is null")

        lat = cam.get("latitude")
        lng = cam.get("longitude")
        if lat is not None and not (CHICAGO_BOUNDS["lat_min"] <= lat <= CHICAGO_BOUNDS["lat_max"]):
            errors.append(f"Camera {cam_id}: latitude {lat} is outside Chicago bounds")
        if lng is not None and not (CHICAGO_BOUNDS["lng_min"] <= lng <= CHICAGO_BOUNDS["lng_max"]):
            errors.append(f"Camera {cam_id}: longitude {lng} is outside Chicago bounds")

    return errors, warnings
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest data/tests/test_validate.py -k "validate" -v
```

Expected: 7 tests passing

- [ ] **Step 5: Commit**

```bash
git add data/sync.py data/tests/test_validate.py
git commit -m "feat: add validate_cameras with error/warning distinction"
```

---

## Task 8: Diff (TDD)

**Files:**
- Modify: `data/tests/test_validate.py` (append)
- Modify: `data/sync.py`

`diff_cameras` compares the new cameras against the currently published dataset. Returns an empty diff on first run (URL unreachable). Raises `ValueError` if changes exceed `DIFF_THRESHOLD`.

- [ ] **Step 1: Update the import line in `data/tests/test_validate.py`**

Change:
```python
from sync import validate_cameras, DIFF_THRESHOLD
```
To:
```python
from sync import validate_cameras, diff_cameras, DIFF_THRESHOLD
```

- [ ] **Step 2: Append failing tests to `data/tests/test_validate.py`**

```python
PUBLISHED_URL = "https://phoolish.github.io/chidar/cameras.json"


def _make_cam(cam_id: str, speed: int = 30) -> dict:
    return {**VALID_CAM, "id": cam_id, "source_location_id": cam_id, "speed_limit_mph": speed}


def _mock_published(cameras: list[dict]) -> Mock:
    m = Mock()
    m.json.return_value = {"version": "1.0", "cameras": cameras}
    m.raise_for_status = Mock()
    return m


def test_diff_returns_empty_diff_on_first_run():
    with patch("sync.requests.get", side_effect=Exception("not reachable")):
        diff = diff_cameras([], PUBLISHED_URL)
    assert diff == {"added": [], "removed": [], "changed": []}


def test_diff_detects_added_camera():
    published = [_make_cam("CHI-A")]
    new = [_make_cam("CHI-A"), _make_cam("CHI-B")]
    with patch("sync.requests.get", return_value=_mock_published(published)):
        diff = diff_cameras(new, PUBLISHED_URL)
    assert diff["added"] == ["CHI-B"]
    assert diff["removed"] == []
    assert diff["changed"] == []


def test_diff_detects_removed_camera():
    published = [_make_cam("CHI-A"), _make_cam("CHI-B")]
    new = [_make_cam("CHI-A")]
    with patch("sync.requests.get", return_value=_mock_published(published)):
        diff = diff_cameras(new, PUBLISHED_URL)
    assert diff["removed"] == ["CHI-B"]


def test_diff_detects_changed_camera():
    published = [_make_cam("CHI-A", speed=30)]
    new = [_make_cam("CHI-A", speed=25)]
    with patch("sync.requests.get", return_value=_mock_published(published)):
        diff = diff_cameras(new, PUBLISHED_URL)
    assert diff["changed"] == ["CHI-A"]


def test_diff_raises_when_changes_exceed_threshold():
    published = [_make_cam(f"CHI-OLD-{i}") for i in range(100)]
    new = [_make_cam(f"CHI-NEW-{i}") for i in range(100)]
    with patch("sync.requests.get", return_value=_mock_published(published)):
        with pytest.raises(ValueError, match="threshold"):
            diff_cameras(new, PUBLISHED_URL)
```

- [ ] **Step 3: Run tests — expect FAIL**

```bash
pytest data/tests/test_validate.py -k "diff" -v
```

Expected: `ImportError: cannot import name 'diff_cameras'`

- [ ] **Step 4: Implement `diff_cameras` in `data/sync.py`**

Add after `validate_cameras`:

```python
# ---------------------------------------------------------------------------
# Stage 4: Diff
# ---------------------------------------------------------------------------

def diff_cameras(new_cameras: list[dict], published_url: str) -> dict:
    """Compare new cameras against the currently published dataset.

    Returns {'added': [...], 'removed': [...], 'changed': [...]} with camera IDs.
    Returns an empty diff if the published URL is unreachable (first run).
    Raises ValueError if total changes exceed DIFF_THRESHOLD.
    """
    try:
        response = requests.get(published_url, timeout=10)
        response.raise_for_status()
        published_cameras = response.json().get("cameras", [])
    except Exception:
        return {"added": [], "removed": [], "changed": []}

    published = {cam["id"]: cam for cam in published_cameras}
    new = {cam["id"]: cam for cam in new_cameras}

    added = sorted(id_ for id_ in new if id_ not in published)
    removed = sorted(id_ for id_ in published if id_ not in new)
    changed = sorted(
        id_ for id_ in new if id_ in published and new[id_] != published[id_]
    )

    total = len(added) + len(removed) + len(changed)
    if total > DIFF_THRESHOLD:
        raise ValueError(
            f"Diff threshold exceeded: {total} cameras changed "
            f"(+{len(added)} -{len(removed)} ~{len(changed)}). "
            f"Threshold is {DIFF_THRESHOLD}. Inspect before publishing."
        )

    return {"added": added, "removed": removed, "changed": changed}
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
pytest data/tests/test_validate.py -k "diff" -v
```

Expected: 5 tests passing

- [ ] **Step 6: Commit**

```bash
git add data/sync.py data/tests/test_validate.py
git commit -m "feat: add diff_cameras with safety threshold"
```

---

## Task 9: Write Output (TDD)

**Files:**
- Modify: `data/tests/test_validate.py` (append)
- Modify: `data/sync.py`

- [ ] **Step 1: Update the import line in `data/tests/test_validate.py`**

Change:
```python
from sync import validate_cameras, diff_cameras, DIFF_THRESHOLD
```
To:
```python
from sync import validate_cameras, diff_cameras, write_output, DIFF_THRESHOLD
```

- [ ] **Step 2: Append failing tests to `data/tests/test_validate.py`**

```python
def test_write_output_creates_cameras_json():
    cameras = [_make_cam("CHI-A")]
    diff = {"added": [], "removed": [], "changed": []}
    with tempfile.TemporaryDirectory() as tmpdir:
        write_output(cameras, diff, [], tmpdir)
        cameras_path = os.path.join(tmpdir, "cameras.json")
        assert os.path.exists(cameras_path)
        with open(cameras_path) as f:
            data = json.load(f)
        assert data["version"] == "1.0"
        assert len(data["cameras"]) == 1
        assert data["cameras"][0]["id"] == "CHI-A"
        assert "last_updated" in data


def test_write_output_creates_manifest_json():
    cameras = [_make_cam("CHI-A")]
    diff = {"added": ["CHI-B"], "removed": [], "changed": []}
    warnings = ["some warning"]
    with tempfile.TemporaryDirectory() as tmpdir:
        write_output(cameras, diff, warnings, tmpdir)
        with open(os.path.join(tmpdir, "manifest.json")) as f:
            manifest = json.load(f)
        assert manifest["camera_count"] == 1
        assert manifest["diff"]["added"] == ["CHI-B"]
        assert manifest["warnings"] == ["some warning"]
        assert "generated_at" in manifest
```

- [ ] **Step 3: Run tests — expect FAIL**

```bash
pytest data/tests/test_validate.py -k "write_output" -v
```

Expected: `ImportError: cannot import name 'write_output'`

- [ ] **Step 4: Implement `write_output` in `data/sync.py`**

Add after `diff_cameras`:

```python
# ---------------------------------------------------------------------------
# Stage 5: Write
# ---------------------------------------------------------------------------

def write_output(
    cameras: list[dict],
    diff: dict,
    warnings: list[str],
    output_dir: str,
) -> None:
    """Write cameras.json and manifest.json to output_dir."""
    os.makedirs(output_dir, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    cameras_data = {
        "version": "1.0",
        "last_updated": now,
        "cameras": cameras,
    }
    manifest_data = {
        "generated_at": now,
        "camera_count": len(cameras),
        "warnings": warnings,
        "diff": diff,
    }

    with open(os.path.join(output_dir, "cameras.json"), "w") as f:
        json.dump(cameras_data, f, indent=2)

    with open(os.path.join(output_dir, "manifest.json"), "w") as f:
        json.dump(manifest_data, f, indent=2)
```

- [ ] **Step 5: Run all tests — expect PASS**

```bash
pytest -v
```

Expected: all tests in all three test files passing

- [ ] **Step 6: Commit**

```bash
git add data/sync.py data/tests/test_validate.py
git commit -m "feat: add write_output producing cameras.json and manifest.json"
```

---

## Task 10: Main Pipeline Entrypoint

**Files:**
- Modify: `data/sync.py`

Wire all five stages together in `main()` with stage-by-stage logging.

- [ ] **Step 1: Append `main()` to `data/sync.py`**

```python
# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    app_token = os.environ.get("SOCRATA_APP_TOKEN", "")
    if not app_token:
        print("WARNING: SOCRATA_APP_TOKEN not set — requests may be rate-limited")

    print("Stage 1: Fetching data...")
    raw_cameras = fetch_cameras(app_token)
    parks_geojson = fetch_parks()
    print(f"  {len(raw_cameras)} cameras, {len(parks_geojson['features'])} park polygons")

    print("Stage 2: Enriching cameras...")
    with open(OVERRIDES_PATH) as f:
        overrides = json.load(f)
    cameras, enrich_warnings = enrich_cameras(raw_cameras, parks_geojson, overrides)
    for w in enrich_warnings:
        print(f"  WARNING: {w}")

    print("Stage 3: Validating...")
    errors, validate_warnings = validate_cameras(cameras)
    for w in validate_warnings:
        print(f"  WARNING: {w}")
    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
        sys.exit(1)

    print("Stage 4: Diffing against published data...")
    diff = diff_cameras(cameras, PUBLISHED_URL)
    print(
        f"  +{len(diff['added'])} added  "
        f"-{len(diff['removed'])} removed  "
        f"~{len(diff['changed'])} changed"
    )

    print("Stage 5: Writing output...")
    all_warnings = enrich_warnings + validate_warnings
    write_output(cameras, diff, all_warnings, OUTPUT_DIR)
    print(f"  Written to {OUTPUT_DIR}/")
    print(f"Done — {len(cameras)} cameras.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the pipeline locally**

```bash
python data/sync.py
```

Expected output:
```
Stage 1: Fetching data...
  162 cameras, 600 park polygons    # numbers will vary
Stage 2: Enriching cameras...
  WARNING: No speed limit resolved for camera XXXX ...  # if any park cameras lack OSM data
Stage 3: Validating...
Stage 4: Diffing against published data...
  +0 added  -0 removed  ~0 changed  # or "first run" skips diff
Stage 5: Writing output...
  Written to data/output/
Done — 162 cameras.
```

If the pipeline exits with errors (null speed limits), note each camera ID from the WARNING lines and proceed to Step 3.

- [ ] **Step 3: Populate `data/overrides.json` for any unresolved park zone cameras**

If Step 2 printed WARNING lines, find the posted speed limit for each flagged camera by looking up its address on Google Maps (Street View shows speed limit signs). Then update `data/overrides.json`:

```json
{
  "LOCATION_ID_1": 30,
  "LOCATION_ID_2": 25
}
```

Re-run `python data/sync.py` until no errors appear.

- [ ] **Step 4: Inspect the output**

```bash
python3 -c "
import json
d = json.load(open('data/output/cameras.json'))
m = json.load(open('data/output/manifest.json'))
print(f'cameras: {len(d[\"cameras\"])}')
print(f'first: {d[\"cameras\"][0][\"id\"]} — {d[\"cameras\"][0][\"enforcement_zone\"]} zone, {d[\"cameras\"][0][\"speed_limit_mph\"]} mph')
print(f'warnings: {m[\"warnings\"]}')
"
```

Expected: camera count between 100–250, all speed limits non-null, warnings empty.

- [ ] **Step 5: Run all tests**

```bash
pytest -v
```

Expected: all tests passing

- [ ] **Step 6: Commit**

```bash
git add data/sync.py data/overrides.json
git commit -m "feat: add main() pipeline entrypoint and speed limit overrides"
```

---

## Task 11: Data CI Workflow

**Files:**
- Create: `.github/workflows/data-ci.yml`

- [ ] **Step 1: Create `.github/workflows/data-ci.yml`**

```yaml
name: Data Pipeline CI

on:
  pull_request:
    paths:
      - 'data/**'
      - 'pytest.ini'
  push:
    branches: [main]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    name: Python Tests
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install -r data/requirements.txt

      - name: Run tests
        run: pytest -v
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/data-ci.yml
git commit -m "ci: add data-ci.yml for Python pipeline tests"
```

---

## Task 12: Data Sync Workflow

**Files:**
- Create: `.github/workflows/data-sync.yml`

- [ ] **Step 1: Create `.github/workflows/data-sync.yml`**

```yaml
name: Data Sync

on:
  schedule:
    - cron: '0 6 * * *'  # 6am UTC daily
  workflow_dispatch:      # allow manual trigger

jobs:
  sync:
    name: Sync Camera Data
    runs-on: ubuntu-latest
    permissions:
      contents: write  # required to push to gh-pages branch

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install -r data/requirements.txt

      - name: Run pipeline
        env:
          SOCRATA_APP_TOKEN: ${{ secrets.SOCRATA_APP_TOKEN }}
        run: python data/sync.py

      - name: Publish to GitHub Pages
        uses: peaceiris/actions-gh-pages@v4
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: data/output
          publish_branch: gh-pages
          keep_files: false

      - name: Write job summary
        if: always()
        run: |
          if [ -f data/output/manifest.json ]; then
            echo "## Data Sync Summary" >> $GITHUB_STEP_SUMMARY
            python3 -c "
          import json, sys
          m = json.load(open('data/output/manifest.json'))
          d = m['diff']
          print(f'**Cameras:** {m[\"camera_count\"]}')
          print(f'**Changes:** +{len(d[\"added\"])} added, -{len(d[\"removed\"])} removed, ~{len(d[\"changed\"])} changed')
          if m['warnings']:
              print('**Warnings:**')
              for w in m['warnings']:
                  print(f'- {w}')
            " >> $GITHUB_STEP_SUMMARY
          fi
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/data-sync.yml
git commit -m "ci: add data-sync.yml for daily camera data sync to GitHub Pages"
```

---

## Task 13: Enable GitHub Pages and Verify End-to-End

- [ ] **Step 1: Enable GitHub Pages on the repository**

```bash
gh api repos/phoolish/chidar/pages \
  --method POST \
  --field source='{"branch":"gh-pages","path":"/"}' \
  2>/dev/null && echo "Pages enabled" || echo "Pages may already be enabled — check Settings"
```

If the gh CLI call fails, enable it manually:
- Repo **Settings** → **Pages** → Source: **Deploy from a branch** → Branch: `gh-pages`, folder: `/ (root)` → Save

- [ ] **Step 2: Push the branch and open a PR**

```bash
git push -u origin feat/iteration-2-design
gh pr create \
  --title "feat: Iteration 2 — Backend Data Service" \
  --body "Implements the Python data pipeline for ChiDar.

## What's included
- \`data/sync.py\`: full pipeline (fetch → enrich → validate → diff → write)
- \`data/overrides.json\`: manual speed limit overrides for park zone cameras
- \`data/tests/\`: pytest suite covering all pipeline functions (TDD)
- \`.github/workflows/data-ci.yml\`: Python CI on PRs to \`data/\` and all merges to main
- \`.github/workflows/data-sync.yml\`: daily cron + manual sync to GitHub Pages

## Verification
- [ ] data-ci.yml passes
- [ ] Manual data-sync.yml run succeeds
- [ ] cameras.json accessible at GitHub Pages URL"
```

- [ ] **Step 3: Verify CI is green**

```bash
gh pr checks --watch
```

Expected: `Python Tests` job passes.

- [ ] **Step 4: Trigger the sync pipeline manually**

```bash
gh workflow run data-sync.yml
gh run watch $(gh run list --workflow=data-sync.yml --limit 1 --json databaseId --jq '.[0].databaseId')
```

Expected: all steps green, including the GitHub Pages publish step.

- [ ] **Step 5: Verify cameras.json is live**

```bash
curl -s https://phoolish.github.io/chidar/cameras.json | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'version: {d[\"version\"]}')
print(f'cameras: {len(d[\"cameras\"])}')
print(f'first: {d[\"cameras\"][0][\"id\"]} ({d[\"cameras\"][0][\"enforcement_zone\"]} zone, {d[\"cameras\"][0][\"speed_limit_mph\"]} mph)')
"
```

Expected:
```
version: 1.0
cameras: 162    # ~150-180, exact count varies
first: CHI-XXXX (school zone, 20 mph)
```

If GitHub Pages takes a few minutes to propagate, wait and retry.

- [ ] **Step 6: Merge the PR**

```bash
gh pr merge --squash
```
