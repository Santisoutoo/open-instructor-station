/**
 * The staging bar — the reason this panel is safe to use during a lesson.
 *
 * Tapping a preset or editing a tank/station does not write anything. It stages a
 * `FuelPayloadRequest`; this bar previews it, shows the resolved fuel/payload/gross/CG
 * numbers and the notes explaining where they came from, and **one** button commits.
 *
 * Owns its own RTK Query hooks (preview, apply, and the manifest for its own gate) —
 * the same shape as `features/position/StagingBar.tsx`, deliberately: like Position,
 * Fuel & Payload is wired to a real backend, so the request the panel actually sends
 * is worth asserting directly against a stubbed `fetch` rather than through a mocked
 * hook.
 *
 * When the preview reports `within_envelope: false`, Apply disables until the
 * instructor explicitly ticks "Load anyway" (D8 of the design — refuse by default, an
 * explicit opt-in past a genuinely computed violation, never the default). Errors
 * render inline, never a modal.
 */

import { useEffect, useState } from 'react';
import { useAppDispatch, useAppSelector } from '../../store';
import { errorMessage } from './errors';
import {
  useApplyFuelPayloadMutation,
  useGetFuelPayloadManifestQuery,
  usePreviewFuelPayloadQuery,
} from './fuelPayloadApi';
import { fuelPayloadGate } from './gate';
import { cleared, overrideToggled } from './fuelPayloadSlice';

/** How long the confirmation stays up after a successful apply. MOTION is dialled low. */
const FLASH_MS = 2400;

export function FuelPayloadStagingBar() {
  const dispatch = useAppDispatch();
  const staged = useAppSelector((state) => state.fuelPayload.staged);
  const overrideEnvelope = useAppSelector((state) => state.fuelPayload.overrideEnvelope);

  const { data: manifest, isError: manifestFailed } = useGetFuelPayloadManifestQuery();
  const gate = fuelPayloadGate(manifest, manifestFailed);

  const {
    data: preview,
    isFetching,
    isError: previewFailed,
    error: previewError,
  } = usePreviewFuelPayloadQuery(staged ?? ({} as never), { skip: staged === null });

  const [applyFuelPayload, applyState] = useApplyFuelPayloadMutation();
  const [flash, setFlash] = useState<string | null>(null);

  useEffect(() => {
    if (flash === null) {
      return;
    }
    const handle = window.setTimeout(() => {
      setFlash(null);
    }, FLASH_MS);
    return () => {
      window.clearTimeout(handle);
    };
  }, [flash]);

  if (staged === null) {
    return (
      <section className="fuel-payload-staging fuel-payload-staging--empty" aria-label="Staged loadout">
        {flash !== null ? (
          <p className="fuel-payload-staging__flash" role="status">
            {flash}
          </p>
        ) : (
          <p className="panel__empty">
            Pick a preset or edit a tank/station above. Nothing changes until you press Apply
            loadout.
          </p>
        )}
      </section>
    );
  }

  if (previewFailed) {
    return (
      <section className="fuel-payload-staging fuel-payload-staging--error" aria-label="Staged loadout">
        <p className="panel__error">
          {errorMessage(previewError, 'This loadout could not be worked out.')}
        </p>
        <button
          type="button"
          className="fuel-payload-staging__dismiss"
          onClick={() => dispatch(cleared())}
        >
          Clear
        </button>
      </section>
    );
  }

  if (preview === undefined) {
    return (
      <section className="fuel-payload-staging" aria-label="Staged loadout">
        <p className="panel__empty">Working out the loadout…</p>
      </section>
    );
  }

  const massAndBalance = preview.mass_and_balance;
  const violated = massAndBalance.within_envelope === false;
  const applyDisabled =
    !gate.open || isFetching || applyState.isLoading || (violated && !overrideEnvelope);

  function commit() {
    if (staged === null) {
      return;
    }
    // `staged` already carries `override_envelope` — `overrideToggled` recomputes it —
    // so this sends the staged request verbatim, never a value rebuilt at commit time.
    void applyFuelPayload(staged)
      .unwrap()
      .then((result) => {
        const applied = result.state.mass_and_balance;
        setFlash(
          `Applied — ${String(Math.round(applied.gross_weight_kg))} kg gross, ` +
            `${String(Math.round(applied.fuel_kg))} kg fuel.`,
        );
        dispatch(cleared());
      })
      .catch(() => {
        // Rendered from applyState.error below; nothing to do here.
      });
  }

  const values: { label: string; value: string }[] = [
    { label: 'fuel', value: `${String(Math.round(massAndBalance.fuel_kg))} kg` },
    { label: 'payload', value: `${String(Math.round(massAndBalance.payload_kg))} kg` },
    { label: 'gross', value: `${String(Math.round(massAndBalance.gross_weight_kg))} kg` },
    {
      label: 'CG',
      value: massAndBalance.cg_arm_in == null ? 'unknown' : `${massAndBalance.cg_arm_in.toFixed(2)} in`,
    },
  ];

  return (
    <section className="fuel-payload-staging" aria-label="Staged loadout">
      <dl className="fuel-payload-staging__values">
        {values.map((entry) => (
          <div className="fuel-payload-staging__item" key={entry.label}>
            <dt className="fuel-payload-staging__key">{entry.label}</dt>
            <dd className="fuel-payload-staging__value">{entry.value}</dd>
          </div>
        ))}
      </dl>

      {preview.notes.length > 0 && (
        <ul className="fuel-payload-staging__notes">
          {preview.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}

      {violated && (
        <label className="fuel-payload-staging__override">
          <input
            type="checkbox"
            checked={overrideEnvelope}
            onChange={() => dispatch(overrideToggled())}
          />
          Load anyway — I understand this is outside the envelope
        </label>
      )}

      <div className="fuel-payload-staging__commit">
        {!gate.open && <p className="fuel-payload-staging__blocked">{gate.reason}</p>}
        {applyState.isError && (
          <p className="panel__error">
            {errorMessage(applyState.error, 'The loadout could not be applied.')}
          </p>
        )}
        {flash !== null && (
          <p className="fuel-payload-staging__flash" role="status">
            {flash}
          </p>
        )}
        <div className="fuel-payload-staging__actions">
          <button
            type="button"
            className="fuel-payload-staging__dismiss"
            disabled={applyState.isLoading}
            onClick={() => dispatch(cleared())}
          >
            Clear
          </button>
          <button
            type="button"
            className="fuel-payload-staging__apply"
            disabled={applyDisabled}
            onClick={commit}
          >
            {applyState.isLoading ? 'Applying…' : 'Apply loadout'}
          </button>
        </div>
      </div>
    </section>
  );
}
