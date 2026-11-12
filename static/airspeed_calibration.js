/* ==========================================================================
   AIRSPEED CALIBRATION ANALYSIS INTERACTIVE INTERFACE
   Allows 2-click maneuver selection on plot (similar to GAMI spread),
   calculates airspeed calibration, and extracts engine settings.
   ========================================================================== */

function getAsCalElem(id) {
    if (!id) return null;
    const prefixed = 'asCal' + id.charAt(0).toUpperCase() + id.slice(1);
    const calPrefixed = 'cal' + id.charAt(0).toUpperCase() + id.slice(1);
    return document.getElementById(prefixed) || 
           document.getElementById(calPrefixed) || 
           document.getElementById('asCal' + id) || 
           document.getElementById('cal' + id) || 
           document.getElementById(id);
}

let asCalCurrentData = null;
let asCalSelectionState = {
    start: null,
    end: null
};

document.addEventListener("DOMContentLoaded", () => {
    // Populate airspeed calibration modal saved flights dropdown if present
    fetch('/api/saved_flights')
        .then(r => r.json())
        .then(data => {
            const sel = document.getElementById('asCalSavedFlights');
            if (!sel) return;

            const files = Array.isArray(data)
                ? data
                : (data.files || data.file_list || []);

            sel.innerHTML = '';
            files
                .filter(Boolean)
                .sort((a, b) => b.localeCompare(a))
                .forEach(f => {
                    sel.add(new Option(f, f));
                });
        })
        .catch(err => {
            console.error("Failed to load flights for calibration:", err);
        });

    const modalEl = document.getElementById('airspeedCalModal');
    if (modalEl) {
        modalEl.addEventListener('shown.bs.modal', () => {
            const timeGraph = getAsCalElem('timeGraph');
            const mapDiv = getAsCalElem('mapDiv');
            if (timeGraph && timeGraph.data) Plotly.Plots.resize(timeGraph);
            if (mapDiv && mapDiv.data) Plotly.Plots.resize(mapDiv);
        });
    }
});

function getAppStateRef() {
    if (typeof AppState !== 'undefined') return AppState;
    if (typeof window !== 'undefined' && window.AppState) return window.AppState;
    return null;
}

function openAirspeedCalModal() {
    const modalEl = document.getElementById('airspeedCalModal');
    if (!modalEl) return;

    // Reset selection state
    asCalSelectionState = { start: null, end: null };

    // Clear previous inputs
    const startInput = getAsCalElem('calStartTime') || getAsCalElem('startTime');
    const endInput = getAsCalElem('calEndTime') || getAsCalElem('endTime');
    if (startInput) startInput.value = '';
    if (endInput) endInput.value = '';

    const resultsContainer = document.getElementById('asCalResultsContainer');
    if (resultsContainer) resultsContainer.classList.add('d-none');

    const resultBox = document.getElementById('calibrationResult');
    if (resultBox) {
        resultBox.classList.add('d-none');
        resultBox.innerText = 'Results will appear here...';
    }

    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();

    // Sync modal dropdown with main select choices safely
    const mainSelect = document.getElementById('savedFlights');
    const calSelect = document.getElementById('asCalSavedFlights');
    const appState = getAppStateRef();

    let activeFile = null;
    if (appState && appState.file && appState.file.currentName) {
        activeFile = appState.file.currentName;
    } else if (mainSelect && mainSelect.value) {
        activeFile = mainSelect.value;
    }

    if (mainSelect && calSelect && mainSelect !== calSelect && mainSelect.options.length > 0) {
        calSelect.innerHTML = mainSelect.innerHTML;
        if (activeFile) {
            calSelect.value = activeFile;
        }
    }

    const timeGraph = getAsCalElem('timeGraph');
    const waitForLayoutAndLoad = () => {
        if (timeGraph && timeGraph.clientWidth === 0 && modalEl.style.display !== 'block') {
            requestAnimationFrame(waitForLayoutAndLoad);
            return;
        }
        loadAirspeedCalFlight();
    };
    requestAnimationFrame(waitForLayoutAndLoad);
}

function loadAirspeedCalFlight() {
    // Reset maneuver selection & previous flight results when loading a flight
    asCalSelectionState = { start: null, end: null };
    window._lastAsCalCursorIdx = null;
    const startInput = getAsCalElem('calStartTime') || getAsCalElem('startTime');
    const endInput = getAsCalElem('calEndTime') || getAsCalElem('endTime');
    if (startInput) startInput.value = '';
    if (endInput) endInput.value = '';
    const resultsContainer = document.getElementById('asCalResultsContainer');
    if (resultsContainer) resultsContainer.classList.add('d-none');
    const resultBox = document.getElementById('calibrationResult');
    if (resultBox) {
        resultBox.classList.add('d-none');
        resultBox.innerText = 'Results will appear here...';
    }

    let selectedFile = null;
    const calSel = document.getElementById('asCalSavedFlights');
    const mainSel = document.getElementById('savedFlights');
    const appState = getAppStateRef();

    if (calSel && calSel.value && calSel.value !== "") {
        selectedFile = calSel.value;
    } else if (mainSel && mainSel.value && mainSel.value !== "") {
        selectedFile = mainSel.value;
    } else if (appState && appState.file && appState.file.currentName) {
        selectedFile = appState.file.currentName;
    }

    if (!selectedFile) {
        const instruction = getAsCalElem('instruction');
        if (instruction) instruction.innerText = 'No flight loaded. Select a flight from the dropdown above.';
        return;
    }

    // Check if we already have this flight loaded in AppState
    if (appState && appState.file && appState.file.currentName === selectedFile) {
        const existingData = appState.rawData ||
            (appState.lastAnalysisResponse && (appState.lastAnalysisResponse.rawData || appState.lastAnalysisResponse.plot_data)) ||
            appState.currentPlotData;
        if (existingData) {
            asCalCurrentData = existingData;
            renderAirspeedCalPlot(asCalCurrentData);
            const savedCals = (appState.currentFlightStats && appState.currentFlightStats.saved_calibrations) ||
                (appState.lastAnalysisResponse && appState.lastAnalysisResponse.stats && appState.lastAnalysisResponse.stats.saved_calibrations) ||
                window.lastSavedCalibrations || [];
            renderModalSavedAirspeedCalibrations(savedCals);
            return;
        }
    }

    const instruction = getAsCalElem('instruction');
    if (instruction) instruction.innerHTML = '<span class="spinner-border spinner-border-sm text-primary"></span> Loading flight data for calibration...';

    const formData = new FormData();
    formData.append('saved_filename', selectedFile);
    formData.append('filters', JSON.stringify([]));

    fetch('/api/analyze_flight', {
        method: 'POST',
        body: formData
    })
    .then(r => r.json())
    .then(data => {
        if (data.error) {
            if (instruction) instruction.innerText = 'Error: ' + data.error;
            return;
        }
        if (!data.rawData && data.plot_data && typeof window.reconstructRawDataFromPlotData === 'function') {
            data.rawData = window.reconstructRawDataFromPlotData(data.plot_data);
        }
        asCalCurrentData = data.rawData || data.plot_data || data.data || data;
        renderAirspeedCalPlot(asCalCurrentData);
        const savedCals = (data.stats && data.stats.saved_calibrations) || [];
        renderModalSavedAirspeedCalibrations(savedCals);
    })
    .catch(err => {
        console.error("Airspeed Cal data load error:", err);
        if (instruction) instruction.innerText = "Error loading flight data.";
    });
}

