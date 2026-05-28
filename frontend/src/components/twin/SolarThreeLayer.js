import * as THREE from 'three'
import mapboxgl from 'mapbox-gl'

function lngLatToWorld(lng, lat, altitude = 0) {
  const mc = mapboxgl.MercatorCoordinate.fromLngLat({ lng, lat }, altitude)
  return new THREE.Vector3(mc.x, mc.y, mc.z)
}

function meterInMercator(lng, lat) {
  const mc = mapboxgl.MercatorCoordinate.fromLngLat({ lng, lat }, 0)
  return mc.meterInMercatorCoordinateUnits()
}

function statusToColor(status, availPct) {
  if (status === 'offline') return new THREE.Color(0x1e293b)
  if (status === 'degraded') return new THREE.Color(0xca8a04)
  if (status === 'normal') return new THREE.Color(0x16a34a)
  // unknown — use availability if present
  if (availPct != null) {
    if (availPct >= 95) return new THREE.Color(0x16a34a)
    if (availPct >= 50) return new THREE.Color(0xca8a04)
    return new THREE.Color(0xdc2626)
  }
  return new THREE.Color(0x334155) // unknown/no data
}

export function createSolarLayer(layoutData, geometryData) {
  if (!layoutData?.inverter_groups?.length || !geometryData?.groups?.length) return null

  // ── All geometry from API — zero hardcoding ─────────────────────────────
  const tiltRad    = (geometryData.tilt_deg ?? layoutData.tilt_deg ?? 0) * Math.PI / 180
  const azimuthRad = (geometryData.azimuth_deg ?? layoutData.azimuth_deg ?? 0) * Math.PI / 180
  const moduleW    = geometryData.module_width_m   // panel width along slope
  const moduleH    = geometryData.module_height_m  // panel thickness
  const rowPitch   = geometryData.row_pitch_m

  // Site origin — use layout centre for Mercator reference point
  const originLng   = layoutData.centre_lon
  const originLat   = layoutData.centre_lat
  const originWorld = lngLatToWorld(originLng, originLat)
  const scale       = meterInMercator(originLng, originLat)

  // Per-group geometry lookup keyed by group id
  const geoByGroup = {}
  for (const g of geometryData.groups) {
    geoByGroup[g.id] = g
  }

  // Per-group status/availability lookup keyed by group id
  const statusByGroup = {}
  for (const g of layoutData.inverter_groups) {
    statusByGroup[g.id] = g
  }

  let scene, camera, renderer, _map
  const pulseMeshes = [] // inverter boxes to animate

  const layer = {
    id: 'solar-twin-3d',
    type: 'custom',
    renderingMode: '3d',

    onAdd(map, gl) {
      _map = map

      renderer = new THREE.WebGLRenderer({
        canvas: map.getCanvas(),
        context: gl,
        antialias: true,
        powerPreference: 'high-performance',
      })
      renderer.autoClear = false
      renderer.toneMapping = THREE.ACESFilmicToneMapping
      renderer.toneMappingExposure = 1.1
      renderer.shadowMap.enabled = false

      scene = new THREE.Scene()
      camera = new THREE.Camera()

      // Lighting — hemisphere (sky/ground bounce) + directional sun
      scene.add(new THREE.HemisphereLight(0x8ab4d4, 0x2d4a1e, 0.5))
      const sun = new THREE.DirectionalLight(0xfff4e0, 2.5)
      sun.position.set(0.5, -1.0, 1.0).normalize()
      sun.castShadow = true
      sun.shadow.mapSize.set(2048, 2048)
      scene.add(sun)

      for (const geoGroup of geometryData.groups) {
        const liveGroup = statusByGroup[geoGroup.id]
        if (!liveGroup) continue

        const groupWorld = lngLatToWorld(geoGroup.centre_lon, geoGroup.centre_lat)
        const dx = groupWorld.x - originWorld.x
        const dy = groupWorld.y - originWorld.y

        const zoneEW  = geoGroup.zone_ew_m
        const zoneNS  = geoGroup.zone_ns_m
        const numRows = Math.round(zoneNS / rowPitch)

        const color     = statusToColor(liveGroup.status, liveGroup.availability_pct)
        const isOffline = liveGroup.status === 'offline'
        const isFault   = liveGroup.status === 'degraded'

        // ── Panel rows — InstancedMesh (one draw call per group) ────────
        const panelGeo = new THREE.BoxGeometry(
          zoneEW  * scale,
          moduleW * scale,  // depth along slope
          moduleH * scale   // thickness
        )
        const panelMat = new THREE.MeshPhysicalMaterial({
          color,
          metalness: 0.05,
          roughness: 0.08,
          clearcoat: 1.0,
          clearcoatRoughness: 0.04,
          sheen: 0.3,
          sheenColor: new THREE.Color(0x1a3a5c),
        })
        const rowMesh = new THREE.InstancedMesh(panelGeo, panelMat, numRows)
        rowMesh.castShadow = true
        rowMesh.receiveShadow = true

        const dummy = new THREE.Object3D()
        for (let r = 0; r < numRows; r++) {
          const rowOffset = (r - (numRows - 1) / 2) * rowPitch * scale
          dummy.position.set(dx, dy + rowOffset, 1.5 * scale)
          dummy.rotation.set(tiltRad, azimuthRad, 0)
          dummy.updateMatrix()
          rowMesh.setMatrixAt(r, dummy.matrix)
        }
        rowMesh.instanceMatrix.needsUpdate = true
        scene.add(rowMesh)

        // ── Inverter station — sized from inverter_count ─────────────────
        const invCount = liveGroup.inverter_count ?? 1
        const invSize  = Math.max(5, invCount * 1.2) // metres
        const invGeo   = new THREE.BoxGeometry(
          invSize * scale,
          invSize * scale,
          (invSize * 0.5) * scale
        )
        const invMat = new THREE.MeshPhysicalMaterial({
          color:             isOffline ? 0x1e293b : (isFault ? 0x7f1d1d : 0x1a2f1a),
          metalness:         0.7,
          roughness:         0.35,
          emissive:          isOffline ? 0x000000 : (isFault ? 0x3f0000 : 0x051005),
          emissiveIntensity: isFault ? 0.8 : 0.4,
        })
        const invBox = new THREE.Mesh(invGeo, invMat)
        invBox.position.set(
          dx,
          dy + zoneNS * scale * 0.6,
          invSize * 0.25 * scale
        )
        invBox.castShadow = true
        invBox.userData = { isFault, isOffline }
        scene.add(invBox)
        if (!isOffline) pulseMeshes.push(invBox)

        // ── Combiner boxes — count derived from inverter_count ───────────
        const numCombiners = Math.max(1, Math.ceil(invCount / 4))
        for (let c = 0; c < numCombiners; c++) {
          const t  = (c + 0.5) / numCombiners
          const cx = dx + (t - 0.5) * zoneEW * scale
          const cbGeo = new THREE.BoxGeometry(2 * scale, 1.5 * scale, 1.8 * scale)
          const cbMat = new THREE.MeshStandardMaterial({
            color:             isOffline ? 0x1e293b : 0x374151,
            metalness:         0.6,
            roughness:         0.3,
            emissive:          isOffline ? 0x000000 : 0x0a0f0a,
            emissiveIntensity: 0.2,
          })
          const cb = new THREE.Mesh(cbGeo, cbMat)
          cb.position.set(cx, dy + zoneNS * scale * 0.52, 0.9 * scale)
          cb.castShadow = true
          scene.add(cb)
        }

        // ── Status LED point light ───────────────────────────────────────
        if (!isOffline) {
          const ledColor = isFault ? 0xff4444 : 0x22ff88
          const led = new THREE.PointLight(ledColor, 1.2, 60 * scale)
          led.position.set(dx, dy + zoneNS * scale * 0.6, invSize * 0.6 * scale)
          scene.add(led)
        }
      }
    },

    render(gl, matrix) {
      // Animate inverter box pulse
      const t = Date.now() / 1000
      for (const mesh of pulseMeshes) {
        const pulse = 0.5 + 0.5 * Math.sin(t * 1.5)
        mesh.material.emissiveIntensity = mesh.userData.isFault
          ? 0.5 + pulse * 0.5
          : 0.2 + pulse * 0.2
      }

      // Mapbox v3 passes the 16-element projection matrix as the second arg directly
      // (not nested under defaultProjectionData)
      const m = new THREE.Matrix4().fromArray(matrix)
      const rotX = new THREE.Matrix4().makeRotationAxis(
        new THREE.Vector3(1, 0, 0), Math.PI / 2
      )
      m.multiply(rotX)
      camera.projectionMatrix = m
      camera.projectionMatrixInverse.copy(m).invert()

      renderer.resetState()
      renderer.render(scene, camera)
      _map?.triggerRepaint()
    },

    onRemove() {
      scene?.traverse(obj => {
        if (obj.isMesh) {
          obj.geometry?.dispose()
          if (Array.isArray(obj.material)) {
            obj.material.forEach(mat => mat.dispose())
          } else {
            obj.material?.dispose()
          }
        }
      })
      scene?.clear()
      renderer?.dispose()
    },
  }

  return layer
}
