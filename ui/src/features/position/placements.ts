/**
 * The runway-relative placement catalogue, and where each one sits on screen.
 *
 * The server owns *which* placements exist — `RunwayPlacementName` is the OpenAPI enum, so
 * a placement added in `core/geodesy.py` fails the typecheck here until this file gives it
 * a label and a position. This file owns only the presentation.
 *
 * **The grid is spatial on purpose.** An instructor does not read "left_downwind" off a
 * list; they point at where the aeroplane should be relative to the runway. So the circuit
 * tiles are laid out where those legs actually are — left-hand legs to the left of the
 * runway, right-hand to the right, base before the threshold, upwind past the far end —
 * and the finals run down the approach side as a rail of distances.
 */

import type { RunwayPlacementName } from '../../api/models';

/** A cell of the 3-column circuit grid: column, then row, both 1-based CSS grid lines. */
export interface GridCell {
  readonly column: 1 | 2 | 3;
  readonly row: number;
}

export interface PlacementTile {
  readonly name: RunwayPlacementName;
  readonly label: string;
  /** One short line under the label, or `null` when the label says everything. */
  readonly detail: string | null;
  readonly cell: GridCell;
}

/**
 * The eight circuit legs, positioned as they are flown.
 *
 * Row 1 is the far (departure) end, row 3 is the approach end, so the runway diagram sits
 * in column 2 and the aircraft tiles fall on the correct side of it.
 */
export const PATTERN_TILES: readonly PlacementTile[] = [
  {
    name: 'left_crosswind',
    label: 'Crosswind L',
    detail: 'Left-hand circuit',
    cell: { column: 1, row: 1 },
  },
  { name: 'left_upwind', label: 'Upwind L', detail: null, cell: { column: 1, row: 2 } },
  {
    name: 'left_downwind',
    label: 'Downwind L',
    detail: 'Circuit height',
    cell: { column: 1, row: 3 },
  },
  { name: 'left_base', label: 'Base L', detail: null, cell: { column: 1, row: 4 } },
  {
    name: 'right_crosswind',
    label: 'Crosswind R',
    detail: 'Right-hand circuit',
    cell: { column: 3, row: 1 },
  },
  { name: 'right_upwind', label: 'Upwind R', detail: null, cell: { column: 3, row: 2 } },
  {
    name: 'right_downwind',
    label: 'Downwind R',
    detail: 'Circuit height',
    cell: { column: 3, row: 3 },
  },
  { name: 'right_base', label: 'Base R', detail: null, cell: { column: 3, row: 4 } },
];

/** The finals rail, longest first — the order an approach is flown. */
export const FINAL_TILES: readonly { name: RunwayPlacementName; label: string }[] = [
  { name: 'final_20nm', label: '20 NM' },
  { name: 'final_15nm', label: '15 NM' },
  { name: 'final_10nm', label: '10 NM' },
  { name: 'final_8nm', label: '8 NM' },
  { name: 'final_5nm', label: '5 NM' },
  { name: 'final_3nm', label: '3 NM' },
  { name: 'short_final', label: 'Short' },
];

/**
 * Every runway-relative placement the panel offers.
 *
 * Typed as covering the whole enum, so this list cannot silently fall behind the server.
 */
export const ALL_RUNWAY_PLACEMENTS: readonly RunwayPlacementName[] = [
  ...FINAL_TILES.map((tile) => tile.name),
  ...PATTERN_TILES.map((tile) => tile.name),
];

/** Formats an altitude for a tile: `4184.4` -> `"4,184 ft"`. */
export function formatAltitudeFt(value: number): string {
  return `${Math.round(value).toLocaleString('en-GB')} ft`;
}

/** Formats a speed: `120` -> `"120 kt"`. */
export function formatSpeedKt(value: number): string {
  return `${Math.round(value).toLocaleString('en-GB')} kt`;
}

/** Formats a runway length in metres as both metres and feet, the way charts do. */
export function formatRunwayLength(metres: number): string {
  const feet = Math.round(metres / 0.3048);
  return `${Math.round(metres).toLocaleString('en-GB')} m · ${feet.toLocaleString('en-GB')} ft`;
}

/** Formats an ILS frequency: `110300` kHz -> `"110.30"`. */
export function formatIlsFrequency(khz: number): string {
  return (khz / 1000).toFixed(2);
}
