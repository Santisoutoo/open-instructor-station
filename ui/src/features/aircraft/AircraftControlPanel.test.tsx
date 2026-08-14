import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AircraftControlPanel } from './AircraftControlPanel';
import type {
  AircraftControlManifest,
  AircraftControlSupport,
  AircraftState,
  ControlId,
} from '../../api/models';
import { setupStore, type RootState } from '../../store';

const CRUISE: AircraftState = {
  latitude: 40.49,
  longitude: -3.56,
  altitude_ft: 3000,
  heading_deg: 90,
  ias_kt: 250,
  vertical_speed_fpm: 0,
  pitch_deg: 0,
  roll_deg: 0,
  on_ground: false,
};

/** Mirrors what the real server returns for `FakeSimAdapter`. */
function entry(
  control: ControlId,
  setupField: string,
  supported: boolean,
  reason?: string,
): AircraftControlSupport {
  const base: AircraftControlSupport = {
    control,
    setup_field: setupField,
    capability:
      control.startsWith('autopilot') || control.startsWith('target')
        ? 'can_control_autopilot'
        : 'can_set_aircraft_state',
    supported,
  };
  return reason === undefined ? base : { ...base, reason };
}

/**
 * What the real server returns for `FakeSimAdapter`: every control writable, the
 * autopilot block included since issue #41 put its fields on `AircraftSetup`.
 */
const FAKE_MANIFEST: AircraftControlManifest = {
  adapter: 'fake',
  controls: [
    entry('flaps', 'flaps_ratio', true),
    entry('speedbrake', 'speedbrake_ratio', true),
    entry('gear', 'gear_down', true),
    entry('autobrake', 'autobrake_level', true),
    entry('trim', 'elevator_trim_ratio', true),
    entry('throttle', 'throttle_ratio', true),
    entry('lights', 'lights', true),
    entry('altitude', 'altitude_ft', true),
    entry('speed', 'ias_kt', true),
    entry('vertical_speed', 'vertical_speed_fpm', true),
    entry('heading', 'heading_deg', true),
    entry('autopilot_master', 'autopilot_master', true),
    entry('autopilot_nav', 'autopilot_nav', true),
    entry('autopilot_app', 'autopilot_app', true),
    entry('autopilot_hdg', 'autopilot_hdg', true),
    entry('flight_director', 'flight_director', true),
    entry('target_altitude', 'target_altitude_ft', true),
    entry('target_speed', 'target_ias_kt', true),
    entry('target_heading', 'target_heading_deg', true),
    entry('target_vertical_speed', 'target_vertical_speed_fpm', true),
  ],
};

/**
 * An adapter that cannot drive an autopilot: the manifest still lists the block,
 * disabled with the capability as the stated reason. This is hard rule 3 in its
 * primary form — the reason an instructor sees is "this simulator cannot", not
 * "this panel has not been finished".
 */
const NO_AUTOPILOT_MANIFEST: AircraftControlManifest = {
  adapter: 'stub',
  controls: FAKE_MANIFEST.controls.map((control) =>
    control.capability === 'can_control_autopilot'
      ? entry(
          control.control,
          control.setup_field,
          false,
          "The 'stub' adapter does not declare can_control_autopilot.",
        )
      : control,
  ),
};

/** Every POST body the panel sent, in order. */
let posted: unknown[] = [];

interface StubOptions {
  manifest?: AircraftControlManifest | null;
  setupStatus?: number;
  setupBody?: unknown;
}

/**
 * `fetchBaseQuery` hands `fetch` a fully-built `Request`, never a (url, init) pair, so the
 * stub has to read the body off the request rather than off an `init` argument.
 */
