/**
 * The map's query builders, with the one risk instructor-map.md §10.7 flags pinned
 * hard: `kinds` must reach FastAPI as REPEATED query keys (`kinds=vor&kinds=ndb`),
 * never a comma-joined string or a JSON array. Asserted both on the pure helper and
 * on the URL the store actually fetches, `fetch` stubbed the same way the Position
 * panel's tests stub it.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { setupStore } from '../../store';
import { stubApi } from '../position/testApi';
import { mapApi, toRepeatedParams } from './mapApi';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('toRepeatedParams', () => {
  it('serializes an array as one key per element, in order', () => {
    expect(
      toRepeatedParams({ lat: 40.5, lon: -3.6, radius_nm: 60, kinds: ['vor', 'ndb'] }),
    ).toBe('lat=40.5&lon=-3.6&radius_nm=60&kinds=vor&kinds=ndb');
  });

  it('drops undefined values instead of writing key=undefined', () => {
    expect(toRepeatedParams({ lat: 1, kinds: undefined })).toBe('lat=1');
  });
});

describe('mapApi', () => {
  it('requests navaids with repeated kinds keys, never a comma-joined value', async () => {
    const { calls } = stubApi({ 'navdata/navaids': { body: [] } });
    const store = setupStore();

    await store.dispatch(
      mapApi.endpoints.getNavaidsNear.initiate({
        lat: 40.5,
        lon: -3.6,
        radiusNm: 60,
        kinds: ['vor', 'ndb'],
      }),
    );

    const url = calls[0]?.url ?? '';
    expect(url).toContain('kinds=vor&kinds=ndb');
    expect(url).not.toContain('vor%2Cndb');
    expect(url).not.toContain('vor,ndb');
  });

  it('sends the measure request as the four scalar params the endpoint declares', async () => {
    const { calls } = stubApi({
      'geodesy/measure': { body: { distance_nm: 25, initial_bearing_true_deg: 137 } },
    });
    const store = setupStore();

    await store.dispatch(
      mapApi.endpoints.measureGeodesic.initiate({
        a: { lat: 40.4168, lon: -3.7038 },
        b: { lat: 40.1, lon: -3.4 },
      }),
    );

    const url = calls[0]?.url ?? '';
    expect(url).toContain('/api/geodesy/measure?');
    expect(url).toContain('lat1=40.4168');
    expect(url).toContain('lon1=-3.7038');
    expect(url).toContain('lat2=40.1');
    expect(url).toContain('lon2=-3.4');
  });
});
