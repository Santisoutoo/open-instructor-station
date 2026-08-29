import { CAMERA_VIEWS } from './catalogue';
import { type CameraViewId, type CameraViewSupport } from '../../api/models';

interface ViewGridProps {
  /** The manifest's per-view support entries, one per catalogue id (design D2). */
  views: readonly CameraViewSupport[];
  /**
   * The last view REQUESTED — the optimistic highlight (design D6), client state only,
   * never a server read.
   */
  activeViewId: CameraViewId | null;
  /** True while the camera gate is closed — every control disables, none disappears. */
  disabled: boolean;
  /**
   * Fires immediately on tap — momentary, no staging (design §7.1: this *is* the
   * product, one tap). The RTK Query mutation hangs off this callback in the wiring
   * wave; for now the parent decides what a tap means.
   */
  onSelectView: (viewId: CameraViewId) => void;
}

/**
 * Five large touch targets, one per named view, in catalogue order. A view the
 * manifest reports unsupported renders disabled with its `reason` inline — the
 * Failures panel's disabled-with-reason pattern, not a hidden control.
 */
export function ViewGrid({ views, activeViewId, disabled, onSelectView }: ViewGridProps) {
  const supportById = new Map(views.map((entry) => [entry.view_id, entry]));

  return (
    <div className="camera-view-grid" role="group" aria-label="Camera views">
      {CAMERA_VIEWS.map((view) => {
        // A missing manifest entry counts as unsupported — the gate posture, fail closed.
        const support = supportById.get(view.viewId);
        const supported = support?.supported ?? false;
        const reason = support?.reason ?? null;
        const active = view.viewId === activeViewId;

        return (
          <button
            key={view.viewId}
            type="button"
            className={
              active ? 'camera-view-card camera-view-card--active' : 'camera-view-card'
            }
            aria-pressed={active}
            disabled={disabled || !supported}
            onClick={() => {
              onSelectView(view.viewId);
            }}
          >
            <span className="camera-view-card__label">{view.label}</span>
            <span className="camera-view-card__description">{view.description}</span>
            {!supported && reason !== null && (
              <span className="camera-view-card__reason">{reason}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
