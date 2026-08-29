import { useAppSelector } from '../../store';
import { useClearAllFailuresMutation, useClearFailureMutation, useDisarmFailureMutation } from './failuresApi';
import { armedLive, engineSuffix, triggerPhrase } from './format';
import { useNowMs } from './useNowMs';
import type {
  ActiveFailure,
  ArmedFailure,
  FailureCatalogueEntry,
  FailuresStatus,
} from '../../api/models';

interface ActiveStripProps {
  status: FailuresStatus;
  catalogue: FailureCatalogueEntry[];
}

function labelFor(catalogue: FailureCatalogueEntry[], failureId: string): string {
  return catalogue.find((entry) => entry.failure_id === failureId)?.label ?? failureId;
}

/**
 * What is hurting the aircraft right now (red chips) and what is waiting to (amber
 * chips, with the trigger phrase and a live countdown or current value). Clear all is
 * the single largest control here on purpose, and asks no confirmation: when a lesson
 * goes wrong, resetting the aircraft in one action is the instructor-station
 * convention (feature-spec §4) — re-injecting is just as cheap.
 *
 * Active and armed chips clear through different endpoints: an active failure is
 * repaired by its `(failure_id, engine_index)` ref, an armed one is disarmed by its
 * server-assigned `armed_id` — the scheduler is the only honest home for arming state
 * (D5), so there is no `failure_id` to disarm by.
 */
export function ActiveStrip({ status, catalogue }: ActiveStripProps) {
  const frame = useAppSelector((state) => state.telemetry.latest);
  const [clearFailure] = useClearFailureMutation();
  const [disarmFailure] = useDisarmFailureMutation();
  const [clearAllFailures] = useClearAllFailuresMutation();

  // The once-a-second clock only runs while a countdown is actually on screen.
  const nowMs = useNowMs(status.armed.some((armed) => armed.trigger.type === 'delay'));

  const empty = status.active.length === 0 && status.armed.length === 0;

  return (
    <div className="failures-strip">
      <div className="failures-strip__head">
        <span className="failures-strip__title">Active and armed</span>
        <button
          type="button"
          className="failures-clear-all"
          disabled={empty}
          onClick={() => void clearAllFailures()}
        >
          Clear all
        </button>
      </div>

      {empty ? (
        <p className="failures-empty">No active or armed failures.</p>
      ) : (
        <ul className="failures-chips">
          {status.active.map((active: ActiveFailure) => {
            const label = labelFor(catalogue, active.failure_id) + engineSuffix(active.engine_index);
            return (
              <li
                key={`${active.failure_id}-${String(active.engine_index)}`}
                className="failures-chip failures-chip--active"
              >
                <span className="failures-chip__dot" />
                <span className="failures-chip__label">{label}</span>
                <button
                  type="button"
                  className="failures-chip__clear"
                  aria-label={`Clear ${label}`}
                  onClick={() =>
                    void clearFailure({
                      failure_id: active.failure_id,
                      engine_index: active.engine_index ?? null,
                    })
                  }
                >
                  ×
                </button>
              </li>
            );
          })}
          {status.armed.map((armed: ArmedFailure) => {
            const label = labelFor(catalogue, armed.failure_id) + engineSuffix(armed.engine_index);
            return (
              <li key={armed.armed_id} className="failures-chip failures-chip--armed">
                <span className="failures-chip__dot" />
                <span className="failures-chip__label">{label}</span>
                <span className="failures-chip__phrase">{triggerPhrase(armed.trigger)}</span>
                <span className="failures-chip__live">{armedLive(armed, frame, nowMs)}</span>
                {armed.last_error !== null && (
                  <span className="failures-chip__error">{armed.last_error}</span>
                )}
                <button
                  type="button"
                  className="failures-chip__clear"
                  aria-label={`Disarm ${label}`}
                  onClick={() => void disarmFailure(armed.armed_id)}
                >
                  ×
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
