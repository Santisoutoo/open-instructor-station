/**
 * The four recorded demo landings, generated — not hand-typed — by one deterministic
 * simulation with per-landing parameters.
 *
 * Generating buys the property the debrief depends on: the report *matches* its
 * trace, because everything derivable is derived from the samples (touchdown sink
 * rate, flare and float, distances, threshold speed) and only what a trace cannot
 * carry (peak G, centreline metres, heading vs runway) comes from the parameters.
 * No `Math.random`, no clock: the wiggle on the approach is a fixed-phase sine, so
 * every import sees byte-identical fixtures.
 *
 * Dies at backend integration — real landings come from `core/`'s analysis of a
 * recorded approach.
 */

import type { Landing, LandingId, LandingReport, TraceSample } from './types.mock';

/** 4 Hz, like the mock feed — enough to draw, small enough to keep fixtures cheap. */
const DT_S = 0.25;

/** Metres per nautical mile / feet, for the along-track integration. */
const M_PER_KT_S = 0.514444; // 1 kt in m/s (still air: IAS ≈ ground speed)
const FT_PER_M = 3.28084;

/** A 3° slope: feet lost per metre travelled. */
const SLOPE_FT_PER_M = Math.tan((3 * Math.PI) / 180) * FT_PER_M;

/** Round for storage, normalising `-0` (it survives toFixed and trips deep equality). */
function round(value: number, digits: number): number {
  const result = Number(value.toFixed(digits));
  return result === 0 ? 0 : result;
}

interface LandingParams {
  id: LandingId;
  label: string;
  description: string;
  /** IAS flown down the approach, kt. */
  approachIas: number;
  /** Steady localizer offset flown down final, dots. */
  locBiasDot: number;
  /** Height the flare begins, ft AGL. */
  flareStartAgl: number;
  /** How long the flare takes to arrest the descent, s. */
  flareDuration: number;
  /** Time spent floating nearly level before touching, s. */
  floatDuration: number;
  /** Sink rate at the touchdown instant, fpm (negative). */
  touchdownVs: number;
  pitchAtTouchdown: number;
  rollAtTouchdown: number;
  /** Not derivable from the trace: the recorder's accelerometer / position data. */
  peakG: number;
  centrelineOffsetM: number;
  headingVsRunwayDeg: number;
}