function renderAirspeedCalPlot(data) {
    const instruction = getAsCalElem('instruction');
    const graphDiv = getAsCalElem('timeGraph');
    if (!graphDiv || !data) return;

    // Helper to safely fetch numeric arrays from row array or column dict
    function getSeries(colNames) {
        if (!data) return [];
        const records = (typeof data === 'object' && data !== null && !Array.isArray(data) && (data.rawData || data.plot_data || data.data || data.dataframe))
            ? (data.rawData || data.plot_data || data.data || data.dataframe)
            : data;

        // Case 1: Array of record objects [{ col1: v1, col2: v2 }, ...]
        if (Array.isArray(records)) {
            for (const col of colNames) {
                if (records.length > 0 && col in records[0]) {
                    return records.map(row => row[col]);
                }
            }
        }

        // Case 2: Column dictionary { col1: [v1, v2], col2: [...] }
        if (typeof records === 'object' && records !== null) {
            for (const col of colNames) {
                if (records[col] && Array.isArray(records[col])) {
                    return records[col];
                }
            }
        }

        return [];
    }

    const sessionTimes = getSeries(['Session Time', 'session_time', 'x_sec']);
    const ias = getSeries(['Indicated Airspeed (knots)', 'ias', 'IAS', 'airspeed']);
    const gs = getSeries(['Ground Speed (knots)', 'groundspeed', 'gps_gs', 'GS']);
    const hdg = getSeries(['Magnetic Heading (deg)', 'heading', 'hdg', 'HDG']);
    const alt = getSeries(['Pressure Altitude (ft)', 'press_alt', 'altitude', 'ALT']);

    if (!sessionTimes.length || !ias.length) {
        if (instruction) instruction.innerText = "Airspeed or time data missing in this log file.";
        return;
    }

    if (instruction) {
        instruction.innerText = "Click 2 points on the graph or map to select your 360° maneuver window (Green = Start, Red = End).";
    }

    const traceIAS = {
        x: sessionTimes,
        y: ias,
        name: 'IAS (kts)',
        type: 'scatter',
        mode: 'lines',
        line: { color: '#0d6efd', width: 2 }
    };

    const traceGS = {
        x: sessionTimes,
        y: gs,
        name: 'Ground Speed (kts)',
        type: 'scatter',
        mode: 'lines',
        line: { color: '#0dcaf0', width: 1.5, dash: 'dot' }
    };

    const traceHDG = {
        x: sessionTimes,
        y: hdg,
        name: 'Heading (°)',
        yaxis: 'y2',
        type: 'scatter',
        mode: 'lines',
        line: { color: '#fd7e14', width: 1.5 }
    };

    const traceAlt = {
        x: sessionTimes,
        y: alt,
        name: 'Alt (ft)',
        yaxis: 'y3',
        type: 'scatter',
        mode: 'lines',
        line: { color: '#6c757d', width: 1, dash: 'dash' },
        visible: 'legendonly'
    };

    const layout = {
        autosize: true,
        xaxis: { title: 'Session Time (seconds)' },
        yaxis: { title: 'Airspeed / Groundspeed (kts)', side: 'left' },
        yaxis2: { title: 'Magnetic Heading (°)', overlaying: 'y', side: 'right', range: [0, 360] },
        yaxis3: { title: 'Altitude (ft)', overlaying: 'y', visible: false },
        margin: { l: 55, r: 55, t: 36, b: 42 },
        legend: { orientation: 'h', x: 0, y: 1.1 },
        hovermode: 'x'
    };

    Plotly.newPlot(graphDiv, [traceIAS, traceGS, traceHDG, traceAlt], layout, { responsive: true });

    // Render side-by-side interactive map
    renderAsCalMap(data, asCalSelectionState.start, asCalSelectionState.end);

    // Hover listener to follow cursor on map & banner
    graphDiv.on('plotly_hover', (eventData) => {
        if (!eventData || !eventData.points || !eventData.points.length) return;
        const pt = eventData.points[0];
        const pointIdx = pt.pointIndex;
        updateAsCalMapCursor(data, pointIdx);
    });

    // Handle 2-click maneuver selection
    graphDiv.on('plotly_click', (eventData) => {
        if (!eventData || !eventData.points || !eventData.points.length) return;
        const x = eventData.points[0].x;
        handleAsCalPointSelection(x, data);
    });
}

function handleAsCalPointSelection(x, dataOverride) {
    const selectedTime = parseFloat(x);
    if (isNaN(selectedTime)) return;
    const activeData = dataOverride || asCalCurrentData;

    if (asCalSelectionState.start === null || asCalSelectionState.end !== null) {
        // First click
        asCalSelectionState.start = selectedTime;
        asCalSelectionState.end = null;
    } else {
        // Second click
        asCalSelectionState.end = selectedTime;
        if (asCalSelectionState.end < asCalSelectionState.start) {
            const tmp = asCalSelectionState.start;
            asCalSelectionState.start = asCalSelectionState.end;
            asCalSelectionState.end = tmp;
        }
    }

    // Sync input boxes
    const startInput = getAsCalElem('calStartTime') || getAsCalElem('startTime');
    const endInput = getAsCalElem('calEndTime') || getAsCalElem('endTime');
    if (startInput) {
        startInput.value = asCalSelectionState.start !== null
            ? Math.round(asCalSelectionState.start * 10) / 10
            : '';
    }
    if (endInput) {
        endInput.value = asCalSelectionState.end !== null
            ? Math.round(asCalSelectionState.end * 10) / 10
            : '';
    }

    drawAsCalShapes();

    // Update map maneuver segment highlight & start/end markers
    if (activeData) {
        renderAsCalMap(activeData, asCalSelectionState.start, asCalSelectionState.end);
    }

    const instruction = getAsCalElem('instruction');
    if (asCalSelectionState.start !== null && asCalSelectionState.end === null) {
        if (instruction) {
            instruction.innerText = `Start set at ${Math.round(asCalSelectionState.start * 10) / 10}s. Click a 2nd point on the graph or map to set End and run calibration.`;
        }
    } else if (asCalSelectionState.start !== null && asCalSelectionState.end !== null) {
        submitAirspeedCalibration(asCalSelectionState.start, asCalSelectionState.end);
    }
}

