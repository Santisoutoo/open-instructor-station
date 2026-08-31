/**
 * Trigger defaults — pure, no store, no timers.
 *
 * Evaluation itself is no longer client-side: the server's `FailureScheduler` and its
 * watcher task (`server/failure_routes.py`) evaluate armed triggers against live
 * telemetry, and the panel simply polls `/status` to see what fired. This file keeps
 * only what the editor needs — the five trigger types and what each opens with.
 */

import type { FailureTrigger, FailureTriggerType } from '../../api/models';

/** Editor tab order — the five-arm union from `core/failures.py` (D6). */
export const TRIGGER_TYPES: readonly FailureTriggerType[] = [
  'altitude_above',
  'altitude_below',
  'speed_above',
  'speed_below',
  'delay',
];

/** What the editor opens with when a type is picked. Static, so drafts are predictable. */
export function defaultTrigger(type: FailureTriggerType): FailureTrigger {
  switch (type) {
    case 'altitude_above':
      return { type: 'altitude_above', altitude_ft: 3000 };
    case 'altitude_below':
      return { type: 'altitude_below', altitude_ft: 3000 };
    case 'speed_above':
      return { type: 'speed_above', ias_kt: 100 };
    case 'speed_below':
      return { type: 'speed_below', ias_kt: 100 };
    case 'delay':
      return { type: 'delay', delay_s: 60 };
  }
}
