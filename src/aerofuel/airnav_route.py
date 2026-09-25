import json
import os
import re
import urllib.parse
import urllib.request
from bs4 import BeautifulSoup

try:
    import airportsdata
except ImportError:
    airportsdata = None

try:
    from .airnav_client import (
        DEFAULT_USER_AGENT,
        _urlopen_with_ssl_fallback,
        clean_text,
        parse_price_val,
    )
except ImportError:
    from airnav_client import (
        DEFAULT_USER_AGENT,
        _urlopen_with_ssl_fallback,
        clean_text,
        parse_price_val,
    )

BASE_URL = "https://www.airnav.com/cgi-bin/"
HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Cache for loaded airportsdata databases
_ICAO_DB = None
_LID_DB = None
_LOCAL_AIRPORTS_CACHE = None


def _load_local_airports():
    """Load airports from in-memory catalog / airports.csv for fast coordinate resolution."""
    global _LOCAL_AIRPORTS_CACHE
    if _LOCAL_AIRPORTS_CACHE is not None:
        return _LOCAL_AIRPORTS_CACHE

    _LOCAL_AIRPORTS_CACHE = {}
    try:
        try:
            from .core import load_catalog
        except ImportError:
            try:
                from core import load_catalog
            except ImportError:
                from server import load_catalog
        catalog = load_catalog()
        for apt in catalog.get("airports", []):
            icao = (apt.get("icao") or "").upper().strip()
            faa = (apt.get("faa") or "").upper().strip()
            lat = apt.get("lat")
            lon = apt.get("lon")
            if lat is not None and lon is not None:
                coords = (float(lat), float(lon), apt.get("name") or "", apt.get("city") or "", apt.get("state") or "")
                if icao:
                    _LOCAL_AIRPORTS_CACHE[icao] = coords
                if faa and faa != icao:
                    _LOCAL_AIRPORTS_CACHE[faa] = coords
    except Exception:
        pass

    return _LOCAL_AIRPORTS_CACHE


def _extract_lat_lon(text: str):
    """
    Extract decimal lat/lon from AirNav page text.
    Returns (lat, lon) or (None, None)
    """
    match = re.search(
        r"(\d{1,3}-\d{2}-\d{2}(?:\.\d+)?[NS]).*?(\d{1,3}-\d{2}-\d{2}(?:\.\d+)?[EW])",
        text,
        re.DOTALL,
    )
    if not match:
        # Try alternate format: 37-04.895N 121-35.808W
        match2 = re.search(
            r"(\d{1,3}-\d{2}(?:\.\d+)?[NS]).*?(\d{1,3}-\d{2}(?:\.\d+)?[EW])",
            text,
            re.DOTALL,
        )
        if not match2:
            return None, None

        def dm_to_dd(dm):
            dm = dm.strip()
            direction = dm[-1]
            parts = dm[:-1].split("-")
            if len(parts) != 2:
                return None
            dd = float(parts[0]) + float(parts[1]) / 60
            if direction in ["S", "W"]:
                dd *= -1
            return dd

        return dm_to_dd(match2.group(1)), dm_to_dd(match2.group(2))

    def dms_to_dd(dms):
        dms = dms.strip()
        direction = dms[-1]
        parts = dms[:-1].split("-")
        if len(parts) != 3:
            return None
        dd = float(parts[0]) + float(parts[1]) / 60 + float(parts[2]) / 3600
        if direction in ["S", "W"]:
            dd *= -1
        return dd

    lat = dms_to_dd(match.group(1))
    lon = dms_to_dd(match.group(2))
    return lat, lon


