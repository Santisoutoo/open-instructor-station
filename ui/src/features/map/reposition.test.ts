/**
 * D6, tested at the decision: a staged map point carries the aircraft's own last
 * telemetry frame — altitude, heading, IAS — onto the new coordinates, and only an
 * instructor who has never received a frame gets the bare ground-point defaults.
 */

import { describe, expect, it } from 'vitest';
import type { AircraftState } from '../../api/models';
import { defaultCoordinateRequest } from './reposition';

const CRUISE: AircraftState = {
  latitude: 40.49,
  longitude: -3.56,
  altitude_ft: 3000,
  heading_deg: 90,
  ias_kt: 250,
  vertical_speed_fpm: 0,
  pitch_deg: 0,
  roll_deg: 0,
  on_ground: false,
};

describe('defaultCoordinateRequest', () => {
  it('carries altitude, heading and IAS verbatim from the telemetry frame', () => {
    const request = defaultCoordinateRequest({ lat: 40.46, lon: -3.57 }, CRUISE);

    expect(request).toEqual({
      type: 'coordinate',
      position: { latitude: 40.46, longitude: -3.57, altitude_ft: 3000 },
      heading_deg: 90,
      ias_kt: 250,
    });
  });

  it('takes the point from the map, never from the frame', () => {
    const request = defaultCoordinateRequest({ lat: 51.47, lon: -0.46 }, CRUISE);

    expect(request.position.latitude).toBe(51.47);
    expect(request.position.longitude).toBe(-0.46);
  });

  it('defaults to a ground point with nothing to carry when telemetry is null', () => {
    const request = defaultCoordinateRequest({ lat: 40.46, lon: -3.57 }, null);

    expect(request).toEqual({
      type: 'coordinate',
      position: { latitude: 40.46, longitude: -3.57, altitude_ft: 0 },
      heading_deg: null,
      ias_kt: null,
    });
  });
});
