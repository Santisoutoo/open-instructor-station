/**
 * One labelled number input on the 44 px touch grid, shared by the weather editors.
 *
 * Writes clamp to the field's range instead of rejecting — an inline number input
 * cannot show an error mid-lesson, so the edges just stop, like the traffic
 * steppers. An emptied input is ignored: the value is controlled, and there is no
 * meaningful "no wind direction" to store.
 */

interface NumberFieldProps {
  label: string;
  unit: string;
  value: number;
  min: number;
  max: number;
  step: number;
  disabled: boolean;
  onChange: (value: number) => void;
}

export function NumberField({
  label,
  unit,
  value,
  min,
  max,
  step,
  disabled,
  onChange,
}: NumberFieldProps) {
  return (
    <label className="weather-field">
      <span className="weather-field__label">
        {label}
        {unit === '' ? '' : ` (${unit})`}
      </span>
      <input
        type="number"
        className="weather-field__input"
        value={Math.round(value)}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onChange={(event) => {
          const parsed = Number(event.target.value);
          if (event.target.value === '' || !Number.isFinite(parsed)) {
            return;
          }
          onChange(Math.min(max, Math.max(min, parsed)));
        }}
      />
    </label>
  );
}
