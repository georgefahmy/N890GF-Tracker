import calendar
import csv
import json
import logging
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta
from io import StringIO
from logging.handlers import RotatingFileHandler

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup
from flask import (
    Flask,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import LoginManager, UserMixin, login_required, login_user
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

from src.airnav_route import fetch_route
from src.airspeed_calibration import analyze_flight_data
from src.fuel_estimate_simple import calculate_fuel
from src.fuel_prices import scrape_airnav_to_json
from src.oil_analysis import parse_oil_report
from src.sw_db_updates import download_dynon_databases_only

CWD_PATH = os.path.abspath(os.getcwd())
app = Flask(__name__)
app.secret_key = "827311a9a172036c2f5ebaa0cb68c0ed90b037d30cccf15097627ec1759eee61"
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

# Replace your sqlite3 path logic with this
db_path = os.path.join(CWD_PATH, "../maintenance.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = os.path.join("static", "uploads")

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

# --- Login attempt logging (split logs) ---
LOG_DIR = os.path.join(CWD_PATH if "CWD_PATH" in globals() else os.getcwd(), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

log_formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | ip=%(ip)s | user=%(user)s | status=%(status)s | ua=%(ua)s | msg=%(message)s"
)


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


class Users(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.Text, nullable=False)
    password_hash = db.Column(db.Text, nullable=False)


class FlightLog(db.Model):
    __tablename__ = "flight_log"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, nullable=False)
    takeoff_airport = db.Column(db.Text)
    landing_airport = db.Column(db.Text)
    hobbs = db.Column(db.Float)
    tach = db.Column(db.Float)
    hobbs_delta = db.Column(db.Float, default=0.0)
    tach_delta = db.Column(db.Float, default=0.0)
    landings = db.Column(db.Integer)
    notes = db.Column(db.Text)


class MaintenanceLog(db.Model):
    __tablename__ = (
        "maintenance_entries"  # Kept original name for migration compatibility
    )
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, nullable=False)
    tach_time = db.Column(db.Float)
    airframe_time = db.Column(db.Float)
    recurrent_item = db.Column(db.Text)
    category = db.Column(db.Text)
    notes = db.Column(db.Text)


class FuelLog(db.Model):
    __tablename__ = "fuel_tracker"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, nullable=False)
    hobbs = db.Column(db.Float)
    gallons = db.Column(db.Float)
    price_per_gallon = db.Column(db.Float)
    total_cost = db.Column(db.Float)
    gal_per_hour = db.Column(db.Float)


class OilAnalysis(db.Model):
    __tablename__ = "oil_analysis"
    id = db.Column(db.Integer, primary_key=True)
    tail_number = db.Column(db.String(20), default="N890GF")
    date_sampled = db.Column(db.Date, nullable=False)
    sample_no = db.Column(db.Float)
    oil_hrs = db.Column(db.Float)
    engine_hrs = db.Column(db.Float)

    # Wear Metals (ppm)
    iron = db.Column(db.Float)
    copper = db.Column(db.Float)
    chromium = db.Column(db.Float)
    aluminum = db.Column(db.Float)
    nickel = db.Column(db.Float)
    lead = db.Column(db.Float)

    diagnosis = db.Column(db.Text)
    report_path = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class BannedIPs(db.Model):
    __tablename__ = "banned_ips"
    id = db.Column(db.Integer, primary_key=True)
    ip = db.Column(db.String(50))
    username = db.Column(db.String(100))
    ban_time = db.Column(db.Float, default=0.0)
    count = db.Column(db.Integer, default=0)


post_categories = db.Table(
    "post_categories",
    db.Column("post_id", db.Integer, db.ForeignKey("post.id"), primary_key=True),
    db.Column(
        "category_id", db.Integer, db.ForeignKey("category.id"), primary_key=True
    ),
)

post_tags = db.Table(
    "post_tags",
    db.Column("post_id", db.Integer, db.ForeignKey("post.id"), primary_key=True),
    db.Column("tag_id", db.Integer, db.ForeignKey("tag.id"), primary_key=True),
)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)


