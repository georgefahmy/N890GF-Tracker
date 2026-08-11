import numpy as np
import pandas as pd
from scipy.optimize import minimize


def calculate_heading_span(hdg_series):
    """
    Calculates total angular heading coverage (span) in degrees [0, 360]
    by finding the maximum angular gap between unique modulo-360 headings.
    """
    valid_hdgs = pd.to_numeric(hdg_series, errors="coerce").dropna().values
    if len(valid_hdgs) < 2:
        return 0.0

    hdgs = np.sort(np.unique(np.mod(valid_hdgs, 360)))
    if len(hdgs) < 2:
        return 0.0

    gaps = np.diff(hdgs)
    wrap_gap = (360.0 + hdgs[0]) - hdgs[-1]
    max_gap = np.max(np.append(gaps, wrap_gap))
    return max(0.0, min(360.0, round(360.0 - max_gap, 1)))


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

    # Calculate True Heading (incorporating Magnetic Variation + Compass Correction)
    mag_var = df["mag_var"] if "mag_var" in df.columns else 0.0
    true_hdg_rad = np.radians(df["hdg"] + mag_var + hdg_corr)

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

    # Measured GPS Ground velocity components (GPS track is True North)
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
            "Mag Var (deg)": "mag_var",
            "Mag Variation (deg)": "mag_var",
            "Magnetic Variation (deg)": "mag_var",
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
    ] + ([c for c in ["mag_var"] if c in df.columns])
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
    if "oat_c" in maneuver_df.columns and not maneuver_df["oat_c"].dropna().empty:
        oat_c = pd.to_numeric(maneuver_df["oat_c"], errors="coerce")
    elif "oat" in maneuver_df.columns and not maneuver_df["oat"].dropna().empty:
        oat_vals = pd.to_numeric(maneuver_df["oat"], errors="coerce")
        if oat_vals.dropna().mean() > 45.0:
            oat_c = (oat_vals - 32.0) * 5.0 / 9.0
        else:
            oat_c = oat_vals
    elif "OAT (deg C)" in maneuver_df.columns:
        oat_c = pd.to_numeric(maneuver_df["OAT (deg C)"], errors="coerce")
    elif "OAT (deg F)" in maneuver_df.columns:
        oat_vals = pd.to_numeric(maneuver_df["OAT (deg F)"], errors="coerce")
        oat_c = (oat_vals - 32.0) * 5.0 / 9.0
    else:
        oat_c = pd.Series([15.0] * len(maneuver_df), index=maneuver_df.index)

    oat_c = oat_c.fillna(15.0)

    maneuver_df["sigma"] = calculate_density_ratio(
        maneuver_df["press_alt"], oat_c
    )

    # Extract Magnetic Variation (deg) if present in columns
    mag_var = 0.0
    for col in ["mag_var", "Mag Var (deg)", "Mag Variation (deg)", "Magnetic Variation (deg)", "MagVar (deg)", "MAGVAR", "Mag Var", "MagVar"]:
        if col in maneuver_df.columns:
            s = pd.to_numeric(maneuver_df[col], errors="coerce").dropna()
            if not s.empty:
                mag_var = float(s.mean())
                break

    maneuver_df["mag_var"] = mag_var

    # Check for native avionics wind speed and direction in columns
    native_w_spd = float(maneuver_df["Wind Speed (knots)"].mean()) if "Wind Speed (knots)" in maneuver_df.columns and not maneuver_df["Wind Speed (knots)"].dropna().empty else 0.0
    native_w_dir = float(maneuver_df["Wind Direction (deg)"].mean()) if "Wind Direction (deg)" in maneuver_df.columns and not maneuver_df["Wind Direction (deg)"].dropna().empty else 0.0

    # Calculate heading span in maneuver segment
    heading_span = calculate_heading_span(maneuver_df["hdg"])

    if heading_span >= 180.0 or native_w_spd < 0.5:
        # Full 4-parameter optimization (cas_corr, hdg_corr, wind_speed, wind_dir)
        init_w_spd = native_w_spd if native_w_spd > 0 else 10.0
        init_w_dir = native_w_dir if native_w_dir > 0 else 180.0
        initial_guess = [0.0, 0.0, init_w_spd, init_w_dir]
        bounds = ((-20, 20), (-10, 10), (0, 150), (0, 360))

        result = minimize(
            wind_triangle_residuals,
            initial_guess,
            args=(maneuver_df,),
            bounds=bounds,
            method="L-BFGS-B",
        )
        if result.success:
            cas_corr, hdg_corr, w_spd, w_dir = result.x
            w_dir = w_dir % 360
        else:
            cas_corr, hdg_corr, w_spd, w_dir = 0.0, 0.0, native_w_spd, native_w_dir
    else:
        # Low heading span: 2-parameter optimization fixing wind to native avionics wind
        def fixed_wind_obj(params, df, f_spd, f_dir):
            return wind_triangle_residuals([params[0], params[1], f_spd, f_dir], df)

        res_2p = minimize(
            fixed_wind_obj,
            [0.0, 0.0],
            args=(maneuver_df, native_w_spd, native_w_dir),
            bounds=((-20, 20), (-10, 10)),
            method="L-BFGS-B",
        )
        if res_2p.success:
            cas_corr, hdg_corr = res_2p.x
            w_spd, w_dir = native_w_spd, native_w_dir
        else:
            cas_corr, hdg_corr, w_spd, w_dir = 0.0, 0.0, native_w_spd, native_w_dir

    # Calculate corrected TAS
    cas = maneuver_df["ias"] + cas_corr
    tas_array = cas / np.sqrt(maneuver_df["sigma"])

    # Calculate UNCORRECTED TAS
    uncorrected_tas_array = maneuver_df["ias"] / np.sqrt(maneuver_df["sigma"])

    calibrated_hdg_array = (maneuver_df["hdg"] + mag_var + hdg_corr) % 360

    engine_settings = extract_engine_settings(maneuver_df)

    results = {
        "calibrated_airspeed_correction_kts": round(cas_corr, 2),
        "calibrated_heading_correction_deg": round(hdg_corr, 2),
        "magnetic_variation_deg": round(mag_var, 2),
        "airspeed_error_kts": round(cas_corr, 2),
        "wind_direction_deg": round(w_dir, 1),
        "wind_speed_kts": round(w_spd, 1),
        "native_wind_direction_deg": round(native_w_dir, 1),
        "native_wind_speed_kts": round(native_w_spd, 1),
        "heading_span_deg": heading_span,
        "average_indicated_airspeed_kts": round(float(np.mean(maneuver_df["ias"])), 2),
        "average_calibrated_airspeed_kts": round(float(np.mean(cas)), 2),
        "uncorrected_average_true_airspeed_kts": round(
            float(np.mean(uncorrected_tas_array)), 2
        ),
        "corrected_average_true_airspeed_kts": round(float(np.mean(tas_array)), 2),
        "ts_true_airspeed": tas_array.tolist() if hasattr(tas_array, "tolist") else list(tas_array),
        "ts_calibrated_heading": calibrated_hdg_array.tolist() if hasattr(calibrated_hdg_array, "tolist") else list(calibrated_hdg_array),
        "analyzed_data_points": len(maneuver_df),
        "engine_settings": engine_settings,
    }

    return results


