import { describe, expect, it } from 'vitest';
import { cockpitCatalogManifestFixture, cockpitStateSnapshotFixture } from './fixtures';
import {
  controlStateMap,
  selectedOptionIndex,
  splitByLayout,
  unmetHints,
  visibleControls,
  visibleParked,
} from './filter';
import { FAKE_TRAINER_LAYOUT } from './layouts/fake-trainer';
import { slotIndex } from './layouts';
import type { CockpitControlSpec, ParkedControl } from '../../api/models';

function specFor(controlId: string): CockpitControlSpec {
  const spec = cockpitCatalogManifestFixture().controls.find(
    (control) => control.control_id === controlId,
  );
  if (spec === undefined) {
    throw new Error(`fixture is missing ${controlId}`);
  }
  return spec;
}

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
    expect(visibleParked(catalog, 'mcp', 'V/S').map((entry) => entry.control_id)).toEqual(
      ['mcp_vs'],
    );
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

describe('splitByLayout', () => {
  const catalog = cockpitCatalogManifestFixture();
  const mcpPanel = FAKE_TRAINER_LAYOUT.panels.mcp;
  if (mcpPanel === undefined) {
    throw new Error('fake-trainer layout is missing the mcp panel');
  }
  const mcpSlots = slotIndex(mcpPanel);

  it('places every fixture control the layout draws and leaves nothing over', () => {
    const controls = visibleControls(catalog, 'mcp', '');
    const parked = visibleParked(catalog, 'mcp', '');

    const split = splitByLayout(controls, parked, mcpSlots);

    expect(split.placedControls).toEqual(controls);
    expect(split.placedParked).toEqual(parked);
    expect(split.unplacedControls).toEqual([]);
    expect(split.unplacedParked).toEqual([]);
  });

  it('routes an entry the layout does not know to the unplaced side, keeping order', () => {
    const extra: CockpitControlSpec = { ...specFor('fd_capt'), control_id: 'new_switch' };
    const extraParked: ParkedControl = {
      control_id: 'new_parked',
      label: 'New parked',
      panel_id: 'mcp',
      reason: 'not mapped yet',
      since: '2026-09-04',
    };
    const controls = [specFor('cmd_a'), extra, specFor('fd_capt')];
    const parked = [extraParked, ...visibleParked(catalog, 'mcp', '')];

    const split = splitByLayout(controls, parked, mcpSlots);

    expect(split.placedControls.map((c) => c.control_id)).toEqual(['cmd_a', 'fd_capt']);
    expect(split.unplacedControls.map((c) => c.control_id)).toEqual(['new_switch']);
    expect(split.placedParked.map((p) => p.control_id)).toEqual(['mcp_vs']);
    expect(split.unplacedParked.map((p) => p.control_id)).toEqual(['new_parked']);
  });

  it('places nothing against an empty slot index', () => {
    const controls = visibleControls(catalog, 'mcp', '');

    const split = splitByLayout(controls, [], new Map());

    expect(split.placedControls).toEqual([]);
    expect(split.unplacedControls).toEqual(controls);
  });
});

describe('selectedOptionIndex', () => {
  const irs = specFor('irs_l'); // options 0 OFF, 1 ALIGN, 2 NAV, 3 ATT

  it('finds the option by value', () => {
    expect(selectedOptionIndex(irs, 0)).toBe(0);
    expect(selectedOptionIndex(irs, 2)).toBe(2);
    expect(selectedOptionIndex(irs, 3)).toBe(3);
  });

  it('tolerates a float read-back of an integer option', () => {
    expect(selectedOptionIndex(irs, 1.0000001)).toBe(1);
    expect(selectedOptionIndex(irs, 0.9999999)).toBe(1);
  });

  it('is -1 for an unknown value, a non-matching value or a spec without options', () => {
    expect(selectedOptionIndex(irs, null)).toBe(-1);
    expect(selectedOptionIndex(irs, undefined)).toBe(-1);
    expect(selectedOptionIndex(irs, 7)).toBe(-1);
    expect(selectedOptionIndex(irs, 1.5)).toBe(-1);
    expect(selectedOptionIndex(specFor('fd_capt'), true)).toBe(-1);
  });

  it('compares string and boolean options strictly', () => {
    const modes: CockpitControlSpec = {
      ...irs,
      options: [
        { value: 'STBY', label: 'Standby' },
        { value: 'ON', label: 'On' },
      ],
    };
    expect(selectedOptionIndex(modes, 'ON')).toBe(1);
    expect(selectedOptionIndex(modes, 'on')).toBe(-1);
    expect(selectedOptionIndex(modes, 1)).toBe(-1);
    expect(selectedOptionIndex(irs, '1')).toBe(-1);
    expect(selectedOptionIndex(irs, true)).toBe(-1);
  });
});
