import { useEffect, useRef, useCallback } from 'react';
import mapboxgl from 'mapbox-gl';
import { Deck } from '@deck.gl/core';
import { ScatterplotLayer, TextLayer } from '@deck.gl/layers';
import { statusToRgb } from './InverterMarker.jsx';
import 'mapbox-gl/dist/mapbox-gl.css';

const BRACON_ASH = { lat: 52.5626, lon: 1.2132 };

const INITIAL_VIEW_STATE = {
  latitude: BRACON_ASH.lat,
  longitude: BRACON_ASH.lon,
  zoom: 15,
  pitch: 45,
  bearing: -17,
};

export default function SiteMap({ layoutData, onGroupClick }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const deckRef = useRef(null);
  const layersRef = useRef([]);
  const rafRef = useRef(null);

  // Build deck.gl layers from current data + animation tick
  const buildLayers = useCallback((groups, tick) => {
    if (!groups?.length) return [];

    const radiusScale = 1.0 + 0.15 * Math.sin(tick / 500);

    const scatter = new ScatterplotLayer({
      id: 'groups-scatter',
      data: groups,
      getPosition: d => [d.centre_lon, d.centre_lat, 0],
      getFillColor: d => [...statusToRgb(d.status), 200],
      getRadius: 40,
      radiusScale,
      pickable: true,
      onClick: ({ object }) => object && onGroupClick?.(object),
    });

    const text = new TextLayer({
      id: 'groups-text',
      data: groups,
      getPosition: d => [d.centre_lon, d.centre_lat, 5],
      getText: d => d.id,
      getSize: 13,
      getColor: [255, 255, 255, 230],
      getTextAnchor: 'middle',
      getAlignmentBaseline: 'bottom',
      fontWeight: 600,
      background: true,
      getBackgroundColor: [15, 22, 41, 180],
      backgroundPadding: [3, 1, 3, 1],
    });

    return [scatter, text];
  }, [onGroupClick]);

  // Initialise map + deck.gl on mount
  useEffect(() => {
    if (!containerRef.current) return;

    mapboxgl.accessToken = import.meta.env.VITE_MAPBOX_TOKEN ?? '';

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: 'mapbox://styles/mapbox/satellite-streets-v12',
      center: [BRACON_ASH.lon, BRACON_ASH.lat],
      zoom: INITIAL_VIEW_STATE.zoom,
      pitch: INITIAL_VIEW_STATE.pitch,
      bearing: INITIAL_VIEW_STATE.bearing,
      antialias: true,
    });
    mapRef.current = map;

    map.addControl(new mapboxgl.NavigationControl(), 'top-right');

    map.on('load', () => {
      // Add deck.gl as a Mapbox custom layer
      const deckCustomLayer = {
        id: 'deck-overlay',
        type: 'custom',
        renderingMode: '2d',

        onAdd(m, gl) {
          deckRef.current = new Deck({
            gl,
            initialViewState: INITIAL_VIEW_STATE,
            controller: false,
            layers: [],
            // Prevent deck.gl from creating its own canvas
            canvas: m.getCanvas(),
            width: m.getCanvas().width,
            height: m.getCanvas().height,
            useDevicePixels: true,
            _customRender: () => m.triggerRepaint(),
          });
        },

        render(gl, args) {
          if (!deckRef.current) return;

          const m = mapRef.current;
          if (!m) return;

          deckRef.current.setProps({
            viewState: {
              latitude: m.getCenter().lat,
              longitude: m.getCenter().lng,
              zoom: m.getZoom(),
              bearing: m.getBearing(),
              pitch: m.getPitch(),
              repeat: true,
            },
            layers: layersRef.current,
          });

          // Trigger deck to draw into mapbox's current WebGL state
          deckRef.current._drawLayers('custom-layer', { clearCanvas: false });
        },

        onRemove() {
          deckRef.current?.finalize();
          deckRef.current = null;
        },
      };

      map.addLayer(deckCustomLayer);
    });

    return () => {
      cancelAnimationFrame(rafRef.current);
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Animation loop — updates layers with pulsing radiusScale
  useEffect(() => {
    const groups = layoutData?.inverter_groups ?? [];

    function animate() {
      layersRef.current = buildLayers(groups, Date.now());
      mapRef.current?.triggerRepaint();
      rafRef.current = requestAnimationFrame(animate);
    }

    rafRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(rafRef.current);
  }, [layoutData, buildLayers]);

  return (
    <div ref={containerRef} className="w-full h-full rounded-xl overflow-hidden" />
  );
}
