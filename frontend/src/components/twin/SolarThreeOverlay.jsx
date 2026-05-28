import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import mapboxgl from 'mapbox-gl'

function lngLatToMercator(lng, lat) {
  const mc = mapboxgl.MercatorCoordinate.fromLngLat({ lng, lat }, 0)
  return {
    x: mc.x,
    y: mc.y,
    meterScale: mc.meterInMercatorCoordinateUnits()
  }
}

function statusToColor(status, availPct) {
  if (status === 'offline') return new THREE.Color(0x1e293b)
  if (status === 'degraded') return new THREE.Color(0xca8a04)
  if (status === 'normal') return new THREE.Color(0x16a34a)
  if (availPct != null) {
    if (availPct >= 95) return new THREE.Color(0x16a34a)
    if (availPct >= 50) return new THREE.Color(0xca8a04)
    return new THREE.Color(0xdc2626)
  }
  return new THREE.Color(0x334155)
}

function buildScene(layoutData, geometryData) {
  const scene = new THREE.Scene()

  // All geometry constants from API
  const tiltRad     = (geometryData.tilt_deg    ?? layoutData.tilt_deg    ?? 0) * Math.PI / 180
  const azimuthRad  = (geometryData.azimuth_deg ?? layoutData.azimuth_deg ?? 0) * Math.PI / 180
  const moduleH     = geometryData.module_height_m   // 1.134m
  const tableW      = geometryData.table_width_m     // 54.672m
  const tableD      = moduleH * 3                    // ~3.4m (3 portrait rows)
  const heightM     = geometryData.height_m ?? 0.70  // array bottom above ground
  const panelThickM = moduleH * 0.035                // ~4cm

  // Site origin in Mercator
  const originLng = layoutData.centre_lon
  const originLat = layoutData.centre_lat
  const { x: ox, y: oy, meterScale: scale } = lngLatToMercator(originLng, originLat)

  // Status lookup
  const statusByGroup = {}
  for (const g of layoutData.inverter_groups) statusByGroup[g.id] = g

  // Lighting
  scene.add(new THREE.HemisphereLight(0x8ab4d4, 0x2d4a1e, 0.6))
  const sun = new THREE.DirectionalLight(0xfff4e0, 2.5)
  sun.position.set(0.5, -1.0, 1.0).normalize()
  scene.add(sun)

  const pulseMeshes = []

  for (const geoGroup of geometryData.groups) {
    const liveGroup = statusByGroup[geoGroup.id]
    if (!liveGroup) continue

    const isOffline = liveGroup.status === 'offline'
    const isFault   = liveGroup.status === 'degraded'
    const color     = statusToColor(liveGroup.status, liveGroup.availability_pct)
    const panels    = geoGroup.panels ?? []
    if (panels.length === 0) continue

    // ── Mounting tables ─────────────────────────────────────────────────
    const tableGeo = new THREE.BoxGeometry(
      tableW      * scale,
      tableD      * scale,
      panelThickM * scale
    )
    const tableMat = new THREE.MeshPhysicalMaterial({
      color,
      metalness: 0.05, roughness: 0.06,
      clearcoat: 1.0,  clearcoatRoughness: 0.03,
      sheen: 0.4,      sheenColor: new THREE.Color(0x1a3a5c),
    })
    const tableMesh = new THREE.InstancedMesh(tableGeo, tableMat, panels.length)
    const dummy = new THREE.Object3D()
    const zCentre = heightM * scale + (tableD / 2) * Math.sin(tiltRad) * scale

    for (let i = 0; i < panels.length; i++) {
      const [pLon, pLat] = panels[i]
      const { x: px, y: py } = lngLatToMercator(pLon, pLat)
      dummy.position.set(px - ox, py - oy, zCentre)
      dummy.rotation.set(tiltRad, 0, azimuthRad)
      dummy.updateMatrix()
      tableMesh.setMatrixAt(i, dummy.matrix)
    }
    tableMesh.instanceMatrix.needsUpdate = true
    scene.add(tableMesh)

    // ── Aluminium frames ────────────────────────────────────────────────
    const frameGeo = new THREE.BoxGeometry(
      (tableW + 0.1) * scale,
      (tableD + 0.1) * scale,
      0.02           * scale
    )
    const frameMat = new THREE.MeshStandardMaterial({ color: 0x9ca3af, metalness: 0.85, roughness: 0.25 })
    const frameMesh = new THREE.InstancedMesh(frameGeo, frameMat, panels.length)
    for (let i = 0; i < panels.length; i++) {
      const [pLon, pLat] = panels[i]
      const { x: px, y: py } = lngLatToMercator(pLon, pLat)
      dummy.position.set(px - ox, py - oy, zCentre - panelThickM * scale * 0.5)
      dummy.rotation.set(tiltRad, 0, azimuthRad)
      dummy.updateMatrix()
      frameMesh.setMatrixAt(i, dummy.matrix)
    }
    frameMesh.instanceMatrix.needsUpdate = true
    scene.add(frameMesh)

    // ── Inverter station ────────────────────────────────────────────────
    const { x: gx, y: gy } = lngLatToMercator(geoGroup.centre_lon, geoGroup.centre_lat)
    const invCount = liveGroup.inverter_count ?? 1
    const invW     = Math.max(4, invCount * 0.9)
    const invD     = 2.5
    const invH     = 2.2
    const southM   = geoGroup.zone_ns_m / 2 + 5
    const invGeo   = new THREE.BoxGeometry(invW * scale, invD * scale, invH * scale)
    const invMat   = new THREE.MeshPhysicalMaterial({
      color:             isOffline ? 0x1e293b : (isFault ? 0x7f1d1d : 0x1a2f1a),
      metalness: 0.75,   roughness: 0.3,
      emissive:          isOffline ? 0x000000 : (isFault ? 0x3f0000 : 0x051005),
      emissiveIntensity: isFault ? 0.8 : 0.4,
    })
    const invBox = new THREE.Mesh(invGeo, invMat)
    invBox.position.set(gx - ox, gy - oy + southM * scale, invH * scale / 2)
    invBox.userData = { isFault, isOffline }
    scene.add(invBox)
    if (!isOffline) pulseMeshes.push(invBox)

    // ── Combiner boxes ──────────────────────────────────────────────────
    const numCombiners = Math.max(1, Math.ceil(invCount / 4))
    for (let c = 0; c < numCombiners; c++) {
      const t        = (c + 0.5) / numCombiners
      const ewOffset = (t - 0.5) * geoGroup.zone_ew_m
      const cbX      = gx - ox + ewOffset * scale * Math.cos(azimuthRad)
      const cbY      = gy - oy + ewOffset * scale * Math.sin(azimuthRad) + geoGroup.zone_ns_m * 0.42 * scale
      const cbGeo    = new THREE.BoxGeometry(0.8 * scale, 0.5 * scale, 1.2 * scale)
      const cbMat    = new THREE.MeshStandardMaterial({ color: isOffline ? 0x1e293b : 0x374151, metalness: 0.65, roughness: 0.3 })
      const cb       = new THREE.Mesh(cbGeo, cbMat)
      cb.position.set(cbX, cbY, 0.6 * scale)
      scene.add(cb)
    }

    // ── Status LED ──────────────────────────────────────────────────────
    if (!isOffline) {
      const led = new THREE.PointLight(isFault ? 0xff4444 : 0x22ff88, 1.5, Math.max(invW, 20) * 3 * scale)
      led.position.set(gx - ox, gy - oy + southM * scale, (invH + 1) * scale)
      scene.add(led)
    }
  }

  return { scene, pulseMeshes, ox, oy }
}

