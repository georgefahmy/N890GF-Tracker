document.addEventListener('DOMContentLoaded', function() {
    let viewer;
    let aircraftEntity;

    // Smooth Animation State
    let animStartPos, animTargetPos;
    let animStartOri, animTargetOri;
    let animStartTime = 0;
    let animDuration = 1000; // 1 second glide for 1Hz data

    async function init3DViewer() {
        const container = document.getElementById('attitude3DContainer');
        if (!container) return;
        if (viewer) return;

        // Remove placeholder text if present
        const placeholder = container.querySelector('.cesium-placeholder');
        if (placeholder) placeholder.remove();

        // Create or find dedicated canvas wrapper for Cesium viewer
        let cesiumDiv = document.getElementById('cesiumCanvasDiv');
        if (!cesiumDiv) {
            cesiumDiv = document.createElement('div');
            cesiumDiv.id = 'cesiumCanvasDiv';
            cesiumDiv.style.width = '100%';
            cesiumDiv.style.height = '100%';
            cesiumDiv.style.position = 'absolute';
            cesiumDiv.style.top = '0';
            cesiumDiv.style.left = '0';
            cesiumDiv.style.zIndex = '1';
            container.insertBefore(cesiumDiv, container.firstChild);
        }

        Cesium.Ion.defaultAccessToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiI1OWFhZWY3Yi04N2EwLTRjMzEtOTU1Ny04ZTU0NjIwZGI2NGUiLCJpZCI6NDIxMzY1LCJpYXQiOjE3NzY3ODUyNTh9.JD1aQq2VNXJDdjP7D4gz3YJc2XkRnc6bSbDBA6YmNrE';

        viewer = new Cesium.Viewer(cesiumDiv, {
            terrain: Cesium.Terrain.fromWorldTerrain(),
            baseLayerPicker: false, timeline: false, animation: false,
            infoBox: false, selectionIndicator: false,
            fullscreenButton: true,
            fullscreenElement: container
        });

        aircraftEntity = viewer.entities.add({
            name: 'Aircraft',
            model: { uri: '/static/models/N890GF.glb', minimumPixelSize: 1 },
            // THE CAMERA FIX: Offset the camera 40m back and 10m up
            viewFrom: new Cesium.Cartesian3(-40.0, 0.0, 10.0),
            // The position is now a MATH FUNCTION, not a static point
            position: new Cesium.CallbackProperty((time, result) => {
                if (!animStartPos || !animTargetPos) return animTargetPos;
                const now = performance.now();
                const t = Math.min((now - animStartTime) / animDuration, 1.0);
                return Cesium.Cartesian3.lerp(animStartPos, animTargetPos, t, result || new Cesium.Cartesian3());
            }, false),
            orientation: new Cesium.CallbackProperty((time, result) => {
                if (!animStartOri || !animTargetOri) return animTargetOri;
                const now = performance.now();
                const t = Math.min((now - animStartTime) / animDuration, 1.0);
                return Cesium.Quaternion.slerp(animStartOri, animTargetOri, t, result || new Cesium.Quaternion());
            }, false)
        });

        viewer.trackedEntity = aircraftEntity;
    }

    // 3d_model.js (Simplified)
    window.updateAircraft3D = function(pitchDeg, rollDeg, headingDeg, lat, lon, altFt) {
        if (!viewer || !aircraftEntity) return;

        let groundHeight = 0;
        const cartographic = Cesium.Cartographic.fromDegrees(lon, lat);

        // Synchronously read the terrain height currently loaded in the viewer's memory
        if (viewer.scene && viewer.scene.globe) {
            const h = viewer.scene.globe.getHeight(cartographic);
            groundHeight = h !== undefined ? h : 0;
        }

        // 2. Clamp Logic: Max of ground or (altMeters)
        const altMeters = (altFt || 0) * 0.3048;
        const finalHeight = Math.max(groundHeight, altMeters-35);

        const position = Cesium.Cartesian3.fromDegrees(lon, lat, finalHeight);
        // const position = Cesium.Cartesian3.fromDegrees(lon, lat, altMeters-30);

        const hpr = new Cesium.HeadingPitchRoll(
            Cesium.Math.toRadians(headingDeg || 0),
            Cesium.Math.toRadians(-rollDeg || 0),
            Cesium.Math.toRadians(pitchDeg || 0)
        );
        const orientation = Cesium.Transforms.headingPitchRollQuaternion(position, hpr);

        // No interpolation here—just snap to the high-frequency points
        aircraftEntity.position = position;
        aircraftEntity.orientation = orientation;

        // Ensure camera stays locked
        if (!viewer.trackedEntity) {
            viewer.trackedEntity = aircraftEntity;
        }
    };

    window.toggle3DFullscreen = function() {
        const container = document.getElementById('attitude3DContainer');
        if (!container) return;
        const isFullscreen = document.fullscreenElement || document.webkitFullscreenElement || document.mozFullScreenElement || document.msFullscreenElement;
        if (isFullscreen) {
            if (document.exitFullscreen) document.exitFullscreen();
            else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
            else if (document.mozCancelFullScreen) document.mozCancelFullScreen();
            else if (document.msExitFullscreen) document.msExitFullscreen();
        } else {
            if (container.requestFullscreen) container.requestFullscreen();
            else if (container.webkitRequestFullscreen) container.webkitRequestFullscreen();
            else if (container.mozRequestFullScreen) container.mozRequestFullScreen();
            else if (container.msRequestFullscreen) container.msRequestFullscreen();
        }
    };

    window.init3DViewer = init3DViewer;
});