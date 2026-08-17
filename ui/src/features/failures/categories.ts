/**
 * Display order and labels for the nine failure categories (`core/failures.py`'s
 * `FailureCategory`). Lives next to the component that renders it, not in `api/`: the
 * categories themselves are generated from the OpenAPI schema, but how they are grouped
 * and worded on screen is a display decision — the same split `CapabilityList.tsx`
 * makes for capability flags.
 */

import type { FailureCategory } from '../../api/models';

/** Accordion order — engines first, the category instructors reach for most. */
export const CATEGORY_ORDER: readonly FailureCategory[] = [
  'engine',
  'fuel',
  'electrical',
  'hydraulics',
  'instruments',
  'avionics',
  'flight_controls',
  'gear',
  'airframe',
];

/** Sentence-case group headings, keyed by category id. */
export const CATEGORY_LABELS: Readonly<Record<FailureCategory, string>> = {
  engine: 'Engine',
  fuel: 'Fuel',
  electrical: 'Electrical',
  hydraulics: 'Hydraulics',
  instruments: 'Instruments',
  avionics: 'Avionics',
  flight_controls: 'Flight controls',
  gear: 'Landing gear',
  airframe: 'Airframe',
};
