/**
 * The Position screen against a stubbed API.
 *
 * `fetch` is stubbed rather than the RTK Query hooks mocked, for the reason `testApi.ts`
 * gives: the request the screen actually sends is the thing worth asserting, and mocking a
 * hook would hide a screen that asks the wrong endpoint.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setupStore, type RootState } from '../../store';
import { PositionPanel } from './PositionPanel';
import { initialPositionDesignState } from './positionDesignSlice';
import { callsTo, stubApi, type ApiCall } from './testApi';
import { ICAO, positionRoutes } from './testFixtures';

afterEach(() => {
  vi.unstubAllGlobals();
});

const LOADED: Partial<RootState> = {
  positionDesign: { ...initialPositionDesignState, icaoInput: ICAO, loadedIcao: ICAO },
};

function renderPanel(preloadedState: Partial<RootState> = LOADED) {
  const store = setupStore(preloadedState);
  render(
    <Provider store={store}>
      <PositionPanel />
    </Provider>,
  );
  return store;
}

describe('the navdata gate', () => {
  it('replaces the body with a build offer while the index is missing', async () => {
    stubApi(
      positionRoutes({
        'navdata/status': {
          body: {
            state: 'unavailable',
            provider: 'xplane_native',
            reason: 'No index yet.',
          },
        },
      }),
    );
    renderPanel();

    expect(await screen.findByText('No index yet.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Build index' })).toBeInTheDocument();
    expect(
      screen.queryByRole('tablist', { name: 'Placement mode' }),
    ).not.toBeInTheDocument();
  });

  it('offers no build button when the index errored — the same failure would repeat', async () => {
    stubApi(
      positionRoutes({
        'navdata/status': {
          body: {
            state: 'error',
            provider: 'xplane_native',
            reason: 'apt.dat unreadable.',
          },
        },
      }),
    );
    renderPanel();

    expect(await screen.findByText('apt.dat unreadable.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Build index' })).not.toBeInTheDocument();
  });

  it('asks for an airport before showing a screen full of nothing', async () => {
    stubApi(positionRoutes());
    renderPanel({ positionDesign: initialPositionDesignState });

    expect(
      await screen.findByText(/Type an ICAO code and press Load/),
    ).toBeInTheDocument();
  });
});

describe('the loaded airport', () => {
  it('renders one runway tab per navdata runway end, with its own wind', async () => {
    stubApi(positionRoutes());
    renderPanel();

    expect(await screen.findByRole('tab', { name: '04R' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '22L' })).toBeInTheDocument();
    // 240°/12 kt: a tailwind on 04R and a headwind on 22L.
    expect(await screen.findByText('11 kt tail')).toBeInTheDocument();
    expect(screen.getByText('11 kt head')).toBeInTheDocument();
  });

  it('renders the 4 placement tabs with exactly one selected', async () => {
    stubApi(positionRoutes());
    renderPanel();

    await screen.findByRole('tab', { name: '04R' });
    const tabs = screen.getAllByRole('tab', {
      name: /Approach training|SID & STAR|Airwork|Custom location/,
    });
    expect(tabs).toHaveLength(4);
    const selected = tabs.filter((tab) => tab.getAttribute('aria-selected') === 'true');
    expect(selected).toHaveLength(1);
    expect(selected[0]).toHaveTextContent('Approach training');
  });

  it('shows the SERVER’s resolved altitude and heading, not a locally derived one', async () => {
    stubApi(positionRoutes());
    renderPanel();

    // 968 ft and 040°T come from the preview fixture, not from any arithmetic here.
    expect(await screen.findByText('968 ft MSL')).toBeInTheDocument();
    expect(screen.getAllByText('040°T').length).toBeGreaterThan(0);
    expect(screen.getByText('LFMN 04R 3 NM final')).toBeInTheDocument();
  });

  it('renders the preview’s provenance notes verbatim', async () => {
    stubApi(positionRoutes());
    renderPanel();

    expect(
      await screen.findByText(
        'Altitude from a 3.0° glidepath, 3.0 NM from the threshold.',
      ),
    ).toBeInTheDocument();
  });
});

describe('choosing a start position', () => {
  it('previews the placement the selected marker means', async () => {
    const { calls } = stubApi(positionRoutes());
    renderPanel();
    await screen.findByRole('tab', { name: '04R' });

    await userEvent.click(screen.getByRole('button', { name: 'Downwind left' }));

    await waitFor(() => {
      expect(bodiesOf(calls, 'position/preview')).toContainEqual({
        type: 'runway',
        airport_icao: ICAO,
        runway_ident: '04R',
        placement: 'left_downwind',
        pattern_width_nm: 4,
      });
    });
    expect(screen.getByRole('heading', { name: 'Downwind left' })).toBeInTheDocument();
  });

  it('sends the final the distance selector names, not the dot that was clicked', async () => {
    const { calls } = stubApi(positionRoutes());
    renderPanel();
    await screen.findByRole('tab', { name: '04R' });

    await userEvent.click(screen.getByRole('radio', { name: '10 NM' }));

    await waitFor(() => {
      expect(bodiesOf(calls, 'position/preview')).toContainEqual({
        type: 'runway',
        airport_icao: ICAO,
        runway_ident: '04R',
        placement: 'final_10nm',
      });
    });
    expect(screen.getByRole('heading', { name: '10 NM final' })).toBeInTheDocument();
  });

  it('picking a stand clears the runway tab selection and places on the stand', async () => {
    const { calls } = stubApi(positionRoutes());
    const store = renderPanel();
    await screen.findByRole('tab', { name: '04R' });
    expect(store.getState().positionDesign.selectedRunway).toBe('04R');

    await userEvent.click(screen.getByRole('button', { name: /^Start at/ }));
    await userEvent.click(await screen.findByRole('button', { name: 'Stand A1' }));

    expect(store.getState().positionDesign.selectedStand).toBe('A1');
    expect(store.getState().positionDesign.selectedRunway).toBeNull();
    await waitFor(() => {
      expect(bodiesOf(calls, 'position/preview')).toContainEqual({
        type: 'parking',
        airport_icao: ICAO,
        stand_name: 'A1',
      });
    });
  });
});

function bodiesOf(calls: readonly ApiCall[], fragment: string): unknown[] {
  return callsTo(calls, fragment).map((call) => call.body);
}