function drawAsCalShapes() {
    const graphDiv = getAsCalElem('timeGraph');
    if (!graphDiv || !graphDiv.layout) return;

    const shapes = [];

    // Shaded maneuver region
    if (asCalSelectionState.start !== null && asCalSelectionState.end !== null) {
        shapes.push({
            type: 'rect',
            x0: asCalSelectionState.start,
            x1: asCalSelectionState.end,
            y0: 0,
            y1: 1,
            yref: 'paper',
            fillcolor: 'rgba(25, 135, 84, 0.15)',
            line: { width: 0 }
        });
    }

    // Start vertical line (green)
    if (asCalSelectionState.start !== null) {
        shapes.push({
            type: 'line',
            x0: asCalSelectionState.start,
            x1: asCalSelectionState.start,
            y0: 0,
            y1: 1,
            yref: 'paper',
            line: { color: '#198754', width: 2 }
        });
    }

    // End vertical line (red)
    if (asCalSelectionState.end !== null) {
        shapes.push({
            type: 'line',
            x0: asCalSelectionState.end,
            x1: asCalSelectionState.end,
            y0: 0,
            y1: 1,
            yref: 'paper',
            line: { color: '#dc3545', width: 2 }
        });
    }

    Plotly.relayout(graphDiv, { shapes });
}

function submitAirspeedCalibration(optStart, optEnd) {
    const startInput = getAsCalElem('calStartTime') || getAsCalElem('startTime');
    const endInput = getAsCalElem('calEndTime') || getAsCalElem('endTime');

    let start = (optStart !== undefined && optStart !== null) ? parseFloat(optStart) : (startInput ? parseFloat(startInput.value) : NaN);
    let end = (optEnd !== undefined && optEnd !== null) ? parseFloat(optEnd) : (endInput ? parseFloat(endInput.value) : NaN);

    // Fall back to selection state if inputs are blank
    if (isNaN(start) && asCalSelectionState.start !== null) start = asCalSelectionState.start;
    if (isNaN(end) && asCalSelectionState.end !== null) end = asCalSelectionState.end;

    const instruction = getAsCalElem('instruction');
    const resultBox = document.getElementById('calibrationResult');
    const resultsContainer = document.getElementById('asCalResultsContainer');

    if (isNaN(start) || isNaN(end)) {
        if (instruction) instruction.innerText = "Please select or enter valid start and end maneuver times.";
        return;
    }

    let selectedFile = null;
    const calSel = document.getElementById('asCalSavedFlights');
    const mainSel = document.getElementById('savedFlights');
    const appState = getAppStateRef();

    if (calSel && calSel.value && calSel.value !== "") {
        selectedFile = calSel.value;
    } else if (mainSel && mainSel.value && mainSel.value !== "") {
        selectedFile = mainSel.value;
    } else if (appState && appState.file && appState.file.currentName) {
        selectedFile = appState.file.currentName;
    }

    if (!selectedFile) {
        if (instruction) instruction.innerText = "No flight selected.";
        return;
    }

    // Store globally for flight map highlight if calibrating the currently active Analyzer flight
    if (appState && appState.calibration && (!appState.file || !appState.file.currentName || appState.file.currentName === selectedFile)) {
        appState.calibration.start = start;
        appState.calibration.end = end;
        appState.calibration.filename = selectedFile;
    }

    asCalSelectionState.start = start;
    asCalSelectionState.end = end;
    drawAsCalShapes();

    if (instruction) {
        instruction.innerHTML = '<span class="spinner-border spinner-border-sm text-primary"></span> Running calibration calculation...';
    }

    const formData = new FormData();
    formData.append('saved_filename', selectedFile);
    formData.append('start_time', start);
    formData.append('end_time', end);

    fetch('/api/airspeed_calibration', {
        method: 'POST',
        body: formData
    })
    .then(res => {
        if (res.redirected && res.url && res.url.includes('/login')) {
            throw new Error('SESSION_EXPIRED');
        }
        return res.json();
    })
    .then(data => {
        if (data.error) {
            if (instruction) instruction.innerText = "Error: " + data.error;
            if (resultBox) {
                resultBox.classList.remove('d-none');
                resultBox.innerText = "Error: " + data.error;
            }
            return;
        }

        const resObj = data.results || {};
        const engObj = data.engine_settings || {};

        if (instruction) {
            let msg = `✅ Calibration calculated for <strong>${formatMMSS(start)}</strong> to <strong>${formatMMSS(end)}</strong>.`;
            if (resObj.heading_span_deg !== undefined && resObj.heading_span_deg < 180) {
                msg += `<br><span class="text-warning fw-bold">⚠️ Notice: Selected segment covers ${resObj.heading_span_deg}° of heading change. For optimal wind triangle calibration, select a 3-leg triangle maneuver or a 360° turn segment.</span>`;
            }
            instruction.innerHTML = msg;
        }

        const summary = data.summary || "No summary returned.";
        if (resultBox) resultBox.innerText = summary;

        let windStr = 'N/A';
        if (resObj.wind_direction_deg !== undefined && resObj.wind_speed_kts !== undefined && resObj.wind_speed_kts > 0) {
            windStr = `${resObj.wind_direction_deg}° @ ${resObj.wind_speed_kts} kts`;
        } else if (resObj.native_wind_direction_deg !== undefined && resObj.native_wind_speed_kts !== undefined) {
            windStr = `${resObj.native_wind_direction_deg}° @ ${resObj.native_wind_speed_kts} kts`;
        }

        const magVarStr = resObj.magnetic_variation_deg !== undefined ? (resObj.magnetic_variation_deg >= 0 ? '+' : '') + resObj.magnetic_variation_deg + '°' : '0.0°';
        const asErrorStr = resObj.airspeed_error_kts !== undefined ? (resObj.airspeed_error_kts >= 0 ? '+' : '') + resObj.airspeed_error_kts + ' kts' : 'N/A';
        const corrCasStr = resObj.average_calibrated_airspeed_kts !== undefined ? resObj.average_calibrated_airspeed_kts + ' kts' : 'N/A';
        const uncorrTasStr = resObj.uncorrected_average_true_airspeed_kts !== undefined ? resObj.uncorrected_average_true_airspeed_kts + ' kts' : 'N/A';
        const corrTasStr = resObj.corrected_average_true_airspeed_kts !== undefined ? resObj.corrected_average_true_airspeed_kts + ' kts' : 'N/A';

        const errorColorClass = (resObj.airspeed_error_kts !== undefined && resObj.airspeed_error_kts >= 0) ? 'text-success' : 'text-danger';

        const daStr = resObj.density_altitude_ft !== undefined ? Number(resObj.density_altitude_ft).toLocaleString() + ' ft' : 'N/A';

        const metricsGrid = document.getElementById('asCalMetricsGrid');
        if (metricsGrid) {
            metricsGrid.innerHTML = `
                <div class="col-6 col-md-3">
                    <div class="p-2 bg-light rounded text-center">
                        <div class="text-muted extra-small">Airspeed Error</div>
                        <div class="fw-bold fs-6 ${errorColorClass}">${asErrorStr}</div>
                    </div>
                </div>
                <div class="col-6 col-md-3">
                    <div class="p-2 bg-light rounded text-center">
                        <div class="text-muted extra-small">Corrected CAS</div>
                        <div class="fw-bold fs-6 text-primary">${corrCasStr}</div>
                    </div>
                </div>
                <div class="col-6 col-md-3">
                    <div class="p-2 bg-light rounded text-center">
                        <div class="text-muted extra-small">Uncorrected TAS</div>
                        <div class="fw-bold fs-6 text-secondary">${uncorrTasStr}</div>
                    </div>
                </div>
                <div class="col-6 col-md-3">
                    <div class="p-2 bg-light rounded text-center">
                        <div class="text-muted extra-small">Corrected TAS</div>
                        <div class="fw-bold fs-6 text-success">${corrTasStr}</div>
                    </div>
                </div>
                <div class="col-6 col-md-3 mt-2">
                    <div class="p-2 bg-light rounded text-center">
                        <div class="text-muted extra-small">Density Altitude</div>
                        <div class="fw-bold fs-6 text-dark">${daStr}</div>
                    </div>
                </div>
                <div class="col-6 col-md-3 mt-2">
                    <div class="p-2 bg-light rounded text-center">
                        <div class="text-muted extra-small">Compass HDG Bias</div>
                        <div class="fw-bold fs-6 text-secondary">${resObj.calibrated_heading_correction_deg !== undefined ? (resObj.calibrated_heading_correction_deg >= 0 ? '+' : '') + resObj.calibrated_heading_correction_deg + '°' : 'N/A'}</div>
                    </div>
                </div>
                <div class="col-6 col-md-3 mt-2">
                    <div class="p-2 bg-light rounded text-center">
                        <div class="text-muted extra-small">Mag Variation</div>
                        <div class="fw-bold fs-6 text-info">${magVarStr}</div>
                    </div>
                </div>
                <div class="col-6 col-md-3 mt-2">
                    <div class="p-2 bg-light rounded text-center">
                        <div class="text-muted extra-small">Wind Dir / Speed</div>
                        <div class="fw-bold fs-6 text-dark">${windStr}</div>
                    </div>
                </div>
            `;
        }

        const engineGrid = document.getElementById('asCalEngineGrid');
        if (engineGrid) {
            engineGrid.innerHTML = `
                <div class="col-6">
                    <div class="p-2 bg-light rounded text-center">
                        <div class="text-muted extra-small">Manifold Pressure</div>
                        <div class="fw-bold fs-6 text-dark">${engObj.manifold_pressure_inhg !== null && engObj.manifold_pressure_inhg !== undefined ? engObj.manifold_pressure_inhg + ' inHg' : 'N/A'}</div>
                    </div>
                </div>
                <div class="col-6">
                    <div class="p-2 bg-light rounded text-center">
                        <div class="text-muted extra-small">RPM</div>
                        <div class="fw-bold fs-6 text-dark">${engObj.rpm !== null && engObj.rpm !== undefined ? engObj.rpm : 'N/A'}</div>
                    </div>
                </div>
                <div class="col-6">
                    <div class="p-2 bg-light rounded text-center">
                        <div class="text-muted extra-small">Fuel Flow</div>
                        <div class="fw-bold fs-6 text-dark">${engObj.fuel_flow_gph !== null && engObj.fuel_flow_gph !== undefined ? engObj.fuel_flow_gph + ' gph' : 'N/A'}</div>
                    </div>
                </div>
                <div class="col-6">
                    <div class="p-2 bg-light rounded text-center">
                        <div class="text-muted extra-small">% Power</div>
                        <div class="fw-bold fs-6 text-dark">${engObj.percent_power !== null && engObj.percent_power !== undefined ? engObj.percent_power + ' %' : 'N/A'}</div>
                    </div>
                </div>
            `;
        }

        if (resultsContainer) resultsContainer.classList.remove('d-none');

        if (data.saved_calibrations) {
            const appState = getAppStateRef();
            const isActiveAnalyzerFlight = !appState || !appState.file || !appState.file.currentName || appState.file.currentName === selectedFile;
            if (isActiveAnalyzerFlight) {
                window.lastSavedCalibrations = data.saved_calibrations;
                if (appState && appState.currentFlightStats) {
                    appState.currentFlightStats.saved_calibrations = data.saved_calibrations;
                }
                renderSavedAirspeedCalibrations(data.saved_calibrations);
            }
            renderModalSavedAirspeedCalibrations(data.saved_calibrations);
        }

        const appState = getAppStateRef();
        if (window.renderMap && appState && appState.map && appState.map.lastRenderData && (!appState.file || !appState.file.currentName || appState.file.currentName === selectedFile)) {
            renderMap(appState.map.lastRenderData);
        }
    })
    .catch(err => {
        console.error(err);
        if (instruction) {
            if (err && err.message === 'SESSION_EXPIRED') {
                instruction.innerHTML = '⚠️ Your login session expired. Please <a href="/login?next=/analyzer" class="fw-bold">log in again</a> to run and save calibrations.';
            } else {
                instruction.innerText = "Network error during calibration.";
            }
        }
    });
}