class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    slug = db.Column(db.String(150), nullable=False, unique=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    categories = db.relationship(
        "Category",
        secondary=post_categories,
        backref=db.backref("posts", lazy="dynamic"),
    )
    tags = db.relationship(
        "Tag",
        secondary=post_tags,
        backref=db.backref("posts", lazy="select"),
    )


# Create the tables in the DB if they don't exist
with app.app_context():
    db.create_all()


def validate_float(value, default=0.0):
    if value is None:
        return default
    try:
        return round(float(value), 2)
    except (ValueError, TypeError):
        return default


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


def parse_date_obj(value):
    """Returns a datetime object."""
    if not value:
        return datetime.today()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return datetime.today()


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


def recompute_flight_history():
    flights = FlightLog.query.order_by(FlightLog.date.asc(), FlightLog.id.asc()).all()
    prev_hobbs, prev_tach = None, None
    for f in flights:
        h_val = validate_float(f.hobbs)
        t_val = validate_float(f.tach)
        f.hobbs_delta = (
            round(max(0.0, h_val - prev_hobbs), 1) if prev_hobbs is not None else 0.0
        )
        f.tach_delta = (
            round(max(0.0, t_val - prev_tach), 1) if prev_tach is not None else 0.0
        )
        prev_hobbs, prev_tach = h_val, t_val
    db.session.commit()


def check_auto_maintenance():
    last_oil = (
        db.session.query(func.max(MaintenanceLog.tach_time))
        .filter_by(recurrent_item="Oil Change")
        .scalar()
        or 0.0
    )
    current_tach = db.session.query(func.max(FlightLog.tach)).scalar() or 0.0

    if current_tach - last_oil >= OIL_CHANGE_INTERVAL_HOURS:
        new_mx = MaintenanceLog(
            date=datetime.now(),
            tach_time=current_tach,
            airframe_time=current_tach,
            notes=f"Auto oil change reminder (>{OIL_CHANGE_INTERVAL_HOURS} hrs)",
            recurrent_item="Oil Change",
            category="Engine",
        )
        db.session.add(new_mx)
        db.session.commit()


def calculate_overdue_items():
    overdue_items = []
    today = datetime.today().date()
    current_tach = db.session.query(func.max(FlightLog.tach)).scalar() or 0.0

    # Get latest date for each recurrent item
    latest_entries = (
        db.session.query(MaintenanceLog.recurrent_item, func.max(MaintenanceLog.date))
        .group_by(MaintenanceLog.recurrent_item)
        .all()
    )

    for item, last_date in latest_entries:
        if not item or item == "None" or last_date is None:
            continue
        rule = MAINTENANCE_RULES.get(item)
        if not rule:
            continue

        last_date_only = last_date.date()
        if rule["type"] == "date" and today > (
            last_date_only + timedelta(days=rule["days"])
        ):
            overdue_items.append(item)
        elif rule["type"] == "tach":
            last_tach = (
                db.session.query(func.max(MaintenanceLog.tach_time))
                .filter_by(recurrent_item=item)
                .scalar()
                or 0.0
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


def _get_nav_database_status_live():
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

                # --- SQLAlchemy Query Update ---
                nav_entry = (
                    MaintenanceLog.query.filter_by(recurrent_item="Nav Data Update")
                    .order_by(MaintenanceLog.date.desc())
                    .first()
                )

                if nav_entry and nav_entry.date and date_aviation and date_obstacle:
                    # SQLAlchemy returns a datetime object natively
                    nav_date = (
                        nav_entry.date.date()
                        if isinstance(nav_entry.date, datetime)
                        else nav_entry.date
                    )

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


def get_nav_database_status():
    global NAV_CACHE
    now = time.time()
    with NAV_CACHE_LOCK:
        if NAV_CACHE["data"] and (now - NAV_CACHE["timestamp"] < NAV_CACHE_TTL):
            return NAV_CACHE["data"]
    live = _get_nav_database_status_live()
    with NAV_CACHE_LOCK:
        NAV_CACHE["data"] = live
        NAV_CACHE["timestamp"] = now
    return live


def get_upcoming_maintenance():
    today = datetime.today().date()

    # Get current tach time using SQLAlchemy func.max
    current_tach = db.session.query(func.max(FlightLog.tach)).scalar() or 0.0

    # --- Condition Inspection Logic ---
    cond_due_str, cond_class = "--", "status-default"

    ci_entry = (
        MaintenanceLog.query.filter_by(recurrent_item="Condition Inspection")
        .order_by(MaintenanceLog.date.desc())
        .first()
    )

    if ci_entry and ci_entry.date:
        try:
            # SQLAlchemy returns a datetime object; ensure we have the date portion
            last_dt = (
                ci_entry.date.date()
                if isinstance(ci_entry.date, datetime)
                else ci_entry.date
            )

            prelim_due = last_dt + timedelta(
                days=MAINTENANCE_RULES["Condition Inspection"]["days"]
            )
            # Find the last day of the month for the due date
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
        except Exception as e:
            print(f"Condition inspection calculation failed: {e}")

    # --- Oil Change Logic ---
    oil_due_str, oil_class = "--", "status-default"

    oil_entry = (
        MaintenanceLog.query.filter_by(recurrent_item="Oil Change")
        .order_by(MaintenanceLog.date.desc(), MaintenanceLog.tach_time.desc())
        .first()
    )

    if oil_entry and oil_entry.tach_time is not None:
        last_oil_tach = validate_float(oil_entry.tach_time)
        next_oil_due = last_oil_tach + MAINTENANCE_RULES["Oil Change"]["hours"]
        hrs_left = round(next_oil_due - current_tach, 1)

        oil_due_str = f"{next_oil_due:.1f} hrs ({hrs_left:.1f} hrs left)"
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


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("index"))

    if request.method == "POST":
        ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        user_agent = request.headers.get("User-Agent", "")
        now = time.time()
        username = request.form.get("username")
        log_user = username or "-"

        # --- Check ban list (SQLAlchemy) ---
        ban_entry = BannedIPs.query.filter_by(ip=ip, username=username).first()

        if ban_entry:
            if now - ban_entry.ban_time < BAN_DURATION_SECONDS:
                login_security_logger.warning(
                    "banned_ip_attempt",
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
            else:
                # Ban expired, remove it
                db.session.delete(ban_entry)
                db.session.commit()

        # --- Rate limit check ---
        with LOGIN_LOCK:
            attempts = LOGIN_ATTEMPTS.get(ip, [])
            attempts = [t for t in attempts if now - t < BLOCK_WINDOW_SECONDS]
            LOGIN_ATTEMPTS[ip] = attempts

            if len(attempts) >= MAX_ATTEMPTS:
                # Re-fetch ban_entry in case it was deleted above
                ban_entry = BannedIPs.query.filter_by(ip=ip, username=username).first()

                if ban_entry:
                    ban_entry.count += 1
                else:
                    ban_entry = BannedIPs(ip=ip, username=username, ban_time=0, count=1)
                    db.session.add(ban_entry)

                # Check if we should elevate to a timed ban
                if ban_entry.count >= BAN_THRESHOLD:
                    ban_entry.ban_time = now
                    db.session.commit()

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

                db.session.commit()

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
        user = Users.query.filter_by(username=username).first()
        # user = User.query.filter_by(username=request.form.get("username")).first()
        if user and check_password_hash(user.password_hash, password):
            # reset attempts on success
            with LOGIN_LOCK:
                LOGIN_ATTEMPTS.pop(ip, None)

            # Clear any ban tracking for this user/ip combo
            BannedIPs.query.filter_by(ip=ip, username=username).delete()
            db.session.commit()

            remember = request.form.get("remember") == "on"
            session["user_id"] = user.id
            session.permanent = remember

            login_success_logger.info(
                "login_success",
                extra={
                    "ip": ip,
                    "user": log_user,
                    "status": "success",
                    "ua": user_agent,
                },
            )
            login_user(user)
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
    # Helper to convert SQLAlchemy models to dictionaries so existing template
    # and sorting logic continues to work seamlessly without modifications.
    def model_to_dict(obj):
        if not obj:
            return {}
        return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}

    def sort_and_format_logs(logs_list):
        def parse_to_datetime(d):
            if not d:
                return datetime.min
            # SQLAlchemy natively returns datetime objects
            if isinstance(d, datetime):
                return d

            # Fallback for string representations
            for fmt in (
                "%Y-%m-%d",
                "%m/%d/%Y",
                "%m-%d-%Y",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
            ):
                try:
                    return datetime.strptime(str(d), fmt)
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
                parse_to_datetime(x.get("date")),
                hobbs_val(x),
            ),
            reverse=True,
        )
        for log in sorted_logs:
            dt = parse_to_datetime(log.get("date"))
            if dt != datetime.min:
                log["date"] = dt.strftime("%Y-%m-%d")
                log["display_date"] = dt.strftime("%m/%d/%Y")
            else:
                log["display_date"] = str(log.get("date", ""))
        return sorted_logs

    # --- Fetch and format logs using SQLAlchemy ---
    flight_logs_raw = [model_to_dict(row) for row in FlightLog.query.all()]
    mx_logs_raw = [model_to_dict(row) for row in MaintenanceLog.query.all()]
    fuel_logs_raw = [model_to_dict(row) for row in FuelLog.query.all()]

    flight_logs = sort_and_format_logs(flight_logs_raw)
    mx_logs = sort_and_format_logs(mx_logs_raw)
    fuel_logs = sort_and_format_logs(fuel_logs_raw)

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
    latest_flight = FlightLog.query.order_by(FlightLog.hobbs.desc()).first()

    total_hobbs = validate_float(latest_flight.hobbs) if latest_flight else 0.0
    total_tach = validate_float(latest_flight.tach) if latest_flight else 0.0

    # Keep legacy total_hours for compatibility
    total_hours = total_hobbs

    # --- Get latest Hobbs from fuel tracker ---
    latest_fuel = FuelLog.query.order_by(FuelLog.hobbs.desc()).first()

    latest_fuel_hobbs = validate_float(latest_fuel.hobbs) if latest_fuel else 0.0

    # --- Sum total landings ---
    total_landings = db.session.query(func.sum(FlightLog.landings)).scalar() or 0

    # --- Fuel Cost Metrics ---
    total_fuel_cost = 0.0
    total_gallons = 0.0
    cost_per_month = 0.0
    insurance_per_year = 2400
    insurance_per_month = insurance_per_year / 12
    hangar_per_month = 605
    taxes_per_year = 0.01 * 150000
    taxes_per_month = taxes_per_year / 12
    xpndr_check = 125
    xpndr_check_per_month = xpndr_check / 24
    foreflight_year = 250
    foreflight_month = foreflight_year / 12
    airmate_year = 49
    airmate_month = airmate_year / 12
    atc_year = 89
    atc_month = atc_year / 12

    for f in fuel_logs:
        try:
            gallons = float(f.get("gallons", 0) or 0)
            price = float(f.get("price_per_gallon", 0) or 0)
            total_gallons += gallons
            total_fuel_cost += gallons * price
        except Exception:
            continue

    total_fuel_cost = round(total_fuel_cost, 2)
    total_gallons = round(total_gallons, 2) - 40

    avg_gph = (
        round(total_gallons / latest_fuel_hobbs, 2) if latest_fuel_hobbs > 0 else 0.0
    )

    avg_fuel_cost_per_hour = (
        round(total_fuel_cost / total_hours, 2) if total_hours > 0 else 0.0
    )
    print(avg_gph, db.session.query(func.avg(FuelLog.gal_per_hour)).scalar() or 0)

    total_fuel_cost = db.session.query(func.sum(FuelLog.total_cost)).scalar() or 0
    first_flight_date = db.session.query(func.min(FlightLog.date)).scalar()
    today = datetime.now()
    years_diff = today.year - first_flight_date.year
    months_diff = today.month - first_flight_date.month
    total_months = (years_diff * 12) + months_diff
    total_months = max(total_months, 1)
    cost_per_month = (
        total_fuel_cost / total_months
        + insurance_per_month
        + hangar_per_month
        + taxes_per_month
        + xpndr_check_per_month
        + foreflight_month
        + airmate_month
        + atc_month
    )
    # avg_price_per_gallon = (
    #     db.session.query(func.avg(FuelLog.price_per_gallon)).scalar() or 0
    # )
    # total_gallons_qry = db.session.query(func.sum(FuelLog.gallons)).scalar() or 0

    # Note: Passed without 'conn' assuming these helpers have also been refactored
    # to use SQLAlchemy queries directly as requested in prior steps.
    overdue_items = calculate_overdue_items()
    nav_status = get_nav_database_status()
    upcoming_mx = get_upcoming_maintenance()

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
        cost_per_month=cost_per_month,
        avg_fuel_cost_per_hour=avg_fuel_cost_per_hour,
        avg_gph=avg_gph,
        oil_results=None,
    )


