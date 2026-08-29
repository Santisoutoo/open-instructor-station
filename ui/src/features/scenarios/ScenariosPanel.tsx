/**
 * The Flight Scenario Generator panel: the catalogue with per-row availability, the
 * two-tap run, and the sticky bar tracking the run in progress.
 *
 * Selecting a card is client state (the slice); the catalogue and the run's progress are
 * both server state (RTK Query) — `useScenarioRun` decides when the latter is polled. The
 * server only ever runs one scenario at a time (design D9: a second `POST … /run` while
 * one is in progress is 409), so every card's Run button is disabled while any run is in
 * progress, not just the selected one.
 */

import { useAppDispatch, useAppSelector } from '../../store';
import { ActiveScenarioBar } from './ActiveScenarioBar';
import { errorMessage } from './errors';
import { ScenarioCard } from './ScenarioCard';
import { useGetScenariosQuery, useRunScenarioMutation } from './scenariosApi';
import { scenarioSelected } from './scenariosSlice';
import { useScenarioRun } from './useScenarioRun';
import './scenarios.css';

export function ScenariosPanel() {
  const dispatch = useAppDispatch();
  const selectedId = useAppSelector((state) => state.scenarios.selectedId);
  const { data: manifest, isLoading, isError } = useGetScenariosQuery();
  const [runScenario, runScenarioState] = useRunScenarioMutation();
  const { run, dismiss } = useScenarioRun();

  const runInProgress = run?.status === 'running';
  const runningScenarioName =
    run !== null
      ? (manifest?.scenarios.find((scenario) => scenario.id === run.scenario_id)?.name ??
        run.scenario_id)
      : null;

  return (
    <section className="panel scenarios-panel" aria-labelledby="scenarios-heading">
      <h2 id="scenarios-heading">Scenarios</h2>

      {/* Keyed by start time so a new run's bar is a fresh mount, not a reused one. */}
      {run !== null && runningScenarioName !== null && (
        <ActiveScenarioBar
          key={run.started_at}
          run={run}
          scenarioName={runningScenarioName}
          onDismiss={dismiss}
        />
      )}

      {isLoading && <p className="panel__empty">Loading scenarios…</p>}
      {isError && (
        <p className="panel__error">The scenario catalogue could not be loaded.</p>
      )}
      {runScenarioState.isError && (
        <p className="panel__error">
          {errorMessage(runScenarioState.error, 'The scenario could not be started.')}
        </p>
      )}

      {manifest !== undefined && (
        <div className="scenarios-grid">
          {manifest.scenarios.map((scenario) => (
            <ScenarioCard
              key={scenario.id}
              scenario={scenario}
              selected={scenario.id === selectedId}
              runDisabled={runInProgress || runScenarioState.isLoading}
              onSelect={() => {
                dispatch(scenarioSelected(scenario.id));
              }}
              onRun={() => {
                void runScenario(scenario.id);
              }}
            />
          ))}
        </div>
      )}
    </section>
  );
}
