import type { CockpitControlSpec } from '../../../api/models';

/**
 * A two-state switch showing the **confirmed** value, never the optimistic click
 * (design §7.1's acceptance for #221). `value` is `null` until the first snapshot names
 * this control or its own actuation's read-back has not landed yet; the button then
 * reads "Unknown" rather than guessing a side.
 *
 * The `pending` lock (design §7.2) is what keeps the widget from racing a second tap
 * against its own in-flight write — `aria-pressed` still reflects the last confirmed
 * value while locked, never the requested one.
 */
export interface ToggleControlProps {
  spec: CockpitControlSpec;
  value: boolean | null;
  pending: boolean;
  onCommit: (value: boolean) => void;
}

export function ToggleControl({ spec, value, pending, onCommit }: ToggleControlProps) {
  const state = value === null ? 'unknown' : value ? 'on' : 'off';

  return (
    <button
      type="button"
      className={`control__toggle control__toggle--${state}`}
      disabled={pending}
      aria-pressed={value ?? false}
      onClick={() => {
        onCommit(!(value ?? false));
      }}
    >
      {pending ? 'Setting…' : value === null ? 'Unknown' : value ? spec.on_label : spec.off_label}
    </button>
  );
}
