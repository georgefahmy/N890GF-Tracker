let globalFlights = [];
let sortKey = 'date';
let sortAsc = false;

document.addEventListener("DOMContentLoaded", () => {
    loadMultiFlightStats();

    const searchInput = document.getElementById("searchFlightInput");
    if (searchInput) {
        searchInput.addEventListener("input", filterAndRenderTable);
    }

    const calsSearchInput = document.getElementById("searchAirspeedCalsInput");
    if (calsSearchInput) {
        calsSearchInput.addEventListener("input", renderAirspeedCalsModalTable);
    }
});

function loadMultiFlightStats() {
    const statusEl = document.getElementById("multiStatsStatus");
    if (statusEl) {
        statusEl.style.display = "block";
        statusEl.innerHTML = '<span class="spinner-border spinner-border-sm text-primary"></span> Loading multi-flight analytics...';
    }

    fetch("/api/multi_flight_stats")
        .then(r => r.json())
        .then(data => {
            if (statusEl) statusEl.style.display = "none";
            window.globalFlights = globalFlights = data.flights || [];

            try {
                renderFleetTotals(data.totals || {});
            } catch (e) {
                console.error("Error rendering totals:", e);
            }

            try {
                renderTrendCharts(globalFlights);
            } catch (e) {
                console.error("Error rendering trend charts:", e);
            }

            try {
                filterAndRenderTable();
            } catch (e) {
                console.error("Error rendering flight table:", e);
            }
        })
        .catch(err => {
            console.error("Multi-flight stats error:", err);
            if (statusEl) {
                statusEl.style.display = "block";
                statusEl.innerText = "Error loading flight statistics.";
            }
        });
}

function renderFleetTotals(totals) {
    const setVal = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.innerText = val;
    };

    setVal("totalFlightCount", totals.flight_count || 0);
    setVal("totalHours", (totals.total_hours || 0) + " hrs");
    setVal("totalAirborneHours", (totals.total_airborne_hours || 0) + " hrs");
    setVal("totalMiles", (totals.total_distance_mi || 0).toLocaleString() + " mi");
    setVal("totalFuel", (totals.total_fuel_gal || 0).toLocaleString() + " gal");
    setVal("totalLandings", totals.total_landings || 0);
    setVal("fleetAvgCht", (totals.fleet_avg_cht || "--") + " °F");
}

