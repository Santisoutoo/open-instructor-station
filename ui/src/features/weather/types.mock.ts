/**
 * PROVISIONAL mock-only view models — replace with generated schema.d.ts types at
 * backend integration; do not import outside this feature.
 *
 * These describe what the Weather Manager *will* serve. Once the FastAPI endpoints
 * exist, `npm run generate:api` produces the real types and this file dies.
 */

/**
 * One wind layer. X-Plane exposes at most three indexed layers (feature-spec §3);
 * the adapter presents them as a typed list, and so does this mock.
 */
export interface WindLayer {
  /** Layer base altitude in ft MSL. The surface layer uses 0. */
  base_ft_msl: number;
  /**
   * True direction the wind blows *from*, 0–359°.
   *
   * On a runway-relative preset (`requires_runway`) this is stored as an offset
   * from the runway heading instead, and resolved into a true direction at apply
   * time — "20 kt at 90° off the runway" is preset data, not a fixed direction.
   */
  direction_deg: number;
  speed_kt: number;
  /** Gust peak in kt. 0 means steady wind. */
  gust_kt: number;
}

/** One cloud layer, of the up-to-three the simulator models. */
export interface CloudLayer {
  base_ft_agl: number;
  tops_ft_agl: number;
  /** Coverage in octas, 0 (sky clear) to 8 (overcast). */
  coverage_octas: number;
}

export type Precipitation = 'none' | 'rain' | 'snow';

/** The full environment, as the Weather Manager reads and writes it. */
export interface WeatherState {
  wind_layers: WindLayer[];
  cloud_layers: CloudLayer[];
  visibility_m: number;
  qnh_hpa: number;
  temperature_c: number;
  /** Never above `temperature_c`; resolution clamps it (see `mock.ts`). */
  dewpoint_c: number;
  precipitation: Precipitation;
}

/** The seven presets from feature-spec §3. */
export type WeatherPresetId =
  'cavok' | 'cat-i' | 'cat-ii' | 'cat-iii' | 'storm' | 'crosswind' | 'mountain-wave';

export interface WeatherPreset {
  id: WeatherPresetId;
  label: string;
  /** One line under the label on the tile. */
  description: string;
  /**
   * True for relative presets (crosswind): their wind is an offset from the active
   * runway heading and cannot be resolved without one, so the tile disables until
   * the Position panel has an airport and runway selected.
   */
  requires_runway: boolean;
  state: WeatherState;
}

/**
 * The instructor's edits on top of a staged preset — only the fields they actually
 * touched. Sparse on purpose: an untouched field must keep the preset's value.
 */
export type WeatherOverrides = Partial<
  Pick<
    WeatherState,
    | 'wind_layers'
    | 'cloud_layers'
    | 'visibility_m'
    | 'qnh_hpa'
    | 'temperature_c'
    | 'dewpoint_c'
  >
>;

/** The runway a relative preset resolves against, read from the Position panel. */
export interface RunwayRef {
  icao: string;
  ident: string;
}

/** What the apply mutation sends: intent, not resolved values (core/ resolves). */
export interface ApplyWeatherRequest {
  preset_id: WeatherPresetId;
  overrides: WeatherOverrides;
  /** Required by `requires_runway` presets; `null` otherwise. */
  runway: RunwayRef | null;
}
