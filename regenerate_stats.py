import pandas as pd
import os
import csv


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

df = load_flights(data_dir, files)
flight_ids = sorted(
    [fid for fid in df["Flight ID"].unique() if fid not in (None, 0, "", "nan")]
)

for fid in flight_ids:
    flight_data = df[df["Flight ID"] == fid].copy()
    # Extract date from Flight ID (assumes format: "YYYY-MM-DD ... - Flight X")
    fid_str = "-".join(str(fid).split("-")[:-1])
    safe_name = fid_str.replace("/", "-").replace(":", "-")

    total_duration = (
        flight_data["Session Time"].iloc[-1] - flight_data["Session Time"].iloc[-0]
    )
    try:
        air_time = (
            flight_data[flight_data["Transponder Status"] == 3]["Session Time"].iloc[-1]
            - flight_data[flight_data["Transponder Status"] == 3]["Session Time"].iloc[
                0
            ]
        )
    except:
        air_time = 0
    distance_traveled = flight_data["Distance Traveled"].iloc[-1] / 5280
    gallons_used = flight_data["Fuel Flow Integral"].iloc[-1]
    max_cht = flight_data["Max CHT"].iloc[-1]
    max_rpm = flight_data["RPM"].max()
    avg_mpg = flight_data["MPG"].mean()
    avg_speed = (
        flight_data[flight_data["Transponder Status"] == 3][
            "Ground Speed (knots)"
        ].mean()
        * 1.15
    )
    data = [
        safe_name,
        total_duration,
        air_time,
        distance_traveled,
        gallons_used,
        max_cht,
        max_rpm,
        avg_mpg,
        avg_speed,
    ]
    append_unique_row(stats_file, data)


final_mask = pd.Series(True, index=flight_data.index)
final_mask &= pd.to_numeric(flight_data["RPM"], errors="coerce") > 2200
final_mask &= pd.to_numeric(flight_data["Manifold Pressure (inHg)"], errors="coerce") > 17
final_mask &= pd.to_numeric(flight_data["Indicated Airspeed (knots)"], errors="coerce") > 100

# 2. Set up the 3D canvas
fig = plt.figure(figsize=(10, 7))
ax = fig.add_subplot(projection="3d")

# 3. Plot using DataFrame columns
# 's' controls the sizes, 'c' controls colors (optional)
scatter = ax.scatter(
    df[final_mask]["RPM"],
    df[final_mask]["Total Fuel Flow (gal/hr)"],
    df[final_mask]["Manifold Pressure (inHg)"],
    c=df[final_mask]["True Airspeed (knots)"],
    alpha=0.7,
    cmap="viridis",
)
fig.colorbar(scatter, ax=ax, label="True Airspeed (knots)")
# 4. Add labels and titles
ax.set_xlabel("RPM")
ax.set_ylabel("FF")
ax.set_zlabel("MAP")
plt.title("Matplotlib 3D Scatter Plot with Variable Sizes")
plt.show()
