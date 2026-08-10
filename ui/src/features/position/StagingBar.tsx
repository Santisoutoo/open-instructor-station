/**
 * The staging bar — the reason this panel is safe to use during a lesson.
 *
 * Selecting a placement anywhere in the panel does not move the aircraft. It stages it
 * here: the server's preview arrives, the diagram is drawn, the numbers appear with a note
 * saying where each one came from, and **one** button commits. The incumbent product
 * teleports on the first click of a tile, mid-flight, with no way back; this exists to not
 * do that.
 *
 * Two rules the rest of the panel depends on:
 *
 * - **Edits re-ask the server.** Changing the altitude re-runs `preview`, so the diagram
 *   and the notes stay true to what will actually be applied. The panel never recomputes
 *   geometry it has no business knowing.
 * - **Errors render here, inline.** Never a modal. A stacking modal dialog over a running
 *   lesson is the incumbent's worst habit.
 */

import { useEffect, useState } from 'react';
import {
  useApplyPlacementMutation,
  useGetCapabilitiesQuery,
  usePreviewPlacementQuery,
} from '../../api/instructorApi';
import type { AircraftSetup } from '../../api/models';
import { useAppDispatch, useAppSelector } from '../../store';
import { Schematic } from './Schematic';
import { errorMessage } from './errors';
import { commitGate } from './gate';
import { formatAltitudeFt, formatSpeedKt } from './placements';
import { setupOverridden, staleCleared } from './positionSlice';

/** How long the confirmation stays up after a successful commit. MOTION is dialled low. */
const FLASH_MS = 2400;

/**
 * One editable number, with the provenance of its default underneath.
 *
 * **Rounded for display.** A 3° glidepath 10 NM out works out at 4184.357192657228 ft, and
 * showing an instructor twelve decimal places of a figure they are about to round to the
 * nearest hundred is noise pretending to be precision. Rounding here is safe because an
 * untouched field is never sent — the overlay carries only what was actually edited, so the
 * server's own full-precision value is what gets applied.
 */
function EditableNumber({
  label,
  unit,
  value,
  note,
  disabled,
  onChange,
}: {
  label: string;
  unit: string;
  value: number | null | undefined;
  note: string | undefined;
  disabled: boolean;
  onChange: (value: number | null) => void;
}) {
  return (
    <label className="staging__field">
      <span className="staging__field-label">{label}</span>
      <span className="staging__field-input">
        <input
          type="number"
          className="staging__number"
          value={value == null ? '' : Math.round(value)}
          disabled={disabled}
          onChange={(event) => {
            const raw = event.target.value;
            onChange(raw === '' ? null : Number(raw));
          }}
        />
        <span className="staging__field-unit">{unit}</span>
      </span>
      {note !== undefined && <span className="staging__field-note">{note}</span>}
    </label>
  );
}

export function StagingBar() {
  const dispatch = useAppDispatch();
  const staged = useAppSelector((state) => state.position.staged);
  const overrides = useAppSelector((state) => state.position.setupOverrides);

  const { data: capabilities, isError: capabilitiesFailed } = useGetCapabilitiesQuery();
  const gate = commitGate(capabilities, capabilitiesFailed);

  const {
    data: preview,
    isFetching,
    isError: previewFailed,
    error: previewError,
  } = usePreviewPlacementQuery(staged ?? ({} as never), { skip: staged === null });

  const [applyPlacement, applyState] = useApplyPlacementMutation();
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
      <section className="staging staging--empty" aria-label="Staged placement">
        <p className="panel__empty">
          Pick a placement above. Nothing moves until you press Place aircraft.
        </p>
      </section>
    );
  }

  if (previewFailed) {
    return (
      <section className="staging staging--error" aria-label="Staged placement">
        <p className="panel__error">
          {errorMessage(previewError, 'This placement could not be worked out.')}
        </p>
        <button
          type="button"
          className="staging__dismiss"
          onClick={() => dispatch(staleCleared())}
        >
          Clear
        </button>
      </section>
    );
  }

  if (preview === undefined) {
    return (
      <section className="staging" aria-label="Staged placement">
        <p className="panel__empty">Working out the placement…</p>
      </section>
    );
  }

  // The instructor's edits sit on top of the geometry's, never instead of it.
  const merged: AircraftSetup = { ...preview.setup, ...overrides };
  const noteFor = (needle: string): string | undefined =>
    preview.notes.find((note) => note.toLowerCase().includes(needle));

  function commit() {
    if (staged === null) {
      return;
    }
    void applyPlacement({
      placement: staged,
      setup: Object.keys(overrides).length === 0 ? null : overrides,
    })
      .unwrap()
      .then((result) => {
        setFlash(
          `Placed at ${formatAltitudeFt(result.state.altitude_ft)}, ` +
            `${formatSpeedKt(result.state.ias_kt)}.`,
        );
      })
      .catch(() => {
        // Rendered from applyState.error below; nothing to do here.
      });
  }

  return (
    <section className="staging" aria-label="Staged placement">
      <div className="staging__diagram">
        <Schematic
          schematic={preview.schematic}
          headingDeg={preview.placement.heading_deg}
        />
        <p className="staging__label">{preview.placement.label}</p>
      </div>

      <div className="staging__fields">
        <EditableNumber
          label="Altitude"
          unit="ft"
          value={merged.altitude_ft}
          note={noteFor('glidepath') ?? noteFor('constraint') ?? noteFor('circuit')}
          disabled={!gate.open}
          onChange={(value) => {
            dispatch(setupOverridden({ field: 'altitude_ft', value }));
          }}
        />
        <EditableNumber
          label="Airspeed"
          unit="kt"
          value={merged.ias_kt}
          note={noteFor('kt')}
          disabled={!gate.open}
          onChange={(value) => {
            dispatch(setupOverridden({ field: 'ias_kt', value }));
          }}
        />
        <EditableNumber
          label="Heading"
          unit="°"
          value={merged.heading_deg}
          note="True, down the placement's own track."
          disabled={!gate.open}
          onChange={(value) => {
            dispatch(setupOverridden({ field: 'heading_deg', value }));
          }}
        />
        <label className="staging__field staging__field--toggle">
          <span className="staging__field-label">Landing gear</span>
          <button
            type="button"
            className={`staging__toggle${merged.gear_down === true ? ' staging__toggle--on' : ''}`}
            aria-pressed={merged.gear_down === true}
            disabled={!gate.open}
            onClick={() => {
              dispatch(
                setupOverridden({ field: 'gear_down', value: merged.gear_down !== true }),
              );
            }}
          >
            {merged.gear_down === true ? 'Down' : 'Up'}
          </button>
        </label>
      </div>

      <div className="staging__commit">
        {!gate.open && <p className="staging__blocked">{gate.reason}</p>}
        {applyState.isError && (
          <p className="panel__error">
            {errorMessage(applyState.error, 'The placement could not be applied.')}
          </p>
        )}
        {flash !== null && <p className="staging__flash">{flash}</p>}
        <button
          type="button"
          className="staging__place"
          disabled={!gate.open || isFetching || applyState.isLoading}
          onClick={commit}
        >
          {applyState.isLoading ? 'Placing…' : 'Place aircraft'}
        </button>
      </div>
    </section>
  );
}
