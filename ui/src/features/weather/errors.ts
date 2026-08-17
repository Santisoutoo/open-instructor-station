/**
 * Turning an RTK Query error into a sentence an instructor can act on.
 *
 * The server always states a reason — a 501 names the capability the adapter does not
 * declare, a 422 names what the request could not be resolved against, a 404 names what was
 * missing — so the job here is to *find* that reason rather than to invent one. The fallback
 * is only for the case where nothing came back at all.
 *
 * A near-duplicate of `features/position/errors.ts` rather than a shared import: each
 * manager owns its own small logic (CLAUDE.md — adding a manager must not require touching
 * the others), and this function is twelve lines with no state of its own.
 */
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
