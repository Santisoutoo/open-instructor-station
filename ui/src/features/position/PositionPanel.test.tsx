/**
 * The Position panel as a whole.
 *
 * Two things only this level can check.
 *
 * **The navdata gate fails closed.** There is no point offering an airport search over an
 * index that does not exist, so until the status says `ready` the panel body is replaced by
 * a status card — and "the status could not be read" has to count as not ready, or a server
 * that is merely slow reads as a working index and the instructor searches an empty void.
 * `gate.test.ts` proves the decision; this proves the panel obeys it.
 *
 * **Issue #39 end to end.** The panel's own answer to "will this aeroplane arrive below
 * stall speed" is the server's note, rendered in the staging bar. The last test walks the
 * whole path — coordinate tab, an airborne point, no speed — and asserts the warning
 * actually reaches the screen rather than being computed and dropped.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Capabilities, NavdataStatus, PlacementPreview } from '../../api/models';
import { type AppStore, type RootState, setupStore } from '../../store';
import { PositionPanel } from './PositionPanel';
import { type ApiCall, type Answer, callsTo, positionState, stubApi } from './testApi';

const CAPABLE: Capabilities = {
  can_set_position: true,
  can_set_aircraft_state: true,
  can_set_weather: false,
  can_inject_failures: false,
  can_spawn_traffic: false,
  can_control_autopilot: false,
  can_set_fuel_payload: false,
  can_control_camera: false,
  can_pushback: false,
};

function status(overrides: Partial<NavdataStatus> = {}): NavdataStatus {
  return { state: 'ready', provider: 'in_memory', ...overrides };
}

/**
 * A bare coordinate 4,000 ft up with no speed — the shape of issue #39.
 *
 * The note is the server's own wording. The warning is keyed on the *resolved* speed, so it
 * fires whether the caller asked for 0 kt or said nothing at all.
 */
const STALLED_PREVIEW: PlacementPreview = {
  request: {
    type: 'coordinate',
    position: { latitude: 40.4936, longitude: -3.5668, altitude_ft: 4000 },
    heading_deg: 0,
    ias_kt: 0,
  },
  placement: {
    position: { latitude: 40.4936, longitude: -3.5668, altitude_ft: 4000 },
    heading_deg: 0,
    ias_kt: 0,
    label: '40.4936, -3.5668 at 4,000 ft',
  },
  setup: { altitude_ft: 4000, heading_deg: 0, ias_kt: 0 },
  schematic: { points: [] },
  notes: [
    '0 kt was requested at a non-zero altitude — the aircraft will be below stall speed. ' +
      'Set a speed unless this point is on the ground.',
  ],
};

/** Routes for a panel whose index is ready and whose adapter can reposition. */
function readyRoutes(extra: Record<string, Answer> = {}): Record<string, Answer> {
  return {
    'navdata/status': { body: status({ airac_cycle: '2607' }) },
    'navdata/index': { body: status({ state: 'building' }) },
    ...extra,
    '/runways': { body: [] },
    '/parking': { body: [] },
    '/procedures': { body: [] },
    capabilities: { body: CAPABLE },
    'position/preview': { body: STALLED_PREVIEW },
  };
}

function renderPanel(
  routes: Record<string, Answer>,
  preloaded: Partial<RootState> = positionState(),
): { store: AppStore; calls: ApiCall[] } {
  const { calls } = stubApi(routes);
  const store = setupStore(preloaded);
  render(
    <Provider store={store}>
      <PositionPanel />
    </Provider>,
  );
  return { store, calls };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('the navdata gate', () => {
  it('offers nothing at all until the index status has been read', () => {
    renderPanel(readyRoutes());

    // First paint, before the query resolves. Failing open here would mean an airport
    // search against an index that may not exist.
    expect(screen.getByText(/reading the navigation data status/i)).toBeInTheDocument();
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('tablist')).not.toBeInTheDocument();
  });

  it('stays closed, without a build button, when the status itself cannot be read', async () => {
    renderPanel({ 'navdata/status': { status: 500, detail: 'boom' } });

    expect(
      await screen.findByText(/navigation data status could not be read/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /build index/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
  });

  it('offers to build an index that has never been built', async () => {
    const user = userEvent.setup();
    const { calls } = renderPanel(
      readyRoutes({
        'navdata/status': {
          body: status({ state: 'unavailable', reason: 'No index has been built yet.' }),
        },
      }),
    );

    expect(await screen.findByText(/No index has been built yet/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /build index/i }));

    await waitFor(() => {
      expect(callsTo(calls, 'navdata/index')).toHaveLength(1);
    });
    expect(callsTo(calls, 'navdata/index')[0]?.method).toBe('POST');
  });

  it('does not offer to re-run a build that failed', async () => {
    // It would fail the same way until the underlying problem is fixed.
    renderPanel({
      'navdata/status': {
        body: status({ state: 'error', reason: 'apt.dat is unreadable.' }),
      },
    });

    expect(await screen.findByText('apt.dat is unreadable.')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /build index/i }),
    ).not.toBeInTheDocument();
  });

  it('shows build progress as a real progress bar', async () => {
    renderPanel({
      'navdata/status': {
        body: status({
          state: 'building',
          progress: {
            stage: 'airports',
            stage_index: 1,
            stage_count: 6,
            fraction: 0.25,
            detail: 'apt.dat — 3.1 M / 12.4 M lines',
          },
        }),
      },
    });

    const bar = await screen.findByRole('progressbar');
    expect(bar).toHaveAttribute('aria-valuenow', '25');
    expect(screen.getByText('apt.dat — 3.1 M / 12.4 M lines')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /build index/i }),
    ).not.toBeInTheDocument();
  });

  it('opens the panel and badges the cycle once the index is ready', async () => {
    renderPanel(readyRoutes());

    expect(await screen.findByRole('searchbox')).toBeInTheDocument();
    expect(screen.getByText('AIRAC 2607')).toBeInTheDocument();
    expect(screen.getByText(/Search for an airport to begin/i)).toBeInTheDocument();
  });
});

