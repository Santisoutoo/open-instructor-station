/**
 * The strip above the catalogue while a run is live: name, elapsed time, the step
 * checklist ticking, and the one way out. Rendered only when a run exists — the panel
 * passes the run in, so the hooks here never run conditionally.
 */

import { useAppDispatch } from '../../store';
import { formatSeconds } from './format';
import { runCleared, runStopped, type ScenarioRunState } from './scenariosSlice';
import { useElapsedSeconds } from './useElapsedSeconds';

export function ActiveScenarioBar({ run }: { run: ScenarioRunState }) {
  const dispatch = useAppDispatch();
  const seconds = useElapsedSeconds(run.startedAt);
  const allDone = run.steps.every((step) => step.done);

  return (
    <div className="scenarios-bar" role="status" aria-label="Active scenario">
      <span className="scenarios-bar__name">{run.name}</span>
      <span className="scenarios-bar__elapsed">{formatSeconds(seconds)}</span>

      <ol className="scenarios-bar__steps">
        {run.steps.map((step) => (
          <li
            key={step.label}
            className={`scenarios-bar__step${step.done ? ' scenarios-bar__step--done' : ''}`}
          >
            <span className="scenarios-bar__dot" aria-hidden="true" />
            {step.label}
          </li>
        ))}
      </ol>

      {allDone && <p className="scenarios-bar__armed">Scenario armed and running</p>}

      <button
        type="button"
        className="scenarios-bar__stop"
        onClick={() => {
          dispatch(runStopped());
          dispatch(runCleared());
        }}
      >
        Stop scenario
      </button>
    </div>
  );
}
