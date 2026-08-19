import { SaveDialog } from './SaveDialog';
import { type SavedCameraPosition } from '../../api/models';

interface SavedPositionsProps {
  /** In creation order, as `GET /positions` serves them. */
  positions: readonly SavedCameraPosition[];
  /** The position last applied (`cameraSlice.selectedPositionId`). Display-only. */
  selectedPositionId: string | null;
  /** From the manifest (design D3) — gates Save and Apply, never Delete. */
  customPositionsSupported: boolean;
  /** The manifest's stated sentence when the above is false. */
  customPositionsReason: string | null;
  /**
   * True when the last requested view is `drone` — the client-side mirror of the
   * server's 409 precondition (design §7.1), informational only: the server's 409 is
   * the real gate.
   */
  droneActive: boolean;
  /** True while the camera gate is closed — every control disables, none disappears. */
  disabled: boolean;
  draftName: string;
  onDraftNameChanged: (name: string) => void;
  /** Fires with the trimmed name — `POST /positions` in the wiring wave. */
  onSaveCurrent: (name: string) => void;
  /** Fires with the position id — `POST /positions/{id}/apply` in the wiring wave. */
  onApply: (positionId: string) => void;
  /** Fires with the position id — `DELETE /positions/{id}` in the wiring wave. */
  onDelete: (positionId: string) => void;
}

/**
 * The saved-positions list: recall and delete per entry, plus the inline save-current
 * form. Saving is disabled with a stated reason when the adapter cannot position a
 * free camera (`custom_positions_supported`) or when the drone view is not the last
 * one requested — so the instructor is never surprised by a failed POST.
 */
export function SavedPositions({
  positions,
  selectedPositionId,
  customPositionsSupported,
  customPositionsReason,
  droneActive,
  disabled,
  draftName,
  onDraftNameChanged,
  onSaveCurrent,
  onApply,
  onDelete,
}: SavedPositionsProps) {
  const saveBlockedReason = !customPositionsSupported
    ? (customPositionsReason ?? 'This adapter cannot save custom camera positions.')
    : !droneActive
      ? 'Switch to the drone/free camera to save the current position.'
      : null;

  return (
    <section className="camera-positions" aria-label="Saved camera positions">
      <h3 className="camera-positions__title">Saved positions</h3>

      {positions.length === 0 ? (
        <p className="camera-positions__empty">No saved positions yet.</p>
      ) : (
        <ul className="camera-positions__list">
          {positions.map((position) => {
            const selected = position.position_id === selectedPositionId;
            return (
              <li
                key={position.position_id}
                className={
                  selected
                    ? 'camera-positions__row camera-positions__row--selected'
                    : 'camera-positions__row'
                }
                aria-current={selected || undefined}
              >
                <span className="camera-positions__name">{position.name}</span>
                <button
                  type="button"
                  className="camera-positions__apply"
                  aria-label={`Apply ${position.name}`}
                  disabled={disabled || !customPositionsSupported}
                  onClick={() => {
                    onApply(position.position_id);
                  }}
                >
                  Apply
                </button>
                <button
                  type="button"
                  className="camera-positions__delete"
                  aria-label={`Delete ${position.name}`}
                  disabled={disabled}
                  onClick={() => {
                    onDelete(position.position_id);
                  }}
                >
                  ✕
                </button>
              </li>
            );
          })}
        </ul>
      )}

      <SaveDialog
        name={draftName}
        disabled={disabled || saveBlockedReason !== null}
        onNameChanged={onDraftNameChanged}
        onSubmit={onSaveCurrent}
      />
      {saveBlockedReason !== null && (
        <p className="camera-positions__reason">{saveBlockedReason}</p>
      )}
    </section>
  );
}
