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
