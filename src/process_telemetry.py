import numpy as np
import pandas as pd


def process_flights(df):
    """
    Processes raw aircraft telemetry DataFrame:
    - Normalizes numeric fields & temperature units (deg C -> deg F).
    - Identifies flight segments by Session Time resets.
    - Computes fuel integration (gallons used), distance integration (miles), MPG, and temperature deltas.
    - Filters/identifies engine runs based on RPM and CHT thresholds.
    - Assigns localized Flight IDs.
    """
    if df is None or df.empty:
        return df

    df = df.copy()

    # --- 1. CLEANING & TYPE NORMALIZATION ---
    # Convert all temperature columns from deg C to deg F
    temp_c_cols = [col for col in df.columns if "(deg C)" in col]
    for col in temp_c_cols:
        try:
            new_name = col.replace("(deg C)", "(deg F)")
            numeric_vals = pd.to_numeric(df[col], errors="coerce")
            df[new_name] = numeric_vals * 9.0 / 5.0 + 32.0
        except Exception as e:
            print(f"Warning: Temperature conversion failed for column '{col}': {e}")

    # Identify and standardize core numeric columns
    core_numeric_cols = [
        "Session Time",
        "System Time",
        "RPM L",
        "RPM R",
        "RPM",
        "CHT 1 (deg F)",
        "CHT 2 (deg F)",
        "CHT 3 (deg F)",
        "CHT 4 (deg F)",
        "OAT (deg F)",
        "OIL TEMPERATURE (deg F)",
        "Fuel Flow 1 (gal/hr)",
        "Total Fuel Flow (gal/hr)",
        "Ground Speed (knots)",
        "Transponder Status",
    ]

    for col in core_numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Filter invalid/blank rows
    if "System Time" in df.columns:
        df = df[df["System Time"].notna() & (df["System Time"] != "")]
    if "GPS Date & Time" in df.columns:
        df = df[df["GPS Date & Time"].notna() & (df["GPS Date & Time"] != "")]

    if df.empty:
        return df

    # --- 2. IDENTIFY FLIGHT SEGMENTS ---
    if "Session Time" in df.columns:
        df["_orig_flight_num"] = (df["Session Time"].diff() < 0).cumsum()
    else:
        df["_orig_flight_num"] = 0

    # RPM calculation
    rpm_l = df["RPM L"] if "RPM L" in df.columns else 0
    rpm_r = df["RPM R"] if "RPM R" in df.columns else 0
    if "RPM" not in df.columns or (df["RPM"] == 0).all():
        df["RPM"] = (rpm_l + rpm_r) / 2.0

    # CHT Average & Deltas
    cht_cols = [
        col
        for col in ["CHT 1 (deg F)", "CHT 2 (deg F)", "CHT 3 (deg F)", "CHT 4 (deg F)"]
        if col in df.columns
    ]
    if cht_cols:
        df["AVG_CHT"] = df[cht_cols].mean(axis=1)
    else:
        df["AVG_CHT"] = 0.0

    oat = df["OAT (deg F)"] if "OAT (deg F)" in df.columns else 0.0
    oil_temp = (
        df["OIL TEMPERATURE (deg F)"]
        if "OIL TEMPERATURE (deg F)" in df.columns
        else 0.0
    )

    df["CHT_Delta_T"] = df["AVG_CHT"] - oat
    df["OIL_Delta_T"] = oil_temp - oat

    # --- 3. FUEL FLOW INTEGRATION ---
    if (
        "Total Fuel Flow (gal/hr)" not in df.columns
        and "Fuel Flow 1 (gal/hr)" in df.columns
    ):
        df["Total Fuel Flow (gal/hr)"] = df["Fuel Flow 1 (gal/hr)"]

    if "Total Fuel Flow (gal/hr)" in df.columns and "Session Time" in df.columns:
        df = df.sort_values(["_orig_flight_num", "Session Time"])
        dt = df.groupby("_orig_flight_num")["Session Time"].diff().fillna(0)
        flow_gps = df["Total Fuel Flow (gal/hr)"] / 3600.0
        flow_prev = flow_gps.groupby(df["_orig_flight_num"]).shift(1).fillna(flow_gps)
        avg_flow = 0.5 * (flow_gps + flow_prev)
        increment = avg_flow * dt
        df["Fuel Flow Integral"] = increment.groupby(df["_orig_flight_num"]).cumsum()

    # --- 4. DISTANCE INTEGRATION ---
    if "Ground Speed (knots)" in df.columns and "Session Time" in df.columns:
        dt = df.groupby("_orig_flight_num")["Session Time"].diff().fillna(0)
        speed_fps = df["Ground Speed (knots)"] * 1.15 * 5280 / 3600
        speed_prev = (
            speed_fps.groupby(df["_orig_flight_num"]).shift(1).fillna(speed_fps)
        )
        avg_speed = 0.5 * (speed_fps + speed_prev)
        increment = avg_speed * dt
        df["Distance Traveled"] = increment.groupby(df["_orig_flight_num"]).cumsum()

    # MPG calculation
    if (
        "Ground Speed (knots)" in df.columns
        and "Total Fuel Flow (gal/hr)" in df.columns
    ):
        df["MPG"] = df["Ground Speed (knots)"] / df["Total Fuel Flow (gal/hr)"].replace(
            0, np.nan
        )
        df["MPG"] = df["MPG"].replace([float("inf"), -float("inf")], 0).fillna(0)
    else:
        df["MPG"] = 0.0

    # --- 5. ENGINE RUN EVALUATION & FLIGHT ID ASSIGNMENT ---
    flight_max_rpm = df.groupby("_orig_flight_num")["RPM"].max()
    if cht_cols:
        flight_max_cht = df.groupby("_orig_flight_num")[cht_cols].max().max(axis=1)
    else:
        flight_max_cht = pd.Series(0, index=df["_orig_flight_num"].unique())

    df["Max CHT"] = df["_orig_flight_num"].map(flight_max_cht)

    flights_with_engine = (flight_max_rpm > 0) & (flight_max_cht > 125)
    flight_start_gps = df.groupby("_orig_flight_num")["GPS Date & Time"].first()

    df["Engine Run"] = df["_orig_flight_num"].map(flights_with_engine)

    engine_flight_ids = [
        fid
        for fid in df["_orig_flight_num"].unique()
        if flights_with_engine.get(fid, False)
    ]
    flightid_map = {
        fid: f"{flight_start_gps.get(fid, '')}" for fid in engine_flight_ids
    }

    raw_flight_id = df["_orig_flight_num"].map(lambda x: flightid_map.get(x, None))

    # Safe Datetime parsing (handles both tz-naive and tz-aware strings)
    dt_series = pd.to_datetime(raw_flight_id, errors="coerce")
    if dt_series.dt.tz is None:
        dt_series = dt_series.dt.tz_localize("UTC").dt.tz_convert("America/Los_Angeles")
    else:
        dt_series = dt_series.dt.tz_convert("America/Los_Angeles")

    df["Flight ID"] = dt_series

    if "_orig_flight_num" in df.columns:
        df.drop(columns=["_orig_flight_num"], inplace=True)

    # Safe NaN filling by dtype
    num_cols = df.select_dtypes(include=[np.number]).columns
    obj_cols = df.select_dtypes(include=["object", "string", "str"]).columns

    if len(num_cols) > 0:
        df[num_cols] = df[num_cols].fillna(0)
    if len(obj_cols) > 0:
        df[obj_cols] = df[obj_cols].fillna("")

    return df.copy()


