/**
 * Mock fixtures for the Weather Manager.
 *
 * The seven-preset catalogue from feature-spec §3, the current-weather fixture the
 * mock server "reports", and the resolution that turns preset + overrides + runway
 * into a concrete `WeatherState`. Deterministic on purpose: same request, same
 * weather. Dies at backend integration — presets are `core/` data and crosswind
 * resolution happens server-side against real navdata, not against a runway ident.
 */

import type {
  ApplyWeatherRequest,
  RunwayRef,
  WeatherOverrides,
  WeatherPreset,
  WeatherPresetId,
  WeatherState,
  WindLayer,
} from './types.mock';

/** The seven presets from feature-spec §3, in the order the grid shows them. */
export const WEATHER_PRESETS: readonly WeatherPreset[] = [
  {
    id: 'cavok',
    label: 'CAVOK',
    description: 'No cloud, unlimited visibility, light wind',
    requires_runway: false,
    state: {
      wind_layers: [{ base_ft_msl: 0, direction_deg: 250, speed_kt: 8, gust_kt: 0 }],
      cloud_layers: [],
      visibility_m: 10000,
      qnh_hpa: 1013,
      temperature_c: 22,
      dewpoint_c: 9,
      precipitation: 'none',
    },
  },
  {
    id: 'cat-i',
    label: 'CAT I',
    description: 'Ceiling 200 ft, 800 m visibility',
    requires_runway: false,
    state: {
      wind_layers: [{ base_ft_msl: 0, direction_deg: 240, speed_kt: 10, gust_kt: 0 }],
      cloud_layers: [{ base_ft_agl: 200, tops_ft_agl: 2500, coverage_octas: 8 }],
      visibility_m: 800,
      qnh_hpa: 1018,
      temperature_c: 12,
      dewpoint_c: 11,
      precipitation: 'none',
    },
  },
  {
    id: 'cat-ii',
    label: 'CAT II',
    description: 'Ceiling 100 ft, 350 m visibility',
    requires_runway: false,
    state: {
      wind_layers: [{ base_ft_msl: 0, direction_deg: 230, speed_kt: 6, gust_kt: 0 }],
      cloud_layers: [{ base_ft_agl: 100, tops_ft_agl: 1500, coverage_octas: 8 }],
      visibility_m: 350,
      qnh_hpa: 1020,
      temperature_c: 10,
      dewpoint_c: 9,
      precipitation: 'none',
    },
  },
  {
    id: 'cat-iii',
    label: 'CAT III',
    description: 'Fog on the deck — ceiling 50 ft, 125 m',
    requires_runway: false,
    state: {
      wind_layers: [{ base_ft_msl: 0, direction_deg: 220, speed_kt: 3, gust_kt: 0 }],
      cloud_layers: [{ base_ft_agl: 50, tops_ft_agl: 800, coverage_octas: 8 }],
      visibility_m: 125,
      qnh_hpa: 1021,
      temperature_c: 9,
      dewpoint_c: 9,
      precipitation: 'none',
    },
  },
  {
    id: 'storm',
    label: 'Storm',
    description: 'Heavy rain, gusting wind, embedded CB',
    requires_runway: false,
    state: {
      wind_layers: [
        { base_ft_msl: 0, direction_deg: 240, speed_kt: 25, gust_kt: 40 },
        { base_ft_msl: 6000, direction_deg: 260, speed_kt: 45, gust_kt: 55 },
      ],
      cloud_layers: [
        { base_ft_agl: 1500, tops_ft_agl: 4000, coverage_octas: 6 },
        { base_ft_agl: 4000, tops_ft_agl: 28000, coverage_octas: 8 },
      ],
      visibility_m: 3000,
      qnh_hpa: 998,
      temperature_c: 17,
      dewpoint_c: 16,
      precipitation: 'rain',
    },
  },
  {
    id: 'crosswind',
    label: 'Crosswind',
    // Relative preset (feature-spec §3): direction_deg below is the offset from
    // the runway heading, resolved into a true direction at apply time.
    description: '20 kt at 90° off the active runway',
    requires_runway: true,
    state: {
      wind_layers: [{ base_ft_msl: 0, direction_deg: 90, speed_kt: 20, gust_kt: 28 }],
      cloud_layers: [{ base_ft_agl: 3500, tops_ft_agl: 5000, coverage_octas: 4 }],
      visibility_m: 9000,
      qnh_hpa: 1015,
      temperature_c: 18,
      dewpoint_c: 8,
      precipitation: 'none',
    },
  },
  {
    id: 'mountain-wave',
    label: 'Mountain wave',
    description: 'Strong wind aloft, lenticular cloud, wave turbulence',
    requires_runway: false,
    state: {
      wind_layers: [
        { base_ft_msl: 0, direction_deg: 280, speed_kt: 18, gust_kt: 25 },
        { base_ft_msl: 8000, direction_deg: 290, speed_kt: 45, gust_kt: 55 },
      ],
      cloud_layers: [{ base_ft_agl: 9000, tops_ft_agl: 12000, coverage_octas: 3 }],
      visibility_m: 10000,
      qnh_hpa: 1008,
      temperature_c: 5,
      dewpoint_c: -5,
      precipitation: 'none',
    },
  },
];

