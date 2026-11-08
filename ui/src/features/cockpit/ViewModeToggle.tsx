import type { CockpitViewMode } from './cockpitSlice';

export interface ViewModeToggleProps {
  /** The mode actually rendered — `'list'` while no schematic exists, whatever the preference. */
  mode: CockpitViewMode;
  onChange: (mode: CockpitViewMode) => void;
  /** Present when the schematic cannot be shown; the option is disabled and the reason shown. */
  disabledReason?: string;
}

const OPTIONS: readonly { readonly mode: CockpitViewMode; readonly label: string }[] = [
  { mode: 'schematic', label: 'Schematic' },
  { mode: 'list', label: 'List' },
];

/**
 * Schematic / List switch (issue #253, design §4). A radio group so the current mode is
 * announced, ≥ 44 px per option for the tablet. Hidden by the panel while a search is
 * active — search hits span panels, so only the list can show them.
 */
export function ViewModeToggle({ mode, onChange, disabledReason }: ViewModeToggleProps) {
  return (
    <div className="cockpit-viewmode" role="radiogroup" aria-label="Cockpit view">
      {OPTIONS.map((option) => {
        const disabled = option.mode === 'schematic' && disabledReason !== undefined;
        return (
          <button
            key={option.mode}
            type="button"
            role="radio"
            className="cockpit-viewmode__option"
            aria-checked={mode === option.mode}
            disabled={disabled}
            {...(disabled ? { title: disabledReason } : {})}
            onClick={() => {
              // A tap on the checked option is not a change — it must not clear the focus.
              if (mode !== option.mode) {
                onChange(option.mode);
              }
            }}
          >
            {option.label}
          </button>
        );
      })}
      {disabledReason !== undefined && (
        <span className="cockpit-viewmode__reason">{disabledReason}</span>
      )}
    </div>
  );
}
