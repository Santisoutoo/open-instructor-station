/**
 * The contact list is the panel's despawn surface: CLEAR ALL emits exactly one
 * clear-all intent (no confirmation — the Failures posture), and each row's ✕ emits
 * the despawn intent with that row's `traffic_id`, never a neighbour's.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ContactList } from './ContactList';
import type { TrafficContact } from '../../api/models';

function contact(overrides: Partial<TrafficContact> = {}): TrafficContact {
  return {
    traffic_id: 'a3f9',
    kind: 'aircraft',
    scenario_shape: 'tcas_conflict',
    callsign: 'TFC01',
    label: 'TCAS conflict, head-on',
    latitude: 40.0,
    longitude: -3.0,
    altitude_ft: 10000,
    heading_deg: 270,
    ground_speed_kt: 250,
    vertical_speed_fpm: 0,
    on_ground: false,
    ...overrides,
  };
}

interface Overrides {
  contacts?: TrafficContact[];
  disabled?: boolean;
  connected?: boolean;
  capacity?: number | null;
}

function renderList(overrides: Overrides = {}) {
  const onDespawn = vi.fn();
  const onClearAll = vi.fn();
  render(
    <ContactList
      contacts={overrides.contacts ?? []}
      disabled={overrides.disabled ?? false}
      connected={overrides.connected ?? true}
      capacity={overrides.capacity ?? null}
      onDespawn={onDespawn}
      onClearAll={onClearAll}
    />,
  );
  return { onDespawn, onClearAll };
}

describe('ContactList', () => {
  it('says so when the sky is empty', () => {
    renderList();

    expect(screen.getByText('No active traffic.')).toBeInTheDocument();
  });

  it('shows callsign, altitude and speed per contact', () => {
    renderList({
      contacts: [contact({ callsign: 'SEQ01', altitude_ft: 3184.4, ground_speed_kt: 120 })],
    });

    expect(screen.getByText('SEQ01')).toBeInTheDocument();
    expect(screen.getByText('3,184 ft · 120 kt')).toBeInTheDocument();
  });

  it('CLEAR ALL emits exactly one clear-all intent, with no confirmation step', async () => {
    const user = userEvent.setup();
    const { onClearAll, onDespawn } = renderList({ contacts: [contact()] });

    await user.click(screen.getByRole('button', { name: /clear all/i }));

    expect(onClearAll).toHaveBeenCalledTimes(1);
    expect(onDespawn).not.toHaveBeenCalled();
  });

  it('CLEAR ALL is disabled with nothing to clear', () => {
    renderList();

    expect(screen.getByRole('button', { name: /clear all/i })).toBeDisabled();
  });

  it('each despawn button emits its own traffic_id, not a neighbour’s', async () => {
    const user = userEvent.setup();
    const { onDespawn } = renderList({
      contacts: [
        contact({ traffic_id: 'aaa', callsign: 'TFC01' }),
        contact({ traffic_id: 'bbb', callsign: 'GND01', kind: 'ground_vehicle' }),
      ],
    });

    await user.click(screen.getByRole('button', { name: 'Despawn GND01' }));

    expect(onDespawn).toHaveBeenCalledTimes(1);
    expect(onDespawn).toHaveBeenCalledWith('bbb');
  });

  it('disables every despawn control while the gate is closed', () => {
    renderList({ contacts: [contact()], disabled: true });

    expect(screen.getByRole('button', { name: /clear all/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Despawn TFC01' })).toBeDisabled();
  });

  it('labels a populated list stale when the stream is not delivering', () => {
    renderList({ contacts: [contact()], connected: false });

    expect(screen.getByText(/may be stale/i)).toBeInTheDocument();
  });

  it('does not cry stale over an empty list', () => {
    renderList({ connected: false });

    expect(screen.queryByText(/may be stale/i)).toBeNull();
  });

  it('shows the count against the adapter capacity when one is advertised', () => {
    renderList({ contacts: [contact()], capacity: 19 });

    expect(screen.getByText('1 / 19')).toBeInTheDocument();
  });

  it('shows a bare count when the adapter advertises no capacity', () => {
    renderList({ contacts: [contact()], capacity: null });

    expect(screen.getByText('1')).toBeInTheDocument();
  });
});
