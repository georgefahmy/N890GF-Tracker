// Centralized Application State
const AppState = {
    file: {
        currentName: "",
        signalsList: [],
    },
    ui: {
        plotCounter: 0,
        filters: {},      // { plotId: [filters] }
        xyFilters: [],
        xyOverlay: false
    },
    map: {
        followAircraft: true,
        colorMode: 'altitude',
        isMapPanning: false,
        lastRenderData: null,
        markerTraceIndex: 0,
        data: {
            lat: null, // Float32Array
            lon: null,
            alt: null,
            length: 0
        }
    },
    playback: {
        timer: null,
        index: 0,
        speed: 1,
        isScrubbing: false,
        tick: 0,
        fps: 30
    },
    calibration: {
        start: null,
        end: null
    },
    currentPlotData: null
};

function resetApp() {
    if (AppState.playback.timer && AppState.playback.timer !== true) {
        clearInterval(AppState.playback.timer);
    }
    AppState.file.currentName = "";
    AppState.file.signalsList = [];
    AppState.ui.filters = {};
    AppState.ui.plotCounter = 0;
    AppState.map.data = { lat: null, lon: null, alt: null, length: 0 };
    AppState.playback = { timer: null, index: 0, speed: 1, isScrubbing: false, tick: 0 };

    const container = document.getElementById('plots-container');
    if (container) container.innerHTML = '';
}

const STORAGE_KEY = 'analyzer_selected_flight';

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
    AppState.map.followAircraft = state;
}

function toggleXYTab() {
    const tab = document.getElementById('xyTab');
    tab.classList.toggle('d-none');
    populateXYDropdowns();
}

function generateBandShapes(signalName, yAxisRef) {
    const cleanSignal = signalName;
    const bands = SIGNAL_BANDS[cleanSignal];

    if (!bands) return [];

    return bands.map(band => ({
        type: 'rect',
        xref: 'paper',
        x0: 0,
        x1: 1,
        yref: yAxisRef,
        // Default to extreme bounds if the user left the input blank
        y0: band.min !== undefined && band.min !== null ? band.min : -999999,
        y1: band.max !== undefined && band.max !== null ? band.max : 999999,
        fillcolor: band.color,
        opacity: 0.15,
        layer: 'below',
        line: { width: 0 },
        name: 'band'
    }));
}