describe('the panel body', () => {
  it('shows the placement tabs only once an airport is chosen', async () => {
    renderPanel(readyRoutes(), positionState({ selectedIcao: 'ZZZZ' }));

    const tabs = await screen.findByRole('tablist', { name: /placement type/i });
    for (const label of [
      'Pattern & final',
      'Procedures',
      'Gates & stands',
      'Coordinate & fix',
    ]) {
      expect(within(tabs).getByRole('tab', { name: label })).toBeInTheDocument();
    }
  });

  it('asks for a runway end before offering a final or a circuit leg', async () => {
    // "10 NM final" means nothing until it is known which way the aeroplane is pointing.
    renderPanel(readyRoutes(), positionState({ selectedIcao: 'ZZZZ' }));

    expect(await screen.findByText(/Pick a runway end above/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '10 NM' })).not.toBeInTheDocument();
  });

  it('shows the pattern grid once an end is chosen', async () => {
    renderPanel(
      readyRoutes(),
      positionState({ selectedIcao: 'ZZZZ', selectedRunwayIdent: '32L' }),
    );

    expect(await screen.findByRole('button', { name: '10 NM' })).toBeInTheDocument();
  });

  it('switches tabs and marks the selected one', async () => {
    const user = userEvent.setup();
    const { store } = renderPanel(readyRoutes(), positionState({ selectedIcao: 'ZZZZ' }));

    await user.click(await screen.findByRole('tab', { name: /gates & stands/i }));

    expect(store.getState().position.activeTab).toBe('parking');
    expect(screen.getByRole('tab', { name: /gates & stands/i })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(screen.getByRole('tab', { name: /pattern & final/i })).toHaveAttribute(
      'aria-selected',
      'false',
    );
  });

  it('always shows the staging bar, saying that nothing has moved', async () => {
    renderPanel(readyRoutes());

    expect(
      await screen.findByText(/Nothing moves until you press Place aircraft/i),
    ).toBeInTheDocument();
  });
});

describe('an airborne placement with no speed (issue #39)', () => {
  it("puts the server's stall-speed warning in front of the instructor", async () => {
    // The whole path: coordinate tab, 4,000 ft, speed left blank. The geometry is perfect
    // and the aeroplane still ends up in the terrain, so the warning is the only thing
    // standing between the instructor and a wrecked lesson.
    const user = userEvent.setup();
    const { calls } = renderPanel(
      readyRoutes(),
      positionState({ selectedIcao: 'ZZZZ', activeTab: 'coordinate' }),
    );

    const submit = await screen.findByRole('button', { name: /stage coordinate/i });
    // Scoped to the form, because the waypoint form beside it labels a field identically.
    const coordinate = within(submit.closest('form') as HTMLElement);
    await user.type(coordinate.getByLabelText(/latitude/i), '40.4936');
    await user.type(coordinate.getByLabelText(/longitude/i), '-3.5668');
    await user.type(coordinate.getByLabelText(/altitude/i), '4000');
    await user.click(submit);

    expect(await screen.findByText(/below stall speed/i)).toBeInTheDocument();
    // Still nothing has moved: the warning arrives from `preview`, not from `apply`.
    expect(callsTo(calls, 'position/apply')).toEqual([]);
    expect(callsTo(calls, 'position/preview')).toHaveLength(1);
  });
});

describe('polling', () => {
  it('re-reads the status while an index build is running', async () => {
    const { calls } = renderPanel({
      'navdata/status': { body: status({ state: 'building' }) },
    });
    await screen.findByText(/Building the navigation index/i);

    await new Promise((resolve) => setTimeout(resolve, 1400));

    expect(callsTo(calls, 'navdata/status').length).toBeGreaterThan(1);
  });

  it('stops re-reading it once the index is ready', async () => {
    // `BUILD_POLL_MS` is documented as "how often to re-read the status while an index
    // build is running". A panel left open on a ready index must not sit there asking a
    // simulator-facing server the same question once a second for the rest of the lesson.
    const { calls } = renderPanel(readyRoutes());
    await screen.findByRole('searchbox');
    const settled = callsTo(calls, 'navdata/status').length;

    await new Promise((resolve) => setTimeout(resolve, 1400));

    expect(callsTo(calls, 'navdata/status')).toHaveLength(settled);
  });
});
