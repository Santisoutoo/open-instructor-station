/**
 * SVG glyphs for the schematic cockpit (issue #253, design §2).
 *
 * One pure drawing per `SlotShape`, sized to its slot box in viewBox units. A glyph knows
 * nothing about the catalog: `SchematicPanel` folds the spec, the confirmed value and
 * the layout slot into a {@link GlyphModel} and the glyph only draws it. Every visual
 * state is expressed through `data-state`/`data-focused` on the wrapping `<g>` and
 * class hooks (`glyph-lit`, `glyph-lit-off`, `glyph-pointer`, …) that `schematic.css`
 * colours — no fill or stroke is hard-coded here, so both themes are a variable swap.
 *
 * **No `<text>` anywhere.** SVG font-size is a user unit and scales down with the board
 * (`CircuitDiagram`'s measured 8 px labels); every caption and readout is an HTML overlay
 * in `SchematicSlot`.
 */

import type { LayoutSlot } from './layouts';

/**
 * The single visual state of a slot, both layers styled from it. Precedence when several
 * apply: `parked` > `pending` > `unmet` > `on`/`off`/`unknown`.
 */
export type SlotState = 'on' | 'off' | 'unknown' | 'parked' | 'pending' | 'unmet';

export interface GlyphModel {
  readonly slot: LayoutSlot;
  readonly state: SlotState;
  readonly focused: boolean;
  /**
   * Pointer / handle position in `[0, 1]` — a dial over its range, a selector over its
   * option indices — or `null` when nothing has been read back (no pointer is drawn).
   */
  readonly ratio: number | null;
  /** Index into `spec.options` of the confirmed selector value, `-1` when unknown. */
  readonly optionIndex: number;
  /** `spec.options.length` for a selector, `0` otherwise. */
  readonly optionCount: number;
  /**
   * Lever only: `slot.detents` as `[0, 1]` fractions of the **same** range `ratio` uses,
   * so a handle sitting on a detent lands exactly on its tick.
   */
  readonly detentRatios: readonly number[];
}

/** A knob or selector pointer sweeps this arc, from `-SWEEP/2` (7 o'clock) clockwise. */
const SWEEP_DEG = 270;

function pointerAngle(ratio: number): number {
  return -SWEEP_DEG / 2 + ratio * SWEEP_DEG;
}