function stubFetch({
  manifest = FAKE_MANIFEST,
  setupStatus = 200,
  setupBody,
}: StubOptions = {}) {
  const fetchStub = vi.fn(async (input: RequestInfo | URL) => {
    const request = input instanceof Request ? input : new Request(input);

    if (request.url.includes('/api/aircraft/controls')) {
      return manifest === null
        ? new Response('boom', { status: 503 })
        : Response.json(manifest);
    }
    if (request.url.includes('/api/aircraft/setup')) {
      posted.push(await request.clone().json());
      return Response.json(setupBody ?? { applied: {}, state: CRUISE }, {
        status: setupStatus,
      });
    }
    return new Response('not found', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchStub);
  return fetchStub;
}

function renderPanel(preloadedState?: Partial<RootState>) {
  const store = setupStore(preloadedState);
  return {
    store,
    ...render(
      <Provider store={store}>
        <AircraftControlPanel />
      </Provider>,
    ),
  };
}

/** One of the panel's headed groups — "NAV" the AP mode and "Nav" the light differ by it. */
function group(title: string): HTMLElement {
  return screen.getByRole('region', { name: title });
}

/** The row that owns a widget — where its "why is this disabled" text lives. */
function rowOf(element: HTMLElement): HTMLElement {
  const row = element.closest('.control');
  if (!(row instanceof HTMLElement)) {
    throw new Error(`No .control wrapper for ${element.tagName}`);
  }
  return row;
}

describe('<AircraftControlPanel />', () => {
  beforeEach(() => {
    posted = [];
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('renders every control from the feature spec', async () => {
    stubFetch();
    renderPanel();
    await screen.findByRole('slider', { name: /flaps/i });

    const configuration = group('Configuration');
    for (const label of [
      /flaps/i,
      /speedbrake/i,
      /elevator trim/i,
      /landing gear/i,
      /autobrake/i,
    ]) {
      expect(within(configuration).getByLabelText(label)).toBeInTheDocument();
    }

    const flightState = group('Flight state');
    for (const label of [/altitude/i, /airspeed/i, /vertical speed/i, /heading/i]) {
      expect(within(flightState).getByLabelText(label)).toBeInTheDocument();
    }

    const autopilot = group('Autopilot');
    for (const label of [
      /^autopilot$/i,
      /^nav$/i,
      /^app$/i,
      /^hdg$/i,
      /flight director/i,
      /ap altitude/i,
      /ap speed/i,
      /ap heading/i,
      /ap vertical speed/i,
    ]) {
      expect(within(autopilot).getByLabelText(label)).toBeInTheDocument();
    }

    const lights = screen.getByRole('group', { name: /exterior lights/i });
    for (const label of [/landing/i, /taxi/i, /nav/i, /beacon/i, /strobe/i]) {
      expect(within(lights).getByRole('button', { name: label })).toBeInTheDocument();
    }
  });

  it('disables every control until the manifest has been read — fails closed', () => {
    stubFetch();
    renderPanel();

    // First paint: the query has not resolved yet.
    expect(screen.getByRole('slider', { name: /flaps/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /landing gear/i })).toBeDisabled();
    expect(
      screen.getAllByText(/waiting for the control manifest/i).length,
    ).toBeGreaterThan(0);
  });

  it('keeps every control disabled when the manifest cannot be read', async () => {
    stubFetch({ manifest: null });
    renderPanel();

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /every control stays disabled/i,
    );
    expect(screen.getByRole('slider', { name: /flaps/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /landing gear/i })).toBeDisabled();
  });

  it('enables every control the server backs, autopilot and trim included', async () => {
    stubFetch();
    renderPanel();

    await waitFor(() => {
      expect(screen.getByRole('slider', { name: /flaps/i })).toBeEnabled();
    });
    expect(screen.getByRole('button', { name: /landing gear/i })).toBeEnabled();
    expect(screen.getByRole('slider', { name: /elevator trim/i })).toBeEnabled();

    const autopilot = group('Autopilot');
    expect(within(autopilot).getByRole('button', { name: /^nav$/i })).toBeEnabled();
    expect(within(autopilot).getByLabelText(/ap heading/i)).toBeEnabled();
  });

  it('disables the autopilot block with the capability as the reason on an adapter without one', async () => {
    stubFetch({ manifest: NO_AUTOPILOT_MANIFEST });
    renderPanel();

    // Everything outside the autopilot still works: an unsupported capability
    // disables its own controls and nothing else.
    await waitFor(() => {
      expect(screen.getByRole('slider', { name: /flaps/i })).toBeEnabled();
    });
    expect(screen.getByRole('slider', { name: /elevator trim/i })).toBeEnabled();

    const nav = within(group('Autopilot')).getByRole('button', { name: /^nav$/i });
    expect(nav).toBeDisabled();
    expect(rowOf(nav)).toHaveTextContent(/does not declare can_control_autopilot/);
  });

  it('arms an autopilot mode through the same idempotent setup write', async () => {
    stubFetch({ setupBody: { applied: { autopilot_hdg: true }, state: CRUISE } });
    const user = userEvent.setup();
    const { store } = renderPanel();

    const hdg = within(group('Autopilot')).getByRole('button', { name: /^hdg$/i });
    await waitFor(() => {
      expect(hdg).toBeEnabled();
    });
    await user.click(hdg);

    await waitFor(() => {
      expect(posted).toEqual([{ autopilot_hdg: true }]);
    });
    await waitFor(() => {
      expect(store.getState().aircraft.commanded['autopilot_hdg']).toBe(true);
    });
  });

  it('commits an autopilot selector to its own field', async () => {
    stubFetch();
    const user = userEvent.setup();
    renderPanel();

    const field = screen.getByLabelText(/^ap altitude \(ft\)/i);
    await waitFor(() => {
      expect(field).toBeEnabled();
    });
    await user.type(field, '12000');
    await user.click(within(rowOf(field)).getByRole('button', { name: /^set$/i }));

    await waitFor(() => {
      expect(posted).toEqual([{ target_altitude_ft: 12000 }]);
    });
  });

  it('posts the gear command and confirms it optimistically', async () => {
    stubFetch({ setupBody: { applied: { gear_down: true }, state: CRUISE } });
    const user = userEvent.setup();
    const { store } = renderPanel();

    const gear = await screen.findByRole('button', { name: /landing gear/i });
    await waitFor(() => {
      expect(gear).toBeEnabled();
    });
    await user.click(gear);

    await waitFor(() => {
      expect(posted).toEqual([{ gear_down: true }]);
    });
    await waitFor(() => {
      expect(store.getState().aircraft.commanded['gear']).toBe(true);
    });
    expect(gear).toHaveTextContent('Down');
    expect(store.getState().aircraft.pending['gear']).toBeUndefined();
  });

  it('writes one light switch without touching the other four', async () => {
    stubFetch();
    const user = userEvent.setup();
    renderPanel();

    const lights = screen.getByRole('group', { name: /exterior lights/i });
    const beacon = within(lights).getByRole('button', { name: /beacon/i });
    await waitFor(() => {
      expect(beacon).toBeEnabled();
    });
    await user.click(beacon);

    await waitFor(() => {
      expect(posted).toEqual([{ lights: { beacon: true } }]);
    });
  });

  it('commits a stepper only when "Set" is pressed', async () => {
    stubFetch();
    const user = userEvent.setup();
    renderPanel({ telemetry: { latest: CRUISE, receivedAt: 1, frameCount: 1 } });

    const field = screen.getByLabelText(/^altitude \(ft\)/i);
    await waitFor(() => {
      expect(field).toBeEnabled();
    });

    // The live value is a readout, never the field's content: a field seeded from a 4 Hz
    // feed would overwrite whatever the instructor was halfway through typing.
    const row = rowOf(field);
    expect(within(row).getByText('3,000')).toBeInTheDocument();
    expect(field).toHaveValue(null);

    await user.type(field, '5500');
    expect(posted).toEqual([]);

    await user.click(within(row).getByRole('button', { name: /^set$/i }));

    await waitFor(() => {
      expect(posted).toEqual([{ altitude_ft: 5500 }]);
    });
    // The field hands the display back to the readout once the intent has been sent.
    expect(field).toHaveValue(null);
  });

  it("shows the server's reason when a write is refused, and drops the optimistic value", async () => {
    stubFetch({
      setupStatus: 501,
      setupBody: {
        detail:
          "gear_down: the 'xplane' adapter does not declare can_set_aircraft_state.",
      },
    });
    const user = userEvent.setup();
    const { store } = renderPanel();

    const gear = await screen.findByRole('button', { name: /landing gear/i });
    await waitFor(() => {
      expect(gear).toBeEnabled();
    });
    await user.click(gear);

    expect(
      await screen.findByText(/does not declare can_set_aircraft_state/i),
    ).toBeInTheDocument();
    expect(store.getState().aircraft.commanded['gear']).toBeUndefined();
    expect(store.getState().aircraft.pending['gear']).toBeUndefined();
    expect(gear).toHaveTextContent('Unknown');
  });
});
