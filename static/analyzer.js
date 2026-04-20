

// Global State
let currentSavedFilename = "";
let masterSignalsList = [];
let plotIdCounter = 0;
let plotFilters = {}; // { plotId: [filters] }
let xyFilters = [];
let xyOverlay = false;
let followAircraft = true;
let lastMapRenderData = null;
const STORAGE_KEY = 'analyzer_selected_flight';

// Calibration highlight globals
let calStartTimeGlobal = null;
let calEndTimeGlobal = null;

let mapColorMode = 'altitude';
let playbackTimer = null;
let playbackIndex = 0;
let playbackSpeed = 1;

// --- 3D WORLD DATA ---
window._worldX = [];
window._worldY = [];
window._worldZ = [];

// --- MAP COLOR SCALE CONFIG (easy tuning point) ---
const COLOR_SCALES = {
    altitude: 'Rainbow',
    airspeed: 'Jet',
    groundspeed: 'Rainbow',
    vertical_speed: 'RdYlBu'
};

const COLOR_LABELS = {
    altitude: 'GPS Alt (ft)',
    airspeed: 'TAS (kt)',
    groundspeed: 'GS (kt)',
    vertical_speed: 'VS (fpm)'
};

function toggleFollowAircraft(state) {
    followAircraft = state;
}

function toggleXYTab() {
    const tab = document.getElementById('xyTab');
    tab.classList.toggle('d-none');
    populateXYDropdowns();
}

function populateXYDropdowns() {
    const xSelect = document.getElementById('xyXSelect');
    const ySelect = document.getElementById('xyYSelect');

    if (!xSelect || masterSignalsList.length === 0) return;

    const unitF = document.getElementById('unitF').checked;
    const hideString = unitF ? "(deg C)" : "(deg F)";

    // Apply same filtering logic as main plots
    const filteredSignals = masterSignalsList.filter(sig => {
        if (sig === "CHT" || sig === "EGT") return true;
        return !sig.includes(hideString);
    });

    let optionsHtml = '';
    filteredSignals.forEach(sig => {
        optionsHtml += `<option value="${sig}">${sig}</option>`;
    });

    const currentX = xSelect.value;
    const currentY = ySelect.value;

    xSelect.innerHTML = optionsHtml;
    ySelect.innerHTML = optionsHtml;

    // Restore previous selections if possible
    if (filteredSignals.includes(currentX)) {
        xSelect.value = currentX;
    } else {
        xSelect.value = filteredSignals[0];
    }

    if (filteredSignals.includes(currentY)) {
        ySelect.value = currentY;
    } else {
        ySelect.value = filteredSignals.length > 1 ? filteredSignals[1] : filteredSignals[0];
    }
    // Populate XY filter dropdown
    const xySelect = document.getElementById('xyFilterSignal');
    if (xySelect) {
        let html = '';
        filteredSignals.forEach(sig => {
            html += `<option value="${sig}">${sig}</option>`;
        });
        xySelect.innerHTML = html;
    }
}

// 1. Initialize: Fetch saved flights on page load
document.addEventListener('DOMContentLoaded', function() {
    fetch('/api/saved_flights')
        .then(res => res.json())
        .then(data => {
            const select = document.getElementById('savedFlights');

            // Sort flight list in reverse alphabetical order for easier browsing
            const sortedFiles = (data.files || []).slice().sort((a, b) => b.localeCompare(a));

            sortedFiles.forEach(f => {
                select.options.add(new Option(f, f));
            });

            // Restore previously selected flight from URL first, then LocalStorage
            const urlParams = new URLSearchParams(window.location.search);
            const urlFlight = urlParams.get('flight');
            const saved = urlFlight || localStorage.getItem(STORAGE_KEY);

            if (saved && sortedFiles.includes(saved)) {
                select.value = saved;

                // If it loaded from LocalStorage, push it to the URL so the link is immediately shareable
                if (!urlFlight) {
                    const newUrl = window.location.pathname + '?flight=' + encodeURIComponent(saved);
                    window.history.replaceState({ path: newUrl }, '', newUrl);
                }

                const formData = new FormData();
                formData.append('saved_filename', saved);
                loadSignals(formData);
            }
        });
});

// 2. Centralized function to request signals
function loadSignals(formData) {
    // Show temporary loading state
    document.getElementById('statsPlaceholder').innerHTML = '<div class="spinner-border text-primary spinner-border-sm"></div> Loading data...';

    fetch('/api/get_signals', { method: 'POST', body: formData })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            alert("Error: " + data.error);
            document.getElementById('statsPlaceholder').innerHTML = 'Error loading data.';
            return;
        }

        currentSavedFilename = data.saved_filename;
        if (data.saved_filename) {
            localStorage.setItem(STORAGE_KEY, data.saved_filename);
        }
        masterSignalsList = data.signals;

        // Hide placeholders, show relevant UI
        document.getElementById('statsPlaceholder').classList.add('d-none');
        document.getElementById('statsCard').classList.remove('d-none');
        document.getElementById('plotHeader').classList.remove('d-none');
        document.getElementById('addPlotBtn').classList.remove('d-none');

        // If no plots exist, create the first one
        if (plotIdCounter === 0) {
            addPlot();
        } else {
            // If plots already exist, update their dropdowns and re-trigger analysis
            updateAllPlots();
        }
    })
    .catch(err => {
        console.error(err);
        alert("Failed to read file signals.");
    });
}

// 3. Handle File Upload
document.getElementById('csvFile').addEventListener('change', function(e) {
    if (e.target.files.length === 0) return;

    // Clear the URL parameter since we are uploading a new, unsaved file
    window.history.pushState({ path: window.location.pathname }, '', window.location.pathname);

    document.getElementById('savedFlights').value = ""; // Reset dropdown
    localStorage.removeItem(STORAGE_KEY);
    const formData = new FormData();
    formData.append('file', e.target.files[0]);
    loadSignals(formData);
});

// 4. Handle Saved Flight Selection
document.getElementById('savedFlights').addEventListener('change', function(e) {
    if (!e.target.value) {
        // Clear URL if empty selection
        window.history.pushState({ path: window.location.pathname }, '', window.location.pathname);
        return;
    }

    // Update the URL dynamically
    const newUrl = window.location.pathname + '?flight=' + encodeURIComponent(e.target.value);
    window.history.pushState({ path: newUrl }, '', newUrl);

    localStorage.setItem(STORAGE_KEY, e.target.value);
    document.getElementById('csvFile').value = ""; // Reset file input
    const formData = new FormData();
    formData.append('saved_filename', e.target.value);
    loadSignals(formData);
});

// 5. Handle Unit Toggle Change
document.querySelectorAll('input[name="tempUnit"]').forEach(radio => {
    radio.addEventListener('change', () => {
        updateAllPlots();
        populateXYDropdowns();
    });
});

