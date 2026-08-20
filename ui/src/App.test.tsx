/**
 * The shell's full-bleed behaviour when the Position screen is active: no header/tabbar,
 * no status bar — but the map's `keepMounted` panel must survive the round trip, hidden
 * rather than unmounted, exactly as it does outside full-bleed mode.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { describe, expect, it, vi } from 'vitest';
import App from './App';
import { setupStore } from './store';
import { tabSelected } from './store/uiSlice';

vi.mock('maplibre-gl', () => import('./test/maplibreStub'));

describe('App — full-bleed Position screen', () => {
  it('hides the module tab bar and the status bar while Position is active', () => {
    const store = setupStore();
    render(
      <Provider store={store}>
        <App />
      </Provider>,
    );

    expect(
      screen.queryByRole('tablist', { name: 'Instructor station modules' }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('keeps the map tabpanel mounted (hidden) after visiting it and returning to Position', async () => {
    const store = setupStore();
    render(
      <Provider store={store}>
        <App />
      </Provider>,
    );

    store.dispatch(tabSelected('map'));
    await waitFor(() => {
      expect(document.getElementById('tabpanel-map')).toBeInTheDocument();
    });

    store.dispatch(tabSelected('position'));

    await waitFor(() => {
      expect(document.getElementById('tabpanel-map')).toHaveAttribute('hidden');
    });
    expect(document.getElementById('tabpanel-map')).toBeInTheDocument();
  });
});