function selectSavedCalibrationInModal(start, end) {
    const s = parseFloat(start);
    const e = parseFloat(end);
    if (isNaN(s) || isNaN(e)) return;
    asCalSelectionState.start = s;
    asCalSelectionState.end = e;
    const startInput = getAsCalElem('calStartTime') || getAsCalElem('startTime');
    const endInput = getAsCalElem('calEndTime') || getAsCalElem('endTime');
    if (startInput) startInput.value = Math.round(s * 10) / 10;
    if (endInput) endInput.value = Math.round(e * 10) / 10;
    drawAsCalShapes();
    if (asCalCurrentData) {
        renderAsCalMap(asCalCurrentData, s, e, true);
    }
    submitAirspeedCalibration(s, e);
}

function renderModalSavedAirspeedCalibrations(calsList) {
    let container = document.getElementById('asCalModalSavedList');
    if (!container) {
        const resultsContainer = document.getElementById('asCalResultsContainer');
        if (!resultsContainer || !resultsContainer.parentNode) return;
        container = document.createElement('div');
        container.id = 'asCalModalSavedList';
        resultsContainer.parentNode.insertBefore(container, resultsContainer);
    }
    if (!calsList || calsList.length === 0) {
        container.innerHTML = '';
        return;
    }
    const itemsHtml = calsList.map((item, idx) => {
        const resObj = item.results || {};
        const engObj = item.engine_settings || {};
        const start = item.start_time;
        const end = item.end_time;
        const asErrorVal = resObj.airspeed_error_kts;
        const asErrorStr = asErrorVal !== undefined ? (asErrorVal >= 0 ? '+' : '') + asErrorVal + ' kts' : 'N/A';
        const errorColorClass = (asErrorVal !== undefined && asErrorVal >= 0) ? 'text-success' : 'text-danger';
        const corrTasStr = resObj.corrected_average_true_airspeed_kts !== undefined ? resObj.corrected_average_true_airspeed_kts + ' kts' : 'N/A';
        const uncorrTasStr = resObj.uncorrected_average_true_airspeed_kts !== undefined ? resObj.uncorrected_average_true_airspeed_kts + ' kts' : 'N/A';
        const daStr = resObj.density_altitude_ft !== undefined ? Number(resObj.density_altitude_ft).toLocaleString() + ' ft' : 'N/A';
        const powerStr = engObj.percent_power !== null && engObj.percent_power !== undefined ? engObj.percent_power + '%' : 'N/A';
        return `
            <div class="d-flex flex-wrap justify-content-between align-items-center p-2 mb-1 rounded border bg-white shadow-sm small">
                <div class="d-flex flex-wrap align-items-center gap-2">
                    <span class="badge bg-primary">#${idx + 1}: ${formatMMSS(start)} - ${formatMMSS(end)}</span>
                    <span><strong>Corr TAS:</strong> ${corrTasStr} <span class="text-muted">(Uncorr: ${uncorrTasStr})</span></span>
                    <span><strong>Error:</strong> <span class="${errorColorClass} fw-bold">${asErrorStr}</span></span>
                    <span><strong>DA:</strong> ${daStr}</span>
                    <span><strong>Power:</strong> ${powerStr}</span>
                </div>
                <div class="d-flex align-items-center gap-1 mt-1 mt-sm-0">
                    <button type="button" class="btn btn-sm btn-outline-primary py-0 px-2" onclick="selectSavedCalibrationInModal(${start}, ${end})">
                        View Segment
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-danger py-0 px-2" onclick="deleteAirspeedCalibration(${item.id})">
                        &times; Delete
                    </button>
                </div>
            </div>
        `;
    }).join('');
    container.innerHTML = `
        <div class="card p-2 mb-3 bg-body-tertiary border shadow-sm">
            <div class="fw-bold small text-primary mb-2">✈️ Saved Airspeed Calibrations for Selected Flight (${calsList.length})</div>
            ${itemsHtml}
        </div>
    `;
}

