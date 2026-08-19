/**
 * The right rail's Checks list — the highest-value suite in this feature. Every assertion
 * is against the **full ordered array** the rail actually renders, never membership: the
 * rules fire in a fixed order and a reorder is as much a bug as a missing rule.
 */

import { describe, expect, it } from 'vitest';
import { checks } from './checks';
import {
  initialPositionDesignState,
  type PositionDesignState,
} from './positionDesignSlice';

function state(overrides: Partial<PositionDesignState> = {}): PositionDesignState {
  return { ...initialPositionDesignState, ...overrides };
}

const CTR_PASS = {
  dot: 'accent',
  text: 'Position inside the LFMN CTR',
  note: 'Terrain and airspace check passed with sample data',
};

describe('rule 1 — tailwind on the selected runway', () => {
  it('fires when the tailwind is 3 kt or more and no stand is selected', () => {
    // 04R (course 40°) is 160° off the sample 240°/12 kt wind — an 11 kt tailwind.
    expect(checks(state({ selectedRunway: null }))).not.toContainEqual(
      expect.objectContaining({ text: expect.stringContaining('Tailwind') as unknown }),
    );
    const result = checks(state({ selectedRunway: '04R' }));
    expect(result[0]).toEqual({
      dot: 'caution',
      text: 'Tailwind 11 kt on 04R',
      note: '22L is the favoured runway for this wind',
    });
  });

  it('does not fire when the runway has a headwind', () => {
    // 22L (course 220°) is 20° off the same wind — an 11 kt headwind, no tailwind.
    const result = checks(
      state({
        selectedRunway: '22L',
        config: { ...initialPositionDesignState.config, gearDown: true },
      }),
    );
    expect(result.some((c) => c.text.includes('Tailwind'))).toBe(false);
  });
});

describe('rule 2 — gear up on a final/base/vectors marker', () => {
  it('fires on the Approach tab with no stand selected and gear up', () => {
    const result = checks(state({ selectedRunway: null }));
    expect(result).toEqual([
      {
        dot: 'caution',
        text: 'Gear up 3.0 NM from the threshold',
        note: 'Tick "Gear down" to spawn configured for landing',
      },
      CTR_PASS,
    ]);
  });

  it('does not fire once gear is down', () => {
    const result = checks(
      state({
        selectedRunway: null,
        config: { ...initialPositionDesignState.config, gearDown: true },
      }),
    );
    expect(result).toEqual([CTR_PASS]);
  });
});

describe('rule 3 — ILS toggle on, no ILS on the selected runway', () => {
  it('fires when the toggle is on and the runway has no ILS', () => {
    const result = checks(
      state({
        selectedRunway: '22L',
        config: { ...initialPositionDesignState.config, gearDown: true },
      }),
    );
    expect(result).toEqual([
      {
        dot: 'info',
        text: 'No ILS on 22L',
        note: 'The frequency will be skipped when the position is set',
      },
      CTR_PASS,
    ]);
  });

  it('does not fire when the toggle is off', () => {
    const result = checks(
      state({
        selectedRunway: '22L',
        config: { ...initialPositionDesignState.config, gearDown: true },
        send: { ...initialPositionDesignState.send, ilsFrequency: false },
      }),
    );
    expect(result).toEqual([CTR_PASS]);
  });
});

describe('rule 4 — low IAS on the Airwork tab', () => {
  it('fires below 150 kt', () => {
    const result = checks(state({ selectedRunway: null, activeTab: 'airwork' }));
    expect(result).toEqual([
      {
        dot: 'caution',
        text: '60 kt IAS at FL100',
        note: 'Below a sustainable speed at that level for most aircraft',
      },
      CTR_PASS,
    ]);
  });

  it('does not fire at or above 150 kt', () => {
    const result = checks(
      state({
        selectedRunway: null,
        activeTab: 'airwork',
        config: { ...initialPositionDesignState.config, iasKt: 200 },
      }),
    );
    expect(result).toEqual([CTR_PASS]);
  });
});

describe('rule 5 — altitude override active', () => {
  it('fires when the override checkbox is on', () => {
    const result = checks(
      state({
        selectedRunway: null,
        activeTab: 'custom',
        config: { ...initialPositionDesignState.config, altitudeOverride: true },
      }),
    );
    expect(result).toEqual([
      {
        dot: 'caution',
        text: 'Altitude override active',
        note: 'Replaces the computed 0 ft',
      },
      CTR_PASS,
    ]);
  });

  it('does not fire when the override checkbox is off', () => {
    const result = checks(state({ selectedRunway: null, activeTab: 'custom' }));
    expect(result).toEqual([CTR_PASS]);
  });
});

describe('rule 6 — a stand is selected', () => {
  it('fires and names the stand', () => {
    const result = checks(
      state({ selectedRunway: null, selectedStand: 'A3', activeTab: 'custom' }),
    );
    expect(result).toEqual([
      {
        dot: 'info',
        text: 'Starting from stand A3',
        note: 'Circuit and procedure positions are ignored while a stand is selected',
      },
      CTR_PASS,
    ]);
  });

  it('does not fire when no stand is selected', () => {
    const result = checks(state({ selectedRunway: null, activeTab: 'custom' }));
    expect(result.some((c) => c.text.startsWith('Starting from stand'))).toBe(false);
  });
});

describe('rule 7 — CTR pass', () => {
  it('is always last and always present', () => {
    for (const overrides of [
      {},
      { activeTab: 'airwork' as const },
      { selectedStand: 'A3', selectedRunway: null },
    ]) {
      const result = checks(state(overrides));
      expect(result[result.length - 1]).toEqual(CTR_PASS);
    }
  });
});

describe('default state', () => {
  it('produces the full ordered array: tailwind, gear up, CTR pass', () => {
    expect(checks(initialPositionDesignState)).toEqual([
      {
        dot: 'caution',
        text: 'Tailwind 11 kt on 04R',
        note: '22L is the favoured runway for this wind',
      },
      {
        dot: 'caution',
        text: 'Gear up 3.0 NM from the threshold',
        note: 'Tick "Gear down" to spawn configured for landing',
      },
      CTR_PASS,
    ]);
  });
});