@app.route("/add_flight", methods=["POST"])
@login_required
def add_flight():
    # Create a new FlightLog object using values from the form
    new_flight = FlightLog(
        date=parse_date_obj(request.form.get("date")),
        takeoff_airport=request.form.get("takeoff").upper(),
        landing_airport=request.form.get("landing").upper(),
        hobbs=validate_float(request.form.get("hobbs")),
        tach=validate_float(request.form.get("tach")),
        landings=int(request.form.get("landings", 0)),
        notes=request.form.get("notes"),
    )

    # Add to the session and commit to the database
    db.session.add(new_flight)
    db.session.commit()

    # Call helpers (assuming these have been updated to use the SQLAlchemy session)
    recompute_flight_history()
    check_auto_maintenance()

    # Trigger external synchronization
    git_push_data()

    return redirect(url_for("index", _anchor="flight"))


@app.route("/add_mx", methods=["POST"])
@login_required
def add_mx():
    # Create a new MaintenanceLog object using values from the form
    new_mx = MaintenanceLog(
        date=parse_date_obj(request.form.get("date")),
        tach_time=validate_float(request.form.get("tach")),
        airframe_time=validate_float(request.form.get("airframe")),
        recurrent_item=request.form.get("recurrent_item"),
        category=request.form.get("category"),
        notes=request.form.get("notes"),
    )

    # Add to the session and commit
    db.session.add(new_mx)
    db.session.commit()

    # Call the updated helper functions (no connection parameter needed)
    recompute_flight_history()
    check_auto_maintenance()

    # Reset the nav cache
    global NAV_CACHE
    NAV_CACHE = {"data": None, "timestamp": 0}

    # Trigger external synchronization
    git_push_data()

    return redirect(url_for("index", _anchor="mx"))


