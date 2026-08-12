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

    const isMapInitialized = div.data && div.data.length > 0;

    let centerLat, centerLon, fitZoom;

    if (isMapInitialized && !forceRecenter && div.layout && div.layout.mapbox) {
        centerLat = div.layout.mapbox.center ? div.layout.mapbox.center.lat : 0;
        centerLon = div.layout.mapbox.center ? div.layout.mapbox.center.lon : 0;
        fitZoom = div.layout.mapbox.zoom || 11;
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

    Plotly.react(div, [fullPathTrace, segmentTrace, cursorTrace], layout, { responsive: true });

    if (!isMapInitialized) {
        div.on('plotly_hover', (eventData) => {
            if (!eventData || !eventData.points || !eventData.points.length) return;
            const pt = eventData.points[0];
            if (pt.curveNumber === 2) return;
            updateAirspeedCalMapCursor(pt.pointIndex);
        });
    }

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
}

function onAirspeedCalMapSliderChange(val) {
    updateAirspeedCalMapCursor(val);
}

window.toggleAirspeedCalMap = toggleAirspeedCalMap;
window.viewCalOnMap = viewCalOnMap;
window.highlightAirspeedCalSegment = highlightAirspeedCalSegment;
window.onAirspeedCalMapSliderChange = onAirspeedCalMapSliderChange;

// --- FLEET ENGINE HEALTH & COOLING TRENDS MODAL ---
window.engineHealthData = null;
window.activeEngineHealthTab = 'thermal';

function openEngineHealthModal() {
    const modalEl = document.getElementById("engineHealthModal");
    if (!modalEl) return;
    const modal = new bootstrap.Modal(modalEl);
    modal.show();

    if (!window.engineHealthData) {
        fetchEngineHealthData();
    } else {
        renderEngineHealthTab(window.activeEngineHealthTab || 'thermal');
    }
}

function fetchEngineHealthData() {
    fetch('/api/engine_health_trends')
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                console.error("Engine health fetch error:", data.error);
                return;
            }
            window.engineHealthData = data;
            renderEngineHealthTab(window.activeEngineHealthTab || 'thermal');
        })
        .catch(err => console.error("Error fetching engine health trends:", err));
}