function generateLanding(params: LandingParams): Landing {
  const samples: TraceSample[] = [];

  // Approach VS on a 3° slope at this ground speed (kt → fpm on the slope).
  const approachVs = -params.approachIas * M_PER_KT_S * SLOPE_FT_PER_M * 60;

  // Start 500 ft above the threshold-crossing height, on-slope: AGL 550 ft.
  let t = 0;
  let agl = 550;
  let ias = params.approachIas;
  let pitch = 2;
  // On the slope, 50 ft over the threshold: distance back from it follows the slope.
  let x = -((agl - 50) / SLOPE_FT_PER_M);

  let phase: 'approach' | 'flare' | 'float' | 'ground' = 'approach';
  let flareStartT: number | null = null;
  let floatStartX: number | null = null;
  let iasAtThreshold: number | null = null;
  let touchdownT: number | null = null;

  // Cap well beyond any profile's real duration; the loop exits on rollout speed.
  const maxSamples = 2000;

  while (samples.length < maxSamples) {
    const wiggle = Math.sin(t * 0.7); // fixed phase — deterministic "hand flying"
    let vs: number;
    let roll: number;
    let locDev: number;
    let gsDev = 0;

    if (phase === 'approach') {
      vs = approachVs * (1 + 0.06 * wiggle);
      pitch = 2 + 0.4 * wiggle;
      roll = 0.8 * Math.sin(t * 0.45);
      locDev = params.locBiasDot + 0.12 * Math.sin(t * 0.5);
      gsDev = 0.15 * wiggle;
      if (agl <= params.flareStartAgl) {
        phase = 'flare';
        flareStartT = t;
      }
    } else if (phase === 'flare' && flareStartT !== null) {
      const k = Math.min(1, (t - flareStartT) / params.flareDuration);
      vs = approachVs + (params.touchdownVs - approachVs) * k;
      pitch = 2 + (params.pitchAtTouchdown - 2) * k;
      roll = params.rollAtTouchdown * k;
      ias -= 1.2 * DT_S;
      locDev = params.locBiasDot * (1 - 0.5 * k);
      if (k >= 1) {
        if (params.floatDuration > 0) {
          phase = 'float';
          floatStartX = x;
        }
        // With no float the descent is already at touchdown VS: fall through it.
      }
    } else if (phase === 'float' && flareStartT !== null) {
      const floatElapsed = t - flareStartT - params.flareDuration;
      // Nearly level: sinking gently until the float time is spent.
      vs = floatElapsed < params.floatDuration ? -40 : params.touchdownVs;
      pitch = params.pitchAtTouchdown;
      roll = params.rollAtTouchdown;
      ias -= 1.6 * DT_S;
      locDev = params.locBiasDot * 0.5;
    } else {
      // Ground roll: decelerate, derotate, hold the offset.
      vs = 0;
      ias = Math.max(0, ias - 3.5 * DT_S);
      pitch = Math.max(0, pitch - 2.5 * DT_S);
      roll = 0;
      locDev = params.locBiasDot * 0.5;
    }

    // Integrate.
    if (phase !== 'ground') {
      agl += (vs / 60) * DT_S;
      if (agl <= 0) {
        agl = 0;
        phase = 'ground';
        touchdownT = t + DT_S;
      }
    }
    x += ias * M_PER_KT_S * DT_S;
    t += DT_S;

    if (iasAtThreshold === null && x >= 0) {
      iasAtThreshold = ias;
    }

    samples.push({
      t_s: round(t, 2),
      ias_kt: round(ias, 1),
      altitude_agl_ft: round(agl, 1),
      vs_fpm: round(phase === 'ground' ? 0 : vs, 0),
      pitch_deg: round(pitch, 2),
      roll_deg: round(roll, 2),
      loc_dev_dot: round(locDev, 2),
      gs_dev_dot: round(gsDev, 2),
      distance_from_threshold_m: round(x, 1),
    });

    if (phase === 'ground' && ias <= 45) {
      break;
    }
  }

  const touchdownIndex = samples.findIndex(
    (sample) => sample.altitude_agl_ft === 0,
  );
  const lastAirborne = samples[touchdownIndex - 1];
  const touchdown = samples[touchdownIndex];
  if (lastAirborne === undefined || touchdown === undefined) {
    throw new Error(`mock landing '${params.id}' never touched down`);
  }

  const report: LandingReport = {
    touchdown_vs_fpm: lastAirborne.vs_fpm,
    peak_g: params.peakG,
    pitch_at_touchdown_deg: touchdown.pitch_deg,
    roll_at_touchdown_deg: lastAirborne.roll_deg,
    centreline_offset_m: params.centrelineOffsetM,
    flare_duration_s:
      flareStartT !== null && touchdownT !== null
        ? round(touchdownT - flareStartT - params.floatDuration, 1)
        : 0,
    float_distance_m:
      floatStartX === null
        ? 0
        : round(touchdown.distance_from_threshold_m - floatStartX, 0),
    touchdown_distance_m: round(touchdown.distance_from_threshold_m, 0),
    ias_at_threshold_kt: iasAtThreshold ?? params.approachIas,
    heading_vs_runway_deg: params.headingVsRunwayDeg,
  };

  return {
    id: params.id,
    label: params.label,
    description: params.description,
    runway: 'LEMD 32L',
    recorded_at: '2026-08-14T16:20:00Z',
    samples,
    touchdownIndex,
    report,
  };
}

export const MOCK_LANDINGS: Landing[] = [
  generateLanding({
    id: 'good',
    label: 'Good',
    description: 'Stable approach, gentle touchdown near the aim point',
    approachIas: 92,
    locBiasDot: 0.05,
    flareStartAgl: 22,
    flareDuration: 4,
    floatDuration: 0.75,
    touchdownVs: -140,
    pitchAtTouchdown: 5,
    rollAtTouchdown: -0.5,
    peakG: 1.15,
    centrelineOffsetM: 0.8,
    headingVsRunwayDeg: 1,
  }),
  generateLanding({
    id: 'firm',
    label: 'Firm',
    description: 'Late flare, firm touchdown',
    approachIas: 94,
    locBiasDot: -0.1,
    flareStartAgl: 10,
    flareDuration: 1.5,
    floatDuration: 0,
    touchdownVs: -540,
    pitchAtTouchdown: 3,
    rollAtTouchdown: 0.8,
    peakG: 1.75,
    centrelineOffsetM: 1.6,
    headingVsRunwayDeg: 2,
  }),
  generateLanding({
    id: 'floated',
    label: 'Floated',
    description: 'Fast over the threshold, long float, deep touchdown',
    approachIas: 103,
    locBiasDot: 0.1,
    flareStartAgl: 30,
    flareDuration: 5,
    floatDuration: 6,
    touchdownVs: -120,
    pitchAtTouchdown: 7,
    rollAtTouchdown: 0.3,
    peakG: 1.1,
    centrelineOffsetM: -1.2,
    headingVsRunwayDeg: -1,
  }),
  generateLanding({
    id: 'off-centre',
    label: 'Off centre',
    description: 'Crosswind, drifting right of the centreline at touchdown',
    approachIas: 95,
    locBiasDot: 0.8,
    flareStartAgl: 20,
    flareDuration: 3,
    floatDuration: 0,
    touchdownVs: -320,
    pitchAtTouchdown: 4,
    rollAtTouchdown: 4,
    peakG: 1.4,
    centrelineOffsetM: 9,
    headingVsRunwayDeg: -6,
  }),
];
