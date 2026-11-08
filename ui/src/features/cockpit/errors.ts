/**
 * Turning a rejected actuation into the one sentence `cockpitSlice.lastError` shows.
 *
 * Unlike the Camera/Pushback managers, the Cockpit panel does not need to tell the
 * failures apart by *kind* — every one of `server/cockpit_routes.py`'s refusals (409
 * `CockpitCatalogInactive`/`CockpitPreconditionUnmet`, 404 `CockpitControlUnknown`, 422 a
 * kind/value mismatch, 502 `CockpitWriteRejected`, 501 unsupported) already carries its
 * own one-sentence `detail` naming the control and the reason (design §2.1/§2.2), so
 * finding that sentence is the whole job.
 */

/** The `detail` string of a FastAPI error body, when there is one. */
function detailOf(error: unknown): string | null {
  if (typeof error === 'object' && error !== null && 'data' in error) {
    const data = (error as { data: unknown }).data;
    if (typeof data === 'object' && data !== null && 'detail' in data) {
      const detail = (data as { detail: unknown }).detail;
      if (typeof detail === 'string' && detail !== '') {
        return detail;
      }
    }
  }
  return null;
}

/** The server's own sentence, or `fallback` for a transport-level failure. */
export function cockpitErrorDetail(error: unknown, fallback: string): string {
  return detailOf(error) ?? fallback;
}
