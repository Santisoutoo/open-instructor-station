/**
 * `buildWeatherRequest` and `mergeForDisplay`: the two small pure functions between the
 * slice and the server. The interesting behaviour is what happens at the edges — no edits
 * must mean `setup: null`, never `setup: {}`, and the dewpoint invariant must hold across a
 * merge even when the current weather and the staged setup disagree about it.
 */

import { describe, expect, it } from 'vitest';
import type { WeatherState } from '../../api/models';
import { buildWeatherRequest, mergeForDisplay } from './resolve';

function currentFixture(overrides: Partial<WeatherState> = {}): WeatherState {
  return {
    wind_layers: [{ altitude_ft: 0, direction_deg: 270, speed_kt: 5, gust_increase_kt: 0, turbulence_ratio: 0 }],
    cloud_layers: [{ base_ft: 4000, tops_ft: 6000, coverage_ratio: 0.25, cloud_type: 'cumulus' }],
    visibility_m: 10000,
    qnh_hpa: 1016,
    temperature_c: 19,
    dewpoint_c: 7,
    precipitation_ratio: 0,
    runway_contamination: 'dry',
    ...overrides,
  };
}

describe('buildWeatherRequest', () => {
  it('sends setup: null rather than {} when nothing was overridden', () => {
    const request = buildWeatherRequest('cavok', {}, null, null);
    expect(request).toEqual({
      preset: 'cavok',
      airport_icao: null,
      runway_ident: null,
      setup: null,
    });
  });

  it('carries the runway context and the sparse overlay through unchanged', () => {
    const request = buildWeatherRequest('crosswind', { qnh_hpa: 1002 }, 'LEMD', '18R');
    expect(request).toEqual({
      preset: 'crosswind',
      airport_icao: 'LEMD',
      runway_ident: '18R',
      setup: { qnh_hpa: 1002 },
    });
  });
});

describe('mergeForDisplay', () => {
  it('falls back to the current weather for every field the setup left untouched', () => {
    const current = currentFixture();
    const merged = mergeForDisplay(current, {});
    expect(merged).toEqual(current);
  });

  it('replaces only the fields the resolved setup actually states', () => {
    const current = currentFixture();
    const merged = mergeForDisplay(current, { qnh_hpa: 998, visibility_m: 3000 });
    expect(merged.qnh_hpa).toBe(998);
    expect(merged.visibility_m).toBe(3000);
    expect(merged.temperature_c).toBe(current.temperature_c);
    expect(merged.wind_layers).toBe(current.wind_layers);
  });

  it('replaces a layer list wholesale, never merging entry by entry', () => {
    const current = currentFixture();
    const newWind = [
      { altitude_ft: 0, direction_deg: 90, speed_kt: 20, gust_increase_kt: 5, turbulence_ratio: 0.2 },
    ];
    const merged = mergeForDisplay(current, { wind_layers: newWind });
    expect(merged.wind_layers).toBe(newWind);
  });

  it('an empty layer list is a real command — calm/clear, not "untouched"', () => {
    const current = currentFixture();
    const merged = mergeForDisplay(current, { cloud_layers: [] });
    expect(merged.cloud_layers).toEqual([]);
  });

  it('re-clamps the dewpoint when the setup lowers the temperature under the current dewpoint', () => {
    const current = currentFixture({ temperature_c: 19, dewpoint_c: 17 });
    const merged = mergeForDisplay(current, { temperature_c: 10 });
    expect(merged.temperature_c).toBe(10);
    expect(merged.dewpoint_c).toBe(10);
  });

  it('clamps an overridden dewpoint to the (possibly also overridden) temperature', () => {
    const current = currentFixture();
    const merged = mergeForDisplay(current, { dewpoint_c: 30, temperature_c: 22 });
    expect(merged.dewpoint_c).toBe(22);
  });
});