@app.route("/add_fuel", methods=["POST"])
@login_required
def add_fuel():
    hobbs, gallons, price = (
        validate_float(request.form.get("hobbs")),
        validate_float(request.form.get("gallons")),
        validate_float(request.form.get("price")),
    )

    # Create a new FuelLog object mapping to the fuel_tracker table
    new_fuel = FuelLog(
        date=parse_date_obj(request.form.get("date")),
        hobbs=hobbs,
        gallons=gallons,
        price_per_gallon=price,
        total_cost=round(gallons * price, 2),
        gal_per_hour=round(gallons / hobbs, 2) if hobbs > 0 else 0,
    )

    # Add to the session and commit
    db.session.add(new_fuel)
    db.session.commit()

    # Trigger external synchronization
    git_push_data()

    return redirect(url_for("index", _anchor="fuel"))


@app.route("/edit_flight/<int:id>", methods=["POST"])
@login_required
def edit_flight(id):
    # Fetch the existing flight record or return a 404 if not found
    flight = FlightLog.query.get_or_404(id)

    # Update the object attributes directly
    flight.date = parse_date_obj(request.form.get("date"))
    flight.takeoff_airport = request.form.get("takeoff").upper()
    flight.landing_airport = request.form.get("landing").upper()
    flight.hobbs = validate_float(request.form.get("hobbs"))
    flight.tach = validate_float(request.form.get("tach"))
    flight.landings = int(request.form.get("landings", 0))
    flight.notes = request.form.get("notes")

    # Commit the changes to the database
    db.session.commit()

    # Call updated helpers (no connection object required)
    recompute_flight_history()
    check_auto_maintenance()

    # Trigger external synchronization
    git_push_data()

    return redirect(url_for("index", _anchor="flight"))


