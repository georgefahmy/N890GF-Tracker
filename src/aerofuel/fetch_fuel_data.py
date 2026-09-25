#!/usr/bin/env python3
"""
fetch_fuel_data.py
Manages, fetches, builds, validates, and exports the comprehensive aviation
fuel and public-use airport dataset for AeroFuel IQ.
Catalog ingests the authoritative OurAirports / FAA NASR dataset covering
all US states and territories (airports, frequencies, and runways).
"""

import argparse
import csv
import json
import math
import os
import re
import sys
import time
import urllib.request

try:
    from .airnav_client import AirNavClient, _urlopen_with_ssl_fallback
    from .build_airport_database import (
        get_data_path,
        load_runways,
        load_frequencies,
        normalize_surface,
    )
except ImportError:
    from airnav_client import AirNavClient, _urlopen_with_ssl_fallback
    from build_airport_database import (
        get_data_path,
        load_runways,
        load_frequencies,
        normalize_surface,
    )

DIRECTORY = os.path.dirname(os.path.abspath(__file__))

# Primary GA reference airports for default live sync tasks
DEFAULT_SYNC_AIRPORTS = [
    "KSQL", "KPAO", "KHAF", "KRHV", "KTCY", "KCVH", "E16", "KBOI", "KBOS", "KDAL"
]


def find_ourairports_csv():
    """Locate authoritative OurAirports airports.csv from data directory."""
    return get_data_path("airports.csv")


def map_aviation_identifiers(row):
    """
    Applies FAA / ICAO / IATA standards to an OurAirports row:
    - faa: FAA LID (e.g. CVH for Hollister, SQL for San Carlos, E16 for San Martin, O22 for Columbia)
    - icao: Standard ICAO or primary GA identifier (KCVH, KSQL, KHAF, E16, O22, C83, 0Q5)
    - iata: IATA commercial code (HLI for Hollister, SFO, etc.)
    """
    ident = row.get("ident", "").strip().upper()
    gps = row.get("gps_code", "").strip().upper()
    local = row.get("local_code", "").strip().upper()
    iata = row.get("iata_code", "").strip().upper()
    region = row.get("iso_region", "").strip()
    country = row.get("iso_country", "").strip().upper()

    if country in ("PR", "VI", "GU", "AS", "MP", "UM"):
        state = country
    elif region.startswith("US-") and "-" in region:
        state = region.split("-")[1]
    elif any(
        region.startswith(tc + "-") for tc in ("PR", "VI", "GU", "AS", "MP", "UM")
    ):
        state = region.split("-")[0]
    else:
        state = country

    # 1. Map FAA LID
    if local:
        faa = local
    elif (
        len(ident) == 4
        and ident.startswith("K")
        and ident[1:].isalpha()
        and state not in ("AK", "HI", "PR", "VI", "GU", "AS", "MP", "UM")
    ):
        faa = ident[1:]
    elif (
        len(gps) == 4
        and gps.startswith("K")
        and gps[1:].isalpha()
        and state not in ("AK", "HI", "PR", "VI", "GU", "AS", "MP", "UM")
    ):
        faa = gps[1:]
    elif (
        ident.startswith("K")
        and len(ident) in (4, 5)
        and any(ch.isdigit() for ch in ident)
    ):
        faa = ident[1:]
    elif iata:
        faa = iata
    elif gps:
        faa = gps
    else:
        faa = ident

    # 2. Map Primary ICAO / Airport Identifier
    # - In CONUS: 3-letter FAA LIDs prefix with 'K' (CVH -> KCVH, SQL -> KSQL, HAF -> KHAF).
    # - 3-character/4-character alphanumeric airfields (E16, O22, C83, 0Q5, O88, 1B1) retain their FAA LID.
    # - Alaska/Hawaii/Territories use standard 4-letter ICAO when available (PANC, PHNL, TJSJ), or FAA LID.
    if (
        len(ident) == 4
        and ident.isalpha()
        and (
            ident.startswith("K")
            or state in ("AK", "HI", "PR", "VI", "GU", "AS", "MP", "UM")
        )
    ):
        icao = ident
    elif len(gps) == 4 and gps.isalpha():
        icao = gps
    elif (
        len(faa) == 3
        and faa.isalpha()
        and state not in ("AK", "HI", "PR", "VI", "GU", "AS", "MP", "UM")
    ):
        icao = "K" + faa
    else:
        icao = faa or ident

    return icao, faa, iata, state


