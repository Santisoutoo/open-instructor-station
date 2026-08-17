/**
 * The shipped preset catalogue and its resolution. Seven presets is a spec number
 * (feature-spec §3), not an implementation detail — a fixture edit that loses one
 * should fail loudly here. The invariant that matters most: a dewpoint can never
 * come out above the temperature, whatever the fixtures or the overrides say.
 */

import { describe, expect, it } from 'vitest';
import {
  initialWeatherFixture,
  presetById,
  resolveAppliedWeather,
  resolveWeather,
  runwayHeadingDeg,
  WEATHER_PRESETS,
} from './mock';

const CROSSWIND = WEATHER_PRESETS.find((preset) => preset.id === 'crosswind');

describe('WEATHER_PRESETS', () => {
  it('ships exactly the seven presets from the spec', () => {
    expect(WEATHER_PRESETS).toHaveLength(7);
    expect(WEATHER_PRESETS.map((preset) => preset.id)).toEqual([
      'cavok',
      'cat-i',
      'cat-ii',
      'cat-iii',
      'storm',
      'crosswind',
      'mountain-wave',
    ]);
  });

  it('marks only the crosswind preset runway-relative', () => {
    const relative = WEATHER_PRESETS.filter((preset) => preset.requires_runway);
    expect(relative.map((preset) => preset.id)).toEqual(['crosswind']);
  });

  it('keeps dewpoint at or below temperature in every fixture', () => {
    for (const preset of WEATHER_PRESETS) {
      expect(preset.state.dewpoint_c, preset.id).toBeLessThanOrEqual(
        preset.state.temperature_c,
      );
    }
    const initial = initialWeatherFixture();
    expect(initial.dewpoint_c).toBeLessThanOrEqual(initial.temperature_c);
  });

  it('keeps every cloud layer right side up and every octa in 0-8', () => {
    for (const preset of WEATHER_PRESETS) {
      for (const layer of preset.state.cloud_layers) {
        expect(layer.tops_ft_agl, preset.id).toBeGreaterThanOrEqual(layer.base_ft_agl);
        expect(layer.coverage_octas, preset.id).toBeGreaterThanOrEqual(0);
        expect(layer.coverage_octas, preset.id).toBeLessThanOrEqual(8);
      }
    }
  });

  it('keeps every wind layer plausible: direction 0-359, speeds not negative', () => {
    for (const preset of WEATHER_PRESETS) {
      for (const layer of preset.state.wind_layers) {
        expect(layer.direction_deg, preset.id).toBeGreaterThanOrEqual(0);
        expect(layer.direction_deg, preset.id).toBeLessThan(360);
        expect(layer.speed_kt, preset.id).toBeGreaterThanOrEqual(0);
        expect(layer.gust_kt, preset.id).toBeGreaterThanOrEqual(0);
      }
    }
  });
});

describe('runwayHeadingDeg', () => {
  it('reads the heading off the ident', () => {
    expect(runwayHeadingDeg('32L')).toBe(320);
    expect(runwayHeadingDeg('04')).toBe(40);
    expect(runwayHeadingDeg('36')).toBe(0);
  });

  it('falls back to 0 on an unparsable ident', () => {
    expect(runwayHeadingDeg('N1')).toBe(0);
  });
});

describe('resolveWeather', () => {
  it('aims the crosswind 90° off the selected runway', () => {
    expect(CROSSWIND).toBeDefined();
    if (CROSSWIND === undefined) {
      return;
    }
    const resolved = resolveWeather(CROSSWIND, {}, { icao: 'LEMD', ident: '32L' });
    expect(resolved.wind_layers[0]?.direction_deg).toBe(50);
    expect(resolved.wind_layers[0]?.speed_kt).toBe(20);
  });

  it('lets an explicit wind override win over the runway resolution', () => {
    if (CROSSWIND === undefined) {
      return;
    }
    const edited = [{ base_ft_msl: 0, direction_deg: 180, speed_kt: 12, gust_kt: 0 }];
    const resolved = resolveWeather(
      CROSSWIND,
      { wind_layers: edited },
      { icao: 'LEMD', ident: '32L' },
    );
    expect(resolved.wind_layers).toEqual(edited);
  });

  it('clamps an overridden dewpoint to the temperature', () => {
    const cavok = presetById('cavok');
    expect(cavok).toBeDefined();
    if (cavok === undefined) {
      return;
    }
    const resolved = resolveWeather(cavok, { dewpoint_c: 30 }, null);
    expect(resolved.dewpoint_c).toBe(resolved.temperature_c);
  });

  it('clamps the dewpoint when the temperature is lowered under it', () => {
    const storm = presetById('storm');
    if (storm === undefined) {
      return;
    }
    const resolved = resolveWeather(storm, { temperature_c: 2 }, null);
    expect(resolved.dewpoint_c).toBe(2);
  });
});

describe('resolveAppliedWeather', () => {
  it('resolves the request exactly as the staging display does', () => {
    const applied = resolveAppliedWeather({
      preset_id: 'crosswind',
      overrides: { qnh_hpa: 1002 },
      runway: { icao: 'LEMD', ident: '18R' },
    });
    expect(applied.wind_layers[0]?.direction_deg).toBe(270);
    expect(applied.qnh_hpa).toBe(1002);
  });
});
