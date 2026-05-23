import { useMemo, useEffect, useState } from 'react';
import DeckGL from '@deck.gl/react';
import Map from 'react-map-gl/mapbox';
import { ScatterplotLayer, TextLayer, PathLayer, PolygonLayer } from '@deck.gl/layers';
import { PathStyleExtension } from '@deck.gl/extensions';
import 'mapbox-gl/dist/mapbox-gl.css';

const INITIAL_VIEW = {
  longitude: 1.2132,
  latitude: 52.5626,
  zoom: 15,
  pitch: 55,
  bearing: -20,
  transitionDuration: 1000,
};

const STATUS_COLOURS = {
  normal:   [16, 185, 129],
  degraded: [246, 173, 85],
  offline:  [239, 68, 68],
  unknown:  [148, 163, 184],
};

function getColour(status) {
  return STATUS_COLOURS[status] ?? STATUS_COLOURS.unknown;
}

const GROUP_ORDER = ['MQA11', 'MQA21', 'MQA22', 'MQA23'];

function buildZonePolygon(centreLat, centreLon, widthM, heightM) {
  const latPerM = 1 / 111320;
  const lonPerM = 1 / (111320 * Math.cos(centreLat * Math.PI / 180));
  const hw = widthM / 2;
  const hh = heightM / 2;
  return [
    [centreLon - hw * lonPerM, centreLat - hh * latPerM],
    [centreLon + hw * lonPerM, centreLat - hh * latPerM],
    [centreLon + hw * lonPerM, centreLat + hh * latPerM],
    [centreLon - hw * lonPerM, centreLat + hh * latPerM],
  ];
}

export default function SiteMap({ layoutData, onGroupClick }) {
  const [animTick, setAnimTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setAnimTick(t => t + 1), 50);
    return () => clearInterval(id);
  }, []);

  const groups = layoutData?.inverter_groups ?? [];

  const layers = useMemo(() => {
    if (!groups.length) return [];

    // Layer 0 — 3D panel zones (extruded rectangles, rendered beneath markers)
    const panelZones = new PolygonLayer({
      id: 'panel-zones',
      data: groups.map(g => ({
        ...g,
        polygon: buildZonePolygon(g.centre_lat, g.centre_lon, 200, 150),
      })),
      getPolygon: d => d.polygon,
      getFillColor: d => {
        const base = STATUS_COLOURS[d.status] ?? STATUS_COLOURS.unknown;
        return [...base, 60];
      },
      getLineColor: d => {
        const base = STATUS_COLOURS[d.status] ?? STATUS_COLOURS.unknown;
        return [...base, 180];
      },
      getElevation: 4,
      extruded: true,
      wireframe: true,
      lineWidthMinPixels: 1,
      pickable: false,
    });

    // Layer 1 — outer glow
    const glowOuter = new ScatterplotLayer({
      id: 'glow-outer',
      data: groups,
      getPosition: d => [d.centre_lon, d.centre_lat],
      getRadius: d => 90 + 20 * Math.sin(animTick / 8 + GROUP_ORDER.indexOf(d.id)),
      getFillColor: d => [...getColour(d.status), 30],
      stroked: false,
      radiusUnits: 'meters',
    });

    // Layer 2 — mid glow
    const glowMid = new ScatterplotLayer({
      id: 'glow-mid',
      data: groups,
      getPosition: d => [d.centre_lon, d.centre_lat],
      getRadius: d => 60 + 10 * Math.sin(animTick / 8 + GROUP_ORDER.indexOf(d.id)),
      getFillColor: d => [...getColour(d.status), 60],
      stroked: false,
      radiusUnits: 'meters',
    });

    // Layer 3 — core marker
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

    // Layer 4 — energy flow lines
    const sortedGroups = GROUP_ORDER
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

    // Layer 5 — labels
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

    return [panelZones, glowOuter, glowMid, energyFlow, core, labels].filter(Boolean);
  }, [groups, animTick, onGroupClick]);

  return (
    <DeckGL
      initialViewState={INITIAL_VIEW}
      controller={true}
      layers={layers}
      style={{ position: 'absolute', inset: 0 }}
    >
      <Map
        mapboxAccessToken={import.meta.env.VITE_MAPBOX_TOKEN}
        mapStyle="mapbox://styles/mapbox/satellite-streets-v12"
      />
    </DeckGL>
  );
}
