import { describe, expect, it } from 'vitest';
import type { CockpitControlSpec } from '../../../api/models';
import { cockpitCatalogManifestFixture } from '../fixtures';
import type { Detent, LayoutSlot } from '../layouts';
import {
  EMPTY_ROTARY_DRAFT,
  clampOrWrap,
  dialDraftValue,
  formatValue,
  nudgeDial,
  nudgeEncoder,
  predictedEncoderValue,
  roundToStep,
  snapToDetent,
  stepDecimals,
  wheelNotches,
} from './rotary';

function specFor(controlId: string): CockpitControlSpec {
  const spec = cockpitCatalogManifestFixture().controls.find(
    (control) => control.control_id === controlId,
  );
  if (spec === undefined) {
    throw new Error(`fixture is missing ${controlId}`);
  }
  return spec;
}

const heading = specFor('mcp_hdg'); // 0..360, step 1
const altitude = specFor('mcp_alt'); // 0..50000, step 100
const wrapSlot: LayoutSlot = {
  control_id: 'mcp_hdg',
  x: 0,
  y: 0,
  w: 1,
  h: 1,
  shape: 'knob',
  wrap: true,
};
const flapDetents: readonly Detent[] = [
  { value: 0, label: 'UP' },
  { value: 1, label: '1' },
  { value: 2, label: '2' },
  { value: 5, label: '5' },
  { value: 10, label: '10' },
  { value: 15, label: '15' },
  { value: 25, label: '25' },
  { value: 30, label: '30' },
  { value: 40, label: '40' },
];
const flaps: CockpitControlSpec = {
  ...altitude,
  control_id: 'flaps_lever',
  unit: 'units',
  min_value: 0,
  max_value: 40,
  step: 1,
};
const flapSlot: LayoutSlot = {
  control_id: 'flaps_lever',
  x: 0,
  y: 0,
  w: 1,
  h: 1,
  shape: 'lever',
  detents: flapDetents,
};

describe('EMPTY_ROTARY_DRAFT', () => {
  it('belongs to no control', () => {
    expect(EMPTY_ROTARY_DRAFT).toEqual({
      controlId: null,
      kind: null,
      text: '',
      clicks: 0,
    });
  });
});

describe('stepDecimals', () => {
  it('counts the decimals a step needs', () => {
    expect(stepDecimals(0.125)).toBe(3);
    expect(stepDecimals(100)).toBe(0);
    expect(stepDecimals(1)).toBe(0);
    expect(stepDecimals(0.5)).toBe(1);
    expect(stepDecimals(0.004)).toBe(3);
    expect(stepDecimals(0.0007)).toBe(4);
    expect(stepDecimals(1e-7)).toBe(7);
  });

  it('is 0 for a degenerate step', () => {
    expect(stepDecimals(0)).toBe(0);
    expect(stepDecimals(NaN)).toBe(0);
    expect(stepDecimals(Infinity)).toBe(0);
  });
});

describe('roundToStep', () => {
  it('lands on the step grid with exactly the decimals the step needs', () => {
    expect(roundToStep(0.1 + 0.2, 0.1)).toBe(0.3);
    expect(roundToStep(5.0625, 0.125)).toBe(5.125);
    expect(roundToStep(5.06, 0.125)).toBe(5);
    expect(roundToStep(0.0101, 0.004)).toBe(0.012);
    expect(roundToStep(0.006, 0.004)).toBe(0.008);
    expect(roundToStep(5049, 100)).toBe(5000);
    expect(roundToStep(5050, 100)).toBe(5100);
  });

  it('measures from the origin when one is given', () => {
    expect(roundToStep(11803, 25, 11800)).toBe(11800);
    expect(roundToStep(11813, 25, 11800)).toBe(11825);
  });

  it('leaves the value alone for a non-positive step', () => {
    expect(roundToStep(3.14159, 0)).toBe(3.14159);
    expect(roundToStep(3.14159, -1)).toBe(3.14159);
  });
});

describe('clampOrWrap', () => {
  it('wraps into [min, max) when asked', () => {
    expect(clampOrWrap(360, 0, 360, true)).toBe(0);
    expect(clampOrWrap(361, 0, 360, true)).toBe(1);
    expect(clampOrWrap(-1, 0, 360, true)).toBe(359);
    expect(clampOrWrap(725, 0, 360, true)).toBe(5);
    expect(clampOrWrap(359, 0, 360, true)).toBe(359);
    expect(clampOrWrap(0, 1, 361, true)).toBe(360);
  });

  it('clamps otherwise', () => {
    expect(clampOrWrap(50100, 0, 50000, false)).toBe(50000);
    expect(clampOrWrap(-5, 0, 50000, false)).toBe(0);
    expect(clampOrWrap(4200, 0, 50000, false)).toBe(4200);
  });

  it('falls back to clamping when a wrapped range has no finite bound', () => {
    expect(clampOrWrap(7, -Infinity, 5, true)).toBe(5);
    expect(clampOrWrap(7, 0, Infinity, true)).toBe(7);
  });
});

