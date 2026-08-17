/**
 * Pure flat-earth geometry for the mock traffic feed.
 *
 * Flat earth is fine here: everything spawns within ~20 NM of the aircraft, where the
 * tangent-plane error is metres. The real path geometry lives in `core/` on the backend
 * (feature-spec §13) — none of this survives integration.
 */

import type { LatLon, TrafficEntity } from './types.mock';

/** One degree of latitude is 60 NM everywhere; longitude shrinks with cos(lat). */
const NM_PER_DEG = 60;

const DEG_TO_RAD = Math.PI / 180;
const RAD_TO_DEG = 180 / Math.PI;

/** Normalise any angle to [0, 360). */
export function normalizeDeg(degrees: number): number {
  return ((degrees % 360) + 360) % 360;
}

/** The point `distanceNm` away from `origin` on true bearing `bearingDeg`. */
export function offset(origin: LatLon, bearingDeg: number, distanceNm: number): LatLon {
  const bearingRad = bearingDeg * DEG_TO_RAD;
  const dLat = (distanceNm * Math.cos(bearingRad)) / NM_PER_DEG;
  const dLon =
    (distanceNm * Math.sin(bearingRad)) /
    (NM_PER_DEG * Math.cos(origin.lat * DEG_TO_RAD));
  return { lat: origin.lat + dLat, lon: origin.lon + dLon };
}

/** Great-circle-ish distance in NM — flat-earth, accurate at panel ranges. */
export function distanceNm(a: LatLon, b: LatLon): number {
  const midLatRad = ((a.lat + b.lat) / 2) * DEG_TO_RAD;
  const dNorth = (b.lat - a.lat) * NM_PER_DEG;
  const dEast = (b.lon - a.lon) * NM_PER_DEG * Math.cos(midLatRad);
  return Math.hypot(dNorth, dEast);
}

/** True bearing from `from` to `to`, degrees in [0, 360). */
export function bearingDeg(from: LatLon, to: LatLon): number {
  const midLatRad = ((from.lat + to.lat) / 2) * DEG_TO_RAD;
  const dNorth = to.lat - from.lat;
  const dEast = (to.lon - from.lon) * Math.cos(midLatRad);
  return normalizeDeg(Math.atan2(dEast, dNorth) * RAD_TO_DEG);
}

/**
 * Advance one entity along its track by `speed_kt × dtS`.
 *
 * Waypoints are consumed as they are reached, with the leftover distance carried into
 * the next leg, so a tick that crosses a corner turns the corner instead of overshooting.
 * With the track exhausted the entity continues straight on its current heading. Pure:
 * returns a new entity, never mutates.
 */
export function advanceEntity(entity: TrafficEntity, dtS: number): TrafficEntity {
  let remainingNm = (entity.speed_kt * dtS) / 3600;
  if (remainingNm <= 0) {
    return entity;
  }

  let position = entity.position;
  let heading = entity.heading_deg;
  const track = [...entity.track];

  while (remainingNm > 0) {
    const target = track[0];
    if (target === undefined) {
      position = offset(position, heading, remainingNm);
      break;
    }
    const legNm = distanceNm(position, target);
    heading = legNm > 1e-9 ? bearingDeg(position, target) : heading;
    if (legNm > remainingNm) {
      position = offset(position, heading, remainingNm);
      break;
    }
    position = target;
    remainingNm -= legNm;
    track.shift();
  }

  return { ...entity, position, heading_deg: heading, track };
}