// 6. Plot Management Functions
function addPlot() {
    const plotId = plotIdCounter++;
    const container = document.getElementById('plotsContainer');

    const card = document.createElement('div');
    card.className = "card p-0 shadow-sm mb-4 plot-card border-1";
    card.id = `plotCard-${plotId}`;

    // Construct the HTML for the dynamic plot card
    card.innerHTML = `
        <div class="card-header border-bottom-0 pt-3 pb-0 px-4">
            <div class="row align-items-center g-2">
                <div class="col-md">
                    <label class="form-label text-primary fw-bold mb-1 small">Left Axis Signal</label>
                    <select class="form-select border-primary left-signal-select" data-plot-id="${plotId}"></select>
                </div>
                <div class="col-md">
                    <label class="form-label text-danger fw-bold mb-1 small">Right Axis Signal</label>
                    <select class="form-select border-danger right-signal-select" data-plot-id="${plotId}"></select>
                </div>
                <div class="col-md-auto mt-2 mt-md-0 d-flex justify-content-end flex-nowrap gap-1">
                    <label class="form-label text-primary fw-bold mb-1 small"> </label>
                    <button class="btn btn-outline-secondary btn-sm text-nowrap" id="filter-btn-${plotId}" onclick="togglePlotFilters(${plotId})">
                        Show Filters
                    </button>
                    ${plotId > 0 ? `<button class="btn btn-outline-secondary btn-sm text-nowrap" onclick="removePlot(${plotId})">
                        ✖
                    </button>` : ''}
                </div>
            </div>
        </div>
        <div class="card-body px-4 pb-4 pt-3">

            <div class="mb-3 p-2 border rounded filter-section d-none" id="filter-section-${plotId}">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <div class="small text-muted fw-bold" id="filter-label-${plotId}">
                        Filters
                    </div>
                </div>
                <div class="row g-2 align-items-end">
                    <div class="col-md-4">
                        <label class="form-label small">Filter Signal</label>
                        <select class="form-select form-select-sm filter-signal"></select>
                    </div>

                    <div class="col-md-2">
                        <label class="form-label small">Op</label>
                        <select class="form-select form-select-sm filter-op">
                            <option value=">">></option>
                            <option value="<"><</option>
                            <option value=">=">>=</option>
                            <option value="<="><=</option>
                            <option value="==">==</option>
                        </select>
                    </div>

                    <div class="col-md-3">
                        <label class="form-label small">Value</label>
                        <input type="number" class="form-control form-control-sm filter-value">
                    </div>

                    <div class="col-md-3">
                        <button class="btn btn-primary btn-sm w-100 add-filter-btn">Add Filter</button>
                    </div>
                </div>

                <div class="mt-2">
                    <div class="small text-muted">Active Filters</div>
                    <ul class="list-group mt-1 filter-list"></ul>
                    <button class="btn btn-outline-danger btn-sm mt-2 clear-filter-btn">
                        Clear Filters
                    </button>
                </div>
            </div>

            <div class="graph-wrapper position-relative w-100" style="height: 450px;">
                <div id="loader-${plotId}" class="plot-loader position-absolute top-50 start-50 translate-middle d-none text-center p-3 shadow-sm border">
                    <div class="spinner-border text-primary" role="status"></div>
                    <div class="mt-2 text-muted small">Loading Plot...</div>
                </div>
                <div id="flightGraph-${plotId}" class="w-100 h-100 plotly-graph"></div>
            </div>
        </div>
    `;

    container.appendChild(card);

    const cardEl = document.getElementById(`plotCard-${plotId}`);

    const signalSelect = cardEl.querySelector('.filter-signal');
    const unitF = document.getElementById('unitF').checked;
    const hideString = unitF ? "(deg C)" : "(deg F)";

    const filteredSignals = masterSignalsList.filter(sig => {
        if (sig === "CHT" || sig === "EGT") return true;
        return !sig.includes(hideString);
    });

    signalSelect.innerHTML = filteredSignals.map(s => `<option value="${s}">${s}</option>`).join('');

    // Add Filter
    cardEl.querySelector('.add-filter-btn').onclick = () => {
        const signal = cardEl.querySelector('.filter-signal').value;
        const op = cardEl.querySelector('.filter-op').value;
        const value = parseFloat(cardEl.querySelector('.filter-value').value);

        if (isNaN(value)) return;

        if (!plotFilters[plotId]) plotFilters[plotId] = [];
        plotFilters[plotId].push({ signal, op, value });

        renderPlotFilters(plotId);
        triggerAnalysis(plotId);
    };

    // Clear Filters
    cardEl.querySelector('.clear-filter-btn').onclick = () => {
        plotFilters[plotId] = [];
        renderPlotFilters(plotId);
        triggerAnalysis(plotId);
    };

    // Attach Event Listeners to the new dropdowns
    card.querySelector('.left-signal-select').addEventListener('change', () => triggerAnalysis(plotId));
    card.querySelector('.right-signal-select').addEventListener('change', () => triggerAnalysis(plotId));

    // Populate dropdowns and trigger the initial graph render
    populateDropdownsForPlot(plotId);
    if (currentSavedFilename) triggerAnalysis(plotId);
    renderPlotFilters(plotId);
}

function removePlot(plotId) {
    const card = document.getElementById(`plotCard-${plotId}`);
    if (card) card.remove();
}

function updateAllPlots() {
    document.querySelectorAll('.plot-card').forEach(card => {
        const id = parseInt(card.id.split('-')[1]);
        populateDropdownsForPlot(id);
        triggerAnalysis(id);
    });
}

function populateDropdownsForPlot(plotId) {
    if (masterSignalsList.length === 0) return;

    const unitF = document.getElementById('unitF').checked;
    const hideString = unitF ? "(deg C)" : "(deg F)";

    const leftSelect = document.querySelector(`.left-signal-select[data-plot-id="${plotId}"]`);
    const rightSelect = document.querySelector(`.right-signal-select[data-plot-id="${plotId}"]`);

    const currentLeft = leftSelect.value;
    const currentRight = rightSelect.value;

    let optionsHtml = '';

    // Filter out the wrong temperature unit
    const filteredSignals = masterSignalsList.filter(sig => {
        if (sig === "CHT" || sig === "EGT") return true;
        return !sig.includes(hideString);
    });

    filteredSignals.forEach(sig => {
        optionsHtml += `<option value="${sig}">${sig}</option>`;
    });

    leftSelect.innerHTML = optionsHtml;
    rightSelect.innerHTML = optionsHtml;

    // Restore previous selections, or apply intelligent defaults based on the plot number
    if (filteredSignals.includes(currentLeft)) {
        leftSelect.value = currentLeft;
    } else if (plotId === 0 && filteredSignals.includes("CHT")) {
        leftSelect.value = "CHT";
    } else {
        leftSelect.value = filteredSignals[0];
    }

    if (filteredSignals.includes(currentRight)) {
        rightSelect.value = currentRight;
    } else if (plotId === 0 && filteredSignals.includes("EGT")) {
        rightSelect.value = "EGT";
    } else {
        rightSelect.value = filteredSignals.length > 1 ? filteredSignals[1] : filteredSignals[0];
    }
}

