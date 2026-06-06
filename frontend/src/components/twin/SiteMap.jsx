import { useMemo, useEffect, useState, useCallback } from 'react';
import DeckGL from '@deck.gl/react';
import Map from 'react-map-gl/mapbox';
import { ScatterplotLayer, TextLayer, PathLayer } from '@deck.gl/layers';
import { PathStyleExtension } from '@deck.gl/extensions';
import { SimpleMeshLayer } from '@deck.gl/mesh-layers';
import 'mapbox-gl/dist/mapbox-gl.css';
import { getGeometry } from '../../api/sites.js';
function createPanelTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = 1024; canvas.height = 128;
  const ctx = canvas.getContext('2d');
  const cols = 24, rows = 3;
  const cW = 1024 / cols, cH = 128 / rows;
  ctx.fillStyle = '#0e1a33';
  ctx.fillRect(0, 0, 1024, 128);
  for (let col = 0; col < cols; col++) {
    for (let row = 0; row < rows; row++) {
      const x = col * cW, y = row * cH;
      ctx.fillStyle = '#152240';
      ctx.fillRect(x + 2, y + 2, cW - 4, cH - 4);
      ctx.strokeStyle = 'rgba(100,140,210,0.13)';
      ctx.lineWidth = 0.5;
      for (let ci = 1; ci < 4; ci++) {
        ctx.beginPath(); ctx.moveTo(x + ci*cW/4, y+2);
        ctx.lineTo(x + ci*cW/4, y+cH-2); ctx.stroke();
      }
      for (let ri = 1; ri < 6; ri++) {
        ctx.beginPath(); ctx.moveTo(x+2, y + ri*cH/6);
        ctx.lineTo(x+cW-2, y + ri*cH/6); ctx.stroke();
      }
      ctx.strokeStyle = 'rgba(190,215,255,0.28)';
      ctx.lineWidth = 1;
      for (let b = 1; b < 3; b++) {
        ctx.beginPath(); ctx.moveTo(x + b*cW/3, y+2);
        ctx.lineTo(x + b*cW/3, y+cH-2); ctx.stroke();
      }
      ctx.strokeStyle = 'rgba(160,190,230,0.55)';
      ctx.lineWidth = 2;
      ctx.strokeRect(x+1, y+1, cW-2, cH-2);
    }
  }
  const grad = ctx.createLinearGradient(0, 0, 1024, 128);
  grad.addColorStop(0,    'rgba(255,255,255,0.06)');
  grad.addColorStop(0.25, 'rgba(255,255,255,0.01)');
  grad.addColorStop(0.5,  'rgba(255,255,255,0.04)');
  grad.addColorStop(0.75, 'rgba(255,255,255,0.00)');
  grad.addColorStop(1,    'rgba(255,255,255,0.05)');
  ctx.fillStyle = grad; ctx.fillRect(0, 0, 1024, 128);
  return canvas;
}

