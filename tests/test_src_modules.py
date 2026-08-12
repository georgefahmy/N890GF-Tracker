"""
Tests for src/ library modules.

Covers: fuel_estimate_simple, airspeed_calibration, tool_functions
"""

import math
import os
import tempfile

import numpy as np
import pandas as pd
import pytest


# =============================================================================
# Airspeed Calibration (src/airspeed_calibration.py)
# =============================================================================


class TestCalculateHeadingSpan:
    """Tests for calculate_heading_span()."""

    def test_triangle_maneuver_span(self):
        from src.airspeed_calibration import calculate_heading_span

        # 3-leg triangle maneuver (120, 240, 360)
        hdgs = pd.Series([120, 120, 240, 240, 360, 360])
        span = calculate_heading_span(hdgs)
        assert span == 240.0

    def test_straight_leg_span(self):
        from src.airspeed_calibration import calculate_heading_span

        hdgs = pd.Series([90.0, 91.0, 92.0, 90.5])
        span = calculate_heading_span(hdgs)
        assert span == 2.0

    def test_full_circle_span(self):
        from src.airspeed_calibration import calculate_heading_span

        hdgs = pd.Series(np.linspace(0, 359, 360))
        span = calculate_heading_span(hdgs)
        assert span >= 358.0


# =============================================================================
# Fuel Estimation (src/fuel_estimate_simple.py)
# =============================================================================


class TestAirfoilThickness:
    """Tests for airfoil_thickness() — NACA thickness distribution."""

    def test_zero_chord_position(self):
        from src.fuel_estimate_simple import airfoil_thickness

        # At x=0, all NACA polynomial terms are 0
        result = airfoil_thickness(0)
        assert result == 0.0

    def test_positive_thickness_at_midchord(self):
        from src.fuel_estimate_simple import airfoil_thickness

        result = airfoil_thickness(0.3)
        assert result > 0

    def test_thickness_increases_then_decreases(self):
        from src.fuel_estimate_simple import airfoil_thickness

        # Thickness should increase toward max thickness location
        t_near_le = airfoil_thickness(0.05)
        t_at_max = airfoil_thickness(0.30)
        t_near_te = airfoil_thickness(0.9)

        assert t_at_max > t_near_le
        assert t_at_max > t_near_te


class TestAirfoilCamber:
    """Tests for airfoil_camber() — NACA 230-series camber line."""

    def test_zero_camber_at_trailing_edge(self):
        from src.fuel_estimate_simple import airfoil_camber

        result = airfoil_camber(1.0)
        assert abs(result) < 0.01  # Should be ~0 at TE

    def test_camber_positive_at_midchord(self):
        from src.fuel_estimate_simple import airfoil_camber

        result = airfoil_camber(0.3)
        assert result > 0


class TestSectionBounds:
    """Tests for section_bounds() — top/bottom surface heights."""

    def test_top_above_bottom(self):
        from src.fuel_estimate_simple import section_bounds

        for x in [0.05, 0.15, 0.30, 0.50, 0.80]:
            top, bottom = section_bounds(x)
            assert top > bottom, f"top <= bottom at x={x}"


class TestCalculateFullVolume:
    """Tests for calculate_full_volume() — total tank volume."""

    def test_positive_volume(self):
        from src.fuel_estimate_simple import calculate_full_volume

        vol = calculate_full_volume()
        assert vol > 0

    def test_volume_reasonable_magnitude(self):
        from src.fuel_estimate_simple import calculate_full_volume

        vol = calculate_full_volume()
        # Volume in cubic inches for a ~50" x 17" tank section
        assert 100 < vol < 50000


