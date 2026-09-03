/**
 * The shell's full-bleed behaviour when the Position screen is active: no header/tabbar,
 * no status bar — but the map's `keepMounted` panel must survive the round trip, hidden
 * rather than unmounted, exactly as it does outside full-bleed mode.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { describe, expect, it, vi } from 'vitest';
import App from './App';
import { SUPPORT_URL } from './config/support';
import { readyStartupState } from './features/startup/testFixtures';
import { setupStore } from './store';
import { tabSelected } from './store/uiSlice';

vi.mock('maplibre-gl', () => import('./test/maplibreStub'));

/** Bypasses the startup gate: every test in this file except the gate's own is about what
 * is behind it. */
function readyStore() {
  return setupStore({ startup: readyStartupState('LEMD', 'Adolfo Suárez Madrid–Barajas Airport') });
}

describe('App — the startup gate', () => {
  it('blocks the shell by default, with no preloaded startup state', () => {
    const store = setupStore();
    render(
      <Provider store={store}>
        <App />
      </Provider>,
    );

    expect(screen.getByRole('dialog', { name: 'Choose an airport' })).toBeInTheDocument();
    expect(
      screen.queryByRole('tablist', { name: 'Instructor station modules' }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});

describe('App — full-bleed Position screen', () => {
  it('hides the module tab bar and the status bar while Position is active', () => {
    const store = readyStore();
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
    const store = readyStore();
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

describe('App — gated tabs', () => {
  it('shows GateDelayedPanel instead of the real panel for a gated tab', async () => {
    const store = readyStore();
    render(
      <Provider store={store}>
        <App />
      </Provider>,
    );

    store.dispatch(tabSelected('scenarios'));

    expect(
      await screen.findByRole('region', { name: 'Scenarios' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: /scenarios delayed/i }),
    ).toBeInTheDocument();
  });

  it('does not gate Position or Weather', async () => {
    const store = readyStore();
    render(
      <Provider store={store}>
        <App />
      </Provider>,
    );

    store.dispatch(tabSelected('weather'));

    await waitFor(() => {
      expect(
        screen.queryByRole('heading', { name: /weather delayed/i }),
      ).not.toBeInTheDocument();
    });
  });

  it('"Back to home" on a gated panel returns to Position', async () => {
    const store = readyStore();
    render(
      <Provider store={store}>
        <App />
      </Provider>,
    );

    store.dispatch(tabSelected('scenarios'));
    const back = await screen.findByRole('button', { name: /back to home/i });
    back.click();

    await waitFor(() => {
      expect(store.getState().ui.activeTab).toBe('position');
    });
  });
});

describe('App — support link', () => {
  it('renders the Buy Me a Coffee support link pointing at SUPPORT_URL', async () => {
    const store = readyStore();
    render(
      <Provider store={store}>
        <App />
      </Provider>,
    );

    // The header (and the support link inside it) is only rendered outside the
    // full-bleed Position tab, which is the default active tab.
    store.dispatch(tabSelected('weather'));

    const link = await screen.findByRole('link', {
      name: 'Support the project — Buy Me a Coffee',
    });
    expect(link).toHaveAttribute('href', SUPPORT_URL);
    expect(link).toHaveAttribute('target', '_blank');
    expect(link.getAttribute('rel')).toContain('noreferrer');
  });
});
