/**
 * The Map panel's chrome and dispatches in jsdom: layer toggles, tool arming, and the
 * staged-position hand-off to the Position tab. The WebGL side is behind the maplibre
 * stub — its `load` never fires, so every imperative hook stays dormant (asserting
 * geometry on a canvas is the pure modules' job, not this test's).
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { describe, expect, it, vi } from 'vitest';
import { setupStore, type RootState } from '../../store';
import { initialMapState } from './mapSlice';
import { MapPanel } from './MapPanel';

vi.mock('maplibre-gl', () => import('../../test/maplibreStub'));

function renderPanel(preloadedState: Partial<RootState> = {}) {
  const store = setupStore(preloadedState);
  render(
    <Provider store={store}>
      <MapPanel />
    </Provider>,
  );
  return store;
}

describe('MapPanel', () => {
  it('renders the four layer toggles on and the five tools disarmed', () => {
    renderPanel();

    for (const label of ['Runways', 'ILS', 'Navaids', 'Trail']) {
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
  });

  it('a layer toggle flips exactly its overlay in the store', () => {
    const store = renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'ILS' }));
    expect(store.getState().map.layers.ils).toBe(false);
    expect(store.getState().map.layers.runways).toBe(true);
  });

  it('arming measure shows the hint chip; the second press disarms it', () => {
    renderPanel();

    const measure = screen.getByRole('button', { name: 'Measure distance' });
    fireEvent.click(measure);
    expect(measure).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('Tap two points to measure')).toBeInTheDocument();

    fireEvent.click(measure);
    expect(measure).toHaveAttribute('aria-pressed', 'false');
    expect(screen.queryByText('Tap two points to measure')).toBeNull();
  });

  it('shows the measured distance and bearing once both points are set', () => {
    renderPanel({
      map: {
        ...initialMapState,
        mode: 'measure',
        measureA: { lat: 40, lon: -3.56 },
        measureB: { lat: 41, lon: -3.56 },
      },
    });

    // One degree of latitude, due north.
    expect(screen.getByText('60.0 NM · 000°')).toBeInTheDocument();
  });

  it('sends a staged position to the Position tab as a coordinate placement', () => {
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
  });

  it('discard clears the staged position without leaving the map', () => {
    const store = renderPanel({
      map: { ...initialMapState, staged: { lat: 40.46, lon: -3.57 } },
    });

    const tabBefore = store.getState().ui.activeTab;
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }));
    expect(store.getState().map.staged).toBeNull();
    expect(store.getState().position.staged).toBeNull();
    expect(store.getState().ui.activeTab).toBe(tabBefore);
  });
});
