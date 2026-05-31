import { useMemo, useEffect, useState, useCallback } from 'react';
import DeckGL from '@deck.gl/react';
import Map from 'react-map-gl/mapbox';
import { ScatterplotLayer, TextLayer, PathLayer } from '@deck.gl/layers';
import { PathStyleExtension } from '@deck.gl/extensions';
import 'mapbox-gl/dist/mapbox-gl.css';
import { getGeometry } from '../../api/sites.js';
function buildTablePolygon(lon, lat, tableW, tableD, azimuthDeg) {
  const metersPerDegLat = 111320
  const metersPerDegLon = 111320 * Math.cos(lat * Math.PI / 180)
  const halfW = tableW / 2
  const halfD = tableD / 2
  const az = azimuthDeg * Math.PI / 180
  const cosA = Math.cos(az), sinA = Math.sin(az)
  const corners = [[-halfW,-halfD],[halfW,-halfD],[halfW,halfD],[-halfW,halfD],[-halfW,-halfD]]
  return corners.map(([x, y]) => [
    lon + (x * cosA - y * sinA) / metersPerDegLon,
    lat + (x * sinA + y * cosA) / metersPerDegLat,
  ])
}

const STATUS_COLOURS = {
  normal:   [16, 185, 129],
  degraded: [246, 173, 85],
  offline:  [239, 68, 68],
  unknown:  [148, 163, 184],
};

function getColour(status) {
  return STATUS_COLOURS[status] ?? STATUS_COLOURS.unknown;
}

