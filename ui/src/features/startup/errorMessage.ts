import type { SerializedError } from '@reduxjs/toolkit';
import type { FetchBaseQueryError } from '@reduxjs/toolkit/query';

/**
 * Turn whatever `getAirport` rejects with into one line an instructor can act on.
 *
 * A 404 is the ordinary "no such airport" outcome; any other numeric status reads as an
 * index that could not be searched; anything without a `status` at all (RTK Query's own
 * `FETCH_ERROR`/`PARSING_ERROR`/`TIMEOUT_ERROR`, or a `SerializedError` from an unwrapped
 * thunk) means the station itself could not be reached.
 */
export function errorMessageFor(
  error: FetchBaseQueryError | SerializedError,
  icao: string,
): string {
  if ('status' in error) {
    if (error.status === 404) {
      return `No airport found for "${icao}". Check the ICAO code and try again.`;
    }
    if (typeof error.status === 'number') {
      return `The airport index could not be searched (HTTP ${String(error.status)}).`;
    }
  }
  return 'The station could not be reached. Check the network connection.';
}
