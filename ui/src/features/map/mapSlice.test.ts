/**
 * The map slice's interaction rules: mode buttons are toggles that reset the
 * measurement, measure clicks cycle A → B → restart, and the trail is capped and
 * deduplicated.
 */

import { describe, expect, it } from 'vitest';
import reducer, {
  initialMapState,
  layerToggled,
  measurePointAdded,
  modeSelected,
  procedureLayerToggled,
  referenceAirportSelected,
  repositionStaged,
  stagedDiscarded,
  TRAIL_LIMIT,
  trailPointAppended,
  type MapState,
  type OpenProcedure,
} from './mapSlice';

const A = { lat: 40.46, lon: -3.57 };
const B = { lat: 40.5, lon: -3.5 };
const C = { lat: 41, lon: -3 };

describe('modeSelected', () => {
  it('arms a mode and disarms it back to pan on the second press', () => {
    const armed = reducer(initialMapState, modeSelected('measure'));
    expect(armed.mode).toBe('measure');
    expect(reducer(armed, modeSelected('measure')).mode).toBe('pan');
  });

  it('resets the measure points on every mode change', () => {
    let state = reducer(initialMapState, modeSelected('measure'));
    state = reducer(state, measurePointAdded(A));
    state = reducer(state, measurePointAdded(B));
    state = reducer(state, modeSelected('reposition'));
    expect(state.measureA).toBeNull();
    expect(state.measureB).toBeNull();
  });
});

describe('measurePointAdded', () => {
  it('cycles first point, second point, then restarts', () => {
    let state = reducer(initialMapState, measurePointAdded(A));
    expect(state.measureA).toEqual(A);
    expect(state.measureB).toBeNull();

    state = reducer(state, measurePointAdded(B));
    expect(state.measureB).toEqual(B);

    state = reducer(state, measurePointAdded(C));
    expect(state.measureA).toEqual(C);
    expect(state.measureB).toBeNull();
  });
});

describe('staged reposition', () => {
  it('stages the click and discards on demand', () => {
    const staged = reducer(initialMapState, repositionStaged(A));
    expect(staged.staged).toEqual(A);
    expect(reducer(staged, stagedDiscarded()).staged).toBeNull();
  });
});

describe('layerToggled', () => {
  it('flips exactly the named overlay', () => {
    const state = reducer(initialMapState, layerToggled('ils'));
    expect(state.layers.ils).toBe(false);
    expect(state.layers.runways).toBe(true);
  });
});

describe('referenceAirportSelected', () => {
  const SID: OpenProcedure = { kind: 'sid', ident: 'BARD3B', transition: null };

  it('sets the reference airport and clears it on null', () => {
    const selected = reducer(initialMapState, referenceAirportSelected('LEMD'));
    expect(selected.referenceIcao).toBe('LEMD');
    expect(reducer(selected, referenceAirportSelected(null)).referenceIcao).toBeNull();
  });

  it('resets the open procedures when the airport changes — never when re-selected', () => {
    let state = reducer(initialMapState, referenceAirportSelected('LEMD'));
    state = reducer(state, procedureLayerToggled(SID));
    expect(reducer(state, referenceAirportSelected('LEMD')).openProcedures).toEqual([SID]);
    expect(reducer(state, referenceAirportSelected('LEBL')).openProcedures).toEqual([]);
  });
});

describe('procedureLayerToggled', () => {
  const SID: OpenProcedure = { kind: 'sid', ident: 'BARD3B', transition: null };

  it('adds a procedure, keeps others, and removes it on the second toggle', () => {
    const other: OpenProcedure = { kind: 'approach', ident: 'I32L', transition: 'ADUXO' };
    let state = reducer(initialMapState, procedureLayerToggled(SID));
    state = reducer(state, procedureLayerToggled(other));
    expect(state.openProcedures).toEqual([SID, other]);

    state = reducer(state, procedureLayerToggled(SID));
    expect(state.openProcedures).toEqual([other]);
  });

  it('treats the same ident with a different transition as a different layer', () => {
    const viaAduxo: OpenProcedure = { kind: 'sid', ident: 'BARD3B', transition: 'ADUXO' };
    let state = reducer(initialMapState, procedureLayerToggled(SID));
    state = reducer(state, procedureLayerToggled(viaAduxo));
    expect(state.openProcedures).toHaveLength(2);
  });
});

describe('trailPointAppended', () => {
  it('drops consecutive duplicates so a paused sim does not flood the trail', () => {
    let state = reducer(initialMapState, trailPointAppended(A));
    state = reducer(state, trailPointAppended(A));
    expect(state.trail).toHaveLength(1);
  });

  it('caps the trail at the limit, dropping the oldest points', () => {
    let state: MapState = initialMapState;
    for (let i = 0; i < TRAIL_LIMIT + 5; i += 1) {
      state = reducer(state, trailPointAppended({ lat: 40 + i * 0.001, lon: -3 }));
    }
    expect(state.trail).toHaveLength(TRAIL_LIMIT);
    expect(state.trail[0]?.lat).toBeCloseTo(40.005, 10);
  });
});
