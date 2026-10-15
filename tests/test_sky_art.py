import json
import xml.etree.ElementTree as ET
import pytest


class TestSkyArt:
    """Test suite for Sky Art & ForeFlight flight plan generation."""

    def test_sky_art_page_renders(self, app, client):
        """Verify the /sky_art page loads successfully with all essential UI controls."""
        with app.app_context():
            response = client.get("/sky_art")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert "artMap" in html
            assert "airportSearchInput" in html
            assert "downloadFplBtn" in html
            assert "openForeflightBtn" in html
            assert "showQrBtn" in html
            assert "copyRouteBtn" in html
            assert "foreflightQrModal" in html
            assert "waypointTableModal" in html
            assert "sizeSlider" in html
            assert "heightInput" in html
            assert "heightSlider" in html
            assert "aspectLockBtn" in html
            assert "undoBtn" in html
            assert "redoBtn" in html
            assert "mapUndoBtn" in html
            assert "mapRedoBtn" in html
            assert "depAirportInput" in html
            assert "arrAirportInput" in html
            assert "setDepAsHomeBtn" in html
            assert "syncArrToDepBtn" in html
            assert "configHomeAirportModal" in html
            assert "headerSaveDrawingBtn" in html
            assert "saveDrawingModal" in html
            assert "confirmSaveDrawingBtn" in html
            assert "optimizeEntryExitCheck" in html
            assert "reverseRouteBtn" in html
            assert "mapReverseBtn" in html
            assert "Sky Art" in html
            assert "tabPresetsDropdownBtn" in html
            assert "tabPresetsUnifiedContainer" in html
            assert "importModeOutline" in html
            assert "importModeAllStrokes" in html

    def test_flight_art_legacy_alias_renders(self, app, client):
        """Verify legacy /flight_art alias route still loads successfully."""
        with app.app_context():
            response = client.get("/flight_art")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert "artMap" in html

    def test_airport_search_api(self, app, client):
        """Verify /api/airports/search finds airports accurately and rapidly."""
        with app.app_context():
            # Short query
            resp = client.get("/api/airports/search?q=k")
            assert resp.status_code == 200
            assert resp.get_json() == []

            # Exact / prefix match for San Martin E16
            resp = client.get("/api/airports/search?q=E16")
            assert resp.status_code == 200
            data = resp.get_json()
            assert len(data) >= 1
            e16 = next((a for a in data if "E16" in a["icao"] or "E16" in a["faa"]), None)
            assert e16 is not None
            assert "San Martin" in e16["name"]
            assert abs(e16["lat"] - 37.0816) < 0.05
            assert abs(e16["lon"] - (-121.597)) < 0.05

            # Exact / prefix match for Buchanan Field KCCR
            resp = client.get("/api/airports/search?q=KCCR")
            assert resp.status_code == 200
            data = resp.get_json()
            assert len(data) >= 1
            kccr = next((a for a in data if "CCR" in a["icao"] or "CCR" in a["faa"]), None)
            assert kccr is not None
            assert "Buchanan" in kccr["name"]
            assert abs(kccr["lat"] - 37.9897) < 0.05
            assert abs(kccr["lon"] - (-122.0569)) < 0.05

            # Search by city name
            resp = client.get("/api/airports/search?q=Concord")
            assert resp.status_code == 200
            data = resp.get_json()
            assert any("CCR" in a["icao"] or "CCR" in a["faa"] for a in data)

    def test_export_fpl_api(self, app, client):
        """Verify /api/sky_art/export_fpl and legacy alias generate valid ForeFlight/Garmin Flight Plan XML."""
        payload = {
            "route_name": "N890GF_TEST_ART",
            "waypoints": [
                {"id": "KCCR", "name": "Buchanan Field", "type": "AIRPORT", "lat": 37.9897, "lon": -122.0569, "isAirport": True},
                {"id": "WP01", "name": "Art 1", "type": "USER WAYPOINT", "lat": 38.0123, "lon": -122.0345, "isAirport": False},
                {"id": "WP02", "name": "Art 2", "type": "USER WAYPOINT", "lat": 38.0245, "lon": -122.0123, "isAirport": False},
                {"id": "KCCR", "name": "Buchanan Field", "type": "AIRPORT", "lat": 37.9897, "lon": -122.0569, "isAirport": True}
            ]
        }
        with app.app_context():
            for endpoint in ["/api/sky_art/export_fpl", "/api/flight_art/export_fpl"]:
                resp = client.post(endpoint, json=payload)
                assert resp.status_code == 200
                assert "application/xml" in resp.headers["Content-Type"]
                assert "N890GF_TEST_ART.fpl" in resp.headers["Content-Disposition"]

                xml_str = resp.data.decode("utf-8")
                assert 'xmlns="http://www8.garmin.com/xmlschemas/FlightPlan/v1"' in xml_str
                assert "<route-name>N890GF_TEST_ART</route-name>" in xml_str

                # Parse XML to verify well-formed syntax
                root = ET.fromstring(xml_str)
                assert "flight-plan" in root.tag

    def test_export_gpx_api(self, app, client):
        """Verify /api/sky_art/export_gpx and legacy alias generate valid GPX route XML."""
        payload = {
            "route_name": "N890GF GPX Test",
            "waypoints": [
                {"id": "KCCR", "name": "Buchanan Field", "lat": 37.9897, "lon": -122.0569},
                {"id": "WP01", "name": "Art 1", "lat": 38.0123, "lon": -122.0345}
            ]
        }
        with app.app_context():
            for endpoint in ["/api/sky_art/export_gpx", "/api/flight_art/export_gpx"]:
                resp = client.post(endpoint, json=payload)
                assert resp.status_code == 200
                assert "gpx" in resp.headers["Content-Type"]

                xml_str = resp.data.decode("utf-8")
                root = ET.fromstring(xml_str)
                assert "gpx" in root.tag

    def test_export_kml_api(self, app, client):
        """Verify /api/sky_art/export_kml and legacy alias generate valid KML path XML."""
        payload = {
            "route_name": "N890GF KML Test",
            "waypoints": [
                {"id": "KCCR", "lat": 37.9897, "lon": -122.0569},
                {"id": "WP01", "lat": 38.0123, "lon": -122.0345}
            ]
        }
        with app.app_context():
            for endpoint in ["/api/sky_art/export_kml", "/api/flight_art/export_kml"]:
                resp = client.post(endpoint, json=payload)
                assert resp.status_code == 200
                assert "kml" in resp.headers["Content-Type"]

                xml_str = resp.data.decode("utf-8")
                root = ET.fromstring(xml_str)
                assert "kml" in root.tag

    def test_sky_art_drawings_crud_api(self, app, client):
        """Verify server-side CRUD persistence for Sky Art drawings across browsers."""
        with app.app_context():
            # 1. Initially list drawings
            res = client.get("/api/sky_art/drawings")
            assert res.status_code == 200
            initial_list = res.get_json()
            assert isinstance(initial_list, list)

            # 2. Save a new drawing
            test_id = "art_test_123456"
            payload = {
                "id": test_id,
                "name": "Server Persisted Test Art",
                "aspectRatio": 0.47,
                "sizeNM": 11.5,
                "heightNM": 5.4,
                "lockAspect": True,
                "routeReversed": False,
                "basePoints": [
                    {"x": -0.5, "y": 0.0},
                    {"x": 0.0, "y": 0.5},
                    {"x": 0.5, "y": -0.5}
                ]
            }
            post_res = client.post("/api/sky_art/drawings", json=payload)
            assert post_res.status_code == 200
            data = post_res.get_json()
            assert data["status"] == "success"
            assert data["drawing"]["id"] == test_id
            assert data["drawing"]["name"] == "Server Persisted Test Art"
            assert data["drawing"]["aspectRatio"] == 0.47
            assert len(data["drawing"]["basePoints"]) == 3

            # 3. Verify it is returned in GET
            get_res = client.get("/api/sky_art/drawings")
            assert get_res.status_code == 200
            drawings = get_res.get_json()
            found = [d for d in drawings if d["id"] == test_id]
            assert len(found) == 1
            assert found[0]["name"] == "Server Persisted Test Art"

            # 4. Verify legacy endpoint works as alias
            alias_res = client.get("/api/flight_art/drawings")
            assert alias_res.status_code == 200
            assert any(d["id"] == test_id for d in alias_res.get_json())

            # 5. Delete drawing
            del_res = client.delete(f"/api/sky_art/drawings/{test_id}")
            assert del_res.status_code == 200
            assert del_res.get_json()["status"] == "success"

            # 6. Verify deletion
            get_after = client.get("/api/sky_art/drawings")
            assert not any(d["id"] == test_id for d in get_after.get_json())
