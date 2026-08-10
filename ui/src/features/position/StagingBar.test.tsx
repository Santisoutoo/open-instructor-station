/**
 * The staging bar, against a stubbed API.
 *
 * The guarantee under test is the one the whole panel is built around: **staging a
 * placement must not move the aircraft.** Everything else here — the provenance notes, the
 * inline error, the disabled commit — exists so that an instructor can tell what is about
 * to happen before it does.
 *
 * `fetch` is stubbed rather than the RTK Query hooks mocked, so the request bodies the
 * panel actually sends are observable and can be asserted.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Capabilities, PlacementPreview, PlacementRequest } from '../../api/models';
import { type RootState, setupStore } from '../../store';
import { StagingBar } from './StagingBar';

const FINAL: PlacementRequest = {
  type: 'runway',
  airport_icao: 'ZZZZ',
  runway_ident: '36',
  placement: 'final_10nm',
};

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

const PREVIEW: PlacementPreview = {
  request: FINAL,
  placement: {
    position: { latitude: 39.83, longitude: -3.0, altitude_ft: 4184.4 },
    heading_deg: 0,
    ias_kt: 120,
    label: 'ZZZZ 36 10 NM final',
  },
  setup: { altitude_ft: 4184.4, heading_deg: 0, ias_kt: 120 },
  schematic: {
    runway_ident: '36',
    runway_true_bearing_deg: 0,
    runway_length_m: 3000,
    glidepath_deg: 3,
    points: [
      {
        label: '36',
        position: { latitude: 40, longitude: -3, altitude_ft: 1000 },
        x_nm: 0,
        y_nm: 0,
        role: 'threshold',
      },
      {
        label: '18',
        position: { latitude: 40.03, longitude: -3, altitude_ft: 1000 },
        x_nm: 1.62,
        y_nm: 0,
        role: 'runway_end',
      },
      {
        label: 'ZZZZ 36 10 NM final',
        position: { latitude: 39.83, longitude: -3, altitude_ft: 4184.4 },
        x_nm: -10,
        y_nm: 0,
        role: 'placement',
      },
    ],
  },
  notes: [
    '4,184 ft — 3° glidepath 10 NM from the 36 threshold at 1,000 ft.',
    '120 kt — ICAO category B threshold speed (V_AT). This is a category default, not this airframe’s number; set a speed if you know it.',
  ],
};

/** Every call made through `fetch`, so the test can assert what was sent. */
let calls: { url: string; method: string; body: unknown }[] = [];

function json(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function stubApi(options: { capabilities?: Capabilities; applyStatus?: number } = {}) {
  calls = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      // RTK Query's fetchBaseQuery calls fetch with a Request object, not a URL plus
      // init — stringifying that gives "[object Request]" and matches nothing.
      const request = input instanceof Request ? input : null;
      const url = request?.url ?? String(input);
      const method = request?.method ?? init?.method ?? 'GET';
      const rawBody = request === null ? init?.body : await request.clone().text();
      const body =
        typeof rawBody === 'string' && rawBody !== ''
          ? (JSON.parse(rawBody) as unknown)
          : undefined;
      calls.push({ url, method, body });

      if (url.includes('/capabilities')) {
        return json(options.capabilities ?? CAPABLE);
      }
      if (url.includes('/position/preview')) {
        return json(PREVIEW);
      }
      if (url.includes('/position/apply')) {
        const status = options.applyStatus ?? 200;
        if (status !== 200) {
          return json(
            { detail: 'The fake adapter does not declare can_set_position.' },
            status,
          );
        }
        return json({
          placement: PREVIEW.placement,
          applied: PREVIEW.setup,
          state: {
            latitude: 39.83,
            longitude: -3,
            altitude_ft: 4184.4,
            heading_deg: 0,
            ias_kt: 120,
            vertical_speed_fpm: -650,
            pitch_deg: 0,
            roll_deg: 0,
            on_ground: false,
          },
        });
      }
      return json({});
    }),
  );
}

function renderBar(preloaded: Partial<RootState> = {}) {
  const store = setupStore(preloaded);
  return render(
    <Provider store={store}>
      <StagingBar />
    </Provider>,
  );
}

