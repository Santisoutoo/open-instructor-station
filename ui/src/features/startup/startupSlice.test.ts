import { describe, expect, it } from 'vitest';
import startupReducer, {
  MIN_QUERY_LENGTH,
  initialStartupState,
  queryTyped,
  rememberedAirportLoaded,
  resolveFailed,
  resolveRequested,
  resolveSucceeded,
  type StartupState,
} from './startupSlice';

describe('startupSlice — queryTyped', () => {
  it.each([
    ['', 'idle'],
    ['L', 'idle'],
    ['LE', 'searching'],
    ['LEMD', 'searching'],
  ] as const)('%j (below/at/above MIN_QUERY_LENGTH) -> %s', (text, expectedStatus) => {
    const state = startupReducer(initialStartupState, queryTyped(text));
    expect(state.status).toBe(expectedStatus);
    expect(state.query).toBe(text);
  });

  it('clears errorMessage and leaves the error state', () => {
    const errored: StartupState = {
      ...initialStartupState,
      status: 'error',
      errorMessage: 'No airport found for "ZZZZ".',
    };
    const state = startupReducer(errored, queryTyped('LEMD'));
    expect(state.status).toBe('searching');
    expect(state.errorMessage).toBeNull();
  });
});

describe('startupSlice — resolveRequested', () => {
  it.each(['idle', 'searching', 'error'] as const)(
    'from %s: sets resolving, uppercases the ICAO, clears errorMessage',
    (fromStatus) => {
      const starting: StartupState = {
        ...initialStartupState,
        status: fromStatus,
        errorMessage: fromStatus === 'error' ? 'boom' : null,
      };
      const state = startupReducer(starting, resolveRequested('lemd'));
      expect(state.status).toBe('resolving');
      expect(state.icao).toBe('LEMD');
      expect(state.errorMessage).toBeNull();
    },
  );
});

describe('startupSlice — resolveSucceeded / resolveFailed', () => {
  it('resolveSucceeded sets ready, icao and name', () => {
    const resolving: StartupState = { ...initialStartupState, status: 'resolving', icao: 'LEMD' };
    const state = startupReducer(
      resolving,
      resolveSucceeded({ icao: 'LEMD', name: 'Adolfo Suárez Madrid–Barajas' }),
    );
    expect(state.status).toBe('ready');
    expect(state.icao).toBe('LEMD');
    expect(state.name).toBe('Adolfo Suárez Madrid–Barajas');
    expect(state.errorMessage).toBeNull();
  });

  it('resolveFailed sets error and the message, leaving icao as the last attempted value', () => {
    const resolving: StartupState = { ...initialStartupState, status: 'resolving', icao: 'ZZZZ' };
    const state = startupReducer(
      resolving,
      resolveFailed('No airport found for "ZZZZ". Check the ICAO code and try again.'),
    );
    expect(state.status).toBe('error');
    expect(state.errorMessage).toBe(
      'No airport found for "ZZZZ". Check the ICAO code and try again.',
    );
    expect(state.icao).toBe('ZZZZ');
  });
});

describe('startupSlice — rememberedAirportLoaded', () => {
  it('pre-fills query and name, lands in searching, never ready', () => {
    const state = startupReducer(
      initialStartupState,
      rememberedAirportLoaded({ icao: 'LEMD', name: 'Adolfo Suárez Madrid–Barajas' }),
    );
    expect(state.status).toBe('searching');
    expect(state.query).toBe('LEMD');
    expect(state.name).toBe('Adolfo Suárez Madrid–Barajas');
    expect(state.status).not.toBe('ready');
  });

  it('an ICAO shorter than MIN_QUERY_LENGTH lands in idle instead', () => {
    // Defensive only — a real ICAO is always >= MIN_QUERY_LENGTH characters.
    const state = startupReducer(
      initialStartupState,
      rememberedAirportLoaded({ icao: 'L', name: null }),
    );
    expect(state.status).toBe('idle');
    expect(MIN_QUERY_LENGTH).toBeGreaterThan(1);
  });
});