def is_valid_us_coord(state, lat, lon):
    """Validates that coordinates are within authentic physical bounds for the specified US state/territory."""
    if state == "AK":
        return (51.0 <= lat <= 72.0) and (
            -180.0 <= lon <= -130.0 or 170.0 <= lon <= 180.0
        )
    elif state == "HI":
        return (18.0 <= lat <= 29.0) and (-179.0 <= lon <= -154.0)
    elif state in ("PR", "VI"):
        return (17.0 <= lat <= 19.5) and (-68.5 <= lon <= -64.0)
    elif state in ("GU", "MP"):
        return (13.0 <= lat <= 21.0) and (144.0 <= lon <= 146.5)
    elif state == "AS":
        return (-15.0 <= lat <= -11.0) and (-171.0 <= lon <= -168.0)
    elif state == "UM":
        return (-1.0 <= lat <= 30.0) and (-180.0 <= lon <= 180.0)
    else:
        # CONUS
        return (24.0 <= lat <= 50.0) and (-125.5 <= lon <= -66.5)


PRIVATE_KEYWORDS = [
    "(private)",
    "[private]",
    "ranch strip",
    "farm strip",
    "hospital",
    "clinic",
    "helipad",
    "heliport",
]


def is_private_facility(row):
    """
    Strictly filters out private facilities based on FAA identifier patterns and keywords:
    - 4-character FAA private patterns: 2 numbers + 2 letters (00AA, 00CA, 12CA, 00TX, 01FL),
      2 letters + 2 numbers (CA01, TX12, FL04), 1 number + 2 letters + 1 number (9CL2, 1CA5, 2TX3),
      or any 4-character code with 2 or more digits.
    - In CONUS: any 4-character identifier not starting with 'K' or containing private patterns.
    - Synthetic OurAirports identifiers (US-xxxx, PR-xxxx).
    - Private keywords in airport name or keywords ((Private), [Private], Ranch Strip, Farm Strip, Hospital, Clinic, Helipad, Heliport, Private).
    """
    raw_ident = row.get("ident", "").strip().upper()
    gps = row.get("gps_code", "").strip().upper()
    local = row.get("local_code", "").strip().upper()
    name = row.get("name", "").strip()
    keywords = row.get("keywords", "").strip()
    region = row.get("iso_region", "").strip()
    country = row.get("iso_country", "").strip().upper()

    if country in ("PR", "VI", "GU", "AS", "MP", "UM"):
        state = country
    elif region.startswith("US-") and "-" in region:
        state = region.split("-")[1]
    elif any(
        region.startswith(tc + "-") for tc in ("PR", "VI", "GU", "AS", "MP", "UM")
    ):
        state = region.split("-")[0]
    else:
        state = country

    # 1. Synthetic identifiers (US-xxxx, PR-xxxx)
    if raw_ident.startswith("US-") or (
        raw_ident.startswith("PR-") and len(raw_ident) > 4
    ):
        return True

    # 2. Private facility keywords in name or keywords
    name_lower = name.lower()
    keywords_lower = keywords.lower()
    for kw in PRIVATE_KEYWORDS:
        if kw in name_lower or kw in keywords_lower:
            return True
    if re.search(r"\bprivate\b", name_lower) or re.search(
        r"\bprivate\b", keywords_lower
    ):
        return True

    # 3. Check FAA identifier:
    is_conus = state not in ("AK", "HI", "PR", "VI", "GU", "AS", "MP", "UM")

    if local:
        if len(local) == 4:
            digits = sum(1 for c in local if c.isdigit())
            if digits >= 2:
                return True
            if is_conus and not local.startswith("K") and digits >= 1:
                return True
        elif len(local) > 4:
            return True

    if len(raw_ident) == 4:
        digits = sum(1 for c in raw_ident if c.isdigit())
        if digits >= 3:
            return True
        if is_conus and not raw_ident.startswith("K"):
            return True
        if not is_conus and digits >= 2:
            return True
    elif len(raw_ident) > 4:
        return True

    return False


