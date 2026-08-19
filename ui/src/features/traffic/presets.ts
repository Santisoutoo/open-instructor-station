/**
 * The spawn forms' presets and bounds — a sibling `.ts` file rather than exports from
 * the component files (the `categories.ts`/`triggers.ts` convention: react-refresh
 * wants component files to export components).
 *
 * The numbers restate `core/traffic.py`'s constants as the design fixes them
 * (docs/designs/ai-traffic.md §3.3, §6.1) and must move with them at wiring time.
 */

import type { TcasSeverity } from './types.mock';

/**
 * What each TCAS preset does, in plain language (design §7.1) — the seconds and feet
 * come straight off `TCAS_SEVERITY_PROFILES`, so the instructor knows what they are
 * about to do to the student before they tap Spawn.
 */
export const SEVERITY_SENTENCES: Record<TcasSeverity, string> = {
  head_on_ra:
    'Resolution advisory: the intruder meets your projected position exactly — 0 ft ' +
    'vertical, 0 NM lateral — about 100 s after you tap Spawn.',
  crossing_ra:
    'Resolution advisory, crossing: the intruder crosses your projected position — 0 ft ' +
    'vertical, 0 NM lateral — about 100 s after you tap Spawn.',
  ta_only:
    'Traffic advisory only: the intruder passes 500 ft and 0.5 NM clear of your ' +
    'projected position about 90 s after you tap Spawn.',
};

export const SEVERITY_LABELS: Record<TcasSeverity, string> = {
  head_on_ra: 'Head-on RA',
  crossing_ra: 'Crossing RA',
  ta_only: 'TA only',
};

/** Mirrors `APPROACH_SEQUENCE_DEFAULT_DISTANCES_NM` in `core/traffic.py` (design §6.1). */
export const DEFAULT_DISTANCES_NM = [12, 8, 4];

/** The request model's `distances_nm` upper bound (design §3.3). */
export const MAX_DISTANCES = 8;

/** The request model's `route` bounds (design §3.3). */
export const MIN_ROUTE_POINTS = 2;
export const MAX_ROUTE_POINTS = 32;
