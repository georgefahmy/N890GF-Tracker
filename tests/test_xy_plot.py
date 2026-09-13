"""
Tests for the XY Plot feature and the /api/analyze_flight endpoint.
Validates trace generation, filtering, temperature units, error handling, and performance.
"""

import json
import time
import pytest


class TestXYPlotAPI:
    """Tests covering XY Plot data retrieval, filtering, and performance."""

    TEST_FLIGHT = "2026-09-07 16-27-33.csv"

    def test_xy_plot_endpoint_basic_signals(self, app, client):
        """Test fetching basic signal pairs with only_traces=true."""
        with app.app_context():
            response = client.post(
                "/api/analyze_flight",
                data={
                    "saved_filename": self.TEST_FLIGHT,
                    "left_signal": "RPM",
                    "right_signal": "Indicated Airspeed (knots)",
                    "temp_unit": "F",
                    "filters": "[]",
                    "only_traces": "true",
                },
            )
            assert response.status_code == 200
            data = response.get_json()
            assert "plot_data" in data
            plot_data = data["plot_data"]
            assert "left_traces" in plot_data
            assert "right_traces" in plot_data
            assert len(plot_data["left_traces"]) >= 1
            assert len(plot_data["right_traces"]) >= 1

            # Ensure x and y series exist and have matching length
            left_y = plot_data["left_traces"][0]["y"]
            right_y = plot_data["right_traces"][0]["y"]
            assert len(left_y) > 0
            assert len(left_y) == len(right_y)
            assert all(isinstance(v, (int, float)) for v in left_y[:50])

    def test_xy_plot_temperature_grouped_signals(self, app, client):
        """Test CHT vs EGT grouped signals return cylinder traces."""
        with app.app_context():
            response = client.post(
                "/api/analyze_flight",
                data={
                    "saved_filename": self.TEST_FLIGHT,
                    "left_signal": "CHT",
                    "right_signal": "EGT",
                    "temp_unit": "F",
                    "filters": "[]",
                    "only_traces": "true",
                },
            )
            assert response.status_code == 200
            data = response.get_json()
            plot_data = data["plot_data"]
            # Both CHT and EGT should have multiple cylinder traces
            assert len(plot_data["left_traces"]) >= 1
            assert len(plot_data["right_traces"]) >= 1
            assert any("CHT" in t["name"] for t in plot_data["left_traces"])
            assert any("EGT" in t["name"] for t in plot_data["right_traces"])

    def test_xy_plot_filters_application(self, app, client):
        """Test numeric filters properly filter data points."""
        with app.app_context():
            # 1. Unfiltered request
            res_raw = client.post(
                "/api/analyze_flight",
                data={
                    "saved_filename": self.TEST_FLIGHT,
                    "left_signal": "RPM",
                    "right_signal": "Indicated Airspeed (knots)",
                    "temp_unit": "F",
                    "filters": "[]",
                    "only_traces": "true",
                },
            )
            raw_len = len(res_raw.get_json()["plot_data"]["left_traces"][0]["y"])

            # 2. Filtered request (RPM > 2000)
            filters = json.dumps([{"signal": "RPM", "op": ">", "value": 2000}])
            res_filtered = client.post(
                "/api/analyze_flight",
                data={
                    "saved_filename": self.TEST_FLIGHT,
                    "left_signal": "RPM",
                    "right_signal": "Indicated Airspeed (knots)",
                    "temp_unit": "F",
                    "filters": filters,
                    "only_traces": "true",
                },
            )
            assert res_filtered.status_code == 200
            filtered_y = res_filtered.get_json()["plot_data"]["left_traces"][0]["y"]
            filtered_len = len(filtered_y)

            assert 0 < filtered_len < raw_len
            # Verify all remaining points satisfy RPM > 2000
            assert all(v > 2000 for v in filtered_y)

    def test_xy_plot_multiple_filters(self, app, client):
        """Test multiple chained filters (e.g. RPM >= 2200 and IAS >= 110)."""
        with app.app_context():
            filters = json.dumps([
                {"signal": "RPM", "op": ">=", "value": 2200},
                {"signal": "Indicated Airspeed (knots)", "op": ">=", "value": 110},
            ])
            res = client.post(
                "/api/analyze_flight",
                data={
                    "saved_filename": self.TEST_FLIGHT,
                    "left_signal": "RPM",
                    "right_signal": "Indicated Airspeed (knots)",
                    "temp_unit": "F",
                    "filters": filters,
                    "only_traces": "true",
                },
            )
            assert res.status_code == 200
            data = res.get_json()["plot_data"]
            rpm_vals = data["left_traces"][0]["y"]
            ias_vals = data["right_traces"][0]["y"]
            assert len(rpm_vals) == len(ias_vals)
            if len(rpm_vals) > 0:
                assert all(r >= 2200 for r in rpm_vals)
                assert all(i >= 110 for i in ias_vals)

    def test_xy_plot_performance_fast(self, app, client):
        """Test that only_traces=true returns in under 0.5s."""
        with app.app_context():
            start_time = time.time()
            res = client.post(
                "/api/analyze_flight",
                data={
                    "saved_filename": self.TEST_FLIGHT,
                    "left_signal": "RPM",
                    "right_signal": "Indicated Airspeed (knots)",
                    "temp_unit": "F",
                    "filters": "[]",
                    "only_traces": "true",
                },
            )
            elapsed = time.time() - start_time
            assert res.status_code == 200
            assert elapsed < 0.5, f"Expected < 0.5s, took {elapsed:.3f}s"

    def test_xy_plot_missing_file_error(self, app, client):
        """Test error handling when filename is missing or nonexistent."""
        with app.app_context():
            # Missing parameter
            res = client.post("/api/analyze_flight", data={"only_traces": "true"})
            assert res.status_code == 400
            assert "error" in res.get_json()

            # Nonexistent file
            res = client.post(
                "/api/analyze_flight",
                data={
                    "saved_filename": "nonexistent_flight_12345.csv",
                    "only_traces": "true",
                },
            )
            assert res.status_code == 404

    def test_xy_plot_nonexistent_signal_graceful(self, app, client):
        """Test requesting a signal that does not exist returns empty trace without crashing."""
        with app.app_context():
            res = client.post(
                "/api/analyze_flight",
                data={
                    "saved_filename": self.TEST_FLIGHT,
                    "left_signal": "NonexistentSignal_ABC",
                    "right_signal": "RPM",
                    "temp_unit": "F",
                    "filters": "[]",
                    "only_traces": "true",
                },
            )
            assert res.status_code == 200
            data = res.get_json()
            assert "plot_data" in data
            assert data["plot_data"]["left_traces"] == []
            assert len(data["plot_data"]["right_traces"]) >= 1
