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

    paginateTable("flightTable", "flightPagination", 10);
    paginateTable("mxTable", "mxPagination", 10);
    paginateTable("fuelTable", "fuelPagination", 10);

    // ====== FUEL PRICE LOGIC ======
    let fuelOptionsCache = [];
    function renderFuelPrices(limit) {
        const tbody = document.getElementById('pricesTableBody');
        tbody.innerHTML = '';

        const totalGallons = parseFloat(document.getElementById('totalGallonsInput').value) || 0;

        let filtered = [...fuelOptionsCache];

        if (limit !== "all") {
            filtered = filtered.slice(0, parseInt(limit));
        }

        // Sort by estimated total trip cost (lowest first)
        filtered.sort((a, b) => {
            const totalGallonsVal = parseFloat(document.getElementById('totalGallonsInput').value) || 0;
            const costA = (a.price * totalGallonsVal) + (a.price * a.used_to_return);
            const costB = (b.price * totalGallonsVal) + (b.price * b.used_to_return);
            return costA - costB;
        });

        filtered.forEach(opt => {
            const tr = document.createElement('tr');
            const distanceStr = opt.distance > 0 ? `${opt.distance} nm ${opt.direction}` : '0 nm';

            tr.innerHTML = `
                <td style="white-space: nowrap; min-width: ${Math.max(150, opt.name.length * 7)}px;">
                    <strong>${opt.airport}</strong><br>
                    <small class="text-muted">${opt.name}</small>
                </td>
                <td class="text-success fw-bold">$
                    ${opt.price.toFixed(2)}
                </td>
                <td style="white-space: nowrap; min-width: 150px;">
                    ${distanceStr}<br>
                    <small class="text-muted">
                        (${opt.used_to_return.toFixed(1)} gal)
                    </small>
                </td>
                <td>
                    $${(opt.price * totalGallons+(opt.price * opt.used_to_return)).toFixed(2)}<br>
                    <small class="text-muted">
                        (${totalGallons.toFixed(1)} gal)
                    </small>
                </td>
                <td>${opt.date}</td>
            `;
            tbody.appendChild(tr);
        });

        document.getElementById('pricesTable').classList.remove('d-none');
        // Dynamically adjust modal width based on the longest airport name
        const modalDialog = document.querySelector('#pricesResultModal .modal-dialog');
        const maxNameLength = Math.max(...filtered.map(o => o.name.length), 0);
        const dynamicWidth = Math.min(95, Math.max(60, maxNameLength * 0.8));
        modalDialog.style.maxWidth = dynamicWidth + '%';
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
        const downloadPath = "~/Documents/RV-7/SoftwareDocuments/projects/dynon/Software/sv_software/";

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