/**
 * Van's Aircraft Painting Prototype Design Hub - Interactive Vector Studio Controller
 * Scaled Coordinate Engine: Pixel-exact click alignment via getScreenCTM().inverse(),
 * proportional node handles, and non-scaling-stroke vector lines.
 */

document.addEventListener('DOMContentLoaded', function() {
    
    // --- Sherwin-Williams Aerospace Color Database ---
    const SW_AEROSPACE_COLORS = [
        { code: "SW1001", name: "Insignia White", hex: "#FFFFFF", line: "skyscapes", finish: "gloss" },
        { code: "SW1002", name: "Matterhorn White", hex: "#F4F5F0", line: "jetglo", finish: "gloss" },
        { code: "SW1003", name: "Jet Black", hex: "#111111", line: "jetglo", finish: "gloss" },
        { code: "SW1004", name: "Vader Matte Black", hex: "#1C1D21", line: "jetglo", finish: "matte" },
        { code: "SW2001", name: "Cadillac Red", hex: "#D61A1F", line: "acryglo", finish: "gloss" },
        { code: "SW2002", name: "Victory Crimson Metallic", hex: "#8B0000", line: "skyscapes", finish: "metallic" },
        { code: "SW3001", name: "Tahiti Blue Metallic", hex: "#0047AB", line: "skyscapes", finish: "metallic" },
        { code: "SW3002", name: "Navy Blue", hex: "#001F3F", line: "jetglo", finish: "gloss" },
        { code: "SW3003", name: "Sky Blue", hex: "#399CBD", line: "acryglo", finish: "gloss" },
        { code: "SW4001", name: "Sunburst Yellow", hex: "#FFD700", line: "acryglo", finish: "gloss" },
        { code: "SW5001", name: "Titanium Silver Metallic", hex: "#C0C0C0", line: "skyscapes", finish: "metallic" },
        { code: "SW5002", name: "Charcoal Gray Metallic", hex: "#36454F", line: "skyscapes", finish: "metallic" },
        { code: "SW6001", name: "Emerald Green", hex: "#008751", line: "acryglo", finish: "gloss" },
        { code: "SW7001", name: "Champagne Gold Metallic", hex: "#D4AF37", line: "skyscapes", finish: "metallic" },
        { code: "SW8001", name: "Safety Orange", hex: "#FF6600", line: "acryglo", finish: "gloss" },
        { code: "SW9001", name: "Stealth Blue Gray", hex: "#4B5563", line: "jetglo", finish: "satin" }
    ];

    // --- State Variables ---
    let currentModelId = "rv7";
    let activeView = "split"; // 'side', 'top', 'front', 'combined', 'split'
    let activeColor = SW_AEROSPACE_COLORS[4]; // Cadillac Red default
    let sectionColors = {};
    let showGuides = true;
    let clipToModel = true;

    // SVG Geometry Cache for ClipPath
    const svgContentCache = {};

    // N-Number Registration Customization State
    let nNumber = "N890GF";
    let nNumberFont = "Outfit";
    let nNumberViewTarget = "side"; // 'side', 'top', 'both'
    let nNumberSize = 0.15; // Ratio relative to vh
    let nNumberRotation = 0; // Degrees
    let nNumberFill = "#000000";
    let nNumberStroke = "#FFFFFF";
    let nNumberPos = { side: null, top: null, combined: null }; // Custom drag & drop coords {x, y}

    // Vector Drawing Engine State
    let activeDrawTool = "select"; // 'select', 'pen', 'spline', 'line', 'rect', 'circle', 'swoosh'
    let drawnShapes = [];
    let selectedShapeId = null;
    
    // Multi-Point Pen & Spline State
    let multiPoints = [];
    let currentPenViewType = null;

    // Drawing & Dragging State
    let isDrawing = false;
    let isDraggingShape = false;
    let isDraggingNNumber = false;
    let dragStartMouseCoords = null;
    let dragInitialShapeState = null;
    let dragInitialNNumberPos = null;
    let drawStartCoords = null;
    let tempShape = null;

    // Drawn Shape Default Styles
    let currentFillColor = "#D61A1F";
    let currentFillOpacity = 0.85;
    let currentStrokeColor = "#000000";
    let currentStrokeWidth = 1; // Default 1px crisp stroke
    let currentCornerRadius = 4; // Corner Curvature for Rectangles
    let currentRotation = 0;

    // History Stacks
    let historyStack = [];
    let redoStack = [];

    // --- Initialization ---
    initSwatches();
    initModelSelector();
    initViewSwitcher();
    initTabNavigation();
    initColorSectionDefaults();
    initDrawingTools();
    renderAllViews();
    bindEvents();

    // --- Swatches Initialization ---
    function initSwatches() {
        const grid = document.getElementById("swatchGrid");
        if (!grid) return;
        grid.innerHTML = "";

        const lineFilter = document.getElementById("swLineSelector").value;

        SW_AEROSPACE_COLORS.forEach((sw) => {
            if (lineFilter !== "all" && sw.line !== lineFilter) return;

            const item = document.createElement("div");
            item.className = `swatch-item ${sw.code === activeColor.code ? 'active' : ''}`;
            item.style.backgroundColor = sw.hex;
            item.dataset.code = sw.code;

            const tooltip = document.createElement("div");
            tooltip.className = "swatch-tooltip";
            tooltip.innerText = `${sw.name} (${sw.code})`;
            item.appendChild(tooltip);

            item.addEventListener("click", () => {
                document.querySelectorAll(".swatch-item").forEach(s => s.classList.remove("active"));
                item.classList.add("active");
                setActiveColor(sw);
            });

            grid.appendChild(item);
        });
    }

    function setActiveColor(sw) {
        activeColor = sw;
        currentFillColor = sw.hex;
        document.getElementById("activeSwatchPreview").style.backgroundColor = sw.hex;
        document.getElementById("activeSwatchName").innerText = sw.name;
        document.getElementById("activeSwatchCode").innerText = `SW Code: ${sw.code} (${sw.line.toUpperCase()})`;
        document.getElementById("customColorPicker").value = sw.hex;
        document.getElementById("customColorHex").value = sw.hex.toUpperCase();

        document.getElementById("shapeFillColorPicker").value = sw.hex;
        document.getElementById("shapeFillPreview").style.backgroundColor = sw.hex;

        if (selectedShapeId) {
            updateSelectedShapeProperties();
        }
    }

    // --- Default Section Colors ---
    function initColorSectionDefaults() {
        sectionColors = {};
        window.VANS_DEFAULT_SECTIONS.forEach(sec => {
            sectionColors[sec.id] = sec.defaultColor;
        });
        saveStateToHistory();
        updatePaletteSummary();
        renderSectionLayerList();
    }

    // --- History Tracking ---
    function saveStateToHistory() {
        historyStack.push(JSON.stringify({
            sections: sectionColors,
            shapes: drawnShapes,
            nNumberPos: nNumberPos
        }));
        if (historyStack.length > 30) historyStack.shift();
        redoStack = [];
    }

    function undo() {
        if (historyStack.length <= 1) return;
        redoStack.push(historyStack.pop());
        const state = JSON.parse(historyStack[historyStack.length - 1]);
        sectionColors = state.sections || sectionColors;
        drawnShapes = state.shapes || [];
        nNumberPos = state.nNumberPos || nNumberPos;
        renderAllViews();
        updatePaletteSummary();
        renderSectionLayerList();
    }

    function redo() {
        if (redoStack.length === 0) return;
        const stateStr = redoStack.pop();
        historyStack.push(stateStr);
        const state = JSON.parse(stateStr);
        sectionColors = state.sections || sectionColors;
        drawnShapes = state.shapes || [];
        nNumberPos = state.nNumberPos || nNumberPos;
        renderAllViews();
        updatePaletteSummary();
        renderSectionLayerList();
    }

    // --- Model Switcher ---
    function initModelSelector() {
        const sel = document.getElementById("modelSelector");
        if (!sel) return;

        sel.addEventListener("change", (e) => {
            currentModelId = e.target.value;
            updateModelSpecsCard();
            renderAllViews();
        });
        updateModelSpecsCard();
    }

    function updateModelSpecsCard() {
        const model = window.VANS_AIRCRAFT_MODELS[currentModelId];
        if (!model) return;
        document.getElementById("modelCardName").innerText = `${model.name} Specs`;
        document.getElementById("modelCardDesc").innerText = model.description;
        document.getElementById("specWingspan").innerText = model.wingspanFt;
        document.getElementById("specLength").innerText = model.lengthFt;
        document.getElementById("specGear").innerText = model.gear === 'tricycle' ? 'Tricycle (Nosewheel)' : 'Taildragger';
        document.getElementById("specWeight").innerText = model.emptyWeight;
    }

    // --- View Switcher ---
    function initViewSwitcher() {
        const buttons = document.querySelectorAll(".view-btn");
        buttons.forEach(btn => {
            btn.addEventListener("click", () => {
                buttons.forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                activeView = btn.dataset.view;
                applyViewLayout();
            });
        });
    }

    function applyViewLayout() {
        const grid = document.getElementById("viewsGrid");
        const cardSide = document.getElementById("cardSideView");
        const cardTop = document.getElementById("cardTopView");
        const cardFront = document.getElementById("cardFrontView");
        const cardCombined = document.getElementById("cardCombinedView");

        if (activeView === "split") {
            grid.className = "views-grid split-4-view";
            if (cardSide) cardSide.style.display = "flex";
            if (cardTop) cardTop.style.display = "flex";
            if (cardFront) cardFront.style.display = "flex";
            if (cardCombined) cardCombined.style.display = "flex";
        } else {
            grid.className = "views-grid single-view";
            if (cardSide) cardSide.style.display = activeView === "side" ? "flex" : "none";
            if (cardTop) cardTop.style.display = activeView === "top" ? "flex" : "none";
            if (cardFront) cardFront.style.display = activeView === "front" ? "flex" : "none";
            if (cardCombined) cardCombined.style.display = activeView === "combined" ? "flex" : "none";
        }
    }

    // --- Tabs Navigation ---
    function initTabNavigation() {
        const tabBtns = document.querySelectorAll(".tab-btn");
        tabBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                tabBtns.forEach(b => b.classList.remove("active"));
                btn.classList.add("active");

                const targetTab = btn.dataset.tab;
                document.querySelectorAll(".tab-pane").forEach(pane => {
                    pane.style.display = pane.id === targetTab ? "block" : "none";
                });
            });
        });
    }

    // --- Vector Drawing Tools Selection ---
    function initDrawingTools() {
        const toolBtns = document.querySelectorAll(".draw-tool-btn, .tool-quick-btn");
        toolBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                toolBtns.forEach(b => b.classList.remove("active"));
                const tool = btn.dataset.tool;
                
                if (multiPoints.length > 1 && currentPenViewType && (activeDrawTool === 'pen' || activeDrawTool === 'spline')) {
                    finalizeMultiPointShape();
                }

                activeDrawTool = tool;
                multiPoints = [];
                currentPenViewType = null;

                document.querySelectorAll(`[data-tool="${tool}"]`).forEach(b => b.classList.add("active"));
            });
        });

        // Property Controls
        document.getElementById("shapeFillColorPicker")?.addEventListener("input", (e) => {
            currentFillColor = e.target.value;
            document.getElementById("shapeFillPreview").style.backgroundColor = currentFillColor;
            if (selectedShapeId) updateSelectedShapeProperties();
        });

        document.getElementById("shapeFillOpacity")?.addEventListener("input", (e) => {
            currentFillOpacity = parseFloat(e.target.value);
            if (selectedShapeId) updateSelectedShapeProperties();
        });

        document.getElementById("shapeStrokeColorPicker")?.addEventListener("input", (e) => {
            currentStrokeColor = e.target.value;
            document.getElementById("shapeStrokePreview").style.backgroundColor = currentStrokeColor;
            if (selectedShapeId) updateSelectedShapeProperties();
        });

        document.getElementById("shapeStrokeWidth")?.addEventListener("input", (e) => {
            currentStrokeWidth = parseFloat(e.target.value);
            if (selectedShapeId) updateSelectedShapeProperties();
        });

        document.getElementById("shapeCornerRadius")?.addEventListener("input", (e) => {
            currentCornerRadius = parseFloat(e.target.value);
            document.getElementById("shapeCornerRadiusVal").innerText = `${currentCornerRadius}px`;
            if (selectedShapeId) updateSelectedShapeProperties();
        });

        document.getElementById("shapeRotation")?.addEventListener("input", (e) => {
            currentRotation = parseFloat(e.target.value);
            document.getElementById("shapeRotationVal").innerText = `${currentRotation}°`;
            if (selectedShapeId) updateSelectedShapeProperties();
        });

        document.getElementById("btnDeleteSelectedShape")?.addEventListener("click", () => {
            if (selectedShapeId) {
                drawnShapes = drawnShapes.filter(s => s.id !== selectedShapeId);
                selectedShapeId = null;
                saveStateToHistory();
                renderAllViews();
            }
        });

        document.getElementById("btnClearAllShapes")?.addEventListener("click", () => {
            drawnShapes = [];
            selectedShapeId = null;
            multiPoints = [];
            currentPenViewType = null;
            saveStateToHistory();
            renderAllViews();
        });
    }

    function updateSelectedShapeProperties() {
        const shape = drawnShapes.find(s => s.id === selectedShapeId);
        if (!shape) return;
        shape.fill = currentFillColor;
        shape.fillOpacity = currentFillOpacity;
        shape.stroke = currentStrokeColor;
        shape.strokeWidth = currentStrokeWidth;
        shape.cornerRadius = currentCornerRadius;
        shape.rotation = currentRotation;
        renderAllViews();
    }

    function syncSelectedShapePanel(shape) {
        if (!shape) return;
        currentFillColor = shape.fill || "#D61A1F";
        currentFillOpacity = shape.fillOpacity !== undefined ? shape.fillOpacity : 0.85;
        currentStrokeColor = shape.stroke || "#000000";
        currentStrokeWidth = shape.strokeWidth !== undefined ? shape.strokeWidth : 1;
        currentCornerRadius = shape.cornerRadius !== undefined ? shape.cornerRadius : 4;
        currentRotation = shape.rotation || 0;

        document.getElementById("shapeFillColorPicker").value = currentFillColor;
        document.getElementById("shapeFillPreview").style.backgroundColor = currentFillColor;
        document.getElementById("shapeFillOpacity").value = currentFillOpacity;
        document.getElementById("shapeStrokeColorPicker").value = currentStrokeColor;
        document.getElementById("shapeStrokePreview").style.backgroundColor = currentStrokeColor;
        document.getElementById("shapeStrokeWidth").value = currentStrokeWidth;
        document.getElementById("shapeCornerRadius").value = currentCornerRadius;
        document.getElementById("shapeCornerRadiusVal").innerText = `${currentCornerRadius}px`;
        document.getElementById("shapeRotation").value = currentRotation;
        document.getElementById("shapeRotationVal").innerText = `${currentRotation}°`;
    }

    // --- Catmull-Rom Smooth Spline Curve Generator ---
    function pointsToSplineD(points, closed = false) {
        if (!points || points.length < 2) return "";
        if (points.length === 2) {
            return `M ${points[0].x.toFixed(2)},${points[0].y.toFixed(2)} L ${points[1].x.toFixed(2)},${points[1].y.toFixed(2)}`;
        }

        let d = `M ${points[0].x.toFixed(2)},${points[0].y.toFixed(2)}`;
        const tension = 0.25;

        for (let i = 0; i < points.length - 1; i++) {
            const p0 = points[i === 0 ? i : i - 1];
            const p1 = points[i];
            const p2 = points[i + 1];
            const p3 = points[i + 2 < points.length ? i + 2 : i + 1];

            const cp1x = p1.x + (p2.x - p0.x) * tension;
            const cp1y = p1.y + (p2.y - p0.y) * tension;
            const cp2x = p2.x - (p3.x - p1.x) * tension;
            const cp2y = p2.y - (p3.y - p1.y) * tension;

            d += ` C ${cp1x.toFixed(2)},${cp1y.toFixed(2)} ${cp2x.toFixed(2)},${cp2y.toFixed(2)} ${p2.x.toFixed(2)},${p2.y.toFixed(2)}`;
        }

        if (closed) d += " Z";
        return d;
    }

    function pointsToPolylineD(points) {
        if (!points || points.length === 0) return "";
        return points.map((p, idx) => `${idx === 0 ? 'M' : 'L'} ${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ');
    }

    function finalizeMultiPointShape() {
        if (multiPoints.length < 2 || !currentPenViewType) {
            multiPoints = [];
            currentPenViewType = null;
            renderAllViews();
            return;
        }

        const pathD = activeDrawTool === 'spline' 
            ? pointsToSplineD(multiPoints, true) 
            : pointsToPolylineD(multiPoints) + " Z";

        const newShape = {
            id: "shape_" + Date.now() + "_" + Math.floor(Math.random()*1000),
            type: activeDrawTool === 'spline' ? 'spline' : 'pen',
            viewType: currentPenViewType,
            pathD: pathD,
            points: [...multiPoints],
            fill: currentFillColor,
            fillOpacity: currentFillOpacity,
            stroke: currentStrokeColor,
            strokeWidth: currentStrokeWidth,
            cornerRadius: currentCornerRadius,
            rotation: currentRotation
        };

        drawnShapes.push(newShape);
        selectedShapeId = newShape.id;
        multiPoints = [];
        currentPenViewType = null;
        saveStateToHistory();
        renderAllViews();
    }

    // --- Inline XML Loader for ClipPath Geometry ---
    function fetchAndCacheSvg(url, callback) {
        if (svgContentCache[url]) {
            callback(svgContentCache[url]);
            return;
        }
        fetch(url + '?v=1.3')
            .then(res => res.text())
            .then(xmlText => {
                const parser = new DOMParser();
                const doc = parser.parseFromString(xmlText, "image/svg+xml");
                const gEl = doc.querySelector("g");
                
                let innerContent = "";
                if (gEl) {
                    innerContent = gEl.innerHTML;
                } else {
                    const svgEl = doc.querySelector("svg");
                    if (svgEl) innerContent = svgEl.innerHTML;
                }
                svgContentCache[url] = innerContent;
                callback(innerContent);
            })
            .catch(err => {
                console.error("Error fetching SVG clip path:", err);
                callback("");
            });
    }

    // --- SVG Standalone View Renderer ---
    function renderAllViews() {
        renderSvgView("side", "svgContainerSide");
        renderSvgView("top", "svgContainerTop");
        renderSvgView("front", "svgContainerFront");
        renderSvgView("combined", "svgContainerCombined");
    }

    function getShapeCenter(shape) {
        if (shape.type === 'line') {
            return { cx: (shape.x1 + shape.x2) / 2, cy: (shape.y1 + shape.y2) / 2 };
        } else if (shape.type === 'rect') {
            return { cx: shape.x + shape.width / 2, cy: shape.y + shape.height / 2 };
        } else if (shape.type === 'circle') {
            return { cx: shape.cx, cy: shape.cy };
        } else if (shape.type === 'swoosh' || shape.type === 'pen' || shape.type === 'spline') {
            const nums = (shape.pathD.match(/[-+]?\d*\.?\d+/g) || []).map(Number);
            let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
            for (let i = 0; i < nums.length; i += 2) {
                minX = Math.min(minX, nums[i]);
                maxX = Math.max(maxX, nums[i]);
                if (i + 1 < nums.length) {
                    minY = Math.min(minY, nums[i+1]);
                    maxY = Math.max(maxY, nums[i+1]);
                }
            }
            return { cx: (minX + maxX) / 2, cy: (minY + maxY) / 2 };
        }
        return { cx: 0, cy: 0 };
    }

    function renderSvgView(viewType, containerId) {
        const container = document.getElementById(containerId);
        const model = window.VANS_AIRCRAFT_MODELS[currentModelId];
        if (!container || !model || !model.views[viewType]) return;

        const vDef = model.views[viewType];
        const vb = vDef.viewBox.split(" ").map(Number);
        const vw = vb[2], vh = vb[3];

        let svgHtml = `<svg id="svgElement_${viewType}" data-view="${viewType}" viewBox="${vDef.viewBox}" xmlns="http://www.w3.org/2000/svg" style="width: 100%; height: 100%; user-select: none; background: #ffffff;">`;

        // 0. Define SVG ClipPath from Aircraft Structural Component Hull
        const clipId = `modelClip_${currentModelId}_${viewType}`;
        const hullMarkup = (window.VANS_AIRCRAFT_CLIP_HULLS && window.VANS_AIRCRAFT_CLIP_HULLS[currentModelId]) 
            ? window.VANS_AIRCRAFT_CLIP_HULLS[currentModelId][viewType] 
            : '';

        const hasClip = clipToModel && viewType !== 'combined' && hullMarkup;

        svgHtml += `<defs>`;
        if (hasClip) {
            svgHtml += `  <clipPath id="${clipId}">`;
            svgHtml += `    ${hullMarkup}`;
            svgHtml += `  </clipPath>`;
        } else {
            svgHtml += `  <clipPath id="${clipId}">`;
            svgHtml += `    <rect x="0" y="0" width="${vw}" height="${vh}" rx="4" />`;
            svgHtml += `  </clipPath>`;
        }
        svgHtml += `</defs>`;

        // 1. Base Fuselage Section Backdrop
        const fuseColor = sectionColors["fuselage_main"] || "#FFFFFF";
        svgHtml += `<rect x="0" y="0" width="${vw}" height="${vh}" fill="${fuseColor}" opacity="0.12" rx="4" />`;

        // 2. Clipped Design Group (User Shapes & Section Colors)
        const clipAttr = `clip-path="url(#${clipId})"`;
        svgHtml += `<g id="clippedDesignGroup_${viewType}" ${clipAttr}>`;

        // Render User-Drawn Movable & Rotatable Shapes (Lines, Boxes, Circles, Swooshes, Pen, Spline)
        drawnShapes.filter(s => s.viewType === viewType).forEach(shape => {
            const isSel = shape.id === selectedShapeId;
            const stroke = shape.stroke || "#000000";
            const strokeW = shape.strokeWidth !== undefined ? shape.strokeWidth : 1;
            const strokeAttr = strokeW === 0 
                ? `stroke="none"` 
                : `stroke="${stroke}" stroke-width="${strokeW}" vector-effect="non-scaling-stroke"`;
            const fill = shape.fill || "#D61A1F";
            const opacity = shape.fillOpacity !== undefined ? shape.fillOpacity : 0.85;
            const cr = shape.cornerRadius !== undefined ? shape.cornerRadius : 4;
            const rot = shape.rotation || 0;
            const center = getShapeCenter(shape);
            const rotAttr = rot !== 0 ? `transform="rotate(${rot}, ${center.cx.toFixed(2)}, ${center.cy.toFixed(2)})"` : '';
            const selClass = `drawn-shape-element ${isSel ? 'selected' : ''}`;
            const cursorStyle = activeDrawTool === 'select' ? 'cursor: move;' : 'cursor: pointer;';

            if (shape.type === 'line') {
                svgHtml += `<line data-id="${shape.id}" class="${selClass}" style="${cursorStyle}" ${rotAttr} x1="${shape.x1}" y1="${shape.y1}" x2="${shape.x2}" y2="${shape.x2}" ${strokeAttr} stroke-linecap="round" />`;
            } else if (shape.type === 'rect') {
                svgHtml += `<rect data-id="${shape.id}" class="${selClass}" style="${cursorStyle}" ${rotAttr} x="${shape.x}" y="${shape.y}" width="${shape.width}" height="${shape.height}" fill="${fill}" fill-opacity="${opacity}" ${strokeAttr} rx="${cr}" ry="${cr}" />`;
            } else if (shape.type === 'circle') {
                svgHtml += `<ellipse data-id="${shape.id}" class="${selClass}" style="${cursorStyle}" ${rotAttr} cx="${shape.cx}" cy="${shape.cy}" rx="${shape.rx}" ry="${shape.ry}" fill="${fill}" fill-opacity="${opacity}" ${strokeAttr} />`;
            } else if (shape.type === 'swoosh' || shape.type === 'pen' || shape.type === 'spline') {
                svgHtml += `<path data-id="${shape.id}" class="${selClass}" style="${cursorStyle}" ${rotAttr} d="${shape.pathD}" fill="${fill}" fill-opacity="${opacity}" ${strokeAttr} stroke-linejoin="round" stroke-linecap="round" />`;
            }
        });

        // Live Active Multi-Point Pen or Spline Preview
        if (multiPoints.length > 0 && currentPenViewType === viewType) {
            const previewPathD = activeDrawTool === 'spline' 
                ? pointsToSplineD(multiPoints, false) 
                : pointsToPolylineD(multiPoints);

            const strokeAttr = currentStrokeWidth === 0 
                ? `stroke="none"` 
                : `stroke="${currentStrokeColor}" stroke-width="${currentStrokeWidth}" vector-effect="non-scaling-stroke"`;

            svgHtml += `<path d="${previewPathD}" fill="${currentFillColor}" fill-opacity="${currentFillOpacity * 0.5}" ${strokeAttr} stroke-dasharray="2,2" stroke-linecap="round" stroke-linejoin="round" />`;

            // Proportional, small node handles (3-4px screen radius)
            const nodeRadius = (vh * 0.008).toFixed(2);
            const nodeStroke = (vh * 0.002).toFixed(2);
            multiPoints.forEach((pt, idx) => {
                svgHtml += `<circle cx="${pt.x.toFixed(2)}" cy="${pt.y.toFixed(2)}" r="${nodeRadius}" fill="${idx === 0 ? '#ff007f' : '#00f2fe'}" stroke="#000000" stroke-width="${nodeStroke}" />`;
            });
        }

        // Temp Shape Preview while dragging mouse for drag-to-draw tools
        if (tempShape && tempShape.viewType === viewType) {
            const stroke = tempShape.stroke || "#000000";
            const strokeW = tempShape.strokeWidth !== undefined ? tempShape.strokeWidth : 1;
            const strokeAttr = strokeW === 0 
                ? `stroke="none"` 
                : `stroke="${stroke}" stroke-width="${strokeW}" vector-effect="non-scaling-stroke"`;
            const fill = tempShape.fill || "#D61A1F";
            const opacity = tempShape.fillOpacity !== undefined ? tempShape.fillOpacity : 0.85;
            const cr = tempShape.cornerRadius !== undefined ? tempShape.cornerRadius : 4;

            if (tempShape.type === 'line') {
                svgHtml += `<line x1="${tempShape.x1}" y1="${tempShape.y1}" x2="${tempShape.x2}" y2="${tempShape.y2}" ${strokeAttr} stroke-dasharray="2,2" />`;
            } else if (tempShape.type === 'rect') {
                svgHtml += `<rect x="${tempShape.x}" y="${tempShape.y}" width="${tempShape.width}" height="${tempShape.height}" fill="${fill}" fill-opacity="${opacity}" ${strokeAttr} rx="${cr}" ry="${cr}" stroke-dasharray="2,2" />`;
            } else if (tempShape.type === 'circle') {
                svgHtml += `<ellipse cx="${tempShape.cx}" cy="${tempShape.cy}" rx="${tempShape.rx}" ry="${tempShape.ry}" fill="${fill}" fill-opacity="${opacity}" ${strokeAttr} stroke-dasharray="2,2" />`;
            } else if (tempShape.type === 'swoosh') {
                svgHtml += `<path d="${tempShape.pathD}" fill="${fill}" fill-opacity="${opacity}" ${strokeAttr} stroke-dasharray="2,2" />`;
            }
        }

        svgHtml += `</g>`; // End Clipped Design Group

        // 3. High-Contrast Vector Lines - Direct Instant Image Embed (Crisp Black 1px Vector Lines on Top)
        svgHtml += `<image href="${vDef.file}?v=1.3" x="0" y="0" width="${vw}" height="${vh}" pointer-events="none" />`;

        // 4. Cross-View Projection Guidelines
        if (showGuides && (viewType === 'side' || viewType === 'top')) {
            svgHtml += `
                <line x1="${vw*0.25}" y1="0" x2="${vw*0.25}" y2="${vh}" stroke="#ff007f" stroke-width="1" vector-effect="non-scaling-stroke" stroke-dasharray="3,3" opacity="0.5" pointer-events="none" />
                <line x1="${vw*0.5}" y1="0" x2="${vw*0.5}" y2="${vh}" stroke="#ff007f" stroke-width="1" vector-effect="non-scaling-stroke" stroke-dasharray="3,3" opacity="0.5" pointer-events="none" />
                <line x1="${vw*0.85}" y1="0" x2="${vw*0.85}" y2="${vh}" stroke="#ff007f" stroke-width="1" vector-effect="non-scaling-stroke" stroke-dasharray="3,3" opacity="0.5" pointer-events="none" />
            `;
        }

        // 5. Registration N-Number (Excluding Combined 3-View Blueprint)
        const shouldShowNNum = (viewType !== 'combined') && (nNumberViewTarget === 'both' || nNumberViewTarget === viewType);
        if (nNumber && shouldShowNNum) {
            const pos = nNumberPos[viewType] || (viewType === 'side' ? { x: vw*0.55, y: vh*0.52 } : { x: vw*0.45, y: vh*0.35 });
            const fontSize = vh * nNumberSize;
            const rotTransform = nNumberRotation !== 0 ? `transform="rotate(${nNumberRotation}, ${pos.x.toFixed(2)}, ${pos.y.toFixed(2)})"` : '';

            svgHtml += `
                <text id="nNumberText_${viewType}"
                      data-type="nnumber"
                      data-view="${viewType}"
                      x="${pos.x.toFixed(2)}" y="${pos.y.toFixed(2)}"
                      font-family="${nNumberFont}, sans-serif"
                      font-size="${fontSize.toFixed(2)}"
                      font-weight="bold"
                      fill="${nNumberFill}"
                      stroke="${nNumberStroke}"
                      stroke-width="${(fontSize * 0.06).toFixed(2)}"
                      letter-spacing="0.5"
                      ${rotTransform}
                      style="cursor: move; user-select: none;">
                      ${nNumber}
                </text>
            `;
        }

        svgHtml += `</svg>`;
        container.innerHTML = svgHtml;

        // Bind interactive SVG events for drawing and dragging shapes
        bindSvgDrawingEvents(container.querySelector("svg"), viewType);
    }

    // --- Interactive Movable Vector Shapes Drag & Drop Handler ---
    function translatePathD(d_str, dx, dy) {
        return d_str.replace(/[-+]?\d*\.?\d+,[-+]?\d*\.?\d+/g, match => {
            const parts = match.split(',');
            return `${(floatVal(parts[0]) + dx).toFixed(2)},${(floatVal(parts[1]) + dy).toFixed(2)}`;
        });
    }

    function floatVal(val) {
        return parseFloat(val) || 0;
    }

    function bindSvgDrawingEvents(svgEl, viewType) {
        if (!svgEl) return;

        function getSvgCoords(e) {
            if (svgEl.createSVGPoint && svgEl.getScreenCTM) {
                const pt = svgEl.createSVGPoint();
                pt.x = e.clientX;
                pt.y = e.clientY;
                const ctm = svgEl.getScreenCTM();
                if (ctm) {
                    const svgP = pt.matrixTransform(ctm.inverse());
                    return { x: svgP.x, y: svgP.y };
                }
            }
            const rect = svgEl.getBoundingClientRect();
            const vb = svgEl.getAttribute("viewBox").split(" ").map(Number);
            const scaleX = vb[2] / rect.width;
            const scaleY = vb[3] / rect.height;
            return {
                x: vb[0] + (e.clientX - rect.left) * scaleX,
                y: vb[1] + (e.clientY - rect.top) * scaleY
            };
        }

        svgEl.addEventListener("click", (e) => {
            // Handle Multi-Point Pen and Spline Curve clicks
            if (activeDrawTool === "pen" || activeDrawTool === "spline") {
                const coords = getSvgCoords(e);

                if (currentPenViewType && currentPenViewType !== viewType) {
                    multiPoints = [];
                }
                currentPenViewType = viewType;

                if (multiPoints.length >= 3) {
                    const start = multiPoints[0];
                    const dist = Math.hypot(coords.x - start.x, coords.y - start.y);
                    if (dist < 5) {
                        finalizeMultiPointShape();
                        return;
                    }
                }

                multiPoints.push(coords);
                renderAllViews();
                return;
            }
        });

        svgEl.addEventListener("dblclick", (e) => {
            if ((activeDrawTool === "pen" || activeDrawTool === "spline") && multiPoints.length > 1) {
                e.preventDefault();
                finalizeMultiPointShape();
            }
        });

        svgEl.addEventListener("mousedown", (e) => {
            if (activeDrawTool === "pen" || activeDrawTool === "spline") return;

            const isNNum = e.target.getAttribute("data-type") === "nnumber";
            if (isNNum) {
                isDraggingNNumber = true;
                dragStartMouseCoords = getSvgCoords(e);
                const vb = svgEl.getAttribute("viewBox").split(" ").map(Number);
                const defaultX = viewType === 'side' ? vb[2]*0.55 : vb[2]*0.45;
                const defaultY = viewType === 'side' ? vb[3]*0.52 : vb[3]*0.35;
                const curPos = nNumberPos[viewType] || { x: defaultX, y: defaultY };
                dragInitialNNumberPos = { ...curPos };
                return;
            }

            const targetShapeId = e.target.getAttribute("data-id");

            if (activeDrawTool === "select") {
                if (targetShapeId) {
                    selectedShapeId = targetShapeId;
                    const shape = drawnShapes.find(s => s.id === targetShapeId);
                    if (shape) {
                        syncSelectedShapePanel(shape);
                        isDraggingShape = true;
                        dragStartMouseCoords = getSvgCoords(e);
                        dragInitialShapeState = JSON.parse(JSON.stringify(shape));
                    }
                    renderAllViews();
                } else {
                    selectedShapeId = null;
                    isDraggingShape = false;
                    renderAllViews();
                }
                return;
            }

            // Creating a new shape (line, rect, circle, swoosh)
            isDrawing = true;
            drawStartCoords = getSvgCoords(e);
            selectedShapeId = null;
        });

        svgEl.addEventListener("mousemove", (e) => {
            const curr = getSvgCoords(e);

            // Live preview line for active Pen or Spline drawing
            if ((activeDrawTool === "pen" || activeDrawTool === "spline") && multiPoints.length > 0 && currentPenViewType === viewType) {
                renderSvgView(viewType, `svgContainer${viewType.charAt(0).toUpperCase() + viewType.slice(1)}`);
                return;
            }

            // 1. Moving N-Number Registration Text
            if (isDraggingNNumber && dragStartMouseCoords && dragInitialNNumberPos) {
                const dx = curr.x - dragStartMouseCoords.x;
                const dy = curr.y - dragStartMouseCoords.y;
                nNumberPos[viewType] = {
                    x: dragInitialNNumberPos.x + dx,
                    y: dragInitialNNumberPos.y + dy
                };
                renderAllViews();
                return;
            }

            // 2. Moving an existing selected shape (Drag & Drop)
            if (isDraggingShape && selectedShapeId && dragStartMouseCoords && dragInitialShapeState) {
                const dx = curr.x - dragStartMouseCoords.x;
                const dy = curr.y - dragStartMouseCoords.y;
                const shape = drawnShapes.find(s => s.id === selectedShapeId);

                if (shape) {
                    if (shape.type === 'line') {
                        shape.x1 = dragInitialShapeState.x1 + dx;
                        shape.y1 = dragInitialShapeState.y1 + dy;
                        shape.x2 = dragInitialShapeState.x2 + dx;
                        shape.y2 = dragInitialShapeState.y2 + dy;
                    } else if (shape.type === 'rect') {
                        shape.x = dragInitialShapeState.x + dx;
                        shape.y = dragInitialShapeState.y + dy;
                    } else if (shape.type === 'circle') {
                        shape.cx = dragInitialShapeState.cx + dx;
                        shape.cy = dragInitialShapeState.cy + dy;
                    } else if (shape.type === 'swoosh' || shape.type === 'pen' || shape.type === 'spline') {
                        shape.pathD = translatePathD(dragInitialShapeState.pathD, dx, dy);
                    }
                    renderAllViews();
                }
                return;
            }

            // 3. Drag-to-draw preview for new shapes
            if (!isDrawing || !drawStartCoords) return;

            if (activeDrawTool === "line") {
                tempShape = {
                    type: "line",
                    viewType: viewType,
                    x1: drawStartCoords.x,
                    y1: drawStartCoords.y,
                    x2: curr.x,
                    y2: curr.y,
                    stroke: currentStrokeColor,
                    strokeWidth: currentStrokeWidth,
                    cornerRadius: currentCornerRadius,
                    rotation: currentRotation
                };
            } else if (activeDrawTool === "rect") {
                const x = Math.min(drawStartCoords.x, curr.x);
                const y = Math.min(drawStartCoords.y, curr.y);
                const w = Math.abs(curr.x - drawStartCoords.x);
                const h = Math.abs(curr.y - drawStartCoords.y);
                tempShape = {
                    type: "rect",
                    viewType: viewType,
                    x: x,
                    y: y,
                    width: w,
                    height: h,
                    fill: currentFillColor,
                    fillOpacity: currentFillOpacity,
                    stroke: currentStrokeColor,
                    strokeWidth: currentStrokeWidth,
                    cornerRadius: currentCornerRadius,
                    rotation: currentRotation
                };
            } else if (activeDrawTool === "circle") {
                const rx = Math.abs(curr.x - drawStartCoords.x) / 2;
                const ry = Math.abs(curr.y - drawStartCoords.y) / 2;
                const cx = Math.min(drawStartCoords.x, curr.x) + rx;
                const cy = Math.min(drawStartCoords.y, curr.y) + ry;
                tempShape = {
                    type: "circle",
                    viewType: viewType,
                    cx: cx,
                    cy: cy,
                    rx: rx,
                    ry: ry,
                    fill: currentFillColor,
                    fillOpacity: currentFillOpacity,
                    stroke: currentStrokeColor,
                    strokeWidth: currentStrokeWidth,
                    cornerRadius: currentCornerRadius,
                    rotation: currentRotation
                };
            } else if (activeDrawTool === "swoosh") {
                const x1 = drawStartCoords.x;
                const y1 = drawStartCoords.y;
                const x2 = curr.x;
                const y2 = curr.y;
                const cx = (x1 + x2) / 2;
                const cy = Math.min(y1, y2) - Math.abs(x2 - x1) * 0.3;
                const pathD = `M ${x1.toFixed(2)},${y1.toFixed(2)} Q ${cx.toFixed(2)},${cy.toFixed(2)} ${x2.toFixed(2)},${y2.toFixed(2)} L ${x2.toFixed(2)},${(y2+20).toFixed(2)} Q ${cx.toFixed(2)},${(cy+20).toFixed(2)} ${x1.toFixed(2)},${(y1+10).toFixed(2)} Z`;
                tempShape = {
                    type: "swoosh",
                    viewType: viewType,
                    pathD: pathD,
                    fill: currentFillColor,
                    fillOpacity: currentFillOpacity,
                    stroke: currentStrokeColor,
                    strokeWidth: currentStrokeWidth,
                    cornerRadius: currentCornerRadius,
                    rotation: currentRotation
                };
            }
            renderSvgView(viewType, `svgContainer${viewType.charAt(0).toUpperCase() + viewType.slice(1)}`);
        });

        svgEl.addEventListener("mouseup", () => {
            if (isDraggingNNumber) {
                isDraggingNNumber = false;
                dragStartMouseCoords = null;
                dragInitialNNumberPos = null;
                saveStateToHistory();
                renderAllViews();
                return;
            }

            if (isDraggingShape) {
                isDraggingShape = false;
                dragStartMouseCoords = null;
                dragInitialShapeState = null;
                saveStateToHistory();
                renderAllViews();
                return;
            }

            if (isDrawing && tempShape) {
                tempShape.id = "shape_" + Date.now() + "_" + Math.floor(Math.random()*1000);
                drawnShapes.push({ ...tempShape });
                selectedShapeId = tempShape.id;
                tempShape = null;
                isDrawing = false;
                drawStartCoords = null;
                saveStateToHistory();
                renderAllViews();
            }
            isDrawing = false;
            tempShape = null;
        });
    }

    // --- Section Layer List ---
    function renderSectionLayerList() {
        const list = document.getElementById("sectionLayerList");
        if (!list) return;

        list.innerHTML = "";
        window.VANS_DEFAULT_SECTIONS.forEach(sec => {
            const color = sectionColors[sec.id] || sec.defaultColor;
            const row = document.createElement("div");
            row.style.cssText = "display: flex; align-items: center; justify-content: space-between; background: rgba(0,0,0,0.2); padding: 8px 12px; border-radius: 6px; border: 1px solid var(--border-glass);";
            
            row.innerHTML = `
                <span style="font-size: 0.85rem; color: var(--text-primary);">${sec.name}</span>
                <div style="display: flex; align-items: center; gap: 8px;">
                    <div style="width: 24px; height: 24px; border-radius: 4px; background: ${color}; border: 1px solid rgba(255,255,255,0.3);"></div>
                    <input type="color" value="${color.startsWith('#') ? color : '#FFFFFF'}" style="width: 28px; height: 28px; border: none; background: transparent; cursor: pointer;" data-sec="${sec.id}">
                </div>
            `;

            row.querySelector("input[type='color']").addEventListener("change", (e) => {
                sectionColors[sec.id] = e.target.value;
                saveStateToHistory();
                renderAllViews();
                updatePaletteSummary();
            });

            list.appendChild(row);
        });
    }

    // --- Palette Summary ---
    function updatePaletteSummary() {
        const summary = document.getElementById("activePaletteSummary");
        if (!summary) return;
        summary.innerHTML = "";

        const usedHexes = [...new Set(Object.values(sectionColors))];
        usedHexes.forEach(hex => {
            const matchSW = SW_AEROSPACE_COLORS.find(sw => sw.hex.toLowerCase() === hex.toLowerCase());
            const name = matchSW ? matchSW.name : "Custom Color";
            const code = matchSW ? matchSW.code : hex.toUpperCase();

            const item = document.createElement("div");
            item.style.cssText = "display: flex; align-items: center; gap: 10px; font-size: 0.8rem; color: var(--text-muted);";
            item.innerHTML = `
                <div style="width: 18px; height: 18px; border-radius: 4px; background: ${hex}; border: 1px solid rgba(255,255,255,0.3);"></div>
                <span><strong>${name}</strong> (${code})</span>
            `;
            summary.appendChild(item);
        });
    }

    // --- Pattern Preset Tool ---
    function applyPatternPreset(patternType) {
        if (patternType === "swoosh") {
            sectionColors["spinner"] = "#D61A1F";
            sectionColors["cowl"] = "#0047AB";
            sectionColors["fuselage_main"] = "#FFFFFF";
            sectionColors["wheel_pants"] = "#0047AB";
            sectionColors["rudder"] = "#D61A1F";
        } else if (patternType === "speed") {
            sectionColors["spinner"] = "#111111";
            sectionColors["cowl"] = "#FFD700";
            sectionColors["fuselage_main"] = "#36454F";
            sectionColors["wheel_pants"] = "#FFD700";
            sectionColors["rudder"] = "#111111";
        } else if (patternType === "chevron") {
            sectionColors["spinner"] = "#008751";
            sectionColors["cowl"] = "#FFFFFF";
            sectionColors["fuselage_main"] = "#008751";
            sectionColors["wheel_pants"] = "#FFFFFF";
        } else if (patternType === "checker") {
            sectionColors["spinner"] = "#111111";
            sectionColors["cowl"] = "#FFFFFF";
            sectionColors["rudder"] = "#111111";
            sectionColors["wheel_pants"] = "#111111";
        }
        saveStateToHistory();
        renderAllViews();
        updatePaletteSummary();
        renderSectionLayerList();
    }

    // --- Bind DOM Event Handlers ---
    function bindEvents() {
        document.getElementById("btnUndo")?.addEventListener("click", undo);
        document.getElementById("btnRedo")?.addEventListener("click", redo);
        document.getElementById("btnResetScheme")?.addEventListener("click", () => {
            initColorSectionDefaults();
            drawnShapes = [];
            selectedShapeId = null;
            multiPoints = [];
            currentPenViewType = null;
            nNumberPos = { side: null, top: null, combined: null };
            renderAllViews();
        });

        document.getElementById("swLineSelector")?.addEventListener("change", initSwatches);
        document.getElementById("swFinishSelector")?.addEventListener("change", initSwatches);

        document.getElementById("customColorPicker")?.addEventListener("input", (e) => {
            const hex = e.target.value.toUpperCase();
            document.getElementById("customColorHex").value = hex;
            activeColor = { code: "CUSTOM", name: "Custom Hex", hex: hex, line: "custom", finish: "gloss" };
            currentFillColor = hex;
            document.getElementById("activeSwatchPreview").style.backgroundColor = hex;
            document.getElementById("activeSwatchName").innerText = "Custom Color";
            document.getElementById("activeSwatchCode").innerText = `Hex: ${hex}`;
        });

        document.querySelectorAll(".pattern-preset-btn").forEach(btn => {
            btn.addEventListener("click", () => applyPatternPreset(btn.dataset.pattern));
        });

        // N-Number Customization Event Controls
        document.getElementById("inputNNumber")?.addEventListener("input", (e) => {
            nNumber = e.target.value.toUpperCase();
            renderAllViews();
        });

        document.getElementById("nNumberFont")?.addEventListener("change", (e) => {
            nNumberFont = e.target.value;
            renderAllViews();
        });

        document.getElementById("nNumberViewTarget")?.addEventListener("change", (e) => {
            nNumberViewTarget = e.target.value;
            renderAllViews();
        });

        document.getElementById("nNumberSize")?.addEventListener("input", (e) => {
            nNumberSize = parseFloat(e.target.value);
            renderAllViews();
        });

        document.getElementById("nNumberRotation")?.addEventListener("input", (e) => {
            nNumberRotation = parseFloat(e.target.value);
            document.getElementById("nNumberRotVal").innerText = `${nNumberRotation}°`;
            renderAllViews();
        });

        document.getElementById("nNumberColor")?.addEventListener("input", (e) => {
            nNumberFill = e.target.value;
            document.getElementById("nNumFillPreview").style.backgroundColor = nNumberFill;
            renderAllViews();
        });

        document.getElementById("nNumberStrokeColor")?.addEventListener("input", (e) => {
            nNumberStroke = e.target.value;
            document.getElementById("nNumStrokePreview").style.backgroundColor = nNumberStroke;
            renderAllViews();
        });

        document.getElementById("chkShowGuides")?.addEventListener("change", (e) => {
            showGuides = e.target.checked;
            renderAllViews();
        });

        document.getElementById("chkClipToModel")?.addEventListener("change", (e) => {
            clipToModel = e.target.checked;
            renderAllViews();
        });

        window.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && (activeDrawTool === "pen" || activeDrawTool === "spline") && multiPoints.length > 1) {
                finalizeMultiPointShape();
                return;
            }

            if ((e.key === "Delete" || e.key === "Backspace") && selectedShapeId) {
                if (document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "SELECT") {
                    drawnShapes = drawnShapes.filter(s => s.id !== selectedShapeId);
                    selectedShapeId = null;
                    saveStateToHistory();
                    renderAllViews();
                }
            }
        });

        const modal = document.getElementById("exportModal");
        document.getElementById("btnOpenExport")?.addEventListener("click", () => modal?.classList.add("active"));
        document.getElementById("btnCloseModal")?.addEventListener("click", () => modal?.classList.remove("active"));

        document.getElementById("btnQuickExportImg")?.addEventListener("click", exportJpegSnapshot);
        document.getElementById("btnGenerateJpeg")?.addEventListener("click", exportJpegSnapshot);
        document.getElementById("btnGeneratePdf")?.addEventListener("click", exportPdfTechSpec);
    }

    // --- Export Functions ---
    function exportJpegSnapshot() {
        const workspace = document.getElementById("mainCanvasContainer");
        if (!workspace) return;

        html2canvas(workspace, { backgroundColor: "#ffffff", scale: 2 }).then(canvas => {
            const link = document.createElement("a");
            link.download = `${currentModelId.toUpperCase()}_Paint_Design_${nNumber}.jpg`;
            link.href = canvas.toDataURL("image/jpeg", 0.95);
            link.click();
        });
    }

    function exportPdfTechSpec() {
        const workspace = document.getElementById("mainCanvasContainer");
        if (!workspace) return;

        const { jsPDF } = window.jspdf;
        const pdf = new jsPDF("landscape", "mm", "a4");

        html2canvas(workspace, { backgroundColor: "#ffffff", scale: 2 }).then(canvas => {
            const imgData = canvas.toDataURL("image/png");
            
            pdf.setFontSize(16);
            pdf.text(`VAN'S AIRCRAFT PAINT TECH SPECIFICATION SHEET`, 14, 15);
            
            pdf.setFontSize(10);
            const model = window.VANS_AIRCRAFT_MODELS[currentModelId];
            pdf.text(`Model: ${model ? model.name : currentModelId} | N-Number: ${nNumber} | Date: ${new Date().toLocaleDateString()}`, 14, 22);

            pdf.addImage(imgData, "PNG", 14, 28, 268, 140);

            pdf.setFontSize(12);
            pdf.text(`Sherwin-Williams Aerospace Color Callouts:`, 14, 178);

            let yPos = 186;
            const usedHexes = [...new Set(Object.values(sectionColors))];
            usedHexes.forEach(hex => {
                const matchSW = SW_AEROSPACE_COLORS.find(sw => sw.hex.toLowerCase() === hex.toLowerCase());
                const text = matchSW 
                    ? `• ${matchSW.name} (Code: ${matchSW.code}, Line: ${matchSW.line.toUpperCase()}, Finish: ${matchSW.finish}) - Hex ${hex}`
                    : `• Custom Accent Color - Hex ${hex}`;
                pdf.setFontSize(9);
                pdf.text(text, 18, yPos);
                yPos += 6;
            });

            const projName = document.getElementById("exportProjectName").value || "Custom RV Paint Scheme";
            pdf.save(`${projName.replace(/\s+/g, '_')}_TechSpec.pdf`);
            document.getElementById("exportModal")?.classList.remove("active");
        });
    }

});
