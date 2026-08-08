

function getGamiElem(id) {
    const prefixed = 'gami' + id.charAt(0).toUpperCase() + id.slice(1);
    return document.getElementById(prefixed) || document.getElementById(id);
}

// Temp unit toggle event handler (supports both page radio name="tempUnit" and modal radio name="gamiTempUnit")
document.addEventListener('change', (e) => {
    if (e.target && (e.target.name === 'tempUnit' || e.target.name === 'gamiTempUnit')) {
        tempUnit = e.target.value;
        if (currentData) renderGami(currentData);
    }
});

let currentData = null;
let tempUnit = 'F';
let timeWindow = null; // {start, end} based on selection

let timeSelectionState = {
    start: null,
    end: null
};
let clickMarkers = [];
let hoverX = null;

function setTempUnit(u) {
    tempUnit = u;
    if (currentData) {
        renderGami(currentData);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    fetch('/api/saved_flights')
        .then(r => r.json())
        .then(data => {
            const sel = getGamiElem('savedFlights');
            if (!sel) return;

            // Support multiple possible API response shapes
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

            // AUTO-SELECT FIRST FLIGHT AND LOAD IT (Only if standalone page)
            if (sel.options.length > 0 && !document.getElementById('gamiModal')) {
                sel.selectedIndex = 0;
                loadFlight();
            }
        })
        .catch(err => {
            console.error("Failed to load flights:", err);
        });

    const modalEl = document.getElementById('gamiModal');
    if (modalEl) {
        modalEl.addEventListener('shown.bs.modal', () => {
            const timeGraph = getGamiElem('timeGraph');
            const scatterGraph = getGamiElem('scatterGraph');
            if (timeGraph && timeGraph.data) Plotly.Plots.resize(timeGraph);
            if (scatterGraph && scatterGraph.data) Plotly.Plots.resize(scatterGraph);
        });
    }
});

function openGamiModal() {
    const modalEl = document.getElementById('gamiModal');
    if (!modalEl) return;

    // Reset selection state & markers to start fresh every time modal is opened
    timeWindow = null;
    timeSelectionState = { start: null, end: null };
    clickMarkers = [];
    hoverX = null;

    // Purge old Plotly layouts and zoom ranges
    const timeGraph = getGamiElem('timeGraph');
    const scatterGraph = getGamiElem('scatterGraph');
    if (timeGraph) Plotly.purge(timeGraph);
    if (scatterGraph) Plotly.purge(scatterGraph);

    const mainSelect = document.getElementById('savedFlights');
    const gamiSelect = getGamiElem('savedFlights');
    if (mainSelect && gamiSelect) {
        gamiSelect.innerHTML = mainSelect.innerHTML;
        if (mainSelect.value) {
            gamiSelect.value = mainSelect.value;
        } else if (gamiSelect.options.length > 0) {
            gamiSelect.selectedIndex = 0;
        }
    }

    const modal = new bootstrap.Modal(modalEl);
    modal.show();

    loadFlight();
}

function loadFlight() {
    const sel = getGamiElem('savedFlights');
    if (!sel || !sel.value) return;

    const file = sel.value;

    // PIGGYBACK: If the requested flight is already loaded in AppState, render instantly without network fetch!
    if (typeof AppState !== 'undefined' && file === AppState.file.currentName && (AppState.lastAnalysisResponse || AppState.rawData)) {
        renderGami(AppState.lastAnalysisResponse || { rawData: AppState.rawData, plot_data: AppState.currentPlotData });
        return;
    }

    const metricsEl = getGamiElem('metrics');
    if (metricsEl) {
        metricsEl.innerHTML = '<span class="spinner-border spinner-border-sm text-primary"></span> Loading flight data for GAMI analysis...';
    }

    const formData = new FormData();
    formData.append('saved_filename', file);
    formData.append('filters', JSON.stringify([]));

    fetch('/api/analyze_flight', { method: 'POST', body: formData })
        .then(r => r.json())
        .then(renderGami)
        .catch(err => {
            console.error("GAMI load error:", err);
            if (metricsEl) metricsEl.innerText = "Error loading GAMI analysis data.";
        });
}

