/**
 * The Scenarios panel end to end against the mock API: the catalogue loads through the
 * queryFn's simulated latency, the unavailable card is stated rather than hidden, and
 * the two-tap run plays out — select, run, a step ticking, stop.
 */

import { act, fireEvent, render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setupStore } from '../../store';
import { ScenariosPanel } from './ScenariosPanel';

function renderPanel() {
  const store = setupStore();
  render(
    <Provider store={store}>
      <ScenariosPanel />
    </Provider>,
  );
  return store;
}

afterEach(() => {
  vi.useRealTimers();
});

describe('ScenariosPanel', () => {
  it('renders the twelve scenario cards once the catalogue loads', async () => {
    renderPanel();

    const names = await screen.findAllByRole('heading', { level: 3 });
    expect(names).toHaveLength(12);
    expect(screen.getByText('Engine failure after V1')).toBeInTheDocument();
    expect(screen.getByText('Rejected take-off')).toBeInTheDocument();
  });

  it('shows the unavailable card disabled, with its reason visible', async () => {
    renderPanel();

    const tcas = await screen.findByRole('button', {
      name: /TCAS resolution advisory/,
    });
    expect(tcas).toBeDisabled();
    expect(
      screen.getByText('AI traffic bridge not connected (demo)'),
    ).toBeInTheDocument();
  });

  it('runs a scenario on the second tap, ticks a step, and stops on demand', async () => {
    // fireEvent, not user-event: this test fakes timers for the run engine, and
    // user-event's own internal waits then deadlock against them (observed even with
    // toFake restricted and advanceTimers wired). The assertions here are about
    // dispatches, not pointer fidelity, so the synchronous click loses nothing.
    vi.useFakeTimers({
      toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'],
    });
    const store = renderPanel();

    // Let the mock latency elapse so the catalogue is on screen.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });

    // First tap selects the card and reveals the one primary action.
    const card = screen.getByRole('button', { name: /Engine failure after V1/ });
    fireEvent.click(card);
    const run = screen.getByRole('button', { name: 'Run scenario' });

    // Second tap starts the run: the bar appears with the full pending checklist.
    fireEvent.click(run);
    expect(screen.getByRole('button', { name: 'Stop scenario' })).toBeInTheDocument();
    expect(store.getState().scenarios.runState?.steps.map((step) => step.done)).toEqual([
      false,
      false,
      false,
    ]);

    // One engine interval later the first step — and only the first — is done.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1300);
    });
    expect(store.getState().scenarios.runState?.steps.map((step) => step.done)).toEqual([
      true,
      false,
      false,
    ]);

    // Stop tears the run down and the bar goes with it.
    fireEvent.click(screen.getByRole('button', { name: 'Stop scenario' }));
    expect(store.getState().scenarios.runState).toBeNull();
    expect(screen.queryByRole('button', { name: 'Stop scenario' })).toBeNull();
  });
});
