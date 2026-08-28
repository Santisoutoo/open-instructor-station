/**
 * The Start-at popover's map content: the airport's real pavement footprint, one DOM
 * `Marker` per runway threshold, and one per parking stand.
 *
 * Modelled on `features/map/useAircraftMarker.ts`'s **element**-`Marker` pattern — a real
 * `<button>` per marker, so every marker gets a DOM node, keyboard focus and a 44px hit box,
 * exactly what CLAUDE.md's tablet-first rule and this screen's existing accessibility
 * pattern (the deleted `AirportDiagram.tsx`'s `aria-pressed`/`aria-label="Stand A1"`
 * buttons) require. Unlike that hook, this one carries **no** `store.subscribe` — it draws
 * static navdata that only changes when the airport or the selection changes, never a live
 * telemetry feed.
 *
 * Every marker's click calls the exact same `onSelectRunway`/`onSelectStand` callback the
 * sidebar list and the stands list already call (`StartAtPopover.tsx`) — that is what makes
 * a map click and a list click take the identical code path, by construction rather than by
 * convention.
 */

import type { GeoJSONSource, Map as MapLibreMap } from 'maplibre-gl';
import { Marker } from 'maplibre-gl';
import type { FeatureCollection, Polygon } from 'geojson';
import { useEffect, useRef } from 'react';
import type { ParkingStand, Runway } from '../../api/models';
import { primaryRunwayEnds, runwayFeature, type RunwayProperties } from '../map/overlays';

const PAVEMENT_SOURCE_ID = 'pos-startat-pavement';
const PAVEMENT_LAYER_ID = 'pos-startat-pavement';

const SELECTED_CLASS = 'pos-startat-marker--selected';

interface TrackedMarker {
  readonly marker: Marker;
  readonly element: HTMLButtonElement;
}

function pavementCollection(runways: readonly Runway[]): FeatureCollection<Polygon, RunwayProperties> {
  return {
    type: 'FeatureCollection',
    features: primaryRunwayEnds(runways).map(runwayFeature),
  };
}

function markerButton(className: string): HTMLButtonElement {
  const element = document.createElement('button');
  element.type = 'button';
  element.className = `pos-startat-marker ${className}`;
  return element;
}

/** A plain `[[minLon, minLat], [maxLon, maxLat]]` box — `fitBounds` accepts this directly. */
function boundsOf(
  points: ReadonlyArray<{ readonly latitude: number; readonly longitude: number }>,
): [[number, number], [number, number]] | null {
  if (points.length === 0) {
    return null;
  }
  const lats = points.map((point) => point.latitude);
  const lons = points.map((point) => point.longitude);
  return [
    [Math.min(...lons), Math.min(...lats)],
    [Math.max(...lons), Math.max(...lats)],
  ];
}

