let globalFlights = [];
let sortKey = 'date';
let sortAsc = false;

document.addEventListener("DOMContentLoaded", () => {
    loadMultiFlightStats();

    const searchInput = document.getElementById("searchFlightInput");
    if (searchInput) {
        searchInput.addEventListener("input", filterAndRenderTable);
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
            globalFlights = data.flights || [];

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

    // Chronological order for trend charts (oldest -> newest)
    const chronological = [...flights].reverse();
    const dates = chronological.map(f => f.date || f.filename);

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

        return `
            <tr>
                <td><strong>${f.date}</strong><br><span class="small text-muted">${f.filename}</span></td>
                <td>${f.duration_hours || 0} hrs (${f.duration_min || 0}m)<br><span class="small text-muted">Airborne: ${f.airborne_hours || 0} hrs</span></td>
                <td><span class="fw-bold text-teal" style="color: #20c997;">${f.cum_airborne_hours !== undefined ? f.cum_airborne_hours + ' hrs' : 'N/A'}</span></td>
                <td>${f.distance_traveled_mi || 0} mi</td>
                <td>${f.total_fuel || 0} gal</td>
                <td>${f.avg_fuel_flow || 0} GPH</td>
                <td><span class="text-success fw-bold">${f.avg_mpg || 'N/A'}</span></td>
                <td><span class="${chtColor}">${f.max_cht || '--'} °F</span> / ${f.max_rpm || '--'}</td>
                <td>${shockBadge}</td>
                <td>${f.cht_spread !== undefined ? f.cht_spread + ' °F' : 'N/A'}</td>
                <td><span class="badge bg-info text-dark">${f.landing_count || 1}</span></td>
                <td>${f.wind_speed_kts !== 'N/A' && f.wind_speed_kts !== undefined ? `${f.wind_speed_kts} kts @ ${f.wind_dir_deg}°` : 'N/A'}</td>
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
