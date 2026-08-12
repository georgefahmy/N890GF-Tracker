import csv
import os

import pandas as pd


# ====== LOAD ALL CSV FILES ======
def load_flights(data_dir, files):
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


def append_unique_row(filename, new_row):
    # Read existing rows to check for duplicates
    with open(filename, "r", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if row == new_row:
                print("Entry already exists. Skipping...")
                return
    # If loop finishes without returning, append the new row
    with open(filename, "a", newline="") as f:
        csv.writer(f).writerow(new_row)
        print("New entry added successfully.")


cwd = os.getcwd()
data_dir = cwd + "/clean_flights/"
files = os.listdir(data_dir)
stats_file = cwd + "/static/stats.csv"

rows = []
for file in sorted(files):
    if not file.endswith(".csv"):
        continue
    filepath = os.path.join(data_dir, file)
    try:
        flight_data = pd.read_csv(filepath, low_memory=False)
        if flight_data.empty or "Session Time" not in flight_data.columns:
            continue

        safe_name = os.path.splitext(file)[0]
        total_duration = flight_data["Session Time"].iloc[-1] - flight_data["Session Time"].iloc[0]

        air_time = 0
        if "Transponder Status" in flight_data.columns:
            tx_data = flight_data[flight_data["Transponder Status"] == 3]["Session Time"]
            if not tx_data.empty:
                air_time = tx_data.iloc[-1] - tx_data.iloc[0]

        # Calculate distance
        dist_miles = 0.0
        gs_col = None
        for c in ["Ground Speed (knots)", "Ground Speed", "GPS GS", "gps_gs"]:
            if c in flight_data.columns:
                gs_col = c
                break

        if gs_col and "Session Time" in flight_data.columns:
            gs_s = pd.to_numeric(flight_data[gs_col], errors="coerce").fillna(0)
            t_s = pd.to_numeric(flight_data["Session Time"], errors="coerce").fillna(0)
            dt_s = t_s.diff().fillna(0).clip(lower=0, upper=10)
            dist_miles = float((gs_s * 1.15078 * (dt_s / 3600.0)).sum())

        if dist_miles <= 0.1 and "Distance Traveled" in flight_data.columns:
            dt_series = pd.to_numeric(flight_data["Distance Traveled"], errors="coerce").dropna()
            if not dt_series.empty:
                dist_miles = float(dt_series.max() / 5280.0)

        gallons_used = 0.0
        if "Fuel Flow Integral" in flight_data.columns:
            ff_series = pd.to_numeric(flight_data["Fuel Flow Integral"], errors="coerce").dropna()
            if not ff_series.empty:
                gallons_used = float(ff_series.max())

        max_cht = float(flight_data["Max CHT"].max()) if "Max CHT" in flight_data.columns else 0.0
        max_rpm = float(flight_data["RPM"].max()) if "RPM" in flight_data.columns else 0.0

        avg_mpg = 0.0
        if "MPG" in flight_data.columns:
            valid_mpg = pd.to_numeric(flight_data["MPG"], errors="coerce").dropna()
            if not valid_mpg.empty:
                avg_mpg = float(valid_mpg.mean())

        avg_speed = 0.0
        if gs_col and "Transponder Status" in flight_data.columns:
            tx_speed = flight_data[flight_data["Transponder Status"] == 3][gs_col]
            if not tx_speed.empty:
                avg_speed = float(tx_speed.mean() * 1.15)

        rows.append([
            safe_name,
            total_duration,
            air_time,
            dist_miles,
            gallons_used,
            max_cht,
            max_rpm,
            avg_mpg,
            avg_speed
        ])
        print(f"Processed {safe_name}: Distance={dist_miles:.1f} mi, Duration={total_duration/60:.1f} min")
    except Exception as e:
        print(f"Error processing {file}: {e}")

# Write static/stats.csv cleanly from scratch
with open(stats_file, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerows(rows)
print(f"Regenerated {stats_file} cleanly with {len(rows)} flight entries.")


# final_mask = pd.Series(True, index=flight_data.index)
# final_mask &= pd.to_numeric(flight_data["RPM"], errors="coerce") > 2200
# final_mask &= (
#     pd.to_numeric(flight_data["Manifold Pressure (inHg)"], errors="coerce") > 17
# )
# final_mask &= (
#     pd.to_numeric(flight_data["Indicated Airspeed (knots)"], errors="coerce") > 100
# )

# # 2. Set up the 3D canvas
# fig = plt.figure(figsize=(10, 7))
# ax = fig.add_subplot(projection="3d")

# # 3. Plot using DataFrame columns
# # 's' controls the sizes, 'c' controls colors (optional)
# scatter = ax.scatter(
#     df[final_mask]["RPM"],
#     df[final_mask]["Total Fuel Flow (gal/hr)"],
#     df[final_mask]["Manifold Pressure (inHg)"],
#     c=df[final_mask]["True Airspeed (knots)"],
#     alpha=0.7,
#     cmap="viridis",
# )
# fig.colorbar(scatter, ax=ax, label="True Airspeed (knots)")
# # 4. Add labels and titles
# ax.set_xlabel("RPM")
# ax.set_ylabel("FF")
# ax.set_zlabel("MAP")
# plt.title("Matplotlib 3D Scatter Plot with Variable Sizes")
# plt.show()
