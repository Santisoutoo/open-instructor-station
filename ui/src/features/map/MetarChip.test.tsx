/**
 * The METAR chip against a stubbed API — `fetch` stubbed rather than the RTK Query hooks
 * mocked, the same choice `WeatherPanel.test.tsx` makes, because what the chip actually
 * asks for (and, when the gate is closed, that it asks for NOTHING) is what is worth
 * asserting.
 *
 * The behaviour under test is D10's fail-closed discipline: the chip is ABSENT — not
 * disabled, not a placeholder — unless `can_set_weather` is declared and the weather read
 * succeeded, and it never even issues `GET /api/weather` while the capability is unknown
 * or false (the endpoint 501s without it).
 */

import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Capabilities, WeatherState } from '../../api/models';
import { setupStore } from '../../store';
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
          ? json(COMMANDED)
          : json({ detail: 'Unavailable' }, status);
      }
      return json({});
    }),
  );
}

function renderChip() {
  const store = setupStore();
  const { container } = render(
    <Provider store={store}>
      <MetarChip />
    </Provider>,
  );
  return container;
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

  it('renders nothing without can_set_weather, and never asks for the weather', async () => {
    stubApi({ capabilities: { ...CAPABLE, can_set_weather: false } });
    const container = renderChip();

    await waitFor(() => {
      expect(calls.some((url) => url.includes('/capabilities'))).toBe(true);
    });
    expect(container).toBeEmptyDOMElement();
    expect(calls.some((url) => url.includes('/weather'))).toBe(false);
  });

  it('renders nothing when the capabilities themselves cannot be read', async () => {
    stubApi({ capabilitiesStatus: 500 });
    const container = renderChip();

    await waitFor(() => {
      expect(calls.some((url) => url.includes('/capabilities'))).toBe(true);
    });
    expect(container).toBeEmptyDOMElement();
    expect(calls.some((url) => url.includes('/weather'))).toBe(false);
  });

  it('renders nothing when the weather read fails', async () => {
    stubApi({ weatherStatus: 501 });
    const container = renderChip();

    await waitFor(() => {
      expect(calls.some((url) => url.includes('/weather'))).toBe(true);
    });
    expect(container).toBeEmptyDOMElement();
  });
});
