import calendar
import csv
import json
import logging
import os
import re
import socket
import sqlite3
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from functools import wraps
from io import StringIO
from logging.handlers import RotatingFileHandler
from xml.dom import minidom

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup
from flask import (
    Flask,
    Response,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

from src.airnav_route import fetch_route
from src.airspeed_calibration import analyze_flight_data
from src.fuel_prices import scrape_airnav_to_json
from src.sw_db_updates import download_dynon_databases_only

CWD_PATH = os.path.abspath(os.path.dirname(__file__))
print(CWD_PATH)
app = Flask(__name__)
app.secret_key = "827311a9a172036c2f5ebaa0cb68c0ed90b037d30cccf15097627ec1759eee61"
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

# --- Login attempt logging (split logs) ---
LOG_DIR = os.path.join(CWD_PATH if "CWD_PATH" in globals() else os.getcwd(), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

log_formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | ip=%(ip)s | user=%(user)s | status=%(status)s | ua=%(ua)s | msg=%(message)s"
)

# Define the pins based on your vertical_power.py data
VPX_PINS = [
    {"id": "Starter", "name": "Starter", "breaker": 10, "sw": "AlwaysOn"},
    {"id": "EFIS", "name": "EFIS PFD", "breaker": 5, "sw": "AlwaysOn"},
    {"id": "Alternator", "name": "Alternator Field", "breaker": 5, "sw": "Switch1"},
    {"id": "A5_1", "name": "Boost pump", "breaker": 5, "sw": "Switch4"},
    {"id": "A5_2", "name": "SV-INT-2S - BOSE", "breaker": 2, "sw": "Switch3"},
    {"id": "A5_3", "name": "Garmin G5", "breaker": 2, "sw": "Switch3"},
    {"id": "A5_4", "name": "E-Mag/P-Mag 1", "breaker": 3, "sw": "Switch9"},
    {"id": "A5_5", "name": "E-Mag/P-Mag 2", "breaker": 3, "sw": "Switch10"},
    {"id": "A5_6", "name": "Taxi Light Left", "breaker": 5, "sw": "Switch6"},
    {"id": "A5_7", "name": "Taxi Light Right", "breaker": 5, "sw": "Switch6"},
    {"id": "A5_8", "name": "Hobbs meter", "breaker": 2, "sw": "Switch3"},
    {"id": "A5_9", "name": "SV-XPNDR/SV-ADSB", "breaker": 3, "sw": "Switch3"},
    {"id": "A5_10", "name": "Nav Light Left", "breaker": 5, "sw": "Switch7"},
    {"id": "A5_11", "name": "EFIS MFD", "breaker": 5, "sw": "Switch3"},
    {"id": "A5_12", "name": "Nav Light Right", "breaker": 5, "sw": "Switch7"},
    {"id": "A10_1", "name": "trim AP Power", "breaker": 5, "sw": "Switch3"},
    {"id": "A10_2", "name": "Left Landing Lt", "breaker": 7, "sw": "Switch5"},
    {"id": "A10_3", "name": "Right Landing Lt", "breaker": 7, "sw": "Switch5"},
    {"id": "A10_4", "name": "Strobe Left", "breaker": 7, "sw": "Switch8"},
    {"id": "A10_5", "name": "Strobe Right", "breaker": 7, "sw": "Switch8"},
    {"id": "A10_6", "name": "SV-COM-X25", "breaker": 7, "sw": "Switch3"},
    {"id": "A15_1", "name": "AP Servos", "breaker": 10, "sw": "Switch3"},
    {"id": "A15_3", "name": "Eyeball lights", "breaker": 10, "sw": "AlwaysOn"},
    {"id": "A3_1", "name": "ELT", "breaker": 10, "sw": "AlwaysOn"},
]


def _create_logger(name, filename):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = RotatingFileHandler(
            os.path.join(LOG_DIR, filename), maxBytes=5 * 1024 * 1024, backupCount=5
        )
        handler.setFormatter(log_formatter)
        logger.addHandler(handler)

    return logger


login_success_logger = _create_logger("login_success", "login_success.log")
login_failure_logger = _create_logger("login_failure", "login_failure.log")
login_security_logger = _create_logger("login_security", "login_security.log")


app.config["SESSION_PERMANENT"] = False
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

# DB_PATH = CWD_PATH + "/src/maintenance.db"
DB_PATH = CWD_PATH + "/../maintenance.db"
print(DB_PATH)
DEBUG = True
# --- Directory for saving processed dataframes ---
SAVE_DIR = "clean_flights"
os.makedirs(SAVE_DIR, exist_ok=True)

# Constants
OIL_CHANGE_INTERVAL_HOURS = 25
MAINTENANCE_RULES = {
    "Condition Inspection": {"type": "date", "days": 365},
    "ELT Test": {"type": "date", "days": 90},
    "ELT Batteries": {"type": "date", "days": 365 * 7},
    "ELT Registration": {"type": "date", "days": 365 * 2},
    "Nav Data Update": {"type": "date", "days": 28},
    "Transponder Check": {"type": "date", "days": 365 * 2},
    "Oil Change": {"type": "tach", "hours": OIL_CHANGE_INTERVAL_HOURS},
}

# In-Memory Cache for Nav Data
NAV_CACHE = {"data": None, "timestamp": 0}
NAV_CACHE_TTL = 6 * 60 * 60
NAV_CACHE_LOCK = threading.Lock()

# --- Login Rate Limiting (simple in-memory) ---
LOGIN_ATTEMPTS = {}
LOGIN_LOCK = threading.Lock()
MAX_ATTEMPTS = 3
BLOCK_WINDOW_SECONDS = 300  # 5 minutes
BAN_THRESHOLD = 3  # number of times hitting rate limit before ban
BAN_DURATION_SECONDS = 3600  # 1 hour


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


def git_push_data():
    script_path = "/home/georgefahmy/Documents/n890gf_tracker/push.sh"
    try:
        result = subprocess.Popen(["/bin/bash", script_path], start_new_session=True)
        if result.returncode == 0:
            return f"Push started - {result.stdout}", 200
        else:
            return f"Error - {result.stderr}", 500
    except Exception as e:
        return f"Server Error: {str(e)}", 500


def validate_float(value, default=0.0):
    if value is None:
        return default
    if isinstance(value, str) and value.strip().lower() in ["none", "null", ""]:
        return default
    try:
        return round(float(value), 1)
    except (ValueError, TypeError):
        return default


def parse_date_safe(value):
    if not value:
        return datetime.today().strftime("%Y-%m-%d")
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return datetime.today().strftime("%Y-%m-%d")


def sanitize_for_json(obj):
    """
    Recursively replace NaN / inf / None values with 0 for safe JSON serialization.
    """
    import math

    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_for_json(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0
        return obj
    if obj is None:
        return 0
    return obj


def recompute_flight_history(conn):
    cur = conn.execute(
        "SELECT id, hobbs, tach FROM flight_log ORDER BY date ASC, id ASC"
    )
    rows = cur.fetchall()
    prev_hobbs, prev_tach = None, None

    for r in rows:
        row_id, hobbs, tach = (
            r["id"],
            validate_float(r["hobbs"]),
            validate_float(r["tach"]),
        )
        hobbs_delta = round(hobbs - prev_hobbs, 1) if prev_hobbs is not None else 0.0
        tach_delta = round(tach - prev_tach, 1) if prev_tach is not None else 0.0
        if hobbs_delta < 0:
            hobbs_delta = 0.0
        if tach_delta < 0:
            tach_delta = 0.0

        conn.execute(
            "UPDATE flight_log SET hobbs_delta = ?, tach_delta = ? WHERE id = ?",
            (hobbs_delta, tach_delta, row_id),
        )
        prev_hobbs, prev_tach = hobbs, tach
    conn.commit()


def check_auto_maintenance(conn):
    cur = conn.execute(
        "SELECT MAX(tach_time) FROM maintenance_entries WHERE recurrent_item='Oil Change'"
    )
    last_row = cur.fetchone()
    last = validate_float(last_row[0] if last_row and last_row[0] else 0)

    cur2 = conn.execute("SELECT MAX(tach) FROM flight_log")
    curr_row = cur2.fetchone()
    current = validate_float(curr_row[0] if curr_row and curr_row[0] else 0)

    if current - last >= OIL_CHANGE_INTERVAL_HOURS:
        conn.execute(
            "INSERT INTO maintenance_entries (date, tach_time, airframe_time, notes, recurrent_item, category) VALUES (date('now'), ?, ?, ?, ?, ?)",
            (
                current,
                current,
                "AUTO",
                f"Auto oil change reminder (>{OIL_CHANGE_INTERVAL_HOURS} hrs)",
                "Oil Change",
                "Engine",
            ),
        )
        conn.commit()


def calculate_overdue(conn):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT recurrent_item, MAX(date) FROM maintenance_entries GROUP BY recurrent_item"
    )
    rows = cursor.fetchall()
    today = datetime.today().date()
    overdue_items = []

    cursor.execute("SELECT MAX(tach) FROM flight_log")
    tach_row = cursor.fetchone()
    current_tach = validate_float(tach_row[0] if tach_row and tach_row[0] else 0)

    for item, last_date in rows:
        if not item or not last_date or item == "None":
            continue
        rule = MAINTENANCE_RULES.get(item)
        if not rule:
            continue
        try:
            last_dt = datetime.strptime(parse_date_safe(last_date), "%Y-%m-%d").date()
        except:
            continue

        if rule["type"] == "date" and today > (last_dt + timedelta(days=rule["days"])):
            overdue_items.append(item)
        elif rule["type"] == "tach":
            cursor.execute(
                "SELECT MAX(tach_time) FROM maintenance_entries WHERE recurrent_item=?",
                (item,),
            )
            last_tach_row = cursor.fetchone()
            last_tach = validate_float(
                last_tach_row[0] if last_tach_row and last_tach_row[0] else 0
            )
            if current_tach > (last_tach + rule["hours"]):
                overdue_items.append(item)
    return overdue_items


def compute_nav_status(nav_date, date_aviation, date_obstacle, today):
    """
    Computes aviation and obstacle database status with early update grace window.
    """
    # Aviation cycle
    aviation_cycle_end = date_aviation + timedelta(days=28)
    aviation_grace_start = date_aviation - timedelta(days=3)

    # Obstacle cycle
    obstacle_cycle_end = date_obstacle + timedelta(days=56)
    obstacle_grace_start = date_obstacle - timedelta(days=3)

    aviation_status = (
        "Current"
        if (today < aviation_cycle_end and nav_date >= aviation_grace_start)
        else "Overdue"
    )

    obstacle_status = (
        "Current"
        if (today < obstacle_cycle_end and nav_date >= obstacle_grace_start)
        else "Overdue"
    )

    return aviation_status, obstacle_status


def _get_nav_database_status_live(conn):
    url = "https://dynonavionics.com/us-aviation-obstacle-data.php"
    aviation_status, obstacle_status = "--", "--"
    aviation_days_remaining, obstacle_days_remaining = None, None
    html = None

    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print("Requests fetch failed:", e)

    if html:
        try:
            soup = BeautifulSoup(html, "html.parser")
            spans = soup.find_all(string=lambda t: t and "Valid:" in t)
            if len(spans) >= 2:
                today = datetime.today().date()
                match_aviation = re.search(
                    r"([A-Za-z]+ \d{1,2})", spans[0].split("Valid:")[-1].strip()
                )
                match_obstacle = re.search(
                    r"([A-Za-z]+ \d{1,2})", spans[1].split("Valid:")[-1].strip()
                )

                date_aviation = (
                    datetime.strptime(
                        match_aviation.group(1) + f" {today.year}", "%B %d %Y"
                    ).date()
                    if match_aviation
                    else None
                )
                date_obstacle = (
                    datetime.strptime(
                        match_obstacle.group(1) + f" {today.year}", "%B %d %Y"
                    ).date()
                    if match_obstacle
                    else None
                )

                cursor = conn.cursor()
                cursor.execute(
                    "SELECT date FROM maintenance_entries WHERE recurrent_item='Nav Data Update' ORDER BY date DESC LIMIT 1"
                )
                nav_entry = cursor.fetchone()
                if nav_entry and nav_entry[0] and date_aviation and date_obstacle:
                    nav_date = datetime.strptime(
                        parse_date_safe(nav_entry[0]), "%Y-%m-%d"
                    ).date()
                    aviation_status, obstacle_status = compute_nav_status(
                        nav_date,
                        date_aviation,
                        date_obstacle,
                        today,
                    )
                else:
                    aviation_status = obstacle_status = "Overdue"

                if date_aviation:
                    aviation_days_remaining = (
                        (date_aviation + timedelta(days=28)) - today
                    ).days
                if date_obstacle:
                    obstacle_days_remaining = (
                        (date_obstacle + timedelta(days=56)) - today
                    ).days
        except Exception as e:
            print("Nav parsing failed:", e)

    return {
        "aviation_status": aviation_status,
        "obstacle_status": obstacle_status,
        "aviation_days_remaining": aviation_days_remaining,
        "obstacle_days_remaining": obstacle_days_remaining,
    }


def get_nav_database_status(conn):
    global NAV_CACHE
    now = time.time()
    with NAV_CACHE_LOCK:
        if NAV_CACHE["data"] and (now - NAV_CACHE["timestamp"] < NAV_CACHE_TTL):
            return NAV_CACHE["data"]
    live = _get_nav_database_status_live(conn)
    with NAV_CACHE_LOCK:
        NAV_CACHE["data"] = live
        NAV_CACHE["timestamp"] = now
    return live


def get_upcoming_maintenance(conn):
    cursor = conn.cursor()
    today = datetime.today().date()
    cursor.execute("SELECT MAX(tach) FROM flight_log")
    tach_row = cursor.fetchone()
    current_tach = validate_float(tach_row[0] if tach_row and tach_row[0] else 0)

    cond_due_str, cond_class = "--", "status-default"
    cursor.execute(
        "SELECT date FROM maintenance_entries WHERE recurrent_item='Condition Inspection' ORDER BY date DESC LIMIT 1"
    )
    ci_row = cursor.fetchone()
    if ci_row and ci_row[0]:
        try:
            last_dt = datetime.strptime(parse_date_safe(ci_row[0]), "%Y-%m-%d").date()
            prelim_due = last_dt + timedelta(
                days=MAINTENANCE_RULES["Condition Inspection"]["days"]
            )
            due_date = prelim_due.replace(
                day=calendar.monthrange(prelim_due.year, prelim_due.month)[1]
            )
            days_left = (due_date - today).days
            cond_due_str = f"{due_date.strftime('%m/%d/%Y')} ({days_left} days)"
            cond_class = (
                "status-overdue"
                if days_left < 0
                else "status-warning" if days_left <= 30 else "status-current"
            )
        except Exception:
            pass

    oil_due_str, oil_class = "--", "status-default"
    cursor.execute(
        "SELECT tach_time FROM maintenance_entries WHERE recurrent_item='Oil Change' ORDER BY date DESC, tach_time DESC LIMIT 1"
    )
    oil_row = cursor.fetchone()
    if oil_row and oil_row[0] is not None:
        hrs_left = round(
            (validate_float(oil_row[0]) + MAINTENANCE_RULES["Oil Change"]["hours"])
            - current_tach,
            1,
        )
        oil_due_str = f"{(validate_float(oil_row[0]) + MAINTENANCE_RULES['Oil Change']['hours']):.1f} hrs ({hrs_left:.1f} hrs left)"
        oil_class = (
            "status-overdue"
            if hrs_left < 0
            else "status-warning" if hrs_left <= 5.0 else "status-current"
        )

    return {
        "cond_due": cond_due_str,
        "cond_status_class": cond_class,
        "oil_due": oil_due_str,
        "oil_status_class": oil_class,
    }


def process_flights(df):
    """
    Groups data into flights and marks if the engine was run.
    """
    # --- FORCE CORE NUMERIC TYPES (prevent string math issues) ---
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
    ]

    for col in core_numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
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
    df["OIL_Delta_T"] = df["OIL TEMPERATURE (deg F)"] - df["OAT (deg F)"]

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
    # Create a boolean Series: True if any RPM > 0 and CHT > 125
    flights_with_engine = (flight_max_rpm["RPM"] > 0) & (
        flight_max_cht.max(axis=1) > 125
    )
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
    # Fill NaNs safely by dtype:
    # - numeric columns → 0
    # - string/object columns → ""
    num_cols = df.select_dtypes(include=[np.number]).columns
    obj_cols = df.select_dtypes(include=["object"]).columns

    if len(num_cols) > 0:
        df[num_cols] = df[num_cols].fillna(0)

    if len(obj_cols) > 0:
        df[obj_cols] = df[obj_cols].fillna("")
    # Defragment DataFrame to improve performance after many column insertions
    df = df.copy()
    return df


