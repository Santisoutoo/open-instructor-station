/**
 * Schematic layout for the Fake adapter's `fake-trainer` catalog (issue #253, design §1).
 *
 * Mirrors `fixtures.ts` id for id — the eleven controls plus the parked `mcp_vs` on the
 * same four panel ids — so it drives the component tests and `npm run dev` against the
 * Fake. `fake-trainer.test.ts` pins every fixture id to a slot or to `unplaced`, which is
 * the closest thing `ui/` has to a drift check against the YAML that lives outside it.
 *
 * Slots keep ≥ 60 viewBox units on both axes so the 44 px hit target still fits at
 * `minWidthPx` (design §2, `.schematic__hit`).
 */

import type { CatalogLayout, PanelLayout } from './types';

const MCP: PanelLayout = {
  panel_id: 'mcp',
  viewBox: { w: 900, h: 300 },
  minWidthPx: 560,
  slots: [
    {
      control_id: 'fd_capt',
      x: 40,
      y: 50,
      w: 80,
      h: 110,
      shape: 'rocker',
      caption: 'F/D',
    },
    {
      control_id: 'mcp_hdg',
      x: 200,
      y: 30,
      w: 140,
      h: 140,
      shape: 'knob',
      caption: 'HEADING',
      labelSide: 'below',
      wrap: true,
    },
    {
      control_id: 'mcp_alt',
      x: 400,
      y: 30,
      w: 140,
      h: 140,
      shape: 'knob',
      caption: 'ALTITUDE',
      labelSide: 'below',
    },
    {
      control_id: 'mcp_vs',
      x: 620,
      y: 50,
      w: 160,
      h: 80,
      shape: 'display',
      caption: 'VERT SPEED',
      labelSide: 'below',
    },
    {
      control_id: 'cmd_a',
      x: 200,
      y: 210,
      w: 110,
      h: 60,
      shape: 'pushbutton',
      caption: 'CMD A',
    },
    {
      control_id: 'hdg_sel',
      x: 400,
      y: 210,
      w: 110,
      h: 60,
      shape: 'pushbutton',
      caption: 'HDG SEL',
    },
  ],
  decorations: [
    { kind: 'box', x: 20, y: 20, w: 860, h: 260 },
    { kind: 'line', x1: 160, y1: 30, x2: 160, y2: 270 },
    { kind: 'line', x1: 580, y1: 30, x2: 580, y2: 270 },
    { kind: 'caption', x: 610, y: 190, text: 'V/S' },
  ],
};

const OVERHEAD: PanelLayout = {
  panel_id: 'overhead',
  viewBox: { w: 600, h: 400 },
  minWidthPx: 360,
  slots: [
    {
      control_id: 'battery',
      x: 60,
      y: 120,
      w: 80,
      h: 110,
      shape: 'rocker',
      caption: 'BAT',
    },
    {
      control_id: 'irs_l',
      x: 250,
      y: 100,
      w: 140,
      h: 140,
      shape: 'rotary-selector',
      caption: 'IRS L',
      labelSide: 'below',
    },
    {
      control_id: 'chime_test',
      x: 450,
      y: 130,
      w: 100,
      h: 70,
      shape: 'pushbutton',
      caption: 'CHIME',
    },
  ],
  decorations: [
    { kind: 'box', x: 30, y: 60, w: 160, h: 280, caption: 'ELEC' },
    { kind: 'box', x: 220, y: 60, w: 200, h: 280, caption: 'IRS' },
    { kind: 'box', x: 430, y: 60, w: 140, h: 280, caption: 'TEST' },
  ],
};

const PEDESTAL: PanelLayout = {
  panel_id: 'pedestal',
  viewBox: { w: 800, h: 300 },
  minWidthPx: 560,
  slots: [
    {
      control_id: 'stab_trim',
      x: 100,
      y: 60,
      w: 140,
      h: 140,
      shape: 'knob',
      caption: 'STAB TRIM',
      labelSide: 'below',
    },
    {
      control_id: 'toga',
      x: 520,
      y: 100,
      w: 120,
      h: 70,
      shape: 'pushbutton',
      caption: 'TO/GA',
    },
  ],
  decorations: [
    { kind: 'box', x: 40, y: 30, w: 280, h: 240, caption: 'TRIM' },
    { kind: 'box', x: 400, y: 30, w: 360, h: 240, caption: 'THROTTLE' },
    { kind: 'line', x1: 460, y1: 60, x2: 460, y2: 240 },
    { kind: 'line', x1: 700, y1: 60, x2: 700, y2: 240 },
  ],
};

const LIGHTS: PanelLayout = {
  panel_id: 'lights',
  viewBox: { w: 900, h: 220 },
  minWidthPx: 560,
  slots: [
    {
      control_id: 'landing_lights',
      x: 60,
      y: 50,
      w: 80,
      h: 110,
      shape: 'rocker',
      caption: 'LANDING',
    },
  ],
  decorations: [
    { kind: 'box', x: 30, y: 20, w: 840, h: 180, caption: 'LIGHTS' },
    { kind: 'caption', x: 200, y: 110, text: 'Fake trainer carries one light switch.' },
  ],
};

export const FAKE_TRAINER_LAYOUT: CatalogLayout = {
  catalog_id: 'fake-trainer',
  panels: {
    [MCP.panel_id]: MCP,
    [OVERHEAD.panel_id]: OVERHEAD,
    [PEDESTAL.panel_id]: PEDESTAL,
    [LIGHTS.panel_id]: LIGHTS,
  },
  controlIds: [
    'fd_capt',
    'cmd_a',
    'hdg_sel',
    'mcp_alt',
    'mcp_hdg',
    'mcp_vs',
    'battery',
    'irs_l',
    'chime_test',
    'stab_trim',
    'toga',
    'landing_lights',
  ],
  unplaced: [],
};
