/**
 * The Flight Scenario Generator panel: the twelve-scenario catalogue, the two-tap run,
 * and the sticky bar tracking the run in progress.
 *
 * Selecting is client state (the slice); the catalogue is server state (RTK Query).
 * Starting a run seeds the checklist from the scenario's own declared plan — the panel
 * invents no steps of its own.
 */

import { useAppDispatch, useAppSelector } from '../../store';
import { ActiveScenarioBar } from './ActiveScenarioBar';
import { ScenarioCard } from './ScenarioCard';
import { useGetScenariosQuery } from './scenariosApi';
import { runStarted, scenarioSelected } from './scenariosSlice';
import { useScenarioRun } from './useScenarioRun';
import './scenarios.css';

export function ScenariosPanel() {
  const dispatch = useAppDispatch();
  const selectedId = useAppSelector((state) => state.scenarios.selectedId);
  const runState = useAppSelector((state) => state.scenarios.runState);
  const { data: scenarios, isLoading, isError } = useGetScenariosQuery();

  useScenarioRun();

  return (
    <section className="panel scenarios-panel" aria-labelledby="scenarios-heading">
      <h2 id="scenarios-heading">Scenarios</h2>

      {/* Keyed by start time so a new run resets the elapsed counter immediately. */}
      {runState !== null && <ActiveScenarioBar key={runState.startedAt} run={runState} />}

      {isLoading && <p className="panel__empty">Loading scenarios…</p>}
      {isError && (
        <p className="panel__error">The scenario catalogue could not be loaded.</p>
      )}

      {scenarios !== undefined && (
        <div className="scenarios-grid">
          {scenarios.map((scenario) => (
            <ScenarioCard
              key={scenario.id}
              scenario={scenario}
              selected={scenario.id === selectedId}
              onSelect={() => {
                dispatch(scenarioSelected(scenario.id));
              }}
              onRun={() => {
                dispatch(
                  runStarted({
                    id: scenario.id,
                    name: scenario.name,
                    steps: scenario.steps,
                  }),
                );
              }}
            />
          ))}
        </div>
      )}
    </section>
  );
}