export default function SiteMap({ layoutData, onGroupClick }) {
  const [animTick, setAnimTick] = useState(0);
  const [geometry, setGeometry] = useState(null);
  const [mbMap, setMbMap] = useState(null);
  const handleMapLoad = useCallback(e => setMbMap(e.target), []);
  const [viewState, setViewState] = useState(() => ({
    longitude: layoutData?.centre_lon ?? 0,
    latitude:  layoutData?.centre_lat ?? 0,
    zoom: 15,
    pitch: 45,
    bearing: -20,
    transitionDuration: 1000,
  }));

  useEffect(() => {
    const id = setInterval(() => setAnimTick(t => t + 1), 50);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const siteId = layoutData?.site_id;
    if (!siteId) return;
    getGeometry(siteId, 300).then(setGeometry).catch(() => {});
  }, [layoutData?.site_id]);

  useEffect(() => {
    if (!mbMap || !geometry || !layoutData) return

    const tableW  = geometry.table_width_m            // 54.672m E-W
    const moduleH = geometry.module_height_m          // 1.134m
    const tableD  = moduleH * 3                        // ~3.4m N-S
    const az      = geometry.azimuth_deg ?? layoutData.azimuth_deg ?? 0

    // Visible-but-reasonable extrusion height. Real panel top edge is ~1.6m,
    // which is invisible at site zoom, so we exaggerate to 3m for legibility.
    const EXT_HEIGHT = 3.0

    const statusByGroup = {}
    for (const g of layoutData.inverter_groups) statusByGroup[g.id] = g

    const statusColor = (s) =>
      s === 'offline'  ? '#1e293b' :
      s === 'degraded' ? '#eab308' :
      s === 'normal'   ? '#22c55e' : '#64748b'

    const features = []
    for (const group of geometry.groups) {
      const live   = statusByGroup[group.id]
      const status = live?.status ?? 'unknown'
      const color  = statusColor(status)
      for (const [lon, lat] of (group.panels ?? [])) {
        features.push({
          type: 'Feature',
          properties: { color, groupId: group.id, status },
          geometry: {
            type: 'Polygon',
            coordinates: [buildTablePolygon(lon, lat, tableW, tableD, az)],
          },
        })
      }
    }
    const geojson = { type: 'FeatureCollection', features }

    function addLayers() {
      try {
        if (mbMap.getLayer('solar-panels-3d')) mbMap.removeLayer('solar-panels-3d')
        if (mbMap.getSource('solar-panels'))   mbMap.removeSource('solar-panels')

        mbMap.addSource('solar-panels', { type: 'geojson', data: geojson })
        mbMap.addLayer({
          id: 'solar-panels-3d',
          type: 'fill-extrusion',
          source: 'solar-panels',
          paint: {
            'fill-extrusion-color': ['get', 'color'],
            'fill-extrusion-height': EXT_HEIGHT,
            'fill-extrusion-base': 0,
            'fill-extrusion-opacity': 0.9,
            'fill-extrusion-vertical-gradient': true,
          },
        })

        mbMap.setLight({
          anchor: 'viewport',
          color: '#ffffff',
          intensity: 0.45,
          position: [1.5, 210, 30],
        })
      } catch (e) {
        console.warn('solar panels layer error:', e)
      }
    }

    if (mbMap.isStyleLoaded()) addLayers()
    else mbMap.once('styledata', addLayers)

    return () => {
      try {
        if (mbMap.getLayer('solar-panels-3d')) mbMap.removeLayer('solar-panels-3d')
        if (mbMap.getSource('solar-panels'))   mbMap.removeSource('solar-panels')
      } catch (_) {}
    }
  }, [mbMap, geometry, layoutData])

  const groups = layoutData?.inverter_groups ?? [];

  // Flatten all panel positions with group status colour for rendering
  const panelPoints = useMemo(() => {
    if (!geometry?.groups) return [];
    const groupStatusMap = Object.fromEntries(groups.map(g => [g.id, g.status]));
    return geometry.groups.flatMap(g => {
      const status = groupStatusMap[g.id] ?? 'unknown';
      const colour = STATUS_COLOURS[status] ?? STATUS_COLOURS.unknown;
      return g.panels.map(([lon, lat]) => ({ position: [lon, lat], colour }));
    });
  }, [geometry, groups]);

  const layers = useMemo(() => {
    if (!groups.length) return [];

    // Layer 0 — individual panel dots (zoom-gated, rendered beneath everything)
    const showPanels = viewState.zoom > 13.5;
    const panelLayer = showPanels && !mbMap && panelPoints.length > 0
      ? new ScatterplotLayer({
          id: 'panels',
          data: panelPoints,
          getPosition: d => d.position,
          getFillColor: [45, 85, 130, 220],
          getLineColor: [100, 150, 200, 150],
          getRadius: 1.5,
          radiusMinPixels: 1.5,
          radiusMaxPixels: 4,
          radiusUnits: 'meters',
          stroked: false,
          pickable: false,
        })
      : null;

    const groupOrder = groups.map(g => g.id);

    // Layer 1 — outer glow
    const glowOuter = new ScatterplotLayer({
      id: 'glow-outer',
      data: groups,
      getPosition: d => [d.centre_lon, d.centre_lat],
      getRadius: d => 90 + 20 * Math.sin(animTick / 8 + groupOrder.indexOf(d.id)),
      getFillColor: d => [...getColour(d.status), 30],
      stroked: false,
      radiusUnits: 'meters',
    });

    // Layer 3 — mid glow
    const glowMid = new ScatterplotLayer({
      id: 'glow-mid',
      data: groups,
      getPosition: d => [d.centre_lon, d.centre_lat],
      getRadius: d => 60 + 10 * Math.sin(animTick / 8 + groupOrder.indexOf(d.id)),
      getFillColor: d => [...getColour(d.status), 60],
      stroked: false,
      radiusUnits: 'meters',
    });

    // Layer 4 — core marker
    const core = new ScatterplotLayer({
      id: 'core',
      data: groups,
      getPosition: d => [d.centre_lon, d.centre_lat],
      getRadius: 40,
      getFillColor: d => [...getColour(d.status), 220],
      stroked: true,
      getLineColor: [255, 255, 255, 180],
      lineWidthMinPixels: 2,
      radiusUnits: 'meters',
      pickable: true,
      onClick: ({ object }) => object && onGroupClick?.(object),
    });

    // Layer 5 — energy flow lines
    const sortedGroups = groupOrder
      .map(id => groups.find(g => g.id === id))
      .filter(Boolean);

    let energyFlow = null;
    if (sortedGroups.length >= 2) {
      const flowPath = [
        ...sortedGroups.map(g => [g.centre_lon, g.centre_lat]),
        [sortedGroups[0].centre_lon, sortedGroups[0].centre_lat],
      ];
      energyFlow = new PathLayer({
        id: 'energy-flow',
        data: [{ path: flowPath }],
        getPath: d => d.path,
        getColor: [251, 191, 36, 180],
        getWidth: 3,
        widthUnits: 'pixels',
        getDashArray: [8, 4],
        dashJustified: true,
        dashGapPickable: false,
        extensions: [new PathStyleExtension({ dash: true })],
        currentTime: animTick,
      });
    }

    // Layer 6 — labels
    const labels = new TextLayer({
      id: 'labels',
      data: groups,
      getPosition: d => [d.centre_lon, d.centre_lat, 50],
      getText: d => `${d.id}\n${d.active_inverters}/${d.inverter_count}`,
      getSize: 13,
      getColor: [255, 255, 255, 230],
      getBackgroundColor: [15, 22, 41, 180],
      background: true,
      backgroundPadding: [6, 4],
      getTextAnchor: 'middle',
      getAlignmentBaseline: 'bottom',
      fontFamily: 'monospace',
      multiline: true,
    });

    return [panelLayer, glowOuter, glowMid, energyFlow, core, labels].filter(Boolean);
  }, [groups, animTick, onGroupClick, panelPoints, viewState.zoom]);

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <DeckGL
        viewState={viewState}
        onViewStateChange={({ viewState: vs }) => setViewState(vs)}
        controller={true}
        layers={layers}
        style={{ position: 'absolute', inset: 0 }}
      >
        <Map
          onLoad={handleMapLoad}
          mapboxAccessToken={import.meta.env.VITE_MAPBOX_TOKEN}
          mapStyle="mapbox://styles/mapbox/satellite-streets-v12"
        />
      </DeckGL>
    </div>
  );
}
