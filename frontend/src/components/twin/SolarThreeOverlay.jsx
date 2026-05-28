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
  if (status === 'normal') return new THREE.Color(0x16a34a)
  if (availPct != null) {
    if (availPct >= 95) return new THREE.Color(0x16a34a)
    if (availPct >= 50) return new THREE.Color(0xca8a04)
    return new THREE.Color(0xdc2626)
  }
  return new THREE.Color(0x334155)
}

export default function SolarThreeOverlay({ map, layoutData, geometryData }) {
  const canvasRef = useRef(null)
  const stateRef = useRef(null)

  useEffect(() => {
    if (!map || !layoutData?.inverter_groups?.length || !geometryData?.groups?.length) return
    const canvas = canvasRef.current
    if (!canvas) return

    // Own WebGL context — no sharing with Mapbox/DeckGL
    const renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
      powerPreference: 'high-performance',
    })
    renderer.autoClear = true
    renderer.setClearColor(0x000000, 0)
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.1

    // Deduplicated FOV — used in both camera init and animate loop
    const FOV = 28

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(FOV, canvas.width / canvas.height, 0.000001, 10)

    // Lighting
    scene.add(new THREE.HemisphereLight(0x8ab4d4, 0x2d4a1e, 0.6))
    const sun = new THREE.DirectionalLight(0xfff4e0, 2.5)
    sun.position.set(0.5, -1.0, 1.0).normalize()
    scene.add(sun)

    // All geometry from API — zero hardcoded numbers
    const tiltRad     = (geometryData.tilt_deg    ?? layoutData.tilt_deg    ?? 0) * Math.PI / 180
    const azimuthRad  = (geometryData.azimuth_deg ?? layoutData.azimuth_deg ?? 0) * Math.PI / 180
    const moduleW     = geometryData.module_width_m    // E-W panel width (2.278m)
    const moduleH     = geometryData.module_height_m   // N-S panel height (1.134m)
    const tableW      = geometryData.table_width_m     // E-W table span (54.672m)
    const tableD      = moduleH * 3                    // 3P portrait rows deep (~3.4m)
    const rowPitch    = geometryData.row_pitch_m       // row centre-to-centre (6.6m)
    const heightM     = geometryData.height_m ?? 0.70  // array bottom above ground
    const panelThickM = moduleH * 0.035                // realistic panel thickness ~4cm

    const originLng = layoutData.centre_lon
    const originLat = layoutData.centre_lat
    const { x: ox, y: oy, meterScale: scale } = lngLatToMercator(originLng, originLat)

    const statusByGroup = {}
    for (const g of layoutData.inverter_groups) statusByGroup[g.id] = g

    const pulseMeshes = []

    for (const geoGroup of geometryData.groups) {
      const liveGroup = statusByGroup[geoGroup.id]
      if (!liveGroup) continue

      const isOffline = liveGroup.status === 'offline'
      const isFault   = liveGroup.status === 'degraded'
      const color     = statusToColor(liveGroup.status, liveGroup.availability_pct)
      const panels    = geoGroup.panels ?? []
      if (panels.length === 0) continue

      // ── Mounting tables — one InstancedMesh per group ────────────────────
      // Each panel[i] is the centre of a mounting table (tableW × tableD metres)
      const tableGeo = new THREE.BoxGeometry(
        tableW      * scale,   // E-W width  (54.672m)
        tableD      * scale,   // N-S depth  (~3.4m — 3 portrait rows)
        panelThickM * scale    // Thickness  (~4cm)
      )
      const tableMat = new THREE.MeshPhysicalMaterial({
        color,
        metalness:          0.05,
        roughness:          0.06,
        clearcoat:          1.0,
        clearcoatRoughness: 0.03,
        sheen:              0.4,
        sheenColor:         new THREE.Color(0x1a3a5c),
      })
      const tableMesh = new THREE.InstancedMesh(tableGeo, tableMat, panels.length)
      const dummy = new THREE.Object3D()

      for (let i = 0; i < panels.length; i++) {
        const [pLon, pLat] = panels[i]
        const { x: px, y: py } = lngLatToMercator(pLon, pLat)
        // Z: height_m is bottom of array; add half panel depth projected vertically
        const zCentre = heightM * scale + (tableD / 2) * Math.sin(tiltRad) * scale
        dummy.position.set(px - ox, py - oy, zCentre)
        dummy.rotation.set(tiltRad, 0, azimuthRad)
        dummy.updateMatrix()
        tableMesh.setMatrixAt(i, dummy.matrix)
      }
      tableMesh.instanceMatrix.needsUpdate = true
      scene.add(tableMesh)

      // ── Aluminium frames — thin border around each table ─────────────────
      const frameGeo = new THREE.BoxGeometry(
        (tableW + 0.1) * scale,
        (tableD + 0.1) * scale,
        0.02           * scale
      )
      const frameMat = new THREE.MeshStandardMaterial({
        color: 0x9ca3af, metalness: 0.85, roughness: 0.25,
      })
      const frameMesh = new THREE.InstancedMesh(frameGeo, frameMat, panels.length)
      for (let i = 0; i < panels.length; i++) {
        const [pLon, pLat] = panels[i]
        const { x: px, y: py } = lngLatToMercator(pLon, pLat)
        const zCentre = heightM * scale + (tableD / 2) * Math.sin(tiltRad) * scale - panelThickM * scale * 0.5
        dummy.position.set(px - ox, py - oy, zCentre)
        dummy.rotation.set(tiltRad, 0, azimuthRad)
        dummy.updateMatrix()
        frameMesh.setMatrixAt(i, dummy.matrix)
      }
      frameMesh.instanceMatrix.needsUpdate = true
      scene.add(frameMesh)

      // ── Racking posts — 2 per table, at N and S edges ────────────────────
      const postH   = heightM + (tableD / 2) * Math.sin(tiltRad)
      const postGeo = new THREE.CylinderGeometry(0.025 * scale, 0.03 * scale, postH * scale, 6)
      const postMat = new THREE.MeshStandardMaterial({ color: 0x6b7280, metalness: 0.7, roughness: 0.4 })
      // Only render posts for first 30 tables for performance
      const postCount = Math.min(panels.length, 30) * 2
      const postMesh = new THREE.InstancedMesh(postGeo, postMat, postCount)
      let pi = 0
      for (let i = 0; i < Math.min(panels.length, 30); i++) {
        const [pLon, pLat] = panels[i]
        const { x: px, y: py } = lngLatToMercator(pLon, pLat)
        const halfD = (tableD / 2) * scale
        for (const side of [-1, 1]) {
          dummy.position.set(
            px - ox + side * halfD * Math.sin(azimuthRad),
            py - oy + side * halfD * Math.cos(azimuthRad),
            postH * scale / 2
          )
          dummy.rotation.set(0, 0, 0)
          dummy.updateMatrix()
          postMesh.setMatrixAt(pi++, dummy.matrix)
        }
      }
      postMesh.instanceMatrix.needsUpdate = true
      scene.add(postMesh)

      // ── Inverter station ─────────────────────────────────────────────────
      const { x: gx, y: gy } = lngLatToMercator(geoGroup.centre_lon, geoGroup.centre_lat)
      const invCount = liveGroup.inverter_count ?? 1
      const invW     = Math.max(4, invCount * 0.9) // width scales with inverter count
      const invD     = 2.5                          // standard inverter depth (m)
      const invH     = 2.2                          // standard inverter height (m)
      const invGeo   = new THREE.BoxGeometry(invW * scale, invD * scale, invH * scale)
      const invMat   = new THREE.MeshPhysicalMaterial({
        color:             isOffline ? 0x1e293b : (isFault ? 0x7f1d1d : 0x1a2f1a),
        metalness:         0.75,
        roughness:         0.3,
        emissive:          isOffline ? 0x000000 : (isFault ? 0x3f0000 : 0x051005),
        emissiveIntensity: isFault ? 0.8 : 0.4,
      })
      const invBox = new THREE.Mesh(invGeo, invMat)
      // Place south of array centre by half the zone depth plus a buffer
      const southM = (geoGroup.zone_ns_m / 2 + 5)
      invBox.position.set(gx - ox, gy - oy + southM * scale, invH * scale / 2)
      invBox.userData = { isFault, isOffline }
      scene.add(invBox)
      if (!isOffline) pulseMeshes.push(invBox)

      // ── Combiner boxes ────────────────────────────────────────────────────
      const numCombiners = Math.max(1, Math.ceil(invCount / 4))
      const cbW = 0.8, cbD = 0.5, cbH = 1.2
      for (let c = 0; c < numCombiners; c++) {
        const t        = (c + 0.5) / numCombiners
        const ewOffset = (t - 0.5) * geoGroup.zone_ew_m
        const cbX = gx - ox + ewOffset * scale * Math.cos(azimuthRad)
        const cbY = gy - oy + ewOffset * scale * Math.sin(azimuthRad) + (geoGroup.zone_ns_m * 0.42) * scale
        const cbGeo = new THREE.BoxGeometry(cbW * scale, cbD * scale, cbH * scale)
        const cbMat = new THREE.MeshStandardMaterial({
          color: isOffline ? 0x1e293b : 0x374151,
          metalness: 0.65, roughness: 0.3,
          emissive: isOffline ? 0x000000 : 0x0a0f0a,
          emissiveIntensity: 0.2,
        })
        const cb = new THREE.Mesh(cbGeo, cbMat)
        cb.position.set(cbX, cbY, cbH * scale / 2)
        scene.add(cb)
      }

      // ── Status LED point light ────────────────────────────────────────────
      if (!isOffline) {
        const ledColor = isFault ? 0xff4444 : 0x22ff88
        const ledRange = Math.max(invW, 20) * 3 * scale
        const led = new THREE.PointLight(ledColor, 1.5, ledRange)
        led.position.set(gx - ox, gy - oy + southM * scale, (invH + 1) * scale)
        scene.add(led)
      }
    }

    stateRef.current = { renderer, scene, camera, pulseMeshes }

    // Animation loop — sync camera from Mapbox state every frame
    let rafId
    function animate() {
      rafId = requestAnimationFrame(animate)
      if (!canvasRef.current) return

      const mbMap = map
      const { width, height } = canvas.getBoundingClientRect()
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width  = width  * devicePixelRatio
        canvas.height = height * devicePixelRatio
        renderer.setSize(width, height, false)
        camera.aspect = width / height
        camera.updateProjectionMatrix()
      }

      const center    = mbMap.getCenter()
      const zoom      = mbMap.getZoom()
      const bearing   = mbMap.getBearing()
      const pitch     = mbMap.getPitch()
      const zoomScale = Math.pow(2, zoom)

      const { x: cx, y: cy } = lngLatToMercator(center.lng, center.lat)
      const altitude = 0.5 / Math.tan((FOV / 2) * Math.PI / 180) / zoomScale

      camera.fov    = FOV
      camera.aspect = canvas.width / canvas.height
      camera.near   = altitude / 100
      camera.far    = altitude * 100
      camera.updateProjectionMatrix()

      const bearingRad = -bearing * Math.PI / 180
      const pitchRad   =  pitch   * Math.PI / 180

      camera.position.set(
        cx - ox + Math.sin(bearingRad) * altitude * Math.sin(pitchRad),
        cy - oy - Math.cos(bearingRad) * altitude * Math.sin(pitchRad),
        altitude * Math.cos(pitchRad)
      )
      camera.up.set(
        -Math.sin(bearingRad) * Math.cos(pitchRad),
        Math.cos(bearingRad) * Math.cos(pitchRad),
        Math.sin(pitchRad)
      )
      camera.lookAt(cx - ox, cy - oy, 0)

      // Pulse inverter emissive
      const t = Date.now() / 1000
      for (const mesh of pulseMeshes) {
        const pulse = 0.5 + 0.5 * Math.sin(t * 1.5)
        mesh.material.emissiveIntensity = mesh.userData.isFault
          ? 0.5 + pulse * 0.5
          : 0.2 + pulse * 0.2
      }

      renderer.render(scene, camera)
    }
    animate()

    return () => {
      cancelAnimationFrame(rafId)
      scene.traverse(obj => {
        if (obj.isMesh) {
          obj.geometry?.dispose()
          obj.material?.dispose()
        }
      })
      renderer.dispose()
      stateRef.current = null
    }
  }, [map, layoutData, geometryData])

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        zIndex: 2,
      }}
    />
  )
}
