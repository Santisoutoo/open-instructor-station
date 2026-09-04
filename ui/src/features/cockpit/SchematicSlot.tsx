/**
 * The HTML overlay for one layout slot (issue #253, design §2/§3): caption, confirmed
 * readout, the draft line and the ≥ 44 px transparent hit button, absolutely positioned
 * at the slot's `%` box so it lands exactly on the SVG glyph underneath.
 *
 * What a tap does depends on the catalog `kind`, never on the drawn shape:
 *
 * - toggle → commit the flipped value; press → commit `{}`;
 * - selector with exactly two options and a known position → commit the other one; any
 *   other selector → focus (the tray shows every option);
 * - dial / encoder → focus; the wheel and the keys edit the **parent-owned draft** and
 *   nothing is written until `Enter` (`onCommitDraft`) — design rule "no drag ever moves
 *   the student";
 * - parked → focus only, so the tray can show the reason. Never a commit.
 *
 * Every readout shows the **confirmed** value from the snapshot; the draft is a separate
 * accent line, never mixed into the readout.
 */

import { useRef, type KeyboardEvent } from 'react';
import type { CockpitControlSpec, CockpitValue, ParkedControl } from '../../api/models';
import type { ActuationBody } from './ControlRow';
import type { SlotState } from './glyphs';
import { slotRect, type LayoutSlot, type PanelLayout } from './layouts';
import {
  dialDraftValue,
  encoderDraftText,
  formatReadout,
  rotaryKeyAction,
  type RotaryDraft,
} from './widgets/rotary';
import { useWheelNotches } from './widgets/useWheelNotches';

/** The catalog entry a slot renders: exactly one of a live control or a parked one. */
export type SlotEntry =
  | { readonly kind: 'control'; readonly spec: CockpitControlSpec }
  | { readonly kind: 'parked'; readonly parked: ParkedControl };

export interface SchematicSlotProps {
  slot: LayoutSlot;
  viewBox: PanelLayout['viewBox'];
  entry: SlotEntry;
  /** The confirmed value from the snapshot, or `null`/`undefined` when unread. */
  value: CockpitValue | null | undefined;
  /** Unmet-precondition hints, informational only (the server's 409 is the gate). */
  hints: readonly string[];
  pending: boolean;
  /** Index into `spec.options` of the confirmed value, `-1` when unknown. */
  optionIndex: number;
  state: SlotState;
  focused: boolean;
  draft: RotaryDraft;
  onFocus: (controlId: string | null) => void;
  onCommit: (controlId: string, body: ActuationBody) => void;
  onNudge: (
    spec: CockpitControlSpec,
    slot: LayoutSlot,
    sign: 1 | -1,
    count: number,
  ) => void;
  onDraftText: (spec: CockpitControlSpec, text: string) => void;
  onCommitDraft: (spec: CockpitControlSpec, slot: LayoutSlot) => void;
  onDiscardDraft: (spec: CockpitControlSpec) => void;
}

function isRotary(spec: CockpitControlSpec): boolean {
  return spec.kind === 'dial' || spec.kind === 'encoder';
}

/** The confirmed value as the readout shows it, or `null` for a kind with no readout. */
function readoutText(
  spec: CockpitControlSpec,
  slot: LayoutSlot,
  value: CockpitValue | null | undefined,
  optionIndex: number,
): string | null {
  switch (spec.kind) {
    case 'toggle':
      return value === true
        ? spec.on_label
        : value === false
          ? spec.off_label
          : 'Unknown';
    case 'selector':
      return spec.options?.[optionIndex]?.label ?? 'Unknown';
    case 'dial':
    case 'encoder':
      return formatReadout(typeof value === 'number' ? value : null, spec, slot);
    case 'press':
      return null;
    default: {
      const exhaustive: never = spec.kind;
      throw new Error(`Unhandled cockpit control kind: ${String(exhaustive)}`);
    }
  }
}

