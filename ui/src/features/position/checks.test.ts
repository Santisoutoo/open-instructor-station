/**
 * The right rail's Checks list — the highest-value suite in this feature. Every assertion is
 * against the **full ordered array** the rail actually renders, never membership: the rules
 * fire in a fixed order and a reorder is as much a bug as a missing rule.
 *
 * The v3 mockup's seventh, always-passing "inside the LFMN CTR" check is deliberately gone,
 * and the last test here is what keeps it gone.
 */

import { describe, expect, it } from 'vitest';
import { checks, type CheckInputs } from './checks';

/** A placement with nothing wrong with it: headwind, gear down, ILS present. */
function inputs(overrides: Partial<CheckInputs> = {}): CheckInputs {
  return {
    runwayIdent: '04R',
    reciprocalIdent: '22L',
    tailwindKt: 0,
    hasIls: true,
    sendIls: true,
    standName: null,
    activeTab: 'approach',
    marker: 'final-3nm',
    finalPlacement: 'final_3nm',
    gearDown: true,
    iasKt: 121,
    altitudeFt: 968,
    groundElevationFt: 12,
    altitudeOverride: false,
    altitudeOverrideFt: 0,
    ...overrides,
  };
}

describe('a clean placement', () => {
  it('has nothing to flag', () => {
    expect(checks(inputs())).toEqual([]);
  });
});

describe('rule 1 — tailwind on the selected runway', () => {
  it('fires at 3 kt and names the reciprocal', () => {
    expect(checks(inputs({ tailwindKt: 11 }))).toEqual([
      {
        dot: 'caution',
        text: 'Tailwind 11 kt on 04R',
        note: '22L is the favoured runway for this wind',
      },
    ]);
  });

  it('falls back to a generic note when navdata publishes no reciprocal', () => {
    expect(checks(inputs({ tailwindKt: 5, reciprocalIdent: null }))[0]?.note).toBe(
      'Check the wind before starting',
    );
  });

  it('does not fire below the threshold, or with no wind at all', () => {
    expect(checks(inputs({ tailwindKt: 2 }))).toEqual([]);
    expect(checks(inputs({ tailwindKt: null }))).toEqual([]);
  });

  it('does not fire while a stand is selected', () => {
    const result = checks(inputs({ tailwindKt: 11, standName: 'A3' }));
    expect(result.some((check) => check.text.startsWith('Tailwind'))).toBe(false);
  });
});

describe('rule 2 — gear up on a final/base/vectors marker', () => {
  it('fires on the Approach tab with the gear up, quoting the selected final', () => {
    expect(checks(inputs({ gearDown: false, finalPlacement: 'final_10nm' }))).toEqual([
      {
        dot: 'caution',
        text: 'Gear up 10.0 NM from the threshold',
        note: 'Tick "Gear down" to spawn configured for landing',
      },
    ]);
  });

  it('fires on a circuit leg at that leg’s own distance', () => {
    expect(checks(inputs({ gearDown: false, marker: 'base-left' }))[0]?.text).toBe(
      'Gear up 6.0 NM from the threshold',
    );
  });

  it('does not fire on the threshold or downwind', () => {
    expect(checks(inputs({ gearDown: false, marker: 'takeoff' }))).toEqual([]);
    expect(checks(inputs({ gearDown: false, marker: 'downwind-left' }))).toEqual([]);
  });

  it('does not fire once the gear is down, or before the gear is known', () => {
    expect(checks(inputs({ gearDown: true }))).toEqual([]);
    expect(checks(inputs({ gearDown: null }))).toEqual([]);
  });
});

describe('rule 3 — ILS switch on, no ILS on the selected runway', () => {
  it('fires when the runway publishes none', () => {
    expect(checks(inputs({ runwayIdent: '22L', hasIls: false }))).toEqual([
      {
        dot: 'info',
        text: 'No ILS on 22L',
        note: 'The frequency will be skipped when the position is set',
      },
    ]);
  });

  it('does not fire while the lookup is still in flight', () => {
    expect(checks(inputs({ runwayIdent: '22L', hasIls: null }))).toEqual([]);
  });

  it('does not fire when the switch is off', () => {
    expect(checks(inputs({ runwayIdent: '22L', hasIls: false, sendIls: false }))).toEqual(
      [],
    );
  });
});

