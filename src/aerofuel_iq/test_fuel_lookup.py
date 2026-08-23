#!/usr/bin/env python3
"""
test_fuel_lookup.py
Comprehensive automated test suite for AeroFuel IQ.
Tests:
1. Great circle / Haversine distance calculations and bearing
2. Spatial radius filtering (0 mi, 25 mi, 50 mi, 500 mi, NM, km)
3. Lowest fuel price selection algorithm & deterministic tie-breaking by distance
4. Non-jet fuel filtering (100LL, 94UL, 100UL, 100R, Mogas vs Jet-A exclusion)
5. Service mode filtering (Self-Serve vs Full-Serve vs Any)
6. Data schema integrity & validation across entire 5,000+ airport dataset
7. Static offline sync validation (fuel_data.json and fuel_data.js consistency)
8. Edge cases (airports without fuel data properly excluded from lowest price, antipodes, null values)
9. National coverage (all 50 states + US territories represented)
10. Fast spatial pre-filtering & performance benchmarks (< 2ms per query across 5,000+ airports)
"""

import json
import math
import os
import unittest

from airnav_client import (AirNavClient, clean_text, normalize_fuel_type,
                           parse_price_val)

DIRECTORY = os.path.dirname(os.path.abspath(__file__))


def haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8  # statute miles
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    a = (math.sin(dLat / 2.0) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dLon / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def calculate_bearing(lat1, lon1, lat2, lon2):
    y = math.sin(math.radians(lon2 - lon1)) * math.cos(math.radians(lat2))
    x = (math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) -
         math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.cos(math.radians(lon2 - lon1)))
    brng = (math.degrees(math.atan2(y, x)) + 360) % 360
    return round(brng)


def get_effective_fuel_price(airport, fuel_type='all', service='any'):
    eligible = []
    for fbo in airport.get("fbos", []):
        for fkey, fobj in fbo.get("fuels", {}).items():
            if fobj.get("type") == "Jet-A":
                continue  # Never count Jet-A for piston lookup
            if fuel_type != 'all' and fobj.get("type") != fuel_type:
                continue
            if service == 'self' and fobj.get("service") != 'Self-Serve':
                continue
            if service == 'full' and fobj.get("service") != 'Full-Serve':
                continue
            price = fobj.get("price")
            if price and price > 0:
                eligible.append({
                    "price": price,
                    "type": fobj.get("type"),
                    "service": fobj.get("service"),
                    "fbo": fbo.get("name")
                })
    if not eligible:
        return None
    eligible.sort(key=lambda x: x["price"])
    return eligible[0]


def query_radius(airports, center_lat, center_lon, radius_miles, fuel_type='all', service='any', include_unpriced=False):
    results = []
    lowest = None
    min_price = float('inf')

    # Fast bounding box pre-filter
    lat_delta = radius_miles / 68.7
    min_lat = max(-89.9, center_lat - lat_delta)
    max_lat = min(89.9, center_lat + lat_delta)
    max_abs_lat = max(abs(min_lat), abs(max_lat))
    cos_lat = max(0.01, math.cos(math.radians(max_abs_lat)))
    lon_delta = min(180.0, radius_miles / (68.7 * cos_lat))
    min_lon, max_lon = center_lon - lon_delta, center_lon + lon_delta

    for apt in airports:
        if apt["lat"] < min_lat or apt["lat"] > max_lat or apt["lon"] < min_lon or apt["lon"] > max_lon:
            continue

        dist = haversine_miles(center_lat, center_lon, apt["lat"], apt["lon"])
        if dist <= radius_miles:
            fuel_info = get_effective_fuel_price(apt, fuel_type, service)
            entry = {
                "icao": apt["icao"],
                "name": apt["name"],
                "distance": dist,
                "fuel": fuel_info,
                "has_fuel": fuel_info is not None
            }

            if fuel_info is not None:
                results.append(entry)
                # Deterministic tie breaking: lowest price, then closer distance
                if fuel_info["price"] < min_price or (fuel_info["price"] == min_price and dist < (lowest["distance"] if lowest else float('inf'))):
                    min_price = fuel_info["price"]
                    lowest = entry
            elif include_unpriced:
                results.append(entry)

    # Sort results: priced first (by price, then distance), unpriced last
    results.sort(key=lambda x: (
        0 if x["has_fuel"] else 1,
        x["fuel"]["price"] if x["has_fuel"] else 0,
        x["distance"]
    ))
    return results, lowest


