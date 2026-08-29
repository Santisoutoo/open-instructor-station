/**
 * The shell's full-bleed behaviour when the Position screen is active: the shell's own
 * header/tabbar and status bar are hidden, but the Position screen embeds its own copy of
 * the same module tab bar in its 64px header — and the map's `keepMounted` panel must
 * survive the round trip, hidden rather than unmounted, exactly as it does outside
 * full-bleed mode.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { describe, expect, it, vi } from 'vitest';
import App from './App';
import { setupStore } from './store';
import { tabSelected } from './store/uiSlice';

vi.mock('maplibre-gl', () => import('./test/maplibreStub'));

describe('App — full-bleed Position screen', () => {
  it('embeds the module tab bar and hides the shell header/status bar while Position is active', async () => {
    const store = setupStore();
    const { container } = render(
      <Provider store={store}>
        <App />
      </Provider>,
    );

    // The Position screen's own embedded TabBar is a lazy chunk, so this has to be
    // awaited — a synchronous query would pass before the chunk even resolves, whether
    // or not the embedding actually worked.
    expect(
      await screen.findByRole('tablist', { name: 'Instructor station modules' }),
    ).toBeInTheDocument();

    // The shell's own header (its ConnectionBadge is also `role="status"`, so once the
    // Position screen's embedded header has mounted a blanket `queryByRole('status')`
    // would match *its* connection indicator instead) and the bottom status bar footer
    // are gone in full-bleed mode — check their containers directly rather than an ARIA
    // role that Position's own header now legitimately shares.
    expect(container.querySelector('.app__header')).toBeNull();
    expect(container.querySelector('.statusbar')).toBeNull();
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

describe('App — gated tabs', () => {
  it('shows GateDelayedPanel instead of the real panel for a gated tab', async () => {
    const store = setupStore();
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
    const store = setupStore();
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
    const store = setupStore();
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
