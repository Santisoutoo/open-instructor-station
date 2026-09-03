import type { ParkedControl } from '../../api/models';

/**
 * A control the aircraft has but no verified mapping exists for (design D10). Rendered
 * disabled with the reason **inline, never hidden** — the `FailureRow`/`ViewGrid`
 * disabled-with-reason pattern, hard rule 3. There is no widget and no click handler at
 * all: a parked entry has nothing to actuate.
 */
export function ParkedRow({ entry }: { entry: ParkedControl }) {
  return (
    <div className="cockpit-row cockpit-row--parked" aria-disabled="true">
      <div className="cockpit-row__main">
        <span className="cockpit-row__label">{entry.label}</span>
        <p className="cockpit-row__reason">{entry.reason}</p>
      </div>
      <span className="cockpit-row__parked-badge">Parked</span>
    </div>
  );
}
