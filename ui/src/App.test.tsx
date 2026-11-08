/**
 * The shell's full-bleed behaviour when the Position screen is active: no shell header
 * (and so no shell module menu), no status bar — but the map's `keepMounted` panel must survive the round trip, hidden
 * rather than unmounted, exactly as it does outside full-bleed mode.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
  return setupStore({
    startup: readyStartupState('LEMD', 'Adolfo Suárez Madrid–Barajas Airport'),
  });
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
    expect(document.querySelector('.app__header')).not.toBeInTheDocument();
    expect(document.querySelectorAll('[aria-haspopup="menu"]')).toHaveLength(0);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});

describe('App — full-bleed Position screen', () => {
  it('hides the shell header and the status bar while Position is active', async () => {
    const store = readyStore();
    render(
      <Provider store={store}>
        <App />
      </Provider>,
    );

    expect(document.querySelector('.app__header')).not.toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    // The shell's module menu goes with its header: the only menu trigger left is the
    // one in Position's own full-bleed header, once its lazy chunk has resolved.
    await waitFor(
      () => {
        expect(document.querySelectorAll('[aria-haspopup="menu"]')).toHaveLength(1);
      },
      { timeout: 5000 },
    );
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

describe('App — module menu in the shell header', () => {
  it('navigates between modules from the dropdown, marking the current one', async () => {
    const user = userEvent.setup();
    const store = readyStore();
    render(
      <Provider store={store}>
        <App />
      </Provider>,
    );

    store.dispatch(tabSelected('weather'));
    const header = await waitFor(() => {
      const el = document.querySelector<HTMLElement>('.app__header');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });

    await user.click(within(header).getByRole('button', { name: /^Weather/ }));
    const menu = within(header).getByRole('menu', { name: 'Modules' });
    expect(within(menu).getByRole('menuitem', { name: 'Weather' })).toHaveAttribute(
      'aria-current',
      'page',
    );

    await user.click(within(menu).getByRole('menuitem', { name: 'Map' }));

    expect(store.getState().ui.activeTab).toBe('map');
    expect(
      await within(header).findByRole('button', { name: /^Map/ }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(document.getElementById('tabpanel-map')).not.toHaveAttribute('hidden');
    });
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

    const panel = await waitFor(() => {
      const el = document.getElementById('tabpanel-scenarios');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    expect(
      within(panel).getByRole('heading', { name: /scenarios delayed/i }),
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

  it('does not gate Cockpit — the real panel mounts with its own heading (#253)', async () => {
    const store = readyStore();
    render(
      <Provider store={store}>
        <App />
      </Provider>,
    );

    store.dispatch(tabSelected('cockpit'));

    // The panel is a lazy chunk; under full-suite load it can take longer than the
    // default 1 s to resolve, which is not what this test is about.
    expect(
      await screen.findByRole('heading', { name: 'Cockpit' }, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('heading', { name: /cockpit delayed/i }),
    ).not.toBeInTheDocument();
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
