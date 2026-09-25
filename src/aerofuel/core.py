#!/usr/bin/env python3
"""
core.py
Core data layer and master catalog management for AeroFuel IQ in N890GF Tracker.
Provides in-memory caching, OurAirports CSV parsing, AirNav cache indexing,
and lightweight pre-serialized JSON streaming.
"""

import csv
import json
import os
import sys
import time
from typing import Dict, List, Optional, Any

try:
    from .airnav_client import AirNavClient
except ImportError:
    from airnav_client import AirNavClient

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "data", "aerofuel")
if not os.path.exists(DATA_DIR):
    DATA_DIR = os.path.join(PROJECT_ROOT, "data")
CACHE_DIR = os.path.join(DATA_DIR, ".airnav_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# Global AirNav client instance targeting the aerofuel cache
airnav = AirNavClient(
    cache_dir=CACHE_DIR,
    cache_ttl=259200,  # 3 days (3 * 24 * 3600 seconds)
    request_delay=1.0,
)

# In-memory master catalog cache
_catalog_cache = None
_cached_directory = None


def load_all_airnav_cache(cache_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Scans and indexes all individual airport fuel cache files from .airnav_cache/*.json.
    Returns a dict mapping clean uppercase ICAO/FAA codes to their cached airport fuel data.
    """
    if cache_dir is None:
        cache_dir = CACHE_DIR
    if not os.path.exists(cache_dir):
        return {}

    cache_map = {}
    try:
        filenames = os.listdir(cache_dir)
    except Exception:
        return {}

    for fname in filenames:
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


def load_catalog(directory: str = DATA_DIR, force_reload: bool = False) -> Dict[str, Any]:
    """
    Load or retrieve cached master public airport catalog directly from OurAirports CSVs in-memory.
    Attaches cached individual fuel JSONs if available in .airnav_cache/.
    """
    global _catalog_cache, _cached_directory
    if (
        _catalog_cache is not None
        and _cached_directory == directory
        and not force_reload
    ):
        return _catalog_cache

    # 1. First, check if fuel_data.json exists (for mock test fixtures in temporary directories)
    fuel_file = os.path.join(directory, "fuel_data.json")
    if os.path.exists(fuel_file) and directory != DATA_DIR:
        try:
            with open(fuel_file, "r", encoding="utf-8") as f:
                _catalog_cache = json.load(f)
                _cached_directory = directory
                return _catalog_cache
        except Exception:
            pass

    # 2. Build directly from authoritative OurAirports CSV dataset
    try:
        try:
            from . import fetch_fuel_data
        except ImportError:
            import fetch_fuel_data

        airports_list = fetch_fuel_data.build_dataset()
        cache_map = load_all_airnav_cache()
        for apt in airports_list:
            icao = (apt.get("icao") or "").upper().strip()
            faa = (apt.get("faa") or "").upper().strip()
            raw_ident = (apt.get("raw_ident") or "").upper().strip()
            cached_fuel = (
                cache_map.get(icao)
                or (cache_map.get(faa) if faa else None)
                or (cache_map.get(raw_ident) if raw_ident else None)
                or (cache_map.get(icao[1:]) if icao.startswith("K") else None)
            )
            if cached_fuel:
                apt["fbos"] = cached_fuel.get("fbos", [])
                apt["best_price"] = cached_fuel.get("best_price")
                apt["primary_fuel"] = cached_fuel.get("primary_fuel")
                apt["fuels_available"] = cached_fuel.get("fuels_available", [])
                apt["last_updated"] = cached_fuel.get("last_updated")
                apt["fetched_at"] = cached_fuel.get("fetched_at")
                if cached_fuel.get("source"):
                    apt["source"] = cached_fuel.get("source")
    except Exception as e:
        print(
            f"Notice: Error building in-memory catalog from CSV: {e}", file=sys.stderr
        )
        airports_list = []

    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    now_human = time.strftime("%b %d, %Y %I:%M %p UTC", time.gmtime())

    _catalog_cache = {
        "version": "2.5.29",
        "last_synced": now_iso,
        "last_synced_human": now_human,
        "source": "https://ourairports.com/data/",
        "total_airports": len(airports_list),
        "airports": airports_list,
    }
    _cached_directory = directory
    return _catalog_cache


_summary_bytes_cache = None
_summary_cached_dir = None


def get_summary_catalog_bytes(directory: str = DATA_DIR, force_reload: bool = False) -> bytes:
    """
    Returns pre-encoded UTF-8 bytes for data/aerofuel/airports_summary.json.
    Enables ultra-fast catalog streaming without redundant JSON serialization.
    """
    global _summary_bytes_cache, _summary_cached_dir
    if (
        _summary_bytes_cache is not None
        and _summary_cached_dir == directory
        and not force_reload
    ):
        return _summary_bytes_cache

    summary_file = os.path.join(directory, "airports_summary.json")
    if not os.path.exists(summary_file):
        summary_file = os.path.join(DATA_DIR, "airports_summary.json")

    if os.path.exists(summary_file) and not force_reload:
        try:
            with open(summary_file, "rb") as f:
                _summary_bytes_cache = f.read()
                _summary_cached_dir = directory
                return _summary_bytes_cache
        except Exception:
            pass

    catalog = load_catalog(directory=directory, force_reload=force_reload)
    airports = catalog.get("airports", [])
    summary_airports = []
    for apt in airports:
        summary_obj = {
            "icao": apt.get("icao"),
            "faa": apt.get("faa"),
            "iata": apt.get("iata", ""),
            "name": apt.get("name"),
            "city": apt.get("city"),
            "state": apt.get("state"),
            "country": "US",
            "lat": apt.get("lat"),
            "lon": apt.get("lon"),
            "elevation_ft": apt.get("elevation_ft"),
            "tower": apt.get("tower", False),
            "tower_freq": apt.get("tower_freq"),
            "ctaf_freq": apt.get("ctaf_freq"),
            "unicom_freq": apt.get("unicom_freq"),
            "weather_freq": apt.get("weather_freq"),
            "weather_type": apt.get("weather_type"),
            "weather_desc": apt.get("weather_desc"),
            "approach_freq": apt.get("approach_freq"),
            "approach_desc": apt.get("approach_desc"),
            "departure_freq": apt.get("departure_freq"),
            "departure_desc": apt.get("departure_desc"),
            "ground_freq": apt.get("ground_freq"),
            "ground_desc": apt.get("ground_desc"),
            "clearance_freq": apt.get("clearance_freq"),
            "clearance_desc": apt.get("clearance_desc"),
            "frequencies": apt.get("frequencies", []),
            "runways": apt.get("runways", []),
            "fbos": apt.get("fbos", []),
            "best_price": apt.get("best_price"),
            "primary_fuel": apt.get("primary_fuel"),
            "fuels_available": apt.get("fuels_available", []),
            "last_updated": apt.get("last_updated"),
            "fetched_at": apt.get("fetched_at"),
        }
        summary_airports.append(summary_obj)

    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    now_human = time.strftime("%b %d, %Y %I:%M %p UTC", time.gmtime())
    summary_payload = {
        "version": catalog.get("version", "2.5.29"),
        "last_synced": now_iso,
        "last_synced_human": now_human,
        "total_airports": len(summary_airports),
        "airports": summary_airports,
    }

    _summary_bytes_cache = json.dumps(summary_payload, separators=(",", ":")).encode("utf-8")
    _summary_cached_dir = directory

    # Persist to airports_summary.json if directory is DATA_DIR
    if directory == DATA_DIR:
        try:
            summary_file = os.path.join(DATA_DIR, "airports_summary.json")
            with open(summary_file, "wb") as f:
                f.write(_summary_bytes_cache)
        except Exception:
            pass

    return _summary_bytes_cache


_ourairports_lookup_cache = None


def get_public_ourairports_lookup(directory: str = DATA_DIR) -> Dict[str, Any]:
    """
    Returns an index of authentic public airports parsed from data/aerofuel/airports.csv.
    Used to guarantee only genuine public airports are ever hydrated into the catalog.
    """
    global _ourairports_lookup_cache
    if _ourairports_lookup_cache is not None:
        return _ourairports_lookup_cache

    csv_path = os.path.join(directory, "airports.csv")
    if not os.path.exists(csv_path):
        csv_path = os.path.join(DATA_DIR, "airports.csv")

    lookup = {}
    if os.path.exists(csv_path):
        try:
            try:
                from .fetch_fuel_data import is_private_facility
            except ImportError:
                from fetch_fuel_data import is_private_facility

            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    if r.get("iso_country") == "US" or (
                        r.get("iso_region") or ""
                    ).startswith("US-"):
                        if r.get("type") in (
                            "large_airport",
                            "medium_airport",
                            "small_airport",
                            "seaplane_base",
                        ):
                            if not is_private_facility(r):
                                ident = (r.get("ident") or "").upper().strip()
                                icao = (r.get("icao_code") or "").upper().strip()
                                local = (r.get("local_code") or "").upper().strip()
                                iata = (r.get("iata_code") or "").upper().strip()
                                gps = (r.get("gps_code") or "").upper().strip()
                                entry = {
                                    "icao": icao or ident,
                                    "faa": local
                                    or (
                                        ident[1:]
                                        if ident.startswith("K")
                                        and len(ident) == 4
                                        and not ident[1:].isdigit()
                                        else ident
                                    ),
                                    "iata": iata,
                                    "name": r.get("name") or f"{ident} Airport",
                                    "city": r.get("municipality") or "",
                                    "state": (
                                        r.get("iso_region", "").split("-")[-1]
                                        if r.get("iso_region")
                                        else ""
                                    ),
                                    "country": "US",
                                    "lat": float(r.get("latitude_deg") or 0.0),
                                    "lon": float(r.get("longitude_deg") or 0.0),
                                    "elevation_ft": int(
                                        float(r.get("elevation_ft") or 0)
                                    ),
                                    "ctaf_freq": 122.8,
                                    "unicom_freq": 122.8,
                                    "runways": [
                                        {
                                            "id": "01/19",
                                            "length": 3000,
                                            "surface": "Asphalt",
                                        }
                                    ],
                                }
                                for k in (ident, icao, local, iata, gps):
                                    if k and k not in lookup:
                                        lookup[k] = entry
        except Exception:
            pass

    _ourairports_lookup_cache = lookup
    return lookup


def update_stored_fuel_data(airport_data: Any, directory: str = DATA_DIR) -> List[str]:
    """
    Updates the in-memory master dataset and saves each airport directly to its
    individual .airnav_cache/<ICAO>.json file without rewriting monolithic disk files.
    """
    global _catalog_cache, _cached_directory
    catalog = load_catalog(directory=directory, force_reload=False)
    if catalog is None:
        return []

    airports = catalog.get("airports", [])
    apt_by_ident = {}
    for a in airports:
        if a.get("icao"):
            apt_by_ident[str(a["icao"]).upper().strip()] = a
        if a.get("faa"):
            apt_by_ident[str(a["faa"]).upper().strip()] = a
        if a.get("iata"):
            apt_by_ident[str(a["iata"]).upper().strip()] = a

    # Normalize airport_data into a list of airport dicts
    items_to_process = []
    if isinstance(airport_data, dict):
        if "icao" in airport_data and (
            "fbos" in airport_data
            or "best_price" in airport_data
            or "name" in airport_data
        ):
            items_to_process.append(airport_data)
        else:
            for k, v in airport_data.items():
                if isinstance(v, dict) and not v.get("error"):
                    items_to_process.append(v)
    elif isinstance(airport_data, list):
        for v in airport_data:
            if isinstance(v, dict) and not v.get("error"):
                items_to_process.append(v)

    updated_icaos = []
    for scraped in items_to_process:
        if not scraped or scraped.get("error"):
            continue
        icao_code = str(scraped.get("icao") or "").upper().strip()
        faa_code = str(scraped.get("faa") or "").upper().strip()
        iata_code = str(scraped.get("iata") or "").upper().strip()

        if not icao_code and not faa_code:
            continue

        # Robust identifier matching across ICAO, FAA, IATA, and 3/4-letter K prefixes
        target_apt = None
        for code in (icao_code, faa_code, iata_code):
            if code and code in apt_by_ident:
                target_apt = apt_by_ident[code]
                break

        if not target_apt and icao_code:
            if (
                icao_code.startswith("K")
                and len(icao_code) == 4
                and icao_code[1:] in apt_by_ident
            ):
                target_apt = apt_by_ident[icao_code[1:]]
            elif len(icao_code) == 3 and ("K" + icao_code) in apt_by_ident:
                target_apt = apt_by_ident["K" + icao_code]

        if target_apt:
            if "fbos" in scraped and scraped["fbos"] is not None:
                target_apt["fbos"] = scraped["fbos"]

            # Compute or update best_price
            if "best_price" in scraped and scraped["best_price"] is not None:
                target_apt["best_price"] = scraped["best_price"]
            elif target_apt.get("fbos"):
                prices = []
                for fbo in target_apt["fbos"]:
                    for fkey, fobj in fbo.get("fuels", {}).items():
                        if isinstance(fobj, dict):
                            ftype = fobj.get("type")
                            pval = fobj.get("price")
                            if ftype not in ("Jet-A", "SAF") and pval and pval > 0:
                                prices.append(pval)
                target_apt["best_price"] = min(prices) if prices else None
            elif "best_price" in scraped and scraped["best_price"] is None:
                target_apt["best_price"] = None

            # Compute or update primary_fuel and fuels_available
            if "fuels_available" in scraped and scraped["fuels_available"] is not None:
                target_apt["fuels_available"] = scraped["fuels_available"]
            elif target_apt.get("fbos"):
                avail = set()
                for fbo in target_apt["fbos"]:
                    for fkey, fobj in fbo.get("fuels", {}).items():
                        if isinstance(fobj, dict) and fobj.get("type"):
                            avail.add(fobj["type"])
                target_apt["fuels_available"] = sorted(list(avail))

            if "primary_fuel" in scraped and scraped["primary_fuel"]:
                target_apt["primary_fuel"] = scraped["primary_fuel"]
            elif target_apt.get("fuels_available"):
                fuels_set = set(target_apt["fuels_available"])
                for pref in ("100LL", "94UL", "100UL", "100R", "Mogas"):
                    if pref in fuels_set:
                        target_apt["primary_fuel"] = pref
                        break
                if not target_apt.get("primary_fuel"):
                    target_apt["primary_fuel"] = "100LL" if target_apt.get("best_price") else "None"

            clean_save_ident = target_apt.get("icao") or icao_code
            if clean_save_ident:
                airnav.save_to_cache(clean_save_ident, target_apt)

            recorded_ident = target_apt.get("icao") or icao_code
            if recorded_ident and recorded_ident not in updated_icaos:
                updated_icaos.append(recorded_ident)
        else:
            # Check if airport is an authentic public airport in our authoritative OurAirports directory
            public_lookup = get_public_ourairports_lookup(directory)
            matched_meta = None
            for code in (icao_code, faa_code, iata_code):
                if code and code in public_lookup:
                    matched_meta = public_lookup[code]
                    break
            if not matched_meta and icao_code:
                if (
                    icao_code.startswith("K")
                    and len(icao_code) == 4
                    and icao_code[1:] in public_lookup
                ):
                    matched_meta = public_lookup[icao_code[1:]]
                elif len(icao_code) == 3 and ("K" + icao_code) in public_lookup:
                    matched_meta = public_lookup["K" + icao_code]

            if matched_meta:
                primary_fuel = scraped.get("primary_fuel")
                best_price = scraped.get("best_price")
                if not primary_fuel:
                    primary_fuel = "100LL" if best_price else "None"

                new_entry = {
                    "icao": matched_meta["icao"] or icao_code,
                    "faa": matched_meta["faa"] or faa_code,
                    "iata": matched_meta.get("iata") or iata_code,
                    "name": matched_meta.get("name")
                    or scraped.get("name", f"{icao_code} Airport"),
                    "city": matched_meta.get("city") or scraped.get("city", ""),
                    "state": matched_meta.get("state") or scraped.get("state", ""),
                    "country": "US",
                    "lat": matched_meta.get("lat") or scraped.get("lat", 0.0),
                    "lon": matched_meta.get("lon") or scraped.get("lon", 0.0),
                    "elevation_ft": matched_meta.get("elevation_ft", 0),
                    "ctaf_freq": matched_meta.get("ctaf_freq", 122.8),
                    "unicom_freq": matched_meta.get("unicom_freq", 122.8),
                    "runways": matched_meta.get(
                        "runways",
                        [{"id": "01/19", "length": 3000, "surface": "Asphalt"}],
                    ),
                    "fbos": scraped.get("fbos", []),
                    "best_price": best_price,
                    "primary_fuel": primary_fuel,
                    "fuels_available": scraped.get("fuels_available", []),
                    "last_updated": scraped.get(
                        "last_updated", time.strftime("%Y-%m-%d")
                    ),
                    "fetched_at": scraped.get(
                        "fetched_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    ),
                    "source": scraped.get("source", "AirNav Live Feed"),
                }
                airports.append(new_entry)
                new_ident = new_entry["icao"]
                apt_by_ident[new_ident] = new_entry
                if new_entry.get("faa"):
                    apt_by_ident[new_entry["faa"]] = new_entry
                airnav.save_to_cache(new_ident, new_entry)
                if new_ident not in updated_icaos:
                    updated_icaos.append(new_ident)

    if updated_icaos:
        global _summary_bytes_cache
        _summary_bytes_cache = None
        if isinstance(catalog, dict):
            catalog["airports"] = airports
            catalog["total_airports"] = len(airports)
            catalog["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _catalog_cache = catalog
        _cached_directory = directory

    return updated_icaos
