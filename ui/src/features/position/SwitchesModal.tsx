/**
 * The "Airplane switches" placeholder — a scaffolded entry point only.
 *
 * The interactive cockpit-layout design (which switch lives where, and how it rides into
 * `AircraftSetup`) is explicitly deferred to a later, separate `planner` pass. This panel
 * carries no state, no fetch and no wiring into the apply payload — dismissing it leaves
 * `applyPlacement`'s request body identical to what it would have been without it.
 */

import type { RefObject } from 'react';
import { useAppDispatch, useAppSelector } from '../../store';
import { Popover } from './Popover';
import { switchesModalToggled } from './positionDesignSlice';

export function SwitchesModal({
  triggerRef,
}: {
  readonly triggerRef: RefObject<HTMLElement | null>;
}) {
  const dispatch = useAppDispatch();
  const open = useAppSelector((state) => state.positionDesign.switchesModalOpen);

  return (
    <Popover
      id="pos-switches-modal"
      open={open}
      onClose={() => {
        dispatch(switchesModalToggled());
      }}
      triggerRef={triggerRef}
      className="pos-popover pos-switchesmodal"
    >
      <h2 className="pos-switchesmodal__title">Airplane switches</h2>
      <p className="pos-switchesmodal__body">Aircraft layout — coming soon.</p>
    </Popover>
  );
}
