import { describe, expect, it } from 'vitest';
import type {
  AircraftControlManifest,
  AircraftControlSupport,
  ControlId,
} from '../../api/models';
import { CONTROL_DISPLAY, CONTROL_SECTIONS, controlAvailability } from './controls';

function manifest(...controls: AircraftControlSupport[]): AircraftControlManifest {
  return { adapter: 'fake', controls };
}

function supported(control: ControlId): AircraftControlSupport {
  return {
    control,
    setup_field: 'flaps_ratio',
    capability: 'can_set_aircraft_state',
    supported: true,
  };
}

describe('controlAvailability', () => {
  it('fails closed while the manifest is still loading', () => {
    const availability = controlAvailability('flaps', undefined, false);

    expect(availability.writable).toBe(false);
    expect(availability.reason).toMatch(/waiting/i);
  });

  it('fails closed when the manifest could not be read at all', () => {
    const availability = controlAvailability('flaps', undefined, true);

    expect(availability.writable).toBe(false);
    expect(availability.reason).toMatch(/could not be read/i);
  });

  it('enables a control the server declares supported', () => {
    expect(controlAvailability('flaps', manifest(supported('flaps')), false)).toEqual({
      writable: true,
      reason: '',
    });
  });

  it("repeats the server's own reason for a control it declares unsupported", () => {
    const unsupported = manifest({
      control: 'flaps',
      setup_field: 'flaps_ratio',
      capability: 'can_set_aircraft_state',
      supported: false,
      reason: "The 'xplane' adapter does not declare can_set_aircraft_state.",
    });

    expect(controlAvailability('flaps', unsupported, false)).toEqual({
      writable: false,
      reason: "The 'xplane' adapter does not declare can_set_aircraft_state.",
    });
  });

  it('fails closed for a control the manifest does not mention', () => {
    const availability = controlAvailability('flaps', manifest(), false);

    expect(availability.writable).toBe(false);
    expect(availability.reason).toMatch(/does not offer this control/i);
  });

  it('still disables a supported control this panel has no writer for', () => {
    // The autopilot block is exactly this case today: the moment `AircraftSetup` grows
    // the fields, the server will call it supported while the widget is still unwired.
    const availability = controlAvailability(
      'autopilot_nav',
      manifest(supported('autopilot_nav')),
      false,
    );

    expect(availability.writable).toBe(false);
    expect(availability.reason).toMatch(/no control wired to it yet/i);
  });
});

describe('the control catalogue', () => {
  it('lays out every control the panel knows about exactly once', () => {
    const laidOut = CONTROL_SECTIONS.flatMap((section) => section.controls);

    expect([...laidOut].sort()).toEqual(Object.keys(CONTROL_DISPLAY).sort());
    expect(new Set(laidOut).size).toBe(laidOut.length);
  });
});
