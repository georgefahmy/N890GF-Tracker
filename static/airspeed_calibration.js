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
            if (timeGraph && timeGraph.data) Plotly.Plots.resize(timeGraph);
        });
    }
});

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

    const modal = new bootstrap.Modal(modalEl);
    modal.show();

    // Sync modal dropdown with main select choices safely
    const mainSelect = document.getElementById('savedFlights');
    const calSelect = document.getElementById('asCalSavedFlights');

    let activeFile = null;
    if (window.AppState && AppState.file && AppState.file.currentName) {
        activeFile = AppState.file.currentName;
    } else if (mainSelect && mainSelect.value) {
        activeFile = mainSelect.value;
    }

    if (mainSelect && calSelect && mainSelect !== calSelect) {
        calSelect.innerHTML = mainSelect.innerHTML;
        if (activeFile) {
            calSelect.value = activeFile;
        }
    }

    loadAirspeedCalFlight();
}

function loadAirspeedCalFlight() {
    let selectedFile = null;
    const calSel = document.getElementById('asCalSavedFlights');
    const mainSel = document.getElementById('savedFlights');

    if (calSel && calSel.value && calSel.value !== "") {
        selectedFile = calSel.value;
    } else if (mainSel && mainSel.value && mainSel.value !== "") {
        selectedFile = mainSel.value;
    } else if (window.AppState && AppState.file && AppState.file.currentName) {
        selectedFile = AppState.file.currentName;
    }

    if (!selectedFile) {
        const instruction = getAsCalElem('instruction');
        if (instruction) instruction.innerText = 'No flight loaded. Select a flight from the dropdown above.';
        return;
    }

    // Check if we already have this flight loaded in AppState
    if (window.AppState && AppState.file && AppState.file.currentName === selectedFile && (AppState.rawData || (AppState.lastAnalysisResponse && AppState.lastAnalysisResponse.rawData))) {
        asCalCurrentData = AppState.rawData || (AppState.lastAnalysisResponse && AppState.lastAnalysisResponse.rawData);
        renderAirspeedCalPlot(asCalCurrentData);
        return;
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
        asCalCurrentData = data.rawData || data.data || data;
        renderAirspeedCalPlot(asCalCurrentData);
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

        // Case 1: Array of record objects [{ col1: v1, col2: v2 }, ...]
        if (Array.isArray(data)) {
            for (const col of colNames) {
                if (data.length > 0 && col in data[0]) {
                    return data.map(row => row[col]);
                }
            }
        }

        // Case 2: Column dictionary { col1: [v1, v2], col2: [...] }
        if (typeof data === 'object') {
            for (const col of colNames) {
                if (data[col] && Array.isArray(data[col])) {
                    return data[col];
                }
            }
        }

        return [];
    }

    const sessionTimes = getSeries(['Session Time', 'session_time']);
    const ias = getSeries(['Indicated Airspeed (knots)', 'ias', 'IAS']);
    const gs = getSeries(['Ground Speed (knots)', 'gps_gs', 'GS']);
    const hdg = getSeries(['Magnetic Heading (deg)', 'hdg', 'HDG']);
    const alt = getSeries(['Pressure Altitude (ft)', 'press_alt', 'ALT']);

    if (!sessionTimes.length || !ias.length) {
        if (instruction) instruction.innerText = "Airspeed or time data missing in this log file.";
        return;
    }

    if (instruction) {
        instruction.innerText = "Click 2 points on the graph to select your 360° maneuver window (Green line = Start, Red line = End).";
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
        title: { text: 'Airspeed Calibration Maneuver Selection', font: { size: 14 } },
        xaxis: { title: 'Session Time (seconds)' },
        yaxis: { title: 'Airspeed / Groundspeed (kts)', side: 'left' },
        yaxis2: { title: 'Magnetic Heading (°)', overlaying: 'y', side: 'right', range: [0, 360] },
        yaxis3: { title: 'Altitude (ft)', overlaying: 'y', visible: false },
        margin: { l: 50, r: 50, t: 40, b: 40 },
        legend: { orientation: 'h', x: 0, y: 1.12 },
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

        if (asCalSelectionState.start === null || asCalSelectionState.end !== null) {
            // First click
            asCalSelectionState.start = x;
            asCalSelectionState.end = null;
        } else {
            // Second click
            asCalSelectionState.end = x;
            if (asCalSelectionState.end < asCalSelectionState.start) {
                const tmp = asCalSelectionState.start;
                asCalSelectionState.start = asCalSelectionState.end;
                asCalSelectionState.end = tmp;
            }
        }

        // Sync input boxes
        const startInput = getAsCalElem('calStartTime') || getAsCalElem('startTime');
        const endInput = getAsCalElem('calEndTime') || getAsCalElem('endTime');
        if (startInput && asCalSelectionState.start !== null) {
            startInput.value = Math.round(asCalSelectionState.start * 10) / 10;
        }
        if (endInput && asCalSelectionState.end !== null) {
            endInput.value = Math.round(asCalSelectionState.end * 10) / 10;
        }

        drawAsCalShapes();

        // Update map maneuver segment highlight
        renderAsCalMap(data, asCalSelectionState.start, asCalSelectionState.end);

        // If both start & end are set, run calibration automatically
        if (asCalSelectionState.start !== null && asCalSelectionState.end !== null) {
            submitAirspeedCalibration(asCalSelectionState.start, asCalSelectionState.end);
        }
    });
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

    if (calSel && calSel.value && calSel.value !== "") {
        selectedFile = calSel.value;
    } else if (mainSel && mainSel.value && mainSel.value !== "") {
        selectedFile = mainSel.value;
    } else if (window.AppState && AppState.file && AppState.file.currentName) {
        selectedFile = AppState.file.currentName;
    }

    if (!selectedFile) {
        if (instruction) instruction.innerText = "No flight selected.";
        return;
    }

    // Store globally for flight map highlight
    if (window.AppState && window.AppState.calibration) {
        AppState.calibration.start = start;
        AppState.calibration.end = end;
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
    .then(res => res.json())
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
            window.lastSavedCalibrations = data.saved_calibrations;
            if (window.AppState && AppState.currentFlightStats) {
                AppState.currentFlightStats.saved_calibrations = data.saved_calibrations;
            }
            renderSavedAirspeedCalibrations(data.saved_calibrations);
        }

        if (window.renderMap && window.AppState && AppState.map && AppState.map.lastRenderData) {
            renderMap(AppState.map.lastRenderData);
        }
    })
    .catch(err => {
        console.error(err);
        if (instruction) instruction.innerText = "Network error during calibration.";
    });
}

