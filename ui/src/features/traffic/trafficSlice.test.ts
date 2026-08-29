/**
 * The traffic slice mirrors the `/ws/traffic` stream (design §7.2): every frame is the
 * full picture and replaces the contact list wholesale — the stream never sends diffs,
 * so the slice must never merge. Disconnection keeps the last frame (marked stale via
 * `connected`) rather than pretending an empty sky.
 */

import { describe, expect, it } from 'vitest';
import reducer, {
  initialTrafficState,
  shapeSelected,
  trafficFrameReceived,
  trafficStreamDisconnected,
} from './trafficSlice';
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

describe('trafficSlice', () => {
  it('starts empty, disconnected, with the TCAS form selected', () => {
    expect(initialTrafficState).toEqual({
      contacts: [],
      connected: false,
      selectedShape: 'tcas_conflict',
    });
  });

  it('replaces the contacts wholesale on every frame — never merges', () => {
    const first = reducer(
      initialTrafficState,
      trafficFrameReceived([contact({ traffic_id: 'aaa' }), contact({ traffic_id: 'bbb' })]),
    );
    // The next frame no longer carries 'aaa': it must be gone, not merged in.
    const second = reducer(
      first,
      trafficFrameReceived([contact({ traffic_id: 'bbb', callsign: 'SEQ02' })]),
    );

    expect(second.contacts.map((c) => c.traffic_id)).toEqual(['bbb']);
    expect(second.contacts[0]?.callsign).toBe('SEQ02');
  });

  it('an empty frame empties the list — "no traffic" is an honest answer', () => {
    const populated = reducer(initialTrafficState, trafficFrameReceived([contact()]));
    const emptied = reducer(populated, trafficFrameReceived([]));

    expect(emptied.contacts).toEqual([]);
  });

  it('a frame marks the stream connected', () => {
    const state = reducer(initialTrafficState, trafficFrameReceived([]));

    expect(state.connected).toBe(true);
  });

  it('disconnection keeps the last frame but marks it stale', () => {
    const populated = reducer(initialTrafficState, trafficFrameReceived([contact()]));
    const dropped = reducer(populated, trafficStreamDisconnected());

    expect(dropped.connected).toBe(false);
    expect(dropped.contacts).toHaveLength(1);
  });

  it('remembers which spawn form is open — client-only state', () => {
    const state = reducer(initialTrafficState, shapeSelected('runway_incursion'));

    expect(state.selectedShape).toBe('runway_incursion');
    expect(state.contacts).toEqual([]);
  });
});
