/**
 * Gates, stands, tie-downs and hangars.
 *
 * The two filters look alike on screen and are not alike at all, which is the thing worth
 * pinning: the **kind** filter is a query parameter the server answers, and the **name**
 * filter is a client-side narrowing of what already arrived. Getting them the wrong way
 * round would either fetch several hundred stands to show four, or fetch four and quietly
 * hide the rest of the airport.
 *
 * The staged request is asserted with `toEqual` for the same reason as in the pattern grid:
 * a stand placement is on the ground, and any speed the panel invented on its way there
 * would be a speed the server never asked for.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ParkingKind, ParkingStand } from '../../api/models';
import { type AppStore, setupStore } from '../../store';
import { ParkingList } from './ParkingList';
import { type ApiCall, type Answer, callsTo, positionState, stubApi } from './testApi';

/** The full `kind` enum, spelled out so the toolbar cannot fall behind the server. */
const EVERY_KIND: Record<ParkingKind, true> = {
  gate: true,
  hangar: true,
  tie_down: true,
  misc: true,
};

function stand(
  name: string,
  kind: ParkingKind = 'gate',
  overrides: Partial<ParkingStand> = {},
): ParkingStand {
  return {
    airport_icao: 'ZZZZ',
    name,
    position: { latitude: 40.47, longitude: -3.56, altitude_ft: 2001 },
    heading_true_deg: 91.7,
    kind,
    aircraft_types: [],
    airline_codes: [],
    ...overrides,
  };
}

const STANDS = [
  stand('R32'),
  stand('R33'),
  stand('T7', 'tie_down'),
  stand('Maintenance 1', 'hangar'),
];

function renderList(routes: Record<string, Answer> = { '/parking': { body: STANDS } }): {
  store: AppStore;
  calls: ApiCall[];
} {
  const { calls } = stubApi(routes);
  const store = setupStore(positionState({ selectedIcao: 'ZZZZ' }));
  render(
    <Provider store={store}>
      <ParkingList icao="ZZZZ" />
    </Provider>,
  );
  return { store, calls };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('<ParkingList />', () => {
  it('offers a filter for every kind the server publishes, plus "all"', async () => {
    renderList();
    await screen.findByText('R32');

    for (const label of ['All', 'Gates', 'Tie-downs', 'Hangars', 'Other']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }
    // One chip per member of the enum, plus "All". If the server grows a kind, this file
    // stops compiling until the toolbar grows a chip.
    expect(Object.keys(EVERY_KIND)).toHaveLength(4);
  });

  it('lists every stand with its kind and its parked heading', async () => {
    renderList();

    expect(await screen.findByText('R32')).toBeInTheDocument();
    expect(screen.getByText('Maintenance 1')).toBeInTheDocument();
    // `tie_down` is a wire value, not something to show an instructor.
    expect(screen.getByText('tie down')).toBeInTheDocument();
    expect(screen.getAllByText('92°')).toHaveLength(STANDS.length);
  });

  it('asks the server for one kind rather than filtering hundreds client-side', async () => {
    const user = userEvent.setup();
    const { calls } = renderList();
    await screen.findByText('R32');

    await user.click(screen.getByRole('button', { name: 'Tie-downs' }));

    const parking = callsTo(calls, '/parking');
    expect(parking.at(-1)?.url).toContain('kind=tie_down');
    // The unfiltered first load must not have sent a kind at all.
    expect(parking[0]?.url).not.toContain('kind=');
  });

  it('filters by name without going back to the server', async () => {
    const user = userEvent.setup();
    const { calls } = renderList();
    await screen.findByText('R32');
    const before = callsTo(calls, '/parking').length;

    await user.type(screen.getByPlaceholderText(/filter by name/i), 'r3');

    expect(screen.getByText('R32')).toBeInTheDocument();
    expect(screen.queryByText('T7')).not.toBeInTheDocument();
    expect(callsTo(calls, '/parking')).toHaveLength(before);
  });

  it('distinguishes "no such stand" from "this airport publishes none"', async () => {
    const user = userEvent.setup();
    renderList();
    await screen.findByText('R32');

    await user.type(screen.getByPlaceholderText(/filter by name/i), 'zzz');

    expect(screen.getByText(/no stand matches that filter/i)).toBeInTheDocument();
    expect(screen.queryByText(/publishes no parking positions/i)).not.toBeInTheDocument();
  });

  it('says so when the airport publishes no parking at all', async () => {
    renderList({ '/parking': { body: [] } });

    expect(
      await screen.findByText(/ZZZZ publishes no parking positions/i),
    ).toBeInTheDocument();
  });

  it('says so when the parking could not be read, rather than showing an empty list', async () => {
    renderList({ '/parking': { status: 500, detail: 'apt.dat is unreadable.' } });

    expect(
      await screen.findByText(/parking of ZZZZ could not be read/i),
    ).toBeInTheDocument();
  });

  it('stages a stand by name alone and commands no speed of its own', async () => {
    const user = userEvent.setup();
    const { store, calls } = renderList();

    await user.click(await screen.findByRole('button', { name: /R32/ }));

    expect(store.getState().position.staged).toEqual({
      type: 'parking',
      airport_icao: 'ZZZZ',
      stand_name: 'R32',
    });
    // Staging is not commanding: nothing was applied.
    expect(callsTo(calls, '/position/apply')).toEqual([]);
  });

  it('marks the staged stand, and only it', async () => {
    const user = userEvent.setup();
    renderList();

    await user.click(await screen.findByRole('button', { name: /R33/ }));

    const pressed = screen
      .getAllByRole('button', { pressed: true })
      .map((node) => node.textContent);
    // "All" is also a pressed chip; the stand is the only pressed *stand*.
    expect(pressed.filter((text) => text?.includes('R33'))).toHaveLength(1);
    expect(pressed.filter((text) => text?.includes('R32'))).toEqual([]);
  });
});