@app.route("/edit_mx/<int:id>", methods=["POST"])
@login_required
def edit_mx(id):
    # Fetch the existing maintenance record or return a 404
    mx_entry = MaintenanceLog.query.get_or_404(id)

    # Update attributes directly from form data
    mx_entry.date = parse_date_obj(request.form.get("date"))
    mx_entry.tach_time = validate_float(request.form.get("tach"))
    mx_entry.airframe_time = validate_float(request.form.get("airframe"))
    mx_entry.recurrent_item = request.form.get("recurrent_item")
    mx_entry.category = request.form.get("category")
    mx_entry.notes = request.form.get("notes")

    # Save changes to the database
    db.session.commit()

    # Update logs and check reminders using updated helpers
    recompute_flight_history()
    check_auto_maintenance()

    # Invalidate the navigation database cache
    global NAV_CACHE
    NAV_CACHE = {"data": None, "timestamp": 0}

    # Synchronize data
    git_push_data()

    return redirect(url_for("index", _anchor="mx"))


@app.route("/edit_fuel/<int:id>", methods=["POST"])
@login_required
def edit_fuel(id):
    # Fetch the existing fuel record or return a 404
    fuel_entry = FuelLog.query.get_or_404(id)

    hours, gallons, price = (
        validate_float(request.form.get("hobbs")),
        validate_float(request.form.get("gallons")),
        validate_float(request.form.get("price")),
    )

    # Update attributes directly
    fuel_entry.date = parse_date_obj(request.form.get("date"))
    fuel_entry.hobbs = hours
    fuel_entry.gallons = gallons
    fuel_entry.price_per_gallon = price
    fuel_entry.total_cost = round(gallons * price, 2)
    fuel_entry.gal_per_hour = round(gallons / hours, 2) if hours > 0 else 0

    # SQLAlchemy tracks these changes and syncs them on commit
    db.session.commit()

    # Trigger external synchronization
    git_push_data()

    return redirect(url_for("index", _anchor="fuel"))


@app.route("/delete_flight/<int:id>")
@login_required
def delete_flight(id):
    # Fetch the record by ID or return a 404 if it doesn't exist
    flight = FlightLog.query.get_or_404(id)

    # Delete the object from the session
    db.session.delete(flight)

    # Commit the transaction to the database
    db.session.commit()

    # Recompute history (using the SQLAlchemy-based helper)
    recompute_flight_history()

    # Trigger external synchronization
    git_push_data()

    return redirect(url_for("index", _anchor="flight"))