describe('snapToDetent', () => {
  it('picks the nearest detent, the lower one on a tie', () => {
    expect(snapToDetent(3, flapDetents)).toBe(2);
    expect(snapToDetent(4, flapDetents)).toBe(5);
    expect(snapToDetent(3.5, flapDetents)).toBe(2);
    expect(snapToDetent(20, flapDetents)).toBe(15);
    expect(snapToDetent(99, flapDetents)).toBe(40);
    expect(snapToDetent(-3, flapDetents)).toBe(0);
  });

  it('does not depend on the table order', () => {
    const shuffled = [...flapDetents].reverse();
    expect(snapToDetent(3.5, shuffled)).toBe(2);
    expect(snapToDetent(12.5, shuffled)).toBe(10);
  });

  it('returns the value itself with no detents', () => {
    expect(snapToDetent(12.5, [])).toBe(12.5);
  });
});

describe('nudgeDial', () => {
  it('moves by step and clamps at the range', () => {
    expect(nudgeDial(altitude, undefined, 5000, 1)).toBe(5100);
    expect(nudgeDial(altitude, undefined, 5000, -1, 3)).toBe(4700);
    expect(nudgeDial(altitude, undefined, 49950, 1)).toBe(50000);
    expect(nudgeDial(altitude, undefined, 0, -1)).toBe(0);
  });

  it('wraps a heading through 360', () => {
    expect(nudgeDial(heading, wrapSlot, 359, 1)).toBe(0);
    expect(nudgeDial(heading, wrapSlot, 0, -1)).toBe(359);
    expect(nudgeDial(heading, wrapSlot, 355, 1, 10)).toBe(5);
    expect(nudgeDial(heading, { ...wrapSlot, wrap: false }, 359, 1)).toBe(360);
  });

  it('lands on the step grid from an off-grid base', () => {
    expect(nudgeDial(altitude, undefined, 5050, 1)).toBe(5200);
    expect(nudgeDial(heading, wrapSlot, 359.7, 1)).toBe(1); // 360.7 wraps to 0.7, rounds to 1
    expect(nudgeDial(heading, wrapSlot, 358.6, 1)).toBe(0); // 359.6 rounds to 360, wraps to 0
  });

  it('never carries float junk', () => {
    const fine: CockpitControlSpec = {
      ...heading,
      min_value: 0,
      max_value: 1,
      step: 0.1,
    };
    expect(nudgeDial(fine, undefined, 0.2, 1)).toBe(0.3);
  });

  it('walks the detents and saturates at both ends', () => {
    expect(nudgeDial(flaps, flapSlot, 5, 1)).toBe(10);
    expect(nudgeDial(flaps, flapSlot, 5, -1)).toBe(2);
    expect(nudgeDial(flaps, flapSlot, 5, 1, 3)).toBe(25);
    expect(nudgeDial(flaps, flapSlot, 30, 1, 5)).toBe(40);
    expect(nudgeDial(flaps, flapSlot, 40, 1)).toBe(40);
    expect(nudgeDial(flaps, flapSlot, 0, -1)).toBe(0);
    expect(nudgeDial(flaps, flapSlot, 1, -1, 4)).toBe(0);
  });

  it('starts a detent walk from the detent nearest the base', () => {
    expect(nudgeDial(flaps, flapSlot, 3.5, 1)).toBe(5); // nearest is 2 (tie → lower), then up
    expect(nudgeDial(flaps, flapSlot, 12, -1)).toBe(5); // nearest is 10, then down
  });
});

describe('dialDraftValue', () => {
  it('parses, clamps and rounds to the grid', () => {
    expect(dialDraftValue(altitude, undefined, ' 5100 ')).toBe(5100);
    expect(dialDraftValue(altitude, undefined, '5149')).toBe(5100);
    expect(dialDraftValue(altitude, undefined, '99999')).toBe(50000);
    expect(dialDraftValue(altitude, undefined, '-5')).toBe(0);
  });

  it('wraps a heading and snaps to detents', () => {
    expect(dialDraftValue(heading, wrapSlot, '360')).toBe(0);
    expect(dialDraftValue(heading, wrapSlot, '-10')).toBe(350);
    expect(dialDraftValue(flaps, flapSlot, '12')).toBe(10);
    expect(dialDraftValue(flaps, flapSlot, '3.5')).toBe(2);
    expect(dialDraftValue(flaps, flapSlot, '90')).toBe(40);
  });

  it('is null for an empty or non-numeric draft', () => {
    expect(dialDraftValue(altitude, undefined, '')).toBeNull();
    expect(dialDraftValue(altitude, undefined, '   ')).toBeNull();
    expect(dialDraftValue(altitude, undefined, 'abc')).toBeNull();
    expect(dialDraftValue(altitude, undefined, '1e999')).toBeNull();
  });
});

