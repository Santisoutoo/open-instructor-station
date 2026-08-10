import { afterEach, describe, expect, it, vi } from 'vitest';
import { instructorApi } from './instructorApi';
import { setupStore } from '../store';

/**
 * The wire shape of the airport search, pinned.
 *
 * `schema.d.ts` is generated, so TypeScript already guarantees the *types* match the
 * server. It cannot guarantee the *query-string keys* do: `params` is a plain record and
 * a wrong key type-checks perfectly, then returns a 422 at runtime. The navdata design
 * (§12) names the parameter `q`, and this is the only place that failure is catchable
 * without a running backend.
 */

afterEach(() => {
  vi.unstubAllGlobals();
});

/** Capture the URLs RTK Query actually requests, and answer with an empty result set. */
function stubFetch(): { urls: string[]; only: () => URL } {
  const urls: string[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(input);
      urls.push(request.url);
      return Response.json([]);
    }),
  );
  return {
    urls,
    only: () => {
      const [url, ...rest] = urls;
      if (url === undefined || rest.length > 0) {
        throw new Error(`Expected exactly one request, got ${urls.length}.`);
      }
      return new URL(url);
    },
  };
}

describe('searchAirports', () => {
  it('sends the search term as ?q=, the name the server publishes', async () => {
    const fetched = stubFetch();
    const store = setupStore();

    await store.dispatch(
      instructorApi.endpoints.searchAirports.initiate({ query: 'LEMD' }),
    );

    const params = fetched.only().searchParams;
    expect(params.get('q')).toBe('LEMD');
    // The old name is gone: sending it would be a 422 from the server.
    expect(params.has('query')).toBe(false);
  });

  it('bounds the result set, so a one-letter search cannot pull the whole index', async () => {
    const fetched = stubFetch();
    const store = setupStore();

    await store.dispatch(instructorApi.endpoints.searchAirports.initiate({ query: 'L' }));

    expect(fetched.only().searchParams.get('limit')).toBe('12');
  });
});