/** The draft line for a rotary control, or `null` when the draft is not this slot's. */
function draftText(
  spec: CockpitControlSpec,
  slot: LayoutSlot,
  value: CockpitValue | null | undefined,
  draft: RotaryDraft,
): string | null {
  if (draft.controlId !== spec.control_id) {
    return null;
  }
  if (spec.kind === 'dial') {
    if (draft.text.trim() === '') {
      return null;
    }
    const parsed = dialDraftValue(spec, slot, draft.text);
    return parsed === null ? draft.text : formatReadout(parsed, spec, slot);
  }
  if (spec.kind === 'encoder') {
    return encoderDraftText(
      typeof value === 'number' ? value : null,
      draft.clicks,
      spec,
      slot.format,
    );
  }
  return null;
}

export function SchematicSlot({
  slot,
  viewBox,
  entry,
  value,
  hints,
  pending,
  optionIndex,
  state,
  focused,
  draft,
  onFocus,
  onCommit,
  onNudge,
  onDraftText,
  onCommitDraft,
  onDiscardDraft,
}: SchematicSlotProps) {
  const hitRef = useRef<HTMLButtonElement>(null);
  const spec = entry.kind === 'control' ? entry.spec : null;
  const parked = entry.kind === 'parked' ? entry.parked : null;
  const controlId = slot.control_id;
  const label = spec?.label ?? parked?.label ?? controlId;

  const wheelEnabled = spec !== null && isRotary(spec) && !pending;
  useWheelNotches(
    hitRef,
    (sign, count) => {
      if (spec !== null) {
        onFocus(controlId);
        onNudge(spec, slot, sign, count);
      }
    },
    wheelEnabled,
  );

  const tap = () => {
    if (spec === null) {
      // Parked: the tray shows the reason. Nothing is ever written.
      onFocus(controlId);
      return;
    }
    switch (spec.kind) {
      case 'toggle':
        onCommit(controlId, { value: !(typeof value === 'boolean' && value) });
        return;
      case 'press':
        onCommit(controlId, {});
        return;
      case 'selector': {
        const options = spec.options ?? [];
        const other =
          options.length === 2 && optionIndex >= 0 ? options[1 - optionIndex] : null;
        if (other === null || other === undefined) {
          onFocus(controlId);
          return;
        }
        onCommit(controlId, { value: other.value });
        return;
      }
      case 'dial':
      case 'encoder':
        onFocus(controlId);
        return;
      default: {
        const exhaustive: never = spec.kind;
        throw new Error(`Unhandled cockpit control kind: ${String(exhaustive)}`);
      }
    }
  };

  const keyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (spec === null || !isRotary(spec)) {
      return;
    }
    const action = rotaryKeyAction(event.key, spec, slot);
    if (action === null) {
      return;
    }
    // Chrome fires the button's click on Enter *keydown*; preventing every mapped key here
    // is what keeps a commit from double-firing through `tap` and the page from scrolling
    // under the arrows.
    event.preventDefault();
    switch (action.kind) {
      case 'nudge':
        onFocus(controlId);
        onNudge(spec, slot, action.sign, action.count);
        return;
      case 'text':
        onFocus(controlId);
        onDraftText(spec, action.text);
        return;
      case 'commit':
        onCommitDraft(spec, slot);
        return;
      case 'discard':
        onDiscardDraft(spec);
        return;
    }
  };

  const readout = spec === null ? null : readoutText(spec, slot, value, optionIndex);
  const draftLine = spec === null ? null : draftText(spec, slot, value, draft);
  const title =
    parked !== null ? parked.reason : hints.length > 0 ? hints.join('; ') : null;

  return (
    <div
      className={`schematic__slot${focused ? ' schematic__slot--focused' : ''}`}
      style={slotRect(slot, viewBox)}
      data-control-id={controlId}
      data-shape={slot.shape}
      data-label-side={slot.labelSide ?? 'above'}
      data-state={state}
      data-focused={focused ? 'true' : 'false'}
    >
      <span className="schematic__caption" aria-hidden="true">
        {slot.caption ?? label}
      </span>
      {readout !== null && <output className="schematic__readout">{readout}</output>}
      {draftLine !== null && <span className="schematic__draft">{draftLine}</span>}
      <button
        ref={hitRef}
        type="button"
        className="schematic__hit"
        aria-label={label}
        disabled={pending}
        onClick={tap}
        onKeyDown={keyDown}
        {...(spec?.kind === 'toggle' ? { 'aria-pressed': value === true } : {})}
        {...(parked !== null ? { 'aria-disabled': true } : {})}
        {...(title !== null ? { title } : {})}
      />
    </div>
  );
}
