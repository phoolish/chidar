"""ChiDar data pipeline: fetch → enrich → validate → diff → write."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SODA_BASE_URL = "https://data.cityofchicago.org/resource"
CAMERAS_DATASET = "4i42-qv3h"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
PUBLISHED_URL = "https://phoolish.github.io/chidar/cameras.json"
DIFF_THRESHOLD = 15

CHICAGO_BOUNDS = {
    "lat_min": 41.6,
    "lat_max": 42.1,
    "lng_min": -88.0,
    "lng_max": -87.4,
}

# Note: first_approach is intentionally excluded — CHI-242 and CHI-243 do not
# provide this field in the SODA dataset, so it is treated as optional.
# Fields that must be non-null on every published camera record
REQUIRED_FIELDS = [
    "id",
    "source_location_id",
    "latitude",
    "longitude",
    "enforcement_zone",
    "street",
    "active",
]

_SCRIPT_DIR = os.path.dirname(__file__)
OVERRIDES_PATH = os.path.join(_SCRIPT_DIR, "overrides.json")
OUTPUT_DIR = os.path.join(_SCRIPT_DIR, "output")
CACHE_DIR = os.path.join(_SCRIPT_DIR, ".cache")

# ---------------------------------------------------------------------------
# Stage 1: Fetch
# ---------------------------------------------------------------------------


def fetch_cameras(app_token: str) -> list[dict]:
    """Fetch raw speed camera records from Chicago SODA API."""
    url = f"{SODA_BASE_URL}/{CAMERAS_DATASET}.json"
    response = requests.get(
        url,
        headers={"X-App-Token": app_token},
        params={"$limit": 1000},  # dataset has ~160 cameras; revisit if it grows past 1000
    )
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Stage 2: Enrich — zone type + speed limit (combined per-camera OSM query)
# ---------------------------------------------------------------------------


def query_osm_for_camera(lat: float, lng: float) -> tuple[str, int | None]:
    """Single Overpass query returning zone type and speed limit for one camera.

    Checks for a park way within 200m (Chicago's ~1/8 mile safety zone) and a road
    with a maxspeed tag within 50m. Defaults to 'school' zone on any error.

    Returns (zone_type, speed_limit_mph). speed_limit_mph is None if not found.
    """
    query = (
        "[out:json];"
        f"("
        f"  way[\"leisure\"=\"park\"](around:200,{lat},{lng});"
        f"  way[highway][maxspeed](around:50,{lat},{lng});"
        f");"
        "out tags;"
    )
    try:
        response = requests.post(OVERPASS_URL, data={"data": query}, timeout=15)
        response.raise_for_status()
        elements = response.json().get("elements", [])
    except Exception:
        return "school", None

    zone_type = "school"
    speed_limit: int | None = None
    for elem in elements:
        tags = elem.get("tags", {})
        if tags.get("leisure") == "park":
            zone_type = "park"
        if "maxspeed" in tags and speed_limit is None:
            speed_limit = _parse_maxspeed(tags["maxspeed"])
    return zone_type, speed_limit


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


def enrich_cameras(
    raw_cameras: list[dict],
    overrides: dict,
) -> tuple[list[dict], list[str]]:
    """Map raw SODA records to the output schema with zone type and speed limits.

    Makes one OSM Overpass call per camera to determine zone type (park/school)
    and speed limit simultaneously. School zones always get 20 MPH per ordinance;
    park zones use the OSM speed limit, then overrides.json, then None.

    Returns (cameras, warnings). warnings lists cameras with unresolved speed limits.
    """
    cameras: list[dict] = []
    warnings: list[str] = []

    for raw in raw_cameras:
        lat = float(raw["latitude"])
        lng = float(raw["longitude"])
        loc_id = raw["location_id"]  # city-assigned stable ID, e.g. "CHI217"
        zone_type, osm_speed = query_osm_for_camera(lat, lng)
        time.sleep(0.5)  # avoid Overpass rate limiting
        if zone_type == "school":
            speed_limit: int | None = 20
        elif osm_speed is not None:
            speed_limit = osm_speed
        else:
            speed_limit = overrides.get(loc_id)

        if speed_limit is None:
            warnings.append(
                f"No speed limit resolved for camera {loc_id} "
                f"(lat={lat}, lng={lng}, zone={zone_type})"
            )

        raw_second = raw.get("second_approach") or None
        cameras.append(
            {
                "id": loc_id,  # location_id is already namespaced, e.g. "CHI217"
                "source_location_id": loc_id,
                "latitude": lat,
                "longitude": lng,
                "speed_limit_mph": speed_limit,
                "first_approach": (raw.get("first_approach") or "").lower() or None,
                "second_approach": raw_second.lower() if raw_second else None,
                "enforcement_zone": zone_type,
                "street": raw.get("address") or None,
                "cross_street": None,  # SODA dataset does not include cross-street data
                "active": True,
                "go_live_date": (raw.get("go_live_date") or "")[:10] or None,
                "last_verified": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )

    return cameras, warnings


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

    if not published_cameras:
        # Empty published dataset = first run (bootstrapped placeholder); skip diff.
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


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    app_token = os.environ.get("SOCRATA_APP_TOKEN", "")
    if not app_token:
        print("WARNING: SOCRATA_APP_TOKEN not set — requests may be rate-limited")

    print("Stage 1: Fetching data...")
    raw_cameras = fetch_cameras(app_token)
    print(f"  {len(raw_cameras)} cameras")

    print("Stage 2: Enriching cameras (one OSM query per camera)...")
    with open(OVERRIDES_PATH) as f:
        overrides = json.load(f)
    cameras, enrich_warnings = enrich_cameras(raw_cameras, overrides)
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