def load_authoritative_airports():
    """Ingests all US public-use airports from OurAirports dataset with strict private filtering, type filtering and deduplication."""
    csv_path = find_ourairports_csv()
    if not csv_path or not os.path.exists(csv_path):
        raise FileNotFoundError(
            "Authoritative airports.csv dataset could not be located."
        )

    type_rank = {
        "large_airport": 4,
        "medium_airport": 3,
        "small_airport": 2,
        "seaplane_base": 1,
    }
    airports_by_icao = {}

    with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for row in reader:
            c = row.get("iso_country", "").strip().upper()
            r = row.get("iso_region", "").strip()
            t = row.get("type", "").strip()

            is_us = (
                c == "US"
                or r.startswith("US-")
                or c in ("PR", "VI", "GU", "AS", "MP", "UM")
                or any(
                    r.startswith(tc + "-")
                    for tc in ("PR", "VI", "GU", "AS", "MP", "UM")
                )
            )
            if is_us and t in type_rank and not is_private_facility(row):
                icao, faa, iata, state = map_aviation_identifiers(row)
                name = row.get("name", "").strip()
                municipality = row.get("municipality", "").strip()

                lat_str = row.get("latitude_deg", "").strip()
                lon_str = row.get("longitude_deg", "").strip()
                if not lat_str or not lon_str:
                    continue

                try:
                    lat = round(float(lat_str), 4)
                    lon = round(float(lon_str), 4)
                except ValueError:
                    continue

                if not is_valid_us_coord(state, lat, lon):
                    continue

                elev_str = row.get("elevation_ft", "").strip()
                elevation_ft = int(float(elev_str)) if elev_str else 100

                entry = {
                    "icao": icao,
                    "faa": faa,
                    "iata": iata,
                    "name": name,
                    "city": municipality or name,
                    "state": state,
                    "country": "US",
                    "lat": lat,
                    "lon": lon,
                    "elevation_ft": elevation_ft,
                    "type": t,
                    "raw_ident": row.get("ident", "").strip().upper(),
                    "airport_ref": row.get("id", "").strip(),
                }

                # Deterministic deduplication: prefer authentic FAA LID over synthetic 'US-xxxx' ident, then higher type rank
                if icao in airports_by_icao:
                    existing = airports_by_icao[icao]
                    existing_synthetic = existing["raw_ident"].startswith("US-")
                    new_synthetic = entry["raw_ident"].startswith("US-")
                    if existing_synthetic and not new_synthetic:
                        airports_by_icao[icao] = entry
                    elif not existing_synthetic and new_synthetic:
                        pass
                    elif type_rank.get(t, 0) > type_rank.get(existing["type"], 0):
                        airports_by_icao[icao] = entry
                else:
                    airports_by_icao[icao] = entry

    return airports_by_icao


