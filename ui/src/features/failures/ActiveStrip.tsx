import { useAppSelector } from '../../store';
import { useClearAllFailuresMutation, useClearFailureMutation } from './failuresApi';
import { armedLive, triggerPhrase } from './format';
import { useNowMs } from './useNowMs';
import type { ActiveFailure, ArmedFailure, FailureDefinition, FailuresBoard } from './types.mock';

interface ActiveStripProps {
  board: FailuresBoard;
  catalogue: FailureDefinition[];
}

function labelFor(catalogue: FailureDefinition[], failureId: string): string {
  return (
    catalogue.find((definition) => definition.id === failureId)?.label ?? failureId
  );
}

/**
 * What is hurting the aircraft right now (red chips) and what is waiting to (amber
 * chips, with the trigger phrase and a live countdown or current value). Clear all is
 * the single largest control here on purpose, and asks no confirmation: when a lesson
 * goes wrong, resetting the aircraft in one action is the instructor-station
 * convention (feature-spec §4) — re-injecting is just as cheap.
 */
export function ActiveStrip({ board, catalogue }: ActiveStripProps) {
  const frame = useAppSelector((state) => state.telemetry.latest);
  const [clearFailure] = useClearFailureMutation();
  const [clearAllFailures] = useClearAllFailuresMutation();

  // The once-a-second clock only runs while a countdown is actually on screen.
  const nowMs = useNowMs(board.armed.some((armed) => armed.trigger.type === 'delay'));

  const empty = board.active.length === 0 && board.armed.length === 0;

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
          {board.active.map((active: ActiveFailure) => {
            const label = labelFor(catalogue, active.failureId);
            return (
              <li key={active.failureId} className="failures-chip failures-chip--active">
                <span className="failures-chip__dot" />
                <span className="failures-chip__label">{label}</span>
                <button
                  type="button"
                  className="failures-chip__clear"
                  aria-label={`Clear ${label}`}
                  onClick={() => void clearFailure(active.failureId)}
                >
                  ×
                </button>
              </li>
            );
          })}
          {board.armed.map((armed: ArmedFailure) => {
            const label = labelFor(catalogue, armed.failureId);
            return (
              <li key={armed.failureId} className="failures-chip failures-chip--armed">
                <span className="failures-chip__dot" />
                <span className="failures-chip__label">{label}</span>
                <span className="failures-chip__phrase">{triggerPhrase(armed.trigger)}</span>
                <span className="failures-chip__live">{armedLive(armed, frame, nowMs)}</span>
                <button
                  type="button"
                  className="failures-chip__clear"
                  aria-label={`Disarm ${label}`}
                  onClick={() => void clearFailure(armed.failureId)}
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
