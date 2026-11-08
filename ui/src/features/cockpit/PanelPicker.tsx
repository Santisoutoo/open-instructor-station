import type { CockpitPanel } from '../../api/models';

export interface PanelPickerProps {
  /** Already sorted by `order` — the caller owns that so no other consumer re-sorts. */
  panels: readonly CockpitPanel[];
  activePanelId: string | null;
  onSelect: (panelId: string) => void;
}

/** Horizontal segmented buttons, ≥44px, scrollable on narrow tablets (design §7.1). */
export function PanelPicker({ panels, activePanelId, onSelect }: PanelPickerProps) {
  if (panels.length === 0) {
    return null;
  }

  return (
    <div className="cockpit-picker" role="tablist" aria-label="Cockpit panels">
      {panels.map((panel) => (
        <button
          key={panel.panel_id}
          type="button"
          role="tab"
          className="cockpit-picker__tab"
          aria-selected={panel.panel_id === activePanelId}
          onClick={() => {
            onSelect(panel.panel_id);
          }}
        >
          {panel.label}
        </button>
      ))}
    </div>
  );
}