describe('nudgeEncoder', () => {
  it('accumulates clicks and saturates at ±maxDelta', () => {
    expect(nudgeEncoder(0, 1, 1, 20)).toBe(1);
    expect(nudgeEncoder(3, -1, 5, 20)).toBe(-2);
    expect(nudgeEncoder(18, 1, 5, 20)).toBe(20);
    expect(nudgeEncoder(20, 1, 1, 20)).toBe(20);
    expect(nudgeEncoder(-19, -1, 100, 20)).toBe(-20);
    expect(nudgeEncoder(20, -1, 40, 20)).toBe(-20);
  });
});

describe('predictedEncoderValue', () => {
  it('projects the confirmed value by clicks × step on the step decimals', () => {
    expect(predictedEncoderValue(4, 3, 0.5)).toBe(5.5);
    expect(predictedEncoderValue(4, -10, 0.5)).toBe(-1);
    expect(predictedEncoderValue(0.1, 2, 0.1)).toBe(0.3);
  });

  it('is null while nothing has been read back', () => {
    expect(predictedEncoderValue(null, 3, 0.5)).toBeNull();
  });
});

describe('formatValue', () => {
  it('shows a dash for an unknown value', () => {
    expect(formatValue(null, 'ft')).toBe('—');
    expect(formatValue(null, 'khz', 'khz')).toBe('—');
  });

  it('formats khz as MHz', () => {
    expect(formatValue(11800, 'khz', 'khz')).toBe('118.00 MHz');
    expect(formatValue(12197, 'khz', 'khz')).toBe('121.97 MHz');
  });

  it('formats octal as a four-digit squawk', () => {
    expect(formatValue(512, 'count', 'octal')).toBe('0512');
    expect(formatValue(7700, 'count', 'octal')).toBe('7700');
  });

  it('formats plain values with their unit and grouping', () => {
    expect(formatValue(5000, 'ft', 'plain')).toBe('5,000 ft');
    expect(formatValue(5000, 'ft')).toBe('5,000 ft');
    expect(formatValue(0.8125, 'mach')).toBe('0.813 mach');
    expect(formatValue(90, null)).toBe('90');
    expect(formatValue(90, undefined)).toBe('90');
  });
});

describe('wheelNotches', () => {
  it('turns scroll-up into positive notches and scroll-down into negative ones', () => {
    expect(wheelNotches(0, -100, 0)).toEqual({ notches: 2, carry: 0 });
    expect(wheelNotches(0, 100, 0)).toEqual({ notches: -2, carry: 0 });
    expect(wheelNotches(0, -120, 0)).toEqual({ notches: 2, carry: -20 });
  });

  it('accumulates below the threshold and pays out once it is crossed', () => {
    const first = wheelNotches(0, 30, 0);
    expect(first).toEqual({ notches: 0, carry: 30 });

    const second = wheelNotches(first.carry, 30, 0);
    expect(second).toEqual({ notches: -1, carry: 10 });
  });

  it('throws the carry away on a change of direction', () => {
    const forward = wheelNotches(0, 40, 0);
    expect(forward).toEqual({ notches: 0, carry: 40 });

    const reversed = wheelNotches(forward.carry, -10, 0);
    expect(reversed).toEqual({ notches: 0, carry: -10 });

    expect(wheelNotches(-45, 45, 0)).toEqual({ notches: 0, carry: 45 });
  });

  it('honours a custom threshold', () => {
    expect(wheelNotches(0, -25, 0, 25)).toEqual({ notches: 1, carry: 0 });
    expect(wheelNotches(0, -24, 0, 25)).toEqual({ notches: 0, carry: -24 });
  });

  it('scales line and page delta modes into pixels', () => {
    const lines = wheelNotches(0, -3, 1); // 3 lines × 16 px = 48 px
    expect(lines).toEqual({ notches: 0, carry: -48 });
    expect(wheelNotches(lines.carry, -1, 1)).toEqual({ notches: 1, carry: -14 });

    expect(wheelNotches(0, -1, 2)).toEqual({ notches: 1, carry: 0 });
    expect(wheelNotches(0, 2, 2)).toEqual({ notches: -2, carry: 0 });
  });

  it('ignores a zero delta', () => {
    expect(wheelNotches(30, 0, 0)).toEqual({ notches: 0, carry: 30 });
    expect(wheelNotches(0, 0, 0)).toEqual({ notches: 0, carry: 0 });
  });
});