def extract_engine_settings(maneuver_df):
    """
    Extracts mean engine parameters specifically averaged over the selected maneuver segment
    (between start_time and end_time): Manifold Pressure, RPM, Fuel Flow, and Percent Power.
    """
    def get_avg(possible_cols):
        for col in possible_cols:
            if col in maneuver_df.columns:
                series = pd.to_numeric(maneuver_df[col], errors="coerce").dropna()
                valid = series[series > 0]
                if not valid.empty:
                    val = float(valid.mean())
                    if not (np.isnan(val) or np.isinf(val)):
                        return round(val, 1)
        return None

    map_val = get_avg([
        "Manifold Pressure (inHg)", "MAP (inHg)", "map_inhg", "MAP",
        "Manifold Pressure", "Engine MAP", "MAP 1"
    ])
    rpm_val = get_avg([
        "RPM", "rpm", "RPM L", "RPM R", "Engine Speed", "RPM 1",
        "Propeller RPM", "TACH"
    ])
    ff_val = get_avg([
        "Total Fuel Flow (gal/hr)", "Fuel Flow (gal/hr)", "Fuel Flow 1 (gal/hr)",
        "fuel_flow", "Fuel Flow", "FF (gal/hr)", "FF"
    ])
    power_val = get_avg([
        "Percent Power", "percent_power", "Power (%)", "POWER",
        "Engine Power (%)", "Power"
    ])

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
