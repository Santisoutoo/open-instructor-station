/**
 * Real-navdata GeoJSON geometry builders (instructor-map.md §7.4): runway rectangles,
 * ILS feathers, navaid/fix points, procedure polylines and hold racetracks, generalising
 * what `mock.ts` prototyped for one hand-written airport.
 *
 * All pure functions on the spherical primitives of `measure.ts` — decoration, not
 * navigation (D3). Anything that must be exact (a measurement's settled reading, a
 * placement's geometry) goes through the server's WGS84 geodesy, never through here.
 */

import type { Feature, LineString, MultiLineString, Point, Polygon } from 'geojson';
import type { Fix, Hold, Navaid, NavaidKind, Procedure, Runway } from '../../api/models';
import { destinationPoint, type LatLon } from './measure';

export interface RunwayProperties {
  /** Runway end ident, e.g. `"32L"`. */
  ident: string;
  airport_icao: string;
}

export interface IlsProperties {
  /** The runway end the feather serves, e.g. `"32L"`. */
  ident: string;
  airport_icao: string;
  localizer_ident: string;
}

export interface NavaidProperties {
  ident: string;
  kind: NavaidKind;
}

export interface FixProperties {
  ident: string;
}

export interface ProcedureProperties {
  ident: string;
  kind: Procedure['kind'];
  transition: string | null;
}

export interface HoldProperties {
  fix_ident: string;
  turn_direction: Hold['turn_direction'];
}

/** Metres per nautical mile, for the metric fields the navdata publishes. */
const M_PER_NM = 1852;

/** Pavement width to draw when the source publishes none. */
const RUNWAY_FALLBACK_WIDTH_M = 45;

/** Nominal feather length, matching typical localizer service volume. */
export const ILS_FEATHER_LENGTH_NM = 10;

/** Half-angle when the source publishes no `localizer_width_deg`. */
export const ILS_FEATHER_FALLBACK_HALF_ANGLE_DEG = 2.5;

/** Racetrack turn radius. Decorative — roughly a rate-one turn at approach speed. */
const HOLD_TURN_RADIUS_NM = 0.75;

/** Leg length flown per published minute when only a time is given (~180 kt). */
const HOLD_NM_PER_MIN = 3.0;

/** Sample step for the racetrack's two half-turns. */
const HOLD_ARC_STEP_DEG = 15;

function toPosition(point: LatLon): [number, number] {
  return [point.lon, point.lat];
}

function toLatLon(position: { latitude: number; longitude: number }): LatLon {
  return { lat: position.latitude, lon: position.longitude };
}

/**
 * The paved rectangle of one runway end, from the pavement end (falling back to the
 * displaced threshold when the source does not publish it) along the true bearing.
 */
export function runwayFeature(runway: Runway): Feature<Polygon, RunwayProperties> {
  const start = toLatLon(runway.pavement_end ?? runway.threshold);
  const bearing = runway.true_bearing_deg;
  const lengthNm = runway.length_m / M_PER_NM;
  const halfWidthNm = (runway.width_m ?? RUNWAY_FALLBACK_WIDTH_M) / M_PER_NM / 2;
  const far = destinationPoint(start, bearing, lengthNm);
  const a = destinationPoint(start, bearing - 90, halfWidthNm);
  const b = destinationPoint(start, bearing + 90, halfWidthNm);
  const c = destinationPoint(far, bearing + 90, halfWidthNm);
  const d = destinationPoint(far, bearing - 90, halfWidthNm);
  return {
    type: 'Feature',
    properties: { ident: runway.ident, airport_icao: runway.airport_icao },
    geometry: { type: 'Polygon', coordinates: [[a, b, c, d, a].map(toPosition)] },
  };
}

/**
 * Both ends of a strip describe the same pavement. Keep one rectangle per strip —
 * the end whose ident sorts first — so the fill is painted once, not twice.
 */
export function primaryRunwayEnds(runways: readonly Runway[]): Runway[] {
  return runways.filter((runway) => {
    if (runway.opposite_ident == null) {
      return true;
    }
    const opposite = runways.find(
      (other) =>
        other.airport_icao === runway.airport_icao &&
        other.ident === runway.opposite_ident,
    );
    return opposite === undefined || runway.ident < opposite.ident;
  });
}

/**
 * The charted ILS feather: a thin triangle from the localizer antenna, opening down
 * the reciprocal of the front course (the approach direction), for
 * {@link ILS_FEATHER_LENGTH_NM} at a half-angle of half the published course width,
 * else {@link ILS_FEATHER_FALLBACK_HALF_ANGLE_DEG}. `null` when the end has no ILS.
 */