def build_dataset():
    """Generates the unified 5,000+ US public-use airport catalog directly from OurAirports CSVs."""
    raw_airports = load_authoritative_airports()
    runways_by_ident, runways_by_ref = load_runways()
    freqs_by_ident, freqs_by_ref = load_frequencies()

    dataset = []

    # Sort keys for deterministic output ordering
    sorted_icaos = sorted(raw_airports.keys())

    for idx, icao in enumerate(sorted_icaos):
        raw = raw_airports[icao]
        faa = raw["faa"]
        raw_ident = raw.get("raw_ident", "")
        ref = raw.get("airport_ref", "")

        # Look up authentic runways from runways.csv
        csv_runways = (
            runways_by_ref.get(ref)
            or runways_by_ident.get(icao)
            or runways_by_ident.get(raw_ident)
            or runways_by_ident.get(faa)
            or (runways_by_ident.get(icao[1:]) if icao.startswith("K") else None)
            or (runways_by_ident.get("K" + faa) if len(faa) == 3 else None)
        )

        # Look up authentic frequencies from airport-frequencies.csv
        freq_list = (
            freqs_by_ref.get(ref)
            or freqs_by_ident.get(icao)
            or freqs_by_ident.get(raw_ident)
            or freqs_by_ident.get(faa)
            or (freqs_by_ident.get(icao[1:]) if icao.startswith("K") else None)
            or (freqs_by_ident.get("K" + faa) if len(faa) == 3 else None)
            or []
        )

        has_tower = False
        tower_freq = None
        ctaf_freq = None
        unicom_freq = None
        weather_freq = None
        weather_type = None
        weather_desc = None
        approach_freq = None
        approach_desc = None
        departure_freq = None
        departure_desc = None
        ground_freq = None
        ground_desc = None
        cld_freq = None
        cld_desc = None

        for f_item in freq_list:
            ftype = f_item["type"]
            fmhz = f_item["frequency_mhz"]
            fdesc = f_item.get("description") or ftype
            fdesc_upper = fdesc.upper()

            if ftype in ("TWR", "TOWER", "TWR/APP", "TWR/CTAF", "TWR 1", "TWR 2") or "TOWER" in fdesc_upper:
                has_tower = True
                if tower_freq is None:
                    tower_freq = fmhz
            if ("CTAF" in ftype) or ("CTAF" in fdesc_upper):
                if ctaf_freq is None:
                    ctaf_freq = fmhz
            elif ("UNIC" in ftype) or ("UNICOM" in fdesc_upper):
                if unicom_freq is None:
                    unicom_freq = fmhz

            if (ftype in ("ATIS", "AWOS", "ASOS") or "ATIS" in fdesc_upper or "AWOS" in fdesc_upper or "ASOS" in fdesc_upper) and weather_freq is None:
                weather_freq = fmhz
                weather_type = "ATIS" if ("ATIS" in ftype or "ATIS" in fdesc_upper) else "AWOS"
                weather_desc = fdesc

            if (ftype in ("APP", "A/D", "ARR", "RADAR") or "APP" in fdesc_upper) and approach_freq is None:
                approach_freq = fmhz
                approach_desc = fdesc

            if (ftype in ("DEP",) or "DEP" in fdesc_upper) and departure_freq is None:
                departure_freq = fmhz
                departure_desc = fdesc

            if (ftype in ("GND", "GROUND") or "GND" in fdesc_upper) and ground_freq is None:
                ground_freq = fmhz
                ground_desc = fdesc

            if (ftype in ("CLD", "CD", "DELIVERY") or "CLD" in fdesc_upper or "DELIVERY" in fdesc_upper) and cld_freq is None:
                cld_freq = fmhz
                cld_desc = fdesc

        if not has_tower and raw.get("type") in ("large_airport", "medium_airport"):
            has_tower = True

        # Harmonize CTAF and UNICOM frequencies so there is no artificial divergence
        if ctaf_freq is None and unicom_freq is not None:
            ctaf_freq = unicom_freq
        elif unicom_freq is None and ctaf_freq is not None:
            unicom_freq = ctaf_freq
        elif ctaf_freq is None and unicom_freq is None:
            if has_tower and tower_freq:
                ctaf_freq = tower_freq
                unicom_freq = 122.95
            else:
                ctaf_freq = 122.8
                unicom_freq = 122.8

        # Fallback runway if missing from runways.csv
        if not csv_runways:
            csv_runways = [{"id": "09/27", "length": 3500, "surface": "Paved"}]

        entry = {
            "icao": icao,
            "faa": faa,
            "iata": raw.get("iata", ""),
            "name": raw["name"],
            "city": raw["city"],
            "state": raw["state"],
            "country": "US",
            "lat": raw["lat"],
            "lon": raw["lon"],
            "elevation_ft": raw["elevation_ft"],
            "tower": has_tower,
            "tower_freq": round(tower_freq, 3) if tower_freq else None,
            "ctaf_freq": round(ctaf_freq, 3),
            "unicom_freq": round(unicom_freq, 3),
            "weather_freq": round(weather_freq, 3) if weather_freq else None,
            "weather_type": weather_type,
            "weather_desc": weather_desc,
            "approach_freq": round(approach_freq, 3) if approach_freq else None,
            "approach_desc": approach_desc,
            "departure_freq": round(departure_freq, 3) if departure_freq else None,
            "departure_desc": departure_desc,
            "ground_freq": round(ground_freq, 3) if ground_freq else None,
            "ground_desc": ground_desc,
            "clearance_freq": round(cld_freq, 3) if cld_freq else None,
            "clearance_desc": cld_desc,
            "frequencies": freq_list,
            "runways": csv_runways,
            "fbos": [],
            "best_price": None,
            "primary_fuel": None,
            "fuels_available": [],
            "last_updated": None,
            "source": "FAA National Airspace System Resource (NASR) / OurAirports",
            "raw_ident": raw_ident,
            "airport_ref": ref,
        }
        dataset.append(entry)

    return dataset


