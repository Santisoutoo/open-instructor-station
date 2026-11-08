/**
 * The Weather panel end to end against a stubbed API.
 *
 * `fetch` is stubbed rather than the RTK Query hooks mocked — the same choice
 * `features/position/StagingBar.test.tsx` makes, for the same reason: the request the panel
 * actually sends is what is worth asserting, and mocking the hooks would hide a panel that
 * asks the wrong endpoint.
 *
 * Two behaviours matter most here, both direct consequences of the real backend
 * (weather-manager.md D2, D7): applying CAVOK must NOT change the wind — the preset never
 * states one — and every number the staging bar shows must come from the server's own
 * `preview`/`apply` response, never from a client-side re-implementation of the resolver.
 */

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type {
  Capabilities,
  WeatherApplyResult,
  WeatherManifest,
  WeatherPreview,
  WeatherRequest,
  WeatherState,
} from '../../api/models';
import { type RootState, setupStore } from '../../store';
import { WeatherPanel } from './WeatherPanel';

/** A Position panel state with LEMD 32L picked, for the runway-relative preset. */
const POSITION_WITH_RUNWAY = {
  selectedIcao: 'LEMD',
  selectedRunwayIdent: '32L',
  activeTab: 'pattern' as const,
  openProcedure: null,
  staged: null,
  setupOverrides: {},
  recentIcaos: ['LEMD'],
};

const CAPABLE: Capabilities = {
  can_set_position: true,
  can_set_aircraft_state: true,
  can_set_weather: true,
  can_inject_failures: false,
  can_spawn_traffic: false,
  can_control_autopilot: false,
  can_set_fuel_payload: false,
  can_control_camera: false,
  can_pushback: false,
  can_control_cockpit: false,
};

const CURRENT: WeatherState = {
  wind_layers: [
    {
      altitude_ft: 0,
      direction_deg: 270,
      speed_kt: 5,
      gust_increase_kt: 0,
      turbulence_ratio: 0,
    },
  ],
  cloud_layers: [],
  visibility_m: 10000,
  qnh_hpa: 1016,
  temperature_c: 19,
  dewpoint_c: 7,
  precipitation_ratio: 0,
  runway_contamination: 'dry',
};

const MANIFEST: WeatherManifest = {
  adapter: 'fake',
  supported: true,
  reason: null,
  presets: [
    {
      id: 'cavok',
      label: 'CAVOK',
      description: 'Clear skies',
      requires_runway: false,
      requires_airport: false,
    },
    {
      id: 'cat_i',
      label: 'CAT I',
      description: '',
      requires_runway: false,
      requires_airport: true,
    },
    {
      id: 'cat_ii',
      label: 'CAT II',
      description: '',
      requires_runway: false,
      requires_airport: true,
    },
    {
      id: 'cat_iii',
      label: 'CAT III',
      description: '',
      requires_runway: false,
      requires_airport: true,
    },
    {
      id: 'storm',
      label: 'Storm',
      description: '',
      requires_runway: false,
      requires_airport: true,
    },
    {
      id: 'crosswind',
      label: 'Crosswind',
      description: '90° off the runway',
      requires_runway: true,
      requires_airport: true,
    },
    {
      id: 'mountain_wave',
      label: 'Mountain Wave',
      description: '',
      requires_runway: false,
      requires_airport: true,
    },
  ],
};

/** CAVOK never states wind (core/weather/presets.py) — resolving it leaves wind_layers null. */
const CAVOK_SETUP = {
  wind_layers: null,
  cloud_layers: [],
  visibility_m: 20000,
  qnh_hpa: 1013.25,
  temperature_c: 15,
  dewpoint_c: 5,
  precipitation_ratio: 0,
  runway_contamination: 'dry' as const,
};

/** What the server would actually have on record after applying it: wind untouched. */
const AFTER_CAVOK: WeatherState = { ...CAVOK_SETUP, wind_layers: CURRENT.wind_layers };

let calls: { url: string; method: string; body: unknown }[];