export function ilsFeature(runway: Runway): Feature<LineString, IlsProperties> | null {
  const ils = runway.ils;
  if (ils == null) {
    return null;
  }
  const apex = toLatLon(ils.localizer_position);
  const approachBearing = (ils.localizer_true_deg + 180) % 360;
  const halfAngle =
    ils.localizer_width_deg != null
      ? ils.localizer_width_deg / 2
      : ILS_FEATHER_FALLBACK_HALF_ANGLE_DEG;
  const left = destinationPoint(apex, approachBearing - halfAngle, ILS_FEATHER_LENGTH_NM);
  const right = destinationPoint(apex, approachBearing + halfAngle, ILS_FEATHER_LENGTH_NM);
  return {
    type: 'Feature',
    properties: {
      ident: runway.ident,
      airport_icao: runway.airport_icao,
      localizer_ident: ils.localizer_ident,
    },
    geometry: {
      type: 'LineString',
      coordinates: [apex, left, right, apex].map(toPosition),
    },
  };
}

export function navaidFeature(navaid: Navaid): Feature<Point, NavaidProperties> {
  return {
    type: 'Feature',
    properties: { ident: navaid.ident, kind: navaid.kind },
    geometry: { type: 'Point', coordinates: toPosition(toLatLon(navaid.position)) },
  };
}

export function fixFeature(fix: Fix): Feature<Point, FixProperties> {
  return {
    type: 'Feature',
    properties: { ident: fix.ident },
    geometry: { type: 'Point', coordinates: toPosition(toLatLon(fix.position)) },
  };
}

/**
 * The procedure's track: the `position` of every leg whose `fix` resolved, in
 * `sequence` order. **A trajectory-dependent leg (no fix) breaks the line** rather
 * than inventing a point for it — the gap is visible on the map, which is honest: a
 * SID's climbing turn is not a straight segment across airspace. Hence a
 * `MultiLineString`, one line per unbroken run of fix-carrying legs; the total
 * coordinate count equals the fix-carrying leg count, never the total leg count.
 */
export function procedureLineFeature(
  procedure: Procedure,
): Feature<MultiLineString, ProcedureProperties> {
  const segments: [number, number][][] = [];
  let current: [number, number][] = [];
  const legs = [...procedure.legs].sort((a, b) => a.sequence - b.sequence);
  for (const leg of legs) {
    if (leg.fix == null) {
      if (current.length > 0) {
        segments.push(current);
        current = [];
      }
      continue;
    }
    current.push(toPosition(toLatLon(leg.fix.position)));
  }
  if (current.length > 0) {
    segments.push(current);
  }
  return {
    type: 'Feature',
    properties: {
      ident: procedure.ident,
      kind: procedure.kind,
      transition: procedure.transition ?? null,
    },
    geometry: { type: 'MultiLineString', coordinates: segments },
  };
}

/**
 * A published hold as a closed racetrack over its fix: inbound leg into the fix on
 * `inbound_course_mag_deg` **unconverted** (D11-reversed: this project carries no world
 * magnetic model, and a decorative racetrack a few degrees off true is cosmetic — the
 * actual hold *placement* stays server-side and correct), a half-turn in
 * `turn_direction`, the outbound leg, and the half-turn back.
 */
export function holdFeature(hold: Hold): Feature<LineString, HoldProperties> {
  const fix = toLatLon(hold.fix.position);
  const course = hold.inbound_course_mag_deg;
  const sign = hold.turn_direction === 'R' ? 1 : -1;
  const legNm =
    hold.leg_length_nm ?? (hold.leg_time_min ?? 1) * HOLD_NM_PER_MIN;
  const radius = HOLD_TURN_RADIUS_NM;

  const inboundStart = destinationPoint(fix, course + 180, legNm);
  const points: LatLon[] = [inboundStart, fix];

  // Half-turn at the fix, onto the outbound track offset one diameter abeam.
  const fixTurnCentre = destinationPoint(fix, course + sign * 90, radius);
  for (let t = HOLD_ARC_STEP_DEG; t <= 180; t += HOLD_ARC_STEP_DEG) {
    points.push(destinationPoint(fixTurnCentre, course - sign * 90 + sign * t, radius));
  }
  // Outbound leg, then the half-turn back onto the inbound start.
  const outboundStart = points[points.length - 1] as LatLon;
  const outboundEnd = destinationPoint(outboundStart, course + 180, legNm);
  points.push(outboundEnd);
  const endTurnCentre = destinationPoint(inboundStart, course + sign * 90, radius);
  for (let t = HOLD_ARC_STEP_DEG; t <= 180; t += HOLD_ARC_STEP_DEG) {
    points.push(destinationPoint(endTurnCentre, course + sign * 90 + sign * t, radius));
  }

  return {
    type: 'Feature',
    properties: { fix_ident: hold.fix.ident, turn_direction: hold.turn_direction },
    geometry: { type: 'LineString', coordinates: points.map(toPosition) },
  };
}
