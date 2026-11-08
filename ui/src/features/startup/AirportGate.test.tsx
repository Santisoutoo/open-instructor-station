/**
 * `AirportGate`'s own component tests.
 *
 * `fetch` is stubbed rather than the RTK Query hooks mocked — the same reasoning
 * `features/aircraft/AircraftControlPanel.test.tsx` gives: the request the gate actually
 * sends is the thing worth asserting, and mocking the hooks would hide a gate that asks the
 * wrong endpoint. There is no MSW anywhere in this repository (only a transitive mention in
 * `package-lock.json`); `vi.stubGlobal('fetch', fetchStub)` is the established pattern.
 *
 * Real timers throughout: the debounce (250 ms) and the RTK Query round trip are both real
 * async work, and `waitFor` already retries — a fake-timers harness buys nothing here and
 * risks the interaction between `userEvent`, RTK Query's own microtasks and the debounce
 * `setTimeout` resolving out of order.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Airport, AirportSummary, NavdataStatus } from '../../api/models';
import { setupStore, type RootState } from '../../store';
import { AirportGate } from './AirportGate';

const NAVDATA_READY: NavdataStatus = {
  state: 'ready',
  provider: 'in_memory',
  airac_cycle: '2508',
};

const NAVDATA_BUILDING: NavdataStatus = {
  state: 'building',
  provider: 'in_memory',
  reason: 'Indexing…',
  progress: {
    stage: 'airports',
    stage_index: 1,
    stage_count: 6,
    fraction: 0.4,
    detail: 'Reading apt.dat…',
  },
};

const LEMD_SUMMARY: AirportSummary = {
  icao: 'LEMD',
  iata: 'MAD',
  name: 'Adolfo Suárez Madrid–Barajas',
  position: { latitude: 40.4936, longitude: -3.5668, altitude_ft: 1998 },
  elevation_ft: 1998,
  longest_runway_m: 4350,
  has_procedures: true,
};

const LEMD: Airport = {
  icao: 'LEMD',
  iata: 'MAD',
  name: 'Adolfo Suárez Madrid–Barajas',
  position: { latitude: 40.4936, longitude: -3.5668, altitude_ft: 1998 },
  elevation_ft: 1998,
  has_tower: true,
  runway_count: 4,
  longest_runway_m: 4350,
  has_procedures: true,
};

interface StubOptions {
  navdata?: NavdataStatus;
  search?: readonly AirportSummary[];
  airportStatus?: number;
  airportBody?: unknown;
}

/** Every request path the gate made, in order — asserted against so a debounce regression
 * shows up as "more than one search request", not as a passing test that never checked. */
