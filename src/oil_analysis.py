import os
import re

import pdfplumber


def parse_oil_report(pdf_path):
    data = {"metadata": {}, "metals": {}, "diagnosis": ""}

    with pdfplumber.open(pdf_path) as pdf:
        # Extract all text from the first page
        first_page = pdf.pages[0]
        text = first_page.extract_text()

        # 1. Parse Metadata using Regex
        # Looking for patterns like "Oil Hrs", "13"
        metadata_map = {
            "sample_no": "Sample No\\.\\s*(\\d+)",
            "date_sampled": "Date Sampled\\s*([0-9]+-[a-zA-Z]+-[0-9]+)",
            "oil_brand": "Oil Brand\\s*\\s*([^\\n]+)",
            "oil_hrs": "Oil Hrs\\s*\\s*(\\d+)",
            "engine_hrs": "Hrs Since New\\s*\\s*(\\d+)",
        }

        for key, pattern in metadata_map.items():
            match = re.search(pattern, text)
            if match:
                data["metadata"][key] = match.group(1).strip()

        # 2. Parse Wear Metals (ppm)
        # These are usually listed with the label followed by the numeric value
        metals_map = {
            "Chromium": "Chromium \\(Cr\\)\\s*([\\d\\.<>]+)",
            "Iron": "Iron \\(Fe\\)\\s*([\\d\\.<>]+)",
            "Copper": "Copper \\(Cu\\)\\s*([\\d\\.<>]+)",
            "Aluminium": "Aluminium \\(Al\\)\\s*([\\d\\.<>]+)",
            "Nickel": "Nickel \\(Ni\\)\\s*([\\d\\.<>]+)",
            "Lead": "Lead \\(Pb\\)\\s*([\\d\\.<>]+)",
        }

        for metal, pattern in metals_map.items():
            match = re.search(pattern, text)
            if match:
                # Clean up values like "<1" or "24.29"
                val = match.group(1).strip()
                data["metals"][metal] = val

        # 3. Parse Diagnosis
        if "Diagnosis/Recommendations" in text:
            diag_part = text.split("Diagnosis/Recommendations")[-1].split("Page")[0]
            data["diagnosis"] = diag_part.strip()

    return data


# Example usage for the web app
if __name__ == "__main__":
    report_path = (
        "static/oil_analysis/George_Fah_UnitN890GF_Single_Eng_Normal_92825407.pdf"
    )
    if os.path.exists(report_path):
        results = parse_oil_report(report_path)
        print(results)
