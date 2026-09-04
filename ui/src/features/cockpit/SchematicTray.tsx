/**
 * The sticky tray under the schematic board (issue #253, design §2): the full widget
 * for the focused control. A ~220 px rotary editor cannot sit inside a knob slot on a
 * tablet, so the slot focuses and the tray edits — `ControlRow` for a live control,
 * `ParkedRow` (with its reason) for a parked one, a hint while nothing is focused.
 */

import type { CockpitControlSpec, CockpitValue, ParkedControl } from '../../api/models';
import { ControlRow, type ActuationBody } from './ControlRow';
import type { LayoutSlot } from './layouts';
import { ParkedRow } from './ParkedRow';
import type { RotaryDraftHandle } from './widgets/rotary';

export type TrayFocus =
  | { readonly spec: CockpitControlSpec; readonly slot: LayoutSlot | undefined }
  | { readonly parked: ParkedControl };

export interface SchematicTrayProps {
  focused: TrayFocus | null;
  value: CockpitValue | null | undefined;
  hints: readonly string[];
  pending: boolean;
  onCommit: (body: ActuationBody) => void;
  /** `CockpitPanel`'s rotary draft, so the tray edits the same draft the slot's wheel does. */
  draft?: RotaryDraftHandle;
}

/** Labels of the slot's spring-back positions, resolved through the spec's options. */
function momentaryLabels(
  spec: CockpitControlSpec,
  slot: LayoutSlot | undefined,
): string[] {
  const momentary = slot?.momentary ?? [];
  return momentary.map(
    (value) =>
      spec.options?.find((option) => option.value === value)?.label ?? String(value),
  );
}

export function SchematicTray({
  focused,
  value,
  hints,
  pending,
  onCommit,
  draft,
}: SchematicTrayProps) {
  if (focused === null) {
    return (
      <div className="schematic__tray">
        <p className="schematic__tray-hint">Tap a control on the diagram</p>
      </div>
    );
  }

  if ('parked' in focused) {
    return (
      <div className="schematic__tray">
        <ParkedRow entry={focused.parked} />
      </div>
    );
  }

  const springs = momentaryLabels(focused.spec, focused.slot);
  return (
    <div className="schematic__tray">
      <ControlRow
        spec={focused.spec}
        value={value}
        hints={hints}
        pending={pending}
        onCommit={onCommit}
        {...(draft !== undefined ? { draft } : {})}
        {...(focused.slot !== undefined ? { layout: focused.slot } : {})}
      />
      {springs.length > 0 && (
        <p className="schematic__tray-note">{springs.join(', ')} springs back</p>
      )}
    </div>
  );
}
