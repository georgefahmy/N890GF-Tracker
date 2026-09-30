import json
import os
import pandas as pd

FLEET_SUMMARY_PATH = os.path.join(os.getcwd(), "static", "fleet_summary.json")
STATS_CSV_PATH = os.path.join(os.getcwd(), "static", "stats.csv")


def load_fleet_summary():
    """Loads static/fleet_summary.json if available, or returns None."""
    if os.path.exists(FLEET_SUMMARY_PATH):
        try:
            with open(FLEET_SUMMARY_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def load_stats_file():
    """
    Returns a DataFrame with flight stats records.
    Prioritizes static/fleet_summary.json, falling back to static/stats.csv if not found.
    """
    summary = load_fleet_summary()
    if summary and "flights" in summary and summary["flights"]:
        df = pd.DataFrame(summary["flights"])
        if "fid" in df.columns:
            df.set_index("fid", inplace=True)
        return df

    if os.path.exists(STATS_CSV_PATH):
        try:
            return pd.read_csv(
                STATS_CSV_PATH,
                names=[
                    "fid",
                    "total_duration",
                    "air_time",
                    "distance_traveled",
                    "gallons_used",
                    "max_cht",
                    "max_rpm",
                    "avg_mpg",
                    "avg_speed",
                ],
                index_col=0,
                skiprows=1,
            )
        except Exception:
            pass
    return pd.DataFrame()


def calc_total_distance(df):
    if df is None or df.empty:
        return 0.0
    for col in ["distance_traveled", "distance_traveled_mi"]:
        if col in df.columns:
            return float(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())
    return 0.0


def calc_total_air_time(df):
    if df is None or df.empty:
        return 0.0
    for col in ["air_time", "air_time_sec"]:
        if col in df.columns:
            return float(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())
    return 0.0


def calc_total_gallons(df):
    if df is None or df.empty:
        return 0.0
    for col in ["gallons_used", "total_fuel"]:
        if col in df.columns:
            return float(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())
    return 0.0


def calc_total_duration(df):
    if df is None or df.empty:
        return 0.0
    for col in ["total_duration", "engine_duration"]:
        if col in df.columns:
            return float(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())
    return 0.0
