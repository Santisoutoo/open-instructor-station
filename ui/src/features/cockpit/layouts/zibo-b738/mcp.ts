/**
 * Zibo 737 MCP (mode control panel) — issue #253 design §1.
 *
 * Drawn as two stacked rows in a 3:1 box on purpose, not the real 10:1 strip: a 10:1
 * board is ~100 px tall on a tablet and every knob shrinks under the 44 px hit target.
 * Row 1 is the flight-director / speed / heading / altitude / V/S line, row 2 the mode
 * buttons and the disengage bar. Parked entries (`mcp_vs`, `ias_mach_changeover`, `lnav`)
 * keep their real place and render disabled with their reason.
 */

import type { PanelLayout } from '../types';
import { slot } from './slot';

export const MCP_UNPLACED: readonly string[] = [];

export const MCP_LAYOUT: PanelLayout = {
  panel_id: 'mcp',
  viewBox: { w: 900, h: 300 },
  minWidthPx: 640,
  slots: [
    // Row 1 — the dial line.
    slot('fd_capt', 'rocker', 20, 40, 70, 110, { caption: 'F/D', labelSide: 'below' }),
    slot('mcp_speed', 'knob', 110, 25, 130, 140, {
      caption: 'IAS/MACH',
      labelSide: 'below',
    }),
    slot('ias_mach_changeover', 'pushbutton', 255, 60, 80, 70, { caption: 'C/O' }),
    slot('mcp_hdg', 'knob', 350, 25, 130, 140, {
      caption: 'HEADING',
      labelSide: 'below',
      wrap: true,
    }),
    slot('mcp_alt', 'knob', 495, 25, 130, 140, {
      caption: 'ALTITUDE',
      labelSide: 'below',
    }),
    slot('mcp_vs', 'display', 640, 50, 150, 90, { caption: 'VERT SPEED' }),
    slot('fd_fo', 'rocker', 810, 40, 70, 110, { caption: 'F/D', labelSide: 'below' }),
    // Row 2 — mode buttons and the A/P disengage bar.
    slot('lnav', 'pushbutton', 20, 195, 95, 75, { caption: 'LNAV' }),
    slot('vorloc', 'pushbutton', 130, 195, 95, 75, { caption: 'VOR LOC' }),
    slot('hdg_sel', 'pushbutton', 240, 195, 95, 75, { caption: 'HDG SEL' }),
    slot('app', 'pushbutton', 350, 195, 95, 75, { caption: 'APP' }),
    slot('cmd_a', 'pushbutton', 460, 195, 95, 75, { caption: 'CMD A' }),
    slot('cmd_b', 'pushbutton', 570, 195, 95, 75, { caption: 'CMD B' }),
    slot('ap_disconnect', 'pushbutton', 690, 195, 190, 75, { caption: 'A/P DISENGAGE' }),
  ],
  decorations: [
    { kind: 'caption', x: 20, y: 8, text: 'MCP' },
    { kind: 'box', x: 10, y: 15, w: 880, h: 165 },
    { kind: 'box', x: 10, y: 185, w: 880, h: 100 },
  ],
};