/** What the mock server reports before anything is applied: a calm, clear day. */
export function initialWeatherFixture(): WeatherState {
  return {
    wind_layers: [{ base_ft_msl: 0, direction_deg: 270, speed_kt: 5, gust_kt: 0 }],
    cloud_layers: [{ base_ft_agl: 4000, tops_ft_agl: 6000, coverage_octas: 2 }],
    visibility_m: 10000,
    qnh_hpa: 1016,
    temperature_c: 19,
    dewpoint_c: 7,
    precipitation: 'none',
  };
}

// ----------------------------------------------------------------- resolution

/**
 * True heading of a runway end from its ident: "32L" → 320°, "04" → 40°, "36" → 0°.
 *
 * A mock stand-in only — the real resolution reads the runway's surveyed heading
 * from navdata in `core/`, next to the geodesy (feature-spec §3).
 */
export function runwayHeadingDeg(ident: string): number {
  const match = /^\d{1,2}/.exec(ident);
  if (match === null) {
    return 0;
  }
  return (Number(match[0]) * 10) % 360;
}

function resolveRelativeWind(layers: WindLayer[], runway: RunwayRef): WindLayer[] {
  const heading = runwayHeadingDeg(runway.ident);
  return layers.map((layer) => ({
    ...layer,
    direction_deg: (heading + layer.direction_deg) % 360,
  }));
}

/**
 * Preset + overrides + runway → the concrete `WeatherState` that would be applied.
 *
 * Also what the staging bar displays, so what the instructor reads is what the
 * apply mutation commits. Two rules:
 *
 * - A relative preset's wind resolves against the runway first; an explicit wind
 *   override still wins over the resolution — an edit is always the last word.
 * - Dewpoint can never exceed temperature, whatever order the edits arrived in.
 */
export function resolveWeather(
  preset: WeatherPreset,
  overrides: WeatherOverrides,
  runway: RunwayRef | null,
): WeatherState {
  const base = preset.state;
  const wind =
    preset.requires_runway && runway !== null
      ? resolveRelativeWind(base.wind_layers, runway)
      : base.wind_layers;
  const merged: WeatherState = { ...base, wind_layers: wind, ...overrides };
  return { ...merged, dewpoint_c: Math.min(merged.dewpoint_c, merged.temperature_c) };
}

export function presetById(id: WeatherPresetId): WeatherPreset | undefined {
  return WEATHER_PRESETS.find((preset) => preset.id === id);
}

/** What the apply endpoint answers: the resolved state it (pretends it) wrote. */
export function resolveAppliedWeather(request: ApplyWeatherRequest): WeatherState {
  const preset = presetById(request.preset_id);
  if (preset === undefined) {
    // Unreachable with the typed id; the fixture day keeps the mock total anyway.
    return initialWeatherFixture();
  }
  return resolveWeather(preset, request.overrides, request.runway);
}