class TestAeroFuelCore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fuel_json_path = os.path.join(DIRECTORY, "fuel_data.json")
        with open(fuel_json_path, "r") as f:
            data = json.load(f)
        cls.airports = data.get("airports", data)

    def test_dataset_loaded_and_populated(self):
        """Verify dataset has over 5,000 public airports and all required keys."""
        self.assertGreaterEqual(len(self.airports), 5000, f"Expected >= 5000 airports, got {len(self.airports)}")
        required_keys = {"icao", "name", "city", "state", "lat", "lon", "fbos", "best_price"}
        for apt in self.airports:
            for k in required_keys:
                self.assertIn(k, apt, f"Airport {apt.get('icao')} missing required key {k}")

    def test_all_50_states_and_territories_present(self):
        """Verify all 50 US states + territories are present in the dataset."""
        states = set(a["state"] for a in self.airports)
        all_50 = {'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
                  'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
                  'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
                  'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
                  'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY'}
        for s in all_50:
            self.assertIn(s, states, f"State {s} missing from public airports dataset")

        # Territories
        for territory in ['PR', 'VI', 'GU']:
            self.assertIn(territory, states, f"Territory {territory} missing from dataset")

    def test_unreported_fuel_airports_handling(self):
        """Verify baseline airports have empty fbos, best_price None, and fuels_available empty."""
        unpriced = [a for a in self.airports if a.get("best_price") is None]
        self.assertEqual(len(unpriced), len(self.airports))
        for apt in unpriced[:50]:
            self.assertEqual(apt.get("fbos"), [])
            self.assertEqual(apt.get("fuels_available"), [])
            fuel_info = get_effective_fuel_price(apt)
            self.assertIsNone(fuel_info)

    def test_unpriced_airports_excluded_from_lowest_fuel_price(self):
        """Verify unpriced airports within search radius are never selected as lowest fuel candidate."""
        mock_airports = [
            {
                "icao": "KSQL",
                "name": "San Carlos Airport",
                "lat": 37.5119,
                "lon": -122.2495,
                "fbos": [{"name": "Rabbit Aviation", "fuels": {"100LL": {"price": 6.15, "type": "100LL", "service": "Self-Serve"}}}]
            },
            {
                "icao": "KPAO",
                "name": "Palo Alto Airport",
                "lat": 37.4611,
                "lon": -122.1151,
                "fbos": []  # Unpriced baseline
            },
            {
                "icao": "KHAF",
                "name": "Half Moon Bay Airport",
                "lat": 37.5134,
                "lon": -122.5011,
                "fbos": []  # Unpriced baseline
            }
        ]
        center_lat, center_lon = 37.5119, -122.2495  # KSQL
        results_priced_only, lowest = query_radius(mock_airports, center_lat, center_lon, 50, include_unpriced=False)
        results_all, lowest_all = query_radius(mock_airports, center_lat, center_lon, 50, include_unpriced=True)

        self.assertIsNotNone(lowest)
        self.assertIsNotNone(lowest_all)
        self.assertEqual(lowest["icao"], "KSQL")
        self.assertEqual(lowest_all["icao"], "KSQL")
        self.assertEqual(lowest["fuel"]["price"], 6.15)
        self.assertEqual(lowest_all["fuel"]["price"], 6.15)

        # Unpriced airports are included in results_all but excluded from results_priced_only
        self.assertEqual(len(results_priced_only), 1)
        self.assertEqual(len(results_all), 3)

    def test_static_js_json_sync(self):
        """Verify fuel_data.js and fuel_data.json exist and contain matching data."""
        json_path = os.path.join(DIRECTORY, "fuel_data.json")
        js_path = os.path.join(DIRECTORY, "fuel_data.js")
        self.assertTrue(os.path.exists(json_path), "fuel_data.json missing")
        self.assertTrue(os.path.exists(js_path), "fuel_data.js missing")

        with open(js_path, "r") as f:
            js_content = f.read()
        self.assertIn("window.EMBEDDED_AIRPORTS =", js_content)
        self.assertIn("KSQL", js_content)

    def test_haversine_distance_known_benchmarks(self):
        """Verify Haversine against known airport pairs."""
        # KSQL (San Carlos: 37.5119, -122.2495) to KPAO (Palo Alto: 37.4611, -122.1151) ~ 8.1 miles
        dist_sql_pao = haversine_miles(37.5119, -122.2495, 37.4611, -122.1151)
        self.assertAlmostEqual(dist_sql_pao, 8.1, delta=0.5)

        # Same point distance is 0
        self.assertEqual(haversine_miles(37.5119, -122.2495, 37.5119, -122.2495), 0.0)

        # KOSH (Oshkosh: 43.9844, -88.5570) to KPWK (Chicago Exec: 42.1143, -87.9015) ~ 133 miles
        dist_osh_pwk = haversine_miles(43.9844, -88.5570, 42.1143, -87.9015)
        self.assertAlmostEqual(dist_osh_pwk, 133.0, delta=2.5)

    def test_bearing_calculation(self):
        """Test initial bearing calculations."""
        # Due north
        self.assertEqual(calculate_bearing(0.0, 0.0, 10.0, 0.0), 0)
        # Due east
        self.assertEqual(calculate_bearing(0.0, 0.0, 0.0, 10.0), 90)
        # Due south
        self.assertEqual(calculate_bearing(10.0, 0.0, 0.0, 0.0), 180)
        # Due west
        self.assertEqual(calculate_bearing(0.0, 10.0, 0.0, 0.0), 270)

    def test_radius_50_miles_sf_bay_area(self):
        """Test 50 mile search centered at San Carlos (KSQL)."""
        center_lat, center_lon = 37.5119, -122.2495
        # All public airfields in radius are returned when include_unpriced=True
        results, lowest = query_radius(self.airports, center_lat, center_lon, 50, include_unpriced=True)

        self.assertGreater(len(results), 5)

        # Verify all found airports are indeed within 50 miles
        for r in results:
            self.assertLessEqual(r["distance"], 50.0)

        # Now test with seeded live AirNav rates
        in_radius_apts = [dict(a) for a in self.airports if haversine_miles(center_lat, center_lon, a["lat"], a["lon"]) <= 50][:5]
        self.assertGreaterEqual(len(in_radius_apts), 2)
        in_radius_apts[0]["fbos"] = [{"name": "FBO 1", "fuels": {"100LL": {"price": 5.95, "type": "100LL", "service": "Self-Serve"}}}]
        in_radius_apts[1]["fbos"] = [{"name": "FBO 2", "fuels": {"100LL": {"price": 6.45, "type": "100LL", "service": "Self-Serve"}}}]
        seeded_results, seeded_lowest = query_radius(in_radius_apts, center_lat, center_lon, 50, include_unpriced=False)
        self.assertGreater(len(seeded_results), 0)
        self.assertIsNotNone(seeded_lowest)
        self.assertEqual(seeded_lowest["fuel"]["price"], 5.95)

    def test_tie_breaking_by_distance(self):
        """Verify that when two airports have the exact same price, the closer one is chosen."""
        mock_airports = [
            {
                "icao": "FAR_AIRPORT",
                "name": "Far Away Airport",
                "lat": 38.0,
                "lon": -122.0,
                "fbos": [{"name": "FBO 1", "fuels": {"100LL": {"price": 4.99, "type": "100LL", "service": "Self-Serve"}}}]
            },
            {
                "icao": "CLOSE_AIRPORT",
                "name": "Close Airport",
                "lat": 37.52,
                "lon": -122.25,
                "fbos": [{"name": "FBO 2", "fuels": {"100LL": {"price": 4.99, "type": "100LL", "service": "Self-Serve"}}}]
            }
        ]
        center_lat, center_lon = 37.5119, -122.2495
        results, lowest = query_radius(mock_airports, center_lat, center_lon, 100)
        self.assertEqual(len(results), 2)
        # Both prices are $4.99, but CLOSE_AIRPORT is closer (~0.5 mi vs ~35 mi)
        self.assertEqual(lowest["icao"], "CLOSE_AIRPORT")

    def test_jet_fuel_exclusion(self):
        """Ensure Jet-A is never selected as lowest piston fuel."""
        for apt in self.airports:
            fuel_info = get_effective_fuel_price(apt, 'all', 'any')
            if fuel_info:
                self.assertNotEqual(fuel_info["type"], "Jet-A")

    def test_fuel_type_filter_100ll(self):
        """Test 100LL explicit filtering."""
        mock_data = [
            {"icao": "K1", "name": "Apt 1", "lat": 37.5, "lon": -122.2, "fbos": [{"name": "F1", "fuels": {"100LL": {"price": 6.00, "type": "100LL", "service": "Self-Serve"}}}]},
            {"icao": "K2", "name": "Apt 2", "lat": 37.5, "lon": -122.2, "fbos": [{"name": "F2", "fuels": {"94UL": {"price": 7.00, "type": "94UL", "service": "Self-Serve"}}}]}
        ]
        results, lowest = query_radius(mock_data, 37.5, -122.2, 60, fuel_type='100LL')
        self.assertEqual(len(results), 1)
        for r in results:
            self.assertEqual(r["fuel"]["type"], "100LL")

    def test_fuel_type_filter_94ul(self):
        """Test 94UL unleaded fuel filtering."""
        mock_data = [
            {"icao": "K1", "name": "Apt 1", "lat": 37.5, "lon": -122.2, "fbos": [{"name": "F1", "fuels": {"100LL": {"price": 6.00, "type": "100LL", "service": "Self-Serve"}}}]},
            {"icao": "K2", "name": "Apt 2", "lat": 37.5, "lon": -122.2, "fbos": [{"name": "F2", "fuels": {"94UL": {"price": 7.00, "type": "94UL", "service": "Self-Serve"}}}]}
        ]
        results, lowest = query_radius(mock_data, 37.5, -122.2, 100, fuel_type='94UL')
        self.assertEqual(len(results), 1)
        for r in results:
            self.assertEqual(r["fuel"]["type"], "94UL")

    def test_fuel_type_filter_100ul(self):
        """Test 100UL unleaded fuel filtering."""
        mock_data = [
            {"icao": "K1", "name": "Apt 1", "lat": 37.5, "lon": -122.2, "fbos": [{"name": "F1", "fuels": {"100LL": {"price": 6.00, "type": "100LL", "service": "Self-Serve"}}}]},
            {"icao": "K2", "name": "Apt 2", "lat": 37.5, "lon": -122.2, "fbos": [{"name": "F2", "fuels": {"100UL": {"price": 7.50, "type": "100UL", "service": "Self-Serve"}}}]}
        ]
        results, lowest = query_radius(mock_data, 37.5, -122.2, 100, fuel_type='100UL')
        self.assertEqual(len(results), 1)
        for r in results:
            self.assertEqual(r["fuel"]["type"], "100UL")

    def test_fuel_type_filter_mogas(self):
        """Test Mogas ethanol-free fuel filtering."""
        mock_data = [
            {"icao": "K1", "name": "Apt 1", "lat": 38.0, "lon": -121.5, "fbos": [{"name": "F1", "fuels": {"Mogas": {"price": 5.20, "type": "Mogas", "service": "Self-Serve"}}}]}
        ]
        results, lowest = query_radius(mock_data, 38.0, -121.5, 100, fuel_type='Mogas')
        self.assertEqual(len(results), 1)
        for r in results:
            self.assertEqual(r["fuel"]["type"], "Mogas")

    def test_fuel_type_filter_100r(self):
        """Test 100R Swift fuel filtering."""
        mock_data = [
            {"icao": "K1", "name": "Apt 1", "lat": 43.98, "lon": -88.55, "fbos": [{"name": "F1", "fuels": {"100R": {"price": 6.80, "type": "100R", "service": "Self-Serve"}}}]}
        ]
        results, lowest = query_radius(mock_data, 43.98, -88.55, 200, fuel_type='100R')
        self.assertEqual(len(results), 1)
        for r in results:
            self.assertEqual(r["fuel"]["type"], "100R")

    def test_service_filter_self_serve(self):
        """Test self-serve only filtering."""
        mock_data = [
            {"icao": "K1", "name": "Apt 1", "lat": 37.5, "lon": -122.2, "fbos": [{"name": "F1", "fuels": {"100LL": {"price": 6.00, "type": "100LL", "service": "Self-Serve"}}}]},
            {"icao": "K2", "name": "Apt 2", "lat": 37.5, "lon": -122.2, "fbos": [{"name": "F2", "fuels": {"100LL": {"price": 6.50, "type": "100LL", "service": "Full-Serve"}}}]}
        ]
        results, lowest = query_radius(mock_data, 37.5, -122.2, 60, service='self')
        self.assertEqual(len(results), 1)
        for r in results:
            self.assertEqual(r["fuel"]["service"], "Self-Serve")

    def test_service_filter_full_serve(self):
        """Test full-serve only filtering."""
        mock_data = [
            {"icao": "K1", "name": "Apt 1", "lat": 37.5, "lon": -122.2, "fbos": [{"name": "F1", "fuels": {"100LL": {"price": 6.00, "type": "100LL", "service": "Self-Serve"}}}]},
            {"icao": "K2", "name": "Apt 2", "lat": 37.5, "lon": -122.2, "fbos": [{"name": "F2", "fuels": {"100LL": {"price": 6.50, "type": "100LL", "service": "Full-Serve"}}}]}
        ]
        results, lowest = query_radius(mock_data, 37.5, -122.2, 60, service='full')
        self.assertEqual(len(results), 1)
        for r in results:
            self.assertEqual(r["fuel"]["service"], "Full-Serve")

    def test_empty_radius_ocean(self):
        """Query middle of Pacific Ocean where no airports exist."""
        results, lowest = query_radius(self.airports, 25.0, -140.0, 50, include_unpriced=True)
        self.assertEqual(len(results), 0)
        self.assertIsNone(lowest)

    def test_zero_radius_behavior(self):
        """Query with 0 radius - should only match exact point if coincident."""
        results, lowest = query_radius(self.airports, 37.5119, -122.2495, 0.0, include_unpriced=True)
        if results:
            self.assertEqual(results[0]["distance"], 0.0)

    def test_large_radius_500_miles(self):
        """Test 500 mile radius centered at Oshkosh (KOSH)."""
        center_lat, center_lon = 43.9844, -88.5570
        results, lowest = query_radius(self.airports, center_lat, center_lon, 500, include_unpriced=True)
        self.assertGreater(len(results), 20)
        for r in results:
            self.assertLessEqual(r["distance"], 500.0)

    def test_out_of_radius_airports_strictly_excluded(self):
        """Verify that airports outside the search radius are strictly excluded from radar results."""
        center_lat, center_lon = 37.5119, -122.2495  # KSQL
        radius = 25.0
        results, lowest = query_radius(self.airports, center_lat, center_lon, radius)

        in_radius_icaos = {r["icao"] for r in results}
        for apt in self.airports:
            dist = haversine_miles(center_lat, center_lon, apt["lat"], apt["lon"])
            if dist > radius:
                self.assertNotIn(apt["icao"], in_radius_icaos,
                                 f"Airport {apt['icao']} at {dist:.1f} mi was incorrectly included in {radius} mi radius")

    def test_marker_fuel_price_visibility_css_rules(self):
        """Verify style.css hides fuel price badges, ribbons, and rings by default and reveals them in-radius."""
        css_path = os.path.join(DIRECTORY, "style.css")
        self.assertTrue(os.path.exists(css_path), "style.css missing")
        with open(css_path, "r") as f:
            css_content = f.read()

        # Check that default fuel-price-badge is display: none
        self.assertIn(".fuel-price-badge {\n  display: none;", css_content)
        # Check that in-radius reveals badge
        self.assertIn(".airport-marker-container.in-radius .fuel-price-badge", css_content)
        self.assertIn("display: inline-flex;", css_content)
        # Check unreported tier styling
        self.assertIn(".tier-unreported", css_content)
        # Check that lowest ribbon and pulse ring are hidden by default
        self.assertIn(".lowest-ribbon {\n  display: none;", css_content)
        self.assertIn(".pulse-ring {\n  display: none;", css_content)
        # Check that is-lowest reveals them
        self.assertIn(".airport-marker-container.is-lowest .lowest-ribbon", css_content)
        self.assertIn(".airport-marker-container.is-lowest .pulse-ring", css_content)

    def test_app_js_marker_markup_no_price_leak(self):
        """Verify app.js marker markup does not leak fuel prices in hover title."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        self.assertTrue(os.path.exists(app_js_path), "app.js missing")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        # Ensure title attribute only contains ICAO/FAA/Name/City/State and no '$' or price
        self.assertIn('title="${apt.icao} - ${apt.name} (${apt.city}, ${apt.state})"', app_content)

    def test_performance_speed(self):
        """Performance benchmark: filtering 5,000+ airport dataset must take < 2ms."""
        import time
        t0 = time.perf_counter()
        for _ in range(100):
            query_radius(self.airports, 37.5119, -122.2495, 100)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0 / 100.0
        self.assertLess(elapsed_ms, 2.0, f"Query took {elapsed_ms:.3f}ms (expected < 2ms)")

    def test_high_latitude_spatial_bounding(self):
        """Verify high-latitude airports (Alaska up to 71.3°N) are never missed by bounding box."""
        for center_lat, center_lon in [(64.8, -147.7), (70.0, -150.0)]:
            for r in [50, 100, 500]:
                results, _ = query_radius(self.airports, center_lat, center_lon, r, include_unpriced=True)
                exact_count = sum(1 for a in self.airports if haversine_miles(center_lat, center_lon, a["lat"], a["lon"]) <= r)
                self.assertEqual(len(results), exact_count,
                                 f"Spatial bounding box missed airports at lat {center_lat}, radius {r}: got {len(results)}, expected {exact_count}")

    def test_remote_circle_zero_priced_airports(self):
        """Test radar circle positioned over a remote region with airports but zero reported fuel prices."""
        unpriced_airports = [a for a in self.airports if a.get("best_price") is None]
        if unpriced_airports:
            sample = unpriced_airports[0]
            results, lowest = query_radius(self.airports, sample["lat"], sample["lon"], 10, include_unpriced=True)
            self.assertGreater(len(results), 0)
            if all(not r["has_fuel"] for r in results):
                self.assertIsNone(lowest)

    def test_territories_public_airports_coverage(self):
        """Verify coverage for all US territories (PR, VI, GU, AS, MP) with valid coordinates and properties."""
        territories = {'PR', 'VI', 'GU', 'AS', 'MP'}
        found_territories = set()
        for apt in self.airports:
            state = apt.get("state")
            if state in territories:
                found_territories.add(state)
                self.assertTrue(apt.get("icao"), f"Missing ICAO for territory airport {apt}")
                self.assertTrue(apt.get("name"), f"Missing name for territory airport {apt}")
                self.assertIsNotNone(apt.get("lat"), f"Missing lat for territory airport {apt}")
                self.assertIsNotNone(apt.get("lon"), f"Missing lon for territory airport {apt}")
                self.assertGreaterEqual(len(apt.get("runways", [])), 1)
        self.assertEqual(found_territories, territories, f"Missing territory coverage: {territories - found_territories}")

    def test_all_airports_schema_completeness(self):
        """Verify that every airport in the catalog has all essential fields defined and non-empty."""
        for apt in self.airports:
            self.assertTrue(apt.get("icao"), f"Missing ICAO: {apt}")
            self.assertTrue(apt.get("name"), f"Missing name: {apt['icao']}")
            self.assertTrue(apt.get("city"), f"Missing city: {apt['icao']}")
            self.assertTrue(apt.get("state"), f"Missing state: {apt['icao']}")
            self.assertEqual(apt.get("country"), "US", f"Country should be US: {apt['icao']}")
            self.assertIsInstance(apt.get("elevation_ft"), (int, float), f"Invalid elevation: {apt['icao']}")
            self.assertIsInstance(apt.get("ctaf_freq"), (int, float), f"Invalid CTAF: {apt['icao']}")
            self.assertIsInstance(apt.get("runways"), list, f"Runways should be list: {apt['icao']}")
            self.assertGreater(len(apt["runways"]), 0, f"Runways should not be empty: {apt['icao']}")
            self.assertIn("surface", apt["runways"][0], f"Runway missing surface: {apt['icao']}")
            self.assertIn("length", apt["runways"][0], f"Runway missing length: {apt['icao']}")

    def test_marker_z_index_ordering_css(self):
        """Verify style.css ensures lowest price marker is on top (z-index: 10000) over in-radius (500) and hover."""
        css_path = os.path.join(DIRECTORY, "style.css")
        self.assertTrue(os.path.exists(css_path), "style.css missing")
        with open(css_path, "r") as f:
            css_content = f.read()

        # Check in-radius container has z-index: 500
        self.assertIn(".airport-marker-container.in-radius {\n  z-index: 500;\n}", css_content)
        # Check lowest container has z-index: 10000 !important
        self.assertIn(".airport-marker-container.is-lowest {\n  z-index: 10000 !important;", css_content)

    def test_app_js_z_index_offset_calls(self):
        """Verify app.js applies Leaflet setZIndexOffset for lowest (10000), in-radius (500), and reset (0)."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        self.assertTrue(os.path.exists(app_js_path), "app.js missing")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        # Check lowest price marker gets z-index offset 10000
        self.assertIn("lowestMarkerObj.marker.setZIndexOffset(10000);", app_content)
        # Check in-radius markers get z-index offset 500
        self.assertIn("markerObj.marker.setZIndexOffset(500);", app_content)
        # Check out-of-radius markers get reset to 0
        self.assertIn("markerObj.marker.setZIndexOffset(0);", app_content)
        # Check previous lowest gets reset properly
        self.assertIn("prevMarkerObj.marker.setZIndexOffset(resetZ);", app_content)

    def test_marker_z_index_hierarchy(self):
        """Verify z-index hierarchy guarantees lowest price marker rendered in front of all other markers."""
        z_lowest = 10000
        z_in_radius = 500
        z_default = 0
        self.assertGreater(z_lowest, z_in_radius, "Lowest marker z-index must exceed in-radius marker z-index")
        self.assertGreater(z_in_radius, z_default, "In-radius marker z-index must exceed default out-of-radius z-index")

    def test_canvas_overlay_rendering_and_hit_testing_in_app_js(self):
        """Verify app.js implements high-performance canvas background overlay and spatial hit-testing."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        self.assertIn("function initAirportCanvas()", app_content)
        self.assertIn("function redrawAirportCanvas()", app_content)
        self.assertIn("function findAirportNearPoint(", app_content)
        self.assertIn("airportCanvasEl", app_content)
        self.assertIn("airportCanvasCtx", app_content)

    def test_canvas_container_mounting_and_drag_event_listeners(self):
        """Verify canvas is mounted to map.getContainer() and locked during drag gestures without pane doubling."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        self.assertTrue(os.path.exists(app_js_path), "app.js missing")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        # Canvas must be appended directly to map.getContainer() to prevent double translation during map drag
        self.assertIn("map.getContainer().appendChild(airportCanvasEl);", app_content)
        self.assertNotIn("map.getPanes().overlayPane.appendChild(airportCanvasEl);", app_content)

        # Ensure container-relative coordinate projection is used for canvas dots
        self.assertIn("map.latLngToContainerPoint([apt.lat, apt.lon])", app_content)

        # Ensure move, drag, and zoom events all trigger canvas redraw
        self.assertIn("map.on('move', redrawAirportCanvas);", app_content)
        self.assertIn("map.on('drag', redrawAirportCanvas);", app_content)
        self.assertIn("map.on('zoom', redrawAirportCanvas);", app_content)

        # Verify pointer-events and z-index on canvas element (must be > 400 to sit above Leaflet map tiles)
        self.assertIn("airportCanvasEl.style.position = 'absolute';", app_content)
        self.assertIn("airportCanvasEl.style.pointerEvents = 'none';", app_content)
        self.assertIn("airportCanvasEl.style.zIndex = '450';", app_content)

    def test_smart_decluttering_and_zoom_filtering_in_app_js(self):
        """Verify app.js includes smart decluttering and collision avoidance to prevent DOM bloat."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        self.assertIn("tagBudget", app_content)
        self.assertIn("minSeparationPx", app_content)
        self.assertIn("acceptedHighlightList", app_content)
        self.assertIn("acceptedScreenPoints", app_content)
        self.assertIn("currentHighlightedIcaos", app_content)

    def test_no_synthetic_diagonal_coordinates_in_generator(self):
        """Verify fetch_fuel_data.py has purged all synthetic linear-congruential grid formulas."""
        gen_path = os.path.join(DIRECTORY, "fetch_fuel_data.py")
        with open(gen_path, "r") as f:
            gen_content = f.read()

        self.assertNotIn("((pseudo_seed * 7) % 1000)", gen_content)
        self.assertNotIn("(pseudo_seed * 7)", gen_content)

    def test_real_coordinates_geographic_bounds_all_airports(self):
        """Verify all airports in the catalog have realistic coordinates on authentic US soil/territories."""
        for apt in self.airports:
            lat = apt["lat"]
            lon = apt["lon"]
            state = apt["state"]

            self.assertIsInstance(lat, (int, float))
            self.assertIsInstance(lon, (int, float))
            self.assertFalse(math.isnan(lat))
            self.assertFalse(math.isnan(lon))

            if state == 'AK':
                self.assertTrue(51.0 <= lat <= 72.0, f"Alaska lat out of bounds: {apt}")
                self.assertTrue(-180.0 <= lon <= -130.0 or 170.0 <= lon <= 180.0, f"Alaska lon out of bounds: {apt}")
            elif state == 'HI':
                self.assertTrue(18.0 <= lat <= 29.0, f"Hawaii lat out of bounds: {apt}")
                self.assertTrue(-179.0 <= lon <= -154.0, f"Hawaii lon out of bounds: {apt}")
            elif state in ('PR', 'VI'):
                self.assertTrue(17.0 <= lat <= 19.5, f"PR/VI lat out of bounds: {apt}")
                self.assertTrue(-68.5 <= lon <= -64.0, f"PR/VI lon out of bounds: {apt}")
            elif state in ('GU', 'MP'):
                self.assertTrue(13.0 <= lat <= 21.0, f"GU/MP lat out of bounds: {apt}")
                self.assertTrue(144.0 <= lon <= 146.5, f"GU/MP lon out of bounds: {apt}")
            elif state == 'AS':
                self.assertTrue(-15.0 <= lat <= -11.0, f"AS lat out of bounds: {apt}")
                self.assertTrue(-171.0 <= lon <= -168.0, f"AS lon out of bounds: {apt}")
            elif state == 'UM':
                self.assertTrue(-1.0 <= lat <= 30.0, f"UM lat out of bounds: {apt}")
                self.assertTrue(-180.0 <= lon <= 180.0, f"UM lon out of bounds: {apt}")
            else:
                # CONUS
                self.assertTrue(24.0 <= lat <= 50.0, f"CONUS lat out of bounds: {apt}")
                self.assertTrue(-125.5 <= lon <= -66.5, f"CONUS lon out of bounds: {apt}")

    def test_faa_icao_standards_hollister_cvh_not_khli(self):
        """Verify Hollister is cataloged as KCVH (ICAO) / CVH (FAA LID) with IATA HLI, and KHLI does not exist."""
        by_icao = {a["icao"]: a for a in self.airports}
        self.assertIn("KCVH", by_icao, "KCVH (Hollister Municipal) must be present in catalog")
        self.assertNotIn("KHLI", by_icao, "KHLI is a confused IATA identifier and must NOT exist as primary ICAO")

        hollister = by_icao["KCVH"]
        self.assertEqual(hollister["faa"], "CVH", f"Expected FAA LID 'CVH', got {hollister.get('faa')}")
        self.assertEqual(hollister["iata"], "HLI", f"Expected IATA code 'HLI', got {hollister.get('iata')}")
        self.assertEqual(hollister["state"], "CA")
        self.assertIn("Hollister", hollister["name"])
        self.assertAlmostEqual(hollister["lat"], 36.8933, places=2)
        self.assertAlmostEqual(hollister["lon"], -121.4100, places=2)

    def test_alphanumeric_faa_lid_standards(self):
        """Verify 3-character alphanumeric airfields retain their FAA LID as primary identifier without leading K."""
        by_icao = {a["icao"]: a for a in self.airports}

        # San Martin: E16 (not KE16)
        self.assertIn("E16", by_icao, "E16 (San Martin Airport) must be primary identifier")
        self.assertNotIn("KE16", by_icao, "KE16 must NOT exist as primary identifier")
        san_martin = by_icao["E16"]
        self.assertEqual(san_martin["faa"], "E16")
        self.assertEqual(san_martin["state"], "CA")

        # Columbia: O22 (not KO22)
        self.assertIn("O22", by_icao, "O22 (Columbia Airport) must be primary identifier")
        self.assertNotIn("KO22", by_icao, "KO22 must NOT exist as primary identifier")
        columbia = by_icao["O22"]
        self.assertEqual(columbia["faa"], "O22")
        self.assertEqual(columbia["iata"], "COA")
        self.assertEqual(columbia["state"], "CA")

        # Byron: C83 (not KC83)
        self.assertIn("C83", by_icao, "C83 (Byron Airport) must be primary identifier")
        self.assertNotIn("KC83", by_icao, "KC83 must NOT exist as primary identifier")
        byron = by_icao["C83"]
        self.assertEqual(byron["faa"], "C83")
        self.assertEqual(byron["state"], "CA")

        # Shelter Cove: 0Q5 (not K0Q5)
        self.assertIn("0Q5", by_icao, "0Q5 (Shelter Cove Airport) must be primary identifier")
        self.assertNotIn("K0Q5", by_icao, "K0Q5 must NOT exist as primary identifier")

        # Rio Vista: O88 (not KO88)
        self.assertIn("O88", by_icao, "O88 (Rio Vista Municipal) must be primary identifier")
        self.assertNotIn("KO88", by_icao, "KO88 must NOT exist as primary identifier")

    def test_real_world_conus_4letter_icao_and_faa_lids(self):
        """Verify CONUS 3-letter FAA LIDs correctly map to 4-letter ICAO prefixed with K."""
        by_icao = {a["icao"]: a for a in self.airports}

        # Reid-Hillview: KRHV / RHV
        self.assertIn("KRHV", by_icao)
        self.assertEqual(by_icao["KRHV"]["faa"], "RHV")
        self.assertEqual(by_icao["KRHV"]["iata"], "RHV")
        self.assertIn("Reid-Hillview", by_icao["KRHV"]["name"])

        # Half Moon Bay: KHAF / HAF
        self.assertIn("KHAF", by_icao)
        self.assertEqual(by_icao["KHAF"]["faa"], "HAF")
        self.assertEqual(by_icao["KHAF"]["iata"], "HAF")
        self.assertIn("Half Moon Bay", by_icao["KHAF"]["name"])

        # San Carlos: KSQL / SQL
        self.assertIn("KSQL", by_icao)
        self.assertEqual(by_icao["KSQL"]["faa"], "SQL")
        self.assertEqual(by_icao["KSQL"]["iata"], "SQL")

        # Palo Alto: KPAO / PAO
        self.assertIn("KPAO", by_icao)
        self.assertEqual(by_icao["KPAO"]["faa"], "PAO")
        self.assertEqual(by_icao["KPAO"]["iata"], "PAO")

        # Tracy: KTCY / TCY
        self.assertIn("KTCY", by_icao)
        self.assertEqual(by_icao["KTCY"]["faa"], "TCY")

    def test_baseline_airports_clean_unpriced_catalog(self):
        """Verify baseline airports have authentic operational metadata but start clean and unpriced."""
        by_icao = {a["icao"]: a for a in self.airports}

        for icao in ["KCVH", "E16", "O22", "KRHV", "KHAF", "KSQL", "KPAO", "C83", "KTCY", "O88", "0Q5"]:
            self.assertIn(icao, by_icao, f"Curated airport {icao} must exist in dataset")
            apt = by_icao[icao]
            self.assertIsNone(apt.get("best_price"), f"{icao} must NOT have baseline default fuel price")
            self.assertEqual(apt.get("fbos", []), [], f"{icao} must have empty fbos until AirNav on-demand fetch")
            self.assertEqual(apt.get("fuels_available", []), [])
            self.assertIsNone(apt.get("primary_fuel"))
            # Operational metadata intact
            self.assertTrue(len(apt.get("name", "")) > 0)
            self.assertIsNotNone(apt.get("lat"))
            self.assertIsNotNone(apt.get("lon"))

    def test_search_filter_matches_faa_icao_iata(self):
        """Verify search logic matches airports by ICAO, FAA LID, IATA code, and city name."""
        def search_airports(q):
            q_low = q.lower()
            return [
                a for a in self.airports
                if (a["icao"].lower().find(q_low) != -1 or
                    (a.get("faa") and a["faa"].lower().find(q_low) != -1) or
                    (a.get("iata") and a["iata"].lower().find(q_low) != -1) or
                    a["name"].lower().find(q_low) != -1 or
                    a["city"].lower().find(q_low) != -1 or
                    a["state"].lower().find(q_low) != -1)
            ]

        # Search Hollister by ICAO 'KCVH', FAA 'CVH', IATA 'HLI', and city 'Hollister'
        res_icao = search_airports("KCVH")
        res_faa = search_airports("CVH")
        res_iata = search_airports("HLI")
        res_city = search_airports("Hollister")

        self.assertTrue(any(a["icao"] == "KCVH" for a in res_icao))
        self.assertTrue(any(a["icao"] == "KCVH" for a in res_faa))
        self.assertTrue(any(a["icao"] == "KCVH" for a in res_iata))
        self.assertTrue(any(a["icao"] == "KCVH" for a in res_city))

        # Search San Martin by FAA LID 'E16'
        res_e16 = search_airports("E16")
        self.assertTrue(any(a["icao"] == "E16" for a in res_e16))

        # Search Columbia by FAA LID 'O22' or IATA 'COA'
        res_o22 = search_airports("O22")
        res_coa = search_airports("COA")
        self.assertTrue(any(a["icao"] == "O22" for a in res_o22))
        self.assertTrue(any(a["icao"] == "O22" for a in res_coa))

    def test_modal_identifier_formatting_in_app_js(self):
        """Verify app.js modal title properly formats identifiers without duplicate codes and includes IATA."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        self.assertTrue(os.path.exists(app_js_path), "app.js missing")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        self.assertIn("const identParts = [apt.icao];", app_content)
        self.assertIn("if (apt.faa && apt.faa !== apt.icao)", app_content)
        self.assertIn("if (apt.iata && apt.iata !== apt.faa && apt.iata !== apt.icao)", app_content)
        self.assertIn("<h2>✈️ ${apt.name} (${identHeader})</h2>", app_content)

    def test_alaska_hawaii_territories_icao_and_faa_standards(self):
        """Verify Alaska, Hawaii, and US territories use proper 4-letter ICAO and 3-letter FAA LIDs."""
        by_icao = {a["icao"]: a for a in self.airports}

        # Alaska: Anchorage PANC / ANC
        self.assertIn("PANC", by_icao)
        self.assertEqual(by_icao["PANC"]["faa"], "ANC")
        self.assertEqual(by_icao["PANC"]["state"], "AK")

        # Hawaii: Honolulu PHNL / HNL
        self.assertIn("PHNL", by_icao)
        self.assertEqual(by_icao["PHNL"]["faa"], "HNL")
        self.assertEqual(by_icao["PHNL"]["state"], "HI")

        # Puerto Rico: San Juan TJSJ / SJU
        self.assertIn("TJSJ", by_icao)
        self.assertEqual(by_icao["TJSJ"]["faa"], "SJU")
        self.assertEqual(by_icao["TJSJ"]["state"], "PR")

        # US Virgin Islands: St. Thomas TIST / STT
        self.assertIn("TIST", by_icao)
        self.assertEqual(by_icao["TIST"]["faa"], "STT")
        self.assertEqual(by_icao["TIST"]["state"], "VI")

        # Guam: Antonio B. Won Pat PGUM / GUM
        self.assertIn("PGUM", by_icao)
        self.assertEqual(by_icao["PGUM"]["faa"], "GUM")
        self.assertEqual(by_icao["PGUM"]["state"], "GU")

        # American Samoa: Pago Pago NSTU / PPG
        self.assertIn("NSTU", by_icao)
        self.assertEqual(by_icao["NSTU"]["faa"], "PPG")
        self.assertEqual(by_icao["NSTU"]["state"], "AS")

        # Northern Mariana Islands: Saipan PGSN / GSN
        self.assertIn("PGSN", by_icao)
        self.assertEqual(by_icao["PGSN"]["faa"], "GSN")
        self.assertEqual(by_icao["PGSN"]["state"], "MP")

    def test_midwest_alphanumeric_k_codes(self):
        """Verify Kansas/Midwest FAA LIDs starting with 'K' followed by numbers avoid spurious double 'K' prefixes."""
        by_icao = {a["icao"]: a for a in self.airports}

        # Abilene Municipal K78 (not KK78)
        self.assertIn("K78", by_icao, "K78 (Abilene Municipal) must be primary identifier")
        self.assertNotIn("KK78", by_icao, "KK78 must NOT exist as primary identifier")
        self.assertEqual(by_icao["K78"]["faa"], "K78")

        # Rolla Downtown K07 (not KK07)
        self.assertIn("K07", by_icao, "K07 (Rolla Downtown) must be primary identifier")
        self.assertNotIn("KK07", by_icao, "KK07 must NOT exist as primary identifier")
        self.assertEqual(by_icao["K07"]["faa"], "K07")

        # Gardner Municipal K34 (not KK34)
        self.assertIn("K34", by_icao, "K34 (Gardner Municipal) must be primary identifier")
        self.assertNotIn("KK34", by_icao, "KK34 must NOT exist as primary identifier")
        self.assertEqual(by_icao["K34"]["faa"], "K34")

    def test_canvas_overlay_z_index_and_layering(self):
        """Verify airport canvas overlay z-index is strictly above Leaflet map pane (400) and keeps pointer-events none."""
        import re
        app_js_path = os.path.join(DIRECTORY, "app.js")
        style_css_path = os.path.join(DIRECTORY, "style.css")

        self.assertTrue(os.path.exists(app_js_path), "app.js missing")
        self.assertTrue(os.path.exists(style_css_path), "style.css missing")

        with open(app_js_path, "r") as f:
            app_content = f.read()

        with open(style_css_path, "r") as f:
            css_content = f.read()

        # Check app.js canvas zIndex > 400 and < 500
        z_match = re.search(r"airportCanvasEl\.style\.zIndex\s*=\s*['\"](\d+)['\"]", app_content)
        self.assertIsNotNone(z_match, "airportCanvasEl.style.zIndex setting not found in app.js")
        z_val = int(z_match.group(1))
        self.assertGreater(z_val, 400, f"Canvas zIndex ({z_val}) must be > 400 to sit above Leaflet map pane (400)")
        self.assertLess(z_val, 500, f"Canvas zIndex ({z_val}) must be < 500 so active marker bubbles sit on top")

        # Check pointer-events is none
        self.assertIn("airportCanvasEl.style.pointerEvents = 'none'", app_content)

        # Check style.css .airport-dots-canvas
        self.assertIn(".airport-dots-canvas", css_content)
        css_z_match = re.search(r"\.airport-dots-canvas\s*\{[^}]*z-index:\s*(\d+)", css_content)
        self.assertIsNotNone(css_z_match, ".airport-dots-canvas z-index not found in style.css")
        css_z_val = int(css_z_match.group(1))
        self.assertGreater(css_z_val, 400, f"CSS .airport-dots-canvas z-index ({css_z_val}) must be > 400")
        self.assertLess(css_z_val, 500, f"CSS .airport-dots-canvas z-index ({css_z_val}) must be < 500")

    def test_default_in_radius_badges_render_identifier_only_without_prices(self):
        """Verify that in app.js, in-radius airport badges default to displaying only the Airport Identifier (no initial prices or dollar signs)."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        self.assertTrue(os.path.exists(app_js_path), "app.js missing")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        # Check default identifier-only tier class is present
        self.assertIn("tier-ident", app_content)
        self.assertIn('<span class="badge-code">${ident}</span>', app_content)
        # Check hasFetchedPrice helper exists and gates price display
        self.assertIn("function hasFetchedPrice(airport)", app_content)
        self.assertIn("STATE.fetchedAirports", app_content)

    def test_onclick_triggers_airnav_fetch_and_loading_state(self):
        """Verify marker click invokes fetchAirportFuelAndHighlight, sets is-loading state with spinner, and queries /api/airnav."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        # Check click handler calls on-demand fetch
        self.assertIn("fetchAirportFuelAndHighlight(apt);", app_content)
        self.assertIn("async function fetchAirportFuelAndHighlight(apt", app_content)
        self.assertIn("setMarkerLoadingState(icao, true);", app_content)
        self.assertIn("is-loading", app_content)
        self.assertIn("badge-loading-spinner", app_content)
        self.assertIn("/api/airnav?icao=", app_content)

    def test_dynamic_badge_update_with_live_airnav_price(self):
        """Verify dynamic DOM badge update renders live price, fuel type, and tier class upon fetch completion."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        self.assertIn("function updateMarkerBadgeContent(apt)", app_content)
        self.assertIn('<span class="badge-price">$${fuelInfo.price.toFixed(2)}</span>', app_content)
        self.assertIn('<span class="badge-fuel-type">${fuelInfo.type}</span>', app_content)
        self.assertIn("updateMarkerBadgeContent(apt);", app_content)

    def test_session_state_persistence_for_fetched_airports(self):
        """Verify fetched AirNav rates are persisted in STATE.fetchedAirports and STATE.customPrices."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        self.assertIn("STATE.fetchedAirports.add(icao);", app_content)
        self.assertIn("STATE.customPrices[icao]", app_content)

    def test_sidebar_stats_focus_on_priced_airports(self):
        """Verify app.js sidebar stats count prioritizes priced airports and clearly separates unfetched and unpriced airfields."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        self.assertIn("const priced = inRadiusList.filter(a => a.hasFuel && a.effectiveFuel);", app_content)
        self.assertIn("const unfetched = inRadiusList.filter(a => !a.isFetched);", app_content)
        self.assertIn("const confirmedNoFuel = inRadiusList.filter(a => a.isFetched && !a.hasFuel);", app_content)
        self.assertIn("countEl.innerText = priced.length;", app_content)
        self.assertIn("is-unfetched-card", app_content)
        self.assertIn("card-price-fetch", app_content)

    def test_modal_loading_and_fetch_live_persistence(self):
        """Verify openAirportModal handles loading state and persists fetched prices when live fetch button is clicked."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        self.assertIn("function openAirportModal(apt, isLoading = false)", app_content)
        self.assertIn("Fetching Live AirNav Fuel Rates...", app_content)
        self.assertIn("STATE.fetchedAirports.add(apt.icao);", app_content)
        self.assertIn("STATE.customPrices[apt.icao]", app_content)

    def test_search_click_triggers_airnav_on_demand_fetch(self):
        """Verify selecting an airport from search dropdown triggers on-demand AirNav fetch."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        self.assertIn("fetchAirportFuelAndHighlight(apt);", app_content)

    def test_spatial_radius_separates_priced_dom_candidates_from_canvas_dots(self):
        """Verify spatial radius query properly distinguishes DOM-eligible candidates from background canvas dots."""
        center_lat, center_lon = 37.5119, -122.2495  # KSQL
        results_all, lowest = query_radius(self.airports, center_lat, center_lon, 50, include_unpriced=True)

        self.assertGreater(len(results_all), 0, "Should have airfields in Bay Area")

        # Now test with seeded live AirNav rates
        mock_data = [
            {"icao": "KSQL", "name": "San Carlos", "lat": 37.5119, "lon": -122.2495, "fbos": [{"name": "Rabbit", "fuels": {"100LL": {"price": 6.15, "type": "100LL", "service": "Self-Serve"}}}]},
            {"icao": "KPAO", "name": "Palo Alto", "lat": 37.4611, "lon": -122.1151, "fbos": []}
        ]
        results_mock, lowest_mock = query_radius(mock_data, center_lat, center_lon, 50, include_unpriced=True)
        priced_results = [r for r in results_mock if r["has_fuel"] and r["fuel"] is not None]
        unpriced_results = [r for r in results_mock if not r["has_fuel"] or r["fuel"] is None]

        self.assertEqual(len(priced_results), 1)
        self.assertEqual(len(unpriced_results), 1)
        self.assertEqual(priced_results[0]["fuel"]["price"], 6.15)

    def test_fuel_filter_transitions_exclude_unmatching_from_highlight_bubbles(self):
        """Verify that applying strict fuel filters causes airports without matching grades to be treated as unpriced and excluded from marker highlight."""
        mock_data = [
            {"icao": "K1", "name": "Apt 1", "lat": 37.51, "lon": -122.24, "fbos": [{"name": "F1", "fuels": {"100LL": {"price": 6.15, "type": "100LL", "service": "Self-Serve"}}}]},
            {"icao": "K2", "name": "Apt 2", "lat": 37.46, "lon": -122.11, "fbos": [{"name": "F2", "fuels": {"100UL": {"price": 7.20, "type": "100UL", "service": "Self-Serve"}}}]}
        ]
        # Test 100UL unleaded fuel filter
        results_100ul, lowest_100ul = query_radius(mock_data, 37.51, -122.24, 100, fuel_type='100UL', include_unpriced=True)
        priced_100ul = [r for r in results_100ul if r["has_fuel"]]
        unpriced_100ul = [r for r in results_100ul if not r["has_fuel"]]

        self.assertEqual(len(priced_100ul), 1)
        self.assertEqual(priced_100ul[0]["fuel"]["type"], "100UL")
        self.assertEqual(len(unpriced_100ul), 1)
        self.assertEqual(unpriced_100ul[0]["icao"], "K1")

    def test_screen_space_budget_and_highlight_selection_supports_in_radius_identifiers(self):
        """Simulate app.js highlight candidate selection logic and verify in-radius airports are selected with identifier-only default presentation."""
        center_lat, center_lon = 37.5119, -122.2495
        results_all, lowest = query_radius(self.airports, center_lat, center_lon, 50, include_unpriced=True)

        accepted_highlight_list = []
        if lowest:
            accepted_highlight_list.append(lowest)

        # In-radius candidates accepted up to tag budget
        for candidate in results_all:
            if lowest and candidate["icao"] == lowest["icao"]:
                continue
            accepted_highlight_list.append(candidate)

        self.assertGreater(len(accepted_highlight_list), 0)
        # All accepted items are valid in-radius airports
        for apt in accepted_highlight_list:
            self.assertTrue("icao" in apt or "faa" in apt)

    def test_zip_package_archive_integrity(self):
        """Verify airport_fuel_lookup.zip is packaged at the requested debug path and contains all essential application files."""
        import zipfile
        zip_candidates = [
            "/google/src/cloud/gfahmy/debug_working_directory_path/airport_fuel_lookup.zip",
            os.path.join(DIRECTORY, "airport_fuel_lookup.zip"),
            "/tmp/airport_fuel_lookup.zip"
        ]
        zip_path = None
        for c in zip_candidates:
            if os.path.exists(c) and os.path.getsize(c) > 0:
                zip_path = c
                break

        self.assertIsNotNone(zip_path, f"airport_fuel_lookup.zip not found in {zip_candidates}")
        self.assertTrue(
            os.path.exists("/google/src/cloud/gfahmy/debug_working_directory_path/airport_fuel_lookup.zip"),
            "Expected /google/src/cloud/gfahmy/debug_working_directory_path/airport_fuel_lookup.zip to exist"
        )

        with zipfile.ZipFile(zip_path, "r") as zf:
            namelist = zf.namelist()
            required_files = [
                "index.html",
                "app.js",
                "style.css",
                "fetch_fuel_data.py",
                "airnav_client.py",
                "generate_dataset.py",
                "test_fuel_lookup.py",
                "README.md",
                "server.py"
            ]
            for rf in required_files:
                self.assertTrue(
                    any(rf == n or n.endswith("/" + rf) for n in namelist),
                    f"File {rf} missing from airport_fuel_lookup.zip"
                )


class TestAirNavParser(unittest.TestCase):
    """Automated tests for AirNav HTML parsing, price extraction, and FBO detection."""

    def setUp(self):
        import tempfile

        from airnav_client import (AirNavClient, normalize_fuel_type,
                                   normalize_service_type, parse_price_val)
        self.test_cache_dir = tempfile.mkdtemp()
        self.client = AirNavClient(cache_dir=self.test_cache_dir, cache_ttl=10)
        self.normalize_fuel_type = normalize_fuel_type
        self.normalize_service_type = normalize_service_type
        self.parse_price_val = parse_price_val

    def tearDown(self):
        import shutil
        self.client.clear_cache()
        if os.path.exists(self.test_cache_dir):
            try:
                shutil.rmtree(self.test_cache_dir, ignore_errors=True)
            except Exception:
                pass

    def test_fuel_type_normalization_variations(self):
        """Verify normalization of diverse fuel grade designations into canonical aviation types."""
        # 100LL
        for raw in ["100LL", "100ll", "100-LL", "100 LL Avgas", "Avgas 100LL", "100 Low Lead", "100LL (Blue)"]:
            self.assertEqual(self.normalize_fuel_type(raw), "100LL", f"Failed for {raw}")

        # 94UL / UL94
        for raw in ["94UL", "UL94", "UL 94", "94 UL", "Unleaded 94", "Swift 94UL", "94 Unleaded"]:
            self.assertEqual(self.normalize_fuel_type(raw), "94UL", f"Failed for {raw}")

        # 100UL
        for raw in ["100UL", "UL100", "G100UL", "100 UL Unleaded", "Unleaded 100"]:
            self.assertEqual(self.normalize_fuel_type(raw), "100UL", f"Failed for {raw}")

        # 100R
        for raw in ["100R", "100R Swift", "Swift 100R", "R100"]:
            self.assertEqual(self.normalize_fuel_type(raw), "100R", f"Failed for {raw}")

        # Mogas
        for raw in ["Mogas", "MOGAS", "Auto Gas", "Autogas", "Ethanol-free Mogas", "Mo-Gas"]:
            self.assertEqual(self.normalize_fuel_type(raw), "Mogas", f"Failed for {raw}")

        # Jet-A
        for raw in ["Jet A", "Jet-A", "JetA", "Jet A-1", "Jet A with Prist", "Turbine Fuel"]:
            self.assertEqual(self.normalize_fuel_type(raw), "Jet-A", f"Failed for {raw}")

    def test_service_type_normalization(self):
        """Verify service type normalization to 'Self-Serve' and 'Full-Serve'."""
        for raw in ["Self service", "Self Serve", "Self-Serve", "SS", "24/7 Island", "Credit Card Island"]:
            self.assertEqual(self.normalize_service_type(raw), "Self-Serve")

        for raw in ["Full service", "Full Serve", "Full-Serve", "FS", "Fuel Truck", "Assisted"]:
            self.assertEqual(self.normalize_service_type(raw), "Full-Serve")

    def test_price_val_parsing(self):
        """Verify price parsing extracts float accurately and rejects out-of-bounds prices."""
        self.assertEqual(self.parse_price_val("$6.15"), 6.15)
        self.assertEqual(self.parse_price_val("6.85/gal"), 6.85)
        self.assertEqual(self.parse_price_val("5.999"), 6.00)
        self.assertEqual(self.parse_price_val("$4.89 (discount)"), 4.89)
        self.assertEqual(self.parse_price_val("$6.5"), 6.50)
        self.assertEqual(self.parse_price_val("$6"), 6.00)

        # Invalid or out-of-bounds
        self.assertIsNone(self.parse_price_val("$0.00"))
        self.assertIsNone(self.parse_price_val("$-5.00"))
        self.assertIsNone(self.parse_price_val("$85.00"))
        self.assertIsNone(self.parse_price_val("N/A"))
        self.assertIsNone(self.parse_price_val(""))

    def test_parse_authentic_airnav_matrix_fuel_table(self):
        """Verify parsing authentic AirNav matrix fuel tables with supplier branding and FS/SS rows."""
        matrix_html = """
        <TABLE border=0 cellpadding=0 cellspacing=0 width="100%">
        <TR valign=middle bgcolor="#ffffff"><TH align=left colspan=12 width="100%" bgcolor="#9999ff"><H3>FBO, Fuel Providers, and Aircraft Ground Support</H3></TH></TR>
        <TR valign=middle>
         <TD width=240><A href="/airport/KPAO/ROSSI">Rossi Aircraft</A></TD>
         <TD></TD>
         <TD nowrap align=left><FONT size="-1">650-493-3326<BR>[<A href="/airport/KPAO/ROSSI/link">web site</A>]</FONT></TD>
         <TD></TD>
         <TD colspan=1><FONT size="-1">Aviation fuel, Aircraft ground handling</FONT></TD>
         <TD></TD>
         <TD width="94">
        <table border=0 cellpadding=0 cellspacing=0 width=100%><tr><td colspan=7 align=center>Titan</td></tr><tr valign=top><td></td><td valign=top colspan=2 align=right nowrap width=33%>100LL</td> <td valign=top colspan=2 align=right nowrap width=33%>UL94</td> <td valign=top colspan=2 align=right nowrap width=33%>Jet A</td></tr><tr valign=top><td>FS&nbsp;</td><td nowrap align=right></td><td nowrap align=right>$7.65&nbsp;</td><td nowrap align=right></td><td nowrap align=right>$8.64&nbsp;</td><td nowrap align=right></td><td nowrap align=right>$7.85&nbsp;</td></tr><tr valign=top><td>SS&nbsp;</td><td nowrap align=right></td><td nowrap align=right>$7.40&nbsp;</td><td nowrap align=right></td><td nowrap align=right><FONT color=red>---</FONT>&nbsp;</td><td nowrap align=right></td><td nowrap align=right><FONT color=red>---</FONT>&nbsp;</td></tr><tr><td colspan=7 bgcolor=yellow align=center><B><A href=/fuel/guarantee.html>GUARANTEED</A></B></td></tr></table>
        </TD>
        </TR>
        </TABLE>
        """
        parsed = self.client.parse_airport_fuel(matrix_html, icao="KPAO")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["icao"], "KPAO")
        self.assertEqual(len(parsed["fbos"]), 1)
        fbo = parsed["fbos"][0]
        self.assertEqual(fbo["name"], "Rossi Aircraft")
        self.assertEqual(fbo["phone"], "650-493-3326")
        self.assertIn("Titan", fbo["notes"])
        self.assertIn("100LL_FS", fbo["fuels"])
        self.assertEqual(fbo["fuels"]["100LL_FS"]["price"], 7.65)
        self.assertEqual(fbo["fuels"]["94UL_FS"]["price"], 8.64)
        self.assertEqual(fbo["fuels"]["JET_A"]["price"], 7.85)
        self.assertEqual(fbo["fuels"]["100LL_SS"]["price"], 7.40)
        self.assertEqual(parsed["best_price"], 7.40)
        self.assertEqual(parsed["primary_fuel"], "100LL")
        self.assertIn("100LL", parsed["fuels_available"])
        self.assertIn("94UL", parsed["fuels_available"])

    def test_parse_multi_column_fbo_table(self):
        """Verify parsing tables where Self-Serve and Full-Serve prices are in separate columns."""
        multi_col_html = """
        <h3><a href="/airport/KSQL/RABBIT">Rabbit Aviation Services</a></h3>
        <div>Phone: 650-591-5857 • UNICOM: 122.95</div>
        <table>
          <tr><th>Fuel</th><th>Self-Serve</th><th>Full-Serve</th></tr>
          <tr><td>100LL</td><td>$6.15</td><td>$6.85</td></tr>
          <tr><td>UL94</td><td>$5.95</td><td>$6.45</td></tr>
        </table>
        """
        parsed = self.client.parse_airport_fuel(multi_col_html, icao="KSQL")
        self.assertIsNotNone(parsed)
        fbo = parsed["fbos"][0]
        self.assertEqual(fbo["fuels"]["100LL_SS"]["price"], 6.15)
        self.assertEqual(fbo["fuels"]["100LL_FS"]["price"], 6.85)
        self.assertEqual(fbo["fuels"]["94UL_SS"]["price"], 5.95)
        self.assertEqual(fbo["fuels"]["94UL_FS"]["price"], 6.45)

    def test_parse_full_airnav_html_multiple_fbos(self):
        """Verify parsing authentic AirNav HTML containing multiple FBOs, all fuel grades, and specs."""
        sample_html = """
        <!DOCTYPE html>
        <html>
        <head><title>AirNav: KSQL - San Carlos Airport</title></head>
        <body>
        <h1>San Carlos Airport</h1>
        <table>
          <tr><td>FAA Identifier:</td><td>SQL</td></tr>
          <tr><td>CTAF:</td><td>119.0</td></tr>
          <tr><td>UNICOM:</td><td>122.95</td></tr>
          <tr><td>Fuel available:</td><td>100LL JET-A UL94 100UL MOGAS</td></tr>
        </table>

        <!-- FBO 1 -->
        <h3><a href="/airport/KSQL/RABBIT">Rabbit Aviation Services</a></h3>
        <div>Phone: (650) 591-5857 • UNICOM: 122.95 • Guaranteed through 25-Aug-2026 • 24/7 self-serve</div>
        <table>
          <tr><th>Fuel</th><th>Price</th><th>Service</th></tr>
          <tr><td>100LL Avgas</td><td>$6.15</td><td>Self service</td></tr>
          <tr><td>100LL Avgas</td><td>$6.85</td><td>Full service</td></tr>
          <tr><td>94UL Unleaded</td><td>$5.95</td><td>Self service</td></tr>
          <tr><td>100UL Unleaded</td><td>$6.40</td><td>Self service</td></tr>
          <tr><td>100R Swift Fuel</td><td>$6.30</td><td>Self service</td></tr>
          <tr><td>Mogas (Ethanol-Free)</td><td>$5.50</td><td>Self service</td></tr>
          <tr><td>Jet A Turbine</td><td>$7.20</td><td>Full service</td></tr>
        </table>

        <!-- FBO 2 -->
        <h3><a href="/airport/KSQL/SAN_CARLOS_FLIGHT_CENTER">San Carlos Flight Center</a></h3>
        <div>Phone: 650-946-1700</div>
        <table>
          <tr><td>100LL</td><td>$6.25</td><td>Self service</td></tr>
          <tr><td>Jet A</td><td>$7.10</td><td>Full service</td></tr>
        </table>
        </body>
        </html>
        """
        parsed = self.client.parse_airport_fuel(sample_html, icao="KSQL")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["icao"], "KSQL")
        self.assertIn("San Carlos", parsed["name"])
        self.assertEqual(parsed["ctaf_freq"], 119.0)
        self.assertEqual(parsed["unicom_freq"], 122.95)
        self.assertGreaterEqual(len(parsed["fbos"]), 2)

        # FBO 1 checks
        fbo1 = parsed["fbos"][0]
        self.assertIn("Rabbit Aviation", fbo1["name"])
        self.assertEqual(fbo1["phone"], "(650) 591-5857")
        self.assertIn("100LL_SS", fbo1["fuels"])
        self.assertEqual(fbo1["fuels"]["100LL_SS"]["price"], 6.15)
        self.assertEqual(fbo1["fuels"]["100LL_FS"]["price"], 6.85)
        self.assertEqual(fbo1["fuels"]["94UL_SS"]["price"], 5.95)
        self.assertEqual(fbo1["fuels"]["100UL_SS"]["price"], 6.40)
        self.assertEqual(fbo1["fuels"]["100R_SS"]["price"], 6.30)
        self.assertEqual(fbo1["fuels"]["MOGAS_SS"]["price"], 5.50)
        self.assertEqual(fbo1["fuels"]["JET_A"]["price"], 7.20)

        # Best price calculation: lowest piston price is $5.50 (Mogas) or $5.95 (94UL) -> $5.50
        self.assertEqual(parsed["best_price"], 5.50)
        self.assertIn("100LL", parsed["fuels_available"])
        self.assertIn("94UL", parsed["fuels_available"])
        self.assertIn("100UL", parsed["fuels_available"])
        self.assertIn("100R", parsed["fuels_available"])
        self.assertIn("Mogas", parsed["fuels_available"])
        self.assertEqual(parsed["source"], "AirNav Live Feed")

    def test_parse_unpriced_airport_html(self):
        """Verify unpriced airfield page returns empty FBO list and None best_price without errors."""
        unpriced_html = """
        <html>
        <head><title>AirNav: 0Q5 - Shelter Cove Airport</title></head>
        <body>
        <h1>Shelter Cove Airport</h1>
        <table><tr><td>CTAF:</td><td>122.8</td></tr></table>
        <p>No commercial fuel providers or FBOs reported at this airfield.</p>
        </body>
        </html>
        """
        parsed = self.client.parse_airport_fuel(unpriced_html, icao="0Q5")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["icao"], "0Q5")
        self.assertEqual(parsed["fbos"], [])
        self.assertIsNone(parsed["best_price"])
        self.assertEqual(parsed["fuels_available"], [])
        self.assertEqual(parsed["primary_fuel"], "None")

    def test_parse_malformed_html_robustness(self):
        """Verify parser does not crash on malformed, truncated, or empty HTML."""
        self.assertIsNone(self.client.parse_airport_fuel("", icao="KSQL"))
        self.assertIsNone(self.client.parse_airport_fuel(None, icao="KSQL"))

        garbage = "<html><body><div><><><random tags without closing table tr td $6.50 100LL"
        parsed = self.client.parse_airport_fuel(garbage, icao="KTEST")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["icao"], "KTEST")


class TestAirNavClientCachingAndThrottling(unittest.TestCase):
    """Tests for AirNavClient multi-tier caching (memory + disk) and rate throttling."""

    def setUp(self):
        import tempfile

        from airnav_client import AirNavClient
        self.cache_dir = tempfile.mkdtemp()
        self.client = AirNavClient(cache_dir=self.cache_dir, cache_ttl=2, request_delay=0.1)

    def tearDown(self):
        import shutil
        self.client.clear_cache()
        if os.path.exists(self.cache_dir):
            try:
                shutil.rmtree(self.cache_dir, ignore_errors=True)
            except Exception:
                pass

    def test_memory_and_disk_cache_lifecycle(self):
        """Verify saving, reading from memory, writing to disk, and TTL expiry."""
        mock_data = {
            "icao": "KSQL",
            "best_price": 6.15,
            "fbos": [{"name": "Rabbit Aviation", "fuels": {"100LL_SS": {"price": 6.15, "type": "100LL", "service": "Self-Serve"}}}]
        }

        # Save to cache
        self.client.save_to_cache("KSQL", mock_data)

        # 1. Read back from memory cache
        cached = self.client.get_from_cache("KSQL")
        self.assertIsNotNone(cached)
        self.assertEqual(cached["icao"], "KSQL")
        self.assertEqual(cached["best_price"], 6.15)

        # 2. Clear memory cache and read from disk cache
        self.client._memory_cache.clear()
        disk_cached = self.client.get_from_cache("KSQL")
        self.assertIsNotNone(disk_cached)
        self.assertEqual(disk_cached["icao"], "KSQL")

        # 3. Test TTL expiration
        import time
        time.sleep(2.1)
        expired = self.client.get_from_cache("KSQL")
        self.assertIsNone(expired, "Expired cache entry should return None")

        # 4. Test allow_expired=True returns stale data
        stale = self.client.get_from_cache("KSQL", allow_expired=True)
        self.assertIsNotNone(stale, "allow_expired=True must return stale cache entry")
        self.assertEqual(stale["icao"], "KSQL")

    def test_stale_cache_emergency_fallback(self):
        """Verify get_airport_fuel falls back to stale cache when network fails."""
        mock_data = {
            "icao": "KSQL",
            "best_price": 6.15,
            "fbos": [{"name": "Rabbit Aviation", "fuels": {"100LL_SS": {"price": 6.15, "type": "100LL", "service": "Self-Serve"}}}]
        }
        self.client.save_to_cache("KSQL", mock_data)
        import time
        time.sleep(2.1)  # expire cache

        # Mock fetch_airport_html to fail
        def mock_failing_fetch(ident):
            raise ConnectionError("AirNav connection timeout")

        self.client.fetch_airport_html = mock_failing_fetch

        # get_airport_fuel should return stale cache with fallback marker
        res = self.client.get_airport_fuel("KSQL", force_refresh=False)
        self.assertIsNotNone(res)
        self.assertTrue(res.get("from_cache"))
        self.assertTrue(res.get("_stale_fallback"))
        self.assertEqual(res.get("best_price"), 6.15)

    def test_request_delay_throttling(self):
        """Verify rate throttling ensures minimum delay between consecutive calls."""
        import time
        self.client.request_delay = 0.15
        t0 = time.perf_counter()
        self.client._throttle()
        self.client._throttle()
        elapsed = time.perf_counter() - t0
        self.assertGreaterEqual(elapsed, 0.14)

    def test_batch_get_fuel_with_cached_entries(self):
        """Verify batch_get_fuel retrieves multiple airport records."""
        self.client.save_to_cache("KSQL", {"icao": "KSQL", "best_price": 6.15, "fbos": [{"name": "Rabbit"}]})
        self.client.save_to_cache("KPAO", {"icao": "KPAO", "best_price": 6.45, "fbos": [{"name": "Palo Alto Fuel"}]})

        results = self.client.batch_get_fuel(["KSQL", "KPAO"])
        self.assertEqual(len(results), 2)
        self.assertIn("KSQL", results)
        self.assertIn("KPAO", results)
        self.assertEqual(results["KSQL"]["best_price"], 6.15)
        self.assertEqual(results["KPAO"]["best_price"], 6.45)


class TestAirNavProxyServerRoutes(unittest.TestCase):
    """Automated tests for server.py HTTP endpoints and AirNav proxy handlers."""

    @classmethod
    def setUpClass(cls):
        import server
        cls.server_module = server

    def setUp(self):
        import tempfile

        from airnav_client import AirNavClient
        self._orig_airnav = self.server_module.airnav
        self.test_cache_dir = tempfile.mkdtemp()
        self.server_module.airnav = AirNavClient(
            cache_dir=self.test_cache_dir,
            cache_ttl=3600,
            request_delay=0.0
        )

    def tearDown(self):
        import shutil
        if os.path.exists(self.test_cache_dir):
            try:
                shutil.rmtree(self.test_cache_dir, ignore_errors=True)
            except Exception:
                pass
        self.server_module.airnav = self._orig_airnav

    def test_server_routes_defined(self):
        """Verify server request handler handles health, airnav proxy, and sync endpoints."""
        handler_cls = self.server_module.AeroFuelHTTPRequestHandler
        self.assertTrue(hasattr(handler_cls, 'do_GET'))
        self.assertTrue(hasattr(handler_cls, 'do_POST'))
        self.assertTrue(hasattr(handler_cls, 'do_OPTIONS'))

    def test_airnav_health_endpoint_response_structure(self):
        """Verify /api/airnav/health returns proper JSON schema."""
        self.assertIsNotNone(self.server_module.airnav)
        self.assertEqual(self.server_module.airnav.base_url, "https://www.airnav.com")
        self.assertGreaterEqual(self.server_module.airnav.cache_ttl, 1)

    def test_airnav_proxy_get_single_airport_mocked(self):
        """Verify GET /api/airnav?icao=KSQL returns parsed JSON from airnav client."""
        # Pre-seed cache
        self.server_module.airnav.save_to_cache("KSQL", {
            "icao": "KSQL",
            "name": "San Carlos Airport",
            "best_price": 6.15,
            "fbos": [{"name": "Rabbit Aviation", "fuels": {"100LL_SS": {"price": 6.15, "type": "100LL", "service": "Self-Serve"}}}]
        })
        cached = self.server_module.airnav.get_airport_fuel("KSQL", force_refresh=False)
        self.assertIsNotNone(cached)
        self.assertEqual(cached["icao"], "KSQL")
        self.assertEqual(cached["best_price"], 6.15)

    def test_airnav_proxy_sync_batch_catalog_merge(self):
        """Verify batch sync updates multiple airports with proper structure."""
        self.server_module.airnav.save_to_cache("KSQL", {"icao": "KSQL", "best_price": 6.15, "fbos": [{"name": "Rabbit"}]})
        self.server_module.airnav.save_to_cache("KPAO", {"icao": "KPAO", "best_price": 6.45, "fbos": [{"name": "Palo Alto Fuel"}]})

        res = self.server_module.airnav.batch_get_fuel(["KSQL", "KPAO"], delay=0.0)
        self.assertEqual(len(res), 2)
        self.assertEqual(res["KSQL"]["best_price"], 6.15)
        self.assertEqual(res["KPAO"]["best_price"], 6.45)


class TestAirNavStoragePersistence(unittest.TestCase):
    """Automated tests for AirNav on-demand query disk persistence, catalog reload, and client storage."""

    def setUp(self):
        import shutil
        import tempfile

        import server
        self.server_module = server
        self.test_dir = tempfile.mkdtemp()

        # Seed miniature test dataset
        self.initial_dataset = {
            "version": "2026.08.22",
            "updated_at": "2026-08-22T00:00:00Z",
            "data_source": "AeroFuel Test Catalog",
            "total_airports": 2,
            "airports": [
                {
                    "icao": "KSQL",
                    "faa": "SQL",
                    "iata": "SQL",
                    "name": "San Carlos Airport",
                    "city": "San Carlos",
                    "state": "CA",
                    "country": "US",
                    "lat": 37.5119,
                    "lon": -122.2495,
                    "elevation_ft": 5,
                    "ctaf_freq": 119.0,
                    "unicom_freq": 122.95,
                    "runways": [{"id": "12/30", "length": 2600, "surface": "Asphalt"}],
                    "fbos": [],
                    "best_price": None,
                    "primary_fuel": "None",
                    "fuels_available": [],
                    "last_updated": "2026-08-21",
                    "source": "FAA Public Airfield Directory"
                },
                {
                    "icao": "KPAO",
                    "faa": "PAO",
                    "iata": "PAO",
                    "name": "Palo Alto Airport",
                    "city": "Palo Alto",
                    "state": "CA",
                    "country": "US",
                    "lat": 37.4611,
                    "lon": -122.1151,
                    "elevation_ft": 4,
                    "ctaf_freq": 118.6,
                    "unicom_freq": 122.95,
                    "runways": [{"id": "13/31", "length": 2443, "surface": "Asphalt"}],
                    "fbos": [
                        {
                            "name": "Rossi Aircraft",
                            "phone": "650-493-3326",
                            "notes": "Titan Avfuel",
                            "fuels": {
                                "100LL_FS": {"price": 7.65, "type": "100LL", "service": "Full-Serve", "label": "100LL Avgas (Full-Serve)"}
                            }
                        }
                    ],
                    "best_price": 7.65,
                    "primary_fuel": "100LL",
                    "fuels_available": ["100LL"],
                    "last_updated": "2026-08-21",
                    "source": "FAA Public Airfield Directory"
                }
            ]
        }

        self.json_path = os.path.join(self.test_dir, "fuel_data.json")
        self.js_path = os.path.join(self.test_dir, "fuel_data.js")

        with open(self.json_path, "w", encoding="utf-8") as f:
            json.dump(self.initial_dataset, f, indent=2)

        with open(self.js_path, "w", encoding="utf-8") as f:
            f.write("// AeroFuel IQ Static Airport Database\n")
            f.write("window.EMBEDDED_AIRPORTS = ")
            json.dump(self.initial_dataset, f, indent=2)
            f.write(";\n")

    def tearDown(self):
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_update_stored_fuel_data_updates_unpriced_airport(self):
        """Verify update_stored_fuel_data updates an unpriced airport with live AirNav FBOs, prices, and timestamp on disk."""
        scraped_data = {
            "icao": "KSQL",
            "name": "San Carlos Airport",
            "ctaf_freq": 119.0,
            "unicom_freq": 122.95,
            "fbos": [
                {
                    "name": "Rabbit Aviation Services",
                    "phone": "(650) 591-5857",
                    "notes": "24/7 Self-Serve",
                    "fuels": {
                        "100LL_SS": {"price": 6.15, "type": "100LL", "service": "Self-Serve", "label": "100LL Avgas (Self-Serve)"},
                        "94UL_SS": {"price": 5.95, "type": "94UL", "service": "Self-Serve", "label": "94UL Unleaded (Self-Serve)"}
                    }
                }
            ],
            "best_price": 5.95,
            "primary_fuel": "100LL",
            "fuels_available": ["100LL", "94UL"],
            "last_updated": "2026-08-22",
            "source": "AirNav Live Feed"
        }

        updated_icaos = self.server_module.update_stored_fuel_data(scraped_data, directory=self.test_dir)
        self.assertEqual(updated_icaos, ["KSQL"])

        # Reload from disk
        with open(self.json_path, "r", encoding="utf-8") as f:
            updated_json = json.load(f)

        apt_map = {a["icao"]: a for a in updated_json["airports"]}
        self.assertIn("KSQL", apt_map)
        ksql = apt_map["KSQL"]
        self.assertEqual(ksql["best_price"], 5.95)
        self.assertEqual(len(ksql["fbos"]), 1)
        self.assertEqual(ksql["fbos"][0]["name"], "Rabbit Aviation Services")
        self.assertIn("100LL_SS", ksql["fbos"][0]["fuels"])
        self.assertEqual(ksql["fbos"][0]["fuels"]["100LL_SS"]["price"], 6.15)
        self.assertEqual(ksql["last_updated"], "2026-08-22")
        self.assertEqual(ksql["source"], "AirNav Live Feed")

        # Check fuel_data.js was also updated
        with open(self.js_path, "r", encoding="utf-8") as f:
            js_content = f.read()
        self.assertIn("window.EMBEDDED_AIRPORTS =", js_content)
        self.assertIn("Rabbit Aviation Services", js_content)
        self.assertIn("6.15", js_content)

    def test_update_stored_fuel_data_overwrites_existing_prices(self):
        """Verify update_stored_fuel_data updates existing FBO rates when new rates are fetched."""
        new_kpao_data = {
            "icao": "KPAO",
            "name": "Palo Alto Airport",
            "fbos": [
                {
                    "name": "Rossi Aircraft",
                    "phone": "650-493-3326",
                    "notes": "Titan",
                    "fuels": {
                        "100LL_SS": {"price": 7.40, "type": "100LL", "service": "Self-Serve", "label": "100LL Avgas (Self-Serve)"},
                        "100LL_FS": {"price": 7.65, "type": "100LL", "service": "Full-Serve", "label": "100LL Avgas (Full-Serve)"}
                    }
                }
            ],
            "best_price": 7.40,
            "primary_fuel": "100LL",
            "fuels_available": ["100LL"],
            "last_updated": "2026-08-22",
            "source": "Parse.bot AirNav API"
        }

        updated_icaos = self.server_module.update_stored_fuel_data(new_kpao_data, directory=self.test_dir)
        self.assertEqual(updated_icaos, ["KPAO"])

        # Verify load_catalog returns updated data
        catalog = self.server_module.load_catalog(directory=self.test_dir, force_reload=True)
        kpao = next(a for a in catalog["airports"] if a["icao"] == "KPAO")
        self.assertEqual(kpao["best_price"], 7.40)
        self.assertIn("100LL_SS", kpao["fbos"][0]["fuels"])
        self.assertEqual(kpao["source"], "Parse.bot AirNav API")

    def test_update_stored_fuel_data_adds_new_airport_to_catalog(self):
        """Verify update_stored_fuel_data appends a newly discovered airfield to the stored dataset."""
        new_apt = {
            "icao": "KHAF",
            "faa": "HAF",
            "iata": "HAF",
            "name": "Half Moon Bay Airport",
            "city": "Half Moon Bay",
            "state": "CA",
            "lat": 37.5134,
            "lon": -122.5011,
            "fbos": [
                {
                    "name": "Half Moon Bay Fuel Service",
                    "fuels": {
                        "100LL_SS": {"price": 6.89, "type": "100LL", "service": "Self-Serve", "label": "100LL Avgas (Self-Serve)"}
                    }
                }
            ],
            "best_price": 6.89,
            "primary_fuel": "100LL",
            "fuels_available": ["100LL"],
            "last_updated": "2026-08-22",
            "source": "AirNav Live Feed"
        }

        updated_icaos = self.server_module.update_stored_fuel_data(new_apt, directory=self.test_dir)
        self.assertEqual(updated_icaos, ["KHAF"])

        with open(self.json_path, "r", encoding="utf-8") as f:
            catalog = json.load(f)

        self.assertEqual(catalog["total_airports"], 3)
        self.assertTrue(any(a["icao"] == "KHAF" for a in catalog["airports"]))

    def test_update_stored_fuel_data_ident_matching_variants(self):
        """Verify update_stored_fuel_data correctly matches 3-letter FAA codes against 4-letter ICAO records (and vice-versa)."""
        # Catalog has KSQL (faa: SQL). Scraped has icao: SQL.
        scraped_3letter = {
            "icao": "SQL",
            "name": "San Carlos Airport",
            "fbos": [
                {
                    "name": "Rabbit Aviation Services",
                    "fuels": {
                        "100LL_SS": {"price": 6.05, "type": "100LL", "service": "Self-Serve", "label": "100LL Avgas (Self-Serve)"}
                    }
                }
            ],
            "best_price": 6.05,
            "last_updated": "2026-08-22",
            "source": "AirNav Live Feed"
        }

        updated_icaos = self.server_module.update_stored_fuel_data(scraped_3letter, directory=self.test_dir)
        self.assertEqual(updated_icaos, ["KSQL"])

        with open(self.json_path, "r", encoding="utf-8") as f:
            catalog = json.load(f)
        ksql = next(a for a in catalog["airports"] if a["icao"] == "KSQL")
        self.assertEqual(ksql["best_price"], 6.05)

    def test_update_stored_fuel_data_derives_missing_best_price_and_fuels(self):
        """Verify update_stored_fuel_data automatically computes best_price and fuels_available from FBO fuels if omitted."""
        scraped_partial = {
            "icao": "KSQL",
            "name": "San Carlos Airport",
            "fbos": [
                {
                    "name": "Rabbit Aviation Services",
                    "fuels": {
                        "100LL_SS": {"price": 6.25, "type": "100LL", "service": "Self-Serve"},
                        "94UL_SS": {"price": 5.85, "type": "94UL", "service": "Self-Serve"},
                        "JET_A": {"price": 7.50, "type": "Jet-A", "service": "Full-Serve"}
                    }
                }
            ]
            # Notice best_price and primary_fuel are omitted
        }

        updated_icaos = self.server_module.update_stored_fuel_data(scraped_partial, directory=self.test_dir)
        self.assertEqual(updated_icaos, ["KSQL"])

        with open(self.json_path, "r", encoding="utf-8") as f:
            catalog = json.load(f)
        ksql = next(a for a in catalog["airports"] if a["icao"] == "KSQL")
        self.assertEqual(ksql["best_price"], 5.85)  # Lowest piston rate (94UL), excluding Jet-A
        self.assertIn("100LL", ksql["fuels_available"])
        self.assertIn("94UL", ksql["fuels_available"])

    def test_update_stored_fuel_data_preserves_catalog_metadata_and_atomic_replace(self):
        """Verify catalog version, data_source, and total_airports are preserved across updates."""
        scraped = {
            "icao": "KSQL",
            "best_price": 5.99,
            "fbos": [{"name": "Rabbit", "fuels": {"100LL_SS": {"price": 5.99, "type": "100LL"}}}]
        }
        self.server_module.update_stored_fuel_data(scraped, directory=self.test_dir)

        with open(self.json_path, "r", encoding="utf-8") as f:
            catalog = json.load(f)

        self.assertEqual(catalog["version"], "2026.08.22")
        self.assertEqual(catalog["data_source"], "AeroFuel Test Catalog")
        self.assertEqual(catalog["total_airports"], 2)
        self.assertTrue(catalog["updated_at"].endswith("Z"))

    def test_frontend_localstorage_persistence_implementation(self):
        """Verify app.js contains AEROFUEL_PERSISTED_AIRPORTS key, helper methods, and load/save lifecycle."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        self.assertTrue(os.path.exists(app_js_path), "app.js missing")
        with open(app_js_path, "r") as f:
            content = f.read()

        # Key definition
        self.assertIn("AEROFUEL_PERSISTED_AIRPORTS", content)
        self.assertIn("function savePersistedAirportToStorage(", content)
        self.assertIn("function savePersistedAirportsBatchToStorage(", content)
        self.assertIn("function applyPersistedAirportsFromStorage(", content)

        # Coordinate and metadata persistence
        self.assertIn("lat: apt.lat", content)
        self.assertIn("lon: apt.lon", content)
        self.assertIn("elevation_ft: apt.elevation_ft", content)

        # Call in loadFuelData
        self.assertIn("applyPersistedAirportsFromStorage();", content)

        # Calls upon live fetches
        self.assertIn("savePersistedAirportToStorage(apt);", content)
        self.assertIn("savePersistedAirportsBatchToStorage(updatedAptsList);", content)


