/**
 * The preset surface: one tile per catalogue entry (Empty, Training, Full, Ferry), one
 * tap each. Tapping a tile stages its `FuelPayloadRequest` — the staging bar below
 * previews it immediately. Nothing changes in the simulator until Apply.
 *
 * Disabled, with the reason spelled out on the tile rather than in a tooltip, when the
 * manifest's `limits_source` is `"unknown"` — a preset cannot resolve a capacity
 * fraction against capacities nobody knows (§2.2 of the design).
 */

import type { FuelPayloadManifest, FuelPayloadPresetId } from '../../api/models';
import { useAppDispatch, useAppSelector } from '../../store';
import { presetSelected } from './fuelPayloadSlice';

interface PresetGridProps {
  manifest: FuelPayloadManifest;
  /** True while the panel's own gate is closed — every tile disables, none disappears. */
  disabled: boolean;
}

/** Mirrors `server/fuel_payload_routes.py::_no_capacities_detail`'s wording. */
function capacitiesUnknownReason(
  presetId: FuelPayloadPresetId,
  manifest: FuelPayloadManifest,
): string {
  const named = manifest.icao_type !== null ? ` for ${manifest.icao_type}` : '';
  return (
    `The '${presetId}' preset needs the airframe's known tank and station capacities; ` +
    `none are published for this aircraft and no fallback table entry exists${named}.`
  );
}

export function PresetGrid({ manifest, disabled }: PresetGridProps) {
  const dispatch = useAppDispatch();
  const selectedPresetId = useAppSelector((state) => state.fuelPayload.selectedPresetId);
  const capacitiesUnknown = manifest.limits_source === 'unknown';

  return (
    <div className="fuel-payload-grid">
      {manifest.presets.map((preset) => {
        const isSelected = preset.id === selectedPresetId;
        return (
          <button
            key={preset.id}
            type="button"
            className={
              isSelected ? 'fuel-payload-tile fuel-payload-tile--staged' : 'fuel-payload-tile'
            }
            disabled={disabled || capacitiesUnknown}
            aria-pressed={isSelected}
            onClick={() => {
              dispatch(presetSelected(preset.id));
            }}
          >
            <span className="fuel-payload-tile__label">{preset.label}</span>
            <span className="fuel-payload-tile__desc">{preset.description}</span>
            {capacitiesUnknown && (
              <span className="fuel-payload-tile__reason">
                {capacitiesUnknownReason(preset.id, manifest)}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