function renderSavedAirspeedCalibrations(calsList) {
    const statsList = document.getElementById('statsList');
    if (!statsList) return;

    const statsCard = document.getElementById('statsCard');
    const statsPlaceholder = document.getElementById('statsPlaceholder');
    if (statsCard) statsCard.classList.remove('d-none');
    if (statsPlaceholder) statsPlaceholder.classList.add('d-none');

    let wasCollapsed = window._airspeedCalCollapsed === true;
    let existingCollapse = document.getElementById('airspeedCalCollapse');
    if (existingCollapse) {
        wasCollapsed = !existingCollapse.classList.contains('show');
    }

    let existing = document.getElementById('airspeed-summary-block');
    if (existing) existing.remove();

    if (!calsList || calsList.length === 0) return;

    const block = document.createElement('div');
    block.id = 'airspeed-summary-block';
    block.className = 'col-12 mt-3 p-3 border rounded shadow-sm bg-light';

    let headerHtml = `
        <div class="d-flex justify-content-between align-items-center" role="button" data-bs-toggle="collapse" data-bs-target="#airspeedCalCollapse" aria-expanded="${!wasCollapsed}" aria-controls="airspeedCalCollapse" style="cursor: pointer; user-select: none;">
            <h6 class="text-primary fw-bold mb-0 d-flex align-items-center gap-2">
                <span>✈️ Saved Airspeed Calibrations (${calsList.length})</span>
            </h6>
            <button class="btn btn-sm btn-outline-secondary py-0 px-2 d-flex align-items-center gap-1" type="button" data-bs-toggle="collapse" data-bs-target="#airspeedCalCollapse" aria-expanded="${!wasCollapsed}" aria-controls="airspeedCalCollapse" title="Toggle saved calibrations">
                <i class="bi ${wasCollapsed ? 'bi-chevron-down' : 'bi-chevron-up'}" id="airspeedCalCollapseIcon"></i>
            </button>
        </div>
    `;

    let cardsHtml = '';
    calsList.forEach((item, index) => {
        const resObj = item.results || {};
        const engObj = item.engine_settings || {};
        const start = item.start_time;
        const end = item.end_time;

        const asErrorVal = resObj.airspeed_error_kts;
        const asErrorStr = asErrorVal !== undefined ? (asErrorVal >= 0 ? '+' : '') + asErrorVal + ' kts' : 'N/A';
        const errorColorClass = (asErrorVal !== undefined && asErrorVal >= 0) ? 'text-success' : 'text-danger';

        const corrCasStr = resObj.average_calibrated_airspeed_kts !== undefined ? resObj.average_calibrated_airspeed_kts + ' kts' : 'N/A';
        const uncorrTasStr = resObj.uncorrected_average_true_airspeed_kts !== undefined ? resObj.uncorrected_average_true_airspeed_kts + ' kts' : 'N/A';
        const corrTasStr = resObj.corrected_average_true_airspeed_kts !== undefined ? resObj.corrected_average_true_airspeed_kts + ' kts' : 'N/A';
        const daStr = resObj.density_altitude_ft !== undefined ? Number(resObj.density_altitude_ft).toLocaleString() + ' ft' : 'N/A';
        const magVarStr = resObj.magnetic_variation_deg !== undefined ? (resObj.magnetic_variation_deg >= 0 ? '+' : '') + resObj.magnetic_variation_deg + '°' : '0.0°';
        const hdgBiasStr = resObj.calibrated_heading_correction_deg !== undefined ? (resObj.calibrated_heading_correction_deg >= 0 ? '+' : '') + resObj.calibrated_heading_correction_deg + '°' : 'N/A';

        let windStr = 'N/A';
        if (resObj.wind_direction_deg !== undefined && resObj.wind_speed_kts !== undefined && resObj.wind_speed_kts > 0) {
            windStr = `${resObj.wind_direction_deg}° @ ${resObj.wind_speed_kts} kts`;
        }

        const mapStr = engObj.manifold_pressure_inhg !== null && engObj.manifold_pressure_inhg !== undefined ? engObj.manifold_pressure_inhg + ' inHg' : 'N/A';
        const rpmStr = engObj.rpm !== null && engObj.rpm !== undefined ? engObj.rpm : 'N/A';
        const ffStr = engObj.fuel_flow_gph !== null && engObj.fuel_flow_gph !== undefined ? engObj.fuel_flow_gph + ' gph' : 'N/A';
        const powerStr = engObj.percent_power !== null && engObj.percent_power !== undefined ? engObj.percent_power + ' %' : 'N/A';

        cardsHtml += `
            <div class="card mb-2 border-0 bg-white shadow-sm">
                <div class="card-body p-3">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <span class="badge bg-secondary">Calibration #${index + 1} (${formatMMSS(start)} - ${formatMMSS(end)})</span>
                        <button class="btn btn-sm btn-outline-danger py-0 px-2" onclick="event.stopPropagation(); deleteAirspeedCalibration(${item.id})" title="Delete Calibration">
                            &times; Delete
                        </button>
                    </div>
                    <div class="row g-2 mb-2 small">
                        <div class="col-6 col-md-3"><strong>Airspeed Error:</strong> <span class="${errorColorClass} fw-bold">${asErrorStr}</span></div>
                        <div class="col-6 col-md-3"><strong>Corrected CAS:</strong> ${corrCasStr}</div>
                        <div class="col-6 col-md-3"><strong>Uncorrected TAS:</strong> ${uncorrTasStr}</div>
                        <div class="col-6 col-md-3"><strong>Corrected TAS:</strong> ${corrTasStr}</div>
                    </div>
                    <div class="row g-2 mb-2 small">
                        <div class="col-6 col-md-3"><strong>Compass HDG Bias:</strong> ${hdgBiasStr}</div>
                        <div class="col-6 col-md-3"><strong>Mag Variation:</strong> ${magVarStr}</div>
                        <div class="col-6 col-md-3"><strong>Wind Vector:</strong> ${windStr}</div>
                        <div class="col-6 col-md-3"><strong>Density Alt:</strong> ${daStr}</div>
                    </div>
                    <div class="row g-2 small text-muted border-top pt-2 mt-1">
                        <div class="col-3"><strong>MAP:</strong> ${mapStr}</div>
                        <div class="col-3"><strong>RPM:</strong> ${rpmStr}</div>
                        <div class="col-3"><strong>Fuel Flow:</strong> ${ffStr}</div>
                        <div class="col-3"><strong>% Power:</strong> ${powerStr}</div>
                    </div>
                </div>
            </div>
        `;
    });

    block.innerHTML = `
        ${headerHtml}
        <div class="collapse ${wasCollapsed ? '' : 'show'} pt-2" id="airspeedCalCollapse">
            ${cardsHtml}
        </div>
    `;
    statsList.appendChild(block);

    const collapseEl = document.getElementById('airspeedCalCollapse');
    const collapseIcon = document.getElementById('airspeedCalCollapseIcon');
    if (collapseEl && collapseIcon) {
        collapseEl.addEventListener('show.bs.collapse', () => {
            collapseIcon.className = 'bi bi-chevron-up';
            window._airspeedCalCollapsed = false;
        });
        collapseEl.addEventListener('hide.bs.collapse', () => {
            collapseIcon.className = 'bi bi-chevron-down';
            window._airspeedCalCollapsed = true;
        });
    }
}