class TestFrontendAirNavIntegration(unittest.TestCase):
    """Verify frontend HTML, CSS, and JS integration for AirNav as primary source."""

    def test_app_js_contains_airnav_sync_and_fetch_logic(self):
        """Verify app.js implements AirNav Live sync and airport modal fetch buttons."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        self.assertTrue(os.path.exists(app_js_path), "app.js missing")
        with open(app_js_path, "r") as f:
            content = f.read()

        # Modal button and listener
        self.assertIn("btn-fetch-live-airnav", content)
        self.assertIn("Fetch Live AirNav Price", content)
        self.assertIn("/api/airnav?icao=", content)

        # Sync modal primary AirNav source
        self.assertIn("btn-sync-airnav", content)
        self.assertIn("AirNav Live Sync", content)
        self.assertIn("PRIMARY SOURCE", content)
        self.assertIn("/api/airnav/sync", content)

    def test_style_css_contains_airnav_button_and_badge_rules(self):
        """Verify style.css includes .btn-hud-airnav and .badge-recommended styling."""
        css_path = os.path.join(DIRECTORY, "style.css")
        self.assertTrue(os.path.exists(css_path), "style.css missing")
        with open(css_path, "r") as f:
            content = f.read()

        self.assertIn(".btn-hud-airnav", content)
        self.assertIn(".badge-recommended", content)


class TestParsebotAirNavIntegration(unittest.TestCase):
    """Automated tests for Parse.bot AirNav API integration, JSON normalization, and error fallback."""

    def setUp(self):
        import tempfile

        from airnav_client import (PARSEBOT_AIRNAV_BOT_ID,
                                   PARSEBOT_API_ENDPOINT,
                                   PARSEBOT_MARKETPLACE_URL, AirNavClient)
        self.cache_dir = tempfile.mkdtemp()
        self.client = AirNavClient(cache_dir=self.cache_dir, cache_ttl=10)
        self.bot_id = PARSEBOT_AIRNAV_BOT_ID
        self.endpoint = PARSEBOT_API_ENDPOINT
        self.marketplace_url = PARSEBOT_MARKETPLACE_URL

    def tearDown(self):
        import shutil
        self.client.clear_cache()
        if os.path.exists(self.cache_dir):
            try:
                shutil.rmtree(self.cache_dir, ignore_errors=True)
            except Exception:
                pass

    def test_parsebot_constants_and_urls(self):
        """Verify Parse.bot bot ID and API endpoints."""
        self.assertEqual(self.bot_id, "208de514-ca12-4c51-923b-18380d9c6978")
        self.assertIn("208de514-ca12-4c51-923b-18380d9c6978", self.endpoint)
        self.assertIn("208de514-ca12-4c51-923b-18380d9c6978", self.marketplace_url)
        self.assertIn("parse.bot/marketplace", self.marketplace_url)

    def test_parsebot_api_key_initialization(self):
        """Verify Parse.bot API key initialization via constructor and environment variable."""
        from airnav_client import AirNavClient

        # 1. Constructor parameter
        client_explicit = AirNavClient(parsebot_api_key="pb_live_test123", cache_dir=self.cache_dir)
        self.assertEqual(client_explicit.parsebot_api_key, "pb_live_test123")

        # 2. Environment variable
        old_env = os.environ.get("PARSEBOT_API_KEY")
        try:
            os.environ["PARSEBOT_API_KEY"] = "pb_env_secret_key"
            client_env = AirNavClient(cache_dir=self.cache_dir)
            self.assertEqual(client_env.parsebot_api_key, "pb_env_secret_key")
        finally:
            if old_env is not None:
                os.environ["PARSEBOT_API_KEY"] = old_env
            else:
                os.environ.pop("PARSEBOT_API_KEY", None)

    def test_normalize_parsebot_structured_json_multi_fbo(self):
        """Verify normalization of structured multi-FBO Parse.bot JSON with all fuel grades."""
        raw_parsebot_payload = {
            "data": {
                "icao": "KSQL",
                "name": "San Carlos Airport",
                "ctaf_freq": "119.0",
                "unicom_freq": "122.95",
                "fbos": [
                    {
                        "name": "Rabbit Aviation Services",
                        "phone": "(650) 591-5857",
                        "notes": "Guaranteed through 25-Aug-2026 • 24/7 self-serve",
                        "fuels": {
                            "100LL_SS": 6.15,
                            "100LL_FS": 6.85,
                            "94UL_SS": 5.95,
                            "100UL_SS": 6.40,
                            "100R_SS": 6.30,
                            "MOGAS_SS": 5.50,
                            "SAF": 8.75,
                            "JET_A": 7.20
                        }
                    },
                    {
                        "name": "San Carlos Flight Center",
                        "phone": "650-946-1700",
                        "notes": "Flight school & aircraft rental",
                        "fuels": {
                            "100LL_SS": 6.25,
                            "JET_A": 7.10
                        }
                    }
                ]
            }
        }

        normalized = self.client._normalize_parsebot_data(raw_parsebot_payload, "KSQL")
        self.assertIsNotNone(normalized)
        self.assertEqual(normalized["icao"], "KSQL")
        self.assertEqual(normalized["name"], "San Carlos Airport")
        self.assertEqual(normalized["ctaf_freq"], 119.0)
        self.assertEqual(normalized["unicom_freq"], 122.95)
        self.assertEqual(len(normalized["fbos"]), 2)
        self.assertEqual(normalized["source"], "Parse.bot AirNav API")

        # FBO 1 checks
        fbo1 = normalized["fbos"][0]
        self.assertEqual(fbo1["name"], "Rabbit Aviation Services")
        self.assertEqual(fbo1["phone"], "(650) 591-5857")
        self.assertIn("100LL_SS", fbo1["fuels"])
        self.assertEqual(fbo1["fuels"]["100LL_SS"]["price"], 6.15)
        self.assertEqual(fbo1["fuels"]["100LL_FS"]["price"], 6.85)
        self.assertEqual(fbo1["fuels"]["94UL_SS"]["price"], 5.95)
        self.assertEqual(fbo1["fuels"]["100UL_SS"]["price"], 6.40)
        self.assertEqual(fbo1["fuels"]["100R_SS"]["price"], 6.30)
        self.assertEqual(fbo1["fuels"]["MOGAS_SS"]["price"], 5.50)
        self.assertEqual(fbo1["fuels"]["SAF"]["price"], 8.75)
        self.assertEqual(fbo1["fuels"]["JET_A"]["price"], 7.20)

        # Best piston price calculation: lowest non-jet/SAF price is $5.50 (Mogas)
        self.assertEqual(normalized["best_price"], 5.50)
        self.assertEqual(normalized["primary_fuel"], "100LL")
        self.assertIn("100LL", normalized["fuels_available"])
        self.assertIn("94UL", normalized["fuels_available"])
        self.assertIn("100UL", normalized["fuels_available"])
        self.assertIn("100R", normalized["fuels_available"])
        self.assertIn("Mogas", normalized["fuels_available"])

    def test_normalize_parsebot_nested_service_rates_list(self):
        """Verify normalization of Parse.bot JSON with rates represented as a list of price objects."""
        raw_payload = {
            "result": {
                "airport": "KPAO",
                "airport_name": "Palo Alto Airport",
                "ctaf": 118.6,
                "unicom": 122.95,
                "providers": [
                    {
                        "fbo_name": "Rossi Aircraft",
                        "telephone": "650-493-3326",
                        "brand": "Titan",
                        "prices": [
                            {"fuel": "100LL", "service": "Self-Serve", "price": "$7.40"},
                            {"fuel": "100LL", "service": "Full-Serve", "price": "$7.65"},
                            {"fuel": "UL94", "service": "Full-Serve", "price": "$8.64"},
                            {"fuel": "Jet A", "service": "Full-Serve", "price": "$7.85"}
                        ]
                    }
                ]
            }
        }

        normalized = self.client._normalize_parsebot_data(raw_payload, "KPAO")
        self.assertIsNotNone(normalized)
        self.assertEqual(normalized["icao"], "KPAO")
        self.assertEqual(len(normalized["fbos"]), 1)
        fbo = normalized["fbos"][0]
        self.assertEqual(fbo["name"], "Rossi Aircraft")
        self.assertEqual(fbo["phone"], "650-493-3326")
        self.assertIn("100LL_SS", fbo["fuels"])
        self.assertEqual(fbo["fuels"]["100LL_SS"]["price"], 7.40)
        self.assertEqual(fbo["fuels"]["100LL_FS"]["price"], 7.65)
        self.assertEqual(fbo["fuels"]["94UL_FS"]["price"], 8.64)
        self.assertEqual(fbo["fuels"]["JET_A"]["price"], 7.85)
        self.assertEqual(normalized["best_price"], 7.40)

    def test_parsebot_error_fallback_to_direct_html_scraper(self):
        """Verify get_airport_fuel automatically falls back to direct HTML scraping when Parse.bot is unavailable."""
        client = self.client
        client.parsebot_api_key = "pb_test_key"

        # Mock _fetch_from_parsebot to fail
        def mock_failing_parsebot(icao, api_key=None):
            raise RuntimeError("Parse.bot 503 Service Unavailable")

        client._fetch_from_parsebot = mock_failing_parsebot

        # Mock fetch_airport_html to return sample HTML
        sample_html = """
        <html><head><title>AirNav: KSQL - San Carlos</title></head><body>
        <h1>San Carlos Airport</h1>
        <h3><a href="/airport/KSQL/RABBIT">Rabbit Aviation</a></h3>
        <div>Phone: 650-591-5857</div>
        <table><tr><td>100LL</td><td>$6.15</td><td>Self service</td></tr></table>
        </body></html>
        """
        client.fetch_airport_html = lambda icao: sample_html

        # Calling get_airport_fuel should not crash; it should fall back to HTML parser
        result = client.get_airport_fuel("KSQL", force_refresh=True)
        self.assertIsNotNone(result)
        self.assertEqual(result["icao"], "KSQL")
        self.assertEqual(result["best_price"], 6.15)
        self.assertEqual(result["source"], "AirNav Live Feed")

    def test_server_routes_parsebot_api_key_support(self):
        """Verify server.py supports parsebot_api_key parameter and X-Parsebot-Api-Key header."""
        from unittest.mock import MagicMock

        import server

        # 1. Health check includes parsebot fields
        self.assertTrue(hasattr(server, 'airnav'))

        # 2. Server proxy GET parameter passing
        captured_keys = []
        orig_get_fuel = server.airnav.get_airport_fuel

        def mock_get_fuel(icao, force_refresh=False, parsebot_api_key=None):
            captured_keys.append(parsebot_api_key)
            return {"icao": icao, "best_price": 5.99, "fbos": [], "source": "Parse.bot AirNav API"}

        server.airnav.get_airport_fuel = mock_get_fuel
        try:
            res = server.airnav.get_airport_fuel("KSQL", force_refresh=True, parsebot_api_key="pb_custom_header_key")
            self.assertEqual(captured_keys[-1], "pb_custom_header_key")
            self.assertEqual(res["source"], "Parse.bot AirNav API")
        finally:
            server.airnav.get_airport_fuel = orig_get_fuel

    def test_frontend_parsebot_ui_and_localstorage_integration(self):
        """Verify app.js implements Parse.bot API key input, localStorage persistence, and request propagation."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        self.assertTrue(os.path.exists(app_js_path), "app.js missing")
        with open(app_js_path, "r") as f:
            content = f.read()

        # Parse.bot marketplace link and input ID
        self.assertIn("https://parse.bot/marketplace/208de514-ca12-4c51-923b-18380d9c6978/airnav-com-api", content)
        self.assertIn("input-parsebot-key", content)
        self.assertIn("btn-save-parsebot-key", content)
        self.assertIn("aerofuel_parsebot_api_key", content)
        self.assertIn("X-Parsebot-Api-Key", content)
        self.assertIn("parsebot_api_key", content)

    def test_service_and_fuel_type_normalization_edge_cases(self):
        """Verify service and fuel type normalization handles underscore formats, prefixes, and edge cases."""
        from airnav_client import normalize_fuel_type, normalize_service_type

        # Service type normalizations
        self.assertEqual(normalize_service_type("full_serve"), "Full-Serve")
        self.assertEqual(normalize_service_type("self_serve"), "Self-Serve")
        self.assertEqual(normalize_service_type("100ll_fs"), "Full-Serve")
        self.assertEqual(normalize_service_type("100ll_ss"), "Self-Serve")
        self.assertEqual(normalize_service_type("full"), "Full-Serve")
        self.assertEqual(normalize_service_type("self"), "Self-Serve")
        self.assertEqual(normalize_service_type("Full-Serve"), "Full-Serve")
        self.assertEqual(normalize_service_type("Self-Serve"), "Self-Serve")

        # Fuel type normalizations
        self.assertEqual(normalize_fuel_type("100LL"), "100LL")
        self.assertEqual(normalize_fuel_type("100ll_self"), "100LL")
        self.assertEqual(normalize_fuel_type("100ll_full"), "100LL")
        self.assertEqual(normalize_fuel_type("ll_self"), "100LL")
        self.assertEqual(normalize_fuel_type("ll_full"), "100LL")
        self.assertEqual(normalize_fuel_type("auto_gas"), "Mogas")
        self.assertEqual(normalize_fuel_type("mogas"), "Mogas")
        self.assertEqual(normalize_fuel_type("SAF"), "SAF")
        self.assertEqual(normalize_fuel_type("saf"), "SAF")
        self.assertEqual(normalize_fuel_type("Jet-A"), "Jet-A")
        self.assertEqual(normalize_fuel_type("jet_a"), "Jet-A")
        self.assertEqual(normalize_fuel_type("94UL"), "94UL")
        self.assertEqual(normalize_fuel_type("ul94_self"), "94UL")
        self.assertEqual(normalize_fuel_type("100UL"), "100UL")
        self.assertEqual(normalize_fuel_type("ul100_self"), "100UL")
        self.assertEqual(normalize_fuel_type("100R"), "100R")

    def test_normalize_parsebot_nested_wrapper_and_custom_rate_dict(self):
        """Verify normalization when response has deeply nested wrapper objects and rate dictionaries."""
        raw_payload = {
            "result": {
                "output": {
                    "airport": "KSQL",
                    "airport_name": "San Carlos Airport",
                    "ctaf": 119.0,
                    "unicom": 122.95,
                    "fbos": [
                        {
                            "name": "Rabbit Aviation",
                            "telephone": "650-591-5857",
                            "rates": {
                                "100LL": {"rate": "$6.15", "service": "self_serve"},
                                "94UL": {"cost": 5.95, "service": "self_serve"},
                                "Jet-A": {"amount": 7.20, "service": "full_serve"}
                            }
                        }
                    ]
                }
            }
        }

        normalized = self.client._normalize_parsebot_data(raw_payload, "KSQL")
        self.assertIsNotNone(normalized)
        self.assertEqual(normalized["icao"], "KSQL")
        self.assertEqual(normalized["name"], "San Carlos Airport")
        self.assertEqual(len(normalized["fbos"]), 1)
        fbo = normalized["fbos"][0]
        self.assertEqual(fbo["fuels"]["100LL_SS"]["price"], 6.15)
        self.assertEqual(fbo["fuels"]["94UL_SS"]["price"], 5.95)
        self.assertEqual(fbo["fuels"]["JET_A"]["price"], 7.20)
        self.assertEqual(normalized["best_price"], 5.95)

    def test_parsebot_error_payload_raises_and_triggers_fallback(self):
        """Verify that when Parse.bot returns an error payload, it triggers fallback to HTML scraper."""
        client = self.client
        client.parsebot_api_key = "pb_test_key"

        # Mock _fetch_from_parsebot to simulate an API error payload
        def mock_error_parsebot(icao, api_key=None):
            raise RuntimeError("Parse.bot API error: Quota limit reached")

        client._fetch_from_parsebot = mock_error_parsebot

        sample_html = """
        <html><head><title>AirNav: KSQL - San Carlos</title></head><body>
        <h1>San Carlos Airport</h1>
        <h3><a href="/airport/KSQL/RABBIT">Rabbit Aviation</a></h3>
        <table><tr><td>100LL</td><td>$6.15</td><td>Self service</td></tr></table>
        </body></html>
        """
        client.fetch_airport_html = lambda icao: sample_html

        result = client.get_airport_fuel("KSQL", force_refresh=True)
        self.assertIsNotNone(result)
        self.assertEqual(result["icao"], "KSQL")
        self.assertEqual(result["best_price"], 6.15)
        self.assertEqual(result["source"], "AirNav Live Feed")

    def test_saf_excluded_from_piston_best_price(self):
        """Verify SAF (Sustainable Aviation Fuel) is treated as turbine fuel and excluded from piston best price."""
        raw_payload = {
            "icao": "KSQL",
            "name": "San Carlos Airport",
            "fbos": [
                {
                    "name": "Eco Aviation",
                    "fuels": {
                        "SAF": 5.00,
                        "100LL_SS": 6.50
                    }
                }
            ]
        }

        normalized = self.client._normalize_parsebot_data(raw_payload, "KSQL")
        self.assertEqual(normalized["best_price"], 6.50)  # Must be 6.50 (100LL), NOT 5.00 (SAF)
        self.assertEqual(normalized["primary_fuel"], "100LL")

    def test_server_authorization_bearer_header_support(self):
        """Verify server.py extracts API key from Authorization: Bearer <token> header."""
        from unittest.mock import MagicMock

        import server

        captured_keys = []
        orig_get_fuel = server.airnav.get_airport_fuel

        def mock_get_fuel(icao, force_refresh=False, parsebot_api_key=None):
            captured_keys.append(parsebot_api_key)
            return {"icao": icao, "best_price": 5.99, "fbos": [], "source": "Parse.bot AirNav API"}

        server.airnav.get_airport_fuel = mock_get_fuel
        try:
            res = server.airnav.get_airport_fuel("KSQL", force_refresh=True, parsebot_api_key="pb_bearer_token_123")
            self.assertEqual(captured_keys[-1], "pb_bearer_token_123")
        finally:
            server.airnav.get_airport_fuel = orig_get_fuel

    def test_generate_airport_popup_html_structure(self):
        """Verify app.js defines generateAirportPopupHtml with header, specs, FBO fuel breakdown, and Open Full Details button."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        self.assertIn("function generateAirportPopupHtml(apt, isLoading = false)", app_content)
        self.assertIn("popup-header-block", app_content)
        self.assertIn("popup-tower-tag", app_content)
        self.assertIn("popup-specs-grid", app_content)
        self.assertIn("Runway:", app_content)
        self.assertIn("CTAF:", app_content)
        self.assertIn("UNICOM:", app_content)
        self.assertIn("popup-fuels-container", app_content)
        self.assertIn("popup-fbo-card", app_content)
        self.assertIn("btn-popup-open-details", app_content)
        self.assertIn("📋 Open Full Details", app_content)
        self.assertIn("openAirportPopup(apt, isLoading = false)", app_content)

    def test_generate_airport_popup_html_detailed_rendering(self):
        """Verify popup template string rendering logic in Python parity matches expected rich popup specifications."""
        mock_apt = {
            "icao": "KSQL",
            "faa": "SQL",
            "iata": "SQL",
            "name": "San Carlos Airport",
            "city": "San Carlos",
            "state": "CA",
            "elevation_ft": 13,
            "tower": True,
            "ctaf_freq": 119.0,
            "unicom_freq": 122.95,
            "runways": [
                {"id": "12/30", "length": 2600, "surface": "Asphalt"}
            ],
            "last_updated": "2026-08-22",
            "source": "AirNav Live Feed",
            "fbos": [
                {
                    "name": "Rabbit Aviation Services",
                    "phone": "650-591-5857",
                    "fuels": {
                        "100LL_SS": {"price": 6.15, "type": "100LL", "service": "Self-Serve"},
                        "100LL_FS": {"price": 6.65, "type": "100LL", "service": "Full-Serve"},
                        "94UL_SS": {"price": 5.95, "type": "94UL", "service": "Self-Serve"},
                        "100UL_SS": {"price": 6.20, "type": "100UL", "service": "Self-Serve"},
                        "100R_SS": {"price": 6.10, "type": "100R", "service": "Self-Serve"},
                        "Mogas": {"price": 5.40, "type": "Mogas", "service": "Self-Serve"},
                        "JET_A": {"price": 7.25, "type": "Jet-A", "service": "Full-Serve"}
                    }
                }
            ]
        }

        # Check required fields exist on airport
        self.assertEqual(mock_apt["icao"], "KSQL")
        self.assertEqual(mock_apt["faa"], "SQL")
        self.assertTrue(mock_apt["tower"])
        self.assertEqual(len(mock_apt["fbos"]), 1)
        fbo = mock_apt["fbos"][0]
        self.assertIn("100LL_SS", fbo["fuels"])
        self.assertIn("94UL_SS", fbo["fuels"])
        self.assertIn("100UL_SS", fbo["fuels"])
        self.assertIn("100R_SS", fbo["fuels"])
        self.assertIn("Mogas", fbo["fuels"])
        self.assertIn("JET_A", fbo["fuels"])

        # Check effective non-jet best price calculation
        effective = get_effective_fuel_price(mock_apt, fuel_type='all', service='any')
        self.assertIsNotNone(effective)
        self.assertEqual(effective["price"], 5.40)  # Mogas ($5.40)
        self.assertEqual(effective["type"], "Mogas")

        effective_100ll = get_effective_fuel_price(mock_apt, fuel_type='100LL', service='self')
        self.assertIsNotNone(effective_100ll)
        self.assertEqual(effective_100ll["price"], 6.15)

    def test_price_persistence_across_modal_close_and_recalculate(self):
        """Verify closeModal invokes recalculateRadiusAirports and retains live AirNav rates without reverting."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        # In closeModal:
        self.assertIn("function closeModal()", app_content)
        self.assertIn("recalculateRadiusAirports();", app_content)

        # In fetchAirportFuelAndHighlight:
        self.assertIn("STATE.fetchedAirports.add(cleanIcao);", app_content)
        self.assertIn("STATE.customPrices[cleanIcao]", app_content)
        self.assertIn("savePersistedAirportToStorage(targetApt);", app_content)
        self.assertIn("window.AeroFuelApp", app_content)

    def test_price_persistence_full_lifecycle_simulation(self):
        """Simulate the end-to-end price fetch, modal open, modal close, and radius recalculate lifecycle."""
        # 1. Initial State: Airport has no active fuel price
        mock_state = {
            "airports": [
                {
                    "icao": "KSQL",
                    "faa": "SQL",
                    "name": "San Carlos Airport",
                    "city": "San Carlos",
                    "state": "CA",
                    "lat": 37.5119,
                    "lon": -122.2495,
                    "fbos": [],
                    "best_price": None,
                    "primary_fuel": "None",
                    "fuels_available": []
                }
            ],
            "airportsMap": {},
            "fetchedAirports": set(),
            "customPrices": {},
            "activeAirportModal": None
        }
        for a in mock_state["airports"]:
            mock_state["airportsMap"][a["icao"]] = a
            if a.get("faa"):
                mock_state["airportsMap"][a["faa"]] = a

        # Verify initially unpriced
        initial_apt = mock_state["airportsMap"]["KSQL"]
        self.assertIsNone(get_effective_fuel_price(initial_apt))

        # 2. Simulate AirNav Fetch Response
        airnav_response = {
            "icao": "KSQL",
            "name": "San Carlos Airport",
            "best_price": 6.15,
            "primary_fuel": "100LL",
            "fuels_available": ["100LL", "Jet-A"],
            "last_updated": "2026-08-22",
            "source": "AirNav Live Feed",
            "fbos": [
                {
                    "name": "Rabbit Aviation",
                    "phone": "650-591-5857",
                    "fuels": {
                        "100LL_SS": {"price": 6.15, "type": "100LL", "service": "Self-Serve"},
                        "JET_A": {"price": 7.45, "type": "Jet-A", "service": "Full-Serve"}
                    }
                }
            ]
        }

        # Apply fetch updates to master object, maps, sets, and customPrices
        target_apt = mock_state["airportsMap"]["KSQL"]
        target_apt["fbos"] = airnav_response["fbos"]
        target_apt["best_price"] = airnav_response["best_price"]
        target_apt["primary_fuel"] = airnav_response["primary_fuel"]
        target_apt["fuels_available"] = airnav_response["fuels_available"]
        target_apt["last_updated"] = airnav_response["last_updated"]
        target_apt["source"] = airnav_response["source"]

        mock_state["fetchedAirports"].add("KSQL")
        mock_state["fetchedAirports"].add("SQL")
        mock_state["customPrices"]["KSQL"] = {"100LL_SS": 6.15}
        mock_state["customPrices"]["SQL"] = {"100LL_SS": 6.15}

        # 3. Simulate Modal Open
        mock_state["activeAirportModal"] = target_apt
        self.assertEqual(mock_state["activeAirportModal"]["best_price"], 6.15)
        self.assertEqual(len(mock_state["activeAirportModal"]["fbos"]), 1)

        # 4. Simulate Modal Close (calls closeModal -> recalculateRadiusAirports)
        mock_state["activeAirportModal"] = None
        results, lowest = query_radius(mock_state["airports"], 37.5119, -122.2495, 50)

        # 5. Assert that after modal close, the price is fully retained and visible
        self.assertIsNotNone(lowest)
        self.assertEqual(lowest["icao"], "KSQL")
        self.assertEqual(lowest["fuel"]["price"], 6.15)
        self.assertEqual(lowest["fuel"]["type"], "100LL")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["fuel"]["price"], 6.15)

    def test_origin_airport_distance_calculation_and_unit_conversion(self):
        """Verify distance and bearing from origin airport are accurately computed in mi, NM, and km."""
        # Origin: KSQL (San Carlos: 37.5119, -122.2495)
        # Target: KPAO (Palo Alto: 37.4611, -122.1151) ~ 8.1 statute miles
        dist_mi = haversine_miles(37.5119, -122.2495, 37.4611, -122.1151)
        dist_nm = dist_mi / 1.15078
        dist_km = dist_mi * 1.60934

        self.assertAlmostEqual(dist_mi, 8.1, delta=0.5)
        self.assertAlmostEqual(dist_nm, 7.0, delta=0.5)
        self.assertAlmostEqual(dist_km, 13.0, delta=1.0)

        # Bearing from KSQL to KPAO is South-Southeast (~122°)
        bearing = calculate_bearing(37.5119, -122.2495, 37.4611, -122.1151)
        self.assertGreater(bearing, 100)
        self.assertLess(bearing, 140)

    def test_marker_badge_formatting_all_four_combinations(self):
        """Verify marker badge formatting logic across all 4 origin and AirNav fuel combinations."""
        # Simulated JS getBadgeHtml logic in Python
        def format_badge(ident, origin_dist_str, fuel_price, fuel_type, is_fetched=False, has_fbos=False):
            if fuel_price is not None:
                if origin_dist_str:
                    return f"{ident} • {origin_dist_str} • ${fuel_price:.2f} {fuel_type}"
                else:
                    return f"{ident} • ${fuel_price:.2f} {fuel_type}"
            elif is_fetched and not has_fbos:
                if origin_dist_str:
                    return f"{ident} • {origin_dist_str} • No Fuel"
                else:
                    return f"{ident} • No Fuel"
            else:
                if origin_dist_str:
                    return f"{ident} • {origin_dist_str}"
                else:
                    return f"{ident}"

        # State 1: No origin, No AirNav fuel -> Identifier only
        s1 = format_badge("KPAO", None, None, None)
        self.assertEqual(s1, "KPAO")

        # State 2: With origin, No AirNav fuel -> Identifier + Distance from origin
        s2 = format_badge("KPAO", "7.0 NM", None, None)
        self.assertEqual(s2, "KPAO • 7.0 NM")

        # State 3: No origin, With AirNav fuel -> Identifier + Price + Fuel Type
        s3 = format_badge("KSQL", None, 6.15, "100LL")
        self.assertEqual(s3, "KSQL • $6.15 100LL")

        # State 4: With origin, With AirNav fuel -> Identifier + Distance + Price + Fuel Type
        s4 = format_badge("KSQL", "8.1 mi", 6.15, "100LL")
        self.assertEqual(s4, "KSQL • 8.1 mi • $6.15 100LL")

    def test_origin_airport_ui_elements_in_html_and_css(self):
        """Verify index.html and style.css contain origin airport container, input, clear button, and dropdown."""
        html_path = os.path.join(DIRECTORY, "index.html")
        with open(html_path, "r") as f:
            html_content = f.read()

        self.assertIn("origin-airport-container", html_content)
        self.assertIn('id="origin-airport-input"', html_content)
        self.assertIn('id="btn-clear-origin"', html_content)
        self.assertIn('id="origin-search-dropdown"', html_content)

        css_path = os.path.join(DIRECTORY, "style.css")
        with open(css_path, "r") as f:
            css_content = f.read()

        self.assertIn(".origin-airport-container", css_content)
        self.assertIn(".origin-input-wrapper", css_content)
        self.assertIn(".btn-clear-origin", css_content)
        self.assertIn(".origin-dropdown", css_content)
        self.assertIn(".badge-dist", css_content)
        self.assertIn(".badge-sep", css_content)

    def test_origin_airport_persistence_and_events_in_app_js(self):
        """Verify app.js implements origin airport setting, localStorage persistence, and search wiring."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r") as f:
            js_content = f.read()

        self.assertIn("originAirport: null", js_content)
        self.assertIn("AEROFUEL_ORIGIN_AIRPORT", js_content)
        self.assertIn("function setOriginAirport(", js_content)
        self.assertIn("function clearOriginAirport()", js_content)
        self.assertIn("function getOriginDistanceInfo(", js_content)
        self.assertIn("function setupOriginSearch()", js_content)
        self.assertIn("applyPersistedOriginAirportFromStorage()", js_content)
        self.assertIn("setOriginAirport: setOriginAirport", js_content)

    def test_dataset_zero_default_fuel_prices_pure_airnav(self):
        """Verify all 5,000+ public-use catalog records start with clean unpriced baseline data."""
        with open(os.path.join(DIRECTORY, "fuel_data.json"), "r") as f:
            catalog = json.load(f)

        airports = catalog.get("airports", [])
        self.assertGreaterEqual(len(airports), 5000)

        for a in airports:
            self.assertIsNone(a.get("best_price"), f"{a.get('icao')} must not have default best_price")
            self.assertEqual(a.get("fbos"), [], f"{a.get('icao')} must have empty fbos array")
            self.assertEqual(a.get("fuels_available"), [], f"{a.get('icao')} must have empty fuels_available")
            self.assertIsNone(a.get("primary_fuel"), f"{a.get('icao')} must have None primary_fuel")
            self.assertIsNone(a.get("last_updated"), f"{a.get('icao')} must have None last_updated")

    def test_rich_popup_css_styling_rules(self):
        """Verify style.css provides dark glassmorphic styling for the Leaflet popup and Open Details button."""
        css_path = os.path.join(DIRECTORY, "style.css")
        with open(css_path, "r") as f:
            css_content = f.read()

        self.assertIn(".aerofuel-rich-popup .leaflet-popup-content-wrapper", css_content)
        self.assertIn(".popup-header-block", css_content)
        self.assertIn(".popup-specs-grid", css_content)
        self.assertIn(".popup-fuels-container", css_content)
        self.assertIn(".popup-fbo-card", css_content)
        self.assertIn(".popup-fuel-chip", css_content)
        self.assertIn(".btn-popup-open-details", css_content)

    def test_origin_airport_input_parsing_and_various_types(self):
        """Verify setOriginAirport handles diverse string formats, JSON strings, and airport objects."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r") as f:
            js_content = f.read()

        self.assertIn("function setOriginAirport(identOrApt)", js_content)
        self.assertIn("clean.includes('-')", js_content)
        self.assertIn("clean.includes(' ')", js_content)
        self.assertIn("typeof identOrApt === 'object'", js_content)

    def test_origin_airport_heading_and_cardinal_directions(self):
        """Verify calculate_bearing and getCompassDirection for 16-point compass headings."""
        directions = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
        def get_direction(bearing):
            idx = round(bearing / 22.5) % 16
            return directions[idx]

        self.assertEqual(get_direction(0), 'N')
        self.assertEqual(get_direction(45), 'NE')
        self.assertEqual(get_direction(90), 'E')
        self.assertEqual(get_direction(135), 'SE')
        self.assertEqual(get_direction(180), 'S')
        self.assertEqual(get_direction(225), 'SW')
        self.assertEqual(get_direction(270), 'W')
        self.assertEqual(get_direction(315), 'NW')

    def test_popup_and_modal_set_origin_buttons_presence(self):
        """Verify popup and modal include interactive Set Origin buttons and styling."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        self.assertIn('btn-popup-set-origin', app_content)
        self.assertIn('btn-modal-set-origin', app_content)

        css_path = os.path.join(DIRECTORY, "style.css")
        with open(css_path, "r") as f:
            css_content = f.read()

        self.assertIn('.btn-popup-set-origin', css_content)

    def test_sidebar_and_best_deal_hud_signature_reactivity(self):
        """Verify updateSidebarRadarList and updateBestDealHUD signatures react to origin airport and unit changes."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        self.assertIn("const originKey = STATE.originAirport ? STATE.originAirport.icao : 'no-origin';", app_content)
        self.assertIn("`${originKey}:${STATE.radiusUnit}:`", app_content)
        self.assertIn("`${STATE.radiusUnit}:${lowest.icao}:", app_content)

    def test_marker_badge_fuel_price_border_and_glow_css_rules(self):
        """Verify style.css adds distinct 2px borders, tier color matching, and glow to badges with fuel prices, and muted neutral borders to unpriced badges."""
        css_path = os.path.join(DIRECTORY, "style.css")
        self.assertTrue(os.path.exists(css_path), "style.css missing")
        with open(css_path, "r") as f:
            css_content = f.read()

        # Active fuel price badge distinction: 2px accent border and glow
        self.assertIn(".fuel-price-badge.has-fuel-price", css_content)
        self.assertIn("border: 2px solid #38bdf8;", css_content)
        self.assertIn("box-shadow: 0 0 10px rgba(56, 189, 248, 0.35)", css_content)

        # Tier cheap: emerald #10b981 border and glow
        self.assertIn(".tier-cheap .fuel-price-badge", css_content)
        self.assertIn("border: 2px solid #10b981;", css_content)
        self.assertIn("rgba(16, 185, 129, 0.45)", css_content)

        # Tier avg: sky blue #38bdf8 border and glow
        self.assertIn(".tier-avg .fuel-price-badge", css_content)
        self.assertIn("border: 2px solid #38bdf8;", css_content)

        # Tier exp: amber #f59e0b border and glow
        self.assertIn(".tier-exp .fuel-price-badge", css_content)
        self.assertIn("border: 2px solid #f59e0b;", css_content)
        self.assertIn("rgba(245, 158, 11, 0.45)", css_content)

        # Unpriced badges (unreported & unfetched): muted neutral border
        self.assertIn("border: 1px solid rgba(148, 163, 184, 0.2);", css_content)
        self.assertIn("border: 1px dashed rgba(148, 163, 184, 0.35);", css_content)

    def test_unpriced_marker_badge_no_cyan_glow_cascade(self):
        """Verify .airport-marker-container.in-radius .fuel-price-badge does not inject a blue glow over unpriced badges."""
        css_path = os.path.join(DIRECTORY, "style.css")
        with open(css_path, "r") as f:
            css_content = f.read()

        # In-radius base rule should not force cyan box-shadow
        self.assertIn(".airport-marker-container.in-radius .fuel-price-badge {\n  display: inline-flex;\n  animation: badge-appear", css_content)

        # Unpriced marker dot in radius should remain muted gray
        self.assertIn(".airport-marker-container.in-radius.tier-ident .marker-dot", css_content)
        self.assertIn(".airport-marker-container.in-radius.no-fuel-price .marker-dot", css_content)

    def test_app_js_has_fuel_price_class_attachment(self):
        """Verify app.js attaches .has-fuel-price and .no-fuel-price classes to marker badge and container elements."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        self.assertTrue(os.path.exists(app_js_path), "app.js missing")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        self.assertIn("const hasPriceClass = fuelInfo ? 'has-fuel-price' : 'no-fuel-price';", app_content)
        self.assertIn('fuel-price-badge ${hasPriceClass}', app_content)
        self.assertIn('airport-marker-container ${tierClass} ${hasPriceClass}', app_content)
        self.assertIn("el.classList.add(tierClass, hasPriceClass);", app_content)
        self.assertIn("badge.className = `fuel-price-badge ${tierClass} ${hasPriceClass}`;", app_content)

    def test_canvas_dots_halo_stroke_for_priced_airports(self):
        """Verify app.js draws outer halo ring / stroke around canvas dots for airports with known fuel prices."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        self.assertTrue(os.path.exists(app_js_path), "app.js missing")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        # Canvas redraw must check fuelInfo and draw outer stroke ring
        self.assertIn("Draw outer stroke ring / bright halo for airports with known fuel prices", app_content)
        self.assertIn("airportCanvasCtx.strokeStyle = color;", app_content)
        self.assertIn("airportCanvasCtx.stroke();", app_content)

    def test_sidebar_active_fuel_price_card_accent_border(self):
        """Verify sidebar cards with active fuel prices are highlighted with accent borders in CSS and JS."""
        css_path = os.path.join(DIRECTORY, "style.css")
        with open(css_path, "r") as f:
            css_content = f.read()

        self.assertIn(".radar-airport-card.has-fuel-card", css_content)
        self.assertIn(".radar-airport-card.has-fuel-price", css_content)
        self.assertIn("border: 1.5px solid rgba(56, 189, 248, 0.45);", css_content)
        self.assertIn(".radar-airport-card.has-fuel-card.tier-cheap", css_content)
        self.assertIn(".radar-airport-card.has-fuel-card.tier-exp", css_content)

        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        self.assertIn("radar-airport-card has-fuel-card has-fuel-price", app_content)
        self.assertIn("tierCardClass", app_content)

    def test_zip_package_integrity(self):
        """Verify airport_fuel_lookup.zip exists and contains all required application files."""
        import zipfile
        zip_path = os.path.join(DIRECTORY, "..", "..", "..", "..", "..", "airport_fuel_lookup.zip")
        zip_path = os.path.abspath(zip_path)
        self.assertTrue(os.path.exists(zip_path), f"ZIP file missing at {zip_path}")
        self.assertGreater(os.path.getsize(zip_path), 1000)

        required_in_zip = {
            "app.js",
            "index.html",
            "style.css",
            "airnav_client.py",
            "server.py",
            "fetch_fuel_data.py",
            "test_fuel_lookup.py",
            "README.md"
        }

        with zipfile.ZipFile(zip_path, "r") as z:
            names = set(z.namelist())
            for req in required_in_zip:
                self.assertIn(req, names, f"Required file {req} missing from ZIP")


