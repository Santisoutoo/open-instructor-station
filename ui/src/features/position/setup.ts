/**
 * The instructor's edits, as the sparse `AircraftSetup` the apply endpoint merges.
 *
 * `POST /api/position/apply` merges the body's `setup` **over** the preview's own, field by
 * field, with `exclude_none` — so this object can only ever *add* to or *replace* what the
 * geometry resolved. It cannot unset anything, and this module does not pretend it can:
 * an untouched field is simply absent, and the preview's value stands.
 *
 * That asymmetry is also what the "sent with the position" switches mean. A final
 * already arrives with NAV1 and the OBS tuned (`Placement.to_setup()` does it from the
 * runway's published ILS, so no caller can place an aircraft on an approach with cold
 * radios). Ticking "ILS frequency" is what tunes them for the placements that do *not* get
 * it for free — a circuit leg, a threshold — and unticking it leaves the placement's own
 * configuration alone rather than stripping it.
 */

import type { AircraftSetup, Ils, PlacementPreview } from '../../api/models';
import type { AircraftConfigState, SendWithPositionState } from './positionDesignSlice';

/** What the instructor changed, and therefore what is sent. */
export interface InstructorSetup {
  readonly overrides: AircraftSetup;
  /** The keys `overrides` carries, for the rail's provenance tags. */
  readonly overridden: ReadonlySet<keyof AircraftSetup>;
}

/**
 * Build the sparse override from the bottom bar's state.
 *
 * `ils` is read but never *derived from*: the frequency and the course are the ones navdata
 * published. Nothing in this file computes a value the server could have computed.
 */
export function instructorSetup(
  config: AircraftConfigState,
  send: SendWithPositionState,
  ils: Ils | null,
): InstructorSetup {
  const overrides: AircraftSetup = {};

  if (config.iasKt !== null) {
    overrides.ias_kt = config.iasKt;
  }
  if (config.pitchDeg !== null) {
    overrides.pitch_deg = config.pitchDeg;
  }
  if (config.gearDown !== null) {
    overrides.gear_down = config.gearDown;
  }
  if (config.flapsPercent !== null) {
    overrides.flaps_ratio = config.flapsPercent / 100;
  }
  if (config.altitudeOverride) {
    overrides.altitude_ft = config.altitudeOverrideFt;
  }
  // The OBS is a MAGNETIC course (AircraftSetup.obs1_deg says so), and the only magnetic
  // course on this screen is the one the ILS publishes. A runway's true bearing is not it,
  // and there is no variation here to convert with — so with no ILS, nothing is sent.
  if (send.course && ils !== null) {
    overrides.obs1_deg = ils.localizer_mag_deg;
  }
  if (send.ilsFrequency && ils !== null) {
    overrides.nav1_freq_khz = ils.frequency_khz;
    overrides.ils_freq_khz = ils.frequency_khz;
  }

  return {
    overrides,
    overridden: new Set(Object.keys(overrides) as (keyof AircraftSetup)[]),
  };
}

/** What will actually be applied: the geometry's setup with the instructor's edits on top. */
export function mergedSetup(
  preview: PlacementPreview | undefined,
  overrides: AircraftSetup,
): AircraftSetup {
  return { ...(preview?.setup ?? {}), ...overrides };
}

/** `null` when nothing was edited — the wire's way of saying "apply the preview verbatim". */
export function overridesOrNull(overrides: AircraftSetup): AircraftSetup | null {
  return Object.keys(overrides).length === 0 ? null : overrides;
}
