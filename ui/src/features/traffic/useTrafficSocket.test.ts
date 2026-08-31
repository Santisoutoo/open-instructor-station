/**
 * `WS /ws/traffic` → the traffic slice.
 *
 * The socket is an untyped byte pipe, so the interesting cases are the dishonest ones: a
 * frame that is not JSON, and a frame that is JSON but is not a contact list. Both must
 * be dropped rather than rendered, and neither may tear the link down. The happy path is
 * checked too, but it is the cheap half.
 */

import { act, renderHook } from '@testing-library/react';
import { createElement, type ReactNode } from 'react';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { TrafficContact } from '../../api/models';
import { setupStore } from '../../store';
import { useTrafficSocket } from './useTrafficSocket';

type Listener = (event: unknown) => void;

/** The narrowest WebSocket that satisfies `api/liveSocket.ts`. */
class FakeSocket {
  static instances: FakeSocket[] = [];

  readonly listeners = new Map<string, Listener[]>();
  readonly url: string;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeSocket.instances.push(this);
  }

  addEventListener(type: string, handler: Listener): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), handler]);
  }

  close(): void {
    this.closed = true;
  }

  emit(type: string, event: unknown): void {
    act(() => {
      for (const handler of this.listeners.get(type) ?? []) {
        handler(event);
      }
    });
  }
}

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

function mount() {
  FakeSocket.instances = [];
  vi.stubGlobal('WebSocket', FakeSocket);
  const store = setupStore();
  renderHook(() => {
    useTrafficSocket();
  }, {
    wrapper: ({ children }: { children: ReactNode }) =>
      createElement(Provider, { store, children }),
  });
  const socket = FakeSocket.instances[0];
  if (socket === undefined) {
    throw new Error('the hook opened no socket');
  }
  return { store, socket };
}

/** One frame as the server sends it: a JSON string on a `message` event. */
function frame(payload: unknown): { data: string } {
  return { data: JSON.stringify(payload) };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('useTrafficSocket', () => {
  it('opens /ws/traffic on the page origin', () => {
    const { socket } = mount();

    expect(socket.url).toBe(`ws://${window.location.host}/ws/traffic`);
  });

  it('replaces the contact list wholesale on every frame', () => {
    const { store, socket } = mount();

    socket.emit('message', frame([contact({ traffic_id: 'aaa' })]));
    socket.emit('message', frame([contact({ traffic_id: 'bbb' })]));

    expect(store.getState().traffic.contacts.map((c) => c.traffic_id)).toEqual(['bbb']);
    expect(store.getState().traffic.connected).toBe(true);
  });

  it('an empty frame is a valid frame — no bridge means an empty sky, not an error', () => {
    const { store, socket } = mount();

    socket.emit('message', frame([]));

    expect(store.getState().traffic.contacts).toEqual([]);
    expect(store.getState().traffic.connected).toBe(true);
  });

  it('drops a frame that is not JSON without dropping the link', () => {
    const { store, socket } = mount();

    socket.emit('message', frame([contact()]));
    socket.emit('message', { data: 'not json at all' });

    expect(store.getState().traffic.contacts).toHaveLength(1);
    expect(socket.closed).toBe(false);
  });

  it('drops a frame that is JSON but is not a contact list', () => {
    const { store, socket } = mount();

    socket.emit('message', frame([contact()]));
    // An `AircraftState` frame on the wrong socket, and a contact missing its position.
    socket.emit('message', frame({ latitude: 40, longitude: -3 }));
    socket.emit('message', frame([{ traffic_id: 'x', callsign: 'Y' }]));

    expect(store.getState().traffic.contacts.map((c) => c.traffic_id)).toEqual(['a3f9']);
  });

  it('a close marks the stream stale but keeps the last honest picture', () => {
    const { store, socket } = mount();
    socket.emit('message', frame([contact()]));

    socket.emit('close', { code: 1006, reason: '' });

    expect(store.getState().traffic.connected).toBe(false);
    expect(store.getState().traffic.contacts).toHaveLength(1);
  });
});
