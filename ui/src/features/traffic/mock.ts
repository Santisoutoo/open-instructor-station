/**
 * Mock fixtures for the AI Traffic manager.
 *
 * Everything the fake bridge "serves": the availability manifest, the spawn templates
 * shown on the grid, and the deterministic entity builder behind the spawn mutation.
 * Dies at backend integration — the real geometry is computed in `core/` and delivered
 * by the bridge (feature-spec §13).
 */

import { bearingDeg, normalizeDeg, offset } from './geo';
import type {
  LatLon,
  OwnShipRef,
  SpawnRequest,
  SpawnTemplateId,
  TrafficEntity,
  TrafficKind,
  TrafficManifest,
} from './types.mock';

/**
 * Flip to `false` in code to demo the gated state: the manifest then reports the bridge
 * as absent and the whole panel disables with the reason shown, exactly as it will when
 * a real X-Plane runs without the XPPython3 bridge plugin.
 */
export const TRAFFIC_AVAILABLE = true;

export function trafficManifestFixture(): TrafficManifest {
  if (!TRAFFIC_AVAILABLE) {
    return {
      available: false,
      reason:
        'The AI traffic bridge plugin is not connected. Traffic needs the in-sim ' +
        'bridge; everything else works without it.',
      bridge: 'not connected',
    };
  }
  return { available: true, reason: null, bridge: 'connected (demo)' };
}

/**
 * Where traffic spawns before the first telemetry frame: a field NE of Madrid, matching
 * the demo feed's neighbourhood, at a plausible field elevation.
 */
export const FALLBACK_OWN: OwnShipRef = {
  position: { lat: 40.46, lon: -3.57 },
  altitude_ft: 2000,
  heading_deg: 0,
};

// ------------------------------------------------------------------ templates

export interface SpawnTemplate {
  id: SpawnTemplateId;
  label: string;
  /** One line under the label on the card. */
  description: string;
  /** Kinds honour the count/distance parameters; scenarios fix their own shape. */
  group: 'kind' | 'scenario';
}

export const SPAWN_TEMPLATES: readonly SpawnTemplate[] = [
  {
    id: 'aircraft',
    label: 'Aircraft',
    description: 'Airliners at the set distance, converging on you',
    group: 'kind',
  },
  {
    id: 'ground-vehicle',
    label: 'Ground vehicle',
    description: 'Follow-me trucks working the apron nearby',
    group: 'kind',
  },
  {
    id: 'birds',
    label: 'Birds',
    description: 'Flocks crossing ahead, just above your level',
    group: 'kind',
  },
  {
    id: 'tcas-conflict',
    label: 'TCAS conflict',
    description: 'Converging airliner 10 NM out, co-altitude and closing',
    group: 'scenario',
  },
  {
    id: 'runway-incursion',
    label: 'Runway incursion',
    description: 'A ground vehicle crossing the runway ahead of you',
    group: 'scenario',
  },
  {
    id: 'taxi-traffic',
    label: 'Taxi traffic',
    description: 'Two aircraft taxiing near your position',
    group: 'scenario',
  },
  {
    id: 'approach-traffic',
    label: 'Approach traffic',
    description: 'Two aircraft in sequence on final, 3 NM spacing',
    group: 'scenario',
  },
];

// ----------------------------------------------------------------- identities

/**
 * Deterministic module counter: no Math.random anywhere, so a demo replays the same
 * ids and callsigns every time, and tests never flake on identity.
 */
let sequence = 0;

/** Test-only: rewind the counter so identity assertions are stable per test. */
export function resetTrafficSequence(): void {
  sequence = 0;
}

const AIRLINE_PREFIXES = ['IBE', 'VLG', 'RYR', 'AEA', 'DLH', 'BAW'] as const;

function nextIdentity(kind: TrafficKind): { id: string; callsign: string } {
  sequence += 1;
  const id = `TFC-${String(sequence).padStart(3, '0')}`;
  switch (kind) {
    case 'aircraft': {
      const prefix = AIRLINE_PREFIXES[sequence % AIRLINE_PREFIXES.length] ?? 'IBE';
      return { id, callsign: `${prefix}${1000 + ((sequence * 37) % 9000)}` };
    }
    case 'ground vehicle':
      return { id, callsign: `FOL${10 + (sequence % 90)}` };
    case 'birds':
      return { id, callsign: `FLK${10 + (sequence % 90)}` };
  }
}

// -------------------------------------------------------------------- builder

interface EntitySpec {
  kind: TrafficKind;
  position: LatLon;
  altitude_ft: number;
  heading_deg: number;
  speed_kt: number;
  track: LatLon[];
}

function build(spec: EntitySpec): TrafficEntity {
  return { ...nextIdentity(spec.kind), ...spec };
}

