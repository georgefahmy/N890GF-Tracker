/**
 * Van's Aircraft Painting Prototype - Isolated Sub-View Vector Model Definitions
 * Hierarchy: /static/models/<model>/<model>_side.svg, <model>_top.svg, <model>_front.svg
 * True transformed viewports for exact 100% container fit
 */

window.VANS_AIRCRAFT_MODELS = {
    "rv10": {
        id: "rv10",
        name: "Van's RV-10",
        type: "4-Seat Cross Country",
        gear: "tricycle",
        wingspanFt: "31.7 ft",
        lengthFt: "24.4 ft",
        emptyWeight: "1,630 lbs",
        description: "4-place high performance touring aircraft.",
        views: {
            side: { file: "/static/models/rv10/rv10_side.svg", viewBox: "0 0 98.5 42.8" },
            top: { file: "/static/models/rv10/rv10_top.svg", viewBox: "0 0 98.3 129.6" },
            front: { file: "/static/models/rv10/rv10_front.svg", viewBox: "0 0 129.5 40.7" },
            combined: { file: "/static/models/rv10/rv10.svg", viewBox: "0 0 210 297" },
        }
    },
    "rv12": {
        id: "rv12",
        name: "Van's RV-12",
        type: "Light Sport Aircraft",
        gear: "tricycle",
        wingspanFt: "26.7 ft",
        lengthFt: "19.9 ft",
        emptyWeight: "740 lbs",
        description: "Rotax-powered 2-place Light Sport Aircraft (LSA).",
        views: {
            side: { file: "/static/models/rv12/rv12_side.svg", viewBox: "0 0 89.4 39.8" },
            top: { file: "/static/models/rv12/rv12_top.svg", viewBox: "0 0 89.4 117.4" },
            front: { file: "/static/models/rv12/rv12_front.svg", viewBox: "0 0 117.4 41.9" },
            combined: { file: "/static/models/rv12/rv12.svg", viewBox: "0 0 210 297" },
        }
    },
    "rv12is": {
        id: "rv12is",
        name: "Van's RV-12iS",
        type: "Light Sport Fuel-Injected",
        gear: "tricycle",
        wingspanFt: "26.7 ft",
        lengthFt: "19.9 ft",
        emptyWeight: "775 lbs",
        description: "Rotax 912iS fuel-injected 2-place Light Sport Aircraft.",
        views: {
            side: { file: "/static/models/rv12is/rv12is_side.svg", viewBox: "0 0 111.3 47.8" },
            top: { file: "/static/models/rv12is/rv12is_top.svg", viewBox: "0 0 111.8 145.6" },
            front: { file: "/static/models/rv12is/rv12is_front.svg", viewBox: "0 0 145.6 47.8" },
            combined: { file: "/static/models/rv12is/rv12is.svg", viewBox: "0 0 210 297" },
        }
    },
    "rv14": {
        id: "rv14",
        name: "Van's RV-14",
        type: "Performance Aerobatic Taildragger",
        gear: "taildragger",
        wingspanFt: "27.0 ft",
        lengthFt: "21.1 ft",
        emptyWeight: "1,240 lbs",
        description: "Modern aerobatic 2-seater with roomier cabin.",
        views: {
            side: { file: "/static/models/rv14/rv14_side.svg", viewBox: "0 0 59.2 28.6" },
            top: { file: "/static/models/rv14/rv14_top.svg", viewBox: "0 0 59.2 74.0" },
            front: { file: "/static/models/rv14/rv14_front.svg", viewBox: "0 0 74.0 28.8" },
            combined: { file: "/static/models/rv14/rv14.svg", viewBox: "0 0 210 297" },
        }
    },
    "rv14a": {
        id: "rv14a",
        name: "Van's RV-14A",
        type: "Performance Aerobatic Tricycle",
        gear: "tricycle",
        wingspanFt: "27.0 ft",
        lengthFt: "21.1 ft",
        emptyWeight: "1,285 lbs",
        description: "Modern aerobatic 2-seater with tricycle nosewheel.",
        views: {
            side: { file: "/static/models/rv14a/rv14a_side.svg", viewBox: "0 0 59.2 28.0" },
            top: { file: "/static/models/rv14a/rv14a_top.svg", viewBox: "0 0 59.2 74.0" },
            front: { file: "/static/models/rv14a/rv14a_front.svg", viewBox: "0 0 74.0 28.0" },
            combined: { file: "/static/models/rv14a/rv14a.svg", viewBox: "0 0 210 297" },
        }
    },
    "rv3": {
        id: "rv3",
        name: "Van's RV-3",
        type: "Single-Seat Aerobatic",
        gear: "taildragger",
        wingspanFt: "19.9 ft",
        lengthFt: "19.0 ft",
        emptyWeight: "750 lbs",
        description: "Single-seat light aerobatic aircraft with clean lines and taildragger gear.",
        views: {
            side: { file: "/static/models/rv3/rv3_side.svg", viewBox: "0 0 107.8 44.2" },
            top: { file: "/static/models/rv3/rv3_top.svg", viewBox: "0 0 108.2 113.0" },
            front: { file: "/static/models/rv3/rv3_front.svg", viewBox: "0 0 113.0 44.0" },
            combined: { file: "/static/models/rv3/rv3.svg", viewBox: "0 0 210 297" },
        }
    },
    "rv4": {
        id: "rv4",
        name: "Van's RV-4",
        type: "Tandem Two-Seat Aerobatic",
        gear: "taildragger",
        wingspanFt: "23.0 ft",
        lengthFt: "20.4 ft",
        emptyWeight: "905 lbs",
        description: "Tandem two-seat aerobatic aircraft with fighter-style canopy.",
        views: {
            side: { file: "/static/models/rv4/rv4_side.svg", viewBox: "0 0 116.9 48.8" },
            top: { file: "/static/models/rv4/rv4_top.svg", viewBox: "0 0 112.3 130.3" },
            front: { file: "/static/models/rv4/rv4_front.svg", viewBox: "0 0 130.3 43.0" },
            combined: { file: "/static/models/rv4/rv4.svg", viewBox: "0 0 210 297" },
        }
    },
    "rv6": {
        id: "rv6",
        name: "Van's RV-6",
        type: "Side-by-Side Two-Seat",
        gear: "taildragger",
        wingspanFt: "23.0 ft",
        lengthFt: "20.2 ft",
        emptyWeight: "965 lbs",
        description: "Side-by-side two-seat taildragger aircraft.",
        views: {
            side: { file: "/static/models/rv6/rv6_side.svg", viewBox: "0 0 112.2 48.6" },
            top: { file: "/static/models/rv6/rv6_top.svg", viewBox: "0 0 110.4 124.2" },
            front: { file: "/static/models/rv6/rv6_front.svg", viewBox: "0 0 124.2 46.5" },
            combined: { file: "/static/models/rv6/rv6.svg", viewBox: "0 0 210 297" },
        }
    },
    "rv6a": {
        id: "rv6a",
        name: "Van's RV-6A",
        type: "Side-by-Side Two-Seat",
        gear: "tricycle",
        wingspanFt: "23.0 ft",
        lengthFt: "20.2 ft",
        emptyWeight: "1,015 lbs",
        description: "Side-by-side two-seat tricycle nosewheel aircraft.",
        views: {
            side: { file: "/static/models/rv6a/rv6a_side.svg", viewBox: "0 0 109.6 47.6" },
            top: { file: "/static/models/rv6a/rv6a_top.svg", viewBox: "0 0 110.2 126.8" },
            front: { file: "/static/models/rv6a/rv6a_front.svg", viewBox: "0 0 126.8 48.0" },
            combined: { file: "/static/models/rv6a/rv6a.svg", viewBox: "0 0 210 297" },
        }
    },
    "rv7": {
        id: "rv7",
        name: "Van's RV-7",
        type: "Side-by-Side Aerobatic",
        gear: "taildragger",
        wingspanFt: "25.0 ft",
        lengthFt: "20.4 ft",
        emptyWeight: "1,110 lbs",
        description: "Side-by-side aerobatic kitplane with taildragger landing gear.",
        views: {
            side: { file: "/static/models/rv7/rv7_side.svg", viewBox: "0 0 99.3 46.7" },
            top: { file: "/static/models/rv7/rv7_top.svg", viewBox: "0 0 99.8 122.0" },
            front: { file: "/static/models/rv7/rv7_front.svg", viewBox: "0 0 121.9 43.9" },
            combined: { file: "/static/models/rv7/rv7.svg", viewBox: "0 0 210 297" },
        }
    },
    "rv7a": {
        id: "rv7a",
        name: "Van's RV-7A",
        type: "Side-by-Side Aerobatic",
        gear: "tricycle",
        wingspanFt: "25.0 ft",
        lengthFt: "20.4 ft",
        emptyWeight: "1,155 lbs",
        description: "Side-by-side aerobatic kitplane with tricycle nosewheel gear.",
        views: {
            side: { file: "/static/models/rv7a/rv7a_side.svg", viewBox: "0 0 98.8 44.7" },
            top: { file: "/static/models/rv7a/rv7a_top.svg", viewBox: "0 0 99.4 121.5" },
            front: { file: "/static/models/rv7a/rv7a_front.svg", viewBox: "0 0 121.5 44.3" },
            combined: { file: "/static/models/rv7a/rv7a.svg", viewBox: "0 0 210 297" },
        }
    },
    "rv8": {
        id: "rv8",
        name: "Van's RV-8",
        type: "Tandem Two-Seat Fighter-Style",
        gear: "taildragger",
        wingspanFt: "24.0 ft",
        lengthFt: "21.0 ft",
        emptyWeight: "1,120 lbs",
        description: "Tandem two-seat fighter-style aerobatic taildragger.",
        views: {
            side: { file: "/static/models/rv8/rv8_side.svg", viewBox: "0 0 111.5 47.5" },
            top: { file: "/static/models/rv8/rv8_top.svg", viewBox: "0 0 107.6 124.5" },
            front: { file: "/static/models/rv8/rv8_front.svg", viewBox: "0 0 124.0 46.6" },
            combined: { file: "/static/models/rv8/rv8.svg", viewBox: "0 0 210 297" },
        }
    },
    "rv8a": {
        id: "rv8a",
        name: "Van's RV-8A",
        type: "Tandem Two-Seat Fighter-Style",
        gear: "tricycle",
        wingspanFt: "24.0 ft",
        lengthFt: "21.0 ft",
        emptyWeight: "1,165 lbs",
        description: "Tandem two-seat fighter-style aerobatic tricycle nosewheel.",
        views: {
            side: { file: "/static/models/rv8a/rv8a_side.svg", viewBox: "0 0 114.4 48.6" },
            top: { file: "/static/models/rv8a/rv8a_top.svg", viewBox: "0 0 114.1 131.9" },
            front: { file: "/static/models/rv8a/rv8a_front.svg", viewBox: "0 0 131.5 48.6" },
            combined: { file: "/static/models/rv8a/rv8a.svg", viewBox: "0 0 210 297" },
        }
    },
    "rv9": {
        id: "rv9",
        name: "Van's RV-9",
        type: "Cross-Country High-Efficiency",
        gear: "taildragger",
        wingspanFt: "28.0 ft",
        lengthFt: "20.5 ft",
        emptyWeight: "1,075 lbs",
        description: "High-efficiency cross-country wing taildragger.",
        views: {
            side: { file: "/static/models/rv9/rv9_side.svg", viewBox: "0 0 93.5 44.1" },
            top: { file: "/static/models/rv9/rv9_top.svg", viewBox: "0 0 92.5 127.1" },
            front: { file: "/static/models/rv9/rv9_front.svg", viewBox: "0 0 120.6 41.8" },
            combined: { file: "/static/models/rv9/rv9.svg", viewBox: "0 0 210 297" },
        }
    },
    "rv9a": {
        id: "rv9a",
        name: "Van's RV-9A",
        type: "Cross-Country High-Efficiency",
        gear: "tricycle",
        wingspanFt: "28.0 ft",
        lengthFt: "20.5 ft",
        emptyWeight: "1,125 lbs",
        description: "High-efficiency cross-country wing tricycle nosewheel.",
        views: {
            side: { file: "/static/models/rv9a/rv9a_side.svg", viewBox: "0 0 83.2 38.1" },
            top: { file: "/static/models/rv9a/rv9a_top.svg", viewBox: "0 0 83.2 114.2" },
            front: { file: "/static/models/rv9a/rv9a_front.svg", viewBox: "0 0 114.2 38.1" },
            combined: { file: "/static/models/rv9a/rv9a.svg", viewBox: "0 0 210 297" },
        }
    },
};

window.VANS_DEFAULT_SECTIONS = [
    { id: "spinner", name: "Prop Spinner", defaultColor: "#D61A1F" },
    { id: "cowl", name: "Engine Cowling", defaultColor: "#FFFFFF" },
    { id: "fuselage_main", name: "Fuselage Body", defaultColor: "#FFFFFF" },
    { id: "canopy", name: "Canopy Glass", defaultColor: "rgba(100, 200, 255, 0.4)" },
    { id: "vertical_fin", name: "Vertical Fin / Tail", defaultColor: "#FFFFFF" },
    { id: "rudder", name: "Rudder", defaultColor: "#D61A1F" },
    { id: "wings", name: "Wings & Tips", defaultColor: "#FFFFFF" },
    { id: "wheel_pants", name: "Wheel Pants", defaultColor: "#0047AB" }
];