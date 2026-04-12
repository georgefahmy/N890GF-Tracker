import re

import airportsdata
import requests
from bs4 import BeautifulSoup

# from pprint import pprint


BASE_URL = "https://www.airnav.com/cgi-bin/"
session = requests.Session()


headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
}


def _extract_lat_lon(text: str):
    """
    Extract decimal lat/lon from AirNav page text.
    Returns (lat, lon) or (None, None)
    """
    # Common AirNav format examples:
    # "Latitude 37-04-12.345N / Longitude 121-35-12.345W"
    # or "37-04.12N 121-35.12W"

    match = re.search(
        r"(\d{1,3}-\d{2}-\d{2}(?:\.\d+)?[NS]).*?(\d{1,3}-\d{2}-\d{2}(?:\.\d+)?[EW])",
        text,
        re.DOTALL,
    )

    if not match:
        return None, None

    def dms_to_dd(dms):
        dms = dms.strip()
        direction = dms[-1]
        dms = dms[:-1]
        parts = dms.split("-")
        if len(parts) != 3:
            return None

        deg = float(parts[0])
        minutes = float(parts[1])
        seconds = float(parts[2])

        dd = deg + minutes / 60 + seconds / 3600

        if direction in ["S", "W"]:
            dd *= -1

        return dd

    lat = dms_to_dd(match.group(1))
    lon = dms_to_dd(match.group(2))

    return lat, lon


def resolve_airport_coords(url: str):
    """
    Resolve airport lat/lon using airportsdata first (ICAO + LID),
    fallback to AirNav scraping if needed.
    """
    try:
        code = url.rstrip("/").split("/")[-1].upper()

        # Load DBs ONCE per call (can be optimized later with caching)
        icao_db = airportsdata.load("ICAO")
        lid_db = airportsdata.load("LID")

        data = icao_db.get(code)

        # fallback to LID if not found in ICAO
        if not data:
            data = lid_db.get(code)

        # airportsdata returns dicts, not objects
        if data and isinstance(data, dict):
            lat = data.get("lat")
            lon = data.get("lon")

            if lat is not None and lon is not None:
                return float(lat), float(lon)

        # --- FALLBACK: scrape AirNav ---
        print(f"Falling back to AirNav for {code}")

        resp = session.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")

        text = soup.get_text(" ", strip=True)
        lat, lon = _extract_lat_lon(text)

        return lat, lon

    except Exception as e:
        print(f"coord resolution failed for {url}: {e}")
        return None, None


def fetch_route(
    origin: str,
    destination: str,
    range_value: str,
    selected_route: int = 0,
):
    plan_url = BASE_URL + "fuelplan"
    origin = origin.upper()
    destination = destination.upper()
    payload = {
        "origin": origin,  # Replace 'origin' with the actual input name
        "destination": destination,  # Replace 'destination' with the actual input name
        "aptsel": "a-u-0----1-A",
        "method": "cheap",
        "range": range_value,
        "rangeunits": "nm",
        "speed": "160",
        "speedunits": "kt",
        "fuelburn": "10",
        "cheapstrategy": "safe",
        "nroutes": "10",
    }

    response = session.post(plan_url, data=payload, headers=headers)
    soup = BeautifulSoup(response.text, "html.parser")
    try:
        pre_text = soup.find("pre").decode_contents()
    except:
        pre_text = "NO ROUTES FOUND"
        return {
            "routes": [],
            "route_data": [],
            "route_string": pre_text,
        }
    pattern = re.compile(
        r'<a href="([^"]+)">([^<]+)</a>\s+(\d+(?:\s+\[[+-]?\d+%\])?)\s+(.*?)\s+([ -][\d.]+)'
    )
    parsed_routes = []

    # 3. Process line by line
    for line in pre_text.split("\n"):
        # Skip empty lines, headers, or the divider line
        if not line.strip() or "ROUTE" in line or "---" in line:
            continue

        match = pattern.search(line)
        if match:
            route_data = {
                "url": BASE_URL + match.group(1),
                "route": match.group(2),
                "distance": match.group(3).strip(),
                "longest_leg": match.group(4).strip(),
                "savings": float(match.group(5)),
            }
            parsed_routes.append(route_data)
    # pprint(parsed_routes)
    # selected_route = input("Which route? ")
    route_data = BeautifulSoup(
        requests.get(parsed_routes[int(selected_route)]["url"]).text, "html.parser"
    )

    rows = route_data.center.table.find_all("tr")[1:]

    route_data = []

    # Process rows in pairs (step=2)
    for i in range(0, len(rows), 2):
        airport_tds = rows[i].find_all("td")

        # Safety check
        if not airport_tds or len(airport_tds) < 2:
            continue

        # --- NEW: Extract the URL from the <a> tag ---
        a_tag = airport_tds[0].find("a")
        # If the tag exists, grab the href and prepend the domain
        airport_url = (
            f"https://www.airnav.com{a_tag['href']}"
            if a_tag and a_tag.has_attr("href")
            else None
        )

        # 1. Extract Airport Code and Price
        # Using separator='|' turns "LWL<br>$6.2" into "LWL|$6.2"
        code_price_raw = airport_tds[0].get_text(separator="|", strip=True).split("|")
        airport_code = code_price_raw[0] if len(code_price_raw) > 0 else None
        price = code_price_raw[1] if len(code_price_raw) > 1 else None

        # 2. Extract Location and Name
        loc_name_raw = airport_tds[1].get_text(separator="|", strip=True).split("|")
        location = loc_name_raw[0] if len(loc_name_raw) > 0 else None
        airport_name = loc_name_raw[1] if len(loc_name_raw) > 1 else None

        # 3. Extract Leg Data (Distance & Heading) from the subsequent row
        distance = None
        heading = None

        # Check if the next row exists (avoids index errors on the last row)
        if i + 1 < len(rows):
            leg_tds = rows[i + 1].find_all("td")
            # If length is 2, it contains distance/heading.
            # If length is 1, it's the final empty <td colspan="2">
            if len(leg_tds) == 2:
                distance = leg_tds[0].get_text(strip=True)
                # Replaces the <br> between "true" and "magnetic" with a space
                heading = leg_tds[1].get_text(separator=" ", strip=True)

        lat = None
        lon = None

        if airport_url:
            lat, lon = resolve_airport_coords(airport_url)

        # Append to our list
        route_data.append(
            {
                "airport_code": airport_code,
                "airport_url": airport_url,
                "price": price,
                "location": location,
                "airport_name": airport_name,
                "distance_to_next": distance,
                "heading_to_next": heading,
                "lat": lat,
                "lon": lon,
            }
        )

    # Print the parsed dictionary cleanly
    route_string = " ".join(f"{val['airport_code']}" for val in route_data)

    return {
        "routes": parsed_routes,
        "route_data": route_data,
        "route_string": route_string,
    }


if __name__ == "__main__":
    origin = input("Origin Airport: ")
    destination = input("Destination (US) Airport: ")
    result = fetch_route(origin, destination, "400", 0)
    print(result["route_string"])