function deleteAirspeedCalibration(calId) {
    if (!confirm("Are you sure you want to delete this saved airspeed calibration from the database?")) return;
    fetch(`/api/delete_airspeed_calibration/${calId}`, { method: 'POST' })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                const rem = data.remaining_calibrations || [];
                window.lastSavedCalibrations = rem;
                const appState = getAppStateRef();
                if (appState && appState.currentFlightStats) {
                    appState.currentFlightStats.saved_calibrations = rem;
                }
                renderSavedAirspeedCalibrations(rem);
                renderModalSavedAirspeedCalibrations(rem);

                // If on multi-flight stats page, update local globalFlights state & re-render table
                const flights = window.globalFlights || window.allFlightStats;
                if (flights) {
                    for (let f of flights) {
                        if (f.saved_calibrations && f.saved_calibrations.some(c => c.id === calId)) {
                            f.saved_calibrations = f.saved_calibrations.filter(c => c.id !== calId);
                            f.has_calibration = f.saved_calibrations.length > 0;
                        }
                    }
                    if (window.filterAndRenderTable) window.filterAndRenderTable();
                    if (window.renderAirspeedCalsModalTable) window.renderAirspeedCalsModalTable();
                }
            } else {
                alert("Error deleting calibration: " + (data.error || "Unknown error"));
            }
        })
        .catch(err => {
            console.error("Delete calibration error:", err);
            alert("Error deleting calibration.");
        });
}


