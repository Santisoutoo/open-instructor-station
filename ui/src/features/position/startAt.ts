/**
 * What the two Start-at triggers — the header's and the bottom bar's — share: the popover
 * id each points `aria-controls` at, and the one-line "where the aircraft starts" text, so
 * the two never disagree about what is selected.
 */

import type { StartAtAnchor } from './positionDesignSlice';

/** The popover's DOM id for one anchor. */
export function startAtPopoverId(anchor: StartAtAnchor): string {
  return `pos-startat-popover-${anchor}`;
}

export function startAtLabelOf(
  selectedRunway: string | null,
  selectedStand: string | null,
): string {
  if (selectedStand !== null) {
    return `Stand ${selectedStand}`;
  }
  if (selectedRunway !== null) {
    return `Runway ${selectedRunway}`;
  }
  return 'Not set';
}
