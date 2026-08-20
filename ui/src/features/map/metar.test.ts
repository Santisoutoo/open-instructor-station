/**
 * The METAR-style formatting of the commanded weather (instructor-map.md §7.9, D10):
 * pure string building, so every token rule is asserted here without a store or a fetch.
 */

import { describe, expect, it } from 'vitest';
import type { CloudLayer, WeatherState, WindLayer } from '../../api/models';
import {
  formatMetar,
  metarClouds,
  metarQnh,
  metarTemperatures,
  metarVisibility,
  metarWind,
} from './metar';

function wind(overrides: Partial<WindLayer> = {}): WindLayer {
  return {
    altitude_ft: 0,
    direction_deg: 270,
    speed_kt: 5,
    gust_increase_kt: 0,
    turbulence_ratio: 0,
    ...overrides,
  };
}

function cloud(overrides: Partial<CloudLayer> = {}): CloudLayer {
  return {
    base_ft: 2500,
    tops_ft: 5000,
    coverage_ratio: 0.75,
    cloud_type: 'stratus',
    ...overrides,
  };
}

function weatherState(overrides: Partial<WeatherState> = {}): WeatherState {
  return {
    wind_layers: [wind()],
    cloud_layers: [],
    visibility_m: 10000,
    qnh_hpa: 1016,
    temperature_c: 19,
    dewpoint_c: 7,
    precipitation_ratio: 0,
    runway_contamination: 'dry',
    ...overrides,
  };
}

describe('metarWind', () => {
  it('formats the steady surface wind with padded direction and speed', () => {
    expect(metarWind([wind({ direction_deg: 270, speed_kt: 5 })])).toBe('27005KT');
  });

  it('reads 00000KT when no layer is stated at all', () => {
    expect(metarWind([])).toBe('00000KT');
  });

  it('reads 00000KT when the surface layer is calm, whatever its direction', () => {
    expect(metarWind([wind({ direction_deg: 123, speed_kt: 0 })])).toBe('00000KT');
  });

  it('shows the PEAK gust — speed_kt + gust_increase_kt — not the wire field itself', () => {
    // 20 kt gusting 30 is speed_kt=20, gust_increase_kt=10 (weather-manager.md D13).
    expect(metarWind([wind({ speed_kt: 20, gust_increase_kt: 10 })])).toBe('27020G30KT');
  });

  it('picks the LOWEST layer as the surface wind, whatever the array order', () => {
    const aloft = wind({ altitude_ft: 5000, direction_deg: 180, speed_kt: 40 });
    const surface = wind({ altitude_ft: 0, direction_deg: 270, speed_kt: 5 });
    expect(metarWind([aloft, surface])).toBe('27005KT');
  });

  it('normalises direction without rounding to tens — the commanded value verbatim', () => {
    expect(metarWind([wind({ direction_deg: 273 })])).toBe('27305KT');
    expect(metarWind([wind({ direction_deg: 360 })])).toBe('00005KT');
    expect(metarWind([wind({ direction_deg: -10 })])).toBe('35005KT');
  });
});

describe('metarVisibility', () => {
  it('pads to four digits below 10 km', () => {
    expect(metarVisibility(800)).toBe('0800');
  });

  it('caps at 9999 from 10 km up, METAR-style', () => {
    expect(metarVisibility(10000)).toBe('9999');
    expect(metarVisibility(20000)).toBe('9999');
  });

  it('caps the ROUNDED value: 9999.7 m reads 9999, never a five-digit 10000', () => {
    expect(metarVisibility(9999.7)).toBe('9999');
  });
});

describe('metarClouds', () => {
  it('formats group + base in hundreds of feet, ascending by base', () => {
    const high = cloud({ base_ft: 10000, tops_ft: 12000, coverage_ratio: 1 });
    const low = cloud({ base_ft: 2500, coverage_ratio: 0.75 });
    expect(metarClouds([high, low])).toBe('BKN025 OVC100');
  });

  it('drops a layer whose coverage rounds to zero octas, and reads SKC without any', () => {
    expect(metarClouds([cloud({ coverage_ratio: 0 })])).toBe('SKC');
    expect(metarClouds([])).toBe('SKC');
  });

  it('renders bases AGL when the field elevation is stated — real-METAR style', () => {
    // 2500 ft MSL over a 1500 ft field is a 1000 ft ceiling.
    expect(metarClouds([cloud({ base_ft: 2500 })], 1500)).toBe('BKN010');
  });

  it('floors an AGL base at zero when the commanded base sits below the field', () => {
    expect(metarClouds([cloud({ base_ft: 1000 })], 1998)).toBe('BKN000');
  });

  it('stays MSL — the wire value verbatim — when no elevation is stated', () => {
    expect(metarClouds([cloud({ base_ft: 2500 })], null)).toBe('BKN025');
  });
});

describe('metarTemperatures', () => {
  it('pads to two digits, temperature over dewpoint', () => {
    expect(metarTemperatures(19, 7)).toBe('19/07');
  });

  it('marks negatives with M, never a minus sign', () => {
    expect(metarTemperatures(-3, -7)).toBe('M03/M07');
  });
});

describe('metarQnh', () => {
  it('rounds to whole hectopascals behind a Q', () => {
    expect(metarQnh(1013.25)).toBe('Q1013');
  });

  it('pads to four digits — a deep low reads Q0998, never Q998', () => {
    expect(metarQnh(998)).toBe('Q0998');
  });
});

describe('formatMetar', () => {
  it('collapses visibility and cloud to CAVOK when the commanded state earns it', () => {
    expect(formatMetar(weatherState())).toBe('27005KT CAVOK 19/07 Q1016');
  });

  it('reads CAVOK at 9999.7 m — the check uses the same rounded metres as the token', () => {
    expect(formatMetar(weatherState({ visibility_m: 9999.7 }))).toBe(
      '27005KT CAVOK 19/07 Q1016',
    );
  });

  it('never reads CAVOK with cloud stated, even at full visibility', () => {
    expect(formatMetar(weatherState({ cloud_layers: [cloud()] }))).toBe(
      '27005KT 9999 BKN025 19/07 Q1016',
    );
  });

  it('never reads CAVOK with precipitation commanded', () => {
    expect(formatMetar(weatherState({ precipitation_ratio: 0.4 }))).toBe(
      '27005KT 9999 SKC 19/07 Q1016',
    );
  });

  it('renders cloud bases AGL when the reference airport elevation is passed', () => {
    expect(
      formatMetar(weatherState({ cloud_layers: [cloud({ base_ft: 2500 })] }), 1500),
    ).toBe('27005KT 9999 BKN010 19/07 Q1016');
  });

  it('formats a commanded CAT III fog exactly as set, not as observed', () => {
    const catIii = weatherState({
      wind_layers: [],
      cloud_layers: [cloud({ base_ft: 100, tops_ft: 400, coverage_ratio: 1 })],
      visibility_m: 175,
      qnh_hpa: 1013.25,
      temperature_c: 8,
      dewpoint_c: 8,
    });
    expect(formatMetar(catIii)).toBe('00000KT 0175 OVC001 08/08 Q1013');
  });
});
