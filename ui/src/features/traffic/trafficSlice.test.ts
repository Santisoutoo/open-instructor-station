/**
 * Client state of the Traffic panel. The property that matters is clamping: the
 * steppers write through the reducer, and a stepper cannot show an error, so an
 * out-of-range value is corrected instead of rejected.
 */

import { describe, expect, it } from 'vitest';
import reducer, {
  countChanged,
  distanceChanged,
  initialTrafficUiState,
  spawnKindSelected,
} from './trafficSlice';

describe('initial state', () => {
  it('starts with no card used and in-range defaults', () => {
    expect(initialTrafficUiState).toEqual({
      selectedSpawnKind: null,
      params: { count: 1, distanceNm: 8 },
    });
  });
});

describe('spawnKindSelected', () => {
  it('remembers the last card tapped', () => {
    const state = reducer(undefined, spawnKindSelected('tcas-conflict'));
    expect(state.selectedSpawnKind).toBe('tcas-conflict');
  });

  it('clears the marker with null', () => {
    const selected = reducer(undefined, spawnKindSelected('birds'));
    expect(reducer(selected, spawnKindSelected(null)).selectedSpawnKind).toBeNull();
  });
});

describe('countChanged', () => {
  it('accepts values inside 1–4', () => {
    expect(reducer(undefined, countChanged(3)).params.count).toBe(3);
  });

  it('clamps below the floor to 1', () => {
    expect(reducer(undefined, countChanged(0)).params.count).toBe(1);
    expect(reducer(undefined, countChanged(-7)).params.count).toBe(1);
  });

  it('clamps above the ceiling to 4', () => {
    expect(reducer(undefined, countChanged(5)).params.count).toBe(4);
    expect(reducer(undefined, countChanged(99)).params.count).toBe(4);
  });

  it('rounds a fractional value to the nearest step', () => {
    expect(reducer(undefined, countChanged(2.6)).params.count).toBe(3);
  });
});

describe('distanceChanged', () => {
  it('accepts values inside 2–20 NM', () => {
    expect(reducer(undefined, distanceChanged(12)).params.distanceNm).toBe(12);
  });

  it('clamps below the floor to 2 NM', () => {
    expect(reducer(undefined, distanceChanged(0)).params.distanceNm).toBe(2);
    expect(reducer(undefined, distanceChanged(-3)).params.distanceNm).toBe(2);
  });

  it('clamps above the ceiling to 20 NM', () => {
    expect(reducer(undefined, distanceChanged(21)).params.distanceNm).toBe(20);
    expect(reducer(undefined, distanceChanged(500)).params.distanceNm).toBe(20);
  });

  it('rounds a fractional value to a whole mile', () => {
    expect(reducer(undefined, distanceChanged(7.4)).params.distanceNm).toBe(7);
  });
});
