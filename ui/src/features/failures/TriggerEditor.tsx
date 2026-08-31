import { useAppDispatch, useAppSelector } from '../../store';
import { useArmFailureMutation } from './failuresApi';
import { armDraftClosed, armDraftTriggerChanged, armDraftTypeChanged } from './failuresSlice';
import { editorNow } from './format';
import { TRIGGER_TYPES } from './triggers';
import type { ArmDraft } from './failuresSlice';
import type { FailureTrigger, FailureTriggerType } from '../../api/models';

const TYPE_LABELS: Readonly<Record<FailureTriggerType, string>> = {
  altitude_above: 'At or above altitude',
  altitude_below: 'At or below altitude',
  speed_above: 'At or above IAS',
  speed_below: 'At or below IAS',
  delay: 'After delay',
};

interface TriggerEditorProps {
  draft: ArmDraft;
}

/**
 * The inline arm editor a row expands into — never a modal. One segmented row of
 * trigger types, the threshold with the live "now:" reading beside it (D7's honesty
 * affordance — a condition that would fire immediately is visible before Arm is
 * tapped), and the one solid-accent primary of the panel: Arm failure.
 */
export function TriggerEditor({ draft }: TriggerEditorProps) {
  const dispatch = useAppDispatch();
  const frame = useAppSelector((state) => state.telemetry.latest);
  const [armFailure, { isLoading }] = useArmFailureMutation();

  const trigger = draft.trigger;
  const now = editorNow(trigger.type, frame);

  const change = (next: FailureTrigger) => {
    dispatch(armDraftTriggerChanged(next));
  };

  /** Number inputs guard the parse: an empty or partial field changes nothing. */
  const numeric = (raw: string, apply: (value: number) => FailureTrigger) => {
    const value = Number(raw);
    if (Number.isFinite(value)) {
      change(apply(value));
    }
  };

  const arm = async () => {
    await armFailure({
      failure_id: draft.failureId,
      engine_index: draft.engineIndex,
      trigger,
    });
    dispatch(armDraftClosed());
  };

  return (
    <div className="failures-editor">
      <div className="failures-editor__types" role="group" aria-label="Trigger type">
        {TRIGGER_TYPES.map((type) => (
          <button
            key={type}
            type="button"
            className="failures-editor__type"
            aria-pressed={type === trigger.type}
            onClick={() => {
              if (type !== trigger.type) {
                dispatch(armDraftTypeChanged(type));
              }
            }}
          >
            {TYPE_LABELS[type]}
          </button>
        ))}
      </div>

      <div className="failures-editor__fields">
        {(trigger.type === 'altitude_above' || trigger.type === 'altitude_below') && (
          <label className="failures-editor__field">
            <span className="failures-editor__field-label">Altitude (ft MSL)</span>
            <input
              type="number"
              className="failures-editor__input"
              value={trigger.altitude_ft}
              min={-2000}
              max={100_000}
              step={100}
              onChange={(event) => {
                numeric(event.target.value, (altitude_ft) => ({ ...trigger, altitude_ft }));
              }}
            />
          </label>
        )}

        {(trigger.type === 'speed_above' || trigger.type === 'speed_below') && (
          <label className="failures-editor__field">
            <span className="failures-editor__field-label">IAS (kt)</span>
            <input
              type="number"
              className="failures-editor__input"
              value={trigger.ias_kt}
              min={0}
              max={500}
              step={5}
              onChange={(event) => {
                numeric(event.target.value, (ias_kt) => ({ ...trigger, ias_kt }));
              }}
            />
          </label>
        )}

        {trigger.type === 'delay' && (
          <label className="failures-editor__field">
            <span className="failures-editor__field-label">Delay (s)</span>
            <input
              type="number"
              className="failures-editor__input"
              value={trigger.delay_s}
              min={1}
              max={86_400}
              step={5}
              onChange={(event) => {
                numeric(event.target.value, (delay_s) => ({ ...trigger, delay_s }));
              }}
            />
          </label>
        )}

        {now !== null && <span className="failures-editor__now">{now}</span>}
      </div>

      <div className="failures-editor__actions">
        <button
          type="button"
          className="failures-editor__arm"
          disabled={isLoading}
          onClick={() => void arm()}
        >
          Arm failure
        </button>
        <button
          type="button"
          className="failures-editor__cancel"
          onClick={() => {
            dispatch(armDraftClosed());
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
