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
