import pandas as pd
import pytest
from src.process_telemetry import process_flights, calculate_flight_summary


class TestProcessTelemetry:
    def test_process_flights_basic(self):
        data = {
            "Session Time": [1.0, 2.0, 3.0],
            "System Time": ["1.0", "2.0", "3.0"],
            "GPS Date & Time": ["2026-07-26 12:00:00", "2026-07-26 12:00:01", "2026-07-26 12:00:02"],
            "RPM L": [2400, 2420, 2410],
            "RPM R": [2400, 2420, 2410],
            "CHT 1 (deg F)": [350, 355, 360],
            "CHT 2 (deg F)": [350, 355, 360],
            "CHT 3 (deg F)": [350, 355, 360],
            "CHT 4 (deg F)": [350, 355, 360],
            "OAT (deg F)": [70, 70, 70],
            "OIL TEMPERATURE (deg F)": [180, 182, 185],
            "Fuel Flow 1 (gal/hr)": [10.5, 10.5, 10.5],
            "Ground Speed (knots)": [120, 122, 121],
            "Transponder Status": [3, 3, 3],
        }
        df = pd.DataFrame(data)
        processed = process_flights(df)

        assert processed is not None
        assert not processed.empty
        assert "Flight ID" in processed.columns
        assert "AVG_CHT" in processed.columns
        assert "Fuel Flow Integral" in processed.columns
        assert "Distance Traveled" in processed.columns

    def test_calculate_flight_summary(self):
        data = {
            "Session Time": [0, 60, 120],
            "Transponder Status": [3, 3, 3],
            "Distance Traveled": [0, 2640, 5280],  # 5280 ft = 1 mi
            "Fuel Flow Integral": [0.0, 0.1, 0.2],
            "Max CHT": [360, 360, 360],
            "RPM": [2400, 2400, 2400],
            "MPG": [12.0, 12.0, 12.0],
            "Ground Speed (knots)": [100, 100, 100],
        }
        df = pd.DataFrame(data)
        summary = calculate_flight_summary(df)

        assert summary["total_duration"] == 120
        assert summary["air_time"] == 120
        assert summary["distance_traveled"] == 1.0
        assert summary["gallons_used"] == 0.2
        assert summary["max_rpm"] == 2400
