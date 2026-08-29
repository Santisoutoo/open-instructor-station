/**
 * The airborne speed gate.
 *
 * The failure this guards is on the record: an aircraft placed on a geometrically perfect
 * 10 NM final at 0 kt is below stall speed and in the terrain seconds later, and it took four
 * days and a live simulator to find. `core.geodesy.coordinate_placement` still defaults to
 * `GROUND_IAS_KT`, so every coordinate placement this screen sends resolves to 0 kt unless
 * the instructor says otherwise — the gate is what makes them say so.
 */

import { describe, expect, it } from 'vitest';
import {
  AIRBORNE_AGL_FT,
  HIGH_LEVEL_MINIMUM_IAS_KT,
  MINIMUM_AIRBORNE_IAS_KT,
  isAirborne,
  sustainableIasKt,
  unflyableReason,
} from './speed';

describe('isAirborne', () => {
  it('is false on a stand or a threshold, whatever the field elevation', () => {
    expect(isAirborne({ altitudeFt: 12, groundElevationFt: 12, iasKt: 0 })).toBe(false);
    expect(isAirborne({ altitudeFt: 5431, groundElevationFt: 5431, iasKt: 0 })).toBe(
      false,
    );
  });

  it('is true on a circuit height and above', () => {
    expect(isAirborne({ altitudeFt: 1512, groundElevationFt: 12, iasKt: 90 })).toBe(true);
    expect(isAirborne({ altitudeFt: 10000, groundElevationFt: 12, iasKt: 0 })).toBe(true);
  });

  it('takes the ground as sea level when no airport is loaded', () => {
    // A map hand-off carries no elevation. 0 ft is a ground placement; 5,000 ft is not.
    expect(isAirborne({ altitudeFt: 0, groundElevationFt: null, iasKt: 0 })).toBe(false);
    expect(isAirborne({ altitudeFt: 5000, groundElevationFt: null, iasKt: 0 })).toBe(
      true,
    );
  });

  it('is false before the preview has resolved an altitude', () => {
    expect(isAirborne({ altitudeFt: null, groundElevationFt: 12, iasKt: 0 })).toBe(false);
  });

  it('turns over exactly at the documented height above the ground', () => {
    const ground = 200;
    expect(
      isAirborne({
        altitudeFt: ground + AIRBORNE_AGL_FT,
        groundElevationFt: ground,
        iasKt: 0,
      }),
    ).toBe(true);
    expect(
      isAirborne({
        altitudeFt: ground + AIRBORNE_AGL_FT - 1,
        groundElevationFt: ground,
        iasKt: 0,
      }),
    ).toBe(false);
  });
});

describe('sustainableIasKt', () => {
  it('asks for a lot more at a flight level than in the circuit', () => {
    expect(sustainableIasKt(10000)).toBe(HIGH_LEVEL_MINIMUM_IAS_KT);
    expect(sustainableIasKt(30000)).toBe(HIGH_LEVEL_MINIMUM_IAS_KT);
    expect(sustainableIasKt(1500)).toBe(MINIMUM_AIRBORNE_IAS_KT);
  });

  it('leaves an approach-category final speed alone', () => {
    // 121 kt is a category C VAT. The rail must not caution about a correct final.
    expect(sustainableIasKt(968)).toBeLessThanOrEqual(121);
  });
});

describe('unflyableReason', () => {
  it('refuses an airborne placement at 0 kt and names the speed to state', () => {
    expect(
      unflyableReason({ altitudeFt: 10000, groundElevationFt: 12, iasKt: 0 }),
    ).toContain('State an IAS of at least 60 kt');
  });

  it('quotes the altitude and the speed that would have been applied', () => {
    expect(unflyableReason({ altitudeFt: 5000, groundElevationFt: null, iasKt: 0 })).toBe(
      'This placement is airborne at 5,000 ft and would arrive at 0 kt. ' +
        'State an IAS of at least 60 kt before placing.',
    );
  });

  it('lets a ground placement through at 0 kt — that is what a stand is', () => {
    expect(
      unflyableReason({ altitudeFt: 12, groundElevationFt: 12, iasKt: 0 }),
    ).toBeNull();
  });

  it('lets a stabilised final through, though it is slower than a flight level needs', () => {
    expect(
      unflyableReason({ altitudeFt: 968, groundElevationFt: 12, iasKt: 121 }),
    ).toBeNull();
  });

  it('is silent, never blocking, before the preview has answered', () => {
    expect(
      unflyableReason({ altitudeFt: null, groundElevationFt: 12, iasKt: null }),
    ).toBeNull();
    expect(
      unflyableReason({ altitudeFt: 10000, groundElevationFt: 12, iasKt: null }),
    ).toBeNull();
  });

  it('blocks only below a speed that will not fly, not merely a slow one', () => {
    // 90 kt at a flight level is worth a caution in the rail; it is not worth refusing.
    expect(
      unflyableReason({ altitudeFt: 10000, groundElevationFt: 12, iasKt: 90 }),
    ).toBeNull();
  });
});
