/**
 * Deterministic cockpit fixtures — **test-only**.
 *
 * Mirrors `adapters/fake/cockpit_catalog.py`'s `FAKE_COCKPIT_CATALOG` /
 * `FAKE_COCKPIT_INITIAL_VALUES` field for field (design §4.1/§7.1): the same eleven
 * controls, the same one parked entry, the same four panels, the same initial values.
 * Tests build their own degraded manifests/snapshots from these with a spread, the
 * `camera/fixtures.ts` precedent.
 */

import type { CockpitCatalogManifest, CockpitStateSnapshot } from '../../api/models';

const VERIFIED_ON = '2026-09-02';

export function cockpitCatalogManifestFixture(): CockpitCatalogManifest {
  return {
    adapter: 'fake',
    supported: true,
    reason: null,
    aircraft: { catalog_id: 'fake-trainer', label: 'Fake trainer', path_hints: [] },
    revision: 1,
    detection_note: 'Synthetic catalog; nothing was probed.',
    panels: [
      { panel_id: 'mcp', label: 'MCP / autopilot', order: 0 },
      { panel_id: 'overhead', label: 'Overhead', order: 1 },
      { panel_id: 'pedestal', label: 'Pedestal', order: 2 },
      { panel_id: 'lights', label: 'Lights', order: 3 },
    ],
    controls: [
      {
        control_id: 'fd_capt',
        label: 'Flight director (captain)',
        panel_id: 'mcp',
        kind: 'toggle',
        readable: true,
        on_label: 'On',
        off_label: 'Off',
        readback_tolerance: 0,
        verified_on: VERIFIED_ON,
        live_sweep: true,
      },
      {
        control_id: 'cmd_a',
        label: 'CMD A',
        panel_id: 'mcp',
        kind: 'toggle',
        readable: true,
        on_label: 'On',
        off_label: 'Off',
        readback_tolerance: 0,
        verified_on: VERIFIED_ON,
        live_sweep: true,
      },
      {
        control_id: 'hdg_sel',
        label: 'HDG SEL',
        panel_id: 'mcp',
        kind: 'toggle',
        readable: true,
        on_label: 'On',
        off_label: 'Off',
        readback_tolerance: 0,
        preconditions: [
          {
            any_of: [
              { control_id: 'fd_capt', equals: true },
              { control_id: 'cmd_a', equals: true },
            ],
            hint: 'HDG SEL needs a flight director or CMD A engaged.',
          },
        ],
        verified_on: VERIFIED_ON,
        live_sweep: true,
      },
      {
        control_id: 'mcp_alt',
        label: 'Altitude',
        panel_id: 'mcp',
        kind: 'dial',
        readable: true,
        on_label: 'On',
        off_label: 'Off',
        unit: 'ft',
        min_value: 0,
        max_value: 50000,
        step: 100,
        readback_tolerance: 0,
        verified_on: VERIFIED_ON,
        live_sweep: true,
      },
      {
        control_id: 'mcp_hdg',
        label: 'Heading',
        panel_id: 'mcp',
        kind: 'dial',
        readable: true,
        on_label: 'On',
        off_label: 'Off',
        unit: 'deg',
        min_value: 0,
        max_value: 360,
        step: 1,
        readback_tolerance: 0,
        verified_on: VERIFIED_ON,
        live_sweep: true,
      },
      {
        control_id: 'battery',
        label: 'Battery',
        panel_id: 'overhead',
        kind: 'toggle',
        readable: true,
        on_label: 'On',
        off_label: 'Off',
        readback_tolerance: 0,
        verified_on: VERIFIED_ON,
        live_sweep: false,
        live_sweep_note: 'Cutting battery power breaks every later read-back.',
      },
      {
        control_id: 'irs_l',
        label: 'IRS L',
        panel_id: 'overhead',
        kind: 'selector',
        readable: true,
        on_label: 'On',
        off_label: 'Off',
        options: [
          { value: 0, label: 'OFF' },
          { value: 1, label: 'ALIGN' },
          { value: 2, label: 'NAV' },
          { value: 3, label: 'ATT' },
        ],
        readback_tolerance: 0,
        verified_on: VERIFIED_ON,
        live_sweep: true,
      },
      {
        control_id: 'stab_trim',
        label: 'Stab trim',
        panel_id: 'pedestal',
        kind: 'encoder',
        readable: true,
        on_label: 'On',
        off_label: 'Off',
        unit: 'units',
        step: 0.5,
        max_delta: 20,
        readback_tolerance: 0,
        verified_on: VERIFIED_ON,
        live_sweep: true,
      },
      {
        control_id: 'toga',
        label: 'TO/GA',
        panel_id: 'pedestal',
        kind: 'press',
        readable: false,
        on_label: 'On',
        off_label: 'Off',
        readback_tolerance: 0,
        verified_on: VERIFIED_ON,
        live_sweep: false,
        live_sweep_note: 'TO/GA arms thrust; not for a sweep on the ground.',
      },
      {
        control_id: 'landing_lights',
        label: 'Landing lights',
        panel_id: 'lights',
        kind: 'toggle',
        readable: true,
        on_label: 'On',
        off_label: 'Off',
        readback_tolerance: 0,
        verified_on: VERIFIED_ON,
        live_sweep: true,
      },
      {
        control_id: 'chime_test',
        label: 'Chime test',
        panel_id: 'overhead',
        kind: 'press',
        readable: false,
        on_label: 'On',
        off_label: 'Off',
        readback_tolerance: 0,
        verified_on: VERIFIED_ON,
        live_sweep: true,
      },
    ],
    parked: [
      {
        control_id: 'mcp_vs',
        label: 'V/S',
        panel_id: 'mcp',
        reason:
          'No settable vertical-speed dataref exists on the reference aircraft (research §6).',
        since: VERIFIED_ON,
      },
    ],
  };
}

export function cockpitStateSnapshotFixture(): CockpitStateSnapshot {
  return {
    catalog_id: 'fake-trainer',
    revision: 1,
    states: [
      { control_id: 'fd_capt', value: false },
      { control_id: 'cmd_a', value: false },
      { control_id: 'hdg_sel', value: false },
      { control_id: 'mcp_alt', value: 5000 },
      { control_id: 'mcp_hdg', value: 90 },
      { control_id: 'battery', value: true },
      { control_id: 'irs_l', value: 0 },
      { control_id: 'stab_trim', value: 4 },
      { control_id: 'landing_lights', value: false },
    ],
  };
}
