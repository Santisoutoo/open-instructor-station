/**
 * The Fuel & Payload Manager panel: presets, a tank/station editor, a mass-and-balance
 * readout, and the staging bar that previews and applies them.
 *
 * The whole body stays visible even when the gate is closed — the instructor can see
 * *what* is unavailable and *why* (per the manifest), only the editing controls and the
 * commit disable (§8.4 of the design).
 *
 * Tanks and stations are rendered from the live preview's resolved loadout once
 * something is staged, falling back to the current loadout the simulator reports
 * before anything is staged — the same "seeded from current, then the preset/overlay
 * on top" resolution `server/fuel_payload_routes.py` performs (D4).
 */

import { useAppDispatch, useAppSelector } from '../../store';
import { FuelPayloadStagingBar } from './FuelPayloadStagingBar';
import { MassAndBalanceReadout } from './MassAndBalanceReadout';
import { PresetGrid } from './PresetGrid';
import { StationEditor } from './StationEditor';
import { TankEditor } from './TankEditor';
import {
  useGetFuelPayloadManifestQuery,
  useGetFuelPayloadQuery,
  usePreviewFuelPayloadQuery,
} from './fuelPayloadApi';
import { stationEdited, tankEdited } from './fuelPayloadSlice';
import { fuelPayloadGate } from './gate';
import './fuel-payload.css';

export function FuelPayloadPanel() {
  const dispatch = useAppDispatch();
  const staged = useAppSelector((state) => state.fuelPayload.staged);

  const { data: manifest, isError: manifestFailed } = useGetFuelPayloadManifestQuery();
  const gate = fuelPayloadGate(manifest, manifestFailed);

  const { data: current } = useGetFuelPayloadQuery(undefined, { skip: !gate.open });
  const { data: preview } = usePreviewFuelPayloadQuery(staged ?? ({} as never), {
    skip: staged === null || !gate.open,
  });

  const displayedTanks = preview?.loadout.tanks ?? current?.loadout.tanks ?? [];
  const displayedStations = preview?.loadout.stations ?? current?.loadout.stations ?? [];
  const massAndBalance = preview?.mass_and_balance ?? current?.mass_and_balance ?? null;

  return (
    <section className="panel fuel-payload-panel" aria-labelledby="fuel-payload-heading">
      <h2 id="fuel-payload-heading">Fuel &amp; payload</h2>

      {!gate.open && <p className="fuel-payload-panel__blocked">{gate.reason}</p>}

      {manifest !== undefined && <PresetGrid manifest={manifest} disabled={!gate.open} />}

      <div className="fuel-payload-editors">
        <TankEditor
          tanks={displayedTanks}
          capacitiesKg={manifest?.limits?.fuel_tank_capacities_kg}
          disabled={!gate.open}
          onChange={(tanks) => {
            dispatch(tankEdited(tanks));
          }}
        />
        <StationEditor
          stations={displayedStations}
          capacitiesKg={manifest?.limits?.payload_station_capacities_kg}
          disabled={!gate.open}
          onChange={(stations) => {
            dispatch(stationEdited(stations));
          }}
        />
      </div>

      {massAndBalance !== null && (
        <MassAndBalanceReadout massAndBalance={massAndBalance} limits={manifest?.limits ?? null} />
      )}

      <FuelPayloadStagingBar />
    </section>
  );
}
