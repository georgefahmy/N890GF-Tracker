import pandas as pd
import os
import numpy as np

data_dir = "/Users/GFahmy/Documents/RV-7/data_logs"

files = [file for file in os.listdir(data_dir) if "USER_LOG" in file]


# ====== LOAD ALL CSV FILES ======
def load_flights(files):
    all_data = []
    for file in files:
        if file.endswith(".csv"):
            path = os.path.join(data_dir, file)
            try:
                df = pd.read_csv(path)
                all_data.append(df)
            except Exception as e:
                print(f"Skipping {file}: {e}")
    combined = pd.concat(all_data, ignore_index=True)
    return combined


df = load_flights(files)
df = df[df["GPS Date & Time"].notna() & (df["GPS Date & Time"] != "")]
num_cols = df.select_dtypes(include=[np.number]).columns
obj_cols = df.select_dtypes(include=["object"]).columns

if len(num_cols) > 0:
    df[num_cols] = df[num_cols].fillna(0)

if len(obj_cols) > 0:
    df[obj_cols] = df[obj_cols].fillna("")

core_numeric_cols = [
    "Session Time",
    "System Time",
    "RPM L",
    "RPM R",
    "RPM",
    "CHT 1 (deg C)",
    "CHT 2 (deg C)",
    "CHT 3 (deg C)",
    "CHT 4 (deg C)",
    "OAT (deg C)",
    "OIL TEMPERATURE (deg C)",
    "Fuel Flow 1 (gal/hr)",
    "Total Fuel Flow (gal/hr)",
    "Ground Speed (knots)",
]

for col in core_numeric_cols:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

df["_orig_flight_num"] = (df["Session Time"].diff() < 0).cumsum()
df["CHT 1 (deg C)"] = pd.to_numeric(df["CHT 1 (deg C)"], errors="coerce")
df["RPM"] = (df["RPM L"] + df["RPM R"]) / 2
df["AVG_CHT"] = (
    df["CHT 1 (deg C)"]
    + df["CHT 2 (deg C)"]
    + df["CHT 3 (deg C)"]
    + df["CHT 4 (deg C)"]
) / 4
df["CHT_Delta_T (deg C)"] = df["AVG_CHT"] - df["OAT (deg C)"]
df["OIL_Delta_T (deg C)"] = df["OIL TEMPERATURE (deg C)"] - df["OAT (deg C)"]

temp_cols = [col for col in df.columns if "(deg C)" in col]
for col in temp_cols:
    try:
        new_name = col.replace("(deg C)", "(deg F)")
        # Force numeric conversion to prevent string math errors
        df[col] = pd.to_numeric(df[col], errors="coerce")
        # Convert C to F
        df[new_name] = df[col] * 9.0 / 5.0 + 32.0

    except Exception as e:
        print(f"Warning: Temperature conversion failed for column '{col}': {e}")

if "Total Fuel Flow (gal/hr)" in df.columns:
    df["Total Fuel Flow (gal/hr)"] = pd.to_numeric(
        df["Fuel Flow 1 (gal/hr)"], errors="coerce"
    ).fillna(0)
    # Vectorized trapezoidal integration per flight
    df = df.sort_values(["_orig_flight_num", "Session Time"])
    dt = df.groupby("_orig_flight_num")["Session Time"].diff().fillna(0)
    flow_gps = df["Total Fuel Flow (gal/hr)"] / 3600.0
    flow_prev = flow_gps.groupby(df["_orig_flight_num"]).shift(1).fillna(flow_gps)
    avg_flow = 0.5 * (flow_gps + flow_prev)
    increment = avg_flow * dt
    df["Fuel Flow Integral"] = increment.groupby(df["_orig_flight_num"]).cumsum()

if "Ground Speed (knots)" in df.columns:
    df["Ground Speed (knots)"] = pd.to_numeric(
        df["Ground Speed (knots)"], errors="coerce"
    ).fillna(0)
    # Vectorized trapezoidal integration for distance per flight
    dt = df.groupby("_orig_flight_num")["Session Time"].diff().fillna(0)
    speed_fps = df["Ground Speed (knots)"] * 1.15 * 5280 / 3600
    speed_prev = speed_fps.groupby(df["_orig_flight_num"]).shift(1).fillna(speed_fps)
    avg_speed = 0.5 * (speed_fps + speed_prev)
    increment = avg_speed * dt
    df["Distance Traveled"] = increment.groupby(df["_orig_flight_num"]).cumsum()

# Calculate MPG (nautical miles per gallon)
if "Ground Speed (knots)" in df.columns and "Total Fuel Flow (gal/hr)" in df.columns:
    df["MPG"] = df["Ground Speed (knots)"] / df["Total Fuel Flow (gal/hr)"]
    df["MPG"] = df["MPG"].replace([float("inf"), -float("inf")], 0).fillna(0)
else:
    df["MPG"] = 0

flight_max_rpm = df.groupby("_orig_flight_num")[["RPM"]].max()
flight_max_cht = df.groupby("_orig_flight_num")[
    [
        "CHT 1 (deg F)",
        "CHT 2 (deg F)",
        "CHT 3 (deg F)",
        "CHT 4 (deg F)",
    ]
].max()
df["Max CHT"] = df["_orig_flight_num"].map(flight_max_cht.max(axis=1))
flights_with_engine = (flight_max_rpm["RPM"] > 0) & (flight_max_cht.max(axis=1) > 50)
engine_flight_ids = [
    fid
    for fid in df["_orig_flight_num"].unique()
    if flights_with_engine.get(fid, False)
]

flight_start_gps = df.groupby("_orig_flight_num")["GPS Date & Time"].first()
flightid_map = {
    fid: f"{flight_start_gps.get(fid, '')}" for idx, fid in enumerate(engine_flight_ids)
}

df["Flight ID"] = df["_orig_flight_num"].map(lambda x: flightid_map.get(x, None))
df["Flight ID"] = pd.to_datetime(df["Flight ID"])
df["Flight ID"] = df["Flight ID"].dt.tz_localize("UTC").dt.tz_convert("US/Pacific")
df["System Time"] = pd.to_numeric(df["System Time"], errors="coerce").fillna(0)

df.drop(columns=["_orig_flight_num"], inplace=True)
# Ensure RPM L and RPM R are numeric and fill NaNs with 0
flight_ids = [
    fid for fid in df["Flight ID"].unique() if fid not in (None, 0, "", "nan")
]

for fid in flight_ids:
    flight_data = df[df["Flight ID"] == fid]
    if flight_data.empty:
        continue

    # Extract date from Flight ID (assumes format: "YYYY-MM-DD ... - Flight X")
    fid_str = "-".join(str(fid).split("-")[:-1])
    safe_name = fid_str.replace("/", "-").replace(":", "-")

    # Clean filename
    base_name, ext = os.path.splitext(safe_name)
    saved_filename = f"{safe_name}.csv"
    filepath = os.path.join(
        "/Users/GFahmy/Documents/projects/n890gf_tracker/clean_flights", saved_filename
    )
    flight_data.to_csv(filepath, index=False)
