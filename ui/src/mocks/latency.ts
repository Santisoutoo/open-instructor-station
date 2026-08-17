/**
 * Shared helper for the mock feature APIs: resolve a fixture the way a `queryFn`
 * must, after a beat of simulated network latency so loading states are real.
 */

export const MOCK_LATENCY_MS = 180;

export function withLatency<T>(
  data: T,
  ms: number = MOCK_LATENCY_MS,
): Promise<{ data: T }> {
  return new Promise((resolve) => {
    setTimeout(() => resolve({ data }), ms);
  });
}
