import base64
import glob
import os
import warnings

import contextily as ctx
import FreeSimpleGUI as sg
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.widgets import RectangleSelector
from src.airspeed_calibration import analyze_flight_data

warnings.filterwarnings("ignore")
matplotlib.use("TkAgg")
ground_track = {
    "lat": None,
    "lon": None,
    "time": None,
    "marker": None,
    "canvas": None,
}
# # --- Ground track sync globals ---
# ground_track_lat = None
# ground_track_lon = None
# ground_track_time = None
# ground_track_marker = None
# ground_track_canvas = None


def load_data(filepath, folder=False):
    """Loads the CSV file."""
    try:
        # Skip metadata rows if necessary, but standard read_csv usually works
        if folder:
            all_files = glob.glob(os.path.join(filepath, "*.csv"))
            dfs = [pd.read_csv(f) for f in all_files]
            # Concatenate all DataFrames in the list into one master DataFrame
            # ignore_index=True resets the index to a continuous sequence (0, 1, 2, ...)
            df = pd.concat(dfs, ignore_index=True)
            return df
        else:
            df = pd.read_csv(filepath, low_memory=False)
            return df
    except Exception as e:
        print(f"Error loading file: {e}")
        return None


def process_flights(df):
    """
    Groups data into flights and marks if the engine was run.
    """
    # Remove rows where System Time is NaN or blank
    df = df[df["System Time"].notna() & (df["System Time"] != "")]
    # Remove rows where GPS Date & Time is NaN or blank
    df = df[df["GPS Date & Time"].notna() & (df["GPS Date & Time"] != "")]
    # Convert all temperature columns from deg C to deg F
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
    # 1. Identify Flights based on Session Time resets
    df["_orig_flight_num"] = (df["Session Time"].diff() < 0).cumsum()
    # Ensure System Time is numeric and fill NaNs with 0 to prevent aggregation errors
    df["System Time"] = pd.to_numeric(df["System Time"], errors="coerce").fillna(0)
    # Ensure RPM L and RPM R are numeric and fill NaNs with 0
    for col in ["RPM L", "RPM R"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    # Create combined RPM signal as average of left and right
    df["RPM"] = (df["RPM L"] + df["RPM R"]) / 2
    df["AVG_CHT"] = (
        df["CHT 1 (deg F)"]
        + df["CHT 2 (deg F)"]
        + df["CHT 3 (deg F)"]
        + df["CHT 4 (deg F)"]
    ) / 4
    df["CHT_Delta_T"] = df["AVG_CHT"] - df["OAT (deg F)"]
    df["OIL_Delta_T"] = df["Oil Temp (deg F)"] - df["OAT (deg F)"]

    # --- Compute Fuel Flow Integral (gallons) per flight ---
    # Ensure Fuel Flow 1 is numeric
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
        speed_prev = (
            speed_fps.groupby(df["_orig_flight_num"]).shift(1).fillna(speed_fps)
        )
        avg_speed = 0.5 * (speed_fps + speed_prev)
        increment = avg_speed * dt
        df["Distance Traveled"] = increment.groupby(df["_orig_flight_num"]).cumsum()
    if "Ground Speed (knots)" in df.columns:
        df["Ground Speed (knots)"] = pd.to_numeric(
            df["Ground Speed (knots)"], errors="coerce"
        ).fillna(0)
    # Try both "Fuel Flow" and "Fuel Flow 1 (gal/hr)" as possible columns
    if "Total Fuel Flow (gal/hr)" in df.columns:
        df["Total Fuel Flow (gal/hr)"] = pd.to_numeric(
            df["Total Fuel Flow (gal/hr)"], errors="coerce"
        ).fillna(0)
    elif "Fuel Flow 1 (gal/hr)" in df.columns:
        df["Total Fuel Flow (gal/hr)"] = pd.to_numeric(
            df["Fuel Flow 1 (gal/hr)"], errors="coerce"
        ).fillna(0)
    # Calculate MPG (nautical miles per gallon)
    if (
        "Ground Speed (knots)" in df.columns
        and "Total Fuel Flow (gal/hr)" in df.columns
    ):
        df["MPG"] = df["Ground Speed (knots)"] / df["Total Fuel Flow (gal/hr)"]
        df["MPG"] = df["MPG"].replace([float("inf"), -float("inf")], 0).fillna(0)
    else:
        df["MPG"] = 0
    # 2. Determine if Engine was Run for each flight
    # Calculate max RPM for each flight
    flight_max_rpm = df.groupby("_orig_flight_num")[["RPM L", "RPM R"]].max()
    flight_max_cht = df.groupby("_orig_flight_num")[
        [
            "CHT 1 (deg F)",
            "CHT 2 (deg F)",
            "CHT 3 (deg F)",
            "CHT 4 (deg F)",
        ]
    ].max()
    df["Max CHT"] = df["_orig_flight_num"].map(flight_max_cht.max(axis=1))
    # Create a boolean Series: True if any RPM > 0 and CHT > 125
    flights_with_engine = (
        (flight_max_rpm["RPM L"] > 0) | (flight_max_rpm["RPM R"] > 0)
    ) & (flight_max_cht.max(axis=1) > 125)
    # Compute first GPS Date & Time for each flight
    flight_start_gps = df.groupby("_orig_flight_num")["GPS Date & Time"].first()
    # Map this status back to the original DataFrame
    df["Engine Run"] = df["_orig_flight_num"].map(flights_with_engine)
    # Assign sequential Flight IDs as "<seq> - <GPS Date & Time>" for engine-run flights, else NaN
    engine_flight_ids = [
        fid
        for fid in df["_orig_flight_num"].unique()
        if flights_with_engine.get(fid, False)
    ]
    # Map: _orig_flight_num -> "<seq> - <GPS Date & Time>"
    flightid_map = {
        fid: f"{flight_start_gps.get(fid, '')}"
        for idx, fid in enumerate(engine_flight_ids)
    }
    df["Flight ID"] = df["_orig_flight_num"].map(lambda x: flightid_map.get(x, None))
    df.drop(columns=["_orig_flight_num"], inplace=True)
    # Fill any null or NaN values in the DataFrame with 0 to ensure consistent datatypes
    # df.fillna("0", inplace=True)
    # Defragment DataFrame to improve performance after many column insertions
    df = df.copy()
    return df


def list_flights(df):
    """Prints a summary of all detected flights with Engine Run status."""
    stats = df.groupby("Flight ID").agg(
        Start_Time=("Session Time", "min"),
        End_Time=("Session Time", "max"),
        Duration=("Session Time", lambda x: x.max() - x.min()),
        Data_Points=("Session Time", "count"),
        Engine_Run=("Engine Run", "first"),  # All rows in a flight have the same value
        Max_RPM=("RPM L", "max"),  # showing RPM L as an example
        Max_CHT=("Max CHT", "max"),  # showing RPM L as an example
    )
    # print("\n--- Detected Flights ---")
    # print(stats)
    return stats


def list_signals(df):
    """Lists all available signal columns."""
    columns = [
        col
        for col in df.columns
        if col not in ["Flight ID", "Unnamed: 103", "Engine Run"]
    ]
    # print("\n--- Available Signals ---")
    # for i, col in enumerate(columns):
    #     print(f"{i}: {col}")
    return columns


def find_gami_window(df, flight_id):
    """
    Automatically find start and end times of a GAMI sweep.
    Criteria:
    - RPM nearly constant (+-50)
    - Manifold pressure nearly constant
    - Fuel flow decreasing
    - EGT rises then peaks
    """

    flight_df = df[df["Flight ID"] == flight_id].copy().fillna(0)
    if flight_df.empty:
        return None, None

    rpm = flight_df["RPM"].values
    mp = flight_df["Manifold Pressure (inHg)"].values
    ff = flight_df["Total Fuel Flow (gal/hr)"].values

    # Smooth signals slightly to reduce noise
    rpm_s = pd.Series(rpm).rolling(5, center=True).mean().ffill().bfill()
    mp_s = pd.Series(mp).rolling(5, center=True).mean().ffill().bfill()
    ff_s = pd.Series(ff).rolling(5, center=True).mean().ffill().bfill()

    # Compute gradient with respect to time (1 Hz sampling assumed)
    time = flight_df["Session Time"].values
    dt = np.gradient(time)
    dt[dt == 0] = 1  # prevent divide by zero
    dff = np.gradient(ff_s) / dt
    # Normalize gradient to handle scaling differences
    dff_norm = dff / (np.nanmax(np.abs(dff)) + 1e-6)

    # Use rolling median to better capture local stability instead of global median
    rpm_ref = pd.Series(rpm_s).rolling(30, center=True).median().ffill().bfill()
    mp_ref = pd.Series(mp_s).rolling(30, center=True).median().ffill().bfill()

    mask = (abs(rpm_s - rpm_ref) < 50) & (abs(mp_s - mp_ref) < 2.0) & (dff_norm < -0.02)

    indices = np.where(mask)[0]
    if len(indices) == 0:
        print("No GAMI sweep detected.")
        return None, None

    # Group contiguous regions
    groups = np.split(indices, np.where(np.diff(indices) != 1)[0] + 1)

    best_group = None
    best_length = 0

    # --- EGT SHAPE VALIDATION ---
    egt_cols = [
        "EGT 1 (deg F)",
        "EGT 2 (deg F)",
        "EGT 3 (deg F)",
        "EGT 4 (deg F)",
    ]

    for group in groups:
        if len(group) < 15:  # slightly shorter allowed
            continue

        segment = flight_df.iloc[group]
        valid_cylinders = 0

        for col in egt_cols:
            if col not in segment.columns:
                continue

            egt = pd.to_numeric(segment[col], errors="coerce").ffill().bfill().values

            if len(egt) < 10:
                continue

            # Smooth EGT more aggressively to remove noise
            egt_s = pd.Series(egt).rolling(7, center=True).mean().ffill().bfill().values

            # Find peak index
            peak_idx = np.argmax(egt_s)

            # Allow peak closer to edges (real sweeps often truncated)
            if peak_idx < 2 or peak_idx > len(egt_s) - 2:
                continue

            # Split before/after peak
            before = egt_s[:peak_idx]
            after = egt_s[peak_idx:]

            if len(before) < 3 or len(after) < 3:
                continue

            # Use trend (slope) instead of absolute min/max difference
            rise_trend = np.polyfit(range(len(before)), before, 1)[0]
            fall_trend = np.polyfit(range(len(after)), after, 1)[0]

            # Also require total rise magnitude
            total_rise = egt_s[peak_idx] - np.min(before)

            if rise_trend > 0 and fall_trend < 0 and total_rise > 10:
                valid_cylinders += 1

        # Require at least ONE valid cylinder (very tolerant for real-world data)
        if valid_cylinders >= 1:
            if len(group) > best_length:
                best_group = group
                best_length = len(group)

    if best_group is None:
        print("No valid GAMI sweep (EGT shape failed).")
        return None, None

    # Expand window slightly to capture full sweep
    pad = int(len(best_group) * 0.1)
    start_idx = max(0, best_group[0] - pad)
    end_idx = min(len(flight_df) - 1, best_group[-1] + pad)

    start_time = flight_df.iloc[start_idx]["Session Time"]
    end_time = flight_df.iloc[end_idx]["Session Time"]

    print(f"GAMI debug: candidates={len(groups)}, selected_length={best_length}")
    print(f"GAMI sweep detected from {start_time} to {end_time} (EGT validated)")

    return start_time, end_time


def gami_spread(df, start_time, end_time):
    gami_columns = [
        "EGT 1 (deg F)",
        "EGT 2 (deg F)",
        "EGT 3 (deg F)",
        "EGT 4 (deg F)",
        "Total Fuel Flow (gal/hr)",
    ]
    gami_df = (
        df[(df["Session Time"] >= start_time) & (df["Session Time"] <= end_time)]
        .copy()[gami_columns]
        .copy()
    )

    # Find fuel flow at peak EGT for each cylinder
    fuel_flows_at_peak = []
    peak_points = []

    for i in range(1, 5):
        egt_col = f"EGT {i} (deg F)"

        if egt_col not in gami_df.columns:
            continue

        # Find index of max EGT
        idx_max = gami_df[egt_col].idxmax()

        if pd.isna(idx_max):
            continue

        fuel_flow = gami_df.loc[idx_max, "Total Fuel Flow (gal/hr)"]
        egt_val = gami_df.loc[idx_max, egt_col]

        fuel_flows_at_peak.append(fuel_flow)
        peak_points.append((fuel_flow, egt_val, i))

        print(f"Cylinder {i}: Peak EGT ({egt_val}) at fuel flow = {fuel_flow:.2f} GPH")

    if len(fuel_flows_at_peak) >= 2:
        min_ff = min(fuel_flows_at_peak)
        max_ff = max(fuel_flows_at_peak)
        spread = max_ff - min_ff

        print(f"\nGAMI Spread: {spread:.2f} GPH")
    else:
        print("Not enough data to compute GAMI spread.")

    # --- Plot EGT vs Fuel Flow with peak markers ---

    fig, ax = plt.subplots()

    cyl_colors = {}

    # Scatter each cylinder and store its color
    for i in range(1, 5):
        egt_col = f"EGT {i} (deg F)"
        if egt_col in gami_df.columns:
            (line,) = ax.plot(
                gami_df["Total Fuel Flow (gal/hr)"],
                gami_df[egt_col],
                label=f"Cylinder {i}",
            )
            cyl_colors[i] = line.get_color()

    # Add vertical lines and labels at peak fuel flow with color matching
    for ff, egt, cyl in peak_points:
        color = cyl_colors.get(cyl, None)

        ax.axvline(ff, linestyle="--", color=color)
        ax.text(
            ff,
            egt,
            f"Cyl {cyl}\n{ff:.2f} GPH",
            rotation=0,
            verticalalignment="bottom",
            color=color,
        )

    ax.set_xlabel("Total Fuel Flow (GPH)")
    ax.set_ylabel("EGT (deg F)")
    ax.set_title("EGT vs Fuel Flow (GAMI Analysis)")
    ax.legend()
    ax.grid(True)

    fig.show()

    return


# --- Helper function to export each flight to its own CSV file ---
def save_flights_to_csv(df, output_dir):
    """
    Saves each flight to its own CSV file, grouping exports into subfolders based on their GPS date.
    """
    import os

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Only keep valid flight IDs
    flight_ids = [fid for fid in df["Flight ID"].unique() if fid not in (None, 0, "")]

    for fid in flight_ids:
        flight_data = df[df["Flight ID"] == fid]
        if flight_data.empty:
            continue

        # Extract date from Flight ID (assumes format: "YYYY-MM-DD ... - Flight X")
        fid_str = str(fid)

        # Create subfolder for that date
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # Clean filename
        safe_name = fid_str.replace("/", "-").replace(":", "-")
        filepath = os.path.join(output_dir, f"{safe_name}.csv")

        flight_data.to_csv(filepath, index=False)


def plot_flight(df, flight_id, left_signal, right_signal, canvas):
    """Plots two selected signals on dual y-axes inside the GUI canvas."""
    flight_data = df[df["Flight ID"] == flight_id]

    if flight_data.empty:
        return

    fig = plt.Figure(figsize=(8, 4), dpi=100)
    fig.subplots_adjust(right=0.75)
    ax_left = fig.add_subplot(111)
    ax_right = ax_left.twinx()

    # Plot left axis signal
    if left_signal and left_signal != "None":
        if left_signal == "CHT":
            cht_columns = [
                "CHT 1 (deg F)",
                "CHT 2 (deg F)",
                "CHT 3 (deg F)",
                "CHT 4 (deg F)",
            ]
            for col in cht_columns:
                if col in flight_data.columns:
                    ax_left.plot(
                        flight_data["Session Time"],
                        flight_data[col],
                        label=col,
                    )
            ax_left.set_ylabel("CHT (deg F)")
        elif left_signal == "EGT":
            egt_columns = [
                "EGT 1 (deg F)",
                "EGT 2 (deg F)",
                "EGT 3 (deg F)",
                "EGT 4 (deg F)",
            ]
            for col in egt_columns:
                if col in flight_data.columns:
                    ax_left.plot(
                        flight_data["Session Time"],
                        flight_data[col],
                        label=col,
                    )
            ax_left.set_ylabel("EGT (deg F)")
        else:
            ax_left.plot(
                flight_data["Session Time"],
                flight_data[left_signal],
                label=left_signal,
            )
            ax_left.set_ylabel(left_signal)

    # Plot right axis signal
    if right_signal and right_signal != "None":
        if right_signal == "CHT":
            cht_columns = [
                "CHT 1 (deg F)",
                "CHT 2 (deg F)",
                "CHT 3 (deg F)",
                "CHT 4 (deg F)",
            ]
            for col in cht_columns:
                if col in flight_data.columns:
                    ax_right.plot(
                        flight_data["Session Time"],
                        flight_data[col],
                        linestyle="dashed",
                        label=col,
                    )
            ax_right.set_ylabel("CHT (deg F)")
        elif right_signal == "EGT":
            egt_columns = [
                "EGT 1 (deg F)",
                "EGT 2 (deg F)",
                "EGT 3 (deg F)",
                "EGT 4 (deg F)",
            ]
            for col in egt_columns:
                if col in flight_data.columns:
                    ax_right.plot(
                        flight_data["Session Time"],
                        flight_data[col],
                        linestyle="dashed",
                        label=col,
                    )
            ax_right.set_ylabel("EGT (deg F)")
        else:
            ax_right.plot(
                flight_data["Session Time"],
                flight_data[right_signal],
                linestyle="dashed",
                label=right_signal,
                color="red",
            )
            ax_right.set_ylabel(right_signal)

    ax_left.set_xlabel("Session Time (seconds)")
    ax_left.set_title(
        f"Flight {flight_id} Analysis "
        f"(Engine Run: {flight_data['Engine Run'].iloc[0]})"
    )
    ax_left.grid(True)

    # Combine legends and place completely outside plot on the right
    lines_left, labels_left = ax_left.get_legend_handles_labels()
    lines_right, labels_right = ax_right.get_legend_handles_labels()
    ax_left.legend(
        lines_left + lines_right,
        labels_left + labels_right,
        loc="lower left",
        bbox_to_anchor=(1.05, 0.5),
        borderaxespad=3,
    )

    # Clear previous canvas content
    for child in canvas.winfo_children():
        child.destroy()

    figure_canvas = FigureCanvasTkAgg(fig, master=canvas)
    figure_canvas.draw()
    widget = figure_canvas.get_tk_widget()
    widget.pack(fill="both", expand=1)

    # Add real-time hover vertical cursor with value display
    ylim_left = ax_left.get_ylim()
    ylim_right = ax_right.get_ylim()
    # xlim = ax_left.get_xlim()
    (cursor_line,) = ax_left.plot(
        [flight_data["Session Time"].iloc[0]] * 2, ylim_left, linestyle="--"
    )

    # Text box for displaying values
    value_text = ax_left.text(
        0,
        1,
        "",
        transform=ax_left.transData,
        verticalalignment="top",
        horizontalalignment="left",
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.8),
    )

    session_time = flight_data["Session Time"].values

    def on_motion(event):
        if event.inaxes in (ax_left, ax_right) and event.xdata is not None:
            # Move vertical line
            cursor_line.set_xdata([event.xdata, event.xdata])

            # Find nearest index
            idx = (abs(session_time - event.xdata)).argmin()
            global ground_track

            if (
                ground_track["time"] is not None
                and ground_track["marker"] is not None
                and event.xdata is not None
            ):
                idx = (abs(ground_track["time"] - event.xdata)).argmin()
                if idx < len(ground_track["lat"]):
                    x_val = float(ground_track["lon"][idx])
                    y_val = float(ground_track["lat"][idx])

                    marker = ground_track["marker"]
                    marker.set_data([x_val], [y_val])
                    ground_track["canvas"].draw_idle()
            # Prepare display string
            display_lines = [f"Time: {session_time[idx]:.2f} sec"]

            # Left axis signals
            if left_signal and left_signal != "None":
                if left_signal == "CHT":
                    for col in [
                        "CHT 1 (deg F)",
                        "CHT 2 (deg F)",
                        "CHT 3 (deg F)",
                        "CHT 4 (deg F)",
                    ]:
                        if col in flight_data.columns:
                            display_lines.append(
                                f"{col}: {flight_data[col].iloc[idx]:.1f}"
                            )
                elif left_signal == "EGT":
                    for col in [
                        "EGT 1 (deg F)",
                        "EGT 2 (deg F)",
                        "EGT 3 (deg F)",
                        "EGT 4 (deg F)",
                    ]:
                        if col in flight_data.columns:
                            display_lines.append(
                                f"{col}: {flight_data[col].iloc[idx]:.1f}"
                            )
                else:
                    display_lines.append(
                        f"{left_signal}: {flight_data[left_signal].iloc[idx]:.2f}"
                    )

            # Right axis signals
            if right_signal and right_signal != "None":
                if right_signal == "CHT":
                    for col in [
                        "CHT 1 (deg F)",
                        "CHT 2 (deg F)",
                        "CHT 3 (deg F)",
                        "CHT 4 (deg F)",
                    ]:
                        if col in flight_data.columns:
                            display_lines.append(
                                f"{col}: {flight_data[col].iloc[idx]:.1f}"
                            )
                elif right_signal == "EGT":
                    for col in [
                        "EGT 1 (deg F)",
                        "EGT 2 (deg F)",
                        "EGT 3 (deg F)",
                        "EGT 4 (deg F)",
                    ]:
                        if col in flight_data.columns:
                            display_lines.append(
                                f"{col}: {flight_data[col].iloc[idx]:.1f}"
                            )
                else:
                    display_lines.append(
                        f"{right_signal}: {flight_data[right_signal].iloc[idx]:.2f}"
                    )

            # Update text box to appear on the right side of the cursor, slightly below the top of the axis
            x = event.xdata
            ylim_top = ax_left.get_ylim()[1]
            y = ylim_top - 0.60 * (ylim_top - ax_left.get_ylim()[0])  # 70% below top
            value_text.set_position(
                (x + 0.01 * (ax_left.get_xlim()[1] - ax_left.get_xlim()[0]), y)
            )
            value_text.set_text("\n".join(display_lines))

            figure_canvas.draw_idle()

    figure_canvas.mpl_connect("motion_notify_event", on_motion)

    # --- Add RectangleSelector for click-and-drag zoom ---
    def on_select(eclick, erelease):
        # eclick and erelease are matplotlib events at press and release
        x1, y1 = eclick.xdata, eclick.ydata
        x2, y2 = erelease.xdata, erelease.ydata
        if x1 is None or x2 is None or y1 is None or y2 is None:
            return
        # Set new X limits for both axes
        new_xlim = (min(x1, x2), max(x1, x2))

        # --- Compute new Y-limits for left axis based on the selected left signal(s) ---
        if left_signal and left_signal != "None":
            if left_signal == "CHT":
                left_cols = [
                    "CHT 1 (deg F)",
                    "CHT 2 (deg F)",
                    "CHT 3 (deg F)",
                    "CHT 4 (deg F)",
                ]
                ydata_left = []
                mask = (flight_data["Session Time"] >= new_xlim[0]) & (
                    flight_data["Session Time"] <= new_xlim[1]
                )
                for col in left_cols:
                    if col in flight_data.columns:
                        ydata_left.extend(flight_data.loc[mask, col].values.tolist())
                if ydata_left:
                    new_ylim_left = (min(ydata_left), max(ydata_left))
                else:
                    new_ylim_left = ax_left.get_ylim()
            elif left_signal == "EGT":
                left_cols = [
                    "EGT 1 (deg F)",
                    "EGT 2 (deg F)",
                    "EGT 3 (deg F)",
                    "EGT 4 (deg F)",
                ]
                ydata_left = []
                mask = (flight_data["Session Time"] >= new_xlim[0]) & (
                    flight_data["Session Time"] <= new_xlim[1]
                )
                for col in left_cols:
                    if col in flight_data.columns:
                        ydata_left.extend(flight_data.loc[mask, col].values.tolist())
                if ydata_left:
                    new_ylim_left = (min(ydata_left), max(ydata_left))
                else:
                    new_ylim_left = ax_left.get_ylim()
            else:
                mask = (flight_data["Session Time"] >= new_xlim[0]) & (
                    flight_data["Session Time"] <= new_xlim[1]
                )
                ydata_left = flight_data.loc[mask, left_signal].values
                if len(ydata_left) > 0:
                    new_ylim_left = (min(ydata_left), max(ydata_left))
                else:
                    new_ylim_left = ax_left.get_ylim()
        else:
            new_ylim_left = ax_left.get_ylim()

        # --- Compute new Y-limits for right axis based on the selected right signal(s) ---
        if right_signal and right_signal != "None":
            if right_signal == "CHT":
                right_cols = [
                    "CHT 1 (deg F)",
                    "CHT 2 (deg F)",
                    "CHT 3 (deg F)",
                    "CHT 4 (deg F)",
                ]
                ydata_right = []
                mask = (flight_data["Session Time"] >= new_xlim[0]) & (
                    flight_data["Session Time"] <= new_xlim[1]
                )
                for col in right_cols:
                    if col in flight_data.columns:
                        ydata_right.extend(flight_data.loc[mask, col].values.tolist())
                if ydata_right:
                    new_ylim_right = (min(ydata_right), max(ydata_right))
                else:
                    new_ylim_right = ax_right.get_ylim()
            elif right_signal == "EGT":
                right_cols = [
                    "EGT 1 (deg F)",
                    "EGT 2 (deg F)",
                    "EGT 3 (deg F)",
                    "EGT 4 (deg F)",
                ]
                ydata_right = []
                mask = (flight_data["Session Time"] >= new_xlim[0]) & (
                    flight_data["Session Time"] <= new_xlim[1]
                )
                for col in right_cols:
                    if col in flight_data.columns:
                        ydata_right.extend(flight_data.loc[mask, col].values.tolist())
                if ydata_right:
                    new_ylim_right = (min(ydata_right), max(ydata_right))
                else:
                    new_ylim_right = ax_right.get_ylim()
            else:
                mask = (flight_data["Session Time"] >= new_xlim[0]) & (
                    flight_data["Session Time"] <= new_xlim[1]
                )
                ydata_right = flight_data.loc[mask, right_signal].values
                if len(ydata_right) > 0:
                    new_ylim_right = (min(ydata_right), max(ydata_right))
                else:
                    new_ylim_right = ax_right.get_ylim()
        else:
            new_ylim_right = ax_right.get_ylim()

        # Avoid identical y-limits (singularity), expand by small epsilon if needed
        def fix_ylim(lim):
            if lim[0] == lim[1]:
                eps = 1e-6
                return (lim[0] - eps, lim[1] + eps)
            else:
                return (lim[0] - (lim[0] * 0.01), lim[1] + (lim[1] * 0.01))
            return lim

        new_ylim_left = fix_ylim(new_ylim_left)
        new_ylim_right = fix_ylim(new_ylim_right)
        ax_left.set_xlim(*new_xlim)
        ax_left.set_ylim(*new_ylim_left)
        ax_right.set_xlim(*new_xlim)
        ax_right.set_ylim(*new_ylim_right)
        figure_canvas.draw_idle()

    # RectangleSelector for zoom
    # Connect to the axes, set interactive=True, do not use useblit for TkAgg
    selector = RectangleSelector(
        ax_left,  # connect to the axes, not the figure canvas
        on_select,
        button=[1],  # Left mouse button
        spancoords="data",
        interactive=False,
        props=dict(facecolor="blue", alpha=0.3),
    )
    # Make sure selector is not garbage-collected: attach to the figure or canvas
    # Attach to the underlying Tk widget so it persists as long as the plot is visible
    widget.selector = selector
    # Explicitly draw the canvas after creating the selector to ensure it appears
    figure_canvas.draw_idle()

    # Add left double-click to reset zoom
    def on_press(event):
        # Respond to left double-clicks (button 1) anywhere on the figure
        if event.dblclick and event.button == 1:
            # Reset both axes (left and right) to full x/y range
            x_min = flight_data["Session Time"].min()
            x_max = flight_data["Session Time"].max()
            # Left axis
            ax_left.set_xlim(x_min, x_max)
            ax_left.set_ylim(ylim_left)
            # Right axis
            ax_right.set_xlim(x_min, x_max)
            ax_right.set_ylim(ylim_right)
            figure_canvas.draw_idle()
            # Hide rectangle after selection so it does not block right-clicks
            selector.set_visible(False)

    # Connect to button_press_event to detect left double-clicks
    figure_canvas.mpl_connect("button_press_event", on_press)


