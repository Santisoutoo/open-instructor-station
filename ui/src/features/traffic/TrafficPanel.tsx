/**
 * The AI Traffic panel (design §7.1): gate → live contact list on top (thumb-reachable,
 * with CLEAR ALL) → a segmented picker for the four scenario shapes → the active spawn
 * form.
 *
 * Tab-level gating only (design §7.3): `can_spawn_traffic` is a single yes/no once the
 * bridge is present — there is no per-shape capability below it. The gate fails closed:
 * loading, error and a missing flag all read as "disabled, with the reason stated".
 * **Disabled, not hidden** — hard rule 3 and Phase 3 exit criterion 3 both ask for a
 * control the instructor can see next to a sentence saying why it will not move, which a
 * removed control does not give them. Every form field, every Spawn button and every
 * despawn button therefore renders with `disabled={!gate.open}`, and the reason sits
 * above them.
 *
 * The contact list is **never gated**: `GET /api/traffic/status` and `WS /ws/traffic`
 * are capability-free by contract (design §2.1), so a station talking to a simulator
 * with no bridge sees an honest empty sky rather than an error or a blank.
 *
 * The one thing the gate cannot pre-empt is capacity (design D6): "19 of 19 slots in
 * use" is transient, so it arrives as a 409 and is surfaced as an inline error rather
 * than as a disabled control.
 */

import { useGetCapabilitiesQuery } from '../../api/instructorApi';
import { useAppDispatch, useAppSelector } from '../../store';
import { ApproachSequenceForm } from './ApproachSequenceForm';
import { ContactList } from './ContactList';
import { errorMessage } from './errors';
import { trafficGate } from './gate';
import { RunwayIncursionForm } from './RunwayIncursionForm';
import { TaxiTrafficForm } from './TaxiTrafficForm';
import { TcasConflictForm } from './TcasConflictForm';
import {
  useClearAllTrafficMutation,
  useDespawnTrafficMutation,
  useGetTrafficStatusQuery,
  useSpawnTrafficMutation,
} from './trafficApi';
import { shapeSelected } from './trafficSlice';
import type { TrafficScenarioShape, TrafficSpawnRequest } from '../../api/models';
import './traffic.css';

/** The four spawn forms, in tab order. `custom` is the map's escape hatch, not a form. */
const SHAPES: { id: TrafficScenarioShape; label: string }[] = [
  { id: 'tcas_conflict', label: 'TCAS conflict' },
  { id: 'runway_incursion', label: 'Runway incursion' },
  { id: 'approach_sequence', label: 'Approach sequence' },
  { id: 'taxi_traffic', label: 'Taxi traffic' },
];

export function TrafficPanel() {
  const dispatch = useAppDispatch();
  const streamed = useAppSelector((state) => state.traffic.contacts);
  const connected = useAppSelector((state) => state.traffic.connected);
  const selectedShape = useAppSelector((state) => state.traffic.selectedShape);

  const capabilitiesQuery = useGetCapabilitiesQuery();
  const gate = trafficGate(capabilitiesQuery.data, capabilitiesQuery.isError);
  const disabled = !gate.open;

  // Ungated on purpose: `/status` answers `contacts: []` on an adapter without traffic
  // support instead of refusing, so the list renders either way.
  const statusQuery = useGetTrafficStatusQuery();
  const [spawn, spawnState] = useSpawnTrafficMutation();
  const [despawn, despawnState] = useDespawnTrafficMutation();
  const [clearAll, clearAllState] = useClearAllTrafficMutation();

  // The stream is the live picture. `/status` is the fallback before the socket's first
  // frame and while it is down — and it is what every mutation invalidates, so a spawn
  // still shows up on a session whose socket never came up.
  const contacts = connected ? streamed : (statusQuery.data?.contacts ?? streamed);
  const capacity = statusQuery.data?.max_contacts ?? null;

  const failed = [spawnState, despawnState, clearAllState].find(
    (state) => state.error !== undefined,
  );

  const spawnRequested = (request: TrafficSpawnRequest): void => {
    void spawn(request);
  };

  return (
    <section className="panel traffic-panel" aria-labelledby="traffic-heading">
      <h2 id="traffic-heading">Traffic</h2>

      {disabled && <p className="panel__empty">{gate.reason}</p>}

      {failed !== undefined && (
        <p className="panel__error" role="alert">
          {errorMessage(failed.error, 'The traffic request failed.')}
        </p>
      )}

      <ContactList
        contacts={contacts}
        disabled={disabled}
        connected={connected}
        capacity={capacity}
        onDespawn={(trafficId) => {
          void despawn(trafficId);
        }}
        onClearAll={() => {
          void clearAll();
        }}
      />

      <div className="traffic-shapes" role="group" aria-label="Traffic scenario shape">
        {SHAPES.map((shape) => (
          <button
            key={shape.id}
            type="button"
            className="traffic-shapes__tab"
            aria-pressed={selectedShape === shape.id}
            onClick={() => {
              dispatch(shapeSelected(shape.id));
            }}
          >
            {shape.label}
          </button>
        ))}
      </div>

      {selectedShape === 'tcas_conflict' && (
        <TcasConflictForm disabled={disabled} onSpawn={spawnRequested} />
      )}
      {selectedShape === 'runway_incursion' && (
        <RunwayIncursionForm disabled={disabled} onSpawn={spawnRequested} />
      )}
      {selectedShape === 'approach_sequence' && (
        <ApproachSequenceForm disabled={disabled} onSpawn={spawnRequested} />
      )}
      {selectedShape === 'taxi_traffic' && (
        <TaxiTrafficForm disabled={disabled} onSpawn={spawnRequested} />
      )}
    </section>
  );
}
