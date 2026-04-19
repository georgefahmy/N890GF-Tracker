import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js';
import { GLTFLoader } from 'https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/controls/OrbitControls.js';

// All logic is now wrapped in DOMContentLoaded for safe initialization.
document.addEventListener('DOMContentLoaded', function() {
    let scene, camera, renderer;
    let animationFrameId = null;
    let cameraInitialized = false;

    // Inspect / orbit controls
    let controls = null;
    let isInspectMode = false;
    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();

    function init3DViewer() {
        const container = document.getElementById('attitude3DContainer');
        if (!container) return;
        container.innerHTML = '';
        container.style.display = 'block';

        // Scene
        scene = new THREE.Scene();

        // Camera
        camera = new THREE.PerspectiveCamera(
            60,
            container.clientWidth / container.clientHeight,
            0.01,
            10000
        );
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

            // Rotate model so X (nose) points forward in Three.js Z direction
            model.rotation.set(0,0, 0);
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
            camera.position.set(0, safeDim * 0.5, cameraZ * 1.5);
            camera.near = 0.1;
            camera.far = 50000;

            // camera.updateProjectionMatrix();
            const scaleFactor = 2;
            model.scale.set(scaleFactor, scaleFactor, scaleFactor);

            // Make model stationary
            model.position.set(0, 0, 0);

            // Simplify updateAircraft3D to only handle rotation
            window.updateAircraft3D = function(pitchDeg, rollDeg, headingDeg) {
                if (!window.aircraftModel) return;

                const toRad = Math.PI / 180;
                // const toRad = 1;

                const pitch = (pitchDeg || 0) * toRad;
                const roll = (rollDeg || 0) * toRad;
                const yaw = -(headingDeg + 180 || 0) * toRad;

                // Directly set rotations (X = pitch, Y = yaw, Z = roll)
                window.aircraftModel.rotation.set(pitch, yaw, roll);

                // Keep camera fixed in world space
                // Only ensure it is looking at the model origin
                if (controls) {
                    controls.target.set(0, 0, 0);
                    controls.update();
                } else {
                    camera.lookAt(0, 0, 0);
                }
            };
        }, undefined, function(error) {
            console.error('Model load error:', error);
            container.innerHTML = `<div class="text-danger small text-center p-2">Model Load Error</div>`;
        });
        // --- INERTIAL FRAME MARKERS ---

        // World axes (larger and more visible)
        const axesHelper = new THREE.AxesHelper(50);
        scene.add(axesHelper);

        // Ground grid (acts as inertial reference plane)
        const gridHelper = new THREE.GridHelper(200, 50);
        gridHelper.position.set(0, -10, 0);
        scene.add(gridHelper);

        // Optional horizon plane (subtle visual reference)
        const planeGeometry = new THREE.PlaneGeometry(200000, 2000000);
        const planeMaterial = new THREE.MeshBasicMaterial({
            color: 0x444444,
            side: THREE.DoubleSide,
            transparent: true,
            opacity: 0.15
        });

        const horizonPlane = new THREE.Mesh(planeGeometry, planeMaterial);
        horizonPlane.rotation.x = -Math.PI / 2;
        horizonPlane.position.y = 0;
        scene.add(horizonPlane);

        // Optional origin marker (small sphere at 0,0,0)
        const originGeometry = new THREE.SphereGeometry(0.5, 16, 16);
        const originMaterial = new THREE.MeshBasicMaterial({ color: 0xff0000 });
        const originMarker = new THREE.Mesh(originGeometry, originMaterial);
        originMarker.position.set(0, 0, 0);
        scene.add(originMarker);
        function animate() {
            animationFrameId = requestAnimationFrame(animate);
            if (controls) controls.update();
            renderer.render(scene, camera);
        }
        animate();
    }

    // Expose to window for analyzer.html
    window.init3DViewer = init3DViewer;
    console.log("3D viewer module loaded");
});