function polar(
  cx: number,
  cy: number,
  r: number,
  angleDeg: number,
): { x: number; y: number } {
  // 0° points up; positive is clockwise on screen (y grows downwards).
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function Pushbutton({ slot }: { slot: LayoutSlot }) {
  const inset = Math.min(slot.w, slot.h) * 0.18;
  return (
    <>
      <rect
        className="glyph-body"
        x={slot.x}
        y={slot.y}
        width={slot.w}
        height={slot.h}
        rx={Math.min(slot.w, slot.h) * 0.15}
      />
      <rect
        className="glyph-lit"
        x={slot.x + inset}
        y={slot.y + slot.h * 0.32}
        width={slot.w - inset * 2}
        height={slot.h * 0.36}
        rx={slot.h * 0.06}
      />
    </>
  );
}

function Knob({ slot, ratio }: { slot: LayoutSlot; ratio: number | null }) {
  const windowH = slot.h * 0.2;
  const windowInset = slot.w * 0.15;
  const cx = slot.x + slot.w / 2;
  const cy = slot.y + windowH + (slot.h - windowH) / 2;
  const r = Math.min(slot.w, slot.h - windowH) * 0.36;
  const tip = polar(cx, cy, r * 0.85, 0);
  return (
    <>
      <rect
        className="glyph-window"
        x={slot.x + windowInset}
        y={slot.y}
        width={slot.w - windowInset * 2}
        height={windowH * 0.8}
        rx={windowH * 0.15}
      />
      <circle className="glyph-body" cx={cx} cy={cy} r={r} />
      {ratio === null ? (
        <circle className="glyph-centre" cx={cx} cy={cy} r={r * 0.12} />
      ) : (
        <line
          className="glyph-pointer"
          x1={cx}
          y1={cy}
          x2={tip.x}
          y2={tip.y}
          transform={`rotate(${String(pointerAngle(ratio))} ${String(cx)} ${String(cy)})`}
        />
      )}
    </>
  );
}

function Rocker({ slot }: { slot: LayoutSlot }) {
  const inset = slot.w * 0.15;
  const halfH = slot.h / 2;
  const rx = slot.w * 0.12;
  return (
    <>
      <rect
        className="glyph-body"
        x={slot.x}
        y={slot.y}
        width={slot.w}
        height={slot.h}
        rx={rx}
      />
      <rect
        className="glyph-lit"
        x={slot.x + inset}
        y={slot.y + inset}
        width={slot.w - inset * 2}
        height={halfH - inset * 1.5}
        rx={rx * 0.5}
      />
      <rect
        className="glyph-lit-off"
        x={slot.x + inset}
        y={slot.y + halfH + inset * 0.5}
        width={slot.w - inset * 2}
        height={halfH - inset * 1.5}
        rx={rx * 0.5}
      />
    </>
  );
}

function RotarySelector({
  slot,
  optionIndex,
  optionCount,
}: {
  slot: LayoutSlot;
  optionIndex: number;
  optionCount: number;
}) {
  const cx = slot.x + slot.w / 2;
  const cy = slot.y + slot.h / 2;
  const r = Math.min(slot.w, slot.h) * 0.32;
  const tickInner = r * 1.15;
  const tickOuter = r * 1.35;
  const stops = Math.max(optionCount, 1);
  const angleAt = (index: number) =>
    pointerAngle(stops === 1 ? 0.5 : index / (stops - 1));
  const tip = polar(cx, cy, r * 0.85, 0);
  return (
    <>
      {Array.from({ length: optionCount }, (_, index) => {
        const a = angleAt(index);
        const from = polar(cx, cy, tickInner, a);
        const to = polar(cx, cy, tickOuter, a);
        return (
          <line
            key={index}
            className="glyph-tick"
            x1={from.x}
            y1={from.y}
            x2={to.x}
            y2={to.y}
          />
        );
      })}
      <circle className="glyph-body" cx={cx} cy={cy} r={r} />
      {optionIndex >= 0 && optionIndex < optionCount && (
        <line
          className="glyph-pointer"
          x1={cx}
          y1={cy}
          x2={tip.x}
          y2={tip.y}
          transform={`rotate(${String(angleAt(optionIndex))} ${String(cx)} ${String(cy)})`}
        />
      )}
    </>
  );
}

function Lever({
  slot,
  ratio,
  detentRatios,
}: {
  slot: LayoutSlot;
  ratio: number | null;
  detentRatios: readonly number[];
}) {
  const cx = slot.x + slot.w / 2;
  const pad = slot.h * 0.1;
  const top = slot.y + pad;
  const bottom = slot.y + slot.h - pad;
  const travel = bottom - top;
  const trackW = Math.max(slot.w * 0.12, 4);
  const handleW = slot.w * 0.6;
  const handleH = Math.max(slot.h * 0.08, 6);
  const yAt = (r: number) => bottom - r * travel;
  return (
    <>
      <rect
        className="glyph-track"
        x={cx - trackW / 2}
        y={top}
        width={trackW}
        height={travel}
        rx={trackW / 2}
      />
      {detentRatios.map((r) => (
        <line
          key={r}
          className="glyph-tick"
          x1={cx + trackW}
          y1={yAt(r)}
          x2={cx + trackW + slot.w * 0.18}
          y2={yAt(r)}
        />
      ))}
      {ratio !== null && (
        <rect
          className="glyph-handle"
          x={cx - handleW / 2}
          y={yAt(ratio) - handleH / 2}
          width={handleW}
          height={handleH}
          rx={handleH / 2}
        />
      )}
    </>
  );
}

function Display({ slot }: { slot: LayoutSlot }) {
  return (
    <rect
      className="glyph-display"
      x={slot.x}
      y={slot.y}
      width={slot.w}
      height={slot.h}
      rx={Math.min(slot.w, slot.h) * 0.1}
    />
  );
}

/** One slot's drawing, inside a `<g>` that carries every state hook the CSS styles from. */
export function Glyph({ model }: { model: GlyphModel }) {
  const { slot } = model;
  return (
    <g
      className="schematic__glyph"
      data-shape={slot.shape}
      data-state={model.state}
      data-focused={model.focused ? 'true' : 'false'}
    >
      {renderShape(model)}
    </g>
  );
}

function renderShape(model: GlyphModel) {
  const { slot } = model;
  switch (slot.shape) {
    case 'pushbutton':
      return <Pushbutton slot={slot} />;
    case 'knob':
      return <Knob slot={slot} ratio={model.ratio} />;
    case 'rocker':
      return <Rocker slot={slot} />;
    case 'rotary-selector':
      return (
        <RotarySelector
          slot={slot}
          optionIndex={model.optionIndex}
          optionCount={model.optionCount}
        />
      );
    case 'lever':
      return <Lever slot={slot} ratio={model.ratio} detentRatios={model.detentRatios} />;
    case 'display':
      return <Display slot={slot} />;
    default: {
      // `SlotShape` is closed — a seventh shape fails here rather than drawing nothing.
      const exhaustive: never = slot.shape;
      throw new Error(`Unhandled slot shape: ${String(exhaustive)}`);
    }
  }
}
