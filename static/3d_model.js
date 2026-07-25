document.addEventListener('DOMContentLoaded', function() {
    let viewer;
    let aircraftEntity;
    let flightPathEntity;
    let currentCameraMode = 'chase'; // 'chase', 'cockpit', 'top', 'orbit'
    let trailVisible = true;

    async function init3DViewer() {
        const container = document.getElementById('attitude3DContainer');
        if (!container) return;
        container.innerHTML = '';

        Cesium.Ion.defaultAccessToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiI1OWFhZWY3Yi04N2EwLTRjMzEtOTU1Ny04ZTU0NjIwZGI2NGUiLCJpZCI6NDIxMzY1LCJpYXQiOjE3NzY3ODUyNTh9.JD1aQq2VNXJDdjP7D4gz3YJc2XkRnc6bSbDBA6YmNrE';

        viewer = new Cesium.Viewer(container, {
            terrain: Cesium.Terrain.fromWorldTerrain(),
            baseLayerPicker: false,
            timeline: false,
            animation: false,
            infoBox: false,
            selectionIndicator: false,
            fullscreenElement: container
        });

        // Add aircraft model
        aircraftEntity = viewer.entities.add({
            name: 'Aircraft',
            model: {
                uri: '/static/models/N890GF.glb',
                minimumPixelSize: 1
            }
        });

        // Attach preRender event listener to handle custom camera locks
        viewer.scene.preRender.addEventListener(function(scene, time) {
            updateCameraView(time);
        });

        // Initial camera setting
        applyCameraMode();
    }

    function updateCameraView(time) {
        if (!viewer || !aircraftEntity || currentCameraMode === 'orbit') {
            return;
        }

        const position = aircraftEntity.position ? aircraftEntity.position.getValue(time) : null;
        const orientation = aircraftEntity.orientation ? aircraftEntity.orientation.getValue(time) : null;
        if (!position || !orientation) return;

        // 1. Calculate local camera offset, look direction, and up vector
        let localOffset, localDir, localUp;

        if (currentCameraMode === 'chase') {
            // Position behind (-Y) and above (+Z) the aircraft
            localOffset = new Cesium.Cartesian3(0.0, -45.0, 12.0);
            // Look forward (+Y) and slightly down (-Z)
            localDir = Cesium.Cartesian3.normalize(new Cesium.Cartesian3(0.0, 45.0, -10.0), new Cesium.Cartesian3());
            localUp = new Cesium.Cartesian3(0.0, 0.0, 1.0);
        } else if (currentCameraMode === 'cockpit') {
            // Position near cockpit (+Y, +Z)
            localOffset = new Cesium.Cartesian3(0.0, 0.8, 0.7);
            // Look straight forward (+Y) and slightly down (-Z)
            localDir = Cesium.Cartesian3.normalize(new Cesium.Cartesian3(0.0, 10.0, -0.5), new Cesium.Cartesian3());
            localUp = new Cesium.Cartesian3(0.0, 0.0, 1.0);
        } else if (currentCameraMode === 'top') {
            // Position high above (+Z)
            localOffset = new Cesium.Cartesian3(0.0, 0.0, 80.0);
            // Look straight down (-Z)
            localDir = new Cesium.Cartesian3(0.0, 0.0, -1.0);
            // Top of the screen points forward (+Y)
            localUp = new Cesium.Cartesian3(0.0, 1.0, 0.0);
        }

        // 2. Transform these local vectors into the global/ECF frame using the aircraft's modelMatrix
        const rotationMatrix = Cesium.Matrix3.fromQuaternion(orientation);
        const modelMatrix = Cesium.Matrix4.fromRotationTranslation(rotationMatrix, position);

        const globalOffset = Cesium.Matrix4.multiplyByPoint(modelMatrix, localOffset, new Cesium.Cartesian3());
        const globalDir = Cesium.Matrix4.multiplyByPointAsVector(modelMatrix, localDir, new Cesium.Cartesian3());
        const globalUp = Cesium.Matrix4.multiplyByPointAsVector(modelMatrix, localUp, new Cesium.Cartesian3());

        // 3. Clear any active local camera transform to operate in global ECF frame safely
        viewer.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);

        // 4. Position and orient the camera
        viewer.camera.setView({
            destination: globalOffset,
            orientation: {
                direction: globalDir,
                up: globalUp
            }
        });
    }

    function applyCameraMode() {
        if (!viewer) return;

        // Reset transform to identity so we aren't locked to local frame permanently
        viewer.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);

        if (currentCameraMode === 'orbit') {
            viewer.trackedEntity = aircraftEntity;
            if (aircraftEntity) {
                aircraftEntity.viewFrom = new Cesium.Cartesian3(0.0, -45.0, 12.0);
            }
        } else {
            viewer.trackedEntity = undefined;
        }

        // Update active UI classes
        const modes = ['chase', 'cockpit', 'top', 'orbit'];
        modes.forEach(mode => {
            const btn = document.getElementById('btnCam' + mode.charAt(0).toUpperCase() + mode.slice(1));
            if (btn) {
                if (mode === currentCameraMode) {
                    btn.classList.add('active');
                } else {
                    btn.classList.remove('active');
                }
            }
        });
    }

    // Global APIs exposed on window
    window.set3DCameraMode = function(mode) {
        currentCameraMode = mode;
        applyCameraMode();
    };

    window.toggle3DTrail = function() {
        trailVisible = !trailVisible;
        if (flightPathEntity) {
            flightPathEntity.show = trailVisible;
        }
        const btn = document.getElementById('btnToggleTrail');
        if (btn) {
            if (trailVisible) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        }
    };

    window.initFlightPath3D = function(latitudes, longitudes, altitudes) {
        if (!viewer) return;

        // Clear existing path
        if (flightPathEntity) {
            viewer.entities.remove(flightPathEntity);
            flightPathEntity = null;
        }

        if (!latitudes || latitudes.length === 0) return;

        const positions = [];
        for (let i = 0; i < latitudes.length; i++) {
            const altMeters = (altitudes[i] || 0) * 0.3048;
            // Align the altitude offset of the trail with the model (-35m offset)
            const finalHeight = altMeters - 35;
            positions.push(Cesium.Cartesian3.fromDegrees(longitudes[i], latitudes[i], finalHeight));
        }

        flightPathEntity = viewer.entities.add({
            name: 'Flight Path Trail',
            polyline: {
                positions: positions,
                width: 4,
                material: new Cesium.PolylineGlowMaterialProperty({
                    glowPower: 0.25,
                    color: Cesium.Color.fromCssColorString('#0d6efd') // Primary color
                }),
                clampToGround: false
            },
            show: trailVisible
        });
    };

    window.updateAircraft3D = function(pitchDeg, rollDeg, headingDeg, lat, lon, altFt) {
        if (!viewer || !aircraftEntity) return;

        let groundHeight = 0;
        const cartographic = Cesium.Cartographic.fromDegrees(lon, lat);

        // Read the terrain height currently loaded in memory
        if (viewer.scene && viewer.scene.globe) {
            const h = viewer.scene.globe.getHeight(cartographic);
            groundHeight = h !== undefined ? h : 0;
        }

        // Clamp logic
        const altMeters = (altFt || 0) * 0.3048;
        const finalHeight = Math.max(groundHeight, altMeters - 35);

        const position = Cesium.Cartesian3.fromDegrees(lon, lat, finalHeight);

        const hpr = new Cesium.HeadingPitchRoll(
            Cesium.Math.toRadians(headingDeg || 0),
            Cesium.Math.toRadians(-rollDeg || 0),
            Cesium.Math.toRadians(pitchDeg || 0)
        );
        const orientation = Cesium.Transforms.headingPitchRollQuaternion(position, hpr);

        aircraftEntity.position = position;
        aircraftEntity.orientation = orientation;

        // Make sure orientation updates are reflected in camera lock
        updateCameraView(Cesium.JulianDate.now());
    };

    window.init3DViewer = init3DViewer;
});