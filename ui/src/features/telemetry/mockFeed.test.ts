import { describe, expect, it } from 'vitest';
import { isAircraftState } from '../../api/models';
import { CIRCUIT_PERIOD_S, mockFrame } from './mockFeed';

describe('mockFrame', () => {
  it('is deterministic: the same instant always yields the same frame', () => {
    expect(mockFrame(123_456)).toEqual(mockFrame(123_456));
  });

  it('loops: one full period later the aircraft is back where it was', () => {
    const now = mockFrame(30_000);
    const oneLapLater = mockFrame(30_000 + CIRCUIT_PERIOD_S * 1000);
    expect(oneLapLater.latitude).toBeCloseTo(now.latitude, 10);
    expect(oneLapLater.longitude).toBeCloseTo(now.longitude, 10);
    expect(oneLapLater.altitude_ft).toBeCloseTo(now.altitude_ft, 6);
  });

  it('every sampled frame passes the WebSocket payload guard', () => {
    for (let s = 0; s < CIRCUIT_PERIOD_S; s += 5) {
      expect(isAircraftState(mockFrame(s * 1000))).toBe(true);
    }
  });

  it('stays inside the circuit envelope for a whole lap', () => {
    for (let s = 0; s < CIRCUIT_PERIOD_S; s += 1) {
      const frame = mockFrame(s * 1000);
      // Within a few nautical miles of the fictional field.
      expect(frame.latitude).toBeGreaterThan(40.3);
      expect(frame.latitude).toBeLessThan(40.6);
      expect(frame.longitude).toBeGreaterThan(-3.8);
      expect(frame.longitude).toBeLessThan(-3.4);
      expect(frame.altitude_ft).toBeGreaterThanOrEqual(2000);
      expect(frame.altitude_ft).toBeLessThanOrEqual(3000);
      expect(frame.ias_kt).toBeGreaterThan(50);
      expect(frame.ias_kt).toBeLessThan(150);
      expect(frame.heading_deg).toBeGreaterThanOrEqual(0);
      expect(frame.heading_deg).toBeLessThan(360);
    }
  });

  it('is continuous across leg boundaries — no teleports between frames', () => {
    for (let s = 0; s < CIRCUIT_PERIOD_S; s += 1) {
      const a = mockFrame(s * 1000);
      const b = mockFrame((s + 1) * 1000);
      // ~2 NM/min at 120 kt → well under 0.005° in one second.
      expect(Math.abs(b.latitude - a.latitude)).toBeLessThan(0.005);
      expect(Math.abs(b.longitude - a.longitude)).toBeLessThan(0.005);
    }
  });

  it('touches down once per lap and flies the rest', () => {
    let groundSeconds = 0;
    for (let s = 0; s < CIRCUIT_PERIOD_S; s += 1) {
      if (mockFrame(s * 1000).on_ground) {
        groundSeconds += 1;
      }
    }
    expect(groundSeconds).toBeGreaterThan(10);
    expect(groundSeconds).toBeLessThan(60);
  });

  it('descends on final: negative vertical speed while airborne and sinking', () => {
    // Mid-final sits late in the lap, just before the touch-and-go leg.
    const midFinal = mockFrame((CIRCUIT_PERIOD_S - 60) * 1000);
    expect(midFinal.on_ground).toBe(false);
    expect(midFinal.vertical_speed_fpm).toBeLessThan(-200);
    expect(midFinal.pitch_deg).toBeLessThan(0);
  });
});
