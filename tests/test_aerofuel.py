"""
Tests for AeroFuel IQ integration into N890GF Tracker.
Verifies routes, templates, API endpoints, navigation buttons, and dataset loading.
"""

import json
import pytest


class TestAeroFuelIntegration:
    """Tests for AeroFuel IQ radar dashboard and API endpoints."""

    def test_fuel_map_button_in_index(self, app, auth_client):
        """Verify the 'Fuel $$ Map' button is rendered on the main dashboard and 'Check $$' is removed."""
        with app.app_context():
            response = auth_client.get("/")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert "Fuel $$ Map" in html
            assert 'href="/fuel_map"' in html
            assert "Check $$" not in html

    def test_fuel_map_dashboard_route(self, app, client):
        """Verify /fuel_map returns 200, renders the dashboard, and includes back link to tracker."""
        with app.app_context():
            response = client.get("/fuel_map")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert "AeroFuel IQ" in html
            assert "Radar v2.5.29" in html
            assert 'href="/"' in html
            assert "N890GF Tracker" in html
            assert "/static/aerofuel/css/style.css" in html
            assert "/static/aerofuel/js/app.js" in html

    def test_api_airports_summary(self, app, client):
        """Verify /api/airports returns valid summary JSON with airport records."""
        with app.app_context():
            response = client.get("/api/airports")
            assert response.status_code == 200
            data = json.loads(response.data.decode("utf-8"))
            assert "airports" in data
            assert data["total_airports"] > 0
            assert len(data["airports"]) > 0
            # Check fields of first airport
            first_apt = data["airports"][0]
            assert "icao" in first_apt
            assert "lat" in first_apt
            assert "lon" in first_apt

    def test_api_single_airport_lookup(self, app, client):
        """Verify /api/airport/<icao> returns detailed info for an authentic airport."""
        with app.app_context():
            response = client.get("/api/airport/KSQL")
            assert response.status_code == 200
            data = json.loads(response.data.decode("utf-8"))
            assert data["status"] == "ok"
            assert data["airport"]["icao"] == "KSQL"
            assert "San Carlos" in data["airport"]["name"] or data["airport"]["city"] == "San Carlos"

    def test_api_single_airport_not_found(self, app, client):
        """Verify /api/airport/<invalid> returns 404 error."""
        with app.app_context():
            response = client.get("/api/airport/ZZZZNOTREAL")
            assert response.status_code == 404
            data = json.loads(response.data.decode("utf-8"))
            assert data["status"] == "error"

    def test_api_airnav_health(self, app, client):
        """Verify /api/airnav/health returns 200 with service details."""
        with app.app_context():
            response = client.get("/api/airnav/health")
            assert response.status_code == 200
            data = json.loads(response.data.decode("utf-8"))
            assert data["status"] == "ok"
            assert "AeroFuel AirNav Live Proxy" in data["service"]

    def test_api_ourairports_status(self, app, client):
        """Verify /api/ourairports/status returns dataset metadata and timestamps."""
        with app.app_context():
            response = client.get("/api/ourairports/status")
            assert response.status_code == 200
            data = json.loads(response.data.decode("utf-8"))
            assert data["status"] == "ok"
            assert data["total_airports"] > 0

    def test_api_fuel_prices_catalog(self, app, client):
        """Verify /api/fuel-prices returns the master catalog."""
        with app.app_context():
            response = client.get("/api/fuel-prices")
            assert response.status_code == 200
            data = json.loads(response.data.decode("utf-8"))
            assert "airports" in data
            assert data["total_airports"] > 0

    def test_api_airnav_lookup_cached(self, app, client):
        """Verify /api/airnav?icao=KSQL returns cached radar and FBO details."""
        with app.app_context():
            response = client.get("/api/airnav?icao=KSQL")
            assert response.status_code == 200
            data = json.loads(response.data.decode("utf-8"))
            assert data["status"] == "ok"
            assert data["icao"] == "KSQL"
            assert "target" in data
            assert len(data["airports"]) > 0

    def test_api_airnav_missing_icao(self, app, client):
        """Verify /api/airnav without icao returns 400."""
        with app.app_context():
            response = client.get("/api/airnav")
            assert response.status_code == 400

    def test_api_airnav_route_missing_params(self, app, client):
        """Verify /api/airnav/route without origin/destination returns 400."""
        with app.app_context():
            response = client.get("/api/airnav/route?origin=KSQL")
            assert response.status_code == 400

    def test_api_airnav_sync_invalid_payload(self, app, client):
        """Verify /api/airnav/sync with invalid payload returns 400."""
        with app.app_context():
            response = client.post("/api/airnav/sync", json={})
            assert response.status_code == 400

    def test_route_airports_remain_when_radar_disabled_in_app_js(self, app, client):
        """Verify app.js contains logic ensuring route airports remain displayed when radar is turned off."""
        with app.app_context():
            response = client.get("/static/aerofuel/js/app.js")
            assert response.status_code == 200
            content = response.data.decode("utf-8")
            # Verify recalculateRadiusAirports does not return early when radarEnabled is false
            assert "Persistent markers (Origin, Destination, and active Route Stops)" in content
            # Verify active route stops are accepted when rendering markers
            assert "STATE.activeRoute && STATE.activeRoute.stops" in content
            # Verify clearRadarOffHoverMarker preserves route waypoints
            assert "isRouteWaypoint" in content
            assert "!isOrigin && !isDest && !isPopupOpen && !isRouteWaypoint" in content

    def test_radar_power_hotkey_and_tooltip_in_app_js(self, app, client):
        """Verify app.js contains keyboard shortcut (R) to toggle radar and updates tooltips."""
        with app.app_context():
            response = client.get("/static/aerofuel/js/app.js")
            assert response.status_code == 200
            content = response.data.decode("utf-8")
            # Verify hotkey listener for R
            assert "KeyR" in content
            assert "setRadarEnabled(!STATE.radarEnabled)" in content
            # Verify dynamic tooltips highlight shortcut R
            assert "Turn Radar OFF (Shortcut: R)" in content
            assert "Turn Radar ON (Shortcut: R)" in content

    def test_radar_power_button_tooltip_in_template(self, app, client):
        """Verify fuel_map.html renders radar button with shortcut R in title attribute."""
        with app.app_context():
            response = client.get("/fuel_map")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert 'id="btn-radar-power"' in html
            assert "Toggle Search Radius Radar (Shortcut: R)" in html

    def test_radar_off_collapses_sidebar_in_app_js(self, app, client):
        """Verify app.js automatically collapses radar airports sidebar when radar is turned off."""
        with app.app_context():
            response = client.get("/static/aerofuel/js/app.js")
            assert response.status_code == 200
            content = response.data.decode("utf-8")
            # Verify setRadarSidebarCollapsed function exists and is exported
            assert "function setRadarSidebarCollapsed(collapsed)" in content
            assert "setRadarSidebarCollapsed: setRadarSidebarCollapsed" in content
            # Verify setRadarEnabled calls setRadarSidebarCollapsed(true) when radar is turned off
            assert "setRadarSidebarCollapsed(true)" in content

    def test_collapsed_sidebar_zoom_controls_not_overlapping_in_css(self, app, client):
        """Verify style.css sets top: 72px for zoom/layer controls when sidebar is collapsed to avoid overlap."""
        with app.app_context():
            response = client.get("/static/aerofuel/css/style.css")
            assert response.status_code == 200
            css = response.data.decode("utf-8")
            # Check collapsed/minimized selector sets top: 72px
            assert "body.sidebar-minimized .leaflet-top.leaflet-right" in css
            assert "top: 72px !important;" in css
            assert "right: 16px !important;" in css

    def test_legend_secondary_descriptors_removed_and_styles(self, app, client):
        """Verify secondary descriptors are removed from fuel price tiers and styles prevent cutoff."""
        with app.app_context():
            res_html = client.get("/fuel_map")
            assert res_html.status_code == 200
            html = res_html.data.decode("utf-8")
            # Verify secondary descriptors are removed
            for descriptor in ["Best Value", "Above Avg", "On-Demand"]:
                assert descriptor not in html
            assert 'class="legend-tier-sub"' not in html

            res_css = client.get("/static/aerofuel/css/style.css")
            assert res_css.status_code == 200
            css = res_css.data.decode("utf-8")
            assert "width: 250px;" in css
            assert "flex-shrink: 0;" in css

    def test_radar_zoom_vector_renderer_and_prefer_canvas_in_app_js(self, app, client):
        """Verify app.js uses preferCanvas: false and animated zoom to prevent canvas distortion."""
        with app.app_context():
            response = client.get("/static/aerofuel/js/app.js")
            assert response.status_code == 200
            content = response.data.decode("utf-8")
            # Verify preferCanvas is false so vector shapes are rendered via Leaflet standard SVG
            assert "preferCanvas: false" in content
            assert "zoomAnimation: true" in content
            assert "zoomSnap: 1" in content

    def test_radar_zoom_stability_and_no_corrupted_zoom_hooks_in_app_js(self, app, client):
        """Verify app.js does not hook intermediate zoom event listeners that corrupt coordinate projections."""
        with app.app_context():
            response = client.get("/static/aerofuel/js/app.js")
            assert response.status_code == 200
            content = response.data.decode("utf-8")
            # Ensure no buggy syncCircleToCursor or intermediate zoom mutators
            assert "function syncCircleToCursor()" not in content
            assert "syncCircleToCursor" not in content

    def test_radar_zoom_configuration_in_aerofuel_iq_repo(self):
        """Verify standalone aerofuel_iq repo has identical zoom stability configuration."""
        import os
        aerofuel_path = os.path.expanduser("~/Documents/projects/aerofuel_iq/js/app.js")
        if os.path.exists(aerofuel_path):
            with open(aerofuel_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert "preferCanvas: false" in content
            assert "zoomAnimation: true" in content
            assert "syncCircleToCursor" not in content

    def test_radar_zoom_renderer_update_and_scope_in_app_js(self, app, client):
        """Verify radiusCircle._renderer._update() is invoked on zoomend/moveend and centerLat is properly scoped."""
        with app.app_context():
            response = client.get("/static/aerofuel/js/app.js")
            assert response.status_code == 200
            content = response.data.decode("utf-8")
            # Verify zoomend & moveend update the circle renderer container
            assert "radiusCircle._renderer._update()" in content
            # Verify centerLat is declared at function scope in recalculateRadiusAirports
            func_idx = content.find("function recalculateRadiusAirports()")
            assert func_idx != -1
            body_snippet = content[func_idx:func_idx + 350]
            assert "const centerLat = STATE.circleCenter.lat;" in body_snippet
            assert "const centerLon = STATE.circleCenter.lng;" in body_snippet

    def test_mobile_fuel_map_interface_elements(self, app, client):
        """Verify mobile navigation bar, drawer architecture, and backdrop are present in templates, CSS, and JS."""
        with app.app_context():
            # 1. Template verification
            res_html = client.get("/fuel_map")
            assert res_html.status_code == 200
            html = res_html.data.decode("utf-8")
            assert 'id="mobile-action-bar"' in html
            assert 'id="mobile-btn-radar"' in html
            assert 'id="mobile-btn-controls"' in html
            assert 'id="mobile-btn-filters"' in html
            assert 'id="mobile-btn-airports"' in html
            assert 'id="mobile-btn-legend"' in html
            assert 'id="mobile-drawer-backdrop"' in html
            assert 'class="mobile-sheet-header"' in html
            assert "syncNavControlsPlacement" in html or "mobile-drawer" in html

            # 2. CSS verification
            res_css = client.get("/static/aerofuel/css/style.css")
            assert res_css.status_code == 200
            css = res_css.data.decode("utf-8")
            assert "#mobile-action-bar" in css
            assert ".mobile-drawer-backdrop" in css
            assert ".mobile-open" in css
            assert "@media (max-width: 860px)" in css
            assert "#top-nav .nav-controls" in css
            assert "display: none !important;" in css
            assert ".nav-controls.mobile-drawer" in css

            # 3. JavaScript verification
            res_js = client.get("/static/aerofuel/js/app.js")
            assert res_js.status_code == 200
            js = res_js.data.decode("utf-8")
            assert "setupMobileInterface" in js
            assert "closeAllDrawers" in js
            assert "toggleDrawer" in js
            assert "mobile-airports-badge" in js
            assert "syncNavControlsPlacement" in js

    def test_mobile_scale_toggle_and_collapsible_scale(self, app, client):
        """Verify the scale is collapsible, has toggle control button, and starts collapsed on mobile."""
        with app.app_context():
            # 1. JS verification
            res_js = client.get("/static/aerofuel/js/app.js")
            assert res_js.status_code == 200
            js = res_js.data.decode("utf-8")
            assert "AeroScaleControl" in js
            assert "ScaleToggleControl" in js
            assert "leaflet-control-scale-toggle" in js
            assert "leaflet-control-scale-btn" in js
            assert "isCollapsed" in js
            assert "aeroScaleControl.collapse()" in js

            # 2. CSS verification
            res_css = client.get("/static/aerofuel/css/style.css")
            assert res_css.status_code == 200
            css = res_css.data.decode("utf-8")
            assert ".leaflet-control-scale-toggle" in css
            assert ".scale-collapsed" in css
            assert ".aero-scale-close-btn" in css
            assert "has-active-airport-hud" in css

    def test_mobile_map_controls_positioning(self, app, client):
        """Verify map controls on mobile are indented from left edge and desktop offsets are scoped."""
        with app.app_context():
            res_css = client.get("/static/aerofuel/css/style.css")
            assert res_css.status_code == 200
            css = res_css.data.decode("utf-8")
            # Verify desktop right: 368px is scoped inside min-width: 861px
            assert "@media (min-width: 861px)" in css
            assert "right: 368px !important;" in css
            # Verify mobile controls have safe margins from screen edge
            assert "left: 16px !important;" in css
            assert "right: auto !important;" in css

    def test_selected_airport_hud_when_radar_off(self, app, client):
        """Verify airport selection HUD works when radar is off and shows airport specs and rates."""
        with app.app_context():
            res_js = client.get("/static/aerofuel/js/app.js")
            assert res_js.status_code == 200
            js = res_js.data.decode("utf-8")
            assert "showSelectedAirportHUD" in js
            assert "STATE.selectedAirport" in js
            assert "btn-fly-selected" in js
            assert "btn-details-selected" in js
            assert "btn-close-selected" in js
            assert "has-active-airport-hud" in js
            # Verify recalculateRadiusAirports renders selectedAirport HUD when radar is off
            assert "showSelectedAirportHUD(STATE.selectedAirport)" in js

    def test_app_js_syntax_validation(self):
        """Verify static/aerofuel/js/app.js contains strictly valid JavaScript without syntax errors."""
        import shutil
        import subprocess
        node_bin = shutil.which("node")
        if node_bin:
            res = subprocess.run([node_bin, "-c", "static/aerofuel/js/app.js"], capture_output=True, text=True)
            assert res.returncode == 0, f"JavaScript syntax error in static/aerofuel/js/app.js: {res.stderr}"

    def test_mobile_airport_hud_and_popup_centered(self, app, client):
        """Verify the airport HUD and popup cards are horizontally centered on mobile."""
        with app.app_context():
            res_css = client.get("/static/aerofuel/css/style.css")
            assert res_css.status_code == 200
            css = res_css.data.decode("utf-8")
            assert "left: 50% !important;" in css
            assert "transform: translateX(-50%) !important;" in css
            assert "max-width: calc(100vw - 24px) !important;" in css


