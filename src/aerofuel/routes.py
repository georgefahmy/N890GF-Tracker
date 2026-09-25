#!/usr/bin/env python3
"""
routes.py
Flask Blueprint for AeroFuel IQ radar and API endpoints in N890GF Tracker.
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

from flask import Blueprint, Response, jsonify, render_template, request

from .core import (
    CACHE_DIR,
    DATA_DIR,
    airnav,
    get_public_ourairports_lookup,
    get_summary_catalog_bytes,
    load_catalog,
    update_stored_fuel_data,
)
from .airnav_client import DEFAULT_USER_AGENT, _urlopen_with_ssl_fallback
from .airnav_route import fetch_route

aerofuel_bp = Blueprint("aerofuel", __name__)


@aerofuel_bp.route("/fuel_map")
def fuel_map():
    """Renders the AeroFuel IQ interactive radar dashboard."""
    return render_template("fuel_map.html")


@aerofuel_bp.route("/api/airports", methods=["GET"])
@aerofuel_bp.route("/api/airports/", methods=["GET"])
def api_airports():
    """Streams pre-encoded compact UTF-8 JSON summary of all US public airports (~5MB)."""
    force_reload = request.args.get("reload", "").lower() in ("1", "true")
    summary_bytes = get_summary_catalog_bytes(directory=DATA_DIR, force_reload=force_reload)
    resp = Response(summary_bytes, mimetype="application/json; charset=utf-8")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@aerofuel_bp.route("/api/airport/<target_code>", methods=["GET"])
@aerofuel_bp.route("/api/airports/<target_code>", methods=["GET"])
def api_single_airport(target_code):
    """Returns detailed airport metadata and cached FBO fuel details for a single airport."""
    clean_code = target_code.strip().upper()
    catalog = load_catalog(directory=DATA_DIR)
    airports = catalog.get("airports", [])
    matched = next(
        (
            a
            for a in airports
            if a.get("icao") == clean_code
            or a.get("faa") == clean_code
            or a.get("iata") == clean_code
        ),
        None,
    )
    if not matched and clean_code.startswith("K"):
        matched = next((a for a in airports if a.get("faa") == clean_code[1:]), None)

    if matched:
        cached_fuel = airnav.get_from_cache(matched["icao"], allow_expired=True)
        if cached_fuel and cached_fuel.get("fbos"):
            matched = {
                **matched,
                "fbos": cached_fuel["fbos"],
                "best_price": cached_fuel.get("best_price", matched.get("best_price")),
                "primary_fuel": cached_fuel.get("primary_fuel", matched.get("primary_fuel")),
                "fuels_available": cached_fuel.get("fuels_available", matched.get("fuels_available")),
                "fetched_at": cached_fuel.get("fetched_at", matched.get("fetched_at")),
            }
        return jsonify({"status": "ok", "airport": matched})
    return jsonify({"status": "error", "message": f"Airport '{clean_code}' not found in catalog"}), 404


@aerofuel_bp.route("/api/airnav/health", methods=["GET"])
def api_airnav_health():
    """Health check endpoint for AirNav live proxy service."""
    return jsonify({
        "status": "ok",
        "service": "AeroFuel AirNav Live Proxy",
        "airnav_source": "https://www.airnav.com",
        "cache_ttl_seconds": airnav.cache_ttl,
        "request_delay_seconds": airnav.request_delay,
    })


@aerofuel_bp.route("/api/ourairports/status", methods=["GET"])
def api_ourairports_status():
    """Returns status and last-synced timestamps of OurAirports data files."""
    meta_path = os.path.join(DATA_DIR, ".ourairports_meta.json")
    meta = {}
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            pass

    airports_csv_path = os.path.join(DATA_DIR, "airports.csv")
    freq_csv_path = os.path.join(DATA_DIR, "airport-frequencies.csv")
    runways_csv_path = os.path.join(DATA_DIR, "runways.csv")
    airports_mtime = os.path.getmtime(airports_csv_path) if os.path.exists(airports_csv_path) else None
    freq_mtime = os.path.getmtime(freq_csv_path) if os.path.exists(freq_csv_path) else None
    runways_mtime = os.path.getmtime(runways_csv_path) if os.path.exists(runways_csv_path) else None

    airports_mtime_human = (
        datetime.fromtimestamp(airports_mtime, tz=timezone.utc).strftime("%b %d, %Y %I:%M %p UTC")
        if airports_mtime
        else "Never"
    )

    catalog = load_catalog(DATA_DIR)
    total_airports = meta.get("total_airports") or (len(catalog.get("airports", [])) if catalog else 0)

    return jsonify({
        "status": "ok",
        "service": "OurAirports Authoritative Source Sync",
        "source_url": "https://ourairports.com/data/",
        "last_synced_human": meta.get("last_synced_human") or airports_mtime_human,
        "last_synced_iso": meta.get("last_synced_iso"),
        "airports_csv_mtime": airports_mtime,
        "airports_csv_mtime_human": airports_mtime_human,
        "frequencies_csv_mtime": freq_mtime,
        "runways_csv_mtime": runways_mtime,
        "total_airports": total_airports,
        "total_frequencies_indexed": meta.get("total_frequencies_indexed") or 0,
        "total_runways_indexed": meta.get("total_runways_indexed") or 0,
    })


@aerofuel_bp.route("/api/ourairports/sync", methods=["GET", "POST"])
def api_ourairports_sync():
    """Downloads authoritative OurAirports CSV datasets and rebuilds local database."""
    try:
        from . import build_airport_database

        airports_url = "https://davidmegginson.github.io/ourairports-data/airports.csv"
        freq_url = "https://davidmegginson.github.io/ourairports-data/airport-frequencies.csv"
        runways_url = "https://davidmegginson.github.io/ourairports-data/runways.csv"

        headers = {"User-Agent": DEFAULT_USER_AGENT}
        req_airports = urllib.request.Request(airports_url, headers=headers)
        req_freq = urllib.request.Request(freq_url, headers=headers)
        req_runways = urllib.request.Request(runways_url, headers=headers)

        airports_dest = os.path.join(DATA_DIR, "airports.csv")
        freq_dest = os.path.join(DATA_DIR, "airport-frequencies.csv")
        runways_dest = os.path.join(DATA_DIR, "runways.csv")

        with _urlopen_with_ssl_fallback(req_airports, timeout=30) as resp:
            with open(airports_dest, "wb") as f_out:
                f_out.write(resp.read())

        with _urlopen_with_ssl_fallback(req_freq, timeout=30) as resp:
            with open(freq_dest, "wb") as f_out:
                f_out.write(resp.read())

        with _urlopen_with_ssl_fallback(req_runways, timeout=60) as resp:
            with open(runways_dest, "wb") as f_out:
                f_out.write(resp.read())

        meta = build_airport_database.build_database()
        load_catalog(force_reload=True)

        return jsonify({
            "status": "ok",
            "message": "Successfully downloaded OurAirports data (airports, frequencies, runways) and rebuilt airport database",
            **meta,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to sync OurAirports data: {e}"}), 500


@aerofuel_bp.route("/api/airnav/route", methods=["GET"])
def api_airnav_route():
    """Computes cross-country fuel planning route between origin and destination."""
    origin = request.args.get("origin", "").strip()
    destination = request.args.get("destination", "").strip()
    range_val = request.args.get("range", "400").strip()
    selected_route = request.args.get("selected", "0").strip()

    if not origin or not destination:
        return jsonify({
            "status": "error",
            "message": "Both 'origin' and 'destination' query parameters are required (e.g. /api/airnav/route?origin=KSQL&destination=KDEN&range=400)",
        }), 400

    try:
        route_res = fetch_route(
            origin=origin,
            destination=destination,
            range_value=range_val,
            selected_route=int(selected_route) if selected_route.isdigit() else 0,
        )
        if route_res.get("success"):
            return jsonify({"status": "ok", **route_res})
        status_code = 404 if "not found" in route_res.get("error", "").lower() else 502
        return jsonify({
            "status": "error",
            "message": route_res.get("error", "Route computation failed"),
            **route_res,
        }), status_code
    except Exception as route_err:
        return jsonify({"status": "error", "message": f"Route computation error: {route_err}"}), 500


@aerofuel_bp.route("/api/airnav", methods=["GET"])
@aerofuel_bp.route("/api/airnav/<icao_param>", methods=["GET"])
def api_airnav(icao_param=None):
    """
    Looks up live or cached fuel pricing from AirNav for a given airport ICAO/FAA code,
    plus regional surrounding survey.
    """
    icao = icao_param or request.args.get("icao") or request.args.get("ident")
    if not icao:
        return jsonify({
            "status": "error",
            "message": "Missing 'icao' or 'ident' parameter (e.g. /api/airnav?icao=KSQL)",
        }), 400

    force_refresh = request.args.get("refresh", "false").lower() in ("1", "true", "yes")
    clean_icao = icao.strip().upper()

    try:
        single_target = None
        try:
            single_target = airnav.get_airport_fuel(clean_icao, force_refresh=force_refresh)
        except Exception as single_err:
            print(f"Notice: single airport fuel fetch failed for {clean_icao} ({single_err})", file=sys.stderr)

        local_res = None
        try:
            local_res = airnav.fetch_local_fuel_prices(clean_icao, force_refresh=force_refresh, use_cache=True)
        except Exception as local_err:
            print(f"Notice: local fuel prices fetch failed for {clean_icao} ({local_err})", file=sys.stderr)
            local_res = None

        if local_res and local_res.get("airports"):
            airports_list = local_res.get("airports", [])
            target_data = single_target or local_res.get("target") or (airports_list[0] if airports_list else None)
            is_fallback = bool(local_res.get("fallback", False))
            radius_val = (
                local_res.get("radius_miles")
                if local_res.get("radius_miles") is not None
                else (0 if is_fallback else 45)
            )

            if single_target and single_target.get("fbos"):
                target_data = single_target
                replaced = False
                for idx, apt_item in enumerate(airports_list):
                    if apt_item.get("icao") == clean_icao or apt_item.get("faa") == clean_icao:
                        airports_list[idx] = single_target
                        replaced = True
                        break
                if not replaced:
                    airports_list.insert(0, single_target)

            catalog = load_catalog(DATA_DIR) or {}
            known_public_icaos = {a["icao"].upper() for a in catalog.get("airports", []) if a.get("icao")}
            known_public_faas = {a["faa"].upper() for a in catalog.get("airports", []) if a.get("faa")}

            filtered_airports_list = [
                a
                for a in airports_list
                if (a.get("icao") and a["icao"].upper() in known_public_icaos)
                or (a.get("faa") and a["faa"].upper() in known_public_faas)
                or (a.get("icao") == clean_icao or a.get("faa") == clean_icao)
            ]

            updated_stored_icaos = update_stored_fuel_data(filtered_airports_list, directory=DATA_DIR)
            return jsonify({
                "status": "ok",
                "success": True,
                "icao": clean_icao,
                "source_airport": clean_icao,
                "radius_miles": radius_val,
                "count": len(filtered_airports_list),
                "data": target_data,
                "target": target_data,
                "airports": filtered_airports_list,
                "fallback": is_fallback,
                "updated_stored": bool(updated_stored_icaos),
            })
        else:
            # Fallback to direct single airport query
            data = airnav.fetch_airport_fuel(clean_icao, force_refresh=force_refresh)
            if data:
                updated_stored_icaos = update_stored_fuel_data(data, directory=DATA_DIR)
                return jsonify({
                    "status": "ok",
                    "success": True,
                    "icao": clean_icao,
                    "source_airport": clean_icao,
                    "radius_miles": 0,
                    "count": 1,
                    "data": data,
                    "target": data,
                    "airports": [data],
                    "fallback": True,
                    "updated_stored": bool(updated_stored_icaos),
                })
            else:
                return jsonify({
                    "status": "error",
                    "icao": clean_icao,
                    "message": f"No fuel or FBO pricing data found on AirNav for {clean_icao}",
                }), 404
    except Exception as e:
        return jsonify({
            "status": "error",
            "icao": clean_icao,
            "message": f"Failed to fetch AirNav data: {str(e)}",
        }), 502


@aerofuel_bp.route("/api/airnav/sync", methods=["POST"])
def api_airnav_sync():
    """Batch fetch and persist latest AirNav fuel prices for a list of ICAOs."""
    req_data = request.get_json(silent=True) or {}
    icaos = req_data.get("icaos", [])
    if not isinstance(icaos, list) or not icaos:
        return jsonify({
            "status": "error",
            "message": "Payload must include non-empty 'icaos' array (e.g. {\"icaos\": [\"KSQL\", \"KPAO\"]})",
        }), 400

    force_refresh = bool(req_data.get("force_refresh", False))
    delay = float(req_data.get("delay", 0.5))

    results = airnav.batch_get_fuel(icaos, delay=delay, force_refresh=force_refresh)
    persist = bool(req_data.get("persist", True))
    updated_icaos = []
    if persist:
        updated_icaos = update_stored_fuel_data(results, directory=DATA_DIR)

    return jsonify({
        "status": "ok",
        "synced_count": len(results),
        "updated_icaos": updated_icaos,
        "data": results,
    })


@aerofuel_bp.route("/api/fuel-prices", methods=["GET"])
def api_fuel_prices_catalog():
    """Legacy endpoint returning full Master Public Airport catalog."""
    catalog = load_catalog(DATA_DIR, force_reload=False)
    if catalog is not None:
        return jsonify(catalog)
    return jsonify({"status": "error", "message": "Airport catalog could not be assembled"}), 500
