import numpy as np
import pandas as pd
from src.flight_analytics import (
    calculate_shock_cooling,
    calculate_cht_spread,
    calculate_cht_thermal_durations,
    calculate_oil_metrics,
    calculate_flight_phases,
    calculate_landings,
    calculate_wind_aloft,
    calculate_g_load_and_bank,
    calculate_climb_gradient,
    extract_comprehensive_flight_stats,
)


def create_sample_flight_df():
    time_points = np.linspace(0, 1800, 100)  # 30 minutes
    df = pd.DataFrame(
        {
            "Session Time": time_points,
            "Ground Speed (knots)": np.where(time_points < 300, 20, 120),
            "True Airspeed (knots)": np.where(time_points < 300, 0, 115),
            "Magnetic Heading (deg)": np.full(100, 270.0),
            "Ground Track (deg)": np.full(100, 265.0),
            "RPM": np.where(time_points < 300, 1000, 2400),
            "GPS Altitude (feet)": np.where(
                time_points < 300,
                500,
                np.where(time_points < 900, 500 + (time_points - 300) * 5, 3500),
            ),
            "Vertical Speed (ft/min)": np.where(
                time_points < 300,
                0,
                np.where(time_points < 900, 500, 0),
            ),
            "CHT 1 (deg F)": np.where(time_points > 1200, 390 - (time_points - 1200) * 0.1, 350),
            "CHT 2 (deg F)": np.full(100, 340.0),
            "CHT 3 (deg F)": np.full(100, 330.0),
            "CHT 4 (deg F)": np.full(100, 320.0),
            "OAT (deg F)": np.full(100, 50.0),
            "OIL TEMPERATURE (deg F)": np.full(100, 180.0),
            "Oil Pressure (PSI)": np.full(100, 65.0),
            "Roll (deg)": np.full(100, 15.0),
            "Vert Accel (G)": np.full(100, 1.2),
        }
    )
    return df


def test_shock_cooling():
    df = create_sample_flight_df()
    shock = calculate_shock_cooling(df)
    assert isinstance(shock, float)
    assert shock >= 0.0


def test_cht_spread():
    df = create_sample_flight_df()
    spread = calculate_cht_spread(df)
    assert isinstance(spread, float)
    assert spread >= 0.0


def test_thermal_durations():
    df = create_sample_flight_df()
    durations = calculate_cht_thermal_durations(df)
    assert "above_380_min" in durations
    assert "above_400_min" in durations
    assert durations["above_380_min"] >= 0.0


def test_oil_metrics():
    df = create_sample_flight_df()
    oil = calculate_oil_metrics(df)
    assert "oil_temp_delta" in oil
    assert "min_oil_press" in oil


def test_flight_phases():
    df = create_sample_flight_df()
    phases = calculate_flight_phases(df)
    assert "taxi_min" in phases
    assert "climb_min" in phases
    assert "cruise_min" in phases


def test_landings():
    df = create_sample_flight_df()
    landings = calculate_landings(df)
    assert isinstance(landings, int)
    assert landings >= 1


def test_wind_aloft():
    df = create_sample_flight_df()
    wind = calculate_wind_aloft(df)
    assert "wind_speed_kts" in wind
    assert "headwind_kts" in wind


def test_g_load_and_bank():
    df = create_sample_flight_df()
    g_bank = calculate_g_load_and_bank(df)
    assert "peak_pos_g" in g_bank
    assert "max_bank_deg" in g_bank


def test_comprehensive_stats():
    df = create_sample_flight_df()
    stats = extract_comprehensive_flight_stats(df)
    assert "max_shock_cooling" in stats
    assert "cht_spread" in stats
    assert "taxi_min" in stats
    assert "landing_count" in stats