// --- INTERACTIVE AIRSPEED CALIBRATION MAP & CURSOR FOLLOW ---
function renderAsCalMap(data, startTime, endTime, forceRecenter = false) {
    const mapDiv = getAsCalElem('mapDiv');
    if (!mapDiv || !data) return;

    function getSeries(colNames) {
        if (!data) return [];
        const records = (typeof data === 'object' && data !== null && !Array.isArray(data) && (data.rawData || data.plot_data || data.data || data.dataframe))
            ? (data.rawData || data.plot_data || data.data || data.dataframe)
            : data;

        if (Array.isArray(records)) {
            for (const col of colNames) {
                if (records.length > 0 && col in records[0]) {
                    return records.map(row => row[col]);
                }
            }
        }
        if (typeof records === 'object' && records !== null) {
            for (const col of colNames) {
                if (records[col] && Array.isArray(records[col])) {
                    return records[col];
                }
            }
        }
        return [];
    }

    const sessionTimes = getSeries(['Session Time', 'session_time', 'x_sec']);
    const lats = getSeries(['Latitude (deg)', 'latitude', 'LAT', 'Lat']);
    const lons = getSeries(['Longitude (deg)', 'longitude', 'LON', 'Lon']);
    const alts = getSeries(['GPS Altitude (feet)', 'Pressure Altitude (ft)', 'altitude', 'press_alt', 'ALT']);
    const iass = getSeries(['Indicated Airspeed (knots)', 'ias', 'IAS']);
    const tass = getSeries(['Corrected TAS (knots)', 'True Airspeed (knots)', 'airspeed', 'tas', 'TAS']);
    const hdgs = getSeries(['Magnetic Heading (deg)', 'heading', 'hdg', 'HDG']);

    if (!lats.length || !lons.length) {
        mapDiv.innerHTML = '<div class="text-center text-muted p-4">No GPS coordinate track logged for this flight.</div>';
        return;
    }

    // Identify indices for selected maneuver segment & start/end markers
    const sTime = (startTime !== null && startTime !== undefined && startTime !== '') ? parseFloat(startTime) : null;
    const eTime = (endTime !== null && endTime !== undefined && endTime !== '') ? parseFloat(endTime) : null;

    function findClosestTimeIdx(targetTime) {
        if (targetTime === null || targetTime === undefined || isNaN(targetTime) || !sessionTimes.length) return null;
        let bestIdx = 0;
        let minDiff = Infinity;
        for (let i = 0; i < sessionTimes.length; i++) {
            const diff = Math.abs(parseFloat(sessionTimes[i]) - targetTime);
            if (diff < minDiff) {
                minDiff = diff;
                bestIdx = i;
            }
        }
        return bestIdx;
    }

    const startIdx = findClosestTimeIdx(sTime);
    const endIdx = findClosestTimeIdx(eTime);

    let segIndices = [];
    if (sTime !== null && eTime !== null && !isNaN(sTime) && !isNaN(eTime)) {
        for (let i = 0; i < sessionTimes.length; i++) {
            const t = parseFloat(sessionTimes[i]);
            if (t >= sTime && t <= eTime) {
                segIndices.push(i);
            }
        }
    }

    const segLats = segIndices.map(i => lats[i]);
    const segLons = segIndices.map(i => lons[i]);
    const segTimes = segIndices.map(i => sessionTimes[i]);

    // Build Start / End boundary markers (Green = Start, Red = End)
    const boundaryIndices = [];
    const boundaryColors = [];
    const boundaryTexts = [];
    if (startIdx !== null) {
        boundaryIndices.push(startIdx);
        boundaryColors.push('#198754');
        boundaryTexts.push(
            `<b>Start Maneuver</b><br>` +
            `Time: ${Math.round(sessionTimes[startIdx] || 0)}s<br>` +
            `Alt: ${Math.round(alts[startIdx] || 0).toLocaleString()} ft<br>` +
            `IAS: ${Math.round(iass[startIdx] || 0)} kt`
        );
    }
    if (endIdx !== null) {
        boundaryIndices.push(endIdx);
        boundaryColors.push('#dc3545');
        boundaryTexts.push(
            `<b>End Maneuver</b><br>` +
            `Time: ${Math.round(sessionTimes[endIdx] || 0)}s<br>` +
            `Alt: ${Math.round(alts[endIdx] || 0).toLocaleString()} ft<br>` +
            `IAS: ${Math.round(iass[endIdx] || 0)} kt`
        );
    }

    // Traces:
    // 0. Full Flight Path
    const fullPathTrace = {
        type: 'scattermapbox',
        mode: 'lines',
        lat: lats,
        lon: lons,
        customdata: sessionTimes.map((_, i) => i),
        line: { width: 3, color: '#6c757d' },
        name: 'Full Flight Track',
        hoverinfo: 'none'
    };

    // 1. Highlighted Maneuver Segment (Cyan line with Gold markers)
    const segmentTrace = {
        type: 'scattermapbox',
        mode: 'lines+markers',
        lat: segLats,
        lon: segLons,
        customdata: segIndices,
        line: { width: 6, color: '#00f0ff' },
        marker: { size: 7, color: '#ffc107' },
        name: 'Calibration Segment',
        text: segTimes.map((t, idx) => 
            `<b>Calibration Segment</b><br>` +
            `Time: ${Math.round(t)}s<br>` +
            `Alt: ${Math.round(alts[segIndices[idx]] || 0).toLocaleString()} ft<br>` +
            `IAS: ${Math.round(iass[segIndices[idx]] || 0)} kt`
        ),
        hoverinfo: 'text'
    };

    // 2. Start / End Selection Markers (Green = Start, Red = End)
    const boundaryTrace = {
        type: 'scattermapbox',
        mode: 'markers',
        lat: boundaryIndices.map(i => lats[i]),
        lon: boundaryIndices.map(i => lons[i]),
        customdata: boundaryIndices,
        marker: {
            size: 13,
            color: boundaryColors.length ? boundaryColors : '#198754'
        },
        name: 'Start / End Markers',
        text: boundaryTexts,
        hoverinfo: 'text'
    };

    // 3. Cursor Follow Marker (Pulsing Red Circle)
    let initIdx = 0;
    if (window._lastAsCalCursorIdx !== null && window._lastAsCalCursorIdx !== undefined && window._lastAsCalCursorIdx >= 0 && window._lastAsCalCursorIdx < lats.length) {
        initIdx = window._lastAsCalCursorIdx;
    } else if (startIdx !== null) {
        initIdx = startIdx;
    } else if (segIndices.length > 0) {
        initIdx = segIndices[0];
    }

    const cursorTrace = {
        type: 'scattermapbox',
        mode: 'markers',
        lat: [lats[initIdx]],
        lon: [lons[initIdx]],
        customdata: [initIdx],
        marker: { size: 16, color: '#ff0055', symbol: 'circle', opacity: 0.9 },
        name: 'Position Cursor',
        hoverinfo: 'text',
        text: [
            `<b>Position Cursor</b><br>` +
            `Time: ${Math.round(sessionTimes[initIdx] || 0)}s<br>` +
            `Alt: ${Math.round(alts[initIdx] || 0).toLocaleString()} ft<br>` +
            `IAS: ${Math.round(iass[initIdx] || 0)} kt | TAS: ${Math.round(tass[initIdx] || 0)} kt<br>`
        ]
    };

    const isMapInitialized = mapDiv.data && mapDiv.data.length > 0;

    let centerLat, centerLon, fitZoom;

    if (isMapInitialized && !forceRecenter && mapDiv.layout && mapDiv.layout.mapbox) {
        centerLat = mapDiv.layout.mapbox.center ? mapDiv.layout.mapbox.center.lat : 0;
        centerLon = mapDiv.layout.mapbox.center ? mapDiv.layout.mapbox.center.lon : 0;
        fitZoom = mapDiv.layout.mapbox.zoom || 11;
    } else {
        const calcLats = segLats.length > 1 ? segLats : lats;
        const calcLons = segLons.length > 1 ? segLons : lons;

        let minLat = Infinity, maxLat = -Infinity, minLon = Infinity, maxLon = -Infinity;
        for (let i = 0; i < calcLats.length; i++) {
            const la = Number(calcLats[i]);
            const lo = Number(calcLons[i]);
            if (isFinite(la) && isFinite(lo) && (la !== 0 || lo !== 0)) {
                if (la < minLat) minLat = la;
                if (la > maxLat) maxLat = la;
                if (lo < minLon) minLon = lo;
                if (lo > maxLon) maxLon = lo;
            }
        }
        if (!isFinite(minLat)) {
            minLat = 0; maxLat = 0; minLon = 0; maxLon = 0;
        }

        centerLat = (minLat + maxLat) / 2;
        centerLon = (minLon + maxLon) / 2;
        const maxDiff = Math.max(Math.abs(maxLat - minLat), Math.abs(maxLon - minLon));

        fitZoom = 11;
        if (maxDiff > 0.0001) {
            fitZoom = Math.min(13, Math.max(8, Math.log2(360 / maxDiff) - 2.8));
        }
    }

    const layout = {
        mapbox: {
            style: 'open-street-map',
            center: { lat: centerLat, lon: centerLon },
            zoom: fitZoom
        },
        hovermode: 'closest',
        hoverdistance: 30,
        margin: { l: 0, r: 0, t: 0, b: 0 },
        showlegend: false,
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent'
    };

    const mapBadge = document.getElementById('asCalMapBadge');
    if (mapBadge) {
        if (sTime !== null && eTime !== null && !isNaN(sTime) && !isNaN(eTime)) {
            mapBadge.textContent = `${Math.round(sTime)}s – ${Math.round(eTime)}s`;
            mapBadge.className = 'badge bg-info text-dark extra-small';
        } else if (sTime !== null && !isNaN(sTime)) {
            mapBadge.textContent = `Start: ${Math.round(sTime)}s — Click End`;
            mapBadge.className = 'badge bg-success text-white extra-small';
        } else {
            mapBadge.textContent = 'Click 2 points to set range';
            mapBadge.className = 'badge bg-info text-dark extra-small';
        }
    }

    Plotly.react(mapDiv, [fullPathTrace, segmentTrace, boundaryTrace, cursorTrace], layout, { responsive: true })
        .then(() => {
            if (typeof mapDiv.removeAllListeners === 'function') {
                mapDiv.removeAllListeners('plotly_hover');
                mapDiv.removeAllListeners('plotly_unhover');
                mapDiv.removeAllListeners('plotly_click');
            }

            // Enable hover sync on map
            mapDiv.on('plotly_hover', (eventData) => {
                if (!eventData || !eventData.points || !eventData.points.length) return;
                window._lastAsCalMapHoverTime = Date.now();
                const pt = eventData.points[0];
                // Ignore hover events on the cursor marker itself to prevent hover loops/glitches
                if (pt.curveNumber === 3 || (pt.data && pt.data.name === 'Position Cursor')) return;
                const ptIdx = (pt.customdata !== undefined && pt.customdata !== null) ? pt.customdata : pt.pointIndex;
                updateAsCalMapCursor(data, ptIdx);
            });

            mapDiv.on('plotly_unhover', () => {
                window._lastAsCalMapHoverTime = 0;
            });

            // Enable 2-click start/end selection directly on the map
            mapDiv.on('plotly_click', (eventData) => {
                if (!eventData || !eventData.points || !eventData.points.length) return;
                const pt = eventData.points[0];
                let ptIdx = (pt.customdata !== undefined && pt.customdata !== null) ? pt.customdata : null;
                if (ptIdx === null) {
                    if ((pt.curveNumber === 3 || (pt.data && pt.data.name === 'Position Cursor')) && window._lastAsCalCursorIdx !== null && window._lastAsCalCursorIdx !== undefined) {
                        ptIdx = window._lastAsCalCursorIdx;
                    } else if (pt.curveNumber === 0) {
                        ptIdx = pt.pointIndex;
                    }
                }
                if (ptIdx !== null && ptIdx >= 0 && ptIdx < sessionTimes.length) {
                    window._lastAsCalMapClickTime = Date.now();
                    window._lastAsCalCursorIdx = ptIdx;
                    handleAsCalPointSelection(sessionTimes[ptIdx], data);
                }
            });

            // Fallback click handler in case Plotly.restyle on hover interrupts Mapbox's internal plotly_click event
            mapDiv._asCalSessionTimes = sessionTimes;
            mapDiv._asCalData = data;
            if (!mapDiv._hasAsCalPointerFallback) {
                mapDiv._hasAsCalPointerFallback = true;
                let downPos = null;
                mapDiv.addEventListener('pointerdown', (e) => {
                    if (e.button !== 0 || (e.target && e.target.closest && e.target.closest('.modebar'))) {
                        downPos = null;
                        return;
                    }
                    downPos = { x: e.clientX, y: e.clientY, t: Date.now() };
                });
                mapDiv.addEventListener('pointerup', (e) => {
                    if (!downPos) return;
                    const dx = e.clientX - downPos.x;
                    const dy = e.clientY - downPos.y;
                    const dt = Date.now() - downPos.t;
                    downPos = null;
                    if (Math.hypot(dx, dy) < 6 && dt < 450) {
                        setTimeout(() => {
                            const sincePlotlyClick = Date.now() - (window._lastAsCalMapClickTime || 0);
                            const sinceHover = Date.now() - (window._lastAsCalMapHoverTime || 0);
                            const cursorIdx = window._lastAsCalCursorIdx;
                            const times = mapDiv._asCalSessionTimes || [];
                            if (sincePlotlyClick > 150 && sinceHover < 1500 && cursorIdx !== null && cursorIdx !== undefined && cursorIdx >= 0 && cursorIdx < times.length) {
                                window._lastAsCalMapClickTime = Date.now();
                                handleAsCalPointSelection(times[cursorIdx], mapDiv._asCalData);
                            }
                        }, 60);
                    }
                });
            }
        })
        .catch(e => console.debug("Map style loading notice:", e));
}

