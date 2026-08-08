import numpy as np
import pandas as pd


def calculate_shock_cooling(df: pd.DataFrame) -> float:
    """
    Calculates the maximum CHT cooling rate in deg F / min across all cylinders.
    """
    cht_cols = [c for c in df.columns if c.startswith("CHT ") and ("(deg F)" in c or "(deg C)" in c)]
    if not cht_cols or "Session Time" not in df.columns:
        return 0.0

    try:
        dt = pd.to_numeric(df["Session Time"], errors="coerce").diff().fillna(0)
        dt = dt.replace(0, np.nan)

        max_cooling_rates = []
        for col in cht_cols:
            cht_vals = pd.to_numeric(df[col], errors="coerce").fillna(method="ffill")
            # dCHT / dt (deg F per sec) * 60 = deg F per min
            dcht_dt = (cht_vals.diff() / dt) * 60.0
            dcht_dt = dcht_dt.replace([np.inf, -np.inf], np.nan).fillna(0)
            # Cooling rate is negative derivative
            cooling_rate = -dcht_dt
            max_cooling_rates.append(cooling_rate.max())

        return round(float(max(max_cooling_rates)), 1) if max_cooling_rates else 0.0
    except Exception:
        return 0.0


def calculate_cht_spread(df: pd.DataFrame) -> float:
    """
    Calculates maximum CHT cylinder spread (max CHT - min CHT) across all cylinders.
    """
    cht_cols = [c for c in df.columns if c.startswith("CHT ") and "(deg F)" in c]
    if not cht_cols or len(cht_cols) < 2:
        return 0.0

    try:
        cht_data = df[cht_cols].apply(pd.to_numeric, errors="coerce")
        # Find row-wise spread (max - min)
        row_spreads = cht_data.max(axis=1) - cht_data.min(axis=1)
        # Filter for rows where engine is running (> 150 F)
        valid_mask = cht_data.min(axis=1) > 150
        valid_spreads = row_spreads[valid_mask]
        return round(float(valid_spreads.max()), 1) if not valid_spreads.empty else 0.0
    except Exception:
        return 0.0


def calculate_cht_thermal_durations(df: pd.DataFrame) -> dict:
    """
    Calculates duration (in minutes) spent with any CHT > 380 F and > 400 F.
    """
    cht_cols = [c for c in df.columns if c.startswith("CHT ") and "(deg F)" in c]
    if not cht_cols or "Session Time" not in df.columns:
        return {"above_380_min": 0.0, "above_400_min": 0.0}

    try:
        dt = pd.to_numeric(df["Session Time"], errors="coerce").diff().fillna(0)
        cht_max = df[cht_cols].apply(pd.to_numeric, errors="coerce").max(axis=1)

        sec_above_380 = dt[cht_max > 380].sum()
        sec_above_400 = dt[cht_max > 400].sum()

        return {
            "above_380_min": round(float(sec_above_380 / 60.0), 1),
            "above_400_min": round(float(sec_above_400 / 60.0), 1),
        }
    except Exception:
        return {"above_380_min": 0.0, "above_400_min": 0.0}


def calculate_oil_metrics(df: pd.DataFrame) -> dict:
    """
    Extracts oil temperature delta vs OAT and minimum oil pressure at operating temp.
    """
    res = {"oil_temp_delta": "N/A", "min_oil_press": "N/A"}
    try:
        if "OIL TEMPERATURE (deg F)" in df.columns and "OAT (deg F)" in df.columns:
            oil_temp = pd.to_numeric(df["OIL TEMPERATURE (deg F)"], errors="coerce")
            oat = pd.to_numeric(df["OAT (deg F)"], errors="coerce")
            delta = (oil_temp - oat).dropna()
            if not delta.empty:
                res["oil_temp_delta"] = round(float(delta.max()), 1)

        oil_press_cols = [c for c in df.columns if "oil" in c.lower() and "press" in c.lower()]
        if oil_press_cols:
            press = pd.to_numeric(df[oil_press_cols[0]], errors="coerce").dropna()
            # Only consider when engine is warmed up (RPM > 1000)
            if "RPM" in df.columns:
                rpm = pd.to_numeric(df["RPM"], errors="coerce")
                press = press[rpm > 1000]
            if not press.empty:
                res["min_oil_press"] = round(float(press.min()), 1)
    except Exception:
        pass
    return res


