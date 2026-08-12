import numpy as np
import pandas as pd


def reconcile_fuel_burn(pre_flight_gallons: float, post_flight_gallons: float, df_telemetry: pd.DataFrame) -> dict:
    """
    Reconciles sight gauge fuel measurements against logged telemetry Fuel Flow Integral.
    Returns:
        dict: {
            "pre_flight_gallons": float,
            "post_flight_gallons": float,
            "measured_burn_sight_gauge": float,
            "telemetry_burn_integral": float,
            "totalizer_drift_gallons": float,
            "totalizer_drift_pct": float,
            "status": str ("EXCELLENT", "ACCEPTABLE", "CHECK_TOTALIZER")
        }
    """
    measured_burn = max(float(pre_flight_gallons) - float(post_flight_gallons), 0.0)

    telemetry_burn = 0.0
    if df_telemetry is not None and not df_telemetry.empty:
        if "Fuel Flow Integral" in df_telemetry.columns:
            series = pd.to_numeric(df_telemetry["Fuel Flow Integral"], errors="coerce").dropna()
            if not series.empty:
                telemetry_burn = float(series.max())
        elif "Total Fuel Flow (gal/hr)" in df_telemetry.columns and "Session Time" in df_telemetry.columns:
            ff = pd.to_numeric(df_telemetry["Total Fuel Flow (gal/hr)"], errors="coerce").fillna(0)
            t = pd.to_numeric(df_telemetry["Session Time"], errors="coerce").fillna(0)
            dt = t.diff().fillna(0).clip(lower=0, upper=10)
            telemetry_burn = float((ff * (dt / 3600.0)).sum())

    drift_gal = round(float(telemetry_burn - measured_burn), 2)
    drift_pct = round(float((drift_gal / measured_burn * 100.0) if measured_burn > 0 else 0.0), 1)

    if abs(drift_gal) <= 0.8 or abs(drift_pct) <= 5.0:
        status = "EXCELLENT"
    elif abs(drift_gal) <= 2.0 or abs(drift_pct) <= 10.0:
        status = "ACCEPTABLE"
    else:
        status = "CHECK_TOTALIZER"

    return {
        "pre_flight_gallons": round(float(pre_flight_gallons), 2),
        "post_flight_gallons": round(float(post_flight_gallons), 2),
        "measured_burn_sight_gauge": round(measured_burn, 2),
        "telemetry_burn_integral": round(telemetry_burn, 2),
        "totalizer_drift_gallons": drift_gal,
        "totalizer_drift_pct": drift_pct,
        "status": status
    }
