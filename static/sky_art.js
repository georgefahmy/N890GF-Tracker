/**
 * Flight Art / Sky Art Generator & ForeFlight Exporter
 * Interactive map drawing, vector SVG & transparent PNG import,
 * spatial transformation, and ForeFlight flight plan generation.
 */

(function () {
    'use strict';

    // Default Home Airport: E16 (San Martin Airport, CA)
    const DEFAULT_HOME_AIRPORT = {
        icao: 'E16',
        faa: 'E16',
        name: 'San Martin Airport',
        lat: 37.0816,
        lon: -121.5970
    };

    const HOME_AIRPORT_STORAGE_KEY = 'sky_art_home_airport';
    const LEGACY_HOME_AIRPORT_STORAGE_KEY = 'flight_art_home_airport';

    function loadConfiguredHomeAirport() {
        try {
            const saved = localStorage.getItem(HOME_AIRPORT_STORAGE_KEY) || localStorage.getItem(LEGACY_HOME_AIRPORT_STORAGE_KEY);
            if (saved) {
                const parsed = JSON.parse(saved);
                if (parsed && (parsed.icao || parsed.faa) && !isNaN(parsed.lat) && !isNaN(parsed.lon)) {
                    return parsed;
                }
            }
        } catch (e) {
            console.error("Error loading home airport from localStorage:", e);
        }
        return { ...DEFAULT_HOME_AIRPORT };
    }

    function saveConfiguredHomeAirport(airportObj) {
        if (!airportObj) return;
        try {
            localStorage.setItem(HOME_AIRPORT_STORAGE_KEY, JSON.stringify(airportObj));
        } catch (e) {
            console.error("Error saving home airport to localStorage:", e);
        }
        ArtState.homeAirport = airportObj;
        updateHomeAirportUI();
    }

    const initialHome = loadConfiguredHomeAirport();

    // --- State Management ---
    const ArtState = {
        map: null,
        layers: {
            osm: null,
            cartoDark: null,
            cartoVoyager: null,
            satellite: null
        },
        homeAirport: initialHome,
        basePoints: [],        // Normalized points in [-0.5, 0.5] space
        rawProjectedPoints: [],// Latitude/Longitude points before simplification
        projectedPoints: [],   // Active simplified flight path [{lat, lon}]
        waypoints: [],         // Full flight plan route including airport transit
        center: { lat: initialHome.lat, lon: initialHome.lon },
        sizeNM: 12,            // Width in Nautical Miles
        heightNM: 12,          // Height in Nautical Miles
        lockAspect: true,      // Proportional width & height link
        rotationDeg: 0,        // Heading rotation (0-359 deg)
        flipH: false,
        flipV: false,
        aspectRatio: 1.0,
        simplificationTolerance: 0.015, // RDP epsilon
        cruiseSpeedKts: 150,   // RV-7 default cruise speed
        fuelFlowGPH: 8.5,      // RV-7 default fuel burn
        includeAirport: true,
        optimizeEntryExit: true, // Auto-optimize start/end waypoint for shortest transit
        routeReversed: false,    // Reverse traversal direction
        depAirport: { ...initialHome },
        arrAirport: { ...initialHome },
        drawMode: false,       // Freehand drawing mode active
        clickMode: false,      // Waypoint click mode active
        isDrawing: false,
        currentFreehandPoints: [],
        mapMarkers: [],
        centerMarker: null,
        routePolyline: null,
        transitPolylineDep: null,
        transitPolylineArr: null,
        tempFreehandPolyline: null
    };

    // --- History Manager (Undo / Redo) ---
    const HistoryManager = {
        undoStack: [],
        redoStack: [],
        maxSize: 50,
        isApplying: false,

        captureSnapshot() {
            return {
                basePoints: ArtState.basePoints ? ArtState.basePoints.map(p => ({ x: p.x, y: p.y })) : [],
                projectedPoints: ArtState.projectedPoints ? ArtState.projectedPoints.map(p => ({ lat: p.lat, lon: p.lon })) : [],
                sizeNM: ArtState.sizeNM,
                heightNM: ArtState.heightNM,
                lockAspect: ArtState.lockAspect,
                aspectRatio: ArtState.aspectRatio,
                rotationDeg: ArtState.rotationDeg,
                flipH: ArtState.flipH,
                flipV: ArtState.flipV,
                center: { ...ArtState.center },
                simplificationTolerance: ArtState.simplificationTolerance,
                optimizeEntryExit: ArtState.optimizeEntryExit,
                routeReversed: ArtState.routeReversed
            };
        },

        pushState() {
            if (this.isApplying) return;
            const snapshot = this.captureSnapshot();
            this.undoStack.push(snapshot);
            if (this.undoStack.length > this.maxSize) {
                this.undoStack.shift();
            }
            this.redoStack = [];
            this.updateButtons();
        },

        undo() {
            if (this.undoStack.length === 0 || this.isApplying) return;
            this.isApplying = true;
            try {
                const current = this.captureSnapshot();
                this.redoStack.push(current);

                const prev = this.undoStack.pop();
                this.restoreSnapshot(prev);
            } finally {
                this.isApplying = false;
                this.updateButtons();
            }
        },

        redo() {
            if (this.redoStack.length === 0 || this.isApplying) return;
            this.isApplying = true;
            try {
                const current = this.captureSnapshot();
                this.undoStack.push(current);

                const next = this.redoStack.pop();
                this.restoreSnapshot(next);
            } finally {
                this.isApplying = false;
                this.updateButtons();
            }
        },

        restoreSnapshot(s) {
            ArtState.basePoints = s.basePoints ? s.basePoints.map(p => ({ x: p.x, y: p.y })) : [];
            ArtState.sizeNM = s.sizeNM ?? 12;
            ArtState.heightNM = s.heightNM ?? 12;
            ArtState.lockAspect = s.lockAspect ?? true;
            ArtState.aspectRatio = s.aspectRatio ?? 1.0;
            ArtState.rotationDeg = s.rotationDeg ?? 0;
            ArtState.flipH = !!s.flipH;
            ArtState.flipV = !!s.flipV;
            ArtState.center = s.center ? { ...s.center } : { ...ArtState.homeAirport };
            ArtState.simplificationTolerance = s.simplificationTolerance ?? 0.015;
            ArtState.optimizeEntryExit = s.optimizeEntryExit ?? true;
            ArtState.routeReversed = s.routeReversed ?? false;

            syncAllControls();
            applyTransformations();

            if (ArtState.projectedPoints && ArtState.projectedPoints.length > 0) {
                const bounds = L.latLngBounds(ArtState.projectedPoints.map(p => [p.lat, p.lon]));
                ArtState.map.fitBounds(bounds, { padding: [40, 40] });
            }
        },

        updateButtons() {
            const canUndo = this.undoStack.length > 0;
            const canRedo = this.redoStack.length > 0;

            ['undoBtn', 'mapUndoBtn'].forEach(id => {
                const btn = document.getElementById(id);
                if (btn) {
                    btn.disabled = !canUndo;
                    btn.classList.toggle('disabled', !canUndo);
                }
            });

            ['redoBtn', 'mapRedoBtn'].forEach(id => {
                const btn = document.getElementById(id);
                if (btn) {
                    btn.disabled = !canRedo;
                    btn.classList.toggle('disabled', !canRedo);
                }
            });
        }
    };

    function syncDimensionInputs() {
        const sizeInput = document.getElementById('sizeInput');
        const sizeSlider = document.getElementById('sizeSlider');
        const heightInput = document.getElementById('heightInput');
        const heightSlider = document.getElementById('heightSlider');
        const lockBtn = document.getElementById('aspectLockBtn');
        const lockIcon = document.getElementById('aspectLockIcon');
        const lockLabel = document.getElementById('aspectLockLabel');

        if (sizeInput) sizeInput.value = ArtState.sizeNM;
        if (sizeSlider) sizeSlider.value = ArtState.sizeNM;
        if (heightInput) heightInput.value = ArtState.heightNM;
        if (heightSlider) heightSlider.value = ArtState.heightNM;

        if (lockBtn && lockIcon && lockLabel) {
            if (ArtState.lockAspect) {
                lockBtn.classList.remove('btn-outline-warning');
                lockBtn.classList.add('btn-outline-secondary');
                lockIcon.className = 'bi bi-link-45deg text-primary me-1';
                lockLabel.innerText = 'Locked';
            } else {
                lockBtn.classList.remove('btn-outline-secondary');
                lockBtn.classList.add('btn-outline-warning');
                lockIcon.className = 'bi bi-slash-circle text-warning me-1';
                lockLabel.innerText = 'Unlocked';
            }
        }
    }

    function updateReverseButtons() {
        ['reverseRouteBtn', 'mapReverseBtn'].forEach(id => {
            const btn = document.getElementById(id);
            if (btn) {
                btn.classList.toggle('active', ArtState.routeReversed);
                if (id === 'reverseRouteBtn') {
                    btn.classList.toggle('btn-primary', ArtState.routeReversed);
                    btn.classList.toggle('btn-outline-secondary', !ArtState.routeReversed);
                } else if (id === 'mapReverseBtn') {
                    btn.classList.toggle('btn-primary', ArtState.routeReversed);
                    btn.classList.toggle('text-white', ArtState.routeReversed);
                    btn.classList.toggle('btn-light', !ArtState.routeReversed);
                }
            }
        });
    }

    function syncAllControls() {
        syncDimensionInputs();
        updateCenterInputs();

        const optCheck = document.getElementById('optimizeEntryExitCheck');
        if (optCheck) optCheck.checked = ArtState.optimizeEntryExit;

        updateReverseButtons();

        const rotSlider = document.getElementById('rotSlider');
        const rotBadge = document.getElementById('rotBadge');
        if (rotSlider) rotSlider.value = ArtState.rotationDeg;
        if (rotBadge) rotBadge.innerText = ArtState.rotationDeg + '°';

        const smoothSlider = document.getElementById('smoothSlider');
        if (smoothSlider) smoothSlider.value = ArtState.simplificationTolerance;

        const flipHBtn = document.getElementById('flipHBtn');
        const flipVBtn = document.getElementById('flipVBtn');
        if (flipHBtn) flipHBtn.classList.toggle('active', ArtState.flipH);
        if (flipVBtn) flipVBtn.classList.toggle('active', ArtState.flipV);
    }

    // --- Ramer-Douglas-Peucker (RDP) Simplification ---
    function perpendicularDistance(point, lineStart, lineEnd) {
        const dx = lineEnd.x - lineStart.x;
        const dy = lineEnd.y - lineStart.y;
        const mag = Math.hypot(dx, dy);
        if (mag === 0) return Math.hypot(point.x - lineStart.x, point.y - lineStart.y);
        const u = ((point.x - lineStart.x) * dx + (point.y - lineStart.y) * dy) / (mag * mag);
        const clampU = Math.max(0, Math.min(1, u));
        const projX = lineStart.x + clampU * dx;
        const projY = lineStart.y + clampU * dy;
        return Math.hypot(point.x - projX, point.y - projY);
    }

    function ramerDouglasPeucker(points, epsilon) {
        if (!points || points.length <= 2) return points ? [...points] : [];
        let maxDist = 0;
        let index = 0;
        for (let i = 1; i < points.length - 1; i++) {
            const d = perpendicularDistance(points[i], points[0], points[points.length - 1]);
            if (d > maxDist) {
                maxDist = d;
                index = i;
            }
        }
        if (maxDist > epsilon) {
            const left = ramerDouglasPeucker(points.slice(0, index + 1), epsilon);
            const right = ramerDouglasPeucker(points.slice(index), epsilon);
            return left.slice(0, left.length - 1).concat(right);
        } else {
            return [points[0], points[points.length - 1]];
        }
    }

    // --- Great Circle Math ---
    function toRad(deg) { return deg * Math.PI / 180; }
    function toDeg(rad) { return rad * 180 / Math.PI; }

    function calculateDistanceNM(lat1, lon1, lat2, lon2) {
        const R = 3440.065; // Earth radius in Nautical Miles
        const dLat = toRad(lat2 - lat1);
        const dLon = toRad(lon2 - lon1);
        const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
                  Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
                  Math.sin(dLon / 2) * Math.sin(dLon / 2);
        const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        return R * c;
    }

    function calculateBearingDeg(lat1, lon1, lat2, lon2) {
        const y = Math.sin(toRad(lon2 - lon1)) * Math.cos(toRad(lat2));
        const x = Math.cos(toRad(lat1)) * Math.sin(toRad(lat2)) -
                  Math.sin(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.cos(toRad(lon2 - lon1));
        const brng = toDeg(Math.atan2(y, x));
        return (brng + 360) % 360;
    }

    // --- Map Initialization ---
    function initMap() {
        const cartoKey = 'cb1_272f_1_6642cd2a2abfdf826cc7fc9c';

        ArtState.layers.osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '&copy; OpenStreetMap'
        });

        ArtState.layers.cartoDark = L.tileLayer(`https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png?key=${cartoKey}`, {
            maxZoom: 19,
            attribution: '&copy; CARTO'
        });

        ArtState.layers.cartoVoyager = L.tileLayer(`https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png?key=${cartoKey}`, {
            maxZoom: 19,
            attribution: '&copy; CARTO'
        });

        ArtState.layers.satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
            maxZoom: 18,
            attribution: '&copy; Esri World Imagery'
        });

        const isDarkMode = document.body.classList.contains('dark-mode');
        const defaultBase = isDarkMode ? ArtState.layers.cartoDark : ArtState.layers.cartoVoyager;

        ArtState.map = L.map('artMap', {
            center: [ArtState.center.lat, ArtState.center.lon],
            zoom: 11,
            layers: [defaultBase]
        });

        const baseMaps = {
            "Dark Theme": ArtState.layers.cartoDark,
            "Light / Voyager": ArtState.layers.cartoVoyager,
            "OpenStreetMap": ArtState.layers.osm,
            "Satellite": ArtState.layers.satellite
        };
        L.control.layers(baseMaps, null, { position: 'topright' }).addTo(ArtState.map);

        L.control.scale({ imperial: true, metric: false, position: 'bottomleft' }).addTo(ArtState.map);

        // Center Pin
        createCenterMarker();

        // Setup Freehand and Click listeners
        setupMapDrawingListeners();

        // Default artwork: Airplane
        loadPreset('airplane');
    }

    function createCenterMarker() {
        if (ArtState.centerMarker) {
            ArtState.map.removeLayer(ArtState.centerMarker);
        }

        const centerIcon = L.divIcon({
            className: 'center-pin-icon',
            html: '<div class="center-pin-inner" style="background:#ffc107; color:#000; border:2px solid #000; border-radius:50%; width:26px; height:26px; display:flex; align-items:center; justify-content:center; font-size:13px; font-weight:bold; cursor:grab; box-shadow:0 2px 6px rgba(0,0,0,0.35);">⚓</div>',
            iconSize: [26, 26],
            iconAnchor: [13, 13]
        });

        ArtState.centerMarker = L.marker([ArtState.center.lat, ArtState.center.lon], {
            icon: centerIcon,
            draggable: true,
            zIndexOffset: 2500
        }).addTo(ArtState.map);

        ArtState.centerMarker.on('dragstart', function () {
            HistoryManager.pushState();
        });

        ArtState.centerMarker.on('drag', function (e) {
            const pos = e.target.getLatLng();
            ArtState.center.lat = pos.lat;
            ArtState.center.lon = pos.lng;
            updateCenterInputs();
            applyTransformations();
        });

        ArtState.centerMarker.bindTooltip("Artwork Anchor / Center (Drag to move)", { direction: 'top', offset: [0, -12] });
    }

    function updateCenterInputs() {
        const latInput = document.getElementById('centerLatInput');
        const lonInput = document.getElementById('centerLonInput');
        if (latInput) latInput.value = ArtState.center.lat.toFixed(4);
        if (lonInput) lonInput.value = ArtState.center.lon.toFixed(4);
    }

    function updateHomeAirportUI() {
        const home = ArtState.homeAirport || DEFAULT_HOME_AIRPORT;
        const label = document.getElementById('connectHomeAirportLabel');
        const badge = document.getElementById('homeAirportHeaderBadge');
        const modalBadge = document.getElementById('configHomeCurrentBadge');
        const modalName = document.getElementById('configHomeCurrentName');
        const modalCoords = document.getElementById('configHomeCurrentCoords');

        if (label) label.innerText = `Connect to Home Airport ( ${home.icao} )`;
        if (badge) badge.innerText = `Home: ${home.icao}`;
        if (modalBadge) modalBadge.innerText = home.icao;
        if (modalName) modalName.innerText = home.name;
        if (modalCoords) modalCoords.innerText = `${home.lat.toFixed(4)}°, ${home.lon.toFixed(4)}°`;

        const depInput = document.getElementById('depAirportInput');
        const depName = document.getElementById('depAirportName');
        if (depInput && !depInput.value) depInput.value = ArtState.depAirport.icao;
        if (depName && ArtState.depAirport) depName.innerText = ArtState.depAirport.name;

        const arrInput = document.getElementById('arrAirportInput');
        const arrName = document.getElementById('arrAirportName');
        if (arrInput && !arrInput.value) arrInput.value = ArtState.arrAirport.icao;
        if (arrName && ArtState.arrAirport) arrName.innerText = ArtState.arrAirport.name;
    }

    // --- Spatial Transformation Engine ---
    // Takes normalized 2D points in [-0.5, 0.5] and projects to Lat/Lon
    function applyTransformations() {
        if (!ArtState.basePoints || ArtState.basePoints.length === 0) {
            clearRenderedRoute();
            return;
        }

        const theta = toRad(ArtState.rotationDeg);
        const cosT = Math.cos(theta);
        const sinT = Math.sin(theta);
        const sizeNM = ArtState.sizeNM;
        const aspect = ArtState.aspectRatio || 1.0;
        const centerLat = ArtState.center.lat;
        const centerLon = ArtState.center.lon;
        const cosLat = Math.cos(toRad(centerLat)) || 1.0;

        // 1 NM = 1/60 degrees latitude
        const nmToLatDeg = 1.0 / 60.0;
        // 1 NM longitude depends on latitude
        const nmToLonDeg = (1.0 / 60.0) / Math.max(cosLat, 0.05);

        const widthNM = ArtState.sizeNM || 12;
        const heightNM = ArtState.heightNM || (widthNM * (ArtState.aspectRatio || 1.0));

        // Project and apply rotation, flip, and scaling
        const projected = ArtState.basePoints.map(pt => {
            let nx = pt.x;
            let ny = pt.y;

            if (ArtState.flipH) nx = -nx;
            if (ArtState.flipV) ny = -ny;

            // Scale along shape's natural axes
            const sx = nx * widthNM;
            const sy = ny * heightNM;

            // Rotation
            const rx = sx * cosT - sy * sinT;
            const ry = sx * sinT + sy * cosT;

            return {
                lat: centerLat + (ry * nmToLatDeg),
                lon: centerLon + (rx * nmToLonDeg)
            };
        });

        ArtState.rawProjectedPoints = projected;

        // Simplify using Ramer-Douglas-Peucker
        simplifyProjectedRoute();
    }

    // --- Entry / Exit Waypoint Optimization ---
    // Optimizes entry/exit points for connected airports to prevent transit legs
    // from needlessly crossing/cutting through closed artwork loops or open shapes.
    function optimizeRouteWaypoints(points) {
        if (!points || points.length < 3) return points;

        const p0 = points[0];
        const pEnd = points[points.length - 1];
        const gapNM = calculateDistanceNM(p0.lat, p0.lon, pEnd.lat, pEnd.lon);
        const maxThresholdNM = Math.max(0.15, (ArtState.sizeNM || 12) * 0.05);
        const isClosed = gapNM <= maxThresholdNM || (Math.abs(p0.lat - pEnd.lat) < 0.0001 && Math.abs(p0.lon - pEnd.lon) < 0.0001);

        const shouldOptimize = ArtState.includeAirport && ArtState.optimizeEntryExit && ArtState.depAirport;

        if (isClosed) {
            // Unique vertices of the closed loop
            const uniquePts = points.slice(0, points.length - 1);
            const M = uniquePts.length;
            if (M < 3) return points;

            let bestIdx = 0;
            if (shouldOptimize) {
                const dep = ArtState.depAirport;
                const arr = ArtState.arrAirport || dep;
                let minTransit = Infinity;

                for (let i = 0; i < M; i++) {
                    const pt = uniquePts[i];
                    const dDep = calculateDistanceNM(dep.lat, dep.lon, pt.lat, pt.lon);
                    const dArr = calculateDistanceNM(pt.lat, pt.lon, arr.lat, arr.lon);
                    const totalTransit = dDep + dArr;
                    if (totalTransit < minTransit) {
                        minTransit = totalTransit;
                        bestIdx = i;
                    }
                }
            }

            // Build cycled loop starting at bestIdx
            const result = [];
            if (ArtState.routeReversed) {
                // Traverse loop in reverse direction
                for (let j = 0; j < M; j++) {
                    const idx = (bestIdx - j + M) % M;
                    result.push({ lat: uniquePts[idx].lat, lon: uniquePts[idx].lon });
                }
            } else {
                // Traverse loop in forward direction
                for (let j = 0; j < M; j++) {
                    const idx = (bestIdx + j) % M;
                    result.push({ lat: uniquePts[idx].lat, lon: uniquePts[idx].lon });
                }
            }
            // Close loop cleanly
            result.push({ lat: result[0].lat, lon: result[0].lon });
            return result;
        } else {
            // Open path (unclosed)
            let result = points.map(p => ({ lat: p.lat, lon: p.lon }));

            if (shouldOptimize) {
                const dep = ArtState.depAirport;
                const arr = ArtState.arrAirport || dep;
                const pFirst = result[0];
                const pLast = result[result.length - 1];

                const costFwd = calculateDistanceNM(dep.lat, dep.lon, pFirst.lat, pFirst.lon) +
                                calculateDistanceNM(pLast.lat, pLast.lon, arr.lat, arr.lon);
                const costRev = calculateDistanceNM(dep.lat, dep.lon, pLast.lat, pLast.lon) +
                                calculateDistanceNM(pFirst.lat, pFirst.lon, arr.lat, arr.lon);

                if (costRev < costFwd) {
                    result.reverse();
                }
            }

            if (ArtState.routeReversed) {
                result.reverse();
            }

            return result;
        }
    }

    function simplifyProjectedRoute() {
        if ((!ArtState.rawProjectedPoints || ArtState.rawProjectedPoints.length === 0) &&
            (!ArtState.projectedPoints || ArtState.projectedPoints.length === 0)) {
            clearRenderedRoute();
            return;
        }

        let points = [];
        if (ArtState.rawProjectedPoints && ArtState.rawProjectedPoints.length > 0) {
            // Convert lat/lon to local x/y for accurate Euclidean RDP simplification
            const originLat = ArtState.center.lat;
            const originLon = ArtState.center.lon;
            const cosLat = Math.cos(toRad(originLat)) || 1.0;

            const xyPoints = ArtState.rawProjectedPoints.map(p => ({
                x: (p.lon - originLon) * cosLat * 60.0, // in NM
                y: (p.lat - originLat) * 60.0,          // in NM
                raw: p
            }));

            const toleranceNM = ArtState.simplificationTolerance;
            const simplifiedXY = ramerDouglasPeucker(xyPoints, toleranceNM);
            points = simplifiedXY.map(p => ({ lat: p.raw.lat, lon: p.raw.lon }));
        } else {
            points = ArtState.projectedPoints.map(p => ({ lat: p.lat, lon: p.lon }));
        }

        // Optimize entry/exit waypoints for connected airport
        points = optimizeRouteWaypoints(points);
        ArtState.projectedPoints = points;

        buildFullFlightPlan();
        renderRouteOnMap();
        updateStatsHUD();
        renderWaypointTable();
    }

    // --- Build Full Flight Plan with Airports ---
    function buildFullFlightPlan() {
        const full = [];

        // Departure airport if enabled
        if (ArtState.includeAirport && ArtState.depAirport) {
            full.push({
                id: ArtState.depAirport.icao,
                name: ArtState.depAirport.name,
                type: 'AIRPORT',
                lat: ArtState.depAirport.lat,
                lon: ArtState.depAirport.lon,
                isAirport: true
            });
        }

        // Artwork user waypoints
        ArtState.projectedPoints.forEach((pt, idx) => {
            const wpId = 'WP' + String(idx + 1).padStart(2, '0');
            full.push({
                id: wpId,
                name: `Art Pt ${idx + 1}`,
                type: 'USER WAYPOINT',
                lat: pt.lat,
                lon: pt.lon,
                isAirport: false,
                artIndex: idx
            });
        });

        // Arrival airport if enabled
        if (ArtState.includeAirport && ArtState.arrAirport) {
            full.push({
                id: ArtState.arrAirport.icao,
                name: ArtState.arrAirport.name,
                type: 'AIRPORT',
                lat: ArtState.arrAirport.lat,
                lon: ArtState.arrAirport.lon,
                isAirport: true
            });
        }

        ArtState.waypoints = full;
    }

    // --- Map Rendering ---
    function clearRenderedRoute() {
        if (ArtState.routePolyline) ArtState.map.removeLayer(ArtState.routePolyline);
        if (ArtState.transitPolylineDep) ArtState.map.removeLayer(ArtState.transitPolylineDep);
        if (ArtState.transitPolylineArr) ArtState.map.removeLayer(ArtState.transitPolylineArr);
        ArtState.mapMarkers.forEach(m => ArtState.map.removeLayer(m));
        ArtState.mapMarkers = [];
    }

    function renderRouteOnMap() {
        clearRenderedRoute();

        if (!ArtState.projectedPoints || ArtState.projectedPoints.length < 2) return;

        const artLatLngs = ArtState.projectedPoints.map(p => [p.lat, p.lon]);

        // Main Sky Art Polyline
        ArtState.routePolyline = L.polyline(artLatLngs, {
            color: '#0d6efd',
            weight: 4,
            opacity: 0.9,
            lineJoin: 'round',
            lineCap: 'round',
            dashArray: null
        }).addTo(ArtState.map);

        // Departure Transit Line (dotted green)
        if (ArtState.includeAirport && ArtState.depAirport && ArtState.projectedPoints.length > 0) {
            const firstPt = ArtState.projectedPoints[0];
            ArtState.transitPolylineDep = L.polyline([
                [ArtState.depAirport.lat, ArtState.depAirport.lon],
                [firstPt.lat, firstPt.lon]
            ], {
                color: '#198754',
                weight: 3,
                dashArray: '6, 6',
                opacity: 0.8
            }).addTo(ArtState.map);
        }

        // Arrival Transit Line (dotted red)
        if (ArtState.includeAirport && ArtState.arrAirport && ArtState.projectedPoints.length > 0) {
            const lastPt = ArtState.projectedPoints[ArtState.projectedPoints.length - 1];
            ArtState.transitPolylineArr = L.polyline([
                [lastPt.lat, lastPt.lon],
                [ArtState.arrAirport.lat, ArtState.arrAirport.lon]
            ], {
                color: '#dc3545',
                weight: 3,
                dashArray: '6, 6',
                opacity: 0.8
            }).addTo(ArtState.map);
        }

        // Waypoint Markers
        ArtState.projectedPoints.forEach((pt, idx) => {
            const isFirst = idx === 0;
            const isLast = idx === ArtState.projectedPoints.length - 1;
            const markerClass = isFirst ? 'first-pt' : (isLast ? 'last-pt' : '');

            const icon = L.divIcon({
                className: 'custom-wp-icon',
                html: `<div class="waypoint-badge-marker ${markerClass}">${idx + 1}</div>`,
                iconSize: [22, 22],
                iconAnchor: [11, 11]
            });

            const marker = L.marker([pt.lat, pt.lon], {
                icon: icon,
                draggable: true
            }).addTo(ArtState.map);

            marker.bindTooltip(`WP${idx + 1}: ${pt.lat.toFixed(4)}, ${pt.lon.toFixed(4)}`, { direction: 'top' });

            // Push history before dragging
            marker.on('dragstart', function () {
                HistoryManager.pushState();
            });

            // Allow dragging individual waypoint to fine tune flight plan
            marker.on('drag', function (e) {
                const pos = e.target.getLatLng();
                ArtState.projectedPoints[idx].lat = pos.lat;
                ArtState.projectedPoints[idx].lon = pos.lng;

                // If closed loop and dragging start/end point, update corresponding closing vertex
                const totalPts = ArtState.projectedPoints.length;
                if (totalPts >= 3) {
                    const firstPt = ArtState.projectedPoints[0];
                    const lastPt = ArtState.projectedPoints[totalPts - 1];
                    if (isFirst) {
                        lastPt.lat = pos.lat;
                        lastPt.lon = pos.lng;
                    } else if (isLast) {
                        firstPt.lat = pos.lat;
                        firstPt.lon = pos.lng;
                    }
                }

                buildFullFlightPlan();
                updateStatsHUD();
                renderWaypointTable();

                // Update polylines
                const updatedLatLngs = ArtState.projectedPoints.map(p => [p.lat, p.lon]);
                ArtState.routePolyline.setLatLngs(updatedLatLngs);
                if (ArtState.transitPolylineDep) {
                    ArtState.transitPolylineDep.setLatLngs([
                        [ArtState.depAirport.lat, ArtState.depAirport.lon],
                        [ArtState.projectedPoints[0].lat, ArtState.projectedPoints[0].lon]
                    ]);
                }
                if (ArtState.transitPolylineArr) {
                    ArtState.transitPolylineArr.setLatLngs([
                        [ArtState.projectedPoints[totalPts - 1].lat, ArtState.projectedPoints[totalPts - 1].lon],
                        [ArtState.arrAirport.lat, ArtState.arrAirport.lon]
                    ]);
                }
            });

            ArtState.mapMarkers.push(marker);
        });

        // Airport Markers
        if (ArtState.includeAirport) {
            const isDepColocated = ArtState.depAirport &&
                Math.abs(ArtState.center.lat - ArtState.depAirport.lat) < 0.0008 &&
                Math.abs(ArtState.center.lon - ArtState.depAirport.lon) < 0.0008;

            if (ArtState.depAirport) {
                // If colocated with center anchor, shift badge below anchor [30, -15] so anchor is completely accessible
                const anchorY = isDepColocated ? -15 : 10;
                const depIcon = L.divIcon({
                    className: 'dep-apt-icon' + (isDepColocated ? ' colocated-with-center' : ''),
                    html: '<div class="apt-badge-inner" style="background:#198754; color:#fff; border-radius:4px; padding:2px 6px; font-weight:bold; font-size:11px; box-shadow:0 1px 4px rgba(0,0,0,0.3); border:1px solid #fff; cursor:default;">🛫 ' + ArtState.depAirport.icao + '</div>',
                    iconSize: [60, 20],
                    iconAnchor: [30, anchorY]
                });
                const depMarker = L.marker([ArtState.depAirport.lat, ArtState.depAirport.lon], {
                    icon: depIcon,
                    zIndexOffset: isDepColocated ? 1000 : 1500
                }).addTo(ArtState.map);

                const tooltipDir = isDepColocated ? 'bottom' : 'top';
                const tooltipOffset = isDepColocated ? [0, 12] : [0, -10];
                depMarker.bindTooltip(ArtState.depAirport.name + ' (Departure)', { direction: tooltipDir, offset: tooltipOffset });

                if (isDepColocated) {
                    depMarker.on('mouseover', function () {
                        const pinEl = document.querySelector('.center-pin-icon');
                        if (pinEl) pinEl.classList.add('colocated-highlight');
                    });
                    depMarker.on('mouseout', function () {
                        const pinEl = document.querySelector('.center-pin-icon');
                        if (pinEl) pinEl.classList.remove('colocated-highlight');
                    });
                }

                ArtState.mapMarkers.push(depMarker);
            }

            if (ArtState.arrAirport && (ArtState.arrAirport.icao !== ArtState.depAirport?.icao || ArtState.arrAirport.lat !== ArtState.depAirport?.lat)) {
                const isArrColocated = Math.abs(ArtState.center.lat - ArtState.arrAirport.lat) < 0.0008 &&
                    Math.abs(ArtState.center.lon - ArtState.arrAirport.lon) < 0.0008;
                const arrAnchorY = isArrColocated ? -15 : 10;
                const arrIcon = L.divIcon({
                    className: 'arr-apt-icon' + (isArrColocated ? ' colocated-with-center' : ''),
                    html: '<div class="apt-badge-inner" style="background:#dc3545; color:#fff; border-radius:4px; padding:2px 6px; font-weight:bold; font-size:11px; box-shadow:0 1px 4px rgba(0,0,0,0.3); border:1px solid #fff; cursor:default;">🛬 ' + ArtState.arrAirport.icao + '</div>',
                    iconSize: [60, 20],
                    iconAnchor: [30, arrAnchorY]
                });
                const arrMarker = L.marker([ArtState.arrAirport.lat, ArtState.arrAirport.lon], {
                    icon: arrIcon,
                    zIndexOffset: isArrColocated ? 1000 : 1500
                }).addTo(ArtState.map);

                const arrTooltipDir = isArrColocated ? 'bottom' : 'top';
                const arrTooltipOffset = isArrColocated ? [0, 12] : [0, -10];
                arrMarker.bindTooltip(ArtState.arrAirport.name + ' (Arrival)', { direction: arrTooltipDir, offset: arrTooltipOffset });

                if (isArrColocated) {
                    arrMarker.on('mouseover', function () {
                        const pinEl = document.querySelector('.center-pin-icon');
                        if (pinEl) pinEl.classList.add('colocated-highlight');
                    });
                    arrMarker.on('mouseout', function () {
                        const pinEl = document.querySelector('.center-pin-icon');
                        if (pinEl) pinEl.classList.remove('colocated-highlight');
                    });
                }

                ArtState.mapMarkers.push(arrMarker);
            }
        }
    }

    // --- Statistics & Calculations ---
    function updateStatsHUD() {
        let totalNM = 0;
        let artNM = 0;
        let transitNM = 0;

        // Artwork legs
        for (let i = 0; i < ArtState.projectedPoints.length - 1; i++) {
            const p1 = ArtState.projectedPoints[i];
            const p2 = ArtState.projectedPoints[i + 1];
            artNM += calculateDistanceNM(p1.lat, p1.lon, p2.lat, p2.lon);
        }

        // Transit legs
        if (ArtState.includeAirport && ArtState.projectedPoints.length > 0) {
            if (ArtState.depAirport) {
                const first = ArtState.projectedPoints[0];
                transitNM += calculateDistanceNM(ArtState.depAirport.lat, ArtState.depAirport.lon, first.lat, first.lon);
            }
            if (ArtState.arrAirport) {
                const last = ArtState.projectedPoints[ArtState.projectedPoints.length - 1];
                transitNM += calculateDistanceNM(last.lat, last.lon, ArtState.arrAirport.lat, ArtState.arrAirport.lon);
            }
        }

        totalNM = artNM + transitNM;

        const speed = ArtState.cruiseSpeedKts || 150;
        const gph = ArtState.fuelFlowGPH || 8.5;

        const hours = totalNM / speed;
        const totalMinutes = Math.round(hours * 60);
        const dispHours = Math.floor(totalMinutes / 60);
        const dispMins = totalMinutes % 60;
        const eteStr = dispHours > 0 ? `${dispHours}h ${dispMins}m` : `${dispMins}m`;

        const fuelBurn = hours * gph;

        const elTotalDist = document.getElementById('statTotalDist');
        const elArtDist = document.getElementById('statArtDist');
        const elWaypoints = document.getElementById('statWaypoints');
        const elETE = document.getElementById('statETE');
        const elFuel = document.getElementById('statFuel');

        if (elTotalDist) elTotalDist.innerText = totalNM.toFixed(1) + ' NM';
        if (elArtDist) elArtDist.innerText = artNM.toFixed(1) + ' NM';
        if (elWaypoints) {
            const count = ArtState.waypoints.length;
            elWaypoints.innerText = count;
            if (count > 99) {
                elWaypoints.innerHTML = `${count} <span class="badge bg-warning text-dark ms-1" title="Garmin 99 waypoint limit exceeded" style="font-size:0.6rem;">>99</span>`;
            }
        }
        if (elETE) elETE.innerText = eteStr;
        if (elFuel) elFuel.innerText = fuelBurn.toFixed(1) + ' gal';
    }

    // --- Waypoint Leg Table ---
    function renderWaypointTable() {
        const tbody = document.getElementById('waypointTableBody');
        if (!tbody) return;

        if (!ArtState.waypoints || ArtState.waypoints.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-3">No waypoints loaded</td></tr>';
            return;
        }

        let cumDist = 0;
        let html = '';

        for (let i = 0; i < ArtState.waypoints.length; i++) {
            const wp = ArtState.waypoints[i];
            let legDist = 0;
            let legBearing = 0;

            if (i > 0) {
                const prev = ArtState.waypoints[i - 1];
                legDist = calculateDistanceNM(prev.lat, prev.lon, wp.lat, wp.lon);
                legBearing = calculateBearingDeg(prev.lat, prev.lon, wp.lat, wp.lon);
                cumDist += legDist;
            }

            const badgeColor = wp.isAirport ? 'bg-success' : 'bg-primary';

            html += `<tr>
                <td><span class="badge ${badgeColor}">${wp.id}</span></td>
                <td class="small">${wp.name}</td>
                <td class="text-nowrap font-monospace small">${wp.lat.toFixed(4)}°, ${wp.lon.toFixed(4)}°</td>
                <td>${i === 0 ? '--' : legDist.toFixed(1) + ' NM'}</td>
                <td>${i === 0 ? '--' : Math.round(legBearing) + '°'}</td>
                <td class="fw-bold">${cumDist.toFixed(1)} NM</td>
            </tr>`;
        }

        tbody.innerHTML = html;
    }

    // --- Path Chaining Helper (Nearest Neighbor TSP) ---
    function chainPathsNearestNeighbor(segments) {
        if (!segments || segments.length === 0) return [];
        if (segments.length === 1) return segments[0];

        const unvisited = [...segments];
        const chained = [...unvisited.shift()];

        while (unvisited.length > 0) {
            const lastPt = chained[chained.length - 1];
            let bestIdx = 0;
            let bestDist = Infinity;
            let shouldFlip = false;

            for (let i = 0; i < unvisited.length; i++) {
                const seg = unvisited[i];
                const startPt = seg[0];
                const endPt = seg[seg.length - 1];
                const dStart = Math.hypot(startPt.x - lastPt.x, startPt.y - lastPt.y);
                const dEnd = Math.hypot(endPt.x - lastPt.x, endPt.y - lastPt.y);

                if (dStart < bestDist) {
                    bestDist = dStart;
                    bestIdx = i;
                    shouldFlip = false;
                }
                if (dEnd < bestDist) {
                    bestDist = dEnd;
                    bestIdx = i;
                    shouldFlip = true;
                }
            }

            const [nextSeg] = unvisited.splice(bestIdx, 1);
            if (shouldFlip) nextSeg.reverse();
            chained.push(...nextSeg);
        }
        return chained;
    }

    // --- Silhouette Outline Extraction (Exterior Boundary Flood-Fill) ---
    function extractOutlineFromCanvas(canvas, options = {}) {
        const w = canvas.width;
        const h = canvas.height;
        const ctx = canvas.getContext('2d');
        const imgData = ctx.getImageData(0, 0, w, h);
        const data = imgData.data;

        // Detect if background is transparent vs white/light
        const cornerAlphas = [
            data[3],
            data[(w - 1) * 4 + 3],
            data[((h - 1) * w) * 4 + 3],
            data[((h - 1) * w + (w - 1)) * 4 + 3]
        ];
        const isTransparentBg = cornerAlphas.some(a => a < 30);

        const grid = Array.from({ length: h }, () => new Uint8Array(w));
        let fgCount = 0;

        for (let y = 0; y < h; y++) {
            for (let x = 0; x < w; x++) {
                const idx = (y * w + x) * 4;
                const r = data[idx];
                const g = data[idx + 1];
                const b = data[idx + 2];
                const a = data[idx + 3];

                let isForeground = false;
                if (isTransparentBg) {
                    isForeground = (a > 30);
                } else {
                    const lum = (r * 299 + g * 587 + b * 114) / 1000;
                    isForeground = (a > 30 && lum < 220);
                }

                if (isForeground) {
                    grid[y][x] = 1;
                    fgCount++;
                }
            }
        }

        if (fgCount < 10) {
            throw new Error("No artwork detected in image/SVG.");
        }

        // Morphological dilation (radius 2) to seal sub-pixel CAD joints & panel lines
        const dilated = Array.from({ length: h }, () => new Uint8Array(w));
        for (let y = 0; y < h; y++) {
            for (let x = 0; x < w; x++) {
                if (grid[y][x]) {
                    for (let dy = -2; dy <= 2; dy++) {
                        for (let dx = -2; dx <= 2; dx++) {
                            const ny = y + dy;
                            const nx = x + dx;
                            if (ny >= 0 && ny < h && nx >= 0 && nx < w) {
                                dilated[ny][nx] = 1;
                            }
                        }
                    }
                }
            }
        }

        // Flood fill exterior starting from canvas edges
        const exterior = Array.from({ length: h }, () => new Uint8Array(w));
        const queue = [];
        for (let x = 0; x < w; x++) {
            if (!dilated[0][x]) { exterior[0][x] = 1; queue.push([x, 0]); }
            if (!dilated[h - 1][x]) { exterior[h - 1][x] = 1; queue.push([x, h - 1]); }
        }
        for (let y = 0; y < h; y++) {
            if (!dilated[y][0] && !exterior[y][0]) { exterior[y][0] = 1; queue.push([0, y]); }
            if (!dilated[y][w - 1] && !exterior[y][w - 1]) { exterior[y][w - 1] = 1; queue.push([w - 1, y]); }
        }

        let head = 0;
        while (head < queue.length) {
            const [cx, cy] = queue[head++];
            const neighbors = [
                [cx + 1, cy],
                [cx - 1, cy],
                [cx, cy + 1],
                [cx, cy - 1]
            ];
            for (let i = 0; i < 4; i++) {
                const nx = neighbors[i][0];
                const ny = neighbors[i][1];
                if (nx >= 0 && nx < w && ny >= 0 && ny < h && !dilated[ny][nx] && !exterior[ny][nx]) {
                    exterior[ny][nx] = 1;
                    queue.push([nx, ny]);
                }
            }
        }

        // Solid interior = !exterior
        const solid = Array.from({ length: h }, () => new Uint8Array(w));
        for (let y = 0; y < h; y++) {
            for (let x = 0; x < w; x++) {
                if (!exterior[y][x]) solid[y][x] = 1;
            }
        }

        const CLOCKWISE_8 = [
            { dx: 0, dy: -1 },  // N
            { dx: 1, dy: -1 },  // NE
            { dx: 1, dy: 0 },   // E
            { dx: 1, dy: 1 },   // SE
            { dx: 0, dy: 1 },   // S
            { dx: -1, dy: 1 },  // SW
            { dx: -1, dy: 0 },  // W
            { dx: -1, dy: -1 }  // NW
        ];

        // Find all outer boundary contours of solid regions and pick the dominant one
        const visitedContour = Array.from({ length: h }, () => new Uint8Array(w));
        const allContours = [];

        for (let y = 0; y < h; y++) {
            for (let x = 0; x < w; x++) {
                if (solid[y][x] && !visitedContour[y][x] && (y === 0 || !solid[y - 1][x])) {
                    const singleContour = [];
                    let cx = x;
                    let cy = y;
                    let backtrackDir = 0;
                    singleContour.push({ x: cx, y: cy });
                    visitedContour[cy][cx] = 1;

                    const maxSteps = w * h;
                    let steps = 0;

                    while (steps < maxSteps) {
                        steps++;
                        let nextX = null;
                        let nextY = null;
                        let foundDir = -1;

                        for (let i = 0; i < 8; i++) {
                            const checkIdx = (backtrackDir + i) % 8;
                            const nx = cx + CLOCKWISE_8[checkIdx].dx;
                            const ny = cy + CLOCKWISE_8[checkIdx].dy;
                            if (nx >= 0 && nx < w && ny >= 0 && ny < h && solid[ny][nx]) {
                                nextX = nx;
                                nextY = ny;
                                foundDir = checkIdx;
                                break;
                            }
                        }

                        if (foundDir === -1) break;
                        if (nextX === x && nextY === y && singleContour.length > 2) break;

                        singleContour.push({ x: nextX, y: nextY });
                        visitedContour[nextY][nextX] = 1;
                        cx = nextX;
                        cy = nextY;
                        backtrackDir = (foundDir + 5) % 8;
                    }

                    if (singleContour.length >= 8) {
                        allContours.push(singleContour);
                    }
                }
            }
        }

        if (allContours.length === 0) {
            throw new Error("Could not find outer boundary of shape.");
        }

        // Filter out tiny noise specks (< 10px or < 12% of largest contour)
        const maxLen = Math.max(...allContours.map(c => c.length));
        const minSignificance = Math.max(10, maxLen * 0.12);
        let significantContours = allContours.filter(c => c.length >= minSignificance);

        if (significantContours.length === 0) {
            allContours.sort((a, b) => b.length - a.length);
            significantContours = [allContours[0]];
        }

        if (options && options.singleObjectOnly) {
            // Pick only the single largest object
            significantContours.sort((a, b) => b.length - a.length);
            significantContours = [significantContours[0]];
        } else {
            // Sort contours left-to-right (minX) for natural reading and flying order
            significantContours.sort((a, b) => {
                const minAx = Math.min(...a.map(p => p.x));
                const minBx = Math.min(...b.map(p => p.x));
                return minAx - minBx;
            });
        }

        const mergedPoints = [];
        significantContours.forEach(c => {
            c.push({ x: c[0].x, y: c[0].y });
            const simplified = ramerDouglasPeucker(c, 2.0);
            mergedPoints.push(...simplified);
        });

        return mergedPoints;
    }

    // --- Direct Vector SVG Path Parser (with nearest-neighbor chaining) ---
    function parseSvgDirect(svgEl) {
        const container = document.createElement("div");
        container.style.position = "absolute";
        container.style.visibility = "hidden";
        container.style.width = "500px";
        container.style.height = "500px";
        container.appendChild(svgEl);
        document.body.appendChild(container);

        const pathElements = svgEl.querySelectorAll("path, polyline, line, polygon, circle, ellipse, rect");
        if (pathElements.length === 0) {
            document.body.removeChild(container);
            alert("No vector paths found in SVG.");
            return;
        }

        const segments = [];

        pathElements.forEach(el => {
            const tag = el.tagName.toLowerCase();
            const seg = [];
            if (tag === 'path') {
                const len = el.getTotalLength ? el.getTotalLength() : 0;
                if (len > 0) {
                    const numSteps = Math.max(10, Math.min(250, Math.round(len / 4)));
                    for (let s = 0; s <= numSteps; s++) {
                        const pt = el.getPointAtLength((s / numSteps) * len);
                        seg.push({ x: pt.x, y: pt.y });
                    }
                }
            } else if (tag === 'polyline' || tag === 'polygon') {
                const pts = el.points;
                if (pts) {
                    for (let p = 0; p < pts.numberOfItems; p++) {
                        const pt = pts.getItem(p);
                        seg.push({ x: pt.x, y: pt.y });
                    }
                }
            } else if (tag === 'line') {
                const x1 = el.x1?.baseVal?.value || 0;
                const y1 = el.y1?.baseVal?.value || 0;
                const x2 = el.x2?.baseVal?.value || 0;
                const y2 = el.y2?.baseVal?.value || 0;
                seg.push({ x: x1, y: y1 }, { x: x2, y: y2 });
            } else if (tag === 'rect') {
                const x = el.x?.baseVal?.value || 0;
                const y = el.y?.baseVal?.value || 0;
                const w = el.width?.baseVal?.value || 10;
                const h = el.height?.baseVal?.value || 10;
                seg.push({ x, y }, { x: x + w, y }, { x: x + w, y: y + h }, { x, y: y + h }, { x, y });
            } else if (tag === 'circle' || tag === 'ellipse') {
                const cx = (el.cx?.baseVal?.value) || 0;
                const cy = (el.cy?.baseVal?.value) || 0;
                const rx = (el.r?.baseVal?.value) || (el.rx?.baseVal?.value) || 10;
                const ry = (el.r?.baseVal?.value) || (el.ry?.baseVal?.value) || 10;
                for (let a = 0; a <= Math.PI * 2; a += 0.1) {
                    seg.push({ x: cx + rx * Math.cos(a), y: cy + ry * Math.sin(a) });
                }
            }
            if (seg.length >= 2) segments.push(seg);
        });

        document.body.removeChild(container);

        if (segments.length === 0) {
            alert("SVG did not contain enough valid vector paths.");
            return;
        }

        const chained = chainPathsNearestNeighbor(segments);
        normalizeAndSetBasePoints(chained);
    }

    // --- Vector SVG Parser ---
    function parseSvg(svgText) {
        HistoryManager.pushState();
        const mode = document.querySelector('input[name="importModeRadio"]:checked')?.value || 'outline';

        try {
            const parser = new DOMParser();
            const doc = parser.parseFromString(svgText, "image/svg+xml");
            const svgEl = doc.querySelector("svg");
            if (!svgEl) {
                alert("Could not find an <svg> element in the uploaded file.");
                return;
            }

            if (mode === 'outline') {
                // Outline Only: Render to canvas and extract solid exterior silhouette
                let vbW = 600, vbH = 600;
                const vb = svgEl.getAttribute("viewBox");
                if (vb) {
                    const parts = vb.trim().split(/[\s,]+/).map(Number);
                    if (parts.length === 4 && parts[2] > 0 && parts[3] > 0) {
                        vbW = parts[2];
                        vbH = parts[3];
                    }
                } else {
                    vbW = parseFloat(svgEl.getAttribute("width")) || 600;
                    vbH = parseFloat(svgEl.getAttribute("height")) || 600;
                }

                const aspect = vbH / vbW;
                let targetW = 600, targetH = 600;
                if (aspect >= 1) {
                    targetH = 700;
                    targetW = Math.max(200, Math.round(700 / aspect));
                } else {
                    targetW = 700;
                    targetH = Math.max(200, Math.round(700 * aspect));
                }

                svgEl.setAttribute("width", targetW);
                svgEl.setAttribute("height", targetH);

                const serializer = new XMLSerializer();
                const cleanSvg = serializer.serializeToString(doc);
                const blob = new Blob([cleanSvg], { type: 'image/svg+xml;charset=utf-8' });
                const url = URL.createObjectURL(blob);
                const img = new Image();

                img.onload = function () {
                    URL.revokeObjectURL(url);
                    const canvas = document.createElement('canvas');
                    canvas.width = targetW + 60;
                    canvas.height = targetH + 60;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 30, 30, targetW, targetH);

                    try {
                        const outlinePts = extractOutlineFromCanvas(canvas);
                        if (outlinePts && outlinePts.length >= 4) {
                            normalizeAndSetBasePoints(outlinePts);
                        } else {
                            throw new Error("Extracted outline had too few points");
                        }
                    } catch (e) {
                        console.warn("Canvas silhouette extraction fallback to vector chain:", e);
                        parseSvgDirect(svgEl);
                    }
                };

                img.onerror = function () {
                    URL.revokeObjectURL(url);
                    parseSvgDirect(svgEl);
                };

                img.src = url;
            } else {
                parseSvgDirect(svgEl);
            }
        } catch (err) {
            console.error("SVG parsing error:", err);
            alert("Error parsing SVG file: " + err.message);
        }
    }

    // --- Single-Stroke Stick Font Definitions (for clean, low-waypoint text flight paths) ---
    const STICK_FONT = {
        'A': [[0, 1], [0.5, 0], [1, 1], [0.75, 0.6], [0.25, 0.6]],
        'B': [[0, 1], [0, 0], [0.7, 0], [0.9, 0.25], [0.7, 0.5], [0, 0.5], [0.8, 0.5], [1.0, 0.75], [0.8, 1], [0, 1]],
        'C': [[1, 0.2], [0.7, 0], [0.3, 0], [0, 0.3], [0, 0.7], [0.3, 1], [0.7, 1], [1, 0.8]],
        'D': [[0, 1], [0, 0], [0.6, 0], [1, 0.35], [1, 0.65], [0.6, 1], [0, 1]],
        'E': [[1, 0], [0, 0], [0, 0.5], [0.7, 0.5], [0, 0.5], [0, 1], [1, 1]],
        'F': [[0, 1], [0, 0], [1, 0], [0, 0], [0, 0.5], [0.7, 0.5]],
        'G': [[1, 0.2], [0.7, 0], [0.3, 0], [0, 0.3], [0, 0.7], [0.3, 1], [0.7, 1], [1, 0.8], [1, 0.5], [0.6, 0.5]],
        'H': [[0, 0], [0, 1], [0, 0.5], [1, 0.5], [1, 0], [1, 1]],
        'I': [[0.2, 0], [0.8, 0], [0.5, 0], [0.5, 1], [0.2, 1], [0.8, 1]],
        'J': [[0.8, 0], [0.8, 0.8], [0.6, 1], [0.2, 1], [0, 0.7]],
        'K': [[0, 0], [0, 1], [0, 0.5], [1, 0], [0, 0.5], [1, 1]],
        'L': [[0, 0], [0, 1], [1, 1]],
        'M': [[0, 1], [0, 0], [0.5, 0.6], [1, 0], [1, 1]],
        'N': [[0, 1], [0, 0], [1, 1], [1, 0]],
        'O': [[0.5, 0], [0.85, 0.15], [1, 0.5], [0.85, 0.85], [0.5, 1], [0.15, 0.85], [0, 0.5], [0.15, 0.15], [0.5, 0]],
        'P': [[0, 1], [0, 0], [0.8, 0], [1, 0.25], [0.8, 0.5], [0, 0.5]],
        'Q': [[0.5, 0], [0.85, 0.15], [1, 0.5], [0.85, 0.85], [0.5, 1], [0.15, 0.85], [0, 0.5], [0.15, 0.15], [0.5, 0], [0.7, 0.7], [1, 1]],
        'R': [[0, 1], [0, 0], [0.8, 0], [1, 0.25], [0.8, 0.5], [0, 0.5], [1, 1]],
        'S': [[1, 0.2], [0.8, 0], [0.2, 0], [0, 0.25], [0.3, 0.5], [0.7, 0.5], [1, 0.75], [0.8, 1], [0.2, 1], [0, 0.8]],
        'T': [[0, 0], [1, 0], [0.5, 0], [0.5, 1]],
        'U': [[0, 0], [0, 0.75], [0.25, 1], [0.75, 1], [1, 0.75], [1, 0]],
        'V': [[0, 0], [0.5, 1], [1, 0]],
        'W': [[0, 0], [0.25, 1], [0.5, 0.4], [0.75, 1], [1, 0]],
        'X': [[0, 0], [1, 1], [0.5, 0.5], [0, 1], [1, 0]],
        'Y': [[0, 0], [0.5, 0.5], [1, 0], [0.5, 0.5], [0.5, 1]],
        'Z': [[0, 0], [1, 0], [0, 1], [1, 1]],
        '0': [[0.5, 0], [0.85, 0.15], [1, 0.5], [0.85, 0.85], [0.5, 1], [0.15, 0.85], [0, 0.5], [0.15, 0.15], [0.5, 0]],
        '1': [[0.2, 0.2], [0.5, 0], [0.5, 1], [0.2, 1], [0.8, 1]],
        '2': [[0, 0.25], [0.2, 0], [0.8, 0], [1, 0.25], [0, 1], [1, 1]],
        '3': [[0, 0.2], [0.2, 0], [0.8, 0], [1, 0.25], [0.6, 0.5], [1, 0.75], [0.8, 1], [0.2, 1], [0, 0.8]],
        '4': [[0.8, 1], [0.8, 0], [0, 0.7], [1, 0.7]],
        '5': [[1, 0], [0, 0], [0, 0.45], [0.7, 0.45], [1, 0.65], [0.8, 1], [0.2, 1], [0, 0.8]],
        '6': [[0.8, 0.15], [0.4, 0], [0.1, 0.3], [0, 0.7], [0.3, 1], [0.7, 1], [1, 0.7], [0.7, 0.5], [0, 0.6]],
        '7': [[0, 0], [1, 0], [0.4, 1]],
        '8': [[0.5, 0.5], [0.2, 0.3], [0.3, 0], [0.7, 0], [0.8, 0.3], [0.5, 0.5], [0.8, 0.7], [0.7, 1], [0.3, 1], [0.2, 0.7], [0.5, 0.5]],
        '9': [[1, 0.4], [0.3, 0.5], [0, 0.3], [0.3, 0], [0.7, 0], [1, 0.3], [0.9, 0.7], [0.6, 1], [0.2, 0.85]],
        '-': [[0.2, 0.5], [0.8, 0.5]],
        '.': [[0.4, 0.95], [0.6, 0.95], [0.6, 1], [0.4, 1], [0.4, 0.95]],
        ' ': []
    };

    function generateStickTextArt(text) {
        const chars = text.toUpperCase().split('');
        const pts = [];
        const charWidth = 1.0;
        const charSpacing = 0.35;

        chars.forEach((ch, idx) => {
            const strokeDef = STICK_FONT[ch];
            if (!strokeDef || strokeDef.length === 0) return;
            const offsetX = idx * (charWidth + charSpacing);

            strokeDef.forEach(p => {
                pts.push({
                    x: offsetX + p[0],
                    y: p[1]
                });
            });
        });

        return pts;
    }

    // --- PNG Raster Tracer: Moore-Neighbor Boundary Contour Tracing ---
    // Traces the clean perimeter outlines of artwork with zero interior hatching or zigzags
    function tracePngImage(imgElement) {
        try {
            const canvas = document.createElement('canvas');
            const maxDim = 400; // Constrain for rapid responsive tracing
            let w = imgElement.naturalWidth || imgElement.width || 300;
            let h = imgElement.naturalHeight || imgElement.height || 300;

            if (w > maxDim || h > maxDim) {
                if (w > h) {
                    h = Math.round((h * maxDim) / w);
                    w = maxDim;
                } else {
                    w = Math.round((w * maxDim) / h);
                    h = maxDim;
                }
            }

            canvas.width = w + 40;
            canvas.height = h + 40;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(imgElement, 20, 20, w, h);

            const mode = document.querySelector('input[name="importModeRadio"]:checked')?.value || 'outline';
            if (mode === 'outline') {
                try {
                    const outlinePts = extractOutlineFromCanvas(canvas, { singleObjectOnly: false });
                    if (outlinePts && outlinePts.length >= 4) {
                        normalizeAndSetBasePoints(outlinePts);
                        return;
                    }
                } catch (err) {
                    console.warn("PNG outline extraction fallback to multi-contour:", err);
                }
            }

            const imgData = ctx.getImageData(0, 0, w, h);
            const data = imgData.data;

            // Extract foreground coordinates (alpha > 40 and luminance < 170)
            const grid = Array.from({ length: h }, () => new Uint8Array(w));
            let fgCount = 0;

            for (let y = 0; y < h; y++) {
                for (let x = 0; x < w; x++) {
                    const idx = (y * w + x) * 4;
                    const r = data[idx];
                    const g = data[idx + 1];
                    const b = data[idx + 2];
                    const a = data[idx + 3];

                    const luminance = (r * 299 + g * 587 + b * 114) / 1000;
                    if (a > 40 && luminance < 170) {
                        grid[y][x] = 1;
                        fgCount++;
                    }
                }
            }

            if (fgCount < 10) {
                alert("No dark line artwork detected on transparent background. Please ensure your image has dark lines and transparency.");
                return;
            }

            // 8-neighborhood ordered clockwise starting from North
            const CLOCKWISE_8 = [
                { dx: 0, dy: -1 },  // 0: N
                { dx: 1, dy: -1 },  // 1: NE
                { dx: 1, dy: 0 },   // 2: E
                { dx: 1, dy: 1 },   // 3: SE
                { dx: 0, dy: 1 },   // 4: S
                { dx: -1, dy: 1 },  // 5: SW
                { dx: -1, dy: 0 },  // 6: W
                { dx: -1, dy: -1 }  // 7: NW
            ];

            const visited = Array.from({ length: h }, () => new Uint8Array(w));
            const contours = [];

            function isFg(x, y) {
                return x >= 0 && x < w && y >= 0 && y < h && grid[y][x] === 1;
            }

            for (let y = 0; y < h; y++) {
                for (let x = 0; x < w; x++) {
                    // Find start of an untraced outer boundary: foreground pixel whose top neighbor is background
                    if (grid[y][x] === 1 && !visited[y][x] && (y === 0 || grid[y - 1][x] === 0)) {
                        const contour = [];
                        let cx = x;
                        let cy = y;
                        let backtrackDir = 0; // Came from North

                        contour.push({ x: cx, y: cy });
                        const maxSteps = w * h * 2;
                        let steps = 0;

                        while (steps < maxSteps) {
                            steps++;
                            let nextX = null;
                            let nextY = null;
                            let foundDir = -1;

                            for (let i = 0; i < 8; i++) {
                                const checkIdx = (backtrackDir + i) % 8;
                                const nx = cx + CLOCKWISE_8[checkIdx].dx;
                                const ny = cy + CLOCKWISE_8[checkIdx].dy;

                                if (isFg(nx, ny)) {
                                    nextX = nx;
                                    nextY = ny;
                                    foundDir = checkIdx;
                                    break;
                                }
                            }

                            if (foundDir === -1) break;

                            if (nextX === x && nextY === y && contour.length > 2) {
                                break;
                            }

                            contour.push({ x: nextX, y: nextY });
                            cx = nextX;
                            cy = nextY;
                            backtrackDir = (foundDir + 5) % 8;
                        }

                        if (contour.length >= 4) {
                            // Mark bounding row spans in visited to avoid interior hatching or duplicate scans
                            let minY = h, maxY = 0;
                            contour.forEach(pt => {
                                visited[pt.y][pt.x] = 1;
                                if (pt.y < minY) minY = pt.y;
                                if (pt.y > maxY) maxY = pt.y;
                            });

                            for (let rowY = minY; rowY <= maxY; rowY++) {
                                let xs = [];
                                contour.forEach(pt => {
                                    if (pt.y === rowY) xs.push(pt.x);
                                });
                                if (xs.length >= 2) {
                                    const minX = Math.min(...xs);
                                    const maxX = Math.max(...xs);
                                    for (let colX = minX; colX <= maxX; colX++) {
                                        if (grid[rowY][colX] === 1) visited[rowY][colX] = 1;
                                    }
                                }
                            }

                            // Close loop and simplify using RDP
                            contour.push({ x: contour[0].x, y: contour[0].y });
                            const simplified = ramerDouglasPeucker(contour, 1.2);
                            contours.push(simplified);
                        }
                    }
                }
            }

            if (contours.length === 0) {
                alert("Could not extract clean outlines from image. Please ensure the image has dark lines on transparent background.");
                return;
            }

            // Sort contours left-to-right (by bounding box minX)
            contours.sort((a, b) => {
                const minAx = Math.min(...a.map(p => p.x));
                const minBx = Math.min(...b.map(p => p.x));
                return minAx - minBx;
            });

            // Merge into a continuous flyable path with clean transition legs
            const pathPoints = [];
            contours.forEach(c => {
                pathPoints.push(...c);
            });

            normalizeAndSetBasePoints(pathPoints);
        } catch (err) {
            console.error("PNG tracing error:", err);
            alert("Error processing image: " + err.message);
        }
    }

    // --- Normalize Base Points to [-0.5, 0.5] ---
    function normalizeAndSetBasePoints(points) {
        if (!points || points.length < 2) return;

        let minX = Infinity, maxX = -Infinity;
        let minY = Infinity, maxY = -Infinity;

        points.forEach(p => {
            if (p.x < minX) minX = p.x;
            if (p.x > maxX) maxX = p.x;
            if (p.y < minY) minY = p.y;
            if (p.y > maxY) maxY = p.y;
        });

        const spanX = maxX - minX || 1;
        const spanY = maxY - minY || 1;

        ArtState.aspectRatio = spanY / spanX;

        ArtState.basePoints = points.map(p => ({
            x: (p.x - (minX + maxX) / 2) / spanX,
            y: -((p.y - (minY + maxY) / 2) / spanY)
        }));

        if (ArtState.lockAspect) {
            ArtState.heightNM = Math.max(1, Math.min(100, Math.round(ArtState.sizeNM * (ArtState.aspectRatio || 1.0) * 10) / 10));
        }

        ArtState.routeReversed = false;
        updateReverseButtons();

        syncDimensionInputs();
        applyTransformations();

        if (ArtState.projectedPoints.length > 0) {
            const bounds = L.latLngBounds(ArtState.projectedPoints.map(p => [p.lat, p.lon]));
            ArtState.map.fitBounds(bounds, { padding: [50, 50] });
        }
    }

    // --- Shape Presets ---
    function loadPreset(shapeName) {
        HistoryManager.pushState();
        const pts = [];
        if (shapeName === 'rv7') {
            const rv7Outline = [
                {"x":-0.009,"y":0.5},{"x":0.004,"y":0.5},{"x":-0.006,"y":0.453},{"x":-0.006,"y":0.068},{"x":0.29,"y":0.028},
                {"x":0.324,"y":0.177},{"x":0.392,"y":0.18},{"x":0.426,"y":0.175},{"x":0.447,"y":0.025},{"x":0.407,"y":0.011},
                {"x":0.451,"y":0.008},{"x":0.453,"y":0.014},{"x":0.462,"y":0.014},{"x":0.464,"y":0.008},{"x":0.5,"y":0.003},
                {"x":0.498,"y":-0.005},{"x":0.464,"y":-0.008},{"x":0.462,"y":-0.014},{"x":0.453,"y":-0.014},{"x":0.451,"y":-0.008},
                {"x":0.407,"y":-0.011},{"x":0.447,"y":-0.025},{"x":0.428,"y":-0.174},{"x":0.39,"y":-0.18},{"x":0.324,"y":-0.177},
                {"x":0.29,"y":-0.028},{"x":-0.004,"y":-0.067},{"x":-0.006,"y":-0.455},{"x":0.004,"y":-0.5},{"x":-0.21,"y":-0.478},
                {"x":-0.244,"y":-0.458},{"x":-0.25,"y":-0.439},{"x":-0.25,"y":-0.154},{"x":-0.275,"y":-0.151},{"x":-0.294,"y":-0.138},
                {"x":-0.292,"y":-0.126},{"x":-0.258,"y":-0.112},{"x":-0.295,"y":-0.07},{"x":-0.43,"y":-0.056},{"x":-0.437,"y":-0.028},
                {"x":-0.491,"y":-0.012},{"x":-0.5,"y":0.005},{"x":-0.475,"y":0.019},{"x":-0.441,"y":0.025},{"x":-0.43,"y":0.056},
                {"x":-0.295,"y":0.07},{"x":-0.258,"y":0.112},{"x":-0.292,"y":0.126},{"x":-0.294,"y":0.138},{"x":-0.275,"y":0.151},
                {"x":-0.25,"y":0.154},{"x":-0.25,"y":0.439},{"x":-0.237,"y":0.466},{"x":-0.21,"y":0.478},{"x":-0.011,"y":0.498}
            ];
            rv7Outline.forEach(p => pts.push({ x: p.x, y: p.y }));
        } else if (shapeName === 'heart') {
            for (let t = 0; t <= Math.PI * 2; t += 0.08) {
                const x = 16 * Math.pow(Math.sin(t), 3);
                const y = 13 * Math.cos(t) - 5 * Math.cos(2*t) - 2 * Math.cos(3*t) - Math.cos(4*t);
                pts.push({ x: x / 35, y: y / 35 });
            }
        } else if (shapeName === 'airplane') {
            const raw = [
                {x: 0, y: 1.0}, {x: 0.1, y: 0.8}, {x: 0.1, y: 0.3},
                {x: 1.0, y: -0.2}, {x: 1.0, y: -0.35}, {x: 0.1, y: -0.15},
                {x: 0.1, y: -0.7}, {x: 0.35, y: -0.85}, {x: 0.35, y: -0.95},
                {x: 0, y: -0.88},
                {x: -0.35, y: -0.95}, {x: -0.35, y: -0.85}, {x: -0.1, y: -0.7},
                {x: -0.1, y: -0.15}, {x: -1.0, y: -0.35}, {x: -1.0, y: -0.2},
                {x: -0.1, y: 0.3}, {x: -0.1, y: 0.8}, {x: 0, y: 1.0}
            ];
            raw.forEach(p => pts.push({ x: p.x * 0.5, y: p.y * 0.5 }));
        } else if (shapeName === 'star') {
            const numPoints = 5;
            for (let i = 0; i <= numPoints * 2; i++) {
                const r = i % 2 === 0 ? 0.5 : 0.22;
                const angle = (i * Math.PI / numPoints) - (Math.PI / 2);
                pts.push({ x: r * Math.cos(angle), y: r * Math.sin(angle) });
            }
        } else if (shapeName === 'clover') {
            for (let t = 0; t <= Math.PI * 2; t += 0.05) {
                const r = 0.45 * Math.cos(2 * t);
                pts.push({ x: r * Math.cos(t), y: r * Math.sin(t) });
            }
        } else if (shapeName === 'diamond') {
            pts.push({x: 0, y: 0.5}, {x: 0.5, y: 0}, {x: 0, y: -0.5}, {x: -0.5, y: 0}, {x: 0, y: 0.5});
        }

        if (pts.length > 0) {
            normalizeAndSetBasePoints(pts);
        }
    }

    // --- Saved Custom Drawings / Presets Management ---
    const SAVED_DRAWINGS_STORAGE_KEY = 'sky_art_saved_drawings';
    const LEGACY_SAVED_DRAWINGS_STORAGE_KEY = 'flight_art_saved_drawings';

    function getSavedDrawings() {
        try {
            const raw = localStorage.getItem(SAVED_DRAWINGS_STORAGE_KEY) || localStorage.getItem(LEGACY_SAVED_DRAWINGS_STORAGE_KEY);
            return raw ? JSON.parse(raw) : [];
        } catch (err) {
            console.error("Error loading saved drawings from localStorage:", err);
            return [];
        }
    }

    function saveDrawingToStorage(name) {
        if (!ArtState.basePoints || ArtState.basePoints.length < 2) {
            alert("No sky artwork to save. Please generate text, pick a preset, or draw/import a shape first.");
            return false;
        }

        const drawings = getSavedDrawings();
        const trimmedName = (name || '').trim() || `Drawing ${drawings.length + 1}`;
        const newDrawing = {
            id: 'art_' + Date.now(),
            name: trimmedName,
            createdAt: new Date().toISOString(),
            aspectRatio: ArtState.aspectRatio || 1.0,
            sizeNM: ArtState.sizeNM,
            heightNM: ArtState.heightNM,
            lockAspect: ArtState.lockAspect,
            routeReversed: ArtState.routeReversed,
            basePoints: ArtState.basePoints.map(p => ({ x: p.x, y: p.y })),
            pointCount: ArtState.basePoints.length
        };

        drawings.unshift(newDrawing); // Newest at top
        try {
            localStorage.setItem(SAVED_DRAWINGS_STORAGE_KEY, JSON.stringify(drawings));
        } catch (err) {
            console.error("Error saving drawing to localStorage:", err);
            alert("Could not save drawing to browser storage.");
            return false;
        }

        renderSavedDrawingsDropdown();
        return true;
    }

    function deleteSavedDrawing(id) {
        let drawings = getSavedDrawings();
        drawings = drawings.filter(d => d.id !== id);
        try {
            localStorage.setItem(SAVED_DRAWINGS_STORAGE_KEY, JSON.stringify(drawings));
        } catch (err) {
            console.error("Error updating saved drawings:", err);
        }
        renderSavedDrawingsDropdown();
    }

    function loadSavedDrawing(id) {
        HistoryManager.pushState();
        const drawings = getSavedDrawings();
        const found = drawings.find(d => d.id === id);
        if (!found || !found.basePoints || found.basePoints.length === 0) {
            alert("Saved drawing not found or empty.");
            return;
        }

        ArtState.aspectRatio = found.aspectRatio || 1.0;
        ArtState.basePoints = found.basePoints.map(p => ({ x: p.x, y: p.y }));

        // Restore dimensions with exact aspect ratio
        if (found.sizeNM && found.heightNM) {
            ArtState.sizeNM = found.sizeNM;
            ArtState.heightNM = found.heightNM;
        } else {
            // Compute heightNM from the drawing's aspectRatio so it immediately displays in true proportion
            ArtState.heightNM = Math.max(1, Math.min(100, Math.round(ArtState.sizeNM * (ArtState.aspectRatio || 1.0) * 10) / 10));
        }

        if (found.lockAspect !== undefined) {
            ArtState.lockAspect = !!found.lockAspect;
        }

        if (found.routeReversed !== undefined) {
            ArtState.routeReversed = !!found.routeReversed;
            updateReverseButtons();
        }

        syncDimensionInputs();
        applyTransformations();

        if (ArtState.projectedPoints && ArtState.projectedPoints.length > 0) {
            const bounds = L.latLngBounds(ArtState.projectedPoints.map(p => [p.lat, p.lon]));
            ArtState.map.fitBounds(bounds, { padding: [50, 50] });
        }
    }

    const BUILTIN_PRESETS = [
        { id: 'rv7', name: "Van's RV-7 (N890GF)", icon: '✈️', badge: '55 pts', desc: "Van's RV-7 top silhouette" },
        { id: 'airplane', name: 'Jet Silhouette', icon: '✈️', badge: '19 pts', desc: 'Low-poly cartoon jet' },
        { id: 'heart', name: 'Heart', icon: '❤️', badge: '79 pts', desc: 'Classic parametric heart' },
        { id: 'star', name: '5-Point Star', icon: '⭐', badge: '11 pts', desc: 'Geometric 5-point star' },
        { id: 'clover', name: 'Four-Leaf Clover', icon: '🍀', badge: '126 pts', desc: 'Lucky 4-leaf clover curve' },
        { id: 'diamond', name: 'Diamond', icon: '💎', badge: '5 pts', desc: 'Geometric diamond facet' }
    ];

    function renderSavedDrawingsDropdown() {
        const drawings = getSavedDrawings();
        const container = document.getElementById('tabPresetsUnifiedContainer');
        if (!container) return;

        let html = '';

        // 1. Built-in Presets section (No delete button)
        html += `<li><h6 class="dropdown-header small py-1 text-uppercase fw-bold text-muted" style="font-size: 0.68rem; letter-spacing: 0.5px;"><i class="bi bi-stars text-warning me-1"></i> Built-in Presets</h6></li>`;

        BUILTIN_PRESETS.forEach(p => {
            html += `<li>
                <button class="dropdown-item py-1 px-3 d-flex align-items-center justify-content-between load-preset-item-btn text-start border-0 bg-transparent" type="button" data-shape="${p.id}" title="${p.desc}">
                    <span class="d-flex align-items-center text-truncate">
                        <span class="me-2">${p.icon}</span>
                        <span class="fw-semibold small text-truncate">${p.name}</span>
                    </span>
                    <span class="badge bg-light text-dark border ms-2" style="font-size: 0.65rem;">${p.badge}</span>
                </button>
            </li>`;
        });

        // 2. Divider & My Saved Drawings section (With delete button)
        html += `<li><hr class="dropdown-divider my-1"></li>`;
        html += `<li>
            <div class="d-flex justify-content-between align-items-center px-3 py-1">
                <h6 class="dropdown-header p-0 small text-uppercase fw-bold text-muted" style="font-size: 0.68rem; letter-spacing: 0.5px;">
                    <i class="bi bi-bookmark-fill text-primary me-1"></i> My Saved Drawings
                </h6>
                <span class="badge bg-primary text-white" style="font-size: 0.65rem;">${drawings.length}</span>
            </div>
        </li>`;

        if (drawings.length === 0) {
            html += `<li><span class="dropdown-item-text small text-muted fst-italic px-3 py-1">No custom saved drawings yet</span></li>`;
        } else {
            drawings.forEach(d => {
                const safeName = d.name.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
                html += `<li class="d-flex align-items-center justify-content-between px-2 py-1 saved-drawing-row">
                    <button class="dropdown-item p-1 text-truncate flex-grow-1 load-saved-drawing-btn text-start border-0 bg-transparent" type="button" data-id="${d.id}" title="${safeName}">
                        <i class="bi bi-bookmark-check text-primary me-2"></i>
                        <span class="fw-semibold small">${safeName}</span>
                        <span class="text-muted small ms-1" style="font-size:0.7rem;">(${d.pointCount || d.basePoints?.length || 0} pts)</span>
                    </button>
                    <button class="btn btn-link btn-sm text-danger p-0 px-2 delete-saved-drawing-btn" type="button" data-id="${d.id}" title="Delete saved drawing" style="text-decoration: none;">
                        <i class="bi bi-trash3 small"></i>
                    </button>
                </li>`;
            });
        }

        // 3. Save Action at the bottom
        html += `<li><hr class="dropdown-divider my-1"></li>`;
        html += `<li>
            <button class="dropdown-item small text-primary fw-semibold py-1 px-3 d-flex align-items-center gap-2 trigger-save-drawing-btn text-start border-0 bg-transparent w-100" type="button">
                <i class="bi bi-plus-circle-fill"></i> Save Current Drawing...
            </button>
        </li>`;

        container.innerHTML = html;

        // Bind built-in preset click
        container.querySelectorAll('.load-preset-item-btn').forEach(btn => {
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                const shape = this.getAttribute('data-shape');
                loadPreset(shape);
                const preset = BUILTIN_PRESETS.find(p => p.id === shape);
                const labelEl = document.getElementById('tabPresetsDropdownLabel');
                if (labelEl && preset) {
                    labelEl.innerHTML = `<span class="me-2">${preset.icon}</span><strong>${preset.name}</strong>`;
                }
            });
        });

        // Bind saved drawing click
        container.querySelectorAll('.load-saved-drawing-btn').forEach(btn => {
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                const id = this.getAttribute('data-id');
                loadSavedDrawing(id);
                const d = drawings.find(item => item.id === id);
                const labelEl = document.getElementById('tabPresetsDropdownLabel');
                if (labelEl && d) {
                    labelEl.innerHTML = `<i class="bi bi-bookmark-check text-primary me-2"></i><strong>${d.name}</strong>`;
                }
            });
        });

        // Bind delete button click
        container.querySelectorAll('.delete-saved-drawing-btn').forEach(btn => {
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                const id = this.getAttribute('data-id');
                if (confirm("Delete this saved drawing preset?")) {
                    deleteSavedDrawing(id);
                }
            });
        });

        // Bind save action click
        container.querySelectorAll('.trigger-save-drawing-btn').forEach(btn => {
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                openSaveDrawingModal();
            });
        });
    }

    function openSaveDrawingModal() {
        if (!ArtState.basePoints || ArtState.basePoints.length < 2) {
            alert("No sky artwork to save. Please generate text, pick a preset, or draw/import a shape first.");
            return;
        }

        const modalPointsBadge = document.getElementById('saveDrawingModalPointsBadge');
        const modalInput = document.getElementById('saveDrawingNameInput');
        if (modalPointsBadge) modalPointsBadge.innerText = `${ArtState.basePoints.length} points`;

        const textInput = document.getElementById('textArtInput');
        const drawings = getSavedDrawings();
        if (modalInput) {
            if (textInput && textInput.value.trim().length > 0) {
                modalInput.value = textInput.value.trim().toUpperCase() + ' Art';
            } else {
                modalInput.value = `Custom Drawing ${drawings.length + 1}`;
            }
        }

        const modalEl = document.getElementById('saveDrawingModal');
        if (modalEl && typeof bootstrap !== 'undefined') {
            const modal = new bootstrap.Modal(modalEl);
            modal.show();
            setTimeout(() => {
                modalInput?.focus();
                modalInput?.select();
            }, 350);
        }
    }

    // --- Text-to-Sky Art Generator ---
    function generateTextArt(text) {
        if (!text || text.trim() === '') return;
        text = text.trim().toUpperCase();

        const isStick = document.getElementById('textStyleStick')?.checked;
        if (isStick) {
            const stickPts = generateStickTextArt(text);
            if (stickPts && stickPts.length >= 2) {
                normalizeAndSetBasePoints(stickPts);
                return;
            }
        }

        // Outline Mode: Draws clean outline perimeter of the text with zero solid hatching/zigzags
        const canvas = document.createElement('canvas');
        const fontSize = 100;
        const charWidth = 85;
        const totalW = Math.max(600, text.length * charWidth + 140);
        const totalH = 220;

        canvas.width = totalW;
        canvas.height = totalH;
        const ctx = canvas.getContext('2d');

        ctx.fillStyle = '#000000';
        ctx.font = `bold ${fontSize}px sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';

        // Draw each letter with generous spacing so outlines don't merge into each other
        const letterSpacing = 28;
        const chars = text.split('');
        let totalTextWidth = 0;
        const metrics = chars.map(ch => {
            const w = ctx.measureText(ch).width;
            totalTextWidth += w;
            return { ch, w };
        });
        totalTextWidth += (chars.length - 1) * letterSpacing;

        let curX = (totalW - totalTextWidth) / 2;
        const baselineY = totalH / 2;

        metrics.forEach(m => {
            ctx.fillText(m.ch, curX + m.w / 2, baselineY);
            curX += m.w + letterSpacing;
        });

        try {
            const outlinePts = extractOutlineFromCanvas(canvas, { singleObjectOnly: false });
            if (outlinePts && outlinePts.length >= 4) {
                normalizeAndSetBasePoints(outlinePts);
                return;
            }
        } catch (e) {
            console.warn("Text outline extraction fallback:", e);
        }

        tracePngImage(canvas);
    }

    // --- Freehand and Click Drawing Setup ---
    function setupMapDrawingListeners() {
        ArtState.map.on('mousedown touchstart', function (e) {
            if (!ArtState.drawMode) return;
            ArtState.isDrawing = true;
            ArtState.currentFreehandPoints = [e.latlng];

            if (ArtState.tempFreehandPolyline) {
                ArtState.map.removeLayer(ArtState.tempFreehandPolyline);
            }

            ArtState.tempFreehandPolyline = L.polyline([e.latlng], {
                color: '#0d6efd',
                weight: 4,
                opacity: 0.8
            }).addTo(ArtState.map);

            ArtState.map.dragging.disable();
        });

        ArtState.map.on('mousemove touchmove', function (e) {
            if (!ArtState.drawMode || !ArtState.isDrawing) return;
            ArtState.currentFreehandPoints.push(e.latlng);
            ArtState.tempFreehandPolyline.addLatLng(e.latlng);
        });

        ArtState.map.on('mouseup touchend', function () {
            if (!ArtState.drawMode || !ArtState.isDrawing) return;
            ArtState.isDrawing = false;
            ArtState.map.dragging.enable();

            if (ArtState.tempFreehandPolyline) {
                ArtState.map.removeLayer(ArtState.tempFreehandPolyline);
                ArtState.tempFreehandPolyline = null;
            }

            if (ArtState.currentFreehandPoints.length >= 3) {
                const originLat = ArtState.center.lat;
                const originLon = ArtState.center.lon;
                const cosLat = Math.cos(toRad(originLat)) || 1.0;

                const localPoints = ArtState.currentFreehandPoints.map(ll => ({
                    x: (ll.lng - originLon) * cosLat * 60.0,
                    y: (ll.lat - originLat) * 60.0
                }));

                normalizeAndSetBasePoints(localPoints);
                toggleDrawMode(false);
            }
        });

        ArtState.map.on('click', function (e) {
            if (!ArtState.clickMode) return;
            const newPt = {
                lat: e.latlng.lat,
                lon: e.latlng.lng
            };

            ArtState.projectedPoints.push(newPt);
            buildFullFlightPlan();
            renderRouteOnMap();
            updateStatsHUD();
            renderWaypointTable();
        });
    }

    function toggleDrawMode(active) {
        ArtState.drawMode = active;
        const btn = document.getElementById('drawModeBtn');
        const mapEl = document.getElementById('artMap');

        if (active) {
            ArtState.clickMode = false;
            document.getElementById('clickModeBtn')?.classList.remove('active');
            if (btn) btn.classList.add('active');
            mapEl.classList.add('drawing-active');
        } else {
            if (btn) btn.classList.remove('active');
            mapEl.classList.remove('drawing-active');
            ArtState.map.dragging.enable();
        }
    }

    function toggleClickMode(active) {
        ArtState.clickMode = active;
        const btn = document.getElementById('clickModeBtn');
        if (active) {
            ArtState.drawMode = false;
            document.getElementById('drawModeBtn')?.classList.remove('active');
            document.getElementById('artMap')?.classList.remove('drawing-active');
            if (btn) btn.classList.add('active');
        } else {
            if (btn) btn.classList.remove('active');
        }
    }

    // --- ForeFlight Formats & Exports ---
    function generateForeFlightRouteString() {
        if (!ArtState.waypoints || ArtState.waypoints.length === 0) return '';

        const parts = [];
        ArtState.waypoints.forEach(wp => {
            if (wp.isAirport) {
                parts.push(wp.id);
            } else {
                parts.push(`${wp.lat.toFixed(4)}/${wp.lon.toFixed(4)}`);
            }
        });

        return parts.join(' ');
    }

    function generateForeFlightMobileUrl() {
        const routeStr = generateForeFlightRouteString();
        if (!routeStr) return '';
        return `foreflightmobile://maps/search?q=${encodeURIComponent(routeStr)}`;
    }

    function generateGarminFplXml() {
        const nowIso = new Date().toISOString();
        const routeName = 'N890GF_ART';

        let xml = `<?xml version="1.0" encoding="utf-8"?>\n`;
        xml += `<flight-plan xmlns="http://www8.garmin.com/xmlschemas/FlightPlan/v1">\n`;
        xml += `  <created>${nowIso}</created>\n`;
        xml += `  <waypoint-table>\n`;

        ArtState.waypoints.forEach(wp => {
            xml += `    <waypoint>\n`;
            xml += `      <identifier>${wp.id}</identifier>\n`;
            xml += `      <type>${wp.type}</type>\n`;
            xml += `      <country-code>${wp.isAirport ? 'US' : ''}</country-code>\n`;
            xml += `      <lat>${wp.lat.toFixed(6)}</lat>\n`;
            xml += `      <lon>${wp.lon.toFixed(6)}</lon>\n`;
            xml += `      <comment>${wp.name || wp.id}</comment>\n`;
            xml += `    </waypoint>\n`;
        });

        xml += `  </waypoint-table>\n`;
        xml += `  <route>\n`;
        xml += `    <route-name>${routeName}</route-name>\n`;
        xml += `    <flight-plan-index>1</flight-plan-index>\n`;

        ArtState.waypoints.forEach(wp => {
            xml += `    <route-point>\n`;
            xml += `      <waypoint-identifier>${wp.id}</waypoint-identifier>\n`;
            xml += `      <waypoint-type>${wp.type}</waypoint-type>\n`;
            if (wp.isAirport) {
                xml += `      <country-code>US</country-code>\n`;
            }
            xml += `    </route-point>\n`;
        });

        xml += `  </route>\n`;
        xml += `</flight-plan>\n`;

        return xml;
    }

    function generateGpxXml() {
        const routeName = 'N890GF Sky Art';
        let xml = `<?xml version="1.0" encoding="UTF-8"?>\n`;
        xml += `<gpx version="1.1" creator="N890GF Sky Art Planner" xmlns="http://www.topografix.com/GPX/1/1">\n`;
        xml += `  <metadata><name>${routeName}</name></metadata>\n`;
        xml += `  <rte>\n`;
        xml += `    <name>${routeName}</name>\n`;

        ArtState.waypoints.forEach(wp => {
            xml += `    <rtept lat="${wp.lat.toFixed(6)}" lon="${wp.lon.toFixed(6)}">\n`;
            xml += `      <name>${wp.id}</name>\n`;
            xml += `      <desc>${wp.name || wp.id}</desc>\n`;
            xml += `    </rtept>\n`;
        });

        xml += `  </rte>\n`;
        xml += `</gpx>\n`;
        return xml;
    }

    function generateKmlXml() {
        const routeName = 'N890GF Sky Art';
        let xml = `<?xml version="1.0" encoding="UTF-8"?>\n`;
        xml += `<kml xmlns="http://www.opengis.net/kml/2.2">\n`;
        xml += `  <Document>\n`;
        xml += `    <name>${routeName}</name>\n`;
        xml += `    <Placemark>\n`;
        xml += `      <name>${routeName} Path</name>\n`;
        xml += `      <LineString>\n`;
        xml += `        <tessellate>1</tessellate>\n`;
        xml += `        <coordinates>\n`;

        ArtState.waypoints.forEach(wp => {
            xml += `          ${wp.lon.toFixed(6)},${wp.lat.toFixed(6)},0\n`;
        });

        xml += `        </coordinates>\n`;
        xml += `      </LineString>\n`;
        xml += `    </Placemark>\n`;
        xml += `  </Document>\n`;
        xml += `</kml>\n`;
        return xml;
    }

    function triggerFileDownload(content, filename, mimeType) {
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        setTimeout(() => {
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }, 100);
    }

    function showQrCodeModal() {
        const url = generateForeFlightMobileUrl();
        const routeStr = generateForeFlightRouteString();
        const container = document.getElementById('qrCodeContainer');
        const textDisplay = document.getElementById('qrCodeRouteText');

        if (!container) return;
        container.innerHTML = '';

        if (!routeStr) {
            alert("No flight plan generated yet.");
            return;
        }

        if (textDisplay) textDisplay.innerText = routeStr;

        if (typeof QRCode !== 'undefined') {
            new QRCode(container, {
                text: url,
                width: 256,
                height: 256,
                colorDark: "#000000",
                colorLight: "#ffffff",
                correctLevel: QRCode.CorrectLevel.M
            });
        }

        const modalEl = document.getElementById('foreflightQrModal');
        if (modalEl && typeof bootstrap !== 'undefined') {
            const modal = new bootstrap.Modal(modalEl);
            modal.show();
        }
    }

    // --- Helper: Generic Airport Lookup by Query ---
    function searchAirports(query, callback) {
        const q = (query || '').trim();
        if (q.length < 2) {
            callback([]);
            return;
        }
        fetch(`/api/airports/search?q=${encodeURIComponent(q)}`)
            .then(res => res.json())
            .then(data => callback(data || []))
            .catch(err => {
                console.error("Airport search error:", err);
                callback([]);
            });
    }

    // --- Single Airport Input Autocomplete & Resolver ---
    function setupSingleAirportInput(inputId, dropdownId, nameLabelId, onSelectCallback) {
        const inputEl = document.getElementById(inputId);
        const listEl = document.getElementById(dropdownId);
        const nameEl = document.getElementById(nameLabelId);
        let timeout = null;

        if (!inputEl || !listEl) return;

        inputEl.addEventListener('input', function () {
            clearTimeout(timeout);
            const q = inputEl.value.trim().toUpperCase();
            if (q.length < 2) {
                listEl.classList.add('d-none');
                listEl.innerHTML = '';
                return;
            }

            timeout = setTimeout(() => {
                searchAirports(q, function (data) {
                    if (!data || data.length === 0) {
                        listEl.innerHTML = '<div class="p-2 text-muted small">No airport found</div>';
                        listEl.classList.remove('d-none');
                        return;
                    }

                    let html = '';
                    data.forEach(ap => {
                        html += `<div class="airport-autocomplete-item" data-lat="${ap.lat}" data-lon="${ap.lon}" data-icao="${ap.icao || ap.faa}" data-name="${ap.name}">
                            <strong>${ap.icao || ap.faa}</strong> - ${ap.name} <span class="text-muted small">(${ap.city || ''}, ${ap.state || ''})</span>
                        </div>`;
                    });
                    listEl.innerHTML = html;
                    listEl.classList.remove('d-none');
                });
            }, 180);
        });

        listEl.addEventListener('click', function (e) {
            const item = e.target.closest('.airport-autocomplete-item');
            if (!item) return;

            const lat = parseFloat(item.getAttribute('data-lat'));
            const lon = parseFloat(item.getAttribute('data-lon'));
            const icao = item.getAttribute('data-icao');
            const name = item.getAttribute('data-name');

            if (!isNaN(lat) && !isNaN(lon)) {
                inputEl.value = icao;
                if (nameEl) nameEl.innerText = name;
                listEl.classList.add('d-none');
                onSelectCallback({ icao, name, lat, lon });
            }
        });

        // Resolve on blur / enter if user just typed an ICAO and pressed Tab/Enter
        function resolveDirectInput() {
            const val = inputEl.value.trim().toUpperCase();
            if (!val || val.length < 2) return;

            searchAirports(val, function (data) {
                if (data && data.length > 0) {
                    const exact = data.find(a => (a.icao || '').toUpperCase() === val || (a.faa || '').toUpperCase() === val) || data[0];
                    inputEl.value = exact.icao || exact.faa;
                    if (nameEl) nameEl.innerText = exact.name;
                    onSelectCallback({
                        icao: exact.icao || exact.faa,
                        name: exact.name,
                        lat: exact.lat,
                        lon: exact.lon
                    });
                }
            });
        }

        inputEl.addEventListener('change', resolveDirectInput);
        inputEl.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                resolveDirectInput();
                listEl.classList.add('d-none');
            }
        });

        document.addEventListener('click', function (e) {
            if (!inputEl.contains(e.target) && !listEl.contains(e.target)) {
                listEl.classList.add('d-none');
            }
        });
    }

    // --- Airport Search Autocomplete & Controls ---
    function setupAirportControls() {
        // Top Global Search Bar
        const searchInput = document.getElementById('airportSearchInput');
        const listEl = document.getElementById('airportSearchResults');
        let searchTimeout = null;

        if (searchInput && listEl) {
            searchInput.addEventListener('input', function () {
                clearTimeout(searchTimeout);
                const q = searchInput.value.trim();
                if (q.length < 2) {
                    listEl.classList.add('d-none');
                    listEl.innerHTML = '';
                    return;
                }

                searchTimeout = setTimeout(() => {
                    searchAirports(q, function (data) {
                        if (!data || data.length === 0) {
                            listEl.innerHTML = '<div class="p-2 text-muted small">No airports found</div>';
                            listEl.classList.remove('d-none');
                            return;
                        }

                        let html = '';
                        data.forEach(ap => {
                            html += `<div class="airport-autocomplete-item" data-lat="${ap.lat}" data-lon="${ap.lon}" data-icao="${ap.icao || ap.faa}" data-name="${ap.name}">
                                <strong>${ap.icao || ap.faa}</strong> - ${ap.name} <span class="text-muted small">(${ap.city || ''}, ${ap.state || ''})</span>
                            </div>`;
                        });
                        listEl.innerHTML = html;
                        listEl.classList.remove('d-none');
                    });
                }, 180);
            });

            listEl.addEventListener('click', function (e) {
                const item = e.target.closest('.airport-autocomplete-item');
                if (!item) return;

                const lat = parseFloat(item.getAttribute('data-lat'));
                const lon = parseFloat(item.getAttribute('data-lon'));
                const icao = item.getAttribute('data-icao');
                const name = item.getAttribute('data-name');

                if (!isNaN(lat) && !isNaN(lon)) {
                    // Set as new center
                    ArtState.center.lat = lat;
                    ArtState.center.lon = lon;
                    updateCenterInputs();
                    if (ArtState.centerMarker) {
                        ArtState.centerMarker.setLatLng([lat, lon]);
                    }
                    ArtState.map.setView([lat, lon], 11);

                    // Update departure & arrival airport
                    ArtState.depAirport = { icao, name, lat, lon };
                    ArtState.arrAirport = { icao, name, lat, lon };

                    const depInput = document.getElementById('depAirportInput');
                    const arrInput = document.getElementById('arrAirportInput');
                    const depName = document.getElementById('depAirportName');
                    const arrName = document.getElementById('arrAirportName');

                    if (depInput) depInput.value = icao;
                    if (arrInput) arrInput.value = icao;
                    if (depName) depName.innerText = name;
                    if (arrName) arrName.innerText = name;

                    applyTransformations();
                }

                listEl.classList.add('d-none');
                searchInput.value = `${icao} - ${name}`;
            });

            document.addEventListener('click', function (e) {
                if (!searchInput.contains(e.target) && !listEl.contains(e.target)) {
                    listEl.classList.add('d-none');
                }
            });
        }

        // Editable Departure & Arrival Airport Inputs
        setupSingleAirportInput('depAirportInput', 'depAirportSearchResults', 'depAirportName', (airport) => {
            ArtState.depAirport = airport;
            simplifyProjectedRoute();
        });

        setupSingleAirportInput('arrAirportInput', 'arrAirportSearchResults', 'arrAirportName', (airport) => {
            ArtState.arrAirport = airport;
            simplifyProjectedRoute();
        });

        // "Set Home" Button on Departure Input
        document.getElementById('setDepAsHomeBtn')?.addEventListener('click', () => {
            if (ArtState.depAirport) {
                saveConfiguredHomeAirport(ArtState.depAirport);
                const btn = document.getElementById('setDepAsHomeBtn');
                const orig = btn.innerHTML;
                btn.innerHTML = '<i class="bi bi-star-fill text-warning"></i> Saved!';
                setTimeout(() => { btn.innerHTML = orig; }, 2000);
            }
        });

        // "Round Trip" Button (Sync Arrival to Departure)
        document.getElementById('syncArrToDepBtn')?.addEventListener('click', () => {
            if (ArtState.depAirport) {
                ArtState.arrAirport = { ...ArtState.depAirport };
                const arrInput = document.getElementById('arrAirportInput');
                const arrName = document.getElementById('arrAirportName');
                if (arrInput) arrInput.value = ArtState.depAirport.icao;
                if (arrName) arrName.innerText = ArtState.depAirport.name;

                simplifyProjectedRoute();
            }
        });

        // Modal: Configure Home Airport
        let modalSelectedHome = { ...ArtState.homeAirport };
        const modalInput = document.getElementById('configHomeAirportInput');
        const modalList = document.getElementById('configHomeSearchResults');
        let modalTimeout = null;

        if (modalInput && modalList) {
            modalInput.addEventListener('input', function () {
                clearTimeout(modalTimeout);
                const q = modalInput.value.trim();
                if (q.length < 2) {
                    modalList.classList.add('d-none');
                    modalList.innerHTML = '';
                    return;
                }

                modalTimeout = setTimeout(() => {
                    searchAirports(q, function (data) {
                        if (!data || data.length === 0) {
                            modalList.innerHTML = '<div class="p-2 text-muted small">No airports found</div>';
                            modalList.classList.remove('d-none');
                            return;
                        }

                        let html = '';
                        data.forEach(ap => {
                            html += `<div class="airport-autocomplete-item" data-lat="${ap.lat}" data-lon="${ap.lon}" data-icao="${ap.icao || ap.faa}" data-name="${ap.name}">
                                <strong>${ap.icao || ap.faa}</strong> - ${ap.name} <span class="text-muted small">(${ap.city || ''}, ${ap.state || ''})</span>
                            </div>`;
                        });
                        modalList.innerHTML = html;
                        modalList.classList.remove('d-none');
                    });
                }, 180);
            });

            modalList.addEventListener('click', function (e) {
                const item = e.target.closest('.airport-autocomplete-item');
                if (!item) return;

                const lat = parseFloat(item.getAttribute('data-lat'));
                const lon = parseFloat(item.getAttribute('data-lon'));
                const icao = item.getAttribute('data-icao');
                const name = item.getAttribute('data-name');

                if (!isNaN(lat) && !isNaN(lon)) {
                    modalSelectedHome = { icao, name, lat, lon };
                    document.getElementById('configHomeCurrentBadge').innerText = icao;
                    document.getElementById('configHomeCurrentName').innerText = name;
                    document.getElementById('configHomeCurrentCoords').innerText = `${lat.toFixed(4)}°, ${lon.toFixed(4)}°`;
                }

                modalList.classList.add('d-none');
                modalInput.value = `${icao} - ${name}`;
            });

            document.addEventListener('click', function (e) {
                if (!modalInput.contains(e.target) && !modalList.contains(e.target)) {
                    modalList.classList.add('d-none');
                }
            });
        }

        document.getElementById('saveHomeAirportModalBtn')?.addEventListener('click', () => {
            saveConfiguredHomeAirport(modalSelectedHome);

            // Also switch current departure & arrival to the newly chosen home airport
            ArtState.depAirport = { ...modalSelectedHome };
            ArtState.arrAirport = { ...modalSelectedHome };

            const depInput = document.getElementById('depAirportInput');
            const arrInput = document.getElementById('arrAirportInput');
            const depName = document.getElementById('depAirportName');
            const arrName = document.getElementById('arrAirportName');

            if (depInput) depInput.value = modalSelectedHome.icao;
            if (arrInput) arrInput.value = modalSelectedHome.icao;
            if (depName) depName.innerText = modalSelectedHome.name;
            if (arrName) arrName.innerText = modalSelectedHome.name;

            buildFullFlightPlan();
            renderRouteOnMap();
            updateStatsHUD();
            renderWaypointTable();

            const modalEl = document.getElementById('configHomeAirportModal');
            if (modalEl && typeof bootstrap !== 'undefined') {
                const modal = bootstrap.Modal.getInstance(modalEl);
                if (modal) modal.hide();
            }
        });
    }

    // --- UI Controls Binding ---
    function bindUiControls() {
        // Undo / Redo Buttons
        ['undoBtn', 'mapUndoBtn'].forEach(id => {
            document.getElementById(id)?.addEventListener('click', () => HistoryManager.undo());
        });
        ['redoBtn', 'mapRedoBtn'].forEach(id => {
            document.getElementById(id)?.addEventListener('click', () => HistoryManager.redo());
        });

        // Global Keyboard Shortcuts (Cmd+Z / Ctrl+Z for Undo, Cmd+Shift+Z / Ctrl+Y for Redo)
        document.addEventListener('keydown', (e) => {
            const tag = (e.target.tagName || '').toLowerCase();
            if (tag === 'input' || tag === 'textarea' || e.target.isContentEditable) return;

            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
                e.preventDefault();
                if (e.shiftKey) {
                    HistoryManager.redo();
                } else {
                    HistoryManager.undo();
                }
            } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') {
                e.preventDefault();
                HistoryManager.redo();
            }
        });

        // Width (Size) Slider & Input
        const sizeSlider = document.getElementById('sizeSlider');
        const sizeInput = document.getElementById('sizeInput');
        if (sizeSlider && sizeInput) {
            sizeSlider.addEventListener('mousedown', () => HistoryManager.pushState());
            sizeSlider.addEventListener('touchstart', () => HistoryManager.pushState(), { passive: true });
            sizeInput.addEventListener('focus', () => HistoryManager.pushState());

            sizeSlider.addEventListener('input', () => {
                ArtState.sizeNM = parseFloat(sizeSlider.value) || 12;
                if (ArtState.lockAspect) {
                    ArtState.heightNM = Math.max(1, Math.min(100, Math.round(ArtState.sizeNM * (ArtState.aspectRatio || 1.0) * 10) / 10));
                }
                syncDimensionInputs();
                applyTransformations();
            });
            sizeInput.addEventListener('change', () => {
                ArtState.sizeNM = Math.max(1, Math.min(100, parseFloat(sizeInput.value) || 12));
                if (ArtState.lockAspect) {
                    ArtState.heightNM = Math.max(1, Math.min(100, Math.round(ArtState.sizeNM * (ArtState.aspectRatio || 1.0) * 10) / 10));
                }
                syncDimensionInputs();
                applyTransformations();
            });
        }

        // Height Slider & Input
        const heightSlider = document.getElementById('heightSlider');
        const heightInput = document.getElementById('heightInput');
        if (heightSlider && heightInput) {
            heightSlider.addEventListener('mousedown', () => HistoryManager.pushState());
            heightSlider.addEventListener('touchstart', () => HistoryManager.pushState(), { passive: true });
            heightInput.addEventListener('focus', () => HistoryManager.pushState());

            heightSlider.addEventListener('input', () => {
                ArtState.heightNM = parseFloat(heightSlider.value) || 12;
                if (ArtState.lockAspect) {
                    const asp = ArtState.aspectRatio || 1.0;
                    ArtState.sizeNM = Math.max(1, Math.min(100, Math.round((ArtState.heightNM / asp) * 10) / 10));
                }
                syncDimensionInputs();
                applyTransformations();
            });
            heightInput.addEventListener('change', () => {
                ArtState.heightNM = Math.max(1, Math.min(100, parseFloat(heightInput.value) || 12));
                if (ArtState.lockAspect) {
                    const asp = ArtState.aspectRatio || 1.0;
                    ArtState.sizeNM = Math.max(1, Math.min(100, Math.round((ArtState.heightNM / asp) * 10) / 10));
                }
                syncDimensionInputs();
                applyTransformations();
            });
        }

        // Aspect Ratio Lock Toggle Button
        document.getElementById('aspectLockBtn')?.addEventListener('click', () => {
            HistoryManager.pushState();
            ArtState.lockAspect = !ArtState.lockAspect;
            if (ArtState.lockAspect) {
                ArtState.heightNM = Math.max(1, Math.min(100, Math.round(ArtState.sizeNM * (ArtState.aspectRatio || 1.0) * 10) / 10));
                applyTransformations();
            }
            syncDimensionInputs();
        });

        // Rotation slider
        const rotSlider = document.getElementById('rotSlider');
        const rotBadge = document.getElementById('rotBadge');
        if (rotSlider) {
            rotSlider.addEventListener('mousedown', () => HistoryManager.pushState());
            rotSlider.addEventListener('touchstart', () => HistoryManager.pushState(), { passive: true });
            rotSlider.addEventListener('input', () => {
                ArtState.rotationDeg = parseInt(rotSlider.value) || 0;
                if (rotBadge) rotBadge.innerText = ArtState.rotationDeg + '°';
                applyTransformations();
            });
        }

        // Simplification / Smoothing slider
        const smoothSlider = document.getElementById('smoothSlider');
        if (smoothSlider) {
            smoothSlider.addEventListener('mousedown', () => HistoryManager.pushState());
            smoothSlider.addEventListener('touchstart', () => HistoryManager.pushState(), { passive: true });
            smoothSlider.addEventListener('input', () => {
                ArtState.simplificationTolerance = parseFloat(smoothSlider.value) || 0.015;
                simplifyProjectedRoute();
            });
        }

        // Flip buttons
        document.getElementById('flipHBtn')?.addEventListener('click', () => {
            HistoryManager.pushState();
            ArtState.flipH = !ArtState.flipH;
            applyTransformations();
        });
        document.getElementById('flipVBtn')?.addEventListener('click', () => {
            HistoryManager.pushState();
            ArtState.flipV = !ArtState.flipV;
            applyTransformations();
        });

        // Center Coordinate Inputs
        const centerLatInput = document.getElementById('centerLatInput');
        const centerLonInput = document.getElementById('centerLonInput');
        function onCenterChanged() {
            const lat = parseFloat(centerLatInput?.value);
            const lon = parseFloat(centerLonInput?.value);
            if (!isNaN(lat) && !isNaN(lon)) {
                ArtState.center.lat = lat;
                ArtState.center.lon = lon;
                if (ArtState.centerMarker) ArtState.centerMarker.setLatLng([lat, lon]);
                applyTransformations();
            }
        }
        centerLatInput?.addEventListener('change', onCenterChanged);
        centerLonInput?.addEventListener('change', onCenterChanged);

        // Center to Map button
        document.getElementById('centerToMapBtn')?.addEventListener('click', () => {
            const center = ArtState.map.getCenter();
            ArtState.center.lat = center.lat;
            ArtState.center.lon = center.lng;
            updateCenterInputs();
            if (ArtState.centerMarker) ArtState.centerMarker.setLatLng(center);
            applyTransformations();
        });

        // Speed & Fuel inputs
        const speedInput = document.getElementById('cruiseSpeedInput');
        const fuelInput = document.getElementById('fuelFlowInput');
        speedInput?.addEventListener('change', () => {
            ArtState.cruiseSpeedKts = parseFloat(speedInput.value) || 150;
            updateStatsHUD();
        });
        fuelInput?.addEventListener('change', () => {
            ArtState.fuelFlowGPH = parseFloat(fuelInput.value) || 8.5;
            updateStatsHUD();
        });

        // Include Airport toggle
        const airportToggle = document.getElementById('includeAirportCheck');
        airportToggle?.addEventListener('change', () => {
            ArtState.includeAirport = !!airportToggle.checked;
            simplifyProjectedRoute();
        });

        // Optimize Start/End Waypoint toggle
        const optToggle = document.getElementById('optimizeEntryExitCheck');
        optToggle?.addEventListener('change', () => {
            HistoryManager.pushState();
            ArtState.optimizeEntryExit = !!optToggle.checked;
            simplifyProjectedRoute();
        });

        // Reverse Route Direction Buttons
        function handleReverseRoute() {
            HistoryManager.pushState();
            ArtState.routeReversed = !ArtState.routeReversed;
            updateReverseButtons();
            simplifyProjectedRoute();
        }
        document.getElementById('reverseRouteBtn')?.addEventListener('click', handleReverseRoute);
        document.getElementById('mapReverseBtn')?.addEventListener('click', handleReverseRoute);

        // Drawing Mode Buttons
        document.getElementById('drawModeBtn')?.addEventListener('click', () => {
            toggleDrawMode(!ArtState.drawMode);
        });
        document.getElementById('clickModeBtn')?.addEventListener('click', () => {
            toggleClickMode(!ArtState.clickMode);
        });
        document.getElementById('clearDrawingBtn')?.addEventListener('click', () => {
            HistoryManager.pushState();
            ArtState.basePoints = [];
            ArtState.projectedPoints = [];
            ArtState.rawProjectedPoints = [];
            buildFullFlightPlan();
            renderRouteOnMap();
            updateStatsHUD();
            renderWaypointTable();
        });

        // Preset buttons
        document.querySelectorAll('.shape-preset-btn').forEach(btn => {
            btn.addEventListener('click', function () {
                const shape = this.getAttribute('data-shape');
                loadPreset(shape);
            });
        });

        // Text Art Form
        const textBtn = document.getElementById('textArtBtn');
        const textInput = document.getElementById('textArtInput');
        if (textBtn && textInput) {
            textBtn.addEventListener('click', () => {
                generateTextArt(textInput.value);
            });
            textInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    generateTextArt(textInput.value);
                }
            });
        }
        document.querySelectorAll('input[name="textStyleRadio"]').forEach(radio => {
            radio.addEventListener('change', () => {
                const text = textInput?.value;
                if (text && text.trim().length > 0) {
                    generateTextArt(text);
                }
            });
        });

        // Save Drawing triggers & Modal
        document.getElementById('headerSaveDrawingBtn')?.addEventListener('click', openSaveDrawingModal);
        document.getElementById('dropdownSaveDrawingAction')?.addEventListener('click', (e) => {
            e.preventDefault();
            openSaveDrawingModal();
        });
        document.getElementById('saveDrawingFromDrawTabBtn')?.addEventListener('click', openSaveDrawingModal);

        document.getElementById('confirmSaveDrawingBtn')?.addEventListener('click', () => {
            const input = document.getElementById('saveDrawingNameInput');
            const name = input?.value || '';
            const success = saveDrawingToStorage(name);
            if (success) {
                const modalEl = document.getElementById('saveDrawingModal');
                if (modalEl && typeof bootstrap !== 'undefined') {
                    const modal = bootstrap.Modal.getInstance(modalEl);
                    if (modal) modal.hide();
                }
            }
        });

        document.getElementById('saveDrawingNameInput')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                document.getElementById('confirmSaveDrawingBtn')?.click();
            }
        });

        // File Dropzone & Input
        const dropzone = document.getElementById('artDropzone');
        const fileInput = document.getElementById('artFileInput');

        if (dropzone && fileInput) {
            dropzone.addEventListener('click', () => fileInput.click());
            dropzone.addEventListener('dragover', (e) => {
                e.preventDefault();
                dropzone.classList.add('dragover');
            });
            dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
            dropzone.addEventListener('drop', (e) => {
                e.preventDefault();
                dropzone.classList.remove('dragover');
                if (e.dataTransfer.files && e.dataTransfer.files[0]) {
                    handleUploadedFile(e.dataTransfer.files[0]);
                }
            });

            fileInput.addEventListener('change', () => {
                if (fileInput.files && fileInput.files[0]) {
                    handleUploadedFile(fileInput.files[0]);
                }
            });
        }

        // Import Mode Radio change listener (instantly reprocesses current uploaded file)
        document.querySelectorAll('input[name="importModeRadio"]').forEach(radio => {
            radio.addEventListener('change', () => {
                if (ArtState.lastUploadedFile) {
                    handleUploadedFile(ArtState.lastUploadedFile);
                }
            });
        });

        // Export Buttons
        document.getElementById('downloadFplBtn')?.addEventListener('click', () => {
            const xml = generateGarminFplXml();
            triggerFileDownload(xml, 'N890GF_SkyArt.fpl', 'application/xml');
        });

        document.getElementById('openForeflightBtn')?.addEventListener('click', () => {
            const url = generateForeFlightMobileUrl();
            if (!url) {
                alert("No route waypoints generated yet.");
                return;
            }
            window.location.href = url;
        });

        document.getElementById('showQrBtn')?.addEventListener('click', showQrCodeModal);

        document.getElementById('copyRouteBtn')?.addEventListener('click', () => {
            const routeStr = generateForeFlightRouteString();
            if (!routeStr) {
                alert("No route waypoints generated yet.");
                return;
            }
            navigator.clipboard.writeText(routeStr).then(() => {
                const btn = document.getElementById('copyRouteBtn');
                const orig = btn.innerHTML;
                btn.innerHTML = '<i class="bi bi-check-lg text-success"></i> Copied!';
                setTimeout(() => { btn.innerHTML = orig; }, 2000);
            });
        });

        document.getElementById('downloadGpxBtn')?.addEventListener('click', () => {
            const xml = generateGpxXml();
            triggerFileDownload(xml, 'N890GF_SkyArt.gpx', 'application/gpx+xml');
        });

        document.getElementById('downloadKmlBtn')?.addEventListener('click', () => {
            const xml = generateKmlXml();
            triggerFileDownload(xml, 'N890GF_SkyArt.kml', 'application/vnd.google-earth.kml+xml');
        });
    }

    function handleUploadedFile(file) {
        if (!file) return;
        ArtState.lastUploadedFile = file;
        const name = file.name.toLowerCase();
        if (name.endsWith('.svg')) {
            const reader = new FileReader();
            reader.onload = (e) => parseSvg(e.target.result);
            reader.readAsText(file);
        } else if (name.endsWith('.png') || file.type === 'image/png') {
            const reader = new FileReader();
            reader.onload = (e) => {
                const img = new Image();
                img.onload = () => tracePngImage(img);
                img.src = e.target.result;
            };
            reader.readAsDataURL(file);
        } else {
            alert("Please upload an SVG vector file (.svg) or a transparent PNG (.png).");
        }
    }

    // --- DOM Ready ---
    document.addEventListener('DOMContentLoaded', function () {
        initMap();
        setupAirportControls();
        bindUiControls();
        updateCenterInputs();
        updateHomeAirportUI();
        syncDimensionInputs();
        renderSavedDrawingsDropdown();
        HistoryManager.updateButtons();
    });

    // Expose for testing & global inspection
    window.ArtState = ArtState;
    window.SkyState = ArtState;
    window.DEFAULT_HOME_AIRPORT = DEFAULT_HOME_AIRPORT;
    window.loadConfiguredHomeAirport = loadConfiguredHomeAirport;
    window.saveConfiguredHomeAirport = saveConfiguredHomeAirport;
    window.generateForeFlightRouteString = generateForeFlightRouteString;
    window.generateGarminFplXml = generateGarminFplXml;
    window.generateForeFlightMobileUrl = generateForeFlightMobileUrl;
    window.getSavedDrawings = getSavedDrawings;
    window.saveDrawingToStorage = saveDrawingToStorage;
    window.loadSavedDrawing = loadSavedDrawing;
    window.deleteSavedDrawing = deleteSavedDrawing;
    window.HistoryManager = HistoryManager;
    window.syncDimensionInputs = syncDimensionInputs;

})();
