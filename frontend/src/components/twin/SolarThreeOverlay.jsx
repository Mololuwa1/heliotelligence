import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import mapboxgl from 'mapbox-gl'

// Convert lng/lat offset from origin to local metres (X=east, Y=north)
function toLocalMetres(lng, lat, originLng, originLat) {
  const metersPerDegLat = 111320
  const metersPerDegLon = 111320 * Math.cos(originLat * Math.PI / 180)
  return {
    x: (lng - originLng) * metersPerDegLon,
    y: (lat - originLat) * metersPerDegLat,
  }
}

function statusToColor(status, availPct) {
  if (status === 'offline') return new THREE.Color(0x1e293b)
  if (status === 'degraded') return new THREE.Color(0xca8a04)
  if (status === 'normal')   return new THREE.Color(0x16a34a)
  if (availPct != null) {
    if (availPct >= 95) return new THREE.Color(0x16a34a)
    if (availPct >= 50) return new THREE.Color(0xca8a04)
    return new THREE.Color(0xdc2626)
  }
  return new THREE.Color(0x334155)
}

function buildScene(layoutData, geometryData) {
  const scene = new THREE.Scene()

  // All geometry in LOCAL METRES — X=east, Y=north, Z=up
  // Origin = site centre (0, 0, 0)
  const originLng = layoutData.centre_lon
  const originLat = layoutData.centre_lat

  const tiltRad    = (geometryData.tilt_deg    ?? layoutData.tilt_deg    ?? 0) * Math.PI / 180
  const azimuthDeg = (geometryData.azimuth_deg ?? layoutData.azimuth_deg ?? 0)
  // Mapbox azimuth: 0=South, positive=West. Convert to bearing from North for Three.js
  const azimuthRad = -(azimuthDeg) * Math.PI / 180
  const moduleH    = geometryData.module_height_m   // 1.134m
  const tableW     = geometryData.table_width_m     // 54.672m
  const tableD     = moduleH * 3                    // ~3.4m
  const heightM    = geometryData.height_m ?? 0.70
  const thickM     = 0.04                           // panel thickness 4cm

  // Lighting
  scene.add(new THREE.HemisphereLight(0x8ab4d4, 0x2d4a1e, 0.6))
  const sun = new THREE.DirectionalLight(0xfff4e0, 2.5)
  sun.position.set(100, -200, 300)
  scene.add(sun)

  const pulseMeshes = []
  const dummy = new THREE.Object3D()

  const statusByGroup = {}
  for (const g of layoutData.inverter_groups) statusByGroup[g.id] = g

  for (const geoGroup of geometryData.groups) {
    const liveGroup = statusByGroup[geoGroup.id]
    if (!liveGroup) continue

    const isOffline = liveGroup.status === 'offline'
    const isFault   = liveGroup.status === 'degraded'
    const color     = statusToColor(liveGroup.status, liveGroup.availability_pct)
    const panels    = geoGroup.panels ?? []
    if (panels.length === 0) continue

    // ── Panel mounting tables ────────────────────────────────────────────
    // BoxGeometry: width=E-W, height=N-S depth, depth=thickness
    const tableGeo = new THREE.BoxGeometry(tableW, tableD, thickM)
    const tableMat = new THREE.MeshPhysicalMaterial({
      color,
      metalness: 0.05, roughness: 0.06,
      clearcoat: 1.0, clearcoatRoughness: 0.03,
      sheen: 0.4, sheenColor: new THREE.Color(0x1a3a5c),
    })
    const tableMesh = new THREE.InstancedMesh(tableGeo, tableMat, panels.length)

    // Z-centre of panel: height above ground + half panel depth projected up
    const zCentre = heightM + (tableD / 2) * Math.sin(tiltRad)

    for (let i = 0; i < panels.length; i++) {
      const [pLon, pLat] = panels[i]
      const { x, y } = toLocalMetres(pLon, pLat, originLng, originLat)
      dummy.position.set(x, y, zCentre)
      dummy.rotation.set(0, 0, azimuthRad)  // azimuth: rotate around Z
      dummy.rotateX(-tiltRad)               // tilt: rotate around local X
      dummy.updateMatrix()
      tableMesh.setMatrixAt(i, dummy.matrix)
    }
    tableMesh.instanceMatrix.needsUpdate = true
    scene.add(tableMesh)

    // ── Aluminium frames ─────────────────────────────────────────────────
    const frameMesh = new THREE.InstancedMesh(
      new THREE.BoxGeometry(tableW + 0.1, tableD + 0.1, 0.02),
      new THREE.MeshStandardMaterial({ color: 0x9ca3af, metalness: 0.85, roughness: 0.25 }),
      panels.length
    )
    for (let i = 0; i < panels.length; i++) {
      const [pLon, pLat] = panels[i]
      const { x, y } = toLocalMetres(pLon, pLat, originLng, originLat)
      dummy.position.set(x, y, zCentre - thickM * 0.5)
      dummy.rotation.set(0, 0, azimuthRad)
      dummy.rotateX(-tiltRad)
      dummy.updateMatrix()
      frameMesh.setMatrixAt(i, dummy.matrix)
    }
    frameMesh.instanceMatrix.needsUpdate = true
    scene.add(frameMesh)

    // ── Inverter station ─────────────────────────────────────────────────
    const { x: gx, y: gy } = toLocalMetres(geoGroup.centre_lon, geoGroup.centre_lat, originLng, originLat)
    const invCount = liveGroup.inverter_count ?? 1
    const invW = Math.max(4, invCount * 0.9), invD = 2.5, invH = 2.2
    const southM = geoGroup.zone_ns_m / 2 + 5
    const invBox = new THREE.Mesh(
      new THREE.BoxGeometry(invW, invD, invH),
      new THREE.MeshPhysicalMaterial({
        color: isOffline ? 0x1e293b : (isFault ? 0x7f1d1d : 0x1a2f1a),
        metalness: 0.75, roughness: 0.3,
        emissive: isOffline ? 0x000000 : (isFault ? 0x3f0000 : 0x051005),
        emissiveIntensity: isFault ? 0.8 : 0.4,
      })
    )
    // Place south of group centre (negative Y = south in Y-up/north convention)
    invBox.position.set(gx, gy - southM, invH / 2)
    invBox.userData = { isFault, isOffline }
    scene.add(invBox)
    if (!isOffline) pulseMeshes.push(invBox)

    // ── Combiner boxes ───────────────────────────────────────────────────
    const numCombiners = Math.max(1, Math.ceil(invCount / 4))
    for (let c = 0; c < numCombiners; c++) {
      const t = (c + 0.5) / numCombiners
      const ewOffset = (t - 0.5) * geoGroup.zone_ew_m
      const cb = new THREE.Mesh(
        new THREE.BoxGeometry(0.8, 0.5, 1.2),
        new THREE.MeshStandardMaterial({ color: isOffline ? 0x1e293b : 0x374151, metalness: 0.65, roughness: 0.3 })
      )
      cb.position.set(gx + ewOffset * Math.cos(azimuthRad), gy - geoGroup.zone_ns_m * 0.42, 0.6)
      scene.add(cb)
    }

    // ── Status LED ───────────────────────────────────────────────────────
    if (!isOffline) {
      const led = new THREE.PointLight(isFault ? 0xff4444 : 0x22ff88, 1.5, Math.max(invW, 20) * 3)
      led.position.set(gx, gy - southM, invH + 1)
      scene.add(led)
    }
  }

  return { scene, pulseMeshes }
}

