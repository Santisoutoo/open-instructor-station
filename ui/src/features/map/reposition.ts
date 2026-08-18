/**
 * What a staged map point resolves to before the instructor commits it.
 *
 * D6 of the map design, made concrete: a drag or click carries the aircraft's
 * *current* altitude, heading and IAS onto the new point by default, so sliding an
 * aircraft sideways on the map preserves the flight it is already in — "a dragged
 * aircraft arrives configured rather than dropped". Before any telemetry has arrived
 * at all there is nothing to carry: heading and IAS are `null` (which the server's
 * own placement pipeline already resolves sensibly) and the altitude is 0, a ground
 * point.
 *
 * Pure on purpose (D15): the decision lives here, unit-tested directly, not inside
 * an imperative MapLibre handler.
 */

import type { AircraftState, CoordinatePlacementRequest } from '../../api/models';
import type { LatLon } from './measure';

/** The coordinate placement a staged map point defaults to. */
export function defaultCoordinateRequest(
  point: LatLon,
  telemetry: AircraftState | null,
): CoordinatePlacementRequest {
  return {
    type: 'coordinate',
    position: {
      latitude: point.lat,
      longitude: point.lon,
      altitude_ft: telemetry?.altitude_ft ?? 0,
    },
    heading_deg: telemetry?.heading_deg ?? null,
    ias_kt: telemetry?.ias_kt ?? null,
  };
}
