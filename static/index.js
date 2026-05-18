document.addEventListener("DOMContentLoaded", function() {
    function paginateTable(tableId, paginationId, rowsPerPage) {
        const table = document.getElementById(tableId);
        if (!table) return;
        const tbody = table.querySelector('tbody');
        const rows = tbody.querySelectorAll('tr');
        const paginationEl = document.getElementById(paginationId);
        if (!paginationEl || rows.length === 0) return;

        let currentPage = 1;
        const totalPages = Math.ceil(rows.length / rowsPerPage);

        function displayPage(page) {
            currentPage = page;
            rows.forEach((row, index) => {
                row.style.display = (index >= (page - 1) * rowsPerPage && index < page * rowsPerPage) ? '' : 'none';
            });
            updatePaginationUI();
        }

        function updatePaginationUI() {
            paginationEl.innerHTML = '';
            if (totalPages <= 1) return;

            const prevLi = document.createElement('li');
            prevLi.className = `page-item ${currentPage === 1 ? 'disabled' : ''}`;
            prevLi.innerHTML = `<a class="page-link" href="#" aria-label="Previous"><span aria-hidden="true">&laquo;</span></a>`;
            prevLi.addEventListener('click', (e) => { e.preventDefault(); if(currentPage > 1) displayPage(currentPage - 1); });
            paginationEl.appendChild(prevLi);

            for (let i = 1; i <= totalPages; i++) {
                const li = document.createElement('li');
                li.className = `page-item ${currentPage === i ? 'active' : ''}`;
                li.innerHTML = `<a class="page-link" href="#">${i}</a>`;
                li.addEventListener('click', (e) => { e.preventDefault(); displayPage(i); });
                paginationEl.appendChild(li);
            }

            const nextLi = document.createElement('li');
            nextLi.className = `page-item ${currentPage === totalPages ? 'disabled' : ''}`;
            nextLi.innerHTML = `<a class="page-link" href="#" aria-label="Next"><span aria-hidden="true">&raquo;</span></a>`;
            nextLi.addEventListener('click', (e) => { e.preventDefault(); if(currentPage < totalPages) displayPage(currentPage + 1); });
            paginationEl.appendChild(nextLi);
        }

        displayPage(1);
    }

    paginateTable("flightTable", "flightPagination", 7);
    paginateTable("mxTable", "mxPagination", 7);
    paginateTable("fuelTable", "fuelPagination", 7);

    // Fuel Estimator Logic
    const leftSlider = document.getElementById('leftFuelSlider');
    const rightSlider = document.getElementById('rightFuelSlider');
    const leftHeightDisp = document.getElementById('leftHeightDisplay');
    const rightHeightDisp = document.getElementById('rightHeightDisplay');
    const leftGalDisp = document.getElementById('leftGalDisplay');
    const rightGalDisp = document.getElementById('rightGalDisplay');
    const totalGalDisp = document.getElementById('totalGalDisplay');

    function updateFuelEstimate() {
        const leftVal = leftSlider.value;
        const rightVal = rightSlider.value;

        // Update the UI height text immediately
        leftHeightDisp.textContent = leftVal;
        rightHeightDisp.textContent = rightVal;

        // Fetch the calculation from the backend
        fetch('/api/estimate_fuel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ left_height: leftVal, right_height: rightVal })
        })
        .then(response => response.json())
        .then(data => {
            leftGalDisp.textContent = data.left_gallons.toFixed(2);
            rightGalDisp.textContent = data.right_gallons.toFixed(2);
            totalGalDisp.textContent = data.total_gallons.toFixed(2);
        })
        .catch(err => console.error("Error fetching fuel estimate:", err));
    }

    // Trigger calculation when sliders are moved
    if(leftSlider && rightSlider) {
        leftSlider.addEventListener('input', updateFuelEstimate);
        rightSlider.addEventListener('input', updateFuelEstimate);
    }

    // ====== FUEL PRICE LOGIC ======
    let fuelOptionsCache = [];
    function renderFuelPrices(limit) {
        const tbody = document.getElementById('pricesTableBody');
        tbody.innerHTML = '';

        const totalGallons = parseFloat(document.getElementById('totalGallonsInput').value) || 0;

        let filtered = [...fuelOptionsCache];

        // PERFORMANCE FIX: Use the already fetched 'totalGallons' variable.
        // The original code was querying the DOM and parsing a float on every single array comparison.
        filtered.sort((a, b) => {
            const costA = (a.price * totalGallons) + (a.price * a.used_to_return);
            const costB = (b.price * totalGallons) + (b.price * b.used_to_return);
            return costA - costB;
        });

        if (limit !== "all") {
            filtered = filtered.slice(0, parseInt(limit));
        }

        filtered.forEach(opt => {
            const tr = document.createElement('tr');
            const distanceStr = opt.distance > 0 ? `${opt.distance} nm ${opt.direction}` : '0 nm';
            const totalTripCost = (opt.price * totalGallons) + (opt.price * opt.used_to_return);

            // RESPONSIVE OPTIMIZATION: Swapped fixed min-widths for Bootstrap utility classes.
            // - 'text-nowrap' keeps prices, distances, and dates on a single line.
            // - 'text-wrap' on the airport name lets long names gracefully fold on mobile instead of blowing out the table width.
            tr.innerHTML = `
                <td>
                    <strong class="text-dark d-block">${opt.airport}</strong>
                    <small class="text-muted d-block text-wrap" style="max-width: 220px;">${opt.name}</small>
                </td>
                <td class="text-success fw-bold text-nowrap">
                    $${opt.price.toFixed(2)}
                </td>
                <td class="text-nowrap">
                    ${distanceStr}<br>
                    <small class="text-muted">(${opt.used_to_return.toFixed(1)} gal)</small>
                </td>
                <td class="text-nowrap">
                    <span class="fw-semibold">$${totalTripCost.toFixed(2)}</span><br>
                    <small class="text-muted">(${totalGallons.toFixed(1)} gal)</small>
                </td>
                <td class="text-muted small text-nowrap">${opt.date}</td>
            `;
            tbody.appendChild(tr);
        });

        document.getElementById('pricesTable').classList.remove('d-none');

        // REMOVED: The dynamic modal maxWidth javascript layout calculation.
        // Bootstrap's CSS classes (like 'modal-xl' and 'modal-fullscreen-sm-down') handle device widths
        // flawlessly native-side. Forcing element styles via JS here breaks mobile responsiveness.
    }

    function loadFuelPrices() {
        const airport = document.getElementById('searchAirportCode').value.trim();
        const limit = document.getElementById('priceLimitSelect').value;

        if (!airport) {
            alert("Please enter an airport code to search!");
            return;
        }

        const modalEl = document.getElementById('pricesResultModal');
        let resultModal = bootstrap.Modal.getInstance(modalEl);
        if (!resultModal) {
            resultModal = new bootstrap.Modal(modalEl);
        }
        // Only show if not already visible
        if (!modalEl.classList.contains('show')) {
            resultModal.show();
        }

        document.getElementById('pricesLoader').classList.remove('d-none');
        document.getElementById('pricesTable').classList.add('d-none');
        document.getElementById('pricesError').classList.add('d-none');
        document.getElementById('pricesTableBody').innerHTML = '';

        fetch(`/api/fuel_prices?airport=${encodeURIComponent(airport)}&limit=${encodeURIComponent(limit)}`)
            .then(response => response.json())
            .then(data => {
                document.getElementById('pricesLoader').classList.add('d-none');

                if (data.error) {
                    const errDiv = document.getElementById('pricesError');
                    errDiv.textContent = data.error;
                    errDiv.classList.remove('d-none');
                } else if (data.options && data.options.length > 0) {
                    fuelOptionsCache = data.options;
                    const limit = document.getElementById('priceLimitSelect').value;
                    renderFuelPrices(limit);
                }
            })
            .catch(err => {
                document.getElementById('pricesLoader').classList.add('d-none');
                const errDiv = document.getElementById('pricesError');
                errDiv.textContent = "Failed to connect to the server.";
                errDiv.classList.remove('d-none');
                console.error(err);
            });
    }

    document.getElementById('checkPricesBtn').addEventListener('click', function() {
        loadFuelPrices();
    });

    document.getElementById('searchAirportCode').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            loadFuelPrices();
        }
    });

    document.getElementById('priceLimitSelect').addEventListener('change', function () {
        const limit = this.value;
        renderFuelPrices(limit);
    });

    document.getElementById('totalGallonsInput').addEventListener('input', function () {
        const limit = document.getElementById('priceLimitSelect').value;
        renderFuelPrices(limit);
    });

    // ====== ROUTE ADVISOR LOGIC ======
    let routeMap = null;
    let routeLine = null;
    let routeMarkers = [];

    const routeModal = document.getElementById("routeAdvisorModal");
    routeModal.addEventListener("shown.bs.modal", function () {
        if (!routeMap) {
            routeMap = L.map("routeMap").setView([37.0, -95.0], 4);

            L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
                attribution: "&copy; OpenStreetMap contributors"
            }).addTo(routeMap);
        }
        setTimeout(() => {
            routeMap.invalidateSize();
        }, 200);
    });

    document.getElementById("routeAdvisorForm").addEventListener("submit", function(e) {
        e.preventDefault();

        const formData = new FormData(this);

        const resultBox = document.getElementById("routeResult");
        resultBox.classList.remove("d-none");
        resultBox.classList.remove("alert-danger");
        resultBox.classList.add("alert-info");
        resultBox.innerHTML = "Calculating route...";

        // Show map only after submission
        const mapEl = document.getElementById("routeMap");
        mapEl.classList.remove("d-none");

        setTimeout(() => {
            if (routeMap) {
                routeMap.invalidateSize();
            }
        }, 200);

        fetch("/route_advisor", {
            method: "POST",
            body: formData
        })
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                resultBox.classList.remove("alert-info");
                resultBox.classList.add("alert-danger");
                resultBox.innerHTML = data.error;
                return;
            }

            const routeStr = data.route_string || "";
            window.currentRouteData = data.route_data;
            const encodedRoute = encodeURIComponent(routeStr);
            const foreFlightDeepLink = `foreflightmobile://maps/search?q=${encodedRoute}`;

            let html = `<strong>Route:</strong><br>
            <div class="d-flex align-items-center gap-2 flex-wrap mb-2">
                <a href="https://www.skyvector.com/?fpl=${encodeURIComponent(routeStr)}" target="_blank" rel="noopener noreferrer">
                    ${routeStr}
                </a>
            </div>
            <div class="d-flex align-items-center gap-2 flex-wrap">
                <button type="button" class="btn btn-sm btn-primary" onclick="downloadDynonGPX()">
                    ⬇ Dynon GPX
                </button>
                <a href="${foreFlightDeepLink}" class="btn btn-sm btn-dark d-md-none">
                    ✈️ Open in ForeFlight
                </a>
            </div>
            <br><hr>`;

            if (data.route_data && data.route_data.length > 0) {
                html += `
                <div class="table-responsive">
                    <table class="table table-sm table-striped">
                        <thead>
                            <tr>
                                <th>Airport</th>
                                <th>Name</th>
                                <th>Location</th>
                                <th>Distance to Next</th>
                                <th>Price</th>
                            </tr>
                        </thead>
                        <tbody>
                `;

                data.route_data.forEach(stop => {
                    html += `
                        <tr>
                            <td><strong>${stop.airport_code}</strong></td>
                            <td>
                                ${stop.airport_url
                                    ? `<a href="${stop.airport_url}" target="_blank" rel="noopener noreferrer">${stop.airport_name || ""}</a>`
                                    : (stop.airport_name || "")
                                }
                            </td>
                            <td>${stop.location || ""}</td>
                            <td>${stop.distance_to_next || "-"}</td>
                            <td>
                                ${stop.price
                                    ? `$${parseFloat(String(stop.price).replace("$", "")).toFixed(2)}`
                                    : "-"
                                }
                            </td>
                        </tr>
                    `;
                });

                html += `
                        </tbody>
                    </table>
                </div>
                `;
            }

            resultBox.innerHTML = html;

            // Build route coordinates if available
            if (routeMap && data.route_data) {
                const coords = [];
                // Clear existing markers
                routeMarkers.forEach(m => routeMap.removeLayer(m));
                routeMarkers = [];
                data.route_data.forEach(stop => {
                    const lat = stop.lat || stop.latitude || stop.lat_deg;
                    const lon = stop.lon || stop.lng || stop.longitude;
                    if (lat !== undefined && lon !== undefined && lat !== null && lon !== null) {
                        const latLng = [parseFloat(lat), parseFloat(lon)];
                        coords.push(latLng);
                        const marker = L.marker(latLng)
                            .addTo(routeMap)
                            .bindPopup(
                                `<strong>${stop.airport_code}</strong><br>${stop.airport_name || ""}`
                            );
                        routeMarkers.push(marker);
                    }
                });
                if (routeLine) {
                    routeMap.removeLayer(routeLine);
                }
                if (coords.length > 1) {
                    routeLine = L.polyline(coords, {
                        color: "#0d6efd",
                        weight: 3
                    }).addTo(routeMap);
                    routeMap.fitBounds(routeLine.getBounds(), {
                        padding: [20, 20]
                    });
                }
            }
        })
        .catch(err => {
            resultBox.classList.remove("alert-info");
            resultBox.classList.add("alert-danger");
            resultBox.innerHTML = "Failed to load route.";
            console.error(err);
        });
    });

    // ====== DATABASE UPDATE MODAL LOGIC ======
    document.getElementById("dbUpdateForm").addEventListener("submit", function(e) {
        e.preventDefault();

        const form = this;
        const downloadPath = "~/Documents/RV-7/Software/sv_software/";

        // UI feedback elements
        let statusDiv = document.getElementById("dbUpdateStatus");
        if (!statusDiv) {
            statusDiv = document.createElement("div");
            statusDiv.id = "dbUpdateStatus";
            statusDiv.className = "alert mt-3";
            form.querySelector(".modal-body").appendChild(statusDiv);
        }

        statusDiv.classList.remove("d-none", "alert-danger", "alert-success");
        statusDiv.classList.add("alert-info");
        statusDiv.innerHTML = "Starting download...";

        fetch("/api/database_updates", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ download_path: downloadPath })
        })
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                statusDiv.classList.remove("alert-info");
                statusDiv.classList.add("alert-danger");
                statusDiv.innerHTML = data.error;
            } else {
                statusDiv.classList.remove("alert-info");
                statusDiv.classList.add("alert-success");
                statusDiv.innerHTML = "Download started successfully.";

                // Close modal after short delay
                setTimeout(() => {
                    const modalEl = document.getElementById("dbUpdateModal");
                    const modal = bootstrap.Modal.getInstance(modalEl);
                    if (modal) modal.hide();
                }, 1000);
            }
        })
        .catch(err => {
            statusDiv.classList.remove("alert-info");
            statusDiv.classList.add("alert-danger");
            statusDiv.innerHTML = "Failed to start download.";
            console.error(err);
        });
    });
});

