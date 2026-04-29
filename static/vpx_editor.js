// --- Hardware Mapping Table ---
// Maps physical connector pins to internal VPX system names and electrical constraints
const hardwareMap = {
    "J12-5": { name: "Flap", max: 10, io: "O" },
    "J12-6": { name: "Flap", max: 10, io: "O" },
    "J10-1": { name: "Starter", max: 10, io: "O" },
    "J12-9": { name: "EFIS", max: 5, io: "O" },
    "J12-11": { name: "Field_Pri", max: 5, io: "O" },
    "J8-1": { name: "5A-1", max: 5, io: "O" },
    "J8-3": { name: "5A-2", max: 5, io: "O" },
    "J8-4": { name: "5A-3", max: 5, io: "O" },
    "J8-5": { name: "5A-4", max: 5, io: "O" },
    "J8-6": { name: "5A-5", max: 5, io: "O" },
    "J8-7": { name: "5A-6", max: 5, io: "O" },
    "J8-8": { name: "5A-7", max: 5, io: "O" },
    "J10-2": { name: "5A-8", max: 5, io: "O" },
    "J10-4": { name: "5A-9", max: 5, io: "O" },
    "J10-7": { name: "5A-10", max: 5, io: "O" },
    "J10-8": { name: "5A-11", max: 5, io: "O" },
    "J10-10": { name: "5A-12", max: 5, io: "O" },
    "J12-8": { name: "5A-13", max: 5, io: "O" },
    "J8-2": { name: "10A-1", max: 10, io: "O" },
    "J10-3": { name: "10A-2", max: 10, io: "O" },
    "J10-5": { name: "10A-3", max: 10, io: "O" },
    "J12-1": { name: "10A-4", max: 10, io: "O" },
    "J12-3": { name: "10A-5", max: 10, io: "O" },
    "J12-7": { name: "10A-6", max: 10, io: "O" },
    "J10-6": { name: "15A-1", max: 15, io: "O" },
    "J12-2": { name: "15A-2", max: 15, io: "O" },
    "J12-12": { name: "15A-3", max: 15, io: "O" },
    "J12-10": { name: "3A-1", max: 3, io: "O" },
    "J1-1": { name: "2A-1", max: 2, io: "O" },
    "J1-2": { name: "2A-2", max: 2, io: "O" },
    "J1-6": { name: "Trim Roll", max: 1, io: "O" },
    "J1-11": { name: "Trim Pitch", max: 1, io: "O" },
    "J2-1": { name: "S1", max: 0, io: "I" },
    "J2-2": { name: "S2", max: 0, io: "I" },
    "J2-3": { name: "S3", max: 0, io: "I" },
    "J2-4": { name: "S4", max: 0, io: "I" },
    "J2-5": { name: "S5", max: 0, io: "I" },
    "J2-6": { name: "S6", max: 0, io: "I" },
    "J2-7": { name: "S7", max: 0, io: "I" },
    "J2-8": { name: "S8", max: 0, io: "I" },
    "J2-9": { name: "S9", max: 0, io: "I" },
    "J2-10": { name: "S10", max: 0, io: "I" }
};

const connectors = [
    { id: 'J8', pins: 8, desc: 'High Current' },
    { id: 'J10', pins: 10, desc: 'Medium Current' },
    { id: 'J12', pins: 12, desc: 'Medium Current' },
    { id: 'J1', pins: 25, desc: 'Inputs/Low Power' },
    { id: 'J2', pins: 25, desc: 'Switch Inputs' }
];

let currentSelectedPin = null;
let deviceLibrary = [];
let switchLibrary = [];

// Update Initialization to be async
document.addEventListener("DOMContentLoaded", async () => {
    await loadLibraries(); // Load data before rendering
    renderConnectors();
    renderAll();
});

// New function to fetch JSON data
async function loadLibraries() {
    try {
        const [deviceRes, switchRes] = await Promise.all([
            fetch('/static/deviceLibrary.json'), // Update path as needed
            fetch('/static/switchLibrary.json')
        ]);

        deviceLibrary = await deviceRes.json();
        switchLibrary = await switchRes.json();

        console.log("Libraries loaded successfully");
    } catch (error) {
        console.error("Error loading JSON libraries:", error);
        // Fallback defaults in case of fetch error
        deviceLibrary = [{ id: 1, name: 'Default EFIS', breaker: 5, switchVal: 'AlwaysOn' }];
        switchLibrary = ['AlwaysOff', 'AlwaysOn'];
    }
}

async function saveLibraryToServer(type) {
    const data = type === 'device' ? deviceLibrary : switchLibrary;
    const endpoint = type === 'device' ? '/save-devices' : '/save-switches';
    const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });

    if (!response.ok) alert(`${type} Error saving library!`);
}

