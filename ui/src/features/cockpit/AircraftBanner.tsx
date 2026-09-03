import type { CockpitCatalogManifest } from '../../api/models';

export interface AircraftBannerProps {
  manifest: CockpitCatalogManifest;
  /** True while the state snapshot's `revision` disagrees with the catalog's (D13). */
  stale: boolean;
  refreshing: boolean;
  onRefresh: () => void;
}

/**
 * `aircraft.label` + `detection_note`, or the manifest's own `reason` with a "Re-detect
 * aircraft" button (design §7.1). Never throws on `aircraft === null` — that is simply
 * "nothing detected yet", an ordinary state per D1, not an error.
 */
export function AircraftBanner({ manifest, stale, refreshing, onRefresh }: AircraftBannerProps) {
  const aircraft = manifest.aircraft;

  return (
    <div className="cockpit-banner">
      <div className="cockpit-banner__body">
        {aircraft !== null ? (
          <>
            <span className="cockpit-banner__aircraft">{aircraft.label}</span>
            {manifest.detection_note != null && (
              <p className="cockpit-banner__note">{manifest.detection_note}</p>
            )}
          </>
        ) : (
          <p className="cockpit-banner__reason">
            {manifest.reason ?? 'No cockpit catalog is active for the loaded aircraft.'}
          </p>
        )}
        {stale && <span className="cockpit-banner__stale">Refreshing…</span>}
      </div>
      <button
        type="button"
        className="cockpit-banner__refresh"
        disabled={refreshing}
        onClick={onRefresh}
      >
        {refreshing ? 'Re-detecting…' : 'Re-detect aircraft'}
      </button>
    </div>
  );
}
