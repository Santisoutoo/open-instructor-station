import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TABS } from '../../components/tabs';
import { setupStore, type RootState } from '../../store';
import { PositionHeaderBar } from './PositionHeaderBar';
import { initialPositionDesignState } from './positionDesignSlice';
import { callsTo, stubApi } from './testApi';
import { ICAO, positionRoutes } from './testFixtures';

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderHeader(preloadedState: Partial<RootState> = {}) {
  const store = setupStore(preloadedState);
  render(
    <Provider store={store}>
      <PositionHeaderBar />
    </Provider>,
  );
  return store;
}

describe('the module tab bar', () => {
  it('renders every module as a tab', () => {
    stubApi(positionRoutes());
    renderHeader();

    expect(screen.getAllByRole('tab')).toHaveLength(TABS.length);
    for (const tab of TABS) {
      expect(screen.getByRole('tab', { name: tab.label })).toBeInTheDocument();
    }
  });

  it('switches the module tab — it is the only way off a full-bleed screen', async () => {
    stubApi(positionRoutes());
    const store = renderHeader();

    await userEvent.click(screen.getByRole('tab', { name: 'Weather' }));

    expect(store.getState().ui.activeTab).toBe('weather');
  });
});

describe('the theme toggle', () => {
  it('flips the theme', async () => {
    stubApi(positionRoutes());
    const store = renderHeader();
    const before = store.getState().ui.theme;

    await userEvent.click(
      screen.getByRole('button', { name: before === 'dark' ? 'Light' : 'Dark' }),
    );

    expect(store.getState().ui.theme).not.toBe(before);
  });
});

describe('loading an airport', () => {
  it('resolves the name through the airport search', async () => {
    const { calls } = stubApi(positionRoutes());
    renderHeader({
      positionDesign: {
        ...initialPositionDesignState,
        icaoInput: ICAO,
        loadedIcao: ICAO,
      },
    });

    expect(await screen.findByText("Nice / Côte d'Azur")).toBeInTheDocument();
    expect(callsTo(calls, 'navdata/airports').length).toBeGreaterThan(0);
  });

  it('mirrors a changed ICAO onto the shared positionSlice', async () => {
    stubApi(positionRoutes());
    const store = renderHeader();

    fireEvent.change(screen.getByLabelText('Airport ICAO code'), {
      target: { value: 'lemd' },
    });
    await userEvent.click(screen.getByRole('button', { name: 'Load' }));

    expect(store.getState().position.selectedIcao).toBe('LEMD');
    expect(store.getState().positionDesign.loadedIcao).toBe('LEMD');
  });

  it('does not re-dispatch for the same ICAO, so a staged placement survives', async () => {
    // `airportSelected` is destructive: it wipes the staged placement, the overrides and
    // the whole Weather panel through its extraReducers.
    stubApi(positionRoutes());
    const store = renderHeader({
      positionDesign: {
        ...initialPositionDesignState,
        icaoInput: ICAO,
        loadedIcao: ICAO,
      },
      position: {
        selectedIcao: ICAO,
        selectedRunwayIdent: null,
        activeTab: 'pattern',
        openProcedure: null,
        staged: {
          type: 'coordinate',
          position: { latitude: 40, longitude: -3, altitude_ft: 0 },
          heading_deg: 0,
          ias_kt: 0,
        },
        setupOverrides: {},
        recentIcaos: [ICAO],
      },
    });

    await userEvent.click(screen.getByRole('button', { name: 'Load' }));

    expect(store.getState().position.staged).not.toBeNull();
  });

  it('says so when the code is not in the index, rather than showing a blank name', async () => {
    stubApi(positionRoutes({ 'navdata/airports': { body: [] } }));
    renderHeader({
      positionDesign: {
        ...initialPositionDesignState,
        icaoInput: 'ZZZZ',
        loadedIcao: 'ZZZZ',
      },
    });

    await waitFor(() => {
      expect(screen.getByText('not in navdata')).toBeInTheDocument();
    });
  });
});
