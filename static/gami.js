

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
        metricsEl.innerHTML = `
            <b>EGT Spread:</b> ${spread.toFixed(1)} °${tempUnit}<br>
            <b>GAMI Spread (ΔFF):</b> ${gamiSpreadText}<br><br>
            <b>Peak EGTs:</b><br>
            ${peakEgtSummary}
        `;
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
            hovermode: false,
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

        // Click-based time window selection
        timeGraphDiv.on('plotly_click', function(eventdata) {
        if (!eventdata.points || eventdata.points.length === 0) return;

        const x = eventdata.points[0].x;

        // add black click marker
        clickMarkers.push(x);

        // CASE 3: reset if both already set
        if (timeSelectionState.start !== null && timeSelectionState.end !== null) {
            timeSelectionState.start = x;
            timeSelectionState.end = null;
            timeWindow = null;

            // reset click markers on new selection
            clickMarkers = [x];

            drawSelectionBox();
            renderGami(currentData);
            return;
        }

        // CASE 1: first click (start)
        if (timeSelectionState.start === null) {
            timeSelectionState.start = x;
            timeSelectionState.end = null;
            timeWindow = null;

            // first click marker
            clickMarkers = [x];
        }
        // CASE 2: second click (end)
        else {
            timeSelectionState.end = x;

            // ensure ordering
            if (timeSelectionState.end < timeSelectionState.start) {
                const tmp = timeSelectionState.start;
                timeSelectionState.start = timeSelectionState.end;
                timeSelectionState.end = tmp;
            }

            timeWindow = {
                start: timeSelectionState.start,
                end: timeSelectionState.end
            };
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

        // CLICK MARKERS (BLACK VERTICAL LINES)
        clickMarkers.forEach(x => {
            shapes.push({
                type: 'line',
                x0: x,
                x1: x,
                y0: 0,
                y1: 1,
                yref: 'paper',
                line: {
                    color: 'black',
                    width: 2
                }
            });
        });

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
                    color: 'green',
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
                    color: 'red',
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
            const currentScatterXRange = scatterDiv.layout?.xaxis?.range ? [...scatterDiv.layout.xaxis.range] : null;
            const currentScatterYRange = scatterDiv.layout?.yaxis?.range ? [...scatterDiv.layout.yaxis.range] : null;

            const scatterLayout = {
                title: "EGT vs Fuel Flow",
                xaxis: { title: "Fuel Flow", autorange: 'reversed'},
                yaxis: { title: `EGT (°${tempUnit})` },
                annotations: annotations,
                hovermode: false,
                margin: { l: 60, r: 60, t: 40, b: 40 },
                legend: { orientation: "h", y: -0.15 }
            };

            if (currentScatterXRange) {
                scatterLayout.xaxis.range = currentScatterXRange;
                scatterLayout.xaxis.autorange = false;
            }
            if (currentScatterYRange) {
                scatterLayout.yaxis.range = currentScatterYRange;
                scatterLayout.yaxis.autorange = false;
            }

            Plotly.react(scatterDiv, scatter, scatterLayout);
        }
    }

}