// Initialization
document.addEventListener("DOMContentLoaded", () => {
    renderConnectors();
    renderAll();
});

// --- Device Library CRUD ---
function openDeviceModal() {
    // Reset modal fields for a new entry
    document.getElementById('editDeviceId').value = '';
    document.getElementById('devName').value = '';
    document.getElementById('devBreaker').value = '5';

    // Refresh switch dropdown in modal to ensure it matches current switch library
    const modalSw = document.getElementById('devSwitch');
    modalSw.innerHTML = switchLibrary.map(sw => `<option value="${sw}">${sw}</option>`).join('');

    // Show the Bootstrap modal
    new bootstrap.Modal(document.getElementById('deviceModal')).show();
}

function saveDevice() {
    const idInput = document.getElementById('editDeviceId').value;
    const newDev = {
        id: idInput ? parseInt(idInput) : Date.now(),
        name: document.getElementById('devName').value || 'New Device',
        breaker: parseInt(document.getElementById('devBreaker').value),
        switchVal: document.getElementById('devSwitch').value
    };

    const idx = deviceLibrary.findIndex(d => d.id === newDev.id);
    if (idx > -1) {
        deviceLibrary[idx] = newDev; // Update existing
    } else {
        deviceLibrary.push(newDev); // Add new
    }

    renderAll();
    saveLibraryToServer('device')
    bootstrap.Modal.getInstance(document.getElementById('deviceModal')).hide();
}

// --- Switch Library CRUD ---
function openSwitchModal() {
    document.getElementById('editSwitchId').value = '';
    document.getElementById('swLabel').value = '';
    new bootstrap.Modal(document.getElementById('switchModal')).show();
}

function saveSwitch() {
    const val = document.getElementById('swLabel').value;
    const id = document.getElementById('editSwitchId').value;

    if (!val) return;

    if (id !== "") {
        switchLibrary[id] = val; // Update existing
    } else {
        switchLibrary.push(val); // Add new
    }

    renderAll();
    saveLibraryToServer('switch')
    bootstrap.Modal.getInstance(document.getElementById('switchModal')).hide();
}

function renderConnectors() {
    const list = document.getElementById('connectorList');
    list.innerHTML = connectors.map(conn => `
        <div class="connector-wrap">
            <div class="connector-header">
                <span class="fw-bold">${conn.id}</span>
                <small class="opacity-75">${conn.desc}</small>
            </div>
            <div class="connector-body">
                ${Array.from({length: conn.pins}, (_, i) => renderPinRow(conn.id, i + 1)).join('')}
            </div>
        </div>
    `).join('');
}

function renderPinRow(cid, pnum) {
    const pinId = `${cid}-${pnum}`;
    const map = hardwareMap[pinId];
    const isInput = map && map.io === "I";
    const maxAmp = map ? map.max : 15;

    return `
        <div class="pin-row row align-items-center flex-nowrap" id="row-${pinId}" onclick="selectPin('${pinId}')">
            <div class="col-auto pin-id">${pinId}</div>
            <div class="col-md-4">
                <input type="text" class="form-control form-control-sm border-0 bg-light" id="nm-${pinId}" placeholder="${isInput ? 'Input Signal' : 'Circuit Name'}">
            </div>
            <div class="col-md-2">
                <div class="input-group input-group-sm">
                    <select class="form-select form-select-sm border-0 bg-light" id="br-${pinId}" ${isInput ? 'disabled' : ''}>
                        ${Array.from({length: maxAmp}, (_, i) => `<option value="${i+1}">${i+1}</option>`).join('')}
                    </select>
                    <span class="input-group-text border-0 bg-light">A</span>
                </div>
            </div>
            <div class="col-md-3">
                <select class="form-select form-select-sm border-0 bg-light switch-select" id="sw-${pinId}"></select>
            </div>
            <div class="col-md-1 text-center">
                <div class="form-check form-switch d-inline-block">
                    <input class="form-check-input" type="checkbox" id="en-${pinId}">
                </div>
            </div>
        </div>
    `;
}

function renderAll() {
    renderDeviceLibrary();
    renderSwitchLibrary();
    updateAllSwitchDropdowns();
}

// --- Updated Device Library CRUD ---
function renderDeviceLibrary() {
    const container = document.getElementById('deviceLibraryContent');
    container.innerHTML = deviceLibrary.map(dev => `
        <div class="col-6 p-1 mb-2">
            <div class="device-card" onclick="applyDevice(${dev.id})">
                <div class="d-flex justify-content-between align-items-start">
                    <div class="device-icon-area">${dev.name.charAt(0)}</div>
                    <div class="btn-group">
                        <button class="btn btn-link btn-sm p-0 text-primary me-2" onclick="editDevice(${dev.id}, event)" style="font-size:0.65rem;">EDIT</button>
                        <button class="btn btn-link btn-sm p-0 text-danger" onclick="deleteDevice(${dev.id}, event)" style="font-size:0.65rem;">DEL</button>
                    </div>
                </div>
                <div class="card-title">${dev.name}</div>
                <div class="card-meta">${dev.breaker}A • ${dev.switchVal}</div>
            </div>
        </div>
    `).join('');
}

