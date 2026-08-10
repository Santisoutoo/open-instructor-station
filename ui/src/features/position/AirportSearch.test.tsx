/**
 * The airport type-ahead.
 *
 * The index holds tens of thousands of airports, so the two things worth pinning are both
 * about **not asking**: a keystroke is not a request, and a one-character query matches too
 * much to be worth sending. Get either wrong and an instructor on a tablet generates a
 * request per keypress against a server that is also flying an aeroplane.
 *
 * The third is about failing honestly. An empty result list and an unreachable server look
 * identical to the instructor unless the component says which it is.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AirportSummary } from '../../api/models';
import { type AppStore, type RootState, setupStore } from '../../store';
import { AirportSearch } from './AirportSearch';
import { type ApiCall, type Answer, callsTo, positionState, stubApi } from './testApi';

/** Long enough for the 250 ms debounce plus the request. */
const AFTER_DEBOUNCE = { timeout: 2000 };

function airport(
  icao: string,
  name: string,
  overrides: Partial<AirportSummary> = {},
): AirportSummary {
  return {
    icao,
    name,
    position: { latitude: 40.47, longitude: -3.56, altitude_ft: 2001 },
    elevation_ft: 2001,
    longest_runway_m: 4100,
    has_procedures: true,
    ...overrides,
  };
}

function renderSearch(
  routes: Record<string, Answer>,
  preloaded: Partial<RootState> = positionState(),
): { store: AppStore; calls: ApiCall[] } {
  const { calls } = stubApi(routes);
  const store = setupStore(preloaded);
  render(
    <Provider store={store}>
      <AirportSearch />
    </Provider>,
  );
  return { store, calls };
}

const RESULTS: Record<string, Answer> = {
  'navdata/airports': { body: [airport('LEMD', 'Madrid Barajas')] },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('<AirportSearch />', () => {
  it('does not query on a single character', async () => {
    const user = userEvent.setup();
    const { calls } = renderSearch(RESULTS);

    await user.type(screen.getByRole('searchbox'), 'L');
    // Well past the debounce: the query is skipped, not merely delayed.
    await new Promise((resolve) => setTimeout(resolve, 500));

    expect(callsTo(calls, 'navdata/airports')).toEqual([]);
  });

  it('sends one request for a typed ICAO, not one per keystroke', async () => {
    const user = userEvent.setup();
    const { calls } = renderSearch(RESULTS);

    await user.type(screen.getByRole('searchbox'), 'LEMD');

    await waitFor(() => {
      expect(callsTo(calls, 'navdata/airports')).toHaveLength(1);
    }, AFTER_DEBOUNCE);
    // The wire parameter is `q`; `query` is only the client argument's name.
    expect(callsTo(calls, 'navdata/airports')[0]?.url).toContain('q=LEMD');
    // Bounded server-side; the panel never pulls the whole index down to filter it.
    expect(callsTo(calls, 'navdata/airports')[0]?.url).toContain('limit=12');
  });

  it('shows what the server ranked, with the longest runway beside it', async () => {
    const user = userEvent.setup();
    renderSearch(RESULTS);

    await user.type(screen.getByRole('searchbox'), 'madrid');

    expect(
      await screen.findByText('Madrid Barajas', {}, AFTER_DEBOUNCE),
    ).toBeInTheDocument();
    const results = screen.getByRole('list', { name: /search results/i });
    expect(within(results).getByText(/4,100 m · 13,451 ft/)).toBeInTheDocument();
  });

  it('selects an airport and clears the box', async () => {
    const user = userEvent.setup();
    const { store } = renderSearch(RESULTS);
    const box = screen.getByRole('searchbox');

    await user.type(box, 'LEMD');
    await user.click(
      await screen.findByRole('button', { name: /Madrid/ }, AFTER_DEBOUNCE),
    );

    expect(store.getState().position.selectedIcao).toBe('LEMD');
    expect(box).toHaveValue('');
  });

  it('says when nothing matched', async () => {
    const user = userEvent.setup();
    renderSearch({ 'navdata/airports': { body: [] } });

    await user.type(screen.getByRole('searchbox'), 'ZZZZ');

    expect(
      await screen.findByText(/No airport matches/, {}, AFTER_DEBOUNCE),
    ).toBeInTheDocument();
  });

  it('says the search failed rather than showing an empty list', async () => {
    // An unreachable server and "no such airport" are the same picture otherwise, and the
    // instructor retypes the code for a while before suspecting the station.
    const user = userEvent.setup();
    renderSearch({ 'navdata/airports': { status: 500, detail: 'The index is locked.' } });

    await user.type(screen.getByRole('searchbox'), 'LEMD');

    expect(
      await screen.findByText(/could not be searched/i, {}, AFTER_DEBOUNCE),
    ).toBeInTheDocument();
    expect(screen.queryByText(/No airport matches/)).not.toBeInTheDocument();
  });

  it('offers the airports used recently before anything is typed', async () => {
    const user = userEvent.setup();
    const { store } = renderSearch(
      RESULTS,
      positionState({ selectedIcao: 'LEBL', recentIcaos: ['LEBL', 'LEMD'] }),
    );

    const recent = screen.getByRole('list', { name: /recent airports/i });
    expect(within(recent).getByText('Selected')).toBeInTheDocument();

    await user.click(within(recent).getByRole('button', { name: /LEMD/ }));

    expect(store.getState().position.selectedIcao).toBe('LEMD');
  });

  it('focuses the box on Ctrl-K, so the search is reachable without the mouse', async () => {
    const user = userEvent.setup();
    renderSearch(RESULTS);
    const box = screen.getByRole('searchbox');
    expect(box).not.toHaveFocus();

    await user.keyboard('{Control>}k{/Control}');

    expect(box).toHaveFocus();
  });
});
