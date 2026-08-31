/**
 * PROVISIONAL mock-only view models — replace with generated schema.d.ts types at
 * backend integration; never import outside this feature.
 *
 * These describe what the Landing Analysis manager *will* serve (feature-spec §11): a
 * recorded approach as timestamped frames plus the computed `LandingReport`. Once the
 * FastAPI endpoints and the `core/` analysis exist, `npm run generate:api` produces the
 * real types and this file dies.
 */

/** The four recorded demo landings. */
export type LandingId = 'good' | 'firm' | 'floated' | 'off-centre';

/**
 * One frame of the recorded approach. The real recorder runs at 10–20 Hz; the mock
 * serves 4 Hz, which is enough to draw and keeps fixtures small.
 */
export interface TraceSample {
  /** Seconds since the start of the recording window. */
  t_s: number;
  /** Indicated airspeed. The mock assumes still air, so IAS ≈ ground speed. */
  ias_kt: number;
  /** Height above the runway. Exactly 0 after touchdown. */
  altitude_agl_ft: number;
  /** Vertical speed, negative descending. 0 on the ground. */
  vs_fpm: number;
  pitch_deg: number;
  roll_deg: number;
  /** Localizer deviation in dots, positive right of centreline. */
  loc_dev_dot: number;
  /** Glideslope deviation in dots, positive above the slope. */
  gs_dev_dot: number;
  /** Along-track distance in metres, 0 at the threshold, negative before it. */
  distance_from_threshold_m: number;
}

/** The ten debrief numbers from feature-spec §11, computed per landing. */
export interface LandingReport {
  /** Sink rate at the touchdown instant, negative (fpm). */
  touchdown_vs_fpm: number;
  /** Peak normal load factor, 1.0 = level flight. */
  peak_g: number;
  pitch_at_touchdown_deg: number;
  roll_at_touchdown_deg: number;
  /** Lateral offset from the centreline at touchdown, metres, positive right. */
  centreline_offset_m: number;
  flare_duration_s: number;
  /** Distance covered nearly level in the flare, metres. 0 for a positive touchdown. */
  float_distance_m: number;
  /** Touchdown point measured from the threshold, metres. */
  touchdown_distance_m: number;
  ias_at_threshold_kt: number;
  /** Heading minus runway heading at touchdown, degrees, positive right. */
  heading_vs_runway_deg: number;
}

/** One recorded landing: identity, the trace, and the report derived from it. */
export interface Landing {
  id: LandingId;
  /** Short selector label, e.g. `Firm`. */
  label: string;
  /** One line under the label, e.g. `Late flare, firm touchdown`. */
  description: string;
  /** Where it was flown, e.g. `LEMD 32L`. */
  runway: string;
  /** Deterministic ISO instant — the mock never reads a clock. */
  recorded_at: string;
  samples: TraceSample[];
  /** Index of the first on-ground sample in `samples`. */
  touchdownIndex: number;
  report: LandingReport;
}