def identify_flight_phases_for_selected_flight(df, flight_id):
    """
    Identify flight phases for the selected flight and print the first timestamp of each phase.
    """

    # Filter the selected flight
    flight_df = df[df["Flight ID"] == flight_id].copy()
    if flight_df.empty:
        print("No data for selected flight.")
        return None

    # Signals
    rpm = flight_df["RPM"].values
    mp = flight_df["Manifold Pressure (inHg)"].values
    ff = flight_df["Fuel Flow 1 (gal/hr)"].values
    pp = flight_df["Percent Power"].values
    gs = flight_df["Ground Speed (knots)"].values
    vs = flight_df["Vertical Speed (ft/min)"].values

    # Rates
    dgs = np.gradient(gs)
    phases = []

    for i in range(len(flight_df)):
        if gs[i] < 25:
            phase = "Taxi"
        elif rpm[i] > 1800 and gs[i] < 5:
            phase = "Runup"
        elif rpm[i] > 2550 and mp[i] > 24 and ff[i] > 12 and pp[i] > 85:
            phase = "Takeoff"
        elif vs[i] > 400:
            phase = "Climb"
        elif abs(vs[i]) < 100 and gs[i] > 90:
            phase = "Cruise"
        elif vs[i] < -300:
            phase = "Descent"
        elif gs[i] < 50 and dgs[i] < 0 and mp[i] < 12:
            phase = "Landing"
        else:
            phase = "Taxi"

        phases.append(phase)

    flight_df["Flight Phase"] = phases

    # Print first occurrence of each phase
    printed = set()
    print(f"\nFlight Phase Summary for flight: {flight_id}")
    for idx, row in flight_df.iterrows():
        phase = row["Flight Phase"]
        if phase not in printed:
            timestamp = (
                row["Session Time"] if "Session Time" in flight_df.columns else idx
            )
            print(f"{phase} begins at timestamp: {timestamp}")
            printed.add(phase)

    return flight_df


