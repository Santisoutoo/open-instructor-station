/**
 * The panel-level behaviour: the gate fails closed against real capability answers, and
 * once open the four spawn forms, the despawn buttons and CLEAR ALL send exactly the
 * requests `server/traffic_routes.py` publishes.
 *
 * The first test is **Phase 3 exit criterion 3's UI half** and is deliberately the
 * strictest one here: against an adapter declaring `can_spawn_traffic: false` the panel
 * must still start and still render its controls, every write control must be *disabled*
 * — not removed, not merely dimmed — and the reason must be on screen. A hidden control
 * satisfies "cannot be used" but not "with a stated reason", and it is exactly the
 * outcome hard rule 3 exists to prevent.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Capabilities, TrafficContact } from '../../api/models';
import { setupStore } from '../../store';
import { initialTrafficState, type TrafficState } from './trafficSlice';
import { TrafficPanel } from './TrafficPanel';
import { callsTo, stubApi, type Answer } from './testApi';

function capabilities(overrides: Partial<Capabilities> = {}): Capabilities {
  return {
    can_set_position: false,
    can_set_aircraft_state: false,
    can_set_weather: false,
    can_inject_failures: false,
    can_spawn_traffic: true,
    can_control_autopilot: false,
    can_set_fuel_payload: false,
    can_control_camera: false,
    can_pushback: false,
    can_control_cockpit: false,
    ...overrides,
  };
}

function contact(overrides: Partial<TrafficContact> = {}): TrafficContact {
  return {
    traffic_id: 'a3f9',
    kind: 'aircraft',
    scenario_shape: 'approach_sequence',
    callsign: 'SEQ01',
    label: 'Approach sequence, 12 NM',
    latitude: 40.0,
    longitude: -3.0,
    altitude_ft: 3184,
    heading_deg: 322,
    ground_speed_kt: 120,
    vertical_speed_fpm: -650,
    on_ground: false,
    ...overrides,
  };
}

function status(contacts: TrafficContact[] = [], maxContacts: number | null = 19) {
  return { adapter: 'fake', contacts, max_contacts: maxContacts };
}

interface Routes {
  status?: Answer;
  spawn?: Answer;
  clear?: Answer;
  despawn?: Answer;
}

function renderPanel(
  caps: Capabilities,
  traffic: Partial<TrafficState> = {},
  routes: Routes = {},
) {
  // Insertion order matters: `stubApi` matches on the first URL fragment that fits, and
  // the bare `/traffic/` of a despawn would otherwise swallow the three named routes.
  const { calls } = stubApi({
    '/capabilities': { body: caps },
    '/traffic/status': routes.status ?? { body: status() },
    '/traffic/spawn': routes.spawn ?? { body: { contacts: [contact()] } },
    '/traffic/clear': routes.clear ?? { body: status() },
    '/traffic/': routes.despawn ?? { body: status() },
  });
  const store = setupStore({ traffic: { ...initialTrafficState, ...traffic } });
  render(
    <Provider store={store}>
      <TrafficPanel />
    </Provider>,
  );
  return { store, calls };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('TrafficPanel', () => {
  it('disables every write control with the stated reason when the adapter lacks can_spawn_traffic', async () => {
    renderPanel(capabilities({ can_spawn_traffic: false }), {
      contacts: [contact()],
      connected: true,
    });

    expect(
      await screen.findByText(/does not declare can_spawn_traffic/),
    ).toBeInTheDocument();
    // Disabled, not hidden: the instructor sees what they cannot do, and why.
    expect(screen.getByRole('button', { name: /spawn tcas conflict/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /clear all/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Despawn SEQ01' })).toBeDisabled();
    // The list itself is never gated — `/status` and `/ws/traffic` are capability-free.
    expect(screen.getByText('Active traffic')).toBeInTheDocument();
    expect(screen.getByText('SEQ01')).toBeInTheDocument();
  });

  it('opens on can_spawn_traffic: contact list on top, TCAS form by default', async () => {
    renderPanel(capabilities());

    expect(await screen.findByText('Active traffic')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /spawn tcas conflict/i })).toBeEnabled();
    });
  });

  it('the segmented picker swaps the active form and remembers it in the slice', async () => {
    const user = userEvent.setup();
    const { store } = renderPanel(capabilities());
    await screen.findByText('Active traffic');

    await user.click(screen.getByRole('button', { name: 'Runway incursion' }));

    expect(store.getState().traffic.selectedShape).toBe('runway_incursion');
    expect(
      screen.getByRole('button', { name: /spawn runway incursion/i }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /spawn tcas conflict/i })).toBeNull();
  });

  it('offers all four scenario shapes — custom is the map’s, not a form', async () => {
    renderPanel(capabilities());
    await screen.findByText('Active traffic');

    for (const label of [
      'TCAS conflict',
      'Runway incursion',
      'Approach sequence',
      'Taxi traffic',
    ]) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }
    expect(screen.queryByRole('button', { name: /custom/i })).toBeNull();
  });

  it('renders the WS-fed contacts from the slice', async () => {
    renderPanel(capabilities(), { contacts: [contact()], connected: true });

    expect(await screen.findByText('SEQ01')).toBeInTheDocument();
    expect(screen.getByText('3,184 ft · 120 kt')).toBeInTheDocument();
  });

  it('falls back to GET /status, capacity included, until the stream connects', async () => {
    renderPanel(
      capabilities(),
      { contacts: [], connected: false },
      { status: { body: status([contact({ callsign: 'SEQ09' })], 19) } },
    );

    expect(await screen.findByText('SEQ09')).toBeInTheDocument();
    expect(screen.getByText('1 / 19')).toBeInTheDocument();
  });

  it('spawning POSTs the form’s request verbatim to /api/traffic/spawn', async () => {
    const user = userEvent.setup();
    const { calls } = renderPanel(capabilities());
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /spawn tcas conflict/i })).toBeEnabled();
    });

    await user.click(screen.getByRole('button', { name: /spawn tcas conflict/i }));

    await waitFor(() => {
      expect(callsTo(calls, '/traffic/spawn')).toHaveLength(1);
    });
    const spawn = callsTo(calls, '/traffic/spawn')[0]!;
    expect(spawn.method).toBe('POST');
    expect(spawn.body).toEqual({
      type: 'tcas_conflict',
      severity: 'head_on_ra',
      relative_bearing_deg: 180,
      miss_side: 'left',
      vertical_offset: 'above',
      closure_ias_kt: null,
      kind: 'aircraft',
      callsign: 'TFC01',
    });
  });

  it('despawn DELETEs that row’s traffic_id', async () => {
    const user = userEvent.setup();
    const { calls } = renderPanel(capabilities(), {
      contacts: [contact({ traffic_id: 'bbb', callsign: 'GND01' })],
      connected: true,
    });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Despawn GND01' })).toBeEnabled();
    });

    await user.click(screen.getByRole('button', { name: 'Despawn GND01' }));

    await waitFor(() => {
      expect(callsTo(calls, '/traffic/bbb')).toHaveLength(1);
    });
    expect(callsTo(calls, '/traffic/bbb')[0]!.method).toBe('DELETE');
  });

  it('CLEAR ALL POSTs /api/traffic/clear exactly once', async () => {
    const user = userEvent.setup();
    const { calls } = renderPanel(capabilities(), {
      contacts: [contact()],
      connected: true,
    });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /clear all/i })).toBeEnabled();
    });

    await user.click(screen.getByRole('button', { name: /clear all/i }));

    await waitFor(() => {
      expect(callsTo(calls, '/traffic/clear')).toHaveLength(1);
    });
    expect(callsTo(calls, '/traffic/clear')[0]!.method).toBe('POST');
  });

  it('surfaces the server’s own sentence when a spawn is refused at capacity', async () => {
    const user = userEvent.setup();
    renderPanel(
      capabilities(),
      {},
      {
        spawn: {
          status: 409,
          detail: "'fake' is at capacity: 19 of 19 traffic slots in use.",
        },
      },
    );
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /spawn tcas conflict/i })).toBeEnabled();
    });

    await user.click(screen.getByRole('button', { name: /spawn tcas conflict/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      "'fake' is at capacity: 19 of 19 traffic slots in use.",
    );
  });
});