function populateXYDropdowns() {
    const xSelect = document.getElementById('xyXSelect');
    const ySelect = document.getElementById('xyYSelect');

    if (!xSelect || AppState.file.signalList.length === 0) return;

    const unitF = document.getElementById('unitF').checked;
    const hideString = unitF ? "(deg C)" : "(deg F)";

    // Apply same filtering logic as main plots
    const filteredSignals = AppState.file.signalList.filter(sig => {
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
    // --- ADD THIS BLOCK ---
    const scrubber = document.getElementById('mapScrubber');
    if (scrubber) {
        scrubber.addEventListener('mousedown', () => AppState.playback.isScrubbing = true);
        scrubber.addEventListener('touchstart', () => { AppState.playback.isScrubbing = true; }, {passive: true});
        scrubber.addEventListener('mouseup', () => AppState.playback.isScrubbing = false);
        scrubber.addEventListener('touchend', () => AppState.playback.isScrubbing = false);
        scrubber.addEventListener('change', () => AppState.playback.isScrubbing = false); // Failsafe if dropped outside
    }
    //
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

        AppState.file.currentName = data.saved_filename;
        if (data.saved_filename) {
            localStorage.setItem(STORAGE_KEY, data.saved_filename);
        }
        AppState.file.signalList = data.signals;

        // Hide placeholders, show relevant UI
        document.getElementById('statsPlaceholder').classList.add('d-none');
        document.getElementById('statsCard').classList.remove('d-none');
        document.getElementById('plotHeader').classList.remove('d-none');
        document.getElementById('addPlotBtn').classList.remove('d-none');

        // If no plots exist, create the first one
        if (AppState.ui.plotCounter === 0) {
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
    if (!urlFlight) {
        const newUrl = window.location.pathname + '?flight=' + encodeURIComponent(saved);
        window.history.replaceState({ path: newUrl }, '', newUrl);
    }
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
    const plotId = AppState.ui.plotCounter++;
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
                <div class="col-md-auto mt-2 mt-md-0 d-flex justify-content-end align-items-end flex-nowrap gap-2">
                    <div class="form-check form-switch mb-1 me-2">
                        <input class="form-check-input" type="checkbox" id="showBands-${plotId}" checked onchange="triggerAnalysis(${plotId})">
                        <label class="form-check-label small text-muted" for="showBands-${plotId}">Bands</label>
                    </div>
                    <div class="form-check form-switch mb-1 me-2">
                        <input class="form-check-input" type="checkbox" id="splitAxis-${plotId}" onchange="triggerAnalysis(${plotId})">
                        <label class="form-check-label small text-muted" for="splitAxis-${plotId}">Split</label>
                    </div>
                    <button class="btn btn-outline-secondary btn-sm text-nowrap mb-1" id="filter-btn-${plotId}" onclick="togglePlotFilters(${plotId})">
                        Show Filters
                    </button>
                    ${plotId > 0 ? `<button class="btn btn-outline-secondary btn-sm text-nowrap mb-1" onclick="removePlot(${plotId})">
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

    const filteredSignals = AppState.file.signalList.filter(sig => {
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

        if (!AppState.ui.filters[plotId]) AppState.ui.filters[plotId] = [];
        AppState.ui.filters[plotId].push({ signal, op, value });

        renderPlotFilters(plotId);
        triggerAnalysis(plotId);
    };

    // Clear Filters
    cardEl.querySelector('.clear-filter-btn').onclick = () => {
        AppState.ui.filters[plotId] = [];
        renderPlotFilters(plotId);
        triggerAnalysis(plotId);
    };

    // Attach Event Listeners to the new dropdowns
    card.querySelector('.left-signal-select').addEventListener('change', () => triggerAnalysis(plotId));
    card.querySelector('.right-signal-select').addEventListener('change', () => triggerAnalysis(plotId));

    // Populate dropdowns and trigger the initial graph render
    populateDropdownsForPlot(plotId);
    if (AppState.file.currentName) triggerAnalysis(plotId);
    renderPlotFilters(plotId);
}

function removePlot(plotId) {
    const card = document.getElementById(`plotCard-${plotId}`);
    if (card) card.remove();

    // Clean up memory
    if (AppState.ui.filters[plotId]) {
        delete AppState.ui.filters[plotId];
    }
}

function updateAllPlots() {
    document.querySelectorAll('.plot-card').forEach(card => {
        const id = parseInt(card.id.split('-')[1]);
        populateDropdownsForPlot(id);
        triggerAnalysis(id);
    });
}

function populateDropdownsForPlot(plotId) {
    if (AppState.file.signalList.length === 0) return;

    const unitF = document.getElementById('unitF').checked;
    const hideString = unitF ? "(deg C)" : "(deg F)";

    const leftSelect = document.querySelector(`.left-signal-select[data-plot-id="${plotId}"]`);
    const rightSelect = document.querySelector(`.right-signal-select[data-plot-id="${plotId}"]`);

    const currentLeft = leftSelect.value;
    const currentRight = rightSelect.value;

    let optionsHtml = '';

    // Filter out the wrong temperature unit
    const filteredSignals = AppState.file.signalList.filter(sig => {
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

// --- GLOBAL TOOLTIP & CROSSHAIR SYNC ---
function syncTooltips(xVal, sourceDivId) {
    const plots = document.querySelectorAll('[id^="flightGraph-"]');

    plots.forEach(div => {
        // Skip the plot we are currently hovering on, and any hidden/empty plots
        if (!div || !div.data || div.id === sourceDivId) return;

        try {
            // Explicitly target both top (xy) and bottom (xy2) subplots
            Plotly.Fx.hover(div, { xval: xVal }, ['xy', 'xy2']);
        } catch (e) {
            console.error("Hover sync failed on", div.id, e);
        }
    });
}

function clearTooltips(sourceDivId) {
    const plots = document.querySelectorAll('[id^="flightGraph-"]');

    plots.forEach(div => {
        if (!div || !div.data || div.id === sourceDivId) return;

        try {
            Plotly.Fx.unhover(div);
        } catch (e) {
            // ignore
        }
    });
}

async function triggerAnalysis(plotId) {
    if (!AppState.file.currentName) return;

    const loader = document.getElementById(`loader-${plotId}`);
    loader.classList.remove('d-none');

    try {
        const formData = new FormData();
        formData.append('saved_filename', AppState.file.currentName);
        formData.append('left_signal', document.querySelector(`.left-signal-select[data-plot-id="${plotId}"]`).value);
        formData.append('right_signal', document.querySelector(`.right-signal-select[data-plot-id="${plotId}"]`).value);
        formData.append('temp_unit', document.getElementById('unitF').checked ? 'F' : 'C');
        formData.append('filters', JSON.stringify(AppState.ui.filters[plotId] || []));

        const response = await fetch('/api/analyze_flight', { method: 'POST', body: formData });
        const data = await response.json();

        loader.classList.add('d-none');
        if (data.error) return alert("Error: " + data.error);

        // 1. Store data
        AppState.currentPlotData = data.plot_data;

        // 2. Specialized Plot Update (Fast)
        renderPlotlyChart(plotId, data);

        // 3. UI/Map Update (Only update if global stats aren't populated yet)
        // or if you want them to refresh.
        updateGlobalUI(data);

    } catch (err) {
        console.error(err);
        loader.classList.add('d-none');
    }
}

function renderPlotlyChart(plotId, data) {
    const graphDiv = document.getElementById(`flightGraph-${plotId}`);
    const isSplit = document.getElementById(`splitAxis-${plotId}`)?.checked;
    const showBands = document.getElementById(`showBands-${plotId}`)?.checked;
    const leftSignal = document.querySelector(`.left-signal-select[data-plot-id="${plotId}"]`).value;
    const rightSignal = document.querySelector(`.right-signal-select[data-plot-id="${plotId}"]`).value;

    AppState.currentPlotData = data.plot_data;

    const traces = [];
    // Colors: Blues/Greens for the Left Axis, Reds/Oranges/Pinks for the Right Axis
    const colorsLeft = ['#0d6efd', '#0dcaf0', '#198754', '#20c997'];
    const colorsRight = ['#dc3545', '#fd7e14', '#ffc107', '#d63384'];
    // --- NEW: Track exact data limits to prevent shapes from squishing the chart ---
    let leftMin = Infinity, leftMax = -Infinity;
    let rightMin = Infinity, rightMax = -Infinity;

    // Map Left Traces
    data.plot_data.left_traces.forEach((traceData, idx) => {
        traceData.y.forEach(v => {
            const val = parseFloat(v);
            if (!isNaN(val)) {
                if (val < leftMin) leftMin = val;
                if (val > leftMax) leftMax = val;
            }
        });
        traces.push({
            x: data.plot_data.x, y: traceData.y, name: traceData.name,
            type: 'scattergl', mode: 'lines',
            line: { color: colorsLeft[idx % colorsLeft.length] }
        });
    });

    // Map Right Traces
    data.plot_data.right_traces.forEach((traceData, idx) => {
        traceData.y.forEach(v => {
            const val = parseFloat(v);
            if (!isNaN(val)) {
                if (val < rightMin) rightMin = val;
                if (val > rightMax) rightMax = val;
            }
        });
        traces.push({
            x: data.plot_data.x, y: traceData.y, name: traceData.name,
            type: 'scattergl', mode: 'lines',
            line: { color: colorsRight[idx % colorsRight.length] },
            yaxis: 'y2'
        });
    });

    // Helper to add a 5% margin to the bounds so the lines don't hug the edges
    const padRange = (min, max) => {
        if (min === Infinity || max === -Infinity) return [0, 100]; // Safe fallback
        if (min === max) return [min - 10, max + 10]; // Flatline trace fallback
        const diff = max - min;
        return [min - (diff * 0.05), max + (diff * 0.05)];
    };

    const leftRange = padRange(leftMin, leftMax);
    const rightRange = padRange(rightMin, rightMax);

    // const isSplit = document.getElementById(`splitAxis-${plotId}`)?.checked;
    // const showBands = document.getElementById(`showBands-${plotId}`)?.checked;

    let plotShapes = [];

    // Only generate and apply shapes if the toggle is checked
    if (showBands) {
        const leftShapes = generateBandShapes(leftSignal, 'y');
        const rightShapes = generateBandShapes(rightSignal, 'y2');
        plotShapes = [...leftShapes, ...rightShapes];
    }

    const layout = {
        title: false,
        xaxis: {
            title: 'Session Time (seconds)',
            gridcolor: '#f0f0f0',
            // Add native spikelines to ensure the vertical line ALWAYS draws
            showspikes: true,
            spikemode: 'across',
            spikedash: 'dot',
            spikethickness: 1,
            spikecolor: '#888',
            anchor: isSplit ? 'free' : 'y',
            position: 0
        },
        yaxis: {
            title: data.plot_data.left_name,
            titlefont: { color: '#0d6efd' }, tickfont: { color: '#0d6efd' },
            gridcolor: '#f0f0f0',
            // If split, top plot takes 55% to 100%. Otherwise, full height.
            domain: isSplit ? [0.55, 1] : [0, 1],
            range: leftRange,      // Assign strict data boundaries
            autorange: false
        },
        yaxis2: {
            title: data.plot_data.right_name,
            titlefont: { color: '#dc3545' }, tickfont: { color: '#dc3545' },

            // If split: bottom plot takes 0% to 45%. Side is left, no overlaying.
            // If combined: overlapping 'y', side is right.
            domain: isSplit ? [0, 0.45] : [0, 1],
            overlaying: isSplit ? undefined : 'y',
            side: isSplit ? 'left' : 'right',
            gridcolor: isSplit ? '#f0f0f0' : 'transparent',
            anchor: 'x', // Ensures it stays bound to the main time axis
            range: rightRange,     // Assign strict data boundaries
            autorange: false
        },
        shapes: plotShapes,
        hovermode: 'x unified',
        margin: { l: 60, r: 60, t: 20, b: 40 },
        legend: { orientation: "h", y: -0.15 },
        template: 'plotly_dark'
    };

    // Use .react() for much faster updates than .newPlot()
    Plotly.react(graphDiv, traces, layout, {responsive: true, doubleClick: 'reset'});

    if (window._crosshairX !== null && window._crosshairX !== undefined) {
        updateCrosshairs(window._crosshairX);
    }

    graphDiv.on('plotly_hover', function(eventdata) {
        // CRITICAL FIX: If this event was triggered by our code (no mouse event), ignore it.
        // This prevents the infinite loop that breaks the tooltips.
        if (!eventdata || !eventdata.event) return;

        if (!eventdata.points || eventdata.points.length === 0) return;
        const pt = eventdata.points[0];
        const idx = pt.pointIndex;
        const xVal = pt.x;

        const pitchArr = AppState.currentPlotData?.pitch || [];
        const rollArr = AppState.currentPlotData?.roll || [];
        const headingArr = AppState.currentPlotData?.heading || [];

        if (pitchArr.length && rollArr.length && headingArr.length && idx !== undefined) {
            document.getElementById('attPitch').innerText =
                (pitchArr[idx] !== undefined ? Number(pitchArr[idx]).toFixed(1) : '--') + ' °';

            document.getElementById('attRoll').innerText =
                (rollArr[idx] !== undefined ? Number(rollArr[idx]).toFixed(1) : '--') + ' °';

            document.getElementById('attHeading').innerText =
                (headingArr[idx] !== undefined ? Number(headingArr[idx]).toFixed(1) : '--') + ' °';
        }

        // --- Drive 3D Model Rotation and Position ---
        if (window.updateAircraft3D && idx !== undefined) {
            const pitchVal = pitchArr[idx] || 0;
            const rollVal = rollArr[idx] || 0;
            const headingVal = headingArr[idx] || 0;
            const magVar = AppState.currentPlotData.mag_variance?.[idx] || -13;
            const trueHeading = headingVal - magVar;

            const lat = AppState.map.data.lat ? AppState.map.data.lat[idx] : 0;
            const lon = AppState.map.data.lon ? AppState.map.data.lon[idx] : 0;
            const alt = AppState.map.data.alt ? AppState.map.data.alt[idx] : 0;

            window.updateAircraft3D(pitchVal, rollVal, trueHeading, lat, lon, alt);
        }

        // DIRECT INDEX MATCH
        if (pt.pointIndex !== undefined && AppState.map.data.lat && AppState.map.data.lon) {
            const mapLat = AppState.map.data.lat[idx];
            const mapLon = AppState.map.data.lon[idx];

            const mapDiv = document.getElementById('mapGraph');
            if (mapDiv) {
                let aircraftIndex = window._mapMarkerTraceIndex || 0;
                try {
                    Plotly.restyle('mapGraph', {
                        lat: [[mapLat]],
                        lon: [[mapLon]]
                    }, [aircraftIndex]);
                } catch (e) {
                    console.error("Direct marker move failed:", e);
                }

                if (AppState.map.followAircraft && !AppState.map.isMapPanning) {
                    AppState.map.isMapPanning = true;
                    Plotly.relayout('mapGraph', {
                        'mapbox.center.lat': mapLat,
                        'mapbox.center.lon': mapLon
                    });

                    // Unlock after 50ms
                    setTimeout(() => { AppState.map.isMapPanning = false; }, 50);
                }
            }
            document.getElementById('mapScrubber').value = idx;
        }

        // Sync other plots using the new clean logic
        if (xVal !== undefined) {
            const t = parseFloat(xVal);
            syncTooltips(xVal);
            syncAircraftToTime(t);
        }
    });
    graphDiv.on('plotly_unhover', function(eventdata) {
        // CRITICAL FIX: Ignore programmatic unhovers
        if (eventdata && !eventdata.event) return;

        clearTooltips(graphDiv.id);
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
}

function updateGlobalUI(data) {
    // Render Map
    renderMap(data);

    // Update Text Stats
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

    document.getElementById('aircraftDataCard').classList.remove('d-none');
}

// 7. Core Analysis & Plotting Function
// function triggerAnalysis(plotId) {
//     if (!AppState.file.currentName) return;

//     const leftSignal = document.querySelector(`.left-signal-select[data-plot-id="${plotId}"]`).value;
//     const rightSignal = document.querySelector(`.right-signal-select[data-plot-id="${plotId}"]`).value;
//     const tempUnit = document.getElementById('unitF').checked ? 'F' : 'C';

//     const loader = document.getElementById(`loader-${plotId}`);
//     loader.classList.remove('d-none');

//     const formData = new FormData();
//     formData.append('saved_filename', AppState.file.currentName);
//     formData.append('left_signal', leftSignal);
//     formData.append('right_signal', rightSignal);
//     formData.append('temp_unit', tempUnit);
//     const filters = AppState.ui.filters[plotId] || [];
//     formData.append('filters', JSON.stringify(filters));

//     fetch('/api/analyze_flight', { method: 'POST', body: formData })
//     .then(response => response.json())
//     .then(data => {
//         loader.classList.add('d-none');
//         const graphDiv = document.getElementById(`flightGraph-${plotId}`);

//         // Store plot data globally for cursor sync
//         AppState.currentPlotData = data.plot_data;

//         if (data.error) {
//             alert("Error: " + data.error);
//             return;
//         }

//         // --- Render Plotly Chart ---
//         const traces = [];

//         // Colors: Blues/Greens for the Left Axis, Reds/Oranges/Pinks for the Right Axis
//         const colorsLeft = ['#0d6efd', '#0dcaf0', '#198754', '#20c997'];
//         const colorsRight = ['#dc3545', '#fd7e14', '#ffc107', '#d63384'];
//         // --- NEW: Track exact data limits to prevent shapes from squishing the chart ---
//         let leftMin = Infinity, leftMax = -Infinity;
//         let rightMin = Infinity, rightMax = -Infinity;

//         // Map Left Traces
//         data.plot_data.left_traces.forEach((traceData, idx) => {
//             traceData.y.forEach(v => {
//                 const val = parseFloat(v);
//                 if (!isNaN(val)) {
//                     if (val < leftMin) leftMin = val;
//                     if (val > leftMax) leftMax = val;
//                 }
//             });
//             traces.push({
//                 x: data.plot_data.x, y: traceData.y, name: traceData.name,
//                 type: 'scattergl', mode: 'lines',
//                 line: { color: colorsLeft[idx % colorsLeft.length] }
//             });
//         });

//         // Map Right Traces
//         data.plot_data.right_traces.forEach((traceData, idx) => {
//             traceData.y.forEach(v => {
//                 const val = parseFloat(v);
//                 if (!isNaN(val)) {
//                     if (val < rightMin) rightMin = val;
//                     if (val > rightMax) rightMax = val;
//                 }
//             });
//             traces.push({
//                 x: data.plot_data.x, y: traceData.y, name: traceData.name,
//                 type: 'scattergl', mode: 'lines',
//                 line: { color: colorsRight[idx % colorsRight.length] },
//                 yaxis: 'y2'
//             });
//         });

//         // Helper to add a 5% margin to the bounds so the lines don't hug the edges
//         const padRange = (min, max) => {
//             if (min === Infinity || max === -Infinity) return [0, 100]; // Safe fallback
//             if (min === max) return [min - 10, max + 10]; // Flatline trace fallback
//             const diff = max - min;
//             return [min - (diff * 0.05), max + (diff * 0.05)];
//         };

//         const leftRange = padRange(leftMin, leftMax);
//         const rightRange = padRange(rightMin, rightMax);

//         // const isSplit = document.getElementById(`splitAxis-${plotId}`)?.checked;
//         const showBands = document.getElementById(`showBands-${plotId}`)?.checked;

//         let plotShapes = [];

//         // Only generate and apply shapes if the toggle is checked
//         if (showBands) {
//             const leftShapes = generateBandShapes(leftSignal, 'y');
//             const rightShapes = generateBandShapes(rightSignal, 'y2');
//             plotShapes = [...leftShapes, ...rightShapes];
//         }

//         const layout = {
//             title: false,
//             xaxis: {
//                 title: 'Session Time (seconds)',
//                 gridcolor: '#f0f0f0',
//                 // Add native spikelines to ensure the vertical line ALWAYS draws
//                 showspikes: true,
//                 spikemode: 'across',
//                 spikedash: 'dot',
//                 spikethickness: 1,
//                 spikecolor: '#888',
//                 anchor: isSplit ? 'free' : 'y',
//                 position: 0
//             },
//             yaxis: {
//                 title: data.plot_data.left_name,
//                 titlefont: { color: '#0d6efd' }, tickfont: { color: '#0d6efd' },
//                 gridcolor: '#f0f0f0',
//                 // If split, top plot takes 55% to 100%. Otherwise, full height.
//                 domain: isSplit ? [0.55, 1] : [0, 1],
//                 range: leftRange,      // Assign strict data boundaries
//                 autorange: false
//             },
//             yaxis2: {
//                 title: data.plot_data.right_name,
//                 titlefont: { color: '#dc3545' }, tickfont: { color: '#dc3545' },

//                 // If split: bottom plot takes 0% to 45%. Side is left, no overlaying.
//                 // If combined: overlapping 'y', side is right.
//                 domain: isSplit ? [0, 0.45] : [0, 1],
//                 overlaying: isSplit ? undefined : 'y',
//                 side: isSplit ? 'left' : 'right',
//                 gridcolor: isSplit ? '#f0f0f0' : 'transparent',
//                 anchor: 'x', // Ensures it stays bound to the main time axis
//                 range: rightRange,     // Assign strict data boundaries
//                 autorange: false
//             },
//             shapes: plotShapes,
//             hovermode: 'x unified',
//             margin: { l: 60, r: 60, t: 20, b: 40 },
//             legend: { orientation: "h", y: -0.15 },
//             template: 'plotly_dark'
//         };

//         Plotly.newPlot(graphDiv, traces, layout, {responsive: true, doubleClick: 'reset'});

//         if (window._crosshairX !== null && window._crosshairX !== undefined) {
//             updateCrosshairs(window._crosshairX);
//         }

//         graphDiv.on('plotly_hover', function(eventdata) {
//             // CRITICAL FIX: If this event was triggered by our code (no mouse event), ignore it.
//             // This prevents the infinite loop that breaks the tooltips.
//             if (!eventdata || !eventdata.event) return;

//             if (!eventdata.points || eventdata.points.length === 0) return;
//             const pt = eventdata.points[0];
//             const idx = pt.pointIndex;
//             const xVal = pt.x;

//             const pitchArr = AppState.currentPlotData?.pitch || [];
//             const rollArr = AppState.currentPlotData?.roll || [];
//             const headingArr = AppState.currentPlotData?.heading || [];

//             if (pitchArr.length && rollArr.length && headingArr.length && idx !== undefined) {
//                 document.getElementById('attPitch').innerText =
//                     (pitchArr[idx] !== undefined ? Number(pitchArr[idx]).toFixed(1) : '--') + ' °';

//                 document.getElementById('attRoll').innerText =
//                     (rollArr[idx] !== undefined ? Number(rollArr[idx]).toFixed(1) : '--') + ' °';

//                 document.getElementById('attHeading').innerText =
//                     (headingArr[idx] !== undefined ? Number(headingArr[idx]).toFixed(1) : '--') + ' °';
//             }

//             // --- Drive 3D Model Rotation and Position ---
//             if (window.updateAircraft3D && idx !== undefined) {
//                 const pitchVal = pitchArr[idx] || 0;
//                 const rollVal = rollArr[idx] || 0;
//                 const headingVal = headingArr[idx] || 0;
//                 const magVar = AppState.currentPlotData.mag_variance?.[idx] || -13;
//                 const trueHeading = headingVal - magVar;

//                 const lat = AppState.map.data.lat ? AppState.map.data.lat[idx] : 0;
//                 const lon = AppState.map.data.lon ? AppState.map.data.lon[idx] : 0;
//                 const alt = AppState.map.data.alt ? AppState.map.data.alt[idx] : 0;

//                 window.updateAircraft3D(pitchVal, rollVal, trueHeading, lat, lon, alt);
//             }

//             // DIRECT INDEX MATCH
//             if (pt.pointIndex !== undefined && AppState.map.data.lat && AppState.map.data.lon) {
//                 const mapLat = AppState.map.data.lat[idx];
//                 const mapLon = AppState.map.data.lon[idx];

//                 const mapDiv = document.getElementById('mapGraph');
//                 if (mapDiv) {
//                     let aircraftIndex = window._mapMarkerTraceIndex || 0;
//                     try {
//                         Plotly.restyle('mapGraph', {
//                             lat: [[mapLat]],
//                             lon: [[mapLon]]
//                         }, [aircraftIndex]);
//                     } catch (e) {
//                         console.error("Direct marker move failed:", e);
//                     }

//                     if (AppState.map.followAircraft && !AppState.map.isMapPanning) {
//                         AppState.map.isMapPanning = true;
//                         Plotly.relayout('mapGraph', {
//                             'mapbox.center.lat': mapLat,
//                             'mapbox.center.lon': mapLon
//                         });

//                         // Unlock after 100ms
//                         setTimeout(() => { AppState.map.isMapPanning = false; }, 100);
//                     }
//                 }
//             }

//             // Sync other plots using the new clean logic
//             if (xVal !== undefined) {
//                 const t = parseFloat(xVal);
//                 syncTooltips(xVal);
//                 syncAircraftToTime(t);
//             }
//         });

//         graphDiv.on('plotly_unhover', function(eventdata) {
//             // CRITICAL FIX: Ignore programmatic unhovers
//             if (eventdata && !eventdata.event) return;

//             clearTooltips(graphDiv.id);
//         });

//         // 2. Sync Relayout (Zoom / Pan)
//         graphDiv.on('plotly_relayout', function(eventdata) {
//             if (window._isZoomSyncing) return;
//             window._isZoomSyncing = true;

//             let update = null;
//             if (eventdata['xaxis.range[0]'] !== undefined) {
//                 update = {
//                     'xaxis.range[0]': eventdata['xaxis.range[0]'],
//                     'xaxis.range[1]': eventdata['xaxis.range[1]']
//                 };
//             } else if (eventdata['xaxis.autorange'] !== undefined) {
//                 update = { 'xaxis.autorange': true };
//             }

//             if (update) {
//                 const promises = [];
//                 document.querySelectorAll('[id^="flightGraph-"]').forEach(plot => {
//                     if (plot.id !== graphDiv.id && !plot.classList.contains('d-none') && plot.data) {
//                         promises.push(Plotly.relayout(plot.id, update));
//                     }
//                 });
//                 // Release lock when all plots finish updating
//                 Promise.all(promises).then(() => { window._isZoomSyncing = false; });
//             } else {
//                 window._isZoomSyncing = false;
//             }
//         });

//         // --- Render Map (Flight Path) ---
//         renderMap(data);

//         // --- Update Summary Stats ---
//         document.getElementById('statFlightId').innerText = `Flight: ${data.stats.flight_id}`;
        // document.getElementById('statsList').innerHTML = `
        //     <div class="col-sm-4 mb-3"><strong>Duration:</strong><br>${data.stats.duration_min} min</div>
        //     <div class="col-sm-4 mb-3"><strong>Total Fuel:</strong><br>${data.stats.total_fuel} gal</div>
        //     <div class="col-sm-4 mb-3"><strong>Avg Flow:</strong><br>${data.stats.avg_fuel_flow} gal/hr</div>
        //     <div class="col-sm-4 mb-3"><strong>Avg MPG:</strong><br><span class="text-success fw-bold">${data.stats.avg_mpg} nm/gal</span></div>
        //     <div class="col-sm-4 mb-3"><strong>Distance Traveled:</strong><br>${data.stats.distance_traveled.toFixed(1)} mi</div>
        //     <div class="col-sm-4 mb-3"><strong>Max RPM:</strong><br>
        //         <span style="
        //             ${data.stats.max_rpm > 2750 ? 'color: red; font-weight: bold;' :
        //               data.stats.max_rpm >= 2700 ? 'color: orange;' :
        //               'color: green;'}
        //         ">
        //             ${data.stats.max_rpm}
        //         </span>
        //     </div>
        //     <div class="col-sm-4 mb-3"><strong>Max CHT:</strong><br>
        //         <span style="
        //             ${data.stats.max_cht > 450 ? 'color: red; font-weight: bold;' :
        //               data.stats.max_cht > 420 ? 'color: orange;' :
        //               data.stats.max_cht < 400 ? 'color: green;' : ''}
        //         ">
        //             ${data.stats.max_cht} °F
        //         </span>
        //     </div>
        // `;

        // // Always show the aircraft card once analysis runs
        // document.getElementById('aircraftDataCard').classList.remove('d-none');
        // document.getElementById('aircraftDataPlaceholder').classList.add('d-none');

        // const pitch = data.plot_data?.pitch || [];
        // const roll = data.plot_data?.roll || [];
        // const heading = data.plot_data?.heading || [];

        // const idx = Math.max(0, pitch.length - 1);

        // document.getElementById('attPitch').innerText =
        //     (pitch[idx] !== undefined ? Number(pitch[idx]).toFixed(1) : '--') + ' °';

        // document.getElementById('attRoll').innerText =
        //     (roll[idx] !== undefined ? Number(roll[idx]).toFixed(1) : '--') + ' °';

        // document.getElementById('attHeading').innerText =
        //     (heading[idx] !== undefined ? Number(heading[idx]).toFixed(1) : '--') + ' °';

        // // --- ALWAYS initialize 3D viewer if not already initialized ---
        // if (window.init3DViewer) {
        //     window.init3DViewer();
        // }
//     })
//     .catch(err => {
//         alert(err);
//         console.error(err);
//         loader.classList.add('d-none');
//     });
// }

function renderPlotFilters(plotId) {
    const card = document.getElementById(`plotCard-${plotId}`);
    if (!card) return;

    const list = card.querySelector('.filter-list');
    list.innerHTML = '';

    const filters = AppState.ui.filters[plotId] || [];

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
    AppState.ui.filters[plotId].splice(index, 1);
    renderPlotFilters(plotId);
    triggerAnalysis(plotId);
}

function plotXY() {
    if (!AppState.file.currentName) return;

    const xSignal = document.getElementById('xyXSelect').value;
    const ySignal = document.getElementById('xyYSelect').value;
    const tempUnit = document.getElementById('unitF').checked ? 'F' : 'C';

    const overlay = document.getElementById('xyOverlayToggle')?.checked;

    const requestData = (filters) => {
        const formData = new FormData();
        formData.append('saved_filename', AppState.file.currentName);
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
                type: 'scattergl',
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
                type: 'scattergl',
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
        requestData(AppState.ui.xyFilters)
            .then(data => {
                if (data.error) return alert(data.error);
                renderPlot(null, data);
            });
    } else {
        Promise.all([
            requestData([]),
            requestData(AppState.ui.xyFilters)
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

    AppState.ui.xyFilters.push({ signal, op, value });
    renderXYFilters();
    plotXY();
}

function removeXYFilter(index) {
    AppState.ui.xyFilters.splice(index, 1);
    renderXYFilters();
    plotXY();
}

function clearXYFilters() {
    AppState.ui.xyFilters = [];
    renderXYFilters();
    plotXY();
}

function renderXYFilters() {
    const list = document.getElementById('xyFilterList');
    if (!list) return;

    list.innerHTML = '';

    AppState.ui.xyFilters.forEach((f, idx) => {
        const li = document.createElement('li');
        li.className = "list-group-item d-flex justify-content-between align-items-center p-1";
        li.innerHTML = `
            <span>${f.signal} ${f.op} ${f.value}</span>
            <button class="btn btn-sm btn-outline-danger" onclick="removeXYFilter(${idx})">✖</button>
        `;
        list.appendChild(li);
    });
}

// --- SIGNAL BANDS EDITOR LOGIC ---
let editingBands = {};
let currentBandSignal = "";

function populateAvailableSignalsDropdown() {
    const select = document.getElementById('newBandSignalSelect');
    if (!select) return;

    select.innerHTML = '';

    if (!AppState.file.signalList || AppState.file.signalList.length === 0) {
        select.options.add(new Option("Load a flight first", ""));
        select.disabled = true;
        return;
    }

    select.disabled = false;

    // Sort them alphabetically to make them easier to find
    const sortedSignals = [...AppState.file.signalList].sort();
    sortedSignals.forEach(sig => {
        select.options.add(new Option(sig, sig));
    });
}

// Helper to convert named colors (like "red") to hex so the HTML color picker works
function normalizeColor(c) {
    const map = { "white": "#ffffff", "yellow": "#ffff00", "green": "#00ff00", "red": "#ff0000" };
    return map[c?.toLowerCase()] || c || "#ffffff";
}

function openSignalBandsModal() {
    // 1. Create a deep working copy of the live bands
    editingBands = JSON.parse(JSON.stringify(SIGNAL_BANDS));

    // Normalize colors for the UI
    for (let sig in editingBands) {
        editingBands[sig].forEach(b => {
            if (b.color) b.color = normalizeColor(b.color);
        });
    }

    populateBandSignalSelect();
    populateAvailableSignalsDropdown(); // <--- ADD THIS LINE

    const el = document.getElementById('signalBandsModal');
    const modal = new bootstrap.Modal(el);
    modal.show();
}

function populateBandSignalSelect() {
    const select = document.getElementById('bandSignalSelect');
    select.innerHTML = '';
    const signals = Object.keys(editingBands).sort();

    signals.forEach(sig => {
        select.options.add(new Option(sig, sig));
    });

    if (signals.length > 0) {
        // Default to the current selection or the first one available
        if (!signals.includes(currentBandSignal)) {
            currentBandSignal = signals[0];
        }
        select.value = currentBandSignal;
        renderBands();
    } else {
        currentBandSignal = "";
        document.getElementById('bandRowsContainer').innerHTML = '<div class="text-muted small p-2">No signals found. Add one above.</div>';
        document.getElementById('currentSignalLabel').innerText = "None Selected";
    }
}

function switchBandSignal() {
    currentBandSignal = document.getElementById('bandSignalSelect').value;
    renderBands();
}

function addNewBandSignal() {
    const select = document.getElementById('newBandSignalSelect');
    const newSig = select.value;

    if (!newSig) return;

    // Create an empty array for the new signal if it doesn't exist
    if (!editingBands[newSig]) {
        editingBands[newSig] = [];
    }

    currentBandSignal = newSig;
    populateBandSignalSelect();
}

function renderBands() {
    const container = document.getElementById('bandRowsContainer');
    document.getElementById('currentSignalLabel').innerText = currentBandSignal;

    const bands = editingBands[currentBandSignal] || [];
    container.innerHTML = '';

    if (bands.length === 0) {
        container.innerHTML = '<div class="text-muted small text-center my-3">No bands configured for this signal yet.</div>';
        return;
    }

    // Inject a row for every configured band
    bands.forEach((b, idx) => {
        const row = document.createElement('div');
        row.className = "row g-2 mb-2 pb-2 border-bottom border-secondary align-items-end";
        row.innerHTML = `
            <div class="col-3">
                <label class="small text-muted mb-1">Min (Leave blank for -∞</label>
                <input type="number" step="any" class="form-control form-control-sm bg-dark text-light border-secondary"
                       value="${b.min !== undefined ? b.min : ''}"
                       onchange="updateBandData(${idx}, 'min', this.value)">
            </div>
            <div class="col-3">
                <label class="small text-muted mb-1">Max (Leave blank for +∞</label>
                <input type="number" step="any" class="form-control form-control-sm bg-dark text-light border-secondary"
                       value="${b.max !== undefined ? b.max : ''}"
                       onchange="updateBandData(${idx}, 'max', this.value)">
            </div>
            <div class="col-4">
                <label class="small text-muted mb-1">Band Color</label>
                <div class="d-flex gap-1">
                    <!-- Visual Color Picker -->
                    <input type="color" class="form-control form-control-sm form-control-color bg-dark border-secondary p-0"
                           style="width: 35px;" value="${b.color || '#ffffff'}"
                           onchange="updateBandData(${idx}, 'color', this.value); this.nextElementSibling.value = this.value;">
                    <!-- Hex Text Input (Synced) -->
                    <input type="text" class="form-control form-control-sm bg-dark text-light border-secondary font-monospace"
                           value="${b.color || '#ffffff'}"
                           onchange="updateBandData(${idx}, 'color', this.value); this.previousElementSibling.value = this.value;">
                </div>
            </div>
            <div class="col-2">
                <button class="btn btn-sm btn-outline-danger w-100" onclick="removeBandRow(${idx})">Remove</button>
            </div>
        `;
        container.appendChild(row);
    });
}

// Live update the working JSON object when an input changes
function updateBandData(idx, field, value) {
    if (!editingBands[currentBandSignal]) return;

    if (field === 'min' || field === 'max') {
        if (value === "") {
            // If the user clears the box, delete the limit entirely
            delete editingBands[currentBandSignal][idx][field];
        } else {
            editingBands[currentBandSignal][idx][field] = parseFloat(value);
        }
    } else {
        editingBands[currentBandSignal][idx][field] = value;
    }
}

function addBandRow() {
    if (!currentBandSignal) return;
    if (!editingBands[currentBandSignal]) editingBands[currentBandSignal] = [];

    // Add a default green band
    editingBands[currentBandSignal].push({ color: '#00ff00' });
    renderBands();
}

function removeBandRow(idx) {
    if (!editingBands[currentBandSignal]) return;
    editingBands[currentBandSignal].splice(idx, 1);
    renderBands();
}

function saveSignalBands() {
    const errorDiv = document.getElementById('signalBandsError');
    errorDiv.classList.add('d-none');

    // Filter out completely empty signals from the final save
    const cleanedBands = {};
    for (let sig in editingBands) {
        if (editingBands[sig].length > 0) {
            cleanedBands[sig] = editingBands[sig];
        }
    }

    // 1. Update the live graph variables
    SIGNAL_BANDS = cleanedBands;
    updateAllPlots();

    // 2. Transmit to Python backend to overwrite signal_bands.js
    fetch('/api/save_signal_bands', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(SIGNAL_BANDS)
    })
    .then(res => res.json())
    .then(data => {
        if (data.error) {
            alert("Error saving file to server: " + data.error);
        } else {
            const el = document.getElementById('signalBandsModal');
            const modal = bootstrap.Modal.getInstance(el);
            if (modal) modal.hide();
        }
    })
    .catch(err => {
        console.error(err);
        alert("Network error while trying to save bands.");
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

    if (!AppState.file.currentName) {
        resultBox.innerText = "No flight loaded.";
        return;
    }

    // Store calibration range globally for map highlight
    AppState.calibration.start = start;
    AppState.calibration.end = end;

    resultBox.innerText = "Running calibration analysis...";

    const formData = new FormData();
    formData.append('saved_filename', AppState.file.currentName);
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
                    <div class="col-md-6"><strong>Start Time:</strong><br>${formatMMSS(AppState.calibration.start)}</div>
                    <div class="col-md-6"><strong>End Time:</strong><br>${formatMMSS(AppState.calibration.end)}</div>
                </div>
                <div class="row">
                    <div class="col-md-4"><strong>CAS Correction:</strong><br>${parsed['CAS Correction'] || 'N/A'}</div>
                    <div class="col-md-4"><strong>Uncorrected TAS:</strong><br>${parsed['Uncorr. Avg TAS'] || 'N/A'}</div>
                    <div class="col-md-4"><strong>Corrected TAS:</strong><br>${parsed['Corrected Avg TAS'] || 'N/A'}</div>
                </div>
            `;

            statsList.appendChild(block);
        }
        if (AppState.map.lastRenderData) {
            renderMap(AppState.map.lastRenderData);
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
    AppState.map.lastRenderData = data;

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

    const latRaw = new Float32Array(lat);
    const lonRaw = new Float32Array(lon);
    AppState.map.data.lat = latRaw;
    AppState.map.data.lon = lonRaw;

    // --- GLOBAL MAP STATE (needed for hover + sync) ---
    AppState.map.data.length = latRaw.length;
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

    // Ensure altitude always matches lat length for heatmap modes
    // --- CONVERT LAT/LON/ALT TO 3D WORLD ---
    const originLat = latRaw[0];
    const originLon = lonRaw[0];

    const scale = 111320; // meters per degree approx

    const len = latRaw.length;
    window._worldX = new Float32Array(len);
    window._worldY = new Float32Array(len);
    window._worldZ = new Float32Array(len);
    const cleanAlt = new Float32Array(len);

    for (let i = 0; i < len; i++) {
        const dLat = (latRaw[i] - originLat);
        const dLon = (lonRaw[i] - originLon);
        const a = (altRaw && Array.isArray(altRaw)) ? altRaw[i] : null;
        const x = dLon * scale * Math.cos(originLat * Math.PI / 180);
        const z = dLat * scale;
        const y = cleanAlt[i] || 0;
        window._worldX[i] = x;
        window._worldY[i] = y;
        window._worldZ[i] = z;
        cleanAlt[i] = a; // direct index assignment is much faster than .push()
    }
    AppState.map.data.alt = cleanAlt;
    window._mapAirspeed = data.plot_data?.airspeed || null;
    window._mapGroundspeed = data.plot_data?.groundspeed || null;
    window._mapVerticalSpeed = data.plot_data?.vertical_speed || null;

    // --- COLOR MODE RESOLVER ---
    const getColorValues = () => {
        if (AppState.map.colorMode === 'altitude') return AppState.map.data.alt;
        if (AppState.map.colorMode === 'airspeed' && window._mapAirspeed) return window._mapAirspeed;
        if (AppState.map.colorMode === 'groundspeed' && window._mapGroundspeed) return window._mapGroundspeed;
        if (AppState.map.colorMode === 'vertical_speed' && window._mapVerticalSpeed) return window._mapVerticalSpeed;

        // fallback
        return AppState.map.data.alt;
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
            sel.value = AppState.map.colorMode;
            sel.onchange = () => {
                AppState.map.colorMode = sel.value;
                if (AppState.map.lastRenderData) {
                    renderMap(AppState.map.lastRenderData);
                }
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
        AppState.map.colorMode = 'altitude';
    }

    if (colorValues && colorValues.length === lat.length) {
        // SAFER color mapping to prevent NaN/black rendering
        const safeColors = (colorValues || []).map(v => {
            const num = parseFloat(v);
            return isNaN(num) ? NaN : num;
        });

        // Fallback to altitude if selected mode is invalid or empty
        let validVals = safeColors.filter(v => !isNaN(v));
        if (!validVals.length && AppState.map.data.alt) {
            validVals = AppState.map.data.alt.filter(v => !isNaN(v));
        }

        // Final safety fallback to avoid black map
        let cmin, cmax;

        if (AppState.map.colorMode === 'altitude' && AppState.map.data.alt && AppState.map.data.alt.length) {
            const altVals = AppState.map.data.alt.filter(v => !isNaN(v));

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
                color: (AppState.map.colorMode === 'altitude')
                    ? AppState.map.data.alt.map(v => isNaN(v) ? NaN : v)
                    : safeColors,
                colorscale: COLOR_SCALES[AppState.map.colorMode] || 'Turbo',
                reversescale: AppState.map.colorMode === 'altitude',
                showscale: true,
                cmin: (AppState.map.colorMode === 'altitude') ? 0 : cmin,
                cmax: (AppState.map.colorMode === 'altitude') ? 15000 : cmax,
                colorbar: {
                    title: {
                        text: COLOR_LABELS[AppState.map.colorMode] || 'Value'
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

    if (AppState.calibration.start !== null && AppState.calibration.end !== null && window._mapTime) {
        const highlightLat = [];
        const highlightLon = [];

        for (let i = 0; i < window._mapTime.length; i++) {
            const t = Number(window._mapTime[i]);

            if (isNaN(t)) continue;

            let start = AppState.calibration.start;
            let end = AppState.calibration.end;

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
    if (scrubber && AppState.map.data.length) {
        scrubber.max = AppState.map.data.length - 1;
        scrubber.value = 0;
    }
}

function syncAircraftToTime(t) {
    if (!window._mapTime || !AppState.map.data.lat || !AppState.map.data.lon) return;

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

    const lat = AppState.map.data.lat[bestIndex];
    const lon = AppState.map.data.lon[bestIndex];

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
    if (AppState.map.followAircraft) {
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

    AppState.playback.index = idx;
    interpolationTick = 0;

    if (!AppState.map.data.lat || !AppState.map.data.lon) return;

    const lat = AppState.map.data.lat[idx];
    const lon = AppState.map.data.lon[idx];

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
    if (AppState.currentPlotData) {
        const pitch = AppState.currentPlotData.pitch?.[idx] || 0;
        const roll = AppState.currentPlotData.roll?.[idx] || 0;
        const heading = AppState.currentPlotData.heading?.[idx] || 0;
        const magVar = AppState.currentPlotData.mag_variance?.[idx] || -13;
        const trueHeading = heading - magVar

        document.getElementById('attPitch').innerText = pitch.toFixed(1) + ' °';
        document.getElementById('attRoll').innerText = roll.toFixed(1) + ' °';
        document.getElementById('attHeading').innerText = heading.toFixed(1) + ' °';

        if (window.updateAircraft3D) {
            const lat = AppState.map.data.lat ? AppState.map.data.lat[idx] : 0;
            const lon = AppState.map.data.lon ? AppState.map.data.lon[idx] : 0;
            const alt = AppState.map.data.alt ? AppState.map.data.alt[idx] : 0; // Assuming alt is in feet

            window.updateAircraft3D(pitch, roll, trueHeading, lat, lon, alt);
        }
    }

    // Follow mode
    if (AppState.map.followAircraft) {
        Plotly.relayout('mapGraph', {
            'mapbox.center.lat': lat,
            'mapbox.center.lon': lon
        });
    }
}
function togglePlayback() {
    const btn = document.getElementById('playPauseBtn');
    if (AppState.playback.timer) {
        clearInterval(AppState.playback.timer);
        AppState.playback.timer = null;
        if (btn) btn.innerText = '▶ Play';
    } else {
        if (btn) btn.innerText = '⏸ Pause';
        const scrubber = document.getElementById('mapScrubber');
        AppState.playback.index = parseInt(scrubber.value) || 0;

        // Temporarily set this so the speed function knows it is allowed to start
        AppState.playback.timer = true;

        // Start the loop!
        setPlaybackSpeed(AppState.playback.speed);
    }
}

// analyzer.js additions
let interpolationTick = 0;

function setPlaybackSpeed(val) {
    AppState.playback.speed = parseInt(val);

    // Only run if we are actively playing
    if (!AppState.playback.timer) return;

    // Clear existing timer if one is already running
    if (AppState.playback.timer !== true) {
        clearInterval(AppState.playback.timer);
    }

    // ALWAYS run the timer at a safe ~33ms (30 Frames Per Second)
    const baseInterval = 1000 / AppState.playback.fps;

    AppState.playback.timer = setInterval(() => {
        if (!AppState.map.data.lat || AppState.playback.index >= AppState.map.data.lat.length - 1) {
            clearInterval(AppState.playback.timer);
            AppState.playback.timer = null;
            const btn = document.getElementById('playPauseBtn');
            if (btn) btn.innerText = '▶ Play';
            return;
        }

        // Pause the clock if the user is dragging the slider
        if (AppState.playback.isScrubbing) return;

        // 1. Calculate how far we are between the current second and the next
        let t = interpolationTick / AppState.playback.fps;

        // 2. Linear Interpolation (lerp) function
        const lerp = (start, end, amt) => (1 - amt) * start + amt * end;

        // Safely determine the next index to prevent array out-of-bounds errors
        const nextIdx = Math.min(AppState.playback.index + 1, AppState.map.data.lat.length - 1);

        // 3. Interpolate all values
        const currentLat = lerp(AppState.map.data.lat[AppState.playback.index], AppState.map.data.lat[nextIdx], t);
        const currentLon = lerp(AppState.map.data.lon[AppState.playback.index], AppState.map.data.lon[nextIdx], t);
        const currentAlt = lerp(AppState.map.data.alt[AppState.playback.index], AppState.map.data.alt[nextIdx], t);

        const lerpAngle = (a, b, t) => {
            let d = b - a;
            if (d > 180) d -= 360;
            if (d < -180) d += 360;
            return a + d * t;
        };

        const magVar = AppState.currentPlotData?.mag_variance?.[AppState.playback.index] || -13;
        const currentHeading = lerpAngle(AppState.currentPlotData?.heading[AppState.playback.index], AppState.currentPlotData?.heading[nextIdx], t);
        const trueHeading = currentHeading - magVar;
        const currentPitch = lerp(AppState.currentPlotData?.pitch[AppState.playback.index], AppState.currentPlotData?.pitch[nextIdx], t);
        const currentRoll = lerp(AppState.currentPlotData?.roll[AppState.playback.index], window.currentPlotData?.roll[nextIdx], t);

        // 4. Send the SMOOTH data to the 3D model
        if (window.updateAircraft3D) {
            window.updateAircraft3D(currentPitch, currentRoll, trueHeading, currentLat, currentLon, currentAlt);
        }
        document.getElementById('attPitch').innerText = currentPitch.toFixed(1) + ' °';
        document.getElementById('attRoll').innerText = currentRoll.toFixed(1) + ' °';
        document.getElementById('attHeading').innerText = currentHeading.toFixed(1) + ' °';

        // 4.5 Smoothly update the 2D Map Marker
        const mapDiv = document.getElementById('mapGraph');
        if (mapDiv) {
            let aircraftIndex = window._mapMarkerTraceIndex || 0;
            try {
                Plotly.restyle('mapGraph', {
                    lat: [[currentLat]],
                    lon: [[currentLon]]
                }, [aircraftIndex]);
            } catch (e) {}

            // Throttle map camera panning to prevent browser lag (updates every ~5th frame)
            if (AppState.map.followAircraft && Math.floor(interpolationTick) % 6 === 0) {
                Plotly.relayout('mapGraph', {
                    'mapbox.center.lat': currentLat,
                    'mapbox.center.lon': currentLon
                });
            }
        }

        // 5. Advance the clock by the playback speed multiplier!
        interpolationTick += AppState.playback.speed;

        // If we have accrued enough ticks to move forward one (or more) full seconds
        if (interpolationTick >= AppState.playback.fps) {
            const secondsToAdvance = Math.floor(interpolationTick / AppState.playback.fps);
            AppState.playback.index += secondsToAdvance;

            // Keep the remainder for smooth interpolation on the next frame
            interpolationTick = interpolationTick % AppState.playback.fps;

            // Sync the scrubber UI
            const scrubber = document.getElementById('mapScrubber');
            if (scrubber) scrubber.value = AppState.playback.index;
        }

    }, baseInterval);
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

function toggleSidebar() {
    document.body.classList.toggle('sidebar-collapsed');

    // Fire resize events multiple times during the transition
    // for a "live" resizing effect, or once at the end.
    const resizeInterval = setInterval(() => {
        window.dispatchEvent(new Event('resize'));
    }, 50);

    // Stop resizing once the 400ms transition is complete
    setTimeout(() => {
        clearInterval(resizeInterval);
        window.dispatchEvent(new Event('resize'));
    }, 450);
}