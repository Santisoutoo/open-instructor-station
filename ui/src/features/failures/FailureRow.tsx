import { useState } from 'react';
import { useAppDispatch } from '../../store';
import { useFailNowMutation } from './failuresApi';
import { armDraftOpened } from './failuresSlice';
import { TriggerEditor } from './TriggerEditor';
import type { ArmDraft } from './failuresSlice';
import type { FailureCatalogueEntry } from '../../api/models';

export type RowStatus = 'idle' | 'armed' | 'active';

interface FailureRowProps {
  entry: FailureCatalogueEntry;
  status: RowStatus;
  /** The panel-wide arm draft; this row expands when it is its own. */
  draft: ArmDraft | null;
}

/** Engine choices shown before "More engines…" is tapped. Matches `FailureRef`'s ge=1, le=8. */
const DEFAULT_ENGINES = [1, 2] as const;
const ALL_ENGINES = [1, 2, 3, 4, 5, 6, 7, 8] as const;

/**
 * One catalogue row: an optional engine-index picker, then Fail now and Arm… inline.
 * Arm expands the row into the trigger editor in place — never a modal. An
 * already-active failure states it and disables both actions; clearing happens on the
 * strip above. An entry the active adapter cannot produce renders disabled with its
 * `reason` inline, exactly like an unpositionable procedure leg.
 */
export function FailureRow({ entry, status, draft }: FailureRowProps) {
  const dispatch = useAppDispatch();
  const [failNow, { isLoading: failing }] = useFailNowMutation();
  const [engineIndex, setEngineIndex] = useState(1);
  const [enginesExpanded, setEnginesExpanded] = useState(false);

  const expanded = draft !== null && draft.failureId === entry.failure_id;
  const isActive = status === 'active';
  const disabled = !entry.supported;
  const selectedEngine = entry.takes_engine_index ? engineIndex : null;

  return (
    <li className="failures-row" aria-disabled={disabled}>
      <div className="failures-row__main">
        <span className="failures-row__label">{entry.label}</span>
        {entry.best_effort && <span className="failures-row__note">best effort</span>}
        <p className="failures-row__description">{entry.description}</p>
        {disabled && entry.reason !== null && (
          <p className="failures-row__reason">{entry.reason}</p>
        )}
      </div>

      {status !== 'idle' && (
        <span className={`failures-row__status failures-row__status--${status}`}>
          <span className="failures-row__status-dot" />
          {status}
        </span>
      )}

      {entry.takes_engine_index && (
        <div className="failures-row__engines" role="group" aria-label={`Engine for ${entry.label}`}>
          {(enginesExpanded ? ALL_ENGINES : DEFAULT_ENGINES).map((n) => (
            <button
              key={n}
              type="button"
              className="failures-row__engine"
              aria-pressed={n === engineIndex}
              disabled={disabled || isActive}
              onClick={() => {
                setEngineIndex(n);
              }}
            >
              {n}
            </button>
          ))}
          {!enginesExpanded && (
            <button
              type="button"
              className="failures-row__engine failures-row__engine--more"
              disabled={disabled || isActive}
              onClick={() => {
                setEnginesExpanded(true);
              }}
            >
              More…
            </button>
          )}
        </div>
      )}

      <button
        type="button"
        className="failures-row__action"
        aria-label={`Fail ${entry.label} now`}
        disabled={disabled || isActive || failing}
        onClick={() =>
          void failNow({ failure_id: entry.failure_id, engine_index: selectedEngine })
        }
      >
        Fail now
      </button>
      <button
        type="button"
        className="failures-row__action"
        aria-label={`Arm ${entry.label}`}
        aria-expanded={expanded}
        disabled={disabled || isActive}
        onClick={() => {
          dispatch(armDraftOpened({ failureId: entry.failure_id, engineIndex: selectedEngine }));
        }}
      >
        Arm…
      </button>

      {expanded && <TriggerEditor draft={draft} />}
    </li>
  );
}