def main_layout():
    return [
        [
            sg.Text("Input CSV File:", font=("Arial", 16), size=(16, 1)),
            sg.Input(
                key="-FILE-",
                enable_events=True,
                readonly=True,
                size=(60, 1),
                font=("Arial", 16),
                disabled_readonly_background_color="white",
            ),
            sg.FileBrowse(
                file_types=(("CSV Files", "*.csv"),),
                font=("Arial", 16),
                initial_folder="/Users/GFahmy/Documents/projects/dynon",
            ),
            sg.Text("", font=("Arial", 16), expand_x=True),
        ],
        [
            sg.Text("Input CSV Folder:", font=("Arial", 16), size=(16, 1)),
            sg.Input(
                key="-FOLDER-",
                enable_events=True,
                readonly=True,
                size=(60, 1),
                font=("Arial", 16),
                disabled_readonly_background_color="white",
            ),
            sg.FolderBrowse(
                button_text="Browse",
                key="folder",
                font=("Arial", 16),
                initial_folder="/Users/GFahmy/Documents/projects/dynon/clean_flights",
            ),
            sg.Text("", font=("Arial", 16), expand_x=True),
        ],
        [sg.HorizontalSeparator()],
        [
            sg.Text("Select Flight ID:", font=("Arial", 22)),
            sg.Combo(
                [],
                key="-FLIGHT-",
                readonly=True,
                enable_events=True,
                font=("Arial", 18),
                size=(30, 1),
            ),
            sg.Text(expand_x=True),
            sg.Button("Export Flights", font=("Arial", 16)),
            sg.Button("Multi-Flight Plot", font=("Arial", 16)),
            sg.Button("Exit", font=("Arial", 16)),
        ],
        [sg.HorizontalSeparator()],
        [
            sg.Text("Filters:", font=("Arial", 16)),
            sg.Combo([], key="-FILTER_COL-", size=(25, 1), font=("Arial", 14)),
            sg.Combo(
                [">=", "<=", ">", "<", "="],
                key="-FILTER_OP-",
                size=(5, 1),
                font=("Arial", 14),
                default_value=">=",
            ),
            sg.Input(key="-FILTER_VAL-", size=(10, 1), font=("Arial", 14)),
            sg.Button("Add Filter", font=("Arial", 14)),
            sg.Button("Clear Filters", font=("Arial", 14)),
            sg.Button("Remove Selected", font=("Arial", 14)),
        ],
        [sg.Listbox(values=[], key="-FILTER_LIST-", size=(50, 4), font=("Arial", 12))],
        [sg.HorizontalSeparator()],
        [
            sg.Text(
                "Flight Summary: ",
                font=("Arial", 18),
            ),
            sg.Text(expand_x=True),
            sg.Text(
                "Start",
                font=("Arial", 16),
            ),
            sg.Input(
                key="-START_MANUEVER-",
                size=(10, 1),
                font=("Arial", 16),
            ),
            sg.Text(
                "End",
                font=("Arial", 16),
            ),
            sg.Input(
                key="-END_MANUEVER-",
                size=(10, 1),
                font=("Arial", 16),
            ),
            sg.Button(
                "Airspeed Calibration",
                key="-AIRSPEED_CALIBRATION-",
                font=("Arial", 16),
            ),
            sg.Button(
                "Gami Spread",
                key="-GAMI_SPREAD-",
                font=("Arial, 16"),
            ),
        ],
        [
            sg.Text(size=(50, 10), key="-SUMMARY-", font=("Arial", 14)),
            sg.Text(expand_x=True),
            sg.Text(size=(50, 8), key="-ASI_CALIBRATION-", font=("Arial", 14)),
        ],
        [sg.HorizontalSeparator()],
        [
            sg.Column(
                expand_x=True,
                expand_y=True,
                layout=[
                    [
                        sg.Text("Left Axis Signal:", font=("Arial", 16)),
                        sg.Combo(
                            [],
                            key="-LEFT_SIGNAL_1-",
                            readonly=True,
                            enable_events=True,
                            size=(30, 1),
                            font=("Arial", 16),
                        ),
                        sg.Text(expand_x=True),
                        sg.Text("Right Axis Signal:", font=("Arial", 16)),
                        sg.Combo(
                            [],
                            key="-RIGHT_SIGNAL_1-",
                            readonly=True,
                            enable_events=True,
                            size=(30, 1),
                            font=("Arial", 16),
                        ),
                    ],
                    [sg.HorizontalSeparator()],
                    [
                        sg.Canvas(key="-CANVAS_1-", expand_x=True, expand_y=True),
                    ],
                ],
            ),
            sg.VerticalSeparator(),
            sg.Column(
                expand_x=True,
                expand_y=True,
                layout=[
                    [
                        sg.Text("Flight Path", font=("Arial", 16), expand_x=True),
                    ],
                    [sg.HorizontalSeparator()],
                    [
                        sg.Canvas(key="-CANVAS_2-", expand_x=True, expand_y=True),
                    ],
                ],
            ),
        ],
        [
            sg.HorizontalSeparator(),
        ],
        [
            sg.Text(
                "No file loaded",
                key="-STATUS-",
                font=("Arial", 14),
                expand_x=True,
                justification="left",
            )
        ],
    ]