function stubFetch({
  navdata = NAVDATA_READY,
  search = [LEMD_SUMMARY],
  airportStatus = 200,
  airportBody,
}: StubOptions = {}) {
  const requested: string[] = [];
  const fetchStub = vi.fn(async (input: RequestInfo | URL) => {
    const request = input instanceof Request ? input : new Request(input);
    const url = new URL(request.url);
    requested.push(url.pathname + url.search);

    if (url.pathname === '/api/navdata/status') {
      return Response.json(navdata);
    }
    if (url.pathname === '/api/navdata/index' && request.method === 'POST') {
      return Response.json(navdata);
    }
    const airportMatch = /^\/api\/navdata\/airports\/([^/]+)$/.exec(url.pathname);
    if (airportMatch) {
      const icao = airportMatch[1];
      if (airportStatus !== 200) {
        return new Response(
          JSON.stringify(airportBody ?? { detail: `No such airport ${icao}` }),
          { status: airportStatus },
        );
      }
      return Response.json(airportBody ?? { ...LEMD, icao });
    }
    if (url.pathname === '/api/navdata/airports') {
      return Response.json(search);
    }
    return new Response('not found', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchStub);
  return { fetchStub, requested };
}

function renderGate(preloadedState?: Partial<RootState>) {
  const store = setupStore(preloadedState);
  return {
    store,
    ...render(
      <Provider store={store}>
        <AirportGate />
      </Provider>,
    ),
  };
}

/** Past the 250 ms debounce, comfortably. */
async function settleDebounce() {
  await new Promise((resolve) => {
    setTimeout(resolve, 320);
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('AirportGate — typing and search', () => {
  it('auto-focuses the input, which has an accessible name; under 2 characters shows the hint, not the listbox', async () => {
    stubFetch();
    renderGate();

    // The accessible name test: a screen reader landing on this autofocused first control of
    // the whole app must hear more than "combobox, edit" (a bare `placeholder` is not a
    // reliable accessible name).
    const input = await screen.findByRole('combobox', { name: /airport/i });
    expect(input).toHaveFocus();
    expect(screen.getByText(/type at least 2 characters/i)).toBeInTheDocument();
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('debounces search: typing "LEM" issues one search request, not one per keystroke', async () => {
    const { requested } = stubFetch();
    const user = userEvent.setup();
    renderGate();

    await user.type(await screen.findByRole('combobox'), 'LEM');
    await settleDebounce();

    await waitFor(() => {
      expect(screen.getByRole('listbox')).toBeInTheDocument();
    });

    const searchRequests = requested.filter((url) => url.startsWith('/api/navdata/airports?'));
    expect(searchRequests).toHaveLength(1);
  });

  it('shows suggestions and resolves on a click', async () => {
    stubFetch();
    const user = userEvent.setup();
    const { store } = renderGate();

    await user.type(await screen.findByRole('combobox'), 'LEM');
    await settleDebounce();

    const option = await screen.findByRole('option', { name: /LEMD/ });
    await user.click(option);

    await waitFor(() => {
      expect(store.getState().startup.status).toBe('ready');
    });
    expect(store.getState().startup.icao).toBe('LEMD');
    expect(store.getState().position.selectedIcao).toBe('LEMD');
    expect(store.getState().positionDesign.loadedIcao).toBe('LEMD');
  });
});

describe('AirportGate — errors', () => {
  it('a 404 on getAirport lands in error with the exact message; typing again clears it', async () => {
    stubFetch({ airportStatus: 404 });
    const user = userEvent.setup();
    const { store } = renderGate();

    const input = await screen.findByRole('combobox');
    await user.type(input, 'ZZZZ');
    await settleDebounce();
    await user.keyboard('{Enter}');

    await waitFor(() => {
      expect(store.getState().startup.status).toBe('error');
    });
    expect(
      screen.getByText('No airport found for "ZZZZ". Check the ICAO code and try again.'),
    ).toBeInTheDocument();

    await user.type(input, 'X');
    expect(store.getState().startup.status).not.toBe('error');
    expect(store.getState().startup.errorMessage).toBeNull();
  });

  it('retries the same ICAO on a second Enter after a 404 — the whole reason resolution uses the lazy hook', async () => {
    const { requested } = stubFetch({ airportStatus: 404 });
    const user = userEvent.setup();
    const { store } = renderGate();

    const input = await screen.findByRole('combobox');
    await user.type(input, 'ZZZZ');
    await settleDebounce();
    await user.keyboard('{Enter}');
    await waitFor(() => {
      expect(store.getState().startup.status).toBe('error');
    });

    await user.keyboard('{Enter}');
    await waitFor(() => {
      const attempts = requested.filter((url) => url === '/api/navdata/airports/ZZZZ');
      expect(attempts).toHaveLength(2);
    });
  });

  it('a 503 (navdata not ready) does not reach error, and re-fetches the navdata status', async () => {
    const { requested } = stubFetch({
      airportStatus: 503,
      airportBody: { detail: 'Navdata is building.', status: NAVDATA_BUILDING },
    });
    const user = userEvent.setup();
    const { store } = renderGate();

    const input = await screen.findByRole('combobox');
    await user.type(input, 'LEMD');
    await settleDebounce();
    await user.keyboard('{Enter}');

    await waitFor(() => {
      expect(store.getState().startup.status).not.toBe('resolving');
    });
    expect(store.getState().startup.status).not.toBe('error');
    // `invalidateTags(['NavdataStatus'])` is only meaningful if it actually triggers a
    // refetch — one status read at mount, at least one more once the 503 invalidates it.
    await waitFor(() => {
      const statusReads = requested.filter((url) => url === '/api/navdata/status');
      expect(statusReads.length).toBeGreaterThanOrEqual(2);
    });
  });
});

describe('AirportGate — remembered airport', () => {
  // The preloaded `startup` state below is exactly what `initStartupSync` would have
  // dispatched from a remembered `localStorage` record before this component ever mounts
  // (`main.tsx` calls it before `createRoot().render(...)`) — `startupSync.test.ts` is what
  // actually exercises that read/write path; this file is about what the gate renders once
  // that state exists, not about `localStorage` itself.
  const REMEMBERED_STARTUP_STATE = {
    status: 'searching' as const,
    query: 'LEMD',
    icao: null,
    name: 'Adolfo Suárez Madrid–Barajas',
    errorMessage: null,
  };

  it('pre-fills the input and shows "Continue with…" without auto-resolving', async () => {
    const { requested } = stubFetch();
    renderGate({ startup: REMEMBERED_STARTUP_STATE });

    expect(await screen.findByRole('combobox')).toHaveValue('LEMD');
    expect(
      screen.getByRole('button', { name: /continue with adolfo suárez madrid–barajas/i }),
    ).toBeInTheDocument();
    expect(requested.some((url) => url.startsWith('/api/navdata/airports/LEMD'))).toBe(false);
  });

  it('resolves and closes the gate when the remembered button is pressed', async () => {
    stubFetch();
    const user = userEvent.setup();
    const { store } = renderGate({ startup: REMEMBERED_STARTUP_STATE });

    await user.click(await screen.findByRole('button', { name: /continue with/i }));

    await waitFor(() => {
      expect(store.getState().startup.status).toBe('ready');
    });
    expect(store.getState().startup.icao).toBe('LEMD');
  });
});

describe('AirportGate — keyboard', () => {
  it('Escape collapses the listbox without changing status or closing the gate', async () => {
    stubFetch();
    const user = userEvent.setup();
    const { store } = renderGate();

    const input = await screen.findByRole('combobox');
    await user.type(input, 'LEM');
    await settleDebounce();
    await waitFor(() => {
      expect(screen.getByRole('listbox')).toBeInTheDocument();
    });

    await user.keyboard('{Escape}');

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(store.getState().startup.status).toBe('searching');
    expect(screen.getByRole('dialog', { name: 'Choose an airport' })).toBeInTheDocument();
  });

  it('ArrowDown moves aria-activedescendant across the options', async () => {
    stubFetch({
      search: [LEMD_SUMMARY, { ...LEMD_SUMMARY, icao: 'LEBL', name: 'Barcelona–El Prat' }],
    });
    const user = userEvent.setup();
    renderGate();

    const input = await screen.findByRole('combobox');
    await user.type(input, 'LE');
    await settleDebounce();
    await waitFor(() => {
      expect(screen.getByRole('listbox')).toBeInTheDocument();
    });

    expect(input).not.toHaveAttribute('aria-activedescendant');
    await user.keyboard('{ArrowDown}');
    expect(input).toHaveAttribute('aria-activedescendant', 'startup-gate-option-LEMD');
    await user.keyboard('{ArrowDown}');
    expect(input).toHaveAttribute('aria-activedescendant', 'startup-gate-option-LEBL');
  });

  it('Escape clears the highlight too — a following Enter resolves the typed text, not the dismissed suggestion', async () => {
    const { requested } = stubFetch({
      search: [LEMD_SUMMARY, { ...LEMD_SUMMARY, icao: 'LEBL', name: 'Barcelona–El Prat' }],
    });
    const user = userEvent.setup();
    const { store } = renderGate();

    const input = await screen.findByRole('combobox');
    await user.type(input, 'LE');
    await settleDebounce();
    await waitFor(() => {
      expect(screen.getByRole('listbox')).toBeInTheDocument();
    });

    // Highlight LEBL (second option), then dismiss the list — the instructor's intent is to
    // keep typing "LE", not to pick LEBL.
    await user.keyboard('{ArrowDown}{ArrowDown}');
    expect(input).toHaveAttribute('aria-activedescendant', 'startup-gate-option-LEBL');

    await user.keyboard('{Escape}');
    expect(input).not.toHaveAttribute('aria-activedescendant');
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();

    await user.keyboard('{Enter}');

    // Resolves the typed "LE", never the dismissed LEBL highlight.
    await waitFor(() => {
      expect(store.getState().startup.icao).toBe('LE');
    });
    expect(requested).not.toContain('/api/navdata/airports/LEBL');
  });
});

describe('AirportGate — navdata not indexed', () => {
  it('replaces the combobox with the navdata block while the index is building', async () => {
    stubFetch({ navdata: NAVDATA_BUILDING });
    renderGate();

    expect(await screen.findByText('Reading apt.dat…')).toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });
});
