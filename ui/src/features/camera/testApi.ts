/**
 * A stubbed instructor API for the Camera panel's component tests.
 *
 * `fetch` is stubbed rather than the RTK Query hooks mocked — the same reasoning and the
 * same shape as `features/profiles/testApi.ts` (duplicated rather than imported: it is
 * one small file, and importing across feature folders would be the wrong coupling for
 * two panels that otherwise share nothing).
 *
 * Named without `.test.` so Vitest does not try to run it as a suite.
 */

import { vi } from 'vitest';

/** One request the panel made, recorded in order. */
export interface ApiCall {
  readonly url: string;
  readonly method: string;
  readonly body: unknown;
}

/** How one endpoint should answer. */
export type Answer =
  | { readonly status?: number; readonly body: unknown }
  | { readonly status: number; readonly detail: unknown };

function response(answer: Answer): Response {
  const status = answer.status ?? 200;
  // `DELETE /positions/{id}` answers 204, and the Fetch spec forbids a body on one —
  // constructing the Response with a body would throw before the panel ever saw it.
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
 * Stub `fetch`, routing on the first `"<METHOD> <fragment>"` key that matches.
 *
 * The method is part of the key because `/api/camera/positions` is two different
 * endpoints — the list and the save — and a URL-only route cannot tell them apart.
 * Routes are tried in insertion order, so a specific route declared before a general one
 * wins. Anything unrouted answers 404 with a detail naming the request, which turns a
 * typo in a test into a readable message instead of a hang.
 */
export function stubApi(routes: Record<string, Answer>): { calls: ApiCall[] } {
  const calls: ApiCall[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      // `fetchBaseQuery` hands `fetch` a fully built `Request`, never a (url, init) pair.
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
          return response(answer);
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
