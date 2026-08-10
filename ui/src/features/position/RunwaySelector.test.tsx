/**
 * The runway end picker.
 *
 * The point of the component is that **an end is not a runway**: 18L and 36R are the same
 * strip of concrete and opposite answers to "which way is the aeroplane pointing". A picker
 * that collapsed them would make "10 NM final" ambiguous, so the test asserts two buttons
 * for one runway and asserts the selection carries the end's own ident.
 *
 * The other thing worth pinning is that a **404 on the ILS is an ordinary outcome**. Most
 * runway ends have no ILS; if that made the row render an error, half of every airport
 * would look broken.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Ils, Runway } from '../../api/models';
import { type AppStore, type RootState, setupStore } from '../../store';
import { RunwaySelector } from './RunwaySelector';
import { type Answer, positionState, stubApi } from './testApi';

const THRESHOLD = { latitude: 40.47, longitude: -3.56, altitude_ft: 2001 };

function runway(ident: string, overrides: Partial<Runway> = {}): Runway {
  return {
    airport_icao: 'ZZZZ',
    ident,
    threshold: THRESHOLD,
    true_bearing_deg: 320,
    length_m: 4100,
    elevation_ft: 2001,
    displaced_threshold_m: 0,
    width_m: 60,
    surface: 'asphalt',
    ...overrides,
  };
}

const ILS: Ils = {
  airport_icao: 'ZZZZ',
  runway_ident: '32L',
  localizer_ident: 'IZZL',
  frequency_khz: 110300,
  localizer_position: THRESHOLD,
  localizer_true_deg: 320,
  localizer_mag_deg: 320,
  glideslope_deg: 3,
  has_dme: true,
};

function renderSelector(
  routes: Record<string, Answer>,
  preloaded: Partial<RootState> = positionState({ selectedIcao: 'ZZZZ' }),
): { store: AppStore } {
  stubApi(routes);
  const store = setupStore(preloaded);
  render(
    <Provider store={store}>
      <RunwaySelector icao="ZZZZ" />
    </Provider>,
  );
  return { store };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('<RunwaySelector />', () => {
  it('renders one button per runway end, not one per runway', async () => {
    renderSelector({
      '/runways/': { status: 404, detail: 'No ILS.' },
      '/runways': { body: [runway('32L'), runway('14R', { true_bearing_deg: 140 })] },
    });

    const group = await screen.findByRole('group', { name: /runway end/i });
    expect(await screen.findByRole('button', { name: /32L/ })).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /14R/ })).toBeInTheDocument();
    expect(group).toBeInTheDocument();
  });

  it('shows the length in both metres and feet', async () => {
    renderSelector({
      '/runways/': { status: 404, detail: 'No ILS.' },
      '/runways': { body: [runway('32L')] },
    });

    expect(await screen.findByText(/4,100 m · 13,451 ft/)).toBeInTheDocument();
  });

  it('selects an end, and marks only that one', async () => {
    const user = userEvent.setup();
    const { store } = renderSelector({
      '/runways/': { status: 404, detail: 'No ILS.' },
      '/runways': { body: [runway('32L'), runway('14R')] },
    });

    await user.click(await screen.findByRole('button', { name: /32L/ }));

    expect(store.getState().position.selectedRunwayIdent).toBe('32L');
    expect(screen.getAllByRole('button', { pressed: true })).toHaveLength(1);
  });

  it('badges the ILS with the frequency an instructor would tune', async () => {
    renderSelector({
      '/runways/32L/ils': { body: ILS },
      '/runways': { body: [runway('32L')] },
    });

    expect(await screen.findByText('110.30')).toBeInTheDocument();
    expect(await screen.findByText(/3\.0°/)).toBeInTheDocument();
  });

  it('draws no badge for an end without an ILS, which is the normal case', async () => {
    renderSelector({
      '/runways/': { status: 404, detail: 'No ILS is published for 14R.' },
      '/runways': { body: [runway('14R')] },
    });

    await screen.findByRole('button', { name: /14R/ });
    // The 404 is expected, so it must not surface as an error anywhere on the row.
    await waitFor(() => {
      expect(screen.queryByText(/ILS/)).not.toBeInTheDocument();
    });
    expect(screen.queryByText(/could not be read/i)).not.toBeInTheDocument();
  });

  it('says so when the runways cannot be read, instead of showing an empty list', async () => {
    renderSelector({ '/runways': { status: 500, detail: 'The index is corrupt.' } });

    expect(
      await screen.findByText(/runways of ZZZZ could not be read/i),
    ).toBeInTheDocument();
  });

  it('points an airport with no published runways at the coordinate placement instead', async () => {
    // A heliport or a strip the index knows only as a point. The panel still works — it
    // just cannot offer anything runway-relative — and it has to say which.
    renderSelector({ '/runways': { body: [] } });

    expect(await screen.findByText(/publishes no runways/i)).toBeInTheDocument();
    expect(screen.getByText(/coordinate placement still works/i)).toBeInTheDocument();
  });
});