def parse_vpx_file(filepath):
    tree = ET.parse(filepath)
    root = tree.getroot()

    # Extract Header Info
    config_data = {
        "user": root.findtext("User"),
        "tailNumber": root.findtext("TailNumber"),
        "circuits": [],
    }

    # Extract Circuit Configurations
    circuits_node = root.find("CircuitConfigurations")
    if circuits_node is not None:
        for circuit in circuits_node.findall("CircuitConfiguration"):
            config_data["circuits"].append(
                {
                    "id": circuit.findtext("Id"),
                    "name": circuit.findtext("Name") or "",
                    "breaker": circuit.findtext("BreakerValue"),
                    "switchId": circuit.findtext("SwitchId"),
                    "enabled": circuit.findtext("Enabled").lower() == "true",
                    "fault": circuit.findtext("CurrentFault").lower() == "true",
                }
            )

    return config_data


@app.route("/update_server", methods=["GET", "POST"])
@app.route("/update_server/", methods=["GET", "POST"])
def update_server():
    if request.method == "POST":
        script_path = "/home/georgefahmy/Documents/n890gf_tracker/deploy.sh"
        try:
            # result = subprocess.run(
            #     [script_path], capture_output=True, text=True, shell=True
            # )
            result = subprocess.Popen(
                ["/bin/bash", script_path], start_new_session=True
            )

            return f"Deployment started - {result.stdout}", 202

        except Exception as e:
            return f"Server Error: {str(e)}", 500
    return "GET received (This is why you got a 405 before)", 200