export default function SolarThreeOverlay({ map, layoutData, geometryData }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    if (!map || !layoutData?.inverter_groups?.length || !geometryData?.groups?.length) return
    const canvas = canvasRef.current
    if (!canvas) return

    // Three.js renderer on its own canvas
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true })
    renderer.setClearColor(0x000000, 0)
    renderer.autoClear = true
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.1

    const camera = new THREE.Camera()
    const { scene, pulseMeshes } = buildScene(layoutData, geometryData)

    // Register a Mapbox custom layer SOLELY to extract the projection matrix
    // This layer renders nothing — it just gives us the correct camera matrix
    let currentMatrix = null
    const matrixLayer = {
      id: 'solar-matrix-sync',
      type: 'custom',
      renderingMode: '3d',
      onAdd() {},
      render(gl, args) {
        if (!this._logged) {
          console.log('solar-matrix-sync args keys:', Object.keys(args))
          console.log('solar-matrix-sync args:', JSON.stringify(
            Object.fromEntries(
              Object.entries(args).map(([k,v]) => [k, Array.isArray(v) ? `Array(${v.length})` : (v && typeof v === 'object' ? Object.keys(v) : v)])
            )
          ))
          this._logged = true
        }
        // Try all known Mapbox v3 matrix locations
        currentMatrix =
          args?.defaultProjectionData?.mainMatrix ??
          args?.defaultProjectionData?.projectionMatrix ??
          args?.projectionMatrix ??
          args?.transform?.projectionMatrix ??
          (Array.isArray(args) ? args : null)
      }
    }

    // Add the matrix sync layer — it never draws anything
    const mbMap = map
    function addMatrixLayer() {
      try {
        if (!mbMap.getLayer('solar-matrix-sync')) {
          mbMap.addLayer(matrixLayer)
          console.log('solar-matrix-sync layer added successfully')
        }
      } catch (e) {
        console.warn('solar-matrix-sync addLayer error:', e)
      }
    }
    if (mbMap.isStyleLoaded()) {
      addMatrixLayer()
    } else {
      mbMap.once('styledata', addMatrixLayer)
    }

    // Size the Three.js canvas to match the map container
    function syncSize() {
      const rect = mbMap.getContainer().getBoundingClientRect()
      canvas.width  = rect.width  * devicePixelRatio
      canvas.height = rect.height * devicePixelRatio
      canvas.style.width  = rect.width  + 'px'
      canvas.style.height = rect.height + 'px'
      renderer.setSize(rect.width, rect.height, false)
      renderer.setPixelRatio(devicePixelRatio)
    }
    syncSize()
    window.addEventListener('resize', syncSize)

    let rafId
    function animate() {
      rafId = requestAnimationFrame(animate)
      if (!currentMatrix) return

      // Pulse inverter emissive
      const t = Date.now() / 1000
      for (const mesh of pulseMeshes) {
        const pulse = 0.5 + 0.5 * Math.sin(t * 1.5)
        mesh.material.emissiveIntensity = mesh.userData.isFault
          ? 0.5 + pulse * 0.5
          : 0.2 + pulse * 0.2
      }

      // Apply Mapbox projection matrix directly to Three.js camera
      // Mapbox v3: matrix is a flat 16-element array (column-major)
      // Rotate X by 90° to convert Mapbox Y-up Mercator to Three.js Z-up
      const rotX = new THREE.Matrix4().makeRotationAxis(
        new THREE.Vector3(1, 0, 0), Math.PI / 2
      )
      const m = new THREE.Matrix4().fromArray(currentMatrix).multiply(rotX)
      camera.projectionMatrix = m
      camera.projectionMatrixInverse.copy(m).invert()

      renderer.resetState()
      renderer.render(scene, camera)
    }
    animate()

    // Trigger Mapbox repaint so the matrix layer fires every frame
    const repaintInterval = setInterval(() => mbMap.triggerRepaint(), 16)

    return () => {
      cancelAnimationFrame(rafId)
      clearInterval(repaintInterval)
      window.removeEventListener('resize', syncSize)
      mbMap.off('styledata', addMatrixLayer)
      try {
        if (mbMap && mbMap.getLayer && mbMap.getLayer('solar-matrix-sync')) {
          mbMap.removeLayer('solar-matrix-sync')
        }
      } catch (_) {}
      scene.traverse(obj => {
        if (obj.isMesh) { obj.geometry?.dispose(); obj.material?.dispose() }
      })
      renderer.dispose()
    }
  }, [map, layoutData, geometryData])

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'absolute',
        inset: 0,
        pointerEvents: 'none',
        zIndex: 2,
      }}
    />
  )
}
