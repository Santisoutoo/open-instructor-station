/**
 * The client state of the Position panel.
 *
 * Most of these tests are about **clearing** rather than setting. A staged placement that
 * survives a change of airport or runway is the dangerous bug in this panel: the staging
 * bar would still show a plausible diagram, and Place aircraft would put the student's
 * aeroplane at the previous field.
 */

import { describe, expect, it } from 'vitest';
import type { PlacementRequest } from '../../api/models';
import reducer, {
  RECENT_AIRPORT_LIMIT,
  airportSelected,
  placementStaged,
  procedureOpened,
  runwaySelected,
  setupOverridden,
  staleCleared,
  tabSelected,
} from './positionSlice';

const FINAL: PlacementRequest = {
  type: 'runway',
  airport_icao: 'ZZZZ',
  runway_ident: '36',
  placement: 'final_10nm',
};

function stagedState() {
  let state = reducer(undefined, airportSelected('ZZZZ'));
  state = reducer(state, runwaySelected('36'));
  state = reducer(state, placementStaged(FINAL));
  return reducer(state, setupOverridden({ field: 'ias_kt', value: 95 }));
}

describe('airportSelected', () => {
  it('upper-cases the code so a typed "lemd" is the same airport as "LEMD"', () => {
    expect(reducer(undefined, airportSelected('lemd')).selectedIcao).toBe('LEMD');
  });

  it('clears everything downstream of the airport', () => {
    const next = reducer(stagedState(), airportSelected('LEMD'));

    expect(next.selectedRunwayIdent).toBeNull();
    expect(next.staged).toBeNull();
    expect(next.setupOverrides).toEqual({});
    expect(next.openProcedure).toBeNull();
  });

  it('remembers recent airports, newest first, without duplicates', () => {
    let state = reducer(undefined, airportSelected('LEMD'));
    state = reducer(state, airportSelected('LEBL'));
    state = reducer(state, airportSelected('LEMD'));

    expect(state.recentIcaos).toEqual(['LEMD', 'LEBL']);
  });

  it('caps the recent list', () => {
    let state = reducer(undefined, airportSelected('AAAA'));
    for (const icao of ['BBBB', 'CCCC', 'DDDD', 'EEEE', 'FFFF', 'GGGG']) {
      state = reducer(state, airportSelected(icao));
    }

    expect(state.recentIcaos).toHaveLength(RECENT_AIRPORT_LIMIT);
    expect(state.recentIcaos[0]).toBe('GGGG');
    expect(state.recentIcaos).not.toContain('AAAA');
  });
});

describe('runwaySelected', () => {
  it('clears the staged placement, which was relative to the previous end', () => {
    const next = reducer(stagedState(), runwaySelected('18'));

    expect(next.selectedRunwayIdent).toBe('18');
    expect(next.staged).toBeNull();
    expect(next.setupOverrides).toEqual({});
  });
});

describe('placementStaged', () => {
  it('stages the request itself, not a resolved placement', () => {
    const state = reducer(undefined, placementStaged(FINAL));

    expect(state.staged).toEqual(FINAL);
  });

  it('drops edits that belonged to the previous placement', () => {
    const next = reducer(
      stagedState(),
      placementStaged({ ...FINAL, placement: 'final_3nm' }),
    );

    expect(next.setupOverrides).toEqual({});
  });
});

describe('setupOverridden', () => {
  it('is a sparse overlay, never a full copy of the setup', () => {
    // An untouched field has to keep the geometry's value, so only edited fields appear.
    const state = reducer(
      stagedState(),
      setupOverridden({ field: 'gear_down', value: true }),
    );

    expect(state.setupOverrides).toEqual({ ias_kt: 95, gear_down: true });
  });

  it('removes the override when a field is cleared', () => {
    const state = reducer(
      stagedState(),
      setupOverridden({ field: 'ias_kt', value: null }),
    );

    expect(state.setupOverrides).toEqual({});
  });
});

describe('the rest', () => {
  it('switches tab without disturbing the staged placement', () => {
    const next = reducer(stagedState(), tabSelected('procedures'));

    expect(next.activeTab).toBe('procedures');
    expect(next.staged).toEqual(FINAL);
  });

  it('opens and closes a procedure', () => {
    const opened = reducer(
      undefined,
      procedureOpened({ kind: 'sid', ident: 'TEST1A', transition: null }),
    );
    expect(opened.openProcedure?.ident).toBe('TEST1A');
    expect(reducer(opened, procedureOpened(null)).openProcedure).toBeNull();
  });

  it('clears the staging bar on demand', () => {
    const next = reducer(stagedState(), staleCleared());

    expect(next.staged).toBeNull();
    expect(next.setupOverrides).toEqual({});
  });
});
