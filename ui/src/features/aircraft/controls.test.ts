import { describe, expect, it } from 'vitest';
import type {
  AircraftControlManifest,
  AircraftControlSupport,
  AircraftSetup,
  ControlId,
} from '../../api/models';
import {
  CONTROL_DISPLAY,
  CONTROL_SECTIONS,
  controlAvailability,
  type ControlValue,
} from './controls';

function manifest(...controls: AircraftControlSupport[]): AircraftControlManifest {
  return { adapter: 'fake', controls };
}

/** The body one control would post, or a loud failure if it has no writer. */
function setupFor(id: ControlId, value: ControlValue): AircraftSetup {
  const display = CONTROL_DISPLAY[id];
  if (display.kind === 'toggle') {
    if (display.toSetup === null || typeof value !== 'boolean') {
      throw new Error(`${id} cannot be written with ${String(value)}`);
    }
    return display.toSetup(value);
  }
  if (display.kind === 'lights' || display.toSetup === null || typeof value !== 'number') {
    throw new Error(`${id} cannot be written with ${String(value)}`);
  }
  return display.toSetup(value);
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
    // Every control has a writer today (the autopilot block gained one with issue #41),
    // so the gap is staged rather than borrowed from a real control. The branch has to
    // keep working: it is what holds the panel honest in the window between a server
    // adding a control and this file wiring a widget to it.
    const wired = CONTROL_DISPLAY.autopilot_nav;
    if (wired.kind !== 'toggle') {
      throw new Error('autopilot_nav is a toggle; this test needs updating');
    }
    CONTROL_DISPLAY.autopilot_nav = { ...wired, toSetup: null };
    try {
      const availability = controlAvailability(
        'autopilot_nav',
        manifest(supported('autopilot_nav')),
        false,
      );

      expect(availability.writable).toBe(false);
      expect(availability.reason).toMatch(/no control wired to it yet/i);
    } finally {
      CONTROL_DISPLAY.autopilot_nav = wired;
    }
  });
});

describe('the control catalogue', () => {
  it('lays out every control the panel knows about exactly once', () => {
    const laidOut = CONTROL_SECTIONS.flatMap((section) => section.controls);

    expect([...laidOut].sort()).toEqual(Object.keys(CONTROL_DISPLAY).sort());
    expect(new Set(laidOut).size).toBe(laidOut.length);
  });

  it('has a writer for every control, so nothing renders decoratively', () => {
    // The whole point of issue #41: a control with no `toSetup` is a widget the
    // instructor can see and cannot use.
    const unwired = Object.entries(CONTROL_DISPLAY)
      .filter(([, display]) => display.kind !== 'lights' && display.toSetup === null)
      .map(([id]) => id);

    expect(unwired).toEqual([]);
  });

  it('writes each autopilot control to its own AircraftSetup field', () => {
    // One assertion per control, because a copy-pasted writer pointing at the
    // neighbouring field is exactly the mistake this table invites.
    expect(setupFor('trim', 0.4)).toEqual({ elevator_trim_ratio: 0.4 });
    expect(setupFor('throttle', 0.75)).toEqual({ throttle_ratio: 0.75 });
    expect(setupFor('autopilot_master', true)).toEqual({ autopilot_master: true });
    expect(setupFor('flight_director', true)).toEqual({ flight_director: true });
    expect(setupFor('autopilot_nav', false)).toEqual({ autopilot_nav: false });
    expect(setupFor('autopilot_app', true)).toEqual({ autopilot_app: true });
    expect(setupFor('autopilot_hdg', true)).toEqual({ autopilot_hdg: true });
    expect(setupFor('target_altitude', 12_000)).toEqual({ target_altitude_ft: 12_000 });
    expect(setupFor('target_speed', 210)).toEqual({ target_ias_kt: 210 });
    expect(setupFor('target_heading', 275)).toEqual({ target_heading_deg: 275 });
    expect(setupFor('target_vertical_speed', -700)).toEqual({
      target_vertical_speed_fpm: -700,
    });
  });
});
