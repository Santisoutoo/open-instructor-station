import type { DiagramMode } from './positionDesignSlice';

/**
 * The 2D/3D selector above the SID/STAR procedure diagram. Same `pos-chip` styling as the
 * family/type chip rows in `SidStarTab.tsx`, but `role="group"` with `aria-pressed` rather
 * than `role="radiogroup"` with `aria-checked` — this toggles a view preference, not a filter
 * over a list of options.
 */
export function ProcedureViewToggle({
  mode,
  onSelect,
}: {
  readonly mode: DiagramMode;
  readonly onSelect: (mode: DiagramMode) => void;
}) {
  return (
    <div className="pos-sidstartab__view-toggle" role="group" aria-label="Diagram view">
      <button
        type="button"
        className={mode === '2d' ? 'pos-chip pos-chip--selected' : 'pos-chip'}
        aria-pressed={mode === '2d'}
        onClick={() => {
          onSelect('2d');
        }}
      >
        2D
      </button>
      <button
        type="button"
        className={mode === '3d' ? 'pos-chip pos-chip--selected' : 'pos-chip'}
        aria-pressed={mode === '3d'}
        onClick={() => {
          onSelect('3d');
        }}
      >
        3D
      </button>
    </div>
  );
}