def calculate_flight_phases(df: pd.DataFrame) -> dict:
    """
    Segments flight into Taxi, Climb, Cruise, Descent, and Pattern/Landing durations (minutes).
    """
    phases = {
        "taxi_min": 0.0,
        "climb_min": 0.0,
        "cruise_min": 0.0,
        "descent_min": 0.0,
        "landing_phase_min": 0.0,
    }
    if "Session Time" not in df.columns:
        return phases

    try:
        dt = pd.to_numeric(df["Session Time"], errors="coerce").diff().fillna(0)
        gs = pd.to_numeric(df.get("Ground Speed (knots)", pd.Series(0, index=df.index)), errors="coerce").fillna(0)
        rpm = pd.to_numeric(df.get("RPM", pd.Series(0, index=df.index)), errors="coerce").fillna(0)

        # Vertical speed: use column or compute from altitude
        if "Vertical Speed (ft/min)" in df.columns:
            vs = pd.to_numeric(df["Vertical Speed (ft/min)"], errors="coerce").fillna(0)
        elif "GPS Altitude (feet)" in df.columns:
            alt = pd.to_numeric(df["GPS Altitude (feet)"], errors="coerce").fillna(0)
            dt_safe = dt.replace(0, np.nan)
            vs = (alt.diff() / dt_safe * 60.0).fillna(0)
        else:
            vs = pd.Series(0, index=df.index)

        # Classification masks
        taxi_mask = (rpm > 600) & (gs < 35)
        climb_mask = (gs >= 35) & (vs > 250)
        descent_mask = (gs >= 35) & (vs < -250)
        cruise_mask = (gs >= 45) & (vs.abs() <= 250)
        landing_mask = (gs < 55) & (gs >= 15) & (vs < -100)

        phases["taxi_min"] = round(float(dt[taxi_mask].sum() / 60.0), 1)
        phases["climb_min"] = round(float(dt[climb_mask].sum() / 60.0), 1)
        phases["cruise_min"] = round(float(dt[cruise_mask].sum() / 60.0), 1)
        phases["descent_min"] = round(float(dt[descent_mask].sum() / 60.0), 1)
        phases["landing_phase_min"] = round(float(dt[landing_mask].sum() / 60.0), 1)

    except Exception:
        pass

    return phases


def calculate_landings(df: pd.DataFrame) -> int:
    """
    Counts landings / touch-and-goes by detecting ground speed dips below 35 kts after flight.
    """
    if "Ground Speed (knots)" not in df.columns:
        return 1

    try:
        gs = pd.to_numeric(df["Ground Speed (knots)"], errors="coerce").fillna(0)
        # Flight mask: GS > 45 kts
        in_air = gs > 45
        # Landings detected when transitioning from in_air (True) to ground (GS < 30 kts)
        transitions = (in_air.astype(int).diff() == -1)
        landing_count = int(transitions.sum())
        return max(landing_count, 1)
    except Exception:
        return 1


def calculate_wind_aloft(df: pd.DataFrame) -> dict:
    """
    Calculates average cruise wind vector (speed in kts, direction, headwind/crosswind).
    Formula: Wind_vector = Ground_Velocity - Air_Velocity
    """
    res = {
        "wind_speed_kts": "N/A",
        "wind_dir_deg": "N/A",
        "headwind_kts": "N/A",
        "crosswind_kts": "N/A",
    }
    required = ["Ground Speed (knots)", "True Airspeed (knots)", "Magnetic Heading (deg)"]
    if not all(c in df.columns for c in required):
        return res

    try:
        gs = pd.to_numeric(df["Ground Speed (knots)"], errors="coerce").fillna(0)
        tas = pd.to_numeric(df["True Airspeed (knots)"], errors="coerce").fillna(0)
        heading = pd.to_numeric(df["Magnetic Heading (deg)"], errors="coerce").fillna(0)

        # Filter for cruise flight (TAS > 70 kts)
        mask = (tas > 70) & (gs > 40)
        if not mask.any():
            return res

        gs_c = gs[mask]
        tas_c = tas[mask]
        hdg_c = heading[mask]

        # Use Track if available, else fallback to Heading
        track_col = next((c for c in df.columns if "track" in c.lower() or "ground track" in c.lower()), None)
        if track_col:
            trk_c = pd.to_numeric(df[track_col], errors="coerce")[mask].fillna(hdg_c)
        else:
            trk_c = hdg_c

        # Convert to radians (0 deg = North)
        hdg_rad = np.radians(hdg_c)
        trk_rad = np.radians(trk_c)

        # Air velocity components (pointing direction of flight)
        v_air_x = tas_c * np.sin(hdg_rad)
        v_air_y = tas_c * np.cos(hdg_rad)

        # Ground velocity components
        v_gnd_x = gs_c * np.sin(trk_rad)
        v_gnd_y = gs_c * np.cos(trk_rad)

        # Wind vector (from direction wind is blowing FROM)
        # Wind = Ground_vector - Air_vector
        w_x = v_gnd_x - v_air_x
        w_y = v_gnd_y - v_air_y

        avg_wx = w_x.mean()
        avg_wy = w_y.mean()

        wind_speed = np.sqrt(avg_wx**2 + avg_wy**2)
        # Direction wind is coming FROM
        wind_dir = (np.degrees(np.arctan2(-avg_wx, -avg_wy))) % 360

        # Headwind & Crosswind components relative to heading
        avg_hdg_rad = np.radians(hdg_c.mean())
        # Headwind = TAS - GS approx or vector projection
        headwind = tas_c.mean() - gs_c.mean()
        crosswind = np.abs(wind_speed * np.sin(np.radians(wind_dir - np.degrees(avg_hdg_rad))))

        res["wind_speed_kts"] = round(float(wind_speed), 1)
        res["wind_dir_deg"] = int(round(wind_dir))
        res["headwind_kts"] = round(float(headwind), 1)
        res["crosswind_kts"] = round(float(crosswind), 1)

    except Exception as e:
        print(f"Wind calculation notice: {e}")

    return res


