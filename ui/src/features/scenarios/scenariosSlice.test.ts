/**
 * Client state of the Scenarios panel. Thin by design (§7.2): the catalogue and a run's
 * progress are both server state in `scenariosApi.ts`'s RTK Query cache, so this slice
 * only ever tracks which card is selected and which run's bar has been dismissed.
 */

import { describe, expect, it } from 'vitest';
import reducer, {
  initialScenariosUiState,
  runDismissed,
  scenarioSelected,
} from './scenariosSlice';

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

describe('runDismissed', () => {
  it('records the dismissed run key, leaving the card selection untouched', () => {
    const selected = reducer(undefined, scenarioSelected('wind-shear'));
    const dismissed = reducer(
      selected,
      runDismissed('engine-failure-after-v1:2026-08-17T12:00:00Z'),
    );

    expect(dismissed.dismissedRunKey).toBe('engine-failure-after-v1:2026-08-17T12:00:00Z');
    expect(dismissed.selectedId).toBe('wind-shear');
  });

  it('starts with no dismissed run', () => {
    expect(initialScenariosUiState.dismissedRunKey).toBeNull();
  });

  it('overwrites the previous dismissal when a different run is dismissed', () => {
    let state = reducer(undefined, runDismissed('a:1'));
    state = reducer(state, runDismissed('b:2'));
    expect(state.dismissedRunKey).toBe('b:2');
  });
});