function buildPanelMesh(tableW, tableD) {
  const tilt = 15 * Math.PI / 180;
  const h    = tableD * Math.tan(tilt);
  const W = tableW, D = tableD;
  const positions = new Float32Array([
    -W/2, -D/2, h,    // SW — north edge, elevated
     W/2, -D/2, h,    // SE — north edge, elevated
     W/2,  D/2, 0,    // NE — south edge, ground
    -W/2,  D/2, 0,    // NW — south edge, ground
  ]);
  // Normal points south-and-upward (correct for south-facing UK panels)
  const normals = new Float32Array([
    0, Math.sin(tilt), Math.cos(tilt),
    0, Math.sin(tilt), Math.cos(tilt),
    0, Math.sin(tilt), Math.cos(tilt),
    0, Math.sin(tilt), Math.cos(tilt),
  ]);
  const indices = new Uint16Array([0,1,2, 0,2,3, 0,2,1, 0,3,2]);
  return {
    topology: 'triangle-list',
    attributes: {
      POSITION:   { value: positions, size: 3 },
      NORMAL:     { value: normals,   size: 3 },
      TEXCOORD_0: { value: new Float32Array([0,0, 1,0, 1,1, 0,1]), size: 2 },
    },
    indices: { value: indices },
  };
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
  const [selectedTable, setSelectedTable] = useState(null);
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

  const tableW  = geometry?.table_width_m ?? 54.672;
  const tableD  = (geometry?.module_height_m ?? 1.134) * 3;
  const rowBearing = geometry?.row_bearing_deg ?? 174.47;
  // azimuth_deg is the panel physics azimuth — never the row bearing
  const yawDeg = (rowBearing + 360) % 360;

  const panelMesh = useMemo(() => buildPanelMesh(tableW, tableD), [tableW, tableD]);
  const panelTexture = useMemo(() => createPanelTexture(), []);

  const tableData = useMemo(() => {
    if (!geometry?.groups) return [];
    return geometry.groups.flatMap(g =>
      (g.panels ?? []).map(([lon, lat]) => ({ lon, lat, groupId: g.id }))
    );
  }, [geometry]);

  const groups = layoutData?.inverter_groups ?? [];

  const GROUP_COLORS = {
    MQA11: [30, 60, 140],
    MQA21: [26, 54, 128],
    MQA22: [34, 68, 152],
    MQA23: [28, 58, 136],
  };

  const solarPanelLayer = useMemo(() => new SimpleMeshLayer({
    id: 'solar-panels',
    data: tableData,
    mesh: panelMesh,
    getPosition: d => [d.lon, d.lat, 1],
    getOrientation: () => [0, yawDeg, 0],
    texture: panelTexture,
    getColor: d => {
      const status = groups?.find(g => g.id === d.groupId)?.status;
      if (selectedTable && d.groupId !== selectedTable.groupId)
        return [80, 90, 110, 200];
      return status === 'offline'  ? [50,  55,  80, 255] :
             status === 'degraded' ? [200, 165,  60, 255] :
                                     [230, 240, 255, 255];
    },
    updateTriggers: { getColor: [groups, selectedTable] },
    material: {
      ambient:       0.55,
      diffuse:       0.65,
      shininess:     90,
      specularColor: [160, 190, 255],
    },
    pickable: true,
    onClick: info => {
      if (info.object) setSelectedTable(info.object);
      else setSelectedTable(null);
    },
    autoHighlight: true,
    highlightColor: [255, 200, 60, 220],
  }), [tableData, panelMesh, yawDeg, selectedTable, panelTexture, groups]);

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
      getRadius: d => 36 + 8 * Math.sin(animTick / 8 + groupOrder.indexOf(d.id)),
      getFillColor: d => {
        const c = d.status === 'offline'  ? [180, 30,  30]  :
                  d.status === 'degraded' ? [220, 100, 30]  : [245, 166, 35];
        return [...c, 28];
      },
      stroked: false,
      radiusUnits: 'meters',
    });

    // Layer 3 — mid glow
    const glowMid = new ScatterplotLayer({
      id: 'glow-mid',
      data: groups,
      getPosition: d => [d.centre_lon, d.centre_lat],
      getRadius: d => 22 + 5 * Math.sin(animTick / 8 + groupOrder.indexOf(d.id)),
      getFillColor: d => {
        const c = d.status === 'offline'  ? [180, 30,  30]  :
                  d.status === 'degraded' ? [220, 100, 30]  : [245, 166, 35];
        return [...c, 18];
      },
      stroked: false,
      radiusUnits: 'meters',
    });

    // Layer 4 — core marker
    const core = new ScatterplotLayer({
      id: 'core',
      data: groups,
      getPosition: d => [d.centre_lon, d.centre_lat],
      getRadius: 14,
      getFillColor: d => d.status === 'offline'  ? [180, 30,  30, 210] :
                         d.status === 'degraded' ? [220, 100, 30, 220] :
                                                   [245, 166, 35, 220],
      stroked: true,
      getLineColor: [10, 14, 26, 200],
      lineWidthMinPixels: 1.5,
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

    return [solarPanelLayer, panelLayer, glowOuter, glowMid, energyFlow, core, labels].filter(Boolean);
  }, [groups, animTick, onGroupClick, panelPoints, viewState.zoom, solarPanelLayer]);

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
      {selectedTable && (() => {
        const grp = groups?.find(g => g.id === selectedTable.groupId) ?? {};
        const statusColor = {
          normal: '#22c55e', degraded: '#eab308', offline: '#ef4444'
        }[grp.status] ?? '#64748b';
        return (
          <div style={{
            position:'absolute', bottom:80, right:24,
            background:'rgba(10,14,26,0.95)',
            border:'1px solid #2D3F55', borderRadius:12,
            padding:'16px 20px', color:'#fff', minWidth:240,
            backdropFilter:'blur(8px)', zIndex:10,
          }}>
            {/* header */}
            <div style={{display:'flex',justifyContent:'space-between',
                         alignItems:'center',marginBottom:12}}>
              <span style={{fontWeight:700,fontSize:15,color:'#f5a623'}}>
                {selectedTable.groupId}
              </span>
              <div style={{display:'flex',alignItems:'center',gap:6}}>
                <div style={{width:8,height:8,borderRadius:'50%',
                             background:statusColor}}/>
                <span style={{fontSize:12,color:statusColor,textTransform:'capitalize'}}>
                  {grp.status ?? 'unknown'}
                </span>
              </div>
            </div>
            {/* metrics */}
            <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:8,
                         marginBottom:14}}>
              <div style={{background:'#0F1629',borderRadius:8,padding:'8px 10px'}}>
                <div style={{fontSize:10,color:'#64748b',marginBottom:2}}>
                  INVERTERS
                </div>
                <div style={{fontSize:18,fontWeight:700}}>
                  {grp.active_inverters ?? '—'}
                  <span style={{fontSize:12,color:'#64748b',fontWeight:400}}>
                    /{grp.inverter_count ?? '—'}
                  </span>
                </div>
              </div>
              <div style={{background:'#0F1629',borderRadius:8,padding:'8px 10px'}}>
                <div style={{fontSize:10,color:'#64748b',marginBottom:2}}>
                  TABLES
                </div>
                <div style={{fontSize:18,fontWeight:700}}>
                  {groups?.find(g=>g.id===selectedTable.groupId)
                    ? tableData.filter(t=>t.groupId===selectedTable.groupId).length
                    : '—'}
                </div>
              </div>
            </div>
            <div style={{fontSize:11,color:'#475569',marginBottom:12}}>
              {selectedTable.lat?.toFixed(5)}°N,&nbsp;
              {selectedTable.lon?.toFixed(5)}°E
            </div>
            {/* actions */}
            <div style={{display:'flex',gap:8}}>
              <button
                onClick={() => setSelectedTable(null)}
                style={{flex:1,padding:'6px 0',borderRadius:6,border:'1px solid #2D3F55',
                        background:'transparent',color:'#94a3b8',cursor:'pointer',
                        fontSize:12}}>
                Dismiss
              </button>
              <button
                onClick={() => {
                  setSelectedTable(null);
                  window.location.href =
                    `/twin/analytics?group=${selectedTable.groupId}`;
                }}
                style={{flex:2,padding:'6px 0',borderRadius:6,border:'none',
                        background:'#f5a623',color:'#0a0e1a',cursor:'pointer',
                        fontWeight:600,fontSize:12}}>
                View Analytics →
              </button>
            </div>
          </div>
        );
      })()}
    </div>
  );
}