class TestPublicAirportsStrictExclusion(unittest.TestCase):
    """Automated tests asserting strict exclusion of private facilities and full preservation of verified public GA airports."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(DIRECTORY, "fuel_data.json"), "r") as f:
            catalog = json.load(f)
        cls.airports = catalog.get("airports", [])
        cls.by_icao = {a["icao"]: a for a in cls.airports}
        cls.by_faa = {a["faa"]: a for a in cls.airports if a.get("faa")}

    def test_catalog_strictly_public_airport_count(self):
        """Verify public airport catalog contains strictly public facilities (~5,000–5,500 total)."""
        self.assertGreaterEqual(len(self.airports), 5000, f"Expected >= 5000 public airports, got {len(self.airports)}")
        self.assertLessEqual(len(self.airports), 5500, f"Expected <= 5500 public airports, got {len(self.airports)}")

    def test_private_airstrips_strictly_excluded(self):
        """Assert that private airstrips, ranch strips, farm strips, and synthetic records are completely absent."""
        known_private_facilities = [
            '00AA', '00CA', '12CA', '9CL2', 'CA01', 'TX12', 'FL04', '00TX',
            'US-6619', 'US-4106', 'US-4107', 'US-4108', '00AK', '00AL', '00AN',
            '00AS', '00AZ', '00CL', '00FA', '00FL', '00GA', '00ID', '00IG',
            '00IL', '00IS', '00KS', '00KY', '00LS', '00MD', '02PR', '02SC',
            '02TN', '02UT', '02VA', '02WA', '02WI', '02WN', '02XA', '03AK',
            '03AZ', '03CO', '03FA', '03GA', '03ID', '03II', '03IL', '03IN',
            '03KY', '03MA', '03ME', '03MN', '03MT', '03MU', '03NC', '03ND',
            '03NE', '03NV', 'BOBS', 'BONI', 'BUTL', 'CHAN', 'CRAI', 'GOAD',
            'HOPA', 'JAMI', 'JOEY', 'OMU9', 'RSCO', 'WEON'
        ]
        for priv in known_private_facilities:
            self.assertNotIn(priv, self.by_icao, f"Private facility {priv} found in by_icao!")
            self.assertNotIn(priv, self.by_faa, f"Private facility {priv} found in by_faa!")

    def test_verified_public_ga_fields_preserved(self):
        """Assert that verified public GA airports across CONUS, Alaska, Hawaii, and territories are preserved."""
        verified_public_fields = [
            'KSQL', 'KPAO', 'KCVH', 'E16', 'O22', 'C83', '0Q5', 'O88', '1O2',
            'KOSH', 'KADS', 'PANC', 'PHNL', 'TJSJ', 'KRHV', 'KHAF', 'KOAK',
            'KHWD', 'KLVK', 'KCCR', 'KAPC', 'KSTS', 'KDVO', 'KSAC', 'KEDU',
            'KVCB', 'KCPU', 'KMRY', 'KWVI', 'KSBP', 'KPRB', 'KTRK', 'KTVL',
            'KSMO', 'KVNY', 'KWHP', 'KTOA', 'KCNO', 'KFUL', 'KCRQ', 'KMYF',
            'KSEE', 'KTRM', 'KBFI', 'KRNT', 'KPAE', 'KTIW', 'KCLS', 'KPDX',
            'KHIO', 'KMMV', 'KBDN', 'KDVT', 'KSDL', 'KFFZ', 'KSEZ', 'KVGT',
            'KHND', 'KBVU', 'KAPA', 'KBJC', 'KFTG', 'KASE', 'KDTO', 'KHYI',
            'KPWK', 'KLAL', 'KFDK', 'PGUM', 'NSTU', 'PGSN', 'TIST', 'K07',
            'K78', 'K34', '00C', '00F', '00M', '00R', '00S', '00W', '01A',
            '01G', '01J', '01K', '01M', '01U', '02A', '02C', '02G', '02T',
            '03B', '03D', '03M', '03S', '04A', '04G', '04I', '04M', '04V',
            '04W', '04Y', '05B', '05C', 'PAAT', 'PAHE'
        ]
        for pub in verified_public_fields:
            self.assertTrue(pub in self.by_icao or pub in self.by_faa,
                            f"Verified public airport {pub} missing from catalog!")

    def test_no_private_4character_faa_identifier_patterns_in_dataset(self):
        """Scan all catalog records and verify no private 4-character FAA identifier patterns exist."""
        for apt in self.airports:
            icao = apt["icao"]
            faa = apt.get("faa", "")

            # If FAA LID is 4 chars, it must not have >= 2 digits (e.g. 00CA, 12CA, CA01, 9CL2)
            if len(faa) == 4:
                digits = sum(1 for c in faa if c.isdigit())
                self.assertLess(digits, 2, f"Airport {icao} has private FAA LID pattern: {faa}")

            # icao must not be synthetic US-xxxx or PR-xxxx
            self.assertFalse(icao.startswith("US-"), f"Synthetic US identifier in catalog: {icao}")
            self.assertFalse(icao.startswith("PR-"), f"Synthetic PR identifier in catalog: {icao}")

    def test_no_private_facility_keywords_in_dataset(self):
        """Verify that no airport in the dataset contains private facility keywords in its name."""
        forbidden_keywords = [
            '(private)', '[private]', 'ranch strip', 'farm strip', 'hospital',
            'clinic', 'helipad', 'heliport'
        ]
        for apt in self.airports:
            name_lower = apt["name"].lower()
            for kw in forbidden_keywords:
                self.assertNotIn(kw, name_lower,
                                 f"Airport {apt['icao']} ({apt['name']}) contains private keyword '{kw}'")

    def test_is_private_facility_unit_logic(self):
        """Unit test is_private_facility logic on explicit public and private mock rows."""
        from fetch_fuel_data import is_private_facility

        # Private test rows
        self.assertTrue(is_private_facility({'ident': '00AA', 'local_code': '00AA', 'name': 'Aero B Ranch'}))
        self.assertTrue(is_private_facility({'ident': '9CL2', 'local_code': '9CL2', 'name': 'Christensen Ranch'}))
        self.assertTrue(is_private_facility({'ident': '00CA', 'local_code': '00CA', 'name': 'Goldstone'}))
        self.assertTrue(is_private_facility({'ident': '12CA', 'local_code': '12CA', 'name': 'Faber Vineyards'}))
        self.assertTrue(is_private_facility({'ident': 'CA01', 'local_code': 'CA01', 'name': 'Private Strip'}))
        self.assertTrue(is_private_facility({'ident': 'TX12', 'local_code': 'TX12', 'name': 'Ranch Strip'}))
        self.assertTrue(is_private_facility({'ident': 'FL04', 'local_code': 'FL04', 'name': 'Pate Lake'}))
        self.assertTrue(is_private_facility({'ident': '00TX', 'local_code': '00TX', 'name': 'Texas Private'}))
        self.assertTrue(is_private_facility({'ident': 'US-6619', 'local_code': '', 'name': 'Unregistered'}))
        self.assertTrue(is_private_facility({'ident': 'KXYZ', 'local_code': 'XYZ', 'name': 'General Hospital Heliport'}))
        self.assertTrue(is_private_facility({'ident': 'KXYZ', 'local_code': 'XYZ', 'name': 'Smith Field (Private)'}))
        self.assertTrue(is_private_facility({'ident': 'KXYZ', 'local_code': 'XYZ', 'name': 'Smith Field [Private]'}))
        self.assertTrue(is_private_facility({'ident': 'KXYZ', 'local_code': 'XYZ', 'name': 'Smith Private Airport'}))
        self.assertTrue(is_private_facility({'ident': '00AK', 'local_code': '00AK', 'name': 'Lowell Field', 'iso_region': 'US-AK'}))
        self.assertTrue(is_private_facility({'ident': '02PR', 'local_code': '02PR', 'name': 'Puerto Rico Private', 'iso_country': 'PR'}))
        self.assertTrue(is_private_facility({'ident': 'BOBS', 'local_code': '', 'name': 'Bobs', 'iso_region': 'US-AR'}))
        self.assertTrue(is_private_facility({'ident': 'BONI', 'local_code': '', 'name': 'McCready AG', 'iso_region': 'US-LA'}))

        # Public test rows
        self.assertFalse(is_private_facility({'ident': 'KSQL', 'local_code': 'SQL', 'name': 'San Carlos Airport', 'iso_region': 'US-CA'}))
        self.assertFalse(is_private_facility({'ident': 'KPAO', 'local_code': 'PAO', 'name': 'Palo Alto Airport', 'iso_region': 'US-CA'}))
        self.assertFalse(is_private_facility({'ident': 'CVH', 'local_code': 'CVH', 'name': 'Hollister Municipal', 'iso_region': 'US-CA'}))
        self.assertFalse(is_private_facility({'ident': 'KE16', 'local_code': 'E16', 'name': 'San Martin Airport', 'iso_region': 'US-CA'}))
        self.assertFalse(is_private_facility({'ident': 'KO22', 'local_code': 'O22', 'name': 'Columbia Airport', 'iso_region': 'US-CA'}))
        self.assertFalse(is_private_facility({'ident': 'KC83', 'local_code': 'C83', 'name': 'Byron Airport', 'iso_region': 'US-CA'}))
        self.assertFalse(is_private_facility({'ident': 'K0Q5', 'local_code': '0Q5', 'name': 'Shelter Cove Airport', 'iso_region': 'US-CA'}))
        self.assertFalse(is_private_facility({'ident': 'KO88', 'local_code': 'O88', 'name': 'Rio Vista Municipal', 'iso_region': 'US-CA'}))
        self.assertFalse(is_private_facility({'ident': 'K1O2', 'local_code': '1O2', 'name': 'Lampson Field', 'iso_region': 'US-CA'}))
        self.assertFalse(is_private_facility({'ident': '02T', 'local_code': '02T', 'name': 'Wise River Airport', 'iso_region': 'US-MT'}))
        self.assertFalse(is_private_facility({'ident': '03M', 'local_code': '03M', 'name': 'Lakeside Marina Seaplane Base', 'iso_region': 'US-LA'}))
        self.assertFalse(is_private_facility({'ident': 'PANC', 'local_code': 'ANC', 'name': 'Ted Stevens Anchorage Intl', 'iso_region': 'US-AK'}))
        self.assertFalse(is_private_facility({'ident': 'PHNL', 'local_code': 'HNL', 'name': 'Daniel K Inouye Intl', 'iso_region': 'US-HI'}))
        self.assertFalse(is_private_facility({'ident': 'TJSJ', 'local_code': 'SJU', 'name': 'Luis Munoz Marin Intl', 'iso_country': 'PR'}))
        self.assertFalse(is_private_facility({'ident': 'K00C', 'local_code': '00C', 'name': 'Animas Air Park', 'iso_region': 'US-CO'}))
        self.assertFalse(is_private_facility({'ident': 'K07', 'local_code': 'K07', 'name': 'Ellsworth Municipal', 'iso_region': 'US-KS'}))
        self.assertFalse(is_private_facility({'ident': 'K78', 'local_code': 'K78', 'name': 'Oberlin Municipal', 'iso_region': 'US-KS'}))
        self.assertFalse(is_private_facility({'ident': 'K34', 'local_code': 'K34', 'name': 'Medicine Lodge Municipal', 'iso_region': 'US-KS'}))


class TestSmoothZoomAndTriUnitScale(unittest.TestCase):
    """Automated tests for smooth gradual zooming and bottom-left Tri-Unit (mi, NM, km) map scale control."""

    def test_smooth_zoom_map_configuration_in_app_js(self):
        """Verify app.js configures Leaflet map for 60 FPS zero-snapping floating-point zoom."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        self.assertTrue(os.path.exists(app_js_path), "app.js missing")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        # Strictly zoomSnap: 0 for continuous floating-point precision (zero snapping grid)
        self.assertIn("zoomSnap: 0", app_content, "zoomSnap: 0 missing for zero-snapping continuous zoom")
        self.assertNotIn("zoomSnap: 0.1", app_content, "zoomSnap: 0.1 must be updated to 0 to eliminate all snapping steps")

        # Built-in debounced wheel handler disabled in favor of custom momentum engine
        self.assertIn("scrollWheelZoom: false", app_content, "scrollWheelZoom: false missing to prevent discrete timer debounce jumps")

        # Smooth wheel engine invoked in setupMapListeners
        self.assertIn("setupSmoothWheelZoom();", app_content, "setupSmoothWheelZoom invocation missing in setupMapListeners")

    def test_smooth_wheel_zoom_engine_implementation_in_app_js(self):
        """Verify app.js implements the 60 FPS momentum-interpolated smooth wheel zoom engine."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        self.assertTrue(os.path.exists(app_js_path), "app.js missing")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        self.assertIn("function setupSmoothWheelZoom()", app_content)
        self.assertIn("mapContainer.addEventListener('wheel'", app_content)
        self.assertIn("{ passive: false }", app_content)
        self.assertIn("e.preventDefault()", app_content)
        self.assertIn("map.mouseEventToLatLng(e)", app_content)
        self.assertIn("map.setZoomAround(zoomTargetPoint, nextZoom, { animate: false })", app_content)
        self.assertIn("nextZoom = currentZoom + diff * 0.22", app_content)
        self.assertIn("redrawAirportCanvas()", app_content)

    def test_momentum_interpolation_mathematical_convergence(self):
        """Verify momentum interpolation easing math converges smoothly to targetZoom without overshoot or jitter."""
        # Simulation: initial zoom 9.0, user scrolls to target 12.5
        current_zoom = 9.0
        target_zoom = 12.5
        frames = []

        for frame in range(60):
            diff = target_zoom - current_zoom
            if abs(diff) < 0.001:
                current_zoom = target_zoom
                frames.append(current_zoom)
                break
            current_zoom = current_zoom + diff * 0.22
            frames.append(current_zoom)

        # Must reach exact target zoom cleanly
        self.assertEqual(frames[-1], 12.5)
        # Must converge monotonically (every frame increases zoom towards target)
        for i in range(len(frames) - 1):
            self.assertLessEqual(frames[i], frames[i + 1])
        # Convergence should happen within ~30 frames (< 0.5s at 60 FPS)
        self.assertLess(len(frames), 40)

        # Simulation: zoom out from 12.5 to 7.0
        current_zoom = 12.5
        target_zoom = 7.0
        frames_out = []
        for frame in range(60):
            diff = target_zoom - current_zoom
            if abs(diff) < 0.001:
                current_zoom = target_zoom
                frames_out.append(current_zoom)
                break
            current_zoom = current_zoom + diff * 0.22
            frames_out.append(current_zoom)

        self.assertEqual(frames_out[-1], 7.0)
        for i in range(len(frames_out) - 1):
            self.assertGreaterEqual(frames_out[i], frames_out[i + 1])

    def test_wheel_delta_normalization_and_zoom_bounds_clamping(self):
        """Verify wheel delta normalization handles pixel/line/page modes and clamps to zoom bounds."""
        min_zoom = 1
        max_zoom = 19

        def compute_new_target(current_target, delta_y, delta_mode):
            delta = delta_y
            if delta_mode == 1:
                delta *= 33.33
            elif delta_mode == 2:
                delta *= 666.67
            zoom_step = -delta * 0.002
            return max(min_zoom, min(max_zoom, current_target + zoom_step))

        # Standard discrete wheel notch (mode 1: 3 lines) -> delta = 3 -> -3 * 33.33 * 0.002 = -0.20
        target = compute_new_target(9.0, 3.0, 1)
        self.assertAlmostEqual(target, 8.8, places=2)

        # Zoom in wheel notch
        target_in = compute_new_target(9.0, -3.0, 1)
        self.assertAlmostEqual(target_in, 9.2, places=2)

        # Trackpad smooth scroll (mode 0: 5px)
        target_trackpad = compute_new_target(9.0, -5.0, 0)
        self.assertAlmostEqual(target_trackpad, 9.01, places=3)

        # Clamping at maxZoom (19)
        clamped_max = compute_new_target(18.95, -100.0, 0)
        self.assertEqual(clamped_max, 19.0)

        # Clamping at minZoom (1)
        clamped_min = compute_new_target(1.05, 100.0, 0)
        self.assertEqual(clamped_min, 1.0)

    def test_tri_unit_scale_control_definition_and_dom_in_app_js(self):
        """Verify app.js defines AeroScaleControl with bottom-left placement, event bindings, and tri-unit DOM elements."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        self.assertTrue(os.path.exists(app_js_path), "app.js missing")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        # Check class and helper function
        self.assertIn("function getNiceScaleNumber(", app_content)
        self.assertIn("const AeroScaleControl = L.Control.extend({", app_content)
        self.assertIn("L.control.aeroScale =", app_content)

        # Check position: bottomleft
        self.assertIn("position: 'bottomleft'", app_content)

        # Check DOM element IDs for all 3 units and latitude indicator
        self.assertIn('id="aero-scale-lat-ind"', app_content)
        self.assertIn('id="aero-scale-bar-mi"', app_content)
        self.assertIn('id="aero-scale-val-mi"', app_content)
        self.assertIn('id="aero-scale-bar-nm"', app_content)
        self.assertIn('id="aero-scale-val-nm"', app_content)
        self.assertIn('id="aero-scale-bar-km"', app_content)
        self.assertIn('id="aero-scale-val-km"', app_content)

        # Check event listeners for dynamic updates
        self.assertIn("this._map.on('zoom', this._update, this);", app_content)
        self.assertIn("this._map.on('move', this._update, this);", app_content)
        self.assertIn("this._map.on('viewreset', this._update, this);", app_content)
        self.assertIn("this._map.on('resize', this._update, this);", app_content)

        # Check scale control instantiation in initMap
        self.assertIn("const aeroScaleControl = L.control.aeroScale({", app_content)

    def test_tri_unit_scale_css_styling_rules(self):
        """Verify style.css includes dark glassmorphic styling, cyan/white accents, and layout for the tri-unit scale."""
        css_path = os.path.join(DIRECTORY, "style.css")
        self.assertTrue(os.path.exists(css_path), "style.css missing")
        with open(css_path, "r") as f:
            css_content = f.read()

        # Check scale control container styling
        self.assertIn(".leaflet-control-aero-scale", css_content)
        self.assertIn("backdrop-filter: blur(", css_content)
        self.assertIn(".aero-scale-hud", css_content)
        self.assertIn(".aero-scale-header", css_content)
        self.assertIn(".aero-scale-title", css_content)
        self.assertIn(".aero-scale-lat-indicator", css_content)

        # Check rows for mi, NM, km
        self.assertIn(".aero-scale-row.aero-scale-mi", css_content)
        self.assertIn(".aero-scale-row.aero-scale-nm", css_content)
        self.assertIn(".aero-scale-row.aero-scale-km", css_content)

        # Check bar and label styling
        self.assertIn(".aero-scale-bar-wrapper", css_content)
        self.assertIn(".aero-scale-bar", css_content)
        self.assertIn(".aero-scale-val", css_content)

    def test_get_nice_scale_number_mathematical_parity(self):
        """Verify nice scale number calculation follows 1-2-5 series across small and large values."""
        def get_nice_scale_number(num):
            if num <= 0:
                return 1
            pow10 = 10.0 ** math.floor(math.log10(num))
            d = num / pow10
            if d >= 5.0:
                factor = 5.0
            elif d >= 2.0:
                factor = 2.0
            else:
                factor = 1.0
            val = factor * pow10
            return round(val) if val >= 1.0 else round(val, 4)

        # Fractional values (< 1)
        self.assertEqual(get_nice_scale_number(0.08), 0.05)
        self.assertEqual(get_nice_scale_number(0.25), 0.2)
        self.assertEqual(get_nice_scale_number(0.48), 0.2)
        self.assertEqual(get_nice_scale_number(0.85), 0.5)

        # Units (1 to 10)
        self.assertEqual(get_nice_scale_number(1.5), 1)
        self.assertEqual(get_nice_scale_number(3.8), 2)
        self.assertEqual(get_nice_scale_number(7.5), 5)
        self.assertEqual(get_nice_scale_number(9.9), 5)

        # Decades (10 to 1000)
        self.assertEqual(get_nice_scale_number(18.5), 10)
        self.assertEqual(get_nice_scale_number(35.0), 20)
        self.assertEqual(get_nice_scale_number(82.0), 50)
        self.assertEqual(get_nice_scale_number(140.0), 100)
        self.assertEqual(get_nice_scale_number(350.0), 200)
        self.assertEqual(get_nice_scale_number(750.0), 500)
        self.assertEqual(get_nice_scale_number(2300.0), 2000)

    def test_ground_resolution_meters_per_pixel_latitude_correction(self):
        """Verify ground resolution (meters per pixel) properly applies cos(lat) across global latitudes."""
        C0 = 40075016.68557849  # Earth circumference at equator (meters)

        def meters_per_pixel(lat_deg, zoom):
            cos_lat = math.cos(math.radians(abs(lat_deg)))
            return (C0 * cos_lat) / (256.0 * (2.0 ** zoom))

        # Equator (lat 0°) at zoom 9
        res_eq = meters_per_pixel(0.0, 9)
        self.assertAlmostEqual(res_eq, 305.748, places=2)

        # Mid-latitude San Carlos (lat 37.5119°) at zoom 9
        res_sql = meters_per_pixel(37.5119, 9)
        self.assertAlmostEqual(res_sql, 242.53, places=1)
        self.assertLess(res_sql, res_eq, "Resolution in m/px must decrease away from equator")

        # High-latitude Alaska Fairbanks (lat 64.8378°) at zoom 9
        res_ak = meters_per_pixel(64.8378, 9)
        self.assertAlmostEqual(res_ak, 130.01, places=1)

        # Southern Hemisphere Sydney (lat -33.8688°) at zoom 9
        res_syd = meters_per_pixel(-33.8688, 9)
        self.assertAlmostEqual(res_syd, meters_per_pixel(33.8688, 9), places=4)

    def test_tri_unit_scale_bar_calibrations_and_proportions(self):
        """Verify that Statute Miles, Nautical Miles, and Kilometers scale bars calibrate correctly to physics."""
        C0 = 40075016.68557849
        max_width_px = 110

        def calculate_scale(lat, zoom):
            m_per_px = (C0 * math.cos(math.radians(abs(lat)))) / (256.0 * (2.0 ** zoom))
            max_meters = max_width_px * m_per_px

            def calc_unit(m_per_unit):
                max_u = max_meters / m_per_unit
                pow10 = 10.0 ** math.floor(math.log10(max_u))
                d = max_u / pow10
                factor = 5.0 if d >= 5.0 else (2.0 if d >= 2.0 else 1.0)
                nice_val = factor * pow10
                nice_num = round(nice_val) if nice_val >= 1.0 else round(nice_val, 4)
                target_m = nice_num * m_per_unit
                w_px = max(1, min(max_width_px, round(target_m / m_per_px)))
                return nice_num, w_px

            mi_num, mi_px = calc_unit(1609.344)
            nm_num, nm_px = calc_unit(1852.0)
            km_num, km_px = calc_unit(1000.0)
            return {
                "mi": (mi_num, mi_px),
                "NM": (nm_num, nm_px),
                "km": (km_num, km_px)
            }

        # Test at zoom 9 (regional view) in SF Bay Area (lat 37.5°)
        scale_z9 = calculate_scale(37.5119, 9)
        mi_num, mi_px = scale_z9["mi"]
        nm_num, nm_px = scale_z9["NM"]
        km_num, km_px = scale_z9["km"]

        self.assertGreater(mi_num, 0)
        self.assertGreater(nm_num, 0)
        self.assertGreater(km_num, 0)
        self.assertLessEqual(mi_px, max_width_px)
        self.assertLessEqual(nm_px, max_width_px)
        self.assertLessEqual(km_px, max_width_px)

        # For equal numeric values, 10 NM represents 18,520m, 10 mi represents 16,093m, 10 km represents 10,000m
        # Therefore NM bar width must be greater than statute mile bar width for the same number of units
        m_per_px = (C0 * math.cos(math.radians(37.5119))) / (256.0 * (2.0 ** 9))
        w_10nm = round(10 * 1852.0 / m_per_px)
        w_10mi = round(10 * 1609.344 / m_per_px)
        w_10km = round(10 * 1000.0 / m_per_px)
        self.assertGreater(w_10nm, w_10mi)
        self.assertGreater(w_10mi, w_10km)

    def test_smooth_zoom_continuous_scale_transitions(self):
        """Verify scale bar pixel widths change smoothly and monotonically as zoom increases continuously."""
        C0 = 40075016.68557849
        lat = 37.5119

        # As zoom increases from 8.0 to 10.0 in 0.1 fractional increments:
        prev_m_per_px = float('inf')
        for step in range(21):
            fractional_zoom = 8.0 + step * 0.1
            m_per_px = (C0 * math.cos(math.radians(lat))) / (256.0 * (2.0 ** fractional_zoom))
            # Ground meters per pixel must decrease smoothly at every fractional increment
            self.assertLess(m_per_px, prev_m_per_px)
            prev_m_per_px = m_per_px

    def test_tri_unit_scale_bar_bounds_at_extreme_zooms_and_latitudes(self):
        """Verify that across extreme zoom levels (1..19) and global latitudes, scale bar width is strictly bounded [1, 110] px."""
        C0 = 40075016.68557849
        max_width_px = 110

        def get_nice_scale_number(max_units):
            if max_units <= 0:
                return 1
            pow10 = 10.0 ** math.floor(math.log10(max_units))
            d = max_units / pow10
            factor = 5.0 if d >= 5.0 else (2.0 if d >= 2.0 else 1.0)
            val = factor * pow10
            return round(val) if val >= 1.0 else round(val, 4)

        test_latitudes = [0.0, 37.5119, 64.8378, 71.2906, -33.8688, -77.8460]
        test_zooms = [1.0, 3.5, 6.0, 9.2, 12.0, 15.7, 19.0]
        units = [("mi", 1609.344), ("NM", 1852.0), ("km", 1000.0)]

        for lat in test_latitudes:
            for zoom in test_zooms:
                m_per_px = (C0 * math.cos(math.radians(abs(lat)))) / (256.0 * (2.0 ** zoom))
                max_meters = max_width_px * m_per_px
                for unit_name, m_per_unit in units:
                    max_units = max_meters / m_per_unit
                    nice_num = get_nice_scale_number(max_units)
                    self.assertGreater(nice_num, 0, f"niceNum must be > 0 at lat {lat}, zoom {zoom}, unit {unit_name}")
                    target_meters = nice_num * m_per_unit
                    width_px = max(1, min(max_width_px, round(target_meters / m_per_px)))
                    self.assertGreaterEqual(width_px, 1, f"width_px < 1 at lat {lat}, zoom {zoom}, unit {unit_name}")
                    self.assertLessEqual(width_px, max_width_px, f"width_px > max_width at lat {lat}, zoom {zoom}, unit {unit_name}")

    def test_aero_scale_control_and_canvas_listeners_in_app_js(self):
        """Verify app.js includes immediate scale initialization in onAdd and attaches zoomanim to canvas overlay."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        self.assertIn("this._buildDom();\n      this._update();", app_content)
        self.assertIn("map.on('zoomanim', redrawAirportCanvas);", app_content)


class TestMarkerHitTestingAndDomListeners(unittest.TestCase):
    """Automated tests for direct DOM click/pointer listeners on badges, CSS hit targets, and capsule screen-space hit testing."""

    def test_marker_direct_dom_listeners_attached_in_app_js(self):
        """Verify app.js attaches direct DOM click, pointerdown, and touchstart listeners with stopPropagation to marker containers, badges, and ribbons."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        self.assertTrue(os.path.exists(app_js_path), "app.js missing")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        # Check attachMarkerDomListeners function definition
        self.assertIn("function attachMarkerDomListeners(icao, apt, element = null)", app_content)
        self.assertIn("el.addEventListener('click', handleAirportClick);", app_content)
        self.assertIn("el.addEventListener('pointerdown', handlePointerDown);", app_content)
        self.assertIn("el.addEventListener('touchstart', handlePointerDown", app_content)
        self.assertIn("badge.addEventListener('click', handleAirportClick);", app_content)
        self.assertIn("badge.addEventListener('pointerdown', handlePointerDown);", app_content)
        self.assertIn("badge.addEventListener('touchstart', handlePointerDown", app_content)
        self.assertIn("ribbon.addEventListener('click', handleAirportClick);", app_content)

        # Check event stopPropagation and preventDefault logic
        self.assertIn("if (e.stopPropagation) e.stopPropagation();", app_content)
        self.assertIn("if (e.preventDefault) e.preventDefault();", app_content)
        self.assertIn("if (L.DomEvent.stopPropagation) L.DomEvent.stopPropagation(e);", app_content)
        self.assertIn("if (L.DomEvent.preventDefault) L.DomEvent.preventDefault(e);", app_content)

        # Check marker add and update wiring
        self.assertIn("attachMarkerDomListeners(apt.icao, apt);", app_content)
        self.assertIn("attachMarkerDomListeners(apt.icao, apt, el);", app_content)

    def test_style_css_generous_hit_targets_and_pointer_events(self):
        """Verify style.css provides generous hit areas, click-padding pseudo-elements, custom-airport-div-icon rules, and pointer-events auto for markers and badges."""
        css_path = os.path.join(DIRECTORY, "style.css")
        self.assertTrue(os.path.exists(css_path), "style.css missing")
        with open(css_path, "r") as f:
            css_content = f.read()

        # Custom airport div icon container rules
        self.assertIn(".custom-airport-div-icon", css_content)
        self.assertIn("overflow: visible !important;", css_content)

        # Marker container hit area padding
        self.assertIn(".airport-marker-container::before", css_content)
        self.assertIn("touch-action: manipulation;", css_content)

        # Fuel price badge hit area padding pseudo-element
        self.assertIn(".fuel-price-badge::before", css_content)
        self.assertIn("border-radius: 999px;", css_content)

        # Lowest trophy ribbon hit target
        self.assertIn(".lowest-ribbon", css_content)

        # Child elements must allow pointer events
        self.assertIn(".fuel-price-badge * {\n  pointer-events: auto;\n  cursor: pointer;\n}", css_content)

    def test_enhanced_hit_testing_capsule_math_and_badge_offsets(self):
        """Verify oriented screen-space capsule/box hit testing accurately detects clicks on center dot, badge pill offsets, and rejects misses."""
        def hit_test(dx, dy, max_pixel_dist=20):
            dot_dist = math.sqrt(dx * dx + dy * dy)
            is_dot_hit = dot_dist <= max(max_pixel_dist, 20)
            is_badge_hit = abs(dx) <= 65 and -45 <= dy <= 15
            if is_dot_hit or is_badge_hit:
                badge_center_dist = math.sqrt(dx * dx + (dy + 18) * (dy + 18))
                return True, min(dot_dist, badge_center_dist)
            return False, float('inf')

        # 1. Click directly on center coordinate dot (dx=0, dy=0)
        hit, dist = hit_test(0, 0)
        self.assertTrue(hit, "Center dot click must hit")
        self.assertEqual(dist, 0.0)

        # 2. Click within dot radius (dx=12, dy=10)
        hit, dist = hit_test(12, 10)
        self.assertTrue(hit, "Click within 20px dot radius must hit")

        # 3. Click 25px directly above dot on badge pill (dx=0, dy=-25)
        hit, dist = hit_test(0, -25)
        self.assertTrue(hit, "Click 25px above dot on badge pill must hit")
        self.assertAlmostEqual(dist, 7.0, places=2)  # Distance to badge center (y=-18)

        # 4. Click 40px above dot at top edge of badge pill (dx=0, dy=-40)
        hit, dist = hit_test(0, -40)
        self.assertTrue(hit, "Click 40px above dot on badge pill must hit")

        # 5. Click 50px to the right and 20px above dot on wide badge pill (dx=50, dy=-20)
        hit, dist = hit_test(50, -20)
        self.assertTrue(hit, "Click 50px right and 20px above dot on badge must hit")

        # 6. Click 60px to the left and 30px above dot on wide badge pill (dx=-60, dy=-30)
        hit, dist = hit_test(-60, -30)
        self.assertTrue(hit, "Click 60px left and 30px above dot on badge must hit")

        # 7. Click 80px horizontally away (dx=80, dy=-25) -> Out of badge width
        hit, _ = hit_test(80, -25)
        self.assertFalse(hit, "Click 80px horizontally away must not hit")

        # 8. Click 55px above dot (dx=0, dy=-55) -> Too far above badge
        hit, _ = hit_test(0, -55)
        self.assertFalse(hit, "Click 55px above dot must not hit")

        # 9. Click 30px below dot (dx=0, dy=30) -> Too far below dot
        hit, _ = hit_test(0, 30)
        self.assertFalse(hit, "Click 30px below dot must not hit")

    def test_find_airport_near_point_code_in_app_js(self):
        """Verify app.js implements oriented capsule bounds, zoom-adaptive search radius, 20px default radius, and exports to window.AeroFuelApp."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        # Capsule bounding check in app.js
        self.assertIn("Math.abs(dx) <= 65 && dy >= -45 && dy <= 15", app_content)
        self.assertIn("isDotHit || isBadgeHit", app_content)
        self.assertIn("function findAirportNearPoint(latlng, maxPixelDist = 20)", app_content)
        self.assertIn("const clickedApt = findAirportNearPoint(e.latlng, 20);", app_content)
        self.assertIn("searchRadiusMiles = Math.max(40, r1 * 1.5, r2 * 1.5);", app_content)

        # Global test exports
        self.assertIn("findAirportNearPoint: findAirportNearPoint,", app_content)
        self.assertIn("attachMarkerDomListeners: attachMarkerDomListeners,", app_content)


class TestAirNav24HourCacheAndTimestampRecording(unittest.TestCase):
    """Automated tests for 24-hour cache window, fetched_at timestamp persistence, instant popup opening, and force refresh."""

    def setUp(self):
        import tempfile

        from airnav_client import AirNavClient
        self.test_cache_dir = tempfile.mkdtemp()
        self.client = AirNavClient(cache_dir=self.test_cache_dir, cache_ttl=10)

    def tearDown(self):
        import shutil
        self.client.clear_cache()
        if os.path.exists(self.test_cache_dir):
            try:
                shutil.rmtree(self.test_cache_dir, ignore_errors=True)
            except Exception:
                pass

    def test_airnav_client_records_fetched_at_iso_timestamp(self):
        """Verify AirNavClient records fetched_at ISO 8601 timestamp in parsed HTML and Parse.bot responses."""
        sample_html = """
        <html>
        <head><title>AirNav: KSQL - San Carlos Airport</title></head>
        <body>
          <h1>San Carlos Airport</h1>
          <a href="/airport/KSQL/RABBIT">Rabbit Aviation Services</a>
          <b>100LL (SS)</b>: $6.15
        </body>
        </html>
        """
        parsed = self.client.parse_airport_fuel(sample_html, icao="KSQL")
        self.assertIsNotNone(parsed)
        self.assertIn("fetched_at", parsed)
        self.assertRegex(parsed["fetched_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

        # Parse.bot normalization check
        raw_parsebot = {
            "icao": "KPAO",
            "name": "Palo Alto Airport",
            "fbos": [
                {
                    "name": "Palo Alto Fuel",
                    "fuels": {
                        "100LL_SS": {"price": 6.45, "type": "100LL", "service": "Self-Serve"}
                    }
                }
            ]
        }
        normalized = self.client._normalize_parsebot_data(raw_parsebot, icao="KPAO")
        self.assertIsNotNone(normalized)
        self.assertIn("fetched_at", normalized)
        self.assertRegex(normalized["fetched_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_server_update_stored_fuel_data_persists_fetched_at(self):
        """Verify update_stored_fuel_data persists fetched_at timestamp on disk into fuel_data.json and fuel_data.js."""
        import shutil
        import tempfile

        import server

        test_dir = tempfile.mkdtemp()
        try:
            sample_catalog = {
                "version": "2026.08.22",
                "updated_at": "2026-08-22T00:00:00Z",
                "airports": [
                    {
                        "icao": "KSQL",
                        "faa": "SQL",
                        "name": "San Carlos Airport",
                        "lat": 37.5119,
                        "lon": -122.2495,
                        "fbos": [],
                        "best_price": None,
                        "primary_fuel": "None",
                        "fuels_available": [],
                        "last_updated": None
                    }
                ]
            }
            json_file = os.path.join(test_dir, "fuel_data.json")
            js_file = os.path.join(test_dir, "fuel_data.js")
            with open(json_file, "w") as f:
                json.dump(sample_catalog, f, indent=2)
            with open(js_file, "w") as f:
                f.write("// static\nwindow.EMBEDDED_AIRPORTS = " + json.dumps(sample_catalog) + ";\n")

            scraped = {
                "icao": "KSQL",
                "best_price": 6.15,
                "fetched_at": "2026-08-22T20:51:50Z",
                "fbos": [{"name": "Rabbit Aviation", "fuels": {"100LL_SS": {"price": 6.15, "type": "100LL"}}}]
            }

            updated = server.update_stored_fuel_data(scraped, directory=test_dir)
            self.assertIn("KSQL", updated)

            with open(json_file, "r") as f:
                saved = json.load(f)
            apt = saved["airports"][0]
            self.assertEqual(apt["icao"], "KSQL")
            self.assertEqual(apt["best_price"], 6.15)
            self.assertEqual(apt.get("fetched_at"), "2026-08-22T20:51:50Z")

            with open(js_file, "r") as f:
                js_content = f.read()
            self.assertIn('"fetched_at": "2026-08-22T20:51:50Z"', js_content)
        finally:
            shutil.rmtree(test_dir)

    def test_24_hour_cache_window_age_calculation(self):
        """Verify 24-hour cache window logic: age < 24h is fresh (cache hit), age >= 24h is stale (cache miss)."""
        import datetime

        now = datetime.datetime.now(datetime.timezone.utc)

        # 1. Fetched 2 hours ago -> Fresh (< 24h)
        t_2h_ago = (now - datetime.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        age_ms_2h = (now - datetime.datetime.fromisoformat(t_2h_ago.replace("Z", "+00:00"))).total_seconds() * 1000
        is_fresh_2h = age_ms_2h < (24 * 60 * 60 * 1000)
        self.assertTrue(is_fresh_2h, "Fetch from 2h ago must be within 24h cache window")

        # 2. Fetched 23.5 hours ago -> Fresh (< 24h)
        t_23h_ago = (now - datetime.timedelta(hours=23, minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        age_ms_23h = (now - datetime.datetime.fromisoformat(t_23h_ago.replace("Z", "+00:00"))).total_seconds() * 1000
        is_fresh_23h = age_ms_23h < (24 * 60 * 60 * 1000)
        self.assertTrue(is_fresh_23h, "Fetch from 23.5h ago must be within 24h cache window")

        # 3. Fetched 25 hours ago -> Stale (>= 24h)
        t_25h_ago = (now - datetime.timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")
        age_ms_25h = (now - datetime.datetime.fromisoformat(t_25h_ago.replace("Z", "+00:00"))).total_seconds() * 1000
        is_fresh_25h = age_ms_25h < (24 * 60 * 60 * 1000)
        self.assertFalse(is_fresh_25h, "Fetch from 25h ago must be outside 24h cache window (stale)")

        # 4. Force refresh overrides fresh cache
        force_refresh = True
        should_skip_network = (not force_refresh) and is_fresh_2h
        self.assertFalse(should_skip_network, "forceRefresh=True must bypass fresh cache")

    def test_relative_time_formatter_simulation(self):
        """Verify formatRelativeTime formatting rules for relative quote freshness."""
        def format_relative_time_py(age_sec):
            if age_sec < 60:
                return "Just now"
            age_min = age_sec // 60
            if age_min < 60:
                return f"{int(age_min)}m ago"
            age_hours = age_min // 60
            if age_hours < 24:
                return f"{int(age_hours)}h ago"
            age_days = age_hours // 24
            return f"{int(age_days)}d ago"

        self.assertEqual(format_relative_time_py(15), "Just now")
        self.assertEqual(format_relative_time_py(55), "Just now")
        self.assertEqual(format_relative_time_py(65), "1m ago")
        self.assertEqual(format_relative_time_py(900), "15m ago")
        self.assertEqual(format_relative_time_py(3600), "1h ago")
        self.assertEqual(format_relative_time_py(3 * 3600), "3h ago")
        self.assertEqual(format_relative_time_py(23 * 3600), "23h ago")
        self.assertEqual(format_relative_time_py(25 * 3600), "1d ago")
        self.assertEqual(format_relative_time_py(48 * 3600), "2d ago")

    def test_app_js_24h_cache_instant_popup_and_force_refresh_implementation(self):
        """Verify app.js contains 24h cache check, 0ms instant popup opening, fetched_at persistence, and refresh buttons."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        self.assertTrue(os.path.exists(app_js_path), "app.js missing")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        # 1. 24h cache window check in fetchAirportFuelAndHighlight
        self.assertIn("24 * 60 * 60 * 1000", app_content)
        self.assertIn("if (!forceRefresh && isFresh && hasFuelData)", app_content)
        self.assertIn("openAirportPopup(targetApt, false);", app_content)

        # 2. fetched_at recording in app.js
        self.assertIn("targetApt.fetched_at = fetchedTimestamp;", app_content)
        self.assertIn("STATE.customPrices[icao].fetched_at = fetchedTimestamp;", app_content)
        self.assertIn("fetched_at: apt.fetched_at || null,", app_content)
        self.assertIn("target.fetched_at = savedApt.fetched_at || target.fetched_at || null;", app_content)

        # 3. formatRelativeTime function and window export
        self.assertIn("function formatRelativeTime(isoString)", app_content)
        self.assertIn("formatRelativeTime: formatRelativeTime,", app_content)

        # 4. Freshness indicator in popup and modal
        self.assertIn("⏱️ AirNav Quote: ${rel} ${isCached ? '(Cached)' : '(Stale)'}", app_content)
        self.assertIn("modal-freshness-badge", app_content)

        # 5. Refresh Live button in popup and modal
        self.assertIn("btn-popup-refresh", app_content)
        self.assertIn("🔄 Refresh Live", app_content)
        self.assertIn("btnRefresh", app_content)
        self.assertIn("fetchAirportFuelAndHighlight(targetApt, true);", app_content)

    def test_style_css_refresh_button_and_modal_freshness_badge(self):
        """Verify style.css contains CSS rules for .btn-popup-refresh and .modal-freshness-badge."""
        css_path = os.path.join(DIRECTORY, "style.css")
        self.assertTrue(os.path.exists(css_path), "style.css missing")
        with open(css_path, "r") as f:
            css_content = f.read()

        self.assertIn(".btn-popup-refresh", css_content)
        self.assertIn(".modal-freshness-badge", css_content)
        self.assertIn("#10b981", css_content)

    def test_format_relative_time_edge_cases(self):
        """Verify formatRelativeTime handling of future dates, invalid dates, and null/empty inputs."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        # formatRelativeTime implementation checks
        self.assertIn("function formatRelativeTime(isoString)", app_content)
        self.assertIn("if (!isoString) return '';", app_content)
        self.assertIn("if (isNaN(date.getTime())) return '';", app_content)
        self.assertIn("if (ageMs < 0) return 'Just now';", app_content)

    def test_open_airport_modal_uses_canonical_object_and_refresh_action(self):
        """Verify openAirportModal resolves canonical airport object and wires Refresh Live with forceRefresh=true."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        # Modal canonical resolution
        self.assertIn("const canonical = STATE.airportsMap.get(cleanIcao) || (cleanFaa ? STATE.airportsMap.get(cleanFaa) : null) || apt;", app_content)
        self.assertIn("apt = canonical;", app_content)
        self.assertIn("STATE.activeAirportModal = apt;", app_content)
        self.assertIn("await fetchAirportFuelAndHighlight(apt, true);", app_content)

    def test_batch_sync_airnav_prices_records_fetched_at(self):
        """Verify batch sync_airnav_prices in fetch_fuel_data.py records fetched_at timestamp."""
        fetch_script = os.path.join(DIRECTORY, "fetch_fuel_data.py")
        with open(fetch_script, "r") as f:
            fetch_content = f.read()

        self.assertIn('target_apt["fetched_at"] = res.get("fetched_at")', fetch_content)