function renderGami(data) {
    if (data.error) {
        alert(data.error);
        return;
    }

    currentData = data;

    // =====================================================
    // USE RAW DATAFRAME (NOT PLOTTED TRACES)
    // =====================================================
    const df =
        data.rawData ||
        data.raw_data ||
        data.dataframe ||
        data.df;

    // fallback time handling
    const time =
        (df && df.length && (df[0].time !== undefined))
            ? df.map(r => r.time)
            : data.plot_data.x;

    // guard
    const metricsEl = getGamiElem('metrics');
    if (!df || !df.length) {
        if (metricsEl) metricsEl.innerText = "No raw dataframe found in response.";
        return;
    }

    // detect column names
    const keys = Object.keys(df[0]);

    const egtKeys = keys.filter(k => {
        const ku = k.toUpperCase();

        if (!ku.includes("EGT")) return false;

        if (tempUnit === 'F') {
            return ku.includes("F");
        }

        if (tempUnit === 'C') {
            return ku.includes("C");
        }

        return true;
    });

    // Prefer Fuel Flow explicitly (avoid Fuel Pressure confusion)
    const fuelKey = keys.find(k => {
        const kl = k.toLowerCase();
        return kl.includes("fuel flow");
    });

    // build EGT series from dataframe
    const egtTraces = egtKeys.map(k => ({
        name: k,
        y: df.map(r => r[k])
    }));

    const fuelTrace = fuelKey ? {
        name: fuelKey,
        y: df.map(r => r[fuelKey])
    } : null;

    if (!egtTraces.length) {
        if (metricsEl) metricsEl.innerText = `No EGT data found for ${tempUnit} units.`;
        return;
    }

    // METRICS
    const avgs = egtTraces.map(t => {
        const avg = t.y.reduce((a,b)=>a+b,0)/t.y.length;
        return { name: t.name, avg };
    });

    const values = avgs.map(a => a.avg);
    const spread = Math.max(...values) - Math.min(...values);

    // ---- GAMI Spread Calculation ----

    // ---- Peak EGT Calculation ----
    let peakEgtSummary = "N/A";

    if (timeWindow && timeWindow.start != null && timeWindow.end != null) {
        const maskPeak = time.map(t =>
            t >= timeWindow.start && t <= timeWindow.end
        );

        const peakEgts = [];

        egtTraces.forEach((t) => {
            let maxY = null;

            for (let j = 0; j < t.y.length; j++) {
                if (!maskPeak[j]) continue;

                if (maxY === null || t.y[j] > maxY) {
                    maxY = t.y[j];
                }
            }

            if (maxY !== null) {
                peakEgts.push(`${t.name}: ${maxY.toFixed(1)}`);
            }
        });

        if (peakEgts.length) {
            peakEgtSummary = peakEgts.join('<br>');
        }
    }

    let gamiSpreadText = "N/A";

    // compute GAMI spread ONLY when time window exists
    if (timeWindow && timeWindow.start != null && timeWindow.end != null && fuelTrace) {

        const mask2 = time.map(t =>
            t >= timeWindow.start && t <= timeWindow.end
        );

        const peakFuelFlows = [];

        egtTraces.forEach((t) => {
            let maxY = null;
            let maxIdx = null;

            for (let j = 0; j < t.y.length; j++) {
                if (!mask2[j]) continue;

                if (maxY === null || t.y[j] > maxY) {
                    maxY = t.y[j];
                    maxIdx = j;
                }
            }

            if (maxIdx !== null) {
                peakFuelFlows.push(fuelTrace.y[maxIdx]);
            }
        });

        if (peakFuelFlows.length) {
            const maxFF = Math.max(...peakFuelFlows);
            const minFF = Math.min(...peakFuelFlows);
            const gamiSpread = maxFF - minFF;

            gamiSpreadText = gamiSpread.toFixed(2);
        }
    }

    if (metricsEl) {
        if (timeSelectionState.start !== null && timeSelectionState.end === null) {
            metricsEl.innerHTML = `
                <b>Overall EGT Spread:</b> ${spread.toFixed(1)} °${tempUnit}<br>
                <b>Start Time:</b> ${Number(timeSelectionState.start).toFixed(1)}s <span class="text-success ms-2 fw-bold">← Click a second point on the graph to set End Time</span>
            `;
        } else if (timeWindow && timeWindow.start != null && timeWindow.end != null) {
            metricsEl.innerHTML = `
                <b>Overall EGT Spread:</b> ${spread.toFixed(1)} °${tempUnit}<br>
                <b>GAMI Spread (ΔFF):</b> <span class="text-primary fw-bold fs-6">${gamiSpreadText} gal/hr</span><br>
                <span class="text-muted small">Window: ${Number(timeSelectionState.start).toFixed(1)}s – ${Number(timeSelectionState.end).toFixed(1)}s (${(timeSelectionState.end - timeSelectionState.start).toFixed(1)}s)</span><br><br>
                <b>Peak EGTs:</b><br>
                ${peakEgtSummary}
            `;
        } else {
            metricsEl.innerHTML = `
                <b>Overall EGT Spread:</b> ${spread.toFixed(1)} °${tempUnit}<br>
                <span class="text-muted small">Click any point on the EGT vs Time graph below to select a Lean Find window.</span>
            `;
        }
    }

    // TIME SERIES
    const timeTraces = egtTraces.map(t => ({
        x: time,
        y: t.y,
        mode: 'lines',
        name: t.name,
        hoverinfo: 'none'
    }));

    if (fuelTrace) {
        timeTraces.push({
            x: time,
            y: fuelTrace.y,
            mode: 'lines',
            name: fuelTrace.name,
            yaxis: 'y2',
            hoverinfo: 'none'
        });
    }

    const timeGraphDiv = getGamiElem('timeGraph');
    if (timeGraphDiv) {
        // PRESERVE EXISTING ZOOM LEVEL ON TIME GRAPH
        const currentTimeXRange = timeGraphDiv.layout?.xaxis?.range ? [...timeGraphDiv.layout.xaxis.range] : null;
        const currentTimeYRange = timeGraphDiv.layout?.yaxis?.range ? [...timeGraphDiv.layout.yaxis.range] : null;
        const currentTimeY2Range = timeGraphDiv.layout?.yaxis2?.range ? [...timeGraphDiv.layout.yaxis2.range] : null;

        const timeLayout = {
            title: "EGT + Fuel Flow vs Time",
            xaxis: { title: "Time" },
            yaxis: { title: `EGT (°${tempUnit})` },
            yaxis2: {
                title: "Fuel Flow",
                overlaying: 'y',
                side: 'right'
            },
            hovermode: 'x',
            margin: { l: 60, r: 60, t: 40, b: 40 },
            legend: { orientation: "h", y: -0.15 }
        };

        if (currentTimeXRange) {
            timeLayout.xaxis.range = currentTimeXRange;
            timeLayout.xaxis.autorange = false;
        }
        if (currentTimeYRange) {
            timeLayout.yaxis.range = currentTimeYRange;
            timeLayout.yaxis.autorange = false;
        }
        if (currentTimeY2Range) {
            timeLayout.yaxis2.range = currentTimeY2Range;
            timeLayout.yaxis2.autorange = false;
        }

        Plotly.react(timeGraphDiv, timeTraces, timeLayout);

        if (timeGraphDiv.removeAllListeners) {
            timeGraphDiv.removeAllListeners('plotly_click');
        }

        // Click-based time window selection
        timeGraphDiv.on('plotly_click', function(eventdata) {
            if (!eventdata.points || eventdata.points.length === 0) return;

            const x = eventdata.points[0].x;

            // Check if start point is set and currently visible on the active plot zoom range
            const currentRange = timeGraphDiv.layout?.xaxis?.range;
            const isStartVisible = timeSelectionState.start !== null && (
                !currentRange || (timeSelectionState.start >= currentRange[0] && timeSelectionState.start <= currentRange[1])
            );

            // First click (or restart if both set or start is not visible on screen)
            if (timeSelectionState.start === null || timeSelectionState.end !== null || !isStartVisible) {
                timeSelectionState.start = x;
                timeSelectionState.end = null;
                timeWindow = null;
                clickMarkers = [x];
            } else {
                // Second click: set end time (only if start time is visible on the plot)
                timeSelectionState.end = x;

                if (timeSelectionState.end < timeSelectionState.start) {
                    const tmp = timeSelectionState.start;
                    timeSelectionState.start = timeSelectionState.end;
                    timeSelectionState.end = tmp;
                }

                timeWindow = {
                    start: timeSelectionState.start,
                    end: timeSelectionState.end
                };
                clickMarkers = [timeSelectionState.start, timeSelectionState.end];
            }

            drawSelectionBox();
            renderGami(currentData);
        });

    function updateVerticalCursor(x) {
        Plotly.relayout(getGamiElem('timeGraph'), {
            shapes: [
                {
                    type: 'line',
                    x0: x,
                    x1: x,
                    y0: 0,
                    y1: 1,
                    yref: 'paper',
                    line: {
                        color: 'rgba(0,0,0,0.4)',
                        width: 1,
                        dash: 'dot'
                    }
                }
            ]
        });
    }

    function drawSelectionBox() {
        const shapes = [];

        // SHADED SELECTION REGION (between start and end)
        if (timeSelectionState.start !== null && timeSelectionState.end !== null) {
            shapes.push({
                type: 'rect',
                x0: timeSelectionState.start,
                x1: timeSelectionState.end,
                y0: 0,
                y1: 1,
                yref: 'paper',
                fillcolor: 'rgba(25, 135, 84, 0.15)',
                line: { width: 0 }
            });
        }

        // START LINE (green)
        if (timeSelectionState.start !== null) {
            shapes.push({
                type: 'line',
                x0: timeSelectionState.start,
                x1: timeSelectionState.start,
                y0: 0,
                y1: 1,
                yref: 'paper',
                line: {
                    color: '#198754',
                    width: 2
                }
            });
        }

        // END LINE (red)
        if (timeSelectionState.end !== null) {
            shapes.push({
                type: 'line',
                x0: timeSelectionState.end,
                x1: timeSelectionState.end,
                y0: 0,
                y1: 1,
                yref: 'paper',
                line: {
                    color: '#dc3545',
                    width: 2
                }
            });
        }

        Plotly.relayout(getGamiElem('timeGraph'), { shapes });
    }
    function drawCursor(plotId, x) {
        const shapes = [];

        // CLICK MARKERS (black persistent clicks)
        clickMarkers.forEach(v => {
            shapes.push({
                type: 'line',
                x0: v,
                x1: v,
                y0: 0,
                y1: 1,
                yref: 'paper',
                line: {
                    color: 'black',
                    width: 2
                }
            });
        });

        // SELECTION START (green)
        if (timeSelectionState.start !== null) {
            shapes.push({
                type: 'line',
                x0: timeSelectionState.start,
                x1: timeSelectionState.start,
                y0: 0,
                y1: 1,
                yref: 'paper',
                line: {
                    color: 'green',
                    width: 2
                }
            });
        }

        // SELECTION END (red)
        if (timeSelectionState.end !== null) {
            shapes.push({
                type: 'line',
                x0: timeSelectionState.end,
                x1: timeSelectionState.end,
                y0: 0,
                y1: 1,
                yref: 'paper',
                line: {
                    color: 'red',
                    width: 2
                }
            });
        }

        // CURSOR LINE (hover)
        if (x !== null && x !== undefined) {
            shapes.push({
                type: 'line',
                x0: x,
                x1: x,
                y0: 0,
                y1: 1,
                yref: 'paper',
                line: {
                    color: 'rgba(0,0,0,0.35)',
                    width: 1,
                    dash: 'dot'
                }
            });
        }

        Plotly.relayout(getGamiElem(plotId), { shapes });
    }

    function syncCursor(x) {
        hoverX = x;
        drawCursor('timeGraph', x);
        drawCursor('scatterGraph', x);
    }

    // mouse hover cursor
    timeGraphDiv.on('plotly_hover', function(eventdata) {
        if (eventdata && eventdata.points && eventdata.points.length > 0) {
            syncCursor(eventdata.points[0].x);
        }
    });

    // remove cursor when leaving plot
    timeGraphDiv.on('plotly_unhover', function() {
        // restore persistent selection + click markers without cursor
        drawSelectionBox();
    });
    }



    // SCATTER (APPLY TIME WINDOW FILTER IF SET)
    if (fuelTrace) {
        const colors = ['#0d6efd','#198754','#dc3545','#fd7e14'];

        const mask = time.map(t => {
            if (!timeWindow) return true;
            return t >= timeWindow.start && t <= timeWindow.end;
        });

        // Enhanced scatter traces: lines, plus dot at each peak
        const scatter = [];

        egtTraces.forEach((t, i) => {
            const color = colors[i % colors.length];

            // main line
            scatter.push({
                x: fuelTrace.y.filter((_, idx) => mask[idx]),
                y: t.y.filter((_, idx) => mask[idx]),
                mode: 'lines',
                type: 'scatter',
                name: t.name,
                hoverinfo: 'none',
                line: {
                    shape: 'spline',
                    width: 2,
                    color: color
                }
            });

            // peak dot (only if window selected)
            if (timeWindow && timeWindow.start != null && timeWindow.end != null) {

                const mask2 = time.map(ti =>
                    ti >= timeWindow.start && ti <= timeWindow.end
                );

                let maxY = null;
                let maxIdx = null;

                for (let j = 0; j < t.y.length; j++) {
                    if (!mask2[j]) continue;

                    if (maxY === null || t.y[j] > maxY) {
                        maxY = t.y[j];
                        maxIdx = j;
                    }
                }

                if (maxIdx !== null && fuelTrace) {
                    scatter.push({
                        x: [fuelTrace.y[maxIdx]],
                        y: [maxY],
                        mode: 'markers',
                        marker: {
                            size: 8,
                            color: color,
                            line: {
                                width: 1,
                                color: 'black'
                            }
                        },
                        showlegend: false,
                        hoverinfo: 'skip'
                    });
                }
            }
        });

        // =====================================================
        // PEAK ANNOTATIONS (ONLY AFTER 2-CLICK WINDOW SELECTION)
        // =====================================================
        let annotations = [];

        if (timeWindow && timeWindow.start != null && timeWindow.end != null) {
            const mask2 = time.map(t =>
                t >= timeWindow.start && t <= timeWindow.end
            );

            egtTraces.forEach((t, i) => {
                let maxY = null;
                let maxIdx = null;

                for (let j = 0; j < t.y.length; j++) {
                    if (!mask2[j]) continue;
                    if (maxY === null || t.y[j] > maxY) {
                        maxY = t.y[j];
                        maxIdx = j;
                    }
                }

                if (maxIdx !== null && fuelTrace) {
                    const fuelVal = fuelTrace.y[maxIdx];
                    const color = colors[i % colors.length];
                    annotations.push({
                        x: fuelVal,
                        y: maxY,
                        text: (fuelVal ? `${t.name}: ${fuelVal.toFixed(1)}` : t.name),
                        showarrow: true,
                        arrowhead: 2,
                        arrowcolor: color,
                        ax: 40,
                        ay: -40,
                        textangle: 0,
                        bgcolor: color,
                        bordercolor: color,
                        borderwidth: 1,
                        font: {
                            size: 10,
                            color: 'white'
                        }
                    });
                }
            });
        }

        // =====================================================
        // SCATTER PLOT (EGT vs FUEL FLOW - SMOOTHED)
        // =====================================================
        const scatterDiv = getGamiElem('scatterGraph');
        if (scatterDiv) {
            const scatterLayout = {
                title: "EGT vs Fuel Flow",
                xaxis: { title: "Fuel Flow", autorange: 'reversed' },
                yaxis: { title: `EGT (°${tempUnit})` },
                annotations: annotations,
                hovermode: 'closest',
                margin: { l: 60, r: 60, t: 40, b: 40 },
                legend: { orientation: "h", y: -0.15 }
            };

            // ZOOM TO SELECTED REGION AFTER SELECTING START AND END MARKS
            if (timeWindow && timeWindow.start != null && timeWindow.end != null && fuelTrace) {
                const selectedFuelFlows = [];
                const selectedEgts = [];

                egtTraces.forEach(t => {
                    for (let j = 0; j < t.y.length; j++) {
                        if (mask[j]) {
                            const ffVal = parseFloat(fuelTrace.y[j]);
                            const egtVal = parseFloat(t.y[j]);
                            if (!isNaN(ffVal) && ffVal > 0) selectedFuelFlows.push(ffVal);
                            if (!isNaN(egtVal) && egtVal > 0) selectedEgts.push(egtVal);
                        }
                    }
                });

                if (selectedFuelFlows.length && selectedEgts.length) {
                    const minFF = Math.min(...selectedFuelFlows);
                    const maxFF = Math.max(...selectedFuelFlows);
                    const minEGT = Math.min(...selectedEgts);
                    const maxEGT = Math.max(...selectedEgts);

                    const ffPad = Math.max((maxFF - minFF) * 0.08, 0.2);
                    const egtPad = Math.max((maxEGT - minEGT) * 0.08, 5);

                    scatterLayout.xaxis.range = [maxFF + ffPad, Math.max(0, minFF - ffPad)];
                    scatterLayout.xaxis.autorange = false;

                    scatterLayout.yaxis.range = [minEGT - egtPad, maxEGT + egtPad];
                    scatterLayout.yaxis.autorange = false;
                }
            }

            Plotly.react(scatterDiv, scatter, scatterLayout);
        }
    }

}