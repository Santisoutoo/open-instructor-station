/**
 * The right rail's "Checks" list — evaluated in a fixed order, always ending in one
 * passing check. The order matters: the rail renders the array as-is, so tests assert the
 * whole sequence rather than membership.
 */

import { formatAltitudeFt, formatDistanceNm } from './format';
import { CIRCUIT_MARKERS } from './markers';
import type { MarkerId, PositionDesignState } from './positionDesignSlice';
import { resolveAltitudeFt } from './applyRows';
import { RECIPROCAL_RUNWAY, RUNWAYS, SAMPLE_WIND } from './sampleData';
import { windComponents } from './wind';

export type CheckDot = 'caution' | 'info' | 'accent';

export interface Check {
  readonly dot: CheckDot;
  readonly text: string;
  readonly note: string;
}

const GEAR_UP_MARKERS: ReadonlySet<MarkerId> = new Set([
  'final-3nm',
  'final-8nm',
  'base-left',
  'base-right',
  'vectors-left',
  'vectors-right',
]);

/** The ordered rule list. Every rule but the last is conditional; the last always passes. */
export function checks(state: PositionDesignState): readonly Check[] {
  const result: Check[] = [];

  // 1. Tailwind on the selected runway, no stand selected.
  if (state.selectedRunway !== null && state.selectedStand === null) {
    const runway = RUNWAYS[state.selectedRunway];
    if (runway.kind === 'runway') {
      const { tail } = windComponents(
        SAMPLE_WIND.directionDeg,
        SAMPLE_WIND.speedKt,
        runway.courseDeg,
      );
      if (tail >= 3) {
        const reciprocal = RECIPROCAL_RUNWAY[state.selectedRunway];
        result.push({
          dot: 'caution',
          text: `Tailwind ${String(tail)} kt on ${state.selectedRunway}`,
          note:
            reciprocal !== undefined
              ? `${reciprocal} is the favoured runway for this wind`
              : 'Check the wind before starting',
        });
      }
    }
  }

  // 2. Gear up on a final/base/vectors marker, Approach tab, no stand selected.
  if (
    state.activeTab === 'approach' &&
    state.selectedStand === null &&
    !state.config.gearDown &&
    GEAR_UP_MARKERS.has(state.selectedMarker)
  ) {
    const marker = CIRCUIT_MARKERS[state.selectedMarker];
    result.push({
      dot: 'caution',
      text: `Gear up ${formatDistanceNm(marker.distNm)} from the threshold`,
      note: 'Tick "Gear down" to spawn configured for landing',
    });
  }

  // 3. ILS toggle on but the selected runway has no ILS.
  if (state.send.ilsFrequency && state.selectedRunway !== null) {
    const runway = RUNWAYS[state.selectedRunway];
    const hasIls = runway.kind === 'runway' && runway.ils !== null;
    if (!hasIls) {
      result.push({
        dot: 'info',
        text: `No ILS on ${state.selectedRunway}`,
        note: 'The frequency will be skipped when the position is set',
      });
    }
  }

  // 4. Low IAS on the Airwork tab.
  if (state.activeTab === 'airwork' && state.config.iasKt < 150) {
    result.push({
      dot: 'caution',
      text: `${String(state.config.iasKt)} kt IAS at ${state.airworkLevel}`,
      note: 'Below a sustainable speed at that level for most aircraft',
    });
  }

  // 5. Altitude override active.
  if (state.config.altitudeOverride) {
    result.push({
      dot: 'caution',
      text: 'Altitude override active',
      note: `Replaces the computed ${formatAltitudeFt(resolveAltitudeFt(state))}`,
    });
  }

  // 6. A stand is selected.
  if (state.selectedStand !== null) {
    result.push({
      dot: 'info',
      text: `Starting from stand ${state.selectedStand}`,
      note: 'Circuit and procedure positions are ignored while a stand is selected',
    });
  }

  // 7. Always last, always passing.
  result.push({
    dot: 'accent',
    text: 'Position inside the LFMN CTR',
    note: 'Terrain and airspace check passed with sample data',
  });

  return result;
}