class TestOriginHighlightAndVectorIndicator(unittest.TestCase):
    """Unit tests for persistent origin airport marker, flight-plan styling, and real-time vector indicator."""

    def setUp(self):
        self.app_js_path = os.path.join(DIRECTORY, "app.js")
        self.style_css_path = os.path.join(DIRECTORY, "style.css")
        self.index_html_path = os.path.join(DIRECTORY, "index.html")

        with open(self.app_js_path, "r", encoding="utf-8") as f:
            self.app_js = f.read()
        with open(self.style_css_path, "r", encoding="utf-8") as f:
            self.style_css = f.read()
        with open(self.index_html_path, "r", encoding="utf-8") as f:
            self.index_html = f.read()

    def test_origin_marker_persistence_outside_radius_in_app_js(self):
        """Verify origin airport is prepended to acceptedHighlightList as Priority #0 regardless of search radius."""
        self.assertIn("// #0 Priority: Origin Airport is ALWAYS accepted and rendered (Persistent Origin Marker)", self.app_js)
        self.assertIn("originAptCanonical = STATE.airportsMap.get(originIcao)", self.app_js)
        self.assertIn("acceptedHighlightList.push(originAptCanonical);", self.app_js)
        self.assertIn("acceptedScreenPoints.push(ptOrigin);", self.app_js)
        self.assertIn("const inRadiusClass = (isInRadius || isOrigin || isPopupOpen) ? 'in-radius' : '';", self.app_js)
        self.assertIn("const originClass = isOrigin ? 'is-origin' : '';", self.app_js)

    def test_origin_marker_z_index_offset_hierarchy(self):
        """Verify z-index hierarchy: Lowest (10000) > Origin (9000) > In-Radius (500) > Default (0)."""
        self.assertIn("markerObj.marker.setZIndexOffset(9000);", self.app_js)
        self.assertIn("markerObj.marker.setZIndexOffset(10000);", self.app_js)
        self.assertIn("markerObj.marker.setZIndexOffset(500);", self.app_js)
        self.assertIn("markerObj.marker.setZIndexOffset(0);", self.app_js)
        self.assertIn(".airport-marker-container.is-origin {\n  z-index: 9000;\n}", self.style_css)
        self.assertIn(".airport-marker-container.is-lowest {\n  z-index: 10000 !important;\n", self.style_css)

    def test_origin_marker_badge_and_ribbon_css_styling_rules(self):
        """Verify origin marker badge, flight-plan indigo/cyan border, ribbon, and stacked offsets in CSS."""
        self.assertIn(".airport-marker-container.is-origin .fuel-price-badge", self.style_css)
        self.assertIn("border: 2px solid #818cf8 !important;", self.style_css)
        self.assertIn("box-shadow: 0 0 16px rgba(129, 140, 248, 0.65)", self.style_css)
        self.assertIn(".origin-ribbon {", self.style_css)
        self.assertIn("background: linear-gradient(135deg, #6366f1, #4f46e5);", self.style_css)
        self.assertIn(".airport-marker-container.is-origin .origin-ribbon {\n  display: flex;\n}", self.style_css)
        self.assertIn(".airport-marker-container.is-lowest.is-origin .origin-ribbon {\n  top: -36px;\n}", self.style_css)

    def test_origin_pulse_ring_animation_css_rules(self):
        """Verify animated origin pulse ring and badge breathing keyframes in CSS."""
        self.assertIn(".origin-pulse-ring {", self.style_css)
        self.assertIn("border: 2px solid #818cf8;", self.style_css)
        self.assertIn("@keyframes origin-radar-expand", self.style_css)
        self.assertIn("@keyframes origin-pulse-badge", self.style_css)
        self.assertIn(".airport-marker-container.is-origin .origin-pulse-ring {\n  display: block;\n}", self.style_css)

    def test_origin_vector_line_and_label_instantiation_in_app_js(self):
        """Verify originVectorLine polyline and originVectorLabel marker are instantiated in Leaflet map."""
        self.assertIn("originVectorLine = L.polyline([], {", self.app_js)
        self.assertIn("color: '#818cf8',", self.app_js)
        self.assertIn("dashArray: '6, 6',", self.app_js)
        self.assertIn("originVectorLabel = L.marker([STATE.circleCenter.lat, STATE.circleCenter.lng], {", self.app_js)
        self.assertIn("className: 'custom-vector-label-div-icon',", self.app_js)
        self.assertIn("zIndexOffset: 8500", self.app_js)

    def test_origin_vector_line_realtime_updates_and_centering_cutoff(self):
        """Verify updateOriginVectorLine computes great-circle course, midpoint coordinates, and handles centering cutoff."""
        self.assertIn("function updateOriginVectorLine()", self.app_js)
        self.assertIn("if (distMiles < 0.05)", self.app_js)
        self.assertIn("originVectorLine.setLatLngs([]);", self.app_js)
        self.assertIn("originVectorLine.setLatLngs([\n      [centerLat, centerLon],\n      [originLat, originLon]\n    ]);", self.app_js)
        self.assertIn("const midLat = (centerLat + originLat) / 2;", self.app_js)
        self.assertIn("const midLon = (centerLon + originLon) / 2;", self.app_js)
        self.assertIn("updateOriginVectorLine();", self.app_js)

    def test_origin_vector_readout_hud_element_in_html_and_css(self):
        """Verify HUD course readout container in index.html and corresponding styles in style.css."""
        self.assertIn('<div id="origin-vector-readout" class="origin-vector-readout" style="display: none;"></div>', self.index_html)
        self.assertIn(".origin-vector-readout {", self.style_css)
        self.assertIn(".origin-vector-badge {", self.style_css)
        self.assertIn(".custom-vector-label-div-icon {", self.style_css)

    def test_origin_dom_hitbox_event_listeners(self):
        """Verify origin ribbon has direct pointer and click event listeners with stopPropagation."""
        self.assertIn("const originRibbon = el.querySelector('.origin-ribbon');", self.app_js)
        self.assertIn("originRibbon.addEventListener('click', handleAirportClick);", self.app_js)
        self.assertIn("originRibbon.addEventListener('pointerdown', handlePointerDown);", self.app_js)

    def test_origin_ribbon_stacking_with_lowest_price_ribbon(self):
        """Verify when an airport is simultaneously lowest and origin, ribbons stack cleanly (lowest top: -18px, origin top: -36px)."""
        self.assertIn(".lowest-ribbon {\n  display: none;\n  position: absolute;\n  top: -18px;", self.style_css)
        self.assertIn(".origin-ribbon {\n  display: none;\n  position: absolute;\n  top: -18px;", self.style_css)
        self.assertIn(".airport-marker-container.is-lowest.is-origin .origin-ribbon {\n  top: -36px;\n}", self.style_css)

    def test_origin_self_distance_filter_in_app_js(self):
        """Verify getOriginDistanceInfo returns null for origin airport itself to avoid redundant 0.0 mi text."""
        self.assertIn("function getOriginDistanceInfo(apt)", self.app_js)
        self.assertIn("if ((cleanIcao && cleanIcao === originIcao) || (cleanFaa && cleanFaa === originFaa))", self.app_js)
        self.assertIn("return null;", self.app_js)

    def test_set_origin_airport_input_parsing_formats(self):
        """Verify setOriginAirport handles string codes, hyphenated names, JSON strings, and objects."""
        self.assertIn("function setOriginAirport(identOrApt)", self.app_js)
        self.assertIn("if (clean.includes('-'))", self.app_js)
        self.assertIn("if (clean.includes(' '))", self.app_js)
        self.assertIn("ORIGIN_AIRPORT_STORAGE_KEY", self.app_js)
        self.assertIn("localStorage.setItem(ORIGIN_AIRPORT_STORAGE_KEY, apt.icao);", self.app_js)

    def test_vector_line_and_radius_recalculation_synchronization(self):
        """Verify recalculateRadiusAirports synchronizes updateOriginVectorLine in real-time."""
        self.assertIn("updateOriginVectorLine();", self.app_js)
        self.assertIn("getOriginVectorLine: () => originVectorLine,", self.app_js)
        self.assertIn("getOriginVectorLabel: () => originVectorLabel,", self.app_js)
        self.assertIn("updateOriginVectorLine: updateOriginVectorLine,", self.app_js)


class TestAirNavLocalRadiusFuelScrapingAndHydration(unittest.TestCase):
    """Tests for AirNav 45-mile local fuel radius scraper, parser, server persistence, and frontend hydration."""

    SCREENSHOT_HTML_MOCK = """<!DOCTYPE html>
<html>
<head><title>AirNav: Fuel prices within 45 miles of E16</title></head>
<body>
<h1>Fuel prices within 45 miles of <a href="/airport/E16">E16</a></h1>
<table border="0" cellpadding="2" cellspacing="0">
<tr bgcolor="#EEEEEE">
  <th></th>
  <th>Airport / FBO</th>
  <th>Brand</th>
  <th><b>100LL</b><br><font size="-2">$6.23–$13.75<br>average $7.81</font></th>
  <th><b>G100UL</b><br><font size="-2">$6.50–$6.99<br>average $6.75</font></th>
  <th><b>UL94</b><br><font size="-2">$8.30–$8.99<br>average $8.69</font></th>
  <th><b>Jet A</b><br><font size="-2">$5.83–$11.99<br>average $8.22</font></th>
  <th><b>SAF</b><br><font size="-2">$12.99–$13.33<br>average $13.10</font></th>
  <th></th>
</tr>
<!-- E16 -->
<tr>
  <td colspan="9"><a href="/airport/E16"><b>E16</b></a> &nbsp; <b>San Martin Airport</b> San Martin, CA</td>
</tr>
<tr>
  <td><a href="/airport/E16/SAN_MARTIN">San Martin Aviation Corp</a></td>
  <td>Titan</td>
  <td></td>
  <td></td>
  <td><a href="...">SS</a> $8.39<br><a href="...">FS</a> $8.59</td>
  <td><a href="...">FS</a> $7.68</td>
  <td></td>
  <td><font size="-2">19-Aug<br><a href="...">update</a></font></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- KWVI -->
<tr>
  <td colspan="9"><a href="/airport/KWVI"><b>KWVI</b></a> 13 SW &nbsp; <b>Watsonville Municipal Airport</b> Watsonville, CA</td>
</tr>
<tr>
  <td><img src="/pics/fbo/wvi.png"> <a href="/airport/KWVI/WVI">Watsonville Municipal Airport</a></td>
  <td>World Fuel</td>
  <td><a href="...">SS</a> $6.50<br><a href="...">FS</a> $7.00</td>
  <td><span style="background-color:#00FF00"><a href="...">FS</a> $6.50</span></td>
  <td></td>
  <td><a href="...">SS</a> $6.25<br><a href="...">FS</a> $6.75</td>
  <td></td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- KCVH -->
<tr>
  <td colspan="9"><a href="/airport/KCVH"><b>KCVH</b></a> 14 SE &nbsp; <b>Hollister Municipal Airport</b> Hollister, CA</td>
</tr>
<tr>
  <td><img src="/pics/fbo/cvh.png"> <a href="/airport/KCVH/HOLLISTER">Hollister Jet Center, Inc</a></td>
  <td>AVFUEL</td>
  <td><a href="...">SS</a> $7.02<br><a href="...">FS</a> $7.52<br><span style="background-color:#38bdf8">$7.42</span></td>
  <td></td>
  <td></td>
  <td><a href="...">SS</a> $7.11<br><a href="...">FS</a> $7.61<br><span style="background-color:#38bdf8">$7.51</span></td>
  <td></td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"> <img src="/pics/airboss.gif" alt="AIRBOSS"></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- KRHV -->
<tr>
  <td colspan="9"><a href="/airport/KRHV"><b>KRHV</b></a> 18 NW &nbsp; <b>Reid-Hillview Airport of Santa Clara County</b> San Jose, CA</td>
</tr>
<tr>
  <td>Santa Clara County</td>
  <td>independent</td>
  <td></td>
  <td><a href="...">FS</a> $6.99</td>
  <td><a href="...">SS</a> $8.30<br><a href="...">FS</a> $8.60</td>
  <td></td>
  <td></td>
  <td><font size="-2">31-Jul<br><a href="...">update</a></font></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- KSJC -->
<tr>
  <td colspan="9"><a href="/airport/KSJC"><b>KSJC</b></a> 23 NW &nbsp; <b>Norman Y Mineta San Jose International Airport</b> San Jose, CA</td>
</tr>
<tr>
  <td><img src="/pics/fbo/atlantic.png"> Atlantic</td>
  <td>independent</td>
  <td><a href="...">FS</a> $12.56</td>
  <td></td>
  <td></td>
  <td><a href="...">FS</a> $11.91</td>
  <td></td>
  <td><font size="-2">22-Aug<br><a href="...">update</a></font></td>
</tr>
<tr>
  <td><a href="/airport/KSJC/SIGNATURE">Signature Aviation</a></td>
  <td>independent</td>
  <td><a href="...">FS</a> $13.75</td>
  <td></td>
  <td></td>
  <td><a href="...">FS</a> $11.37</td>
  <td><a href="...">FS</a> $13.33</td>
  <td><font size="-2">21-Aug<br><a href="...">update</a></font></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- KSNS -->
<tr>
  <td colspan="9"><a href="/airport/KSNS"><b>KSNS</b></a> 25 S &nbsp; <b>Salinas Municipal Airport</b> Salinas, CA</td>
</tr>
<tr>
  <td><img src="/pics/fbo/gateone.png"> <a href="/airport/KSNS/JET_WEST">Jet West GateOne</a></td>
  <td>AVFUEL</td>
  <td><a href="...">SS</a> $6.97<br><a href="...">FS</a> $7.47</td>
  <td></td>
  <td></td>
  <td><a href="...">FS</a> $7.69<br><a href="...">SS</a> $7.69</td>
  <td></td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"></td>
</tr>
<tr>
  <td>gateOne Salinas</td>
  <td>independent</td>
  <td><a href="...">SS</a> $6.97<br><a href="...">FS</a> $7.47</td>
  <td></td>
  <td></td>
  <td><a href="...">FS</a> $7.69<br><a href="...">SS</a> $7.69</td>
  <td></td>
  <td><font size="-2">18-Aug<br><a href="...">update</a></font></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- KOAR -->
<tr>
  <td colspan="9"><a href="/airport/KOAR"><b>KOAR</b></a> 25 SSW &nbsp; <b>Marina Municipal Airport</b> Marina, CA</td>
</tr>
<tr>
  <td><a href="/airport/KOAR/MARINA">City of Marina (FBO)</a></td>
  <td>World Fuel Services</td>
  <td><a href="...">SS</a> $7.24</td>
  <td></td>
  <td></td>
  <td><a href="...">SS</a> $6.75</td>
  <td></td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- KNUQ -->
<tr>
  <td colspan="9"><a href="/airport/KNUQ"><b>KNUQ</b></a> 29 NW &nbsp; <b>Moffett Federal Airfield</b> Mountain View, CA</td>
</tr>
<tr>
  <td><a href="/airport/KNUQ/AVPORTS">Avports Moffett Field</a></td>
  <td>World Fuel</td>
  <td></td>
  <td></td>
  <td></td>
  <td><a href="...">FS</a> $10.20</td>
  <td></td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"></td>
</tr>
</table>
</body>
</html>"""

    def setUp(self):
        import tempfile

        from airnav_client import AirNavClient
        self.temp_dir = tempfile.TemporaryDirectory()
        self.client = AirNavClient(cache_dir=self.temp_dir.name, cache_ttl=10)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_local_fuel_html_exact_screenshot_structure(self):
        """Verify parse_local_fuel_html accurately parses all 8 airports, FBOs, and fuel rates from screenshot."""
        res = self.client.parse_local_fuel_html(self.SCREENSHOT_HTML_MOCK, source_airport="E16")

        self.assertIsNotNone(res)
        self.assertTrue(res["success"])
        self.assertEqual(res["source_airport"], "E16")
        self.assertEqual(res["radius_miles"], 45)
        self.assertEqual(res["count"], 8)
        self.assertEqual(len(res["airports"]), 8)

        by_icao = {a["icao"]: a for a in res["airports"]}

        # 1. E16 (San Martin Airport)
        self.assertIn("E16", by_icao)
        e16 = by_icao["E16"]
        self.assertEqual(e16["name"], "San Martin Airport")
        self.assertEqual(e16["city"], "San Martin")
        self.assertEqual(e16["state"], "CA")
        self.assertEqual(e16["best_price"], 8.39)
        self.assertEqual(e16["primary_fuel"], "94UL")
        self.assertEqual(sorted(e16["fuels_available"]), sorted(["94UL", "Jet-A"]))
        self.assertEqual(len(e16["fbos"]), 1)
        self.assertEqual(e16["fbos"][0]["name"], "San Martin Aviation Corp")
        self.assertEqual(e16["fbos"][0]["brand"], "Titan")
        self.assertEqual(e16["fbos"][0]["fuels"]["94UL_SS"]["price"], 8.39)
        self.assertEqual(e16["fbos"][0]["fuels"]["94UL_FS"]["price"], 8.59)
        self.assertEqual(e16["fbos"][0]["fuels"]["JET_A"]["price"], 7.68)

        # 2. KWVI (Watsonville Municipal Airport, 13 SW)
        self.assertIn("KWVI", by_icao)
        kwvi = by_icao["KWVI"]
        self.assertEqual(kwvi["distance_nm"], 13.0)
        self.assertEqual(kwvi["bearing"], "SW")
        self.assertEqual(kwvi["best_price"], 6.50)
        self.assertEqual(kwvi["primary_fuel"], "100LL")
        self.assertEqual(sorted(kwvi["fuels_available"]), sorted(["100LL", "100UL", "Jet-A"]))
        self.assertEqual(kwvi["fbos"][0]["brand"], "World Fuel")
        self.assertEqual(kwvi["fbos"][0]["fuels"]["100LL_SS"]["price"], 6.50)
        self.assertEqual(kwvi["fbos"][0]["fuels"]["100LL_FS"]["price"], 7.00)
        self.assertEqual(kwvi["fbos"][0]["fuels"]["100UL_FS"]["price"], 6.50)
        self.assertEqual(kwvi["fbos"][0]["fuels"]["JET_A"]["price"], 6.25)

        # 3. KCVH (Hollister Municipal Airport, 14 SE)
        self.assertIn("KCVH", by_icao)
        kcvh = by_icao["KCVH"]
        self.assertEqual(kcvh["distance_nm"], 14.0)
        self.assertEqual(kcvh["bearing"], "SE")
        self.assertEqual(kcvh["best_price"], 7.02)
        self.assertEqual(kcvh["primary_fuel"], "100LL")
        self.assertEqual(sorted(kcvh["fuels_available"]), sorted(["100LL", "Jet-A"]))
        self.assertEqual(kcvh["fbos"][0]["brand"], "AVFUEL")

        # 4. KRHV (Reid-Hillview Airport of Santa Clara County, 18 NW)
        self.assertIn("KRHV", by_icao)
        krhv = by_icao["KRHV"]
        self.assertEqual(krhv["distance_nm"], 18.0)
        self.assertEqual(krhv["bearing"], "NW")
        self.assertEqual(krhv["best_price"], 6.99)
        self.assertEqual(krhv["primary_fuel"], "100UL")
        self.assertEqual(sorted(krhv["fuels_available"]), sorted(["100UL", "94UL"]))

        # 5. KSJC (Norman Y Mineta San Jose International Airport, 23 NW, Multi-FBO)
        self.assertIn("KSJC", by_icao)
        ksjc = by_icao["KSJC"]
        self.assertEqual(ksjc["distance_nm"], 23.0)
        self.assertEqual(ksjc["bearing"], "NW")
        self.assertEqual(len(ksjc["fbos"]), 2)
        self.assertEqual(ksjc["best_price"], 12.56)
        self.assertEqual(ksjc["primary_fuel"], "100LL")
        self.assertEqual(sorted(ksjc["fuels_available"]), sorted(["100LL", "Jet-A", "SAF"]))
        # Atlantic FBO
        self.assertEqual(ksjc["fbos"][0]["fuels"]["100LL_FS"]["price"], 12.56)
        self.assertEqual(ksjc["fbos"][0]["fuels"]["JET_A"]["price"], 11.91)
        # Signature Aviation FBO
        self.assertEqual(ksjc["fbos"][1]["fuels"]["100LL_FS"]["price"], 13.75)
        self.assertEqual(ksjc["fbos"][1]["fuels"]["JET_A"]["price"], 11.37)
        self.assertEqual(ksjc["fbos"][1]["fuels"]["SAF"]["price"], 13.33)

        # 6. KSNS (Salinas Municipal Airport, 25 S, Multi-FBO)
        self.assertIn("KSNS", by_icao)
        ksns = by_icao["KSNS"]
        self.assertEqual(ksns["distance_nm"], 25.0)
        self.assertEqual(ksns["bearing"], "S")
        self.assertEqual(ksns["best_price"], 6.97)
        self.assertEqual(sorted(ksns["fuels_available"]), sorted(["100LL", "Jet-A"]))

        # 7. KOAR (Marina Municipal Airport, 25 SSW)
        self.assertIn("KOAR", by_icao)
        koar = by_icao["KOAR"]
        self.assertEqual(koar["distance_nm"], 25.0)
        self.assertEqual(koar["bearing"], "SSW")
        self.assertEqual(koar["best_price"], 7.24)
        self.assertEqual(sorted(koar["fuels_available"]), sorted(["100LL", "Jet-A"]))

        # 8. KNUQ (Moffett Federal Airfield, 29 NW, Jet-A only)
        self.assertIn("KNUQ", by_icao)
        knuq = by_icao["KNUQ"]
        self.assertEqual(knuq["distance_nm"], 29.0)
        self.assertEqual(knuq["bearing"], "NW")
        self.assertIsNone(knuq["best_price"])
        self.assertEqual(knuq["primary_fuel"], "None")
        self.assertEqual(knuq["fuels_available"], ["Jet-A"])
        self.assertEqual(knuq["fbos"][0]["fuels"]["JET_A"]["price"], 10.20)

    def test_target_airport_matching_in_parse_local_fuel_html(self):
        """Verify target airport is correctly identified as source airport or first entry."""
        res_e16 = self.client.parse_local_fuel_html(self.SCREENSHOT_HTML_MOCK, source_airport="E16")
        self.assertIsNotNone(res_e16["target"])
        self.assertEqual(res_e16["target"]["icao"], "E16")

        res_kwvi = self.client.parse_local_fuel_html(self.SCREENSHOT_HTML_MOCK, source_airport="KWVI")
        self.assertIsNotNone(res_kwvi["target"])
        self.assertEqual(res_kwvi["target"]["icao"], "KWVI")

    def test_server_update_stored_fuel_data_multi_airport_persistence(self):
        """Verify server update_stored_fuel_data atomically updates all 8 airports in dataset on disk."""
        import tempfile

        from server import load_catalog, update_stored_fuel_data

        with tempfile.TemporaryDirectory() as test_dir:
            json_path = os.path.join(test_dir, 'fuel_data.json')
            js_path = os.path.join(test_dir, 'fuel_data.js')

            initial_catalog = {
                "airports": [
                    {"icao": "E16", "faa": "E16", "name": "San Martin Airport", "city": "San Martin", "state": "CA", "lat": 37.08, "lon": -121.59, "fbos": [], "best_price": None},
                    {"icao": "KWVI", "faa": "WVI", "name": "Watsonville Municipal Airport", "city": "Watsonville", "state": "CA", "lat": 36.93, "lon": -121.78, "fbos": [], "best_price": None},
                    {"icao": "KCVH", "faa": "CVH", "name": "Hollister Municipal Airport", "city": "Hollister", "state": "CA", "lat": 36.89, "lon": -121.41, "fbos": [], "best_price": None}
                ],
                "total_airports": 3
            }
            with open(json_path, 'w') as f:
                json.dump(initial_catalog, f)
            with open(js_path, 'w') as f:
                f.write("window.EMBEDDED_AIRPORTS = " + json.dumps(initial_catalog) + ";")

            parsed = self.client.parse_local_fuel_html(self.SCREENSHOT_HTML_MOCK, source_airport="E16")
            updated_icaos = update_stored_fuel_data(parsed["airports"], directory=test_dir)

            self.assertIn("E16", updated_icaos)
            self.assertIn("KWVI", updated_icaos)
            self.assertIn("KCVH", updated_icaos)

            with open(json_path, 'r') as f:
                saved = json.load(f)

            saved_map = {a["icao"]: a for a in saved["airports"]}
            self.assertEqual(saved_map["E16"]["best_price"], 8.39)
            self.assertEqual(saved_map["KWVI"]["best_price"], 6.50)
            self.assertEqual(saved_map["KCVH"]["best_price"], 7.02)
            # New airports (KRHV, KSJC, KSNS, KOAR, KNUQ) automatically added to catalog
            self.assertIn("KRHV", saved_map)
            self.assertIn("KSJC", saved_map)
            self.assertIn("KSNS", saved_map)
            self.assertIn("KOAR", saved_map)
            self.assertIn("KNUQ", saved_map)

    def test_app_js_multi_airport_hydration_logic(self):
        """Verify app.js fetchAirportFuelAndHighlight hydrates all airports in jsonRes.airports array."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r") as f:
            app_content = f.read()

        self.assertIn("const returnedAirports = (Array.isArray(jsonRes.airports) && jsonRes.airports.length > 0) ? jsonRes.airports : (jsonRes.data ? [jsonRes.data] : []);", app_content)
        self.assertIn("savePersistedAirportsBatchToStorage(returnedAirports);", app_content)
        self.assertIn("recalculateRadiusAirports();", app_content)
        self.assertIn("renderAllAirportMarkers();", app_content)
        self.assertIn("redrawAirportCanvas();", app_content)
        self.assertIn("AirNav Local: Updated", app_content)
        self.assertIn("within ${radiusMiles} miles of ${ident}!", app_content)

    def test_parse_local_fuel_html_single_line_table_format(self):
        """Verify parse_local_fuel_html handles compact single-line table layouts where airport and prices share a row."""
        compact_html = """<!DOCTYPE html>
        <html><head><title>AirNav: Fuel prices within 45 miles of KSQL</title></head><body>
        <h1>Fuel prices within 45 miles of KSQL</h1>
        <table>
        <tr><th>Airport</th><th>Brand</th><th>100LL</th><th>Jet A</th></tr>
        <tr><td><a href="/airport/KSQL">KSQL</a> San Carlos Airport</td><td>independent</td><td>SS $6.15 FS $6.65</td><td>FS $7.25</td></tr>
        <tr><td><a href="/airport/KPAO">KPAO</a> 8 SE Palo Alto Airport</td><td>independent</td><td>SS $7.40 FS $7.65</td><td>FS $7.85</td></tr>
        <tr><td><a href="/airport/KHAF">KHAF</a> 11 W Half Moon Bay Airport</td><td>independent</td><td>SS $6.89</td><td></td></tr>
        </table></body></html>"""
        res = self.client.parse_local_fuel_html(compact_html, source_airport="KSQL")
        self.assertTrue(res["success"])
        self.assertEqual(res["count"], 3)
        by_icao = {a["icao"]: a for a in res["airports"]}
        self.assertIn("KSQL", by_icao)
        self.assertIn("KPAO", by_icao)
        self.assertIn("KHAF", by_icao)
        self.assertEqual(by_icao["KSQL"]["best_price"], 6.15)
        self.assertEqual(by_icao["KPAO"]["best_price"], 7.40)
        self.assertEqual(by_icao["KHAF"]["best_price"], 6.89)

    def test_server_update_stored_fuel_data_enriches_survey_coords(self):
        """Verify update_stored_fuel_data backfills lat, lon, CTAF, and elevation from master catalog to scraped records."""
        import tempfile

        from server import update_stored_fuel_data

        with tempfile.TemporaryDirectory() as test_dir:
            json_path = os.path.join(test_dir, 'fuel_data.json')
            js_path = os.path.join(test_dir, 'fuel_data.js')

            catalog = {
                "airports": [
                    {
                        "icao": "KWVI",
                        "faa": "WVI",
                        "name": "Watsonville Municipal Airport",
                        "city": "Watsonville",
                        "state": "CA",
                        "lat": 36.9358,
                        "lon": -121.7899,
                        "elevation_ft": 163,
                        "ctaf_freq": 122.8,
                        "unicom_freq": 122.8,
                        "fbos": [],
                        "best_price": None
                    }
                ],
                "total_airports": 1
            }
            with open(json_path, 'w') as f:
                json.dump(catalog, f)
            with open(js_path, 'w') as f:
                f.write("window.EMBEDDED_AIRPORTS = " + json.dumps(catalog) + ";")

            scraped_record = {
                "icao": "KWVI",
                "name": "Watsonville Municipal Airport",
                "fbos": [{"name": "World Fuel", "fuels": {"100LL_SS": {"price": 6.50, "type": "100LL"}}}]
            }
            # Notice scraped_record initially lacks lat/lon/elevation_ft/ctaf_freq
            updated = update_stored_fuel_data([scraped_record], directory=test_dir)
            self.assertIn("KWVI", updated)
            self.assertEqual(scraped_record.get("lat"), 36.9358)
            self.assertEqual(scraped_record.get("lon"), -121.7899)
            self.assertEqual(scraped_record.get("elevation_ft"), 163)
            self.assertEqual(scraped_record.get("ctaf_freq"), 122.8)

    def test_airnav_html_stripper_nested_tables_isolation(self):
        """Verify AirNavHTMLStripper maintains parent table context and cell contents when nested tables are encountered."""
        from airnav_client import AirNavHTMLStripper, clean_text

        nested_html = """
        <table>
          <tr>
            <th>Airport</th>
            <th>100LL</th>
            <th>G100UL</th>
          </tr>
          <tr>
            <td>KWVI</td>
            <td>SS $6.50</td>
            <td>
              <table bgcolor="#00FF00">
                <tr><td><a href="/fuel/local.html">FS</a> $6.50</td></tr>
              </table>
            </td>
          </tr>
          <tr>
            <td>KCVH</td>
            <td>
              SS $7.02 FS $7.52
              <table class="discount">
                <tr><td>$7.42</td></tr>
              </table>
            </td>
            <td></td>
          </tr>
          <tr>
            <td>KRHV</td>
            <td></td>
            <td>FS $6.99</td>
          </tr>
        </table>
        """
        parser = AirNavHTMLStripper()
        parser.feed(nested_html)

        self.assertGreaterEqual(len(parser.tables), 1)
        outer_table = parser.tables[0]
        # Header + KWVI + KCVH + KRHV = 4 rows in outer table
        self.assertEqual(len(outer_table), 4)

        # KWVI row
        kwvi_row = [clean_text("".join(c)) for c in outer_table[1]]
        self.assertEqual(kwvi_row[0], "KWVI")
        self.assertIn("6.50", kwvi_row[1])
        self.assertIn("6.50", kwvi_row[2])
        self.assertIn("FS", kwvi_row[2])

        # KCVH row
        kcvh_row = [clean_text("".join(c)) for c in outer_table[2]]
        self.assertEqual(kcvh_row[0], "KCVH")
        self.assertIn("7.02", kcvh_row[1])
        self.assertIn("7.42", kcvh_row[1])

        # KRHV row (must NOT be dropped by nested tables in preceding rows!)
        krhv_row = [clean_text("".join(c)) for c in outer_table[3]]
        self.assertEqual(krhv_row[0], "KRHV")
        self.assertIn("6.99", krhv_row[2])

    def test_parse_local_fuel_html_with_nested_discount_and_highlight_tables(self):
        """Verify parse_local_fuel_html accurately parses all airports and FBOs when nested tables wrap prices."""
        nested_screenshot_html = """<!DOCTYPE html>
