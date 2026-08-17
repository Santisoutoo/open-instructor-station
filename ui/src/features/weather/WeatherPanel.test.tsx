/**
 * The Weather panel end to end against the mock API: the current weather loads
 * through the queryFn's simulated latency, the runway-relative tile is stated
 * rather than hidden, and the two-tap flow plays out — stage, edit surface up,
 * apply, cache updated, staging gone.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setupStore } from '../../store';
import { WeatherPanel } from './WeatherPanel';

/** A Position panel state with LEMD 32L picked, for the runway-relative preset. */
const POSITION_WITH_RUNWAY = {
  selectedIcao: 'LEMD',
  selectedRunwayIdent: '32L',
  activeTab: 'pattern' as const,
  openProcedure: null,
  staged: null,
  setupOverrides: {},
  recentIcaos: ['LEMD'],
};

function renderPanel(preloadedState?: Parameters<typeof setupStore>[0]) {
  const store = setupStore(preloadedState);
  render(
    <Provider store={store}>
      <WeatherPanel />
    </Provider>,
  );
  return store;
}

afterEach(() => {
  vi.useRealTimers();
});

describe('WeatherPanel', () => {
  it('renders the seven tiles, fails closed until the weather loads, then opens', async () => {
    renderPanel();

    const cavok = screen.getByRole('button', { name: /CAVOK/ });
    expect(cavok).toBeDisabled();
    expect(screen.getByText('Reading the current weather…')).toBeInTheDocument();

    await waitFor(() => {
      expect(cavok).toBeEnabled();
    });
    expect(screen.getAllByRole('button', { name: /./ })).toHaveLength(7);

    // The relative preset stays disabled without a runway, with the reason stated.
    expect(screen.getByRole('button', { name: /Crosswind/ })).toBeDisabled();
    expect(
      screen.getByText(
        'Relative to a runway — select an airport and runway in Position first.',
      ),
    ).toBeInTheDocument();
  });

  it('enables the crosswind tile when Position has an airport and runway', async () => {
    renderPanel({ position: POSITION_WITH_RUNWAY });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Crosswind/ })).toBeEnabled();
    });
  });

  it('stages on the first tap and applies on Apply weather, updating the readout', async () => {
    // fireEvent, not user-event: this test fakes timers for the mock latency, and
    // user-event's own internal waits then deadlock against them (observed even with
    // toFake restricted and advanceTimers wired — see ScenariosPanel.test.tsx).
    vi.useFakeTimers({
      toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'],
    });
    const store = renderPanel();

    // Let the mock latency elapse so the gate opens. `vi.waitFor` polls in small
    // increments and advances the fake clock between polls, unlike a single blind
    // `advanceTimersByTimeAsync` jump — RTK Query's dispatch-then-subscriber-notify
    // chain can still have a pending microtask hop when a big jump's promise settles,
    // which showed up as an intermittent "Reading the current weather…" failure.
    await vi.waitFor(() => {
      expect(screen.getByText('270° / 5 kt')).toBeInTheDocument();
    });

    // First tap stages: the editors and the staging bar appear, nothing applies.
    fireEvent.click(screen.getByRole('button', { name: /CAVOK/ }));
    expect(screen.getByText('Tap again to apply')).toBeInTheDocument();
    expect(screen.getByText('Staged: CAVOK')).toBeInTheDocument();
    const apply = screen.getByRole('button', { name: 'Apply weather' });

    // Apply commits; after the mock latency the cache is the applied weather.
    fireEvent.click(apply);
    await vi.waitFor(() => {
      expect(store.getState().weather.staged).toBe(false);
    });

    expect(screen.queryByRole('button', { name: 'Apply weather' })).toBeNull();
    expect(screen.getByRole('status')).toHaveTextContent('Weather applied.');
    // The current-weather readout now shows CAVOK's wind, not the fixture day's.
    expect(screen.getByText('250° / 8 kt')).toBeInTheDocument();
  });
});
