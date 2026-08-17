/**
 * The shipped catalogue. Twelve scenarios is a spec number (feature-spec §2), not an
 * implementation detail — a fixture edit that loses one should fail loudly here.
 */

import { describe, expect, it } from 'vitest';
import { MOCK_SCENARIOS } from './mock';

describe('MOCK_SCENARIOS', () => {
  it('ships exactly the twelve scenarios from the spec', () => {
    expect(MOCK_SCENARIOS).toHaveLength(12);
  });

  it('has a unique id per scenario', () => {
    const ids = MOCK_SCENARIOS.map((scenario) => scenario.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('gives every scenario a plan of at least two steps', () => {
    for (const scenario of MOCK_SCENARIOS) {
      expect(scenario.steps.length, scenario.id).toBeGreaterThanOrEqual(2);
    }
  });

  it('marks the TCAS scenario unavailable, with the reason stated', () => {
    const tcas = MOCK_SCENARIOS.find(
      (scenario) => scenario.id === 'tcas-resolution-advisory',
    );
    expect(tcas).toBeDefined();
    expect(tcas?.available).toBe(false);
    expect(tcas?.unavailableReason).toBe('AI traffic bridge not connected (demo)');
  });

  it('leaves every other scenario available, with no dangling reason', () => {
    const others = MOCK_SCENARIOS.filter(
      (scenario) => scenario.id !== 'tcas-resolution-advisory',
    );
    for (const scenario of others) {
      expect(scenario.available, scenario.id).toBe(true);
      expect(scenario.unavailableReason, scenario.id).toBeNull();
    }
  });
});
