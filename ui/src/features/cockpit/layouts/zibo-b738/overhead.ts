/**
 * Zibo 737 forward overhead — issue #253 design §1.
 *
 * Portrait, six bands top to bottom in the real order: IRS, ELEC, FUEL, HYD, ANTI-ICE,
 * PNEU. Every 2-position selector (generators, GPU, crossfeed) is drawn as a rocker like
 * the toggles next to it; the 3-position ones (APU master, isolation valve, packs) are
 * rotary selectors. `apu_master`'s START is spring-loaded — `momentary: [2]` draws the
 * spring arrow and the tray says so. The seven parked entries keep their real places.
 */

import type { PanelLayout } from '../types';
import { slot } from './slot';

export const OVERHEAD_UNPLACED: readonly string[] = [];

const ROCKER = { w: 64, h: 90 } as const;
const SHORT = { w: 64, h: 60 } as const;

export const OVERHEAD_LAYOUT: PanelLayout = {
  panel_id: 'overhead',
  viewBox: { w: 600, h: 900 },
  minWidthPx: 420,
  slots: [
    // IRS
    slot('irs_l', 'rotary-selector', 170, 15, 100, 100, {
      caption: 'IRS L',
      labelSide: 'below',
    }),
    slot('irs_r', 'rotary-selector', 330, 15, 100, 100, {
      caption: 'IRS R',
      labelSide: 'below',
    }),
    // ELEC — row A: DC / standby power and the parked drive disconnects, GPU on the right.
    slot('battery', 'rocker', 30, 145, ROCKER.w, ROCKER.h, {
      caption: 'BATTERY',
      labelSide: 'below',
    }),
    slot('standby_power', 'rocker', 110, 145, ROCKER.w, ROCKER.h, {
      caption: 'STBY PWR',
      labelSide: 'below',
    }),
    slot('bus_transfer', 'rocker', 190, 145, ROCKER.w, ROCKER.h, {
      caption: 'BUS TRANS',
      labelSide: 'below',
    }),
    slot('gen_drive_disc1', 'pushbutton', 285, 155, 70, 70, { caption: 'DRIVE 1' }),
    slot('gen_drive_disc2', 'pushbutton', 370, 155, 70, 70, { caption: 'DRIVE 2' }),
    slot('ext_power', 'rocker', 470, 145, ROCKER.w, ROCKER.h, {
      caption: 'GRD PWR',
      labelSide: 'below',
    }),
    // ELEC — row B: generators around the APU master.
    slot('gen1', 'rocker', 30, 245, ROCKER.w, ROCKER.h, {
      caption: 'GEN 1',
      labelSide: 'below',
    }),
    slot('apu_gen1', 'rocker', 110, 245, ROCKER.w, ROCKER.h, {
      caption: 'APU GEN 1',
      labelSide: 'below',
    }),
    slot('apu_master', 'rotary-selector', 200, 240, 100, 100, {
      caption: 'APU',
      labelSide: 'below',
      momentary: [2],
    }),
    slot('apu_gen2', 'rocker', 330, 245, ROCKER.w, ROCKER.h, {
      caption: 'APU GEN 2',
      labelSide: 'below',
    }),
    slot('gen2', 'rocker', 410, 245, ROCKER.w, ROCKER.h, {
      caption: 'GEN 2',
      labelSide: 'below',
    }),
    // FUEL — crossfeed above the pumps, pumps as the real 2×3 (left | center | right).
    slot('fuel_crossfeed', 'rocker', 268, 365, 64, 64, {
      caption: 'CROSSFEED',
      labelSide: 'below',
    }),
    slot('fuel_pump_l1', 'rocker', 60, 440, SHORT.w, SHORT.h, {
      caption: 'L AFT',
      labelSide: 'left',
    }),
    slot('fuel_pump_c1', 'rocker', 268, 440, SHORT.w, SHORT.h, {
      caption: 'CTR L',
      labelSide: 'left',
    }),
    slot('fuel_pump_r1', 'rocker', 476, 440, SHORT.w, SHORT.h, {
      caption: 'R AFT',
      labelSide: 'right',
    }),
    slot('fuel_pump_l2', 'rocker', 60, 505, SHORT.w, SHORT.h, {
      caption: 'L FWD',
      labelSide: 'left',
    }),
    slot('fuel_pump_c2', 'rocker', 268, 505, SHORT.w, SHORT.h, {
      caption: 'CTR R',
      labelSide: 'left',
    }),
    slot('fuel_pump_r2', 'rocker', 476, 505, SHORT.w, SHORT.h, {
      caption: 'R FWD',
      labelSide: 'right',
    }),
    // HYD — ENG 2 · ELEC 1 · ELEC 2 · ENG 1, the real order.
    slot('hyd_eng2_pump', 'rocker', 60, 592, SHORT.w, 64, {
      caption: 'ENG 2',
      labelSide: 'below',
    }),
    slot('hyd_elec1_pump', 'rocker', 200, 592, SHORT.w, 64, {
      caption: 'ELEC 1',
      labelSide: 'below',
    }),
    slot('hyd_elec2_pump', 'rocker', 340, 592, SHORT.w, 64, {
      caption: 'ELEC 2',
      labelSide: 'below',
    }),
    slot('hyd_eng1_pump', 'rocker', 476, 592, SHORT.w, 64, {
      caption: 'ENG 1',
      labelSide: 'below',
    }),
    // ANTI-ICE — window heat, probe heat, wing, engines.
    slot('window_heat_l_side', 'rocker', 20, 687, 60, 64, {
      caption: 'L SIDE',
      labelSide: 'below',
    }),
    slot('window_heat_l_fwd', 'rocker', 83, 687, 60, 64, {
      caption: 'L FWD',
      labelSide: 'below',
    }),
    slot('window_heat_r_fwd', 'rocker', 146, 687, 60, 64, {
      caption: 'R FWD',
      labelSide: 'below',
    }),
    slot('window_heat_r_side', 'rocker', 209, 687, 60, 64, {
      caption: 'R SIDE',
      labelSide: 'below',
    }),
    slot('probe_heat_capt', 'rocker', 272, 687, 60, 64, {
      caption: 'PROBE A',
      labelSide: 'below',
    }),
    slot('probe_heat_fo', 'rocker', 335, 687, 60, 64, {
      caption: 'PROBE B',
      labelSide: 'below',
    }),
    slot('wing_anti_ice', 'rocker', 398, 687, 60, 64, {
      caption: 'WING',
      labelSide: 'below',
    }),
    slot('eng1_anti_ice', 'rocker', 461, 687, 60, 64, {
      caption: 'ENG 1',
      labelSide: 'below',
    }),
    slot('eng2_anti_ice', 'rocker', 524, 687, 60, 64, {
      caption: 'ENG 2',
      labelSide: 'below',
    }),
    // PNEU — bleeds around the isolation valve and the packs.
    slot('bleed_eng1', 'rocker', 20, 785, ROCKER.w, ROCKER.h, {
      caption: 'BLEED 1',
      labelSide: 'below',
    }),
    slot('iso_valve', 'rotary-selector', 100, 780, 100, 100, {
      caption: 'ISO VALVE',
      labelSide: 'below',
    }),
    slot('apu_bleed', 'rocker', 215, 785, ROCKER.w, ROCKER.h, {
      caption: 'APU BLEED',
      labelSide: 'below',
    }),
    slot('pack_l', 'rotary-selector', 295, 780, 100, 100, {
      caption: 'L PACK',
      labelSide: 'below',
    }),
    slot('pack_r', 'rotary-selector', 410, 780, 100, 100, {
      caption: 'R PACK',
      labelSide: 'below',
    }),
    slot('bleed_eng2', 'rocker', 525, 785, ROCKER.w, ROCKER.h, {
      caption: 'BLEED 2',
      labelSide: 'below',
    }),
  ],
  decorations: [
    { kind: 'box', x: 10, y: 10, w: 580, h: 110 },
    { kind: 'box', x: 10, y: 130, w: 580, h: 215 },
    { kind: 'box', x: 10, y: 355, w: 580, h: 215 },
    { kind: 'box', x: 10, y: 580, w: 580, h: 85 },
    { kind: 'box', x: 10, y: 675, w: 580, h: 85 },
    { kind: 'box', x: 10, y: 770, w: 580, h: 120 },
    { kind: 'caption', x: 20, y: 16, text: 'IRS' },
    { kind: 'caption', x: 20, y: 136, text: 'ELEC' },
    { kind: 'caption', x: 20, y: 361, text: 'FUEL' },
    { kind: 'caption', x: 20, y: 586, text: 'HYD' },
    { kind: 'caption', x: 20, y: 681, text: 'ANTI-ICE' },
    { kind: 'caption', x: 20, y: 776, text: 'PNEU' },
  ],
};
