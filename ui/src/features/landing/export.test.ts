/**
 * The export builders: JSON round-trips the whole debrief, CSV carries one row per
 * sample under a stable header.
 */

import { describe, expect, it } from 'vitest';
import { landingToCsv, landingToJson } from './export';
import { MOCK_LANDINGS } from './mock';

const landing = MOCK_LANDINGS[0]!;

describe('landingToJson', () => {
  it('round-trips the landing losslessly', () => {
    expect(JSON.parse(landingToJson(landing))).toEqual(landing);
  });
});

describe('landingToCsv', () => {
  it('emits a header plus one row per sample', () => {
    const lines = landingToCsv(landing).split('\n');
    expect(lines[0]).toBe(
      't_s,ias_kt,altitude_agl_ft,vs_fpm,pitch_deg,roll_deg,loc_dev_dot,gs_dev_dot,distance_from_threshold_m',
    );
    expect(lines).toHaveLength(landing.samples.length + 1);
  });

  it('writes the first sample in column order', () => {
    const first = landing.samples[0]!;
    const row = landingToCsv(landing).split('\n')[1];
    expect(row).toBe(
      [
        first.t_s,
        first.ias_kt,
        first.altitude_agl_ft,
        first.vs_fpm,
        first.pitch_deg,
        first.roll_deg,
        first.loc_dev_dot,
        first.gs_dev_dot,
        first.distance_from_threshold_m,
      ].join(','),
    );
  });
});
