from unittest.mock import Mock, patch
from sync import determine_zone_type, _parse_maxspeed, query_osm_speed_limit, get_speed_limit, enrich_cameras

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


def test_determine_zone_type_skips_null_geometry_feature():
    """Features with null geometry (as seen in real Chicago parks data) are skipped."""
    geojson_with_null = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": None, "properties": {}},
            PARK_GEOJSON["features"][0],
        ],
    }
    assert determine_zone_type(PARK_LAT, PARK_LNG, geojson_with_null) == "park"


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


def test_parse_maxspeed_bare_number_is_kmh():
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
    assert "last_verified" in cam
    assert cam["last_verified"].endswith("Z")


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


def test_enrich_uses_override_when_osm_unavailable():
    overrides = {"5678": 25}
    with patch("sync.query_osm_speed_limit", return_value=None):
        cameras, warnings = enrich_cameras([RAW_PARK_CAMERA], PARK_GEOJSON, overrides)
    assert cameras[0]["speed_limit_mph"] == 25
    assert warnings == []  # override resolved it, no warning