@app.route("/delete_maintenance/<int:id>")
@login_required
def delete_maintenance(id):
    # Fetch the maintenance record or return 404
    mx_entry = MaintenanceLog.query.get_or_404(id)

    # Delete the record from the session
    db.session.delete(mx_entry)

    # Commit the transaction
    db.session.commit()

    # Update history and maintenance logic using SQLAlchemy-based helpers
    recompute_flight_history()
    check_auto_maintenance()

    # Invalidate the navigation database cache
    global NAV_CACHE
    NAV_CACHE = {"data": None, "timestamp": 0}

    # Synchronize data
    git_push_data()

    return redirect(url_for("index", _anchor="mx"))


@app.route("/delete_fuel/<int:id>")
@login_required
def delete_fuel(id):
    # Fetch the fuel record by ID or return 404 if not found
    fuel_entry = FuelLog.query.get_or_404(id)

    # Delete the record from the session
    db.session.delete(fuel_entry)

    # Commit the transaction to the database
    db.session.commit()

    # Trigger external synchronization
    git_push_data()

    return redirect(url_for("index", _anchor="fuel"))


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


@app.route("/upload_oil_analysis", methods=["POST"])
# @login_required
def upload_oil_analysis():
    logs = OilAnalysis.query.order_by(OilAnalysis.engine_hrs.asc()).all()

    if "oil_pdf" not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files["oil_pdf"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    if file and file.filename.endswith(".pdf"):
        upload_folder = os.path.join(app.static_folder, "oil_analysis")
        os.makedirs(upload_folder, exist_ok=True)

        filepath = os.path.join(upload_folder, secure_filename(file.filename))
        file.save(filepath)

        try:
            # Parse the PDF and return the dictionary as JSON
            results = parse_oil_report(filepath)
            try:
                sample_date = datetime.strptime(
                    results["metadata"]["date_sampled"], "%d-%b-%y"
                ).date()
            except Exception:
                sample_date = datetime.utcnow().date()
            sample_no = results["metadata"].get("sample_no")
            exists = [
                True if float(sample_no) == float(log.sample_no) else False
                for log in logs
            ]
            print(exists)
            if not any(exists):
                # Save to Database using SQLAlchemy
                new_entry = OilAnalysis(
                    date_sampled=sample_date,
                    oil_hrs=float(results["metadata"].get("oil_hrs", 0)),
                    engine_hrs=float(results["metadata"].get("engine_hrs", 0)),
                    iron=float(results["metals"].get("Iron", 0)),
                    copper=float(results["metals"].get("Copper", 0)),
                    chromium=float(results["metals"].get("Chromium", 0)),
                    aluminum=float(results["metals"].get("Aluminium", 0)),
                    nickel=float(results["metals"].get("Nickel", 0)),
                    lead=float(results["metals"].get("Lead", 0)),
                    diagnosis=results.get("diagnosis", ""),
                    report_path=filepath,
                    sample_no=results["metadata"].get("sample_no"),
                )

                db.session.add(new_entry)
                db.session.commit()
                return jsonify(results)
            else:
                return jsonify({"error": "Analysis Already Exists"}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return jsonify({"error": "Only PDF files are allowed"}), 400


@app.route("/api/oil_trends")
def get_oil_trends():
    logs = OilAnalysis.query.order_by(OilAnalysis.engine_hrs.asc()).all()
    history = []
    for log in logs:
        history.append(
            {
                "engine_hrs": log.engine_hrs,
                "iron": log.iron,
                "copper": log.copper,
                "chromium": log.chromium,
                "aluminum": log.aluminum,
                "nickel": log.nickel,
                "lead": log.lead,
                "date": log.date_sampled.strftime("%Y-%m-%d"),
            }
        )
    return jsonify(history)


@app.route("/api/estimate_fuel", methods=["POST"])
# @login_required  <-- Uncomment if your app uses login_required
def estimate_fuel():
    data = request.json

    # Get slider heights (defaulting to 0 if missing)
    left_height = float(data.get("left_height", 0))
    right_height = float(data.get("right_height", 0))

    # Calculate using defaults (TILT_DEG, CHORD_TILT_DEG) from your script
    left_gal, _ = calculate_fuel(left_height)
    right_gal, _ = calculate_fuel(right_height)

    return jsonify(
        {
            "left_gallons": left_gal,
            "right_gallons": right_gal,
            "total_gallons": left_gal + right_gal,
        }
    )


@app.route("/live_map")
# @login_required # Uncomment if you want to restrict this to logged-in users
def live_map():
    return render_template("live_map.html")


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
            print(request.files)
            if "saved_filename" not in request.files:
                return jsonify({"error": "No file part"}), 400
            file = request.files["saved_filename"]
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
                saved_filename = f"{safe_name}.csv"
                filepath = os.path.join(SAVE_DIR, saved_filename)
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
            "Oil Pressure (PSI)",
            "Fuel Pressure (PSI)",
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
    # Use SQLAlchemy to query all records ordered by date and ID
    rows = FlightLog.query.order_by(FlightLog.date.desc(), FlightLog.id.desc()).all()

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
                r.id,
                r.date,
                r.takeoff_airport,
                r.landing_airport,
                r.hobbs,
                r.tach,
                r.landings,
                r.notes,
                r.hobbs_delta,
                r.tach_delta,
            ]
        )

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=Flight_Logs.csv"
    output.headers["Content-type"] = "text/csv"
    return output