// Add copyRouteToast to window inside DOMContentLoaded
document.addEventListener("DOMContentLoaded", function() {
    window.downloadExportFile = function(filename, content, contentType) {
        const blob = new Blob([content], { type: contentType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    };
    // 1. Dynon SkyView GPX Generator
    window.downloadDynonGPX = function() {
        if (!window.currentRouteData || window.currentRouteData.length === 0) return;

        let gpx = `<?xml version="1.0" encoding="UTF-8"?>\n`;
        gpx += `<gpx version="1.1" creator="Dynon SkyView">\n`;
        gpx += `  <rte>\n`;
        gpx += `    <name>Generated Route</name>\n`;

        window.currentRouteData.forEach(stop => {
            const lat = stop.lat || stop.latitude || stop.lat_deg;
            const lon = stop.lon || stop.lng || stop.longitude;
            const code = stop.airport_code || stop.identifier || "WPT";

            if (lat !== undefined && lon !== undefined) {
                gpx += `    <rtept lat="${lat}" lon="${lon}">\n`;
                gpx += `      <name>${code}</name>\n`;
                gpx += `.     <overfly>false</overfly>`
                gpx += `    </rtept>\n`;
            }
        });

        gpx += `  </rte>\n`;
        gpx += `</gpx>`;

        window.downloadExportFile('Dynon_Route.gpx', gpx, 'application/gpx+xml');
    };
});

document.addEventListener('DOMContentLoaded', function() {
    const exportBtn = document.getElementById('dynamicExportBtn');
    const tabs = document.querySelectorAll('button[data-bs-toggle="tab"]');

    tabs.forEach(tab => {
        tab.addEventListener('shown.bs.tab', function (event) {
            const targetId = event.target.id; // e.g., 'flight-tab'

            if (targetId === 'flight-tab') {
                exportBtn.href = '/export/flights';
            } else if (targetId === 'mx-tab') {
                exportBtn.href = '/export/mx';
            } else if (targetId === 'fuel-tab') {
                exportBtn.href = '/export/fuel';
            }
        });
    });
});

document.addEventListener("DOMContentLoaded", () => {
    // Array of the IDs for your creation modals
    const createModals = ['flightModal', 'mxModal', 'fuelModal'];

    createModals.forEach(modalId => {
        const modalElement = document.getElementById(modalId);

        if (modalElement) {
            // 'show.bs.modal' is a Bootstrap event that fires right as the modal starts to open
            modalElement.addEventListener('show.bs.modal', function () {
                const dateInput = this.querySelector('input[name="date"]');

                if (dateInput) {
                    const today = new Date();
                    const yyyy = today.getFullYear();
                    const mm = String(today.getMonth() + 1).padStart(2, '0');
                    const dd = String(today.getDate()).padStart(2, '0');

                    // Inject today's date
                    dateInput.value = `${yyyy}-${mm}-${dd}`;
                }
            });
        }
    });
});

document.addEventListener('DOMContentLoaded', function() {
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('oilFileInput');
    const uploadBtn = document.getElementById('uploadBtn');
    const nameDisplay = document.getElementById('fileSelectedName');
    const oilUploadForm = document.getElementById('oilUploadForm');
    const uploadZoneContainer = document.getElementById('uploadZoneContainer');
    const resultsZoneContainer = document.getElementById('resultsZoneContainer');
    const errorDiv = document.getElementById('uploadError');

    const showOilTrendsBtn = document.getElementById('showOilTrendsBtn');
    const oilTrendsContainer = document.getElementById('oilTrendsContainer');

    // Track if we have a successful upload so we know which screen to return to
    let hasParsedReport = false;

    // --- 1. Drop Zone & File Selection ---
    function handleFileSelection() {
        if (fileInput && fileInput.files.length > 0) {
            if (nameDisplay) {
                nameDisplay.textContent = "Selected: " + fileInput.files[0].name;
                nameDisplay.style.display = 'block';
            }
            if (uploadBtn) uploadBtn.disabled = false;
        }
    }

    if (dropZone && fileInput) {
        dropZone.addEventListener('click', () => fileInput.click());
        dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('bg-white'); });
        dropZone.addEventListener('dragleave', () => dropZone.classList.remove('bg-white'));
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('bg-white');
            fileInput.files = e.dataTransfer.files;
            handleFileSelection();
        });
        fileInput.addEventListener('change', handleFileSelection);
    }

    // --- 2. Form Submission ---
    if (oilUploadForm) {
        oilUploadForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const formData = new FormData(this);

            if (uploadBtn) {
                uploadBtn.disabled = true;
                uploadBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Processing...';
            }
            if (errorDiv) errorDiv.classList.add('d-none');

            fetch(this.action, { method: 'POST', body: formData })
            .then(response => {
                if (!response.ok) return response.json().then(err => { throw err; });
                return response.json();
            })
            .then(data => {
                hasParsedReport = true; // Mark that we have data!

                if (uploadZoneContainer) uploadZoneContainer.classList.add('d-none');
                if (resultsZoneContainer) resultsZoneContainer.classList.remove('d-none');
                if (oilTrendsContainer) oilTrendsContainer.classList.add('d-none'); // Ensure trends are hidden
                if (uploadBtn) uploadBtn.style.display = 'none';

                // Ensure button says "View Trends"
                if (showOilTrendsBtn) {
                    showOilTrendsBtn.textContent = "View Trends";
                    showOilTrendsBtn.classList.replace('btn-info', 'btn-outline-info');
                }

                // Populate UI
                const metaEl = document.getElementById('oilMetadata');
                if (metaEl) metaEl.innerHTML = `<div class="col-6"><strong>Date:</strong> ${data.metadata.date_sampled || 'N/A'}</div><div class="col-6"><strong>Oil Hrs:</strong> ${data.metadata.oil_hrs || 'N/A'}</div>`;

                const tbody = document.getElementById('oilMetalsTableBody');
                if (tbody) {
                    tbody.innerHTML = '';
                    for (const [metal, value] of Object.entries(data.metals)) {
                        tbody.innerHTML += `<tr><td>${metal}</td><td class="fw-bold">${value}</td></tr>`;
                    }
                }

                const diagEl = document.getElementById('oilDiagnosis');
                if (diagEl) diagEl.innerHTML = `<small><strong>Notes:</strong> ${data.diagnosis || 'None'}</small>`;
            })
            .catch(err => {
                console.error("Upload failed:", err);
                if (errorDiv) {
                    errorDiv.textContent = err.error || err.message || "An error occurred during upload.";
                    errorDiv.classList.remove('d-none');
                }
                if (uploadBtn) {
                    uploadBtn.disabled = false;
                    uploadBtn.innerHTML = 'Upload PDF';
                }
            });
        });
    }

    if (showOilTrendsBtn) {
        showOilTrendsBtn.addEventListener('click', function() {
            const isHidden = oilTrendsContainer.classList.contains('d-none');
            const plotDiv = document.getElementById('oilTrendPlot');

            if (isHidden) {
                // 1. Show the containers
                oilTrendsContainer.classList.remove('d-none');
                uploadZoneContainer.classList.add('d-none');
                resultsZoneContainer.classList.add('d-none');
                showOilTrendsBtn.textContent = hasParsedReport ? "Back to Results" : "Upload New Report";

                // 2. Clear old instances
                Plotly.purge(plotDiv);
                plotDiv.innerHTML = '<div class="text-center p-5">Rendering...</div>';

                fetch('/api/oil_trends')
                    .then(res => res.json())
                    .then(data => {
                        if (!data || data.length === 0) return;

                        const engineHrs = data.map(row => parseFloat(row.engine_hrs));
                        const metals = ['iron', 'copper', 'chromium', 'aluminum', 'nickel', 'lead'];

                        const traces = metals.map(metal => ({
                            x: engineHrs,
                            y: data.map(row => parseFloat(row[metal] || 0)),
                            name: metal.charAt(0).toUpperCase() + metal.slice(1),
                            type: 'scatter',
                            mode: 'lines+markers'
                        }));

                        const layout = {
                            title: 'Wear Metals Trend',
                            margin: { l: 50, r: 30, t: 50, b: 80 },
                            xaxis: { title: 'Engine Hours' },
                            yaxis: { title: 'PPM' , type: 'log'},
                            legend: { orientation: 'h', y: -0.3 },
                            autosize: true // Let CSS handle the dimensions
                        };

                        // 3. WAIT FOR ONE BROWSER PAINT CYCLE
                        // This ensures the d-none removal is finished
                        requestAnimationFrame(() => {
                            plotDiv.innerHTML = '';
                            Plotly.newPlot(plotDiv, traces, layout, {responsive: true});

                            // Force a second snap-to-size
                            setTimeout(() => {
                                Plotly.Plots.resize(plotDiv);
                            }, 200);
                        });
                    });
            } else {
                oilTrendsContainer.classList.add('d-none');
                showOilTrendsBtn.textContent = "View Trends";
                if (hasParsedReport) {
                    resultsZoneContainer.classList.remove('d-none');
                } else {
                    uploadZoneContainer.classList.remove('d-none');
                }
            }
        });
    }
});
document.addEventListener('DOMContentLoaded', function() {
    // 1. Check if there is a hash in the URL (e.g., #fuel)
    const hash = window.location.hash;

    if (hash) {
        // Find the tab trigger button that corresponds to this ID
        // The ID of the pane is 'fuel', but the button ID is 'fuel-tab'
        const tabTriggerEl = document.querySelector(`.nav-link[data-bs-target="${hash}"]`);

        if (tabTriggerEl) {
            const tab = new bootstrap.Tab(tabTriggerEl);
            tab.show();
        }
    }

    // 2. Update the Export button dynamically when switching tabs
    // This ensures the "Export to CSV" button always points to the right data
    const tabEls = document.querySelectorAll('button[data-bs-toggle="tab"]');
    const exportBtn = document.getElementById('dynamicExportBtn');

    tabEls.forEach(tabEl => {
        tabEl.addEventListener('shown.bs.tab', function (event) {
            const targetId = event.target.getAttribute('data-bs-target').replace('#', '');

            // Update the CSV link based on the active tab
            if (targetId === 'flight') exportBtn.href = "/export/flights";
            else if (targetId === 'mx') exportBtn.href = "/export/mx";
            else if (targetId === 'fuel') exportBtn.href = "/export/fuel";

            // Optional: Update the URL hash without reloading the page
            window.location.hash = targetId;
        });
    });
});
document.addEventListener('DOMContentLoaded', function() {
    // Initialize all tooltips on the page
    const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    const tooltipList = [...tooltipTriggerList].map(tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl));
});