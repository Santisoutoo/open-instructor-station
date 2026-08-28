import { describe, expect, it } from 'vitest';
import { initialPositionDesignState } from './positionDesignSlice';
import { instructorSetup, mergedSetup, overridesOrNull } from './setup';
import { ILS_04R, PREVIEW } from './testFixtures';

const CONFIG = initialPositionDesignState.config;
const SEND = initialPositionDesignState.send;
const NOTHING_SENT = { course: false, ilsFrequency: false };

describe('instructorSetup', () => {
  it('sends nothing at all when nothing was touched', () => {
    const { overrides, overridden } = instructorSetup(CONFIG, NOTHING_SENT, ILS_04R);
    expect(overrides).toEqual({});
    expect(overridden.size).toBe(0);
    expect(overridesOrNull(overrides)).toBeNull();
  });

  it('sends only the fields the instructor changed', () => {
    const { overrides, overridden } = instructorSetup(
      { ...CONFIG, iasKt: 90 },
      NOTHING_SENT,
      ILS_04R,
    );
    expect(overrides).toEqual({ ias_kt: 90 });
    expect(overridden.has('ias_kt')).toBe(true);
    expect(overridden.has('gear_down')).toBe(false);
  });

  it('turns a flap percentage into the wire’s 0-1 ratio', () => {
    const { overrides } = instructorSetup(
      { ...CONFIG, flapsPercent: 25 },
      NOTHING_SENT,
      ILS_04R,
    );
    expect(overrides.flaps_ratio).toBeCloseTo(0.25, 10);
  });

  it('only sends an altitude when the override switch is on', () => {
    expect(
      instructorSetup({ ...CONFIG, altitudeOverrideFt: 5500 }, NOTHING_SENT, ILS_04R)
        .overrides.altitude_ft,
    ).toBeUndefined();
    expect(
      instructorSetup(
        { ...CONFIG, altitudeOverride: true, altitudeOverrideFt: 5500 },
        NOTHING_SENT,
        ILS_04R,
      ).overrides.altitude_ft,
    ).toBe(5500);
  });

  it('sends no altitude_ft when the switch is on but the box is still blank', () => {
    // A ticked-but-empty override must fall back to the preview's own resolved altitude,
    // never silently send `0 ft` (ground level) by accident.
    const { overrides, overridden } = instructorSetup(
      { ...CONFIG, altitudeOverride: true, altitudeOverrideFt: null },
      NOTHING_SENT,
      ILS_04R,
    );
    expect(overrides.altitude_ft).toBeUndefined();
    expect(overridden.has('altitude_ft')).toBe(false);
  });

  it('never overrides the heading — the placement always resolves its own', () => {
    // `Placement.to_setup()` sets `heading_deg` on every placement and `execute_placement`
    // writes it regardless, so an override here could only copy the preview's own heading
    // back over itself while tagging the rail's Heading row "overridden".
    for (const send of [SEND, NOTHING_SENT]) {
      const { overrides, overridden } = instructorSetup(CONFIG, send, ILS_04R);
      expect(overrides.heading_deg).toBeUndefined();
      expect(overridden.has('heading_deg')).toBe(false);
    }
  });

  it('tunes NAV1 and the OBS from the published ILS', () => {
    const { overrides } = instructorSetup(CONFIG, SEND, ILS_04R);
    expect(overrides.nav1_freq_khz).toBe(ILS_04R.frequency_khz);
    expect(overrides.ils_freq_khz).toBe(ILS_04R.frequency_khz);
    expect(overrides.obs1_deg).toBe(ILS_04R.localizer_mag_deg);
  });

  it('sends no course and no frequency on a runway with no ILS', () => {
    // A runway's TRUE bearing is not an OBS course, and there is no magnetic variation on
    // this side of the API to convert it with — so nothing is sent rather than something
    // plausible-looking and wrong.
    const { overrides } = instructorSetup(CONFIG, SEND, null);
    expect(overrides.obs1_deg).toBeUndefined();
    expect(overrides.nav1_freq_khz).toBeUndefined();
  });
});

describe('mergedSetup', () => {
  it('is the preview’s setup when nothing was edited', () => {
    expect(mergedSetup(PREVIEW, {})).toEqual(PREVIEW.setup);
  });

  it('puts the instructor’s edits on top, field by field', () => {
    const merged = mergedSetup(PREVIEW, { ias_kt: 90 });
    expect(merged.ias_kt).toBe(90);
    expect(merged.altitude_ft).toBe(PREVIEW.setup.altitude_ft);
    expect(merged.gear_down).toBe(true);
  });

  it('survives having no preview at all', () => {
    expect(mergedSetup(undefined, { ias_kt: 90 })).toEqual({ ias_kt: 90 });
  });
});
