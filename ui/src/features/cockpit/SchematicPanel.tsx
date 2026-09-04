/**
 * One panel drawn as a schematic (issue #253, design §2).
 *
 * Folds the catalog entries of the active panel into the layout: every layout slot whose
 * id the catalog knows becomes a glyph (`SchematicSvg`) plus an HTML overlay
 * (`SchematicSlot`) at the same `%` box; catalog entries the layout does not place fall
 * into a "Not on the diagram" strip rendered with the plain `ControlList`. The catalog
 * decides what exists, the layout only where it is drawn — a slot the catalog lacks is
 * simply skipped.
 *
 * Nothing here owns state: the confirmed values, the pending lock, the focus and the
 * rotary draft all arrive as props from `CockpitPanel`, which also owns the one write.
 */

import { useMemo } from 'react';
import type { CockpitControlSpec, CockpitValue, ParkedControl } from '../../api/models';
import { ControlList } from './ControlList';
import type { ActuationBody } from './ControlRow';
import {
  selectedOptionIndex,
  splitByLayout,
  unmetHints,
  type ControlStateMap,
} from './filter';
import type { GlyphModel, SlotState } from './glyphs';
import { slotIndex, type LayoutSlot, type PanelLayout } from './layouts';
import { SchematicSlot, type SlotEntry } from './SchematicSlot';
import { SchematicSvg } from './SchematicSvg';
import type { RotaryDraft } from './widgets/rotary';
import './schematic.css';

export interface SchematicPanelProps {
  layout: PanelLayout;
  /** This panel's live controls, in catalog order. */
  controls: readonly CockpitControlSpec[];
  /** This panel's parked entries. */
  parked: readonly ParkedControl[];
  states: ControlStateMap;
  pending: Readonly<Record<string, true>>;
  focusedId: string | null;
  /** A view of the parent-owned rotary draft (`widgets/rotary`). */
  draft: RotaryDraft;
  onFocus: (controlId: string | null) => void;
  /** Taps: toggles, presses and two-position selectors commit straight from the slot. */
  onCommit: (controlId: string, body: ActuationBody) => void;
  /** Wheel notches / arrow keys on a rotary slot edit the draft. */
  onNudge: (
    spec: CockpitControlSpec,
    slot: LayoutSlot,
    sign: 1 | -1,
    count: number,
  ) => void;
  /** `Home`/`End` on a dial slot. */
  onDraftText: (spec: CockpitControlSpec, text: string) => void;
  /** `Enter` on a rotary slot. */
  onCommitDraft: (spec: CockpitControlSpec, slot: LayoutSlot) => void;
  /** `Escape`. */
  onDiscardDraft: () => void;
}

/** Everything one slot needs, computed once per render and shared by both layers. */
interface RenderedSlot {
  readonly slot: LayoutSlot;
  readonly entry: SlotEntry;
  readonly value: CockpitValue | null | undefined;
  readonly hints: readonly string[];
  readonly pending: boolean;
  readonly optionIndex: number;
  readonly glyph: GlyphModel;
}

function clamp01(ratio: number): number {
  return Math.min(1, Math.max(0, ratio));
}

/** `[0, 1]` position of `value` inside the spec's range, or `null` without a finite range. */
function rangeRatio(spec: CockpitControlSpec, value: number): number | null {
  const min = spec.min_value;
  const max = spec.max_value;
  if (min == null || max == null || !(max > min)) {
    return null;
  }
  return clamp01((value - min) / (max - min));
}

/** The pointer/handle position: a dial over its range, a selector over its stops. */
function pointerRatio(
  spec: CockpitControlSpec,
  value: CockpitValue | null | undefined,
  optionIndex: number,
): number | null {
  if (spec.kind === 'selector') {
    const count = spec.options?.length ?? 0;
    return optionIndex >= 0 && count > 1 ? clamp01(optionIndex / (count - 1)) : null;
  }
  if ((spec.kind === 'dial' || spec.kind === 'encoder') && typeof value === 'number') {
    return rangeRatio(spec, value);
  }
  return null;
}

/** Detent stops as fractions of the spec range (the lever's ticks), falling back to the detents' own span. */
function detentRatios(spec: CockpitControlSpec, slot: LayoutSlot): readonly number[] {
  const detents = slot.detents ?? [];
  if (detents.length === 0) {
    return [];
  }
  const values = detents.map((detent) => detent.value);
  const min = spec.min_value ?? Math.min(...values);
  const max = spec.max_value ?? Math.max(...values);
  if (!(max > min)) {
    return [];
  }
  return values.map((value) => clamp01((value - min) / (max - min)));
}

/** Single-attribute state with precedence `parked` > `pending` > `unmet` > value. */
function slotState(
  entry: SlotEntry,
  value: CockpitValue | null | undefined,
  hints: readonly string[],
  pending: boolean,
  optionIndex: number,
): SlotState {
  if (entry.kind === 'parked') {
    return 'parked';
  }
  if (pending) {
    return 'pending';
  }
  if (hints.length > 0) {
    return 'unmet';
  }
  switch (entry.spec.kind) {
    case 'toggle':
      return value === true ? 'on' : value === false ? 'off' : 'unknown';
    case 'selector':
      return optionIndex >= 0 ? 'off' : 'unknown';
    case 'dial':
    case 'encoder':
      return typeof value === 'number' ? 'off' : 'unknown';
    case 'press':
      return 'off';
    default: {
      const exhaustive: never = entry.spec.kind;
      throw new Error(`Unhandled cockpit control kind: ${String(exhaustive)}`);
    }
  }
}