export function useStartAtMarkers(
  map: MapLibreMap | null,
  runways: readonly Runway[],
  stands: readonly ParkingStand[],
  selectedRunway: string | null,
  selectedStand: string | null,
  onSelectRunway: (ident: string) => void,
  onSelectStand: (name: string) => void,
): void {
  const runwayMarkers = useRef<Map<string, TrackedMarker>>(new Map());
  const standMarkers = useRef<Map<string, TrackedMarker>>(new Map());
  // Which map instance the pavement source/layer were added to — `undefined` before the
  // first add. Guards against re-adding the source on every `runways` change while still
  // adding it fresh after a map is torn down and rebuilt (e.g. a popover re-open).
  const pavementMap = useRef<MapLibreMap | null>(null);

  // 1. Pavement layer: the airport's real runway footprint, added once per map instance
  // and refreshed whenever the runway list changes.
  useEffect(() => {
    if (map === null) {
      return;
    }
    const data = pavementCollection(runways);
    if (pavementMap.current !== map) {
      map.addSource(PAVEMENT_SOURCE_ID, { type: 'geojson', data });
      map.addLayer({
        id: PAVEMENT_LAYER_ID,
        type: 'fill',
        source: PAVEMENT_SOURCE_ID,
        paint: { 'fill-color': '#546170', 'fill-opacity': 0.85 },
      });
      pavementMap.current = map;
    } else {
      (map.getSource(PAVEMENT_SOURCE_ID) as GeoJSONSource | undefined)?.setData(data);
    }
  }, [map, runways]);

  // 2. Marker build: one Marker per runway end and one per stand. Old markers are removed
  // before new ones are built — this must NOT run on a bare selection change, so
  // `selectedRunway`/`selectedStand` are deliberately not in the dependency list; the
  // initial pressed state below still reflects the selection current at build time.
  useEffect(() => {
    if (map === null) {
      return;
    }

    // Captured once per effect run — the same `Map` instance the ref always holds, so this
    // is purely to give the cleanup below a value it does not have to re-read from the ref.
    const runwayMap = runwayMarkers.current;
    const standMap = standMarkers.current;

    function clear(tracked: Map<string, TrackedMarker>) {
      for (const entry of tracked.values()) {
        entry.marker.remove();
      }
      tracked.clear();
    }
    clear(runwayMap);
    clear(standMap);

    for (const runway of runways) {
      const element = markerButton('pos-startat-marker--runway');
      element.textContent = runway.ils == null ? runway.ident : `${runway.ident}·ILS`;
      const selected = runway.ident === selectedRunway;
      element.classList.toggle(SELECTED_CLASS, selected);
      element.setAttribute('aria-pressed', String(selected));
      element.addEventListener('click', () => {
        onSelectRunway(runway.ident);
      });
      const marker = new Marker({ element })
        .setLngLat([runway.threshold.longitude, runway.threshold.latitude])
        .addTo(map);
      runwayMap.set(runway.ident, { marker, element });
    }

    for (const stand of stands) {
      const element = markerButton('pos-startat-marker--stand');
      element.setAttribute('aria-label', `Stand ${stand.name}`);
      const selected = stand.name === selectedStand;
      element.classList.toggle(SELECTED_CLASS, selected);
      element.setAttribute('aria-pressed', String(selected));
      element.addEventListener('click', () => {
        onSelectStand(stand.name);
      });
      const marker = new Marker({ element })
        .setLngLat([stand.position.longitude, stand.position.latitude])
        .addTo(map);
      standMap.set(stand.name, { marker, element });
    }

    return () => {
      clear(runwayMap);
      clear(standMap);
    };
    // `selectedRunway`/`selectedStand`/`onSelectRunway`/`onSelectStand` are intentionally
    // excluded: they are read via closure at build time, which is what the comment above the
    // effect explains — rebuilding on every selection change (or on the callbacks' identity,
    // which is fresh on nearly every render, see `StartAtPopover.tsx`) would flash/refit the
    // map on every click, which effect §3 exists specifically to avoid.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, runways, stands]);

  // 3. Selection restyle: flips the existing elements' class/aria-pressed without touching
  // the marker set at all.
  useEffect(() => {
    for (const [ident, tracked] of runwayMarkers.current) {
      const selected = ident === selectedRunway;
      tracked.element.classList.toggle(SELECTED_CLASS, selected);
      tracked.element.setAttribute('aria-pressed', String(selected));
    }
    for (const [name, tracked] of standMarkers.current) {
      const selected = name === selectedStand;
      tracked.element.classList.toggle(SELECTED_CLASS, selected);
      tracked.element.setAttribute('aria-pressed', String(selected));
    }
  }, [selectedRunway, selectedStand]);

  // 4. Fit to content: frames the airport's own runways and stands once when they arrive.
  // `animate: false` avoids a camera flourish every time the popover opens; a degenerate
  // (single-point) box is MapLibre's own concern, not this hook's.
  useEffect(() => {
    if (map === null) {
      return;
    }
    const bounds = boundsOf([
      ...runways.map((runway) => runway.threshold),
      ...stands.map((stand) => stand.position),
    ]);
    if (bounds === null) {
      return;
    }
    map.fitBounds(bounds, { padding: 40, animate: false, maxZoom: 17 });
  }, [map, runways, stands]);
}
