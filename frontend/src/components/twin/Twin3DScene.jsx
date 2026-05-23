import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { getGeometry } from '../../api/sites.js';

// Status → Three.js hex colour
const STATUS_HEX = {
  normal:   0x10b981,
  degraded: 0xf6ad55,
  offline:  0xef4444,
  unknown:  0x94a3b8,
};

function getHex(status) {
  return STATUS_HEX[status] ?? STATUS_HEX.unknown;
}

// Convert lat/lon to local X (east), Y (north) metres relative to origin
function makeToLocal(originLat, originLon) {
  const LAT_M = 111320;
  const LON_M = 111320 * Math.cos(originLat * Math.PI / 180);
  return (lat, lon) => [(lon - originLon) * LON_M, (lat - originLat) * LAT_M];
}

// Draw a label texture on a canvas element and return a THREE.CanvasTexture
function makeLabelTexture(group, col) {
  const c = document.createElement('canvas');
  c.width = 192;
  c.height = 64;
  const ctx = c.getContext('2d');

  // Background
  ctx.fillStyle = 'rgba(6,13,26,0.92)';
  ctx.fillRect(0, 0, 192, 64);

  // Border
  const hex = '#' + col.toString(16).padStart(6, '0');
  ctx.strokeStyle = hex;
  ctx.lineWidth = 2;
  ctx.strokeRect(1, 1, 190, 62);

  // Group ID
  ctx.fillStyle = '#ffffff';
  ctx.font = 'bold 24px monospace';
  ctx.textAlign = 'center';
  ctx.fillText(group.id, 96, 28);

  // Inverter count
  ctx.fillStyle = hex;
  ctx.font = '15px monospace';
  ctx.fillText(
    `${group.active_inverters ?? '?'}/${group.inverter_count} inv`,
    96, 50,
  );

  return new THREE.CanvasTexture(c);
}

