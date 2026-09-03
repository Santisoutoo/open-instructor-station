import { describe, expect, it } from 'vitest';
import { cockpitCatalogManifestFixture, cockpitStateSnapshotFixture } from './fixtures';
import { controlStateMap, unmetHints, visibleControls, visibleParked } from './filter';

describe('visibleControls', () => {
  it('scopes to the given panel when the search is empty', () => {
    const catalog = cockpitCatalogManifestFixture();

    const mcp = visibleControls(catalog, 'mcp', '');

    expect(mcp.map((control) => control.control_id)).toEqual([
      'fd_capt',
      'cmd_a',
      'hdg_sel',
      'mcp_alt',
      'mcp_hdg',
    ]);
  });

  it('matches by label or id across every panel once a search is active', () => {
    const catalog = cockpitCatalogManifestFixture();

    const results = visibleControls(catalog, 'mcp', 'landing');

    // "Landing lights" lives on the `lights` panel, not the active `mcp` one.
    expect(results.map((control) => control.control_id)).toEqual(['landing_lights']);
  });

  it('matches case-insensitively by control id', () => {
    const catalog = cockpitCatalogManifestFixture();

    expect(visibleControls(catalog, 'mcp', 'HDG_SEL').map((c) => c.control_id)).toEqual([
      'hdg_sel',
    ]);
  });
});

describe('visibleParked', () => {
  it('scopes parked entries the same way as controls', () => {
    const catalog = cockpitCatalogManifestFixture();

    expect(visibleParked(catalog, 'mcp', '').map((entry) => entry.control_id)).toEqual([
      'mcp_vs',
    ]);
    expect(visibleParked(catalog, 'overhead', '')).toEqual([]);
    expect(visibleParked(catalog, 'mcp', 'V/S').map((entry) => entry.control_id)).toEqual([
      'mcp_vs',
    ]);
  });
});

describe('unmetHints', () => {
  const catalog = cockpitCatalogManifestFixture();
  const hdgSel = catalog.controls.find((control) => control.control_id === 'hdg_sel');
  if (hdgSel === undefined) {
    throw new Error('fixture is missing hdg_sel');
  }

  it('reports the group hint when no member of any_of is satisfied', () => {
    const states = controlStateMap(cockpitStateSnapshotFixture()); // fd_capt/cmd_a both false

    expect(unmetHints(hdgSel, states)).toEqual([
      'HDG SEL needs a flight director or CMD A engaged.',
    ]);
  });

  it('clears once one any_of member is satisfied', () => {
    const states = { ...controlStateMap(cockpitStateSnapshotFixture()), fd_capt: true };

    expect(unmetHints(hdgSel, states)).toEqual([]);
  });

  it('treats an unknown (missing/null) referenced state as unmet, never as a pass', () => {
    expect(unmetHints(hdgSel, {})).toEqual([
      'HDG SEL needs a flight director or CMD A engaged.',
    ]);
    expect(unmetHints(hdgSel, { fd_capt: null, cmd_a: null })).toEqual([
      'HDG SEL needs a flight director or CMD A engaged.',
    ]);
  });

  it('is empty for a control with no preconditions', () => {
    const fdCapt = catalog.controls.find((control) => control.control_id === 'fd_capt');
    if (fdCapt === undefined) {
      throw new Error('fixture is missing fd_capt');
    }
    expect(unmetHints(fdCapt, {})).toEqual([]);
  });
});

describe('controlStateMap', () => {
  it('maps every snapshot entry by control id', () => {
    const map = controlStateMap(cockpitStateSnapshotFixture());

    expect(map.mcp_alt).toBe(5000);
    expect(map.battery).toBe(true);
  });

  it('is empty for an undefined snapshot', () => {
    expect(controlStateMap(undefined)).toEqual({});
  });
});
