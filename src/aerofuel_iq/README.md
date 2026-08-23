# ✈️ AeroFuel IQ — Airport Fuel Price Radar

**AeroFuel IQ** is an interactive, web-based aviation fuel lookup and radar scanning application designed for pilots, aircraft owners, and flight dispatchers. It allows pilots to scan any flight area across the country with a variable search radius circle (10 to 500+ miles/NM) that smoothly follows the cursor, dynamically displays bubble tags with avgas prices over all airports, and automatically highlights the lowest fuel price in the active radius with visual glow effects and radar vectors.

---

## 🌟 Key Features

1. **Interactive Scrollable & Pannable Map**
   - Built on Leaflet.js with multi-layer map styling: *Aero Midnight (Dark)*, *Aviation VFR (Light)*, *OpenStreetMap*, and *Satellite Imagery*.
   - Smooth mouse cursor tracking with `requestAnimationFrame` for stutter-free 60+ FPS performance.
   - **Position Lock / Pin Mode**: Click the map or press `Spacebar` to lock the radius circle over any destination or home base; click again to resume following the mouse.

2. **Variable Search Radius Radar**
   - Radius slider and direct numeric input from **10 to 500+ miles / Nautical Miles / Kilometers**.
   - One-click preset chips: **25**, **50**, **100**, **250**, **500**.
   - Toggle distance units between Statute Miles (`mi`), Nautical Miles (`NM`), and Kilometers (`km`).

3. **Airport Bubble Tags & Out-of-Circle Marker Visibility**
   - Every airport within the active search radius circle displays a custom badge tag showing the airport code (e.g. `KOSH`, `KSQL`, `KADS`) and current price (`$5.49`).
   - Airports outside the circle are shown as subtle, unobtrusive dot markers with no fuel prices displayed until swept into the radar circle.
   - Color-coded by price percentile: Green (economical), Blue/Slate (average), Orange (premium).

4. **Dynamic Lowest Fuel Price Highlighting**
   - As the radius circle is moved across the map, the airport with the **lowest non-jet fuel price** within the circle is prominently highlighted:
     - Glowing animated radar pulse ring on its map bubble marker.
     - `🏆 BEST: $X.XX` ribbon banner pinned to the badge.
     - Dashed geodesic vector connecting the circle center directly to the lowest-price airport with distance and bearing.
     - Elevated z-index to stay on top.

5. **Aviation Piston Fuel Filters**
   - Non-jet fuel selector:
     - ⛽ **All Avgas (Lowest Available Non-Jet Price)**
     - **100LL** (Low Lead Avgas)
     - **94UL / UL94** (Unleaded Avgas)
     - **100UL** (GAMI G100UL Unleaded)
     - **100R** (Swift Fuels Unleaded)
     - **Mogas** (Ethanol-Free Auto Fuel for Rotax / LSAs)
   - Service mode selector:
     - **Any Service**
     - **Self-Serve ($)**
     - **Full-Serve ($$)**

6. **Floating "Best Deal in Radius" HUD Banner**
   - Displays lowest price airport name, ICAO code, distance, magnetic bearing (e.g. `245° WSW`), FBO name, and dollar savings calculation (e.g. `Saves $1.42/gal • ~$71.00 on 50 gal fill-up`).
   - Quick action buttons: **🎯 Center Radar on Airport** and **📋 View Full Specs**.

7. **Collapsible Radar Inspector Sidebar**
   - Shows live summary stats: Airports in radius, Minimum price, and Average price.
   - Scrollable ranked list of all airports in radius sorted ascending by price (`#1 🏆`, `#2`, `#3`...).
   - Clicking any list card immediately flies the camera to the airport and opens full details.

8. **Airport Autocomplete Search**
   - Instant search by ICAO (`KOSH`), FAA ID (`OSH`), airport name (`Wittman`), city (`Oshkosh`), or state (`WI`).
   - Selecting a search result automatically flies to the airport and centers the search circle over it.

