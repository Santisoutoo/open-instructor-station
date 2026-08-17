import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { describe, expect, it } from 'vitest';
import type { AircraftState, ScenarioRunStatus } from '../api/models';
import { scenariosApi } from '../features/scenarios/scenariosApi';
import { setupStore, type RootState } from '../store';
import { initialUiState } from '../store/uiSlice';
import { StatusBar } from './StatusBar';

const FINAL_APPROACH: AircraftState = {
  latitude: 40.47,
  longitude: -3.56,
  altitude_ft: 2_450,
  heading_deg: 323,
  ias_kt: 85.4,
  vertical_speed_fpm: -420.2,
  pitch_deg: -3,
  roll_deg: 0,
  on_ground: false,
};

/**
 * Seeds the `getScenarioRun` RTK Query cache directly (`upsertQueryData`) rather than
 * standing up a stubbed `fetch` — `StatusBar` only ever reads that cache passively
 * (`useQueryState`, never `useQuery`), so there is no request for a real API stub to
 * intercept in the first place. `upsertQueryData` is itself an async thunk, so the seed is
 * awaited *before* rendering: otherwise the component's first (and, in these tests, only)
 * render would race the cache write.
 */
async function renderStatusBar(
  preloadedState: Partial<RootState> = {},
  run?: ScenarioRunStatus,
) {
  const store = setupStore(preloadedState);
  if (run !== undefined) {
    await store.dispatch(scenariosApi.util.upsertQueryData('getScenarioRun', undefined, run));
  }
  render(
    <Provider store={store}>
      <StatusBar />
    </Provider>,
  );
  return store;
}

describe('<StatusBar />', () => {
  it('shows the four live numbers when telemetry is present', async () => {
    await renderStatusBar({
      telemetry: { latest: FINAL_APPROACH, receivedAt: 1_700_000_000_000, frameCount: 1 },
    });

    expect(screen.getByText('2,450 ft')).toBeInTheDocument();
    expect(screen.getByText('85 kt')).toBeInTheDocument();
    expect(screen.getByText('323°')).toBeInTheDocument();
    expect(screen.getByText('-420 fpm')).toBeInTheDocument();
  });

  it('says so plainly when there is no aircraft data', async () => {
    await renderStatusBar();
    expect(screen.getByText('No aircraft data')).toBeInTheDocument();
  });

  it('flags demo data with the amber chip only while the sim link is down', async () => {
    await renderStatusBar({ ui: { ...initialUiState, demoFeed: true } });
    expect(screen.getByText('Demo data')).toBeInTheDocument();
  });

  it('hides the demo chip when the real link is up, even with the feed switched on', async () => {
    await renderStatusBar({
      ui: { ...initialUiState, demoFeed: true },
      connection: {
        status: 'connected',
        lastError: null,
        lastUpdateAt: null,
        reconnectAttempts: 0,
      },
    });
    expect(screen.queryByText('Demo data')).not.toBeInTheDocument();
    expect(screen.getByText('Sim link up')).toBeInTheDocument();
  });

  it('shows the running scenario as a chip, falling back to a readable id', async () => {
    const run: ScenarioRunStatus = {
      scenario_id: 'engine-failure-after-v1',
      status: 'running',
      steps: [{ name: 'position', status: 'done', detail: null, error: null }],
      started_at: '2026-08-17T12:00:00Z',
      finished_at: null,
    };

    // No manifest has been fetched in this test, so the chip falls back to the
    // formatted id — StatusBar never fetches the catalogue itself (see StatusBar.tsx).
    await renderStatusBar({}, run);
    expect(screen.getByText('Engine failure after v1')).toBeInTheDocument();
  });

  it('shows no scenario chip once the run has settled', async () => {
    const run: ScenarioRunStatus = {
      scenario_id: 'engine-failure-after-v1',
      status: 'completed',
      steps: [],
      started_at: '2026-08-17T12:00:00Z',
      finished_at: '2026-08-17T12:00:30Z',
    };

    await renderStatusBar({}, run);
    expect(screen.queryByText('Engine failure after v1')).not.toBeInTheDocument();
  });

  it('the demo feed button toggles the store flag', async () => {
    const user = userEvent.setup();
    const store = await renderStatusBar();

    await user.click(screen.getByRole('button', { name: 'Demo feed' }));
    expect(store.getState().ui.demoFeed).toBe(true);
  });
});
