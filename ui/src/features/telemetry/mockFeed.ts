/**
 * The demo telemetry feed: a deterministic traffic circuit, computed as a pure function
 * of elapsed time. No RNG, no state — the same millisecond always yields the same frame,
 * which is what makes it testable and what makes a paused tab resume coherently.
 *
 * The circuit is a left-hand pattern flown as a continuous touch-and-go at a fictional
 * runway placed on the LEMD 32L geometry: climb-out, crosswind, downwind, base, final,
 * touch, and around again. The numbers are chosen to look right on every consumer
 * (status strip, map marker, trigger editor), not to model any aircraft.
 *
 * This file feeds `telemetryFrameReceived` with real `AircraftState` payloads — the
 * exact code path the live WebSocket uses — so nothing downstream can tell the
 * difference. The status bar's "Demo data" chip is what tells the instructor.
 */

import type { AircraftState } from '../../api/models';

interface GeoPoint {
  lat: number;
  lon: number;
}

/** Flat-earth offset — fine at circuit scale (<10 NM), and this is demo data. */
function offsetNm(from: GeoPoint, bearingDeg: number, distanceNm: number): GeoPoint {
  const rad = (bearingDeg * Math.PI) / 180;
  const dLat = (Math.cos(rad) * distanceNm) / 60;
  const dLon =
    (Math.sin(rad) * distanceNm) / (60 * Math.cos((from.lat * Math.PI) / 180));
  return { lat: from.lat + dLat, lon: from.lon + dLon };
}

function bearingDeg(from: GeoPoint, to: GeoPoint): number {
  const midLatRad = (((from.lat + to.lat) / 2) * Math.PI) / 180;
  const dy = (to.lat - from.lat) * 60;
  const dx = (to.lon - from.lon) * 60 * Math.cos(midLatRad);
  return (Math.round((Math.atan2(dx, dy) * 180) / Math.PI) + 360) % 360;
}

const THRESHOLD: GeoPoint = { lat: 40.46, lon: -3.57 };
const RUNWAY_HEADING = 323;
const RECIPROCAL = (RUNWAY_HEADING + 180) % 360; // 143
const CROSSWIND_HEADING = (RUNWAY_HEADING + 270) % 360; // 233 — left-hand pattern
const FIELD_ELEVATION_FT = 2000;
const PATTERN_ALTITUDE_FT = 3000;

const ROLLOUT_END = offsetNm(THRESHOLD, RUNWAY_HEADING, 1.2);
const CLIMBOUT_END = offsetNm(THRESHOLD, RUNWAY_HEADING, 3);
const CROSSWIND_END = offsetNm(CLIMBOUT_END, CROSSWIND_HEADING, 2);
const FINAL_FIX = offsetNm(THRESHOLD, RECIPROCAL, 5);
const DOWNWIND_END = offsetNm(FINAL_FIX, CROSSWIND_HEADING, 2);

interface Leg {
  from: GeoPoint;
  to: GeoPoint;
  durationS: number;
  altFromFt: number;
  altToFt: number;
  iasFromKt: number;
  iasToKt: number;
  onGround: boolean;
}

const LEGS: readonly Leg[] = [
  // Climb-out from the touch-and-go.
  {
    from: ROLLOUT_END,
    to: CLIMBOUT_END,
    durationS: 60,
    altFromFt: FIELD_ELEVATION_FT,
    altToFt: PATTERN_ALTITUDE_FT,
    iasFromKt: 80,
    iasToKt: 100,
    onGround: false,
  },
  {
    from: CLIMBOUT_END,
    to: CROSSWIND_END,
    durationS: 45,
    altFromFt: PATTERN_ALTITUDE_FT,
    altToFt: PATTERN_ALTITUDE_FT,
    iasFromKt: 105,
    iasToKt: 105,
    onGround: false,
  },
  {
    from: CROSSWIND_END,
    to: DOWNWIND_END,
    durationS: 90,
    altFromFt: PATTERN_ALTITUDE_FT,
    altToFt: PATTERN_ALTITUDE_FT,
    iasFromKt: 110,
    iasToKt: 110,
    onGround: false,
  },
  {
    from: DOWNWIND_END,
    to: FINAL_FIX,
    durationS: 45,
    altFromFt: PATTERN_ALTITUDE_FT,
    altToFt: 2600,
    iasFromKt: 95,
    iasToKt: 95,
    onGround: false,
  },
  {
    from: FINAL_FIX,
    to: THRESHOLD,
    durationS: 90,
    altFromFt: 2600,
    altToFt: FIELD_ELEVATION_FT + 10,
    iasFromKt: 85,
    iasToKt: 85,
    onGround: false,
  },
  // Touch and go — the only leg on the ground, and what closes the loop.
  {
    from: THRESHOLD,
    to: ROLLOUT_END,
    durationS: 30,
    altFromFt: FIELD_ELEVATION_FT,
    altToFt: FIELD_ELEVATION_FT,
    iasFromKt: 75,
    iasToKt: 70,
    onGround: true,
  },
];

export const CIRCUIT_PERIOD_S = LEGS.reduce((sum, leg) => sum + leg.durationS, 0);

function lerp(from: number, to: number, fraction: number): number {
  return from + (to - from) * fraction;
}

/** The frame the demo aircraft is in `tMs` milliseconds after the feed started. */
export function mockFrame(tMs: number): AircraftState {
  const tS = (((tMs / 1000) % CIRCUIT_PERIOD_S) + CIRCUIT_PERIOD_S) % CIRCUIT_PERIOD_S;

  let elapsed = 0;
  let found: { leg: Leg; fraction: number } | null = null;
  for (const candidate of LEGS) {
    if (tS < elapsed + candidate.durationS) {
      found = { leg: candidate, fraction: (tS - elapsed) / candidate.durationS };
      break;
    }
    elapsed += candidate.durationS;
  }
  if (found === null) {
    // Unreachable: tS is reduced modulo CIRCUIT_PERIOD_S, the sum of all durations.
    throw new Error('mockFrame: time fell outside the circuit');
  }
  const { leg, fraction } = found;

  const altitudeFt = lerp(leg.altFromFt, leg.altToFt, fraction);
  const verticalSpeedFpm = ((leg.altToFt - leg.altFromFt) / leg.durationS) * 60;
  const pitchDeg = leg.onGround ? 0 : verticalSpeedFpm > 200 ? 8 : verticalSpeedFpm < -200 ? -3 : 2;

  return {
    latitude: lerp(leg.from.lat, leg.to.lat, fraction),
    longitude: lerp(leg.from.lon, leg.to.lon, fraction),
    altitude_ft: altitudeFt,
    heading_deg: bearingDeg(leg.from, leg.to),
    ias_kt: lerp(leg.iasFromKt, leg.iasToKt, fraction),
    vertical_speed_fpm: verticalSpeedFpm,
    pitch_deg: pitchDeg,
    roll_deg: 0,
    on_ground: leg.onGround,
  };
}
