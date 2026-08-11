import numpy as np
import pandas as pd
from scipy.optimize import minimize


def calculate_density_ratio(pressure_alt_ft, oat_c):
    """Calculates the density ratio (sigma) based on standard atmosphere physics."""
    delta = (1 - 6.87559e-6 * pressure_alt_ft) ** 5.25588
    t_abs = oat_c + 273.15
    t0_abs = 288.15
    theta = t_abs / t0_abs
    sigma = delta / theta
    return sigma


def wind_triangle_residuals(params, df):
    """
    Objective function to minimize.
    params: [cas_correction, hdg_correction, wind_speed, wind_dir]
    """
    cas_corr, hdg_corr, w_spd, w_dir = params

    # Calculate CAS and TAS
    cas = df["ias"] + cas_corr
    tas = cas / np.sqrt(df["sigma"])

    # Calculate True Heading (in radians)
    true_hdg_rad = np.radians(df["hdg"] + hdg_corr)

    # Aircraft velocity vector components (relative to airmass)
    v_ax = tas * np.sin(true_hdg_rad)
    v_ay = tas * np.cos(true_hdg_rad)

    # Wind vector components
    w_dir_rad = np.radians(w_dir)
    v_wx = -w_spd * np.sin(w_dir_rad)
    v_wy = -w_spd * np.cos(w_dir_rad)

    # Expected Ground velocity components
    v_gx_expected = v_ax + v_wx
    v_gy_expected = v_ay + v_wy

    # Measured GPS Ground velocity components
    trk_rad = np.radians(df["gps_trk"])
    v_gx_meas = df["gps_gs"] * np.sin(trk_rad)
    v_gy_meas = df["gps_gs"] * np.cos(trk_rad)

    # Calculate sum of squared errors
    error_x = v_gx_expected - v_gx_meas
    error_y = v_gy_expected - v_gy_meas

    return np.sum(error_x**2 + error_y**2)


def load_flight_log(filepath):
    """
    Loads the avionics CSV file and maps the exact columns to internal variable names.
    """
    print(f"Loading data from {filepath}...")
    df = pd.read_csv(filepath)

    df = df.rename(
        columns={
            "Session Time": "session_time",
            "Indicated Airspeed (knots)": "ias",
            "Pressure Altitude (ft)": "press_alt",
            "Magnetic Heading (deg)": "hdg",
            "Ground Speed (knots)": "gps_gs",
            "Ground Track (deg)": "gps_trk",
            "OAT (deg C)": "oat",
            "Barometer Setting (inHg)": "baro",
        }
    )

    essential_columns = [
        "session_time",
        "ias",
        "press_alt",
        "hdg",
        "gps_gs",
        "gps_trk",
        "oat",
        "baro",
    ]
    df = df[essential_columns].copy()

    df = df.dropna()
    df = df[df["ias"] > 40.0]

    df = df.reset_index(drop=True)

    print(f"Loaded and cleaned {len(df)} airborne data points.")
    return df


