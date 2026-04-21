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
        container.innerHTML = '';

        Cesium.Ion.defaultAccessToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiI1OWFhZWY3Yi04N2EwLTRjMzEtOTU1Ny04ZTU0NjIwZGI2NGUiLCJpZCI6NDIxMzY1LCJpYXQiOjE3NzY3ODUyNTh9.JD1aQq2VNXJDdjP7D4gz3YJc2XkRnc6bSbDBA6YmNrE';

        viewer = new Cesium.Viewer(container, {
            terrain: Cesium.Terrain.fromWorldTerrain(),
            baseLayerPicker: false, timeline: false, animation: false,
            infoBox: false, selectionIndicator: false
        });

        aircraftEntity = viewer.entities.add({
            name: 'Aircraft',
            model: { uri: '/static/models/rv7.glb', minimumPixelSize: 128 },
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

        const altMeters = (altFt || 0) * 0.3048;
        const position = Cesium.Cartesian3.fromDegrees(lon, lat, altMeters-40);

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

    window.init3DViewer = init3DViewer;
});