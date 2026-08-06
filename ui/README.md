# Open Instructor Station — UI

React + TypeScript (strict) + Redux Toolkit front end for the instructor station.

This is the **Phase-0 foundation**: a production-shaped shell that proves the stack, the state
management and the live WebSocket link. It is not the full instructor UI — the position,
weather, failure, traffic and map panels arrive in later phases and each plugs into
`App.tsx` without touching the others.

## Requirements

- Node 20+ (developed on Node 24, npm 11)
- The backend from `../server` listening on `http://localhost:8000`

## Running

```powershell
cd ui
npm install
npm run dev          # http://localhost:5173
```

The dev server binds all interfaces (`server.host: true`), so the station is reachable from a
tablet on the same LAN at `http://<your-machine-ip>:5173` — iPad use is a first-class scenario.

### Scripts

| Script                 | What it does                                                |
| ---------------------- | ----------------------------------------------------------- |
| `npm run dev`          | Vite dev server with the backend proxy                      |
| `npm run build`        | `tsc -b` project build + production bundle into `dist/`     |
| `npm run preview`      | Serves the built bundle                                     |
| `npm run lint`         | ESLint (flat config, `typescript-eslint`)                   |
| `npm run typecheck`    | `tsc --noEmit` over both TS projects                        |
| `npm test`             | Vitest (jsdom + React Testing Library), single run          |
| `npm run format`       | Prettier over the whole tree                                |
| `npm run generate:api` | Regenerates the API types from the backend's OpenAPI schema |

CI depends on `lint`, `typecheck`, `test` and `build` — do not rename them.

## How it talks to the backend

The UI only ever uses **relative** paths (`/api/...`, `/ws/state`). In dev, Vite proxies them:

| Path     | Proxied to              |
| -------- | ----------------------- |
| `/api/*` | `http://localhost:8000` |
| `/ws/*`  | `ws://localhost:8000`   |

That keeps the browser on a single origin, so there is no CORS configuration anywhere. In
production FastAPI serves the built bundle from its own origin and the same relative paths
keep working unchanged.

### Endpoints consumed

| Call                    | Consumer                                                           |
| ----------------------- | ------------------------------------------------------------------ |
| `GET /api/health`       | RTK Query, polled every 10 s — feeds the adapter name in the badge |
| `GET /api/capabilities` | RTK Query — drives `CapabilityList`                                |
| `GET /api/state`        | RTK Query — one-shot snapshot endpoint                             |
| `WS /ws/state`          | `useTelemetrySocket` — ~4 Hz `AircraftState` frames                |

The WebSocket hook validates every frame at runtime (`isAircraftState`), drops malformed ones
instead of rendering `NaN`, and reconnects for ever with capped exponential backoff
(500 ms → 10 s, jittered). Losing the link clears the telemetry slice, so the panel shows
"waiting" rather than a stale position pretending to be live.

## State management

Redux Toolkit only — no plain Redux, no Zustand, no Context for global state.

| Slice / API                            | Owns                                                                                                         |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `store/connectionSlice.ts`             | Link status (`idle`/`connecting`/`connected`/`error`), last error, last update timestamp, reconnect attempts |
| `features/telemetry/telemetrySlice.ts` | Latest `AircraftState` + frame count                                                                         |
| `api/instructorApi.ts`                 | **All server state**, via RTK Query                                                                          |

`connectionSlice` derives `lastUpdateAt` from `telemetryFrameReceived` in `extraReducers`, so
the freshness stamp and the telemetry feed can never disagree.

Typed hooks (`useAppDispatch`, `useAppSelector`, `useAppStore`) live in `store/index.ts`.
`setupStore(preloadedState?)` is a factory so tests get an isolated store.

> Note: `configureStore` is given the reducer **map** rather than the combined reducer. With
> RTK 2.12 / TS 5.9 that is the only form whose generics survive `preloadedState` and a custom
> `middleware` callback being used together; the combined-reducer form fails to infer the
> middleware tuple.

## Generated API types — Phase-0 caveat

CLAUDE.md is explicit: _"the UI client is generated from FastAPI's OpenAPI schema. **Never
hand-write API types** in the frontend."_

`npm run generate:api` is wired up for exactly that:

```
openapi-typescript http://localhost:8000/openapi.json -o src/api/schema.d.ts
```

**It cannot run yet.** The FastAPI server is being built in parallel and nothing answers on
`:8000`, so there is no schema to generate from. As a stop-gap, `src/api/types.ts` holds a
small hand-written mirror of the agreed Phase-0 contract, prominently marked with a
`TODO(phase-0)` banner. It is a placeholder, not a pattern to copy.

**Replace it as soon as the backend answers:**

1. Start the server, then `npm run generate:api` — writes `src/api/schema.d.ts`.
2. Re-point `src/api/instructorApi.ts` at the generated schema:
   ```ts
   import type { components } from './schema';
   type AircraftState = components['schemas']['AircraftState'];
   ```
3. Delete `src/api/types.ts`, keeping the `isAircraftState` runtime guard (a compile-time
   type says nothing about what actually arrives over a socket) and the `CAPABILITY_LABELS`
   display table next to the component that uses them.

`src/api/schema.d.ts` is excluded from ESLint and Prettier — generated files are not edited.

## Capabilities, not failures

`CapabilityList` renders `GET /api/capabilities` with an enabled/disabled indicator per flag.
This is the visible enforcement of hard rule 3: what the active adapter cannot do is disabled
in the UI, never left to throw at runtime. Unknown flags (loading, or an unreachable server)
are treated as **unsupported** — failing closed is the safe direction.

## Layout

```
src/
  main.tsx                          React root + <Provider store={store}>
  App.tsx                           Layout shell; owns the telemetry socket
  index.css                         Dark theme, plain CSS, tablet-sized targets
  store/
    index.ts                        configureStore, RootState/AppDispatch, typed hooks
    connectionSlice.ts              Link status
  api/
    instructorApi.ts                RTK Query: getHealth / getCapabilities / getState
    types.ts                        TODO(phase-0) placeholder — see above
  features/telemetry/
    telemetrySlice.ts               Latest AircraftState
    useTelemetrySocket.ts           WebSocket + reconnect backoff
    format.ts                       Display formatting (locale pinned to en-US)
  components/
    ConnectionBadge.tsx
    TelemetryPanel.tsx
    CapabilityList.tsx
  test/setup.ts                     jest-dom matchers + RTL cleanup
```

## Styling

Plain CSS in `src/index.css`, dark theme, no framework dependency. Touch targets are at least
44 px and live numbers use tabular figures so the readout does not jitter at 4 Hz.

## Notes on tooling versions

TypeScript is pinned to `~5.9`, not the latest 7.x: `openapi-typescript@7` requires
`typescript@^5.x` and `typescript-eslint@8` supports `<6.1.0`. 5.9 is the only version both
tools accept. Revisit when both have shipped TypeScript 7 support.

Vitest runs with `globals: false` — every test imports `describe` / `it` / `expect`
explicitly, and `src/test/setup.ts` installs RTL's `cleanup` by hand.
