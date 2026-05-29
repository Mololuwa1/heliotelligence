import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import mapboxgl from 'mapbox-gl'

function lngLatToMercator(lng, lat) {
  const mc = mapboxgl.MercatorCoordinate.fromLngLat({ lng, lat }, 0)
  return { x: mc.x, y: mc.y, meterScale: mc.meterInMercatorCoordinateUnits() }
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
  const tiltRad     = (geometryData.tilt_deg    ?? layoutData.tilt_deg    ?? 0) * Math.PI / 180
  const azimuthRad  = (geometryData.azimuth_deg ?? layoutData.azimuth_deg ?? 0) * Math.PI / 180
  const moduleH     = geometryData.module_height_m
  const tableW      = geometryData.table_width_m
  const tableD      = moduleH * 3
  const heightM     = geometryData.height_m ?? 0.70
  const panelThickM = moduleH * 0.035
  const { meterScale: scale } = lngLatToMercator(layoutData.centre_lon, layoutData.centre_lat)
  const statusByGroup = {}
  for (const g of layoutData.inverter_groups) statusByGroup[g.id] = g
  scene.add(new THREE.HemisphereLight(0x8ab4d4, 0x2d4a1e, 0.6))
  const sun = new THREE.DirectionalLight(0xfff4e0, 2.5)
  sun.position.set(0.5, -1.0, 1.0).normalize()
  scene.add(sun)
  const pulseMeshes = []
  const dummy = new THREE.Object3D()
  const zCentre = heightM * scale + (tableD / 2) * Math.sin(tiltRad) * scale

  for (const geoGroup of geometryData.groups) {
    const liveGroup = statusByGroup[geoGroup.id]
    if (!liveGroup) continue
    const isOffline = liveGroup.status === 'offline'
    const isFault   = liveGroup.status === 'degraded'
    const color     = statusToColor(liveGroup.status, liveGroup.availability_pct)
    const panels    = geoGroup.panels ?? []
    if (panels.length === 0) continue

    // Panel tables
    const tableMesh = new THREE.InstancedMesh(
      new THREE.BoxGeometry(tableW * scale, tableD * scale, panelThickM * scale),
      new THREE.MeshPhysicalMaterial({ color, metalness: 0.05, roughness: 0.06, clearcoat: 1.0, clearcoatRoughness: 0.03, sheen: 0.4, sheenColor: new THREE.Color(0x1a3a5c) }),
      panels.length
    )
    for (let i = 0; i < panels.length; i++) {
      const { x: px, y: py } = lngLatToMercator(panels[i][0], panels[i][1])
      dummy.position.set(px, py, zCentre)
      dummy.rotation.set(tiltRad, 0, azimuthRad)
      dummy.updateMatrix()
      tableMesh.setMatrixAt(i, dummy.matrix)
    }
    tableMesh.instanceMatrix.needsUpdate = true
    scene.add(tableMesh)

    // Aluminium frames
    const frameMesh = new THREE.InstancedMesh(
      new THREE.BoxGeometry((tableW + 0.1) * scale, (tableD + 0.1) * scale, 0.02 * scale),
      new THREE.MeshStandardMaterial({ color: 0x9ca3af, metalness: 0.85, roughness: 0.25 }),
      panels.length
    )
    for (let i = 0; i < panels.length; i++) {
      const { x: px, y: py } = lngLatToMercator(panels[i][0], panels[i][1])
      dummy.position.set(px, py, zCentre - panelThickM * scale * 0.5)
      dummy.rotation.set(tiltRad, 0, azimuthRad)
      dummy.updateMatrix()
      frameMesh.setMatrixAt(i, dummy.matrix)
    }
    frameMesh.instanceMatrix.needsUpdate = true
    scene.add(frameMesh)

    // Inverter box
    const { x: gx, y: gy } = lngLatToMercator(geoGroup.centre_lon, geoGroup.centre_lat)
    const invCount = liveGroup.inverter_count ?? 1
    const invW = Math.max(4, invCount * 0.9), invD = 2.5, invH = 2.2
    const southM = geoGroup.zone_ns_m / 2 + 5
    const invBox = new THREE.Mesh(
      new THREE.BoxGeometry(invW * scale, invD * scale, invH * scale),
      new THREE.MeshPhysicalMaterial({ color: isOffline ? 0x1e293b : (isFault ? 0x7f1d1d : 0x1a2f1a), metalness: 0.75, roughness: 0.3, emissive: isOffline ? 0x000000 : (isFault ? 0x3f0000 : 0x051005), emissiveIntensity: isFault ? 0.8 : 0.4 })
    )
    invBox.position.set(gx, gy + southM * scale, invH * scale / 2)
    invBox.userData = { isFault, isOffline }
    scene.add(invBox)
    if (!isOffline) pulseMeshes.push(invBox)

    // Combiner boxes
    const numCombiners = Math.max(1, Math.ceil(invCount / 4))
    for (let c = 0; c < numCombiners; c++) {
      const t = (c + 0.5) / numCombiners
      const ewOffset = (t - 0.5) * geoGroup.zone_ew_m
      const cb = new THREE.Mesh(
        new THREE.BoxGeometry(0.8 * scale, 0.5 * scale, 1.2 * scale),
        new THREE.MeshStandardMaterial({ color: isOffline ? 0x1e293b : 0x374151, metalness: 0.65, roughness: 0.3 })
      )
      cb.position.set(
        gx + ewOffset * scale * Math.cos(azimuthRad),
        gy + ewOffset * scale * Math.sin(azimuthRad) + geoGroup.zone_ns_m * 0.42 * scale,
        0.6 * scale
      )
      scene.add(cb)
    }

    // LED
    if (!isOffline) {
      const led = new THREE.PointLight(isFault ? 0xff4444 : 0x22ff88, 1.5, Math.max(invW, 20) * 3 * scale)
      led.position.set(gx, gy + southM * scale, (invH + 1) * scale)
      scene.add(led)
    }
  }
  return { scene, pulseMeshes }
}

