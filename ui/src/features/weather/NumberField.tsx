import { useContext, useEffect, useId, useState } from 'react';

import { WeatherValidationContext } from './weatherValidationContext';

interface NumberFieldProps {
  label: string;
  unit: string;
  value: number;
  min: number;
  max: number;
  step: number;
  disabled: boolean;
  rangeError?: string;
  exclusiveMin?: boolean;
  exclusiveMax?: boolean;
  onChange: (value: number) => void;
}

/** Keep unfinished input local while only valid numbers enter the weather draft. */
export function NumberField({
  label,
  unit,
  value,
  min,
  max,
  step,
  disabled,
  rangeError,
  exclusiveMin = false,
  exclusiveMax = false,
  onChange,
}: NumberFieldProps) {
  const id = useId();
  const report = useContext(WeatherValidationContext);
  const [draft, setDraft] = useState<{ text: string; source: number } | null>(null);
  const text = draft !== null && draft.source === value ? draft.text : String(value);
  const number = Number(text);
  const error =
    text.trim() === ''
      ? 'Enter a value.'
      : !Number.isFinite(number)
        ? 'Enter a finite number.'
        : number < min ||
            number > max ||
            (exclusiveMin && number === min) ||
            (exclusiveMax && number === max)
          ? (rangeError ??
            `Enter a value ${Number.isFinite(min) ? `from ${String(min)}` : ''}${Number.isFinite(max) ? ` up to ${String(max)}` : ' or greater'}.`)
          : null;
  useEffect(() => {
    report?.(id, error !== null);
    return () => report?.(id, false);
  }, [report, id, error]);
  return (
    <label className="weather-field" htmlFor={id}>
      <span className="weather-field__label" id={`${id}-label`}>
        {label}
        {unit === '' ? '' : ` (${unit})`}
      </span>
      <input
        id={id}
        name={label}
        type="number"
        className="weather-field__input"
        value={text}
        min={Number.isFinite(min) ? min : undefined}
        max={Number.isFinite(max) ? max : undefined}
        step="any"
        data-step={step}
        disabled={disabled}
        aria-labelledby={`${id}-label`}
        aria-invalid={error !== null}
        aria-describedby={error === null ? undefined : `${id}-error`}
        onChange={(event) => {
          const next = event.target.value;
          const parsed = Number(next);
          const valid =
            next.trim() !== '' &&
            Number.isFinite(parsed) &&
            parsed >= min &&
            parsed <= max &&
            (!exclusiveMin || parsed > min) &&
            (!exclusiveMax || parsed < max);
          setDraft({ text: next, source: valid ? parsed : value });
          if (valid) onChange(parsed);
        }}
      />
      {error !== null && (
        <span id={`${id}-error`} className="weather-field__error">
          {error}
        </span>
      )}
    </label>
  );
}