// --- GLOBAL CROSSHAIR SYNC ---
function updateCrosshairs(xVal) {
    window._crosshairX = xVal;

    const plots = document.querySelectorAll('[id^="flightGraph-"]');

    plots.forEach(div => {
        if (!div) return;

        const layoutUpdate = {
            shapes: [
                {
                    type: 'line',
                    x0: xVal,
                    x1: xVal,
                    y0: 0,
                    y1: 1,
                    xref: 'x',
                    yref: 'paper',
                    line: {
                        color: 'rgba(0,0,0,0.35)',
                        width: 1,
                        dash: 'dot'
                    }
                }
            ]
        };

        Plotly.relayout(div, layoutUpdate);
    });
}

// --- GLOBAL TOOLTIP SYNC (CROSS-PLOT HOVER) ---
function updateTooltips(xVal) {
    const plots = document.querySelectorAll('[id^="flightGraph-"]');

    plots.forEach(div => {
        try {
            if (!div || !div.data) return;

            Plotly.Fx.hover(div, {
                xval: xVal
            }, ['xy']);
        } catch (e) {
            // ignore
        }
    });
}

// 7. Core Analysis & Plotting Function
function triggerAnalysis(plotId) {
    if (!currentSavedFilename) return;

    const leftSignal = document.querySelector(`.left-signal-select[data-plot-id="${plotId}"]`).value;
    const rightSignal = document.querySelector(`.right-signal-select[data-plot-id="${plotId}"]`).value;
    const tempUnit = document.getElementById('unitF').checked ? 'F' : 'C';

    const loader = document.getElementById(`loader-${plotId}`);
    loader.classList.remove('d-none');

    const formData = new FormData();
    formData.append('saved_filename', currentSavedFilename);
    formData.append('left_signal', leftSignal);
    formData.append('right_signal', rightSignal);
    formData.append('temp_unit', tempUnit);
    const filters = plotFilters[plotId] || [];
    formData.append('filters', JSON.stringify(filters));

    fetch('/api/analyze_flight', { method: 'POST', body: formData })
    .then(response => response.json())
    .then(data => {
        loader.classList.add('d-none');

        // Store plot data globally for cursor sync
        window.currentPlotData = data.plot_data;

        if (data.error) {
            alert("Error: " + data.error);
            return;
        }

        // --- Render Plotly Chart ---
        const graphDiv = document.getElementById(`flightGraph-${plotId}`);
        const traces = [];

        // Colors: Blues/Greens for the Left Axis, Reds/Oranges/Pinks for the Right Axis
        const colorsLeft = ['#0d6efd', '#0dcaf0', '#198754', '#20c997'];
        const colorsRight = ['#dc3545', '#fd7e14', '#ffc107', '#d63384'];

        // Map Left Traces
        data.plot_data.left_traces.forEach((traceData, idx) => {
            traces.push({
                x: data.plot_data.x, y: traceData.y, name: traceData.name,
                type: 'scatter', mode: 'lines',
                line: { color: colorsLeft[idx % colorsLeft.length] }
            });
        });

        // Map Right Traces
        data.plot_data.right_traces.forEach((traceData, idx) => {
            traces.push({
                x: data.plot_data.x, y: traceData.y, name: traceData.name,
                type: 'scatter', mode: 'lines',
                line: { color: colorsRight[idx % colorsRight.length] },
                yaxis: 'y2'
            });
        });

        const layout = {
            title: false,
            xaxis: { title: 'Session Time (seconds)', gridcolor: '#f0f0f0' },
            yaxis: {
                title: data.plot_data.left_name,
                titlefont: { color: '#0d6efd' }, tickfont: { color: '#0d6efd' },
                gridcolor: '#f0f0f0'
            },
            yaxis2: {
                title: data.plot_data.right_name,
                titlefont: { color: '#dc3545' }, tickfont: { color: '#dc3545' },
                overlaying: 'y', side: 'right',
                gridcolor: 'transparent'
            },
            hovermode: 'x unified',
            margin: { l: 60, r: 60, t: 20, b: 40 },
            legend: { orientation: "h", y: -0.15 },
            template: 'plotly_dark'
        };

        // const isTemp = (sig) => /CHT|EGT|Temp|OAT/i.test(sig);
        // if (isTemp(leftSignal) && isTemp(rightSignal)) {
        //     layout.yaxis2.matches = 'y';
        // }

        Plotly.newPlot(graphDiv, traces, layout, {responsive: true});

        if (window._crosshairX !== null && window._crosshairX !== undefined) {
            updateCrosshairs(window._crosshairX);
        }

        graphDiv.on('plotly_hover', function(eventdata) {
            if (!eventdata.points || eventdata.points.length === 0) return;

            const pt = eventdata.points[0];
            // --- Sync Aircraft Attitude to Cursor ---
            const idx = pt.pointIndex;

            const pitchArr = window.currentPlotData?.pitch || [];
            const rollArr = window.currentPlotData?.roll || [];
            const headingArr = window.currentPlotData?.heading || [];

            if (pitchArr.length && rollArr.length && headingArr.length && idx !== undefined) {
                document.getElementById('attPitch').innerText =
                    (pitchArr[idx] !== undefined ? Number(pitchArr[idx]).toFixed(1) : '--') + ' °';

                document.getElementById('attRoll').innerText =
                    (rollArr[idx] !== undefined ? Number(rollArr[idx]).toFixed(1) : '--') + ' °';

                document.getElementById('attHeading').innerText =
                    (headingArr[idx] !== undefined ? Number(headingArr[idx]).toFixed(1) : '--') + ' °';
            }

        // --- Drive 3D Model Rotation (placeholder) ---
        if (window.updateAircraft3D && idx !== undefined) {
            const pitchVal = pitchArr[idx] || 0;
            const rollVal = rollArr[idx] || 0;
            const headingVal = headingArr[idx] || 0;
            // Call the 3D module's update
            window.updateAircraft3D(
                pitchVal,
                rollVal,
                headingVal
            );
        }

            // DIRECT INDEX MATCH (this is the fix)
            if (pt.pointIndex !== undefined && window._mapLat && window._mapLon) {
                const idx = pt.pointIndex;

                const lat = window._mapLat[idx];
                const lon = window._mapLon[idx];

                const mapDiv = document.getElementById('mapGraph');
                if (!mapDiv) return;

                let aircraftIndex = window._mapMarkerTraceIndex || 0;

                try {
                    Plotly.restyle('mapGraph', {
                        lat: [[lat]],
                        lon: [[lon]]
                    }, [aircraftIndex]);
                } catch (e) {
                    console.error("Direct marker move failed:", e);
                }

                // update3DPosition(idx);
                // Follow mode
                if (followAircraft) {
                    Plotly.relayout('mapGraph', {
                        'mapbox.center.lat': lat,
                        'mapbox.center.lon': lon
                    });
                }
                return;
            }

            // Fallback (time-based)
            const xVal = pt.x;

            if (xVal !== undefined) {
                const t = parseFloat(xVal);

                if (!window._crosshairLock) {
                    window._crosshairLock = true;

                    updateCrosshairs(t);
                    updateTooltips(t);

                    window._crosshairLock = false;
                }

                syncAircraftToTime(t);

                updateTooltips(t);
            }
        });

        // 2. Sync Relayout (Zoom / Pan)
        graphDiv.on('plotly_relayout', function(eventdata) {
            if (window._isZoomSyncing) return;
            window._isZoomSyncing = true;

            let update = null;
            if (eventdata['xaxis.range[0]'] !== undefined) {
                update = {
                    'xaxis.range[0]': eventdata['xaxis.range[0]'],
                    'xaxis.range[1]': eventdata['xaxis.range[1]']
                };
            } else if (eventdata['xaxis.autorange'] !== undefined) {
                update = { 'xaxis.autorange': true };
            }

            if (update) {
                const promises = [];
                document.querySelectorAll('[id^="flightGraph-"]').forEach(plot => {
                    if (plot.id !== graphDiv.id && !plot.classList.contains('d-none') && plot.data) {
                        promises.push(Plotly.relayout(plot.id, update));
                    }
                });
                // Release lock when all plots finish updating
                Promise.all(promises).then(() => { window._isZoomSyncing = false; });
            } else {
                window._isZoomSyncing = false;
            }
        });

        // --- Render Map (Flight Path) ---
        renderMap(data);

        // --- Update Summary Stats ---
        document.getElementById('statFlightId').innerText = `Flight: ${data.stats.flight_id}`;
        document.getElementById('statsList').innerHTML = `
            <div class="col-sm-4 mb-3"><strong>Duration:</strong><br>${data.stats.duration_min} min</div>
            <div class="col-sm-4 mb-3"><strong>Total Fuel:</strong><br>${data.stats.total_fuel} gal</div>
            <div class="col-sm-4 mb-3"><strong>Avg Flow:</strong><br>${data.stats.avg_fuel_flow} gal/hr</div>
            <div class="col-sm-4 mb-3"><strong>Avg MPG:</strong><br><span class="text-success fw-bold">${data.stats.avg_mpg} nm/gal</span></div>
            <div class="col-sm-4 mb-3"><strong>Distance Traveled:</strong><br>${data.stats.distance_traveled.toFixed(1)} mi</div>
            <div class="col-sm-4 mb-3"><strong>Max RPM:</strong><br>
                <span style="
                    ${data.stats.max_rpm > 2750 ? 'color: red; font-weight: bold;' :
                      data.stats.max_rpm >= 2700 ? 'color: orange;' :
                      'color: green;'}
                ">
                    ${data.stats.max_rpm}
                </span>
            </div>
            <div class="col-sm-4 mb-3"><strong>Max CHT:</strong><br>
                <span style="
                    ${data.stats.max_cht > 450 ? 'color: red; font-weight: bold;' :
                      data.stats.max_cht > 420 ? 'color: orange;' :
                      data.stats.max_cht < 400 ? 'color: green;' : ''}
                ">
                    ${data.stats.max_cht} °F
                </span>
            </div>
        `;

        // Always show the aircraft card once analysis runs
        document.getElementById('aircraftDataCard').classList.remove('d-none');
        document.getElementById('aircraftDataPlaceholder').classList.add('d-none');

        const pitch = data.plot_data?.pitch || [];
        const roll = data.plot_data?.roll || [];
        const heading = data.plot_data?.heading || [];

        const idx = Math.max(0, pitch.length - 1);

        document.getElementById('attPitch').innerText =
            (pitch[idx] !== undefined ? Number(pitch[idx]).toFixed(1) : '--') + ' °';

        document.getElementById('attRoll').innerText =
            (roll[idx] !== undefined ? Number(roll[idx]).toFixed(1) : '--') + ' °';

        document.getElementById('attHeading').innerText =
            (heading[idx] !== undefined ? Number(heading[idx]).toFixed(1) : '--') + ' °';

        // --- ALWAYS initialize 3D viewer if not already initialized ---
        if (window.init3DViewer) {
            window.init3DViewer();
        }
    })
    .catch(err => {
        alert(err);
        console.error(err);
        loader.classList.add('d-none');
    });
}
function renderPlotFilters(plotId) {
    const card = document.getElementById(`plotCard-${plotId}`);
    if (!card) return;

    const list = card.querySelector('.filter-list');
    list.innerHTML = '';

    const filters = plotFilters[plotId] || [];

    filters.forEach((f, idx) => {
        const li = document.createElement('li');
        li.className = "list-group-item d-flex justify-content-between align-items-center p-1";
        li.innerHTML = `
            <span>${f.signal} ${f.op} ${f.value}</span>
            <button class="btn btn-sm btn-outline-danger" onclick="removePlotFilter(${plotId}, ${idx})">✖</button>
        `;
        list.appendChild(li);
    });
}

