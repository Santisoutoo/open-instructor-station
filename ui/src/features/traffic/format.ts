/**
 * Display formatting for traffic rows.
 *
 * Locale pinned to `en-US`, as in `features/telemetry/format.ts`: the readout must be
 * identical on the tablet, the desktop and CI regardless of system locale.
 */

import type { AircraftState } from '../../api/models';
import { bearingDeg, distanceNm } from './geo';
import type { TrafficEntity } from './types.mock';

const INTEGER = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const SIGNED_INTEGER = new Intl.NumberFormat('en-US', {
  maximumFractionDigits: 0,
  signDisplay: 'exceptZero',
});

function formatBearing(degrees: number): string {
  const normalised = ((Math.round(degrees) % 360) + 360) % 360;
  return `${String(normalised).padStart(3, '0')}°`;
}

/**
 * Where the entity is, from the instructor's point of view.
 *
 * With telemetry: relative to the student's aircraft — `3.2 NM · bearing 047° ·
 * +1,200 ft`. Bearing is true bearing *from* the aircraft *to* the entity; the
 * altitude delta is signed, entity minus own. Without telemetry there is nothing to be
 * relative to, so the line degrades to the absolute position instead of lying.
 */
export function positionLine(entity: TrafficEntity, own: AircraftState | null): string {
  if (own === null) {
    return absolutePositionLine(entity);
  }
  const ownPosition = { lat: own.latitude, lon: own.longitude };
  const range = distanceNm(ownPosition, entity.position);
  const bearing = bearingDeg(ownPosition, entity.position);
  const deltaFt = Math.round(entity.altitude_ft - own.altitude_ft);
  return `${range.toFixed(1)} NM · bearing ${formatBearing(bearing)} · ${SIGNED_INTEGER.format(deltaFt)} ft`;
}

/** Absolute fallback: `40.46000° N · 3.57000° W · 5,000 ft`. */
export function absolutePositionLine(entity: TrafficEntity): string {
  const { lat, lon } = entity.position;
  const latPart = `${Math.abs(lat).toFixed(5)}° ${lat < 0 ? 'S' : 'N'}`;
  const lonPart = `${Math.abs(lon).toFixed(5)}° ${lon < 0 ? 'W' : 'E'}`;
  return `${latPart} · ${lonPart} · ${INTEGER.format(Math.round(entity.altitude_ft))} ft`;
}