function json(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function stubApi(
  options: {
    capabilities?: Capabilities;
    current?: WeatherState;
    refreshed?: WeatherState;
    applyStatus?: number;
    applyDetail?: unknown;
    disconnected?: boolean;
  } = {},
) {
  calls = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
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
      if (url.includes('/weather/manifest')) {
        return json(MANIFEST);
      }
      if (url.includes('/weather/preview')) {
        const preview: WeatherPreview = {
          request: body as WeatherRequest,
          setup: CAVOK_SETUP,
          notes: ["visibility_m=20000 — the 'cavok' preset states 20000."],
        };
        return json(preview);
      }
      if (url.includes('/weather/apply')) {
        if (options.disconnected) throw new TypeError('Failed to fetch');
        const status = options.applyStatus ?? 200;
        if (status !== 200) {
          return json(
            {
              detail:
                options.applyDetail ??
                "Unavailable — the 'xplane' adapter does not declare can_set_weather.",
            },
            status,
          );
        }
        const result: WeatherApplyResult = {
          applied: CAVOK_SETUP,
          state: AFTER_CAVOK,
          notes: [],
        };
        return json(result);
      }
      if (url.includes('/weather')) {
        const reads = calls.filter(
          (call) => call.method === 'GET' && /\/weather$/.test(call.url),
        );
        return json(
          reads.length > 1
            ? (options.refreshed ?? options.current ?? CURRENT)
            : (options.current ?? CURRENT),
        );
      }
      return json({});
    }),
  );
}