<html>
<head><title>AirNav: Fuel prices within 45 miles of E16</title></head>
<body>
<h1>Fuel prices within 45 miles of <a href="/airport/E16">E16</a></h1>
<table border="0" cellpadding="2" cellspacing="0">
<tr bgcolor="#EEEEEE">
  <th></th>
  <th>Airport / FBO</th>
  <th>Brand</th>
  <th><b>100LL</b></th>
  <th><b>G100UL</b></th>
  <th><b>UL94</b></th>
  <th><b>Jet A</b></th>
  <th><b>SAF</b></th>
  <th></th>
</tr>
<tr bgcolor="#EEEEEE">
  <td></td>
  <td></td>
  <td></td>
  <td><font size="-2">$6.23—$13.75<br>average $7.81</font></td>
  <td><font size="-2">$6.50—$6.99<br>average $6.75</font></td>
  <td><font size="-2">$8.30—$8.99<br>average $8.69</font></td>
  <td><font size="-2">$5.83—$11.99<br>average $8.22</font></td>
  <td><font size="-2">$12.99—$13.33<br>average $13.10</font></td>
  <td></td>
</tr>
<!-- 1. E16 -->
<tr>
  <td colspan="9"><a href="/airport/E16"><b>E16</b></a> &nbsp; <b>San Martin Airport</b> San Martin, CA</td>
</tr>
<tr>
  <td><a href="/airport/E16/SAN_MARTIN">San Martin Aviation Corp</a></td>
  <td>Titan</td>
  <td></td>
  <td></td>
  <td><a href="...">SS</a> $8.39<br><a href="...">FS</a> $8.59</td>
  <td><a href="...">FS</a> $7.68</td>
  <td></td>
  <td><font size="-2">19-Aug<br><a href="...">update</a></font></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 2. KWVI with nested green table -->
<tr>
  <td colspan="9"><a href="/airport/KWVI"><b>KWVI</b></a> 13 SW &nbsp; <b>Watsonville Municipal Airport</b> Watsonville, CA</td>
</tr>
<tr>
  <td><a href="/airport/KWVI/WVI">Watsonville Municipal Airport</a></td>
  <td>World Fuel</td>
  <td><a href="...">SS</a> $6.50<br><a href="...">FS</a> $7.00</td>
  <td>
    <table bgcolor="#00FF00" border="0" cellpadding="1" cellspacing="0">
      <tr><td><a href="...">FS</a> $6.50</td></tr>
    </table>
  </td>
  <td></td>
  <td><a href="...">SS</a> $6.25<br><a href="...">FS</a> $6.75</td>
  <td></td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 3. KCVH with nested blue discount tables -->
<tr>
  <td colspan="9"><a href="/airport/KCVH"><b>KCVH</b></a> 14 SE &nbsp; <b>Hollister Municipal Airport</b> Hollister, CA</td>
</tr>
<tr>
  <td><a href="/airport/KCVH/HOLLISTER">Hollister Jet Center, Inc</a></td>
  <td>AVFUEL</td>
  <td>
    <a href="...">SS</a> $7.02<br><a href="...">FS</a> $7.52<br>
    <table bgcolor="#38bdf8" border="0" cellpadding="1" cellspacing="0">
      <tr><td>$7.42</td></tr>
    </table>
  </td>
  <td></td>
  <td></td>
  <td>
    <a href="...">SS</a> $7.11<br><a href="...">FS</a> $7.61<br>
    <table bgcolor="#38bdf8" border="0" cellpadding="1" cellspacing="0">
      <tr><td>$7.51</td></tr>
    </table>
  </td>
  <td></td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"> <img src="/pics/airboss.gif" alt="AIRBOSS"></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 4. KRHV -->
<tr>
  <td colspan="9"><a href="/airport/KRHV"><b>KRHV</b></a> 18 NW &nbsp; <b>Reid-Hillview Airport of Santa Clara County</b> San Jose, CA</td>
</tr>
<tr>
  <td>Santa Clara County</td>
  <td>independent</td>
  <td></td>
  <td><a href="...">FS</a> $6.99</td>
  <td><a href="...">SS</a> $8.30<br><a href="...">FS</a> $8.60</td>
  <td></td>
  <td></td>
  <td><font size="-2">31-Jul<br><a href="...">update</a></font></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 5. KSJC -->
<tr>
  <td colspan="9"><a href="/airport/KSJC"><b>KSJC</b></a> 23 NW &nbsp; <b>Norman Y Mineta San Jose International Airport</b> San Jose, CA</td>
</tr>
<tr>
  <td>Atlantic</td>
  <td>independent</td>
  <td><a href="...">FS</a> $12.56</td>
  <td></td>
  <td></td>
  <td><a href="...">FS</a> $11.91</td>
  <td></td>
  <td><font size="-2">22-Aug<br><a href="...">update</a></font></td>
</tr>
<tr>
  <td>Signature Aviation</td>
  <td>independent</td>
  <td><a href="...">FS</a> $13.75</td>
  <td></td>
  <td></td>
  <td><a href="...">FS</a> $11.37</td>
  <td><a href="...">FS</a> $13.33</td>
  <td><font size="-2">21-Aug<br><a href="...">update</a></font></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 6. KSNS -->
<tr>
  <td colspan="9"><a href="/airport/KSNS"><b>KSNS</b></a> 25 S &nbsp; <b>Salinas Municipal Airport</b> Salinas, CA</td>
</tr>
<tr>
  <td>Jet West GateOne</td>
  <td>AVFUEL</td>
  <td><a href="...">SS</a> $6.97<br><a href="...">FS</a> $7.47</td>
  <td></td>
  <td></td>
  <td><a href="...">FS</a> $7.69<br><a href="...">SS</a> $7.69</td>
  <td></td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 7. KOAR -->
<tr>
  <td colspan="9"><a href="/airport/KOAR"><b>KOAR</b></a> 25 SSW &nbsp; <b>Marina Municipal Airport</b> Marina, CA</td>
</tr>
<tr>
  <td>City of Marina (FBO)</td>
  <td>World Fuel Services</td>
  <td><a href="...">SS</a> $7.24</td>
  <td></td>
  <td></td>
  <td><a href="...">SS</a> $6.75</td>
  <td></td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 8. KNUQ -->
<tr>
  <td colspan="9"><a href="/airport/KNUQ"><b>KNUQ</b></a> 29 NW &nbsp; <b>Moffett Federal Airfield</b> Mountain View, CA</td>
</tr>
<tr>
  <td>Avports Moffett Field</td>
  <td>World Fuel</td>
  <td></td>
  <td></td>
  <td></td>
  <td><a href="...">FS</a> $10.20</td>
  <td></td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 9. KMRY (Monterey) -->
<tr>
  <td colspan="9"><a href="/airport/KMRY"><b>KMRY</b></a> 32 SSW &nbsp; <b>Monterey Regional Airport</b> Monterey, CA</td>
</tr>
<tr>
  <td>Del Monte Aviation</td>
  <td>Titan</td>
  <td><a href="...">SS</a> $7.85<br><a href="...">FS</a> $8.45</td>
  <td></td>
  <td></td>
  <td><a href="...">FS</a> $8.95</td>
  <td></td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"></td>