@app.before_request
def redirect_www():
    host = request.host.split(":")[0]
    if host == "www.n890gf.local":
        return redirect("http://n890gf.local:5001" + request.path)


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("index"))

    if request.method == "POST":
        ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        user_agent = request.headers.get("User-Agent", "")
        now = time.time()
        # Extract username before ban check
        username = request.form.get("username")
        log_user = username or "-"

        # --- Check ban list (DB-backed) ---
        conn = get_db_connection()
        ban_row = conn.execute(
            "SELECT ban_time FROM banned_ips WHERE ip = ? AND username = ?",
            (ip, username),
        ).fetchone()

        if ban_row:
            ban_time = ban_row["ban_time"]
            if now - ban_time < BAN_DURATION_SECONDS:
                login_security_logger.warning(
                    "banned_ip_attempt",
                    extra={
                        "ip": ip,
                        "user": log_user,
                        "status": "banned",
                        "ua": user_agent,
                    },
                )
                conn.close()
                return render_template(
                    "login.html",
                    error="Too many attempts. You are temporarily banned.",
                )
            else:
                conn.execute(
                    "DELETE FROM banned_ips WHERE ip = ? AND username = ?",
                    (ip, username),
                )
                conn.commit()
        conn.close()

        # --- Rate limit check ---
        with LOGIN_LOCK:
            attempts = LOGIN_ATTEMPTS.get(ip, [])
            # remove old attempts
            attempts = [t for t in attempts if now - t < BLOCK_WINDOW_SECONDS]
            LOGIN_ATTEMPTS[ip] = attempts

            if len(attempts) >= MAX_ATTEMPTS:
                conn = get_db_connection()

                row = conn.execute(
                    "SELECT count FROM banned_ips WHERE ip = ? AND username = ?",
                    (ip, username),
                ).fetchone()

                if row:
                    new_count = row["count"] + 1
                    conn.execute(
                        "UPDATE banned_ips SET count = ? WHERE ip = ? AND username = ?",
                        (new_count, ip, username),
                    )
                else:
                    new_count = 1
                    conn.execute(
                        "INSERT INTO banned_ips (ip, username, ban_time, count) VALUES (?, ?, ?, ?)",
                        (ip, username, 0, new_count),
                    )

                conn.commit()

                # ban if threshold exceeded
                if new_count >= BAN_THRESHOLD:
                    conn.execute(
                        "UPDATE banned_ips SET ban_time = ? WHERE ip = ? AND username = ?",
                        (now, ip, username),
                    )
                    conn.commit()
                    conn.close()

                    login_security_logger.warning(
                        "ip_banned",
                        extra={
                            "ip": ip,
                            "user": log_user,
                            "status": "banned",
                            "ua": user_agent,
                        },
                    )
                    return render_template(
                        "login.html",
                        error="Too many attempts. You are temporarily banned.",
                    )

                conn.close()

                login_security_logger.warning(
                    "rate_limited",
                    extra={
                        "ip": ip,
                        "user": log_user,
                        "status": "blocked",
                        "ua": user_agent,
                    },
                )
                return render_template(
                    "login.html", error="Too many attempts. Try again later."
                )

        password = request.form.get("password")

        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            # reset attempts on success
            with LOGIN_LOCK:
                LOGIN_ATTEMPTS.pop(ip, None)
            conn = get_db_connection()
            conn.execute(
                "DELETE FROM banned_ips WHERE ip = ? AND username = ?", (ip, username)
            )
            conn.commit()
            conn.close()
            remember = request.form.get("remember") == "on"

            session["user_id"] = user["id"]
            session.permanent = remember  # this is the key

            login_success_logger.info(
                "login_success",
                extra={
                    "ip": ip,
                    "user": log_user,
                    "status": "success",
                    "ua": user_agent,
                },
            )
            return redirect(url_for("index"))
        else:
            # record failed attempt
            with LOGIN_LOCK:
                LOGIN_ATTEMPTS.setdefault(ip, []).append(time.time())

            login_failure_logger.info(
                "login_failure",
                extra={
                    "ip": ip,
                    "user": log_user,
                    "status": "failure",
                    "ua": user_agent,
                },
            )
            return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    conn = get_db_connection()
    cursor = conn.cursor()

    def sort_and_format_logs(logs_list):
        def parse_to_datetime(d):
            if not d:
                return datetime.min
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
                try:
                    return datetime.strptime(d, fmt)
                except ValueError:
                    continue
            return datetime.min

        def hobbs_val(x):
            try:
                return float(x.get("hobbs", 0) or 0)
            except Exception:
                return 0.0

        sorted_logs = sorted(
            logs_list,
            key=lambda x: (
                parse_to_datetime(x["date"]),
                hobbs_val(x),
            ),
            reverse=True,
        )
        for log in sorted_logs:
            dt = parse_to_datetime(log["date"])
            if dt != datetime.min:
                log["date"] = dt.strftime("%Y-%m-%d")
                log["display_date"] = dt.strftime("%m/%d/%Y")
            else:
                log["display_date"] = log.get("date", "")
        return sorted_logs

    cursor.execute("SELECT * FROM flight_log")
    flight_logs = sort_and_format_logs([dict(row) for row in cursor.fetchall()])
    cursor.execute("SELECT * FROM maintenance_entries")
    mx_logs = sort_and_format_logs([dict(row) for row in cursor.fetchall()])
    cursor.execute("SELECT * FROM fuel_tracker")
    fuel_logs = sort_and_format_logs([dict(row) for row in cursor.fetchall()])

    # --- Compute Hobbs delta between fuel-ups ---
    def safe_hobbs(x):
        try:
            return float(x.get("hobbs", 0) or 0)
        except Exception:
            return 0.0

    # Sort ascending for delta calculation
    fuel_logs_sorted = sorted(fuel_logs, key=lambda x: safe_hobbs(x))

    prev = None
    for f in fuel_logs_sorted:
        curr = safe_hobbs(f)
        if prev is None:
            f["delta"] = None
        else:
            delta = round(curr - prev, 1)
            f["delta"] = delta if delta >= 0 else 0.0
        prev = curr

    # --- Get latest Hobbs and Tach ---
    cursor.execute("SELECT hobbs, tach FROM flight_log ORDER BY hobbs DESC LIMIT 1")
    latest_res = cursor.fetchone()

    total_hobbs = (
        validate_float(latest_res["hobbs"])
        if latest_res and latest_res["hobbs"]
        else 0.0
    )
    total_tach = (
        validate_float(latest_res["tach"]) if latest_res and latest_res["tach"] else 0.0
    )

    # Keep legacy total_hours for compatibility
    total_hours = total_hobbs

    # --- Get latest Hobbs from fuel tracker ---
    cursor.execute("SELECT hobbs FROM fuel_tracker ORDER BY hobbs DESC LIMIT 1")
    fuel_hobbs_row = cursor.fetchone()

    latest_fuel_hobbs = (
        validate_float(fuel_hobbs_row["hobbs"])
        if fuel_hobbs_row and fuel_hobbs_row["hobbs"]
        else 0.0
    )

    cursor.execute("SELECT SUM(landings) as total_ldgs FROM flight_log")
    l_res = cursor.fetchone()
    total_landings = l_res["total_ldgs"] if l_res and l_res["total_ldgs"] else 0

    # --- Fuel Cost Metrics ---
    total_fuel_cost = 0.0
    total_gallons = 0.0

    for f in fuel_logs:
        try:
            gallons = float(f.get("gallons", 0) or 0)
            price = float(f.get("price_per_gallon", 0) or 0)
            total_gallons += gallons
            total_fuel_cost += gallons * price
        except Exception:
            continue

    total_fuel_cost = round(total_fuel_cost, 2)
    total_gallons = round(total_gallons, 2)

    avg_gph = (
        round(total_gallons / latest_fuel_hobbs, 2) if latest_fuel_hobbs > 0 else 0.0
    )

    avg_fuel_cost_per_hour = (
        round(total_fuel_cost / total_hours, 2) if total_hours > 0 else 0.0
    )

    overdue_items = calculate_overdue(conn)
    nav_status = get_nav_database_status(conn)
    upcoming_mx = get_upcoming_maintenance(conn)
    conn.close()

    if nav_status.get("aviation_status") == "Overdue":
        overdue_items.append("Aviation DB")
    if nav_status.get("obstacle_status") == "Overdue":
        overdue_items.append("Obstacle DB")
    if (
        "Aviation DB" in overdue_items or "Obstacle DB" in overdue_items
    ) and "Nav Data Update" in overdue_items:
        overdue_items.remove("Nav Data Update")

    aviation_text = nav_status.get("aviation_status", "--") + (
        f" ({nav_status['aviation_days_remaining']} days)"
        if nav_status.get("aviation_days_remaining") is not None
        and nav_status.get("aviation_status") != "--"
        else ""
    )
    obstacle_text = nav_status.get("obstacle_status", "--") + (
        f" ({nav_status['obstacle_days_remaining']} days)"
        if nav_status.get("obstacle_days_remaining") is not None
        and nav_status.get("obstacle_status") != "--"
        else ""
    )

    user_agent = request.headers.get("User-Agent", "").lower()
    is_mobile = any(x in user_agent for x in ["iphone", "android", "mobile"])

    template = "index.html" if is_mobile else "index.html"

    return render_template(
        template,
        flight_logs=flight_logs,
        mx_logs=mx_logs,
        fuel_logs=fuel_logs,
        total_hours=total_hours,
        total_hobbs=total_hobbs,
        total_tach=total_tach,
        total_landings=total_landings,
        overdue_items=overdue_items,
        overdue_count=len(overdue_items),
        aviation_db_text=aviation_text,
        aviation_status_class=(
            "status-current"
            if nav_status.get("aviation_status") == "Current"
            else "status-overdue"
        ),
        obstacle_db_text=obstacle_text,
        obstacle_status_class=(
            "status-current"
            if nav_status.get("obstacle_status") == "Current"
            else "status-overdue"
        ),
        cond_due=upcoming_mx["cond_due"],
        cond_status_class=upcoming_mx["cond_status_class"],
        oil_due=upcoming_mx["oil_due"],
        oil_status_class=upcoming_mx["oil_status_class"],
        total_fuel_cost=total_fuel_cost,
        avg_fuel_cost_per_hour=avg_fuel_cost_per_hour,
        avg_gph=avg_gph,
    )