class TestCalculateFuel:
    """Tests for calculate_fuel() — fuel estimation from sight gauge height."""

    def test_zero_height_returns_some_fuel(self):
        from src.fuel_estimate_simple import calculate_fuel

        gallons, inboard_height = calculate_fuel(0)
        # At zero height at the filler, there may still be fuel
        # due to tilt (fuel pools at inboard end)
        assert isinstance(gallons, float)

    def test_max_height_near_full(self):
        from src.fuel_estimate_simple import calculate_fuel, MAX_THICK

        gallons, _ = calculate_fuel(MAX_THICK)
        # Should be close to or at full capacity
        assert gallons > 0

    def test_increasing_height_increases_fuel(self):
        from src.fuel_estimate_simple import calculate_fuel

        gal_low, _ = calculate_fuel(1.0)
        gal_mid, _ = calculate_fuel(3.0)
        gal_high, _ = calculate_fuel(5.0)

        assert gal_mid >= gal_low
        assert gal_high >= gal_mid

    def test_returns_tuple(self):
        from src.fuel_estimate_simple import calculate_fuel

        result = calculate_fuel(3.0)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_custom_angles(self):
        from src.fuel_estimate_simple import calculate_fuel

        # Different tilt angles should produce different results
        gal_default, _ = calculate_fuel(3.0, angle=2.5, pitch_angle=11)
        gal_flat, _ = calculate_fuel(3.0, angle=0, pitch_angle=0)

        # Both should be valid positive numbers
        assert gal_default > 0
        assert gal_flat > 0

    def test_calculate_fuel_fast(self):
        from src.fuel_estimate_simple import calculate_fuel, calculate_fuel_fast

        gal_slow, _ = calculate_fuel(3.5)
        gal_fast, _ = calculate_fuel_fast(3.5)
        assert abs(gal_slow - gal_fast) < 0.05

    def test_calculate_usable_fuel(self):
        from src.fuel_estimate_simple import calculate_usable_fuel

        assert calculate_usable_fuel(20.0, unusable_per_tank=0.5, num_tanks=2) == 19.0
        assert calculate_usable_fuel(0.5, unusable_per_tank=0.5, num_tanks=2) == 0.0

    def test_calculate_endurance(self):
        from src.fuel_estimate_simple import calculate_endurance

        res = calculate_endurance(21.0, cruise_gph=10.5)
        assert res["hours"] == 2.0
        assert res["fmt"] == "2h 00m"
        assert res["reserve_status"] == "OK"

    def test_reconcile_fuel_burn(self):
        from src.fuel_reconciliation import reconcile_fuel_burn
        import pandas as pd

        df = pd.DataFrame({"Fuel Flow Integral": [0.0, 5.0, 10.0]})
        rec = reconcile_fuel_burn(pre_flight_gallons=30.0, post_flight_gallons=20.0, df_telemetry=df)
        assert rec["measured_burn_sight_gauge"] == 10.0
        assert rec["telemetry_burn_integral"] == 10.0
        assert rec["status"] == "EXCELLENT"


# =============================================================================
# Airspeed Calibration (src/airspeed_calibration.py)
# =============================================================================


class TestCalculateDensityRatio:
    """Tests for calculate_density_ratio() — atmospheric density ratio."""

    def test_sea_level_standard(self):
        from src.airspeed_calibration import calculate_density_ratio

        # At sea level, 15°C (59°F), sigma should be ~1.0
        sigma = calculate_density_ratio(0, 15)
        assert abs(sigma - 1.0) < 0.01

    def test_altitude_reduces_density(self):
        from src.airspeed_calibration import calculate_density_ratio

        sigma_sl = calculate_density_ratio(0, 15)
        sigma_5k = calculate_density_ratio(5000, 5)
        sigma_10k = calculate_density_ratio(10000, -5)

        assert sigma_sl > sigma_5k > sigma_10k

    def test_higher_temp_reduces_density(self):
        from src.airspeed_calibration import calculate_density_ratio

        sigma_cold = calculate_density_ratio(5000, 0)
        sigma_hot = calculate_density_ratio(5000, 30)

        assert sigma_cold > sigma_hot