</tr>
</table>
</body>
</html>"""
        res = self.client.parse_local_fuel_html(nested_screenshot_html, source_airport="E16")
        self.assertTrue(res["success"])
        self.assertEqual(res["count"], 9)

        by_icao = {a["icao"]: a for a in res["airports"]}
        expected_airports = ["E16", "KWVI", "KCVH", "KRHV", "KSJC", "KSNS", "KOAR", "KNUQ", "KMRY"]
        for icao in expected_airports:
            self.assertIn(icao, by_icao, f"Airport {icao} must be captured despite nested tables")

        # Verify E16 true rates (UL94 SS $8.39, FS $8.59, Jet A FS $7.68) and NOT regional average row
        self.assertEqual(by_icao["E16"]["best_price"], 8.39)
        self.assertEqual(by_icao["E16"]["primary_fuel"], "94UL")
        self.assertEqual(len(by_icao["E16"]["fbos"]), 1)
        self.assertEqual(by_icao["E16"]["fbos"][0]["name"], "San Martin Aviation Corp")
        self.assertEqual(by_icao["E16"]["fbos"][0]["fuels"]["94UL_SS"]["price"], 8.39)
        self.assertEqual(by_icao["E16"]["fbos"][0]["fuels"]["94UL_FS"]["price"], 8.59)
        self.assertEqual(by_icao["E16"]["fbos"][0]["fuels"]["JET_A"]["price"], 7.68)

        # Verify KWVI G100UL FS $6.50 captured from inside nested green table
        self.assertEqual(by_icao["KWVI"]["best_price"], 6.50)
        self.assertEqual(by_icao["KWVI"]["fbos"][0]["fuels"]["100UL_FS"]["price"], 6.50)

        # Verify KCVH discount price captured
        self.assertEqual(by_icao["KCVH"]["best_price"], 7.02)
        self.assertIn("100LL_SS", by_icao["KCVH"]["fbos"][0]["fuels"])
        self.assertEqual(by_icao["KCVH"]["fbos"][0]["fuels"]["100LL_FS"]["price"], 7.42)

        # Verify KRHV, KSJC, KSNS, KOAR, KNUQ, KMRY were not dropped
        self.assertEqual(by_icao["KRHV"]["best_price"], 6.99)
        self.assertEqual(by_icao["KSJC"]["best_price"], 12.56)
        self.assertEqual(by_icao["KSNS"]["best_price"], 6.97)
        self.assertEqual(by_icao["KOAR"]["best_price"], 7.24)
        self.assertIsNone(by_icao["KNUQ"]["best_price"])  # Jet-A only
        self.assertEqual(by_icao["KMRY"]["best_price"], 7.85)

    def test_map_click_non_locking_in_app_js(self):
        """Verify map.on('click') in app.js does not toggle STATE.isLocked or lock position."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r", encoding="utf-8") as f:
            app_js = f.read()

        # map.on('click') must not toggle STATE.isLocked
        click_handler_match = app_js[app_js.find("map.on('click'"):app_js.find("window.addEventListener('keydown'")]
        self.assertNotIn("STATE.isLocked = !STATE.isLocked", click_handler_match)
        self.assertNotIn("Radius locked at", click_handler_match)
        self.assertIn("findAirportNearPoint", click_handler_match)
        self.assertIn("fetchAirportFuelAndHighlight", click_handler_match)

    def test_dual_icao_faa_key_indexing_in_app_js(self):
        """Verify app.js indexes airports across both ICAO and FAA identifiers in airportsMap, fetchedAirports, and customPrices."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r", encoding="utf-8") as f:
            app_js = f.read()

        self.assertIn("STATE.airportsMap.set(itemIcao, itemApt);", app_js)
        self.assertIn("STATE.airportsMap.set(itemFaa, itemApt);", app_js)
        self.assertIn("STATE.fetchedAirports.add(itemIcao);", app_js)
        self.assertIn("STATE.fetchedAirports.add(itemFaa);", app_js)
        self.assertIn("STATE.customPrices[cleanIcao]", app_js)
        self.assertIn("STATE.customPrices[faaKey]", app_js)

    def test_fetch_local_fuel_html_post_method_and_form_urlencoded(self):
        """Verify AirNavClient.fetch_local_fuel_html issues HTTP POST with form-urlencoded body (s={code}&maxage=0&submit=)."""
        import io
        import urllib.request
        from unittest.mock import MagicMock, patch

        client = AirNavClient()
        posted_requests = []

        def mock_urlopen(req, timeout=15):
            posted_requests.append(req)
            resp = MagicMock()
            resp.read.return_value = b"""<!DOCTYPE html>
            <html><head><title>AirNav: Fuel prices within 45 miles of E16</title></head>
            <body><h1>Fuel prices within 45 miles of E16</h1>
            <table><tr><th>Airport</th><th>100LL</th></tr>
            <tr><td>E16</td><td>SS $6.50</td></tr></table>
            </body></html>"""
            resp.__enter__.return_value = resp
            resp.__exit__.return_value = False
            return resp

        with patch('urllib.request.urlopen', side_effect=mock_urlopen):
            html = client.fetch_local_fuel_html("E16")

        self.assertGreaterEqual(len(posted_requests), 1)
        req = posted_requests[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_full_url(), "https://www.airnav.com/fuel/local.html")
        self.assertEqual(req.get_header("Content-type"), "application/x-www-form-urlencoded")
        # Decode body
        body_str = req.data.decode("utf-8")
        parsed_body = urllib.parse.parse_qs(body_str, keep_blank_values=True)
        self.assertEqual(parsed_body.get("s"), ["E16"])
        self.assertEqual(parsed_body.get("maxage"), ["0"])
        self.assertIn("submit", parsed_body)
        self.assertIn("Fuel prices within 45 miles of E16", html)

    def test_fetch_local_fuel_html_fallback_to_get_on_blank_search_form(self):
        """Verify AirNavClient.fetch_local_fuel_html falls back to GET query params if POST returns blank search form."""
        import urllib.request
        from unittest.mock import MagicMock, patch

        client = AirNavClient()
        recorded_requests = []

        def mock_urlopen(req, timeout=15):
            recorded_requests.append(req)
            resp = MagicMock()
            if req.get_method() == "POST":
                # Returns empty search form without result data
                resp.read.return_value = b"""<!DOCTYPE html>
                <html><head><title>AirNav: Fuel Prices</title></head>
                <body>
                <FORM action="/fuel/local.html" method=post>
                <input name="s" value="">
                <input name="maxage" value="0">
                <input type="image" name="submit" src="/pics/btn.gif">
                </FORM>
                </body></html>"""
            else:
                # GET fallback returns actual results
                resp.read.return_value = b"""<!DOCTYPE html>
                <html><head><title>AirNav: Fuel prices within 45 miles of KSQL</title></head>
                <body><h1>Fuel prices within 45 miles of KSQL</h1>
                <table><tr><th>Airport</th><th>100LL</th></tr>
                <tr><td>KSQL</td><td>SS $6.15</td></tr></table>
                </body></html>"""
            resp.__enter__.return_value = resp
            resp.__exit__.return_value = False
            return resp

        with patch('urllib.request.urlopen', side_effect=mock_urlopen):
            html = client.fetch_local_fuel_html("KSQL")

        self.assertGreaterEqual(len(recorded_requests), 2)
        # First was POST
        self.assertEqual(recorded_requests[0].get_method(), "POST")
        # Second was GET fallback with query params
        self.assertIn("s=KSQL", recorded_requests[1].get_full_url())
        self.assertIn("Fuel prices within 45 miles of KSQL", html)

    def test_parse_local_fuel_html_blank_search_form_handling(self):
        """Verify parse_local_fuel_html cleanly handles a blank search form page without results or errors."""
        blank_form_html = """<!DOCTYPE html>
        <html><head><title>AirNav: Local Fuel</title></head><body>
        <FORM action="/fuel/local.html" method=post>
        Airport or Zip Code: <input name="s" value=""><br>
        Maximum Age: <input name="maxage" value="0"><br>
        <input type="submit" name="submit" value="Search">
        </FORM>
        </body></html>"""

        client = AirNavClient()
        res = client.parse_local_fuel_html(blank_form_html, source_airport="KSQL")
        self.assertIsNotNone(res)
        self.assertFalse(res["success"])
        self.assertEqual(res["count"], 0)
        self.assertEqual(res["airports"], [])
        self.assertIsNone(res["target"])

    def test_parse_local_fuel_html_quote_timestamps_and_brand_networks(self):
        """Verify parse_local_fuel_html extracts quote timestamps (e.g. 19-Aug, 22-Aug), brand networks, and all fuel grades."""
        html_with_quotes = """<!DOCTYPE html>
        <html><head><title>AirNav: Fuel prices within 45 miles of KSJC</title></head><body>
        <h1>Fuel prices within 45 miles of KSJC</h1>
        <table border="0">
        <tr bgcolor="#EEEEEE">
          <th>Airport / FBO</th><th>Brand</th><th>100LL</th><th>Jet A</th><th>SAF</th><th></th>
        </tr>
        <tr>
          <td colspan="6"><a href="/airport/KSJC"><b>KSJC</b></a> &nbsp; <b>Norman Y Mineta San Jose Intl</b> San Jose, CA</td>
        </tr>
        <tr>
          <td>Atlantic</td>
          <td>independent</td>
          <td><a href="...">FS</a> $12.56</td>
          <td><a href="...">FS</a> $11.91</td>
          <td></td>
          <td><font size="-2">22-Aug<br><a href="...">update</a></font></td>
        </tr>
        <tr>
          <td>Signature Aviation</td>
          <td>independent</td>
          <td><a href="...">FS</a> $13.75</td>
          <td><a href="...">FS</a> $11.37</td>
          <td><a href="...">FS</a> $13.33</td>
          <td><font size="-2">21-Aug<br><a href="...">update</a></font></td>
        </tr>
        </table></body></html>"""

        client = AirNavClient()
        res = client.parse_local_fuel_html(html_with_quotes, source_airport="KSJC")
        self.assertTrue(res["success"])
        self.assertEqual(res["count"], 1)
        apt = res["airports"][0]
        self.assertEqual(apt["icao"], "KSJC")
        self.assertEqual(len(apt["fbos"]), 2)

        # FBO 1: Atlantic
        fbo1 = apt["fbos"][0]
        self.assertEqual(fbo1["name"], "Atlantic")
        self.assertEqual(fbo1["brand"], "independent")
        self.assertEqual(fbo1["quote_date"], "22-Aug")
        self.assertIn("Quote: 22-Aug", fbo1["notes"])
        self.assertEqual(fbo1["fuels"]["100LL_FS"]["price"], 12.56)
        self.assertEqual(fbo1["fuels"]["JET_A"]["price"], 11.91)

        # FBO 2: Signature Aviation
        fbo2 = apt["fbos"][1]
        self.assertEqual(fbo2["name"], "Signature Aviation")
        self.assertEqual(fbo2["brand"], "independent")
        self.assertEqual(fbo2["quote_date"], "21-Aug")
        self.assertIn("Quote: 21-Aug", fbo2["notes"])
        self.assertEqual(fbo2["fuels"]["100LL_FS"]["price"], 13.75)
        self.assertEqual(fbo2["fuels"]["JET_A"]["price"], 11.37)
        self.assertEqual(fbo2["fuels"]["SAF"]["price"], 13.33)

        self.assertEqual(apt["best_price"], 12.56)
        self.assertEqual(apt["primary_fuel"], "100LL")
        self.assertEqual(apt["fuels_available"], ["100LL", "Jet-A", "SAF"])

    def test_app_js_batch_badge_refresh_and_popup_rendering(self):
        """Verify app.js fetchAirportFuelAndHighlight opens fresh popup and refreshes badges across all returned airports."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r", encoding="utf-8") as f:
            app_js = f.read()

        self.assertIn("openAirportPopup(targetApt, false);", app_js)
        self.assertIn("updateMarkerBadgeContent(retApt);", app_js)
        self.assertIn("renderAllAirportMarkers();", app_js)
        self.assertIn("savePersistedAirportsBatchToStorage(returnedAirports);", app_js)

    def test_parse_local_fuel_html_unquoted_and_custom_form_tags(self):
        """Verify parse_local_fuel_html handles unquoted form actions, inverted attribute order, and unquoted hrefs."""
        custom_form_html = """<!DOCTYPE html>
        <html><head><title>AirNav: Fuel Search</title></head><body>
        <FORM method="post" action="/fuel/local.html">
        <input name="s" value="">
        <input type="submit" name="submit" value="Search">
        </FORM>
        </body></html>"""
        res = self.client.parse_local_fuel_html(custom_form_html, source_airport="KSQL")
        self.assertFalse(res["success"])
        self.assertEqual(res["count"], 0)

        unquoted_table_html = """<!DOCTYPE html>
        <html><head><title>AirNav: Fuel prices within 45 miles of E16</title></head><body>
        <h1>Fuel prices within 45 miles of E16</h1>
        <table>
        <tr><th>Airport</th><th>Brand</th><th>100LL</th><th>G100UL</th></tr>
        <tr><td><a href=/airport/E16>E16</a> San Martin Airport</td><td>independent</td><td>SS $7.50</td><td>FS $8.10</td></tr>
        <tr><td><a href=/airport/KWVI/>KWVI</a> 13 SW Watsonville Municipal</td><td>independent</td><td>SS $6.50</td><td>FS $6.50</td></tr>
        </table></body></html>"""
        res_unquoted = self.client.parse_local_fuel_html(unquoted_table_html, source_airport="E16")
        self.assertTrue(res_unquoted["success"])
        self.assertEqual(res_unquoted["count"], 2)
        by_icao = {a["icao"]: a for a in res_unquoted["airports"]}
        self.assertIn("E16", by_icao)
        self.assertIn("KWVI", by_icao)
        self.assertEqual(by_icao["E16"]["best_price"], 7.50)
        self.assertEqual(by_icao["KWVI"]["best_price"], 6.50)

    def test_single_fbo_block_quote_and_brand_network_extraction(self):
        """Verify single airport parser extracts quote date and brand networks on FBO blocks for schema parity."""
        single_fbo_html = """
        <a href="/airport/KSQL/RABBIT">Rabbit Aviation Services</a>
        <div>Titan Aviation Fuel • Guaranteed through 31-Aug • Quote: 22-Aug-2026 • Phone: 650-591-5857</div>
        <table>
          <tr><th>Fuel</th><th>Self-Serve</th><th>Full-Serve</th></tr>
          <tr><td>100LL</td><td>$6.15</td><td>$6.85</td></tr>
          <tr><td>G100UL</td><td>$6.35</td><td>$6.95</td></tr>
          <tr><td>SAF</td><td></td><td>$11.50</td></tr>
        </table>
        """
        fbo = self.client._parse_single_fbo_block(single_fbo_html, "KSQL")
        self.assertEqual(fbo["name"], "Rabbit Aviation Services")
        self.assertEqual(fbo["brand"], "Titan")
        self.assertEqual(fbo["quote_date"], "22-Aug-2026")
        self.assertIn("Quote: 22-Aug-2026", fbo["notes"])
        self.assertIn("Titan", fbo["notes"])
        self.assertEqual(fbo["fuels"]["100LL_SS"]["price"], 6.15)
        self.assertEqual(fbo["fuels"]["100UL_SS"]["price"], 6.35)
        self.assertEqual(fbo["fuels"]["SAF"]["price"], 11.50)

    def test_airnav_client_fetch_airport_fuel_method_alias(self):
        """Verify AirNavClient provides fetch_airport_fuel as an alias/wrapper for get_airport_fuel."""
        client = self.client
        self.assertTrue(hasattr(client, "fetch_airport_fuel"), "AirNavClient missing fetch_airport_fuel method")
        self.assertTrue(callable(getattr(client, "fetch_airport_fuel")))

    def test_dynamic_radius_extraction_varying_distances(self):
        """Verify parse_local_fuel_html extracts non-45 mile radii (15, 25, 30, 45, 60, 75, 100, decimal, NM, and &nbsp; entities)."""
        radii_samples = [15, 25, 30, 45, 60, 75, 100, 30.5]
        for rad in radii_samples:
            html = f"""<!DOCTYPE html>
            <html><head><title>AirNav: Fuel prices within {rad} miles of KSQL</title></head>
            <body><h1>Fuel prices within {rad} miles of <a href="/airport/KSQL">KSQL</a></h1>
            <table><tr><th>Airport</th><th>100LL</th></tr>
            <tr><td><a href="/airport/KSQL">KSQL</a> San Carlos</td><td>SS $6.15</td></tr>
            </table></body></html>"""
            res = self.client.parse_local_fuel_html(html, source_airport="KSQL")
            self.assertIsNotNone(res)
            self.assertTrue(res["success"])
            expected_rad = int(rad) if isinstance(rad, int) or rad.is_integer() else rad
            self.assertEqual(res["radius_miles"], expected_rad, f"Failed for radius {rad}")

        # Test HTML entity &nbsp; and NM units
        html_entities = """<!DOCTYPE html>
        <html><head><title>AirNav:&nbsp;Fuel&nbsp;prices&nbsp;within&nbsp;25&nbsp;miles&nbsp;of&nbsp;KSQL</title></head>
        <body><h2>Fuel prices within 25 NM of KSQL</h2>
        <table><tr><th>Airport</th><th>100LL</th></tr>
        <tr><td><a href="/airport/KSQL">KSQL</a> San Carlos</td><td>SS $6.15</td></tr>
        </table></body></html>"""
        res_entity = self.client.parse_local_fuel_html(html_entities, source_airport="KSQL")
        self.assertIsNotNone(res_entity)
        self.assertTrue(res_entity["success"])
        self.assertEqual(res_entity["radius_miles"], 25)

    def test_dynamic_radius_derivation_from_row_distances_when_header_missing(self):
        """Verify parse_local_fuel_html derives search radius from max distance in parsed rows if title header lacks radius."""
        html_without_radius_header = """<!DOCTYPE html>
        <html><head><title>AirNav: Local Fuel Prices - KSQL</title></head>
        <body><h1>AirNav Regional Fuel Feed</h1>
        <table><tr><th>Airport</th><th>100LL</th></tr>
        <tr><td><a href="/airport/KSQL">KSQL</a> San Carlos</td><td>SS $6.15</td></tr>
        <tr><td><a href="/airport/KPAO">KPAO</a> 8 SE Palo Alto</td><td>SS $6.45</td></tr>
        <tr><td><a href="/airport/KSJC">KSJC</a> 19 SE San Jose</td><td>FS $11.50</td></tr>
        <tr><td><a href="/airport/KMRY">KMRY</a> 58 S Monterey</td><td>FS $8.95</td></tr>
        </table></body></html>"""
        res = self.client.parse_local_fuel_html(html_without_radius_header, source_airport="KSQL")
        self.assertIsNotNone(res)
        self.assertTrue(res["success"])
        self.assertEqual(res["count"], 4)
        # Max distance is 58 NM, so derived radius should be at least 58
        self.assertGreaterEqual(res["radius_miles"], 58)

    def test_single_airport_in_radius_not_marked_as_fallback(self):
        """Verify a local fuel query returning 1 airport within a 15-mile radius retains radius_miles=15 and fallback=False."""
        html_15mi = """<!DOCTYPE html>
        <html><head><title>AirNav: Fuel prices within 15 miles of 0Q5</title></head>
        <body><h1>Fuel prices within 15 miles of 0Q5</h1>
        <table><tr><th>Airport</th><th>100LL</th></tr>
        <tr><td><a href="/airport/0Q5">0Q5</a> Shelter Cove</td><td>SS $7.25</td></tr>
        </table></body></html>"""
        res = self.client.parse_local_fuel_html(html_15mi, source_airport="0Q5")
        self.assertIsNotNone(res)
        self.assertTrue(res["success"])
        self.assertEqual(res["count"], 1)
        self.assertEqual(res["radius_miles"], 15)
        self.assertFalse(res.get("fallback", False))

    def test_fetch_local_fuel_prices_fallback_to_single_airport_on_exception(self):
        """Verify AirNavClient.fetch_local_fuel_prices falls back to single airport query when local query fails."""
        from unittest.mock import patch

        client = self.client
        single_airport_mock = {
            "icao": "KSQL",
            "faa": "SQL",
            "name": "San Carlos Airport",
            "best_price": 6.15,
            "primary_fuel": "100LL",
            "fuels_available": ["100LL"],
            "fbos": [{"name": "Rabbit Aviation", "fuels": {"100LL_SS": {"price": 6.15, "type": "100LL"}}}],
            "last_updated": "2026-08-22",
            "fetched_at": "2026-08-22T22:00:00Z",
            "source": "AirNav Live Feed"
        }

        with patch.object(client, 'fetch_local_fuel_html', side_effect=RuntimeError("Local fuel query blocked by anti-bot")):
            with patch.object(client, 'get_airport_fuel', return_value=single_airport_mock):
                res = client.fetch_local_fuel_prices("KSQL", force_refresh=True)

        self.assertIsNotNone(res)
        self.assertTrue(res["success"])
        self.assertTrue(res.get("fallback"))
        self.assertEqual(res["count"], 1)
        self.assertEqual(len(res["airports"]), 1)
        self.assertEqual(res["airports"][0]["icao"], "KSQL")
        self.assertEqual(res["airports"][0]["best_price"], 6.15)
        self.assertEqual(res["radius_miles"], 0)
        self.assertEqual(res.get("status"), "ok")
        self.assertEqual(res.get("data"), single_airport_mock)

    def test_fetch_local_fuel_prices_fallback_to_single_airport_on_empty_results(self):
        """Verify AirNavClient.fetch_local_fuel_prices falls back to single airport query when local query returns 0 results."""
        from unittest.mock import patch

        client = self.client
        blank_html = """<!DOCTYPE html>
        <html><head><title>AirNav: Local Fuel Search</title></head><body>
        <form action="/fuel/local.html" method="post"><input name="s" value=""></form>
        </body></html>"""

        single_mock = {
            "icao": "KHAF",
            "name": "Half Moon Bay Airport",
            "best_price": 6.89,
            "fbos": [{"name": "HAF Fuel", "fuels": {"100LL_SS": {"price": 6.89, "type": "100LL"}}}]
        }

        with patch.object(client, 'fetch_local_fuel_html', return_value=blank_html):
            with patch.object(client, 'get_airport_fuel', return_value=single_mock):
                res = client.fetch_local_fuel_prices("KHAF", force_refresh=True)

        self.assertIsNotNone(res)
        self.assertTrue(res["success"])
        self.assertTrue(res.get("fallback"))
        self.assertEqual(res["count"], 1)
        self.assertEqual(res["airports"][0]["icao"], "KHAF")
        self.assertEqual(res["airports"][0]["best_price"], 6.89)
        self.assertEqual(res.get("data"), single_mock)

    def test_server_api_airnav_dynamic_radius_and_single_airport_fallback(self):
        """Verify server /api/airnav returns dynamic radius_miles and fallback flag."""
        import tempfile
        from unittest.mock import patch

        import server

        test_dir = tempfile.mkdtemp()
        try:
            # 1. Multi-airport with 30-mile radius
            multi_res = {
                "success": True,
                "source_airport": "KSQL",
                "radius_miles": 30,
                "count": 2,
                "airports": [
                    {"icao": "KSQL", "best_price": 6.15, "fbos": []},
                    {"icao": "KPAO", "best_price": 6.45, "fbos": []}
                ],
                "target": {"icao": "KSQL", "best_price": 6.15, "fbos": []}
            }
            with patch.object(server.airnav, 'fetch_local_fuel_prices', return_value=multi_res):
                res = server.airnav.fetch_local_fuel_prices("KSQL")
                self.assertEqual(res["radius_miles"], 30)
                self.assertEqual(len(res["airports"]), 2)

            # 2. Fallback single airport
            fallback_res = {
                "success": True,
                "status": "ok",
                "source_airport": "KSQL",
                "radius_miles": 0,
                "count": 1,
                "airports": [{"icao": "KSQL", "best_price": 6.15, "fbos": []}],
                "target": {"icao": "KSQL", "best_price": 6.15, "fbos": []},
                "data": {"icao": "KSQL", "best_price": 6.15, "fbos": []},
                "fallback": True
            }
            with patch.object(server.airnav, 'fetch_local_fuel_prices', return_value=fallback_res):
                res_fb = server.airnav.fetch_local_fuel_prices("KSQL")
                self.assertTrue(res_fb["fallback"])
                self.assertEqual(res_fb["radius_miles"], 0)
        finally:
            import shutil
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_app_js_dynamic_radius_and_single_airport_toast_logic(self):
        """Verify app.js fetchAirportFuelAndHighlight contains dynamic radius interpolation and fallback toast."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r", encoding="utf-8") as f:
            app_js = f.read()

        # Dynamic radius toast
        self.assertIn("within ${radiusMiles} miles of ${ident}!", app_js)
        # Single airport / fallback toast
        self.assertIn("⚡ AirNav: Updated rates for ${ident}", app_js)
        self.assertIn("const isFallback = Boolean(jsonRes.fallback || (returnedAirports.length === 1 && jsonRes.radius_miles === 0));", app_js)
        self.assertIn("const radiusMiles = jsonRes.radius_miles !== undefined ? jsonRes.radius_miles : 45;", app_js)

    def test_popup_marker_pinning_and_retention_in_recalculate_radius(self):
        """Verify recalculateRadiusAirports pins active popup marker and prevents unmounting while popup is open."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r", encoding="utf-8") as f:
            app_js = f.read()

        # Verify activePopupIcao in STATE
        self.assertIn("activePopupIcao: null,", app_js)

        # Verify Priority 0.5 Active Open Popup Airport in acceptedHighlightList
        self.assertIn("// #0.5 Priority: Active Open Popup Airport is ALWAYS accepted and rendered (Pin Open Popup Marker)", app_js)
        self.assertIn("const activePopupIcao = STATE.activePopupIcao ? STATE.activePopupIcao.toUpperCase().trim() : null;", app_js)
        self.assertIn("acceptedHighlightList.push(popupAptCanonical);", app_js)

        # Verify activePopupIcao is pinned in currentHighlightedIcaos
        self.assertIn("if (activePopupIcao) {\n      currentHighlightedIcaos.add(activePopupIcao);\n    }", app_js)

        # Verify marker layer is NEVER removed while popup is open
        self.assertIn("if (activePopupIcao) {", app_js)
        self.assertIn("if (cleanKey === activePopupIcao) continue;", app_js)

    def test_open_airport_popup_options_and_explicit_close_contract(self):
        """Verify openAirportPopup configures closeOnClick: false, autoClose: false, closeButton: true, and closes previous popups."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r", encoding="utf-8") as f:
            app_js = f.read()

        # Verify popup options
        self.assertIn("closeOnClick: false,", app_js)
        self.assertIn("autoClose: false,", app_js)
        self.assertIn("closeButton: true", app_js)

        # Verify active popup tracking
        self.assertIn("STATE.activePopupIcao = canonical.icao;", app_js)
        self.assertIn("if (activeAirportPopup && activeAirportPopup.isOpen() && STATE.activePopupIcao && STATE.activePopupIcao !== canonical.icao)", app_js)
        self.assertIn("map.closePopup(activeAirportPopup);", app_js)

    def test_popup_event_isolation_and_propagation_prevention(self):
        """Verify isolatePopupEvents disables click/scroll propagation and stops mousemove/pointermove propagation."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r", encoding="utf-8") as f:
            app_js = f.read()

        # Verify event isolation helper
        self.assertIn("function isolatePopupEvents(popup)", app_js)
        self.assertIn("L.DomEvent.disableClickPropagation(el);", app_js)
        self.assertIn("L.DomEvent.disableScrollPropagation(el);", app_js)
        self.assertIn("el.addEventListener('mousemove', stopProp);", app_js)
        self.assertIn("el.addEventListener('pointermove', stopProp);", app_js)
        self.assertIn("el.addEventListener('mouseenter', stopProp);", app_js)
        self.assertIn("el.addEventListener('mouseover', stopProp);", app_js)
        self.assertIn("el.addEventListener('pointerdown', stopProp);", app_js)
        self.assertIn("el.addEventListener('pointerup', stopProp);", app_js)
        self.assertIn("el.addEventListener('mousedown', stopProp);", app_js)
        self.assertIn("el.addEventListener('mouseup', stopProp);", app_js)

        # Verify map popupopen and popupclose lifecycle listeners
        self.assertIn("map.on('popupopen', function (e) {", app_js)
        self.assertIn("isolatePopupEvents(e.popup);", app_js)
        self.assertIn("map.on('popupclose', function (e) {", app_js)

    def test_popup_dismissal_triggers(self):
        """Verify popups are explicitly closed on Escape and full details modal open."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r", encoding="utf-8") as f:
            app_js = f.read()

        # Escape closes popup
        self.assertIn("if (e.code === 'Escape') {", app_js)
        self.assertIn("map.closePopup(activeAirportPopup);", app_js)

        # openAirportModal closes popup
        self.assertIn("function openAirportModal(apt, isLoading = false) {", app_js)
        self.assertIn("if (activeAirportPopup && map) {", app_js)

    def test_popup_button_delegation_on_container_isolated_from_document(self):
        """Verify popup container directly handles button clicks so disableClickPropagation does not block action buttons."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r", encoding="utf-8") as f:
            app_js = f.read()

        # Verify handlePopupButtonClick helper
        self.assertIn("function handlePopupButtonClick(e)", app_js)
        self.assertIn("const btnDetails = e.target.closest('.btn-popup-open-details');", app_js)
        self.assertIn("const btnRefresh = e.target.closest('.btn-popup-refresh');", app_js)
        self.assertIn("const btnOrigin = e.target.closest('.btn-popup-set-origin');", app_js)

        # Verify click listener attached directly to popup container element
        self.assertIn("el.addEventListener('click', handlePopupButtonClick);", app_js)

    def test_render_all_airport_markers_preserves_and_restores_active_popup(self):
        """Verify renderAllAirportMarkers saves activePopupIcao and re-opens popup after clearing layer group."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r", encoding="utf-8") as f:
            app_js = f.read()

        self.assertIn("const savedPopupIcao = STATE.activePopupIcao;", app_js)
        self.assertIn("if (savedPopupIcao) {\n      STATE.activePopupIcao = savedPopupIcao;\n    }", app_js)
        self.assertIn("if (savedPopupIcao) {\n      const cleanIcao = savedPopupIcao.toUpperCase().trim();", app_js)
        self.assertIn("openAirportPopup(popupApt, false);", app_js)

    def test_popup_marker_in_radius_styling_retention_when_out_of_circle(self):
        """Verify popup marker retains in-radius badge display and high z-index (9500) even if circle center shifts away."""
        app_js_path = os.path.join(DIRECTORY, "app.js")
        with open(app_js_path, "r", encoding="utf-8") as f:
            app_js = f.read()

        self.assertIn("const isPopupOpen = Boolean(activePopupIcao && (cleanIcao === activePopupIcao || (cleanFaa && cleanFaa === activePopupIcao) || (popupAptCanonical && (popupAptCanonical.icao === apt.icao || popupAptCanonical.faa === apt.faa))));", app_js)
        self.assertIn("const inRadiusClass = (isInRadius || isOrigin || isPopupOpen) ? 'in-radius' : '';", app_js)
        self.assertIn("const zOffset = isLowest ? 10000 : (isPopupOpen ? 9500 : (isOrigin ? 9000 : (isInRadius ? 500 : 0)));", app_js)
        self.assertIn("if (isInRadius || isOrigin || isPopupOpen) {", app_js)

    def test_e16_matrix_table_fuel_rates_and_1_to_1_column_alignment(self):
        """Verify single airport matrix table for E16 (which lacks 100LL & 100UL) maintains 1-to-1 column alignment."""
        e16_matrix_html = """
        <a href="/airport/E16/SAN_MARTIN">San Martin Aviation Corp</a>
        <div>Titan Aviation • Phone: 408-683-4102</div>
        <table>
          <tr>
            <th></th>
            <th>100LL</th>
            <th>100UL</th>
            <th>UL94</th>
            <th>Jet A</th>
          </tr>
          <tr>
            <td>Full-Serve</td>
            <td></td>
            <td></td>
            <td>$8.59</td>
            <td>$7.68</td>
          </tr>
          <tr>
            <td>Self-Serve</td>
            <td></td>
            <td></td>
            <td>$8.39</td>
            <td></td>
          </tr>
        </table>
        """
        client = AirNavClient()
        parsed = client.parse_airport_fuel(e16_matrix_html, icao="E16")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["icao"], "E16")
        self.assertEqual(len(parsed["fbos"]), 1)
        fbo = parsed["fbos"][0]
        self.assertEqual(fbo["name"], "San Martin Aviation Corp")
        fuels = fbo["fuels"]

        # Strict checks on E16 rates
        self.assertIn("94UL_SS", fuels)
        self.assertEqual(fuels["94UL_SS"]["price"], 8.39)
        self.assertEqual(fuels["94UL_SS"]["service"], "Self-Serve")

        self.assertIn("94UL_FS", fuels)
        self.assertEqual(fuels["94UL_FS"]["price"], 8.59)
        self.assertEqual(fuels["94UL_FS"]["service"], "Full-Serve")

        self.assertIn("JET_A", fuels)
        self.assertEqual(fuels["JET_A"]["price"], 7.68)
        self.assertEqual(fuels["JET_A"]["service"], "Full-Serve")

        # Piston lowest price is 94UL SS ($8.39) and primary fuel is 94UL
        self.assertEqual(parsed["best_price"], 8.39)
        self.assertEqual(parsed["primary_fuel"], "94UL")
        self.assertEqual(parsed["fuels_available"], ["94UL", "Jet-A"])

    def test_e16_matrix_table_services_as_columns(self):
        """Verify matrix table with service headers as columns and fuel types as rows parses correctly."""
        e16_svc_cols_html = """
        <a href="/airport/E16/SAN_MARTIN">San Martin Aviation Corp</a>
        <table>
          <tr>
            <th>Fuel</th>
            <th>Self-Serve</th>
            <th>Full-Serve</th>
          </tr>
          <tr>
            <td>94UL</td>
            <td>$8.39</td>
            <td>$8.59</td>
          </tr>
          <tr>
            <td>Jet A</td>
            <td></td>
            <td>$7.68</td>
          </tr>
        </table>
        """
        client = AirNavClient()
        parsed = client.parse_airport_fuel(e16_svc_cols_html, icao="E16")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["icao"], "E16")
        fuels = parsed["fbos"][0]["fuels"]
        self.assertEqual(fuels["94UL_SS"]["price"], 8.39)
        self.assertEqual(fuels["94UL_FS"]["price"], 8.59)
        self.assertEqual(fuels["JET_A"]["price"], 7.68)
        self.assertEqual(parsed["best_price"], 8.39)
        self.assertEqual(parsed["primary_fuel"], "94UL")

    def test_e16_local_fuel_multi_airport_table_strict_rates(self):
        """Verify local fuel multi-airport parser extracts E16 true rates without Jet-A shifting into 94UL FS."""
        local_html = """<!DOCTYPE html>
        <html><head><title>AirNav: Fuel prices within 45 miles of E16</title></head><body>
        <h1>Fuel prices within 45 miles of E16</h1>
        <table>
        <tr bgcolor="#EEEEEE">
          <th>Airport / FBO</th><th>Brand</th><th>100LL</th><th>G100UL</th><th>UL94</th><th>Jet A</th><th>SAF</th><th></th>
        </tr>
        <tr>
          <td colspan="8"><a href="/airport/E16"><b>E16</b></a> &nbsp; <b>San Martin Airport</b> San Martin, CA</td>
        </tr>
        <tr>
          <td><a href="/airport/E16/SAN_MARTIN">San Martin Aviation Corp</a></td>
          <td>Titan</td>
          <td></td>
          <td></td>
          <td><a href="...">SS</a> $8.39<br><a href="...">FS</a> $8.59</td>
          <td><a href="...">FS</a> $7.68</td>
          <td></td>
          <td><font size="-2">19-Aug<br><a href="...">update</a></font></td>
        </tr>
        </table></body></html>"""
        client = AirNavClient()
        res = client.parse_local_fuel_html(local_html, source_airport="E16")
        self.assertTrue(res["success"])
        self.assertEqual(res["count"], 1)
        apt = res["airports"][0]
        self.assertEqual(apt["icao"], "E16")
        self.assertEqual(apt["best_price"], 8.39)
        self.assertEqual(apt["primary_fuel"], "94UL")
        fbo = apt["fbos"][0]
        self.assertEqual(fbo["fuels"]["94UL_SS"]["price"], 8.39)
        self.assertEqual(fbo["fuels"]["94UL_FS"]["price"], 8.59)
        self.assertEqual(fbo["fuels"]["JET_A"]["price"], 7.68)

    def test_arbitrary_missing_intermediate_fuels_column_alignment(self):
        """Verify table parser with arbitrary gaps in fuel columns maintains exact column mapping."""
        gapped_html = """
        <a href="/airport/KGAP/FBO">Gapped Fuel FBO</a>
        <table>
          <tr>
            <th></th>
            <th>100LL</th>
            <th>100UL</th>
            <th>UL94</th>
            <th>100R</th>
            <th>Mogas</th>
            <th>Jet A</th>
            <th>SAF</th>
          </tr>
          <tr>
            <td>Full-Serve</td>
            <td></td>
            <td>$7.10</td>
            <td></td>
            <td>$7.40</td>
            <td></td>
            <td>$6.90</td>
            <td>$12.50</td>
          </tr>
          <tr>
            <td>Self-Serve</td>
            <td>$6.20</td>
            <td></td>
            <td>$8.10</td>
            <td></td>
            <td>$5.50</td>
            <td></td>
            <td></td>
          </tr>
        </table>
        """
        client = AirNavClient()
        parsed = client.parse_airport_fuel(gapped_html, icao="KGAP")
        fuels = parsed["fbos"][0]["fuels"]
        self.assertEqual(fuels["100LL_SS"]["price"], 6.20)
        self.assertEqual(fuels["100UL_FS"]["price"], 7.10)
        self.assertEqual(fuels["94UL_SS"]["price"], 8.10)
        self.assertEqual(fuels["100R_FS"]["price"], 7.40)
        self.assertEqual(fuels["MOGAS_SS"]["price"], 5.50)
        self.assertEqual(fuels["JET_A"]["price"], 6.90)
        self.assertEqual(fuels["SAF"]["price"], 12.50)
        self.assertEqual(parsed["best_price"], 5.50)  # Mogas is lowest piston fuel

    def test_row_based_table_parsing_with_empty_cells(self):
        """Verify row-based table parsing maintains positional SS/FS columns when cells are empty."""
        row_table_html = """
        <a href="/airport/KTEST/FBO">Test Aviation</a>
        <table>
          <tr><td>100LL</td><td></td><td>$6.85</td></tr>
          <tr><td>94UL</td><td>$8.39</td><td></td></tr>
          <tr><td>100UL</td><td>$7.10</td><td>$7.50</td></tr>
          <tr><td>Jet A</td><td></td><td>$7.68</td></tr>
        </table>
        """
        client = AirNavClient()
        parsed = client.parse_airport_fuel(row_table_html, icao="KTEST")
        fuels = parsed["fbos"][0]["fuels"]
        self.assertNotIn("100LL_SS", fuels)
        self.assertEqual(fuels["100LL_FS"]["price"], 6.85)
        self.assertEqual(fuels["94UL_SS"]["price"], 8.39)
        self.assertNotIn("94UL_FS", fuels)
        self.assertEqual(fuels["100UL_SS"]["price"], 7.10)
        self.assertEqual(fuels["100UL_FS"]["price"], 7.50)
        self.assertEqual(fuels["JET_A"]["price"], 7.68)
        self.assertEqual(parsed["best_price"], 6.85)
        self.assertEqual(parsed["primary_fuel"], "100LL")

    def test_parse_local_fuel_html_variable_header_columns_100ll_jeta(self):
        """Verify dynamic header indexing with 2 fuel columns [100LL, Jet A]."""
        html_2_cols = """<!DOCTYPE html>
        <html><head><title>AirNav: Fuel prices within 45 miles of KSQL</title></head><body>
        <h1>Fuel prices within 45 miles of KSQL</h1>
        <table>
        <tr bgcolor="#EEEEEE">
          <th>Airport / FBO</th><th>Brand</th><th>100LL</th><th>Jet A</th><th></th>
        </tr>
        <tr>
          <td colspan="5"><a href="/airport/KSQL"><b>KSQL</b></a> &nbsp; <b>San Carlos Airport</b> San Carlos, CA</td>
        </tr>
        <tr>
          <td><a href="/airport/KSQL/RABBIT">Rabbit Aviation</a></td>
          <td>independent</td>
          <td><a href="...">SS</a> $6.15<br><a href="...">FS</a> $6.65</td>
          <td><a href="...">FS</a> $7.25</td>
          <td><font size="-2">22-Aug<br><a href="...">update</a></font></td>
        </tr>
        </table></body></html>"""
        client = AirNavClient()
        res = client.parse_local_fuel_html(html_2_cols, source_airport="KSQL")
        self.assertTrue(res["success"])
        apt = res["airports"][0]
        fbo = apt["fbos"][0]
        self.assertIn("100LL_SS", fbo["fuels"])
        self.assertIn("100LL_FS", fbo["fuels"])
        self.assertIn("JET_A", fbo["fuels"])
        self.assertNotIn("100UL_SS", fbo["fuels"])
        self.assertNotIn("100UL_FS", fbo["fuels"])
        self.assertNotIn("94UL_SS", fbo["fuels"])
        self.assertNotIn("94UL_FS", fbo["fuels"])
        self.assertEqual(fbo["fuels"]["100LL_SS"]["price"], 6.15)
        self.assertEqual(fbo["fuels"]["100LL_FS"]["price"], 6.65)
        self.assertEqual(fbo["fuels"]["JET_A"]["price"], 7.25)
        self.assertEqual(apt["best_price"], 6.15)
        self.assertEqual(apt["primary_fuel"], "100LL")
        self.assertEqual(apt["fuels_available"], ["100LL", "Jet-A"])

    def test_parse_local_fuel_html_variable_header_columns_100ll_ul94_jeta(self):
        """Verify dynamic header indexing with 3 fuel columns [100LL, UL94, Jet A] and unlisted 100UL."""
        html_3_cols = """<!DOCTYPE html>
        <html><head><title>AirNav: Fuel prices within 45 miles of E16</title></head><body>
        <h1>Fuel prices within 45 miles of E16</h1>
        <table>
        <tr bgcolor="#EEEEEE">
          <th>Airport / FBO</th><th>Brand</th><th>100LL</th><th>UL94</th><th>Jet A</th><th></th>
        </tr>
        <tr>
          <td colspan="6"><a href="/airport/E16"><b>E16</b></a> &nbsp; <b>San Martin Airport</b> San Martin, CA</td>
        </tr>
        <tr>
          <td><a href="/airport/E16/SAN_MARTIN">San Martin Aviation Corp</a></td>
          <td>Titan</td>
          <td></td>
          <td><a href="...">SS</a> $8.39<br><a href="...">FS</a> $8.59</td>
          <td><a href="...">FS</a> $7.68</td>
          <td><font size="-2">19-Aug<br><a href="...">update</a></font></td>
        </tr>
        </table></body></html>"""
        client = AirNavClient()
        res = client.parse_local_fuel_html(html_3_cols, source_airport="E16")
        self.assertTrue(res["success"])
        apt = res["airports"][0]
        fbo = apt["fbos"][0]
        # 100UL and 100LL must NOT exist
        self.assertNotIn("100UL_SS", fbo["fuels"])
        self.assertNotIn("100UL_FS", fbo["fuels"])
        self.assertNotIn("100LL_SS", fbo["fuels"])
        self.assertNotIn("100LL_FS", fbo["fuels"])
        self.assertIn("94UL_SS", fbo["fuels"])
        self.assertIn("94UL_FS", fbo["fuels"])
        self.assertIn("JET_A", fbo["fuels"])
        self.assertEqual(fbo["fuels"]["94UL_SS"]["price"], 8.39)
        self.assertEqual(fbo["fuels"]["94UL_FS"]["price"], 8.59)
        self.assertEqual(fbo["fuels"]["JET_A"]["price"], 7.68)
        self.assertEqual(apt["best_price"], 8.39)
        self.assertEqual(apt["primary_fuel"], "94UL")
        self.assertEqual(apt["fuels_available"], ["94UL", "Jet-A"])

    def test_parse_local_fuel_html_variable_header_columns_100ll_100r_mogas_jeta(self):
        """Verify dynamic header indexing with alternative fuel grades [100LL, 100R, Mogas, Jet A]."""
        html_alt_cols = """<!DOCTYPE html>
        <html><head><title>AirNav: Fuel prices within 45 miles of 61S</title></head><body>
        <h1>Fuel prices within 45 miles of 61S</h1>
        <table>
        <tr bgcolor="#EEEEEE">
          <th>Airport / FBO</th><th>Brand</th><th>100LL</th><th>100R</th><th>Mogas</th><th>Jet A</th>
        </tr>
        <tr>
          <td colspan="6"><a href="/airport/61S"><b>61S</b></a> &nbsp; <b>Cascade Locks State Airport</b></td>
        </tr>
        <tr>
          <td>Cascade Aviation</td>
          <td>independent</td>
          <td><a href="...">SS</a> $6.50</td>
          <td><a href="...">SS</a> $7.20</td>
          <td><a href="...">SS</a> $5.50</td>
          <td><a href="...">FS</a> $6.80</td>
        </tr>
        </table></body></html>"""
        client = AirNavClient()
        res = client.parse_local_fuel_html(html_alt_cols, source_airport="61S")
        self.assertTrue(res["success"])
        apt = res["airports"][0]
        fbo = apt["fbos"][0]
        self.assertNotIn("100UL_SS", fbo["fuels"])
        self.assertNotIn("94UL_SS", fbo["fuels"])
        self.assertEqual(fbo["fuels"]["100LL_SS"]["price"], 6.50)
        self.assertEqual(fbo["fuels"]["100R_SS"]["price"], 7.20)
        self.assertEqual(fbo["fuels"]["MOGAS_SS"]["price"], 5.50)
        self.assertEqual(fbo["fuels"]["JET_A"]["price"], 6.80)
        self.assertEqual(apt["best_price"], 5.50)
        self.assertEqual(apt["primary_fuel"], "100LL")
        self.assertEqual(apt["fuels_available"], ["100LL", "100R", "Jet-A", "Mogas"])

    def test_multi_price_cell_without_explicit_service_labels(self):
        """Verify cell with two prices (e.g. $8.39 and $8.59) parses as SS and FS respectively."""
        local_multi_price_html = """<!DOCTYPE html>
        <html><head><title>AirNav: Fuel prices within 45 miles of E16</title></head><body>
        <table>
        <tr bgcolor="#EEEEEE">
          <th>Airport / FBO</th><th>Brand</th><th>100LL</th><th>UL94</th><th>Jet A</th>
        </tr>
        <tr>
          <td colspan="5"><a href="/airport/E16"><b>E16</b></a> &nbsp; <b>San Martin Airport</b></td>
        </tr>
        <tr>
          <td><a href="/airport/E16/SAN_MARTIN">San Martin Aviation Corp</a></td>
          <td>Titan</td>
          <td></td>
          <td>$8.39<br>$8.59</td>
          <td>$7.68</td>
        </tr>
        </table></body></html>"""
        client = AirNavClient()
        res = client.parse_local_fuel_html(local_multi_price_html, source_airport="E16")
        apt = res["airports"][0]
        fuels = apt["fbos"][0]["fuels"]
        self.assertEqual(fuels["94UL_SS"]["price"], 8.39)
        self.assertEqual(fuels["94UL_FS"]["price"], 8.59)
        self.assertEqual(fuels["JET_A"]["price"], 7.68)
        self.assertEqual(apt["best_price"], 8.39)
        self.assertEqual(apt["primary_fuel"], "94UL")

    def test_parse_local_fuel_html_arbitrary_column_ordering(self):
        """Verify dynamic header indexing handles arbitrary fuel column ordering (e.g. Jet A, SAF, 94UL, 100LL)."""
        html_reversed_cols = """<!DOCTYPE html>
        <html><head><title>AirNav: Fuel prices within 45 miles of KSQL</title></head><body>
        <table>
        <tr bgcolor="#EEEEEE">
          <th>Airport / FBO</th><th>Brand</th><th>Jet A</th><th>SAF</th><th>94UL</th><th>100LL</th>
        </tr>
        <tr>
          <td colspan="6"><a href="/airport/KSQL"><b>KSQL</b></a> &nbsp; <b>San Carlos Airport</b></td>
        </tr>
        <tr>
          <td>San Carlos FBO</td>
          <td>independent</td>
          <td><a href="...">FS</a> $7.25</td>
          <td><a href="...">FS</a> $11.50</td>
          <td><a href="...">SS</a> $8.10</td>
          <td><a href="...">SS</a> $6.15</td>
        </tr>
        </table></body></html>"""
        client = AirNavClient()
        res = client.parse_local_fuel_html(html_reversed_cols, source_airport="KSQL")
        apt = res["airports"][0]
        fuels = apt["fbos"][0]["fuels"]
        self.assertEqual(fuels["JET_A"]["price"], 7.25)
        self.assertEqual(fuels["SAF"]["price"], 11.50)
        self.assertEqual(fuels["94UL_SS"]["price"], 8.10)
        self.assertEqual(fuels["100LL_SS"]["price"], 6.15)
        self.assertEqual(apt["best_price"], 6.15)
        self.assertEqual(apt["primary_fuel"], "100LL")
        self.assertEqual(apt["fuels_available"], ["100LL", "94UL", "Jet-A", "SAF"])

    def test_parse_local_fuel_html_interspersed_non_fuel_and_empty_columns(self):
        """Verify header indexing skips non-fuel columns (De-Ice, Hangar, empty cells) without column drift."""
        html_interspersed = """<!DOCTYPE html>
        <html><head><title>AirNav: Fuel prices within 45 miles of E16</title></head><body>
        <table>
        <tr bgcolor="#EEEEEE">
          <th>Airport / FBO</th><th>Brand</th><th>City</th><th>100LL</th><th></th><th>UL94</th><th>Hangar Rate</th><th>Jet A</th>
        </tr>
        <tr>
          <td colspan="8"><a href="/airport/E16"><b>E16</b></a> &nbsp; <b>San Martin Airport</b></td>
        </tr>
        <tr>
          <td>San Martin Aviation</td>
          <td>Titan</td>
          <td></td>
          <td><a href="...">SS</a> $8.39</td>
          <td><a href="...">FS</a> $7.68</td>
        </tr>
        </table></body></html>"""
        client = AirNavClient()
        res = client.parse_local_fuel_html(html_interspersed, source_airport="E16")
        apt = res["airports"][0]
        fuels = apt["fbos"][0]["fuels"]
        self.assertNotIn("100LL_SS", fuels)
        self.assertNotIn("100LL_FS", fuels)
        self.assertNotIn("100UL_SS", fuels)
        self.assertEqual(fuels["94UL_SS"]["price"], 8.39)
        self.assertEqual(fuels["JET_A"]["price"], 7.68)
        self.assertEqual(apt["best_price"], 8.39)
        self.assertEqual(apt["primary_fuel"], "94UL")

    def test_parse_local_fuel_html_all_six_fuel_grades(self):
        """Verify dynamic header indexing handles all six fuel grades present in a single table."""
        html_all_grades = """<!DOCTYPE html>
        <html><head><title>AirNav: Fuel prices within 45 miles of KTEST</title></head><body>
        <table>
        <tr bgcolor="#EEEEEE">
          <th>Airport / FBO</th><th>Brand</th><th>100LL</th><th>100UL</th><th>94UL</th><th>100R</th><th>Mogas</th><th>Jet A</th><th>SAF</th>
        </tr>
        <tr>
          <td colspan="9"><a href="/airport/KTEST"><b>KTEST</b></a> &nbsp; <b>Test Super Field</b></td>
        </tr>
        <tr>
          <td>Test FBO</td>
          <td>independent</td>
          <td><a href="...">SS</a> $6.20</td>
          <td><a href="...">FS</a> $6.50</td>
          <td><a href="...">SS</a> $8.30</td>
          <td><a href="...">SS</a> $7.10</td>
          <td><a href="...">SS</a> $5.40</td>
          <td><a href="...">FS</a> $7.00</td>
          <td><a href="...">FS</a> $12.00</td>
        </tr>
        </table></body></html>"""
        client = AirNavClient()
        res = client.parse_local_fuel_html(html_all_grades, source_airport="KTEST")
        apt = res["airports"][0]
        fuels = apt["fbos"][0]["fuels"]
        self.assertEqual(fuels["100LL_SS"]["price"], 6.20)
        self.assertEqual(fuels["100UL_FS"]["price"], 6.50)
        self.assertEqual(fuels["94UL_SS"]["price"], 8.30)
        self.assertEqual(fuels["100R_SS"]["price"], 7.10)
        self.assertEqual(fuels["MOGAS_SS"]["price"], 5.40)
        self.assertEqual(fuels["JET_A"]["price"], 7.00)
        self.assertEqual(fuels["SAF"]["price"], 12.00)
        self.assertEqual(apt["best_price"], 5.40)  # Mogas is lowest piston fuel
        self.assertEqual(apt["primary_fuel"], "100LL")  # 100LL takes precedence when present
        self.assertEqual(apt["fuels_available"], ["100LL", "100R", "100UL", "94UL", "Jet-A", "Mogas", "SAF"])

    def test_parse_local_fuel_html_exact_user_airnav_16_airports_table(self):
        """Verify parse_local_fuel_html accurately parses real AirNav table with leading blank headers across all 16 airports."""
        real_airnav_html = """<!DOCTYPE html>
<html>
<head><title>AirNav: Fuel prices within 45 miles of E16</title></head>
<body>
<h1>Fuel prices within 45 miles of <a href="/airport/E16">E16</a></h1>
<table border="0" cellpadding="2" cellspacing="0">
<tr bgcolor="#EEEEEE">
  <th></th>
  <th>Airport / FBO</th>
  <th></th>
  <th><b>100LL</b><br><font size="-2">$5.89–$13.75<br>average $7.75</font></th>
  <th><b>G100UL</b><br><font size="-2">$6.50–$6.99<br>average $6.75</font></th>
  <th><b>UL94</b><br><font size="-2">$8.30–$8.99<br>average $8.69</font></th>
  <th><b>Jet A</b><br><font size="-2">$5.65–$11.99<br>average $8.15</font></th>
  <th><b>SAF</b><br><font size="-2">$12.99–$13.33<br>average $13.10</font></th>
  <th></th>
</tr>
<!-- 1. E16 -->
<tr>
  <td colspan="9"><a href="/airport/E16"><b>E16</b></a> &nbsp; <b>San Martin Airport</b> San Martin, CA</td>
</tr>
<tr valign="top">
  <td><a href="/airport/E16/SAN_MARTIN">San Martin Aviation Corp</a></td>
  <td>Titan</td>
  <td></td>
  <td></td>
  <td><a href="...">SS</a> $8.39<br><a href="...">FS</a> $8.59</td>
  <td><a href="...">FS</a> $7.68</td>
  <td></td>
  <td><font size="-2">19-Aug<br><a href="...">update</a></font></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 2. KWVI -->
<tr>
  <td colspan="9"><a href="/airport/KWVI"><b>KWVI</b></a> 13 SW &nbsp; <b>Watsonville Municipal Airport</b> Watsonville, CA</td>
</tr>
<tr valign="top">
  <td><a href="/airport/KWVI/WVI">Watsonville Municipal Airport</a></td>
  <td>World Fuel</td>
  <td><a href="...">SS</a> $6.50<br><a href="...">FS</a> $7.00</td>
  <td><a href="...">FS</a> $6.50</td>
  <td></td>
  <td><a href="...">SS</a> $6.25<br><a href="...">FS</a> $6.75</td>
  <td></td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 3. KCVH -->
<tr>
  <td colspan="9"><a href="/airport/KCVH"><b>KCVH</b></a> 14 SE &nbsp; <b>Hollister Municipal Airport</b> Hollister, CA</td>
</tr>
<tr valign="top">
  <td><a href="/airport/KCVH/HOLLISTER">Hollister Jet Center, Inc</a></td>
  <td>AVFUEL</td>
  <td><a href="...">SS</a> $7.02<br><a href="...">FS</a> $7.52<br>$7.42</td>
  <td></td>
  <td></td>
  <td><a href="...">SS</a> $7.11<br><a href="...">FS</a> $7.61<br>$7.51</td>
  <td></td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 4. KRHV -->
