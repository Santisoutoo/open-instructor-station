/**
 * The panel-level behaviour: the gate fails closed against real capability answers
 * (Phase 3 exit criterion 3's UI half — with the bridge absent, traffic controls are
 * disabled with a stated reason), and once open, the segmented picker swaps the four
 * spawn forms while the WS-fed slice renders the contact list.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Capabilities } from '../../api/models';
import { setupStore } from '../../store';
import { initialTrafficState, type TrafficState } from './trafficSlice';
import { TrafficPanel } from './TrafficPanel';
import type { TrafficContact } from './types.mock';
import { stubApi } from './testApi';

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

function renderPanel(
  caps: Capabilities,
  traffic: Partial<TrafficState> = {},
): ReturnType<typeof setupStore> {
  stubApi({ '/capabilities': { body: caps } });
  const store = setupStore({ traffic: { ...initialTrafficState, ...traffic } });
  render(
    <Provider store={store}>
      <TrafficPanel />
    </Provider>,
  );
  return store;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('TrafficPanel', () => {
  it('fails closed with the stated reason when the adapter lacks can_spawn_traffic', async () => {
    renderPanel(capabilities({ can_spawn_traffic: false }));

    expect(
      await screen.findByText(/does not declare can_spawn_traffic/),
    ).toBeInTheDocument();
    // Closed means closed: no spawn surface, no contact list, not merely dimmed.
    expect(screen.queryByRole('button', { name: /spawn/i })).toBeNull();
    expect(screen.queryByText('Active traffic')).toBeNull();
  });

  it('opens on can_spawn_traffic: contact list on top, TCAS form by default', async () => {
    renderPanel(capabilities());

    expect(await screen.findByText('Active traffic')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /spawn tcas conflict/i }),
    ).toBeInTheDocument();
  });

  it('the segmented picker swaps the active form and remembers it in the slice', async () => {
    const user = userEvent.setup();
    const store = renderPanel(capabilities());
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
    renderPanel(capabilities(), {
      contacts: [contact()],
      connected: true,
    });

    expect(await screen.findByText('SEQ01')).toBeInTheDocument();
    expect(screen.getByText('3,184 ft · 120 kt')).toBeInTheDocument();
  });
});
