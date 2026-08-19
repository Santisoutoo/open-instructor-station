import { describe, expect, it } from 'vitest';
import { applyRows } from './applyRows';
import { initialPositionDesignState, type PositionDesignState } from './positionDesignSlice';

function state(overrides: Partial<PositionDesignState> = {}): PositionDesignState {
  return { ...initialPositionDesignState, ...overrides };
}

describe('applyRows', () => {
  it('returns the 7 rows in order for the default state', () => {
    const rows = applyRows(initialPositionDesignState);
    expect(rows.map((r) => r.label)).toEqual([
      'Start position',
      'Altitude',
      'Heading',
      'IAS',
      'Landing gear',
      'Flaps',
      'Nav radios',
    ]);
  });

  it('tags the default rows correctly', () => {
    const rows = applyRows(initialPositionDesignState);
    const tag = (label: string) => rows.find((r) => r.label === label)?.tag;
    expect(tag('Start position')).toBe('navdata');
    expect(tag('Altitude')).toBe('computed');
    expect(tag('Heading')).toBe('computed');
    expect(tag('IAS')).toBe('editable');
    expect(tag('Landing gear')).toBe('editable');
    expect(tag('Flaps')).toBe('editable');
    expect(tag('Nav radios')).toBe('from navdata');
  });

  it('resolves the start position name from the selected circuit marker', () => {
    const rows = applyRows(initialPositionDesignState);
    expect(rows[0]?.value).toBe('3 NM final');
  });

  it('flips Altitude from computed to overridden', () => {
    const overridden = applyRows(
      state({
        config: {
          ...initialPositionDesignState.config,
          altitudeOverride: true,
          altitudeOverrideFt: 5500,
        },
      }),
    );
    const row = overridden.find((r) => r.label === 'Altitude');
    expect(row?.tag).toBe('overridden');
    expect(row?.colour).toBe('caution');
    expect(row?.value).toBe('5,500 ft');
  });

  it('flips Nav radios from-navdata to unavailable when the runway has no ILS', () => {
    const rows = applyRows(state({ selectedRunway: '22L' }));
    const row = rows.find((r) => r.label === 'Nav radios');
    expect(row?.value).toBe('not available');
    expect(row?.tag).toBe('unavailable');
    expect(row?.colour).toBe('caution');
  });

  it('flips Nav radios to not sent when the toggle is off, even with ILS available', () => {
    const rows = applyRows(
      state({ send: { ...initialPositionDesignState.send, ilsFrequency: false } }),
    );
    const row = rows.find((r) => r.label === 'Nav radios');
    expect(row?.value).toBe('not sent');
    expect(row?.tag).toBe('from navdata');
  });

  it('shows the ILS frequency and course when available and sent', () => {
    const rows = applyRows(initialPositionDesignState);
    const row = rows.find((r) => r.label === 'Nav radios');
    expect(row?.value).toBe('ILS 110.70 · CRS 040');
  });

  it('flips Landing gear to caution when up', () => {
    const up = applyRows(initialPositionDesignState).find((r) => r.label === 'Landing gear');
    expect(up?.value).toBe('up');
    expect(up?.colour).toBe('caution');

    const down = applyRows(
      state({ config: { ...initialPositionDesignState.config, gearDown: true } }),
    ).find((r) => r.label === 'Landing gear');
    expect(down?.value).toBe('down');
    expect(down?.colour).toBe('default');
  });
});
