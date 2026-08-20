import { describe, expect, it } from 'vitest';
import type { AircraftSetup } from '../../api/models';
import { applyRows, type ApplyRowInputs } from './applyRows';
import { mergedSetup } from './setup';
import { PREVIEW } from './testFixtures';

function rows(overrides: AircraftSetup = {}, preview = PREVIEW) {
  const inputs: ApplyRowInputs = {
    preview,
    merged: mergedSetup(preview, overrides),
    overridden: new Set(Object.keys(overrides) as (keyof AircraftSetup)[]),
  };
  return applyRows(inputs);
}

function valueOf(list: readonly { label: string; value: string }[], label: string) {
  return list.find((row) => row.label === label)?.value;
}

function tagOf(list: readonly { label: string; tag: string }[], label: string) {
  return list.find((row) => row.label === label)?.tag;
}

describe('applyRows', () => {
  it('returns the 7 rows in order', () => {
    expect(rows().map((row) => row.label)).toEqual([
      'Start position',
      'Altitude',
      'Heading',
      'IAS',
      'Landing gear',
      'Flaps',
      'Nav radios',
    ]);
  });

  it('shows the server’s own label, altitude, heading and speed', () => {
    const list = rows();
    expect(valueOf(list, 'Start position')).toBe('LFMN 04R 3 NM final');
    expect(valueOf(list, 'Altitude')).toBe('968 ft');
    expect(valueOf(list, 'Heading')).toBe('040°T');
    expect(valueOf(list, 'IAS')).toBe('121 kt');
    expect(valueOf(list, 'Landing gear')).toBe('down');
    expect(valueOf(list, 'Flaps')).toBe('50 %');
    expect(valueOf(list, 'Nav radios')).toBe('ILS 110.70 · CRS 040');
  });

  it('tags everything the placement resolved as computed', () => {
    const list = rows();
    expect(tagOf(list, 'Start position')).toBe('navdata');
    for (const label of ['Altitude', 'Heading', 'IAS', 'Landing gear', 'Flaps']) {
      expect(tagOf(list, label)).toBe('computed');
    }
  });

  it('flips Altitude from computed to overridden, in caution colour', () => {
    const list = rows({ altitude_ft: 5500 });
    const row = list.find((entry) => entry.label === 'Altitude');
    expect(row?.value).toBe('5,500 ft');
    expect(row?.tag).toBe('overridden');
    expect(row?.colour).toBe('caution');
  });

  it('flips IAS and gear to overridden when the instructor edits them', () => {
    const list = rows({ ias_kt: 90, gear_down: false });
    expect(tagOf(list, 'IAS')).toBe('overridden');
    expect(valueOf(list, 'IAS')).toBe('90 kt');
    const gear = list.find((entry) => entry.label === 'Landing gear');
    expect(gear?.value).toBe('up');
    expect(gear?.colour).toBe('caution');
    expect(gear?.tag).toBe('overridden');
  });

  it('says nothing is resolved yet before the preview answers', () => {
    const list = applyRows({ preview: undefined, merged: {}, overridden: new Set() });
    expect(valueOf(list, 'Start position')).toBe('not resolved');
    expect(valueOf(list, 'Altitude')).toBe('not resolved');
    expect(valueOf(list, 'Heading')).toBe('not resolved');
    expect(valueOf(list, 'IAS')).toBe('not resolved');
    expect(valueOf(list, 'Landing gear')).toBe('unchanged');
    expect(valueOf(list, 'Flaps')).toBe('unchanged');
  });

  it('says "not sent" when the merged setup tunes no radio', () => {
    const bare = {
      ...PREVIEW,
      setup: {
        ...PREVIEW.setup,
        nav1_freq_khz: null,
        ils_freq_khz: null,
        obs1_deg: null,
      },
    };
    const row = rows({}, bare).find((entry) => entry.label === 'Nav radios');
    expect(row?.value).toBe('not sent');
    expect(row?.tag).toBe('unavailable');
  });

  it('credits navdata when the frequency came from the instructor’s switch', () => {
    const bare = {
      ...PREVIEW,
      setup: {
        ...PREVIEW.setup,
        nav1_freq_khz: null,
        ils_freq_khz: null,
        obs1_deg: null,
      },
    };
    const row = rows({ nav1_freq_khz: 110700, obs1_deg: 40 }, bare).find(
      (entry) => entry.label === 'Nav radios',
    );
    expect(row?.value).toBe('ILS 110.70 · CRS 040');
    expect(row?.tag).toBe('from navdata');
  });
});
