/**
 * A stubbed instructor API for the Cockpit panel's tests.
 *
 * `fetch` is stubbed rather than the RTK Query hooks mocked — `features/camera/testApi.ts`'s
 * shape, duplicated rather than imported (one small file; importing across feature
 * folders would be the wrong coupling for two panels that otherwise share nothing).
 * Named without `.test.` so Vitest does not try to run it as a suite.
 */

import { vi } from 'vitest';

/** One request the panel made, recorded in order. */
export interface ApiCall {
  readonly url: string;
  readonly method: string;
  readonly body: unknown;
}

/** How one endpoint should answer, in order — repeats the last entry once exhausted. */
export type Answer =
  | { readonly status?: number; readonly body: unknown }
  | { readonly status: number; readonly detail: unknown };

function response(answer: Answer): Response {
  const status = answer.status ?? 200;
  if (status === 204) {
    return new Response(null, { status });
  }
  const payload = 'detail' in answer ? { detail: answer.detail } : answer.body;
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

/**
 * Stub `fetch`, routing on the first `"<METHOD> <fragment>"` key that matches. A value can
 * be one `Answer` (repeated for every call) or an array of them (consumed in order, the
 * last one repeating once exhausted) — the shape a revision-bump test needs to answer a
 * refetch differently from the first fetch.
 */
export function stubApi(routes: Record<string, Answer | readonly Answer[]>): {
  calls: ApiCall[];
} {
  const calls: ApiCall[] = [];
  const cursors = new Map<string, number>();

  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const request = input instanceof Request ? input : null;
      const url = request?.url ?? String(input);
      const method = request?.method ?? init?.method ?? 'GET';
      const rawBody = request === null ? init?.body : await request.clone().text();
      calls.push({
        url,
        method,
        body:
          typeof rawBody === 'string' && rawBody !== ''
            ? (JSON.parse(rawBody) as unknown)
            : undefined,
      });

      for (const [route, answer] of Object.entries(routes)) {
        const [routeMethod, fragment] = route.split(' ');
        if (routeMethod === method && fragment !== undefined && url.includes(fragment)) {
          const sequence = Array.isArray(answer) ? answer : [answer];
          const index = cursors.get(route) ?? 0;
          cursors.set(route, Math.min(index + 1, sequence.length - 1));
          const step = sequence[Math.min(index, sequence.length - 1)];
          return response(step as Answer);
        }
      }
      return response({ status: 404, detail: `No stub for ${method} ${url}` });
    }),
  );
  return { calls };
}

/** Every call whose URL contains `fragment` and whose method matches, in order. */
export function callsTo(
  calls: readonly ApiCall[],
  method: string,
  fragment: string,
): ApiCall[] {
  return calls.filter((call) => call.method === method && call.url.includes(fragment));
}
