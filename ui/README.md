# Open Instructor Station — UI

React + TypeScript (strict) + Redux Toolkit front end for the instructor station.

The Phase-0 shell plus the **Aircraft Control panel** (feature spec manager 6). The position,
weather, failure, traffic and map panels arrive in later phases and each plugs into `App.tsx`
without touching the others.

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

| Call                          | Consumer                                                            |
| ----------------------------- | ------------------------------------------------------------------- |
| `GET /api/health`             | RTK Query, polled every 10 s — feeds the adapter name in the badge  |
| `GET /api/capabilities`       | RTK Query — drives `CapabilityList`                                 |
| `GET /api/state`              | RTK Query — one-shot snapshot endpoint                              |
| `GET /api/aircraft/controls`  | RTK Query — decides what the Aircraft Control panel may enable       |
| `POST /api/aircraft/setup`    | RTK Query mutation — every write the Aircraft Control panel makes    |
| `WS /ws/state`                | `useTelemetrySocket` — ~4 Hz `AircraftState` frames                 |

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
| `features/aircraft/aircraftSlice.ts`   | Optimistic pending/confirmed write state per Aircraft Control widget                                         |
| `api/instructorApi.ts`                 | **All server state**, via RTK Query                                                                          |

Two slices derive from the telemetry feed in `extraReducers` rather than being dispatched
separately, so they can never disagree with it: `connectionSlice` takes `lastUpdateAt` from
`telemetryFrameReceived`, and `aircraftSlice` resets itself on `telemetryCleared` — a "gear
down" the station commanded before losing the link is no longer evidence of anything.

Typed hooks (`useAppDispatch`, `useAppSelector`, `useAppStore`) live in `store/index.ts`.
`setupStore(preloadedState?)` is a factory so tests get an isolated store.

> Note: `configureStore` is given the reducer **map** rather than the combined reducer. With
> RTK 2.12 / TS 5.9 that is the only form whose generics survive `preloadedState` and a custom
> `middleware` callback being used together; the combined-reducer form fails to infer the
> middleware tuple.

## Generated API types

CLAUDE.md is explicit: _"the UI client is generated from FastAPI's OpenAPI schema. **Never
hand-write API types** in the frontend."_ The Phase-0 placeholder (`src/api/types.ts`) is gone;
this is now literally true.

```powershell
.\.venv\Scripts\python.exe -m server   # from the repo root, in another terminal
cd ui; npm run generate:api            # -> src/api/schema.d.ts
```

`src/api/schema.d.ts` is generated output — excluded from ESLint and Prettier, never edited by
hand. `src/api/models.ts` sits on top of it and contains **nothing but aliases** into it
(`type AircraftState = components['schemas']['AircraftState']`), so a backend change surfaces
as a TypeScript error rather than a runtime surprise.

Two things deliberately did **not** move into the generated types:

- **`isAircraftState`** (in `src/api/models.ts`) — a runtime guard for WebSocket frames. A
  compile-time type says nothing about what actually arrives over a socket, so every frame is
  validated and a malformed one is dropped rather than rendered as `NaN`.
- **Display tables** — `CAPABILITY_LABELS` in `CapabilityList.tsx` and `CONTROL_DISPLAY` in
  `features/aircraft/controls.ts`. Wording, ordering and widget choice are not API types. Both
  are keyed by a generated union (`CapabilityKey`, `ControlId`), so a flag or control renamed
  on the server breaks them at compile time.

**Re-run `npm run generate:api` whenever a server model changes**, and commit the result.

## Aircraft Control panel

`features/aircraft/` — feature spec manager 6. Reads and writes take different routes on
purpose: the live picture arrives on `/ws/state`, every write is an idempotent
`POST /api/aircraft/setup`.

| File                       | Role                                                                       |
| -------------------------- | -------------------------------------------------------------------------- |
| `AircraftControlPanel.tsx` | The panel: sections, capability gating, optimistic write orchestration      |
| `ControlWidgets.tsx`       | The three widgets — slider, stepper, toggle                                 |
| `controls.ts`              | Display catalogue and the fail-closed `controlAvailability` resolver        |
| `aircraftSlice.ts`         | Pending/confirmed bookkeeping per control                                   |

Three behaviours worth knowing before changing anything here:

- **Gating comes from `GET /api/aircraft/controls`, not from `GET /api/capabilities`.** A
  capability flag says the adapter can drive an autopilot; the manifest says whether the server
  has an `AircraftSetup` field to carry the request. Both must hold. It fails closed exactly
  like `CapabilityList`: loading, unreachable, or unlisted all mean *disabled*, and the
  server's own sentence is rendered next to the control.
- **Nothing commits on drag or on keystroke.** Sliders write on release; steppers write when
  "Set" is pressed. There is a student flying the aeroplane.
- **A stepper's input is never seeded from the live feed.** Altitude, speed, heading and
  vertical speed arrive at ~4 Hz; a self-synchronising field would overwrite whatever the
  instructor was halfway through typing. The readout tracks the aircraft, the field tracks the
  intent, and they meet only when "Set" is pressed.

The autopilot block and the elevator trim currently render **disabled with a stated reason**:
`AircraftSetup` in `core/models.py` has no autopilot or trim fields yet, so no write path
exists. The server reports that per control, and adding the fields upstream turns them on
without touching `server/app.py`.

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
    schema.d.ts                     GENERATED from the OpenAPI schema — never edited
    models.ts                       Aliases into schema.d.ts + the isAircraftState guard
    instructorApi.ts                RTK Query endpoints
  features/telemetry/
    telemetrySlice.ts               Latest AircraftState
    useTelemetrySocket.ts           WebSocket + reconnect backoff
    format.ts                       Display formatting (locale pinned to en-US)
  features/aircraft/
    AircraftControlPanel.tsx        Manager 6 — the live control panel
    ControlWidgets.tsx              Slider / stepper / toggle
    controls.ts                     Display catalogue + fail-closed availability
    aircraftSlice.ts                Pending/confirmed write state
  components/
    ConnectionBadge.tsx
    TelemetryPanel.tsx
    CapabilityList.tsx
  test/setup.ts                     jest-dom matchers, RTL cleanup, relative-URL Request
```

`test/setup.ts` also restores browser behaviour that jsdom does not provide: jsdom ships no
fetch stack, so the tests inherit Node's, whose `Request` cannot resolve a relative URL. Since
the whole app talks in relative paths on purpose, every RTK Query test would otherwise fail for
a reason that cannot happen in a browser.

## Styling

Plain CSS in `src/index.css`, dark theme, no framework dependency. Touch targets are at least
44 px and live numbers use tabular figures so the readout does not jitter at 4 Hz.

## Notes on tooling versions

TypeScript is pinned to `~5.9`, not the latest 7.x: `openapi-typescript@7` requires
`typescript@^5.x` and `typescript-eslint@8` supports `<6.1.0`. 5.9 is the only version both
tools accept. Revisit when both have shipped TypeScript 7 support.

Vitest runs with `globals: false` — every test imports `describe` / `it` / `expect`
explicitly, and `src/test/setup.ts` installs RTL's `cleanup` by hand.
