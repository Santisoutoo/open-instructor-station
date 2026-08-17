import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
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
 * Seeds the `getScenarioRun` RTK Query cache directly (`upsertQueryData`) before render,
 * so a rendered `StatusBar` starts from a known cache entry without needing a stubbed
 * `fetch` for the very first paint. `StatusBar` itself now holds an ACTIVE subscription
 * (`useScenarioRunStatus`, not a passive `useQueryState` read — see StatusBar.tsx and
 * useScenarioRun.ts's module docstrings for why a passive read went stale whenever the
 * Scenarios tab was not mounted), so tests that need to observe a status *change* still
 * stub `fetch` themselves (see the regression test below) rather than relying on the seed
 * alone. `upsertQueryData` is itself an async thunk, so the seed is awaited *before*
 * rendering: otherwise the component's first render would race the cache write.
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

afterEach(() => {
  vi.unstubAllGlobals();
});

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

  it(
    'keeps polling a running scenario on its own, even with the Scenarios panel never ' +
      'mounted — regression: the chip must not go stale when the instructor switches tabs',
    async () => {
      const RUNNING: ScenarioRunStatus = {
        scenario_id: 'engine-failure-after-v1',
        status: 'running',
        steps: [{ name: 'position', status: 'done', detail: null, error: null }],
        started_at: '2026-08-17T12:00:00Z',
        finished_at: null,
      };
      const FAILED: ScenarioRunStatus = {
        ...RUNNING,
        status: 'failed',
        steps: [{ name: 'position', status: 'failed', detail: null, error: 'boom' }],
        finished_at: '2026-08-17T12:00:05Z',
      };

      let requestCount = 0;
      vi.stubGlobal(
        'fetch',
        vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
          const url = input instanceof Request ? input.url : String(input);
          if (url.includes('scenarios/run')) {
            requestCount += 1;
            return new Response(JSON.stringify(requestCount === 1 ? RUNNING : FAILED), {
              status: 200,
              headers: { 'Content-Type': 'application/json' },
            });
          }
          return new Response(JSON.stringify(null), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }),
      );

      // No `renderStatusBar` seed here on purpose: mounting fetches on its own is exactly
      // the behaviour under test -- a passive `useQueryState` reader would never do this.
      render(
        <Provider store={setupStore()}>
          <StatusBar />
        </Provider>,
      );

      expect(await screen.findByText('Engine failure after v1')).toBeInTheDocument();
      expect(requestCount).toBe(1);

      // The poll interval is 1000ms; give it real time to fire at least once more.
      await waitFor(
        () => {
          expect(screen.queryByText('Engine failure after v1')).not.toBeInTheDocument();
        },
        { timeout: 3_000 },
      );
      expect(requestCount).toBeGreaterThan(1);
    },
  );
});
