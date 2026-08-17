import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { describe, expect, it } from 'vitest';
import type { AircraftState } from '../api/models';
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

function renderStatusBar(preloadedState: Partial<RootState> = {}) {
  const store = setupStore(preloadedState);
  render(
    <Provider store={store}>
      <StatusBar />
    </Provider>,
  );
  return store;
}

describe('<StatusBar />', () => {
  it('shows the four live numbers when telemetry is present', () => {
    renderStatusBar({
      telemetry: { latest: FINAL_APPROACH, receivedAt: 1_700_000_000_000, frameCount: 1 },
    });

    expect(screen.getByText('2,450 ft')).toBeInTheDocument();
    expect(screen.getByText('85 kt')).toBeInTheDocument();
    expect(screen.getByText('323°')).toBeInTheDocument();
    expect(screen.getByText('-420 fpm')).toBeInTheDocument();
  });

  it('says so plainly when there is no aircraft data', () => {
    renderStatusBar();
    expect(screen.getByText('No aircraft data')).toBeInTheDocument();
  });

  it('flags demo data with the amber chip only while the sim link is down', () => {
    renderStatusBar({ ui: { ...initialUiState, demoFeed: true } });
    expect(screen.getByText('Demo data')).toBeInTheDocument();
  });

  it('hides the demo chip when the real link is up, even with the feed switched on', () => {
    renderStatusBar({
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

  it('shows the running scenario as a chip, and drops it once the run stops', () => {
    const run = {
      id: 'engine-failure-v1',
      name: 'Engine failure after V1',
      startedAt: 1_700_000_000_000,
      steps: [{ label: 'Position on runway', done: true }],
      stopped: false,
    };

    renderStatusBar({ scenarios: { selectedId: null, runState: run } });
    expect(screen.getByText('Engine failure after V1')).toBeInTheDocument();
  });

  it('shows no scenario chip when the run is stopped', () => {
    renderStatusBar({
      scenarios: {
        selectedId: null,
        runState: {
          id: 'engine-failure-v1',
          name: 'Engine failure after V1',
          startedAt: 1_700_000_000_000,
          steps: [],
          stopped: true,
        },
      },
    });
    expect(screen.queryByText('Engine failure after V1')).not.toBeInTheDocument();
  });

  it('the demo feed button toggles the store flag', async () => {
    const user = userEvent.setup();
    const store = renderStatusBar();

    await user.click(screen.getByRole('button', { name: 'Demo feed' }));
    expect(store.getState().ui.demoFeed).toBe(true);
  });
});
