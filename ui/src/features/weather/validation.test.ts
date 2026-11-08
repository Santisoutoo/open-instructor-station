import { describe, expect, it } from 'vitest';
import type { CloudLayer, WeatherState, WindLayer } from '../../api/models';
import { weatherValidationError } from './validation';

const WIND: WindLayer = {
  altitude_ft: 0,
  direction_deg: 270,
  speed_kt: 5,
  gust_increase_kt: 0,
  turbulence_ratio: 0,
};
const CLOUD: CloudLayer = {
  base_ft: 3000,
  tops_ft: 5000,
  coverage_ratio: 0.5,
  cloud_type: 'cumulus',
};
const CURRENT: WeatherState = {
  wind_layers: [WIND],
  cloud_layers: [CLOUD],
  visibility_m: 10000,
  qnh_hpa: 1016,
  temperature_c: 19,
  dewpoint_c: 7,
  precipitation_ratio: 0,
  runway_contamination: 'dry',
};

describe('weatherValidationError', () => {
  it('accepts clear and calm conditions and all model boundaries', () => {
    expect(
      weatherValidationError({
        ...CURRENT,
        wind_layers: [],
        cloud_layers: [],
        visibility_m: 0,
        qnh_hpa: 900,
        temperature_c: -60,
        dewpoint_c: -60,
        precipitation_ratio: 1,
      }),
    ).toBeNull();
    expect(
      weatherValidationError({
        ...CURRENT,
        qnh_hpa: 1100,
        temperature_c: 60,
        dewpoint_c: 60,
      }),
    ).toBeNull();
  });

  it('accepts model-valid values beyond the previous sliders and negative cloud bases', () => {
    expect(
      weatherValidationError({
        ...CURRENT,
        visibility_m: 100000,
        wind_layers: [
          {
            ...WIND,
            altitude_ft: 60000,
            direction_deg: 360,
            speed_kt: 150,
            gust_increase_kt: 90,
          },
        ],
        cloud_layers: [{ ...CLOUD, base_ft: -500, tops_ft: -200 }],
      }),
    ).toBeNull();
  });

  it.each([
    ['visibility_m', -1],
    ['visibility_m', Infinity],
    ['qnh_hpa', 899],
    ['qnh_hpa', 1101],
    ['temperature_c', -61],
    ['temperature_c', 61],
    ['dewpoint_c', -61],
    ['dewpoint_c', 61],
    ['precipitation_ratio', -0.1],
    ['precipitation_ratio', 1.1],
    ['precipitation_ratio', NaN],
  ] as const)('rejects %s=%s', (field, value) => {
    expect(weatherValidationError({ ...CURRENT, [field]: value })).not.toBeNull();
  });

  it('rejects contradictory temperature and dewpoint without clamping either', () => {
    const draft = { ...CURRENT, temperature_c: 5, dewpoint_c: 7 };
    expect(weatherValidationError(draft)).toMatch(/Dewpoint must not exceed/);
    expect(draft.dewpoint_c).toBe(7);
  });

  it.each([
    ['altitude_ft', -1],
    ['altitude_ft', Infinity],
    ['direction_deg', -1],
    ['direction_deg', 361],
    ['speed_kt', -1],
    ['speed_kt', Infinity],
    ['gust_increase_kt', -1],
    ['turbulence_ratio', -0.1],
    ['turbulence_ratio', 1.1],
    ['turbulence_ratio', NaN],
  ] as const)('rejects wind %s=%s', (field, value) => {
    expect(
      weatherValidationError({ ...CURRENT, wind_layers: [{ ...WIND, [field]: value }] }),
    ).not.toBeNull();
  });

  it.each([
    ['base_ft', NaN],
    ['tops_ft', Infinity],
    ['tops_ft', 3000],
    ['tops_ft', 2999],
    ['coverage_ratio', -0.1],
    ['coverage_ratio', 1.1],
    ['coverage_ratio', NaN],
  ] as const)('rejects cloud %s=%s', (field, value) => {
    expect(
      weatherValidationError({
        ...CURRENT,
        cloud_layers: [{ ...CLOUD, [field]: value }],
      }),
    ).not.toBeNull();
  });

  it('enforces three layers and ascending 100 ft separation independently for each list', () => {
    for (const altitudes of [
      [0, 100, 200, 300],
      [100, 0],
      [0, 99],
    ]) {
      expect(
        weatherValidationError({
          ...CURRENT,
          wind_layers: altitudes.map((altitude_ft) => ({ ...WIND, altitude_ft })),
        }),
      ).not.toBeNull();
      expect(
        weatherValidationError({
          ...CURRENT,
          cloud_layers: altitudes.map((base_ft) => ({ ...CLOUD, base_ft })),
        }),
      ).not.toBeNull();
    }
    expect(
      weatherValidationError({
        ...CURRENT,
        wind_layers: [0, 100, 200].map((altitude_ft) => ({ ...WIND, altitude_ft })),
        cloud_layers: [0, 100, 200].map((base_ft) => ({ ...CLOUD, base_ft })),
      }),
    ).toBeNull();
  });
});
