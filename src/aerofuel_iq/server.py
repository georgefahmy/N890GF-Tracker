#!/usr/bin/env python3
"""
server.py
Lightweight HTTP server and AirNav API Proxy for AeroFuel IQ.
Serves static files (HTML, CSS, JS, JSON) and provides live mock / refresh API endpoints:
- GET /api/health
- GET /api/airnav/health
- GET /api/airnav?icao=KSQL
- POST /api/airnav/sync
- GET /api/fuel-prices
"""

import http.server
import json
import os
import socketserver
import sys
import time
import urllib.parse

from airnav_client import AirNavClient

PORT = 8080
DIRECTORY = os.path.dirname(os.path.abspath(__file__))

# Global AirNav client instance
airnav = AirNavClient(
    cache_dir=os.path.join(DIRECTORY, ".airnav_cache"),
    cache_ttl=3600,
    request_delay=1.0,
)

# In-memory master catalog cache
_catalog_cache = None
_cached_directory = None


def load_catalog(directory=DIRECTORY, force_reload=False):
    """
    Load or retrieve cached master catalog (fuel_data.json).
    """
    global _catalog_cache, _cached_directory
    if (
        _catalog_cache is not None
        and _cached_directory == directory
        and not force_reload
    ):
        return _catalog_cache

    fuel_file = os.path.join(directory, "fuel_data.json")
    if os.path.exists(fuel_file):
        try:
            with open(fuel_file, "r", encoding="utf-8") as f:
                _catalog_cache = json.load(f)
                _cached_directory = directory
                return _catalog_cache
        except Exception as e:
            print(
                f"Warning: Error loading catalog from {fuel_file}: {e}", file=sys.stderr
            )
    return None