function renderPanel(preloadedState?: Partial<RootState>) {
  const store = setupStore(preloadedState);
  render(
    <Provider store={store}>
      <WeatherPanel />
    </Provider>,
  );
  return store;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('WeatherPanel', () => {
  it('renders nothing clickable until the adapter and the current weather are known', async () => {
    stubApi();
    renderPanel();

    // Refresh may render while loading, but writes and edits must remain unavailable.
    expect(screen.queryByRole('button', { name: /CAVOK/ })).not.toBeInTheDocument();
    for (const button of screen.queryAllByRole('button')) expect(button).toBeDisabled();
    expect(screen.getByText(/waiting for the adapter capabilities/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /CAVOK/ })).toBeEnabled();
    });
    expect(screen.getByRole('button', { name: 'Add wind layer' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Add cloud layer' })).toBeEnabled();

    // The relative preset stays disabled without a runway, with the reason stated.
    expect(screen.getByRole('button', { name: /Crosswind/ })).toBeDisabled();
    expect(
      screen.getByText(
        'Relative to a runway — select an airport and runway in Position first.',
      ),
    ).toBeInTheDocument();
  });

  it('enables the crosswind tile when Position has an airport and runway', async () => {
    stubApi();
    renderPanel({ position: POSITION_WITH_RUNWAY });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Crosswind/ })).toBeEnabled();
    });
  });

  it('disables every tile when the adapter does not declare can_set_weather, and says why', async () => {
    stubApi({ capabilities: { ...CAPABLE, can_set_weather: false } });
    renderPanel();

    await waitFor(() => {
      expect(screen.getByText(/can_set_weather/)).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /CAVOK/ })).toBeDisabled();
  });

  it('stages on the first tap and previews without moving anything', async () => {
    const user = userEvent.setup();
    stubApi();
    renderPanel();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /CAVOK/ })).toBeEnabled();
    });

    await user.click(screen.getByRole('button', { name: /CAVOK/ }));

    expect(await screen.findByText('Staged: CAVOK')).toBeInTheDocument();
    expect(screen.getByText('Tap again to apply')).toBeInTheDocument();
    expect(calls.some((call) => call.url.includes('/weather/preview'))).toBe(true);
    expect(calls.some((call) => call.url.includes('/weather/apply'))).toBe(false);
  });

  it('sends preset + runway context on preview, never a client-resolved setup', async () => {
    const user = userEvent.setup();
    stubApi();
    renderPanel({ position: POSITION_WITH_RUNWAY });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /CAVOK/ })).toBeEnabled();
    });

    await user.click(screen.getByRole('button', { name: /CAVOK/ }));
    await screen.findByText('Staged: CAVOK');

    const preview = calls.find((call) => call.url.includes('/weather/preview'));
    expect(preview?.body).toEqual({
      preset: 'cavok',
      airport_icao: 'LEMD',
      runway_ident: '32L',
      setup: null,
    });
  });

  it('applies on Apply weather, and the wind stays untouched because CAVOK never states one', async () => {
    const user = userEvent.setup();
    stubApi();
    const store = renderPanel();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /CAVOK/ })).toBeEnabled();
    });

    await user.click(screen.getByRole('button', { name: /CAVOK/ }));
    await screen.findByText('Staged: CAVOK');

    await user.click(screen.getByRole('button', { name: 'Apply weather' }));

    await waitFor(() => {
      expect(store.getState().weather.staged).toBe(false);
    });
    expect(screen.queryByRole('button', { name: 'Apply weather' })).toBeNull();
    expect(screen.getByRole('status')).toHaveTextContent('Weather applied.');

    // QNH moved to CAVOK's own figure...
    expect(screen.getByText('1013 hPa')).toBeInTheDocument();
    // ...but the wind — which CAVOK never touches — is exactly what it was before.
    expect(screen.getByText('270° / 5 kt', { selector: 'dd' })).toBeInTheDocument();
  });

  it('renders an apply failure inline instead of in a modal', async () => {
    const user = userEvent.setup();
    stubApi({ applyStatus: 501 });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /CAVOK/ })).toBeEnabled();
    });

    await user.click(screen.getByRole('button', { name: /CAVOK/ }));
    await screen.findByText('Staged: CAVOK');
    await user.click(screen.getByRole('button', { name: 'Apply weather' }));

    expect(
      await screen.findByText(/does not declare can_set_weather/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    // Staging survives a failed apply — nothing was cleared.
    expect(screen.getByText('Staged: CAVOK')).toBeInTheDocument();
  });

  it('lets the instructor edit the staged cloud coverage on the octa chips', async () => {
    const user = userEvent.setup();
    stubApi();
    renderPanel();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /CAVOK/ })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: /CAVOK/ }));
    await screen.findByText('Staged: CAVOK');

    // CAVOK resolves to clear skies, so the editor renders the "no layers" empty state —
    // adding a layer is how the instructor puts cloud into an otherwise clear day. It
    // defaults to 4 octas (SCT); picking 8 (OVC) must move the pressed chip, not just add a
    // second one.
    await user.click(screen.getByRole('button', { name: 'Add cloud layer' }));
    const group = screen.getByRole('group', { name: /Layer 1 coverage in octas/i });
    expect(within(group).getByRole('button', { name: '4' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );

    await user.click(within(group).getByRole('button', { name: '8' }));

    expect(within(group).getByRole('button', { name: '8' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(within(group).getByRole('button', { name: '4' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });

  it("shows today's actual weather in the editors before anything is staged", async () => {
    stubApi();
    renderPanel();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /CAVOK/ })).toBeEnabled();
    });

    expect(screen.getByLabelText('QNH (hPa)')).toHaveValue(1016);
    expect(screen.queryByText('Manual weather')).not.toBeInTheDocument();
    expect(screen.queryByText(/^Staged:/)).not.toBeInTheDocument();
    expect(calls.some((call) => call.url.includes('/weather/preview'))).toBe(false);
  });

  it('stages manually on the first edit, with no preset tapped', async () => {
    stubApi();
    const store = renderPanel();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /CAVOK/ })).toBeEnabled();
    });

    fireEvent.change(screen.getByLabelText('QNH (hPa)'), { target: { value: '1005' } });

    expect(await screen.findByText('Manual weather')).toBeInTheDocument();
    expect(store.getState().weather.staged).toBe(true);
    expect(store.getState().weather.selectedPresetId).toBeNull();
    expect(calls.some((call) => call.url.includes('/weather/preview'))).toBe(false);
  });

  it('applies a manual edit as {preset: null, setup: …}, with no /preview call', async () => {
    const user = userEvent.setup();
    stubApi();
    const store = renderPanel();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /CAVOK/ })).toBeEnabled();
    });

    fireEvent.change(screen.getByLabelText('QNH (hPa)'), { target: { value: '1005' } });
    await screen.findByText('Manual weather');

    await user.click(screen.getByRole('button', { name: 'Apply weather' }));

    await waitFor(() => {
      expect(store.getState().weather.staged).toBe(false);
    });
    expect(calls.some((call) => call.url.includes('/weather/preview'))).toBe(false);
    const apply = calls.find((call) => call.url.includes('/weather/apply'));
    expect(apply?.body).toEqual({
      preset: null,
      airport_icao: null,
      runway_ident: null,
      setup: { qnh_hpa: 1005 },
    });
  });

  it('disables Apply with a reason when a manual stage has nothing to send', async () => {
    stubApi();
    renderPanel({
      weather: { selectedPresetId: null, overrides: {}, staged: true },
    });
    await waitFor(() => {
      expect(screen.getByText('Manual weather')).toBeInTheDocument();
    });

    expect(screen.getByRole('button', { name: 'Apply weather' })).toBeDisabled();
    expect(
      screen.getByText('No changes yet — edit a field to apply.'),
    ).toBeInTheDocument();
    expect(calls.some((call) => call.url.includes('/weather/apply'))).toBe(false);
  });

  it('permits a blank field while typing and blocks Apply until it is corrected', async () => {
    stubApi();
    const store = renderPanel();
    const qnh = await screen.findByLabelText('QNH (hPa)');
    fireEvent.change(qnh, { target: { value: '' } });

    expect(qnh).toHaveValue(null);
    expect(qnh).toHaveAttribute('aria-invalid', 'true');
    expect(await screen.findByRole('button', { name: 'Apply weather' })).toBeDisabled();
    expect(calls.some((call) => call.url.includes('/weather/apply'))).toBe(false);
    expect(calls.some((call) => call.url.includes('/weather/preview'))).toBe(false);

    fireEvent.change(qnh, { target: { value: '1007.5' } });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Apply weather' })).toBeEnabled(),
    );
    expect(store.getState().weather.overrides.qnh_hpa).toBe(1007.5);
  });

  it('discards invalid and valid edits without writing, including the local blank draft', async () => {
    const user = userEvent.setup();
    stubApi();
    const store = renderPanel();
    fireEvent.change(await screen.findByLabelText('QNH (hPa)'), {
      target: { value: '1005' },
    });
    fireEvent.change(screen.getByLabelText('Visibility (m)'), { target: { value: '' } });
    await user.click(screen.getByRole('button', { name: 'Discard' }));

    expect(screen.getByLabelText('QNH (hPa)')).toHaveValue(1016);
    expect(screen.getByLabelText('Visibility (m)')).toHaveValue(10000);
    expect(store.getState().weather.staged).toBe(false);
    expect(calls.filter((call) => call.method !== 'GET')).toEqual([]);
  });

  it('refreshes actual conditions while keeping pending overrides and blank fields', async () => {
    const user = userEvent.setup();
    stubApi({ refreshed: { ...CURRENT, qnh_hpa: 1020, visibility_m: 25000 } });
    const store = renderPanel();
    fireEvent.change(await screen.findByLabelText('QNH (hPa)'), {
      target: { value: '1005' },
    });
    fireEvent.change(screen.getByLabelText('Temperature (°C)'), {
      target: { value: '' },
    });
    await user.click(screen.getByRole('button', { name: 'Refresh weather' }));

    await waitFor(() =>
      expect(screen.getByLabelText('Visibility (m)')).toHaveValue(25000),
    );
    expect(screen.getByLabelText('QNH (hPa)')).toHaveValue(1005);
    expect(screen.getByLabelText('Temperature (°C)')).toHaveValue(null);
    expect(screen.getByRole('button', { name: 'Apply weather' })).toBeDisabled();
    expect(store.getState().weather.overrides).toEqual({ qnh_hpa: 1005 });
    expect(calls.some((call) => call.method !== 'GET')).toBe(false);
  });

  it('blocks contradictory temperature and dewpoint instead of displaying a silent clamp', async () => {
    stubApi();
    renderPanel();
    fireEvent.change(await screen.findByLabelText('Temperature (°C)'), {
      target: { value: '5' },
    });

    expect(screen.getByLabelText('Dewpoint (°C)')).toHaveValue(7);
    expect(await screen.findByRole('button', { name: 'Apply weather' })).toBeDisabled();
    expect(screen.getByText(/Dewpoint must not exceed temperature/)).toBeInTheDocument();
    expect(calls.some((call) => call.url.includes('/weather/apply'))).toBe(false);
  });

  it('shows structured 422 errors, keeps the draft and reads actual state after partial failure', async () => {
    const user = userEvent.setup();
    stubApi({
      applyStatus: 422,
      applyDetail: [
        { loc: ['body', 'setup', 'qnh_hpa'], msg: 'Pressure rejected by simulator.' },
      ],
      refreshed: { ...CURRENT, visibility_m: 1234 },
    });
    const store = renderPanel();
    fireEvent.change(await screen.findByLabelText('QNH (hPa)'), {
      target: { value: '1005' },
    });
    await user.click(screen.getByRole('button', { name: 'Apply weather' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'setup.qnh_hpa: Pressure rejected by simulator.',
    );
    await waitFor(() =>
      expect(screen.getByLabelText('Visibility (m)')).toHaveValue(1234),
    );
    expect(store.getState().weather.overrides).toEqual({ qnh_hpa: 1005 });
    expect(screen.getByLabelText('QNH (hPa)')).toHaveValue(1005);
    expect(screen.getByRole('button', { name: 'Apply weather' })).toBeEnabled();
  });

  it('retains the draft after a disconnected apply and refreshes actual weather', async () => {
    const user = userEvent.setup();
    stubApi({ disconnected: true, refreshed: { ...CURRENT, visibility_m: 8000 } });
    const store = renderPanel();
    fireEvent.change(await screen.findByLabelText('QNH (hPa)'), {
      target: { value: '1005' },
    });
    await user.click(screen.getByRole('button', { name: 'Apply weather' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The weather could not be applied.',
    );
    await waitFor(() =>
      expect(screen.getByLabelText('Visibility (m)')).toHaveValue(8000),
    );
    expect(store.getState().weather.staged).toBe(true);
    expect(screen.getByLabelText('QNH (hPa)')).toHaveValue(1005);
  });
});
