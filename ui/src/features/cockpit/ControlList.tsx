import type { CockpitControlSpec, ParkedControl } from '../../api/models';
import type { ControlStateMap } from './filter';
import { unmetHints } from './filter';
import { ControlRow, type ActuationBody } from './ControlRow';
import { ParkedRow } from './ParkedRow';

export interface ControlListProps {
  controls: readonly CockpitControlSpec[];
  parked: readonly ParkedControl[];
  states: ControlStateMap;
  pending: Readonly<Record<string, true>>;
  emptyMessage: string;
  onCommit: (controlId: string, body: ActuationBody) => void | Promise<boolean>;
}

/**
 * Rows for the selected panel, or the search hits, plus every parked entry the same
 * scoping selected. No virtualisation (design §7.1: "revisit only if measured" — the Fake
 * catalog is eleven controls, and even the eventual Zibo catalog is simple DOM).
 */
export function ControlList({
  controls,
  parked,
  states,
  pending,
  emptyMessage,
  onCommit,
}: ControlListProps) {
  if (controls.length === 0 && parked.length === 0) {
    return <p className="cockpit-empty">{emptyMessage}</p>;
  }

  return (
    <div className="cockpit-list">
      {controls.map((spec) => (
        <ControlRow
          key={spec.control_id}
          spec={spec}
          value={states[spec.control_id]}
          hints={unmetHints(spec, states)}
          pending={pending[spec.control_id] === true}
          onCommit={(body) => {
            onCommit(spec.control_id, body);
          }}
        />
      ))}
      {parked.map((entry) => (
        <ParkedRow key={entry.control_id} entry={entry} />
      ))}
    </div>
  );
}