def update_stored_fuel_data(airport_data, directory=DIRECTORY):
    """
    Updates the master dataset in-memory and persists back to fuel_data.json
    and fuel_data.js on disk.
    airport_data can be a single airport dict, a list of airport dicts,
    or a dict mapping icao -> airport dict.
    Returns list of updated ICAO codes.
    """
    global _catalog_cache, _cached_directory
    fuel_file = os.path.join(directory, "fuel_data.json")
    js_file = os.path.join(directory, "fuel_data.js")

    if not os.path.exists(fuel_file):
        return []

    try:
        catalog = load_catalog(directory=directory, force_reload=False)
        if catalog is None:
            with open(fuel_file, "r", encoding="utf-8") as f:
                catalog = json.load(f)
                _catalog_cache = catalog
                _cached_directory = directory

        airports = catalog.get("airports", catalog if isinstance(catalog, list) else [])
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
                if (
                    "fuels_available" in scraped
                    and scraped["fuels_available"] is not None
                ):
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
                    if "100LL" in target_apt["fuels_available"]:
                        target_apt["primary_fuel"] = "100LL"
                    else:
                        target_apt["primary_fuel"] = target_apt["fuels_available"][0]
                elif not target_apt.get("best_price"):
                    target_apt["primary_fuel"] = "None"

                if "last_updated" in scraped and scraped["last_updated"]:
                    target_apt["last_updated"] = scraped["last_updated"]
                if "fetched_at" in scraped and scraped["fetched_at"]:
                    target_apt["fetched_at"] = scraped["fetched_at"]
                else:
                    target_apt["fetched_at"] = time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                    )
                if "source" in scraped and scraped["source"]:
                    target_apt["source"] = scraped["source"]
                if scraped.get("ctaf_freq"):
                    target_apt["ctaf_freq"] = scraped["ctaf_freq"]
                if scraped.get("unicom_freq"):
                    target_apt["unicom_freq"] = scraped["unicom_freq"]

                # Enrich scraped dict with survey coordinates & frequencies from catalog
                for k in (
                    "lat",
                    "lon",
                    "elevation_ft",
                    "ctaf_freq",
                    "unicom_freq",
                    "runways",
                    "tower",
                    "faa",
                    "iata",
                    "country",
                ):
                    if k in target_apt and (
                        k not in scraped or scraped[k] is None or scraped[k] == 0.0
                    ):
                        scraped[k] = target_apt[k]

                recorded_ident = target_apt.get("icao") or icao_code
                if recorded_ident and recorded_ident not in updated_icaos:
                    updated_icaos.append(recorded_ident)
            else:
                # Add new airport entry if not in catalog
                primary_fuel = scraped.get("primary_fuel")
                best_price = scraped.get("best_price")
                if not primary_fuel:
                    primary_fuel = "100LL" if best_price else "None"

                new_entry = {
                    "icao": icao_code or faa_code,
                    "faa": faa_code or icao_code,
                    "iata": iata_code,
                    "name": scraped.get("name", f"{icao_code or faa_code} Airport"),
                    "city": scraped.get("city", ""),
                    "state": scraped.get("state", ""),
                    "country": scraped.get("country", "US"),
                    "lat": scraped.get("lat", 0.0),
                    "lon": scraped.get("lon", 0.0),
                    "elevation_ft": scraped.get("elevation_ft", 0),
                    "ctaf_freq": scraped.get("ctaf_freq", 122.8),
                    "unicom_freq": scraped.get("unicom_freq", 122.8),
                    "runways": scraped.get("runways", []),
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
                if new_ident not in updated_icaos:
                    updated_icaos.append(new_ident)

        if updated_icaos:
            if isinstance(catalog, dict):
                catalog["airports"] = airports
                catalog["total_airports"] = len(airports)
                catalog["updated_at"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                )
            _catalog_cache = catalog
            _cached_directory = directory

            # Atomic write to prevent partial file reads
            temp_json = fuel_file + ".tmp"
            temp_js = js_file + ".tmp"

            with open(temp_json, "w", encoding="utf-8") as f:
                json.dump(catalog, f, indent=2)
            os.replace(temp_json, fuel_file)

            with open(temp_js, "w", encoding="utf-8") as f:
                f.write("// AeroFuel IQ Static Airport Database\n")
                f.write("window.EMBEDDED_AIRPORTS = ")
                json.dump(catalog, f, indent=2)
                f.write(";\n")
            os.replace(temp_js, js_file)

        return updated_icaos
    except Exception as err:
        print(f"Warning: Failed to update stored fuel data: {err}", file=sys.stderr)
        return []


class AeroFuelHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def end_headers(self):
        # Enable CORS and caching headers
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, X-Parsebot-Api-Key, X-API-Key",
        )
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def send_json(self, status_code, payload):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(payload, indent=2).encode("utf-8"))

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 1. Health check
        if path == "/api/health":
            self.send_json(
                200,
                {
                    "status": "ok",
                    "service": "AeroFuel IQ Radar Server",
                    "version": "2.4",
                },
            )
            return

        # 2. AirNav Proxy Health check
        if path == "/api/airnav/health":
            self.send_json(
                200,
                {
                    "status": "ok",
                    "service": "AeroFuel AirNav Live Proxy",
                    "airnav_source": "https://www.airnav.com",
                    "parsebot_marketplace_url": "https://parse.bot/marketplace/208de514-ca12-4c51-923b-18380d9c6978/airnav-com-api",
                    "parsebot_configured": bool(
                        airnav.parsebot_api_key or os.environ.get("PARSEBOT_API_KEY")
                    ),
                    "cache_ttl_seconds": airnav.cache_ttl,
                    "request_delay_seconds": airnav.request_delay,
                },
            )
            return

        # 3. AirNav Airport Fuel Lookup: /api/airnav?icao=KSQL or /api/airnav/KSQL
        if path == "/api/airnav" or path.startswith("/api/airnav/"):
            icao = None
            if path.startswith("/api/airnav/") and len(path) > len("/api/airnav/"):
                icao = path[len("/api/airnav/") :].split("/")[0].strip()
            elif "icao" in query:
                icao = query["icao"][0].strip()
            elif "ident" in query:
                icao = query["ident"][0].strip()

            if not icao:
                self.send_json(
                    400,
                    {
                        "status": "error",
                        "message": "Missing 'icao' or 'ident' parameter (e.g. /api/airnav?icao=KSQL)",
                    },
                )
                return

            force_refresh = query.get("refresh", ["false"])[0].lower() in (
                "1",
                "true",
                "yes",
            )
            auth_header = self.headers.get("Authorization", "")
            bearer_token = (
                auth_header[7:].strip() if auth_header.startswith("Bearer ") else None
            )
            parsebot_api_key = (
                self.headers.get("X-Parsebot-Api-Key")
                or self.headers.get("X-API-Key")
                or bearer_token
                or query.get("parsebot_api_key", [None])[0]
                or query.get("api_key", [None])[0]
            )

            try:
                clean_icao = icao.strip().upper()
                local_res = None
                try:
                    local_res = airnav.fetch_local_fuel_prices(
                        clean_icao,
                        force_refresh=force_refresh,
                        use_cache=True,
                        parsebot_api_key=parsebot_api_key,
                    )
                except Exception as local_err:
                    print(
                        f"Notice: local fuel prices fetch failed for {clean_icao} ({local_err}); attempting direct single airport query.",
                        file=sys.stderr,
                    )
                    local_res = None

                if local_res and local_res.get("airports"):
                    airports_list = local_res.get("airports", [])
                    target_data = local_res.get("target") or (
                        airports_list[0] if airports_list else None
                    )
                    is_fallback = bool(local_res.get("fallback", False))
                    radius_val = (
                        local_res.get("radius_miles")
                        if local_res.get("radius_miles") is not None
                        else (0 if is_fallback else 45)
                    )

                    # Update stored data on disk and in-memory for all returned airports
                    updated_stored_icaos = update_stored_fuel_data(
                        airports_list, directory=DIRECTORY
                    )
                    self.send_json(
                        200,
                        {
                            "status": "ok",
                            "success": True,
                            "icao": clean_icao,
                            "source_airport": clean_icao,
                            "radius_miles": radius_val,
                            "count": len(airports_list),
                            "data": target_data,
                            "target": target_data,
                            "airports": airports_list,
                            "fallback": is_fallback,
                            "updated_stored": bool(updated_stored_icaos),
                        },
                    )
                else:
                    # Fallback to direct single airport query
                    data = airnav.fetch_airport_fuel(
                        clean_icao,
                        force_refresh=force_refresh,
                        parsebot_api_key=parsebot_api_key,
                    )
                    if data:
                        updated_stored_icaos = update_stored_fuel_data(
                            data, directory=DIRECTORY
                        )
                        self.send_json(
                            200,
                            {
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
                            },
                        )
                    else:
                        self.send_json(
                            404,
                            {
                                "status": "error",
                                "icao": clean_icao,
                                "message": f"No fuel or FBO pricing data found on AirNav for {clean_icao}",
                            },
                        )
            except Exception as e:
                # Attempt direct single airport query if not already tried
                try:
                    clean_icao = icao.strip().upper()
                    data = airnav.fetch_airport_fuel(
                        clean_icao,
                        force_refresh=force_refresh,
                        parsebot_api_key=parsebot_api_key,
                    )
                    if data:
                        updated_stored_icaos = update_stored_fuel_data(
                            data, directory=DIRECTORY
                        )
                        self.send_json(
                            200,
                            {
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
                            },
                        )
                        return
                except Exception:
                    pass

                self.send_json(
                    502,
                    {
                        "status": "error",
                        "icao": icao.strip().upper(),
                        "message": f"Failed to fetch AirNav data: {str(e)}",
                    },
                )
            return

        # 4. Static Fuel Dataset endpoint
        if path.startswith("/api/fuel-prices"):
            catalog = load_catalog(DIRECTORY, force_reload=False)
            if catalog is not None:
                self.send_json(200, catalog)
            else:
                fuel_file = os.path.join(DIRECTORY, "fuel_data.json")
                if os.path.exists(fuel_file):
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    with open(fuel_file, "rb") as f:
                        self.wfile.write(f.read())
                else:
                    self.send_json(
                        404, {"status": "error", "message": "fuel_data.json not found"}
                    )
            return

        # Fallback to SimpleHTTPRequestHandler for static web files
        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/airnav/sync":
            try:
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len) if content_len > 0 else b"{}"
                req_data = json.loads(body.decode("utf-8") or "{}")
            except Exception as e:
                self.send_json(
                    400, {"status": "error", "message": f"Invalid JSON payload: {e}"}
                )
                return

            icaos = req_data.get("icaos", [])
            if not isinstance(icaos, list) or not icaos:
                self.send_json(
                    400,
                    {
                        "status": "error",
                        "message": 'Payload must include non-empty \'icaos\' array (e.g. {"icaos": ["KSQL", "KPAO"]})',
                    },
                )
                return

            force_refresh = bool(req_data.get("force_refresh", False))
            delay = float(req_data.get("delay", 0.5))
            auth_header = self.headers.get("Authorization", "")
            bearer_token = (
                auth_header[7:].strip() if auth_header.startswith("Bearer ") else None
            )
            parsebot_api_key = (
                self.headers.get("X-Parsebot-Api-Key")
                or self.headers.get("X-API-Key")
                or bearer_token
                or req_data.get("parsebot_api_key")
                or req_data.get("api_key")
            )

            # Batch fetch from AirNav / Parse.bot
            results = airnav.batch_get_fuel(
                icaos,
                delay=delay,
                force_refresh=force_refresh,
                parsebot_api_key=parsebot_api_key,
            )

            # Merge with fuel_data.json if requested or by default
            persist = bool(req_data.get("persist", True))
            updated_icaos = []

            if persist:
                updated_icaos = update_stored_fuel_data(results, directory=DIRECTORY)

            self.send_json(
                200,
                {
                    "status": "ok",
                    "synced_count": len(results),
                    "updated_icaos": updated_icaos,
                    "data": results,
                },
            )
            return

        self.send_json(
            404, {"status": "error", "message": f"Endpoint not found: {path}"}
        )


def run_server(port=PORT):
    handler = AeroFuelHTTPRequestHandler
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(
            f"🚀 AeroFuel IQ Radar & AirNav Proxy running at http://localhost:{port}/"
        )
        print(f"📁 Serving static files from: {DIRECTORY}")
        print(
            "📡 AirNav endpoints: /api/airnav?icao=<ICAO>, /api/airnav/sync, /api/airnav/health"
        )
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    run_server(port)
