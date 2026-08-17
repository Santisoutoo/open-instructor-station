import { useAppDispatch, useAppSelector } from '../../store';
import { useArmFailureMutation } from './failuresApi';
import { armDraftClosed, armDraftTriggerChanged, armDraftTypeChanged } from './failuresSlice';
import { editorNow } from './format';
import { TRIGGER_TYPES } from './triggers';
import type { ArmDraft } from './failuresSlice';
import type { FailureTrigger, TriggerType } from './types.mock';

const TYPE_LABELS: Readonly<Record<TriggerType, string>> = {
  altitude: 'At altitude',
  ias: 'At IAS',
  delay: 'After delay',
  distance: 'At distance',
};

interface TriggerEditorProps {
  draft: ArmDraft;
}

/**
 * The inline arm editor a row expands into — never a modal. One segmented row of
 * trigger types, the threshold with the live "now:" reading beside it, and the one
 * solid-accent primary of the panel: Arm failure.
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
      failureId: draft.failureId,
      trigger,
      position: frame === null ? null : { lat: frame.latitude, lon: frame.longitude },
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
        {trigger.type === 'altitude' && (
          <>
            <label className="failures-editor__field">
              <span className="failures-editor__field-label">Altitude (ft)</span>
              <input
                type="number"
                className="failures-editor__input"
                value={trigger.altitudeFt}
                min={0}
                step={100}
                onChange={(event) => {
                  numeric(event.target.value, (altitudeFt) => ({
                    ...trigger,
                    altitudeFt,
                  }));
                }}
              />
            </label>
            <label className="failures-editor__field">
              <span className="failures-editor__field-label">While</span>
              <select
                className="failures-editor__select"
                value={trigger.sense}
                onChange={(event) => {
                  change({
                    ...trigger,
                    sense: event.target.value === 'descending' ? 'descending' : 'climbing',
                  });
                }}
              >
                <option value="climbing">Climbing</option>
                <option value="descending">Descending</option>
              </select>
            </label>
          </>
        )}

        {trigger.type === 'ias' && (
          <>
            <label className="failures-editor__field">
              <span className="failures-editor__field-label">IAS (kt)</span>
              <input
                type="number"
                className="failures-editor__input"
                value={trigger.iasKt}
                min={0}
                step={5}
                onChange={(event) => {
                  numeric(event.target.value, (iasKt) => ({ ...trigger, iasKt }));
                }}
              />
            </label>
            <label className="failures-editor__field">
              <span className="failures-editor__field-label">Fires</span>
              <select
                className="failures-editor__select"
                value={trigger.sense}
                onChange={(event) => {
                  change({
                    ...trigger,
                    sense: event.target.value === 'below' ? 'below' : 'above',
                  });
                }}
              >
                <option value="above">At or above</option>
                <option value="below">At or below</option>
              </select>
            </label>
          </>
        )}

        {trigger.type === 'delay' && (
          <label className="failures-editor__field">
            <span className="failures-editor__field-label">Delay (s)</span>
            <input
              type="number"
              className="failures-editor__input"
              value={trigger.delayS}
              min={1}
              step={5}
              onChange={(event) => {
                numeric(event.target.value, (delayS) => ({ ...trigger, delayS }));
              }}
            />
          </label>
        )}

        {trigger.type === 'distance' && (
          <label className="failures-editor__field">
            <span className="failures-editor__field-label">Distance (NM)</span>
            <input
              type="number"
              className="failures-editor__input"
              value={trigger.distanceNm}
              min={0.5}
              step={0.5}
              onChange={(event) => {
                numeric(event.target.value, (distanceNm) => ({ ...trigger, distanceNm }));
              }}
            />
          </label>
        )}

        {now !== null && <span className="failures-editor__now">{now}</span>}
      </div>

      {trigger.type === 'distance' && (
        <p className="failures-editor__hint">
          Measured from where the aircraft is at the moment of arming.
        </p>
      )}

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
