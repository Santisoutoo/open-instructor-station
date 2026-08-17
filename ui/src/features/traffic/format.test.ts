/**
 * The relative-position line, pinned to exact strings: this is what the instructor
 * reads mid-lesson, and `en-US` is pinned so the readout is identical on the tablet,
 * the desktop and CI regardless of system locale.
 */

import { describe, expect, it } from 'vitest';
import type { AircraftState } from '../../api/models';
import { absolutePositionLine, positionLine } from './format';
import { offset } from './geo';
import type { TrafficEntity } from './types.mock';

const OWN: AircraftState = {
  latitude: 40.46,
  longitude: -3.57,
  altitude_ft: 3000,
  heading_deg: 0,
  ias_kt: 120,
  vertical_speed_fpm: 0,
  pitch_deg: 0,
  roll_deg: 0,
  on_ground: false,
};

function entity(overrides: Partial<TrafficEntity> = {}): TrafficEntity {
  return {
    id: 'TFC-001',
    callsign: 'IBE1000',
    kind: 'aircraft',
    position: { lat: OWN.latitude, lon: OWN.longitude },
    altitude_ft: OWN.altitude_ft,
    heading_deg: 0,
    speed_kt: 250,
    track: [],
    ...overrides,
  };
}

describe('positionLine', () => {
  it('reads range, true bearing and signed altitude delta relative to own', () => {
    const east = entity({
      position: offset({ lat: OWN.latitude, lon: OWN.longitude }, 90, 10),
      altitude_ft: 4200,
    });

    expect(positionLine(east, OWN)).toBe('10.0 NM · bearing 090° · +1,200 ft');
  });

  it('pads the bearing to three digits, with north as 000°', () => {
    const north = entity({
      position: offset({ lat: OWN.latitude, lon: OWN.longitude }, 0, 5),
    });

    expect(positionLine(north, OWN)).toContain('bearing 000°');
  });

  it('signs a negative delta and formats thousands', () => {
    const below = entity({
      position: offset({ lat: OWN.latitude, lon: OWN.longitude }, 180, 3),
      altitude_ft: 2000,
    });

    expect(positionLine(below, OWN)).toBe('3.0 NM · bearing 180° · -1,000 ft');
  });

  it('leaves a co-altitude entity unsigned', () => {
    const level = entity({
      position: offset({ lat: OWN.latitude, lon: OWN.longitude }, 90, 2),
    });

    expect(positionLine(level, OWN)).toMatch(/· 0 ft$/);
  });

  it('degrades to the absolute position when there is no telemetry', () => {
    const alone = entity({ altitude_ft: 5000 });

    expect(positionLine(alone, null)).toBe(absolutePositionLine(alone));
  });
});

describe('absolutePositionLine', () => {
  it('formats a north-west position with hemisphere letters', () => {
    const line = absolutePositionLine(
      entity({ position: { lat: 40.46, lon: -3.57 }, altitude_ft: 5000 }),
    );

    expect(line).toBe('40.46000° N · 3.57000° W · 5,000 ft');
  });

  it('formats a south-east position with the opposite letters', () => {
    const line = absolutePositionLine(
      entity({ position: { lat: -33.9, lon: 151.2 }, altitude_ft: 21 }),
    );

    expect(line).toBe('33.90000° S · 151.20000° E · 21 ft');
  });
});
