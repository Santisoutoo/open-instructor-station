/**
 * The AI Traffic panel (design §7.1): gate → live contact list on top (thumb-reachable,
 * with CLEAR ALL) → a segmented picker for the four scenario shapes → the active spawn
 * form.
 *
 * Tab-level gating only (design §7.3): `can_spawn_traffic` is a single yes/no once the
 * bridge is present — there is no per-shape capability below it. The gate fails closed
 * exactly like Failures': loading, error and a missing flag all read as "disabled, with
 * the reason stated".
 *
 * PURE-LOGIC SLICE: the spawn/despawn/clear intents terminate in the handlers below,
 * which the wiring wave replaces with the `trafficApi.ts` mutations (`injectEndpoints`,
 * design D13) once the server track has merged and `schema.d.ts` is regenerated. The
 * contact list renders the WS-fed slice, which nothing feeds yet for the same reason.
 */

import { useGetCapabilitiesQuery } from '../../api/instructorApi';
import { useAppDispatch, useAppSelector } from '../../store';
import { ApproachSequenceForm } from './ApproachSequenceForm';
import { ContactList } from './ContactList';
import { trafficGate } from './gate';
import { RunwayIncursionForm } from './RunwayIncursionForm';
import { TaxiTrafficForm } from './TaxiTrafficForm';
import { TcasConflictForm } from './TcasConflictForm';
import { shapeSelected } from './trafficSlice';
import type { TrafficScenarioShape, TrafficSpawnRequest } from './types.mock';
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
  const { contacts, connected, selectedShape } = useAppSelector(
    (state) => state.traffic,
  );

  const capabilitiesQuery = useGetCapabilitiesQuery();
  const gate = trafficGate(capabilitiesQuery.data, capabilitiesQuery.isError);

  // Wiring-wave seams: these become the trafficApi.ts mutations (spawnTraffic,
  // despawnTraffic, clearAllTraffic). Until then the intents go nowhere on purpose —
  // there is no endpoint to send them to, and inventing one here would mean
  // hand-writing API plumbing the generated client owns.
  const spawnRequested = (_request: TrafficSpawnRequest): void => undefined;
  const despawnRequested = (_trafficId: string): void => undefined;
  const clearAllRequested = (): void => undefined;

  return (
    <section className="panel traffic-panel" aria-labelledby="traffic-heading">
      <h2 id="traffic-heading">Traffic</h2>

      {!gate.open && <p className="panel__empty">{gate.reason}</p>}

      {gate.open && (
        <>
          <ContactList
            contacts={contacts}
            disabled={!gate.open}
            connected={connected}
            onDespawn={despawnRequested}
            onClearAll={clearAllRequested}
          />

          <div
            className="traffic-shapes"
            role="group"
            aria-label="Traffic scenario shape"
          >
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
            <TcasConflictForm disabled={!gate.open} onSpawn={spawnRequested} />
          )}
          {selectedShape === 'runway_incursion' && (
            <RunwayIncursionForm disabled={!gate.open} onSpawn={spawnRequested} />
          )}
          {selectedShape === 'approach_sequence' && (
            <ApproachSequenceForm disabled={!gate.open} onSpawn={spawnRequested} />
          )}
          {selectedShape === 'taxi_traffic' && (
            <TaxiTrafficForm disabled={!gate.open} onSpawn={spawnRequested} />
          )}
        </>
      )}
    </section>
  );
}
