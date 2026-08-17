/**
 * The MapLibre instance's lifecycle, and nothing else.
 *
 * The map is imperative and lives here — never mirrored into Redux (see mapSlice's
 * header). The hook exposes it as `null` until the style has loaded, so every consumer
 * effect can gate on "the map is ready to take sources" with one null check. In jsdom
 * tests the stub's `load` never fires, the map stays `null`, and everything imperative
 * stays dormant by construction.
 */

import {
  Map as MaplibreMapCtor,
  type Map as MapLibreMap,
  type StyleSpecification,
} from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useEffect, useRef, useState, type RefObject } from 'react';
import { MAP_HOME, MAP_HOME_ZOOM } from './mock';

/**
 * Inline style: one OSM raster source, no external style JSON, no glyph server —
 * the app must work on a LAN with no internet beyond the tile cache (CLAUDE.md: map
 * tiles are OpenStreetMap / open sources only).
 */
const OSM_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 19,
      attribution: '© OpenStreetMap contributors',
    },
  },
  layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
};

export interface MapLibreHandle {
  /** Attach to the map's container div. */
  containerRef: RefObject<HTMLDivElement | null>;
  /** The live map once its style has loaded; `null` before that and after unmount. */
  map: MapLibreMap | null;
}

export function useMapLibre(): MapLibreHandle {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (container === null) {
      return;
    }
    const instance = new MaplibreMapCtor({
      container,
      style: OSM_STYLE,
      center: [MAP_HOME.lon, MAP_HOME.lat],
      zoom: MAP_HOME_ZOOM,
    });
    // Async by nature, so this is not a synchronous set-state-in-effect.
    instance.once('load', () => {
      setMap(instance);
    });

    // The panel is keepMounted: it resizes when its tab is shown again and when the
    // context drawer opens. jsdom has no ResizeObserver — the guard is for tests only.
    let observer: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(() => {
        instance.resize();
      });
      observer.observe(container);
    }

    return () => {
      observer?.disconnect();
      // Cleared before remove() so no consumer effect can touch a dead map.
      setMap(null);
      instance.remove();
    };
  }, []);

  return { containerRef, map };
}