function renderTrendCharts(flights) {
    if (!flights || flights.length === 0) return;
    if (typeof Plotly === "undefined") {
        console.warn("Plotly library is not loaded. Trend charts will be skipped.");
        return;
    }

    // Chronological order for trend charts (oldest -> newest, sorted by cum_total_hours ascending)
    const chronological = [...flights].sort((a, b) => {
        if (typeof a.cum_total_hours === 'number' && typeof b.cum_total_hours === 'number' && a.cum_total_hours !== b.cum_total_hours) {
            return a.cum_total_hours - b.cum_total_hours;
        }
        const keyA = `${a.date || ''}_${a.filename || ''}`;
        const keyB = `${b.date || ''}_${b.filename || ''}`;
        return keyA.localeCompare(keyB);
    });

    const dateCounts = {};
    chronological.forEach(f => {
        const d = (f.date && f.date.length >= 10) ? f.date.substring(0, 10) : (f.filename ? f.filename.substring(0, 10) : '2026-01-01');
        dateCounts[d] = (dateCounts[d] || 0) + 1;
    });

    const dateSeen = {};
    const dates = chronological.map(f => {
        const d = (f.date && f.date.length >= 10) ? f.date.substring(0, 10) : (f.filename ? f.filename.substring(0, 10) : '2026-01-01');
        if (dateCounts[d] > 1) {
            dateSeen[d] = (dateSeen[d] || 0) + 1;
            const hourOffset = String(6 + Math.min(dateSeen[d] * 2, 16)).padStart(2, '0');
            return `${d}T${hourOffset}:00:00`;
        }
        return d;
    });

    // 1. Engine Health Trend Chart (CHT Spread & Shock Cooling)
    const engineDiv = document.getElementById("chartEngineHealth");
    if (engineDiv) {
        const chtSpreadTrace = {
            x: dates,
            y: chronological.map(f => f.cht_spread !== undefined ? f.cht_spread : null),
            type: "scatter",
            mode: "lines+markers",
            name: "CHT Spread (°F)",
            line: { color: "#fd7e14", width: 2 }
        };

        const shockCoolingTrace = {
            x: dates,
            y: chronological.map(f => f.max_shock_cooling !== undefined ? f.max_shock_cooling : null),
            type: "scatter",
            mode: "lines+markers",
            name: "Max Shock Cooling (°F/min)",
            yaxis: "y2",
            line: { color: "#dc3545", width: 2, dash: "dot" }
        };

        const layoutEngine = {
            title: {
                text: "Engine Thermal Trends (CHT Spread & Shock Cooling)",
                font: { size: 14 },
                x: 0.5,
                xanchor: "center",
                y: 0.96,
                yanchor: "top"
            },
            xaxis: { title: { text: "Flight Date", standoff: 12 }, tickangle: -45 },
            yaxis: { title: "CHT Spread (°F)" },
            yaxis2: { title: "Max Shock Cooling (°F/min)", overlaying: "y", side: "right" },
            margin: { l: 55, r: 55, t: 60, b: 100 },
            legend: { orientation: "h", x: 0.5, xanchor: "center", y: -0.38, yanchor: "top" }
        };

        Plotly.newPlot(engineDiv, [chtSpreadTrace, shockCoolingTrace], layoutEngine);
    }

    // 2. Flight Activity & Cumulative Hours Chart
    const activityDiv = document.getElementById("chartActivity");
    if (activityDiv) {
        const durationTrace = {
            x: dates,
            y: chronological.map(f => f.duration_hours || 0),
            type: "bar",
            name: "Per-Flight Engine (hrs)",
            marker: { color: "#0d6efd" }
        };

        const cumHoursTrace = {
            x: dates,
            y: chronological.map(f => f.cum_total_hours || 0),
            type: "scatter",
            mode: "lines+markers",
            name: "Cum. Total Engine Hrs",
            yaxis: "y2",
            line: { color: "#198754", width: 2 }
        };

        const cumAirborneTrace = {
            x: dates,
            y: chronological.map(f => f.cum_airborne_hours || 0),
            type: "scatter",
            mode: "lines+markers",
            name: "Cum. Airborne Flight Time",
            yaxis: "y2",
            line: { color: "#20c997", width: 2, dash: "dot" }
        };

        const layoutActivity = {
            title: {
                text: "Flight Activity & Cumulative Hours",
                font: { size: 14 },
                x: 0.5,
                xanchor: "center",
                y: 0.96,
                yanchor: "top"
            },
            xaxis: { title: { text: "Flight Date", standoff: 12 }, tickangle: -45 },
            yaxis: { title: "Flight Duration (Hours)" },
            yaxis2: { title: "Cumulative Hours", overlaying: "y", side: "right" },
            margin: { l: 55, r: 55, t: 60, b: 100 },
            legend: { orientation: "h", x: 0.5, xanchor: "center", y: -0.38, yanchor: "top" }
        };

        Plotly.newPlot(activityDiv, [durationTrace, cumHoursTrace, cumAirborneTrace], layoutActivity);
    }

    // 3. Fuel & Efficiency Trend Chart
    const fuelDiv = document.getElementById("chartFuelEfficiency");
    if (fuelDiv) {
        const fuelFlowTrace = {
            x: dates,
            y: chronological.map(f => f.avg_fuel_flow || 0),
            type: "scatter",
            mode: "lines+markers",
            name: "Avg Flow (gal/hr)",
            line: { color: "#6f42c1", width: 2 }
        };

        const mpgTrace = {
            x: dates,
            y: chronological.map(f => typeof f.avg_mpg === "number" ? f.avg_mpg : null),
            type: "scatter",
            mode: "lines+markers",
            name: "Avg MPG (nm/gal)",
            yaxis: "y2",
            line: { color: "#20c997", width: 2 }
        };

        const layoutFuel = {
            title: {
                text: "Fuel Consumption & Speed Efficiency",
                font: { size: 14 },
                x: 0.5,
                xanchor: "center",
                y: 0.96,
                yanchor: "top"
            },
            xaxis: { title: { text: "Flight Date", standoff: 12 }, tickangle: -45 },
            yaxis: { title: "Avg Fuel Flow (GPH)" },
            yaxis2: { title: "Avg MPG (NM/gal)", overlaying: "y", side: "right" },
            margin: { l: 55, r: 55, t: 60, b: 100 },
            legend: { orientation: "h", x: 0.5, xanchor: "center", y: -0.38, yanchor: "top" }
        };

        Plotly.newPlot(fuelDiv, [fuelFlowTrace, mpgTrace], layoutFuel);
    }
}

function filterAndRenderTable() {
    const searchInput = document.getElementById("searchFlightInput");
    const query = searchInput ? searchInput.value.toLowerCase().trim() : "";

    let filtered = globalFlights.filter(f => {
        if (!query) return true;
        return (f.filename && f.filename.toLowerCase().includes(query)) ||
               (f.date && f.date.toLowerCase().includes(query)) ||
               (f.flight_id && f.flight_id.toLowerCase().includes(query));
    });

    // Sort table data
    filtered.sort((a, b) => {
        let valA = a[sortKey];
        let valB = b[sortKey];

        if (valA === undefined || valA === "N/A" || valA === null) valA = -999999;
        if (valB === undefined || valB === "N/A" || valB === null) valB = -999999;

        if (typeof valA === "string") {
            return sortAsc ? valA.localeCompare(valB) : valB.localeCompare(valA);
        }
        return sortAsc ? valA - valB : valB - valA;
    });

    renderTableRows(filtered);
}

