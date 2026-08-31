/**
 * Mock overlay fixture for the Instructor Map.
 *
 * One detailed airport, hand-written on the geometry the demo telemetry circuit flies
 * (threshold 40.46/-3.57, runway heading 323 — see `../telemetry/mockFeed.ts`), so the
 * demo aircraft actually lands on the drawn runway and flies down the drawn ILS
 * feather. LEMD-like layout: two parallel 32s, feathers on both, a handful of navaids.
 *
 * Since backend integration (instructor-map.md §7.6) the production overlay comes from
 * the user's own navdata through `useOverlayData`/`overlays.ts`; this fixture is kept
 * only for tests and isolated rendering, plus `MAP_HOME` — where the map opens, which
 * is a view choice, not overlay data. Never import `MOCK_AIRPORT` from production code.
 */

import { destinationPoint, type LatLon } from './measure';
import type {
  AirportOverlay,
  IlsProperties,
  NavaidKind,
  NavaidProperties,
  RunwayProperties,
} from './types.mock';
import type { Feature, LineString, Point, Polygon } from 'geojson';

/** Where the map opens: over the demo airport, wide enough to see the circuit. */
export const MAP_HOME: LatLon = { lat: 40.47, lon: -3.56 };
export const MAP_HOME_ZOOM = 11.5;

/** Matches the demo feed's touch-and-go threshold and runway heading exactly. */
const THRESHOLD_32L: LatLon = { lat: 40.46, lon: -3.57 };
const RUNWAY_HEADING = 323;
const APPROACH_BEARING = (RUNWAY_HEADING + 180) % 360; // 143 — final approach course

/** ~90 m wide: exaggerated slightly so the polygons read at circuit zoom. */
const RUNWAY_WIDTH_NM = 0.05;
const ILS_FEATHER_LENGTH_NM = 8;
const ILS_FEATHER_HALF_ANGLE_DEG = 1.5;

function toPosition(point: LatLon): [number, number] {
  return [point.lon, point.lat];
}

function runwayFeature(
  ident: string,
  threshold: LatLon,
  lengthNm: number,
): Feature<Polygon, RunwayProperties> {
  const far = destinationPoint(threshold, RUNWAY_HEADING, lengthNm);
  const half = RUNWAY_WIDTH_NM / 2;
  const a = destinationPoint(threshold, RUNWAY_HEADING - 90, half);
  const b = destinationPoint(threshold, RUNWAY_HEADING + 90, half);
  const c = destinationPoint(far, RUNWAY_HEADING + 90, half);
  const d = destinationPoint(far, RUNWAY_HEADING - 90, half);
  return {
    type: 'Feature',
    properties: { ident },
    geometry: {
      type: 'Polygon',
      coordinates: [[a, b, c, d, a].map(toPosition)],
    },
  };
}

/** The charted ILS feather: a thin triangle opening down the final approach course. */
function ilsFeature(ident: string, threshold: LatLon): Feature<LineString, IlsProperties> {
  const left = destinationPoint(
    threshold,
    APPROACH_BEARING - ILS_FEATHER_HALF_ANGLE_DEG,
    ILS_FEATHER_LENGTH_NM,
  );
  const right = destinationPoint(
    threshold,
    APPROACH_BEARING + ILS_FEATHER_HALF_ANGLE_DEG,
    ILS_FEATHER_LENGTH_NM,
  );
  return {
    type: 'Feature',
    properties: { ident },
    geometry: {
      type: 'LineString',
      coordinates: [threshold, left, right, threshold].map(toPosition),
    },
  };
}

function navaidFeature(
  ident: string,
  kind: NavaidKind,
  position: LatLon,
): Feature<Point, NavaidProperties> {
  return {
    type: 'Feature',
    properties: { ident, kind },
    geometry: { type: 'Point', coordinates: toPosition(position) },
  };
}

const THRESHOLD_32R = destinationPoint(THRESHOLD_32L, RUNWAY_HEADING + 90, 0.9);

export const MOCK_AIRPORT: AirportOverlay = {
  name: 'Demo field (LEMD-like)',
  runways: {
    type: 'FeatureCollection',
    features: [
      runwayFeature('32L', THRESHOLD_32L, 2.2),
      runwayFeature('32R', THRESHOLD_32R, 1.9),
    ],
  },
  ils: {
    type: 'FeatureCollection',
    features: [ilsFeature('32L', THRESHOLD_32L), ilsFeature('32R', THRESHOLD_32R)],
  },
  navaids: {
    type: 'FeatureCollection',
    features: [
      // On-field DME and the VOR the circuit is flown around, plus the two approach aids.
      navaidFeature('DMD', 'dme', destinationPoint(THRESHOLD_32L, 60, 1.2)),
      navaidFeature('SSY', 'vor', destinationPoint(THRESHOLD_32L, 250, 6)),
      navaidFeature('FF32', 'ndb', destinationPoint(THRESHOLD_32L, APPROACH_BEARING, 4)),
      navaidFeature('CNR', 'vor', destinationPoint(THRESHOLD_32L, 25, 8)),
    ],
  },
};