function removePlotFilter(plotId, index) {
    plotFilters[plotId].splice(index, 1);
    renderPlotFilters(plotId);
    triggerAnalysis(plotId);
}

function plotXY() {
    if (!currentSavedFilename) return;

    const xSignal = document.getElementById('xyXSelect').value;
    const ySignal = document.getElementById('xyYSelect').value;
    const tempUnit = document.getElementById('unitF').checked ? 'F' : 'C';

    const overlay = document.getElementById('xyOverlayToggle')?.checked;

    const requestData = (filters) => {
        const formData = new FormData();
        formData.append('saved_filename', currentSavedFilename);
        formData.append('left_signal', xSignal);
        formData.append('right_signal', ySignal);
        formData.append('temp_unit', tempUnit);
        formData.append('filters', JSON.stringify(filters || []));

        return fetch('/api/analyze_flight', { method: 'POST', body: formData })
            .then(r => r.json());
    };

    const renderPlot = (rawData, filteredData) => {
        const traces = [];

        if (overlay) {
            const rx = rawData.plot_data.left_traces[0].y;
            const ry = rawData.plot_data.right_traces[0].y;

            traces.push({
                x: rx,
                y: ry,
                mode: 'markers',
                type: 'scatter',
                name: 'Raw',
                marker: { size: 3, color: 'rgba(150,150,150,0.5)' }
            });

            const fx = filteredData.plot_data.left_traces[0].y;
            const fy = filteredData.plot_data.right_traces[0].y;

            traces.push({
                x: fx,
                y: fy,
                mode: 'markers',
                type: 'scatter',
                name: 'Filtered',
                marker: { size: 4, color: '#0d6efd' }
            });

        } else {
            const data = filteredData;

            traces.push({
                x: data.plot_data.left_traces[0].y,
                y: data.plot_data.right_traces[0].y,
                mode: 'markers',
                type: 'scatter',
                marker: { size: 4 }
            });
        }

        const layout = {
            xaxis: { title: xSignal },
            yaxis: { title: ySignal },
            margin: { l: 60, r: 20, t: 20, b: 40 },
            legend: { orientation: "h" },
            template: 'plotly_dark',
        };

        Plotly.newPlot('xyGraph', traces, layout, { responsive: true });
    };

    if (!overlay) {
        requestData(xyFilters)
            .then(data => {
                if (data.error) return alert(data.error);
                renderPlot(null, data);
            });
    } else {
        Promise.all([
            requestData([]),
            requestData(xyFilters)
        ]).then(([rawData, filteredData]) => {
            if (rawData.error || filteredData.error) {
                alert("Error generating overlay plot.");
                return;
            }
            renderPlot(rawData, filteredData);
        });
    }
}