@app.route("/vpx-editor")
def vpx_editor():
    return render_template("vpx_editor.html", user="", tail="N890GF")


@app.route("/api/generate-vpx", methods=["POST"])
def generate_vpx():
    data = request.json
    root = ET.Element(
        "VpxConfiguration",
        {
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xmlns:xsd": "http://www.w3.org/2001/XMLSchema",
        },
    )

    # Header
    ET.SubElement(root, "User").text = data.get("user", "George Fahmy")
    ET.SubElement(root, "TailNumber").text = data.get("tailNumber", "N890GF")
    ET.SubElement(root, "HardwareVersion").text = "2"
    ET.SubElement(root, "SoftwareMajor").text = "1"
    ET.SubElement(root, "SoftwareMinor").text = "6"
    ET.SubElement(root, "ConfiguratorVersion").text = "1.6.0.0"

    # Circuits
    circuits_container = ET.SubElement(root, "CircuitConfigurations")
    for c in data.get("circuits", []):
        node = ET.SubElement(circuits_container, "CircuitConfiguration")
        ET.SubElement(node, "Id").text = c["id"]
        ET.SubElement(node, "BreakerValue").text = str(c["breaker"])
        ET.SubElement(node, "CurrentFault").text = "false"
        ET.SubElement(node, "SwitchId").text = c["switchId"]
        ET.SubElement(node, "Enabled").text = "true" if c["enabled"] else "false"
        ET.SubElement(node, "Name").text = c["name"]

    # Boilerplate (Add Trim/Flap defaults as in your vertical_power.py)
    # ... (Omitted for brevity, keep the blocks from your original .py file)

    ET.SubElement(root, "TimeStamp").text = datetime.now().isoformat()

    xml_str = ET.tostring(root, encoding="utf-8")
    pretty_xml = minidom.parseString(xml_str).toprettyxml(indent="  ")

    return Response(
        pretty_xml,
        mimetype="application/xml",
        headers={
            "Content-Disposition": f"attachment;filename={data.get('tailNumber')}_VPX.xml"
        },
    )


