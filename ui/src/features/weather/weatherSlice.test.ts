/**
 * Client state of the Weather panel. The properties that matter: staging replaces
 * wholesale (overrides never leak between presets), and an airport change wipes the
 * staging — a crosswind staged against one field is meaningless at another.
 */

import { describe, expect, it } from 'vitest';
import { airportSelected } from '../position/positionSlice';
import reducer, {
  initialWeatherUiState,
  overrideSet,
  presetStaged,
  stagingCleared,
} from './weatherSlice';

function stagedState() {
  return reducer(undefined, presetStaged('storm'));
}

describe('presetStaged', () => {
  it('stages the preset with a clean overlay', () => {
    const state = stagedState();
    expect(state.selectedPresetId).toBe('storm');
    expect(state.staged).toBe(true);
    expect(state.overrides).toEqual({});
  });

  it('clears the previous preset’s overrides when another is staged', () => {
    let state = stagedState();
    state = reducer(state, overrideSet({ field: 'qnh_hpa', value: 1005 }));
    state = reducer(state, presetStaged('cavok'));
    expect(state.selectedPresetId).toBe('cavok');
    expect(state.overrides).toEqual({});
  });
});

describe('overrideSet', () => {
  it('stores only the fields actually touched', () => {
    let state = stagedState();
    state = reducer(state, overrideSet({ field: 'visibility_m', value: 5000 }));
    state = reducer(state, overrideSet({ field: 'temperature_c', value: 12 }));
    expect(state.overrides).toEqual({ visibility_m: 5000, temperature_c: 12 });
  });

  it('removes an override with null', () => {
    let state = stagedState();
    state = reducer(state, overrideSet({ field: 'visibility_m', value: 5000 }));
    state = reducer(state, overrideSet({ field: 'visibility_m', value: null }));
    expect(state.overrides).toEqual({});
  });

  it('stores the new fields the real model added over the mock one', () => {
    let state = stagedState();
    state = reducer(
      state,
      overrideSet({ field: 'runway_contamination', value: 'wet' }),
    );
    state = reducer(state, overrideSet({ field: 'precipitation_ratio', value: 0.4 }));
    expect(state.overrides).toEqual({
      runway_contamination: 'wet',
      precipitation_ratio: 0.4,
    });
  });
});

describe('stagingCleared', () => {
  it('returns the panel to the initial state whole', () => {
    let state = stagedState();
    state = reducer(state, overrideSet({ field: 'qnh_hpa', value: 990 }));
    expect(reducer(state, stagingCleared())).toEqual(initialWeatherUiState);
  });
});

describe('airport change', () => {
  it('clears the staged preset and overrides when the airport changes', () => {
    let state = stagedState();
    state = reducer(state, overrideSet({ field: 'qnh_hpa', value: 990 }));
    expect(reducer(state, airportSelected('LEBL'))).toEqual(initialWeatherUiState);
  });

  it('leaves an empty staging untouched in shape', () => {
    expect(reducer(initialWeatherUiState, airportSelected('LEMD'))).toEqual(
      initialWeatherUiState,
    );
  });
});