def analyze_flight_data(df, start_time=None, end_time=None, show_plot=False):
    """
    Processes the time-series dataframe and outputs the calibration parameters.
    Slices the data based on Session Time rather than row index.
    """
    if start_time is not None and end_time is not None:
        # Filter rows where session_time is between start_time and end_time
        maneuver_df = df[
            (df["session_time"] >= start_time) & (df["session_time"] <= end_time)
        ].copy()
    else:
        maneuver_df = df.copy()
        start_time = maneuver_df["session_time"].iloc[0]
        end_time = maneuver_df["session_time"].iloc[-1]

    if len(maneuver_df) < 10:
        raise ValueError(
            f"Not enough data points between {start_time}s and {end_time}s. Minimum 10 points required."
        )

    # Robust OAT handling (°C vs °F)
    if "oat_c" in maneuver_df.columns:
        oat_c = pd.to_numeric(maneuver_df["oat_c"], errors="coerce")
    elif "oat" in maneuver_df.columns:
        oat_vals = pd.to_numeric(maneuver_df["oat"], errors="coerce")
        # If mean OAT > 45, assume values are in °F and convert to °C
        if oat_vals.dropna().mean() > 45.0:
            oat_c = (oat_vals - 32.0) * 5.0 / 9.0
        else:
            oat_c = oat_vals
    else:
        oat_c = pd.Series([15.0] * len(maneuver_df), index=maneuver_df.index)

    maneuver_df["sigma"] = calculate_density_ratio(
        maneuver_df["press_alt"], oat_c
    )

    # Check for native avionics wind speed and direction in columns
    native_w_spd = float(maneuver_df["Wind Speed (knots)"].mean()) if "Wind Speed (knots)" in maneuver_df.columns and not maneuver_df["Wind Speed (knots)"].dropna().empty else 0.0
    native_w_dir = float(maneuver_df["Wind Direction (deg)"].mean()) if "Wind Direction (deg)" in maneuver_df.columns and not maneuver_df["Wind Direction (deg)"].dropna().empty else 0.0

    init_w_spd = native_w_spd if native_w_spd > 0 else 10.0
    init_w_dir = native_w_dir if native_w_dir > 0 else 180.0

    initial_guess = [0.0, 0.0, init_w_spd, init_w_dir]
    bounds = ((-20, 20), (-15, 15), (0, 150), (0, 360))

    result = minimize(
        wind_triangle_residuals,
        initial_guess,
        args=(maneuver_df,),
        bounds=bounds,
        method="L-BFGS-B",
    )

    if not result.success:
        print("Optimization failed:", result.message)
        return None

    cas_corr, hdg_corr, w_spd, w_dir = result.x
    w_dir = w_dir % 360

    # If optimized wind speed is ~0 and native wind is available, use native wind values
    if w_spd < 0.5 and native_w_spd > 0.5:
        w_spd = native_w_spd
        w_dir = native_w_dir

    # Calculate heading span in maneuver segment
    hdg_diffs = np.diff(np.sort(maneuver_df["hdg"].values % 360))
    max_gap = np.max(np.append(hdg_diffs, (360 + maneuver_df["hdg"].min() % 360) - (maneuver_df["hdg"].max() % 360))) if len(hdg_diffs) > 0 else 360
    heading_span = max(0, min(360, round(360 - max_gap, 1)))

    # Calculate corrected TAS
    cas = maneuver_df["ias"] + cas_corr
    tas_array = cas / np.sqrt(maneuver_df["sigma"])

    # Calculate UNCORRECTED TAS
    uncorrected_tas_array = maneuver_df["ias"] / np.sqrt(maneuver_df["sigma"])

    calibrated_hdg_array = (maneuver_df["hdg"] + hdg_corr) % 360

    engine_settings = extract_engine_settings(maneuver_df)

    results = {
        "calibrated_airspeed_correction_kts": round(cas_corr, 2),
        "calibrated_heading_correction_deg": round(hdg_corr, 2),
        "airspeed_error_kts": round(-cas_corr, 2),
        "wind_direction_deg": round(w_dir, 1),
        "wind_speed_kts": round(w_spd, 1),
        "native_wind_direction_deg": round(native_w_dir, 1),
        "native_wind_speed_kts": round(native_w_spd, 1),
        "heading_span_deg": heading_span,
        "uncorrected_average_true_airspeed_kts": round(
            np.mean(uncorrected_tas_array), 2
        ),
        "corrected_average_true_airspeed_kts": round(np.mean(tas_array), 2),
        "ts_true_airspeed": tas_array.tolist() if hasattr(tas_array, "tolist") else list(tas_array),
        "ts_calibrated_heading": calibrated_hdg_array.tolist() if hasattr(calibrated_hdg_array, "tolist") else list(calibrated_hdg_array),
        "analyzed_data_points": len(maneuver_df),
        "engine_settings": engine_settings,
    }

    return results


def extract_engine_settings(maneuver_df):
    """
    Extracts mean engine parameters during the maneuver segment:
    Manifold Pressure, RPM, Fuel Flow, and Percent Power.
    """
    def get_avg(possible_cols):
        for col in possible_cols:
            if col in maneuver_df.columns:
                series = pd.to_numeric(maneuver_df[col], errors="coerce").dropna()
                if not series.empty:
                    val = float(series.mean())
                    if not (np.isnan(val) or np.isinf(val)):
                        return round(val, 1)
        return None

    map_val = get_avg(["Manifold Pressure (inHg)", "map_inhg", "MAP", "Manifold Pressure"])
    rpm_val = get_avg(["RPM", "rpm", "RPM L", "RPM R"])
    ff_val = get_avg(["Total Fuel Flow (gal/hr)", "fuel_flow", "Fuel Flow 1 (gal/hr)", "Fuel Flow"])
    power_val = get_avg(["Percent Power", "percent_power", "Power (%)", "POWER"])

    return {
        "manifold_pressure_inhg": map_val,
        "rpm": rpm_val,
        "fuel_flow_gph": ff_val,
        "percent_power": power_val,
    }


# ==========================================
# Example Usage
# ==========================================
if __name__ == "__main__":
    # Point this to your actual uploaded CSV file
    csv_file_path = input("Flight Data File: ")

    # Load and map the data
    flight_log = load_flight_log(csv_file_path)

    # Define the session times (in seconds) for the maneuver segment
    # Check your flight log to find the exact Session Time for your maneuver
    start_maneuver_time = 1530.0  # seconds
    end_maneuver_time = 1828.0  # seconds

    print(
        f"\nAnalyzing flight segment from Session Time {start_maneuver_time}s to {end_maneuver_time}s...\n"
    )

    # Perform Analysis
    output = analyze_flight_data(
        flight_log,
        start_time=start_maneuver_time,
        end_time=end_maneuver_time,
        show_plot=True,
    )

    if output:
        print("--- Calibration Results ---")
        print(f"Data Points Analyzed:  {output['analyzed_data_points']}")
        print(
            f"CAS Correction:        {output['calibrated_airspeed_correction_kts']} kts"
        )
        print(f"Airspeed Error:        {output['airspeed_error_kts']} kts")
        print(
            f"HDG Correction:        {output['calibrated_heading_correction_deg']} deg"
        )
        print(f"Wind Direction:        {output['wind_direction_deg']} deg")
        print(f"Wind Speed:            {output['wind_speed_kts']} kts")
        print(
            f"Uncorr. Avg TAS:       {output['uncorrected_average_true_airspeed_kts']} kts"
        )
        print(
            f"Corrected Avg TAS:     {output['corrected_average_true_airspeed_kts']} kts"
        )
