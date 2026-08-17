/**
 * The Traffic panel end to end against the mock bridge: the gate holds everything
 * closed until the manifest answers, one tap spawns through the mock latency into the
 * active list, and "Despawn all" clears the sky with no confirmation step.
 */

import { act, fireEvent, render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setupStore } from '../../store';
import { resetTrafficSequence } from './mock';
import { TrafficPanel } from './TrafficPanel';

function renderPanel() {
  const store = setupStore();
  render(
    <Provider store={store}>
      <TrafficPanel />
    </Provider>,
  );
  return store;
}

beforeEach(() => {
  resetTrafficSequence();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('TrafficPanel', () => {
  it('renders the gate banner and the seven spawn cards once the manifest loads', async () => {
    renderPanel();

    // The gate opens only after the mock latency: connected state on the banner.
    expect(await screen.findByText('connected (demo)')).toBeInTheDocument();
    expect(screen.getByText('Aircraft')).toBeInTheDocument();
    expect(screen.getByText('TCAS conflict')).toBeInTheDocument();
    expect(screen.getByText('Approach traffic')).toBeInTheDocument();
    expect(screen.getByText('No active traffic.')).toBeInTheDocument();
  });

  it('spawns on one tap and empties the list with Despawn all', async () => {
    // fireEvent, not user-event: this test fakes timers for the movement engine, and
    // user-event's own internal waits then deadlock against them (observed even with
    // toFake restricted and advanceTimers wired). The assertions here are about
    // dispatches, not pointer fidelity, so the synchronous click loses nothing.
    vi.useFakeTimers({
      toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'],
    });
    renderPanel();

    // Fail closed: before the manifest answers, the cards render but are disabled.
    const card = screen.getByRole('button', { name: /^Aircraft/ });
    expect(card).toBeDisabled();
    expect(screen.getByText(/waiting for the traffic bridge/i)).toBeInTheDocument();

    // Let the manifest latency elapse — the gate opens and the cards arm.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    expect(card).toBeEnabled();

    // One tap spawns; the entity lands in the list after the mock latency.
    fireEvent.click(card);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    expect(screen.getByText(/Active traffic/)).toBeInTheDocument();
    // Deterministic identity from the module counter: first spawn is always VLG1037.
    expect(screen.getByText('VLG1037')).toBeInTheDocument();

    // Despawn all clears the sky in one tap, no confirmation.
    fireEvent.click(screen.getByRole('button', { name: 'Despawn all' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    expect(screen.queryByText('VLG1037')).toBeNull();
    expect(screen.getByText('No active traffic.')).toBeInTheDocument();
  });
});