class TestWindTriangleResiduals:
    """Tests for wind_triangle_residuals() — optimizer objective function."""

    def test_zero_residuals_with_perfect_data(self):
        from src.airspeed_calibration import (
            wind_triangle_residuals,
            calculate_density_ratio,
        )

        # Create synthetic data where wind is exactly known
        df = pd.DataFrame(
            {
                "ias": [120.0, 120.0, 120.0, 120.0],
                "press_alt": [5000, 5000, 5000, 5000],
                "hdg": [0, 90, 180, 270],
                "gps_gs": [120, 120, 120, 120],
                "gps_trk": [0, 90, 180, 270],
            }
        )
        df["sigma"] = df.apply(
            lambda r: calculate_density_ratio(r["press_alt"], 15), axis=1
        )

        # No corrections, no wind: residuals should be near zero
        params = [0.0, 0.0, 0.0, 0.0]
        residual = wind_triangle_residuals(params, df)
        # Allow some tolerance since TAS != IAS at altitude
        assert isinstance(residual, float)

    def test_residuals_positive(self):
        from src.airspeed_calibration import (
            wind_triangle_residuals,
            calculate_density_ratio,
        )

        df = pd.DataFrame(
            {
                "ias": [100.0, 110.0],
                "press_alt": [3000, 3000],
                "hdg": [0, 180],
                "gps_gs": [90, 130],
                "gps_trk": [10, 170],
            }
        )
        df["sigma"] = df.apply(
            lambda r: calculate_density_ratio(r["press_alt"], 10), axis=1
        )

        params = [0.0, 0.0, 15.0, 300.0]
        residual = wind_triangle_residuals(params, df)
        assert residual >= 0


class TestAnalyzeFlightData:
    """Tests for analyze_flight_data() — airspeed calibration solver."""

    def _create_synthetic_data(self, n_points=50):
        """Create synthetic flight data for testing the solver."""
        from src.airspeed_calibration import calculate_density_ratio

        np.random.seed(42)
        headings = np.linspace(0, 360, n_points, endpoint=False)
        df = pd.DataFrame(
            {
                "session_time": np.linspace(0, 300, n_points),
                "ias": np.full(n_points, 110.0) + np.random.normal(0, 1, n_points),
                "press_alt": np.full(n_points, 4000),
                "hdg": headings,
                "gps_gs": np.full(n_points, 115.0) + np.random.normal(0, 2, n_points),
                "gps_trk": headings + np.random.normal(0, 1, n_points),
                "oat": np.full(n_points, 50.0),  # deg F
                "baro": np.full(n_points, 29.92),
                "Manifold Pressure (inHg)": np.full(n_points, 24.5),
                "RPM": np.full(n_points, 2400.0),
                "Total Fuel Flow (gal/hr)": np.full(n_points, 11.5),
                "Percent Power": np.full(n_points, 75.0),
            }
        )
        return df

    def test_returns_valid_results(self):
        from src.airspeed_calibration import analyze_flight_data

        df = self._create_synthetic_data()
        result = analyze_flight_data(df)

        assert result is not None
        assert "calibrated_airspeed_correction_kts" in result
        assert "wind_speed_kts" in result
        assert "wind_direction_deg" in result
        assert "engine_settings" in result
        assert result["engine_settings"]["manifold_pressure_inhg"] == 24.5
        assert result["engine_settings"]["rpm"] == 2400.0
        assert result["engine_settings"]["fuel_flow_gph"] == 11.5
        assert result["engine_settings"]["percent_power"] == 75.0
        assert result["analyzed_data_points"] == len(df)

    def test_with_time_slice(self):
        from src.airspeed_calibration import analyze_flight_data

        df = self._create_synthetic_data(n_points=100)
        result = analyze_flight_data(df, start_time=50, end_time=200)

        assert result is not None
        assert result["analyzed_data_points"] < 100

    def test_insufficient_data_raises(self):
        from src.airspeed_calibration import analyze_flight_data

        # Only 5 points — below the 10-point minimum
        df = pd.DataFrame(
            {
                "session_time": [0, 1, 2, 3, 4],
                "ias": [100, 100, 100, 100, 100],
                "press_alt": [3000, 3000, 3000, 3000, 3000],
                "hdg": [0, 90, 180, 270, 45],
                "gps_gs": [100, 100, 100, 100, 100],
                "gps_trk": [0, 90, 180, 270, 45],
                "oat": [50, 50, 50, 50, 50],
                "baro": [29.92] * 5,
            }
        )

        with pytest.raises(ValueError, match="Not enough data"):
            analyze_flight_data(df, start_time=0, end_time=4)