function swapXY() {
    const xSelect = document.getElementById('xyXSelect');
    const ySelect = document.getElementById('xyYSelect');

    const temp = xSelect.value;
    xSelect.value = ySelect.value;
    ySelect.value = temp;

    plotXY();
}

function addXYFilter() {
    const signal = document.getElementById('xyFilterSignal').value;
    const op = document.getElementById('xyFilterOp').value;
    const value = parseFloat(document.getElementById('xyFilterValue').value);

    if (isNaN(value)) return;

    xyFilters.push({ signal, op, value });
    renderXYFilters();
    plotXY();
}

function removeXYFilter(index) {
    xyFilters.splice(index, 1);
    renderXYFilters();
    plotXY();
}

function clearXYFilters() {
    xyFilters = [];
    renderXYFilters();
    plotXY();
}

function renderXYFilters() {
    const list = document.getElementById('xyFilterList');
    if (!list) return;

    list.innerHTML = '';

    xyFilters.forEach((f, idx) => {
        const li = document.createElement('li');
        li.className = "list-group-item d-flex justify-content-between align-items-center p-1";
        li.innerHTML = `
            <span>${f.signal} ${f.op} ${f.value}</span>
            <button class="btn btn-sm btn-outline-danger" onclick="removeXYFilter(${idx})">✖</button>
        `;
        list.appendChild(li);
    });
}

function openAirspeedCalModal() {
    const el = document.getElementById('airspeedCalModal');
    if (!el) return;

    const startInput = document.getElementById('calStartTime');
    const endInput = document.getElementById('calEndTime');
    const resultBox = document.getElementById('calibrationResult');
    if (startInput) startInput.value = '';
    if (endInput) endInput.value = '';
    if (resultBox) resultBox.innerText = 'Results will appear here...';

    const modal = new bootstrap.Modal(el);
    modal.show();
}

function submitAirspeedCalibration() {
    const start = parseFloat(document.getElementById('calStartTime').value);
    const end = parseFloat(document.getElementById('calEndTime').value);
    const resultBox = document.getElementById('calibrationResult');

    if (isNaN(start) || isNaN(end)) {
        resultBox.innerText = "Please enter valid start and end maneuver times.";
        return;
    }

    if (!currentSavedFilename) {
        resultBox.innerText = "No flight loaded.";
        return;
    }

    // Store calibration range globally for map highlight
    calStartTimeGlobal = start;
    calEndTimeGlobal = end;

    resultBox.innerText = "Running calibration analysis...";

    const formData = new FormData();
    formData.append('saved_filename', currentSavedFilename);
    formData.append('start_time', start);
    formData.append('end_time', end);

    fetch('/api/airspeed_calibration', {
        method: 'POST',
        body: formData
    })
    .then(res => res.json())
    .then(data => {
        if (data.error) {
            resultBox.innerText = "Error: " + data.error;
            return;
        }

        const summary = data.summary || "No summary returned.";
        resultBox.innerText = summary;

        const lines = summary.split('\n');
        const parsed = {};

        lines.forEach(line => {
            const parts = line.split(':');
            if (parts.length >= 2) {
                const key = parts[0].trim();
                const value = parts.slice(1).join(':').trim();
                parsed[key] = value;
            }
        });

        const statsList = document.getElementById('statsList');
        if (statsList) {
            let existing = document.getElementById('airspeed-summary-block');
            if (existing) existing.remove();

            const block = document.createElement('div');
            block.id = 'airspeed-summary-block';
            block.className = 'col-12 mt-3 p-2 border rounded';

            block.innerHTML = `
                <h6 class="text-primary mb-2">Airspeed Calibration</h6>
                <div class="row mb-2">
                    <div class="col-md-6"><strong>Start Time:</strong><br>${formatMMSS(calStartTimeGlobal)}</div>
                    <div class="col-md-6"><strong>End Time:</strong><br>${formatMMSS(calEndTimeGlobal)}</div>
                </div>
                <div class="row">
                    <div class="col-md-4"><strong>CAS Correction:</strong><br>${parsed['CAS Correction'] || 'N/A'}</div>
                    <div class="col-md-4"><strong>Uncorrected TAS:</strong><br>${parsed['Uncorr. Avg TAS'] || 'N/A'}</div>
                    <div class="col-md-4"><strong>Corrected TAS:</strong><br>${parsed['Corrected Avg TAS'] || 'N/A'}</div>
                </div>
            `;

            statsList.appendChild(block);
        }
        if (lastMapRenderData) {
            renderMap(lastMapRenderData);
        }
    })
    .catch(err => {
        console.error(err);
        resultBox.innerText = "Network error during calibration.";
    });
}

function formatMMSS(seconds) {
    if (seconds === null || seconds === undefined || isNaN(seconds)) return "--:--";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
}

