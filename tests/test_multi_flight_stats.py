import os
import json
import pytest
from app import app, SAVE_DIR, MULTI_STATS_CACHE_FILE


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_api_multi_flight_stats(client):
    response = client.get("/api/multi_flight_stats")
    assert response.status_code == 200
    data = response.get_json()

    assert "flights" in data
    assert "totals" in data
    assert isinstance(data["flights"], list)
    assert isinstance(data["totals"], dict)

    if data["flights"]:
        first_flight = data["flights"][0]
        assert "filename" in first_flight
        assert "date" in first_flight
        assert "duration_min" in first_flight
        assert "cum_total_hours" in first_flight
        assert "cum_airborne_hours" in first_flight
        assert "max_shock_cooling" in first_flight
        assert "cht_spread" in first_flight

    assert "total_airborne_hours" in data["totals"]


def test_multi_flight_stats_page_route(client):
    response = client.get("/multi_flight_stats")
    assert response.status_code == 200
    assert b"Multi-Flight" in response.data
