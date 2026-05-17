import pandas as pd
import os

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
df["_orig_flight_num"] = (df["Session Time"].diff() < 0).cumsum()
df = df[df["GPS Date & Time"].notna() & (df["GPS Date & Time"] != "")]
df["CHT 1 (deg C)"] = pd.to_numeric(df["CHT 1 (deg C)"], errors="coerce")
df["RPM"] = (df["RPM L"] + df["RPM R"]) / 2
flight_max_rpm = df.groupby("_orig_flight_num")[["RPM"]].max()
flight_max_cht = df.groupby("_orig_flight_num")[["CHT 1 (deg C)"]].max()
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
df.drop(columns=["_orig_flight_num"], inplace=True)

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
        "/Users/GFahmy/Documents/projects/n890gf_tracker/test_dir", saved_filename
    )
    flight_data.to_csv(filepath, index=False)
