/**
 * The right rail's "Will be applied" rows.
 *
 * Every number here is the **server's**, taken from the preview `POST /api/position/preview`
 * returned, with the instructor's own edits merged on top exactly as the apply endpoint
 * will merge them. Nothing is re-derived: an altitude computed a second time on this side
 * of the wire would be a figure on screen that the aircraft never receives, and the whole
 * point of the rail is that it is a promise.
 *
 * Pure — no store access, no JSX, no fetching.
 */

import type { AircraftSetup, PlacementPreview } from '../../api/models';
import {
  formatAltitudeFt,
  formatHeadingTrue,
  formatIlsFrequency,
  formatSpeedKt,
} from './format';

export interface ApplyRow {
  readonly label: string;
  readonly value: string;
  readonly colour: 'default' | 'caution' | 'dim';
  readonly tag: string;
}

export interface ApplyRowInputs {
  /** `undefined` while the preview is loading, or when nothing resolves to a placement. */
  readonly preview: PlacementPreview | undefined;
  /** The preview's setup with the instructor's overrides merged over it. */
  readonly merged: AircraftSetup;
  /** Which keys the instructor set, so a row can say "overridden" rather than "computed". */
  readonly overridden: ReadonlySet<keyof AircraftSetup>;
}

/** Shown wherever the server has not answered yet. Never a zero, never a guess. */
const PENDING = 'not resolved';

function tagFor(
  overridden: ReadonlySet<keyof AircraftSetup>,
  field: keyof AircraftSetup,
  otherwise: string,
): string {
  return overridden.has(field) ? 'overridden' : otherwise;
}

/** The 7 rail rows, in the fixed order the design specifies. */
export function applyRows(inputs: ApplyRowInputs): readonly ApplyRow[] {
  const { preview, merged, overridden } = inputs;

  const altitudeFt =
    merged.altitude_ft ?? preview?.placement.position.altitude_ft ?? null;
  const headingDeg = merged.heading_deg ?? preview?.placement.heading_deg ?? null;
  const iasKt = merged.ias_kt ?? preview?.placement.ias_kt ?? null;
  const altitudeOverridden = overridden.has('altitude_ft');

  return [
    {
      label: 'Start position',
      value: preview?.placement.label ?? PENDING,
      colour: preview === undefined ? 'dim' : 'default',
      tag: 'navdata',
    },
    {
      label: 'Altitude',
      value: altitudeFt === null ? PENDING : formatAltitudeFt(altitudeFt),
      colour: altitudeOverridden ? 'caution' : altitudeFt === null ? 'dim' : 'default',
      tag: altitudeOverridden ? 'overridden' : 'computed',
    },
    {
      label: 'Heading',
      value: headingDeg === null ? PENDING : formatHeadingTrue(headingDeg),
      colour: headingDeg === null ? 'dim' : 'default',
      tag: tagFor(overridden, 'heading_deg', 'computed'),
    },
    {
      label: 'IAS',
      value: iasKt === null ? PENDING : formatSpeedKt(iasKt),
      colour: iasKt === null ? 'dim' : 'default',
      tag: tagFor(overridden, 'ias_kt', 'computed'),
    },
    gearRow(merged, overridden),
    flapsRow(merged, overridden),
    navRadiosRow(merged, overridden),
  ];
}

function gearRow(
  merged: AircraftSetup,
  overridden: ReadonlySet<keyof AircraftSetup>,
): ApplyRow {
  if (merged.gear_down == null) {
    return { label: 'Landing gear', value: 'unchanged', colour: 'dim', tag: 'computed' };
  }
  return {
    label: 'Landing gear',
    value: merged.gear_down ? 'down' : 'up',
    colour: merged.gear_down ? 'default' : 'caution',
    tag: tagFor(overridden, 'gear_down', 'computed'),
  };
}

function flapsRow(
  merged: AircraftSetup,
  overridden: ReadonlySet<keyof AircraftSetup>,
): ApplyRow {
  if (merged.flaps_ratio == null) {
    return { label: 'Flaps', value: 'unchanged', colour: 'dim', tag: 'computed' };
  }
  return {
    label: 'Flaps',
    value: `${String(Math.round(merged.flaps_ratio * 100))} %`,
    colour: 'default',
    tag: tagFor(overridden, 'flaps_ratio', 'computed'),
  };
}

/**
 * NAV1 and the OBS as they will actually stand after the merge.
 *
 * "not sent" is the honest word for an empty frequency: this row reports the merged setup,
 * not the switch. A final tunes its own radios whatever the switch says, and a circuit leg
 * tunes none unless the switch adds them.
 */
function navRadiosRow(
  merged: AircraftSetup,
  overridden: ReadonlySet<keyof AircraftSetup>,
): ApplyRow {
  const frequencyKhz = merged.nav1_freq_khz ?? merged.ils_freq_khz ?? null;
  if (frequencyKhz == null) {
    return { label: 'Nav radios', value: 'not sent', colour: 'dim', tag: 'unavailable' };
  }
  const course = merged.obs1_deg;
  const courseText =
    course == null ? '' : ` · CRS ${String(Math.round(course)).padStart(3, '0')}`;
  return {
    label: 'Nav radios',
    value: `ILS ${formatIlsFrequency(frequencyKhz)}${courseText}`,
    colour: 'default',
    tag: overridden.has('nav1_freq_khz') ? 'from navdata' : 'from the placement',
  };
}
