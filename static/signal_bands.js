// --- BAND CONFIGURATION (Global State) ---
const SIGNAL_BANDS = {
    "Indicated Airspeed (knots)": [
        { min: 49, max: 86, color: "white" },
        { min: 55, max: 170, color:"#00ff00" },
        { min: 168, max: 200, color: "#ffff00" },
        { min: 200, color: "#ff0000" }
    ],
    "True Airspeed (knots)": [
        { min: 49, max: 86, color: "white" },
        { min: 55, max: 170, color:"#00ff00" },
        { min: 168, max: 200, color: "#ffff00" },
        { min: 200, color: "#ff0000" }
    ],
    "RPM": [
        { min: 900, max: 2600, color:"#00ff00" },
        { min: 2600, max: 2700, color: "#ffff00" },
        { min: 2700, color: "#ff0000" }
    ],
    "Manifold Pressure (inHg)": [
        { min: 10, max: 29.2, color:"#00ff00" }
    ],
    "FUEL PRESSURE (PSI)": [
        { min: 0, max: 14, color: "#ffff00" },
        { min: 14, max: 35, color:"#00ff00" },
        { min: 35, color: "#ffff00" }
    ],
    "OIL PRESSURE (PSI)": [
        { min: 0, max: 25, color: "#ff0000" },
        { min: 25, max: 50, color: "#ffff00" },
        { min: 50, max: 95, color: "#00ff00" },
        { min: 95, max: 115, color: "#ffff00" },
        { min: 115, color: "#ff0000" }
    ],
    "OIL TEMPERATURE (deg F)": [
        { min: 0, max: 100, color: "#ff0000" },
        { min: 100, max: 130, color: "#ffff00" },
        { min: 130, max: 220, color:"#00ff00" },
        { min: 220, max: 240, color: "#ffff00" },
        { min: 240, color: "#ff0000" }
    ],
    "CHT": [
        { max: 300, color: "#ffff00" },
        { min: 300, max: 410, color:"#00ff00" },
        { min: 410, max: 430, color: "#ffff00" },
        { min: 430, max: 500, color: "#ff0000" }
    ],
    "EGT": [
        { max: 1000, color: "#ffff00" },
        { min: 1000, max: 1400, color:"#00ff00" },
        { min: 1400, max: 1650, color: "#ffff00" },
        { min: 1650, max: 1800, color: "#ff0000" }
    ],
    "Fuel Level L": [
        { max: 0, max: 1, color: "#ff0000" },
        { min: 1, max: 6, color: "#ffff00" },
        { min: 6, max: 21, color:"#00ff00" }
    ],
    "Fuel Level R": [
        { max: 0, max: 1, color: "#ff0000" },
        { min: 1, max: 6, color: "#ffff00" },
        { min: 6, max: 21, color:"#00ff00" }
    ]
};