export default function Twin3DScene({ layoutData, selectedGroup }) {
  const canvasRef = useRef(null);
  const [geoData, setGeoData] = useState(null);

  // Fetch geometry for zone sizes and tilt angle
  useEffect(() => {
    const siteId = layoutData?.site_id;
    if (!siteId) return;
    let cancelled = false;
    getGeometry(siteId, 1)
      .then(d => { if (!cancelled) setGeoData(d); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [layoutData?.site_id]);

  // Build / rebuild Three.js scene
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !layoutData) return;

    const groups = layoutData.inverter_groups ?? [];
    if (!groups.length) return;

    // Scene origin = centroid of group coordinates
    const originLat = groups.reduce((s, g) => s + g.centre_lat, 0) / groups.length;
    const originLon = groups.reduce((s, g) => s + g.centre_lon, 0) / groups.length;
    const toLocal = makeToLocal(originLat, originLon);

    // ── Scene ──────────────────────────────────────────────────────────────
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x060d1a);
    scene.fog = new THREE.FogExp2(0x060d1a, 0.00065);

    // ── Camera (Z-up convention) ────────────────────────────────────────────
    const w = canvas.clientWidth || canvas.offsetWidth || 600;
    const h = canvas.clientHeight || canvas.offsetHeight || 400;
    const camera = new THREE.PerspectiveCamera(48, w / h, 1, 3000);
    camera.up.set(0, 0, 1);
    camera.position.set(0, -650, 420);
    camera.lookAt(0, 0, 0);

    // ── Renderer ────────────────────────────────────────────────────────────
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setSize(w, h, false);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    // ── Lights ─────────────────────────────────────────────────────────────
    scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const sun = new THREE.DirectionalLight(0xfff4d0, 1.1);
    sun.position.set(-300, -200, 500);
    scene.add(sun);

    // ── Ground plane ────────────────────────────────────────────────────────
    // PlaneGeometry lies in XY by default, which is our ground plane in Z-up
    const groundGeo = new THREE.PlaneGeometry(1600, 1400);
    const groundMat = new THREE.MeshLambertMaterial({ color: 0x091a0d });
    scene.add(new THREE.Mesh(groundGeo, groundMat));

    // Subtle grid (rotated to lie in XY / Z-up ground plane)
    const grid = new THREE.GridHelper(1400, 35, 0x0d2a18, 0x0d2a18);
    grid.rotation.x = Math.PI / 2;
    scene.add(grid);

    // ── Site fence ─────────────────────────────────────────────────────────
    const fw = 870, fd = 640;
    const fencePts = [
      [-fw / 2, -fd / 2, 1], [fw / 2, -fd / 2, 1],
      [fw / 2, fd / 2, 1],   [-fw / 2, fd / 2, 1],
      [-fw / 2, -fd / 2, 1],
    ].map(([x, y, z]) => new THREE.Vector3(x, y, z));
    const fenceGeo = new THREE.BufferGeometry().setFromPoints(fencePts);
    scene.add(new THREE.Line(
      fenceGeo,
      new THREE.LineBasicMaterial({ color: 0x3a5570, transparent: true, opacity: 0.6 }),
    ));

    // ── Panel rows & inverter boxes ─────────────────────────────────────────
    const tiltRad = THREE.MathUtils.degToRad(geoData?.tilt_deg ?? 15);
    const ROW_PITCH = 6.6;

    const inverterBoxes = [];
    const disposables = [groundGeo, groundMat, fenceGeo];

    for (const group of groups) {
      const [gx, gy] = toLocal(group.centre_lat, group.centre_lon);
      const isSelected = selectedGroup?.id === group.id;
      const col = getHex(group.status);
      const displayCol = isSelected ? 0xfbbf24 : col;

      const geoGroup = geoData?.groups?.find(g => g.id === group.id);
      const zoneEW = geoGroup?.zone_ew_m ?? 820;
      const zoneNS = geoGroup?.zone_ns_m ?? 79;
      const numRows = Math.max(1, Math.round(zoneNS / ROW_PITCH));

      // Shared geometries per group
      // BoxGeometry(x-width, y-depth, z-height) in our Z-up frame
      // Panel: wide E-W (x), shallow N-S (y), thin Z
      const panelGeo = new THREE.BoxGeometry(zoneEW, 3.4, 1.2);
      const panelFillMat = new THREE.MeshLambertMaterial({
        color: isSelected ? 0x1e3a5f : 0x152a44,
        transparent: true,
        opacity: isSelected ? 0.55 : 0.38,
      });
      const panelWireMat = new THREE.MeshBasicMaterial({
        color: displayCol,
        wireframe: true,
        transparent: true,
        opacity: isSelected ? 1.0 : 0.65,
      });
      disposables.push(panelGeo, panelFillMat, panelWireMat);

      for (let r = 0; r < numRows; r++) {
        const rowY = gy + (r - numRows / 2 + 0.5) * ROW_PITCH;
        // Tilt: rotate around X axis. Positive X rotation tilts positive-Y edge up (north edge rises).
        const fill = new THREE.Mesh(panelGeo, panelFillMat);
        fill.position.set(gx, rowY, 1.5);
        fill.rotation.x = tiltRad;
        scene.add(fill);

        const wire = new THREE.Mesh(panelGeo, panelWireMat);
        wire.position.copy(fill.position);
        wire.rotation.copy(fill.rotation);
        scene.add(wire);
      }

      // Inverter station
      const invGeo = new THREE.BoxGeometry(10, 10, 5);
      const invMat = new THREE.MeshLambertMaterial({ color: displayCol });
      disposables.push(invGeo, invMat);
      const invBox = new THREE.Mesh(invGeo, invMat);
      invBox.position.set(gx, gy, 2.5);
      scene.add(invBox);
      inverterBoxes.push(invBox);

      // Glow ring at base of inverter
      const ringGeo = new THREE.RingGeometry(14, 18, 32);
      const ringMat = new THREE.MeshBasicMaterial({
        color: displayCol,
        transparent: true,
        opacity: 0.35,
        side: THREE.DoubleSide,
      });
      disposables.push(ringGeo, ringMat);
      const ring = new THREE.Mesh(ringGeo, ringMat);
      ring.position.set(gx, gy, 0.5);
      scene.add(ring);

      // Label sprite above inverter
      const labelTex = makeLabelTexture(group, col);
      const spriteMat = new THREE.SpriteMaterial({ map: labelTex, transparent: true });
      disposables.push(labelTex, spriteMat);
      const sprite = new THREE.Sprite(spriteMat);
      sprite.position.set(gx, gy, 50);
      sprite.scale.set(90, 30, 1);
      scene.add(sprite);
    }

    // ── Manual mouse orbit ─────────────────────────────────────────────────
    let isDragging = false;
    let prevMX = 0, prevMY = 0;
    let theta = 0;           // azimuth around Z
    let phi = Math.PI / 3;   // polar angle from Z axis
    let radius = 750;

    function updateCamera() {
      camera.position.set(
        radius * Math.sin(phi) * Math.sin(theta),
        -radius * Math.sin(phi) * Math.cos(theta),
        radius * Math.cos(phi),
      );
      camera.lookAt(0, 0, 0);
    }
    updateCamera();

    function onMouseDown(e) {
      isDragging = true;
      prevMX = e.clientX;
      prevMY = e.clientY;
      canvas.style.cursor = 'grabbing';
    }
    function onMouseMove(e) {
      if (!isDragging) return;
      theta -= (e.clientX - prevMX) * 0.005;
      phi = Math.max(0.08, Math.min(Math.PI / 2.05, phi + (e.clientY - prevMY) * 0.005));
      prevMX = e.clientX;
      prevMY = e.clientY;
      updateCamera();
    }
    function onMouseUp() {
      isDragging = false;
      canvas.style.cursor = 'grab';
    }
    function onWheel(e) {
      e.preventDefault();
      radius = Math.max(200, Math.min(1400, radius + e.deltaY * 0.5));
      updateCamera();
    }

    canvas.style.cursor = 'grab';
    canvas.addEventListener('mousedown', onMouseDown);
    canvas.addEventListener('wheel', onWheel, { passive: false });
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);

    // ── Resize ─────────────────────────────────────────────────────────────
    const ro = new ResizeObserver(() => {
      const nw = canvas.clientWidth;
      const nh = canvas.clientHeight;
      if (!nw || !nh) return;
      camera.aspect = nw / nh;
      camera.updateProjectionMatrix();
      renderer.setSize(nw, nh, false);
    });
    ro.observe(canvas);

    // ── Animation loop ──────────────────────────────────────────────────────
    let rafId;
    function animate() {
      rafId = requestAnimationFrame(animate);
      const t = Date.now() / 1000;
      inverterBoxes.forEach((box, i) => {
        const s = 1 + 0.05 * Math.sin(t * 2 + i * 1.3);
        box.scale.set(s, s, s);
      });
      renderer.render(scene, camera);
    }
    animate();

    // ── Cleanup ─────────────────────────────────────────────────────────────
    return () => {
      cancelAnimationFrame(rafId);
      canvas.removeEventListener('mousedown', onMouseDown);
      canvas.removeEventListener('wheel', onWheel);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
      ro.disconnect();
      renderer.dispose();
      disposables.forEach(d => d.dispose?.());
      scene.clear();
    };
  }, [layoutData, geoData, selectedGroup]);

  return (
    <>
      {!layoutData && (
        <div className="absolute inset-0 flex items-center justify-center bg-[#060D1A]">
          <p className="text-slate-500 text-xs">3D model loading…</p>
        </div>
      )}
      <canvas
        ref={canvasRef}
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          display: 'block',
        }}
      />
    </>
  );
}