@app.route("/export/mx")
@login_required
def export_mx():
    # Use SQLAlchemy to query all maintenance entries ordered by date and ID
    rows = MaintenanceLog.query.order_by(
        MaintenanceLog.date.desc(), MaintenanceLog.id.desc()
    ).all()

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
                r.id,
                r.date,
                r.tach_time,
                r.airframe_time,
                r.recurrent_item,
                r.category,
                r.notes,
            ]
        )

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=Maintenance_Logs.csv"
    output.headers["Content-type"] = "text/csv"
    return output


@app.route("/export/fuel")
@login_required
def export_fuel():
    # Query all fuel tracker records ordered by date and ID
    rows = FuelLog.query.order_by(FuelLog.date.desc(), FuelLog.id.desc()).all()

    si = StringIO()
    cw = csv.writer(si)

    # Headers for fuel
    cw.writerow(
        ["ID", "Date", "Hobbs", "Gallons", "Price Per Gallon", "Total Cost", "GPH"]
    )

    for r in rows:
        cw.writerow(
            [
                r.id,
                r.date,
                r.hobbs,
                r.gallons,
                r.price_per_gallon,
                r.total_cost,
                r.gal_per_hour,
            ]
        )

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=Fuel_Logs.csv"
    output.headers["Content-type"] = "text/csv"
    return output


@login_manager.user_loader
def load_user(user_id):
    return Users.query.get(int(user_id))


@app.errorhandler(413)
@app.errorhandler(RequestEntityTooLarge)
def app_handle_413(e):
    return jsonify({"error": "File is too large. Max size is 64MB."}), 413


@app.context_processor
def inject_categories():
    return dict(categories=Category.query.order_by(Category.name).all())


@app.route("/blog")
def blog():
    search_query = request.args.get("search", "")
    cat_name = request.args.get("category", "")
    tag_name = request.args.get("tag", "")

    query = Post.query

    # 1. Filter by Search
    if search_query:
        query = query.filter(
            Post.title.contains(search_query) | Post.content.contains(search_query)
        )

    # 2. Filter by Category
    if cat_name:
        query = query.join(Post.categories).filter(Category.name == cat_name)

    # 3. Filter by Tag
    if tag_name:
        query = query.join(Post.tags).filter(Tag.name == tag_name)

    # 4. Fetch the posts
    posts = query.order_by(Post.created_at.desc()).all()

    # 5. Fetch Sidebar Data (Crucial for the widgets to appear)
    categories = Category.query.all()
    all_tags = Tag.query.all()

    return render_template(
        "blog.html",
        posts=posts,
        categories=categories,
        all_tags=all_tags,
        current_cat=cat_name,
        current_tag=tag_name,
    )


@app.route("/admin/new_post", methods=["GET", "POST"])
@login_required
def new_post():
    if request.method == "POST":
        title = request.form.get("title")
        content = request.form.get("content")
        selected_cat_ids = request.form.getlist(
            "categories"
        )  # Gets list of IDs from checkboxes

        slug = re.sub(r"[-\s]+", "-", re.sub(r"[^\w\s-]", "", title).strip().lower())
        post = Post(title=title, slug=slug, content=content)

        # Add existing categories by ID
        for cid in selected_cat_ids:
            cat = Category.query.get(cid)
            if cat:
                post.categories.append(cat)

        tags_input = request.form.get("tags", "")
        if tags_input:
            # Split by comma, remove whitespace, and ignore empty strings
            tag_names = [n.strip() for n in tags_input.split(",") if n.strip()]
            for name in tag_names:
                tag = Tag.query.filter_by(name=name).first()
                if not tag:
                    tag = Tag(name=name)
                    db.session.add(tag)
                post.tags.append(tag)

        db.session.add(post)
        db.session.commit()
        return redirect(url_for("view_post", slug=post.slug))

    categories = Category.query.order_by(Category.name).all()
    files = (
        os.listdir(app.config["UPLOAD_FOLDER"])
        if os.path.exists(app.config["UPLOAD_FOLDER"])
        else []
    )
    return render_template("editor.html", categories=categories, post=None, files=files)


