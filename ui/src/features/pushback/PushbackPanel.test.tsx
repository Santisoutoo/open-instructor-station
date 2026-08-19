/**
 * The Pushback panel end to end against a stubbed API.
 *
 * `fetch` is stubbed rather than the RTK Query hooks mocked — the `WeatherPanel` and
 * `position/StagingBar` choice, for the same reason: the request the panel actually sends
 * is what is worth asserting, and mocking the hooks would hide a panel that asks the
 * wrong endpoint or ships the wrong body.
 *
 * The load-bearing assertions here are the ones the backend's own docstring insists on:
 *
 * - the body posted to `/preview` and `/execute` is the EXACT wire shape
 *   (`direction`/`distance_m`/`angle_deg`), asserted with deep equality so no field can
 *   silently default or stow away;
 * - **501 and 409 must not read the same.** A missing `can_pushback` disables the panel;
 *   an airborne aircraft does not, because it is over the moment the wheels are down;
 * - Execute is armed by a preview that *came back*, never by the act of pressing Preview
 *   — otherwise the panel would offer to execute a manoeuvre the server has just refused.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type {
  AircraftState,
  PushbackManifest,
  PushbackPreview,
  PushbackRequest,
  PushbackResult,
  PushbackTarget,
} from '../../api/models';
import { setupStore } from '../../store';
import { PushbackPanel } from './PushbackPanel';

const SUPPORTED: PushbackManifest = {
  adapter: 'fake',
  supported: true,
  reason: null,
  max_distance_m: 200,
  max_angle_deg: 180,
};

const UNSUPPORTED: PushbackManifest = {
  adapter: 'xplane',
  supported: false,
  reason: "The 'xplane' adapter does not declare can_pushback.",
  max_distance_m: 200,
  max_angle_deg: 180,
};

/** A parked aircraft at LEMD, facing 090°. */
const CURRENT = { latitude: 40.4936, longitude: -3.5668, altitude_ft: 1998 };

const STATE: AircraftState = {
  latitude: 40.4936,
  longitude: -3.5671,
  altitude_ft: 1998,
  heading_deg: 90,
  ias_kt: 0,
  vertical_speed_fpm: 0,
  pitch_deg: 0,
  roll_deg: 0,
  on_ground: true,
};

/** Nine points, as `core.pushback` returns; only the count and the ends are load-bearing. */
function target(headingDeg: number): PushbackTarget {
  const points = Array.from({ length: 9 }, (_, index) => ({
    latitude: CURRENT.latitude,
    longitude: CURRENT.longitude - index * 0.00003,
    altitude_ft: CURRENT.altitude_ft,
  }));
  return {
    position: points[points.length - 1] ?? CURRENT,
    heading_deg: headingDeg,
    path_preview: points,
  };
}

const NOT_ON_GROUND_DETAIL = 'Cannot push back — the aircraft is airborne.';
const UNSUPPORTED_DETAIL =
  "Unavailable on this adapter — the 'xplane' adapter does not declare can_pushback, " +
  'so it cannot push the aircraft back.';

let calls: { url: string; method: string; body: unknown }[];

function json(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

interface StubOptions {
  manifest?: PushbackManifest;
  /** HTTP status for `/preview`; 200 unless a test is exercising a refusal. */
  previewStatus?: number;
  executeStatus?: number;
}

function stubApi(options: StubOptions = {}) {
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

      if (url.includes('/pushback/manifest')) {
        return json(options.manifest ?? SUPPORTED);
      }
      if (url.includes('/pushback/preview')) {
        if (options.previewStatus === 409) {
          return json({ detail: NOT_ON_GROUND_DETAIL }, 409);
        }
        const asked = body as PushbackRequest;
        const preview: PushbackPreview = {
          request: asked,
          current_position: CURRENT,
          current_heading_deg: 90,
          target: target(90 + asked.angle_deg),
        };
        return json(preview);
      }
      if (url.includes('/pushback/execute')) {
        const status = options.executeStatus ?? 200;
        if (status === 501) {
          return json({ detail: UNSUPPORTED_DETAIL }, 501);
        }
        if (status === 409) {
          return json({ detail: NOT_ON_GROUND_DETAIL }, 409);
        }
        const asked = body as PushbackRequest;
        const result: PushbackResult = {
          request: asked,
          target: target(90 + asked.angle_deg),
          state: STATE,
        };
        return json(result);
      }
      return json({});
    }),
  );
}