function renderSavedAirspeedCalibrations(calsList) {
    const statsList = document.getElementById('statsList');
    if (!statsList) return;

    const statsCard = document.getElementById('statsCard');
    const statsPlaceholder = document.getElementById('statsPlaceholder');
    if (statsCard) statsCard.classList.remove('d-none');
    if (statsPlaceholder) statsPlaceholder.classList.add('d-none');

    let existing = document.getElementById('airspeed-summary-block');
    if (existing) existing.remove();

    if (!calsList || calsList.length === 0) return;

    const block = document.createElement('div');
    block.id = 'airspeed-summary-block';
    block.className = 'col-12 mt-3 p-3 border rounded shadow-sm bg-light';

    let cardsHtml = `<div class="d-flex justify-content-between align-items-center mb-2">
        <h6 class="text-primary fw-bold mb-0">✈️ Saved Airspeed Calibrations (${calsList.length})</h6>
    </div>`;

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
                        <button class="btn btn-sm btn-outline-danger py-0 px-2" onclick="deleteAirspeedCalibration(${item.id})" title="Delete Calibration">
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

    block.innerHTML = cardsHtml;
    statsList.appendChild(block);
}

function deleteAirspeedCalibration(calId) {
    if (!confirm("Are you sure you want to delete this saved airspeed calibration from the database?")) return;
    fetch(`/api/delete_airspeed_calibration/${calId}`, { method: 'POST' })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                const rem = data.remaining_calibrations || [];
                window.lastSavedCalibrations = rem;
                if (window.AppState && AppState.currentFlightStats) {
                    AppState.currentFlightStats.saved_calibrations = rem;
                }
                renderSavedAirspeedCalibrations(rem);

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
function renderAsCalMap(data, startTime, endTime) {
    const mapDiv = getAsCalElem('mapDiv');
    if (!mapDiv || !data) return;

    function getSeries(colNames) {
        if (!data) return [];
        if (Array.isArray(data)) {
            for (const col of colNames) {
                if (data.length > 0 && col in data[0]) {
                    return data.map(row => row[col]);
                }
            }
        }
        if (typeof data === 'object') {
            for (const col of colNames) {
                if (data[col] && Array.isArray(data[col])) {
                    return data[col];
                }
            }
        }
        return [];
    }

    const sessionTimes = getSeries(['Session Time', 'session_time']);
    const lats = getSeries(['Latitude (deg)', 'latitude', 'LAT', 'Lat']);
    const lons = getSeries(['Longitude (deg)', 'longitude', 'LON', 'Lon']);
    const alts = getSeries(['GPS Altitude (feet)', 'Pressure Altitude (ft)', 'press_alt', 'ALT']);
    const iass = getSeries(['Indicated Airspeed (knots)', 'ias', 'IAS']);
    const tass = getSeries(['Corrected TAS (knots)', 'True Airspeed (knots)', 'tas', 'TAS']);
    const hdgs = getSeries(['Magnetic Heading (deg)', 'hdg', 'HDG']);

    if (!lats.length || !lons.length) {
        mapDiv.innerHTML = '<div class="text-center text-muted p-4">No GPS coordinate track logged for this flight.</div>';
        return;
    }

    // Identify indices for selected maneuver segment
    const sTime = (startTime !== null && startTime !== undefined) ? parseFloat(startTime) : null;
    const eTime = (endTime !== null && endTime !== undefined) ? parseFloat(endTime) : null;

    let segIndices = [];
    if (sTime !== null && eTime !== null && !isNaN(sTime) && !isNaN(eTime)) {
        for (let i = 0; i < sessionTimes.length; i++) {
            const t = parseFloat(sessionTimes[i]);
            if (t >= sTime && t <= eTime) {
                segIndices.push(i);
            }
        }
    }
    if (segIndices.length === 0) segIndices = [0];

    const segLats = segIndices.map(i => lats[i]);
    const segLons = segIndices.map(i => lons[i]);
    const segTimes = segIndices.map(i => sessionTimes[i]);

    // Traces:
    // 1. Full Flight Path
    const fullPathTrace = {
        type: 'scattermapbox',
        mode: 'lines',
        lat: lats,
        lon: lons,
        line: { width: 3, color: '#6c757d' },
        name: 'Full Flight Track',
        hoverinfo: 'none'
    };

    // 2. Highlighted Maneuver Segment (Cyan line with Gold markers)
    const segmentTrace = {
        type: 'scattermapbox',
        mode: 'lines+markers',
        lat: segLats,
        lon: segLons,
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

    // 3. Cursor Follow Marker (Pulsing Red Circle)
    const initIdx = segIndices[0] || 0;
    const cursorTrace = {
        type: 'scattermapbox',
        mode: 'markers',
        lat: [lats[initIdx]],
        lon: [lons[initIdx]],
        marker: { size: 16, color: '#ff0055', symbol: 'circle', opacity: 0.9 },
        name: 'Position Cursor',
        hoverinfo: 'text',
        text: [`<b>Position Cursor</b><br>Time: ${Math.round(sessionTimes[initIdx] || 0)}s`]
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

        const minLat = Math.min(...calcLats);
        const maxLat = Math.max(...calcLats);
        const minLon = Math.min(...calcLons);
        const maxLon = Math.max(...calcLons);

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
        margin: { l: 0, r: 0, t: 0, b: 0 },
        showlegend: false,
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent'
    };

    Plotly.react(mapDiv, [fullPathTrace, segmentTrace, cursorTrace], layout, { responsive: true });

    if (!isMapInitialized) {
        // Enable hover sync from map to time graph
        mapDiv.on('plotly_hover', (eventData) => {
            if (!eventData || !eventData.points || !eventData.points.length) return;
            const pt = eventData.points[0];
            // Ignore hover events on the cursor marker itself to prevent hover loops/glitches
            if (pt.curveNumber === 2) return;
            const ptIdx = pt.pointIndex;
            updateAsCalMapCursor(data, ptIdx);
        });
    }

    updateAsCalMapCursor(data, initIdx);
}

function updateAsCalMapCursor(data, pointIdx) {
    if (!data) return;
    if (window._lastAsCalCursorIdx === pointIdx) return;
    window._lastAsCalCursorIdx = pointIdx;

    function getSeries(colNames) {
        if (Array.isArray(data)) {
            for (const col of colNames) {
                if (data.length > 0 && col in data[0]) return data.map(row => row[col]);
                }
        }
        if (typeof data === 'object') {
            for (const col of colNames) {
                if (data[col] && Array.isArray(data[col])) return data[col];
            }
        }
        return [];
    }

    const sessionTimes = getSeries(['Session Time', 'session_time']);
    const lats = getSeries(['Latitude (deg)', 'latitude', 'LAT', 'Lat']);
    const lons = getSeries(['Longitude (deg)', 'longitude', 'LON', 'Lon']);
    const alts = getSeries(['GPS Altitude (feet)', 'Pressure Altitude (ft)', 'press_alt', 'ALT']);
    const iass = getSeries(['Indicated Airspeed (knots)', 'ias', 'IAS']);
    const tass = getSeries(['Corrected TAS (knots)', 'True Airspeed (knots)', 'tas', 'TAS']);
    const hdgs = getSeries(['Magnetic Heading (deg)', 'hdg', 'HDG']);

    if (!lats.length || pointIdx < 0 || pointIdx >= lats.length) return;

    const lat = lats[pointIdx];
    const lon = lons[pointIdx];
    const t = sessionTimes[pointIdx];
    const alt = alts[pointIdx];
    const ias = iass[pointIdx];
    const tas = tass[pointIdx];
    const hdg = hdgs[pointIdx];

    // Restyle cursor marker on Plotly map
    const mapDiv = getAsCalElem('mapDiv');
    if (mapDiv && mapDiv.data && mapDiv.data.length >= 3) {
        Plotly.restyle(mapDiv, {
            lat: [[lat]],
            lon: [[lon]],
            text: [[
                `<b>Position Cursor</b><br>` +
                `Time: ${Math.round(t || 0)}s<br>` +
                `Alt: ${Math.round(alt || 0).toLocaleString()} ft<br>` +
                `IAS: ${Math.round(ias || 0)} kt | TAS: ${Math.round(tas || 0)} kt<br>`
            ]]
        }, [2]).catch(e => console.debug("Map cursor update notice:", e));
    }
}


function formatMMSS(seconds) {
    if (seconds === null || seconds === undefined || isNaN(seconds)) return "--:--";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
}