function editDevice(id, event) {
    event.stopPropagation(); // Prevents applying device to selected pin
    const dev = deviceLibrary.find(d => d.id === id);
    if (!dev) return;

    document.getElementById('editDeviceId').value = dev.id;
    document.getElementById('devName').value = dev.name;
    document.getElementById('devBreaker').value = dev.breaker;

    const modalSw = document.getElementById('devSwitch');
    modalSw.innerHTML = switchLibrary.map(sw => `<option value="${sw}">${sw}</option>`).join('');
    modalSw.value = dev.switchVal;

    new bootstrap.Modal(document.getElementById('deviceModal')).show();
}

function deleteDevice(id, event) {
    event.stopPropagation();
    if (confirm("Are you sure you want to remove this device from the library?")) {
        deviceLibrary = deviceLibrary.filter(d => d.id !== id);
        renderAll();
        saveLibraryToServer('device')
    }
}

// --- Updated Switch Library CRUD ---
function renderSwitchLibrary() {
    const container = document.getElementById('switchLibraryContent');
    container.innerHTML = switchLibrary.map((sw, idx) => `
        <div class="switch-list-item d-flex justify-content-between align-items-center">
            <span class="fw-medium">${sw}</span>
            <div class="btn-group">
                <button class="btn btn-link btn-sm p-0 text-primary me-2" onclick="editSwitch(${idx}, event)" style="font-size:0.7rem;">Edit</button>
                <button class="btn btn-link btn-sm p-0 text-danger" onclick="deleteSwitch(${idx}, event)" style="font-size:0.7rem;">Del</button>
            </div>
        </div>
    `).join('');
}

function editSwitch(idx, event) {
    event.stopPropagation();
    document.getElementById('editSwitchId').value = idx;
    document.getElementById('swLabel').value = switchLibrary[idx];
    new bootstrap.Modal(document.getElementById('switchModal')).show();
}

function deleteSwitch(idx, event) {
    event.stopPropagation();
    const swName = switchLibrary[idx];
    if (confirm(`Delete switch "${swName}"? This will not affect devices already assigned to it.`)) {
        switchLibrary.splice(idx, 1);
        renderAll();
        saveLibraryToServer('switch')
    }
}

function updateAllSwitchDropdowns() {
    document.querySelectorAll('.switch-select').forEach(select => {
        const val = select.value;
        select.innerHTML = switchLibrary.map(sw => `<option value="${sw}">${sw}</option>`).join('');
        if (switchLibrary.includes(val)) select.value = val;
    });
}

function selectPin(pinId) {
    document.querySelectorAll('.pin-row').forEach(r => r.classList.remove('active-selection'));
    currentSelectedPin = pinId;
    document.getElementById(`row-${pinId}`).classList.add('active-selection');
}

function applyDevice(devId) {
    const dev = deviceLibrary.find(d => d.id === devId);
    if (!currentSelectedPin || !dev) return;

    const map = hardwareMap[currentSelectedPin];
    if (map && dev.breaker > map.max && map.io !== "I") {
        alert(`Pin ${currentSelectedPin} only supports up to ${map.max}A. This device requires ${dev.breaker}A.`);
        return;
    }

    document.getElementById(`nm-${currentSelectedPin}`).value = dev.name;
    if (map && map.io !== "I") document.getElementById(`br-${currentSelectedPin}`).value = dev.breaker;
    document.getElementById(`sw-${currentSelectedPin}`).value = dev.switchVal;
    document.getElementById(`en-${currentSelectedPin}`).checked = true;
}

function exportConfig() {
    const config = [];
    document.querySelectorAll('.pin-row').forEach(row => {
        const pinId = row.id.replace('row-', '');
        const enabled = document.getElementById(`en-${pinId}`).checked;

        if (enabled) {
            const hardware = hardwareMap[pinId];
            const systemId = hardware ? hardware.name : pinId;

            config.push({
                hardware_pin: pinId,
                system_id: systemId,
                name: document.getElementById(`nm-${pinId}`).value,
                amps: document.getElementById(`br-${pinId}`).value,
                switch: document.getElementById(`sw-${pinId}`).value
            });
        }
    });

    console.log("Exporting Mapping Logic:", config);
    alert("Export compiled with hardware system IDs mapping.");
}