def apply_filters(df, filters):
    filtered_df = df.copy()
    for col, op, val in filters:
        if col not in filtered_df.columns:
            continue

        try:
            series = pd.to_numeric(filtered_df[col], errors="coerce")
            val_num = float(val)

            if op == ">=":
                filtered_df = filtered_df[series >= val_num]
            elif op == "<=":
                filtered_df = filtered_df[series <= val_num]
            elif op == ">":
                filtered_df = filtered_df[series > val_num]
            elif op == "<":
                filtered_df = filtered_df[series < val_num]
            elif op == "=":
                filtered_df = filtered_df[series == val_num]

        except:
            # Fallback for non-numeric comparisons
            if op == "=":
                filtered_df = filtered_df[filtered_df[col] == val]

    return filtered_df


def main():
    sg.set_options(icon=base64.b64encode(open(str("paint_logo.png"), "rb").read()))
    df = None
    flight_stats = None
    flight_ids = []
    available_signals = []
    active_filters = []

    window = sg.Window(
        "Dynon Flight Analyzer", layout=main_layout(), resizable=True, finalize=True
    )
    window.maximize()

    while True:
        event, values = window.read()
        if event in (sg.WINDOW_CLOSED, "Exit"):
            break

        if event == "-GAMI_SPREAD-":
            flight_id = values["-FLIGHT-"]

            if values["-START_MANUEVER-"] and values["-END_MANUEVER-"]:
                try:
                    start_time = float(values["-START_MANUEVER-"])
                    end_time = float(values["-END_MANUEVER-"])
                except:
                    print("Invalid manual inputs.")
            else:
                start_time, end_time = find_gami_window(df, flight_id)

            flight_data = df[df["Flight ID"] == flight_id].copy().fillna(0)

            gami_spread(
                flight_data,
                start_time=start_time,
                end_time=end_time,
            )
        # --- Handle file selection and load ---
        if (event == "-FILE-" and values["-FILE-"]) or (
            event == "-FOLDER-" and values["-FOLDER-"]
        ):
            filename = values["-FILE-"]
            folder = values["-FOLDER-"]

            # Show loading spinner
            sg.popup_animated(
                sg.DEFAULT_BASE64_LOADING_GIF,
                message="Loading file...",
                time_between_frames=50,
            )
            window.refresh()
            if filename:
                df_loaded = load_data(filename)
            if folder:
                df_loaded = load_data(folder, folder=True)
            if df_loaded is None:
                sg.popup_animated(None)
                sg.popup_error("Failed to load file.")
                continue

            df = process_flights(df_loaded)

            # --- Multi-flight scatter plotting support ---
            if folder:
                df["Flight ID"] = df["Flight ID"].fillna("Unknown")

            # --- MPG (nautical miles per gallon) calculation ---
            # Ensure numeric conversion for "Ground Speed (knots)" and "Fuel Flow"
            if "Ground Speed (knots)" in df.columns:
                df["Ground Speed (knots)"] = pd.to_numeric(
                    df["Ground Speed (knots)"], errors="coerce"
                ).fillna(0)
            # Try both "Fuel Flow" and "Fuel Flow 1 (gal/hr)" as possible columns
            if "Total Fuel Flow (gal/hr)" in df.columns:
                df["Total Fuel Flow (gal/hr)"] = pd.to_numeric(
                    df["Total Fuel Flow (gal/hr)"], errors="coerce"
                ).fillna(0)
            elif "Fuel Flow 1 (gal/hr)" in df.columns:
                df["Total Fuel Flow (gal/hr)"] = pd.to_numeric(
                    df["Fuel Flow 1 (gal/hr)"], errors="coerce"
                ).fillna(0)
            # Calculate MPG (nautical miles per gallon)
            if (
                "Ground Speed (knots)" in df.columns
                and "Total Fuel Flow (gal/hr)" in df.columns
            ):
                df["MPG"] = df["Ground Speed (knots)"] / df["Total Fuel Flow (gal/hr)"]
                df["MPG"] = (
                    df["MPG"].replace([float("inf"), -float("inf")], 0).fillna(0)
                )
            else:
                df["MPG"] = 0

            # Stop loading spinner
            sg.popup_animated(None)

            # Update status bar with current file
            window["-STATUS-"].update(f"Current File: {filename}")

            flight_stats = df.groupby("Flight ID").agg(
                Start_Time=("Session Time", "min"),
                End_Time=("Session Time", "max"),
                Duration=("Session Time", lambda x: x.max() - x.min()),
                Data_Points=("Session Time", "count"),
                Engine_Run=("Engine Run", "first"),
                Max_RPM=("RPM L", "max"),
                Max_CHT=("Max CHT", "max"),
                Total_Fuel_Used=("Fuel Flow Integral", "max"),
            )
            # Compute average fuel flow (gal/hr)
            flight_stats["Avg_Fuel_Flow (gal/hr)"] = (
                flight_stats["Total_Fuel_Used"] * 3600
            ) / flight_stats["Duration"].replace(0, np.nan)
            flight_stats["Avg_Fuel_Flow (gal/hr)"] = flight_stats[
                "Avg_Fuel_Flow (gal/hr)"
            ].fillna(0)

            flight_ids = sorted(flight_stats[flight_stats["Engine_Run"]].index.tolist())

            # Identify numeric columns only
            numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()

            # Remove columns we still want to exclude manually
            excluded_cols = [
                "Unnamed: 103",
                "AP Yaw Force",
                "AP Yaw Position",
                "AP Yaw Slip (bool)",
                "Fuel Flow 1 (gal/hr)",
                "Fuel Flow 2 (gal/hr)",
                "FUEL PRESSURE (PSI)",
                "OIL TEMPERATURE (deg C)",
                "OIL TEMPERATURE (deg F)",
                "OIL PRESSURE (PSI)",
                "RPM L",
                "RPM R",
            ]

            # Remove useless columns (all zeros, NaNs, or constant values)
            valid_numeric_cols = []
            for col in numeric_cols:
                if col in excluded_cols:
                    continue

                series = pd.to_numeric(df[col], errors="coerce")

                # Drop NaNs for evaluation
                non_nan = series.dropna()

                if non_nan.empty:
                    continue

                # Skip if all values are zero
                if (non_nan == 0).all():
                    continue

                # Skip if all values are the same
                if non_nan.nunique() <= 1:
                    continue

                valid_numeric_cols.append(col)

            available_signals = sorted(valid_numeric_cols)

            # Add "MPG" to selectable/displayed columns if not present
            if "MPG" not in available_signals:
                available_signals.append("MPG")

            if "CHT" not in available_signals:
                available_signals.append("CHT")
            if "EGT" not in available_signals:
                available_signals.append("EGT")
            available_signals = sorted(available_signals)

            if "None" not in available_signals:
                available_signals = ["None"] + available_signals

            window["-FLIGHT-"].update(values=flight_ids)
            window["-LEFT_SIGNAL_1-"].update(values=available_signals)
            window["-RIGHT_SIGNAL_1-"].update(values=available_signals)
            window["-FILTER_COL-"].update(values=available_signals)

            # Auto-select the last flight and trigger load
            if flight_ids:
                last_flight = flight_ids[-1]
                window["-FLIGHT-"].update(value=last_flight)
                window.write_event_value("-FLIGHT-", last_flight)

        if event == "Add Filter":
            col = values["-FILTER_COL-"]
            op = values["-FILTER_OP-"]
            val = values["-FILTER_VAL-"]
            if col and val and op:
                try:
                    val = float(val)
                except:
                    pass
                active_filters.append((col, op, val))
                window["-FILTER_LIST-"].update(
                    values=[f"{c} {o} {v}" for c, o, v in active_filters]
                )

        if event == "Clear Filters":
            active_filters = []
            window["-FILTER_LIST-"].update(values=[])

            # Set default signals
            if "CHT" in available_signals:
                window["-LEFT_SIGNAL_1-"].update(value="CHT")
                window.write_event_value(key="-LEFT_SIGNAL_1-", value="CHT")

            if "EGT" in available_signals:
                window["-RIGHT_SIGNAL_1-"].update(value="EGT")
                window.write_event_value(key="-RIGHT_SIGNAL_1-", value="EGT")

            if flight_ids:
                window["-FLIGHT-"].update(value=flight_ids[-1])
                window.write_event_value("-FLIGHT-", flight_ids[-1])

        if event == "Remove Selected":
            selected = values["-FILTER_LIST-"]
            if selected:
                # Remove selected filters
                active_filters = [
                    f for f in active_filters if f"{f[0]} {f[1]} {f[2]}" not in selected
                ]
                window["-FILTER_LIST-"].update(
                    values=[f"{c} {o} {v}" for c, o, v in active_filters]
                )

        if event == "Export Flights":
            folder = sg.popup_get_folder("Select folder to save flight CSV files")
            if folder and df is not None:
                save_flights_to_csv(df, folder)
                sg.popup("Flights exported successfully.")

        if (
            event == "-FLIGHT-"
            and values["-FLIGHT-"] is not None
            and flight_stats is not None
        ):
            fid = values["-FLIGHT-"]
            stats = flight_stats.loc[fid]
            total_fuel = stats.get("Total_Fuel_Used", 0)
            avg_flow = stats.get("Avg_Fuel_Flow (gal/hr)", 0)

            summary_text = (
                f"Flight ID: {fid}\n"
                f"Start Time: {stats['Start_Time']}\n"
                f"End Time: {stats['End_Time']}\n"
                f"Duration: {stats['Duration']} sec - {round(stats['Duration'] / 60 , 2)} min\n"
                f"Data Points: {stats['Data_Points']}\n"
                f"Max RPM: {stats['Max_RPM']}\n"
                f"Max CHT: {stats['Max_CHT']}\n"
                f"Total Fuel Used: {total_fuel:.2f} gal\n"
                f"Avg Fuel Flow: {avg_flow:.2f} gal/hr\n"
            )
            window["-SUMMARY-"].update(summary_text)
            identify_flight_phases_for_selected_flight(df, fid)
            window["-LEFT_SIGNAL_1-"].update(value="CHT")
            window["-RIGHT_SIGNAL_1-"].update(value="EGT")
            window.write_event_value("-LEFT_SIGNAL_1-", "CHT")

        if event == "Multi-Flight Plot":
            if df is None or not values["-FOLDER-"]:
                sg.popup("Please load a folder of flights first.")
                continue

            left_signal = values["-LEFT_SIGNAL_1-"]
            right_signal = values["-RIGHT_SIGNAL_1-"]

            if left_signal == "None" or right_signal == "None":
                sg.popup("Select valid signals for both axes.")
                continue

            fig, ax = plt.subplots()

            filtered_df = apply_filters(df, active_filters)
            scatter_map = {}
            for fid, group in filtered_df.groupby("Flight ID"):
                if fid is None:
                    continue
                sc = ax.scatter(
                    group[left_signal], group[right_signal], label=str(fid), alpha=0.4
                )
                scatter_map[str(fid)] = sc

            ax.set_xlabel(left_signal)
            ax.set_ylabel(right_signal)
            ax.set_title("Multi-Flight Scatter Plot")
            legend = ax.legend(fontsize=6)

            # Enable legend click to toggle visibility
            for legend_entry in legend.legend_handles:
                legend_entry.set_picker(True)

            def on_pick(event):
                legend_handle = event.artist
                label = legend_handle.get_label()

                if label in scatter_map:
                    scatter = scatter_map[label]
                    visible = not scatter.get_visible()
                    scatter.set_visible(visible)

                    # Fade legend entry when hidden
                    legend_handle.set_alpha(1.0 if visible else 0.2)

                    fig.canvas.draw_idle()

            fig.canvas.mpl_connect("pick_event", on_pick)

            # Show in popup window
            plot_window = sg.Window(
                "Multi-Flight Plot",
                [
                    [
                        sg.Canvas(
                            key="-PLOT_CANVAS-",
                            expand_x=True,
                            expand_y=True,
                        )
                    ]
                ],
                finalize=True,
                resizable=True,
            )

            canvas_elem = plot_window["-PLOT_CANVAS-"]
            figure_canvas = FigureCanvasTkAgg(fig, canvas_elem.TKCanvas)
            figure_canvas.draw()

            plot_widget = figure_canvas.get_tk_widget()
            plot_widget.pack(side="top", fill="both", expand=1)

            # Add matplotlib navigation toolbar
            toolbar = NavigationToolbar2Tk(figure_canvas, canvas_elem.TKCanvas)
            toolbar.update()
            toolbar.pack(side="bottom", fill="x")

            while True:
                ev, _ = plot_window.read()
                if ev in (sg.WINDOW_CLOSED, "Exit"):
                    break

            plot_window.close()

        if event in ("-LEFT_SIGNAL_1-", "-RIGHT_SIGNAL_1-", "-FLIGHT-"):
            flight_id = values["-FLIGHT-"]
            left_signal_1 = values["-LEFT_SIGNAL_1-"]
            right_signal_1 = values["-RIGHT_SIGNAL_1-"]

            if df is None or flight_id is None:
                continue

            filtered_df = apply_filters(df, active_filters)
            plot_flight(
                filtered_df,
                flight_id,
                left_signal_1,
                right_signal_1,
                window["-CANVAS_1-"].TKCanvas,
            )

            # --- Plot 2D GPS Ground Track on OpenStreetMap using contextily ---
            if "Latitude (deg)" in df.columns and "Longitude (deg)" in df.columns:
                flight_data = df[df["Flight ID"] == flight_id]
                lat = flight_data["Latitude (deg)"].values
                lon = flight_data["Longitude (deg)"].values
                session_time_gt = flight_data["Session Time"].values

                fig2, ax2 = plt.subplots()

                # Plot using real latitude/longitude so a map can be used
                lat_vals = lat
                lon_vals = lon

                # Color by Indicated Airspeed if available
                if "Ground Speed (knots)" in flight_data.columns:
                    ias = flight_data["Ground Speed (knots)"].values
                    sc = ax2.scatter(
                        lon_vals,
                        lat_vals,
                        c=ias,
                        cmap="gist_ncar",
                        s=6,
                        vmin=0,
                        vmax=200,
                    )
                    cbar = fig2.colorbar(sc, ax=ax2, pad=0.1, drawedges=True)
                    cbar.set_label("Ground Speed (knots)")
                else:
                    ax2.plot(lon_vals, lat_vals)

                ax2.set_xlabel("Longitude")
                ax2.set_ylabel("Latitude")
                ax2.set_title("GPS Ground Track on Map")

                # Add OpenStreetMap basemap
                try:
                    ctx.add_basemap(
                        ax2, crs="EPSG:4326", source=ctx.providers.OpenStreetMap.Mapnik
                    )
                except Exception:
                    pass

                ax2.grid(True)

                # --- Make map square and add margin so it is not tightly cropped to the flight path ---
                if len(lat_vals) > 0:
                    min_lat, max_lat = float(min(lat_vals)), float(max(lat_vals))
                    min_lon, max_lon = float(min(lon_vals)), float(max(lon_vals))

                    lat_span = max_lat - min_lat
                    lon_span = max_lon - min_lon

                    # Expand spans slightly so map is not tightly zoomed to path
                    padding_factor = 0.25
                    lat_span *= 1 + padding_factor
                    lon_span *= 1 + padding_factor

                    # Force square map by using the larger span
                    span = max(lat_span, lon_span)

                    center_lat = (min_lat + max_lat) / 2
                    center_lon = (min_lon + max_lon) / 2

                    ax2.set_xlim(center_lon - span / 2, center_lon + span / 2)
                    ax2.set_ylim(center_lat - span / 2, center_lat + span / 2)

                    # Ensure the axes box itself is square
                    ax2.set_box_aspect(1)

                # Moving position marker using airplane icon
                (ground_track_marker,) = ax2.plot(
                    [lon_vals[0]],
                    [lat_vals[0]],
                    marker="$✈$",
                    markersize=14,
                    linestyle="None",
                    zorder=10,
                )

                # Clear existing canvas
                for child in window["-CANVAS_2-"].TKCanvas.winfo_children():
                    child.destroy()

                canvas2 = FigureCanvasTkAgg(fig2, window["-CANVAS_2-"].TKCanvas)
                canvas2.draw()

                map_widget = canvas2.get_tk_widget()
                map_widget.pack(side="top", fill="both", expand=1)

                # Add matplotlib navigation toolbar for zoom/pan
                toolbar = NavigationToolbar2Tk(canvas2, window["-CANVAS_2-"].TKCanvas)
                toolbar.update()
                toolbar.pack(side="bottom", fill="x")

                # Store globals for syncing
                ground_track["lat"] = lat_vals
                ground_track["lon"] = lon_vals
                ground_track["time"] = session_time_gt
                ground_track["marker"] = ground_track_marker
                ground_track["canvas"] = canvas2

        if event == "-AIRSPEED_CALIBRATION-":
            flight_id = values["-FLIGHT-"]
            flight_data = df[df["Flight ID"] == flight_id].copy().fillna(0)
            as_cal_df = flight_data.rename(
                columns={
                    "Session Time": "session_time",
                    "Indicated Airspeed (knots)": "ias",
                    "Pressure Altitude (ft)": "press_alt",
                    "Magnetic Heading (deg)": "hdg",
                    "Ground Speed (knots)": "gps_gs",
                    "Ground Track (deg)": "gps_trk",
                    "OAT (deg F)": "oat",
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
                "Wind Speed (knots)",
                "Wind Direction (deg)",
            ]

            as_cal_df = as_cal_df[essential_columns].copy()

            as_cal_df = as_cal_df.dropna()
            as_cal_df = as_cal_df[as_cal_df["ias"] > 55.0]

            as_cal_df = as_cal_df.reset_index(drop=True)
            output = analyze_flight_data(
                as_cal_df,
                start_time=float(values["-START_MANUEVER-"]),
                end_time=float(values["-END_MANUEVER-"]),
                show_plot=False,
            )
            start_time = float(values["-START_MANUEVER-"])
            end_time = float(values["-END_MANUEVER-"])

            # Filter the DataFrame to only include the selected maneuver window
            maneuver_df = as_cal_df[
                (as_cal_df["session_time"] >= start_time)
                & (as_cal_df["session_time"] <= end_time)
            ]

            # cal_df = maneuver_df[
            #     ["press_alt", "ias", "hdg", "gps_gs", "gps_trk"]
            # ].copy()
            # cal_df.to_csv("~/Documents/projects/dynon/clean_flights/cal_df.csv")

            avg_wind_speed = (
                maneuver_df["Wind Speed (knots)"].mean()
                if not maneuver_df.empty and "Wind Speed (knots)" in maneuver_df.columns
                else float("nan")
            )
            avg_wind_dir = (
                maneuver_df["Wind Direction (deg)"].mean()
                if not maneuver_df.empty
                and "Wind Direction (deg)" in maneuver_df.columns
                else float("nan")
            )

            asi_calibration_summary = (
                f"Data Points Analyzed:  {output['analyzed_data_points']}\n"
                f"CAS Correction:        {output['calibrated_airspeed_correction_kts']} kts\n"
                f"Airspeed Error:        {output['airspeed_error_kts']} kts\n"
                f"HDG Correction:        {output['calibrated_heading_correction_deg']} deg\n"
                f"Wind Direction:        {output['wind_direction_deg']} deg (Avg: {avg_wind_dir:.1f} deg)\n"
                f"Wind Speed:            {output['wind_speed_kts']} kts (Avg: {avg_wind_speed:.1f} kts)\n"
                f"Uncorr. Avg TAS:       {output['uncorrected_average_true_airspeed_kts']} kts\n"
                f"Corrected Avg TAS:     {output['corrected_average_true_airspeed_kts']} kts\n"
            )
            window["-ASI_CALIBRATION-"].update(asi_calibration_summary)

    window.close()
    return df


if __name__ == "__main__":
    df = main()