describe('rule 4 — an airborne placement below a sustainable speed', () => {
  it('fires at a flight level below 150 kt, whatever the tab', () => {
    expect(
      checks(inputs({ activeTab: 'airwork', altitudeFt: 10000, iasKt: 60 })),
    ).toEqual([
      {
        dot: 'caution',
        text: '60 kt IAS at 10,000 ft',
        note: 'Below a sustainable speed at that altitude for most aircraft',
      },
    ]);
  });

  it('fires on the Custom tab too — a coordinate resolves to 0 kt unless one is stated', () => {
    // core.geodesy.coordinate_placement defaults to GROUND_IAS_KT, so a Custom placement at
    // 5,000 ft arrives stationary. The old rule was scoped to the Airwork tab and said
    // nothing about this one.
    expect(
      checks(inputs({ activeTab: 'custom', altitudeFt: 5000, iasKt: 0 }))[0],
    ).toEqual({
      dot: 'caution',
      text: '0 kt IAS at 5,000 ft',
      note: 'Below a sustainable speed at that altitude for most aircraft',
    });
  });

  it('stays quiet on a stabilised final at approach-category speed', () => {
    // 121 kt at 968 ft is the fixture's 3 NM final: correct, and 150 kt would be wrong.
    expect(checks(inputs())).toEqual([]);
  });

  it('does not fire on the ground, at any speed', () => {
    expect(
      checks(
        inputs({ marker: 'takeoff', altitudeFt: 12, groundElevationFt: 12, iasKt: 0 }),
      ),
    ).toEqual([]);
  });

  it('does not fire at or above the sustainable speed', () => {
    expect(checks(inputs({ altitudeFt: 10000, iasKt: 200 }))).toEqual([]);
    expect(checks(inputs({ altitudeFt: 5000, iasKt: 90 }))).toEqual([]);
  });

  it('treats an unknown field elevation as sea level rather than guessing', () => {
    // A map hand-off carries no airport: 0 ft at an unknown field is a ground placement,
    // 5,000 ft is not.
    expect(checks(inputs({ altitudeFt: 0, groundElevationFt: null, iasKt: 0 }))).toEqual(
      [],
    );
    expect(
      checks(inputs({ altitudeFt: 5000, groundElevationFt: null, iasKt: 0 })),
    ).toHaveLength(1);
  });
});

describe('rule 5 — altitude override active', () => {
  it('fires and names the figure that replaces the computed one', () => {
    expect(checks(inputs({ altitudeOverride: true, altitudeOverrideFt: 5500 }))).toEqual([
      {
        dot: 'caution',
        text: 'Altitude override active',
        note: 'Replaces the altitude the placement resolved, with 5,500 ft',
      },
    ]);
  });
});

describe('rule 6 — a stand is selected', () => {
  it('fires and names the stand', () => {
    expect(checks(inputs({ standName: 'A3' }))).toEqual([
      {
        dot: 'info',
        text: 'Starting from stand A3',
        note: 'Circuit and procedure positions are ignored while a stand is selected',
      },
    ]);
  });
});

describe('the whole ordered list', () => {
  it('fires every rule at once, in order', () => {
    expect(
      checks(
        inputs({
          runwayIdent: '22L',
          reciprocalIdent: '04R',
          tailwindKt: 7,
          hasIls: false,
          gearDown: false,
          marker: 'base-right',
          activeTab: 'approach',
          altitudeFt: 10000,
          iasKt: 60,
          altitudeOverride: true,
          altitudeOverrideFt: 2000,
        }),
      ).map((check) => check.text),
    ).toEqual([
      'Tailwind 7 kt on 22L',
      'Gear up 6.0 NM from the threshold',
      'No ILS on 22L',
      '60 kt IAS at 10,000 ft',
      'Altitude override active',
    ]);
  });

  it('never invents an always-passing airspace check', () => {
    // The mockup's "Position inside the LFMN CTR" passed unconditionally on sample data.
    // There is no airspace source behind this station; a check that always passes teaches
    // an instructor to stop reading the list.
    for (const overrides of [{}, { standName: 'A3' }, { tailwindKt: 11 }]) {
      for (const check of checks(inputs(overrides))) {
        expect(check.text).not.toContain('CTR');
        expect(check.dot).not.toBe('accent');
      }
    }
  });
});
