/**
 * The METAR chip against a stubbed API — `fetch` stubbed rather than the RTK Query hooks
 * mocked, the same choice `WeatherPanel.test.tsx` makes, because what the chip actually
 * asks for (and, when the gate is closed, that it asks for NOTHING) is what is worth
 * asserting.
 *
 * The behaviour under test is D10's two fail-closed postures: a *disabled* chip with the
 * reason stated when the capabilities are known and `can_set_weather` is false, and
 * NOTHING at all while the capabilities are unknown/unreadable or the weather read fails —
 * and in every closed state `GET /api/weather` is never even issued (the endpoint 501s
 * without the capability).
 *
 * The fail-closed assertions wait for the query to actually settle (the rendered reason,
 * or the query's own `rejected` status in the store) before asserting that no weather call
 * was made — asserting on "capabilities was requested" alone could pass before the
 * response was processed, proving nothing.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { instructorApi } from '../../api/instructorApi';
import type { Capabilities, WeatherState } from '../../api/models';
import { setupStore } from '../../store';
import { weatherApi } from '../weather/weatherApi';
import { MetarChip } from './MetarChip';

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

const COMMANDED: WeatherState = {
  wind_layers: [
    { altitude_ft: 0, direction_deg: 270, speed_kt: 5, gust_increase_kt: 0, turbulence_ratio: 0 },
  ],
  cloud_layers: [],
  visibility_m: 10000,
  qnh_hpa: 1016,
  temperature_c: 19,
  dewpoint_c: 7,
  precipitation_ratio: 0,
  runway_contamination: 'dry',
};

let calls: string[];

function json(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function stubApi(
  options: {
    capabilities?: Capabilities;
    capabilitiesStatus?: number;
    weatherStatus?: number;
    weather?: WeatherState;
  } = {},
) {
  calls = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
      const url = input instanceof Request ? input.url : String(input);
      calls.push(url);

      if (url.includes('/capabilities')) {
        const status = options.capabilitiesStatus ?? 200;
        return status === 200
          ? json(options.capabilities ?? CAPABLE)
          : json({ detail: 'boom' }, status);
      }
      if (url.includes('/weather')) {
        const status = options.weatherStatus ?? 200;
        return status === 200
          ? json(options.weather ?? COMMANDED)
          : json({ detail: 'Unavailable' }, status);
      }
      return json({});
    }),
  );
}

function renderChip(fieldElevationFt: number | null = null) {
  const store = setupStore();
  const { container } = render(
    <Provider store={store}>
      <MetarChip fieldElevationFt={fieldElevationFt} />
    </Provider>,
  );
  return { container, store };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('MetarChip', () => {
  it('renders the commanded weather METAR-style, labelled as commanded, not observed', async () => {
    stubApi();
    renderChip();

    expect(await screen.findByText('27005KT CAVOK 19/07 Q1016')).toBeInTheDocument();
    expect(screen.getByRole('note', { name: 'Commanded weather' })).toHaveTextContent(
      'commanded weather — not a live observation',
    );
  });

  it('renders cloud bases AGL when the reference airport elevation is passed', async () => {
    stubApi({
      weather: {
        ...COMMANDED,
        cloud_layers: [
          {
            base_ft: 2500,
            tops_ft: 5000,
            coverage_ratio: 0.75,
            cloud_type: 'stratus',
          },
        ],
      },
    });
    renderChip(1500);

    // 2500 ft MSL over a 1500 ft field reads as a 1000 ft ceiling.
    expect(
      await screen.findByText('27005KT 9999 BKN010 19/07 Q1016'),
    ).toBeInTheDocument();
  });

  it('renders a DISABLED chip with the reason without can_set_weather, and never asks for the weather', async () => {
    stubApi({ capabilities: { ...CAPABLE, can_set_weather: false } });
    renderChip();

    // The rendered reason IS the proof the capabilities response was processed.
    expect(
      await screen.findByText(/does not declare can_set_weather/),
    ).toBeInTheDocument();
    const chip = screen.getByRole('note', { name: 'Commanded weather' });
    expect(chip).toHaveAttribute('aria-disabled', 'true');
    expect(chip).toHaveTextContent('METAR unavailable');
    expect(calls.some((url) => url.includes('/weather'))).toBe(false);
  });

  it('renders nothing when the capabilities themselves cannot be read', async () => {
    stubApi({ capabilitiesStatus: 500 });
    const { container, store } = renderChip();

    // Wait for the query itself to settle as rejected — only then is "still empty and no
    // weather call" a verdict rather than a race.
    await waitFor(() => {
      expect(
        instructorApi.endpoints.getCapabilities.select()(store.getState()).isError,
      ).toBe(true);
    });
    expect(container).toBeEmptyDOMElement();
    expect(calls.some((url) => url.includes('/weather'))).toBe(false);
  });

  it('renders nothing when the weather read fails', async () => {
    stubApi({ weatherStatus: 501 });
    const { container, store } = renderChip();

    await waitFor(() => {
      expect(
        weatherApi.endpoints.getWeatherState.select()(store.getState()).isError,
      ).toBe(true);
    });
    expect(container).toBeEmptyDOMElement();
  });
});
