/**
 * Trigger defaults and evaluation — pure functions, no store, no timers.
 *
 * The evaluation runs in the panel's tick hook against the demo telemetry feed; at
 * backend integration the server's trigger evaluator (feature-spec §2) takes over and
 * this file dies with the rest of the mock.
 */

import type { AircraftState } from '../../api/models';
import type { ArmedFailure, FailureTrigger, LatLon, TriggerType } from './types.mock';

/** Editor tab order. */
export const TRIGGER_TYPES: readonly TriggerType[] = [
  'altitude',
  'ias',
  'delay',
  'distance',
];

/** What the editor opens with when a type is picked. Static, so drafts are predictable. */
export function defaultTrigger(type: TriggerType): FailureTrigger {
  switch (type) {
    case 'altitude':
      return { type: 'altitude', altitudeFt: 3000, sense: 'climbing' };
    case 'ias':
      return { type: 'ias', iasKt: 100, sense: 'above' };
    case 'delay':
      return { type: 'delay', delayS: 60 };
    case 'distance':
      return { type: 'distance', distanceNm: 2 };
  }
}

/** Flat-earth distance — fine at trigger scale (<20 NM), same shortcut as the demo feed. */
export function distanceNm(a: LatLon, b: LatLon): number {
  const midLatRad = (((a.lat + b.lat) / 2) * Math.PI) / 180;
  const dy = (b.lat - a.lat) * 60;
  const dx = (b.lon - a.lon) * 60 * Math.cos(midLatRad);
  return Math.hypot(dx, dy);
}

/**
 * Should this armed failure fire, given the latest telemetry frame and the clock?
 *
 * Honest about missing data: without a frame only the delay trigger can be judged, so
 * everything else stays armed rather than firing blind. The altitude senses gate on the
 * vertical speed sign — "at 3,000 ft climbing" must not fire on a descent through the
 * same level, nor while parked at the threshold altitude.
 */
export function triggerFired(
  armed: ArmedFailure,
  frame: AircraftState | null,
  nowMs: number,
): boolean {
  const trigger = armed.trigger;
  switch (trigger.type) {
    case 'delay':
      return nowMs - armed.armedAt >= trigger.delayS * 1000;
    case 'altitude':
      if (frame === null) {
        return false;
      }
      return trigger.sense === 'climbing'
        ? frame.altitude_ft >= trigger.altitudeFt && frame.vertical_speed_fpm > 0
        : frame.altitude_ft <= trigger.altitudeFt && frame.vertical_speed_fpm < 0;
    case 'ias':
      if (frame === null) {
        return false;
      }
      return trigger.sense === 'above'
        ? frame.ias_kt >= trigger.iasKt
        : frame.ias_kt <= trigger.iasKt;
    case 'distance':
      if (frame === null || armed.armedPosition === null) {
        return false;
      }
      return (
        distanceNm(armed.armedPosition, {
          lat: frame.latitude,
          lon: frame.longitude,
        }) >= trigger.distanceNm
      );
  }
}
