/**
 * The Aircraft Control panel's display catalogue.
 *
 * What is *generated* and what is *decided here* are deliberately split:
 *
 * - The server owns the **contract** — which controls exist (`ControlId` is the OpenAPI
 *   enum), which `AircraftSetup` field each one writes, and whether it may be written at
 *   all. `GET /api/aircraft/controls` answers the last question with a reason attached.
 * - This file owns the **presentation** — wording, ordering, widget kind, ranges and step
 *   sizes. None of that belongs in an API type.
 *
 * `Record<ControlId, …>` makes the split enforceable: a control added on the server does
 * not compile here until it is given a label and a widget.
 */

import type {
  AircraftControlManifest,
  AircraftSetup,
  AircraftState,
  ControlId,
  LightsSetup,
} from '../../api/models';

/** Every value a single control can carry. */
export type ControlValue = number | boolean;

/** One of the five exterior light switches. */
export type LightSwitch = keyof LightsSetup;

/**
 * Bookkeeping key for the optimistic write state.
 *
 * The lights are one control as far as capabilities go (they all ride on the single
 * `lights` field) but five switches as far as the instructor is concerned, so the key
 * space is wider than `ControlId`.
 */
export type WriteKey = ControlId | `lights_${LightSwitch}`;

interface ControlDisplayBase {
  /** Shown above the widget. */
  label: string;
  /** One short line under the label. Left out when the label says everything. */
  hint?: string;
}

/** Continuous 0–1 style control: a slider that commits when the instructor lets go. */
export interface SliderControlDisplay extends ControlDisplayBase {
  kind: 'slider';
  min: number;
  max: number;
  step: number;
  /** Renders the raw value for display, e.g. `0.5` -> `50 %`. */
  format: (value: number) => string;
  toSetup: ((value: number) => AircraftSetup) | null;
  readLive: ((state: AircraftState) => number) | null;
}

/** Typed value with an explicit "Set" — no stray drag ever moves the student. */
export interface StepperControlDisplay extends ControlDisplayBase {
  kind: 'stepper';
  unit: string;
  min: number;
  max: number;
  step: number;
  toSetup: ((value: number) => AircraftSetup) | null;
  readLive: ((state: AircraftState) => number) | null;
}

/** On/off control. */
export interface ToggleControlDisplay extends ControlDisplayBase {
  kind: 'toggle';
  onLabel: string;
  offLabel: string;
  toSetup: ((value: boolean) => AircraftSetup) | null;
}

/** The lights block, rendered from {@link LIGHT_SWITCHES}. */
export interface LightsControlDisplay extends ControlDisplayBase {
  kind: 'lights';
}

export type ControlDisplay =
  | SliderControlDisplay
  | StepperControlDisplay
  | ToggleControlDisplay
  | LightsControlDisplay;

const PERCENT = (value: number): string => `${String(Math.round(value * 100))} %`;

/**
 * `toSetup: null` means *this panel has no writer for that control yet* — the field it
 * would need does not exist on `AircraftSetup`. Those controls render disabled with the
 * server's own reason. Adding the field in `core/models.py` and regenerating the schema is
 * what turns them on, plus the one-line writer here.
 */
export const CONTROL_DISPLAY: Record<ControlId, ControlDisplay> = {
  // ---------------------------------------------------------------- configuration
  flaps: {
    kind: 'slider',
    label: 'Flaps',
    min: 0,
    max: 1,
    step: 0.05,
    format: PERCENT,
    toSetup: (value) => ({ flaps_ratio: value }),
    readLive: null,
  },
  speedbrake: {
    kind: 'slider',
    label: 'Speedbrake',
    min: 0,
    max: 1,
    step: 0.05,
    format: PERCENT,
    toSetup: (value) => ({ speedbrake_ratio: value }),
    readLive: null,
  },
  gear: {
    kind: 'toggle',
    label: 'Landing gear',
    onLabel: 'Down',
    offLabel: 'Up',
    toSetup: (value) => ({ gear_down: value }),
  },
  autobrake: {
    kind: 'stepper',
    label: 'Autobrake',
    hint: '0 = off',
    unit: '',
    min: 0,
    max: 5,
    step: 1,
    toSetup: (value) => ({ autobrake_level: value }),
    readLive: null,
  },
  trim: {
    kind: 'slider',
    label: 'Elevator trim',
    hint: 'Nose down to nose up',
    min: -1,
    max: 1,
    step: 0.05,
    format: (value) => value.toFixed(2),
    toSetup: null,
    readLive: null,
  },
  lights: { kind: 'lights', label: 'Exterior lights' },

  // ------------------------------------------------------------ direct flight state
  altitude: {
    kind: 'stepper',
    label: 'Altitude',
    hint: 'Written directly — not the AP selector',
    unit: 'ft',
    min: -1500,
    max: 60_000,
    step: 500,
    toSetup: (value) => ({ altitude_ft: value }),
    readLive: (state) => state.altitude_ft,
  },
  speed: {
    kind: 'stepper',
    label: 'Airspeed',
    hint: 'Written directly — not the AP selector',
    unit: 'kt',
    min: 0,
    max: 500,
    step: 5,
    toSetup: (value) => ({ ias_kt: value }),
    readLive: (state) => state.ias_kt,
  },
  vertical_speed: {
    kind: 'stepper',
    label: 'Vertical speed',
    hint: 'Written directly — not the AP selector',
    unit: 'fpm',
    min: -6000,
    max: 6000,
    step: 100,
    toSetup: (value) => ({ vertical_speed_fpm: value }),
    readLive: (state) => state.vertical_speed_fpm,
  },
  heading: {
    kind: 'stepper',
    label: 'Heading',
    hint: 'True. Written directly — not the AP selector',
    unit: '°',
    min: 0,
    max: 360,
    step: 1,
    toSetup: (value) => ({ heading_deg: value }),
    readLive: (state) => state.heading_deg,
  },

  // ------------------------------------------------------------------- autopilot
  autopilot_master: {
    kind: 'toggle',
    label: 'Autopilot',
    onLabel: 'Engaged',
    offLabel: 'Off',
    toSetup: null,
  },
  autopilot_nav: {
    kind: 'toggle',
    label: 'NAV',
    onLabel: 'Armed',
    offLabel: 'Off',
    toSetup: null,
  },
  autopilot_app: {
    kind: 'toggle',
    label: 'APP',
    onLabel: 'Armed',
    offLabel: 'Off',
    toSetup: null,
  },
  autopilot_hdg: {
    kind: 'toggle',
    label: 'HDG',
    onLabel: 'Armed',
    offLabel: 'Off',
    toSetup: null,
  },
  flight_director: {
    kind: 'toggle',
    label: 'Flight director',
    onLabel: 'On',
    offLabel: 'Off',
    toSetup: null,
  },
  target_altitude: {
    kind: 'stepper',
    label: 'AP altitude',
    unit: 'ft',
    min: 0,
    max: 60_000,
    step: 500,
    toSetup: null,
    readLive: null,
  },
  target_speed: {
    kind: 'stepper',
    label: 'AP speed',
    unit: 'kt',
    min: 0,
    max: 500,
    step: 5,
    toSetup: null,
    readLive: null,
  },
  target_heading: {
    kind: 'stepper',
    label: 'AP heading',
    unit: '°',
    min: 0,
    max: 360,
    step: 1,
    toSetup: null,
    readLive: null,
  },
  target_vertical_speed: {
    kind: 'stepper',
    label: 'AP vertical speed',
    unit: 'fpm',
    min: -6000,
    max: 6000,
    step: 100,
    toSetup: null,
    readLive: null,
  },
};

