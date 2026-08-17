/**
 * The shipped catalogue. Fifteen failures across every system group is the demo's
 * contract with the panel — a fixture edit that loses one should fail loudly here.
 */

import { describe, expect, it } from 'vitest';
import { FAILURE_CATALOGUE, failuresManifestFixture, SYSTEM_LABELS, SYSTEM_ORDER } from './mock';

describe('FAILURE_CATALOGUE', () => {
  it('ships exactly fifteen failures', () => {
    expect(FAILURE_CATALOGUE).toHaveLength(15);
  });

  it('has a unique id per failure', () => {
    const ids = FAILURE_CATALOGUE.map((definition) => definition.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('covers every system group, and names no system outside the order', () => {
    for (const system of SYSTEM_ORDER) {
      expect(
        FAILURE_CATALOGUE.some((definition) => definition.system === system),
        system,
      ).toBe(true);
    }
    for (const definition of FAILURE_CATALOGUE) {
      expect(SYSTEM_ORDER).toContain(definition.system);
    }
  });

  it('labels every system for the accordion headers', () => {
    for (const system of SYSTEM_ORDER) {
      expect(SYSTEM_LABELS[system]).not.toBe('');
    }
  });

  it('marks at least one failure best effort, per feature-spec §4', () => {
    expect(FAILURE_CATALOGUE.some((definition) => definition.bestEffort)).toBe(true);
  });
});

describe('failuresManifestFixture', () => {
  it('reports failure injection available in the demo, with no dangling reason', () => {
    const manifest = failuresManifestFixture();
    expect(manifest.available).toBe(true);
    expect(manifest.reason).toBeNull();
  });
});
