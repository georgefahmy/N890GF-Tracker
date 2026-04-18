import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js';
import { GLTFLoader } from 'https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/controls/OrbitControls.js';
import * as Cesium from 'https://cdn.jsdelivr.net/npm/cesium@1.118/Build/Cesium/Cesium.js';
// All logic is now wrapped in DOMContentLoaded for safe initialization.
document.addEventListener('DOMContentLoaded', function() {
    let scene, camera, renderer;
    let animationFrameId = null;
    let origin = null;
    let cameraInitialized = false;

    // Inspect / orbit controls
    let controls = null;
    let isInspectMode = false;
    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();

    let cesiumViewer = null;
    let cesiumEntity = null;

    function latLonToXYZ(lat, lon, alt) {
        const scale = 5000;
        if (!origin) {
            origin = { lat: lat, lon: lon };
        }
        const dLat = lat - origin.lat;
        const dLon = lon - origin.lon;
        return {
            x: -dLon * scale,
            y: (alt || 0) * 0.05,
            z: dLat * scale
        };
    }

    async function initCesiumWorld(container) {
        const cesiumContainer = document.createElement('div');
        cesiumContainer.style.position = 'absolute';
        cesiumContainer.style.top = '0';
        cesiumContainer.style.left = '0';
        cesiumContainer.style.width = '100%';
        cesiumContainer.style.height = '100%';
        cesiumContainer.style.zIndex = '0';

        container.appendChild(cesiumContainer);

        cesiumViewer = new Cesium.Viewer(cesiumContainer, {
            terrainProvider: await Cesium.createWorldTerrainAsync(),
            animation: false,
            timeline: false,
            baseLayerPicker: true,
            geocoder: false,
            sceneMode: Cesium.SceneMode.SCENE3D
        });

        cesiumEntity = cesiumViewer.entities.add({
            position: Cesium.Cartesian3.fromDegrees(0, 0, 0),
            point: { pixelSize: 10, color: Cesium.Color.RED }
        });
    }

    function init3DViewer() {
        const container = document.getElementById('attitude3DContainer');
        initCesiumWorld(container).catch(console.error);
        if (!container) return;
        container.innerHTML = '';
        container.style.display = 'block';
        // Scene
        scene = new THREE.Scene();
        // Sky dome
        const skyGeo = new THREE.SphereGeometry(50000, 32, 32);
        const skyMat = new THREE.MeshBasicMaterial({ color: 0x87ceeb, side: THREE.BackSide });
        const sky = new THREE.Mesh(skyGeo, skyMat);
        scene.add(sky);
        // Ground
        const groundGeo = new THREE.PlaneGeometry(200000, 200000);
        const textureLoader = new THREE.TextureLoader();
        const groundTexture = textureLoader.load('/static/textures/satellite.jpg');
        groundTexture.wrapS = THREE.RepeatWrapping;
        groundTexture.wrapT = THREE.RepeatWrapping;
        groundTexture.repeat.set(200, 200);
        const groundMat = new THREE.MeshBasicMaterial({ map: groundTexture, side: THREE.DoubleSide });
        const ground = new THREE.Mesh(groundGeo, groundMat);
        ground.position.y = -5;
        ground.rotation.x = -Math.PI / 2;
        scene.add(ground);
        // Camera
        camera = new THREE.PerspectiveCamera(
            60,
            container.clientWidth / container.clientHeight,
            0.01,
            10000
        );
        camera.position.set(0, 2, 5);
        // Renderer
        renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        renderer.setPixelRatio(window.devicePixelRatio);
        renderer.setSize(container.clientWidth, container.clientHeight);
        container.appendChild(renderer.domElement);

        // Orbit controls (inspect mode)
        controls = new OrbitControls(camera, renderer.domElement);
        controls.target.set(0, 0, 0);
        controls.enableDamping = true;
        controls.dampingFactor = 0.08;
        controls.enablePan = false;
        controls.enabled = true; // always enabled for manual camera control
        controls.enableZoom = true;
        controls.enableRotate = true;
        controls.enablePan = false;

        // Resize
        window.addEventListener('resize', () => {
            if (!container || !renderer || !camera) return;
            const width = container.clientWidth;
            const height = container.clientHeight;
            renderer.setSize(width, height);
            camera.aspect = width / height;
            camera.updateProjectionMatrix();
        });
        // Lights
        const light = new THREE.DirectionalLight(0xffffff, 1);
        light.position.set(5, 5, 5);
        scene.add(light);
        const ambient = new THREE.AmbientLight(0xffffff, 0.6);
        scene.add(ambient);
        // Load model
        const loader = new GLTFLoader();
        loader.load('/static/models/rv7.glb', function(gltf) {
            const model = gltf.scene;
            scene.add(model);
            window.aircraftModel = model;
            // Remove baked orientation offsets (prevents sideways flight)
            model.rotation.set(0, 0, 0);
            model.traverse((child) => {
                if (child.isMesh) {
                    child.frustumCulled = false;
                    if (child.material) child.material.side = THREE.DoubleSide;
                }
            });
            const box = new THREE.Box3().setFromObject(model);
            const size = box.getSize(new THREE.Vector3());
            const maxDim = Math.max(size.x, size.y, size.z);
            const safeDim = maxDim > 0 ? maxDim : 1;
            const fov = camera.fov * (Math.PI / 180);
            let cameraZ = Math.abs(safeDim / Math.tan(fov / 2));
            camera.position.set(0, safeDim * 0.25, cameraZ * 1.2);
            camera.near = 0.1;
            camera.far = 50000;
            camera.updateProjectionMatrix();
            const scaleFactor = 2;
            model.scale.set(scaleFactor, scaleFactor, scaleFactor);
            // Initialize position from first data point if available
            const latArr = window.latitudes || window._latitudes;
            const lonArr = window.longitudes || window._longitudes;
            const altArr = window.altitudes || window._altitudes;

            if (latArr && lonArr && latArr.length > 0) {
                const lat0 = latArr[0];
                const lon0 = lonArr[0];
                const alt0 = altArr && altArr.length > 0 ? altArr[0] : 0;

                const pos = latLonToXYZ(lat0, lon0, alt0);
                model.position.set(pos.x, pos.y, pos.z);
                if (controls) {
                    controls.target.set(pos.x, pos.y, pos.z);
                    controls.update();
                } else {
                    camera.lookAt(pos.x, pos.y, pos.z);
                }

            } else {
                model.position.set(0, 0, 0);
                if (controls) {
                    controls.target.set(0, 0, 0);
                    controls.update();
                } else {
                    camera.lookAt(0, 0, 0);
                }
            }
            // Expose updateAircraft3D (updates position, rotation, and moves camera to follow)
            window.updateAircraft3D = function(lat, lon, alt, pitchDeg, rollDeg, headingDeg) {
                if (!window.aircraftModel) return;

                const toRad = Math.PI / 180;

                // --- POSITION UPDATE ---
                const pos = latLonToXYZ(lat, lon, alt);

                // Sync Cesium world position (NO orientation changes)
                if (cesiumViewer && cesiumEntity) {
                    cesiumEntity.position = Cesium.Cartesian3.fromDegrees(lat, lon, alt || 0);
                }

                window.aircraftModel.position.set(pos.x, pos.y, pos.z);

                // --- ROTATION UPDATE ---
                const pitch = (pitchDeg || 0) * toRad;
                const roll = -(rollDeg || 0) * toRad;
                const yaw = -(headingDeg || 0) * toRad;

                // Correct aviation orientation in ENU frame
                const euler = new THREE.Euler(
                    -pitch,
                    yaw,
                    -roll,
                    'YXZ'
                );

                window.aircraftModel.setRotationFromEuler(euler);

                // --- CAMERA FOLLOW ---
                const offsetBack = 15;
                const offsetUp = 5;

                // True world-space forward direction of aircraft
                const forward = new THREE.Vector3();
                window.aircraftModel.getWorldDirection(forward);

                const up = new THREE.Vector3(0, 1, 0)
                    .applyQuaternion(window.aircraftModel.quaternion)
                    .normalize();

                const cameraPos = new THREE.Vector3()
                    .copy(pos)
                    .add(up.clone().multiplyScalar(offsetUp))
                    .add(forward.clone().multiplyScalar(-offsetBack));

                camera.position.copy(cameraPos);

                // Sync OrbitControls target with aircraft position
                if (controls) {
                    controls.target.copy(pos);
                    camera.lookAt(pos);
                    controls.update();
                } else {
                    camera.lookAt(pos.x, pos.y, pos.z);
                }
            };
        }, undefined, function(error) {
            console.error('Model load error:', error);
            container.innerHTML = `<div class="text-danger small text-center p-2">Model Load Error</div>`;
        });
        // Axes helper
        const axesHelper = new THREE.AxesHelper(5);
        scene.add(axesHelper);
        function animate() {
            animationFrameId = requestAnimationFrame(animate);
            if (controls) controls.update();
            renderer.render(scene, camera);
        }
        animate();
    }

    // Expose to window for analyzer.html
    window.init3DViewer = init3DViewer;
    window.latLonToXYZ = latLonToXYZ;
    // Bridge for analyzer hover/index-based updates
    window.update3DPosition = function(idx) {
        try {
            const latArr = window.latitudes || window._latitudes;
            const lonArr = window.longitudes || window._longitudes;
            const altArr = window.altitudes || window._altitudes;
            const pitchArr = window.pitch || window.pitches;
            const rollArr = window.roll || window.rolls;
            const headingArr = window.heading || window.headings;

            if (!latArr || !lonArr) return;

            const lat = latArr[idx];
            const lon = lonArr[idx];
            const alt = altArr ? altArr[idx] : 0;
            const pitch = pitchArr ? pitchArr[idx] : 0;
            const roll = rollArr ? rollArr[idx] : 0;
            const heading = headingArr ? headingArr[idx] : 0;

            if (window.updateAircraft3D) {
                window.updateAircraft3D(lat, lon, alt, pitch, roll, heading);
            }
        } catch (e) {
            console.warn('update3DPosition failed:', e);
        }
    };
    // No global variables are leaked except the above
    // (scene, camera, renderer, animationFrameId, etc are kept local)
    console.log("3D viewer module loaded");
});