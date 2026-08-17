/**
 * Display formatting, and the two unit conversions that only exist because the wire model
 * and the instructor's reading of it are deliberately different: `gust_increase_kt` is an
 * increase over the sustained speed, not the peak, and `coverage_ratio` is a 0-1 float, not
 * octas.
 */

import { describe, expect, it } from 'vitest';
import type { CloudLayer, WeatherState, WindLayer } from '../../api/models';
import {
  coverageGroup,
  formatCloudLayer,
  formatCloudSummary,
  formatContamination,
  formatDirection,
  formatPrecipitation,
  formatQnh,
  formatTempDew,
  formatVisibility,
  formatWind,
  octasToRatio,
  ratioToOctas,
} from './format';

function wind(overrides: Partial<WindLayer> = {}): WindLayer {
  return {
    altitude_ft: 0,
    direction_deg: 250,
    speed_kt: 12,
    gust_increase_kt: 0,
    turbulence_ratio: 0,
    ...overrides,
  };
}

function cloud(overrides: Partial<CloudLayer> = {}): CloudLayer {
  return {
    base_ft: 2000,
    tops_ft: 4000,
    coverage_ratio: 1,
    cloud_type: 'stratus',
    ...overrides,
  };
}

function weatherState(overrides: Partial<WeatherState> = {}): WeatherState {
  return {
    wind_layers: [],
    cloud_layers: [],
    visibility_m: 10000,
    qnh_hpa: 1013,
    temperature_c: 15,
    dewpoint_c: 5,
    precipitation_ratio: 0,
    runway_contamination: 'dry',
    ...overrides,
  };
}

describe('formatDirection', () => {
  it('pads to three digits and normalises negative and 360+ input', () => {
    expect(formatDirection(5)).toBe('005°');
    expect(formatDirection(-10)).toBe('350°');
    expect(formatDirection(360)).toBe('000°');
  });
});

describe('formatWind', () => {
  it('reads calm at zero speed and zero gust increase', () => {
    expect(formatWind(wind({ speed_kt: 0, gust_increase_kt: 0 }))).toBe('calm');
  });

  it('shows the steady wind with no gust suffix when the layer does not gust', () => {
    expect(formatWind(wind({ direction_deg: 250, speed_kt: 12 }))).toBe('250° / 12 kt');
  });

  it('shows the PEAK gust — speed_kt + gust_increase_kt — not the wire field itself', () => {
    // 20 kt gusting 30 is speed_kt=20, gust_increase_kt=10 (weather-manager.md D13).
    expect(formatWind(wind({ speed_kt: 20, gust_increase_kt: 10 }))).toBe('250° / 20 kt G 30 kt');
  });
});

describe('formatVisibility', () => {
  it('caps the primary reading at 10 km+', () => {
    expect(formatVisibility(10000)).toBe('10 km+ · 6.2 SM');
  });

  it('shows metres under 1 km', () => {
    expect(formatVisibility(800)).toBe('800 m · 0.50 SM');
  });

  it('shows kilometres between 1 and 10 km', () => {
    expect(formatVisibility(3000)).toBe('3.0 km · 1.9 SM');
  });
});

describe('formatQnh / formatTempDew', () => {
  it('rounds QNH to the whole hectopascal', () => {
    expect(formatQnh(1013.25)).toBe('1013 hPa');
  });

  it('renders temperature over dewpoint, each rounded', () => {
    expect(formatTempDew(19.4, 6.6)).toBe('19 °C / 7 °C');
  });
});

describe('octas <-> ratio', () => {
  it('round-trips the boundary values', () => {
    expect(ratioToOctas(0)).toBe(0);
    expect(ratioToOctas(1)).toBe(8);
    expect(octasToRatio(0)).toBe(0);
    expect(octasToRatio(8)).toBe(1);
  });

  it('matches the design note\'s worked examples', () => {
    // FEW~=0.2, SCT~=0.44, BKN~=0.75, OVC=1.0 (core/weather/models.py CloudLayer docstring).
    expect(ratioToOctas(0.2)).toBe(2);
    expect(ratioToOctas(0.44)).toBe(4);
    expect(ratioToOctas(0.75)).toBe(6);
  });
});

describe('coverageGroup', () => {
  it('maps every octa boundary to its METAR group', () => {
    expect(coverageGroup(0)).toBe('SKC');
    expect(coverageGroup(octasToRatio(2))).toBe('FEW');
    expect(coverageGroup(octasToRatio(4))).toBe('SCT');
    expect(coverageGroup(octasToRatio(7))).toBe('BKN');
    expect(coverageGroup(1)).toBe('OVC');
  });
});

describe('formatCloudLayer / formatCloudSummary', () => {
  it('formats one layer in ft MSL, group first', () => {
    expect(formatCloudLayer(cloud({ base_ft: 200, tops_ft: 2500, coverage_ratio: 1 }))).toBe(
      'OVC 200–2,500 ft',
    );
  });

  it('reads sky clear with no layers', () => {
    expect(formatCloudSummary(weatherState({ cloud_layers: [] }))).toBe('sky clear');
  });

  it('summarises on the lowest layer and counts the rest', () => {
    const state = weatherState({
      cloud_layers: [
        cloud({ base_ft: 4000, tops_ft: 6000, coverage_ratio: 1 }),
        cloud({ base_ft: 1500, tops_ft: 4000, coverage_ratio: 0.75 }),
      ],
    });
    expect(formatCloudSummary(state)).toBe('BKN 1,500–4,000 ft +1');
  });
});

describe('formatPrecipitation', () => {
  it('reads none at zero', () => {
    expect(formatPrecipitation(0)).toBe('none');
  });

  it('reads a percentage above zero', () => {
    expect(formatPrecipitation(0.4)).toBe('40%');
  });
});

describe('formatContamination', () => {
  it('labels every contamination state', () => {
    expect(formatContamination('dry')).toBe('Dry');
    expect(formatContamination('ice')).toBe('Ice');
  });
});
