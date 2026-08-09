/**
 * Turning whatever RTK Query hands back into a sentence an instructor can act on.
 *
 * Its own module, not a helper beside the component that renders it: a file exporting both
 * a component and a function breaks React Fast Refresh, which is what
 * `react-refresh/only-export-components` is guarding.
 *
 * The server is the one that knows why a placement was refused — an unpositionable leg
 * names its ARINC path terminator, a capability refusal names the flag — so `detail` is
 * shown verbatim wherever there is one, and the generic sentence is the last resort rather
 * than the habit.
 */

/** Pulls a readable sentence out of whatever RTK Query hands back for an error. */
export function errorMessage(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'data' in error) {
    const data = (error as { data: unknown }).data;
    if (typeof data === 'object' && data !== null && 'detail' in data) {
      const detail = (data as { detail: unknown }).detail;
      if (typeof detail === 'string') {
        return detail;
      }
    }
  }
  return 'The placement could not be applied.';
}
