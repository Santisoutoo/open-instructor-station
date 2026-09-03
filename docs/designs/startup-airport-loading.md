# Startup Airport-Selection Loading Screen — design

**Status:** designed, not yet implemented.
**Phase:** layered onto manager 15, the **Instructor Panel**
([`../feature-spec.md`](../feature-spec.md#15-instructor-panel)) — cross-cutting, "not built in a
single step … grows one tab per phase." This document does not add a tab; it adds the shell's own
front door, the same posture `weather-station.md` takes for its manager: UI polish on an
already-shipped surface, not a new roadmap phase gate. It depends on nothing from an
in-progress phase and blocks nothing downstream of it.
**Feature spec:** no single numbered manager — this is the first screen every manager's data
depends on (an airport must be chosen before Position, Weather's `fieldElevationFt`, or any
navdata-backed panel means anything). It operationalises feature-spec manager 15's own stated rule,
"an instructor never discovers missing navdata by clicking a control that fails," by moving that
discovery to before the shell exists at all.
**Depends on:** nothing in-flight. Every endpoint and model this document uses already ships
(`GET /api/navdata/airports`, `GET /api/navdata/airports/{icao}`, `GET /api/navdata/status`,
`POST /api/navdata/index`) and is already tested (`tests/server/test_navdata_routes.py::TestAirports`).
**Blocks:** Wave 1 of epic #230 — #232 (the gate itself) and #233 (the header support link) — which
run in **parallel**, in separate worktrees, immediately after this document merges. Their exact,
disjoint file ownership is pinned in §7.

**A note on sourcing.** This design was written with `Read`/`Grep`/`Glob` only, against the
worktree at `98e0022` (`dev`) — no `gh` CLI, no network access to fetch issues #230–#235. Every
file, line number, and code shape cited below was read directly from the repository and is
accurate as of that commit. §1's scope and the "11 decisions" enumerated in §0 are built from the
task brief's own summary of issue #231's body, cross-checked against the code wherever the code
could confirm or refute a claim in that summary (three claims turned out stale — see §0's notes on
SG-3, SG-6 and SG-9). **The caller should diff this document's §1 against issue #230's own 8
numbered goals before merge** — that text was never fetched directly.

Binding rules live in [`../../CLAUDE.md`](../../CLAUDE.md); layers in
[`../architecture.md`](../architecture.md). This document adds no endpoint, no Pydantic model, no
`SimAdapter` method and no capability flag — it is 100% `ui/` work over surface that already exists
and is already server-tested.

---

## 0. Decisions at a glance

| # | Decision | Where |
|---|---|---|
| SG-1 | **One new slice, `startup`, owns the gate's own machine; success fans out into the two existing Position slices from the gate's own resolve handler**, never from `extraReducers` on `positionSlice`/`positionDesignSlice` (those files are not in #232's ownership, and `positionDesignSlice.airportLoaded`'s own docstring already delegates the mirror to "the calling component"). No third source of truth: `startup.icao`/`startup.name` are the resolve target and the localStorage payload; once `status === 'ready'` nothing reads them again, and `positionDesign.loadedIcao` is the one place "which airport is loaded" lives from then on. | §2, §3 |
| SG-2 | **State machine, exactly:** `idle → searching → resolving → ready \| error`, transitions and per-state rendering pinned below. `resolveRequested` is reachable from `idle`, `searching` or `error` (an Enter keypress or a suggestion click), never from `ready`. Only `resolveSucceeded` reaches `ready`; a keystroke or a suggestion click alone never dismisses the gate. | §2 |
| SG-3 | **New `getAirport` query added to `instructorApi.ts`**, `GET /api/navdata/airports/{icao}` — already server-side and already typed in `schema.d.ts:228`. Resolution uses `useLazyGetAirportQuery`'s imperative `trigger`, not `useGetAirportQuery({skip})`: a query hook re-subscribing to a cached error entry does not refetch by default (`refetchOnMountOrArgChange` is `false`), which would silently break "retry the same ICAO." `usePositionData.ts`'s `useAirport()` is **left untouched in Wave 1** — its stale "there is no `GET /api/navdata/airports/{icao}`" docstring (lines 43–49) is real, but the file is outside #232's/#233's owned set (§7), and #235 already lists the docstring fix as its own fallback close-out item. Fixing it here would be scope creep past the pinned ownership boundary. | §2, §7 |
| SG-4 | **localStorage key `ois-startup-airport`**, JSON `{ "icao": string, "name": string \| null }` — the record shape, not a bare ICAO string, so a friendly label ("Continue with LEMD — Adolfo Suárez Madrid–Barajas") can render on boot before any fetch resolves. Read/write through a **startup-owned** helper (`features/startup/startupSync.ts`), duplicating `uiSync.ts`'s tiny `readStorage`/`writeStorage` try/catch rather than exporting them from `uiSync.ts` — the same call weather-station.md's WS-4 already made for `core/weather_presets/store.py` against `core/profiles/store.py`: a third small copy of an established idiom, not a shared-file edit that would pull `uiSync.ts` outside its scoped concern (hash/theme/demo-feed) and outside #232's owned files. **The remembered airport is the gate's initial value, never a skip** — it pre-fills `query`/`name` and lands the machine in `searching` (an ICAO is always ≥ 2 characters), but the gate always renders and always requires a `resolveSucceeded` to close. | §2, §5.4 |
| SG-5 | **`AirportGate` is a sibling implementation, not a reuse of `AirportMenu.tsx`.** `AirportMenu` is wired to `positionDesignSlice` (`airportMenuOpen`, `icaoInput`) and a `Popover` anchored to a `RefObject` trigger — none of which exists before the shell does. `AirportGate` duplicates the two small constants (`DEBOUNCE_MS = 250`, `MIN_QUERY_LENGTH = 2`) and the debounce-then-search shape, not the component. Same precedent as SG-4. | §5.1 |
| SG-6 | **Mount point: `App.tsx` gates the shell itself, not an overlay.** `const gateOpen = useAppSelector(s => s.startup.status !== 'ready')`; `{gateOpen && <AirportGate />}` renders first, and `header`/`app__body`/`StatusBar` are additionally conditioned on `!gateOpen` — the same idiom `fullBleed` already uses (`{!fullBleed && <header>}`), not a `position: fixed` overlay with `inert` siblings. This avoids two concurrent navdata pollers (`AirportGate`'s own and `PositionPanel`'s, since Position is the default tab and would otherwise mount underneath) and needs no React-version-gated `inert` prop. The three app-wide socket hooks (`useTelemetrySocket`, `useMockTelemetryFeed`, `useTrafficSocket`) stay above the gate and run throughout — SG-8. | §5.2 |
| SG-7 | **Test bypass: `setupStore({ startup: readyStartupState(icao, name) })`**, a fixture exported from `features/startup/testFixtures.ts` (the `features/position/testFixtures.ts` precedent). Every `setupStore()` call in `App.test.tsx` (5 sites) is updated to pass it. **There is no MSW anywhere in this repository** — the task brief's "MSW handler location under `ui/src/mocks/`" does not match the code: `ui/src/mocks/` holds exactly one file, `latency.ts`, a `queryFn`-fixture helper, and `msw` appears only transitively in `package-lock.json`. The actual, established pattern is `vi.stubGlobal('fetch', fetchStub)` matching on `request.url` (`AircraftControlPanel.test.tsx:108–131`). `AirportGate`'s own tests carry their own `stubFetch`; nothing new is added to `ui/src/mocks/`. | §6.1, §7 |
| SG-8 | **The gate never reads `connection`/WebSocket state**, confirmed against `connectionSlice`/`ConnectionBadge.tsx` — neither is imported anywhere in this design. `ConnectionBadge` stays the sole owner of "is the simulator link up"; the gate's only external reads are `getAirport`, `searchAirports` and `getNavdataStatus`. | §5.2 |
| SG-9 | **`SUPPORT_URL` in `ui/src/config/support.ts`** (new directory), one exported constant, a placeholder value with a loud `TODO(#233)` comment — never a real URL invented by this design. | §5.3 |
| SG-10 | **Accessibility:** input `autoFocus` on mount (SG-6 means the gate is the first interactive thing on screen); `role="combobox"` + `aria-expanded`/`aria-controls`/`aria-activedescendant`, a `role="listbox"` of `role="option"` results; ArrowDown/ArrowUp move a local (non-Redux) highlighted index; Enter resolves the highlighted option or, absent one, the raw typed text; Escape collapses the suggestion list only — it does **not** dismiss the gate, which is not closable except by `resolveSucceeded`. Both `data-theme` values styled from existing tokens (`--text`, `--text-dim`, `--border`, `--bg-panel`, `--bg-raised`, `--focus` — `index.css`), no new custom properties. | §5.1 |
| SG-11 | **Parallelisation: #232 first, #233 rebases.** #232's guard in `App.tsx` is structural (wraps the whole header/body in a new condition); #233's button is a small additive leaf inside `app__header-actions`, a block #232 never touches. #232 merges to `dev` first; #233 rebases onto `dev` and its own `App.test.tsx` addition imports #232's already-merged `readyStartupState` fixture. | §7 |

---

## 1. Scope

### 1.1 What this document adds

A blocking, full-screen airport-selection gate that mounts **before** the Instructor Panel shell
(header, tab bar, panel host, status bar) and stays up until an airport has been resolved against
the navigation index. Concretely:

1. A new `startup` Redux slice holding the gate's own state machine (SG-1, SG-2) — client intent
   only, no server data duplicated into it.
2. A type-ahead combobox over the existing `GET /api/navdata/airports` search, and a resolve step
   against the new `getAirport` RTK Query endpoint (SG-3) that both validates the chosen ICAO and
   fetches the fields the rest of the app needs on first paint (name, elevation, position).
3. A remembered-airport pre-fill from `localStorage`, key `ois-startup-airport` (SG-4) — never a
   silent skip.
4. A navdata-not-indexed sub-state, reusing `features/position/gate.ts`'s already-shipped
   `navdataGate()` (SG-6's sibling reasoning does not apply here — this is a pure function with no
   slice coupling, so importing it is not "touching another manager," it is calling a library).
5. A support link in the header, pointing at a placeholder `SUPPORT_URL` (SG-9), a genuinely
   independent leaf the whole rest of this document does not depend on.

### 1.2 What this document explicitly does not do

| Out of scope | Reason |
|---|---|
| Multi-airport sessions, a "recent airports" list beyond the single remembered one | Explicit constraint from the task brief; `positionSlice.recentIcaos` already exists for the Position panel's own, separate "recent" concept and is untouched |
| A router, deep-linking the gate | Hard rule: no router anywhere in this app; `uiSync.ts`'s hash listener is untouched |
| `core/`, `server/`, or adapter changes | Every endpoint needed already exists and is already tested (`tests/server/test_navdata_routes.py::TestAirports`, `core/navdata/provider.py` contract tests) — this document adds no backend surface at all |
| Changes to `AirportMenu.tsx` beyond none | SG-5: sibling implementation, zero edits to the Position manager's own menu |
| A second `schema.d.ts` regen | SG-3's note: `Airport` is already generated (`ui/src/api/models.ts:66`); no route shape changes |
| Fixing `useAirport()`'s stale docstring/implementation | SG-3: deferred to #235, which already lists it as a fallback close-out item, and the file is outside #232/#233's owned set |

---

## 2. REST endpoints

**No new endpoint.** Every call this design makes already exists, is already typed in
`ui/src/api/schema.d.ts`, and is already covered by `tests/server/test_navdata_routes.py`:

| Method | Path | Used for | Already wired client-side? |
|---|---|---|---|
| `GET` | `/api/navdata/status` | Navdata-not-indexed sub-state (SG-6) | Yes — `useGetNavdataStatusQuery` |
| `POST` | `/api/navdata/index` | "Build index" action inside that sub-state | Yes — `useBuildNavdataIndexMutation` |
| `GET` | `/api/navdata/airports?q=&limit=` | Type-ahead suggestions | Yes — `useSearchAirportsQuery` |
| `GET` | `/api/navdata/airports/{icao}` | Resolve step | **No — this document adds the client hook only** (SG-3) |

### 2.1 The one new client endpoint

```ts
// ui/src/api/instructorApi.ts — added inline, next to searchAirports/getRunways/getIls, the
// same "every other navdata read lives here" convention every existing navdata endpoint follows.
getAirport: builder.query<Airport, string>({
  query: (icao) => `navdata/airports/${icao}`,
  providesTags: (_result, _error, icao) => [{ type: 'Airport', id: icao }],
}),
```

`Airport` is imported from `./models` (already generated, `models.ts:66`). The `'Airport'` tag
already exists in `instructorApi.ts`'s `tagTypes` array (line 40) — no new tag type is declared.
`useLazyGetAirportQuery` is RTK Query's auto-generated lazy hook for this `builder.query`; no
`useGetAirportQuery` export is added or used by this design (SG-3).

**Coordination note — a cross-epic collision, not a bug in this design.** `docs/designs/weather-station.md`
§8.1 independently plans to add this exact same `getAirport` endpoint (same signature, same tag),
attributed to its own track #185. The two additions are byte-identical by construction (both were
designed against the same server route and the same existing `'Airport'` tag), so whichever PR
merges to `dev` first defines it in `instructorApi.ts`, and the second rebases and drops its own
hunk as a trivial merge. See §8.

### 2.2 Errors this design must handle client-side

`GET /api/navdata/airports/{icao}` (via `getAirport`):

| Situation | Status | Gate behaviour |
|---|---|---|
| Unknown ICAO | 404 | `resolveFailed('No airport found for "XXXX". Check the ICAO code and try again.')` → `error` state |
| Navdata not ready (race: index dropped mid-session, or the gate's own `getNavdataStatus` poll has not caught up yet) | 503, body `{detail, status}`, `Retry-After` header | **Not** treated as `resolveFailed`. `dispatch(instructorApi.util.invalidateTags(['NavdataStatus']))`, then fall back to `searching`/`idle` via `queryTyped(currentText)` — the navdata-not-indexed sub-state (already polling) takes over rendering. `fetchBaseQuery` does not surface response headers without a custom `baseQuery`, which is out of scope for "`getAirport` only" (SG-3) — the `Retry-After` value is never parsed; the existing poll cadence (§5.4) is the only retry mechanism |
| Network unreachable | `FETCH_ERROR` (RTK Query's own tag, no `status`) | `resolveFailed('The station could not be reached. Check the network connection.')` |

`GET /api/navdata/airports?q=` (via the existing `searchAirports`): unchanged behaviour, the same
`isError` the panel treats as "the index could not be searched" (`AirportMenu.tsx`'s own wording,
reused verbatim by `AirportGate` — not shared code, matching text, SG-5).

---

## 3. Pydantic models

**None.** No server-side model is added, changed, or reinterpreted. `Airport`, `AirportSummary`,
`NavdataStatus`, `NavdataState` (`core/navdata/models.py`) are consumed exactly as already
generated. This is the good outcome the planner brief calls out explicitly: say so, move on.

---

## 4. Client-side contracts

### 4.1 `startup` slice — exact shape

New file `ui/src/features/startup/startupSlice.ts`, registered as `state.startup` in
`store/index.ts`'s `reducerMap` (one more entry, the same shape every other manager's slice already
takes).

```ts
export type StartupStatus = 'idle' | 'searching' | 'resolving' | 'ready' | 'error';

/** Below this, a query matches too much to be worth asking about — the same threshold
 * AirportMenu.tsx uses, duplicated rather than imported (SG-5). */
export const MIN_QUERY_LENGTH = 2;

export interface StartupState {
  status: StartupStatus;
  /** The combobox's raw text, updated on every keystroke. */
  query: string;
  /** The ICAO under resolution, or the last one resolved. `null` before the first attempt. */
  icao: string | null;
  /** The resolved (or remembered) airport's display name. `null` until known. */
  name: string | null;
  /** Set only in `error`; cleared by any further `queryTyped` or a new `resolveRequested`. */
  errorMessage: string | null;
}

export const initialStartupState: StartupState = {
  status: 'idle',
  query: '',
  icao: null,
  name: null,
  errorMessage: null,
};
```

Reducers:

```ts
reducers: {
  /** Every keystroke. Status follows the raw text's length; the debounce that gates the
   * actual network call is local component state (§5.1), not stored here. */
  queryTyped(state, action: PayloadAction<string>) {
    state.query = action.payload;
    state.errorMessage = null;
    state.status = action.payload.trim().length >= MIN_QUERY_LENGTH ? 'searching' : 'idle';
  },

  /** Enter, or a suggestion click. Reachable from idle/searching/error — never from
   * resolving (the input is disabled there, §5.1) or ready (the gate is gone). */
  resolveRequested(state, action: PayloadAction<string>) {
    state.status = 'resolving';
    state.icao = action.payload.toUpperCase();
    state.errorMessage = null;
  },

  /** The only transition into `ready`. */
  resolveSucceeded(state, action: PayloadAction<{ icao: string; name: string }>) {
    state.status = 'ready';
    state.icao = action.payload.icao;
    state.name = action.payload.name;
    state.errorMessage = null;
  },

  resolveFailed(state, action: PayloadAction<string>) {
    state.status = 'error';
    state.errorMessage = action.payload;
  },

  /** Boot-time prefill from localStorage (SG-4). Pre-fills only — never resolves on its
   * own, so the gate always shows regardless of what is remembered. An ICAO is always
   * >= MIN_QUERY_LENGTH characters, so this always lands in `searching`. */
  rememberedAirportLoaded(state, action: PayloadAction<{ icao: string; name: string | null }>) {
    state.query = action.payload.icao;
    state.name = action.payload.name;
    state.status = action.payload.icao.length >= MIN_QUERY_LENGTH ? 'searching' : 'idle';
  },
},
```

**No third source of truth (SG-1, SG-8).** `startup.icao`/`startup.name` exist only to drive the
gate itself and the localStorage payload; the instant `resolveSucceeded` fires, the same handler
(§4.2, not `extraReducers`) also dispatches `positionSlice.airportSelected` and
`positionDesignSlice.airportLoaded`, and from that point on `positionDesign.loadedIcao` is the
single place "which airport is loaded" lives for the rest of the session. Nothing downstream of the
gate ever reads `state.startup` again — `AirportGate` itself unmounts once `status === 'ready'`
(§5.2).

### 4.2 Resolve handler — where the fan-out lives

Inside `AirportGate.tsx` (or a co-located hook in the same file — an internal implementation
choice, not a contract question), never in a reducer:

```ts
const [triggerGetAirport] = useLazyGetAirportQuery();
const dispatch = useAppDispatch();

function resolve(rawText: string) {
  const icao = rawText.trim().toUpperCase();
  if (icao.length < MIN_QUERY_LENGTH) return;
  dispatch(resolveRequested(icao));
  void triggerGetAirport(icao)
    .unwrap()
    .then((airport) => {
      dispatch(resolveSucceeded({ icao: airport.icao, name: airport.name }));
      // The fan-out §2.1's docstring in positionDesignSlice.ts asks for: mirroring
      // airportSelected onto positionSlice is "the calling component's job." This is that
      // component. airportSelected also resets weather staging (weather-station.md WS-1's
      // reducer, unrelated to this document) — harmless here, since nothing is staged yet.
      dispatch(airportSelected(airport.icao));
      dispatch(airportLoaded(airport.icao));
    })
    .catch((error: FetchBaseQueryError | SerializedError) => {
      if ('status' in error && error.status === 503) {
        dispatch(instructorApi.util.invalidateTags(['NavdataStatus']));
        dispatch(queryTyped(rawText)); // falls back to searching/idle; the navdata
                                        // sub-state (already polling, §5.4) takes over
        return;
      }
      dispatch(resolveFailed(errorMessageFor(error, icao)));
    });
}
```

### 4.3 `startupSync.ts` — the boot hook

New file `ui/src/features/startup/startupSync.ts`, `initStartupSync(store)`, called from
`main.tsx` next to the existing `initUiSync(store)`:

```ts
export function initStartupSync(store: AppStore): void {
  const raw = readStartupStorage();          // duplicated try/catch, SG-4
  if (raw !== null) {
    store.dispatch(rememberedAirportLoaded(raw));
  }
  let last = store.getState().startup.status;
  store.subscribe(() => {
    const next = store.getState().startup;
    if (next.status === 'ready' && last !== 'ready') {
      writeStartupStorage({ icao: next.icao!, name: next.name });
    }
    last = next.status;
  });
}
```

`main.tsx` gains one import and one call, mirroring `initUiSync(store)` exactly — this is why
`main.tsx` is in #232's owned file set (§7), not an incidental touch.

### 4.4 Error message helper

```ts
// ui/src/features/startup/errorMessage.ts
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
```

---

## 5. UI panel outline

### 5.1 `AirportGate.tsx`

New file, `ui/src/features/startup/AirportGate.tsx`. Structure, closely mirroring `AirportMenu.tsx`
without its `Popover`/`positionDesignSlice` coupling (SG-5):

```
<section class="startup-gate" role="dialog" aria-modal="true" aria-label="Choose an airport">
  {navdata not ready → NavdataBlock (below), input area not rendered at all}
  {navdata ready →
    <div class="startup-gate__card">
      <h1>Open Instructor Station</h1>
      <p>Choose the airport for this session.</p>

      {remembered airport known && status === 'searching' && query === remembered.icao &&
        <button class="startup-gate__remembered" onClick={() => resolve(remembered.icao)}>
          Continue with {remembered.name ?? remembered.icao}
        </button>}

      <input
        role="combobox"
        aria-expanded={status === 'searching' && results.length > 0}
        aria-controls="startup-gate-listbox"
        aria-activedescendant={highlighted ? `startup-gate-option-${highlighted}` : undefined}
        autoFocus
        disabled={status === 'resolving'}
        value={query}
        onChange={(e) => dispatch(queryTyped(e.target.value))}
        onKeyDown={handleKeyDown}   {/* ArrowUp/Down move `highlighted`, Enter → resolve(),
                                        Escape → collapse suggestions only */}
      />

      {status === 'idle' && <p class="startup-gate__hint">Type at least 2 characters — an
        ICAO or IATA code, or a name.</p>}

      {status === 'searching' && isError && <p class="startup-gate__error">The airport index
        could not be searched. Check the connection to the station.</p>}

      {status === 'searching' && !isError && results.length === 0 && !isFetching &&
        <p class="startup-gate__hint">No airport matches "{debounced}".</p>}

      {status === 'searching' && !isError && results.length > 0 &&
        <ul role="listbox" id="startup-gate-listbox">
          {results.map((airport, i) => (
            <li role="option" id={`startup-gate-option-${airport.icao}`}
                aria-selected={i === highlighted}
                onClick={() => resolve(airport.icao)}>
              {airport.icao} — {airport.name}
            </li>
          ))}
        </ul>}

      {status === 'resolving' && <p class="startup-gate__loading">Loading {icao}…</p>}

      {status === 'error' && <p class="startup-gate__error">{errorMessage}</p>}
    </div>}
</section>
```

`DEBOUNCE_MS = 250`, `MIN_QUERY_LENGTH = 2` — sibling copies of `AirportMenu.tsx`'s own constants
(SG-5). The debounced value is local `useState`, exactly as `AirportMenu.tsx` keeps it, driving
`useSearchAirportsQuery({ query: debounced, limit: 8 }, { skip: status !== 'searching' })`. Result
list capped at 8 (a full-screen gate has more room than the header popover's `limit: 12`, but 8
keeps the touch-target list one screen-height on a tablet portrait).

Tablet-first: input and every listbox row ≥ 44 px tall (the "Continue with…" button too); the card
is centred, `max-width` capped so it reads as a dialog rather than stretching edge-to-edge on a
desktop-wide viewport, full-width on a narrow tablet portrait.

### 5.2 Navdata-not-indexed sub-state (SG-6, SG-7)

Reuses `features/position/gate.ts`'s `navdataGate()` and `NavdataGate` type directly (pure
function, no store access — importing it is calling a library, not editing the Position manager).
`AirportGate.tsx` owns its own small presentational block (not a reuse of `PositionPanel.tsx`'s
private, unexported `NavdataCard` — that component is not exported, so this is a sibling by
necessity, same reasoning as SG-5):

```ts
const cached = instructorApi.endpoints.getNavdataStatus.useQueryState();
const { data: status, isError } = useGetNavdataStatusQuery(undefined, {
  pollingInterval: cached.data?.state === 'building' ? BUILD_POLL_MS : 0,  // 1000, matching
  skipPollingIfUnfocused: true,                                            // PositionPanel.tsx
});
const gate = navdataGate(status, isError);
```

While `gate.kind !== 'ready'`: the combobox area is replaced by `gate.reason`, an optional
`role="progressbar"` while `kind === 'building'`, and a "Build index" button
(`useBuildNavdataIndexMutation`) while `gate.canBuild`. **`Retry-After` is never parsed** (SG-3,
§2.2) — the existing poll cadence is the only retry mechanism, matching `PositionPanel.tsx`'s own
posture exactly.

### 5.3 `App.tsx` mount point (SG-6, exact diff shape)

```tsx
const gateOpen = useAppSelector((state) => state.startup.status !== 'ready');
const fullBleed = activeTab === 'position';

return (
  <div className={fullBleed ? 'app app--fullbleed' : 'app'}>
    {gateOpen && <AirportGate />}

    {!gateOpen && !fullBleed && (
      <header className="app__header">
        {/* … unchanged … */}
      </header>
    )}

    {!gateOpen && (
      <div className="app__body">
        {/* … unchanged … */}
      </div>
    )}

    {!gateOpen && !fullBleed && <StatusBar />}
  </div>
);
```

Only three conditions gain a `!gateOpen &&` clause; nothing inside `header`/`app__body`/`StatusBar`
changes. The three socket hooks at the top of `App()` (`useTelemetrySocket`, `useMockTelemetryFeed`,
`useTrafficSocket`) are unconditional and keep running while the gate is up (SG-8) — the connection
badge the instructor sees the moment the gate closes is not starting from zero.

### 5.4 Support link (#233, SG-9)

`ui/src/config/support.ts`:

```ts
/**
 * Where the "Support" header link points.
 *
 * PLACEHOLDER — TODO(#233): replace with the real support URL (a GitHub issue template,
 * a docs site, a contact form — repo owner's call) before this branch merges to dev.
 */
export const SUPPORT_URL = 'https://example.com/open-instructor-station/support';
```

One new element in `App.tsx`'s `app__header-actions`, after `ConnectionBadge`, reusing
`ProcedureDiagram3D.tsx`'s exact external-link pattern (`target="_blank" rel="noreferrer"`, not
`noopener noreferrer`):

```tsx
<a className="ghost-button" href={SUPPORT_URL} target="_blank" rel="noreferrer">
  Support
</a>
```

`.ghost-button` (`index.css:225`) is class-scoped, not element-scoped, so an `<a>` picks up
identical chrome with no CSS change required; an optional `display: inline-flex; align-items: center;`
tweak is left to the implementer only if vertical alignment against the adjacent `<button>`s looks
off in practice (non-blocking).

---

## 6. Test plan

### 6.1 `startupSlice.test.ts`

- `queryTyped` below/at/above `MIN_QUERY_LENGTH` → `idle`/`searching`/`searching`, table-driven
  over `''`, `'L'`, `'LE'`, `'LEMD'`.
- `queryTyped` clears `errorMessage` and moves out of `error`.
- `resolveRequested` sets `status='resolving'`, uppercases the ICAO, clears `errorMessage`, from
  each of `idle`/`searching`/`error` as the starting state.
- `resolveSucceeded` sets `ready`, `icao`, `name`; `resolveFailed` sets `error` and the message,
  leaving `icao` as the last attempted value.
- `rememberedAirportLoaded('LEMD', 'Adolfo Suárez Madrid–Barajas')` → `status='searching'`,
  `query='LEMD'`, `name` set — never `'ready'`.

### 6.2 `AirportGate.test.tsx`

Own `stubFetch` (the `AircraftControlPanel.test.tsx` pattern, §0 SG-7 — matching on
`request.url.includes(...)`), covering `/api/navdata/status` (ready), `/api/navdata/airports?q=`,
`/api/navdata/airports/{icao}` (200 and 404), `/api/navdata/index`.

- Renders with `autoFocus` on the input; typing under 2 characters shows the hint, not the listbox.
- Typing "LEM" (debounced) issues one `searchAirports` request, not one per keystroke — a
  `vi.useFakeTimers()` + `advanceTimersByTime(DEBOUNCE_MS)` assertion, `AirportMenu.test.tsx`'s
  own idiom if one exists, else the same pattern freshly written here.
- Selecting a suggestion (click or Enter-on-highlighted) dispatches `resolveRequested`, then on the
  stubbed 200 dispatches `resolveSucceeded` **and** both `positionSlice.airportSelected` +
  `positionDesignSlice.airportLoaded` — asserted via `store.getState()`, not by re-rendering
  `PositionPanel` (out of this component's concern).
- A stubbed 404 on `getAirport` lands in `error` with the exact message from §4.4's table; typing
  again clears it.
- A stubbed 503 (with a `status` JSON body) does **not** reach `error` — asserted by checking
  `store.getState().startup.status !== 'error'` and that the navdata block, not the error message,
  is what renders next.
- A remembered airport (`localStorage.setItem('ois-startup-airport', '{"icao":"LEMD","name":"…"}')`
  before render) shows the "Continue with…" button and pre-fills the input, without auto-resolving
  — asserted by confirming no `getAirport` request fires until the button or Enter is pressed.
- Arrow-key navigation moves `aria-activedescendant`; Escape collapses the listbox without changing
  `status`; the gate never closes from Escape.
- `resolveSucceeded` writes `ois-startup-airport` to `localStorage`, in the shape SG-4 pins.

### 6.3 `App.test.tsx` — regression, not new coverage

All five existing tests are updated to `setupStore({ startup: readyStartupState('LEMD', 'Adolfo
Suárez Madrid–Barajas Airport') })`; `readyStartupState` lives in
`features/startup/testFixtures.ts` (SG-7):

```ts
export function readyStartupState(icao: string, name: string): StartupState {
  return { status: 'ready', query: icao, icao, name, errorMessage: null };
}
```

A sixth, new test: `setupStore()` with **no** preloaded state renders `AirportGate` instead of the
header/tab bar/status bar — the direct assertion that the gate blocks by default.

#233's own `App.test.tsx` addition (support link renders with the right `href`/`target`/`rel`) also
uses `readyStartupState` (imported post-#232-merge, per SG-11) so the header is visible to query
against.

### 6.4 What is `@pytest.mark.sim`

**Nothing.** This entire document is `ui/`-only; no Python file changes, no adapter surface, no
live-sim assertion. Backend coverage of every endpoint used (`getAirport`, `searchAirports`,
`getNavdataStatus`, `buildNavdataIndex`) is already in `tests/server/test_navdata_routes.py` and
`core/navdata/`'s own contract tests — no new backend test is written for this document.

### 6.5 Fixtures

No navdata fixture is added (hard rule 4 — this document has no server-side surface). Client-side,
`AirportGate.test.tsx`'s `stubFetch` uses hand-written `Airport`/`AirportSummary`/`NavdataStatus`
literals typed against the generated `models.ts`, `features/position/testFixtures.ts`'s own
convention.

---

## 7. Parallelisation

Wave 0 (this document, **serial**) → Wave 1 (#232 the gate, #233 the support link — **2 parallel**,
in separate worktrees).

| Track | Owns (disjoint) | May start |
|---|---|---|
| **This document — SERIALISED** | `docs/designs/startup-airport-loading.md` | first, alone |
| **#232 — the gate** | `ui/src/features/startup/**` (new: `startupSlice.ts`, `AirportGate.tsx`, `AirportGate.css`, `startupSync.ts`, `errorMessage.ts`, `testFixtures.ts`, and their `.test.` files), `ui/src/api/instructorApi.ts` (`getAirport` only, §2.1), `ui/src/store/index.ts` (one `reducerMap` entry), `ui/src/main.tsx` (one import + one `initStartupSync(store)` call), the gate guard in `ui/src/App.tsx` (§5.3's exact three clauses), the bypass fixture applied to `ui/src/App.test.tsx`'s five existing tests plus the one new test (§6.3) | after this document |
| **#233 — support link** | `ui/src/config/support.ts` (new), one `<a>` in `ui/src/App.tsx`'s `app__header-actions` (§5.4), one new test in `ui/src/App.test.tsx`, an optional `.ghost-button` CSS tweak in `ui/src/index.css` | after this document |

**Dispatch:** `{#232, #233}` in one message, two worktrees, once this document is reviewed and
landed — genuinely independent surfaces (§0's SG-11 reasoning: #232's `App.tsx` edit is structural
around the header/body conditionals, #233's is a single additive leaf inside a block #232 never
touches).

**Merge order: #232 first.** Its guard changes `App.tsx`'s control flow; #233's button is additive
inside a region #232 does not edit, so #233 rebases onto `dev` cleanly once #232 lands, and its own
`App.test.tsx` test imports #232's now-merged `readyStartupState` fixture (§6.3) rather than
inventing a second bypass.

**Never parallelised:** this document itself; the `getAirport` addition to `instructorApi.ts`
racing against `docs/designs/weather-station.md`'s own #185 (§2.1's coordination note — resolved by
"whichever merges to `dev` first wins, the other rebases," not by pre-coordinating the two epics'
schedules); merges to `dev`/`main`; release tagging. No `SimAdapter`/`Capabilities` change and no
navdata schema migration exists anywhere in this document (§3, §4), so neither CLAUDE.md
"never parallelise" clause beyond the generic merge/tag rule is in play here.

---

## 8. Open questions and risks

### 8.1 The `getAirport` cross-epic collision — real, not hypothetical

§2.1 and §0 (SG-3) already flag it: this document and `docs/designs/weather-station.md` §8.1 both
plan the identical addition to `instructorApi.ts`. Because both were designed against the same
already-existing server route and the same already-existing `'Airport'` tag, the two additions are
byte-identical, so the collision resolves as a trivial rebase regardless of merge order — but it is
worth the caller's attention that **whichever of epic #179's #185 or epic #230's #232 merges to
`dev` second must drop its own hunk**, not merge both (which would be a harmless-looking duplicate
key in the `endpoints` object that TypeScript would actually reject at compile time). No spike
needed; this is a process note for whoever merges the second PR.

### 8.2 This document could not fetch issues #230–#235 directly

No `gh` CLI or Bash tool was available to this design pass — only `Read`/`Grep`/`Glob`/`advisor`.
Every code-level claim above (line numbers, existing constants, existing patterns) was verified
directly against the repository. §1's scope and §0's 11 pinned decisions are built from the task
brief's own summary of issue #231's body. **Resolution: the caller cross-checks §1 against #230's
own 8 numbered goals and #231's own 11-item list before this document is treated as final** — if
either enumerates something this document does not cover, that is a real gap, not a design choice.

### 8.3 Three claims in the task brief that the code contradicted, and how this document resolved them

Recorded here rather than silently corrected, so a reviewer comparing this document against the
original brief is not confused by the discrepancy:

- **"MSW handler location under `ui/src/mocks/`"** — no MSW package is used anywhere in this
  repository (only a transitive mention in `package-lock.json`). The actual pattern is
  `vi.stubGlobal('fetch', fetchStub)`, per test file. §0 SG-7, §6.1–§6.3 design around the real
  pattern.
- **`useAirport()`'s docstring "There is no `GET /api/navdata/airports/{icao}`"** — false as of this
  commit; the endpoint exists and is generated. §0 SG-3 leaves the fix to #235, out of ownership
  scope rather than silently patching a file neither #232 nor #233 owns.
- **App.tsx line numbers "~51–71" for `app__header-actions`** — the task brief itself already
  flagged and corrected this against the verified `App.tsx:61–72`; this document's own reads
  (`App.tsx:53–74`, current commit) match the corrected numbers, confirmed independently.

### 8.4 Not resolved by this document — left to the implementer, non-blocking

- The exact visual treatment of the gate card (imagery, animation, whether "loading screen" implies
  a splash/logo beyond the plain dialog sketched in §5.1) — nothing downstream depends on it, the
  same posture weather-station.md §11.3 takes for its own cloud-type glyph choice.
- Whether `AirportGate.css` needs a dedicated dark/light contrast pass beyond reusing existing
  tokens (SG-10) — no test in §6 asserts specific colour values.
- The real `SUPPORT_URL` (SG-9) — explicitly the repo owner's decision, never invented here.

---

## 9. Verification

```bash
pytest                       # unchanged — no Python file in this document's surface
ruff check . && ruff format --check .
mypy .
cd ui && npm run lint && npm run typecheck && npm test && npm run build
```

No `pytest -m sim` gate exists for this document's own surface (§6.4). No `npm run generate:api`
step — `Airport` is already generated (§0 SG-3, §1.2).

Manual smoke, once #232 and #233 have both landed on `dev`: open the app cold (no
`ois-startup-airport` in `localStorage`) — gate shows, header/tab bar absent; type "LEM", see the
debounced suggestion list; pick LEMD — gate closes, Position panel shows LEMD loaded, Support link
visible in the header. Reload — gate shows again (never skips), pre-filled with "Continue with
LEMD…"; click it — gate closes without retyping. Type an unknown code, press Enter — error message,
input still editable. Support link opens in a new tab, console clean throughout.
