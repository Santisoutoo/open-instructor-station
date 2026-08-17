/**
 * One row per known fuel tank: a capacity bar, a kg input, a percent readout.
 *
 * Renders from the currently *displayed* tanks — the live preview's resolved loadout
 * once something is staged, otherwise the current loadout the simulator reports. An
 * edit is computed against that same array and dispatched whole: `Loadout.tanks`
 * replaces its entire list on the wire (D10 of the design), so a one-tank edit still
 * has to carry every other tank's current value along with it.
 */

import type { TankFuel } from '../../api/models';

interface TankEditorProps {
  tanks: TankFuel[];
  /** `manifest.limits?.fuel_tank_capacities_kg`, same order as `tanks`. */
  capacitiesKg: readonly number[] | undefined;
  disabled: boolean;
  onChange: (tanks: TankFuel[]) => void;
}

export function TankEditor({ tanks, capacitiesKg, disabled, onChange }: TankEditorProps) {
  const patch = (index: number, fuelKg: number) => {
    onChange(tanks.map((tank, i) => (i === index ? { ...tank, fuel_kg: fuelKg } : tank)));
  };

  return (
    <fieldset className="fuel-payload-group">
      <legend className="fuel-payload-group__title">Fuel tanks</legend>
      {tanks.length === 0 && <p className="fuel-payload-group__empty">No known tanks.</p>}
      {tanks.map((tank, index) => {
        const capacity = capacitiesKg?.[index];
        const pct =
          capacity !== undefined && capacity > 0
            ? Math.min(100, Math.round((tank.fuel_kg / capacity) * 100))
            : null;
        return (
          <div className="fuel-payload-row" key={tank.tank_index}>
            <span className="fuel-payload-row__label">Tank {tank.tank_index + 1}</span>
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
              <span className="fuel-payload-row__field-label">Fuel kg</span>
              <input
                type="number"
                className="fuel-payload-row__input"
                value={Math.round(tank.fuel_kg)}
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
                    capacity !== undefined ? Math.min(capacity, Math.max(0, parsed)) : Math.max(0, parsed);
                  patch(index, clamped);
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