def calculate_g_load_and_bank(df: pd.DataFrame) -> dict:
    """
    Extracts peak positive/negative vertical G acceleration and maximum bank angle.
    """
    res = {"peak_pos_g": "N/A", "peak_neg_g": "N/A", "max_bank_deg": "N/A"}

    # G-Load column candidates (Garmin / Dynon)
    g_cols = [c for c in df.columns if "accel" in c.lower() or "g_load" in c.lower() or "norm accel" in c.lower() or "vert accel" in c.lower()]
    if g_cols:
        try:
            g_series = pd.to_numeric(df[g_cols[0]], errors="coerce").dropna()
            if not g_series.empty:
                res["peak_pos_g"] = round(float(g_series.max()), 2)
                res["peak_neg_g"] = round(float(g_series.min()), 2)
        except Exception:
            pass

    if "Roll (deg)" in df.columns:
        try:
            roll_series = pd.to_numeric(df["Roll (deg)"], errors="coerce").abs().dropna()
            if not roll_series.empty:
                res["max_bank_deg"] = round(float(roll_series.max()), 1)
        except Exception:
            pass

    return res


def calculate_climb_gradient(df: pd.DataFrame) -> float:
    """
    Calculates average climb gradient in feet per nautical mile (ft/NM).
    """
    if "GPS Altitude (feet)" not in df.columns or "Ground Speed (knots)" not in df.columns or "Session Time" not in df.columns:
        return 0.0

    try:
        alt = pd.to_numeric(df["GPS Altitude (feet)"], errors="coerce").fillna(0)
        gs = pd.to_numeric(df["Ground Speed (knots)"], errors="coerce").fillna(0)
        dt = pd.to_numeric(df["Session Time"], errors="coerce").diff().fillna(0)

        # Filter for active climb (VS > 300 fpm, GS > 40 kts)
        dt_safe = dt.replace(0, np.nan)
        vs_fpm = (alt.diff() / dt_safe) * 60.0

        climb_mask = (vs_fpm > 300) & (gs > 40)
        if not climb_mask.any():
            return 0.0

        # Gradient (ft/NM) = (Vertical Speed ft/min) / (Ground Speed NM/min) = (vs_fpm) / (gs / 60)
        grad_series = vs_fpm[climb_mask] / (gs[climb_mask] / 60.0)
        grad_series = grad_series.replace([np.inf, -np.inf], np.nan).dropna()
        return round(float(grad_series.mean()), 1) if not grad_series.empty else 0.0
    except Exception:
        return 0.0


def extract_comprehensive_flight_stats(df: pd.DataFrame) -> dict:
    """
    Combines all advanced analytics into a structured dictionary.
    """
    stats = {}
    stats["max_shock_cooling"] = calculate_shock_cooling(df)
    stats["cht_spread"] = calculate_cht_spread(df)

    thermal = calculate_cht_thermal_durations(df)
    stats.update(thermal)

    oil = calculate_oil_metrics(df)
    stats.update(oil)

    phases = calculate_flight_phases(df)
    stats.update(phases)

    stats["landing_count"] = calculate_landings(df)

    wind = calculate_wind_aloft(df)
    stats.update(wind)

    g_bank = calculate_g_load_and_bank(df)
    stats.update(g_bank)

    stats["climb_gradient_ft_nm"] = calculate_climb_gradient(df)

    return stats
