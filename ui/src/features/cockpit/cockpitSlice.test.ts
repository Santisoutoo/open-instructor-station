import { describe, expect, it } from 'vitest';
import { telemetryCleared } from '../telemetry/telemetrySlice';
import reducer, {
  actuationSettled,
  actuationStarted,
  errorDismissed,
  initialCockpitUiState,
  panelSelected,
  searchChanged,
  selectIsPending,
} from './cockpitSlice';

describe('cockpitSlice', () => {
  it('locks a control on actuationStarted and clears any previous error', () => {
    const withError = { ...initialCockpitUiState, lastError: 'stale' };

    const state = reducer(withError, actuationStarted('fd_capt'));

    expect(selectIsPending(state, 'fd_capt')).toBe(true);
    expect(state.lastError).toBeNull();
  });

  it('unlocks on a successful actuationSettled and leaves no error', () => {
    const started = reducer(initialCockpitUiState, actuationStarted('fd_capt'));

    const settled = reducer(started, actuationSettled({ controlId: 'fd_capt' }));

    expect(selectIsPending(settled, 'fd_capt')).toBe(false);
    expect(settled.lastError).toBeNull();
  });

  it('unlocks on a failed actuationSettled and records the message', () => {
    const started = reducer(initialCockpitUiState, actuationStarted('hdg_sel'));

    const settled = reducer(
      started,
      actuationSettled({ controlId: 'hdg_sel', error: 'HDG SEL needs a flight director.' }),
    );

    expect(selectIsPending(settled, 'hdg_sel')).toBe(false);
    expect(settled.lastError).toBe('HDG SEL needs a flight director.');
  });

  it('dismisses the error without touching pending locks', () => {
    const started = reducer(initialCockpitUiState, actuationStarted('mcp_alt'));
    const errored = reducer(
      started,
      actuationSettled({ controlId: 'mcp_alt', error: 'rejected' }),
    );

    const dismissed = reducer(errored, errorDismissed());

    expect(dismissed.lastError).toBeNull();
  });

  it('tracks the selected panel and the search text', () => {
    let state = reducer(initialCockpitUiState, panelSelected('overhead'));
    expect(state.selectedPanelId).toBe('overhead');

    state = reducer(state, searchChanged('light'));
    expect(state.search).toBe('light');
  });

  it('resets everything on telemetryCleared — a lost link makes every belief stale', () => {
    const dirty = {
      selectedPanelId: 'lights',
      search: 'land',
      pending: { landing_lights: true as const },
      lastError: 'boom',
    };

    expect(reducer(dirty, telemetryCleared())).toEqual(initialCockpitUiState);
  });
});