function updateAsCalMapCursor(data, pointIdx) {
    if (!data) return;
    if (window._lastAsCalCursorIdx === pointIdx) return;
    window._lastAsCalCursorIdx = pointIdx;

    function getSeries(colNames) {
        if (!data) return [];
        const records = (typeof data === 'object' && data !== null && !Array.isArray(data) && (data.rawData || data.plot_data || data.data || data.dataframe))
            ? (data.rawData || data.plot_data || data.data || data.dataframe)
            : data;

        if (Array.isArray(records)) {
            for (const col of colNames) {
                if (records.length > 0 && col in records[0]) return records.map(row => row[col]);
            }
        }
        if (typeof records === 'object' && records !== null) {
            for (const col of colNames) {
                if (records[col] && Array.isArray(records[col])) return records[col];
            }
        }
        return [];
    }

    const sessionTimes = getSeries(['Session Time', 'session_time', 'x_sec']);
    const lats = getSeries(['Latitude (deg)', 'latitude', 'LAT', 'Lat']);
    const lons = getSeries(['Longitude (deg)', 'longitude', 'LON', 'Lon']);
    const alts = getSeries(['GPS Altitude (feet)', 'Pressure Altitude (ft)', 'altitude', 'press_alt', 'ALT']);
    const iass = getSeries(['Indicated Airspeed (knots)', 'ias', 'IAS']);
    const tass = getSeries(['Corrected TAS (knots)', 'True Airspeed (knots)', 'airspeed', 'tas', 'TAS']);
    const hdgs = getSeries(['Magnetic Heading (deg)', 'heading', 'hdg', 'HDG']);

    if (!lats.length || pointIdx < 0 || pointIdx >= lats.length) return;

    const lat = lats[pointIdx];
    const lon = lons[pointIdx];
    const t = sessionTimes[pointIdx];
    const alt = alts[pointIdx];
    const ias = iass[pointIdx];
    const tas = tass[pointIdx];
    const hdg = hdgs[pointIdx];

    // Restyle cursor marker on Plotly map (trace index 3)
    const mapDiv = getAsCalElem('mapDiv');
    if (mapDiv && mapDiv.data && mapDiv.data.length >= 4) {
        Plotly.restyle(mapDiv, {
            lat: [[lat]],
            lon: [[lon]],
            customdata: [[pointIdx]],
            text: [[
                `<b>Position Cursor</b><br>` +
                `Time: ${Math.round(t || 0)}s<br>` +
                `Alt: ${Math.round(alt || 0).toLocaleString()} ft<br>` +
                `IAS: ${Math.round(ias || 0)} kt | TAS: ${Math.round(tas || 0)} kt<br>`
            ]]
        }, [3]).catch(e => console.debug("Map cursor update notice:", e));
    }
}


function formatMMSS(seconds) {
    if (seconds === null || seconds === undefined || isNaN(seconds)) return "--:--";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
}
