/**
 * The GeoJSON overlays: real navdata (airports, runways, ILS, navaids, waypoints,
 * procedures, holds), the aircraft trail, the measure segment and the staged point.
 *
 * Sources and layers are added once when the map becomes ready; after that this hook
 * only pushes data into `setData` and flips `visibility` — the cheap paths. Nothing
 * here dispatches into the map slice: it is a one-way projection of Redux state and
 * navdata onto the canvas.
 *
 * The overlay layers gate on `GET /api/navdata/status` (instructor-map.md D7): until
 * the index is ready every navdata source stays an empty collection. The reposition
 * path is deliberately NOT gated on this — a coordinate placement needs no navdata.
 */

import { type GeoJSONSource, type Map as MapLibreMap } from 'maplibre-gl';
import { skipToken } from '@reduxjs/toolkit/query';
import { useEffect, useState } from 'react';
import type { Feature, FeatureCollection } from 'geojson';
import {
  instructorApi,
  useGetHoldsQuery,
  useGetNavdataStatusQuery,
} from '../../api/instructorApi';
import type { Procedure } from '../../api/models';
import { useAppDispatch, useAppSelector } from '../../store';
import { navdataGate } from '../position/gate';
import { type LatLon } from './measure';
import { type MapLayerKey } from './mapSlice';
import {
  fixFeature,
  holdFeature,
  ilsFeature,
  navaidFeature,
  primaryRunwayEnds,
  procedureLineFeature,
  runwayFeature,
} from './overlays';
import { useOverlayData } from './useOverlayData';

/** Which style layers each left-edge toggle controls. */
const LAYER_BINDINGS: ReadonlyArray<[MapLayerKey, readonly string[]]> = [
  ['runways', ['airport-runways']],
  ['ils', ['airport-ils']],
  ['navaids', ['airport-navaids']],
  ['waypoints', ['waypoints']],
  ['procedures', ['procedure-lines', 'holds']],
  ['trail', ['trail']],
];

/**
 * Canvas colours are literals — WebGL cannot read CSS custom properties. Amber is the
 * app accent and marks the two active-intent drawings (measure, staged point).
 */
const AMBER = '#e8a33d';

const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] };

function collection(features: Feature[]): FeatureCollection {
  return { type: 'FeatureCollection', features };
}

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

const NO_PROCEDURES: Procedure[] = [];

/**
 * The legs of every procedure toggled ON, fetched through the existing endpoint.
 * Fetched imperatively because the open count varies; derived to empty when nothing
 * is open — the effect never resets state, it only reports what it fetched.
 */
function useOpenProcedures(): Procedure[] {
  const dispatch = useAppDispatch();
  const referenceIcao = useAppSelector((state) => state.map.referenceIcao);
  const openProcedures = useAppSelector((state) => state.map.openProcedures);
  const [fetched, setFetched] = useState<Procedure[]>(NO_PROCEDURES);

  useEffect(() => {
    if (referenceIcao === null || openProcedures.length === 0) {
      return;
    }
    let cancelled = false;
    const subscriptions = openProcedures.map((open) =>
      dispatch(
        instructorApi.endpoints.getProcedure.initiate({
          icao: referenceIcao,
          kind: open.kind,
          ident: open.ident,
          transition: open.transition,
        }),
      ),
    );
    void Promise.all(
      subscriptions.map((subscription) =>
        subscription.unwrap().then(
          (procedure) => [procedure],
          () => [] as Procedure[],
        ),
      ),
    ).then((lists) => {
      if (!cancelled) {
        setFetched(lists.flat());
      }
    });
    return () => {
      cancelled = true;
      for (const subscription of subscriptions) {
        subscription.unsubscribe();
      }
    };
  }, [dispatch, referenceIcao, openProcedures]);

  return referenceIcao === null || openProcedures.length === 0 ? NO_PROCEDURES : fetched;
}

