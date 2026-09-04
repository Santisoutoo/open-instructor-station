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
  slotFocused,
  viewModeSet,
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
      actuationSettled({
        controlId: 'hdg_sel',
        error: 'HDG SEL needs a flight director.',
      }),
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

  it('starts in the schematic view with nothing focused', () => {
    expect(initialCockpitUiState.viewMode).toBe('schematic');
    expect(initialCockpitUiState.focusedControlId).toBeNull();
  });

  it('focuses and clears a slot', () => {
    let state = reducer(initialCockpitUiState, slotFocused('mcp_hdg'));
    expect(state.focusedControlId).toBe('mcp_hdg');

    state = reducer(state, slotFocused(null));
    expect(state.focusedControlId).toBeNull();
  });

  it('switches the view mode and drops the focused slot with it', () => {
    const focused = reducer(initialCockpitUiState, slotFocused('mcp_hdg'));

    const listed = reducer(focused, viewModeSet('list'));

    expect(listed.viewMode).toBe('list');
    expect(listed.focusedControlId).toBeNull();
  });

  it('drops the focused slot when another panel is selected', () => {
    const focused = reducer(initialCockpitUiState, slotFocused('mcp_hdg'));

    const switched = reducer(focused, panelSelected('overhead'));

    expect(switched.selectedPanelId).toBe('overhead');
    expect(switched.focusedControlId).toBeNull();
  });

  it('keeps the focused slot across a search edit and an actuation', () => {
    let state = reducer(initialCockpitUiState, slotFocused('mcp_alt'));
    state = reducer(state, searchChanged('alt'));
    state = reducer(state, actuationStarted('mcp_alt'));
    state = reducer(state, actuationSettled({ controlId: 'mcp_alt' }));

    expect(state.focusedControlId).toBe('mcp_alt');
  });

  it('resets everything except the view mode on telemetryCleared', () => {
    // A lost link makes every belief about the sim stale; how the instructor likes to
    // look at the cockpit is not a belief about the sim.
    const dirty = {
      selectedPanelId: 'lights',
      viewMode: 'list' as const,
      focusedControlId: 'landing_lights',
      search: 'land',
      pending: { landing_lights: true as const },
      lastError: 'boom',
    };

    expect(reducer(dirty, telemetryCleared())).toEqual({
      ...initialCockpitUiState,
      viewMode: 'list',
    });
  });
});
