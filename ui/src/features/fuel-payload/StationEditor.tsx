/**
 * One row per known payload station: a kind chip (crew / passenger / cargo / other), a
 * kg input, a capacity bar.
 *
 * Same wholesale-replace edit shape as `TankEditor`: the row's whole array is rebuilt
 * from what is currently displayed and dispatched as one `PayloadStation[]`, because
 * `Loadout.stations` replaces its entire list on the wire, never merges by index (D10).
 */

import type { PayloadStation, StationKind } from '../../api/models';

const KINDS: readonly StationKind[] = ['crew', 'passenger', 'cargo', 'other'];

interface StationEditorProps {
  stations: PayloadStation[];
  /** `manifest.limits?.payload_station_capacities_kg`, same order as `stations`. */
  capacitiesKg: readonly number[] | undefined;
  disabled: boolean;
  onChange: (stations: PayloadStation[]) => void;
}

export function StationEditor({
  stations,
  capacitiesKg,
  disabled,
  onChange,
}: StationEditorProps) {
  const patch = (index: number, change: Partial<PayloadStation>) => {
    onChange(stations.map((station, i) => (i === index ? { ...station, ...change } : station)));
  };

  return (
    <fieldset className="fuel-payload-group">
      <legend className="fuel-payload-group__title">Payload stations</legend>
      {stations.length === 0 && <p className="fuel-payload-group__empty">No known stations.</p>}
      {stations.map((station, index) => {
        const capacity = capacitiesKg?.[index];
        const pct =
          capacity !== undefined && capacity > 0
            ? Math.min(100, Math.round((station.weight_kg / capacity) * 100))
            : null;
        return (
          <div className="fuel-payload-row" key={station.station_index}>
            <span className="fuel-payload-row__label">
              {station.label !== '' ? station.label : `Station ${station.station_index + 1}`}
            </span>
            <div
              className="fuel-payload-chiprow"
              role="group"
              aria-label={`Station ${String(station.station_index + 1)} kind`}
            >
              {KINDS.map((kind) => (
                <button
                  key={kind}
                  type="button"
                  className="fuel-payload-chip"
                  aria-pressed={station.kind === kind}
                  disabled={disabled}
                  onClick={() => {
                    patch(index, { kind });
                  }}
                >
                  {kind}
                </button>
              ))}
            </div>
            <div
              className="fuel-payload-row__bar"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={pct ?? 0}
            >
              <span style={{ width: `${String(pct ?? 0)}%` }} />
            </div>
            <label className="fuel-payload-row__field">
              <span className="fuel-payload-row__field-label">Weight kg</span>
              <input
                type="number"
                className="fuel-payload-row__input"
                value={Math.round(station.weight_kg)}
                min={0}
                max={capacity}
                step={1}
                disabled={disabled}
                onChange={(event) => {
                  const raw = event.target.value;
                  const parsed = Number(raw);
                  if (raw === '' || !Number.isFinite(parsed)) {
                    return;
                  }
                  const clamped =
                    capacity !== undefined
                      ? Math.min(capacity, Math.max(0, parsed))
                      : Math.max(0, parsed);
                  patch(index, { weight_kg: clamped });
                }}
              />
            </label>
            <span className="fuel-payload-row__pct">{pct === null ? '—' : `${String(pct)}%`}</span>
          </div>
        );
      })}
    </fieldset>
  );
}
