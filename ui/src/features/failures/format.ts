/**
 * Display formatting for triggers and the armed/active chips.
 *
 * Locale pinned to `en-US`, as in `features/telemetry/format.ts`: the readout must be
 * identical on the tablet, the desktop and CI regardless of system locale.
 */

import type { AircraftState, ArmedFailure, FailureTrigger, FailureTriggerType } from '../../api/models';

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

/** The armed chip's condition, e.g. `at or above 3,000 ft` or `after 1 min 30 s`. */
export function triggerPhrase(trigger: FailureTrigger): string {
  switch (trigger.type) {
    case 'altitude_above':
      return `at or above ${INTEGER.format(trigger.altitude_ft)} ft`;
    case 'altitude_below':
      return `at or below ${INTEGER.format(trigger.altitude_ft)} ft`;
    case 'speed_above':
      return `at or above ${INTEGER.format(trigger.ias_kt)} kt`;
    case 'speed_below':
      return `at or below ${INTEGER.format(trigger.ias_kt)} kt`;
    case 'delay':
      return `after ${formatDuration(trigger.delay_s)}`;
  }
}

/** `engine N` when the failure is indexed, empty string otherwise — appended to a label. */
export function engineSuffix(engineIndex: number | null | undefined): string {
  return engineIndex == null ? '' : ` — engine ${INTEGER.format(engineIndex)}`;
}

const ALTITUDE_TRIGGER_TYPES: readonly FailureTriggerType[] = ['altitude_above', 'altitude_below'];

/**
 * The live reading shown beside the editor's threshold input, e.g. `now: 2,340 ft`.
 * Only altitude and speed triggers have a meaningful "now" before arming; `null` means
 * show nothing. Without telemetry the honest answer is stated, not blank.
 */
export function editorNow(type: FailureTriggerType, frame: AircraftState | null): string | null {
  if (type === 'delay') {
    return null;
  }
  if (frame === null) {
    return 'no telemetry';
  }
  return ALTITUDE_TRIGGER_TYPES.includes(type)
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
    const armedAtMs = new Date(armed.armed_at).getTime();
    const remaining = Math.min(trigger.delay_s, trigger.delay_s - (nowMs - armedAtMs) / 1000);
    return `${formatDuration(remaining)} left`;
  }
  if (frame === null) {
    return 'no telemetry';
  }
  return ALTITUDE_TRIGGER_TYPES.includes(trigger.type)
    ? `now: ${INTEGER.format(Math.round(frame.altitude_ft))} ft`
    : `now: ${INTEGER.format(Math.round(frame.ias_kt))} kt`;
}
