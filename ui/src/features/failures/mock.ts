/**
 * Mock fixtures for the Failures Manager.
 *
 * Everything the fake backend "serves": the availability manifest, the fifteen-entry
 * catalogue, and the builders behind the fail/arm mutations. Deterministic — no RNG —
 * so a demo replays identically and tests never flake. Dies at backend integration:
 * the real catalogue lives in `core/` and the adapter reports what it can produce.
 */

import type {
  ActiveFailure,
  ArmedFailure,
  ArmRequest,
  FailureDefinition,
  FailureSystem,
  FailuresManifest,
} from './types.mock';

/**
 * Flip to `false` in code to demo the gated state: the manifest then reports the
 * adapter as unable to inject failures and the whole panel disables with the reason
 * shown, exactly as it will against an adapter without `can_inject_failures`.
 */
export const FAILURES_AVAILABLE = true;

export function failuresManifestFixture(): FailuresManifest {
  if (!FAILURES_AVAILABLE) {
    return {
      available: false,
      reason:
        'The active adapter does not declare can_inject_failures, so failure ' +
        'injection is disabled.',
    };
  }
  return { available: true, reason: null };
}

/** Accordion order — engines first, the group instructors reach for most. */
export const SYSTEM_ORDER: readonly FailureSystem[] = [
  'engine',
  'fuel',
  'electrical',
  'avionics',
  'gear',
  'flight controls',
  'instruments',
];

/** Sentence-case group headings, keyed by system id. */
export const SYSTEM_LABELS: Readonly<Record<FailureSystem, string>> = {
  engine: 'Engine',
  fuel: 'Fuel',
  electrical: 'Electrical',
  avionics: 'Avionics',
  gear: 'Landing gear',
  'flight controls': 'Flight controls',
  instruments: 'Instruments',
};

/** The fifteen demo failures, spanning every system group. */
export const FAILURE_CATALOGUE: readonly FailureDefinition[] = [
  {
    id: 'engine-fire',
    label: 'Engine fire',
    system: 'engine',
    description: 'Fire warning and engine damage until shut down',
    bestEffort: false,
  },
  {
    id: 'engine-failure',
    label: 'Total engine failure',
    system: 'engine',
    description: 'The engine quits and will not restart on its own',
    bestEffort: false,
  },
  {
    id: 'engine-power-loss',
    label: 'Partial power loss',
    system: 'engine',
    description: 'Roughness and a fraction of rated power remaining',
    bestEffort: false,
  },
  {
    id: 'fuel-leak',
    label: 'Fuel leak',
    system: 'fuel',
    description: 'Fuel quantity drains visibly faster than burn',
    bestEffort: false,
  },
  {
    id: 'fuel-pump-failure',
    label: 'Fuel pump failure',
    system: 'fuel',
    description: 'Fuel pressure drops; gravity feed only where the type allows',
    bestEffort: false,
  },
  {
    id: 'alternator-failure',
    label: 'Alternator failure',
    system: 'electrical',
    description: 'The battery carries the load and slowly depletes',
    bestEffort: false,
  },
  {
    id: 'electrical-bus-failure',
    label: 'Main bus failure',
    system: 'electrical',
    description: 'Everything on the main bus goes dark at once',
    bestEffort: false,
  },
  {
    id: 'com1-failure',
    label: 'COM 1 radio failure',
    system: 'avionics',
    description: 'The primary radio falls silent, receive and transmit',
    bestEffort: false,
  },
  {
    id: 'transponder-failure',
    label: 'Transponder failure',
    system: 'avionics',
    description: 'No replies; ATC loses the squawk and mode C',
    bestEffort: false,
  },
  {
    id: 'gps-failure',
    label: 'GPS failure',
    system: 'avionics',
    description: 'Position source lost; navigation drops to radio aids',
    bestEffort: true,
  },
  {
    id: 'gear-jammed',
    label: 'Landing gear jammed',
    system: 'gear',
    description: 'The gear stays where it is regardless of the handle',
    bestEffort: false,
  },
  {
    id: 'brake-failure',
    label: 'Brake failure',
    system: 'gear',
    description: 'Little or no braking action on the ground',
    bestEffort: false,
  },
  {
    id: 'flaps-jammed',
    label: 'Flaps jammed',
    system: 'flight controls',
    description: 'Flaps freeze at the current setting',
    bestEffort: true,
  },
  {
    id: 'pitot-blockage',
    label: 'Pitot blockage',
    system: 'instruments',
    description: 'Airspeed indication decays into lies',
    bestEffort: false,
  },
  {
    id: 'vacuum-failure',
    label: 'Vacuum system failure',
    system: 'instruments',
    description: 'Attitude and heading gyros spin down over minutes',
    bestEffort: false,
  },
];

/** What the fail-now mutation returns: the failure in effect as of now. */
export function buildActive(failureId: string): ActiveFailure {
  return { failureId, activatedAt: Date.now() };
}

/** What the arm mutation returns: the request stamped with the arm time. */
export function buildArmed(request: ArmRequest): ArmedFailure {
  return {
    failureId: request.failureId,
    trigger: request.trigger,
    armedAt: Date.now(),
    armedPosition: request.position,
  };
}
