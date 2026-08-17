/**
 * `defaultTrigger` as a pure function: every trigger type opens with a sane default of
 * its own shape. The evaluator itself moved server-side (`core/failure_scheduler.py`)
 * and is covered there, not here.
 */

import { describe, expect, it } from 'vitest';
import { defaultTrigger, TRIGGER_TYPES } from './triggers';

describe('defaultTrigger', () => {
  it('yields a draft of the requested type for every trigger type', () => {
    expect(TRIGGER_TYPES).toHaveLength(5);
    for (const type of TRIGGER_TYPES) {
      expect(defaultTrigger(type).type).toBe(type);
    }
  });

  it('defaults altitude triggers to a sensible pattern-altitude threshold', () => {
    const above = defaultTrigger('altitude_above');
    const below = defaultTrigger('altitude_below');
    expect(above).toMatchObject({ type: 'altitude_above', altitude_ft: 3000 });
    expect(below).toMatchObject({ type: 'altitude_below', altitude_ft: 3000 });
  });

  it('defaults speed triggers to a sensible threshold', () => {
    const above = defaultTrigger('speed_above');
    const below = defaultTrigger('speed_below');
    expect(above).toMatchObject({ type: 'speed_above', ias_kt: 100 });
    expect(below).toMatchObject({ type: 'speed_below', ias_kt: 100 });
  });

  it('defaults the delay trigger to a positive number of seconds', () => {
    const delay = defaultTrigger('delay');
    expect(delay).toMatchObject({ type: 'delay', delay_s: 60 });
  });
});
