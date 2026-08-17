/**
 * The twelve shipped scenarios, mirrored from docs/feature-spec.md §2.
 *
 * Each entry is the UI-side reflection of one declarative YAML document: the building
 * blocks it declares and the ordered plan the engine will execute (set weather →
 * configure aircraft → position aircraft → arm failures → spawn traffic). Scenarios are
 * data, never code — this file adds fixtures, not behaviour.
 *
 * Availability is a capability question, answered per adapter. The TCAS scenario is
 * deliberately unavailable in the mock: it demonstrates the greyed-out-with-reason
 * pattern the spec requires ("shown as unavailable with the reason, never offered and
 * then failed at runtime").
 */

/** A building block a scenario declares — each maps onto one manager. */
export type BuildingBlock =
  | 'position'
  | 'aircraft state'
  | 'weather'
  | 'failures'
  | 'traffic';

export interface Scenario {
  id: string;
  /** Sentence case, as shown on the card. */
  name: string;
  /** One line describing the situation the student is put into. */
  nature: string;
  /** Which managers this scenario composes. */
  blocks: BuildingBlock[];
  /** The ordered execution plan, in the engine's fixed order. */
  steps: string[];
  available: boolean;
  /** Why the scenario cannot run on the active adapter; `null` when it can. */
  unavailableReason: string | null;
}

const SET_WEATHER = 'Set weather';
const CONFIGURE_AIRCRAFT = 'Configure aircraft';
const POSITION_AIRCRAFT = 'Position aircraft';
const ARM_FAILURES = 'Arm failures';
const SPAWN_TRAFFIC = 'Spawn traffic';

export const MOCK_SCENARIOS: Scenario[] = [
  {
    id: 'engine-failure-after-v1',
    name: 'Engine failure after V1',
    nature: 'Failure timed on the take-off roll, past the decision speed',
    blocks: ['position', 'aircraft state', 'failures'],
    steps: [CONFIGURE_AIRCRAFT, POSITION_AIRCRAFT, ARM_FAILURES],
    available: true,
    unavailableReason: null,
  },
  {
    id: 'wind-shear',
    name: 'Wind shear',
    nature: 'Microburst on short final, low and slow',
    blocks: ['weather', 'position'],
    steps: [SET_WEATHER, POSITION_AIRCRAFT],
    available: true,
    unavailableReason: null,
  },
  {
    id: 'low-visibility',
    name: 'Low visibility CAT I/II/III',
    nature: 'Fog on the approach, down to the selected minima',
    blocks: ['weather', 'position'],
    steps: [SET_WEATHER, POSITION_AIRCRAFT],
    available: true,
    unavailableReason: null,
  },
  {
    id: 'crosswind-landing',
    name: 'Crosswind landing',
    nature: 'Steady crosswind at or near the demonstrated limit',
    blocks: ['weather', 'position'],
    steps: [SET_WEATHER, POSITION_AIRCRAFT],
    available: true,
    unavailableReason: null,
  },
  {
    id: 'tailwind-landing',
    name: 'Tailwind landing',
    nature: 'A final flown with the wind behind, landing distance stretched',
    blocks: ['weather', 'position'],
    steps: [SET_WEATHER, POSITION_AIRCRAFT],
    available: true,
    unavailableReason: null,
  },
  {
    id: 'bird-strike',
    name: 'Bird strike',
    nature: 'Impact on climb-out, engine damage on a trigger',
    blocks: ['position', 'failures'],
    steps: [POSITION_AIRCRAFT, ARM_FAILURES],
    available: true,
    unavailableReason: null,
  },
  {
    id: 'tcas-resolution-advisory',
    name: 'TCAS resolution advisory',
    nature: 'Converging traffic forcing a climb or descend RA',
    blocks: ['position', 'traffic'],
    steps: [POSITION_AIRCRAFT, SPAWN_TRAFFIC],
    available: false,
    unavailableReason: 'AI traffic bridge not connected (demo)',
  },
  {
    id: 'hydraulic-failure',
    name: 'Hydraulic failure',
    nature: 'Loss of a hydraulic system in cruise, degraded controls',
    blocks: ['aircraft state', 'failures'],
    steps: [CONFIGURE_AIRCRAFT, ARM_FAILURES],
    available: true,
    unavailableReason: null,
  },
  {
    id: 'electrical-failure',
    name: 'Electrical failure',
    nature: 'Generator drop-off, the aircraft on battery power',
    blocks: ['aircraft state', 'failures'],
    steps: [CONFIGURE_AIRCRAFT, ARM_FAILURES],
    available: true,
    unavailableReason: null,
  },
  {
    id: 'go-around',
    name: 'Go-around',
    nature: 'Configured on short final, primed for the missed approach',
    blocks: ['position', 'aircraft state'],
    steps: [CONFIGURE_AIRCRAFT, POSITION_AIRCRAFT],
    available: true,
    unavailableReason: null,
  },
  {
    id: 'unstable-approach',
    name: 'Unstable approach',
    nature: 'High and fast on final — the student decides whether to continue',
    blocks: ['position', 'aircraft state'],
    steps: [CONFIGURE_AIRCRAFT, POSITION_AIRCRAFT],
    available: true,
    unavailableReason: null,
  },
  {
    id: 'rejected-take-off',
    name: 'Rejected take-off',
    nature: 'Failure on the roll before V1, stop on the remaining runway',
    blocks: ['position', 'aircraft state', 'failures'],
    steps: [CONFIGURE_AIRCRAFT, POSITION_AIRCRAFT, ARM_FAILURES],
    available: true,
    unavailableReason: null,
  },
];