def validate_dataset(data):
    """Validates data schema, unique primary identifiers, geographic bounds, and price integrity."""
    errors = []
    seen_icaos = set()
    seen_states = set()

    for idx, apt in enumerate(data):
        icao = apt.get("icao")
        if not icao:
            errors.append(f"Airport #{idx} missing ICAO code")
        if icao in seen_icaos:
            errors.append(f"Duplicate ICAO code: {icao}")
        seen_icaos.add(icao)

        lat = apt.get("lat")
        lon = apt.get("lon")
        if lat is None or not (-90 <= lat <= 90):
            errors.append(f"{icao}: Invalid latitude {lat}")
        if lon is None or not (-180 <= lon <= 180):
            errors.append(f"{icao}: Invalid longitude {lon}")

        state = apt.get("state")
        if not state:
            errors.append(f"{icao}: Missing airport state")
        else:
            seen_states.add(state)

        best_price = apt.get("best_price")
        if best_price is not None:
            if best_price <= 0 or best_price > 30.0:
                errors.append(f"{icao}: Suspicious or invalid best_price {best_price}")

        if not apt.get("name"):
            errors.append(f"{icao}: Missing airport name")
        if not apt.get("city"):
            errors.append(f"{icao}: Missing airport city")

    for s in ["CA", "TX", "NY", "FL", "IL", "AK", "HI", "PR", "VI", "GU"]:
        if s not in seen_states:
            errors.append(f"Missing state representation: {s}")

    return errors


def print_stats(data):
    priced = [a for a in data if a.get("best_price") is not None]
    unpriced = [a for a in data if a.get("best_price") is None]
    prices = [a["best_price"] for a in priced]

    min_p = min(prices) if prices else 0
    max_p = max(prices) if prices else 0
    avg_p = sum(prices) / len(prices) if prices else 0

    states = set(a["state"] for a in data)

    print("=" * 65)
    print("           AEROFUEL IQ COMPREHENSIVE US AIRPORT DATASET")
    print("=" * 65)
    print(f"Total Public-Use Airports Cataloged : {len(data):,}")
    print(f"Airports with Active Fuel Rates     : {len(priced):,}")
    print(f"Unreported / Non-Commercial Fields   : {len(unpriced):,}")
    print(f"States & Territories Represented    : {len(states)}")
    if prices:
        print(f"Lowest Avgas Price in Catalog       : ${min_p:.2f}/gal")
        print(f"Highest Avgas Price in Catalog      : ${max_p:.2f}/gal")
        print(f"National Average Fuel Price         : ${avg_p:.2f}/gal")
    print("=" * 65)


