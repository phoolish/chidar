from unittest.mock import Mock, patch, MagicMock
from sync import _parse_maxspeed, query_osm_for_camera, enrich_cameras

PARK_LAT, PARK_LNG = 41.875, -87.625
SCHOOL_LAT, SCHOOL_LNG = 41.90, -87.70


def _mock_post(data):
    m = Mock()
    m.json.return_value = data
    m.raise_for_status = Mock()
    return m


def _overpass_park_and_road(speed: str = "30 mph") -> dict:
    return {
        "elements": [
            {"tags": {"leisure": "park"}},
            {"tags": {"highway": "residential", "maxspeed": speed}},
        ]
    }


def _overpass_road_only(speed: str = "30 mph") -> dict:
    return {"elements": [{"tags": {"highway": "residential", "maxspeed": speed}}]}


def _overpass_empty() -> dict:
    return {"elements": []}


# ---------------------------------------------------------------------------
# query_osm_for_camera
# ---------------------------------------------------------------------------

def test_query_osm_for_camera_returns_park_zone_and_speed_when_park_found():
    with patch("sync.requests.post", return_value=_mock_post(_overpass_park_and_road())):
        zone, speed = query_osm_for_camera(PARK_LAT, PARK_LNG)
    assert zone == "park"
    assert speed == 30


def test_query_osm_for_camera_returns_school_when_no_park_element():
    with patch("sync.requests.post", return_value=_mock_post(_overpass_road_only())):
        zone, speed = query_osm_for_camera(SCHOOL_LAT, SCHOOL_LNG)
    assert zone == "school"
    assert speed == 30


def test_query_osm_for_camera_returns_school_and_none_when_empty():
    with patch("sync.requests.post", return_value=_mock_post(_overpass_empty())):
        zone, speed = query_osm_for_camera(SCHOOL_LAT, SCHOOL_LNG)
    assert zone == "school"
    assert speed is None


def test_query_osm_for_camera_defaults_to_school_on_error():
    with patch("sync.requests.post", side_effect=Exception("timeout")):
        zone, speed = query_osm_for_camera(PARK_LAT, PARK_LNG)
    assert zone == "school"
    assert speed is None


# ---------------------------------------------------------------------------
# _parse_maxspeed
# ---------------------------------------------------------------------------

def test_parse_maxspeed_mph_string():
    assert _parse_maxspeed("30 mph") == 30


def test_parse_maxspeed_mph_no_space():
    assert _parse_maxspeed("30mph") == 30


def test_parse_maxspeed_kmh_string():
    # 48 km/h rounds to 30 mph
    assert _parse_maxspeed("48 km/h") == 30


def test_parse_maxspeed_bare_number_is_kmh():
    # OSM convention: unitless number is km/h
    assert _parse_maxspeed("48") == 30


def test_parse_maxspeed_invalid_string_returns_none():
    assert _parse_maxspeed("walk") is None


# ---------------------------------------------------------------------------
# enrich_cameras
# ---------------------------------------------------------------------------

RAW_SCHOOL_CAMERA = {
    "location_id": "CHI1234",
    "address": "4900 N WESTERN AVE",
    "first_approach": "Northbound",
    "second_approach": "",          # empty string → should become None
    "go_live_date": "2020-01-01T00:00:00.000",
    "latitude": str(SCHOOL_LAT),
    "longitude": str(SCHOOL_LNG),
}

RAW_PARK_CAMERA = {
    "location_id": "CHI5678",
    "address": "100 S LAKE SHORE DR",
    "first_approach": "Southbound",
    "second_approach": "Northbound",
    "go_live_date": "2021-06-01T00:00:00.000",
    "latitude": str(PARK_LAT),
    "longitude": str(PARK_LNG),
}


def test_enrich_school_camera_structure():
    osm = _overpass_road_only()  # no park element → school zone
    with patch("sync.requests.post", return_value=_mock_post(osm)), \
         patch("sync._load_osm_cache", return_value={}), \
         patch("sync._save_osm_cache"):
        cameras, warnings = enrich_cameras([RAW_SCHOOL_CAMERA], {})
    assert len(cameras) == 1
    cam = cameras[0]
    assert cam["id"] == "CHI1234"
    assert cam["source_location_id"] == "CHI1234"
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
    assert "last_verified" in cam
    assert cam["last_verified"].endswith("Z")


def test_enrich_park_camera_with_second_approach():
    osm = _overpass_park_and_road("30 mph")
    with patch("sync.requests.post", return_value=_mock_post(osm)), \
         patch("sync._load_osm_cache", return_value={}), \
         patch("sync._save_osm_cache"):
        cameras, warnings = enrich_cameras([RAW_PARK_CAMERA], {})
    cam = cameras[0]
    assert cam["id"] == "CHI5678"
    assert cam["enforcement_zone"] == "park"
    assert cam["speed_limit_mph"] == 30
    assert cam["second_approach"] == "northbound"
    assert warnings == []


def test_enrich_warns_when_speed_limit_unresolved():
    # Park zone but no road maxspeed
    osm = {"elements": [{"tags": {"leisure": "park"}}]}
    with patch("sync.requests.post", return_value=_mock_post(osm)), \
         patch("sync._load_osm_cache", return_value={}), \
         patch("sync._save_osm_cache"):
        cameras, warnings = enrich_cameras([RAW_PARK_CAMERA], {})
    assert cameras[0]["speed_limit_mph"] is None
    assert len(warnings) == 1
    assert "CHI5678" in warnings[0]


def test_enrich_uses_override_when_osm_unavailable():
    osm = {"elements": [{"tags": {"leisure": "park"}}]}
    overrides = {"CHI5678": 25}
    with patch("sync.requests.post", return_value=_mock_post(osm)), \
         patch("sync._load_osm_cache", return_value={}), \
         patch("sync._save_osm_cache"):
        cameras, warnings = enrich_cameras([RAW_PARK_CAMERA], overrides)
    assert cameras[0]["speed_limit_mph"] == 25
    assert warnings == []  # override resolved it, no warning
