/**
 * Pure logic for the panel/search picker and the client-computed precondition hint
 * (design §7.1's `filter.ts`).
 *
 * `unmetHints` is deliberately **informational only** — it mirrors
 * `core.cockpit.preconditions.unmet_preconditions`'s `any_of`/tolerance rule closely
 * enough to warn the instructor before a tap, but the server's 409
 * (`CockpitPreconditionUnmet`) is the actual gate (design §7.3: a row with an unmet
 * hint stays enabled). A control referencing a state this client has not read yet reads
 * as unmet, never as satisfied — "unknown is not a pass", the same rule `core/` uses.
 */

import type {
  CockpitControlSpec,
  CockpitControlState,
  CockpitStateSnapshot,
  CockpitValue,
  ControlCondition,
  ParkedControl,
} from '../../api/models';
import type { LayoutSlot } from './layouts';

/** `null`/`undefined` both mean "unknown" — the map never distinguishes them. */
export type ControlStateMap = Readonly<Record<string, CockpitValue | null | undefined>>;

/** `states[control_id]` for every entry of a snapshot, or `{}` while nothing has loaded. */
export function controlStateMap(
  snapshot: CockpitStateSnapshot | undefined,
): ControlStateMap {
  const map: Record<string, CockpitValue | null> = {};
  for (const entry of snapshot?.states ?? ([] as CockpitControlState[])) {
    map[entry.control_id] = entry.value;
  }
  return map;
}

const NUMERIC_TOLERANCE = 1e-6;

function conditionSatisfied(
  condition: ControlCondition,
  states: ControlStateMap,
): boolean {
  const value = states[condition.control_id];
  if (value === undefined || value === null) {
    return false;
  }
  if (typeof value === 'number' && typeof condition.equals === 'number') {
    return Math.abs(value - condition.equals) < NUMERIC_TOLERANCE;
  }
  return value === condition.equals;
}

/** Every unmet precondition group's hint, in declaration order. Empty when all are met. */
export function unmetHints(
  spec: CockpitControlSpec,
  states: ControlStateMap,
): readonly string[] {
  return (spec.preconditions ?? [])
    .filter(
      (group) => !group.any_of.some((condition) => conditionSatisfied(condition, states)),
    )
    .map((group) => group.hint);
}

function matchesQuery(
  entry: { control_id: string; label: string },
  query: string,
): boolean {
  return (
    entry.label.toLowerCase().includes(query) ||
    entry.control_id.toLowerCase().includes(query)
  );
}

/**
 * Actuable rows to show for the current picker state.
 *
 * Search flattens the picker: a non-empty query matches by label or id **across every
 * panel**; an empty query scopes to `panelId` alone (design §7.1's "Search results").
 */
export function visibleControls(
  catalog: { controls: readonly CockpitControlSpec[] },
  panelId: string | null,
  search: string,
): readonly CockpitControlSpec[] {
  const query = search.trim().toLowerCase();
  return query === ''
    ? catalog.controls.filter((control) => control.panel_id === panelId)
    : catalog.controls.filter((control) => matchesQuery(control, query));
}

/** `parked` counterpart of {@link visibleControls} — same scoping, same search rule. */
export function visibleParked(
  catalog: { parked: readonly ParkedControl[] },
  panelId: string | null,
  search: string,
): readonly ParkedControl[] {
  const query = search.trim().toLowerCase();
  return query === ''
    ? catalog.parked.filter((entry) => entry.panel_id === panelId)
    : catalog.parked.filter((entry) => matchesQuery(entry, query));
}

/** The catalog entries of one panel, split by whether the layout draws them (design §1). */
export interface LayoutSplit {
  readonly placedControls: readonly CockpitControlSpec[];
  readonly placedParked: readonly ParkedControl[];
  readonly unplacedControls: readonly CockpitControlSpec[];
  readonly unplacedParked: readonly ParkedControl[];
}

/**
 * Partition a panel's controls and parked entries by presence in the layout's slot
 * index. Input order is preserved on every side, so the "Not on the diagram" strip lists
 * entries in catalog order. A slot whose id is in neither list is simply not returned —
 * the catalog decides what exists, the layout only where it is drawn.
 */
export function splitByLayout(
  controls: readonly CockpitControlSpec[],
  parked: readonly ParkedControl[],
  slots: ReadonlyMap<string, LayoutSlot>,
): LayoutSplit {
  return {
    placedControls: controls.filter((control) => slots.has(control.control_id)),
    placedParked: parked.filter((entry) => slots.has(entry.control_id)),
    unplacedControls: controls.filter((control) => !slots.has(control.control_id)),
    unplacedParked: parked.filter((entry) => !slots.has(entry.control_id)),
  };
}

/**
 * Index into `spec.options` of the option a confirmed value selects, or `-1` when the
 * value is unknown, the spec has no options, or nothing matches. Numbers compare with
 * the same tolerance as {@link unmetHints}'s conditions so a float read-back (`1.0` for
 * `1`) never leaves the glyph and the `SelectorControl` pointing at different stops —
 * the `selector_index` lesson from PR #248. Strings and booleans compare strictly.
 */
export function selectedOptionIndex(
  spec: CockpitControlSpec,
  value: CockpitValue | null | undefined,
): number {
  if (value === null || value === undefined) {
    return -1;
  }
  return (spec.options ?? []).findIndex((option) =>
    typeof option.value === 'number' && typeof value === 'number'
      ? Math.abs(option.value - value) < NUMERIC_TOLERANCE
      : option.value === value,
  );
}
