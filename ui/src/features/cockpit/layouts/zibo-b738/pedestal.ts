/**
 * Zibo 737 pedestal — issue #253 design §1.
 *
 * Four groups: the throttle quadrant (speedbrake and flap levers with their detents,
 * the trim wheel, parking brake, the parked start levers / TO/GA / A/T disconnect on the
 * throttle heads), the radios (COM standby knobs as MHz×100 → `format: 'khz'`), the trims
 * and stab-trim cutouts, and the transponder (`format: 'octal'` squawk).
 *
 * Detent labels and formats are **table data**: the catalog's `flaps_lever` hint lists
 * the same stops, but nothing here is parsed out of a hint string.
 */

import type { Detent, PanelLayout } from '../types';
import { slot } from './slot';

export const PEDESTAL_UNPLACED: readonly string[] = [];

/** The nine flap detents, ratio → gate label, as the catalog's step 0.125 dial reads. */
export const FLAPS_DETENTS: readonly Detent[] = [
  { value: 0, label: 'UP' },
  { value: 0.125, label: '1' },
  { value: 0.25, label: '2' },
  { value: 0.375, label: '5' },
  { value: 0.5, label: '10' },
  { value: 0.625, label: '15' },
  { value: 0.75, label: '25' },
  { value: 0.875, label: '30' },
  { value: 1, label: '40' },
];

/** Quarter stops of the speedbrake dial (ARM is the separate `speedbrake_arm` selector). */
export const SPEEDBRAKE_DETENTS: readonly Detent[] = [
  { value: 0, label: 'DOWN' },
  { value: 0.25, label: '1/4' },
  { value: 0.5, label: '1/2' },
  { value: 0.75, label: '3/4' },
  { value: 1, label: 'UP' },
];

export const PEDESTAL_LAYOUT: PanelLayout = {
  panel_id: 'pedestal',
  viewBox: { w: 800, h: 600 },
  minWidthPx: 560,
  slots: [
    // Throttle quadrant.
    slot('speedbrake_lever', 'lever', 25, 40, 70, 220, {
      caption: 'SPD BRK',
      labelSide: 'below',
      detents: SPEEDBRAKE_DETENTS,
    }),
    slot('stab_trim', 'knob', 20, 270, 80, 70, {
      caption: 'STAB TRIM',
      labelSide: 'below',
    }),
    slot('speedbrake_arm', 'rocker', 105, 40, 64, 90, {
      caption: 'ARM',
      labelSide: 'below',
    }),
    slot('parking_brake', 'rocker', 105, 150, 64, 90, {
      caption: 'PARK BRAKE',
      labelSide: 'below',
    }),
    slot('horn_cutout', 'pushbutton', 105, 260, 70, 60, { caption: 'HORN CUT' }),
    slot('toga_left', 'pushbutton', 185, 25, 70, 60, { caption: 'TO/GA' }),
    slot('at_disconnect_left', 'pushbutton', 185, 95, 70, 60, { caption: 'A/T DISC' }),
    slot('toga_right', 'pushbutton', 265, 25, 70, 60, { caption: 'TO/GA' }),
    slot('at_disconnect_right', 'pushbutton', 265, 95, 70, 60, { caption: 'A/T DISC' }),
    slot('start_lever_1', 'lever', 190, 170, 60, 110, {
      caption: 'START 1',
      labelSide: 'below',
    }),
    slot('start_lever_2', 'lever', 260, 170, 60, 110, {
      caption: 'START 2',
      labelSide: 'below',
    }),
    slot('flaps_lever', 'lever', 350, 40, 70, 240, {
      caption: 'FLAPS',
      labelSide: 'below',
      detents: FLAPS_DETENTS,
    }),
    // Radios.
    slot('com1_standby_freq', 'knob', 510, 25, 100, 80, {
      caption: 'COM1 STBY',
      labelSide: 'below',
      format: 'khz',
    }),
    slot('com1_swap', 'pushbutton', 620, 35, 60, 60, { caption: 'SWAP' }),
    slot('nav1_swap', 'pushbutton', 700, 35, 80, 60, { caption: 'NAV1 SWAP' }),
    slot('com2_standby_freq', 'knob', 510, 115, 100, 80, {
      caption: 'COM2 STBY',
      labelSide: 'below',
      format: 'khz',
    }),
    slot('com2_swap', 'pushbutton', 620, 125, 60, 60, { caption: 'SWAP' }),
    slot('nav2_swap', 'pushbutton', 700, 125, 80, 60, { caption: 'NAV2 SWAP' }),
    slot('com_rtp_panel', 'display', 510, 205, 270, 65, { caption: 'RTP' }),
    // Trims and cutouts.
    slot('rudder_trim', 'knob', 510, 305, 90, 90, {
      caption: 'RUD TRIM',
      labelSide: 'below',
    }),
    slot('aileron_trim', 'knob', 610, 305, 90, 90, {
      caption: 'AIL TRIM',
      labelSide: 'below',
    }),
    slot('stab_trim_cutout_main', 'rocker', 710, 300, 70, 60, {
      caption: 'MAIN ELEC',
      labelSide: 'below',
    }),
    slot('stab_trim_cutout_autopilot', 'rocker', 710, 370, 70, 60, {
      caption: 'AUTOPILOT',
      labelSide: 'below',
    }),
    // Transponder.
    slot('transponder_code', 'knob', 25, 380, 110, 110, {
      caption: 'SQUAWK',
      labelSide: 'below',
      format: 'octal',
    }),
    slot('transponder_mode', 'rotary-selector', 150, 380, 110, 110, {
      caption: 'MODE',
      labelSide: 'below',
    }),
    slot('transponder_ident', 'pushbutton', 280, 390, 80, 70, { caption: 'IDENT' }),
    slot('weather_radar_wxr', 'pushbutton', 280, 470, 80, 70, { caption: 'WXR' }),
    slot('transponder_atc', 'rocker', 375, 375, 64, 90, {
      caption: 'ATC',
      labelSide: 'below',
    }),
  ],
  decorations: [
    { kind: 'box', x: 10, y: 10, w: 470, h: 340 },
    { kind: 'box', x: 500, y: 10, w: 290, h: 270 },
    { kind: 'box', x: 500, y: 290, w: 290, h: 150 },
    { kind: 'box', x: 10, y: 360, w: 470, h: 230 },
    { kind: 'caption', x: 20, y: 14, text: 'THROTTLES' },
    { kind: 'caption', x: 510, y: 14, text: 'RADIOS' },
    { kind: 'caption', x: 510, y: 294, text: 'TRIM' },
    { kind: 'caption', x: 20, y: 364, text: 'TRANSPONDER' },
  ],
};
