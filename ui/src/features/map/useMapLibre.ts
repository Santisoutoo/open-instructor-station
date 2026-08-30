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
  NavigationControl,
  type LngLatBoundsLike,
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

export interface MapLibreOptions {
  /**
   * Open fitted to this extent instead of `MAP_HOME`. Read once, when the map is created —
   * a later change does not move a map the instructor may already be panning.
   */
  readonly bounds?: LngLatBoundsLike | undefined;
  /** Pixels kept clear inside the frame when fitting `bounds`. */
  readonly fitPadding?: number;
  /** Never zoom closer than this when fitting `bounds` (one stand is not a whole airport). */
  readonly fitMaxZoom?: number;
  /** Add the +/− buttons. The Instructor Map has its own chrome; the airport diagram does not. */
  readonly navigation?: boolean;
  /** Fold the OSM attribution behind an "i" — the diagram is too small for the full line. */
  readonly compactAttribution?: boolean;
}

export function useMapLibre(options: MapLibreOptions = {}): MapLibreHandle {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  // The options only matter at construction: a snapshot keeps the effect's dependency
  // list empty, so a re-render with a new options object never tears the map down.
  const [initialOptions] = useState(options);

  useEffect(() => {
    const container = containerRef.current;
    if (container === null) {
      return;
    }
    const { bounds, fitPadding, fitMaxZoom, navigation, compactAttribution } =
      initialOptions;
    const instance = new MaplibreMapCtor({
      container,
      style: OSM_STYLE,
      ...(bounds === undefined
        ? { center: [MAP_HOME.lon, MAP_HOME.lat], zoom: MAP_HOME_ZOOM }
        : {
            bounds,
            fitBoundsOptions: {
              ...(fitPadding === undefined ? {} : { padding: fitPadding }),
              ...(fitMaxZoom === undefined ? {} : { maxZoom: fitMaxZoom }),
            },
          }),
      ...(compactAttribution === true ? { attributionControl: { compact: true } } : {}),
    });
    if (navigation === true) {
      instance.addControl(new NavigationControl({ showCompass: false }), 'top-right');
    }
    // Async by nature, so this is not a synchronous set-state-in-effect. Everything
    // MapLibre does after the constructor rides on requestAnimationFrame, so in a hidden
    // tab `load` simply waits until the tab is shown — do not "fix" a map that stays
    // `null` under an occluded dev window.
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
    // `initialOptions` is state that never changes, so this still runs exactly once.
  }, [initialOptions]);

  return { containerRef, map };
}