/** An airliner at `distanceNm`/`bearing` from own, flying to own's position and past it. */
function convergingAircraft(
  own: OwnShipRef,
  bearingFromOwn: number,
  distanceNmOut: number,
  altitudeFt: number,
  speedKt: number,
): TrafficEntity {
  const position = offset(own.position, bearingFromOwn, distanceNmOut);
  const inbound = bearingDeg(position, own.position);
  return build({
    kind: 'aircraft',
    position,
    altitude_ft: altitudeFt,
    heading_deg: inbound,
    speed_kt: speedKt,
    track: [own.position, offset(own.position, inbound, 5)],
  });
}

/**
 * Resolve a spawn request into concrete entities.
 *
 * All geometry is relative to `own` — the student's aircraft when telemetry exists,
 * the fallback field otherwise. Deterministic on purpose: same request, same shape.
 */
export function buildSpawn(request: SpawnRequest): TrafficEntity[] {
  const own = request.own ?? FALLBACK_OWN;
  const heading = own.heading_deg;

  switch (request.template) {
    case 'aircraft': {
      // Spread around the nose so a multi-spawn is a picture, not a stack.
      const bearings = [30, -30, 150, -150];
      return Array.from({ length: request.count }, (_unused, i) =>
        convergingAircraft(
          own,
          normalizeDeg(heading + (bearings[i % bearings.length] ?? 0)),
          request.distanceNm,
          own.altitude_ft + 1000 * (i + 1),
          250,
        ),
      );
    }

    case 'ground-vehicle':
      return Array.from({ length: request.count }, (_unused, i) => {
        const position = offset(own.position, normalizeDeg(heading + 90 + 60 * i), 0.3);
        const along = normalizeDeg(heading + 180);
        return build({
          kind: 'ground vehicle',
          position,
          altitude_ft: own.altitude_ft,
          heading_deg: along,
          speed_kt: 15,
          track: [offset(position, along, 1)],
        });
      });

    case 'birds':
      return Array.from({ length: request.count }, (_unused, i) => {
        // Crossing left to right ahead, slightly above — the classic climb-out scare.
        const position = offset(
          own.position,
          normalizeDeg(heading - 45),
          Math.max(1, request.distanceNm / 4) + i * 0.4,
        );
        const crossing = normalizeDeg(heading + 90);
        return build({
          kind: 'birds',
          position,
          altitude_ft: own.altitude_ft + 300,
          heading_deg: crossing,
          speed_kt: 25,
          track: [offset(position, crossing, 3)],
        });
      });

    case 'tcas-conflict':
      // One airliner ~10 NM out on a converging bearing, co-altitude, closing fast —
      // geometry that ends in a resolution advisory, not a fly-by.
      return [convergingAircraft(own, normalizeDeg(heading + 30), 10, own.altitude_ft, 280)];

    case 'runway-incursion': {
      // A follow-me entering the runway 0.8 NM ahead: crosses the extended centreline.
      const entryPoint = offset(own.position, heading, 0.8);
      const position = offset(entryPoint, normalizeDeg(heading + 90), 0.15);
      const crossing = normalizeDeg(heading - 90);
      return [
        build({
          kind: 'ground vehicle',
          position,
          altitude_ft: own.altitude_ft,
          heading_deg: crossing,
          speed_kt: 20,
          track: [entryPoint, offset(entryPoint, crossing, 0.15)],
        }),
      ];
    }

    case 'taxi-traffic':
      // Two aircraft taxiing nearby, each with a corner in its track.
      return [0, 1].map((i) => {
        const side = i === 0 ? 60 : -120;
        const position = offset(own.position, normalizeDeg(heading + side), 0.4);
        const firstLeg = normalizeDeg(heading + 180);
        const corner = offset(position, firstLeg, 0.5);
        return build({
          kind: 'aircraft',
          position,
          altitude_ft: own.altitude_ft,
          heading_deg: firstLeg,
          speed_kt: 12,
          track: [corner, offset(corner, normalizeDeg(firstLeg + 90), 0.5)],
        });
      });

    case 'approach-traffic':
      // Two in sequence on final to own's position, 3 NM spacing, on a 3° slope
      // (~318 ft per NM), both tracking the extended centreline inbound.
      return [0, 1].map((i) => {
        const finalNm = request.distanceNm + 3 * i;
        const position = offset(own.position, normalizeDeg(heading + 180), finalNm);
        return build({
          kind: 'aircraft',
          position,
          altitude_ft: own.altitude_ft + Math.round(318 * finalNm),
          heading_deg: heading,
          speed_kt: 140 + 10 * i,
          track: [own.position],
        });
      });
  }
}