9. **Comprehensive Airport Detail Modal**
   - Elevation MSL, coordinates, Towered vs Non-Towered status, CTAF and UNICOM frequencies.
   - Runway lengths, headings, and surface types (Asphalt, Concrete, Turf, Water).
   - Complete FBO directory with phone numbers, full fuel price menu (100LL SS/FS, UL94, 100UL, 100R, Mogas, Jet-A), notes, and direct links to **AirNav**, **SkyVector Sectional Charts**, and **FlightAware**.

10. **Data Feeds, Sync, and Static Offline Mode**
    - **⚡ Sync Prices Button**: Reloads the static dataset `fuel_data.json` with live timestamp.
    - **Simulate Real-Time Spot Market**: Simulates live market price adjustments across regional FBO fuel islands.
    - **CSV / JSON Custom File Import**: Upload custom flight club or FBO price logs.
    - **Export**: Download filtered radius airports and fuel prices as CSV or JSON.

---

## 📁 File Structure

```
airport_fuel_lookup/
├── index.html            # Main web application entry point
├── app.js                # Core interactive logic, spatial calculations & radar rendering
├── style.css             # Aviation glassmorphic HUD styling & animations
├── airnav_client.py      # Robust AirNav scraper, parser, and caching client
├── fuel_data.json        # Comprehensive static dataset of 5,000+ US public-use airports with multi-fuel prices
├── fuel_data.js          # Browser-ready window.EMBEDDED_AIRPORTS static feed
├── airports.csv          # Authoritative OurAirports / FAA NASR dataset
├── fetch_fuel_data.py    # Python CLI data manager, AirNav live updater, and validator
├── generate_dataset.py   # Dataset compilation script
├── server.py             # Lightweight HTTP server & AirNav API Proxy (GET /api/airnav, POST /api/airnav/sync)
├── test_fuel_lookup.py   # Comprehensive automated unit and integration test suite
└── README.md             # Project documentation
```

---

## 🚀 Quick Start & Execution

### 1. Run the Local Web Server & AirNav API Proxy
```bash
python3 server.py 8080
```
Then navigate to `http://localhost:8080/` in your browser.

- **AirNav Health & Parse.bot Status**: `GET /api/airnav/health`
- **AirNav Real-Time Price**: `GET /api/airnav?icao=KSQL` (or with API key: `GET /api/airnav?icao=KSQL&parsebot_api_key=pb_live_...`)
- **AirNav Radius Batch Sync**: `POST /api/airnav/sync` (payload: `{"icaos": ["KSQL", "KPAO"], "parsebot_api_key": "pb_live_..."}`)

### 2. Parse.bot Managed Scraper Integration
AeroFuel IQ integrates with [Parse.bot AirNav API](https://parse.bot/marketplace/208de514-ca12-4c51-923b-18380d9c6978/airnav-com-api) for high-speed cloud ingestion of retail FBO rates (100LL SS/FS, UL94, 100UL, 100R, Mogas, SAF, Jet-A).
- Configure via `PARSEBOT_API_KEY` environment variable or directly in the **⚡ Sync Prices** UI modal.
- Automatic fallback to the built-in direct HTML scraper if no key is provided or if Parse.bot is unavailable.

### 3. Run Automated Test Suite
```bash
python3 test_fuel_lookup.py
```

### 4. Update Dataset / Ingest Live Prices from AirNav
```bash
# Ingest live AirNav prices for specific airports (optionally via Parse.bot):
python3 fetch_fuel_data.py --source airnav --airports KSQL,KPAO,KHAF,KCVH --parsebot-api-key pb_live_...

# Rebuild full 16,000+ airport baseline catalog:
python3 fetch_fuel_data.py --build
```

---

## 🧭 Keyboard & Mouse Shortcuts

- **Mouse Move**: Move the radar search circle across the map.
- **Click Map**: Lock / pin the search circle at the clicked location (or click again to unlock).
- **Spacebar**: Toggle lock/unlock position.
- **Scroll / Pinch**: Zoom in and out of the map.