@app.route("/sync-vpx", methods=["POST"])
def sync_to_hardware():
    # 1. Get the current UI state (JSON)
    config_data = request.json

    # 2. Convert JSON/XML to the VP-X Binary Format
    # (This is where the Wireshark data mapping comes in)
    binary_payload = config_data

    # 3. Send over Socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect(("192.168.1.50", 50000))
        s.sendall(binary_payload)
        response = s.recv(1024)

    return {"status": "success" if response else "no_ack"}


@app.route("/save-devices", methods=["POST"])
def save_devices():
    data = request.json
    with open("static/deviceLibrary.json", "w") as f:
        json.dump(data, f, indent=4)
    return {"status": "success"}


@app.route("/save-switches", methods=["POST"])
def save_switches():
    data = request.json
    with open("static/switchLibrary.json", "w") as f:
        json.dump(data, f, indent=4)
    return {"status": "success"}


@app.route("/add_flight", methods=["POST"])
@login_required
def add_flight():
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO flight_log (date, takeoff_airport, landing_airport, hobbs, tach, landings, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            parse_date_safe(request.form.get("date")),
            request.form.get("takeoff"),
            request.form.get("landing"),
            validate_float(request.form.get("hobbs")),
            validate_float(request.form.get("tach")),
            request.form.get("landings", 0),
            request.form.get("notes"),
        ),
    )
    conn.commit()
    recompute_flight_history(conn)
    check_auto_maintenance(conn)
    conn.close()
    git_push_data()
    return redirect(url_for("index"))


@app.route("/add_mx", methods=["POST"])
@login_required
def add_mx():
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO maintenance_entries (date, tach_time, airframe_time, recurrent_item, category, notes) VALUES (?, ?, ?, ?, ?, ?)",
        (
            parse_date_safe(request.form.get("date")),
            validate_float(request.form.get("tach")),
            validate_float(request.form.get("airframe")),
            request.form.get("recurrent_item"),
            request.form.get("category"),
            request.form.get("notes"),
        ),
    )
    conn.commit()
    recompute_flight_history(conn)
    check_auto_maintenance(conn)

    global NAV_CACHE
    NAV_CACHE = {"data": None, "timestamp": 0}

    conn.close()
    git_push_data()
    return redirect(url_for("index"))


@app.route("/add_fuel", methods=["POST"])
@login_required
def add_fuel():
    hobbs, gallons, price = (
        validate_float(request.form.get("hobbs", 0)),
        validate_float(request.form.get("gallons", 0)),
        validate_float(request.form.get("price", 0)),
    )
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO fuel_tracker (date, hobbs, gallons, price_per_gallon, total_cost, gal_per_hour) VALUES (?, ?, ?, ?, ?, ?)",
        (
            parse_date_safe(request.form.get("date")),
            hobbs,
            gallons,
            price,
            round(gallons * price, 2),
            round(gallons / hobbs, 2) if hobbs > 0 else 0,
        ),
    )
    conn.commit()
    conn.close()
    git_push_data()
    return redirect(url_for("index"))


@app.route("/api/fuel_prices", methods=["GET"])
@login_required
def api_fuel_prices():
    airport = request.args.get("airport", "").strip()
    if not airport:
        return jsonify({"error": "No airport provided"}), 400
    try:
        options, _ = scrape_airnav_to_json(airport)
        git_push_data()
        return (
            jsonify({"options": options})
            if options
            else jsonify({"error": f"No fuel data found for {airport}"})
        ), 404
    except Exception:
        return jsonify({"error": "An error occurred while fetching fuel prices."}), 500


@app.route("/edit_flight/<int:id>", methods=["POST"])
@login_required
def edit_flight(id):
    conn = get_db_connection()
    conn.execute(
        "UPDATE flight_log SET date = ?, takeoff_airport = ?, landing_airport = ?, hobbs = ?, tach = ?, landings = ?, notes = ? WHERE id = ?",
        (
            parse_date_safe(request.form.get("date")),
            request.form.get("takeoff"),
            request.form.get("landing"),
            validate_float(request.form.get("hobbs")),
            validate_float(request.form.get("tach")),
            request.form.get("landings", 0),
            request.form.get("notes"),
            id,
        ),
    )
    conn.commit()
    recompute_flight_history(conn)
    check_auto_maintenance(conn)
    conn.close()
    git_push_data()
    return redirect(url_for("index"))


@app.route("/edit_mx/<int:id>", methods=["POST"])
@login_required
def edit_mx(id):
    conn = get_db_connection()
    conn.execute(
        "UPDATE maintenance_entries SET date = ?, tach_time = ?, airframe_time = ?, recurrent_item = ?, category = ?, notes = ? WHERE id=?",
        (
            parse_date_safe(request.form.get("date")),
            validate_float(request.form.get("tach")),
            validate_float(request.form.get("airframe")),
            request.form.get("recurrent_item"),
            request.form.get("category"),
            request.form.get("notes"),
            id,
        ),
    )
    conn.commit()
    recompute_flight_history(conn)
    check_auto_maintenance(conn)

    global NAV_CACHE
    NAV_CACHE = {"data": None, "timestamp": 0}

    conn.close()
    git_push_data()
    return redirect(url_for("index"))


@app.route("/edit_fuel/<int:id>", methods=["POST"])
@login_required
def edit_fuel(id):
    hours, gallons, price = (
        validate_float(request.form.get("hours", 0)),
        validate_float(request.form.get("gallons", 0)),
        validate_float(request.form.get("price", 0)),
    )
    conn = get_db_connection()
    conn.execute(
        "UPDATE fuel_tracker SET date =?, hobbs =?, gallons =?, price_per_gallon =?, total_cost =?, gal_per_hour =? WHERE id = ?",
        (
            parse_date_safe(request.form.get("date")),
            hours,
            gallons,
            price,
            round(gallons * price, 2),
            round(gallons / hours, 2) if hours > 0 else 0,
            id,
        ),
    )
    conn.commit()
    conn.close()
    git_push_data()
    return redirect(url_for("index"))


@app.route("/delete_flight/<int:id>")
@login_required
def delete_flight(id):
    conn = get_db_connection()
    conn.execute("DELETE FROM flight_log WHERE id = ?", (id,))
    conn.commit()
    recompute_flight_history(conn)
    conn.close()
    git_push_data()
    return redirect(url_for("index"))


