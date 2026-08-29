/**
 * The right rail's "Checks" list — evaluated in a fixed order, from real data only.
 *
 * The order matters: the rail renders the array as-is, so the tests assert the whole
 * sequence rather than membership.
 *
 * **The v3 mockup's seventh check is gone.** It read "Position inside the LFMN CTR ·
 * terrain and airspace check passed with sample data" and it passed unconditionally,
 * because there was no airspace source behind it and there still is not. A check that
 * always passes teaches an instructor to stop reading the list, which is worse than having
 * one fewer check; it comes back the day this station can answer the question.
 *
 * Pure — every input arrives as an argument, so this is testable without a store or a fetch.
 */

import { formatAltitudeFt, formatDistanceNm, formatSpeedKt } from './format';
import type { FinalPlacementName } from './finals';
import { markerDistanceNm } from './markers';
import type { DesignTabId, EditableDistanceMarkerId, MarkerId } from './positionDesignSlice';
import { isAirborne, sustainableIasKt } from './speed';

export type CheckDot = 'caution' | 'info' | 'accent';

export interface Check {
  readonly dot: CheckDot;
  readonly text: string;
  readonly note: string;
}

/** A tailwind at or above this is worth naming. */
export const TAILWIND_CAUTION_KT = 3;

const GEAR_UP_MARKERS: ReadonlySet<MarkerId> = new Set([
  'final-3nm',
  'final-8nm',
  'base-left',
  'base-right',
  'vectors-left',
  'vectors-right',
]);

export interface CheckInputs {
  readonly runwayIdent: string | null;
  /** The other end of the same strip, from navdata. `null` when the source has none. */
  readonly reciprocalIdent: string | null;
  /** Tailwind component on the selected runway, knots. `null` when the wind is unknown. */
  readonly tailwindKt: number | null;
  /** `true`/`false` once known, `null` while the ILS lookup is still in flight. */
  readonly hasIls: boolean | null;
  readonly sendIls: boolean;
  readonly standName: string | null;
  readonly activeTab: DesignTabId;
  readonly marker: MarkerId;
  readonly finalPlacement: FinalPlacementName;
  /** The instructor's edits to the circuit markers' distances — `markerDistanceNm`'s overrides. */
  readonly markerDistances: Partial<Record<EditableDistanceMarkerId, number>>;
  /** The gear as it will actually be applied — the merged setup, not the checkbox. */
  readonly gearDown: boolean | null;
  /** The speed as it will actually be applied. */
  readonly iasKt: number | null;
  /** The altitude as it will actually be applied, feet MSL. */
  readonly altitudeFt: number | null;
  /** Field elevation under the placement, feet MSL, when an airport is loaded. */
  readonly groundElevationFt: number | null;
  readonly altitudeOverride: boolean;
  /** `null` = ticked but not yet typed — the "5. Altitude override active" rule stays quiet. */
  readonly altitudeOverrideFt: number | null;
}

/** The ordered rule list. Every rule is conditional; an empty list means nothing to say. */
export function checks(inputs: CheckInputs): readonly Check[] {
  const result: Check[] = [];

  // 1. Tailwind on the selected runway, no stand selected.
  if (
    inputs.runwayIdent !== null &&
    inputs.standName === null &&
    inputs.tailwindKt !== null &&
    inputs.tailwindKt >= TAILWIND_CAUTION_KT
  ) {
    result.push({
      dot: 'caution',
      text: `Tailwind ${String(inputs.tailwindKt)} kt on ${inputs.runwayIdent}`,
      note:
        inputs.reciprocalIdent !== null
          ? `${inputs.reciprocalIdent} is the favoured runway for this wind`
          : 'Check the wind before starting',
    });
  }

  // 2. Gear up on a final/base/vectors marker, Approach tab, no stand selected.
  if (
    inputs.activeTab === 'approach' &&
    inputs.standName === null &&
    inputs.gearDown === false &&
    GEAR_UP_MARKERS.has(inputs.marker)
  ) {
    result.push({
      dot: 'caution',
      text: `Gear up ${formatDistanceNm(markerDistanceNm(inputs.marker, inputs.finalPlacement, inputs.markerDistances))} from the threshold`,
      note: 'Tick "Gear down" to spawn configured for landing',
    });
  }

  // 3. ILS switch on but the selected runway publishes none.
  if (inputs.sendIls && inputs.runwayIdent !== null && inputs.hasIls === false) {
    result.push({
      dot: 'info',
      text: `No ILS on ${inputs.runwayIdent}`,
      note: 'The frequency will be skipped when the position is set',
    });
  }

  // 4. An airborne placement below a sustainable speed — on any tab.
  //
  // Not tab-scoped, and it must not be: the two placements that resolve to 0 kt are the two
  // *coordinate* ones, and the Custom location tab sends one of those as readily as Airwork
  // does. A final or a circuit leg arrives with the speed `Placement.to_setup()` worked out
  // from the aircraft's approach category, so this stays quiet on them.
  if (
    inputs.iasKt !== null &&
    inputs.altitudeFt !== null &&
    isAirborne(inputs) &&
    inputs.iasKt < sustainableIasKt(inputs.altitudeFt)
  ) {
    result.push({
      dot: 'caution',
      text: `${formatSpeedKt(inputs.iasKt)} IAS at ${formatAltitudeFt(inputs.altitudeFt)}`,
      note: 'Below a sustainable speed at that altitude for most aircraft',
    });
  }

  // 5. Altitude override active.
  if (inputs.altitudeOverride) {
    result.push({
      dot: 'caution',
      text: 'Altitude override active',
      note:
        inputs.altitudeOverrideFt === null
          ? 'Replaces the altitude the placement resolved — no value typed yet'
          : `Replaces the altitude the placement resolved, with ${formatAltitudeFt(inputs.altitudeOverrideFt)}`,
    });
  }

  // 6. A stand is selected, so nothing airborne applies.
  if (inputs.standName !== null) {
    result.push({
      dot: 'info',
      text: `Starting from stand ${inputs.standName}`,
      note: 'Circuit and procedure positions are ignored while a stand is selected',
    });
  }

  return result;
}
