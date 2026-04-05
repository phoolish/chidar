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
