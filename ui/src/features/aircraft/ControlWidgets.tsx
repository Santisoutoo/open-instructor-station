import { useId, useState } from 'react';
import type {
  SliderControlDisplay,
  StepperControlDisplay,
  ToggleControlDisplay,
} from './controls';

/**
 * The three widgets the Aircraft Control panel is built from.
 *
 * Shared rules, applied by all three:
 *
 * - **A disabled control states why.** `disabled` is never set without a `reason`; the
 *   reason is rendered as text (not only a tooltip — a tooltip does not exist on a tablet)
 *   and wired to the input through `aria-describedby`.
 * - **Nothing commits on drag or on keystroke.** A slider writes when the instructor lets
 *   go; a stepper writes when "Set" is pressed. There is a student flying the aeroplane.
 * - **Touch targets are at least 44 px** — this panel lives on an iPad next to the sim.
 */

interface CommonProps {
  disabled: boolean;
  /** Why it is disabled. Empty when enabled. */
  reason: string;
  /** True while a write is in flight: the widget locks and says so. */
  pending: boolean;
}

function Hint({ id, text }: { id: string; text: string }) {
  return (
    <p className="control__hint" id={id}>
      {text}
    </p>
  );
}

export interface SliderControlProps extends CommonProps {
  display: SliderControlDisplay;
  /** Current value, or `null` when nothing is known yet. */
  value: number | null;
  onCommit: (value: number) => void;
}

/**
 * Range input that commits on release.
 *
 * The dragged value is local state; only pointer-up, key-up and blur push it outwards, so
 * dragging flaps from 0 to full sends one command instead of twenty.
 */
export function SliderControl({
  display,
  value,
  disabled,
  reason,
  pending,
  onCommit,
}: SliderControlProps) {
  const inputId = useId();
  const describedById = `${inputId}-hint`;
  const [draft, setDraft] = useState<number | null>(value);
  const [syncedFrom, setSyncedFrom] = useState<number | null>(value);

  // Follow the outside world when it moves under us — adjusted during render rather than
  // in an effect, which would render once with the stale value and then again with the
  // new one. None of the slider controls appear in the telemetry feed, so `value` only
  // changes when a write of ours is confirmed or the panel is reset.
  if (value !== syncedFrom) {
    setSyncedFrom(value);
    setDraft(value);
  }

  const shown = draft ?? display.min;
  const commit = () => {
    if (!disabled && draft !== null && draft !== value) {
      onCommit(draft);
    }
  };

  return (
    <div className={`control${disabled ? ' control--disabled' : ''}`}>
      <label className="control__label" htmlFor={inputId}>
        {display.label}
      </label>
      <output className="control__value" htmlFor={inputId}>
        {value === null && draft === null ? '—' : display.format(shown)}
      </output>
      <input
        id={inputId}
        className="control__slider"
        type="range"
        min={display.min}
        max={display.max}
        step={display.step}
        value={shown}
        disabled={disabled || pending}
        aria-describedby={describedById}
        onChange={(event) => {
          setDraft(Number(event.target.value));
        }}
        onPointerUp={commit}
        onKeyUp={commit}
        onBlur={commit}
      />
      <Hint id={describedById} text={disabled ? reason : (display.hint ?? '')} />
    </div>
  );
}

/** Locale pinned so the readout is identical on the tablet, the desktop and in CI. */
const INTEGER = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });

export interface StepperControlProps extends CommonProps {
  display: StepperControlDisplay;
  /** What the aircraft reports (or was last commanded), shown as a read-only readout. */
  value: number | null;
  onCommit: (value: number) => void;
}

/**
 * Live readout plus a "what do you want it to be" field and an explicit "Set".
 *
 * The typed value is deliberately **not** seeded from the readout. Altitude, speed,
 * heading and vertical speed arrive on the WebSocket at ~4 Hz, and a field that
 * re-synchronised itself to the live value would overwrite whatever the instructor was
 * halfway through typing. The readout tracks the aircraft; the field tracks the intent;
 * neither touches the other until "Set" is pressed.
 */
export function StepperControl({
  display,
  value,
  disabled,
  reason,
  pending,
  onCommit,
}: StepperControlProps) {
  const inputId = useId();
  const describedById = `${inputId}-hint`;
  const [draft, setDraft] = useState<string>('');

  const parsed = Number(draft);
  const valid = draft.trim() !== '' && Number.isFinite(parsed);
  const current = value === null ? '—' : INTEGER.format(Math.round(value));

  return (
    <form
      className={`control${disabled ? ' control--disabled' : ''}`}
      onSubmit={(event) => {
        event.preventDefault();
        if (!disabled && valid) {
          onCommit(parsed);
          setDraft('');
        }
      }}
    >
      <label className="control__label" htmlFor={inputId}>
        {display.label}
        {display.unit === '' ? '' : ` (${display.unit})`}
      </label>
      <output className="control__value" htmlFor={inputId}>
        {current}
      </output>
      <div className="control__row">
        <input
          id={inputId}
          className="control__number"
          type="number"
          inputMode="numeric"
          placeholder={current}
          min={display.min}
          max={display.max}
          step={display.step}
          value={draft}
          disabled={disabled || pending}
          aria-describedby={describedById}
          onChange={(event) => {
            setDraft(event.target.value);
          }}
        />
        <button
          className="control__button"
          type="submit"
          disabled={disabled || pending || !valid}
        >
          {pending ? 'Setting…' : 'Set'}
        </button>
      </div>
      <Hint id={describedById} text={disabled ? reason : (display.hint ?? '')} />
    </form>
  );
}

export interface ToggleControlProps extends CommonProps {
  display: ToggleControlDisplay;
  /** `null` until the panel has commanded it once — the live feed does not carry it. */
  value: boolean | null;
  onCommit: (value: boolean) => void;
}

/** On/off button. `aria-pressed` is `false` while the state is unknown, never invented. */
export function ToggleControl({
  display,
  value,
  disabled,
  reason,
  pending,
  onCommit,
}: ToggleControlProps) {
  const buttonId = useId();
  const describedById = `${buttonId}-hint`;
  const state = value === null ? 'unknown' : value ? 'on' : 'off';

  return (
    <div className={`control${disabled ? ' control--disabled' : ''}`}>
      <span className="control__label" id={`${buttonId}-label`}>
        {display.label}
      </span>
      <button
        id={buttonId}
        className={`control__toggle control__toggle--${state}`}
        type="button"
        disabled={disabled || pending}
        aria-pressed={value ?? false}
        aria-labelledby={`${buttonId}-label`}
        aria-describedby={describedById}
        onClick={() => {
          onCommit(!(value ?? false));
        }}
      >
        {value === null ? 'Unknown' : value ? display.onLabel : display.offLabel}
      </button>
      <Hint id={describedById} text={disabled ? reason : (display.hint ?? '')} />
    </div>
  );
}
