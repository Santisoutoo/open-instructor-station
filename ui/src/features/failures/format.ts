/**
 * Display formatting for triggers and the armed/active chips.
 *
 * Locale pinned to `en-US`, as in `features/telemetry/format.ts`: the readout must be
 * identical on the tablet, the desktop and CI regardless of system locale.
 */

import type { AircraftState } from '../../api/models';
import { distanceNm } from './triggers';
import type { ArmedFailure, FailureTrigger, TriggerType } from './types.mock';

const INTEGER = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });

/** `45 s`, `1 min`, `1 min 30 s`. Never negative. */
export function formatDuration(totalSeconds: number): string {
  const whole = Math.max(0, Math.round(totalSeconds));
  const minutes = Math.floor(whole / 60);
  const seconds = whole % 60;
  if (minutes === 0) {
    return `${seconds} s`;
  }
  if (seconds === 0) {
    return `${minutes} min`;
  }
  return `${minutes} min ${seconds} s`;
}

/** The armed chip's condition, e.g. `at 3,000 ft climbing` or `after 1 min 30 s`. */
export function triggerPhrase(trigger: FailureTrigger): string {
  switch (trigger.type) {
    case 'altitude':
      return `at ${INTEGER.format(trigger.altitudeFt)} ft ${trigger.sense}`;
    case 'ias':
      return `at ${INTEGER.format(trigger.iasKt)} kt or ${trigger.sense}`;
    case 'delay':
      return `after ${formatDuration(trigger.delayS)}`;
    case 'distance':
      return `${trigger.distanceNm.toFixed(1)} NM from arming point`;
  }
}

/**
 * The live reading shown beside the editor's threshold input, e.g. `now: 2,340 ft`.
 * Only altitude and IAS have a meaningful "now" before arming; `null` means show
 * nothing. Without telemetry the honest answer is stated, not blank.
 */
export function editorNow(type: TriggerType, frame: AircraftState | null): string | null {
  if (type === 'delay' || type === 'distance') {
    return null;
  }
  if (frame === null) {
    return 'no telemetry';
  }
  return type === 'altitude'
    ? `now: ${INTEGER.format(Math.round(frame.altitude_ft))} ft`
    : `now: ${INTEGER.format(Math.round(frame.ias_kt))} kt`;
}

/**
 * The live value on an armed chip: a countdown for delay, the current reading for the
 * telemetry triggers, or `no telemetry` when there is nothing to read.
 */
export function armedLive(
  armed: ArmedFailure,
  frame: AircraftState | null,
  nowMs: number,
): string {
  const trigger = armed.trigger;
  if (trigger.type === 'delay') {
    // Clamped to the full delay so a stale clock can never show more time than armed.
    const remaining = Math.min(
      trigger.delayS,
      trigger.delayS - (nowMs - armed.armedAt) / 1000,
    );
    return `${formatDuration(remaining)} left`;
  }
  if (frame === null) {
    return 'no telemetry';
  }
  switch (trigger.type) {
    case 'altitude':
      return `now: ${INTEGER.format(Math.round(frame.altitude_ft))} ft`;
    case 'ias':
      return `now: ${INTEGER.format(Math.round(frame.ias_kt))} kt`;
    case 'distance': {
      if (armed.armedPosition === null) {
        return 'no arming point';
      }
      const flown = distanceNm(armed.armedPosition, {
        lat: frame.latitude,
        lon: frame.longitude,
      });
      return `now: ${flown.toFixed(1)} NM`;
    }
  }
}