function renderEngineHealthTab(tabKey) {
    window.activeEngineHealthTab = tabKey;
    if (!window.engineHealthData || !window.engineHealthData.flights) return;

    const flights = window.engineHealthData.flights;
    const summary = window.engineHealthData.summary || {};
    const isDarkMode = document.body.classList.contains("dark-mode") || document.documentElement.getAttribute("data-bs-theme") === "dark";
    const textColor = isDarkMode ? '#f8f9fa' : '#212529';
    const gridColor = isDarkMode ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)';

    if (tabKey === 'thermal') {
        // --- TAB 1: Thermal Efficiency & OAT ---
        const div = document.getElementById("enginePlotDiv1");
        if (!div) return;

        const validOat = flights.filter(f => f.oat_f !== null && f.max_cht !== null);
        const oats = validOat.map(f => f.oat_f);
        const chts = validOat.map(f => f.max_cht);
        const oils = validOat.map(f => f.oil_temp).filter(v => v !== null);
        const oilOats = validOat.filter(f => f.oil_temp !== null).map(f => f.oat_f);

        // Linear fit CHT vs OAT
        let slope = 0, intercept = 0, r2 = 0;
        if (oats.length > 2) {
            const n = oats.length;
            const sumX = oats.reduce((a, b) => a + b, 0);
            const sumY = chts.reduce((a, b) => a + b, 0);
            const sumXY = oats.reduce((a, b, i) => a + b * chts[i], 0);
            const sumXX = oats.reduce((a, b) => a + b * b, 0);
            const sumYY = chts.reduce((a, b) => a + b * b, 0);

            const denom = (n * sumXX - sumX * sumX);
            if (denom !== 0) {
                slope = (n * sumXY - sumX * sumY) / denom;
                intercept = (sumY - slope * sumX) / n;
                const rNum = (n * sumXY - sumX * sumY);
                const rDen = Math.sqrt((n * sumXX - sumX * sumX) * (n * sumYY - sumY * sumY));
                r2 = rDen !== 0 ? Math.pow(rNum / rDen, 2) : 0;
            }
        }

        const minOat = Math.min(...oats, 30);
        const maxOat = Math.max(...oats, 100);
        const fitX = [minOat, maxOat];
        const fitY = [slope * minOat + intercept, slope * maxOat + intercept];

        const traceCHT = {
            x: oats,
            y: chts,
            mode: 'markers',
            name: 'Max CHT (°F)',
            marker: { size: 9, color: '#dc3545', opacity: 0.85 },
            text: validOat.map(f => `Date: ${f.date}<br>OAT: ${f.oat_f}°F<br>Max CHT: ${f.max_cht}°F<br>TAS: ${f.tas || '--'} kt`),
            hoverinfo: 'text'
        };

        const traceFit = {
            x: fitX,
            y: fitY,
            mode: 'lines',
            name: `Linear Fit: +${slope.toFixed(2)}°F CHT / +1°F OAT (R²=${r2.toFixed(2)})`,
            line: { color: '#dc3545', width: 2, dash: 'dash' }
        };

        const traceOil = {
            x: oilOats,
            y: oils,
            mode: 'markers',
            name: 'Oil Temp (°F)',
            marker: { size: 8, color: '#ffc107', symbol: 'diamond', opacity: 0.85 },
            text: validOat.filter(f => f.oil_temp !== null).map(f => `Date: ${f.date}<br>OAT: ${f.oat_f}°F<br>Oil Temp: ${f.oil_temp}°F`),
            hoverinfo: 'text'
        };

        const layout = {
            title: { text: 'Engine Thermal Load (Max CHT & Oil Temp) vs. Outside Air Temp (OAT)', font: { color: textColor, size: 15 } },
            xaxis: { title: 'Outside Air Temperature (°F)', gridcolor: gridColor, font: { color: textColor } },
            yaxis: { title: 'Temperature (°F)', gridcolor: gridColor, font: { color: textColor } },
            paper_bgcolor: 'transparent',
            plot_bgcolor: 'transparent',
            margin: { l: 60, r: 40, t: 50, b: 50 },
            legend: { orientation: 'h', y: 1.12, font: { color: textColor } }
        };

        Plotly.newPlot(div, [traceCHT, traceFit, traceOil], layout, { responsive: true });

    } else if (tabKey === 'altitude') {
        // --- TAB 2: Density Altitude & TAS ---
        const div = document.getElementById("enginePlotDiv2");
        if (!div) return;

        const validDA = flights.filter(f => f.density_alt !== null && f.max_cht !== null);
        const das = validDA.map(f => f.density_alt);
        const chts = validDA.map(f => f.max_cht);
        const tass = validDA.map(f => f.tas || 120);

        const traceDA = {
            x: das,
            y: chts,
            mode: 'markers',
            name: 'Flight Density Alt vs CHT',
            marker: {
                size: 10,
                color: tass,
                colorscale: 'Viridis',
                colorbar: { title: { text: 'TAS (kt)', font: { color: textColor } }, tickfont: { color: textColor } },
                showscale: true,
                opacity: 0.9
            },
            text: validDA.map(f => `Date: ${f.date}<br>Density Alt: ${Math.round(f.density_alt).toLocaleString()} ft<br>Max CHT: ${f.max_cht}°F<br>TAS: ${f.tas || '--'} kt`),
            hoverinfo: 'text'
        };

        const layout = {
            title: { text: 'Max CHT vs. Density Altitude (Color-Coded by True Airspeed)', font: { color: textColor, size: 15 } },
            xaxis: { title: 'Density Altitude (feet)', gridcolor: gridColor, font: { color: textColor } },
            yaxis: { title: 'Max CHT (°F)', gridcolor: gridColor, font: { color: textColor } },
            paper_bgcolor: 'transparent',
            plot_bgcolor: 'transparent',
            margin: { l: 60, r: 40, t: 50, b: 50 },
            legend: { orientation: 'h', y: 1.12, font: { color: textColor } }
        };

        Plotly.newPlot(div, [traceDA], layout, { responsive: true });

    } else if (tabKey === 'cylinders') {
        // --- TAB 3: Individual Cylinder Balance (CHT 1-4) ---
        const div = document.getElementById("enginePlotDiv3");
        if (!div) return;

        const dates = flights.map(f => f.date);
        const c1 = flights.map(f => f.cht1);
        const c2 = flights.map(f => f.cht2);
        const c3 = flights.map(f => f.cht3);
        const c4 = flights.map(f => f.cht4);

        const traceC1 = { x: dates, y: c1, mode: 'lines+markers', name: 'CHT 1', line: { color: '#00f0ff', width: 2 }, marker: { size: 6 } };
        const traceC2 = { x: dates, y: c2, mode: 'lines+markers', name: 'CHT 2', line: { color: '#198754', width: 2 }, marker: { size: 6 } };
        const traceC3 = { x: dates, y: c3, mode: 'lines+markers', name: 'CHT 3', line: { color: '#ff5500', width: 2 }, marker: { size: 6 } };
        const traceC4 = { x: dates, y: c4, mode: 'lines+markers', name: 'CHT 4', line: { color: '#9d4edd', width: 2 }, marker: { size: 6 } };

        const layout = {
            title: { text: 'Individual Cylinder Head Temperatures (CHT 1, 2, 3, 4) Across Flights', font: { color: textColor, size: 15 } },
            xaxis: { title: 'Flight Date', gridcolor: gridColor, font: { color: textColor } },
            yaxis: { title: 'Temperature (°F)', gridcolor: gridColor, font: { color: textColor } },
            paper_bgcolor: 'transparent',
            plot_bgcolor: 'transparent',
            margin: { l: 60, r: 40, t: 50, b: 50 },
            legend: { orientation: 'h', y: 1.12, font: { color: textColor } }
        };

        Plotly.newPlot(div, [traceC1, traceC2, traceC3, traceC4], layout, { responsive: true });

    } else if (tabKey === 'power') {
        // --- TAB 4: Engine Power & Fuel Flow ---
        const div = document.getElementById("enginePlotDiv4");
        if (!div) return;

        const validPwr = flights.filter(f => f.percent_power !== null && f.max_cht !== null);
        const pwrs = validPwr.map(f => f.percent_power);
        const chts = validPwr.map(f => f.max_cht);
        const oils = validPwr.map(f => f.oil_temp).filter(v => v !== null);
        const oilPwrs = validPwr.filter(f => f.oil_temp !== null).map(f => f.percent_power);

        const traceCHT = {
            x: pwrs,
            y: chts,
            mode: 'markers',
            name: 'Max CHT vs % Power',
            marker: { size: 9, color: '#e63946' },
            text: validPwr.map(f => `Date: ${f.date}<br>Power: ${f.percent_power}%<br>Max CHT: ${f.max_cht}°F`),
            hoverinfo: 'text'
        };

        const traceOil = {
            x: oilPwrs,
            y: oils,
            mode: 'markers',
            name: 'Oil Temp vs % Power',
            marker: { size: 8, color: '#f4a261', symbol: 'square' },
            text: validPwr.filter(f => f.oil_temp !== null).map(f => `Date: ${f.date}<br>Power: ${f.percent_power}%<br>Oil Temp: ${f.oil_temp}°F`),
            hoverinfo: 'text'
        };

        const layout = {
            title: { text: 'Cylinder Head & Oil Temperature vs. Engine Percent Power (%)', font: { color: textColor, size: 15 } },
            xaxis: { title: 'Percent Power (%)', gridcolor: gridColor, font: { color: textColor } },
            yaxis: { title: 'Temperature (°F)', gridcolor: gridColor, font: { color: textColor } },
            paper_bgcolor: 'transparent',
            plot_bgcolor: 'transparent',
            margin: { l: 60, r: 40, t: 50, b: 50 },
            legend: { orientation: 'h', y: 1.12, font: { color: textColor } }
        };

        Plotly.newPlot(div, [traceCHT, traceOil], layout, { responsive: true });

    } else if (tabKey === 'summary') {
        // --- TAB 5: Diagnostic Summary Cards ---
        const container = document.getElementById("engineSummaryCards");
        if (!container) return;

        const validOat = flights.filter(f => f.oat_f !== null && f.max_cht !== null);
        let slopeStr = "--";
        if (validOat.length > 2) {
            const oats = validOat.map(f => f.oat_f);
            const chts = validOat.map(f => f.max_cht);
            const n = oats.length;
            const sumX = oats.reduce((a, b) => a + b, 0);
            const sumY = chts.reduce((a, b) => a + b, 0);
            const sumXY = oats.reduce((a, b, i) => a + b * chts[i], 0);
            const sumXX = oats.reduce((a, b) => a + b * b, 0);
            const denom = (n * sumXX - sumX * sumX);
            if (denom !== 0) {
                const slope = (n * sumXY - sumX * sumY) / denom;
                slopeStr = `+${(slope * 10).toFixed(1)}°F CHT per +10°F OAT`;
            }
        }

        const spreads = flights.map(f => f.cht_spread).filter(v => v !== null);
        const avgSpread = spreads.length ? (spreads.reduce((a, b) => a + b, 0) / spreads.length).toFixed(1) : "--";

        container.innerHTML = `
            <div class="col-md-4">
                <div class="card p-3 border-danger shadow-sm h-100">
                    <h6 class="text-danger fw-bold"><i class="bi bi-thermometer-high"></i> Ambient Thermal Sensitivity</h6>
                    <div class="display-6 fw-bold my-2 text-danger">${slopeStr}</div>
                    <div class="small text-muted">Linear regression rate of cylinder head temperature rise per degree of ambient temperature increase.</div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card p-3 border-warning shadow-sm h-100">
                    <h6 class="text-warning text-dark fw-bold"><i class="bi bi-fire"></i> Hottest Running Cylinder</h6>
                    <div class="display-6 fw-bold my-2 text-warning text-dark">${summary.hottest_cylinder || 'N/A'}</div>
                    <div class="small text-muted">Identified as peak operating CHT across ${summary.total_flights || 0} fleet flights.</div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card p-3 border-info shadow-sm h-100">
                    <h6 class="text-info fw-bold"><i class="bi bi-arrows-expand"></i> Average Cylinder Spread</h6>
                    <div class="display-6 fw-bold my-2 text-info">${avgSpread}°F</div>
                    <div class="small text-muted">Mean temperature delta across all 4 cylinders during cruise flight.</div>
                </div>
            </div>
        `;
    }
}

window.openEngineHealthModal = openEngineHealthModal;
window.renderEngineHealthTab = renderEngineHealthTab;