def resolve_airport_coords(code_or_url: str):
    """
    Resolve airport lat/lon using local DB first, then airportsdata (ICAO + LID),
    and finally fallback to AirNav scraping if needed.
    """
    global _ICAO_DB, _LID_DB
    if not code_or_url:
        return None, None

    code = code_or_url.rstrip("/").split("/")[-1].upper().strip()
    # 1. Check local airports cache
    local_db = _load_local_airports()
    if code in local_db:
        return local_db[code][0], local_db[code][1]
    if len(code) == 4 and code.startswith("K") and code[1:] in local_db:
        return local_db[code[1:]][0], local_db[code[1:]][1]
    if len(code) == 3 and ("K" + code) in local_db:
        return local_db["K" + code][0], local_db["K" + code][1]

    # 2. Check airportsdata library if available
    if airportsdata:
        try:
            if _ICAO_DB is None:
                _ICAO_DB = airportsdata.load("ICAO")
            if _LID_DB is None:
                _LID_DB = airportsdata.load("LID")

            data = _ICAO_DB.get(code) or _LID_DB.get(code)
            if not data and len(code) == 3:
                data = _ICAO_DB.get("K" + code)
            elif not data and len(code) == 4 and code.startswith("K"):
                data = _LID_DB.get(code[1:])

            if data and isinstance(data, dict):
                lat = data.get("lat")
                lon = data.get("lon")
                if lat is not None and lon is not None:
                    return float(lat), float(lon)
        except Exception:
            pass

    # 3. Fallback: scrape AirNav airport page
    url = code_or_url if code_or_url.startswith("http") else f"https://www.airnav.com/airport/{code}"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with _urlopen_with_ssl_fallback(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            soup = BeautifulSoup(html, "html.parser")
            text = soup.get_text(" ", strip=True)
            lat, lon = _extract_lat_lon(text)
            return lat, lon
    except Exception:
        return None, None


def fetch_route(
    origin: str,
    destination: str,
    range_value: str = "400",
    selected_route: int = 0,
):
    """
    Compute an optimized multi-stop fuel route between origin and destination
    using AirNav's Fuel Plan calculator.
    """
    origin = (origin or "").upper().strip()
    destination = (destination or "").upper().strip()

    if not origin or not destination:
        return {
            "success": False,
            "error": "Origin and destination airport codes are required.",
            "routes": [],
            "stops": [],
            "route_string": "",
        }

    plan_url = BASE_URL + "fuelplan"
    payload = {
        "origin": origin,
        "destination": destination,
        "aptsel": "a-u-0----1-A",
        "method": "cheap",
        "range": str(range_value),
        "rangeunits": "nm",
        "speed": "160",
        "speedunits": "kt",
        "fuelburn": "10",
        "cheapstrategy": "safe",
        "nroutes": "10",
    }

    try:
        encoded_data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            plan_url,
            data=encoded_data,
            headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with _urlopen_with_ssl_fallback(req, timeout=15) as resp:
            html_content = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to connect to AirNav fuel planner: {e}",
            "routes": [],
            "stops": [],
            "route_string": "",
        }

    soup = BeautifulSoup(html_content, "html.parser")
    pre_tag = soup.find("pre")
    if not pre_tag:
        # Check if error message exists
        err_match = soup.find(text=re.compile(r"error|invalid|unknown", re.IGNORECASE))
        err_msg = clean_text(str(err_match)) if err_match else "No routes found for specified airports."
        return {
            "success": False,
            "error": err_msg,
            "routes": [],
            "stops": [],
            "route_string": "",
        }

    pre_text = pre_tag.decode_contents()
    pattern = re.compile(
        r'<a href="([^"]+)">([^<]+)</a>\s+(\d+(?:\s*(?:nm|mi))?(?:\s+\[[+-]?\d+%\])?)\s+(.+?)\s+\$?([ -]?\d+(?:\.\d+)?)'
    )
    parsed_routes = []

    for line in pre_text.split("\n"):
        if not line.strip() or "ROUTE" in line or "---" in line:
            continue

        match = pattern.search(line)
        if match:
            url_part = match.group(1)
            full_url = url_part if url_part.startswith("http") else (BASE_URL + url_part)
            savings_val = 0.0
            try:
                savings_val = float(match.group(5).strip())
            except Exception:
                pass

            dist_raw = clean_text(match.group(3))
            pct_match = re.search(r'(\d+)\s*(\[[+-]?\d+%\])', dist_raw)
            if pct_match:
                dist_formatted = f"{pct_match.group(1)} nm {pct_match.group(2)}"
            elif dist_raw and "nm" not in dist_raw.lower() and "mi" not in dist_raw.lower():
                dist_formatted = f"{dist_raw} nm"
            else:
                dist_formatted = dist_raw

            longest_leg_str = match.group(4).strip()
            if longest_leg_str and "nm" not in longest_leg_str.lower() and "mi" not in longest_leg_str.lower() and longest_leg_str.isdigit():
                longest_leg_formatted = f"{longest_leg_str} nm"
            else:
                longest_leg_formatted = longest_leg_str

            route_data = {
                "idx": len(parsed_routes),
                "url": full_url,
                "route": match.group(2).strip(),
                "distance": dist_formatted,
                "longest_leg": longest_leg_formatted,
                "savings": savings_val,
            }
            parsed_routes.append(route_data)

    if not parsed_routes:
        # Check if direct flight was suggested
        return {
            "success": False,
            "error": "No optimized fuel routes found between specified airports.",
            "routes": [],
            "stops": [],
            "route_string": "",
        }

    selected_idx = max(0, min(int(selected_route), len(parsed_routes) - 1))
    target_route = parsed_routes[selected_idx]

    try:
        req_route = urllib.request.Request(target_route["url"], headers=HEADERS)
        with _urlopen_with_ssl_fallback(req_route, timeout=15) as resp:
            route_detail_html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to fetch route details: {e}",
            "routes": parsed_routes,
            "stops": [],
            "route_string": target_route["route"],
        }

    route_soup = BeautifulSoup(route_detail_html, "html.parser")
    rows = []
    if route_soup.center and route_soup.center.table:
        rows = route_soup.center.table.find_all("tr")[1:]
    else:
        table = route_soup.find("table")
        if table:
            rows = table.find_all("tr")[1:]

    stops = []
    for i in range(0, len(rows), 2):
        airport_tds = rows[i].find_all("td")
        if not airport_tds or len(airport_tds) < 2:
            continue

        a_tag = airport_tds[0].find("a")
        airport_url = (
            f"https://www.airnav.com{a_tag['href']}"
            if (a_tag and a_tag.has_attr("href"))
            else None
        )

        # 1. Airport Code and Price
        code_price_raw = airport_tds[0].get_text(separator="|", strip=True).split("|")
        airport_code = clean_text(code_price_raw[0]) if len(code_price_raw) > 0 else ""
        price_str = clean_text(code_price_raw[1]) if len(code_price_raw) > 1 else ""
        price_num = parse_price_val(price_str)

        # 2. Location and Name
        loc_name_raw = airport_tds[1].get_text(separator="|", strip=True).split("|")
        location = clean_text(loc_name_raw[0]) if len(loc_name_raw) > 0 else ""
        airport_name = clean_text(loc_name_raw[1]) if len(loc_name_raw) > 1 else ""

        # 3. Leg Data (Distance & Heading) from subsequent row
        distance = None
        heading = None

        if i + 1 < len(rows):
            leg_tds = rows[i + 1].find_all("td")
            if len(leg_tds) >= 2:
                distance = clean_text(leg_tds[0].get_text(strip=True))
                heading = clean_text(leg_tds[1].get_text(separator=" ", strip=True))

        lat, lon = resolve_airport_coords(airport_url or airport_code)

        stops.append(
            {
                "stop_index": len(stops),
                "airport_code": airport_code,
                "airport_url": airport_url,
                "price": price_str,
                "price_num": price_num,
                "location": location,
                "airport_name": airport_name,
                "distance_to_next": distance,
                "heading_to_next": heading,
                "lat": lat,
                "lon": lon,
            }
        )

    route_string = " ".join(f"{val['airport_code']}" for val in stops) if stops else target_route["route"]

    return {
        "success": len(stops) > 0,
        "origin": origin,
        "destination": destination,
        "range_nm": int(range_value) if str(range_value).isdigit() else range_value,
        "selected_route_idx": selected_idx,
        "route_string": route_string,
        "total_distance": target_route["distance"],
        "longest_leg": target_route["longest_leg"],
        "savings": target_route["savings"],
        "routes": parsed_routes,
        "stops": stops,
    }


if __name__ == "__main__":
    result = fetch_route("KSQL", "KDEN", "400", 0)
    print(json.dumps(result, indent=2))