function renderPanel() {
  const store = setupStore();
  render(
    <Provider store={store}>
      <PushbackPanel />
    </Provider>,
  );
  return store;
}

function bodiesFor(path: string): unknown[] {
  return calls.filter((call) => call.url.includes(path)).map((call) => call.body);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('PushbackPanel', () => {
  it('fails closed until the manifest arrives, then opens', async () => {
    stubApi();
    renderPanel();

    expect(screen.getByRole('status')).toHaveTextContent(/waiting/i);
    expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Preview' })).toBeEnabled();
    });
    // Nothing was asked of the simulator just by opening the tab.
    expect(bodiesFor('/pushback/preview')).toHaveLength(0);
  });

  it("previews the one-tap default as the exact wire shape, and doesn't move anything", async () => {
    const user = userEvent.setup();
    stubApi();
    renderPanel();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Preview' })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: 'Preview' }));

    await waitFor(() => {
      expect(bodiesFor('/pushback/preview')).toEqual([
        { direction: 'straight', distance_m: 20, angle_deg: 0 },
      ]);
    });
    expect(bodiesFor('/pushback/execute')).toHaveLength(0);
  });

  it('draws the SERVER\'s path and states its heading change, not a client re-derivation', async () => {
    const user = userEvent.setup();
    stubApi();
    renderPanel();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Preview' })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: 'Nose right' }));
    await user.click(screen.getByRole('button', { name: 'Preview' }));

    // 090 + 45 (the default arc angle) = 135, and it is the SERVER's number.
    await waitFor(() => {
      expect(screen.getByText(/090° → 135°/)).toBeInTheDocument();
    });
    const polyline = document.body.querySelector('polyline');
    expect(polyline?.getAttribute('points')?.split(' ')).toHaveLength(9);
  });

  it('executes exactly what was previewed, then disarms — the push is not idempotent', async () => {
    const user = userEvent.setup();
    stubApi();
    const store = renderPanel();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Preview' })).toBeEnabled();
    });

    const execute = screen.getByRole('button', { name: 'Execute pushback' });
    expect(execute).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Nose right' }));
    await user.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => {
      expect(execute).toBeEnabled();
    });

    await user.click(execute);

    await waitFor(() => {
      expect(bodiesFor('/pushback/execute')).toEqual([
        { direction: 'right', distance_m: 20, angle_deg: 45 },
      ]);
    });
    // Disarmed again: a second tap must not push back a second time.
    await waitFor(() => {
      expect(execute).toBeDisabled();
    });
    expect(store.getState().pushback.staged).toBeNull();
    expect(screen.getByText(/Pushed back/)).toBeInTheDocument();
  });

  it('disarms Execute again on any edit after staging — a stale preview never runs', async () => {
    const user = userEvent.setup();
    stubApi();
    renderPanel();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Preview' })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: 'Preview' }));

    const execute = screen.getByRole('button', { name: 'Execute pushback' });
    await waitFor(() => {
      expect(execute).toBeEnabled();
    });

    await user.click(screen.getByRole('button', { name: 'Nose left' }));

    expect(execute).toBeDisabled();
  });

  // ------------------------------------------------------ 501 is NOT 409

  it('501: a missing can_pushback disables every control and names adapter and flag', async () => {
    stubApi({ manifest: UNSUPPORTED });
    renderPanel();

    await waitFor(() => {
      expect(screen.getByText(UNSUPPORTED.reason ?? '')).toBeInTheDocument();
    });
    // Disabled, never hidden (hard rule 3) — and disabled for good, not "right now".
    expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Execute pushback' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Nose right' })).toBeDisabled();
    expect(screen.getByRole('slider', { name: 'Pushback distance' })).toBeDisabled();
    expect(screen.queryByText(/airborne/i)).not.toBeInTheDocument();
  });

  it('409: an airborne aircraft is reported as temporary and leaves the controls alive', async () => {
    const user = userEvent.setup();
    stubApi({ previewStatus: 409 });
    renderPanel();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Preview' })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: 'Preview' }));

    await waitFor(() => {
      expect(screen.getByText(new RegExp(NOT_ON_GROUND_DETAIL))).toBeInTheDocument();
    });
    // The distinction, made visible: this is the aircraft's state, not the adapter's limit.
    expect(screen.getByText(/not a limit of the simulator/i)).toBeInTheDocument();
    expect(screen.queryByText(/can_pushback/)).not.toBeInTheDocument();

    // The manoeuvre can still be described — only the commit is held back.
    expect(screen.getByRole('button', { name: 'Nose right' })).toBeEnabled();
    expect(screen.getByRole('slider', { name: 'Pushback distance' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Preview' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Execute pushback' })).toBeDisabled();
  });

  it('never arms Execute on a refused preview — the path drawn is never one execute refuses', async () => {
    const user = userEvent.setup();
    stubApi({ previewStatus: 409 });
    renderPanel();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Preview' })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: 'Preview' }));

    await waitFor(() => {
      expect(screen.getByText(/airborne/i)).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: 'Execute pushback' }));

    expect(bodiesFor('/pushback/execute')).toHaveLength(0);
  });

  it('409 from execute keeps the controls live too — the aircraft rolled off in between', async () => {
    const user = userEvent.setup();
    stubApi({ executeStatus: 409 });
    renderPanel();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Preview' })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: 'Preview' }));

    const execute = screen.getByRole('button', { name: 'Execute pushback' });
    await waitFor(() => {
      expect(execute).toBeEnabled();
    });
    await user.click(execute);

    await waitFor(() => {
      expect(screen.getByText(new RegExp(NOT_ON_GROUND_DETAIL))).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: 'Nose right' })).toBeEnabled();
  });

  it('clears a previous push\'s refusal when the next preview succeeds', async () => {
    const user = userEvent.setup();
    stubApi({ executeStatus: 409 });
    renderPanel();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Preview' })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Execute pushback' })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: 'Execute pushback' }));
    await waitFor(() => {
      expect(screen.getByText(new RegExp(NOT_ON_GROUND_DETAIL))).toBeInTheDocument();
    });

    // Previewing again asks the server afresh; a stale refusal must not survive an
    // answer that contradicts it.
    await user.click(screen.getByRole('button', { name: 'Preview' }));

    await waitFor(() => {
      expect(screen.queryByText(new RegExp(NOT_ON_GROUND_DETAIL))).not.toBeInTheDocument();
    });
  });

  it('501 from execute — an adapter disagreeing with its own manifest — disables the panel', async () => {
    const user = userEvent.setup();
    stubApi({ executeStatus: 501 });
    renderPanel();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Preview' })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: 'Preview' }));

    const execute = screen.getByRole('button', { name: 'Execute pushback' });
    await waitFor(() => {
      expect(execute).toBeEnabled();
    });
    await user.click(execute);

    await waitFor(() => {
      expect(screen.getByText(UNSUPPORTED_DETAIL)).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: 'Nose right' })).toBeDisabled();
    expect(screen.queryByText(/not a limit of the simulator/i)).not.toBeInTheDocument();
  });

  it('bounds the sliders with the manifest, never with a constant of its own', async () => {
    stubApi({ manifest: { ...SUPPORTED, max_distance_m: 40, max_angle_deg: 60 } });
    renderPanel();

    await waitFor(() => {
      expect(screen.getByRole('slider', { name: 'Pushback distance' })).toHaveAttribute(
        'max',
        '40',
      );
    });
    expect(screen.getByRole('slider', { name: 'Pushback turn angle' })).toHaveAttribute(
      'max',
      '60',
    );
  });
});
