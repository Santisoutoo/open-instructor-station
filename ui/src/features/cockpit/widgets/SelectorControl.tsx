import type { CockpitControlSpec, CockpitValue } from '../../../api/models';

export interface SelectorControlProps {
  /** `options` is required and has at least two entries for `kind: "selector"` (§3.1). */
  spec: CockpitControlSpec;
  value: CockpitValue | null;
  pending: boolean;
  onCommit: (value: number | string) => void;
}

/**
 * A segmented control of the catalog's `options`, the confirmed one highlighted. Every
 * option is one tap away — never a wrap-selecting stepper — because `core.cockpit
 * .actuation.selector_steps` may resolve a written value through `inc`/`dec` clicks on
 * the adapter side (design §5.5), but that is the adapter's problem, not the instructor's:
 * the panel always asks for the target position directly.
 */
export function SelectorControl({ spec, value, pending, onCommit }: SelectorControlProps) {
  const options = spec.options ?? [];

  return (
    <div className="cockpit-selector" role="group" aria-label={spec.label}>
      {options.map((option) => (
        <button
          key={String(option.value)}
          type="button"
          className="cockpit-selector__option"
          aria-pressed={value === option.value}
          disabled={pending}
          onClick={() => {
            onCommit(option.value);
          }}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
