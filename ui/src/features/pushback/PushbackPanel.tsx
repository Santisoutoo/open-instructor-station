/**
 * The Pushback tab: gate → direction/distance/angle controls → path schematic →
 * stage-then-execute bar, the Position/Weather house pattern (design §7.1).
 *
 * PURE-LOGIC HALF — no fetch yet. The RTK Query wiring (`pushbackApi.ts` via
 * `injectEndpoints`, D10) waits for the pushback server track to land and the OpenAPI
 * schema to regenerate. Until then:
 *
 * - `capabilities`/`capabilitiesError` arrive as props instead of the capabilities
 *   query, and Preview/Execute *emit callbacks* carrying the exact `PushbackRequest`
 *   wire shape the endpoints will take;
 * - the form state runs through `pushbackSlice`'s reducer via `useReducer` — the same
 *   actions and transitions the store will own once the wiring wave registers the
 *   slice, so the lift is a mechanical swap;
 * - the slider bounds are the §3 constants the manifest will echo.
 *
 * Preview stages the request (Execute is disarmed until then, and any edit disarms it
 * again — a stale preview is never what Execute sends); the schematic redraws live
 * from the form, so the instructor sees the arc *before* staging anything.
 */

import { useReducer } from 'react';
import type { Capabilities } from '../../api/models';
import { PathPreview } from './PathPreview';
import { PushbackControls } from './PushbackControls';
import { pushbackGate } from './gate';
import pushbackReducer, {
  angleChanged,
  directionSelected,
  distanceChanged,
  initialPushbackState,
  previewStaged,
  toRequest,
} from './pushbackSlice';
import {
  PUSHBACK_MAX_ANGLE_DEG,
  PUSHBACK_MAX_DISTANCE_M,
  type PushbackRequest,
} from './types.mock';
import './pushback.css';

interface PushbackPanelProps {
  /** From the capabilities query once wired; `undefined` while loading or failed. */
  capabilities: Capabilities | undefined;
  capabilitiesError: boolean;
  /** Stands in for `previewPushback` (query) until the wiring wave. */
  onPreview: (request: PushbackRequest) => void;
  /** Stands in for `executePushback` (mutation) until the wiring wave. */
  onExecute: (request: PushbackRequest) => void;
}

export function PushbackPanel({
  capabilities,
  capabilitiesError,
  onPreview,
  onExecute,
}: PushbackPanelProps) {
  const gate = pushbackGate(capabilities, capabilitiesError);
  const [form, dispatch] = useReducer(pushbackReducer, initialPushbackState);

  const preview = () => {
    dispatch(previewStaged());
    onPreview(toRequest(form));
  };

  const execute = () => {
    if (form.staged !== null) {
      onExecute(form.staged);
    }
  };

  const describeStaged = (request: PushbackRequest) =>
    request.direction === 'straight'
      ? `straight back, ${String(request.distance_m)} m`
      : `nose ${request.direction}, ${String(request.distance_m)} m, ${String(request.angle_deg)}°`;

  return (
    <section className="panel pushback-panel" aria-labelledby="pushback-heading">
      <h2 id="pushback-heading">Pushback</h2>

      {!gate.open && (
        <p className="pushback-gate" role="status">
          {gate.reason}
        </p>
      )}

      <PushbackControls
        direction={form.direction}
        distanceM={form.distanceM}
        angleDeg={form.angleDeg}
        maxDistanceM={PUSHBACK_MAX_DISTANCE_M}
        maxAngleDeg={PUSHBACK_MAX_ANGLE_DEG}
        disabled={!gate.open}
        onDirectionSelected={(direction) => dispatch(directionSelected(direction))}
        onDistanceChanged={(distanceM) => dispatch(distanceChanged(distanceM))}
        onAngleChanged={(angleDeg) => dispatch(angleChanged(angleDeg))}
      />

      <PathPreview
        direction={form.direction}
        distanceM={form.distanceM}
        angleDeg={form.angleDeg}
      />

      <div className="pushback-actions">
        {form.staged !== null ? (
          <p className="pushback-actions__staged" role="status">
            Staged: {describeStaged(form.staged)}. Nothing moves until you press Execute.
          </p>
        ) : (
          <p className="panel__empty">
            Preview stages the manoeuvre; nothing is sent to the simulator until you press
            Execute.
          </p>
        )}
        <div className="pushback-actions__buttons">
          <button
            type="button"
            className="pushback-actions__preview"
            disabled={!gate.open}
            onClick={preview}
          >
            Preview
          </button>
          <button
            type="button"
            className="pushback-actions__execute"
            disabled={!gate.open || form.staged === null}
            onClick={execute}
          >
            Execute pushback
          </button>
        </div>
      </div>
    </section>
  );
}
