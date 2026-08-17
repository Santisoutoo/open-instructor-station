/**
 * Formatting for the active scenario bar. Pure on purpose: `now` is a parameter, never
 * read inside, so every path is testable without a clock — and step names are looked up
 * from a closed record, so a step the server adds fails the typecheck here until this map
 * knows its label.
 */

import type { ScenarioRunStatus, ScenarioStepName } from '../../api/models';

const STEP_LABELS: Record<ScenarioStepName, string> = {
  weather: 'Set weather',
  aircraft_state: 'Configure aircraft',
  position: 'Position aircraft',
  failures: 'Arm failures',
  traffic: 'Spawn traffic',
};

/** The label a run step's name is shown under in the active-run checklist. */
export function formatStepName(name: ScenarioStepName): string {
  return STEP_LABELS[name];
}

/** Whole seconds between two epoch-ms instants, clamped at zero. */
export function elapsedSeconds(startedAt: number, now: number): number {
  return Math.max(0, Math.floor((now - startedAt) / 1000));
}

/** `mm:ss`, zero-padded: 65 s → `01:05`. Minutes keep growing past an hour. */
export function formatSeconds(totalSeconds: number): string {
  const clamped = Math.max(0, Math.floor(totalSeconds));
  const minutes = String(Math.floor(clamped / 60)).padStart(2, '0');
  const seconds = String(clamped % 60).padStart(2, '0');
  return `${minutes}:${seconds}`;
}

/** Elapsed time between `startedAt` and `now` as `mm:ss`. */
export function formatElapsed(startedAt: number, now: number): string {
  return formatSeconds(elapsedSeconds(startedAt, now));
}

/**
 * The identity of one run for dismiss-tracking: scenario id plus its server-stamped start
 * time. Two runs of the same scenario started at different times are different runs; the
 * scenario id alone is not enough to tell them apart.
 */
export function runKey(run: ScenarioRunStatus): string {
  return `${run.scenario_id}:${run.started_at}`;
}

/**
 * A readable fallback label built from a scenario's kebab-case id — `"engine-failure-
 * after-v1"` → `"Engine failure after v1"`. Used only where the full catalogue (which
 * carries the real `name`) has not been fetched, e.g. `components/StatusBar.tsx`'s
 * footer chip when the Scenarios tab has never been opened this session.
 */
export function formatScenarioId(id: string): string {
  const [first, ...rest] = id.split('-');
  if (first === undefined) {
    return id;
  }
  return [first.charAt(0).toUpperCase() + first.slice(1), ...rest].join(' ');
}