@app.route("/admin/edit/<int:post_id>", methods=["GET", "POST"])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    if request.method == "POST":
        post.title = request.form.get("title")
        post.content = request.form.get("content")

        # Clear and re-add categories
        post.categories = []
        for cid in request.form.getlist("categories"):
            cat = Category.query.get(cid)
            if cat:
                post.categories.append(cat)

        post.tags = []
        tags_input = request.form.get("tags", "")
        tag_names = [n.strip() for n in tags_input.split(",") if n.strip()]
        for name in tag_names:
            tag = Tag.query.filter_by(name=name).first()
            if not tag:
                tag = Tag(name=name)
                db.session.add(tag)
            post.tags.append(tag)

        db.session.commit()
        return redirect(url_for("view_post", slug=post.slug))

    categories = Category.query.order_by(Category.name).all()
    all_tags = Tag.query.all()
    files = (
        os.listdir(app.config["UPLOAD_FOLDER"])
        if os.path.exists(app.config["UPLOAD_FOLDER"])
        else []
    )
    return render_template(
        "editor.html",
        post=post,
        categories=categories,
        all_tags=all_tags,
        files=files,
    )


@app.route("/admin/delete/<int:post_id>", methods=["GET", "POST"])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    if not post:
        flash("Post not found.")
        return redirect(url_for("blog"))

    # Remove associations in the many-to-many table first (SQLAlchemy usually handles this, but being explicit is safer)
    post.categories = []
    post.tags = []

    db.session.delete(post)
    db.session.commit()
    flash("Post deleted successfully.")
    return redirect(url_for("blog"))


@app.route("/admin/media/upload", methods=["POST"])
@login_required
def upload_to_gallery():
    if "file" not in request.files:
        flash("No file part")
        return redirect(request.url)

    file = request.files["file"]
    if file.filename == "":
        flash("No selected file")
        return redirect(request.url)

    if file:
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
        flash(f"File {filename} uploaded successfully!")

    return redirect(url_for("media_gallery"))


@app.route("/admin/media")
@login_required
def media_gallery():
    # List all files in the upload directory
    files = []
    if os.path.exists(app.config["UPLOAD_FOLDER"]):
        files = os.listdir(app.config["UPLOAD_FOLDER"])
        # Sort by newest first (optional)
        files.sort(
            key=lambda x: os.path.getmtime(
                os.path.join(app.config["UPLOAD_FOLDER"], x)
            ),
            reverse=True,
        )

    return render_template("media.html", files=files)


@app.route("/admin/media/delete/<filename>", methods=["POST"])
@login_required
def delete_media(filename):
    # Secure the filename to prevent directory traversal attacks
    filename = secure_filename(filename)
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)

    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            flash(f"File {filename} deleted successfully.")
        else:
            flash(f"Error: File {filename} not found.", "error")
    except Exception as e:
        flash(f"Error deleting file: {str(e)}", "error")

    return redirect(url_for("media_gallery"))


@app.route("/post/<slug>")
def view_post(slug):
    post = Post.query.filter_by(slug=slug).first_or_404()
    return render_template("post.html", post=post)


@app.route("/admin/category/add", methods=["POST"])
@login_required
def add_category():
    name = request.form.get("name")
    if name:
        existing = Category.query.filter_by(name=name).first()
        if not existing:
            new_cat = Category(name=name)
            db.session.add(new_cat)
            db.session.commit()
            return jsonify({"success": True, "id": new_cat.id, "name": new_cat.name})
    return jsonify({"success": False}), 400


@app.context_processor
def inject_sidebar_data():
    return dict(
        categories=Category.query.order_by(Category.name).all(),
        all_tags=Tag.query.order_by(Tag.name).all(),  # Add this
    )


if __name__ == "__main__":
    # if not Users.query.filter_by(username="george").first():
    #     db.session.add(
    #         Users(username="george", password=generate_password_hash("Soccer10"))
    #     )
    # db.session.commit()
    app.run(debug=DEBUG)