export default function SolarThreeOverlay({ map, layoutData, geometryData }) {
  const canvasRef  = useRef(null)
  const matrixRef  = useRef(null)

  useEffect(() => {
    if (!map || !layoutData?.inverter_groups?.length || !geometryData?.groups?.length) return
    const canvas = canvasRef.current
    if (!canvas) return

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true })
    renderer.setClearColor(0x000000, 0)
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.1

    const camera = new THREE.Camera()
    const { scene, pulseMeshes } = buildScene(layoutData, geometryData)

    // Compute modelTransform — converts local metres to Mercator space
    // This is the official Mapbox + Three.js pattern
    const originLng = layoutData.centre_lon
    const originLat = layoutData.centre_lat
    const originMercator = mapboxgl.MercatorCoordinate.fromLngLat(
      { lng: originLng, lat: originLat }, 0
    )
    const mScale = originMercator.meterInMercatorCoordinateUnits()

    // modelTransform: translate to Mercator origin, scale metres→Mercator,
    // flip Y (Mercator Y increases southward, Three.js Y increases northward),
    // rotate X by π/2 (Three.js Z-up → Mapbox Y-down convention)
    const modelTransform = new THREE.Matrix4()
      .makeTranslation(originMercator.x, originMercator.y, originMercator.z)
      .scale(new THREE.Vector3(mScale, -mScale, mScale))
      .multiply(new THREE.Matrix4().makeRotationX(Math.PI / 2))

    // Matrix sync layer — captures Mapbox projection matrix each frame
    const matrixLayer = {
      id: 'solar-matrix-sync',
      type: 'custom',
      renderingMode: '3d',
      onAdd() {},
      render(gl, args) {
        if (args && args[0] !== undefined && args[15] !== undefined) {
          matrixRef.current = Array.from({ length: 16 }, (_, i) => args[i])
        } else if (args?.defaultProjectionData?.mainMatrix) {
          matrixRef.current = Array.from(args.defaultProjectionData.mainMatrix)
        }
      }
    }

    function addMatrixLayer() {
      try {
        if (!map.getLayer('solar-matrix-sync')) map.addLayer(matrixLayer)
      } catch (e) {
        console.warn('addLayer error:', e)
      }
    }
    if (map.isStyleLoaded()) addMatrixLayer()
    else map.once('styledata', addMatrixLayer)

    function syncSize() {
      const rect = map.getContainer().getBoundingClientRect()
      canvas.width  = rect.width  * devicePixelRatio
      canvas.height = rect.height * devicePixelRatio
      canvas.style.width  = rect.width  + 'px'
      canvas.style.height = rect.height + 'px'
      renderer.setSize(rect.width, rect.height, false)
      renderer.setPixelRatio(devicePixelRatio)
    }
    syncSize()
    window.addEventListener('resize', syncSize)

    const repaintInterval = setInterval(() => map.triggerRepaint(), 16)

    let rafId
    function animate() {
      rafId = requestAnimationFrame(animate)

      const t = Date.now() / 1000
      for (const mesh of pulseMeshes) {
        const pulse = 0.5 + 0.5 * Math.sin(t * 1.5)
        mesh.material.emissiveIntensity = mesh.userData.isFault
          ? 0.5 + pulse * 0.5
          : 0.2 + pulse * 0.2
      }

      const matrix = matrixRef.current
      if (!matrix) return

      // Official Mapbox + Three.js pattern:
      // camera matrix = mapboxProjectionMatrix * modelTransform
      const mapboxMatrix = new THREE.Matrix4().fromArray(matrix)
      camera.projectionMatrix = mapboxMatrix.multiply(modelTransform)
      camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert()

      renderer.render(scene, camera)
    }
    animate()

    return () => {
      cancelAnimationFrame(rafId)
      clearInterval(repaintInterval)
      window.removeEventListener('resize', syncSize)
      map.off('styledata', addMatrixLayer)
      try {
        if (map.getLayer && map.getLayer('solar-matrix-sync')) map.removeLayer('solar-matrix-sync')
      } catch (_) {}
      scene.traverse(obj => {
        if (obj.isMesh) { obj.geometry?.dispose(); obj.material?.dispose() }
      })
      renderer.dispose()
      matrixRef.current = null
    }
  }, [map, layoutData, geometryData])

  return (
    <canvas
      ref={canvasRef}
      style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 2 }}
    />
  )
}
