/**
 * The strip above the catalogue while a run is live or has just finished: name, elapsed
 * time, the step checklist reflecting the server's own progress
 * (`ScenarioStepStatus.status`), and a dismiss control.
 *
 * There is no cancel/abort endpoint (design §2.3, §10.6): dismissing only hides the bar
 * client-side — the run keeps going, or has already finished, on the server regardless.
 * Rendered only when a run exists, so the hooks here never run conditionally.
 */

import type { ScenarioRunStatus } from '../../api/models';
import { formatSeconds, formatStepName } from './format';
import { useElapsedSeconds } from './useElapsedSeconds';

export function ActiveScenarioBar({
  run,
  scenarioName,
  onDismiss,
}: {
  run: ScenarioRunStatus;
  scenarioName: string;
  onDismiss: () => void;
}) {
  const startedAtMs = new Date(run.started_at).getTime();
  const seconds = useElapsedSeconds(startedAtMs);

  return (
    <div className="scenarios-bar" role="status" aria-label="Active scenario">
      <span className="scenarios-bar__name">{scenarioName}</span>
      <span className="scenarios-bar__elapsed">{formatSeconds(seconds)}</span>

      <ol className="scenarios-bar__steps">
        {run.steps.map((step) => (
          <li
            key={step.name}
            className={`scenarios-bar__step scenarios-bar__step--${step.status}`}
          >
            <span className="scenarios-bar__dot" aria-hidden="true" />
            {formatStepName(step.name)}
            {step.status === 'failed' && step.error != null && (
              <span className="scenarios-bar__step-error">{step.error}</span>
            )}
          </li>
        ))}
      </ol>

      {run.status === 'completed' && (
        <p className="scenarios-bar__armed">Scenario complete</p>
      )}
      {run.status === 'failed' && (
        <p className="scenarios-bar__failed">Scenario failed</p>
      )}

      <button
        type="button"
        className="scenarios-bar__dismiss"
        onClick={onDismiss}
      >
        Dismiss
      </button>
    </div>
  );
}