@app.route("/delete_maintenance/<int:id>")
@login_required
def delete_maintenance(id):
    conn = get_db_connection()
    conn.execute("DELETE FROM maintenance_entries WHERE id = ?", (id,))
    conn.commit()
    recompute_flight_history(conn)
    check_auto_maintenance(conn)

    global NAV_CACHE
    NAV_CACHE = {"data": None, "timestamp": 0}

    conn.close()
    git_push_data()
    return redirect(url_for("index"))


@app.route("/delete_fuel/<int:id>")
@login_required
def delete_fuel(id):
    conn = get_db_connection()
    conn.execute("DELETE FROM fuel_tracker WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    git_push_data()
    return redirect(url_for("index"))


@app.route("/analyzer")
def analyzer():
    user_agent = request.headers.get("User-Agent", "").lower()
    is_mobile = any(x in user_agent for x in ["iphone", "android", "mobile"])

    template = "analyzer.html" if is_mobile else "analyzer.html"

    return render_template(template)


# --- GAMI Spread Page Route ---
@app.route("/gami")
def gami():
    return render_template("gami.html")


@app.route("/api/saved_flights", methods=["GET"])
def api_saved_flights():
    """Lists all previously uploaded and processed flight data files."""
    files = [f for f in os.listdir(SAVE_DIR) if f.endswith(".csv")]
    files.sort(key=lambda x: os.path.getmtime(os.path.join(SAVE_DIR, x)), reverse=True)
    return jsonify({"files": files})


@app.route("/api/get_signals", methods=["POST"])
def api_get_signals():
    """Parses a new CSV or loads an existing one to populate the UI dropdowns."""
    saved_filename = request.form.get("saved_filename")

    try:
        if saved_filename:
            filepath = os.path.join(SAVE_DIR, saved_filename)
            if not os.path.exists(filepath):
                return jsonify({"error": "Saved file not found."}), 404
            df = pd.read_csv(filepath, low_memory=False)

        else:
            if "file" not in request.files:
                return jsonify({"error": "No file part"}), 400
            file = request.files["file"]
            if file.filename == "" or not file.filename.endswith(".csv"):
                return jsonify({"error": "Invalid file. Please upload a CSV."}), 400

            df = pd.read_csv(file, low_memory=False)
            df = process_flights(df)

            if df is None or df.empty:
                return jsonify({"error": "No valid flight data found in the CSV."}), 400

            flight_ids = [
                fid
                for fid in df["Flight ID"].unique()
                if fid not in (None, 0, "", "nan")
            ]

            for fid in flight_ids:
                flight_data = df[df["Flight ID"] == fid]
                if flight_data.empty:
                    continue

                # Extract date from Flight ID (assumes format: "YYYY-MM-DD ... - Flight X")
                fid_str = str(fid)

                # Clean filename
                safe_name = fid_str.replace("/", "-").replace(":", "-")
                base_name, ext = os.path.splitext(safe_name)
                filepath = os.path.join(SAVE_DIR, f"{safe_name}.csv")
                flight_data.to_csv(filepath, index=False)
            git_push_data()
            df = flight_data
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        excluded = [
            "Unnamed: 103",
            "Unnamed: 0",
            "Engine Run",
            "id",
            "AP Yaw Force",
            "AP Yaw Position",
            "AP Yaw Slip (bool)",
            "AP Pitch Slip (bool)",
            "AP Roll Slip (bool)",
            "AP Roll Mode",
            "CANOPY CONTACT (V)",
            "CDI Deflection (%)",
            "CDI Scale NM",
            "CDI Source Port",
            "CDI Source Type",
            "Thermocouple 1 (deg F)",
            "Thermocouple 1 (deg C)",
            "Thermocouple 2 (deg F)",
            "Thermocouple 2 (deg C)",
            "Thermocouple 3 (deg F)",
            "Thermocouple 3 (deg C)",
            "Thermocouple 4 (deg F)",
            "Thermocouple 4 (deg C)",
            "Thermocouple 12 (deg F)",
            "Thermocouple 12 (deg C)",
            "Thermocouple 13 (deg F)",
            "Thermocouple 13 (deg C)",
            "Thermocouple 14 (deg F)",
            "Thermocouple 14 (deg C)",
            "Fuel Flow 1 (gal/hr)",
            "Fuel Flow 2 (gal/hr)",
            "GP Input 3",
            "GP Input 7",
            "GP Input 8",
            "GP Input 13",
            "RPM L",
            "RPM R",
            "Oil Pressure (psi)",
            "Oil Temp (deg F)",
        ]
        signals = sorted([col for col in numeric_cols if col not in excluded])

        if "CHT" not in signals:
            signals.append("CHT")
        if "EGT" not in signals:
            signals.append("EGT")

        signals = sorted(signals)

        return jsonify({"signals": signals, "saved_filename": saved_filename})

    except Exception as e:
        print(f"Signal Parsing Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/route_advisor", methods=["POST"])
def route_advisor():
    origin = request.form["origin"]
    destination = request.form["destination"]
    range_value = request.form["range_nm"]

    result = fetch_route(
        origin,
        destination,
        range_value,
    )

    return jsonify(result)


# --- API endpoint for Dynon database updates ---
@app.route("/api/database_updates", methods=["POST"])
@login_required
def api_database_updates():
    """
    Trigger download of Dynon aviation and obstacle databases.
    """
    try:
        data = request.get_json(silent=True) or request.form
        download_path = data.get("download_path", "").strip()
        # Expand ~ to user home directory
        download_path = os.path.expanduser(download_path)
        # If still empty, default to Downloads
        if not download_path:
            download_path = os.path.expanduser("~/Downloads/")

        if not download_path:
            return jsonify({"error": "Download path is required"}), 400

        # Ensure directory exists
        try:
            os.makedirs(download_path, exist_ok=True)
        except Exception as e:
            return jsonify({"error": f"Invalid path: {e}"}), 400

        database_url = "https://dynonavionics.com/us-aviation-obstacle-data.php"

        # Run download in background thread so UI doesn't hang
        def run_download():
            try:
                download_dynon_databases_only(database_url, download_path)
            except Exception as e:
                print("Database download error:", e)

        threading.Thread(target=run_download, daemon=True).start()

        return jsonify({"status": "Download started"})

    except Exception as e:
        print("Database update API error:", e)
        return jsonify({"error": str(e)}), 500


# --- Proxy endpoint for posting a route string to ForeFlight performance API ---
@app.route("/api/foreflight_route", methods=["POST"])
def api_foreflight_route():
    """
    Posts a route string to ForeFlight performance API (server-side to avoid CORS issues).
    """
    try:
        data = request.get_json(silent=True) or request.form
        route_string = data.get("routeString", "")

        if not route_string:
            return jsonify({"error": "No routeString provided"}), 400

        # Clean route for ForeFlight
        clean_route = route_string.replace("➔", " ").replace("→", " ").strip()

        payload = {"routeString": clean_route}

        url = "https://plan.foreflight.com/map/api/performance/flight"

        resp = requests.post(
            url, json=payload, headers={"Content-Type": "application/json"}, timeout=10
        )

        # Try to parse response safely
        try:
            response_data = resp.json()
        except Exception:
            response_data = {"raw": resp.text}

        return jsonify(
            {"status_code": resp.status_code, "foreflight_response": response_data}
        )

    except Exception as e:
        print("ForeFlight POST error:", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/analyze_flight", methods=["POST"])
def api_analyze_flight():
    """Loads the pre-saved dataframe and extracts plot data dynamically."""
    saved_filename = request.form.get("saved_filename")
    if not saved_filename:
        return jsonify({"error": "No data file specified."}), 400

    try:
        filepath = os.path.join(SAVE_DIR, saved_filename)
        if not os.path.exists(filepath):
            return jsonify({"error": "Saved file not found on server."}), 404

        df = pd.read_csv(filepath, low_memory=False)

        left_signal = request.form.get("left_signal", "RPM")
        right_signal = request.form.get("right_signal", "AVG_CHT")
        temp_unit = request.form.get("temp_unit", "F")

        flight_ids = [
            fid for fid in df["Flight ID"].unique() if pd.notna(fid) and fid != ""
        ]
        if not flight_ids:
            return (
                jsonify({"error": "No engine-run flights detected in this file."}),
                400,
            )

        target_flight = flight_ids[0]
        flight_data = df[df["Flight ID"] == target_flight].copy()

        # --- Apply Filters ---
        filters_json = request.form.get("filters")
        if filters_json:
            try:
                filters = json.loads(filters_json)
                for f in filters:
                    signal = f.get("signal")
                    op = f.get("op")
                    value = f.get("value")

                    if signal not in flight_data.columns:
                        continue

                    col_data = pd.to_numeric(flight_data[signal], errors="coerce")

                    if op == ">":
                        flight_data = flight_data[col_data > value]
                    elif op == "<":
                        flight_data = flight_data[col_data < value]
                    elif op == ">=":
                        flight_data = flight_data[col_data >= value]
                    elif op == "<=":
                        flight_data = flight_data[col_data <= value]
                    elif op == "==":
                        flight_data = flight_data[col_data == value]

            except Exception as e:
                print("Filter parsing error:", e)

        # Sanitize data for JSON
        flight_data = flight_data.replace([np.inf, -np.inf], 0)
        flight_data = flight_data.fillna(0)
        x_data = flight_data["Session Time"].tolist()

        def extract_traces(sig):
            traces = []
            deg_str = f"(deg {temp_unit})"

            if sig == "CHT":
                cols = [
                    c
                    for c in flight_data.columns
                    if c.startswith("CHT ") and deg_str in c
                ]
            elif sig == "EGT":
                cols = [
                    c
                    for c in flight_data.columns
                    if c.startswith("EGT ") and deg_str in c
                ]
            else:
                cols = [sig] if sig in flight_data.columns else []

            for col in sorted(cols):
                traces.append({"name": col, "y": flight_data[col].tolist()})
            return traces

        # --- Extract Latitude / Longitude (supports Dynon naming) ---
        lat_col = next(
            (c for c in flight_data.columns if "latitude" in c.lower()), None
        )
        lon_col = next(
            (c for c in flight_data.columns if "longitude" in c.lower()), None
        )
        # --- Explicitly use GPS Altitude (feet) if available ---
        if "GPS Altitude (feet)" in flight_data.columns:
            alt_col = "GPS Altitude (feet)"
        else:
            # Fallbacks if exact name not present
            alt_candidates = [c for c in flight_data.columns if "altitude" in c.lower()]
            alt_col = next(
                (c for c in alt_candidates if "gps" in c.lower()),
                next(
                    (c for c in alt_candidates if "pressure" in c.lower()),
                    alt_candidates[0] if alt_candidates else None,
                ),
            )

        lat_data = []
        lon_data = []
        alt_data = []

        if lat_col and lon_col:
            lat_data = (
                pd.to_numeric(flight_data[lat_col], errors="coerce")
                .replace([np.inf, -np.inf], np.nan)
                .fillna(0)
                .tolist()
            )
            lon_data = (
                pd.to_numeric(flight_data[lon_col], errors="coerce")
                .replace([np.inf, -np.inf], np.nan)
                .fillna(0)
                .tolist()
            )

        if alt_col:
            alt_data = (
                pd.to_numeric(flight_data[alt_col], errors="coerce")
                .replace([np.inf, -np.inf], np.nan)
                .tolist()
            )
        # --- ALIGNED MULTI-MODE SIGNALS (for heatmap modes) ---

        def safe_numeric(series):
            return (
                pd.to_numeric(series, errors="coerce")
                .replace([np.inf, -np.inf], np.nan)
                .fillna(0)
                .tolist()
            )

        # Primary signals aligned to same dataframe index (IMPORTANT for heatmap consistency)
        airspeed_data = safe_numeric(
            flight_data.get("True Airspeed (knots)", pd.Series([0] * len(flight_data)))
        )
        groundspeed_data = safe_numeric(
            flight_data.get("Ground Speed (knots)", pd.Series([0] * len(flight_data)))
        )
        rpm = safe_numeric(flight_data.get("RPM", pd.Series([0] * len(flight_data))))
        map_data = safe_numeric(
            flight_data.get(
                "Manifold Pressure (inHg)", pd.Series([0] * len(flight_data))
            )
        )
        percent_power = safe_numeric(
            flight_data.get("Percent Power", pd.Series([0] * len(flight_data)))
        )
        fuel_flow = safe_numeric(
            flight_data.get(
                "Total Fuel Flow (gal/hr)", pd.Series([0] * len(flight_data))
            )
        )
        mpg = safe_numeric(flight_data.get("MPG", pd.Series([0] * len(flight_data))))

        # --- Vertical speed (use native Dynon data if available) ---
        if "Vertical Speed (ft/min)" in flight_data.columns:
            vertical_speed = (
                pd.to_numeric(flight_data["Vertical Speed (ft/min)"], errors="coerce")
                .replace([np.inf, -np.inf], np.nan)
                .fillna(0)
                .tolist()
            )
        else:
            # fallback: compute from altitude if missing
            altitude_series = pd.to_numeric(
                flight_data.get("Pressure Altitude (ft)", 0),
                errors="coerce",
            ).fillna(0)

            try:
                dt = (
                    pd.to_numeric(flight_data["Session Time"], errors="coerce")
                    .diff()
                    .fillna(0)
                )

                vs_fpm = (
                    altitude_series.diff().fillna(0) / dt.replace(0, np.nan)
                ) * 60.0
                vs_fpm = vs_fpm.replace([np.inf, -np.inf], 0).fillna(0)

                vertical_speed = vs_fpm.tolist()

            except Exception:
                vertical_speed = [0] * len(flight_data)

        # --- Extract Aircraft Attitude Data ---
        def extract_attitude(col_name):
            if col_name in flight_data.columns:
                return (
                    pd.to_numeric(flight_data[col_name], errors="coerce")
                    .replace([np.inf, -np.inf], np.nan)
                    .fillna(0)
                    .tolist()
                )
            return []

        pitch_data = extract_attitude("Pitch (deg)")
        roll_data = extract_attitude("Roll (deg)")
        heading_data = extract_attitude("Magnetic Heading (deg)")
        magnetic_variance = extract_attitude("Mag Var (deg)")

        plot_data = {
            "x": x_data,
            "left_traces": extract_traces(left_signal),
            "right_traces": extract_traces(right_signal),
            "left_name": left_signal,
            "right_name": right_signal,
            "latitude": lat_data,
            "longitude": lon_data,
            "altitude": alt_data,
            "airspeed": airspeed_data,
            "groundspeed": groundspeed_data,
            "vertical_speed": vertical_speed,
            "pitch": pitch_data,
            "roll": roll_data,
            "heading": heading_data,
            "mag_variance": magnetic_variance,
            "rpm": rpm,
            "map_data": map_data,
            "percent_power": percent_power,
            "fuel_flow": fuel_flow,
            "mpg": mpg,
        }

        # --- Generate Summary Stats ---
        numeric_times = pd.to_numeric(flight_data["Session Time"], errors="coerce")
        duration = (
            numeric_times.max() - numeric_times.min() if not numeric_times.empty else 0
        )

        total_fuel = (
            flight_data["Fuel Flow Integral"].max()
            if "Fuel Flow Integral" in flight_data.columns
            and flight_data["Fuel Flow Integral"].max() != ""
            else 0
        )
        avg_flow = (total_fuel * 3600) / duration if duration > 0 else 0

        # Calculate Average MPG using the mean() of the MPG data column
        avg_mpg = "N/A"

        if "MPG" in flight_data.columns:
            try:
                valid_mpg = pd.to_numeric(flight_data["MPG"], errors="coerce").dropna()
                if not valid_mpg.empty:
                    avg_mpg = round(valid_mpg.mean(), 1)
            except Exception:
                pass
        if "Distance Traveled" in flight_data.columns:
            distance_traveled = safe_numeric(
                flight_data.get("Distance Traveled", pd.Series([0] * len(flight_data)))
            )

        def safe_max(col):
            if col in flight_data.columns:
                series = pd.to_numeric(flight_data[col], errors="coerce").dropna()
                return round(series.max(), 1) if not series.empty else "N/A"
            return "N/A"

        stats = {
            "flight_id": target_flight,
            "duration_min": round(duration / 60, 2),
            "max_rpm": safe_max("RPM"),
            "max_cht": safe_max("Max CHT"),
            "total_fuel": (
                round(total_fuel, 2) if isinstance(total_fuel, (int, float)) else "N/A"
            ),
            "avg_fuel_flow": round(avg_flow, 2),
            "avg_mpg": avg_mpg,
            "distance_traveled": distance_traveled[-1] / 5280,
        }

        rawData = flight_data.to_dict(orient="records")

        safe_response = sanitize_for_json(
            {"plot_data": plot_data, "stats": stats, "rawData": rawData}
        )

        return jsonify(safe_response)

    except Exception as e:
        print(f"Analysis Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/save_signal_bands", methods=["POST"])
def save_signal_bands():
    try:
        new_bands_data = request.json

        # Path to your signal_bands.js file (adjust if necessary)
        filepath = os.path.join(app.root_path, "static", "signal_bands.js")

        # We must wrap the raw JSON object inside the JS variable declaration
        # exactly how it was formatted originally
        js_content = f"// --- BAND CONFIGURATION (Global State) ---\nlet SIGNAL_BANDS = {json.dumps(new_bands_data, indent=4)};\n"

        # Write the file directly
        with open(filepath, "w") as f:
            f.write(js_content)

        return jsonify({"success": True, "message": "Bands saved successfully."})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/airspeed_calibration", methods=["POST"])
def api_airspeed_calibration():
    saved_filename = request.form.get("saved_filename")
    start_time = request.form.get("start_time", type=float)
    end_time = request.form.get("end_time", type=float)

    if not saved_filename:
        return jsonify({"error": "No file specified"}), 400

    try:
        filepath = os.path.join(SAVE_DIR, saved_filename)
        if not os.path.exists(filepath):
            return jsonify({"error": "File not found"}), 404

        df = pd.read_csv(filepath, low_memory=False)

        # pick first flight
        flight_ids = [
            fid for fid in df["Flight ID"].unique() if pd.notna(fid) and fid != ""
        ]

        if not flight_ids:
            return jsonify({"error": "No flight data found"}), 400

        flight_id = flight_ids[0]
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
                "Wind Speed (knots)": "Wind Speed (knots)",
                "Wind Direction (deg)": "Wind Direction (deg)",
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
            start_time=start_time,
            end_time=end_time,
            show_plot=False,
        )

        maneuver_df = as_cal_df[
            (as_cal_df["session_time"] >= start_time)
            & (as_cal_df["session_time"] <= end_time)
        ]

        avg_wind_speed = (
            maneuver_df["Wind Speed (knots)"].mean()
            if not maneuver_df.empty
            else float("nan")
        )

        avg_wind_dir = (
            maneuver_df["Wind Direction (deg)"].mean()
            if not maneuver_df.empty
            else float("nan")
        )

        summary = (
            f"Data Points Analyzed:  {output['analyzed_data_points']}\n"
            f"CAS Correction:        {output['calibrated_airspeed_correction_kts']} kts\n"
            f"Airspeed Error:        {output['airspeed_error_kts']} kts\n"
            f"HDG Correction:        {output['calibrated_heading_correction_deg']} deg\n"
            f"Wind Direction:        {output['wind_direction_deg']} deg (Avg: {avg_wind_dir:.1f})\n"
            f"Wind Speed:            {output['wind_speed_kts']} kts (Avg: {avg_wind_speed:.1f})\n"
            f"Uncorr. Avg TAS:       {output['uncorrected_average_true_airspeed_kts']} kts\n"
            f"Corrected Avg TAS:     {output['corrected_average_true_airspeed_kts']} kts\n"
        )

        return jsonify({"summary": summary})

    except Exception as e:
        print("Airspeed calibration error:", e)
        return jsonify({"error": str(e)}), 500


@app.route("/export/flights")
@login_required
def export_flights():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Query all columns from flight_log
    cursor.execute("SELECT * FROM flight_log ORDER BY date DESC, id DESC")
    rows = cursor.fetchall()
    conn.close()

    si = StringIO()
    cw = csv.writer(si)

    # Define headers based on your DB schema
    cw.writerow(
        [
            "ID",
            "Date",
            "Takeoff",
            "Landing",
            "Hobbs",
            "Tach",
            "Landings",
            "Notes",
            "Hobbs Delta",
            "Tach Delta",
        ]
    )

    for r in rows:
        cw.writerow(
            [
                r["id"],
                r["date"],
                r["takeoff_airport"],
                r["landing_airport"],
                r["hobbs"],
                r["tach"],
                r["landings"],
                r["notes"],
                r["hobbs_delta"],
                r["tach_delta"],
            ]
        )

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=Flight_Logs.csv"
    output.headers["Content-type"] = "text/csv"
    return output


@app.route("/export/mx")
@login_required
def export_mx():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM maintenance_entries ORDER BY date DESC, id DESC")
    rows = cursor.fetchall()
    conn.close()

    si = StringIO()
    cw = csv.writer(si)

    # Headers for maintenance
    cw.writerow(
        [
            "ID",
            "Date",
            "Tach Time",
            "Airframe Time",
            "Recurrent Item",
            "Category",
            "Notes",
        ]
    )

    for r in rows:
        cw.writerow(
            [
                r["id"],
                r["date"],
                r["tach_time"],
                r["airframe_time"],
                r["recurrent_item"],
                r["category"],
                r["notes"],
            ]
        )

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=Maintenance_Logs.csv"
    output.headers["Content-type"] = "text/csv"
    return output


@app.route("/export/fuel")
@login_required
def export_fuel():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM fuel_tracker ORDER BY date DESC, id DESC")
    rows = cursor.fetchall()
    conn.close()

    si = StringIO()
    cw = csv.writer(si)

    # Headers for fuel
    cw.writerow(
        ["ID", "Date", "Hobbs", "Gallons", "Price Per Gallon", "Total Cost", "GPH"]
    )

    for r in rows:
        cw.writerow(
            [
                r["id"],
                r["date"],
                r["hobbs"],
                r["gallons"],
                r["price_per_gallon"],
                r["total_cost"],
                r["gal_per_hour"],
            ]
        )

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=Fuel_Logs.csv"
    output.headers["Content-type"] = "text/csv"
    return output


if __name__ == "__main__":
    app.run(debug=DEBUG)