def sync_airnav_prices(
    target_icaos=None, delay=0.5, dry_run=False
):
    """
    Scrapes live fuel rates from AirNav for specified or top GA airports
    and updates individual cache files in .airnav_cache/.
    """
    data = build_dataset()
    apt_map = {a["icao"]: a for a in data}
    for a in data:
        if a.get("faa") and a["faa"] not in apt_map:
            apt_map[a["faa"]] = a

    if not target_icaos:
        target_icaos = DEFAULT_SYNC_AIRPORTS

    client = AirNavClient(request_delay=delay)
    print(f"📡 Fetching live AirNav prices for {len(target_icaos)} airport(s)...")

    updated_count = 0
    for icao in target_icaos:
        clean_icao = icao.strip().upper()
        try:
            print(f"  -> Scraping AirNav for {clean_icao}...")
            res = client.get_airport_fuel(
                clean_icao, force_refresh=True
            )
            target_apt = apt_map.get(clean_icao)
            if res and res.get("fbos"):
                if target_apt:
                    target_apt["fbos"] = res["fbos"]
                    target_apt["best_price"] = res["best_price"]
                    target_apt["primary_fuel"] = res["primary_fuel"]
                    target_apt["fuels_available"] = res["fuels_available"]
                    target_apt["last_updated"] = res["last_updated"]
                    target_apt["fetched_at"] = res.get("fetched_at") or time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                    )
                    target_apt["source"] = res.get("source", "AirNav Live Feed")
                    updated_count += 1
                    print(
                        f"     ✅ Updated {clean_icao}: Best Price ${res['best_price']}, {len(res['fbos'])} FBO(s) [{target_apt['source']}]"
                    )
                else:
                    print(f"     ⚠️ {clean_icao} not found in catalog, skipping merge")
            else:
                if target_apt:
                    target_apt["fetched_at"] = (
                        res.get("fetched_at") if res else None
                    ) or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                print(f"     ℹ️ No active fuel rates on AirNav for {clean_icao}")
        except Exception as e:
            print(f"     ❌ Error fetching {clean_icao}: {e}")

    print(f"Successfully synced {updated_count} airport(s) with live AirNav rates.")
    print_stats(data)
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AeroFuel IQ Data Ingestion and AirNav Price Sync"
    )
    parser.add_argument(
        "--source",
        choices=["default", "nasr", "airnav"],
        default="default",
        help="Data source to ingest from (default, nasr, or airnav)",
    )
    parser.add_argument(
        "--airports",
        type=str,
        default="",
        help="Comma-separated list of airport ICAOs (e.g. KSQL,KPAO,KHAF,KCVH)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay in seconds between consecutive AirNav requests (default: 0.5s)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Fetch prices without writing to disk"
    )
    parser.add_argument(
        "--sync-ourairports",
        action="store_true",
        help="Download fresh airports.csv, airport-frequencies.csv, and runways.csv into the /data folder and rebuild database",
    )

    args = parser.parse_args()

    if args.sync_ourairports:
        print("🌐 Syncing OurAirports data directly into /data/ folder...")
        import build_airport_database
        from airnav_client import DEFAULT_USER_AGENT

        urls = {
            "airports.csv": "https://davidmegginson.github.io/ourairports-data/airports.csv",
            "airport-frequencies.csv": "https://davidmegginson.github.io/ourairports-data/airport-frequencies.csv",
            "runways.csv": "https://davidmegginson.github.io/ourairports-data/runways.csv",
        }
        for fname, url in urls.items():
            dest = os.path.join(build_airport_database.DATA_DIR, fname)
            print(f"  -> Downloading {url} to {dest}...")
            req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
            with _urlopen_with_ssl_fallback(req, timeout=60) as resp:
                with open(dest, "wb") as f_out:
                    f_out.write(resp.read())
            print(f"     ✅ Saved {dest} ({os.path.getsize(dest):,} bytes)")

        print("🔨 Rebuilding database with fresh OurAirports data...")
        build_airport_database.build_database()
        print("✅ OurAirports sync complete. All files saved to /data/ folder.")
        sys.exit(0)

    if args.source == "airnav":
        target_list = (
            [c.strip().upper() for c in args.airports.split(",") if c.strip()]
            if args.airports
            else None
        )
        sync_airnav_prices(
            target_icaos=target_list,
            delay=args.delay,
            dry_run=args.dry_run,
        )
    else:
        data = build_dataset()
        errors = validate_dataset(data)
        if errors:
            print(f"Validation failed with {len(errors)} errors:")
            for e in errors[:10]:
                print(f"  - {e}")
            sys.exit(1)

        print(f"Successfully generated and validated {len(data):,} airport records directly from CSVs.")
        print_stats(data)
