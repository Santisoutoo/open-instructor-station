/**
 * The Camera panel against a stubbed API — the wiring, and the four failures.
 *
 * What is worth pinning here is not that buttons render (`ViewGrid.test.tsx` and
 * `SavedPositions.test.tsx` already own that) but that the panel turns a tap into exactly
 * one request with exactly the right body, and that each of the four refusals the server
 * can give arrives at the instructor as *itself*: a 501 must not read like a 409, or the
 * instructor gives up on something that would have worked after one more tap.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Capabilities, CameraManifest } from '../../api/models';
import { setupStore } from '../../store';
import { CameraPanel } from './CameraPanel';
import { cameraManifestFixture, savedPositionsFixture } from './fixtures';
import { callsTo, stubApi, type Answer } from './testApi';

function capabilities(canControlCamera: boolean): Capabilities {
  return {
    can_set_position: true,
    can_set_aircraft_state: true,
    can_set_weather: true,
    can_inject_failures: true,
    can_spawn_traffic: false,
    can_control_autopilot: true,
    can_set_fuel_payload: true,
    can_control_camera: canControlCamera,
    can_pushback: false,
  };
}

/** What `XPlaneSimAdapter.get_camera_support()` answers today: no, and why, per entry. */
const XPLANE_REASON = "'xplane' does not declare can_control_camera.";

function refusedManifest(): CameraManifest {
  const base = cameraManifestFixture();
  return {
    ...base,
    adapter: 'xplane',
    views: base.views.map((view) => ({ ...view, supported: false, reason: XPLANE_REASON })),
    custom_positions_supported: false,
    custom_positions_reason: XPLANE_REASON,
  };
}

/**
 * `overrides` is spread between the defaults and the positions list, so a test can
 * replace any default answer; keys are matched by `"<METHOD> <fragment>"` in insertion
 * order, which is what separates `POST /positions` (save) from
 * `POST /positions/{id}/apply`.
 */