function computeHeading(lat1, lon1, lat2, lon2) {
    const toRad = Math.PI / 180;
    const toDeg = 180 / Math.PI;

    const dLon = (lon2 - lon1) * toRad;
    const y = Math.sin(dLon) * Math.cos(lat2 * toRad);
    const x = Math.cos(lat1 * toRad) * Math.sin(lat2 * toRad) -
              Math.sin(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.cos(dLon);

    let brng = Math.atan2(y, x) * toDeg;
    return (brng + 360) % 360;
}

function computeDistance(lat1, lon1, lat2, lon2) {
    const R = 6371000;
    const toRad = Math.PI / 180;

    const dLat = (lat2 - lat1) * toRad;
    const dLon = (lon2 - lon1) * toRad;

    const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.sin(dLon / 2) ** 2;
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
}

function renderMap(data) {
    if (!data) return;
    let lat = null;
    let lon = null;
    lastMapRenderData = data;

    if (data.plot_data) {
        const keys = Object.keys(data.plot_data);
        const latKey = keys.find(k => k.toLowerCase().includes("latitude"));
        const lonKey = keys.find(k => k.toLowerCase().includes("longitude"));

        if (latKey && lonKey) {
            lat = data.plot_data[latKey];
            lon = data.plot_data[lonKey];
        }
    }

    if ((!lat || !lon) && data.lat && data.lon) {
        lat = data.lat;
        lon = data.lon;
    }

    if (!lat || !lon) return;

    // --- SAFE PARSE + ALIGN LAT/LON/ALT BY INDEX (CRITICAL FIX) ---

    const latRaw = lat.map(v => parseFloat(v));
    const lonRaw = lon.map(v => parseFloat(v));
    // console.log("DEBUG LAT/LON:");
    // console.log("latRaw length:", latRaw.length);
    // console.log("lonRaw length:", lonRaw.length);
    // console.log("latRaw sample:", latRaw.slice(0, 10));
    // console.log("lonRaw sample:", lonRaw.slice(0, 10));

    // --- GLOBAL MAP STATE (needed for hover + sync) ---
    window._mapLat = latRaw;
    window._mapLon = lonRaw;
    window._mapLength = latRaw.length;
    window._mapTime = (data.plot_data?.time || data.plot_data?.session_time || data.time || null);

    if (window._mapTime && Array.isArray(window._mapTime)) {
        window._mapTime = window._mapTime.map(v => parseFloat(v));
    }

    let altRaw = null;

    if (data.plot_data) {
        const keys = Object.keys(data.plot_data);
        const altKey = keys.find(k => k.toLowerCase().includes("altitude"));
        if (altKey) altRaw = data.plot_data[altKey];
    }

    if (!altRaw && data.alt) altRaw = data.alt;

    if (altRaw) {
        if (!Array.isArray(altRaw)) {
            // Handle case where backend sends single value or object
            altRaw = Object.values(altRaw);
        }
        altRaw = altRaw.map(v => parseFloat(v));
    }
    // console.log("DEBUG ALT RAW:");
    // console.log("altRaw type:", typeof altRaw);
    // console.log("altRaw isArray:", Array.isArray(altRaw));
    // console.log("altRaw length:", altRaw ? altRaw.length : null);
    // console.log("altRaw sample:", altRaw ? altRaw.slice(0, 10) : null);

    // --- ALIGN ALTITUDE TO LAT/LON INDEX (CRITICAL FIX) ---
    const cleanAlt = [];

    for (let i = 0; i < latRaw.length; i++) {
        const a = (altRaw && Array.isArray(altRaw)) ? altRaw[i] : null;

        if (a === undefined || a === null || isNaN(a)) {
            cleanAlt.push(null);
        } else {
            cleanAlt.push(a);
        }
    }
    // console.log("DEBUG CLEAN ALT:");
    // console.log("cleanAlt length:", cleanAlt.length);
    // console.log("cleanAlt sample:", cleanAlt.slice(0, 10));
    // console.log("cleanAlt min:", Math.min(...cleanAlt.filter(v => !isNaN(v))));
    // console.log("cleanAlt max:", Math.max(...cleanAlt.filter(v => !isNaN(v))));

    // Ensure altitude always matches lat length for heatmap modes
    window._mapAlt = cleanAlt;
    // --- CONVERT LAT/LON/ALT TO 3D WORLD ---
    const originLat = latRaw[0];
    const originLon = lonRaw[0];

    const scale = 111320; // meters per degree approx

    window._worldX = [];
    window._worldY = [];
    window._worldZ = [];

    for (let i = 0; i < latRaw.length; i++) {
        const dLat = (latRaw[i] - originLat);
        const dLon = (lonRaw[i] - originLon);

        const x = dLon * scale * Math.cos(originLat * Math.PI / 180);
        const z = dLat * scale;
        const y = cleanAlt[i] || 0;

        window._worldX.push(x);
        window._worldY.push(y);
        window._worldZ.push(z);
    }
    window._mapAirspeed = data.plot_data?.airspeed || null;
    window._mapGroundspeed = data.plot_data?.groundspeed || null;
    window._mapVerticalSpeed = data.plot_data?.vertical_speed || null;

    // --- COLOR MODE RESOLVER ---
    const getColorValues = () => {
        if (mapColorMode === 'altitude') return window._mapAlt;
        if (mapColorMode === 'airspeed' && window._mapAirspeed) return window._mapAirspeed;
        if (mapColorMode === 'groundspeed' && window._mapGroundspeed) return window._mapGroundspeed;
        if (mapColorMode === 'vertical_speed' && window._mapVerticalSpeed) return window._mapVerticalSpeed;

        // fallback
        return window._mapAlt;
    };

    const metricsDiv = document.getElementById('mapMetrics');
    if (metricsDiv) {
        // metricsDiv.innerHTML = `
        //     <div class="d-flex justify-content-between align-items-center">
        //         <div class="small text-muted">Color Mode</div>
        //         <select id="mapColorModeSelect" class="form-select form-select-sm w-auto">
        //             <option value="altitude">Altitude</option>
        //             <option value="airspeed">Airspeed</option>
        //             <option value="groundspeed">Ground Speed</option>
        //             <option value="vertical_speed">Vertical Speed</option>
        //         </select>
        //     </div>
        // `;

        const sel = document.getElementById('mapColorModeSelect');
        if (sel) {
            sel.value = mapColorMode;
            sel.onchange = () => {
                mapColorMode = sel.value;
                renderMap(data);
            };
        }
    }

    // --- Dual-layer heatmap (Option 2: aviation-style) ---

    // 1) Base black outline (slightly thicker)
    const pathLineBaseTrace = {
        type: 'scattermapbox',
        mode: 'lines',
        lat: lat,
        lon: lon,
        line: { width: 5, color: '#000000' },
        name: 'Flight Path Outline',
        showlegend: false
    };

    // 2) Top visible flight path (main line)
    const pathLineTrace = {
        type: 'scattermapbox',
        mode: 'lines',
        lat: lat,
        lon: lon,
        line: { width: 3, color: '#b0b0b0' },
        name: 'Flight Path',
        showlegend: false
    };

    // 2) Heatmap overlay using colored points (altitude-based)
    let heatTrace = null;

    const colorValues = getColorValues();
    // console.log("DEBUG COLOR VALUES:");
    // console.log("mapColorMode:", mapColorMode);
    // console.log("colorValues length:", colorValues ? colorValues.length : null);
    // console.log("colorValues sample:", colorValues ? colorValues.slice(0, 10) : null);

    if (!colorValues || !colorValues.length) {
        mapColorMode = 'altitude';
    }

    if (colorValues && colorValues.length === lat.length) {
        // SAFER color mapping to prevent NaN/black rendering
        const safeColors = (colorValues || []).map(v => {
            const num = parseFloat(v);
            return isNaN(num) ? NaN : num;
        });

        // Fallback to altitude if selected mode is invalid or empty
        let validVals = safeColors.filter(v => !isNaN(v));
        if (!validVals.length && window._mapAlt) {
            validVals = window._mapAlt.filter(v => !isNaN(v));
        }

        // Final safety fallback to avoid black map
        let cmin, cmax;

        if (mapColorMode === 'altitude' && window._mapAlt && window._mapAlt.length) {
            const altVals = window._mapAlt.filter(v => !isNaN(v));

            cmin = altVals.length ? Math.min(...altVals) : 0;
            cmax = altVals.length ? Math.max(...altVals) : 15000;

            // Hard clamp fallback if data is flat or broken
            if (cmin === cmax) {
                cmin = 0;
                cmax = 15000;
            }
        } else {
            cmin = validVals.length ? Math.min(...validVals) : 0;
            cmax = validVals.length ? Math.max(...validVals) : 1;
        }

        heatTrace = {
            type: 'scattermapbox',
            mode: 'markers',
            lat: lat,
            lon: lon,
            marker: {
                size: 4,
                color: (mapColorMode === 'altitude')
                    ? window._mapAlt.map(v => isNaN(v) ? NaN : v)
                    : safeColors,
                colorscale: COLOR_SCALES[mapColorMode] || 'Turbo',
                reversescale: mapColorMode === 'altitude',
                showscale: true,
                cmin: (mapColorMode === 'altitude') ? 0 : cmin,
                cmax: (mapColorMode === 'altitude') ? 15000 : cmax,
                colorbar: {
                    title: {
                        text: COLOR_LABELS[mapColorMode] || 'Value'
                    },
                    orientation: 'h',
                    x: 0.5,
                    xanchor: 'center',
                    y: -0.25
                }
            },
            hoverinfo: 'skip',
            name: 'Altitude Heat',
            showlegend: false
        };
    }

    // Invisible interaction layer (ensures hover always triggers)
    const interactionTrace = {
        type: 'scattermapbox',
        mode: 'markers',
        lat: lat,
        lon: lon,
        marker: {
            size: 20,
            color: 'rgba(0,0,0,0)',
        },
        hoverinfo: 'none',
        showlegend: false
    };

    // Highlight calibration segment, if present
    let highlightTrace = null;
    var startTrace = null;
    var endTrace = null;

    if (calStartTimeGlobal !== null && calEndTimeGlobal !== null && window._mapTime) {
        const highlightLat = [];
        const highlightLon = [];

        for (let i = 0; i < window._mapTime.length; i++) {
            const t = Number(window._mapTime[i]);

            if (isNaN(t)) continue;

            let start = calStartTimeGlobal;
            let end = calEndTimeGlobal;

            // safety swap if user reversed inputs
            if (start > end) {
                const tmp = start;
                start = end;
                end = tmp;
            }

            if (t >= start && t <= end) {
                highlightLat.push(lat[i]);
                highlightLon.push(lon[i]);
            }
        }

        if (highlightLat.length > 1) {
            highlightTrace = {
                type: 'scattermapbox',
                mode: 'lines',
                lat: highlightLat,
                lon: highlightLon,
                line: { width: 4, color: '#66b2ff' },
                name: 'Calibration Segment',
                showlegend: false
            };

            // Compute headings for start and end arrows
            const startHeading = computeHeading(
                highlightLat[0],
                highlightLon[0],
                highlightLat[1],
                highlightLon[1]
            );

            const endHeading = computeHeading(
                highlightLat[highlightLat.length - 2],
                highlightLon[highlightLon.length - 2],
                highlightLat[highlightLat.length - 1],
                highlightLon[highlightLon.length - 1]
            );

            startTrace = {
                type: 'scattermapbox',
                mode: 'markers',
                lat: [highlightLat[0]],
                lon: [highlightLon[0]],
                marker: { size: 12, color: 'lightgreen' },
                name: 'Start',
                showlegend: false
            };

            endTrace = {
                type: 'scattermapbox',
                mode: 'markers',
                lat: [highlightLat[highlightLat.length - 1]],
                lon: [highlightLon[highlightLon.length - 1]],
                marker: { size: 12, color: 'purple' },
                name: 'End',
                showlegend: false
            };
        }
    }

    // aircraft marker
    const markerTrace = {
        type: 'scattermapbox',
        mode: 'markers',
        lat: [lat[0]],
        lon: [lon[0]],
        marker: { size: 10, color: 'black' },
        name: 'Aircraft',
        meta: { role: 'aircraft_marker' },
        showlegend: false
    };

    const layout = {
        mapbox: {
            style: "open-street-map",
            center: {
                lat: lat[Math.floor(lat.length / 2)],
                lon: lon[Math.floor(lon.length / 2)]
            },
            zoom: 8
        },
        margin: { t: 0, b: 0, l: 0, r: 0 },
        showlegend: false
    };

    // --- SAFE TRACE BUILD (prevents Plotly null crashes) ---
    const traces = [];

    // Base flight path with outline effect
    if (pathLineBaseTrace) traces.push(pathLineBaseTrace);
    if (pathLineTrace) traces.push(pathLineTrace);

    // Heat overlay
    if (heatTrace) traces.push(heatTrace);

    // Invisible interaction layer (must be above visuals)
    if (interactionTrace) traces.push(interactionTrace);

    // Calibration highlight
    if (highlightTrace) traces.push(highlightTrace);

    // Start / End markers
    if (typeof startTrace !== 'undefined' && startTrace) traces.push(startTrace);
    if (typeof endTrace !== 'undefined' && endTrace) traces.push(endTrace);

    // Aircraft marker ALWAYS LAST (on top)
    if (markerTrace) traces.push(markerTrace);

    // --- STORE MARKER TRACE INDEX FOR LIVE SYNC ---
    window._mapMarkerTraceIndex = traces.findIndex(
        t => t && t.meta && t.meta.role === 'aircraft_marker'
    );
    if (window._mapMarkerTraceIndex === -1) {
        window._mapMarkerTraceIndex = traces.length - 1;
    }
    if (window._mapMarkerTraceIndex < 0) window._mapMarkerTraceIndex = 0;


    Plotly.newPlot('mapGraph', traces, layout, { responsive: true });

    // --- MAP HOVER SYNC (cursor -> aircraft position) ---
    const mapDiv = document.getElementById('mapGraph');

    // Set up scrubber max and value
    const scrubber = document.getElementById('mapScrubber');
    if (scrubber && window._mapLength) {
        scrubber.max = window._mapLength - 1;
        scrubber.value = 0;
    }
}

function syncAircraftToTime(t) {
    if (!window._mapTime || !window._mapLat || !window._mapLon) return;

    // Find closest index in time array
    let bestIndex = 0;
    let bestDiff = Infinity;

    for (let i = 0; i < window._mapTime.length; i++) {
        const diff = Math.abs(window._mapTime[i] - t);
        if (diff < bestDiff) {
            bestDiff = diff;
            bestIndex = i;
        }
    }

    const mapDiv = document.getElementById('mapGraph');
    if (!mapDiv) return;

    // Resolve aircraft marker trace index (fallback-safe)
    let aircraftIndex = window._mapMarkerTraceIndex;

    if (mapDiv.data && mapDiv.data.length) {
        const idx = mapDiv.data.findIndex(t =>
            t && t.meta && t.meta.role === 'aircraft_marker'
        );
        if (idx !== -1) aircraftIndex = idx;
    }

    if (aircraftIndex === undefined || aircraftIndex === null || aircraftIndex < 0) {
        aircraftIndex = window._mapMarkerTraceIndex || 0;
    }

    const lat = window._mapLat[bestIndex];
    const lon = window._mapLon[bestIndex];

    // Directly update ONLY the aircraft marker trace (stable + no full redraw)
    try {
        Plotly.restyle('mapGraph', {
            lat: [[lat]],
            lon: [[lon]]
        }, [aircraftIndex]);

        Plotly.redraw('mapGraph');
    } catch (e) {
        console.error("Aircraft marker update failed:", e);
    }

    // Follow mode (map recenter)
    if (followAircraft) {
        Plotly.relayout('mapGraph', {
            'mapbox.center.lat': lat,
            'mapbox.center.lon': lon
        });
    }

    // Update the map scrubber position
    const scrubber = document.getElementById('mapScrubber');
    if (scrubber) {
        scrubber.value = bestIndex;
    }
}

function scrubMap(idx) {
    idx = parseInt(idx);

    if (!window._mapLat || !window._mapLon) return;

    const lat = window._mapLat[idx];
    const lon = window._mapLon[idx];

    const mapDiv = document.getElementById('mapGraph');
    if (!mapDiv) return;

    let aircraftIndex = window._mapMarkerTraceIndex || 0;

    try {
        Plotly.restyle('mapGraph', {
            lat: [[lat]],
            lon: [[lon]]
        }, [aircraftIndex]);
    } catch (e) {
        console.error("Scrubber update failed:", e);
    }

    // Also sync 3D + attitude if available
    if (window.currentPlotData) {
        const pitch = window.currentPlotData.pitch?.[idx] || 0;
        const roll = window.currentPlotData.roll?.[idx] || 0;
        const heading = window.currentPlotData.heading?.[idx] || 0;

        document.getElementById('attPitch').innerText = pitch.toFixed(1) + ' °';
        document.getElementById('attRoll').innerText = roll.toFixed(1) + ' °';
        document.getElementById('attHeading').innerText = heading.toFixed(1) + ' °';

        if (window.updateAircraft3D) {
            window.updateAircraft3D(pitch, roll, heading);
        }
    }

    // Follow mode
    if (followAircraft) {
        Plotly.relayout('mapGraph', {
            'mapbox.center.lat': lat,
            'mapbox.center.lon': lon
        });
    }
}
function togglePlayback() {
    const btn = document.getElementById('playPauseBtn');
    const scrubber = document.getElementById('mapScrubber');

    if (playbackTimer) {
        clearInterval(playbackTimer);
        playbackTimer = null;
        btn.innerText = '▶ Play';
        return;
    }

    playbackIndex = parseInt(scrubber.value) || 0;
    btn.innerText = '⏸ Pause';

    const baseInterval = 150;

    playbackTimer = setInterval(() => {
        if (!window._mapLat || playbackIndex >= window._mapLat.length - 1) {
            clearInterval(playbackTimer);
            playbackTimer = null;
            btn.innerText = '▶ Play';
            return;
        }

        playbackIndex += playbackSpeed;

        if (playbackIndex >= window._mapLat.length) {
            playbackIndex = window._mapLat.length - 1;
        }

        // 🔥 KEEP SLIDER IN SYNC
        const scrubber = document.getElementById('mapScrubber');
        if (scrubber) scrubber.value = playbackIndex;

        scrubMap(playbackIndex);

    }, baseInterval / playbackSpeed);
}

function setPlaybackSpeed(val) {
    playbackSpeed = parseInt(val);

    if (playbackTimer) {
        clearInterval(playbackTimer);

        const scrubber = document.getElementById('mapScrubber');
        playbackIndex = parseInt(scrubber.value) || playbackIndex || 0;

        const baseInterval = 150;

        playbackTimer = setInterval(() => {
            if (!window._mapLat || playbackIndex >= window._mapLat.length - 1) {
                clearInterval(playbackTimer);
                playbackTimer = null;
                document.getElementById('playPauseBtn').innerText = '▶ Play';
                return;
            }

            playbackIndex += playbackSpeed;

            if (playbackIndex >= window._mapLat.length) {
                playbackIndex = window._mapLat.length - 1;
            }

            // 🔥 KEEP SLIDER IN SYNC
            const scrubber = document.getElementById('mapScrubber');
            if (scrubber) scrubber.value = playbackIndex;

            scrubMap(playbackIndex);

        }, baseInterval / playbackSpeed);
    }
}

function toggleXYFilters() {
    const section = document.getElementById('xy-filter-section');
    if (!section) return;
    const btn = document.getElementById('xy-filter-btn');
    const isHidden = section.classList.toggle('d-none');
    if (btn) btn.innerText = isHidden ? 'Show Filters' : 'Hide Filters';
}

function togglePlotFilters(plotId) {
    const section = document.getElementById(`filter-section-${plotId}`);
    if (!section) return;
    const btn = document.getElementById(`filter-btn-${plotId}`);
    const isHidden = section.classList.toggle('d-none');
    if (btn) btn.innerText = isHidden ? 'Show Filters' : 'Hide Filters';
}