function sortBy(key) {
    if (sortKey === key) {
        sortAsc = !sortAsc;
    } else {
        sortKey = key;
        sortAsc = false;
    }
    filterAndRenderTable();
}

function renderTableRows(flights) {
    const tbody = document.getElementById("multiStatsTbody");
    if (!tbody) return;

    if (!flights || flights.length === 0) {
        tbody.innerHTML = '<tr><td colspan="13" class="text-center text-muted">No flight logs found.</td></tr>';
        return;
    }

    tbody.innerHTML = flights.map(f => {
        const shockBadge = f.max_shock_cooling > 50
            ? `<span class="badge bg-danger">${f.max_shock_cooling} °F/m</span>`
            : `<span class="badge bg-success">${f.max_shock_cooling || 0} °F/m</span>`;

        const chtColor = f.max_cht > 430 ? 'text-danger fw-bold' : (f.max_cht >= 410 ? 'text-warning fw-bold' : 'text-success');

        let calCell = `<span class="badge bg-light text-muted border">None</span>`;
        if (f.saved_calibrations && f.saved_calibrations.length > 0) {
            calCell = f.saved_calibrations.map((c) => {
                const res = c.results || {};
                const uncorr = res.uncorrected_average_true_airspeed_kts !== undefined ? res.uncorrected_average_true_airspeed_kts : '--';
                const corr = res.corrected_average_true_airspeed_kts !== undefined ? res.corrected_average_true_airspeed_kts : '--';
                const err = res.airspeed_error_kts !== undefined ? (res.airspeed_error_kts >= 0 ? '+' : '') + res.airspeed_error_kts : '';
                const errColor = (res.airspeed_error_kts !== undefined && res.airspeed_error_kts >= 0) ? 'text-success' : 'text-danger';
                return `
                    <div class="d-flex align-items-center gap-1" style="font-size: 0.85rem;">
                        <span><span class="text-muted" title="Uncorrected TAS">${uncorr}</span> &rarr; <span class="text-body-emphasis fw-bold" title="Corrected TAS">${corr} kts</span> ${err ? `<span class="${errColor} small">(${err})</span>` : ''}</span>
                        <button class="btn btn-link btn-sm p-0 text-danger ms-1" onclick="deleteAirspeedCalibration(${c.id})" title="Delete Calibration from Database">
                            <i class="bi bi-trash small"></i>
                        </button>
                    </div>
                `;
            }).join('');
        }

        return `
            <tr>
                <td><strong>${f.date}</strong><br><span class="small text-muted">${f.filename}</span></td>
                <td>${f.duration_hours || 0} hrs (${f.duration_min || 0}m)<br><span class="small text-muted">Airborne: ${f.airborne_hours || 0} hrs</span></td>
                <td>${f.distance_traveled_mi || 0} mi</td>
                <td>${f.total_fuel || 0} gal</td>
                <td>${f.avg_fuel_flow || 0} GPH</td>
                <td><span class="text-success fw-bold">${f.avg_mpg || 'N/A'}</span></td>
                <td><span class="${chtColor}">${f.max_cht || '--'} °F</span> / ${f.max_rpm || '--'}</td>
                <td>${shockBadge}</td>
                <td>${f.cht_spread !== undefined ? f.cht_spread + ' °F' : 'N/A'}</td>
                <td><span class="badge bg-info text-dark">${f.landing_count || 1}</span></td>
                <td>${f.wind_speed_kts !== 'N/A' && f.wind_speed_kts !== undefined ? `${f.wind_speed_kts} kts @ ${f.wind_dir_deg}°` : 'N/A'}</td>
                <td>${calCell}</td>
                <td>
                    <button class="btn btn-sm btn-outline-primary" onclick="openFlightInAnalyzer('${f.filename}')">
                        <i class="bi bi-play-circle"></i> Analyze
                    </button>
                </td>
            </tr>
        `;
    }).join("");
}

function openFlightInAnalyzer(filename) {
    if (window.location.pathname === "/analyzer" || document.getElementById("gamiModal")) {
        const sel = document.getElementById("savedFlights");
        if (sel) {
            sel.value = filename;
            sel.dispatchEvent(new Event("change"));
        }
        const modal = bootstrap.Modal.getInstance(document.getElementById("multiStatsModal"));
        if (modal) modal.hide();
    } else {
        window.location.href = `/analyzer?flight=${encodeURIComponent(filename)}`;
    }
}

window.filterAndRenderTable = filterAndRenderTable;

// --- ALL AIRSPEED CALIBRATIONS COMPARATIVE MODAL ---
let airspeedCalsSortKey = 'date';
let airspeedCalsSortAsc = false;