function renderedSlots(
  layout: PanelLayout,
  controls: readonly CockpitControlSpec[],
  parked: readonly ParkedControl[],
  states: ControlStateMap,
  pending: Readonly<Record<string, true>>,
  focusedId: string | null,
): readonly RenderedSlot[] {
  const specs = new Map(controls.map((spec) => [spec.control_id, spec]));
  const parkedById = new Map(parked.map((entry) => [entry.control_id, entry]));
  const result: RenderedSlot[] = [];
  for (const slot of layout.slots) {
    const spec = specs.get(slot.control_id);
    const parkedEntry = parkedById.get(slot.control_id);
    const entry: SlotEntry | null =
      spec !== undefined
        ? { kind: 'control', spec }
        : parkedEntry !== undefined
          ? { kind: 'parked', parked: parkedEntry }
          : null;
    if (entry === null) {
      continue;
    }
    const value = states[slot.control_id];
    const hints = spec === undefined ? [] : unmetHints(spec, states);
    const isPending = pending[slot.control_id] === true;
    const optionIndex = spec === undefined ? -1 : selectedOptionIndex(spec, value);
    const focused = focusedId === slot.control_id;
    result.push({
      slot,
      entry,
      value,
      hints,
      pending: isPending,
      optionIndex,
      glyph: {
        slot,
        state: slotState(entry, value, hints, isPending, optionIndex),
        focused,
        ratio: spec === undefined ? null : pointerRatio(spec, value, optionIndex),
        optionIndex,
        optionCount: spec?.options?.length ?? 0,
        detentRatios: spec === undefined ? [] : detentRatios(spec, slot),
      },
    });
  }
  return result;
}

/** A decoration caption as an HTML overlay at `%` — never SVG `<text>`. */
function captionStyle(
  x: number,
  y: number,
  viewBox: PanelLayout['viewBox'],
): { left: string; top: string } {
  return {
    left: `${String((x / viewBox.w) * 100)}%`,
    top: `${String((y / viewBox.h) * 100)}%`,
  };
}

export function SchematicPanel({
  layout,
  controls,
  parked,
  states,
  pending,
  focusedId,
  draft,
  onFocus,
  onCommit,
  onNudge,
  onDraftText,
  onCommitDraft,
  onDiscardDraft,
}: SchematicPanelProps) {
  const slots = useMemo(() => slotIndex(layout), [layout]);
  const split = useMemo(
    () => splitByLayout(controls, parked, slots),
    [controls, parked, slots],
  );
  const rendered = useMemo(
    () =>
      renderedSlots(
        layout,
        split.placedControls,
        split.placedParked,
        states,
        pending,
        focusedId,
      ),
    [layout, split, states, pending, focusedId],
  );
  const { w, h } = layout.viewBox;
  const anyUnplaced =
    split.unplacedControls.length > 0 || split.unplacedParked.length > 0;

  return (
    <div className="schematic">
      <div
        className="schematic__board"
        style={{
          aspectRatio: `${String(w)} / ${String(h)}`,
          minWidth: layout.minWidthPx,
        }}
      >
        <SchematicSvg layout={layout} glyphs={rendered.map((item) => item.glyph)} />
        {layout.decorations.map((decoration, index) => {
          if (decoration.kind === 'caption') {
            return (
              <span
                key={index}
                className="schematic__deco-caption"
                aria-hidden="true"
                style={captionStyle(decoration.x, decoration.y, layout.viewBox)}
              >
                {decoration.text}
              </span>
            );
          }
          if (decoration.kind === 'box' && decoration.caption !== undefined) {
            return (
              <span
                key={index}
                className="schematic__deco-caption schematic__deco-caption--box"
                aria-hidden="true"
                style={captionStyle(decoration.x, decoration.y, layout.viewBox)}
              >
                {decoration.caption}
              </span>
            );
          }
          return null;
        })}
        {rendered.map((item) => (
          <SchematicSlot
            key={item.slot.control_id}
            slot={item.slot}
            viewBox={layout.viewBox}
            entry={item.entry}
            value={item.value}
            hints={item.hints}
            pending={item.pending}
            optionIndex={item.optionIndex}
            state={item.glyph.state}
            focused={item.glyph.focused}
            draft={draft}
            onFocus={onFocus}
            onCommit={onCommit}
            onNudge={onNudge}
            onDraftText={onDraftText}
            onCommitDraft={onCommitDraft}
            onDiscardDraft={onDiscardDraft}
          />
        ))}
      </div>

      {anyUnplaced && (
        <section className="schematic__unplaced" aria-label="Not on the diagram">
          <h3 className="schematic__unplaced-heading">Not on the diagram</h3>
          <ControlList
            controls={split.unplacedControls}
            parked={split.unplacedParked}
            states={states}
            pending={pending}
            emptyMessage="Everything on this panel is on the diagram."
            onCommit={onCommit}
          />
        </section>
      )}
    </div>
  );
}