/** The five exterior switches, each with its own typed writer. */
export const LIGHT_SWITCHES: ReadonlyArray<{
  readonly name: LightSwitch;
  readonly label: string;
  readonly toSetup: (on: boolean) => AircraftSetup;
}> = [
  { name: 'landing', label: 'Landing', toSetup: (on) => ({ lights: { landing: on } }) },
  { name: 'taxi', label: 'Taxi', toSetup: (on) => ({ lights: { taxi: on } }) },
  { name: 'nav', label: 'Nav', toSetup: (on) => ({ lights: { nav: on } }) },
  { name: 'beacon', label: 'Beacon', toSetup: (on) => ({ lights: { beacon: on } }) },
  { name: 'strobe', label: 'Strobe', toSetup: (on) => ({ lights: { strobe: on } }) },
];

/** Panel layout: which controls sit under which heading, in order. */
export const CONTROL_SECTIONS: ReadonlyArray<{
  readonly title: string;
  readonly controls: readonly ControlId[];
}> = [
  {
    title: 'Configuration',
    controls: ['flaps', 'speedbrake', 'gear', 'autobrake', 'trim'],
  },
  { title: 'Flight state', controls: ['altitude', 'speed', 'vertical_speed', 'heading'] },
  {
    title: 'Autopilot',
    controls: [
      'autopilot_master',
      'flight_director',
      'autopilot_nav',
      'autopilot_app',
      'autopilot_hdg',
      'target_altitude',
      'target_speed',
      'target_heading',
      'target_vertical_speed',
    ],
  },
  { title: 'Lights', controls: ['lights'] },
];

/** Whether a control may be written, and the sentence to show the instructor when not. */
export interface ControlAvailability {
  readonly writable: boolean;
  /** Empty when writable. */
  readonly reason: string;
}

const WRITABLE: ControlAvailability = { writable: true, reason: '' };

/**
 * Resolve one control against the server's manifest.
 *
 * **Fails closed, exactly like `CapabilityList`.** No manifest — loading, unreachable
 * server, or a control the server does not list — means *disabled*, never "assume it
 * works and let the request throw" (CLAUDE.md hard rule 3).
 */
export function controlAvailability(
  id: ControlId,
  manifest: AircraftControlManifest | undefined,
  isError: boolean,
): ControlAvailability {
  if (manifest === undefined) {
    return {
      writable: false,
      reason: isError
        ? 'The control manifest could not be read — every control stays disabled.'
        : 'Waiting for the control manifest…',
    };
  }

  const entry = manifest.controls.find((control) => control.control === id);
  if (entry === undefined) {
    return {
      writable: false,
      reason: `The ${manifest.adapter} adapter does not offer this control.`,
    };
  }
  if (!entry.supported) {
    return { writable: false, reason: entry.reason ?? 'Unavailable on this adapter.' };
  }

  // The server can carry the write but this panel has no widget wired to it yet. Rare,
  // and it only happens between a `core/models.py` change and the matching UI change.
  const display = CONTROL_DISPLAY[id];
  if (display.kind !== 'lights' && display.toSetup === null) {
    return {
      writable: false,
      reason: `The server accepts ${entry.setup_field} but this panel has no control wired to it yet.`,
    };
  }
  return WRITABLE;
}
