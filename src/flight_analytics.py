import numpy as np
import pandas as pd


def calculate_shock_cooling(df: pd.DataFrame) -> dict:
    """
    Calculates the maximum CHT cooling rate in deg F / min across all cylinders,
    returning peak rate, cylinder name, start/end timestamps, and CHT drop.
    """
    res = {
        "max_shock_cooling": 0.0,
        "shock_cooling_cyl": "N/A",
        "shock_cooling_t_start": None,
        "shock_cooling_t_end": None,
        "shock_cooling_cht_drop": 0.0,
    }

    cht_cols = [c for c in df.columns if c.startswith("CHT ") and "(deg F)" in c]
    needs_c_conversion = False
    if not cht_cols:
        cht_cols = [c for c in df.columns if c.startswith("CHT ") and "(deg C)" in c]
        needs_c_conversion = True

    if not cht_cols or "Session Time" not in df.columns:
        return res

    try:
        time_series = pd.to_numeric(df["Session Time"], errors="coerce")
        gs = pd.to_numeric(df.get("Ground Speed (knots)", pd.Series(0, index=df.index)), errors="coerce").fillna(0)
        rpm = pd.to_numeric(df.get("RPM", pd.Series(0, index=df.index)), errors="coerce").fillna(0)

        # Active flight mask: engine running (> 1000 RPM) or flying (> 35 kts)
        flight_mask = (gs > 35)
        if "RPM" in df.columns:
            flight_mask |= (rpm > 1000)

        # Estimate sampling period
        dt_1s = time_series.diff().median()
        period_window = int(round(15.0 / dt_1s)) if (pd.notna(dt_1s) and dt_1s > 0) else 15
        period_window = max(1, period_window)

        dt_window = time_series.diff(periods=period_window)

        best_rate = 0.0
        best_cyl = "N/A"
        best_t_start = None
        best_t_end = None
        best_drop = 0.0

        for col in cht_cols:
            cht_vals = pd.to_numeric(df[col], errors="coerce")
            if needs_c_conversion:
                cht_vals = cht_vals * 9.0 / 5.0 + 32.0

            valid_mask = flight_mask & (cht_vals > 200) & (dt_window > 0) & (dt_window < 120)

            # dCHT / dt over period window (deg F per min)
            dcht = cht_vals.diff(periods=period_window)
            cooling_rate = (-dcht / dt_window) * 60.0
            valid_rates = cooling_rate[valid_mask].replace([np.inf, -np.inf], np.nan).dropna()

            if not valid_rates.empty:
                max_idx = valid_rates.idxmax()
                rate_val = valid_rates.loc[max_idx]
                if rate_val > best_rate:
                    best_rate = rate_val
                    best_cyl = col.split(" (")[0]
                    best_t_start = float(time_series.iloc[max_idx - period_window])
                    best_t_end = float(time_series.iloc[max_idx])
                    best_drop = float(cht_vals.iloc[max_idx - period_window] - cht_vals.iloc[max_idx])

        if best_rate > 0:
            res["max_shock_cooling"] = round(float(best_rate), 1)
            res["shock_cooling_cyl"] = best_cyl
            res["shock_cooling_t_start"] = round(best_t_start, 1) if best_t_start is not None else None
            res["shock_cooling_t_end"] = round(best_t_end, 1) if best_t_end is not None else None
            res["shock_cooling_cht_drop"] = round(best_drop, 1)

    except Exception as e:
        print(f"Shock cooling detail extraction notice: {e}")

    return res


def calculate_cht_spread(df: pd.DataFrame) -> float:
    """
    Calculates maximum CHT cylinder spread (max CHT - min CHT) across all cylinders.
    """
    cht_cols = [c for c in df.columns if c.startswith("CHT ") and "(deg F)" in c]
    if not cht_cols or len(cht_cols) < 2:
        return 0.0

    try:
        cht_data = df[cht_cols].apply(pd.to_numeric, errors="coerce")
        row_spreads = cht_data.max(axis=1) - cht_data.min(axis=1)
        valid_mask = cht_data.min(axis=1) > 150
        valid_spreads = row_spreads[valid_mask]
        return round(float(valid_spreads.max()), 1) if not valid_spreads.empty else 0.0
    except Exception:
        return 0.0