function openAirspeedCalibrationsModal() {
    renderAirspeedCalsModalTable();
    const modalEl = document.getElementById("allAirspeedCalsModal");
    if (modalEl) {
        const modal = new bootstrap.Modal(modalEl);
        modal.show();
    }
}

function renderAirspeedCalsModalTable() {
    const tbody = document.getElementById("allAirspeedCalsTbody");
    if (!tbody) return;

    let allCals = [];
    const flights = window.globalFlights || [];
    flights.forEach(f => {
        if (f.saved_calibrations && f.saved_calibrations.length > 0) {
            f.saved_calibrations.forEach(c => {
                allCals.push({
                    ...c,
                    flight_date: f.date,
                    filename: f.filename
                });
            });
        }
    });

    const searchInput = document.getElementById("searchAirspeedCalsInput");
    const query = searchInput ? searchInput.value.trim().toLowerCase() : "";
    if (query) {
        allCals = allCals.filter(c => 
            (c.filename && c.filename.toLowerCase().includes(query)) ||
            (c.flight_date && c.flight_date.toLowerCase().includes(query))
        );
    }

    allCals.sort((a, b) => {
        let valA, valB;
        const resA = a.results || {};
        const resB = b.results || {};

        if (airspeedCalsSortKey === 'date') {
            valA = a.flight_date || a.filename;
            valB = b.flight_date || b.filename;
        } else if (airspeedCalsSortKey === 'ias') {
            valA = resA.average_indicated_airspeed_kts || 0;
            valB = resB.average_indicated_airspeed_kts || 0;
        } else if (airspeedCalsSortKey === 'cas') {
            valA = resA.average_calibrated_airspeed_kts || 0;
            valB = resB.average_calibrated_airspeed_kts || 0;
        } else if (airspeedCalsSortKey === 'uncorr_tas') {
            valA = resA.uncorrected_average_true_airspeed_kts || 0;
            valB = resB.uncorrected_average_true_airspeed_kts || 0;
        } else if (airspeedCalsSortKey === 'corr_tas') {
            valA = resA.corrected_average_true_airspeed_kts || 0;
            valB = resB.corrected_average_true_airspeed_kts || 0;
        } else if (airspeedCalsSortKey === 'error') {
            valA = resA.airspeed_error_kts || 0;
            valB = resB.airspeed_error_kts || 0;
        } else if (airspeedCalsSortKey === 'bias') {
            valA = resA.calibrated_heading_correction_deg || 0;
            valB = resB.calibrated_heading_correction_deg || 0;
        } else if (airspeedCalsSortKey === 'da') {
            valA = resA.density_altitude_ft || 0;
            valB = resB.density_altitude_ft || 0;
        } else {
            valA = a.id;
            valB = b.id;
        }

        if (typeof valA === 'string') {
            return airspeedCalsSortAsc ? valA.localeCompare(valB) : valB.localeCompare(valA);
        }
        return airspeedCalsSortAsc ? valA - valB : valB - valA;
    });

    if (allCals.length === 0) {
        tbody.innerHTML = '<tr><td colspan="12" class="text-center text-muted p-4">No saved airspeed calibrations found.</td></tr>';
        return;
    }

    tbody.innerHTML = allCals.map(c => {
        const res = c.results || {};
        const eng = c.engine_settings || {};
        const errVal = res.airspeed_error_kts;
        const errStr = errVal !== undefined ? (errVal >= 0 ? '+' : '') + errVal + ' kts' : '--';
        const errColor = (errVal !== undefined && errVal >= 0) ? 'text-success fw-bold' : 'text-danger fw-bold';
        const da = res.density_altitude_ft !== undefined ? Number(res.density_altitude_ft).toLocaleString() + ' ft' : '--';

        const mapStr = eng.manifold_pressure_inhg !== null && eng.manifold_pressure_inhg !== undefined ? eng.manifold_pressure_inhg + '"' : '--';
        const rpmStr = eng.rpm !== null && eng.rpm !== undefined ? Math.round(eng.rpm) : '--';
        const ffStr = eng.fuel_flow_gph !== null && eng.fuel_flow_gph !== undefined ? eng.fuel_flow_gph + ' gph' : '--';
        const powerStr = eng.percent_power !== null && eng.percent_power !== undefined ? eng.percent_power + '%' : '--';

        const windStr = (res.wind_direction_deg !== undefined && res.wind_speed_kts !== undefined && res.wind_speed_kts > 0)
            ? `${res.wind_direction_deg}°@${res.wind_speed_kts}kt`
            : 'N/A';

        return `
            <tr onmouseenter="highlightAirspeedCalSegment('${c.filename}', ${c.start_time}, ${c.end_time})" style="cursor: pointer;">
                <td class="text-nowrap"><strong>${c.flight_date}</strong><br><span class="extra-small text-muted">${c.filename}</span></td>
                <td class="text-nowrap">${formatMMSS(c.start_time)}-${formatMMSS(c.end_time)}</td>
                <td class="text-nowrap">${res.average_indicated_airspeed_kts || '--'}</td>
                <td class="text-nowrap">${res.average_calibrated_airspeed_kts || '--'}</td>
                <td class="text-nowrap"><span class="text-muted">${res.uncorrected_average_true_airspeed_kts || '--'}</span></td>
                <td class="text-nowrap"><span class="text-body-emphasis fw-bold">${res.corrected_average_true_airspeed_kts || '--'} kt</span></td>
                <td class="text-nowrap"><span class="${errColor}">${errStr}</span></td>
                <td class="text-nowrap">${res.calibrated_heading_correction_deg !== undefined ? (res.calibrated_heading_correction_deg >= 0 ? '+' : '') + res.calibrated_heading_correction_deg + '°' : '--'}</td>
                <td class="text-nowrap">${windStr}</td>
                <td class="text-nowrap">${da}</td>
                <td><span class="extra-small text-muted text-nowrap">${mapStr} | ${rpmStr} | ${ffStr} | ${powerStr}</span></td>
                <td class="text-nowrap">
                    <div class="btn-group btn-group-sm">
                        <button class="btn btn-outline-info py-0 px-1" onclick="viewCalOnMap('${c.filename}', ${c.start_time}, ${c.end_time})" title="View Maneuver Track on Map">
                            <i class="bi bi-geo-alt-fill"></i> Map
                        </button>
                        <button class="btn btn-outline-primary py-0 px-1" onclick="openFlightInAnalyzer('${c.filename}')" title="Analyze Flight">
                            <i class="bi bi-play-circle"></i>
                        </button>
                        <button class="btn btn-outline-danger py-0 px-1" onclick="deleteAirspeedCalibration(${c.id})" title="Delete Calibration">
                            <i class="bi bi-trash"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function sortAirspeedCalsTable(key) {
    if (airspeedCalsSortKey === key) {
        airspeedCalsSortAsc = !airspeedCalsSortAsc;
    } else {
        airspeedCalsSortKey = key;
        airspeedCalsSortAsc = false;
    }
    renderAirspeedCalsModalTable();
}

window.openAirspeedCalibrationsModal = openAirspeedCalibrationsModal;
window.renderAirspeedCalsModalTable = renderAirspeedCalsModalTable;
window.sortAirspeedCalsTable = sortAirspeedCalsTable;

// --- TAS VS % POWER (DENSITY ALTITUDE NORMALIZED) PLOT ---
function toggleAirspeedPowerPlot() {
    const card = document.getElementById("airspeedPowerPlotCard");
    if (!card) return;
    const isHidden = card.classList.contains("d-none");
    if (isHidden) {
        card.classList.remove("d-none");
        renderAirspeedPowerPlot();
    } else {
        card.classList.add("d-none");
    }
}

function renderAirspeedPowerPlot() {
    const div = document.getElementById("airspeedPowerPlotDiv");
    const statsDiv = document.getElementById("airspeedPowerPlotStats");
    if (!div) return;

    const flights = window.globalFlights || [];
    let dataPoints = [];

    flights.forEach(f => {
        if (f.saved_calibrations && f.saved_calibrations.length > 0) {
            f.saved_calibrations.forEach(c => {
                const res = c.results || {};
                const eng = c.engine_settings || {};

                const power = eng.percent_power;
                const corrTas = res.corrected_average_true_airspeed_kts;
                const da = res.density_altitude_ft !== undefined ? res.density_altitude_ft : 0;
                const ias = res.average_indicated_airspeed_kts;
                const cas = res.average_calibrated_airspeed_kts;

                if (power !== undefined && power !== null && power > 0 && corrTas !== undefined && corrTas !== null && corrTas > 0) {
                    const sigma = Math.pow(Math.max(0.1, 1 - 6.87559e-6 * da), 4.25588);
                    const normTas = corrTas * Math.sqrt(sigma);

                    dataPoints.push({
                        power: Number(power),
                        corrTas: Number(corrTas),
                        normTas: Number(normTas.toFixed(1)),
                        da: Number(da),
                        ias: ias,
                        cas: cas,
                        flight_date: f.date,
                        filename: f.filename,
                        id: c.id,
                        segment: `${formatMMSS(c.start_time)}-${formatMMSS(c.end_time)}`
                    });
                }
            });
        }
    });

    if (dataPoints.length === 0) {
        div.innerHTML = '<div class="text-center text-muted p-5">No saved calibrations with recorded % Power and TAS to plot.</div>';
        if (statsDiv) statsDiv.innerHTML = '';
        return;
    }

    const useNormalized = document.getElementById("normTasToggle")?.checked || false;

    dataPoints.sort((a, b) => a.power - b.power);

    const xVals = dataPoints.map(p => p.power);
    const yVals = dataPoints.map(p => useNormalized ? p.normTas : p.corrTas);
    const daVals = dataPoints.map(p => p.da);

    const hoverTexts = dataPoints.map(p => 
        `<b>${p.flight_date}</b> (${p.segment})<br>` +
        `<b>% Power:</b> ${p.power}%<br>` +
        `<b>Corrected TAS:</b> ${p.corrTas} kts<br>` +
        `<b>Normalized TAS (Sea Level):</b> ${p.normTas} kts<br>` +
        `<b>Density Altitude:</b> ${p.da.toLocaleString()} ft<br>` +
        `<b>CAS / IAS:</b> ${p.cas || '--'} / ${p.ias || '--'} kts`
    );

    let n = xVals.length;
    let sumX = 0, sumY = 0, sumXY = 0, sumXX = 0, sumYY = 0;
    for (let i = 0; i < n; i++) {
        sumX += xVals[i];
        sumY += yVals[i];
        sumXY += xVals[i] * yVals[i];
        sumXX += xVals[i] * xVals[i];
        sumYY += yVals[i] * yVals[i];
    }
    let slope = n > 1 && (n * sumXX - sumX * sumX) !== 0 ? (n * sumXY - sumX * sumY) / (n * sumXX - sumX * sumX) : 0;
    let intercept = n > 1 ? (sumY - slope * sumX) / n : 0;
    
    let r2 = 0;
    let num = (n * sumXY - sumX * sumY);
    let den = Math.sqrt((n * sumXX - sumX * sumX) * (n * sumYY - sumY * sumY));
    if (den !== 0) r2 = Math.pow(num / den, 2);

    const minX = Math.min(...xVals) - 5;
    const maxX = Math.max(...xVals) + 5;
    const fitX = [minX, maxX];
    const fitY = [minX * slope + intercept, maxX * slope + intercept];

    const scatterTrace = {
        x: xVals,
        y: yVals,
        mode: 'markers',
        type: 'scatter',
        name: 'Calibration Points',
        text: hoverTexts,
        hoverinfo: 'text',
        marker: {
            size: 12,
            color: daVals,
            colorscale: 'Viridis',
            colorbar: {
                title: 'Density Alt (ft)',
                titleside: 'right',
                len: 0.8
            },
            showscale: true,
            line: { color: '#ffffff', width: 1.5 }
        }
    };

    const fitTrace = {
        x: fitX,
        y: fitY,
        mode: 'lines',
        type: 'scatter',
        name: `Trendline (R² = ${r2.toFixed(3)})`,
        line: { color: '#dc3545', width: 2, dash: 'dash' }
    };

    const isDarkMode = document.body.classList.contains("dark-mode") || document.documentElement.getAttribute("data-bs-theme") === "dark";

    const layout = {
        title: {
            text: useNormalized 
                ? 'Sea-Level Normalized TAS vs. Engine % Power (Density Altitude Normalized)' 
                : 'Corrected TAS vs. Engine % Power (Color-Coded by Density Altitude)',
            font: { size: 14, color: isDarkMode ? '#f8f9fa' : '#212529' }
        },
        xaxis: {
            title: 'Engine % Power (%)',
            gridcolor: isDarkMode ? '#343a40' : '#e9ecef',
            zerolinecolor: isDarkMode ? '#495057' : '#ced4da',
            color: isDarkMode ? '#f8f9fa' : '#212529'
        },
        yaxis: {
            title: useNormalized ? 'Normalized TAS @ Sea Level (kts)' : 'Corrected TAS (kts)',
            gridcolor: isDarkMode ? '#343a40' : '#e9ecef',
            zerolinecolor: isDarkMode ? '#495057' : '#ced4da',
            color: isDarkMode ? '#f8f9fa' : '#212529'
        },
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        margin: { l: 60, r: 60, t: 40, b: 50 },
        showlegend: true,
        legend: {
            orientation: 'h',
            y: 1.15,
            x: 0,
            font: { color: isDarkMode ? '#f8f9fa' : '#212529' }
        }
    };

    Plotly.newPlot(div, [scatterTrace, fitTrace], layout, { responsive: true });

    if (statsDiv) {
        const avgDA = Math.round(daVals.reduce((a, b) => a + b, 0) / n);
        statsDiv.innerHTML = `
            <strong>Performance Linear Fit:</strong> 
            TAS = <strong>${slope.toFixed(2)}</strong> × (% Power) ${intercept >= 0 ? '+' : '-'} <strong>${Math.abs(intercept).toFixed(1)}</strong> kts 
            | Correlation (R²): <strong>${r2.toFixed(3)}</strong> 
            | Avg Density Alt: <strong>${avgDA.toLocaleString()} ft</strong> 
            | Total Data Points: <strong>${n}</strong>
        `;
    }
}

window.toggleAirspeedPowerPlot = toggleAirspeedPowerPlot;
window.renderAirspeedPowerPlot = renderAirspeedPowerPlot;

// --- INTERACTIVE AIRSPEED CALIBRATION FLIGHT TRACK MAP WITH CURSOR FOLLOW ---
window.calMapState = {
    activeFilename: null,
    telemetry: null,
    segStart: 0,
    segEnd: 0,
    cursorIndex: 0
};

function toggleAirspeedCalMap() {
    const card = document.getElementById("airspeedCalMapCard");
    if (!card) return;
    const isHidden = card.classList.contains("d-none");
    if (isHidden) {
        card.classList.remove("d-none");
        if (!window.calMapState.telemetry) {
            // Find first available calibration to display by default
            const flights = window.globalFlights || [];
            for (let f of flights) {
                if (f.saved_calibrations && f.saved_calibrations.length > 0) {
                    const c = f.saved_calibrations[0];
                    viewCalOnMap(c.filename, c.start_time, c.end_time);
                    break;
                }
            }
        }
    } else {
        card.classList.add("d-none");
    }
}

function viewCalOnMap(filename, startTime, endTime) {
    const card = document.getElementById("airspeedCalMapCard");
    if (card && card.classList.contains("d-none")) {
        card.classList.remove("d-none");
    }
    highlightAirspeedCalSegment(filename, startTime, endTime, true);
}

function highlightAirspeedCalSegment(filename, startTime, endTime, forceRecenter = false) {
    const card = document.getElementById("airspeedCalMapCard");
    if (!card || card.classList.contains("d-none")) return;

    if (window.calMapState.activeFilename !== filename) {
        // Fetch new flight map telemetry
        fetch(`/api/flight_map_telemetry?filename=${encodeURIComponent(filename)}`)
            .then(res => res.json())
            .then(data => {
                if (data.error) {
                    console.warn("Map telemetry fetch error:", data.error);
                    return;
                }
                window.calMapState.activeFilename = filename;
                window.calMapState.telemetry = data;
                renderAirspeedCalMapPlot(startTime, endTime, forceRecenter);
            })
            .catch(err => console.error("Error fetching map telemetry:", err));
    } else {
        renderAirspeedCalMapPlot(startTime, endTime, forceRecenter);
    }
}

function renderAirspeedCalMapPlot(startTime, endTime, forceRecenter = false) {
    const div = document.getElementById("airspeedCalMapDiv");
    const titleEl = document.getElementById("airspeedCalMapTitle");
    const badgeEl = document.getElementById("airspeedCalMapSegmentBadge");
    const sliderEl = document.getElementById("airspeedCalMapSlider");
    if (!div || !window.calMapState.telemetry) return;

    const data = window.calMapState.telemetry;
    const lats = data.lat || [];
    const lons = data.lon || [];
    const times = data.time || [];
    const alts = data.alt || [];
    const iass = data.ias || [];
    const tass = data.tas || [];
    const hdgs = data.heading || [];

    if (lats.length === 0 || lons.length === 0) {
        div.innerHTML = '<div class="text-center text-muted p-5">No GPS coordinate track logged for this flight file.</div>';
        return;
    }

    window.calMapState.segStart = startTime;
    window.calMapState.segEnd = endTime;

    // Filter segment indices
    let segIndices = [];
    for (let i = 0; i < times.length; i++) {
        if (times[i] >= startTime && times[i] <= endTime) {
            segIndices.push(i);
        }
    }
    if (segIndices.length === 0) {
        segIndices = [0];
    }

    const segLats = segIndices.map(i => lats[i]);
    const segLons = segIndices.map(i => lons[i]);
    const segTimes = segIndices.map(i => times[i]);
    const segAlts = segIndices.map(i => alts[i]);
    const segIass = segIndices.map(i => iass[i]);
    const segTass = segIndices.map(i => tass[i]);

    // Update Slider
    if (sliderEl) {
        sliderEl.min = 0;
        sliderEl.max = lats.length - 1;
        // Default cursor to start of maneuver segment
        const initCursorIdx = segIndices[0] || 0;
        sliderEl.value = initCursorIdx;
        window.calMapState.cursorIndex = initCursorIdx;
    }

    if (titleEl) {
        titleEl.innerHTML = `🗺️ Flight Track: <strong>${data.filename}</strong>`;
    }
    if (badgeEl) {
        badgeEl.innerHTML = `Maneuver Segment: ${formatMMSS(startTime)} - ${formatMMSS(endTime)}`;
    }

    // Traces:
    // 1. Full flight path line
    const fullPathTrace = {
        type: 'scattermapbox',
        mode: 'lines',
        lat: lats,
        lon: lons,
        line: { width: 3, color: '#6c757d' },
        name: 'Full Flight Track',
        hoverinfo: 'none'
    };

    // 2. Maneuver segment track line (bright cyan with yellow point markers)
    const segmentTrace = {
        type: 'scattermapbox',
        mode: 'lines+markers',
        lat: segLats,
        lon: segLons,
        line: { width: 6, color: '#00f0ff' },
        marker: { size: 7, color: '#ffc107' },
        name: 'Maneuver Segment',
        text: segTimes.map((t, idx) => 
            `<b>Calibration Segment</b><br>` +
            `Time: ${formatMMSS(t)}<br>` +
            `Alt: ${Math.round(segAlts[idx] || 0).toLocaleString()} ft<br>` +
            `IAS: ${Math.round(segIass[idx] || 0)} kt | TAS: ${Math.round(segTass[idx] || 0)} kt`
        ),
        hoverinfo: 'text'
    };

    // 3. Cursor Follow Marker (Red Target Circle)
    const initIdx = window.calMapState.cursorIndex || segIndices[0] || 0;
    const cursorTrace = {
        type: 'scattermapbox',
        mode: 'markers',
        lat: [lats[initIdx]],
        lon: [lons[initIdx]],
        marker: {
            size: 16,
            color: '#ff0055',
            symbol: 'circle',
            opacity: 0.9
        },
        name: 'Position Cursor',
        text: [`<b>Cursor Position</b><br>Time: ${formatMMSS(times[initIdx])}`],
        hoverinfo: 'text'
    };

    // Map Center & Zoom
    const centerLat = segLats.reduce((a, b) => a + b, 0) / segLats.length;
    const centerLon = segLons.reduce((a, b) => a + b, 0) / segLons.length;

    const isDarkMode = document.body.classList.contains("dark-mode") || document.documentElement.getAttribute("data-bs-theme") === "dark";

    const layout = {
        mapbox: {
            style: 'open-street-map',
            center: { lat: centerLat, lon: centerLon },
            zoom: 13
        },
        margin: { l: 0, r: 0, t: 0, b: 0 },
        showlegend: false,
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent'
    };

    Plotly.newPlot(div, [fullPathTrace, segmentTrace, cursorTrace], layout, { responsive: true });

    div.on('plotly_hover', (eventData) => {
        if (!eventData || !eventData.points || !eventData.points.length) return;
        const pt = eventData.points[0];
        if (pt.curveNumber === 2) return;
        updateAirspeedCalMapCursor(pt.pointIndex);
    });

    // Update banner text
    updateAirspeedCalMapCursor(initIdx);
}

function updateAirspeedCalMapCursor(index) {
    if (!window.calMapState.telemetry) return;
    const data = window.calMapState.telemetry;
    const idx = Math.min(Math.max(0, parseInt(index)), (data.lat || []).length - 1);
    if (window.calMapState.cursorIndex === idx && document.getElementById("airspeedCalMapDiv")?.data?.[2]?.lat?.[0] === data.lat[idx]) return;
    window.calMapState.cursorIndex = idx;

    const lat = data.lat[idx];
    const lon = data.lon[idx];
    const t = data.time[idx];
    const alt = data.alt[idx];
    const ias = data.ias[idx];
    const tas = data.tas[idx];
    const hdg = data.heading[idx];

    // Update position marker trace on Plotly map
    const div = document.getElementById("airspeedCalMapDiv");
    if (div && div.data && div.data.length >= 3) {
        Plotly.restyle(div, {
            lat: [[lat]],
            lon: [[lon]],
            text: [[
                `<b>Position Cursor</b><br>` +
                `Time: ${formatMMSS(t)}<br>` +
                `Alt: ${Math.round(alt || 0).toLocaleString()} ft<br>` +
                `IAS: ${Math.round(ias || 0)} kt | TAS: ${Math.round(tas || 0)} kt<br>` +
                `HDG: ${Math.round(hdg || 0)}°`
            ]]
        }, [2]).catch(e => console.debug("Map cursor update notice:", e));
    }

    // Update banner text
    const bannerEl = document.getElementById("airspeedCalMapCursorBanner");
    if (bannerEl) {
        bannerEl.innerHTML = `
            📍 <strong>${formatMMSS(t)}</strong> 
            | Lat: <strong>${lat.toFixed(5)}°</strong>, Lon: <strong>${lon.toFixed(5)}°</strong> 
            | Alt: <strong>${Math.round(alt || 0).toLocaleString()} ft</strong> 
            | IAS: <strong>${Math.round(ias || 0)} kt</strong> 
            | TAS: <strong>${Math.round(tas || 0)} kt</strong>
            ${hdg !== undefined ? `| HDG: <strong>${Math.round(hdg)}°</strong>` : ''}
        `;
    }
}

function onAirspeedCalMapSliderChange(val) {
    updateAirspeedCalMapCursor(val);
}

window.toggleAirspeedCalMap = toggleAirspeedCalMap;
window.viewCalOnMap = viewCalOnMap;
window.highlightAirspeedCalSegment = highlightAirspeedCalSegment;
window.onAirspeedCalMapSliderChange = onAirspeedCalMapSliderChange;

