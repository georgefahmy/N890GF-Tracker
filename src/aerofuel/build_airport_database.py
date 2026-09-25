#!/usr/bin/env python3
"""
build_airport_database.py
Authoritative airport directory and frequencies database builder for AeroFuel IQ.
Parses OurAirports CSV files (`airports.csv` and `airport-frequencies.csv`) as the primary
source of truth for public-use airport identifiers, locations, runway info, and radio frequencies.
Preserves existing fuel price and FBO cache across rebuilds.
"""

import csv
import json
import os
import sys
from datetime import datetime, timezone

try:
    from . import fetch_fuel_data
except ImportError:
    import fetch_fuel_data

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "data", "aerofuel")
if not os.path.exists(DATA_DIR):
    # Fallback to local data dir if running in standalone aerofuel repo
    DATA_DIR = os.path.join(PROJECT_ROOT, "data") if os.path.exists(os.path.join(PROJECT_ROOT, "data")) else os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

AIRPORTS_CSV = os.path.join(DATA_DIR, "airports.csv")
FREQUENCIES_CSV = os.path.join(DATA_DIR, "airport-frequencies.csv")
RUNWAYS_CSV = os.path.join(DATA_DIR, "runways.csv")
METADATA_JSON = os.path.join(DATA_DIR, ".ourairports_meta.json")

# Normalize OurAirports surface codes to human-readable labels
SURFACE_MAP = {
    "ASPH": "Asphalt",
    "ASPH-G": "Asphalt",
    "ASPH-CONC": "Asphalt/Concrete",
    "ASP": "Asphalt",
    "ASPH-F": "Asphalt",
    "ASPH-G-F": "Asphalt",
    "CONC": "Concrete",
    "CONC-G": "Concrete",
    "CONC-ASPH": "Concrete/Asphalt",
    "TURF": "Turf",
    "TURF-G": "Turf",
    "TURF-ASPH": "Turf/Asphalt",
    "GRVL": "Gravel",
    "GVL": "Gravel",
    "GRVL-TURF": "Gravel/Turf",
    "DIRT": "Dirt",
    "DIRT-G": "Dirt",
    "SAND": "Sand",
    "WATER": "Water",
    "SNOW": "Snow",
    "ICE": "Ice",
    "MATS": "PSP/Mats",
    "OIL": "Oil/Chip",
    "ROOFTOP": "Rooftop",
}


def normalize_surface(raw):
    """Convert an OurAirports surface code to a human-readable string."""
    if not raw:
        return "Paved"
    upper = raw.strip().upper()
    if upper in SURFACE_MAP:
        return SURFACE_MAP[upper]
    # Try prefix match (e.g. "ASPH-G-F" → Asphalt)
    for key, label in SURFACE_MAP.items():
        if upper.startswith(key):
            return label
    # Capitalise unknown codes as-is
    return raw.strip().title()


