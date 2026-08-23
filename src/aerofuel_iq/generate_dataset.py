#!/usr/bin/env python3
"""
generate_dataset.py
Generates the comprehensive 5,000+ US public-use airport dataset for AeroFuel IQ.
Delegates to fetch_fuel_data.py builder for unified schema and validation.
"""

import json
import os
import sys
from fetch_fuel_data import build_dataset, validate_dataset, print_stats

if __name__ == "__main__":
    out_dir = os.path.dirname(os.path.abspath(__file__))
    json_out_file = os.path.join(out_dir, "fuel_data.json")
    js_out_file = os.path.join(out_dir, "fuel_data.js")

    data = build_dataset()
    errors = validate_dataset(data)
    if errors:
        print(f"Validation failed with {len(errors)} errors:")
        for e in errors[:10]:
            print(f"  - {e}")
        sys.exit(1)

    payload = {
        "version": "2026.08.21",
        "updated_at": "2026-08-21T15:00:00Z",
        "data_source": "AeroFuel National GA Fuel Network / OurAirports & FAA Public Airfield Directory",
        "total_airports": len(data),
        "airports": data
    }

    with open(json_out_file, "w") as f:
        json.dump(payload, f, indent=2)

    with open(js_out_file, "w") as f:
        f.write("// AeroFuel IQ Static Airport Database\n")
        f.write("window.EMBEDDED_AIRPORTS = ")
        json.dump(payload, f, indent=2)
        f.write(";\n")

    print(f"Successfully generated {len(data):,} airport records.")
    print_stats(data)
