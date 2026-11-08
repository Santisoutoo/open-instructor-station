/**
 * Zibo 737 exterior / cockpit lighting strip — issue #253 design §1.
 *
 * One row in the real overhead order, left to right. The two three-position switches
 * (`taxi_light` OFF/DIM/BRIGHT, `position_light` OFF/POSITION/STROBE+POSITION) are rotary
 * selectors; the glyph points at the **option index**, never the value, which is what
 * makes `position_light`'s −1/0/1 options draw correctly. Parked `strobe_light` keeps its
 * real place next to the position switch.
 */

import type { PanelLayout } from '../types';
import { slot } from './slot';

export const LIGHTS_UNPLACED: readonly string[] = [];

const PITCH = 73;
const LEFT = 15;
const x = (index: number) => LEFT + index * PITCH;

export const LIGHTS_LAYOUT: PanelLayout = {
  panel_id: 'lights',
  viewBox: { w: 900, h: 220 },
  minWidthPx: 720,
  slots: [
    slot('landing_lights_left', 'rocker', x(0), 60, 60, 100, {
      caption: 'LAND L',
      labelSide: 'below',
    }),
    slot('landing_lights_right', 'rocker', x(1), 60, 60, 100, {
      caption: 'LAND R',
      labelSide: 'below',
    }),
    slot('rwy_turnoff_left', 'rocker', x(2), 60, 60, 100, {
      caption: 'RWY L',
      labelSide: 'below',
    }),
    slot('rwy_turnoff_right', 'rocker', x(3), 60, 60, 100, {
      caption: 'RWY R',
      labelSide: 'below',
    }),
    slot('taxi_light', 'rotary-selector', x(4), 60, 60, 100, {
      caption: 'TAXI',
      labelSide: 'below',
    }),
    slot('logo_light', 'rocker', x(5), 60, 60, 100, {
      caption: 'LOGO',
      labelSide: 'below',
    }),
    slot('position_light', 'rotary-selector', x(6), 60, 60, 100, {
      caption: 'POSITION',
      labelSide: 'below',
    }),
    slot('strobe_light', 'rocker', x(7), 60, 60, 100, {
      caption: 'STROBE',
      labelSide: 'below',
    }),
    slot('anti_collision_beacon', 'rocker', x(8), 60, 60, 100, {
      caption: 'BEACON',
      labelSide: 'below',
    }),
    slot('wing_light', 'rocker', x(9), 60, 60, 100, {
      caption: 'WING',
      labelSide: 'below',
    }),
    slot('wheel_well_light', 'rocker', x(10), 60, 60, 100, {
      caption: 'WHEEL WELL',
      labelSide: 'below',
    }),
    slot('cockpit_dome', 'rocker', x(11), 60, 60, 100, {
      caption: 'DOME',
      labelSide: 'below',
    }),
  ],
  decorations: [
    { kind: 'caption', x: 15, y: 15, text: 'LIGHTS' },
    { kind: 'box', x: 5, y: 45, w: 890, h: 130 },
  ],
};
