import { useRef, type KeyboardEvent } from 'react';
import type { CockpitControlSpec } from '../../../api/models';
import type { LayoutSlot } from '../layouts';
import {
  dialDraftValue,
  encoderDraftText,
  formatReadout,
  rotaryKeyAction,
  type RotaryDraftHandle,
} from './rotary';
import { useRepeatPress } from './useRepeatPress';
import { useRotaryDraft } from './useRotaryDraft';
import { useWheelNotches } from './useWheelNotches';

export interface RotaryControlProps {
  /** `kind: "dial"` (`unit`/`min_value`/`max_value`/`step`) or `kind: "encoder"` (`step`/`max_delta`). */
  spec: CockpitControlSpec;
  /** The confirmed read-back, or `null` while nothing has been read (or nothing can be). */
  value: number | null;
  pending: boolean;
  /** Dial → `{ value }` clamped / wrapped / snapped; encoder → `{ delta }` in clicks. */
  /**
   * A caller that returns the write's outcome keeps the draft for a retry on failure and
   * clears it on success; one that returns nothing (the plain list) clears it at once.
   */
  onCommit: (body: { value: number } | { delta: number }) => void | Promise<boolean>;
  /**
   * A parent-owned draft — the schematic tray passes `CockpitPanel`'s, so a wheel notch
   * on the diagram and a keystroke in the tray edit the same text. Omitted → the widget
   * owns one.
   */
  draft?: RotaryDraftHandle;
  /** Drawing hints for the slot: `wrap`, `detents`, `format`. */
  layout?: LayoutSlot;
}

/**
 * The one rotary widget (issue #253, design §2/§3): a dial edits a number-field draft, an
 * encoder accumulates clicks, and neither reaches the wire until `Set`/Enter — nothing
 * commits on a keystroke, a wheel notch or a `±` tap, because a student may be hand-flying
 * while this knob is turned. The readout always shows the **confirmed** value; the draft
 * is a second line beneath it.
 */
export function RotaryControl({
  spec,
  value,
  pending,
  onCommit,
  draft: parentDraft,
  layout,
}: RotaryControlProps) {
  const ownDraft = useRotaryDraft();
  const handle = parentDraft ?? ownDraft;
  // A parent-owned handle may hold another control's draft; this widget then reads clean.
  const mine = handle.isFor(spec.control_id);
  const text = mine ? handle.draft.text : '';
  const clicks = mine ? handle.draft.clicks : 0;
  const dirty = mine && (text !== '' || clicks !== 0);

  const isEncoder = spec.kind === 'encoder';
  const step = spec.step ?? 1;
  const unitSuffix = spec.unit === null || spec.unit === undefined ? '' : ` ${spec.unit}`;
  const readout = formatReadout(value, spec, layout);
  const body = handle.body(spec, layout);

  const nudge = (sign: 1 | -1, count = 1) => {
    handle.nudge(spec, layout, value, sign, count);
  };

  const commit = () => {
    if (body === null) {
      return;
    }
    const outcome = onCommit(body);
    if (outcome instanceof Promise) {
      // Issue #253: the draft survives a failed write and clears on success. The reset
      // is scoped to this control so a draft started elsewhere meanwhile is untouched.
      void outcome.then((ok) => {
        if (ok) {
          handle.reset(spec.control_id);
        }
      });
    } else {
      handle.reset(spec.control_id);
    }
  };

  const discard = () => {
    // Never wipe another control's draft through a parent-owned handle.
    handle.reset(spec.control_id);
  };

  const rowRef = useRef<HTMLDivElement>(null);
  useWheelNotches(rowRef, nudge, !pending);

  // Hold-to-repeat edits the draft only — never a commit per tick — and saturates at
  // `max_delta` both per gesture (here) and in the draft (`nudgeEncoder`).
  const maxTicks = spec.max_delta ?? 1;
  const dec = useRepeatPress(
    () => {
      nudge(-1);
    },
    maxTicks,
    pending || !isEncoder,
  );
  const inc = useRepeatPress(
    () => {
      nudge(1);
    },
    maxTicks,
    pending || !isEncoder,
  );

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    const action = rotaryKeyAction(event.key, spec, layout);
    if (action === null) {
      return;
    }
    // Prevented so a `type="number"` field's own spinner does not step a second time and
    // the form's implicit submission does not commit a second time.
    event.preventDefault();
    switch (action.kind) {
      case 'nudge':
        nudge(action.sign, action.count);
        return;
      case 'text':
        handle.setText(spec, action.text);
        return;
      case 'commit':
        commit();
        return;
      case 'discard':
        discard();
        return;
    }
  };

  const draftValue = isEncoder ? null : dialDraftValue(spec, layout, text);
  const clicksText = encoderDraftText(value, clicks, spec, layout?.format);

  return (
    <form
      className="control cockpit-rotary"
      // The widget clamps / wraps / snaps the draft itself (`dialDraftValue`). Without
      // this, a typed value off the step grid or past the range trips the number field's
      // native constraint validation, and `Set` shows a browser bubble instead of
      // committing the snapped value that Enter already sends.
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        commit();
      }}
    >
      <output className="control__value">{readout}</output>
      {!isEncoder && dirty && (
        <p className="control__hint cockpit-rotary__draft">
          → {formatReadout(draftValue, spec, layout)}
        </p>
      )}
      <div ref={rowRef} className="control__row">
        {isEncoder ? (
          <button type="button" className="control__button" disabled={pending} {...dec}>
            −
          </button>
        ) : (
          <button
            type="button"
            className="control__button"
            disabled={pending}
            onClick={() => {
              nudge(-1);
            }}
          >
            −{step}
          </button>
        )}
        {isEncoder ? (
          <input
            className="control__number"
            type="text"
            readOnly
            aria-label={`${spec.label} clicks`}
            value={clicksText}
            disabled={pending}
            onKeyDown={onKeyDown}
          />
        ) : (
          <input
            className="control__number"
            type="number"
            inputMode="decimal"
            aria-label={`${spec.label} target${unitSuffix}`}
            placeholder={readout}
            min={spec.min_value ?? undefined}
            max={spec.max_value ?? undefined}
            step={step}
            value={text}
            disabled={pending}
            onChange={(event) => {
              handle.setText(spec, event.target.value);
            }}
            onKeyDown={onKeyDown}
          />
        )}
        {isEncoder ? (
          <button type="button" className="control__button" disabled={pending} {...inc}>
            +
          </button>
        ) : (
          <button
            type="button"
            className="control__button"
            disabled={pending}
            onClick={() => {
              nudge(1);
            }}
          >
            +{step}
          </button>
        )}
      </div>
      <div className="control__row">
        <button
          className="control__button"
          type="submit"
          disabled={pending || body === null}
        >
          {pending ? 'Setting…' : 'Set'}
        </button>
        <button
          className="control__button"
          type="button"
          disabled={pending || !dirty}
          onClick={discard}
        >
          Discard
        </button>
      </div>
    </form>
  );
}