function stagedState(overrides = {}): Partial<RootState> {
  return {
    position: {
      selectedIcao: 'ZZZZ',
      selectedRunwayIdent: '36',
      activeTab: 'pattern',
      openProcedure: null,
      staged: FINAL,
      setupOverrides: {},
      recentIcaos: ['ZZZZ'],
      ...overrides,
    },
  };
}

beforeEach(() => {
  stubApi();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('<StagingBar />', () => {
  it('says nothing is going to happen when nothing is staged', () => {
    renderBar();

    expect(screen.getByText(/nothing moves until you press/i)).toBeInTheDocument();
  });

  it('previews a staged placement without applying it', async () => {
    renderBar(stagedState());

    await screen.findByText('ZZZZ 36 10 NM final');

    // The whole design in one assertion: a preview was requested, nothing was applied.
    expect(calls.some((call) => call.url.includes('/position/preview'))).toBe(true);
    expect(calls.some((call) => call.url.includes('/position/apply'))).toBe(false);
  });

  it('pre-fills the numbers the server computed', async () => {
    renderBar(stagedState());

    await screen.findByText('ZZZZ 36 10 NM final');

    expect(screen.getByLabelText(/altitude/i)).toHaveValue(4184);
    expect(screen.getByLabelText(/airspeed/i)).toHaveValue(120);
  });

  it('shows where each number came from', async () => {
    renderBar(stagedState());

    // A charted altitude and a category guess look identical without this.
    expect(await screen.findByText(/3° glidepath 10 NM/)).toBeInTheDocument();
    expect(screen.getByText(/category default/)).toBeInTheDocument();
  });

  it('applies only when the instructor presses the button', async () => {
    const user = userEvent.setup();
    renderBar(stagedState());
    await screen.findByText('ZZZZ 36 10 NM final');

    await user.click(screen.getByRole('button', { name: /place aircraft/i }));

    await waitFor(() => {
      expect(calls.some((call) => call.url.includes('/position/apply'))).toBe(true);
    });
  });

  it('sends the instructor edits as a sparse overlay, not a whole setup', async () => {
    const user = userEvent.setup();
    renderBar(stagedState({ setupOverrides: { ias_kt: 95 } }));
    await screen.findByText('ZZZZ 36 10 NM final');

    await user.click(screen.getByRole('button', { name: /place aircraft/i }));

    await waitFor(() => {
      const apply = calls.find((call) => call.url.includes('/position/apply'));
      // Only the edited field: the server merges it over the geometry's own setup, so
      // sending a full copy is how a stale client drops the computed altitude.
      expect(apply?.body).toEqual({ placement: FINAL, setup: { ias_kt: 95 } });
    });
  });

  it('confirms what actually happened rather than what was asked for', async () => {
    const user = userEvent.setup();
    renderBar(stagedState());
    await screen.findByText('ZZZZ 36 10 NM final');

    await user.click(screen.getByRole('button', { name: /place aircraft/i }));

    expect(await screen.findByText(/placed at 4,184 ft, 120 kt/i)).toBeInTheDocument();
  });

  it('renders a failure inline instead of in a modal', async () => {
    const user = userEvent.setup();
    stubApi({ applyStatus: 501 });
    renderBar(stagedState());
    await screen.findByText('ZZZZ 36 10 NM final');

    await user.click(screen.getByRole('button', { name: /place aircraft/i }));

    expect(
      await screen.findByText(/does not declare can_set_position/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('disables the commit when the adapter cannot reposition, and says why', async () => {
    stubApi({ capabilities: { ...CAPABLE, can_set_position: false } });
    renderBar(stagedState());
    await screen.findByText('ZZZZ 36 10 NM final');

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /place aircraft/i })).toBeDisabled();
    });
    expect(screen.getByText(/can_set_position/)).toBeInTheDocument();
    // Staging still works: a preview is navdata and arithmetic, not a simulator call.
    expect(screen.getByText('ZZZZ 36 10 NM final')).toBeInTheDocument();
  });
});