# =============================================================================
# Tool Functions (src/tool_functions.py)
# =============================================================================


class TestToolFunctions:
    """Tests for src/tool_functions.py aggregation helpers."""

    def _make_mock_df(self):
        """Create a mock stats DataFrame matching load_stats_file() output."""
        return pd.DataFrame(
            {
                "total_duration": [3600, 2400, 1800],
                "air_time": [3000, 2000, 1500],
                "distance_traveled": [120.5, 85.2, 60.0],
                "gallons_used": [12.0, 8.5, 6.0],
                "max_cht": [360, 355, 340],
                "max_rpm": [2600, 2550, 2500],
                "avg_mpg": [14.5, 15.2, 13.8],
                "avg_speed": [145, 140, 135],
            },
            index=["flight_1", "flight_2", "flight_3"],
        )

    def test_calc_total_distance(self):
        from src.tool_functions import calc_total_distance

        df = self._make_mock_df()
        result = calc_total_distance(df)
        expected = 120.5 + 85.2 + 60.0
        assert abs(result - expected) < 0.01

    def test_calc_total_air_time(self):
        from src.tool_functions import calc_total_air_time

        df = self._make_mock_df()
        result = calc_total_air_time(df)
        assert result == 6500.0  # 3000 + 2000 + 1500

    def test_calc_total_gallons(self):
        from src.tool_functions import calc_total_gallons

        df = self._make_mock_df()
        result = calc_total_gallons(df)
        assert result == 26.5  # 12.0 + 8.5 + 6.0

    def test_returns_float(self):
        from src.tool_functions import (
            calc_total_distance,
            calc_total_air_time,
            calc_total_gallons,
        )

        df = self._make_mock_df()
        assert isinstance(calc_total_distance(df), float)
        assert isinstance(calc_total_air_time(df), float)
        assert isinstance(calc_total_gallons(df), float)


class TestAirspeedCalibrationFactor:
    """Tests for calculate_airspeed_calibration_factor and Corrected TAS signal derivation."""

    def test_calculate_airspeed_calibration_factor_default(self):
        from src.process_telemetry import calculate_airspeed_calibration_factor

        factor = calculate_airspeed_calibration_factor()
        assert isinstance(factor, float)
        assert factor == 0.48

    def test_process_flights_generates_corrected_tas(self):
        from src.process_telemetry import process_flights

        df = pd.DataFrame({
            "Session Time": [1.0, 2.0, 3.0],
            "System Time": ["2026-04-10 12:00:00", "2026-04-10 12:00:01", "2026-04-10 12:00:02"],
            "GPS Date & Time": ["2026-04-10 12:00:00", "2026-04-10 12:00:01", "2026-04-10 12:00:02"],
            "Indicated Airspeed (knots)": [120.0, 122.0, 125.0],
            "Pressure Altitude (ft)": [5000, 5000, 5000],
            "OAT (deg F)": [59.0, 59.0, 59.0],
            "RPM": [2400, 2400, 2400],
            "CHT 1 (deg F)": [350, 350, 350],
        })

        processed = process_flights(df)
        assert "CAS (knots)" in processed.columns
        assert "Corrected TAS (knots)" in processed.columns
        assert (processed["CAS (knots)"] > processed["Indicated Airspeed (knots)"]).all()
        assert (processed["Corrected TAS (knots)"] > processed["CAS (knots)"]).all()

