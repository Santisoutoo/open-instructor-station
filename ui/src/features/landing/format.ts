/**
 * Display formatting for the debrief numbers: value + unit strings, signs kept
 * where the sign is the information (offsets, sink rate, heading difference).
 */

import type { LandingReport } from './types.mock';
import type { MetricKey } from './grade';

export interface MetricDescriptor {
  key: MetricKey;
  label: string;
  format: (value: number) => string;
}

const signed = (value: number, digits: number): string =>
  `${value > 0 ? '+' : ''}${value.toFixed(digits)}`;

/** The ten debrief numbers, in the order the report card shows them. */
export const REPORT_METRICS: readonly MetricDescriptor[] = [
  {
    key: 'touchdown_vs_fpm',
    label: 'Touchdown rate',
    format: (v) => `${v.toFixed(0)} fpm`,
  },
  { key: 'peak_g', label: 'Peak G', format: (v) => `${v.toFixed(2)} g` },
  {
    key: 'pitch_at_touchdown_deg',
    label: 'Pitch at touchdown',
    format: (v) => `${v.toFixed(1)}°`,
  },
  {
    key: 'roll_at_touchdown_deg',
    label: 'Roll at touchdown',
    format: (v) => `${signed(v, 1)}°`,
  },
  {
    key: 'centreline_offset_m',
    label: 'Centreline offset',
    format: (v) => `${signed(v, 1)} m`,
  },
  { key: 'flare_duration_s', label: 'Flare', format: (v) => `${v.toFixed(1)} s` },
  { key: 'float_distance_m', label: 'Float', format: (v) => `${v.toFixed(0)} m` },
  {
    key: 'touchdown_distance_m',
    label: 'Touchdown point',
    format: (v) => `${v.toFixed(0)} m`,
  },
  {
    key: 'ias_at_threshold_kt',
    label: 'IAS at threshold',
    format: (v) => `${v.toFixed(0)} kt`,
  },
  {
    key: 'heading_vs_runway_deg',
    label: 'Heading vs runway',
    format: (v) => `${signed(v, 1)}°`,
  },
];

export function formatMetric(key: MetricKey, report: LandingReport): string {
  const descriptor = REPORT_METRICS.find((metric) => metric.key === key);
  return descriptor === undefined ? String(report[key]) : descriptor.format(report[key]);
}
