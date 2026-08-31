/**
 * Debrief grading: each of the ten report numbers → ok / warn / danger.
 *
 * Pure and table-driven so the thresholds are in one place and the tests can walk
 * the edges. Thresholds are the mock's teaching values for a light piston trainer
 * (Vref ~90 kt); the real ones arrive with the backend's analysis config and this
 * file then reads them instead of hard-coding.
 */

import type { LandingReport } from './types.mock';

export type Grade = 'ok' | 'warn' | 'danger';

export type MetricKey = keyof LandingReport;

/** Vref the demo landings are flown to; threshold speed is judged against it. */
export const MOCK_VREF_KT = 92;

interface Band {
  /** Inclusive bounds on the *judged* value (after any absolute/offset transform). */
  okMax: number;
  warnMax: number;
}

/** Grade a magnitude against "ok up to, warn up to, danger beyond". */
function byMagnitude(value: number, band: Band): Grade {
  const magnitude = Math.abs(value);
  if (magnitude <= band.okMax) {
    return 'ok';
  }
  return magnitude <= band.warnMax ? 'warn' : 'danger';
}

export function gradeMetric(key: MetricKey, value: number): Grade {
  switch (key) {
    case 'touchdown_vs_fpm':
      return byMagnitude(value, { okMax: 250, warnMax: 600 });
    case 'peak_g':
      // Above 1 g is what matters: 1.0 is level flight, not a bonus.
      return byMagnitude(value - 1, { okMax: 0.4, warnMax: 0.8 });
    case 'pitch_at_touchdown_deg':
      // Low pitch risks the nosewheel, high pitch the tail: judge distance from
      // a 4° target attitude.
      return byMagnitude(value - 4, { okMax: 3, warnMax: 5 });
    case 'roll_at_touchdown_deg':
      return byMagnitude(value, { okMax: 2, warnMax: 5 });
    case 'centreline_offset_m':
      return byMagnitude(value, { okMax: 3, warnMax: 8 });
    case 'flare_duration_s':
      // Judged around a ~4 s flare: snatched or endless both grade down.
      return byMagnitude(value - 4, { okMax: 2.5, warnMax: 5 });
    case 'float_distance_m':
      return byMagnitude(value, { okMax: 150, warnMax: 450 });
    case 'touchdown_distance_m':
      // Around a 300 m aim point.
      return byMagnitude(value - 300, { okMax: 300, warnMax: 700 });
    case 'ias_at_threshold_kt':
      return byMagnitude(value - MOCK_VREF_KT, { okMax: 5, warnMax: 10 });
    case 'heading_vs_runway_deg':
      return byMagnitude(value, { okMax: 3, warnMax: 8 });
  }
}

export function gradeReport(report: LandingReport): Record<MetricKey, Grade> {
  const entries = (Object.keys(report) as MetricKey[]).map((key) => [
    key,
    gradeMetric(key, report[key]),
  ]);
  return Object.fromEntries(entries) as Record<MetricKey, Grade>;
}
