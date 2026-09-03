/**
 * The drag wiring, exercised for real through the maplibre stub's registries and
 * `trigger()` (map design §8.6): draggability follows the imported `commitGate`, a
 * finished drag dispatches the existing `repositionStaged` with the marker's own
 * lng/lat, and telemetry cannot snap the marker back mid-gesture.
 */

import { render, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Map as MapLibreMap } from 'maplibre-gl';
import type { AircraftState, Capabilities } from '../../api/models';
import { setupStore, type RootState } from '../../store';
import { Map as StubMap, Marker as StubMarker } from '../../test/maplibreStub';
import { telemetryFrameReceived } from '../telemetry/telemetrySlice';
import { stubApi } from '../position/testApi';
import { useAircraftMarker } from './useAircraftMarker';

vi.mock('maplibre-gl', () => import('../../test/maplibreStub'));

const FRAME: AircraftState = {
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
    can_control_cockpit: false,
    ...overrides,
  };
}

function Harness({ map }: { map: MapLibreMap }) {
  useAircraftMarker(map);
  return null;
}

function renderHook(preloadedState: Partial<RootState> = {}) {
  const store = setupStore({
    telemetry: { latest: FRAME, receivedAt: 1, frameCount: 1 },
    ...preloadedState,
  });
  const map = new StubMap() as unknown as MapLibreMap;
  render(
    <Provider store={store}>
      <Harness map={map} />
    </Provider>,
  );
  return store;
}

/** The marker the hook is currently driving — the last one constructed. */
function currentMarker(): StubMarker {
  const marker = StubMarker.created.at(-1);
  if (marker === undefined) {
    throw new Error('No marker was constructed');
  }
  return marker;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('useAircraftMarker dragging', () => {
  it('is not draggable while the capabilities are unknown, and stays so on a failed read', async () => {
    const { calls } = stubApi({ capabilities: { status: 503, detail: 'boom' } });
    renderHook();

    // The first marker exists before any answer: fails closed.
    expect(currentMarker().options.draggable).toBe(false);

    // Once the query has resolved (to an error), the gate stays shut — no marker
    // constructed at any point offered a drag handle.
    await waitFor(() => {
      expect(calls.length).toBeGreaterThan(0);
    });
    expect(StubMarker.created.every((marker) => marker.options.draggable !== true)).toBe(
      true,
    );
  });

  it('is not draggable when the adapter does not declare can_set_position', async () => {
    stubApi({
      capabilities: { body: capabilities({ can_set_position: false }) },
    });
    renderHook();

    // Give the query time to resolve; the marker must never become draggable.
    await waitFor(() => {
      expect(StubMarker.created.length).toBeGreaterThan(0);
    });
    expect(StubMarker.created.every((marker) => marker.options.draggable !== true)).toBe(
      true,
    );
  });

  it('becomes draggable once both required capabilities are declared', async () => {
    stubApi({ capabilities: { body: capabilities() } });
    renderHook();

    await waitFor(() => {
      expect(currentMarker().options.draggable).toBe(true);
    });
  });

  it('a finished drag stages the marker position through repositionStaged', async () => {
    stubApi({ capabilities: { body: capabilities() } });
    const store = renderHook();

    await waitFor(() => {
      expect(currentMarker().options.draggable).toBe(true);
    });
    const marker = currentMarker();

    marker.trigger('dragstart');
    // The real library moves the marker itself during the drag; simulate that.
    marker.setLngLat({ lng: -3.57, lat: 40.46 });

    // A telemetry frame arriving mid-drag must not snap the marker back.
    store.dispatch(telemetryFrameReceived({ state: FRAME, receivedAt: 2 }));
    expect(marker.getLngLat()).toEqual({ lng: -3.57, lat: 40.46 });

    marker.trigger('dragend');
    expect(store.getState().map.staged).toEqual({ lat: 40.46, lon: -3.57 });

    // After the drag, telemetry drives the marker again.
    store.dispatch(telemetryFrameReceived({ state: FRAME, receivedAt: 3 }));
    expect(marker.getLngLat()).toEqual({ lng: FRAME.longitude, lat: FRAME.latitude });
  });
});
