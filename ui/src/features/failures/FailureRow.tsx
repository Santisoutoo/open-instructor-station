import { useAppDispatch } from '../../store';
import { useFailNowMutation } from './failuresApi';
import { armDraftOpened } from './failuresSlice';
import { TriggerEditor } from './TriggerEditor';
import type { ArmDraft } from './failuresSlice';
import type { FailureDefinition } from './types.mock';

export type RowStatus = 'idle' | 'armed' | 'active';

interface FailureRowProps {
  definition: FailureDefinition;
  status: RowStatus;
  /** The panel-wide arm draft; this row expands when it is its own. */
  draft: ArmDraft | null;
}

/**
 * One catalogue row: Fail now and Arm… inline. Arm expands the row into the trigger
 * editor in place — never a modal. An already-active failure states it and disables
 * both actions; clearing happens on the strip above.
 */
export function FailureRow({ definition, status, draft }: FailureRowProps) {
  const dispatch = useAppDispatch();
  const [failNow, { isLoading: failing }] = useFailNowMutation();

  const expanded = draft !== null && draft.failureId === definition.id;
  const isActive = status === 'active';

  return (
    <li className="failures-row">
      <div className="failures-row__main">
        <span className="failures-row__label">{definition.label}</span>
        {definition.bestEffort && (
          <span className="failures-row__note">best effort</span>
        )}
        <p className="failures-row__description">{definition.description}</p>
      </div>

      {status !== 'idle' && (
        <span className={`failures-row__status failures-row__status--${status}`}>
          <span className="failures-row__status-dot" />
          {status}
        </span>
      )}

      <button
        type="button"
        className="failures-row__action"
        aria-label={`Fail ${definition.label} now`}
        disabled={isActive || failing}
        onClick={() => void failNow(definition.id)}
      >
        Fail now
      </button>
      <button
        type="button"
        className="failures-row__action"
        aria-label={`Arm ${definition.label}`}
        aria-expanded={expanded}
        disabled={isActive}
        onClick={() => {
          dispatch(armDraftOpened(definition.id));
        }}
      >
        Arm…
      </button>

      {expanded && <TriggerEditor draft={draft} />}
    </li>
  );
}