export default function SolarThreeOverlay({ map, layoutData, geometryData }) {
  const canvasRef  = useRef(null)
  const matrixRef  = useRef(null)   // ← shared via ref, not closure variable

  useEffect(() => {
    console.log('=== SolarThreeOverlay useEffect fired ===')
    console.log('map:', map ? 'present' : 'NULL')
    console.log('layoutData groups:', layoutData?.inverter_groups?.length ?? 'missing')
    console.log('geometryData groups:', geometryData?.groups?.length ?? 'missing')
    console.log('canvas ref:', canvasRef.current ? 'present' : 'NULL')

    if (!map || !layoutData?.inverter_groups?.length || !geometryData?.groups?.length) {
      console.log('=== EARLY RETURN — missing deps ===')
      return
    }
    const canvas = canvasRef.current
    if (!canvas) {
      console.log('=== EARLY RETURN — no canvas ===')
      return
    }
    console.log('=== proceeding with renderer setup ===')

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true })
    renderer.setClearColor(0x000000, 0)
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.1

    const { scene, pulseMeshes } = buildScene(layoutData, geometryData)

    // Matrix sync layer — writes to matrixRef so animate() can read it
    const matrixLayer = {
      id: 'solar-matrix-sync',
      type: 'custom',
      renderingMode: '3d',
      onAdd() {},
      render(gl, args) {
        if (args && typeof args === 'object' && args[0] !== undefined && args[15] !== undefined) {
          matrixRef.current = Array.from({ length: 16 }, (_, i) => args[i])
        } else if (args?.defaultProjectionData?.mainMatrix) {
          matrixRef.current = Array.from(args.defaultProjectionData.mainMatrix)
        } else if (ArrayBuffer.isView(args)) {
          matrixRef.current = Array.from(args)
        }
      }
    }

    function addMatrixLayer() {
      try {
        if (!map.getLayer('solar-matrix-sync')) {
          map.addLayer(matrixLayer)
        }
      } catch (e) {
        console.warn('addLayer error:', e)
      }
    }

    if (map.isStyleLoaded()) {
      addMatrixLayer()
    } else {
      map.once('styledata', addMatrixLayer)
    }

    // syncSize() must run first to set canvas dimensions
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
    setTimeout(() => {
      document.querySelectorAll('canvas').forEach((c, i) => {
        const s = window.getComputedStyle(c)
        console.log(`DOM Canvas ${i}: ${c.width}x${c.height} z-index:${s.zIndex} position:${s.position} opacity:${s.opacity} parent:${c.parentElement?.className || c.parentElement?.tagName}`)
      })
    }, 2000)
    window.addEventListener('resize', syncSize)

    // Now canvas has correct dimensions
    const camera = new THREE.Camera()

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

      // Mapbox v3 passes projection matrix as numeric-indexed object
      // Apply directly — no rotation needed since geometry is in Mercator space
      const m = new THREE.Matrix4().fromArray(matrix)
      camera.projectionMatrix = m
      camera.projectionMatrixInverse.copy(m).invert()

      renderer.render(scene, camera)
    }
    animate()

    return () => {
      cancelAnimationFrame(rafId)
      clearInterval(repaintInterval)
      window.removeEventListener('resize', syncSize)
      map.off('styledata', addMatrixLayer)
      try { if (map.getLayer('solar-matrix-sync')) map.removeLayer('solar-matrix-sync') } catch (_) {}
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