def calculate_cht_thermal_durations(df: pd.DataFrame) -> dict:
    """
    Calculates duration (in minutes) spent with any CHT > 410 F (caution threshold in SIGNAL_BANDS)
    and > 430 F (redline threshold in SIGNAL_BANDS).
    """
    cht_cols = [c for c in df.columns if c.startswith("CHT ") and "(deg F)" in c]
    if not cht_cols or "Session Time" not in df.columns:
        return {"above_380_min": 0.0, "above_410_min": 0.0, "above_430_min": 0.0}

    try:
        dt = pd.to_numeric(df["Session Time"], errors="coerce").diff().fillna(0)
        cht_max = df[cht_cols].apply(pd.to_numeric, errors="coerce").max(axis=1)

        sec_above_380 = dt[cht_max > 380].sum()
        sec_above_410 = dt[cht_max > 410].sum()
        sec_above_430 = dt[cht_max > 430].sum()

        return {
            "above_380_min": round(float(sec_above_380 / 60.0), 1),
            "above_410_min": round(float(sec_above_410 / 60.0), 1),
            "above_430_min": round(float(sec_above_430 / 60.0), 1),
        }
    except Exception:
        return {"above_380_min": 0.0, "above_410_min": 0.0, "above_430_min": 0.0}


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

        if "Vertical Speed (ft/min)" in df.columns:
            vs = pd.to_numeric(df["Vertical Speed (ft/min)"], errors="coerce").fillna(0)
        elif "GPS Altitude (feet)" in df.columns:
            alt = pd.to_numeric(df["GPS Altitude (feet)"], errors="coerce").fillna(0)
            dt_safe = dt.replace(0, np.nan)
            vs = (alt.diff() / dt_safe * 60.0).fillna(0)
        else:
            vs = pd.Series(0, index=df.index)

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
        in_air = gs > 45
        transitions = (in_air.astype(int).diff() == -1)
        landing_count = int(transitions.sum())
        return max(landing_count, 1)
    except Exception:
        return 1


def calculate_wind_aloft(df: pd.DataFrame) -> dict:
    """
    Uses direct logged signal columns 'Wind Direction (deg)' and 'Wind Speed (knots)'.
    """
    res = {
        "wind_speed_kts": "N/A",
        "wind_dir_deg": "N/A",
        "headwind_kts": "N/A",
        "crosswind_kts": "N/A",
    }

    wdir_cols = [c for c in df.columns if "wind direction" in c.lower()]
    wspd_cols = [c for c in df.columns if "wind speed" in c.lower()]

    if not wdir_cols or not wspd_cols:
        return res

    try:
        wspd = pd.to_numeric(df[wspd_cols[0]], errors="coerce").fillna(0)
        wdir = pd.to_numeric(df[wdir_cols[0]], errors="coerce").fillna(0)
        gs = pd.to_numeric(df.get("Ground Speed (knots)", pd.Series(0, index=df.index)), errors="coerce").fillna(0)
        tas = pd.to_numeric(df.get("True Airspeed (knots)", pd.Series(0, index=df.index)), errors="coerce").fillna(0)
        heading = pd.to_numeric(df.get("Magnetic Heading (deg)", pd.Series(0, index=df.index)), errors="coerce").fillna(0)

        # Filter for active flight (GS > 40 kts)
        mask = (gs > 40) | (tas > 40)
        if not mask.any():
            mask = pd.Series(True, index=df.index)

        wspd_f = wspd[mask]
        wdir_f = wdir[mask]
        hdg_f = heading[mask]
        gs_f = gs[mask]
        tas_f = tas[mask]

        if wspd_f.empty or (wspd_f == 0).all():
            return res

        avg_wspd = float(wspd_f.mean())

        # Circular mean of wind direction
        wdir_rad = np.radians(wdir_f)
        sin_sum = np.sin(wdir_rad).mean()
        cos_sum = np.cos(wdir_rad).mean()
        avg_wdir = (np.degrees(np.arctan2(sin_sum, cos_sum))) % 360

        # Headwind & Crosswind calculation
        if not hdg_f.empty and hdg_f.abs().sum() > 0:
            hdg_rad = np.radians(hdg_f.mean())
            angle_diff = np.radians(avg_wdir) - hdg_rad
            headwind = avg_wspd * np.cos(angle_diff)
            crosswind = abs(avg_wspd * np.sin(angle_diff))
        else:
            headwind = tas_f.mean() - gs_f.mean() if not tas_f.empty else 0.0
            crosswind = 0.0

        res["wind_speed_kts"] = round(avg_wspd, 1)
        res["wind_dir_deg"] = int(round(avg_wdir))
        res["headwind_kts"] = round(float(headwind), 1)
        res["crosswind_kts"] = round(float(crosswind), 1)

    except Exception as e:
        print(f"Wind signal extraction error: {e}")

    return res


