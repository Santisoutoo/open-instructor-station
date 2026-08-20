/**
 * The Map panel's chrome and dispatches in jsdom: layer toggles, tool arming, the
 * navdata gate on the overlay rail, the exact-measure swap and the staged-position
 * hand-off to the Position tab. The WebGL side is behind the maplibre stub — its
 * `load` never fires, so every imperative hook stays dormant (asserting geometry on a
 * canvas is the pure modules' job, not this test's). `fetch` is stubbed rather than
 * the RTK Query hooks mocked, the same choice every other panel test makes.
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setupStore, type RootState } from '../../store';
import { stubApi, type Answer } from '../position/testApi';
import { initialMapState } from './mapSlice';
import { MapPanel } from './MapPanel';

vi.mock('maplibre-gl', () => import('../../test/maplibreStub'));

const STATUS_UNAVAILABLE: Answer = {
  body: { state: 'unavailable', reason: 'No navigation data has been indexed yet.' },
};

const STATUS_READY: Answer = { body: { state: 'ready' } };

function renderPanel(
  preloadedState: Partial<RootState> = {},
  routes: Record<string, Answer> = { 'navdata/status': STATUS_UNAVAILABLE },
) {
  stubApi(routes);
  const store = setupStore(preloadedState);
  render(
    <Provider store={store}>
      <MapPanel />
    </Provider>,
  );
  return store;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('MapPanel', () => {
  it('renders the seven layer toggles and the tools disarmed', async () => {
    renderPanel();

    for (const label of [
      'Runways',
      'ILS',
      'Navaids',
      'Waypoints',
      'Procedures',
      'METAR',
      'Trail',
    ]) {
      expect(screen.getByRole('button', { name: label })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
    }
    expect(screen.getByRole('button', { name: 'Follow aircraft' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    expect(screen.getByRole('button', { name: 'Measure distance' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    await screen.findByText('No navigation data has been indexed yet.');
  });

  it('a layer toggle flips exactly its overlay in the store', async () => {
    const store = renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'ILS' }));
    expect(store.getState().map.layers.ils).toBe(false);
    expect(store.getState().map.layers.runways).toBe(true);
    await screen.findByText('No navigation data has been indexed yet.');
  });

  it('shows the navdata status card — with the build action — while the index is not ready', async () => {
    renderPanel();

    expect(
      await screen.findByText('No navigation data has been indexed yet.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Build index' })).toBeEnabled();
    // The overlay rail is gated; the reposition tools are NOT (D7).
    expect(screen.queryByText('Reference airport')).toBeNull();
    expect(screen.getByRole('button', { name: 'Reposition aircraft' })).toBeEnabled();
  });

  it('shows the reference-airport picker instead of the card once the index is ready', async () => {
    renderPanel({}, { 'navdata/status': STATUS_READY });

    expect(await screen.findByText('Reference airport')).toBeInTheDocument();
    expect(screen.queryByText('No navigation data has been indexed yet.')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Build index' })).toBeNull();
  });

  it('arming measure shows the hint chip; the second press disarms it', async () => {
    renderPanel();

    const measure = screen.getByRole('button', { name: 'Measure distance' });
    fireEvent.click(measure);
    expect(measure).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('Tap two points to measure')).toBeInTheDocument();

    fireEvent.click(measure);
    expect(measure).toHaveAttribute('aria-pressed', 'false');
    expect(screen.queryByText('Tap two points to measure')).toBeNull();
    await screen.findByText('No navigation data has been indexed yet.');
  });

  it('shows the spherical reading instantly, then the exact WGS84 answer replaces it', async () => {
    renderPanel(
      {
        map: {
          ...initialMapState,
          mode: 'measure',
          measureA: { lat: 40, lon: -3.56 },
          measureB: { lat: 41, lon: -3.56 },
        },
      },
      {
        'navdata/status': STATUS_UNAVAILABLE,
        'geodesy/measure': { body: { distance_nm: 60.3, initial_bearing_true_deg: 0.7 } },
      },
    );

    // One degree of latitude, due north — the client-side spherical placeholder…
    expect(screen.getByText('60.0 NM · 000°')).toBeInTheDocument();
    // …replaced by the server's exact geodesic answer once it resolves (D9).
    expect(await screen.findByText('60.3 NM · 001°')).toBeInTheDocument();
    expect(screen.queryByText('60.0 NM · 000°')).toBeNull();
  });

  it('sends a staged position to the Position tab as a coordinate placement', async () => {
    const store = renderPanel({
      map: {
        ...initialMapState,
        mode: 'reposition',
        staged: { lat: 40.46, lon: -3.57 },
      },
    });
    expect(screen.getByText('40.46000, -3.57000')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Send to Position tab' }));

    const state = store.getState();
    expect(state.position.staged).toEqual({
      type: 'coordinate',
      position: { latitude: 40.46, longitude: -3.57, altitude_ft: 0 },
      heading_deg: 0,
      ias_kt: 0,
    });
    expect(state.position.activeTab).toBe('coordinate');
    expect(state.ui.activeTab).toBe('position');
    // The map's own staging is consumed and the mode drops back to pan.
    expect(state.map.staged).toBeNull();
    expect(state.map.mode).toBe('pan');
    await screen.findByText('No navigation data has been indexed yet.');
  });

  it('discard clears the staged position without leaving the map', async () => {
    const store = renderPanel({
      map: { ...initialMapState, staged: { lat: 40.46, lon: -3.57 } },
    });

    const tabBefore = store.getState().ui.activeTab;
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }));
    expect(store.getState().map.staged).toBeNull();
    expect(store.getState().position.staged).toBeNull();
    expect(store.getState().ui.activeTab).toBe(tabBefore);
    await screen.findByText('No navigation data has been indexed yet.');
  });
});
