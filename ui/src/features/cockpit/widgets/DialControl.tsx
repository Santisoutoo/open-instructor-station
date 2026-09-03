import { useState } from 'react';
import type { CockpitControlSpec } from '../../../api/models';

/** Locale pinned so the readout is identical on the tablet, the desktop and in CI. */
const NUMBER_FORMAT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });

export interface DialControlProps {
  /** `unit`/`min_value`/`max_value`/`step` are required for `kind: "dial"` (design §3.1). */
  spec: CockpitControlSpec;
  /** The confirmed value, or `null` while nothing has been read yet. */
  value: number | null;
  pending: boolean;
  onCommit: (value: number) => void;
}

/**
 * Numeric input, `±step` nudges and an explicit "Set" — the Aircraft panel's stepper
 * discipline carried over verbatim (`features/aircraft/ControlWidgets.tsx`'s
 * `StepperControl`): nothing commits on a keystroke, only on submit, because a student
 * may be hand-flying while this dial is set. `step` is a UI increment only — the
 * `readback_tolerance` is what the server actually enforces (design §3.1's own note that
 * X-Plane accepts and rounds any value).
 */
export function DialControl({ spec, value, pending, onCommit }: DialControlProps) {
  const [draft, setDraft] = useState('');
  const min = spec.min_value ?? -Infinity;
  const max = spec.max_value ?? Infinity;
  const step = spec.step ?? 1;
  const clamp = (candidate: number) => Math.min(max, Math.max(min, candidate));
  const current = value === null ? '—' : NUMBER_FORMAT.format(value);
  const unitSuffix = spec.unit === null || spec.unit === undefined ? '' : ` ${spec.unit}`;

  const nudge = (sign: 1 | -1) => {
    const draftValue = Number(draft);
    const base = draft.trim() !== '' && Number.isFinite(draftValue) ? draftValue : (value ?? min);
    setDraft(String(clamp(base + sign * step)));
  };

  const parsed = Number(draft);
  const valid = draft.trim() !== '' && Number.isFinite(parsed);

  return (
    <form
      className="control cockpit-dial"
      onSubmit={(event) => {
        event.preventDefault();
        if (valid) {
          onCommit(clamp(parsed));
          setDraft('');
        }
      }}
    >
      <output className="control__value">
        {current}
        {unitSuffix}
      </output>
      <div className="control__row">
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
        <input
          className="control__number"
          type="number"
          inputMode="decimal"
          aria-label={`${spec.label} target${unitSuffix}`}
          placeholder={current}
          min={spec.min_value ?? undefined}
          max={spec.max_value ?? undefined}
          step={step}
          value={draft}
          disabled={pending}
          onChange={(event) => {
            setDraft(event.target.value);
          }}
        />
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
      </div>
      <button className="control__button" type="submit" disabled={pending || !valid}>
        {pending ? 'Setting…' : 'Set'}
      </button>
    </form>
  );
}