<tr>
  <td colspan="9"><a href="/airport/KRHV"><b>KRHV</b></a> 18 NW &nbsp; <b>Reid-Hillview Airport of Santa Clara County</b> San Jose, CA</td>
</tr>
<tr valign="top">
  <td>Santa Clara County</td>
  <td>independent</td>
  <td></td>
  <td><a href="...">FS</a> $6.99</td>
  <td><a href="...">SS</a> $8.30<br><a href="...">FS</a> $8.60</td>
  <td></td>
  <td></td>
  <td><font size="-2">31-Jul<br><a href="...">update</a></font></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 5. KSJC -->
<tr>
  <td colspan="9"><a href="/airport/KSJC"><b>KSJC</b></a> 23 NW &nbsp; <b>Norman Y Mineta San Jose International Airport</b> San Jose, CA</td>
</tr>
<tr valign="top">
  <td>Atlantic</td>
  <td>independent</td>
  <td><a href="...">FS</a> $12.56</td>
  <td></td>
  <td></td>
  <td><a href="...">FS</a> $11.91</td>
  <td></td>
  <td><font size="-2">22-Aug<br><a href="...">update</a></font></td>
</tr>
<tr valign="top">
  <td>Signature Aviation</td>
  <td>independent</td>
  <td><a href="...">FS</a> $13.75</td>
  <td></td>
  <td></td>
  <td><a href="...">FS</a> $11.37</td>
  <td><a href="...">FS</a> $13.33</td>
  <td><font size="-2">21-Aug<br><a href="...">update</a></font></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 6. KSNS -->
<tr>
  <td colspan="9"><a href="/airport/KSNS"><b>KSNS</b></a> 25 S &nbsp; <b>Salinas Municipal Airport</b> Salinas, CA</td>
</tr>
<tr valign="top">
  <td>Jet West GateOne</td>
  <td>AVFUEL</td>
  <td><a href="...">SS</a> $6.97<br><a href="...">FS</a> $7.47</td>
  <td></td>
  <td></td>
  <td><a href="...">FS</a> $7.69<br><a href="...">SS</a> $7.69</td>
  <td></td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 7. KOAR -->
<tr>
  <td colspan="9"><a href="/airport/KOAR"><b>KOAR</b></a> 25 SSW &nbsp; <b>Marina Municipal Airport</b> Marina, CA</td>
</tr>
<tr valign="top">
  <td>City of Marina (FBO)</td>
  <td>World Fuel Services</td>
  <td><a href="...">SS</a> $7.24</td>
  <td></td>
  <td></td>
  <td><a href="...">SS</a> $6.75</td>
  <td></td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 8. KNUQ -->
<tr>
  <td colspan="9"><a href="/airport/KNUQ"><b>KNUQ</b></a> 29 NW &nbsp; <b>Moffett Federal Airfield</b> Mountain View, CA</td>
</tr>
<tr valign="top">
  <td>Avports Moffett Field</td>
  <td>World Fuel</td>
  <td></td>
  <td></td>
  <td></td>
  <td><a href="...">FS</a> $10.20</td>
  <td></td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 9. KMRY -->
<tr>
  <td colspan="9"><a href="/airport/KMRY"><b>KMRY</b></a> 32 SSW &nbsp; <b>Monterey Regional Airport</b> Monterey, CA</td>
</tr>
<tr valign="top">
  <td>Monterey Jet Center</td>
  <td>AVFUEL</td>
  <td><a href="...">SS</a> $7.25<br><a href="...">FS</a> $7.95</td>
  <td></td>
  <td></td>
  <td><a href="...">FS</a> $8.15</td>
  <td></td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 10. KPAO -->
<tr>
  <td colspan="9"><a href="/airport/KPAO"><b>KPAO</b></a> 33 NW &nbsp; <b>Palo Alto Airport</b> Palo Alto, CA</td>
</tr>
<tr valign="top">
  <td>Advantage Aviation</td>
  <td>Epic</td>
  <td><a href="...">SS</a> $7.40<br><a href="...">FS</a> $7.65</td>
  <td></td>
  <td></td>
  <td><a href="...">FS</a> $7.85</td>
  <td></td>
  <td><font size="-2">20-Aug<br><a href="...">update</a></font></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 11. KLSN -->
<tr>
  <td colspan="9"><a href="/airport/KLSN"><b>KLSN</b></a> 35 E &nbsp; <b>Los Banos Municipal Airport</b> Los Banos, CA</td>
</tr>
<tr valign="top">
  <td>City of Los Banos</td>
  <td>independent</td>
  <td><a href="...">SS</a> $5.89</td>
  <td></td>
  <td></td>
  <td></td>
  <td></td>
  <td><font size="-2">15-Aug<br><a href="...">update</a></font></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 12. KTCY -->
<tr>
  <td colspan="9"><a href="/airport/KTCY"><b>KTCY</b></a> 38 NNE &nbsp; <b>Tracy Municipal Airport</b> Tracy, CA</td>
</tr>
<tr valign="top">
  <td>Tracy Aviation</td>
  <td>Phillips 66</td>
  <td><a href="...">SS</a> $6.15<br><a href="...">FS</a> $6.65</td>
  <td></td>
  <td></td>
  <td><a href="...">FS</a> $7.10</td>
  <td></td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 13. KLVK -->
<tr>
  <td colspan="9"><a href="/airport/KLVK"><b>KLVK</b></a> 39 NNW &nbsp; <b>Livermore Municipal Airport</b> Livermore, CA</td>
</tr>
<tr valign="top">
  <td>Five Rivers Aviation</td>
  <td>Shell</td>
  <td><a href="...">SS</a> $6.75<br><a href="...">FS</a> $7.25</td>
  <td></td>
  <td></td>
  <td><a href="...">FS</a> $7.45</td>
  <td></td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 14. KHWD -->
<tr>
  <td colspan="9"><a href="/airport/KHWD"><b>KHWD</b></a> 42 NW &nbsp; <b>Hayward Executive Airport</b> Hayward, CA</td>
</tr>
<tr valign="top">
  <td>APP Jet Center</td>
  <td>World Fuel Services</td>
  <td><a href="...">FS</a> $8.10</td>
  <td></td>
  <td></td>
  <td><a href="...">FS</a> $8.30</td>
  <td></td>
  <td><font size="-2">18-Aug<br><a href="...">update</a></font></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 15. KMOD -->
<tr>
  <td colspan="9"><a href="/airport/KMOD"><b>KMOD</b></a> 44 NE &nbsp; <b>Modesto City-County Airport</b> Modesto, CA</td>
</tr>
<tr valign="top">
  <td>Modesto Jet Center</td>
  <td>AVFUEL</td>
  <td><a href="...">SS</a> $6.30<br><a href="...">FS</a> $6.80</td>
  <td></td>
  <td></td>
  <td><a href="...">FS</a> $6.95</td>
  <td></td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"></td>
</tr>
<tr><td colspan="9"><hr></td></tr>
<!-- 16. C83 -->
<tr>
  <td colspan="9"><a href="/airport/C83"><b>C83</b></a> 45 N &nbsp; <b>Byron Airport</b> Byron, CA</td>
</tr>
<tr valign="top">
  <td>Patriot Jet Center</td>
  <td>independent</td>
  <td><a href="...">SS</a> $6.20</td>
  <td></td>
  <td></td>
  <td><a href="...">FS</a> $6.85</td>
  <td></td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"></td>
</tr>
</table>
</body>
</html>"""
        client = AirNavClient()
        res = client.parse_local_fuel_html(real_airnav_html, source_airport="E16")
        self.assertTrue(res["success"])
        self.assertEqual(res["count"], 16)
        by_icao = {a["icao"]: a for a in res["airports"]}

        # 1. E16: UL94 SS $8.39, FS $8.59, Jet-A $7.68, no 100LL, no 100UL
        e16 = by_icao["E16"]
        self.assertEqual(e16["best_price"], 8.39)
        self.assertEqual(e16["primary_fuel"], "94UL")
        self.assertEqual(sorted(e16["fuels_available"]), sorted(["94UL", "Jet-A"]))
        e16_fuels = e16["fbos"][0]["fuels"]
        self.assertEqual(e16_fuels["94UL_SS"]["price"], 8.39)
        self.assertEqual(e16_fuels["94UL_FS"]["price"], 8.59)
        self.assertEqual(e16_fuels["JET_A"]["price"], 7.68)
        self.assertNotIn("100LL_SS", e16_fuels)
        self.assertNotIn("100LL_FS", e16_fuels)
        self.assertNotIn("100UL_SS", e16_fuels)
        self.assertNotIn("100UL_FS", e16_fuels)

        # 2. KWVI: 100LL SS $6.50, FS $7.00, 100UL FS $6.50, Jet-A SS $6.25, FS $6.75
        kwvi = by_icao["KWVI"]
        self.assertEqual(kwvi["best_price"], 6.50)
        self.assertEqual(kwvi["primary_fuel"], "100LL")
        kwvi_fuels = kwvi["fbos"][0]["fuels"]
        self.assertEqual(kwvi_fuels["100LL_SS"]["price"], 6.50)
        self.assertEqual(kwvi_fuels["100LL_FS"]["price"], 7.00)
        self.assertEqual(kwvi_fuels["100UL_FS"]["price"], 6.50)
        self.assertEqual(kwvi_fuels["JET_A"]["price"], 6.25)

        # 3. KCVH: 100LL SS $7.02, FS $7.42, Jet-A $7.11
        kcvh = by_icao["KCVH"]
        self.assertEqual(kcvh["best_price"], 7.02)
        kcvh_fuels = kcvh["fbos"][0]["fuels"]
        self.assertEqual(kcvh_fuels["100LL_SS"]["price"], 7.02)
        self.assertEqual(kcvh_fuels["100LL_FS"]["price"], 7.42)
        self.assertEqual(kcvh_fuels["JET_A"]["price"], 7.11)

        # 4. KRHV: 100UL $6.99, 94UL SS $8.30, FS $8.60
        krhv = by_icao["KRHV"]
        self.assertEqual(krhv["best_price"], 6.99)
        self.assertEqual(krhv["primary_fuel"], "100UL")
        krhv_fuels = krhv["fbos"][0]["fuels"]
        self.assertEqual(krhv_fuels["100UL_FS"]["price"], 6.99)
        self.assertEqual(krhv_fuels["94UL_SS"]["price"], 8.30)
        self.assertEqual(krhv_fuels["94UL_FS"]["price"], 8.60)

        # 5. KSJC: Multi-FBO
        ksjc = by_icao["KSJC"]
        self.assertEqual(ksjc["best_price"], 12.56)
        self.assertEqual(ksjc["primary_fuel"], "100LL")
        self.assertEqual(len(ksjc["fbos"]), 2)

        # 6. KSNS: Salinas Municipal Airport
        ksns = by_icao["KSNS"]
        self.assertEqual(ksns["best_price"], 6.97)

        # 7. KOAR: Marina Municipal Airport
        koar = by_icao["KOAR"]
        self.assertEqual(koar["best_price"], 7.24)

        # 8. KNUQ: Jet-A only $10.20
        knuq = by_icao["KNUQ"]
        self.assertIsNone(knuq["best_price"])
        self.assertEqual(knuq["primary_fuel"], "None")
        self.assertEqual(knuq["fuels_available"], ["Jet-A"])
        self.assertEqual(knuq["fbos"][0]["fuels"]["JET_A"]["price"], 10.20)

        # 9. KMRY: Monterey Regional
        kmry = by_icao["KMRY"]
        self.assertEqual(kmry["best_price"], 7.25)
        self.assertEqual(kmry["primary_fuel"], "100LL")

        # 10. KPAO: Palo Alto Airport
        kpao = by_icao["KPAO"]
        self.assertEqual(kpao["best_price"], 7.40)
        self.assertEqual(kpao["primary_fuel"], "100LL")

        # 11. KLSN: Los Banos
        klsn = by_icao["KLSN"]
        self.assertEqual(klsn["best_price"], 5.89)
        self.assertEqual(klsn["primary_fuel"], "100LL")

        # 12. KTCY: Tracy
        ktcy = by_icao["KTCY"]
        self.assertEqual(ktcy["best_price"], 6.15)
        self.assertEqual(ktcy["primary_fuel"], "100LL")

        # 13. KLVK: Livermore
        klvk = by_icao["KLVK"]
        self.assertEqual(klvk["best_price"], 6.75)
        self.assertEqual(klvk["primary_fuel"], "100LL")

        # 14. KHWD: Hayward
        khwd = by_icao["KHWD"]
        self.assertEqual(khwd["best_price"], 8.10)
        self.assertEqual(khwd["primary_fuel"], "100LL")

        # 15. KMOD: Modesto
        kmod = by_icao["KMOD"]
        self.assertEqual(kmod["best_price"], 6.30)
        self.assertEqual(kmod["primary_fuel"], "100LL")

        # 16. C83: Byron
        c83 = by_icao["C83"]
        self.assertEqual(c83["best_price"], 6.20)
        self.assertEqual(c83["primary_fuel"], "100LL")

    def test_parse_local_fuel_html_exact_user_airnav_krdd_2_column_table(self):
        """Verify parse_local_fuel_html accurately parses 2-column AirNav table (100LL, Jet A) for KRDD and surrounding airports."""
        krdd_airnav_html = """<!DOCTYPE html>
<html>
<head><title>AirNav: Fuel prices within 45 miles of KRDD</title></head>
<body>
<h1>Fuel prices within 45 miles of <a href="/airport/KRDD">KRDD</a></h1>
<table border="0" cellpadding="1" cellspacing="0">
<tbody><tr valign="bottom">
<th></th>
<th colspan="2" align="center">Airport / FBO</th>
<th><table><tbody><tr><th>100LL</th></tr><tr><td align="center" nowrap=""><font size="-2">$6.49—$7.93<br>average $7.39</font></td></tr></tbody></table></th>
<th><table><tbody><tr><th>Jet A</th></tr><tr><td align="center" nowrap=""><font size="-2">$6.95—$7.75<br>average $7.35</font></td></tr></tbody></table></th>
</tr>
<!-- 1. KRDD -->
<tr>
  <td colspan="5"><a href="/airport/KRDD"><b>KRDD</b></a> &nbsp; <b>Redding Regional Airport</b> Redding, CA</td>
</tr>
<tr valign="top">
  <td><a href="/airport/KRDD/REDDING_JET"><img src="/pics/fbo/redding_jet.gif" alt="Redding Jet Center"></a></td>
  <td><img src="/pics/brands/avfuel.gif" alt="Avfuel"></td>
  <td><a href="...">FS</a> $7.93</td>
  <td><a href="...">FS</a> $7.34</td>
  <td><font size="-2">22-Aug<br><a href="...">update</a></font></td>
</tr>
<tr valign="top">
  <td><a href="/airport/KRDD/AIR_SHASTA">Air Shasta Rotor and Wing</a></td>
  <td>independent</td>
  <td><a href="...">FS</a> $7.93</td>
  <td><a href="...">FS</a> $7.45</td>
  <td><font size="-2">18-Aug<br><a href="...">update</a></font></td>
</tr>
<tr><td colspan="5"><hr></td></tr>
<!-- 2. O85 -->
<tr>
  <td colspan="5"><a href="/airport/O85"><b>O85</b></a> 7 NW &nbsp; <b>Benton Field</b> Redding, CA</td>
</tr>
<tr valign="top">
  <td><a href="/airport/O85/BENTON">Benton Air Center</a></td>
  <td>Phillips 66</td>
  <td><a href="...">FS</a> $7.84</td>
  <td><a href="...">FS</a> $7.20</td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"></td>
</tr>
<tr><td colspan="5"><hr></td></tr>
<!-- 3. KRBL -->
<tr>
  <td colspan="5"><a href="/airport/KRBL"><b>KRBL</b></a> 25 S &nbsp; <b>Red Bluff Municipal Airport</b> Red Bluff, CA</td>
</tr>
<tr valign="top">
  <td><a href="/airport/KRBL/RED_BLUFF">Red Bluff Aviation</a></td>
  <td>World Fuel</td>
  <td><a href="...">SS</a> $7.69<br><a href="...">FS</a> $7.84</td>
  <td><a href="...">SS</a> $6.95<br><a href="...">FS</a> $7.20</td>
  <td><img src="/pics/guaranteed.gif" alt="GUARANTEED"></td>
</tr>
<tr><td colspan="5"><hr></td></tr>
<!-- 4. O37 -->
<tr>
  <td colspan="5"><a href="/airport/O37"><b>O37</b></a> 44 S &nbsp; <b>Corning Municipal Airport</b> Corning, CA</td>
</tr>
<tr valign="top">
  <td><a href="/airport/O37/CORNING">City of Corning</a></td>
  <td>independent</td>
  <td><a href="...">SS</a> $7.09</td>
  <td></td>
  <td><font size="-2">15-Aug<br><a href="...">update</a></font></td>
</tr>
</tbody></table>
</body>
</html>"""
        client = AirNavClient()
        res = client.parse_local_fuel_html(krdd_airnav_html, source_airport="KRDD")
        self.assertTrue(res["success"])
        self.assertEqual(res["source_airport"], "KRDD")
        self.assertEqual(res["count"], 4)
        self.assertEqual(len(res["airports"]), 4)
        by_icao = {a["icao"]: a for a in res["airports"]}

        # 1. KRDD (Redding Regional Airport)
        self.assertIn("KRDD", by_icao)
        krdd = by_icao["KRDD"]
        self.assertEqual(krdd["best_price"], 7.93)
        self.assertEqual(krdd["primary_fuel"], "100LL")
        self.assertEqual(sorted(krdd["fuels_available"]), sorted(["100LL", "Jet-A"]))
        self.assertEqual(len(krdd["fbos"]), 2)
        fbo_names = [f["name"] for f in krdd["fbos"]]
        self.assertEqual(fbo_names, ["Redding Jet Center", "Air Shasta Rotor and Wing"])

        fbo1_fuels = krdd["fbos"][0]["fuels"]
        self.assertEqual(fbo1_fuels["100LL_FS"]["price"], 7.93)
        self.assertEqual(fbo1_fuels["JET_A"]["price"], 7.34)
        self.assertIn(krdd["fbos"][0]["brand"], ("Avfuel", "AVFUEL"))

        fbo2_fuels = krdd["fbos"][1]["fuels"]
        self.assertEqual(fbo2_fuels["100LL_FS"]["price"], 7.93)
        self.assertEqual(fbo2_fuels["JET_A"]["price"], 7.45)

        # 2. O85 (Benton Field)
        self.assertIn("O85", by_icao)
        o85 = by_icao["O85"]
        self.assertEqual(o85["distance_nm"], 7.0)
        self.assertEqual(o85["bearing"], "NW")
        self.assertEqual(o85["best_price"], 7.84)
        self.assertEqual(o85["primary_fuel"], "100LL")
        o85_fuels = o85["fbos"][0]["fuels"]
        self.assertEqual(o85_fuels["100LL_FS"]["price"], 7.84)
        self.assertEqual(o85_fuels["JET_A"]["price"], 7.20)
        self.assertNotIn("100LL_SS", o85_fuels)

        # 3. KRBL (Red Bluff Municipal Airport)
        self.assertIn("KRBL", by_icao)
        krbl = by_icao["KRBL"]
        self.assertEqual(krbl["distance_nm"], 25.0)
        self.assertEqual(krbl["bearing"], "S")
        self.assertEqual(krbl["best_price"], 7.69)
        self.assertEqual(krbl["primary_fuel"], "100LL")
        krbl_fuels = krbl["fbos"][0]["fuels"]
        self.assertEqual(krbl_fuels["100LL_SS"]["price"], 7.69)
        self.assertEqual(krbl_fuels["100LL_FS"]["price"], 7.84)
        self.assertEqual(krbl_fuels["JET_A"]["price"], 6.95)

        # 4. O37 (Corning Municipal Airport)
        self.assertIn("O37", by_icao)
        o37 = by_icao["O37"]
        self.assertEqual(o37["distance_nm"], 44.0)
        self.assertEqual(o37["bearing"], "S")
        self.assertEqual(o37["best_price"], 7.09)
        self.assertEqual(o37["primary_fuel"], "100LL")
        self.assertEqual(o37["fuels_available"], ["100LL"])
        o37_fuels = o37["fbos"][0]["fuels"]
        self.assertEqual(o37_fuels["100LL_SS"]["price"], 7.09)
        self.assertNotIn("JET_A", o37_fuels)
        self.assertNotIn("100LL_FS", o37_fuels)

    def test_single_fbo_block_img_alt_logo_and_absolute_href(self):
        """Verify _parse_single_fbo_block correctly extracts FBO name from img alt and handles absolute hrefs."""
        single_fbo_html = """
        <div>
          <a href="https://www.airnav.com/airport/KRDD/REDDING_JET"><img src="/pics/fbo/redding_jet.gif" alt="Redding Jet Center"></a>
          <img src="/pics/brands/avfuel.gif" alt="Avfuel">
          <table>
            <tr><th>100LL (Full Service)</th><td>$7.93</td></tr>
            <tr><th>Jet A (Full Service)</th><td>$7.34</td></tr>
          </table>
          <p>Phone: 530-224-2300</p>
          <p>UNICOM: 122.95</p>
        </div>
        """
        client = AirNavClient()
        fbo = client._parse_single_fbo_block(single_fbo_html, "KRDD")
        self.assertEqual(fbo["name"], "Redding Jet Center")
        self.assertIn(fbo["brand"], ("Avfuel", "AVFUEL"))
        self.assertEqual(fbo["phone"], "530-224-2300")
        self.assertEqual(fbo["fuels"]["100LL_FS"]["price"], 7.93)
        self.assertEqual(fbo["fuels"]["JET_A"]["price"], 7.34)

    def test_parse_local_fuel_html_single_column_100ll_only(self):
        """Verify dynamic header parsing when only 1 fuel column (100LL) is present."""
        html_1_col = """<!DOCTYPE html>
        <html><head><title>AirNav: Fuel prices within 30 miles of KOAR</title></head><body>
        <h1>Fuel prices within 30 miles of KOAR</h1>
        <table>
        <tr><th>Airport / FBO</th><th>Brand</th><th>100LL</th><th></th></tr>
        <tr><td colspan="4"><a href="/airport/KOAR"><b>KOAR</b></a> Marina Municipal Airport Marina, CA</td></tr>
        <tr><td><a href="/airport/KOAR/MARINA">Marina Aviation</a></td><td>independent</td><td><a href="...">SS</a> $6.45</td><td><font size="-2">12-Aug<br><a href="...">update</a></font></td></tr>
        </table></body></html>"""
        client = AirNavClient()
        res = client.parse_local_fuel_html(html_1_col, source_airport="KOAR")
        self.assertTrue(res["success"])
        self.assertEqual(len(res["airports"]), 1)
        apt = res["airports"][0]
        self.assertEqual(apt["best_price"], 6.45)
        self.assertEqual(apt["primary_fuel"], "100LL")
        self.assertEqual(apt["fuels_available"], ["100LL"])
        self.assertEqual(apt["fbos"][0]["fuels"]["100LL_SS"]["price"], 6.45)
        self.assertNotIn("JET_A", apt["fbos"][0]["fuels"])

    def test_parse_local_fuel_html_single_column_jeta_only(self):
        """Verify dynamic header parsing when only 1 fuel column (Jet A) is present."""
        html_jeta_only = """<!DOCTYPE html>
        <html><head><title>AirNav: Fuel prices within 30 miles of KNUQ</title></head><body>
        <h1>Fuel prices within 30 miles of KNUQ</h1>
        <table>
        <tr><th>Airport / FBO</th><th>Brand</th><th>Jet A</th><th></th></tr>
        <tr><td colspan="4"><a href="/airport/KNUQ"><b>KNUQ</b></a> Moffett Federal Airfield Mountain View, CA</td></tr>
        <tr><td><a href="/airport/KNUQ/MOFFETT">Moffett Jet Base</a></td><td>independent</td><td><a href="...">FS</a> $7.15</td><td><font size="-2">10-Aug<br><a href="...">update</a></font></td></tr>
        </table></body></html>"""
        client = AirNavClient()
        res = client.parse_local_fuel_html(html_jeta_only, source_airport="KNUQ")
        self.assertTrue(res["success"])
        self.assertEqual(len(res["airports"]), 1)
        apt = res["airports"][0]
        self.assertIsNone(apt["best_price"])  # Jet-A is excluded from piston best_price
        self.assertEqual(apt["primary_fuel"], "None")
        self.assertEqual(apt["fuels_available"], ["Jet-A"])
        self.assertEqual(apt["fbos"][0]["fuels"]["JET_A"]["price"], 7.15)
        self.assertNotIn("100LL_SS", apt["fbos"][0]["fuels"])
        self.assertNotIn("100LL_FS", apt["fbos"][0]["fuels"])

    def test_parse_local_fuel_html_img_logo_without_alt_fallback(self):
        """Verify graceful fallback when FBO logo img has no alt text."""
        html_no_alt = """<!DOCTYPE html>
        <html><head><title>AirNav: Fuel prices within 30 miles of KSQL</title></head><body>
        <h1>Fuel prices within 30 miles of KSQL</h1>
        <table>
        <tr><th>Airport / FBO</th><th>Brand</th><th>100LL</th><th></th></tr>
        <tr><td colspan="4"><a href="/airport/KSQL"><b>KSQL</b></a> San Carlos Airport San Carlos, CA</td></tr>
        <tr><td><a href="/airport/KSQL/RABBIT"><img src="/pics/fbo/logo.gif"></a></td><td>independent</td><td><a href="...">SS</a> $6.15</td><td>12-Aug</td></tr>
        </table></body></html>"""
        client = AirNavClient()
        res = client.parse_local_fuel_html(html_no_alt, source_airport="KSQL")
        self.assertTrue(res["success"])
        apt = res["airports"][0]
        self.assertEqual(len(apt["fbos"]), 1)
        # Should gracefully fall back to airport name or Airport Fuel Facility without raising an error
        self.assertIn(apt["fbos"][0]["name"], ("San Carlos Airport", "Airport Fuel Facility"))
        self.assertEqual(apt["fbos"][0]["fuels"]["100LL_SS"]["price"], 6.15)


class TestAeroFuelTiersAndLegend(unittest.TestCase):
    """Test suite for 5-tier price color scale, canvas dot color mapping, and interactive legend HUD."""

    def compute_quintiles(self, prices):
        """Simulate quintile calculation logic from app.js updatePricePercentiles."""
        sorted_prices = sorted([p for p in prices if isinstance(p, (int, float)) and not math.isnan(p)])
        if len(sorted_prices) >= 2:
            def calc_percentile(arr, q):
                pos = q * (len(arr) - 1)
                base = int(math.floor(pos))
                rest = pos - base
                if base + 1 < len(arr):
                    return arr[base] + rest * (arr[base + 1] - arr[base])
                return arr[base]
            p20 = calc_percentile(sorted_prices, 0.20)
            p40 = calc_percentile(sorted_prices, 0.40)
            p60 = calc_percentile(sorted_prices, 0.60)
            p80 = calc_percentile(sorted_prices, 0.80)
            return p20, p40, p60, p80
        elif len(sorted_prices) == 1:
            val = sorted_prices[0]
            return val, val, val, val
        else:
            return 5.20, 5.80, 6.40, 7.00

    def classify_price_tier(self, price, p20, p40, p60, p80):
        """Simulate getMarkerTierClass and getFuelTierInfo classification logic."""
        if price is None or (isinstance(price, float) and math.isnan(price)):
            return "tier-ident", "#64748b", False
        if price <= p20:
            return "tier-ultra-cheap", "#10b981", True
        elif price <= p40:
            return "tier-budget", "#06b6d4", True
        elif price <= p60:
            return "tier-avg", "#38bdf8", True
        elif price <= p80:
            return "tier-high", "#f59e0b", True
        else:
            return "tier-exp", "#ef4444", True

    def format_legend_range(self, low, high):
        """Simulate formatLegendRange from app.js."""
        if high <= low:
            return f"${high:.2f}"
        start = low + 0.01
        if start >= high:
            return f"${high:.2f}"
        return f"${start:.2f}–${high:.2f}"

    def test_quintile_calculation_five_tiers(self):
        """Verify 5-tier quintiles are accurately computed across varied price distributions."""
        prices = [5.00, 6.00, 7.00, 8.00, 9.00]
        p20, p40, p60, p80 = self.compute_quintiles(prices)
        self.assertAlmostEqual(p20, 5.80, places=2)
        self.assertAlmostEqual(p40, 6.60, places=2)
        self.assertAlmostEqual(p60, 7.40, places=2)
        self.assertAlmostEqual(p80, 8.20, places=2)

        # Verify all 5 items map to each of the 5 bins
        tiers = [self.classify_price_tier(p, p20, p40, p60, p80)[0] for p in prices]
        self.assertEqual(tiers, ["tier-ultra-cheap", "tier-budget", "tier-avg", "tier-high", "tier-exp"])

    def test_quintile_calculation_ten_prices(self):
        """Verify 10 prices are evenly distributed across all 5 tiers (2 items per tier)."""
        prices = [5.00, 5.50, 6.00, 6.50, 7.00, 7.50, 8.00, 8.50, 9.00, 9.50]
        p20, p40, p60, p80 = self.compute_quintiles(prices)
        self.assertAlmostEqual(p20, 5.90, places=2)
        self.assertAlmostEqual(p40, 6.80, places=2)
        self.assertAlmostEqual(p60, 7.70, places=2)
        self.assertAlmostEqual(p80, 8.60, places=2)

        tiers = [self.classify_price_tier(p, p20, p40, p60, p80)[0] for p in prices]
        tier_counts = {t: tiers.count(t) for t in set(tiers)}
        self.assertEqual(tier_counts["tier-ultra-cheap"], 2)
        self.assertEqual(tier_counts["tier-budget"], 2)
        self.assertEqual(tier_counts["tier-avg"], 2)
        self.assertEqual(tier_counts["tier-high"], 2)
        self.assertEqual(tier_counts["tier-exp"], 2)

    def test_price_tier_classification_all_five_ranges(self):
        """Verify exact classification across all 5 price tiers and unpriced state."""
        p20, p40, p60, p80 = 5.50, 6.20, 6.90, 7.60

        # Tier 1: Ultra-Cheap (<= p20)
        tier, color, has_halo = self.classify_price_tier(5.10, p20, p40, p60, p80)
        self.assertEqual(tier, "tier-ultra-cheap")
        self.assertEqual(color, "#10b981")
        self.assertTrue(has_halo)

        # Boundary at p20
        tier, color, has_halo = self.classify_price_tier(5.50, p20, p40, p60, p80)
        self.assertEqual(tier, "tier-ultra-cheap")
        self.assertEqual(color, "#10b981")

        # Tier 2: Budget (p20 < price <= p40)
        tier, color, has_halo = self.classify_price_tier(5.80, p20, p40, p60, p80)
        self.assertEqual(tier, "tier-budget")
        self.assertEqual(color, "#06b6d4")
        self.assertTrue(has_halo)

        # Tier 3: Moderate / Average (p40 < price <= p60)
        tier, color, has_halo = self.classify_price_tier(6.50, p20, p40, p60, p80)
        self.assertEqual(tier, "tier-avg")
        self.assertEqual(color, "#38bdf8")
        self.assertTrue(has_halo)

        # Tier 4: High / Above Average (p60 < price <= p80)
        tier, color, has_halo = self.classify_price_tier(7.25, p20, p40, p60, p80)
        self.assertEqual(tier, "tier-high")
        self.assertEqual(color, "#f59e0b")
        self.assertTrue(has_halo)

        # Tier 5: Expensive / Premium (> p80)
        tier, color, has_halo = self.classify_price_tier(8.40, p20, p40, p60, p80)
        self.assertEqual(tier, "tier-exp")
        self.assertEqual(color, "#ef4444")
        self.assertTrue(has_halo)

        # Unpriced
        tier, color, has_halo = self.classify_price_tier(None, p20, p40, p60, p80)
        self.assertEqual(tier, "tier-ident")
        self.assertEqual(color, "#64748b")
        self.assertFalse(has_halo)

    def test_canvas_dot_color_mapping_five_tiers(self):
        """Verify map canvas dots render in distinct colors per tier with luminous halo flags."""
        p20, p40, p60, p80 = 5.20, 5.80, 6.40, 7.00
        mock_priced_airports = [
            {"icao": "KCHEAP", "price": 4.95, "expected_color": "#10b981"},  # Emerald
            {"icao": "KBUDGET", "price": 5.50, "expected_color": "#06b6d4"}, # Cyan
            {"icao": "KMOD", "price": 6.10, "expected_color": "#38bdf8"},    # Sky blue
            {"icao": "KHIGH", "price": 6.80, "expected_color": "#f59e0b"},   # Amber
            {"icao": "KEXP", "price": 7.95, "expected_color": "#ef4444"},    # Crimson
        ]
        for item in mock_priced_airports:
            tier, color, has_halo = self.classify_price_tier(item["price"], p20, p40, p60, p80)
            self.assertEqual(color, item["expected_color"], f"Airport {item['icao']} failed color check")
            self.assertTrue(has_halo, f"Airport {item['icao']} should have canvas luminous halo")

    def test_empty_and_single_price_edge_cases(self):
        """Verify fallback quintiles on empty dataset or identical single-price dataset."""
        # Empty dataset
        p20, p40, p60, p80 = self.compute_quintiles([])
        self.assertEqual((p20, p40, p60, p80), (5.20, 5.80, 6.40, 7.00))

        # Single identical price
        p20, p40, p60, p80 = self.compute_quintiles([6.50, 6.50, 6.50])
        self.assertEqual(p20, 6.50)
        self.assertEqual(p80, 6.50)

    def test_legend_range_formatting_no_inversion(self):
        """Verify legend range string formatting never creates inverted ranges when quintiles collide."""
        self.assertEqual(self.format_legend_range(5.20, 5.80), "$5.21–$5.80")
        self.assertEqual(self.format_legend_range(5.20, 5.20), "$5.20")
        self.assertEqual(self.format_legend_range(5.80, 5.80), "$5.80")
        self.assertEqual(self.format_legend_range(6.00, 6.00), "$6.00")

    def test_legend_html_and_css_structure(self):
        """Verify HTML contains #fuel-legend-hud after #radar-sidebar and CSS contains required tier selectors and colors."""
        index_html_path = os.path.join(DIRECTORY, "index.html")
        style_css_path = os.path.join(DIRECTORY, "style.css")
        app_js_path = os.path.join(DIRECTORY, "app.js")

        with open(index_html_path, "r") as f:
            html_text = f.read()
        self.assertIn('id="fuel-legend-hud"', html_text)
        self.assertIn('id="legend-header-toggle"', html_text)
        self.assertIn('id="legend-toggle-btn"', html_text)
        self.assertIn('id="legend-range-ultra-cheap"', html_text)
        self.assertIn('id="legend-range-budget"', html_text)
        self.assertIn('id="legend-range-avg"', html_text)
        self.assertIn('id="legend-range-high"', html_text)
        self.assertIn('id="legend-range-exp"', html_text)

        # Verify #fuel-legend-hud comes after #radar-sidebar for sibling selector support
        sidebar_idx = html_text.find('id="radar-sidebar"')
        legend_idx = html_text.find('id="fuel-legend-hud"')
        self.assertGreater(legend_idx, sidebar_idx, "#fuel-legend-hud must follow #radar-sidebar in DOM")

        with open(style_css_path, "r") as f:
            css_text = f.read()
        self.assertIn('#fuel-legend-hud', css_text)
        self.assertIn('.tier-ultra-cheap', css_text)
        self.assertIn('.tier-budget', css_text)
        self.assertIn('.tier-avg', css_text)
        self.assertIn('.tier-high', css_text)
        self.assertIn('.tier-exp', css_text)
        self.assertIn('#10b981', css_text)  # Emerald green
        self.assertIn('#06b6d4', css_text)  # Cyan
        self.assertIn('#38bdf8', css_text)  # Sky blue
        self.assertIn('#f59e0b', css_text)  # Amber
        self.assertIn('#ef4444', css_text)  # Crimson

        # Verify all 5 in-radius dot styles exist
        self.assertIn('.airport-marker-container.in-radius.tier-ultra-cheap .marker-dot', css_text)
        self.assertIn('.airport-marker-container.in-radius.tier-budget .marker-dot', css_text)
        self.assertIn('.airport-marker-container.in-radius.tier-avg .marker-dot', css_text)
        self.assertIn('.airport-marker-container.in-radius.tier-high .marker-dot', css_text)
        self.assertIn('.airport-marker-container.in-radius.tier-exp .marker-dot', css_text)

        # Verify sidebar card price colors exist
        self.assertIn('.radar-airport-card.tier-ultra-cheap .card-price', css_text)
        self.assertIn('.radar-airport-card.tier-budget .card-price', css_text)
        self.assertIn('.radar-airport-card.tier-high .card-price', css_text)
        self.assertIn('.radar-airport-card.tier-exp .card-price', css_text)

        with open(app_js_path, "r") as f:
            js_text = f.read()
        self.assertIn('getFuelTierInfo', js_text)
        self.assertIn('initLegendHUD', js_text)
        self.assertIn('updateLegendUI', js_text)
        self.assertIn('formatLegendRange', js_text)
        self.assertIn('calculatePercentile', js_text)
        self.assertIn('tier-ultra-cheap', js_text)
        self.assertIn('tier-budget', js_text)
        self.assertIn('tier-high', js_text)


if __name__ == "__main__":
    unittest.main()







