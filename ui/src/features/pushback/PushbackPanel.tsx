/**
 * The Pushback tab: gate → direction/distance/angle controls → path schematic →
 * stage-then-execute bar, the Position/Weather house pattern (design §7.1).
 *
 * Form state is the `pushback` slice in the store; everything the server knows —
 * the manifest, the preview, the result — is RTK Query (`pushbackApi.ts`).
 *
 * **The two refusals are kept apart, because the server keeps them apart.** A missing
 * `can_pushback` (501 territory) is permanent: the gate closes, every control disables,
 * and the server's own sentence says which adapter and which flag. "The aircraft is
 * airborne" (409) is not: the adapter is perfectly capable, this aircraft simply is not on
 * the ground *right now*, so the controls stay live, the notice says so in as many words,
 * and only the commit is held back until a preview succeeds again. Flattening the two
 * would disable the panel for the rest of the session over a condition that clears on
 * touchdown.
 *
 * Execute is armed only by a preview that actually came back. The staging latch alone is
 * not enough: pressing Preview while airborne stages a request the server has just
 * refused, and an armed Execute after a refused preview would be exactly the "preview
 * draws a path execute would refuse" lie `server/pushback_routes.py` goes out of its way
 * to prevent. A successful push disarms it again — the manoeuvre is deliberately *not*
 * idempotent, so a second Execute would push back a second time.
 */

import { skipToken } from '@reduxjs/toolkit/query';
import { useAppDispatch, useAppSelector } from '../../store';
import { PathPreview } from './PathPreview';
import { PushbackControls } from './PushbackControls';
import { describePushbackRefusal, disablesPushback } from './errors';
import { pushbackGate } from './gate';
import {
  useExecutePushbackMutation,
  useGetPushbackManifestQuery,
  usePreviewPushbackQuery,
} from './pushbackApi';
import {
  angleChanged,
  directionSelected,
  distanceChanged,
  previewStaged,
  stagedDiscarded,
} from './pushbackSlice';
import type { PushbackRequest } from '../../api/models';
import './pushback.css';

function describeRequest(request: PushbackRequest): string {
  return request.direction === 'straight'
    ? `straight back, ${String(request.distance_m)} m`
    : `nose ${request.direction}, ${String(request.distance_m)} m, ${String(request.angle_deg)}°`;
}

/** Headings are read aloud as three digits on the radio; render them that way. */
function formatHeading(deg: number): string {
  return `${String(Math.round(deg) % 360).padStart(3, '0')}°`;
}

export function PushbackPanel() {
  const dispatch = useAppDispatch();
  const form = useAppSelector((state) => state.pushback);

  const { data: manifest, isError: manifestFailed } = useGetPushbackManifestQuery();
  const gate = pushbackGate(manifest, manifestFailed);

  // `skipToken` rather than a `skip` flag and a throwaway argument: there is no request
  // to describe when nothing is staged, and this way the types say so.
  const {
    data: preview,
    error: previewError,
    isFetching: previewing,
  } = usePreviewPushbackQuery(
    form.staged !== null && gate.open ? form.staged : skipToken,
  );

  const [
    executePushback,
    { data: result, error: executeError, isLoading: executing, reset: resetExecute },
  ] = useExecutePushbackMutation();

  // A refused preview is the one the instructor is acting on right now, so it wins the
  // slot; a stale execute failure would otherwise sit under a fresh, valid preview.
  const refusal =
    previewError !== undefined
      ? describePushbackRefusal(previewError)
      : executeError !== undefined
        ? describePushbackRefusal(executeError)
        : null;

  // Only a capability answer takes the controls away. "Airborne" is a wait, not a wall,
  // and neither is a dropped connection.
  const blocked = !gate.open || disablesPushback(refusal);
  const armed = form.staged !== null && preview !== undefined && !previewing;

  const onPreview = () => {
    // Drop the previous push's outcome: a refusal from the last Execute must not sit on
    // screen under a preview that has just succeeded, and last push's "Pushed back" line
    // is not what the instructor is being told about now.
    resetExecute();
    dispatch(previewStaged());
  };

  const onExecute = () => {
    if (form.staged === null) {
      return;
    }
    void executePushback(form.staged)
      .unwrap()
      // Not idempotent: make the instructor preview again rather than leave a second
      // push one tap away. A failure keeps the staging so the request can be retried.
      .then(() => dispatch(stagedDiscarded()))
      .catch(() => undefined);
  };

  return (
    <section className="panel pushback-panel" aria-labelledby="pushback-heading">
      <h2 id="pushback-heading">Pushback</h2>

      {!gate.open && (
        <p className="pushback-gate" role="status">
          {gate.reason}
        </p>
      )}

      {refusal !== null && (
        <p
          className={
            refusal.kind === 'not-on-ground'
              ? 'pushback-refusal pushback-refusal--transient'
              : 'pushback-refusal'
          }
          role="status"
        >
          {refusal.message}
          {refusal.kind === 'not-on-ground' && (
            <span className="pushback-refusal__note">
              {' '}
              This is the aircraft&apos;s state right now, not a limit of the simulator —
              preview again once it is back on the ground.
            </span>
          )}
        </p>
      )}

      <PushbackControls
        direction={form.direction}
        distanceM={form.distanceM}
        angleDeg={form.angleDeg}
        maxDistanceM={gate.maxDistanceM}
        maxAngleDeg={gate.maxAngleDeg}
        disabled={blocked}
        onDirectionSelected={(direction) => dispatch(directionSelected(direction))}
        onDistanceChanged={(value) => {
          dispatch(distanceChanged({ value, max: gate.maxDistanceM }));
        }}
        onAngleChanged={(value) => {
          dispatch(angleChanged({ value, max: gate.maxAngleDeg }));
        }}
      />

      <PathPreview
        direction={form.direction}
        distanceM={form.distanceM}
        angleDeg={form.angleDeg}
        preview={preview}
      />

      {preview !== undefined && (
        <dl className="pushback-facts">
          <div className="pushback-facts__row">
            <dt>Heading</dt>
            <dd>
              {formatHeading(preview.current_heading_deg)} →{' '}
              {formatHeading(preview.target.heading_deg)}
            </dd>
          </div>
          <div className="pushback-facts__row">
            <dt>Target</dt>
            <dd>
              {preview.target.position.latitude.toFixed(6)},{' '}
              {preview.target.position.longitude.toFixed(6)}
            </dd>
          </div>
        </dl>
      )}

      <div className="pushback-actions">
        {form.staged !== null ? (
          <p className="pushback-actions__staged" role="status">
            Staged: {describeRequest(form.staged)}. Nothing moves until you press Execute.
          </p>
        ) : (
          <p className="panel__empty">
            Preview stages the manoeuvre; nothing is sent to the simulator until you press
            Execute.
          </p>
        )}
        {result !== undefined && form.staged === null && (
          <p className="pushback-actions__result" role="status">
            Pushed back — now heading {formatHeading(result.state.heading_deg)} at{' '}
            {result.state.latitude.toFixed(6)}, {result.state.longitude.toFixed(6)}.
          </p>
        )}
        <div className="pushback-actions__buttons">
          <button
            type="button"
            className="pushback-actions__preview"
            disabled={blocked}
            onClick={onPreview}
          >
            Preview
          </button>
          <button
            type="button"
            className="pushback-actions__execute"
            disabled={blocked || !armed || executing}
            onClick={onExecute}
          >
            Execute pushback
          </button>
        </div>
      </div>
    </section>
  );
}
