interface SaveDialogProps {
  /** The draft name, held in `cameraSlice.saveDraftName` by the parent. */
  name: string;
  /** True when saving is not currently possible; the stated reason renders next to it. */
  disabled: boolean;
  onNameChanged: (name: string) => void;
  /** Fires with the trimmed name — the parent turns it into `POST /positions`. */
  onSubmit: (name: string) => void;
}

/**
 * The smallest possible save form (design §7.1): a single name input, inline rather
 * than a modal. The 1–60 character bound mirrors the server's 422 validation —
 * `maxLength` caps the top, the submit button refuses an empty trim.
 */
export function SaveDialog({ name, disabled, onNameChanged, onSubmit }: SaveDialogProps) {
  const trimmed = name.trim();

  return (
    <form
      className="camera-save"
      onSubmit={(event) => {
        event.preventDefault();
        if (trimmed !== '') {
          onSubmit(trimmed);
        }
      }}
    >
      <input
        type="text"
        className="camera-save__name"
        aria-label="Position name"
        placeholder="Position name"
        maxLength={60}
        value={name}
        disabled={disabled}
        onChange={(event) => {
          onNameChanged(event.target.value);
        }}
      />
      <button
        type="submit"
        className="camera-save__submit"
        disabled={disabled || trimmed === ''}
      >
        Save current
      </button>
    </form>
  );
}
