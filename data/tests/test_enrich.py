from unittest.mock import Mock, patch
from sync import determine_zone_type, _parse_maxspeed, query_osm_speed_limit

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
