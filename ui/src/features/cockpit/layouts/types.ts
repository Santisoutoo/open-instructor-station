/**
 * Layout tables for the schematic cockpit (issue #253, design §1).
 *
 * The catalog served by `GET /api/cockpit/catalog` stays the only source of truth for
 * what a control *is* (kind, range, options, parked reason). A layout adds **position
 * and drawing hints only**, keyed by `control_id`, and never carries anything the
 * catalog already says. A layout slot whose id is absent from the catalog is simply not
 * drawn; a catalog control absent from the layout is listed in a "Not on the diagram"
 * strip. Nothing here is ever parsed out of a catalog `hint` or `unit` string — detent
 * labels and value formats are checked-in table data.
 *
 * Coordinates are in **viewBox units** with `x`/`y` the slot's top-left corner; the
 * components convert them to `%` of the board so the SVG glyph and the HTML hit target
 * land on the same spot at any size (the `CircuitDiagram` dual-draw pattern).
 *
 * `exactOptionalPropertyTypes` is on: an optional field is **omitted**, never set to
 * `undefined`.
 */

/** How a slot is drawn. The catalog `kind` decides how it *acts*; this decides how it looks. */
export type SlotShape =
  'pushbutton' | 'knob' | 'rocker' | 'rotary-selector' | 'lever' | 'display';

/** Where the caption sits relative to the slot box. */
export type LabelSide = 'above' | 'below' | 'left' | 'right';

/**
 * How a dial value is shown in the readout. `khz` values arrive as MHz×100 on the wire
 * (`com1_standby_freq` 11800 = 118.00 MHz); `octal` is a four-digit squawk. Both apply to
 * readouts only — the number field stays raw (design §3).
 */
export type ValueFormat = 'plain' | 'khz' | 'octal';

/** One named stop of a lever or a stepped dial, in the dial's own units. */
export interface Detent {
  readonly value: number;
  readonly label: string;
}

export interface LayoutSlot {
  readonly control_id: string;
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
  readonly shape: SlotShape;
  /** Short panel legend (≤ 12 chars is the rule of thumb). Defaults to the catalog label. */
  readonly caption?: string;
  readonly labelSide?: LabelSide;
  /** Dial-only: snap the draft to these stops after every nudge and on commit. */
  readonly detents?: readonly Detent[];
  /** Dial-only: wrap around `[min_value, max_value)` instead of clamping (headings). */
  readonly wrap?: boolean;
  readonly format?: ValueFormat;
  /** Selector-only: option values that spring back. The tray says so; the glyph draws nothing special. */
  readonly momentary?: readonly (number | string)[];
}

export type PanelDecoration =
  | {
      readonly kind: 'box';
      readonly x: number;
      readonly y: number;
      readonly w: number;
      readonly h: number;
      readonly caption?: string;
    }
  | {
      readonly kind: 'caption';
      readonly x: number;
      readonly y: number;
      readonly text: string;
    }
  | {
      readonly kind: 'line';
      readonly x1: number;
      readonly y1: number;
      readonly x2: number;
      readonly y2: number;
    };

export interface PanelLayout {
  readonly panel_id: string;
  readonly viewBox: { readonly w: number; readonly h: number };
  /** Below this the board scrolls horizontally instead of shrinking hit targets under 44 px. */
  readonly minWidthPx: number;
  readonly slots: readonly LayoutSlot[];
  readonly decorations: readonly PanelDecoration[];
}

export interface CatalogLayout {
  readonly catalog_id: string;
  readonly panels: Readonly<Record<string, PanelLayout>>;
  /** Every control id the layout knows (placed or not) — the drift pin against the catalog. */
  readonly controlIds: readonly string[];
  /** Known ids deliberately left off every diagram. */
  readonly unplaced: readonly string[];
}
