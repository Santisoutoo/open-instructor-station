/**
 * Client state of the Fuel & Payload panel. The property that matters most: a preset
 * change wipes the overlay and the override flag — a violation acknowledged for one
 * loadout must not silently carry over to the next (§8.2 of the design).
 */

import { describe, expect, it } from 'vitest';
import type { PayloadStation, TankFuel } from '../../api/models';
import reducer, {
  cleared,
  initialFuelPayloadState,
  overrideToggled,
  presetSelected,
  stationEdited,
  tankEdited,
} from './fuelPayloadSlice';

const TANKS: TankFuel[] = [
  { tank_index: 0, fuel_kg: 50 },
  { tank_index: 1, fuel_kg: 50 },
];

const STATIONS: PayloadStation[] = [
  { station_index: 0, kind: 'crew', label: 'Pilot', weight_kg: 90 },
];

describe('presetSelected', () => {
  it('stages the preset with a clean overlay and no override', () => {
    const state = reducer(initialFuelPayloadState, presetSelected('training'));

    expect(state.selectedPresetId).toBe('training');
    expect(state.overlay).toEqual({});
    expect(state.overrideEnvelope).toBe(false);
    expect(state.staged).toEqual({
      preset: 'training',
      loadout: null,
      override_envelope: false,
    });
  });

  it('clears a previous overlay and override when another preset is staged', () => {
    let state = reducer(initialFuelPayloadState, presetSelected('full'));
    state = reducer(state, tankEdited(TANKS));
    state = reducer(state, overrideToggled());
    expect(state.overrideEnvelope).toBe(true);
    expect(state.overlay.tanks).toEqual(TANKS);

    state = reducer(state, presetSelected('empty'));

    expect(state.selectedPresetId).toBe('empty');
    expect(state.overlay).toEqual({});
    expect(state.overrideEnvelope).toBe(false);
    expect(state.staged).toEqual({
      preset: 'empty',
      loadout: null,
      override_envelope: false,
    });
  });
});

describe('tankEdited / stationEdited', () => {
  it('stages a manual overlay with no preset', () => {
    const state = reducer(initialFuelPayloadState, tankEdited(TANKS));

    expect(state.selectedPresetId).toBeNull();
    expect(state.staged).toEqual({
      preset: null,
      loadout: { tanks: TANKS },
      override_envelope: false,
    });
  });

  it('accumulates tanks and stations into the same overlay', () => {
    let state = reducer(initialFuelPayloadState, tankEdited(TANKS));
    state = reducer(state, stationEdited(STATIONS));

    expect(state.overlay).toEqual({ tanks: TANKS, stations: STATIONS });
    expect(state.staged?.loadout).toEqual({ tanks: TANKS, stations: STATIONS });
  });
});

describe('overrideToggled', () => {
  it('flips the flag and keeps it reflected on the staged request', () => {
    let state = reducer(initialFuelPayloadState, presetSelected('full'));
    state = reducer(state, overrideToggled());

    expect(state.overrideEnvelope).toBe(true);
    expect(state.staged?.override_envelope).toBe(true);

    state = reducer(state, overrideToggled());
    expect(state.overrideEnvelope).toBe(false);
    expect(state.staged?.override_envelope).toBe(false);
  });
});

describe('cleared', () => {
  it('returns the panel to the initial state whole', () => {
    let state = reducer(initialFuelPayloadState, presetSelected('full'));
    state = reducer(state, tankEdited(TANKS));

    expect(reducer(state, cleared())).toEqual(initialFuelPayloadState);
  });
});
