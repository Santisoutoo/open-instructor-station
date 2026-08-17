/**
 * The GeoJSON overlays: mock airport, aircraft trail, measure segment, staged point.
 *
 * Sources and layers are added once when the map becomes ready; after that this hook
 * only pushes data into `setData` and flips `visibility` — the cheap paths. Nothing
 * here dispatches: it is a one-way projection of Redux state onto the canvas.
 */

import { type GeoJSONSource, type Map as MapLibreMap } from 'maplibre-gl';
import { useEffect } from 'react';
import { useAppSelector } from '../../store';
import { type LatLon } from './measure';
import { type MapLayerKey } from './mapSlice';
import { MOCK_AIRPORT } from './mock';
import type { FeatureCollection } from 'geojson';

/** Which style layers each left-edge toggle controls. */
const LAYER_BINDINGS: ReadonlyArray<[MapLayerKey, string]> = [
  ['runways', 'airport-runways'],
  ['ils', 'airport-ils'],
  ['navaids', 'airport-navaids'],
  ['trail', 'trail'],
];

/**
 * Canvas colours are literals — WebGL cannot read CSS custom properties. Amber is the
 * app accent and marks the two active-intent drawings (measure, staged point).
 */
const AMBER = '#e8a33d';

const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] };

function pointCollection(points: readonly LatLon[]): FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: points.map((point) => ({
      type: 'Feature',
      properties: {},
      geometry: { type: 'Point', coordinates: [point.lon, point.lat] },
    })),
  };
}

function lineCollection(points: readonly LatLon[]): FeatureCollection {
  if (points.length < 2) {
    return EMPTY;
  }
  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: {},
        geometry: {
          type: 'LineString',
          coordinates: points.map((point) => [point.lon, point.lat]),
        },
      },
    ],
  };
}

function setSourceData(map: MapLibreMap, id: string, data: FeatureCollection): void {
  const source = map.getSource(id) as GeoJSONSource | undefined;
  source?.setData(data);
}

export function useMapOverlays(map: MapLibreMap | null): void {
  const layers = useAppSelector((state) => state.map.layers);
  const trail = useAppSelector((state) => state.map.trail);
  const measureA = useAppSelector((state) => state.map.measureA);
  const measureB = useAppSelector((state) => state.map.measureB);
  const staged = useAppSelector((state) => state.map.staged);

  // Sources and layers, once per map instance. They die with `map.remove()`.
  useEffect(() => {
    if (map === null) {
      return;
    }
    map.addSource('airport-runways', { type: 'geojson', data: MOCK_AIRPORT.runways });
    map.addLayer({
      id: 'airport-runways',
      type: 'fill',
      source: 'airport-runways',
      paint: { 'fill-color': '#546170', 'fill-opacity': 0.85 },
    });
    map.addSource('airport-ils', { type: 'geojson', data: MOCK_AIRPORT.ils });
    map.addLayer({
      id: 'airport-ils',
      type: 'line',
      source: 'airport-ils',
      paint: { 'line-color': '#7d8da1', 'line-width': 1.5 },
    });
    map.addSource('airport-navaids', { type: 'geojson', data: MOCK_AIRPORT.navaids });
    map.addLayer({
      id: 'airport-navaids',
      type: 'circle',
      source: 'airport-navaids',
      paint: {
        'circle-radius': 4,
        'circle-color': '#3f7cb8',
        'circle-stroke-color': '#16140f',
        'circle-stroke-width': 1,
      },
    });
    map.addSource('trail', { type: 'geojson', data: EMPTY });
    map.addLayer({
      id: 'trail',
      type: 'line',
      source: 'trail',
      paint: { 'line-color': '#4a7fb5', 'line-width': 2, 'line-opacity': 0.8 },
    });
    map.addSource('measure-line', { type: 'geojson', data: EMPTY });
    map.addLayer({
      id: 'measure-line',
      type: 'line',
      source: 'measure-line',
      paint: { 'line-color': AMBER, 'line-width': 2, 'line-dasharray': [2, 2] },
    });
    map.addSource('measure-points', { type: 'geojson', data: EMPTY });
    map.addLayer({
      id: 'measure-points',
      type: 'circle',
      source: 'measure-points',
      paint: { 'circle-radius': 4, 'circle-color': AMBER },
    });
    map.addSource('staged', { type: 'geojson', data: EMPTY });
    map.addLayer({
      id: 'staged-point',
      type: 'circle',
      source: 'staged',
      paint: {
        'circle-radius': 6,
        'circle-color': AMBER,
        'circle-stroke-color': '#ffffff',
        'circle-stroke-width': 2,
      },
    });
  }, [map]);

  // Toggle visibility per the left-edge buttons.
  useEffect(() => {
    if (map === null) {
      return;
    }
    for (const [key, layerId] of LAYER_BINDINGS) {
      map.setLayoutProperty(layerId, 'visibility', layers[key] ? 'visible' : 'none');
    }
  }, [map, layers]);

  useEffect(() => {
    if (map === null) {
      return;
    }
    setSourceData(map, 'trail', lineCollection(trail));
  }, [map, trail]);

  useEffect(() => {
    if (map === null) {
      return;
    }
    const points = [measureA, measureB].filter((point): point is LatLon => point !== null);
    setSourceData(map, 'measure-points', pointCollection(points));
    setSourceData(map, 'measure-line', lineCollection(points));
  }, [map, measureA, measureB]);

  useEffect(() => {
    if (map === null) {
      return;
    }
    setSourceData(map, 'staged', staged === null ? EMPTY : pointCollection([staged]));
  }, [map, staged]);
}
