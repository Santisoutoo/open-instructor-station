/**
 * Layout registry for the schematic cockpit (issue #253, design §1).
 *
 * `layoutFor` maps the catalog's `aircraft.catalog_id` to its checked-in layout, or
 * `null` when no schematic exists for that aircraft — the caller then disables the
 * schematic view with a reason and renders the list (design §4). The two helpers below
 * are the only geometry shared by the SVG and the HTML overlay, so both land on the
 * same spot at any board size.
 */

import { FAKE_TRAINER_LAYOUT } from './fake-trainer';
import { ZIBO_B738_LAYOUT } from './zibo-b738';
import type { CatalogLayout, LayoutSlot, PanelLayout } from './types';

export type {
  CatalogLayout,
  Detent,
  LabelSide,
  LayoutSlot,
  PanelDecoration,
  PanelLayout,
  SlotShape,
  ValueFormat,
} from './types';

const LAYOUTS: Readonly<Record<string, CatalogLayout>> = {
  [FAKE_TRAINER_LAYOUT.catalog_id]: FAKE_TRAINER_LAYOUT,
  [ZIBO_B738_LAYOUT.catalog_id]: ZIBO_B738_LAYOUT,
};

/** The layout for a catalog id, or `null` when no schematic exists for it. */
export function layoutFor(catalogId: string | null | undefined): CatalogLayout | null {
  if (catalogId === null || catalogId === undefined) {
    return null;
  }
  return LAYOUTS[catalogId] ?? null;
}

/** `control_id → slot` for one panel — the lookup `splitByLayout` and the slots use. */
export function slotIndex(panel: PanelLayout): ReadonlyMap<string, LayoutSlot> {
  return new Map(panel.slots.map((slot) => [slot.control_id, slot]));
}

/**
 * A slot's box as `%` of the board, for the HTML overlay (`CircuitDiagram`'s dual-draw
 * pattern). Plain percentages — no rounding — so the overlay and the SVG's own viewBox
 * scaling agree exactly.
 */
export function slotRect(
  slot: LayoutSlot,
  viewBox: PanelLayout['viewBox'],
): { left: string; top: string; width: string; height: string } {
  return {
    left: `${(slot.x / viewBox.w) * 100}%`,
    top: `${(slot.y / viewBox.h) * 100}%`,
    width: `${(slot.w / viewBox.w) * 100}%`,
    height: `${(slot.h / viewBox.h) * 100}%`,
  };
}
