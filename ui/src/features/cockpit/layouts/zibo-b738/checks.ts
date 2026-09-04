/**
 * Integrity checks shared by the four Zibo panel layouts' tests and the catalog-level
 * test (issue #253). Pure: returns a list of human-readable problems, empty when the
 * layout is sound, so a failing test names every defect at once instead of the first.
 */

import type { PanelLayout } from '../types';

/** Smallest slot side, in viewBox units, that still fits a 44 px hit target at `minWidthPx`. */
export const MIN_SLOT_UNITS = 60;

export function panelLayoutProblems(
  panel: PanelLayout,
  expectedIds: readonly string[],
  unplaced: readonly string[] = [],
): string[] {
  const problems: string[] = [];
  const seen = new Set<string>();
  const expected = new Set(expectedIds);

  for (const slot of panel.slots) {
    const where = `${panel.panel_id}/${slot.control_id}`;
    if (seen.has(slot.control_id)) {
      problems.push(`${where}: duplicate slot id`);
    }
    seen.add(slot.control_id);
    if (!expected.has(slot.control_id)) {
      problems.push(`${where}: slot id is not a known catalog id for this panel`);
    }
    if (
      slot.x < 0 ||
      slot.y < 0 ||
      slot.x + slot.w > panel.viewBox.w ||
      slot.y + slot.h > panel.viewBox.h
    ) {
      problems.push(`${where}: slot leaves the viewBox`);
    }
    if (slot.w < MIN_SLOT_UNITS || slot.h < MIN_SLOT_UNITS) {
      problems.push(`${where}: slot smaller than ${MIN_SLOT_UNITS} units`);
    }
    if (slot.detents !== undefined) {
      const values = slot.detents.map((detent) => detent.value);
      if (new Set(values).size !== values.length) {
        problems.push(`${where}: duplicate detent values`);
      }
      if (new Set(slot.detents.map((detent) => detent.label)).size !== values.length) {
        problems.push(`${where}: duplicate detent labels`);
      }
    }
  }

  for (const id of expectedIds) {
    if (!seen.has(id) && !unplaced.includes(id)) {
      problems.push(
        `${panel.panel_id}/${id}: catalog id neither placed nor listed as unplaced`,
      );
    }
  }
  for (const id of unplaced) {
    if (seen.has(id)) {
      problems.push(`${panel.panel_id}/${id}: listed as unplaced but also placed`);
    }
    if (!expected.has(id)) {
      problems.push(`${panel.panel_id}/${id}: unplaced id is not a known catalog id`);
    }
  }

  return problems;
}
