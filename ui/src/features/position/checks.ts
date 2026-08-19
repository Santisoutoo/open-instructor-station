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

import { AIRWORK_MINIMUM_IAS_KT } from './airwork';
import { formatAltitudeFt, formatDistanceNm } from './format';
import type { FinalPlacementName } from './finals';
import { markerDistanceNm } from './markers';
import type { AirworkLevel, DesignTabId, MarkerId } from './positionDesignSlice';

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
  /** The gear as it will actually be applied — the merged setup, not the checkbox. */
  readonly gearDown: boolean | null;
  /** The speed as it will actually be applied. */
  readonly iasKt: number | null;
  readonly airworkLevel: AirworkLevel;
  readonly altitudeOverride: boolean;
  readonly altitudeOverrideFt: number;
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
      text: `Gear up ${formatDistanceNm(markerDistanceNm(inputs.marker, inputs.finalPlacement))} from the threshold`,
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

  // 4. Low IAS on the Airwork tab.
  if (
    inputs.activeTab === 'airwork' &&
    inputs.iasKt !== null &&
    inputs.iasKt < AIRWORK_MINIMUM_IAS_KT
  ) {
    result.push({
      dot: 'caution',
      text: `${String(Math.round(inputs.iasKt))} kt IAS at ${inputs.airworkLevel}`,
      note: 'Below a sustainable speed at that level for most aircraft',
    });
  }

  // 5. Altitude override active.
  if (inputs.altitudeOverride) {
    result.push({
      dot: 'caution',
      text: 'Altitude override active',
      note: `Replaces the altitude the placement resolved, with ${formatAltitudeFt(inputs.altitudeOverrideFt)}`,
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
