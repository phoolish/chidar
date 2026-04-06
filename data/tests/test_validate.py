import json
import os
import tempfile
from unittest.mock import Mock, patch

import pytest

from sync import validate_cameras, diff_cameras, write_output, DIFF_THRESHOLD

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
