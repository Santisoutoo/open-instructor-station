/** Tiny constructor shared by the Zibo panel tables so the rows stay one line each. */

import type { LayoutSlot, SlotShape } from '../types';

type SlotExtras = Omit<LayoutSlot, 'control_id' | 'shape' | 'x' | 'y' | 'w' | 'h'>;

export function slot(
  control_id: string,
  shape: SlotShape,
  x: number,
  y: number,
  w: number,
  h: number,
  extras: SlotExtras = {},
): LayoutSlot {
  return { control_id, shape, x, y, w, h, ...extras };
}