def calculate_flight_summary(flight_df):
    """
    Extracts summary metrics (total duration, air time, distance, gallons, max CHT/RPM, avg speed, avg MPG)
    from a single flight segment DataFrame.
    """
    if flight_df is None or flight_df.empty:
        return {}

    total_duration = (
        flight_df["Session Time"].iloc[-1] - flight_df["Session Time"].iloc[0]
        if "Session Time" in flight_df.columns
        else 0
    )

    air_time = 0
    if (
        "Transponder Status" in flight_df.columns
        and "Session Time" in flight_df.columns
    ):
        active_air = flight_df[flight_df["Transponder Status"] == 3]["Session Time"]
        if not active_air.empty:
            air_time = active_air.iloc[-1] - active_air.iloc[0]

    distance_traveled = (
        flight_df["Distance Traveled"].iloc[-1] / 5280.0
        if "Distance Traveled" in flight_df.columns
        else 0
    )
    gallons_used = (
        flight_df["Fuel Flow Integral"].iloc[-1]
        if "Fuel Flow Integral" in flight_df.columns
        else 0
    )
    max_cht = flight_df["Max CHT"].max() if "Max CHT" in flight_df.columns else 0
    max_rpm = flight_df["RPM"].max() if "RPM" in flight_df.columns else 0
    avg_mpg = flight_df["MPG"].mean() if "MPG" in flight_df.columns else 0

    avg_speed = 0
    if (
        "Transponder Status" in flight_df.columns
        and "Ground Speed (knots)" in flight_df.columns
    ):
        active_speed = flight_df[flight_df["Transponder Status"] == 3][
            "Ground Speed (knots)"
        ]
        if not active_speed.empty:
            avg_speed = active_speed.mean() * 1.15

    return {
        "total_duration": total_duration,
        "air_time": air_time,
        "distance_traveled": distance_traveled,
        "gallons_used": gallons_used,
        "max_cht": max_cht,
        "max_rpm": max_rpm,
        "avg_mpg": avg_mpg,
        "avg_speed": avg_speed,
    }