def calculate_g_load_and_bank(df: pd.DataFrame) -> dict:
    """
    Extracts peak positive/negative vertical G acceleration and maximum bank angle during flight.
    Uses absolute values for bank angles to properly handle left (<0) and right (>0) turns.
    """
    res = {
        "peak_pos_g": "N/A",
        "peak_neg_g": "N/A",
        "max_bank_deg": "N/A",
        "max_left_bank_deg": "N/A",
        "max_right_bank_deg": "N/A",
    }

    # G-Load column (prefer Vertical Accel)
    g_cols = [c for c in df.columns if "vertical accel" in c.lower() or "vert accel" in c.lower() or "g_load" in c.lower()]
    if not g_cols:
        g_cols = [c for c in df.columns if "accel" in c.lower()]

    if g_cols:
        try:
            gs = pd.to_numeric(df.get("Ground Speed (knots)", pd.Series(0, index=df.index)), errors="coerce").fillna(0)
            g_series = pd.to_numeric(df[g_cols[0]], errors="coerce").dropna()
            
            flight_mask = (gs > 35)
            if "RPM" in df.columns:
                rpm = pd.to_numeric(df["RPM"], errors="coerce").fillna(0)
                flight_mask |= (rpm > 1000)

            if flight_mask.any():
                g_series = g_series[flight_mask]

            if not g_series.empty:
                mean_g = g_series.mean()
                if abs(mean_g) < 0.5:
                    g_total = g_series + 1.0
                else:
                    g_total = g_series

                res["peak_pos_g"] = round(float(g_total.max()), 2)
                res["peak_neg_g"] = round(float(g_total.min()), 2)
        except Exception as e:
            print(f"G-load extraction notice: {e}")

    # Bank Angle (Roll)
    roll_cols = [c for c in df.columns if c.lower() == "roll (deg)" or "roll" in c.lower()]
    if roll_cols:
        try:
            gs = pd.to_numeric(df.get("Ground Speed (knots)", pd.Series(0, index=df.index)), errors="coerce").fillna(0)
            raw_roll = pd.to_numeric(df[roll_cols[0]], errors="coerce")

            flight_mask = (gs > 35)
            if "RPM" in df.columns:
                rpm = pd.to_numeric(df["RPM"], errors="coerce").fillna(0)
                flight_mask |= (rpm > 1000)

            if flight_mask.any():
                raw_roll = raw_roll[flight_mask]

            raw_roll = raw_roll.dropna()
            if not raw_roll.empty:
                abs_roll = raw_roll.abs()
                res["max_bank_deg"] = round(float(abs_roll.max()), 1)

                left_turns = raw_roll[raw_roll < 0].abs()
                if not left_turns.empty:
                    res["max_left_bank_deg"] = round(float(left_turns.max()), 1)

                right_turns = raw_roll[raw_roll > 0]
                if not right_turns.empty:
                    res["max_right_bank_deg"] = round(float(right_turns.max()), 1)

        except Exception as e:
            print(f"Bank angle extraction notice: {e}")

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

        dt_safe = dt.replace(0, np.nan)
        vs_fpm = (alt.diff() / dt_safe) * 60.0

        climb_mask = (vs_fpm > 300) & (gs > 40)
        if not climb_mask.any():
            return 0.0

        grad_series = vs_fpm[climb_mask] / (gs[climb_mask] / 60.0)
        grad_series = grad_series.replace([np.inf, -np.inf], np.nan).dropna()
    except Exception:
        return 0.0


def extract_comprehensive_flight_stats(df: pd.DataFrame) -> dict:
    """
    Combines all advanced analytics into a structured dictionary.
    """
    stats = {}
    shock_dict = calculate_shock_cooling(df)
    stats.update(shock_dict)
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
