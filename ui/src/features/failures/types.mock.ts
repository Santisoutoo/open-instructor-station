/**
 * PROVISIONAL mock-only view models — replace with generated schema.d.ts types at
 * backend integration; never import outside this feature.
 *
 * These describe what the Failures Manager backend *will* serve: the catalogue that
 * lives in `core/` (feature-spec §4) filtered by what the active adapter can actually
 * produce, plus the armed/active board the server owns. Once the FastAPI endpoints
 * exist, `npm run generate:api` produces the real types and this file dies.
 */

/** The systems the accordion groups by. Sim-agnostic, from the feature-spec §4 list. */
export type FailureSystem =
  | 'engine'
  | 'fuel'
  | 'electrical'
  | 'avionics'
  | 'gear'
  | 'flight controls'
  | 'instruments';

/** One catalogue entry, as `core/` will declare it and the adapter will filter it. */
export interface FailureDefinition {
  id: string;
  /** Sentence case, shown verbatim on the row. */
  label: string;
  system: FailureSystem;
  /** One line under the label: what the student will see happen. */
  description: string;
  /**
   * True when the adapter cannot guarantee the failure takes effect — study-level
   * aircraft run their own failure systems and may ignore the simulator's (spec §4).
   */
  bestEffort: boolean;
}

export interface LatLon {
  lat: number;
  lon: number;
}

/**
 * The condition an armed failure fires on (spec §4: time, speed, altitude — plus
 * distance flown, which the scenario engine needs for "engine failure N NM out").
 */
export type FailureTrigger =
  | {
      type: 'altitude';
      altitudeFt: number;
      /** Fires only while passing the altitude in this direction. */
      sense: 'climbing' | 'descending';
    }
  | {
      type: 'ias';
      iasKt: number;
      /** `above` fires at or above the threshold, `below` at or below. */
      sense: 'above' | 'below';
    }
  | {
      type: 'delay';
      /** Seconds after arming. The only trigger that needs no telemetry. */
      delayS: number;
    }
  | {
      type: 'distance';
      /** Fires this many NM from where the aircraft was when armed. */
      distanceNm: number;
    };

export type TriggerType = FailureTrigger['type'];

/** A failure waiting on its trigger. */
export interface ArmedFailure {
  failureId: string;
  trigger: FailureTrigger;
  /** Epoch ms when armed — the delay trigger counts from here. */
  armedAt: number;
  /** Where the aircraft was at arm time; anchors the distance trigger. `null` before telemetry. */
  armedPosition: LatLon | null;
}

/** A failure currently in effect. */
export interface ActiveFailure {
  failureId: string;
  /** Epoch ms when it took effect, manually or by trigger. */
  activatedAt: number;
}

/** Everything injected or pending — what the server will own and push over WebSocket. */
export interface FailuresBoard {
  active: ActiveFailure[];
  armed: ArmedFailure[];
}

/**
 * Whether failures may be injected at all, and why not when they may not.
 * `available` mirrors the adapter's `can_inject_failures` capability.
 */
export interface FailuresManifest {
  available: boolean;
  /** Shown to the instructor verbatim when `available` is false. `null` when open. */
  reason: string | null;
}

/** What the arm mutation sends. */
export interface ArmRequest {
  failureId: string;
  trigger: FailureTrigger;
  /** Aircraft position at arm time, or `null` before the first telemetry frame. */
  position: LatLon | null;
}
