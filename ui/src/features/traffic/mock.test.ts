/**
 * The mock bridge fixtures. Seven cards is the spec surface (three kinds plus four
 * scenario shapes, feature-spec §13); the builder's invariants — unique identities,
 * determinism, geometry relative to own — are what the panel and the map both lean on.
 */

import { beforeEach, describe, expect, it } from 'vitest';
import { bearingDeg, distanceNm, normalizeDeg } from './geo';
import {
  FALLBACK_OWN,
  SPAWN_TEMPLATES,
  buildSpawn,
  resetTrafficSequence,
  trafficManifestFixture,
} from './mock';
import type { OwnShipRef, SpawnRequest, SpawnTemplateId } from './types.mock';

const OWN: OwnShipRef = {
  position: { lat: 40.0, lon: -3.0 },
  altitude_ft: 3000,
  heading_deg: 90,
};

function request(
  template: SpawnTemplateId,
  overrides: Partial<SpawnRequest> = {},
): SpawnRequest {
  return { template, count: 1, distanceNm: 8, own: OWN, ...overrides };
}

beforeEach(() => {
  resetTrafficSequence();
});

describe('trafficManifestFixture', () => {
  it('reports the demo bridge as connected, with no dangling reason', () => {
    expect(trafficManifestFixture()).toEqual({
      available: true,
      reason: null,
      bridge: 'connected (demo)',
    });
  });
});

describe('SPAWN_TEMPLATES', () => {
  it('ships the seven cards: three kinds and four scenarios', () => {
    expect(SPAWN_TEMPLATES).toHaveLength(7);
    expect(SPAWN_TEMPLATES.filter((t) => t.group === 'kind')).toHaveLength(3);
    expect(SPAWN_TEMPLATES.filter((t) => t.group === 'scenario')).toHaveLength(4);
  });

  it('has a unique id per card', () => {
    const ids = SPAWN_TEMPLATES.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('gives every card a label and a one-line description', () => {
    for (const template of SPAWN_TEMPLATES) {
      expect(template.label.length, template.id).toBeGreaterThan(0);
      expect(template.description.length, template.id).toBeGreaterThan(0);
    }
  });
});

describe('buildSpawn', () => {
  it('is deterministic: the same request replays the same entities', () => {
    const first = buildSpawn(request('aircraft', { count: 3 }));
    resetTrafficSequence();
    const second = buildSpawn(request('aircraft', { count: 3 }));

    expect(second).toEqual(first);
  });

  it('never reuses an id or a callsign across one session', () => {
    const spawned = [
      ...buildSpawn(request('aircraft', { count: 4 })),
      ...buildSpawn(request('ground-vehicle', { count: 4 })),
      ...buildSpawn(request('birds', { count: 4 })),
    ];

    expect(new Set(spawned.map((e) => e.id)).size).toBe(spawned.length);
    expect(new Set(spawned.map((e) => e.callsign)).size).toBe(spawned.length);
  });

  it.each(['aircraft', 'ground-vehicle', 'birds'] as const)(
    'honours the count parameter for the %s kind',
    (template) => {
      expect(buildSpawn(request(template, { count: 1 }))).toHaveLength(1);
      resetTrafficSequence();
      expect(buildSpawn(request(template, { count: 4 }))).toHaveLength(4);
    },
  );

  it('spawns aircraft at the requested distance, converging on own', () => {
    const spawned = buildSpawn(request('aircraft', { count: 2, distanceNm: 12 }));

    for (const aircraft of spawned) {
      expect(distanceNm(OWN.position, aircraft.position)).toBeCloseTo(12, 1);
      // Heading points back at own's position, so the picture converges.
      const inbound = bearingDeg(aircraft.position, OWN.position);
      const diff = Math.abs(normalizeDeg(aircraft.heading_deg - inbound));
      expect(Math.min(diff, 360 - diff)).toBeLessThan(0.5);
    }
  });

  it('falls back to the demo field when there is no telemetry yet', () => {
    const spawned = buildSpawn(request('tcas-conflict', { own: null }));

    expect(spawned).toHaveLength(1);
    expect(distanceNm(FALLBACK_OWN.position, spawned[0]?.position ?? OWN.position))
      .toBeCloseTo(10, 1);
  });

  it('builds the TCAS conflict co-altitude, 10 NM out and closing fast', () => {
    const spawned = buildSpawn(request('tcas-conflict'));
    const threat = spawned[0];

    expect(spawned).toHaveLength(1);
    expect(threat?.kind).toBe('aircraft');
    expect(threat?.altitude_ft).toBe(OWN.altitude_ft);
    expect(threat?.speed_kt).toBe(280);
    expect(distanceNm(OWN.position, threat?.position ?? OWN.position)).toBeCloseTo(
      10,
      1,
    );
  });

  it('puts the runway incursion vehicle on the ground, under a mile ahead', () => {
    const spawned = buildSpawn(request('runway-incursion'));
    const vehicle = spawned[0];

    expect(spawned).toHaveLength(1);
    expect(vehicle?.kind).toBe('ground vehicle');
    expect(vehicle?.altitude_ft).toBe(OWN.altitude_ft);
    expect(distanceNm(OWN.position, vehicle?.position ?? OWN.position)).toBeLessThan(1);
  });

  it('taxi traffic is two aircraft at field elevation with a corner to turn', () => {
    const spawned = buildSpawn(request('taxi-traffic'));

    expect(spawned).toHaveLength(2);
    for (const aircraft of spawned) {
      expect(aircraft.kind).toBe('aircraft');
      expect(aircraft.altitude_ft).toBe(OWN.altitude_ft);
      expect(aircraft.track.length).toBeGreaterThanOrEqual(2);
    }
  });

  it('sequences approach traffic 3 NM apart on the extended centreline', () => {
    const spawned = buildSpawn(request('approach-traffic', { distanceNm: 6 }));
    const ranges = spawned.map((e) => distanceNm(OWN.position, e.position));

    expect(spawned).toHaveLength(2);
    expect(ranges[0]).toBeCloseTo(6, 1);
    expect(ranges[1]).toBeCloseTo(9, 1);
    for (const aircraft of spawned) {
      // Both fly own's heading — inbound along the final approach track.
      expect(aircraft.heading_deg).toBe(OWN.heading_deg);
      // On a 3° slope the trailer is higher than the leader.
      expect(aircraft.altitude_ft).toBeGreaterThan(OWN.altitude_ft);
    }
  });
});
