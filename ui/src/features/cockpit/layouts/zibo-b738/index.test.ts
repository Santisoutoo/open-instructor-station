/**
 * The Zibo layout against its own drift pin: every one of the 73 live + 20 parked ids is
 * drawn on its panel (or deliberately unplaced), no slot names an unknown id, every slot
 * fits its viewBox and a 44 px hit target, and the table data the levers depend on is
 * inside the catalog's ranges.
 */

import { describe, expect, it } from 'vitest';
import { panelLayoutProblems } from './checks';
import {
  ZIBO_CONTROL_IDS,
  ZIBO_LIGHTS_IDS,
  ZIBO_MCP_IDS,
  ZIBO_OVERHEAD_IDS,
  ZIBO_PEDESTAL_IDS,
} from './ids';
import { ZIBO_B738_LAYOUT } from './index';
import { LIGHTS_LAYOUT, LIGHTS_UNPLACED } from './lights';
import { MCP_LAYOUT, MCP_UNPLACED } from './mcp';
import { OVERHEAD_LAYOUT, OVERHEAD_UNPLACED } from './overhead';
import {
  FLAPS_DETENTS,
  PEDESTAL_LAYOUT,
  PEDESTAL_UNPLACED,
  SPEEDBRAKE_DETENTS,
} from './pedestal';

const PANELS = [
  { panel: MCP_LAYOUT, ids: ZIBO_MCP_IDS, unplaced: MCP_UNPLACED },
  { panel: OVERHEAD_LAYOUT, ids: ZIBO_OVERHEAD_IDS, unplaced: OVERHEAD_UNPLACED },
  { panel: PEDESTAL_LAYOUT, ids: ZIBO_PEDESTAL_IDS, unplaced: PEDESTAL_UNPLACED },
  { panel: LIGHTS_LAYOUT, ids: ZIBO_LIGHTS_IDS, unplaced: LIGHTS_UNPLACED },
];

function overlaps(
  a: { x: number; y: number; w: number; h: number },
  b: { x: number; y: number; w: number; h: number },
): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

describe('Zibo B738 layout', () => {
  it('pins 73 live + 20 parked ids, unique across the catalog', () => {
    expect(ZIBO_CONTROL_IDS).toHaveLength(93);
    expect(new Set(ZIBO_CONTROL_IDS).size).toBe(93);
  });

  it.each(PANELS)(
    '$panel.panel_id: every catalog id placed, every slot sound',
    ({ panel, ids, unplaced }) => {
      expect(panelLayoutProblems(panel, ids, unplaced)).toEqual([]);
    },
  );

  it.each(PANELS)('$panel.panel_id: no two slots overlap', ({ panel }) => {
    const clashes: string[] = [];
    panel.slots.forEach((a, i) => {
      panel.slots.slice(i + 1).forEach((b) => {
        if (overlaps(a, b)) {
          clashes.push(`${a.control_id} × ${b.control_id}`);
        }
      });
    });
    expect(clashes).toEqual([]);
  });

  it('registers the four panels under their ids and lists nothing as unplaced', () => {
    expect(Object.keys(ZIBO_B738_LAYOUT.panels).sort()).toEqual([
      'lights',
      'mcp',
      'overhead',
      'pedestal',
    ]);
    expect(ZIBO_B738_LAYOUT.unplaced).toEqual([]);
    expect(ZIBO_B738_LAYOUT.controlIds).toBe(ZIBO_CONTROL_IDS);
  });

  it('draws the parked entries as slots — disabled with a reason, never hidden', () => {
    const placed = new Set(
      Object.values(ZIBO_B738_LAYOUT.panels).flatMap((p) =>
        p.slots.map((s) => s.control_id),
      ),
    );
    for (const id of [
      'mcp_vs',
      'lnav',
      'battery',
      'irs_l',
      'start_lever_1',
      'toga_left',
      'strobe_light',
    ]) {
      expect(placed.has(id), id).toBe(true);
    }
  });

  it('keeps the lever detents inside the catalog ranges and the formats on the right knobs', () => {
    for (const detent of [...FLAPS_DETENTS, ...SPEEDBRAKE_DETENTS]) {
      expect(detent.value).toBeGreaterThanOrEqual(0);
      expect(detent.value).toBeLessThanOrEqual(1);
    }
    expect(FLAPS_DETENTS.map((d) => d.label)).toEqual([
      'UP',
      '1',
      '2',
      '5',
      '10',
      '15',
      '25',
      '30',
      '40',
    ]);
    const byId = new Map(PEDESTAL_LAYOUT.slots.map((s) => [s.control_id, s]));
    expect(byId.get('flaps_lever')?.detents).toBe(FLAPS_DETENTS);
    expect(byId.get('com1_standby_freq')?.format).toBe('khz');
    expect(byId.get('com2_standby_freq')?.format).toBe('khz');
    expect(byId.get('transponder_code')?.format).toBe('octal');
  });

  it('marks the spring-loaded APU START and wraps the heading knob', () => {
    const apu = OVERHEAD_LAYOUT.slots.find((s) => s.control_id === 'apu_master');
    expect(apu?.momentary).toEqual([2]);
    expect(apu?.shape).toBe('rotary-selector');
    const hdg = MCP_LAYOUT.slots.find((s) => s.control_id === 'mcp_hdg');
    expect(hdg?.wrap).toBe(true);
    expect(
      MCP_LAYOUT.slots.find((s) => s.control_id === 'mcp_alt')?.wrap,
    ).toBeUndefined();
  });

  it('keeps the lights strip in the real overhead order', () => {
    const order = [...LIGHTS_LAYOUT.slots]
      .sort((a, b) => a.x - b.x)
      .map((s) => s.control_id);
    expect(order).toEqual([
      'landing_lights_left',
      'landing_lights_right',
      'rwy_turnoff_left',
      'rwy_turnoff_right',
      'taxi_light',
      'logo_light',
      'position_light',
      'strobe_light',
      'anti_collision_beacon',
      'wing_light',
      'wheel_well_light',
      'cockpit_dome',
    ]);
    for (const id of ['taxi_light', 'position_light']) {
      expect(LIGHTS_LAYOUT.slots.find((s) => s.control_id === id)?.shape).toBe(
        'rotary-selector',
      );
    }
  });
});
