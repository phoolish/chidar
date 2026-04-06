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


def fetch_parks() -> dict:
    """Fetch Chicago park boundaries as GeoJSON FeatureCollection."""
    url = f"{SODA_BASE_URL}/{PARKS_DATASET}.geojson"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


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
