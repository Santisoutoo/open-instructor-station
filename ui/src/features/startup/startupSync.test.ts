/**
 * `initStartupSync`'s own tests — the boot-time read and the write-on-`ready` half of the
 * gate that `AirportGate.test.tsx` does not exercise: that file preloads `startup` state
 * directly (mirroring what this hook would have dispatched), which is the right way to test
 * the gate's rendering, but never runs `initStartupSync` itself. This file is the one that
 * actually calls it.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setupStore } from '../../store';
import { resolveSucceeded } from './startupSlice';
import { initStartupSync, STARTUP_AIRPORT_STORAGE_KEY } from './startupSync';

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('initStartupSync — boot read', () => {
  it('a valid remembered airport pre-fills query/name and lands in searching', () => {
    localStorage.setItem(
      STARTUP_AIRPORT_STORAGE_KEY,
      JSON.stringify({ icao: 'LEMD', name: 'Adolfo Suárez Madrid–Barajas' }),
    );
    const store = setupStore();
    initStartupSync(store);

    const state = store.getState().startup;
    expect(state.status).toBe('searching');
    expect(state.query).toBe('LEMD');
    expect(state.name).toBe('Adolfo Suárez Madrid–Barajas');
    expect(state.icao).toBeNull();
  });

  it('no stored value leaves the initial state untouched', () => {
    const store = setupStore();
    initStartupSync(store);

    expect(store.getState().startup.status).toBe('idle');
  });

  it.each([
    ['corrupt JSON', '{not json'],
    ['wrong shape (icao not a string)', JSON.stringify({ icao: 123, name: null })],
    ['missing icao entirely', JSON.stringify({ name: 'Nowhere' })],
  ])('%s degrades to the initial state, no throw', (_label, raw) => {
    localStorage.setItem(STARTUP_AIRPORT_STORAGE_KEY, raw);
    const store = setupStore();

    expect(() => {
      initStartupSync(store);
    }).not.toThrow();
    expect(store.getState().startup.status).toBe('idle');
  });

  it('a storage read that throws (private mode) degrades to an empty gate, no throw', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError: storage disabled');
    });
    const store = setupStore();

    expect(() => {
      initStartupSync(store);
    }).not.toThrow();
    expect(store.getState().startup.status).toBe('idle');
  });
});

describe('initStartupSync — write on ready', () => {
  it('resolveSucceeded writes the icao/name shape to storage', () => {
    const store = setupStore();
    initStartupSync(store);

    store.dispatch(resolveSucceeded({ icao: 'LEMD', name: 'Adolfo Suárez Madrid–Barajas' }));

    expect(localStorage.getItem(STARTUP_AIRPORT_STORAGE_KEY)).toBe(
      JSON.stringify({ icao: 'LEMD', name: 'Adolfo Suárez Madrid–Barajas' }),
    );
  });

  it('a second resolveSucceeded while already ready does not rewrite storage', () => {
    const store = setupStore();
    initStartupSync(store);

    store.dispatch(resolveSucceeded({ icao: 'LEMD', name: 'Adolfo Suárez Madrid–Barajas' }));
    localStorage.removeItem(STARTUP_AIRPORT_STORAGE_KEY);
    // Still "ready" going into this dispatch — the `last !== 'ready'` guard must skip it.
    store.dispatch(resolveSucceeded({ icao: 'LEMD', name: 'Adolfo Suárez Madrid–Barajas' }));

    expect(localStorage.getItem(STARTUP_AIRPORT_STORAGE_KEY)).toBeNull();
  });

  it('a storage write that throws (private mode) does not crash the dispatch', () => {
    const store = setupStore();
    initStartupSync(store);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('SecurityError: storage disabled');
    });

    expect(() => {
      store.dispatch(resolveSucceeded({ icao: 'LEMD', name: 'Adolfo Suárez Madrid–Barajas' }));
    }).not.toThrow();
    expect(store.getState().startup.status).toBe('ready');
  });
});
