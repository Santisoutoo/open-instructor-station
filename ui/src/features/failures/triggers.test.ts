/**
 * The trigger evaluator as a pure function: every trigger type, the direction senses,
 * and the honesty rules — no telemetry means nothing telemetry-based fires.
 */

import { describe, expect, it } from 'vitest';
import type { AircraftState } from '../../api/models';
import { defaultTrigger, distanceNm, TRIGGER_TYPES, triggerFired } from './triggers';
import type { ArmedFailure, FailureTrigger } from './types.mock';

function frame(overrides: Partial<AircraftState> = {}): AircraftState {
  return {
    latitude: 40.46,
    longitude: -3.57,
    altitude_ft: 2500,
    heading_deg: 323,
    ias_kt: 100,
    vertical_speed_fpm: 0,
    pitch_deg: 0,
    roll_deg: 0,
    on_ground: false,
    ...overrides,
  };
}

function armed(trigger: FailureTrigger, extra: Partial<ArmedFailure> = {}): ArmedFailure {
  return {
    failureId: 'engine-fire',
    trigger,
    armedAt: 0,
    armedPosition: null,
    ...extra,
  };
}

describe('defaultTrigger', () => {
  it('yields a draft of the requested type for every trigger type', () => {
    expect(TRIGGER_TYPES).toHaveLength(4);
    for (const type of TRIGGER_TYPES) {
      expect(defaultTrigger(type).type).toBe(type);
    }
  });
});

describe('triggerFired — delay', () => {
  const entry = armed({ type: 'delay', delayS: 60 }, { armedAt: 10_000 });

  it('does not fire before the delay elapses', () => {
    expect(triggerFired(entry, null, 69_999)).toBe(false);
  });

  it('fires once the delay has elapsed, even with no telemetry at all', () => {
    expect(triggerFired(entry, null, 70_000)).toBe(true);
  });
});

describe('triggerFired — altitude', () => {
  const climbing = armed({ type: 'altitude', altitudeFt: 3000, sense: 'climbing' });

  it('fires climbing through the altitude', () => {
    expect(
      triggerFired(climbing, frame({ altitude_ft: 3050, vertical_speed_fpm: 800 }), 0),
    ).toBe(true);
  });

  it('does not fire below the altitude, nor when level at it', () => {
    expect(
      triggerFired(climbing, frame({ altitude_ft: 2400, vertical_speed_fpm: 800 }), 0),
    ).toBe(false);
    expect(
      triggerFired(climbing, frame({ altitude_ft: 3000, vertical_speed_fpm: 0 }), 0),
    ).toBe(false);
  });

  it('does not fire descending through when armed for a climb', () => {
    expect(
      triggerFired(climbing, frame({ altitude_ft: 3050, vertical_speed_fpm: -500 }), 0),
    ).toBe(false);
  });

  it('fires descending through when armed for a descent', () => {
    const descending = armed({ type: 'altitude', altitudeFt: 3000, sense: 'descending' });
    expect(
      triggerFired(descending, frame({ altitude_ft: 2900, vertical_speed_fpm: -500 }), 0),
    ).toBe(true);
    expect(
      triggerFired(descending, frame({ altitude_ft: 2900, vertical_speed_fpm: 500 }), 0),
    ).toBe(false);
  });

  it('stays armed with no telemetry', () => {
    expect(triggerFired(climbing, null, 0)).toBe(false);
  });
});

describe('triggerFired — ias', () => {
  it('fires at or above the threshold when armed above', () => {
    const entry = armed({ type: 'ias', iasKt: 120, sense: 'above' });
    expect(triggerFired(entry, frame({ ias_kt: 120 }), 0)).toBe(true);
    expect(triggerFired(entry, frame({ ias_kt: 119 }), 0)).toBe(false);
  });

  it('fires at or below the threshold when armed below', () => {
    const entry = armed({ type: 'ias', iasKt: 80, sense: 'below' });
    expect(triggerFired(entry, frame({ ias_kt: 80 }), 0)).toBe(true);
    expect(triggerFired(entry, frame({ ias_kt: 81 }), 0)).toBe(false);
  });
});

describe('triggerFired — distance', () => {
  const origin = { lat: 40.46, lon: -3.57 };
  const entry = armed({ type: 'distance', distanceNm: 3 }, { armedPosition: origin });

  it('fires once the aircraft is the armed distance from the arming point', () => {
    // 0.06° of latitude is 3.6 NM — past the 3 NM threshold.
    expect(triggerFired(entry, frame({ latitude: 40.52 }), 0)).toBe(true);
    expect(triggerFired(entry, frame({ latitude: 40.48 }), 0)).toBe(false);
  });

  it('stays armed without an arming point or without telemetry', () => {
    expect(triggerFired(armed({ type: 'distance', distanceNm: 3 }), frame(), 0)).toBe(
      false,
    );
    expect(triggerFired(entry, null, 0)).toBe(false);
  });
});

describe('distanceNm', () => {
  it('measures one degree of latitude as sixty NM', () => {
    expect(distanceNm({ lat: 40, lon: -3 }, { lat: 41, lon: -3 })).toBeCloseTo(60, 5);
  });
});
