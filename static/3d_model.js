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
            // Updated updateAircraft3D to handle both rotation and position
            window.updateAircraft3D = function(pitchDeg, rollDeg, headingDeg, x, y, z) {
                if (!window.aircraftModel) return;

                const toRad = Math.PI / 180;

                const pitch = (pitchDeg || 0) * 1.5 * toRad;
                const roll = (rollDeg || 0) * toRad;
                const yaw = -(headingDeg +180|| 0) * toRad;

                // Build quaternion using proper aviation rotation order: yaw → pitch → roll
                const q = new THREE.Quaternion();
                const qYaw = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), yaw);
                const qPitch = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(-1, 0, 0), pitch);
                const qRoll = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), roll);

                // Apply in correct order: yaw, then pitch, then roll
                q.multiply(qYaw).multiply(qPitch).multiply(qRoll);
                window.aircraftModel.quaternion.copy(q);

                // --- NEW POSITION LOGIC ---
                // Default to 0 if coordinates aren't provided yet
                const targetX = x || 0;

                // Note: If altitude is in feet and X/Z are in meters, you may want to multiply Y by 0.3048
                const targetY = y * 0.3048 || 0;
                const targetZ = -z || 0;

                const newPos = new THREE.Vector3(targetX, targetY, targetZ);
                const oldPos = window.aircraftModel.position.clone();

                // Calculate how much the aircraft moved this frame
                const delta = new THREE.Vector3().subVectors(newPos, oldPos);

                // Move the aircraft
                window.aircraftModel.position.copy(newPos);

                // Move the camera by the exact same amount so it follows the plane smoothly
                camera.position.add(delta);

                // --- IMPROVED "SLIDING" GRID LOGIC ---
                if (window.gridHelper && window.gridDots) {
                    const distThreshold = 5000; // Only reset grid position if we move 2km from its current center

                    const dx = targetX - window.gridHelper.position.x;
                    const dz = targetZ - window.gridHelper.position.z;

                    // If the plane moves too far from the current grid center, jump the grid forward
                    if (Math.abs(dx) > distThreshold || Math.abs(dz) > distThreshold) {
                        const snapX = Math.round(targetX / 100) * 100;
                        const snapZ = Math.round(targetZ / 100) * 100;

                        window.gridHelper.position.set(snapX, -1, snapZ);
                        window.gridDots.position.set(snapX, -1, snapZ);
                    }
                }

                // Keep camera orbit controls centered on the aircraft
                if (controls) {
                    controls.target.copy(newPos);
                    controls.update();
                } else {
                    camera.lookAt(newPos);
                }
            };
        }, undefined, function(error) {
            console.error('Model load error:', error);
            container.innerHTML = `<div class="text-danger small text-center p-2">Model Load Error</div>`;
        });

        // World axes (larger and more visible)
        const axesHelper = new THREE.AxesHelper(50);
        scene.add(axesHelper);

        // Ground grid (acts as inertial reference plane)
        window.gridHelper = new THREE.GridHelper(50000, 200);
        window.gridHelper.position.set(0, -1, 0);
        scene.add(window.gridHelper);

        // --- NEW CODE: Add red dots every 100 meters ---
        const dotGeometry = new THREE.BufferGeometry();
        const dotMaterial = new THREE.PointsMaterial({ size: 100, color: 0xff0000 });
        const dotPositions = [];


        const gridExtent = 100000;
        const step = 1000;
        const halfExtent = gridExtent / 2;

        // Loop through the X and Z axes at 100-unit intervals
        for (let x = -halfExtent; x <= halfExtent; x += step) {
            for (let z = -halfExtent; z <= halfExtent; z += step) {
                // Push X, Y, Z coordinates into the array.
                // Y is 0 here, but we will offset the whole Points object to match the grid below.
                dotPositions.push(x, 0, z);
            }
        }

        // Attach the coordinates to the geometry
        dotGeometry.setAttribute('position', new THREE.Float32BufferAttribute(dotPositions, 3));

        // Create the Points object and match the gridHelper's Y-offset
        window.gridDots = new THREE.Points(dotGeometry, dotMaterial);
        window.gridDots.position.set(0, -1, 0);
        scene.add(window.gridDots);
        // -----------------------------------------------
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