function renderPanel(
  overrides: Record<string, Answer> = {},
  canControlCamera = true,
): { calls: ReturnType<typeof stubApi>['calls'] } {
  const { calls } = stubApi({
    'GET capabilities': { body: capabilities(canControlCamera) },
    'GET camera/manifest': {
      body: canControlCamera ? cameraManifestFixture() : refusedManifest(),
    },
    // A default so that a test about *saving* is never also a test about an unrouted
    // view request; overriding this key replaces the value, not the position.
    'POST camera/view': { body: { view_id: 'drone', offset: null } },
    ...overrides,
    'GET camera/positions': { body: savedPositionsFixture() },
  });
  render(
    <Provider store={setupStore()}>
      <CameraPanel />
    </Provider>,
  );
  return { calls };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('<CameraPanel />', () => {
  it('issues exactly one POST /camera/view carrying the tapped view id', async () => {
    const { calls } = renderPanel({
      'POST camera/view': { body: { view_id: 'chase', offset: null } },
    });

    await userEvent.click(await screen.findByRole('button', { name: /Chase/ }));

    await waitFor(() => {
      expect(callsTo(calls, 'POST', 'camera/view')).toHaveLength(1);
    });
    expect(callsTo(calls, 'POST', 'camera/view')[0]?.body).toEqual({ view_id: 'chase' });
  });

  it('moves the highlight on the tap, without waiting for a read-back (D6)', async () => {
    renderPanel({ 'POST camera/view': { body: { view_id: 'tower', offset: null } } });

    const tower = await screen.findByRole('button', { name: /Tower/ });
    expect(tower).toHaveAttribute('aria-pressed', 'false');

    await userEvent.click(tower);

    expect(tower).toHaveAttribute('aria-pressed', 'true');
  });

  // ------------------------------------------------------------------ 501
  it('renders every view disabled WITH the adapter reason when the capability is absent', async () => {
    renderPanel({}, false);

    // One reason per view plus the saved-positions tier — the manifest is capability-free,
    // so it still answers "no, and here is why" for every entry.
    await waitFor(() => {
      expect(screen.getAllByText(XPLANE_REASON)).toHaveLength(6);
    });
    // The whole catalogue is still on screen — disabled, never hidden (hard rule 3).
    const cards = screen.getAllByRole('button', {
      name: /Cockpit|Chase|Tower|Wing|Drone/,
    });
    expect(cards).toHaveLength(5);
    for (const card of cards) {
      expect(card).toBeDisabled();
    }
    // And the tab-level gate names the capability rather than saying "unavailable".
    expect(screen.getByText(/camera control is disabled/)).toBeInTheDocument();
  });

  it('states a 501 from the server as a capability refusal', async () => {
    renderPanel({
      'POST camera/view': {
        status: 501,
        detail: 'No X-Plane command for a wing view was found on this install.',
      },
    });

    await userEvent.click(await screen.findByRole('button', { name: /Wing/ }));

    const notice = await screen.findByRole('alert');
    expect(notice).toHaveTextContent('No X-Plane command for a wing view');
    expect(notice).toHaveClass('camera-notice--unsupported');
  });

  // ------------------------------------------------------------------ 409
  it('states a 409 on save as a precondition, not as an unsupported capability', async () => {
    const detail =
      'Cannot save a camera position right now — switch to the drone/free camera first.';
    renderPanel({ 'POST camera/positions': { status: 409, detail } });

    // The client-side mirror of the precondition gates Save until the drone view is
    // requested; asking anyway is what the server's own 409 is for.
    await userEvent.click(await screen.findByRole('button', { name: /Drone/ }));
    await userEvent.type(
      screen.getByRole('textbox', { name: 'Position name' }),
      'Base leg view',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Save current' }));

    const notice = await screen.findByRole('alert');
    expect(notice).toHaveTextContent(detail);
    expect(notice).toHaveClass('camera-notice--precondition');
    expect(notice).not.toHaveClass('camera-notice--unsupported');
    // The draft survives, so clearing the precondition and pressing Save again is enough.
    expect(screen.getByRole('textbox', { name: 'Position name' })).toHaveValue(
      'Base leg view',
    );
  });

  // ------------------------------------------------------------------ 404
  it('states a 404 on apply as an unknown id and re-reads the list', async () => {
    const { calls } = renderPanel({
      'POST camera/positions/pos-2/apply': {
        status: 404,
        detail: "No saved camera position 'pos-2'.",
      },
    });

    await userEvent.click(await screen.findByRole('button', { name: 'Apply Base leg view' }));

    const notice = await screen.findByRole('alert');
    expect(notice).toHaveTextContent("No saved camera position 'pos-2'.");
    expect(notice).toHaveClass('camera-notice--missing');
    // A 404 means the list, not the camera, is stale — so the list is refetched.
    await waitFor(() => {
      expect(callsTo(calls, 'GET', 'camera/positions').length).toBeGreaterThan(1);
    });
  });

  // ------------------------------------------------------------------ 422
  it('states a 422 as the name bound, since FastAPI’s detail is a list', async () => {
    renderPanel({
      'POST camera/positions': {
        status: 422,
        detail: [{ loc: ['body', 'name'], msg: 'String should have at most 60 characters' }],
      },
    });

    await userEvent.click(await screen.findByRole('button', { name: /Drone/ }));
    await userEvent.type(screen.getByRole('textbox', { name: 'Position name' }), 'x');
    await userEvent.click(screen.getByRole('button', { name: 'Save current' }));

    const notice = await screen.findByRole('alert');
    expect(notice).toHaveTextContent('between 1 and 60 characters');
    expect(notice).toHaveClass('camera-notice--invalid');
  });

  // ------------------------------------------------------------- happy path
  it('saves under the trimmed name, clears the draft and re-reads the list', async () => {
    const [saved] = savedPositionsFixture();
    const { calls } = renderPanel({ 'POST camera/positions': { body: saved } });

    await userEvent.click(await screen.findByRole('button', { name: /Drone/ }));
    const input = screen.getByRole('textbox', { name: 'Position name' });
    await userEvent.type(input, 'Base leg view');
    await userEvent.click(screen.getByRole('button', { name: 'Save current' }));

    await waitFor(() => {
      expect(callsTo(calls, 'POST', 'camera/positions')).toHaveLength(1);
    });
    expect(callsTo(calls, 'POST', 'camera/positions')[0]?.body).toEqual({
      name: 'Base leg view',
    });
    await waitFor(() => {
      expect(input).toHaveValue('');
    });
    await waitFor(() => {
      expect(callsTo(calls, 'GET', 'camera/positions').length).toBeGreaterThan(1);
    });
  });

  it('deletes exactly one position and re-reads the list', async () => {
    const { calls } = renderPanel({
      'DELETE camera/positions/pos-1': { status: 204, body: null },
    });

    await userEvent.click(
      await screen.findByRole('button', { name: 'Delete Three-quarter left' }),
    );

    await waitFor(() => {
      expect(callsTo(calls, 'DELETE', 'camera/positions/pos-1')).toHaveLength(1);
    });
    await waitFor(() => {
      expect(callsTo(calls, 'GET', 'camera/positions').length).toBeGreaterThan(1);
    });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
