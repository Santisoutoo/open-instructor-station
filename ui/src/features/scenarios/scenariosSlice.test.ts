/**
 * Client state of the Scenarios panel. The property that matters is order: the run's
 * checklist ticks strictly in the sequence the scenario declared, because the plan the
 * instructor is watching is the plan the engine executes.
 */

import { describe, expect, it } from 'vitest';
import reducer, {
  initialScenariosUiState,
  runCleared,
  runStarted,
  runStepCompleted,
  runStopped,
  scenarioSelected,
  selectScenarioRun,
} from './scenariosSlice';

const START = {
  id: 'wind-shear',
  name: 'Wind shear',
  steps: ['Set weather', 'Position aircraft'],
};

function startedState() {
  const selected = reducer(undefined, scenarioSelected('wind-shear'));
  return reducer(selected, runStarted(START));
}

describe('scenarioSelected', () => {
  it('selects a card', () => {
    expect(reducer(undefined, scenarioSelected('bird-strike')).selectedId).toBe(
      'bird-strike',
    );
  });

  it('clears the selection with null', () => {
    const selected = reducer(undefined, scenarioSelected('bird-strike'));
    expect(reducer(selected, scenarioSelected(null)).selectedId).toBeNull();
  });
});

describe('runStarted', () => {
  it('seeds the checklist from the declared steps, none done yet', () => {
    const run = startedState().runState;

    expect(run).not.toBeNull();
    expect(run?.id).toBe('wind-shear');
    expect(run?.name).toBe('Wind shear');
    expect(run?.stopped).toBe(false);
    expect(run?.steps).toEqual([
      { label: 'Set weather', done: false },
      { label: 'Position aircraft', done: false },
    ]);
  });

  it('stamps a numeric start time in the action, not in the reducer', () => {
    const action = runStarted(START);
    expect(typeof action.payload.startedAt).toBe('number');
    expect(startedState().runState?.startedAt).toBeGreaterThan(0);
  });
});

describe('runStepCompleted', () => {
  it('marks steps done strictly in order', () => {
    let state = startedState();

    state = reducer(state, runStepCompleted());
    expect(state.runState?.steps.map((step) => step.done)).toEqual([true, false]);

    state = reducer(state, runStepCompleted());
    expect(state.runState?.steps.map((step) => step.done)).toEqual([true, true]);
  });

  it('is a no-op once every step is done, and without a run', () => {
    let state = startedState();
    state = reducer(state, runStepCompleted());
    state = reducer(state, runStepCompleted());
    const settled = reducer(state, runStepCompleted());
    expect(settled.runState?.steps.map((step) => step.done)).toEqual([true, true]);

    expect(reducer(initialScenariosUiState, runStepCompleted()).runState).toBeNull();
  });
});

describe('runStopped / runCleared', () => {
  it('stopping flags the run, clearing removes it', () => {
    let state = reducer(startedState(), runStopped());
    expect(state.runState?.stopped).toBe(true);

    state = reducer(state, runCleared());
    expect(state.runState).toBeNull();
  });

  it('clearing keeps the card selection', () => {
    const state = reducer(reducer(startedState(), runStopped()), runCleared());
    expect(state.selectedId).toBe('wind-shear');
  });
});

describe('selectScenarioRun', () => {
  it('reads the run out of the slice slot', () => {
    const state = startedState();
    expect(selectScenarioRun({ scenarios: state })).toBe(state.runState);
    expect(selectScenarioRun({ scenarios: initialScenariosUiState })).toBeNull();
  });
});