def get_data_path(filename):
    """Locates data file from project data folder, project root, or server directory."""
    candidates = [
        os.path.join(DATA_DIR, filename),
        os.path.join(PROJECT_ROOT, filename),
        os.path.join(BASE_DIR, filename),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return os.path.join(DATA_DIR, filename)


def load_runways():
    """
    Load and index all runways from runways.csv (OurAirports schema).
    Returns (runways_by_ident, runways_by_ref) dicts.
    Each runway dict has keys: id, length, width, surface, lighted.
    """
    runways_by_ident = {}
    runways_by_ref = {}
    csv_path = get_data_path("runways.csv")

    if not os.path.exists(csv_path):
        return runways_by_ident, runways_by_ref

    with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if clean_str(row.get("closed")) == "1":
                continue

            ident = clean_str(row.get("airport_ident")).upper()
            ref = clean_str(row.get("airport_ref"))

            length_raw = clean_str(row.get("length_ft"))
            width_raw = clean_str(row.get("width_ft"))
            surface_raw = clean_str(row.get("surface"))
            lighted_raw = clean_str(row.get("lighted"))
            le_ident = clean_str(row.get("le_ident"))
            he_ident = clean_str(row.get("he_ident"))

            try:
                length = int(float(length_raw)) if length_raw else 0
            except (ValueError, TypeError):
                length = 0

            try:
                width = int(float(width_raw)) if width_raw else 0
            except (ValueError, TypeError):
                width = 0

            if le_ident and he_ident:
                rwy_id = f"{le_ident}/{he_ident}"
            elif le_ident:
                rwy_id = le_ident
            else:
                rwy_id = "Unknown"

            rwy = {
                "id": rwy_id,
                "length": length,
                "width": width,
                "surface": normalize_surface(surface_raw),
                "lighted": lighted_raw == "1",
            }

            if ident:
                runways_by_ident.setdefault(ident, []).append(rwy)
            if ref:
                runways_by_ref.setdefault(ref, []).append(rwy)

    for ident in runways_by_ident:
        runways_by_ident[ident].sort(key=lambda r: r["length"], reverse=True)
    for ref in runways_by_ref:
        runways_by_ref[ref].sort(key=lambda r: r["length"], reverse=True)

    return runways_by_ident, runways_by_ref


def clean_str(val):
    if val is None:
        return ""
    return str(val).strip()


def parse_float(val, default=0.0):
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def load_frequencies():
    """Load and index all frequencies from airport-frequencies.csv."""
    freqs_by_ident = {}
    freqs_by_ref = {}

    if not os.path.exists(FREQUENCIES_CSV):
        print(f"Warning: {FREQUENCIES_CSV} not found.")
        return freqs_by_ident, freqs_by_ref

    with open(FREQUENCIES_CSV, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ident = clean_str(row.get("airport_ident")).upper()
            ref = clean_str(row.get("airport_ref"))
            ftype = clean_str(row.get("type")).upper()
            desc = clean_str(row.get("description"))
            mhz_raw = parse_float(row.get("frequency_mhz"), 0.0)

            if mhz_raw <= 0:
                continue

            freq_item = {
                "type": ftype,
                "description": desc or ftype,
                "frequency_mhz": round(mhz_raw, 3),
            }

            keys = set(filter(None, [ident, ref]))
            if ident.startswith("K") and len(ident) == 4:
                keys.add(ident[1:])
            elif len(ident) == 3:
                keys.add("K" + ident)

            for k in keys:
                freqs_by_ident.setdefault(k, []).append(freq_item)

            if ref:
                freqs_by_ref.setdefault(ref, []).append(freq_item)

    return freqs_by_ident, freqs_by_ref
def load_all_airnav_cache(cache_dir=None):
    """
    Scans and indexes all individual airport fuel cache files from .airnav_cache/*.json.
    Returns a dict mapping clean uppercase ICAO/FAA codes to their cached airport fuel data.
    """
    if cache_dir is None:
        candidates = [
            os.path.join(DATA_DIR, ".airnav_cache"),
            os.path.join(PROJECT_ROOT, "data", "aerofuel", ".airnav_cache"),
            os.path.join(PROJECT_ROOT, "data", ".airnav_cache"),
            os.path.join(PROJECT_ROOT, ".airnav_cache"),
            os.path.join(BASE_DIR, ".airnav_cache"),
        ]
        for c in candidates:
            if os.path.exists(c):
                cache_dir = c
                break
        if cache_dir is None:
            cache_dir = os.path.join(DATA_DIR, ".airnav_cache")
    if not os.path.exists(cache_dir):
        return {}

    cache_map = {}
    for fname in os.listdir(cache_dir):
        if not fname.endswith(".json"):
            continue
        ident_from_filename = fname[:-5].upper().strip()
        fpath = os.path.join(cache_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                obj = json.load(f)
            data = obj.get("data") if isinstance(obj, dict) else None
            if not data or not isinstance(data, dict):
                continue
            
            icao = (data.get("icao") or "").upper().strip()
            faa = (data.get("faa") or "").upper().strip()
            iata = (data.get("iata") or "").upper().strip()

            keys = set(filter(None, [ident_from_filename, icao, faa, iata]))
            for k in list(keys):
                if k.startswith("K") and len(k) == 4:
                    keys.add(k[1:])
                elif len(k) == 3:
                    keys.add("K" + k)

            for k in keys:
                if k not in cache_map:
                    cache_map[k] = data
        except Exception:
            continue

    return cache_map


def build_database():
    """
    Builds the consolidated dataset by reading authentic OurAirports CSVs,
    indexing frequencies and runways, and merging individual .airnav_cache/*.json fuel files.
    """
    print(f"Loading authoritative frequencies from {FREQUENCIES_CSV}...")
    freqs_by_ident, _ = load_frequencies()
    print(f"Indexed frequencies for {len(freqs_by_ident)} airport idents.")

    print(f"Loading authoritative runways from {RUNWAYS_CSV}...")
    runways_by_ident, _ = load_runways()

    print(f"Loading cached fuel rates from .airnav_cache/...")
    airnav_cache = load_all_airnav_cache()
    print(f"Indexed {len(airnav_cache)} airport entries from .airnav_cache/.")

    base_airports = fetch_fuel_data.build_dataset()
    print(f"Built base public dataset with {len(base_airports)} airports.")

    airports = []
    summary_airports = []

    for apt in base_airports:
        icao = (apt.get("icao") or "").upper().strip()
        faa = (apt.get("faa") or "").upper().strip()
        raw_ident = (apt.get("raw_ident") or "").upper().strip()

        # Check if fuel data is cached in .airnav_cache/
        cached_fuel = (
            airnav_cache.get(icao)
            or (airnav_cache.get(faa) if faa else None)
            or (airnav_cache.get(raw_ident) if raw_ident else None)
            or (airnav_cache.get(icao[1:]) if icao.startswith("K") else None)
        )

        fbos = []
        best_price = None
        primary_fuel = None
        fuels_available = []
        last_updated = None
        fetched_at = None
        source = apt.get("source", "FAA National Airspace System Resource (NASR) / OurAirports")

        if cached_fuel:
            fbos = cached_fuel.get("fbos", [])
            best_price = cached_fuel.get("best_price")
            primary_fuel = cached_fuel.get("primary_fuel")
            fuels_available = cached_fuel.get("fuels_available", [])
            last_updated = cached_fuel.get("last_updated")
            fetched_at = cached_fuel.get("fetched_at")
            if cached_fuel.get("source"):
                source = cached_fuel.get("source")

        apt_obj = {
            **apt,
            "fbos": fbos,
            "best_price": best_price,
            "primary_fuel": primary_fuel,
            "fuels_available": fuels_available,
            "last_updated": last_updated,
            "fetched_at": fetched_at,
            "source": source,
        }
        summary_obj = {
            "icao": apt_obj["icao"],
            "faa": apt_obj["faa"],
            "iata": apt_obj.get("iata", ""),
            "name": apt_obj["name"],
            "city": apt_obj["city"],
            "state": apt_obj["state"],
            "country": "US",
            "lat": apt_obj["lat"],
            "lon": apt_obj["lon"],
            "elevation_ft": apt_obj["elevation_ft"],
            "tower": apt_obj["tower"],
            "tower_freq": apt_obj.get("tower_freq"),
            "ctaf_freq": apt_obj["ctaf_freq"],
            "unicom_freq": apt_obj["unicom_freq"],
            "weather_freq": apt_obj.get("weather_freq"),
            "weather_type": apt_obj.get("weather_type"),
            "weather_desc": apt_obj.get("weather_desc"),
            "approach_freq": apt_obj.get("approach_freq"),
            "approach_desc": apt_obj.get("approach_desc"),
            "departure_freq": apt_obj.get("departure_freq"),
            "departure_desc": apt_obj.get("departure_desc"),
            "ground_freq": apt_obj.get("ground_freq"),
            "ground_desc": apt_obj.get("ground_desc"),
            "clearance_freq": apt_obj.get("clearance_freq"),
            "clearance_desc": apt_obj.get("clearance_desc"),
            "frequencies": apt_obj.get("frequencies", []),
            "runways": apt_obj["runways"],
            "fbos": fbos,
            "best_price": apt_obj.get("best_price"),
            "primary_fuel": apt_obj.get("primary_fuel"),
            "fuels_available": apt_obj.get("fuels_available", []),
            "last_updated": apt_obj.get("last_updated"),
            "fetched_at": apt_obj.get("fetched_at"),
        }
        airports.append(apt_obj)
        summary_airports.append(summary_obj)

    # Sort alphabetically by ICAO for deterministic ordering
    airports.sort(key=lambda a: a["icao"])
    summary_airports.sort(key=lambda a: a["icao"])

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_human = datetime.now(timezone.utc).strftime("%b %d, %Y %I:%M %p UTC")

    # Save compact lightweight airports_summary.json for 1.2MB ultra-fast initial catalog load
    summary_path = os.path.join(DATA_DIR, "airports_summary.json")
    summary_payload = {
        "version": "2.5.29",
        "last_synced": now_iso,
        "last_synced_human": now_human,
        "total_airports": len(summary_airports),
        "airports": summary_airports,
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_payload, f, separators=(",", ":"))

    print(f"Generated lightweight catalog summary at {summary_path} ({len(summary_airports)} airports).")

    # Record sync metadata
    runways_mtime = (
        os.path.getmtime(RUNWAYS_CSV) if os.path.exists(RUNWAYS_CSV) else None
    )
    meta = {
        "last_synced_iso": now_iso,
        "last_synced_human": now_human,
        "total_airports": len(airports),
        "total_frequencies_indexed": len(freqs_by_ident),
        "total_runways_indexed": sum(len(v) for v in runways_by_ident.values()),
        "airports_csv_mtime": (
            os.path.getmtime(AIRPORTS_CSV) if os.path.exists(AIRPORTS_CSV) else None
        ),
        "frequencies_csv_mtime": (
            os.path.getmtime(FREQUENCIES_CSV)
            if os.path.exists(FREQUENCIES_CSV)
            else None
        ),
        "runways_csv_mtime": runways_mtime,
    }
    with open(METADATA_JSON, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print(
        f"Database build complete: {len(airports)} public airports successfully processed."
    )
    return meta


if __name__ == "__main__":
    build_database()
