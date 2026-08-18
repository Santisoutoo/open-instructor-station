/**
 * The "Apply here" commit path: it must send the *exact* request the pure default
 * computation produces — telemetry carried onto the point, `setup: null` — through
 * the same `POST /api/position/apply` the Position panel uses, disable behind the
 * imported `commitGate` with the gate's stated reason, and render a failed apply's
 * `detail` inline, verbatim.
 *
 * `fetch` is stubbed rather than the RTK Query hooks mocked, for the same reason
 * `AircraftControlPanel.test.tsx` does it: the request actually sent — URL, method,
 * body — is the thing worth asserting.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AircraftState, Capabilities } from '../../api/models';
import { setupStore, type RootState } from '../../store';
import { callsTo, stubApi, type Answer } from '../position/testApi';
import { initialMapState } from './mapSlice';
import { MapStagingBar } from './MapStagingBar';

const STAGED = { lat: 40.46, lon: -3.57 };

const CRUISE: AircraftState = {
  latitude: 40.49,
  longitude: -3.56,
  altitude_ft: 3000,
  heading_deg: 90,
  ias_kt: 250,
  vertical_speed_fpm: 0,
  pitch_deg: 0,
  roll_deg: 0,
  on_ground: false,
};

function capabilities(overrides: Partial<Capabilities> = {}): Capabilities {
  return {
    can_set_position: true,
    can_set_aircraft_state: true,
    can_set_weather: false,
    can_inject_failures: false,
    can_spawn_traffic: false,
    can_control_autopilot: false,
    can_set_fuel_payload: false,
    can_control_camera: false,
    can_pushback: false,
    ...overrides,
  };
}

interface RenderOptions {
  capabilitiesAnswer?: Answer;
  applyAnswer?: Answer;
  telemetry?: AircraftState | null;
}

function renderBar({
  capabilitiesAnswer = { body: capabilities() },
  applyAnswer = { body: { applied: true } },
  telemetry = CRUISE,
}: RenderOptions = {}) {
  const { calls } = stubApi({
    capabilities: capabilitiesAnswer,
    'position/apply': applyAnswer,
  });
  const store = setupStore({
    telemetry: { latest: telemetry, receivedAt: telemetry === null ? null : 1, frameCount: 1 },
    map: { ...initialMapState, mode: 'reposition', staged: STAGED },
  } satisfies Partial<RootState>);
  render(
    <Provider store={store}>
      <MapStagingBar staged={STAGED} />
    </Provider>,
  );
  return { store, calls };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('<MapStagingBar /> Apply here', () => {
  it('commits the telemetry-carried coordinate request with setup: null', async () => {
    const { store, calls } = renderBar();

    const apply = screen.getByRole('button', { name: 'Apply here' });
    await waitFor(() => {
      expect(apply).toBeEnabled();
    });
    fireEvent.click(apply);

    await waitFor(() => {
      expect(callsTo(calls, 'position/apply')).toHaveLength(1);
    });
    const call = callsTo(calls, 'position/apply')[0];
    expect(call?.method).toBe('POST');
    expect(call?.body).toEqual({
      placement: {
        type: 'coordinate',
        position: { latitude: 40.46, longitude: -3.57, altitude_ft: 3000 },
        heading_deg: 90,
        ias_kt: 250,
      },
      setup: null,
    });

    // A successful apply consumes the staging and drops the armed tool to pan.
    await waitFor(() => {
      expect(store.getState().map.staged).toBeNull();
    });
    expect(store.getState().map.mode).toBe('pan');
  });

  it('sends the bare ground-point defaults before any telemetry has arrived', async () => {
    const { calls } = renderBar({ telemetry: null });

    const apply = screen.getByRole('button', { name: 'Apply here' });
    await waitFor(() => {
      expect(apply).toBeEnabled();
    });
    fireEvent.click(apply);

    await waitFor(() => {
      expect(callsTo(calls, 'position/apply')).toHaveLength(1);
    });
    expect(callsTo(calls, 'position/apply')[0]?.body).toEqual({
      placement: {
        type: 'coordinate',
        position: { latitude: 40.46, longitude: -3.57, altitude_ft: 0 },
        heading_deg: null,
        ias_kt: null,
      },
      setup: null,
    });
  });

  it('is disabled with the stated reason when can_set_position is not declared', async () => {
    renderBar({
      capabilitiesAnswer: { body: capabilities({ can_set_position: false }) },
    });

    await waitFor(() => {
      expect(screen.getByText(/can_set_position/)).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: 'Apply here' })).toBeDisabled();
  });

  it('fails closed while the capabilities are still loading', () => {
    renderBar();

    // Synchronous first paint: the query has not resolved yet.
    expect(screen.getByRole('button', { name: 'Apply here' })).toBeDisabled();
    expect(screen.getByText(/waiting for the adapter capabilities/i)).toBeInTheDocument();
  });

  it('shows a failed apply’s detail verbatim and keeps the staging for a retry', async () => {
    const { store } = renderBar({
      applyAnswer: {
        status: 503,
        detail: 'The X-Plane Web API did not answer within 5 seconds.',
      },
    });

    const apply = screen.getByRole('button', { name: 'Apply here' });
    await waitFor(() => {
      expect(apply).toBeEnabled();
    });
    fireEvent.click(apply);

    expect(
      await screen.findByText('The X-Plane Web API did not answer within 5 seconds.'),
    ).toBeInTheDocument();
    expect(store.getState().map.staged).toEqual(STAGED);
  });

  it('leaves Send to Position tab and Discard in place alongside the commit', () => {
    renderBar();

    expect(
      screen.getByRole('button', { name: 'Send to Position tab' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Discard' })).toBeInTheDocument();
  });
});
