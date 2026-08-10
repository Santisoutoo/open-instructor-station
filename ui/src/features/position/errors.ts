/**
 * Turning an RTK Query error into a sentence an instructor can act on.
 *
 * The server always states a reason — a 501 names the capability the adapter does not
 * declare, a 422 carries the leg's own `unpositionable_reason`, a 404 names what was
 * missing — so the job here is to *find* that reason rather than to invent one. The
 * fallback is only for the case where nothing came back at all.
 */

/** The `detail` string from a FastAPI error body, or a plain fallback. */
export function errorMessage(error: unknown, fallback: string): string {
  if (typeof error === 'object' && error !== null && 'data' in error) {
    const data = (error as { data: unknown }).data;
    if (typeof data === 'object' && data !== null && 'detail' in data) {
      const detail = (data as { detail: unknown }).detail;
      if (typeof detail === 'string') {
        return detail;
      }
    }
  }
  return fallback;
}
