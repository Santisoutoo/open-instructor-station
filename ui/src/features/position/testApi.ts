/**
 * A stubbed instructor API for the Position panel's component tests.
 *
 * `fetch` is stubbed rather than the RTK Query hooks mocked, deliberately and for the same
 * reason `StagingBar.test.tsx` does it: the request the panel actually sends — its URL, its
 * query string, its body — is the thing worth asserting. Mocking `useGetParkingQuery` would
 * hide a panel that asks the wrong endpoint, and it would leave the RTK Query middleware,
 * the cache keys and the loading states untested altogether.
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

/**
 * How one endpoint should answer.
 *
 * The failure form is not an afterthought: every gate in this panel has to fail closed, and
 * a stub that could only succeed would never show whether it does.
 */
export type Answer =
  | { readonly status?: number; readonly body: unknown }
  | { readonly status: number; readonly detail: string };

function response(answer: Answer): Response {
  const payload = 'detail' in answer ? { detail: answer.detail } : answer.body;
  return new Response(JSON.stringify(payload), {
    status: answer.status ?? 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

/**
 * Stub `fetch`, routing on the first URL fragment that matches.
 *
 * Routes are tried in insertion order, so a specific route declared before a general one
 * wins. Anything unrouted answers 404 with a detail naming the URL, which turns a typo in
 * a test into a readable message instead of a hang.
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

      for (const [fragment, answer] of Object.entries(routes)) {
        if (url.includes(fragment)) {
          return response(answer);
        }
      }
      return response({ status: 404, detail: `No stub for ${url}` });
    }),
  );
  return { calls };
}

/** Every call whose URL contains `fragment`, in order. */
export function callsTo(calls: readonly ApiCall[], fragment: string): ApiCall[] {
  return calls.filter((call) => call.url.includes(fragment));
}
