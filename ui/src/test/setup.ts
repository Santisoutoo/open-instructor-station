import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';
import { resetMaplibreStub } from './maplibreStub';
import { resetThreeStub } from './threeStub';

// Vitest runs with `globals: false`, so RTL's automatic cleanup hook is not installed.
// The maplibre and three stubs' instance registries are cleared here too, so no test can see
// a Map/Marker/OrbitControls instance constructed by an earlier one.
afterEach(() => {
  cleanup();
  resetMaplibreStub();
  resetThreeStub();
});

/*
 * Make relative request URLs resolve, the way a browser does.
 *
 * jsdom implements no fetch stack at all, so the test environment inherits Node's — and
 * Node's `Request` has no document to resolve against, so `new Request('/api/state')`
 * throws "Failed to parse URL". The whole app talks in relative paths on purpose (see
 * ui/README.md: one origin, no CORS anywhere), and RTK Query's `fetchBaseQuery` builds a
 * `Request` before it ever reaches a stubbed `fetch`, so without this every RTK Query
 * test would fail for a reason that cannot happen in a browser.
 *
 * This restores browser behaviour; it does not fake anything the app relies on.
 */
const NodeRequest = globalThis.Request;

class DocumentRelativeRequest extends NodeRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    super(
      typeof input === 'string' ? new URL(input, globalThis.location.origin) : input,
      init,
    );
  }
}

globalThis.Request = DocumentRelativeRequest;
