import { render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { describe, expect, it } from 'vitest';
import { TelemetryPanel } from './TelemetryPanel';
import { setupStore, type RootState } from '../store';
import type { AircraftState } from '../api/models';

const CRUISE: AircraftState = {
  latitude: 47.447123_4,
  longitude: -122.309313_9,
  altitude_ft: 12_500.4,
  heading_deg: 47.2,
  ias_kt: 243.6,
  vertical_speed_fpm: 1800.3,
  pitch_deg: 2.51,
  roll_deg: -1.24,
  on_ground: false,
};

function renderWithState(preloadedState: Partial<RootState>) {
  const store = setupStore(preloadedState);
  return render(
    <Provider store={store}>
      <TelemetryPanel />
    </Provider>,
  );
}

describe('<TelemetryPanel />', () => {
  it('renders each value formatted for the instructor', () => {
    renderWithState({
      telemetry: { latest: CRUISE, receivedAt: 1_700_000_000_000, frameCount: 1 },
    });

    expect(screen.getByText('47.44712° N')).toBeInTheDocument();
    expect(screen.getByText('122.30931° W')).toBeInTheDocument();
    expect(screen.getByText('12,500 ft')).toBeInTheDocument();
    expect(screen.getByText('047°')).toBeInTheDocument();
    expect(screen.getByText('244 kt')).toBeInTheDocument();
    expect(screen.getByText('+1,800 fpm')).toBeInTheDocument();
    expect(screen.getByText('+2.5°')).toBeInTheDocument();
    expect(screen.getByText('-1.2°')).toBeInTheDocument();
    expect(screen.getByText('Airborne')).toBeInTheDocument();
  });

  it('shows a placeholder instead of stale numbers before the first frame', () => {
    renderWithState({ telemetry: { latest: null, receivedAt: null, frameCount: 0 } });

    expect(screen.getByText('Waiting for the first frame…')).toBeInTheDocument();
    expect(screen.queryByText(/ kt$/)).not.toBeInTheDocument();
  });
});