export function useMapOverlays(map: MapLibreMap | null): void {
  const layers = useAppSelector((state) => state.map.layers);
  const trail = useAppSelector((state) => state.map.trail);
  const measureA = useAppSelector((state) => state.map.measureA);
  const measureB = useAppSelector((state) => state.map.measureB);
  const staged = useAppSelector((state) => state.map.staged);
  const referenceIcao = useAppSelector((state) => state.map.referenceIcao);

  // D7: the decorative layers wait on the navdata index; nothing else does.
  const { data: status, isError } = useGetNavdataStatusQuery();
  const ready = navdataGate(status, isError).kind === 'ready';

  const overlay = useOverlayData(ready ? map : null);
  const procedures = useOpenProcedures();
  const { data: holds } = useGetHoldsQuery(
    ready && referenceIcao !== null ? { airportIcao: referenceIcao } : skipToken,
  );

  // Sources and layers, once per map instance. They die with `map.remove()`.
  useEffect(() => {
    if (map === null) {
      return;
    }
    // Airport points carry no toggle: they are the anchor every other overlay hangs
    // off, and they only exist at all from AIRPORT_MIN_ZOOM up (the fetch gate).
    map.addSource('airports', { type: 'geojson', data: EMPTY });
    map.addLayer({
      id: 'airports',
      type: 'circle',
      source: 'airports',
      paint: {
        'circle-radius': 5,
        'circle-color': 'rgba(0, 0, 0, 0)',
        'circle-stroke-color': '#94a3b3',
        'circle-stroke-width': 1.5,
      },
    });
    map.addSource('airport-runways', { type: 'geojson', data: EMPTY });
    map.addLayer({
      id: 'airport-runways',
      type: 'fill',
      source: 'airport-runways',
      paint: { 'fill-color': '#546170', 'fill-opacity': 0.85 },
    });
    map.addSource('airport-ils', { type: 'geojson', data: EMPTY });
    map.addLayer({
      id: 'airport-ils',
      type: 'line',
      source: 'airport-ils',
      paint: { 'line-color': '#7d8da1', 'line-width': 1.5 },
    });
    map.addSource('airport-navaids', { type: 'geojson', data: EMPTY });
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
    map.addSource('waypoints', { type: 'geojson', data: EMPTY });
    map.addLayer({
      id: 'waypoints',
      type: 'circle',
      source: 'waypoints',
      paint: {
        'circle-radius': 2.5,
        'circle-color': '#7d8da1',
        'circle-opacity': 0.9,
      },
    });
    map.addSource('procedure-lines', { type: 'geojson', data: EMPTY });
    map.addLayer({
      id: 'procedure-lines',
      type: 'line',
      source: 'procedure-lines',
      paint: { 'line-color': '#8f6fd0', 'line-width': 2, 'line-opacity': 0.9 },
    });
    map.addSource('holds', { type: 'geojson', data: EMPTY });
    map.addLayer({
      id: 'holds',
      type: 'line',
      source: 'holds',
      paint: { 'line-color': '#8f6fd0', 'line-width': 1.5, 'line-opacity': 0.7 },
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
    for (const [key, layerIds] of LAYER_BINDINGS) {
      for (const layerId of layerIds) {
        map.setLayoutProperty(layerId, 'visibility', layers[key] ? 'visible' : 'none');
      }
    }
  }, [map, layers]);

  // The navdata overlays. When the gate is closed every list is already empty.
  useEffect(() => {
    if (map === null) {
      return;
    }
    setSourceData(
      map,
      'airports',
      collection(
        overlay.airports.map(
          (airport): Feature => ({
            type: 'Feature',
            properties: { icao: airport.icao },
            geometry: {
              type: 'Point',
              coordinates: [airport.position.longitude, airport.position.latitude],
            },
          }),
        ),
      ),
    );
    setSourceData(
      map,
      'airport-runways',
      collection(primaryRunwayEnds(overlay.runways).map(runwayFeature)),
    );
    setSourceData(
      map,
      'airport-ils',
      collection(
        overlay.runways
          .map(ilsFeature)
          .filter((feature): feature is NonNullable<typeof feature> => feature !== null),
      ),
    );
    setSourceData(map, 'airport-navaids', collection(overlay.navaids.map(navaidFeature)));
    setSourceData(map, 'waypoints', collection(overlay.fixes.map(fixFeature)));
  }, [map, overlay.airports, overlay.runways, overlay.navaids, overlay.fixes]);

  useEffect(() => {
    if (map === null) {
      return;
    }
    setSourceData(map, 'procedure-lines', collection(procedures.map(procedureLineFeature)));
  }, [map, procedures]);

  useEffect(() => {
    if (map === null) {
      return;
    }
    setSourceData(map, 'holds', collection((holds ?? []).map(holdFeature)));
  }, [map, holds]);

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
