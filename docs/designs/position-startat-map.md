# Design: rename "Start at Runway" and rebuild its picker on MapLibre

## 1. Scope

**Issue:** GitHub #155. **Manager:** Position Manager (`docs/feature-spec.md` §1), specifically the
Start-at picker inside `PositionHeaderBar`. **Roadmap phase:** Phase 1 — Position Manager +
Aircraft Control, marked *complete* in `docs/roadmap.md`; this is a post-completion UI refinement,
not new phase-gating functionality, so it does not move any exit criterion.

**What this manager does, in this change:**

- Renames the header's Start-at trigger from `Start at {label}` to `Start position · {label}`, so
  the control's own name no longer implies it is a runway-only picker.
- Replaces the picker's internal 340×262 hand-drawn SVG (`AirportDiagram.tsx` +
  `standProjection.ts`) with a real MapLibre GL canvas showing the airport's runway pavement, every
  runway threshold, and every parking stand as clickable markers — reusing the exact MapLibre stack
  already built for the Instructor Map tab (`ui/src/features/map/`), per CLAUDE.md rule 6 ("the
  stack is settled") and rule 5 (OSM tiles only).
- Widens the popover so the map is worth having (716px → up to 1040px, clamped to the viewport).
- Keeps the picker's existing sidebar (runway list + parking-type filter) and stands list column
  unchanged in behaviour; only their width/height are adjusted to match the new map size.

**What this explicitly does NOT do:**

- No new REST endpoint, no new Pydantic model, no new `SimAdapter` capability, no new dataref, no
  `core/` logic. The picker already reads runways and parking through `useRunways()` /
  `useGetParkingQuery()` (existing `GET /api/airports/{icao}/runways`,
  `GET /api/airports/{icao}/parking`); this change touches how that data is *drawn*, not how it is
  fetched.
- No change to `positionDesignSlice`'s action or state names (`startAtOpen`, `startAtToggled`,
  `startRunwaySelected`, `startStandSelected` all keep their current names — see §7). Only the
  **rendered copy** of the trigger button changes; the internal identifiers are not user-facing and
  renaming them would be pure churn against `docs/designs/position-redesign-v3.md`'s frozen action
  list for no behavioural gain.
- No change to `positionSlice.ts` (the shared server-intent slice) or to the mirrored-dispatch
  guards (`runwaySelected` same-value check) — those are untouched, existing behaviour.
- Does not touch `coordinateHandoffReceived` or the full Map tab's reposition flow. A map-marker
  click in this popover dispatches `startRunwaySelected`/`startStandSelected` directly, exactly
  like today's list-item clicks — never the Map tab's lat/lon hand-off reducer.
- Does not add a fallback rendering path for tile-fetch failure (see §3/§9 for the reasoning: the
  old SVG is deleted outright, not kept as a fallback).

---

## 2. REST endpoints

N/A — UI-only change, reuses existing navdata endpoints.

For traceability: the picker already calls `GET /api/airports/{icao}/runways` (via
`useRunways()` → `useGetRunwaysQuery`) and `GET /api/airports/{icao}/parking` (via
`useGetParkingQuery`), both defined in `ui/src/api/instructorApi.ts`. No request shape, query
parameter, or response shape changes. No new endpoint is added.

## 3. Pydantic models

N/A — UI-only change, reuses existing navdata endpoints.

The data plotted on the map is the existing generated `Runway` and `ParkingStand` types
(`ui/src/api/models.ts`, generated from the server's OpenAPI schema per CLAUDE.md rule 7). No new
field is read from either model beyond what `AirportDiagram.tsx`/`StartAtPopover.tsx` already read
today: `Runway.threshold`, `Runway.opposite_ident`, `Runway.ident`, `Runway.ils`,
`Runway.pavement_end`, `Runway.width_m`, `Runway.length_m`, `Runway.true_bearing_deg` (the last
four already consumed by `features/map/overlays.ts`'s `runwayFeature`, reused as-is — see §6/§7);
`ParkingStand.name`, `ParkingStand.kind`, `ParkingStand.position`.

## 4. `SimAdapter` / `Capabilities` additions

N/A — UI-only change, reuses existing navdata endpoints. No adapter, no capability flag, no
dataref is touched by this issue. This section requires no contract-suite change
(`tests/adapters/test_contract.py` is untouched).

## 5. Dataref mapping (X-Plane)

N/A — UI-only change, reuses existing navdata endpoints. This design touches `ui/` only; no file
under `adapters/xplane/` changes, and no dataref name appears anywhere in this design (consistent
with CLAUDE.md rule 2, `core/` never talks to a simulator — moot here since `core/` is untouched).

## 6. `core/` logic

N/A — UI-only change, reuses existing navdata endpoints. No Python file changes. Nothing in this
design is unit-testable outside a browser/jsdom environment; there is no sim-agnostic algorithm to
extract into `core/` (the projection math it replaces, `standProjection.ts`, was itself a
TypeScript UI module, never a `core/` module, and it is deleted — see §9).

---

## 7. UI panel outline

### Files

Everything is in `ui/src/features/position/` unless stated otherwise.

**Delete:**
- `AirportDiagram.tsx` (no test file exists for it directly — its behaviour was covered only
  through `StartAtPopover.test.tsx`, addressed in §8).
- `standProjection.ts` + `standProjection.test.ts`. The projection this module solves — lat/lon →
  screen pixels, with a symmetric-widen + minimum-span + longitude-squeeze — is exactly what
  MapLibre's own Web Mercator projection already does, correctly, with real zoom and pan on top.
  Keeping it "as a fallback" would mean maintaining a second, worse map projection for a scenario
  (tile-fetch failure) that does not need it: MapLibre's DOM `Marker` elements are positioned by
  the map's client-side camera transform, which works identically whether or not the raster tiles
  ever load (the style is inline JSON with no external glyph/style server dependency — only the
  *tile images* can fail to fetch, and a blank/grey canvas under working, click-able markers is
  strictly better than today's static SVG, which has no zoom or pan at all). **Decision: delete
  outright, no fallback kept.**

**New — components:**

| File | Role |
|---|---|
| `StartAtMap.tsx` | Replaces `AirportDiagram.tsx`. Owns a `useMapLibre` instance sized to the popover's map column, the runway-pavement layer, and delegates marker lifecycle to `useStartAtMarkers`. Pure props in (`runways`, `stands`, `selectedRunway`, `selectedStand`, `onSelectRunway`, `onSelectStand`, `centerHint`), no direct store access — same posture as `MapPanel.tsx`/hook split. |

**New — hooks (`.ts`, no JSX — `react-refresh/only-export-components` stays satisfied):**

| File | Role |
|---|---|
| `useStartAtMarkers.ts` | Builds one MapLibre `Marker` per runway threshold and one per parking stand, wires their DOM element's click to the passed-in `onSelectRunway`/`onSelectStand` callbacks, and flips selected styling without rebuilding markers. Modelled on `features/map/useAircraftMarker.ts`'s element-`Marker` pattern, **without** its telemetry subscription — this hook is purely prop-driven, not `store.subscribe`-driven. |

**Edited:**

- `PositionHeaderBar.tsx` — trigger button copy only (see "Button copy" below); no logic change.
- `StartAtPopover.tsx` — swap `<AirportDiagram stands={...} runways={...} .../>` for
  `<StartAtMap stands={...} runways={...} onSelectRunway={selectRunway} onSelectStand={(name) => dispatch(startStandSelected(name))} .../>`.
  Passing the **same** `selectRunway` closure already used by the sidebar list (and the **same**
  inline stand-select dispatch already used by the stands list) is what guarantees, by
  construction rather than by convention, that a map click and a list click take the identical
  code path. Also add `aria-label={\`Stand ${stand.name}\`}` to the existing stands-list row buttons
  (currently absent — see §8 for why this is load-bearing for test parity).
- `ui/src/features/map/useMapLibre.ts` — parameterised in place (see "useMapLibre reuse strategy"
  below). Its one existing call site, `MapPanel.tsx:143`, is unaffected (it passes no options and
  gets today's exact `MAP_HOME`/`MAP_HOME_ZOOM` defaults).
- `ui/src/test/maplibreStub.ts` — two small additive changes needed for real (non-vacuous) test
  coverage, detailed in §8: record `Map`'s constructor options, and add a `fitBounds(): void {}`
  no-op. Both are backward compatible; no existing test's behaviour changes.
- `position.css` — widen `.pos-startat`, add `.pos-startat__map` sizing rules and marker button
  styles; remove the now-dead `.pos-diagram*` rules.

### `useMapLibre` reuse strategy — parameterize in place

**Decision: parameterize in place.** One existing consumer (`MapPanel.tsx:143`), confirmed by
`Grep`. A second hook would duplicate the OSM style constant, the `ResizeObserver` guard, and the
`'load'`-gated `null` handle — three things that must never drift apart between the two map
instances (rule 5, OSM-only, applies equally to both).

```ts
export interface MapLibreOptions {
  /** [lon, lat]. Defaults to MAP_HOME (today's exact behaviour) when omitted. */
  readonly center?: readonly [number, number];
  /** Defaults to MAP_HOME_ZOOM when omitted. */
  readonly zoom?: number;
}

export function useMapLibre(options: MapLibreOptions = {}): MapLibreHandle
```

The style stays the shared inline `OSM_STYLE` — no new parameter for it; every consumer draws OSM
tiles, per rule 5, and a style override was not asked for and would invite a non-OSM source later.

**Critical implementation detail, stated explicitly so it isn't lost between design and code:**
`options` must be read **once**, via a `useRef` initialised from the first render's value
(`const initialOptions = useRef(options).current` at the top of the hook, *before* the mount
effect), and the effect must reference `initialOptions`, never the `options` parameter directly,
and must **not** list `options` in its dependency array. A ref access inside an effect is exempt
from `react-hooks/exhaustive-deps` by design (it is not treated as reactive state), so this needs
no lint suppression. Doing it any other way — passing a fresh `[lon, lat]` array literal each
render into the dependency array — would tear down and recreate the `maplibre-gl` `Map` (and
re-fetch every tile) on every re-render of `StartAtMap`, which renders on every Redux dispatch
(e.g. every keystroke in the airport search).

`MapPanel.tsx` needs zero changes: `useMapLibre()` with no arguments keeps producing exactly
today's `center: [MAP_HOME.lon, MAP_HOME.lat], zoom: MAP_HOME_ZOOM`.

### Button copy

The three trigger states, using `·` as the label/value separator (the same convention already
used in this screen's footer, `"Navdata X-Plane 12 · AIRAC 2508 · METAR 6 min old"`):

| State | Trigger text |
|---|---|
| Nothing selected | `Start position · Not set` |
| Runway selected | `Start position · Runway 04R` |
| Stand selected | `Start position · Stand A3` |

Rationale: "Start at" paired with a runway-shaped value (`Runway 24L`) reads as "this button is
about runways." "Start position" is the neutral noun the picker actually resolves — a position,
which happens to come from either a runway or a stand — and it is honest about what opens
underneath it: a picker of *positions*, not a picker of *runways*. The value chip itself is
unchanged (`Runway {ident}` / `Stand {name}` / `Not set`), since it correctly names what is
currently staged; only the leading label changes. JSX changes from
`Start at <span className="pos-mono">{startAtLabel}</span>` to
`Start position · <span className="pos-mono">{startAtLabel}</span>` (the `·` is a plain text node,
not mono — matches the footer's existing pattern).

`aria-haspopup="dialog"`, `aria-controls="pos-startat-popover"`, and the dispatch of
`startAtToggled()` are unchanged.

### Popover layout and sizing

**Decision: the map replaces the diagram region and the popover grows to make room for it** — a
340×262 box inside even a widened 716px popover would still be a postage stamp; the issue's whole
point is that a real map is worth pixels. Concrete target dimensions:

```css
.pos-startat {
  left: 12rem;
  /* Bounded by: an absolute cap, the viewport's own gutter, and this popover's own left
     offset plus a matching right gutter — whichever is smallest wins, so it never runs off
     the right edge of a narrow tablet in portrait. */
  width: min(1040px, calc(100vw - 2rem), calc(100vw - 13rem));
  display: grid;
  grid-template-columns: 186px minmax(420px, 1fr) 220px;
  gap: 1rem;
}

.pos-startat__map {
  width: 100%;
  height: 420px;
  min-width: 420px;
}

.pos-startat__stands-list {
  max-height: 420px; /* was 262px — matches the new map height */
  overflow-y: auto;
}
```

Sidebar (186px) and its two lists (Runways, Parking type) are untouched. The stands column widens
slightly (200px → 220px) for the longer rows a bigger picker invites, but this is cosmetic, not
load-bearing.

**Mount/animation timing:** confirmed by `Grep` that `.pos-popover` carries no `transition` or
`animation` rule (the only `animation`/`@keyframes` in `position.css` is the unrelated connection
status dot's blink). `Popover.tsx` renders `null` outright when `open` is `false` and mounts its
children only once `open` flips `true` — there is no width/opacity transition to race. `StartAtMap`
therefore mounts at its **final** grid-determined size on the very first paint; `maplibre-gl`'s
`Map` constructor measures the container synchronously in that same paint, so **no explicit resize
kick is needed at open-time**. The existing generic `ResizeObserver` inside `useMapLibre` (unchanged
by this design) remains the correct mechanism for anything that changes the container's size
*after* construction (a font-loading reflow, a future viewport resize while the popover is open).
If a future change ever wraps this popover in an opening transition, that change must add a
`requestAnimationFrame` + `map.resize()` kick — flag this in a code comment on `StartAtMap` so a
future editor doesn't have to rediscover it.

**Consequence of `Popover` unmounting on close:** because `Popover` returns `null` when closed,
`StartAtMap`'s `useMapLibre()` mount effect tears down (`instance.remove()`) on every close and
constructs a fresh `maplibre-gl.Map` on every re-open. **Accepted as the boring option** — the
browser's own tile cache makes a re-open cheap, and keeping the map instance alive across close
would require lifting it out of `Popover`'s conditional render (defeating the existing
`queryByRole('dialog')`-based close assertions in `StartAtPopover.test.tsx`) for a cost (one map
re-init on re-open) that is not worth that structural change. State this in code as a comment on
`StartAtMap`, not silently.

### Marker rendering approach

**Decision: DOM `Marker` elements with real `<button>` children for both runway thresholds and
stands — not GeoJSON circle-layer click handlers.** A canvas layer click gives no DOM node, no
`aria-pressed`, no keyboard focus, and no guaranteed 44px hit-box — all things CLAUDE.md's
tablet-first rule and this screen's existing accessibility pattern (`AirportDiagram.tsx`'s
`aria-pressed`/`aria-label="Stand A1"` buttons) require. `useAircraftMarker.ts`'s **element**
pattern is reused; its **telemetry subscription** is not (this hook has no live-position feed to
track — it draws static navdata that only changes when the airport or the selection changes).

`useStartAtMarkers.ts` signature:

```ts
export function useStartAtMarkers(
  map: MapLibreMap | null,
  runways: readonly Runway[],
  stands: readonly ParkingStand[],
  selectedRunway: string | null,
  selectedStand: string | null,
  onSelectRunway: (ident: string) => void,
  onSelectStand: (name: string) => void,
): void
```

Behaviour:

1. **Pavement layer** (one `useEffect`, keyed on `[map, runways]`): reuse
   `primaryRunwayEnds(runways).map(runwayFeature)` from `features/map/overlays.ts` verbatim (both
   are pure, already unit-tested functions — see `overlays.test.ts`) to build a `Polygon`
   `FeatureCollection`, pushed into a `pos-startat-pavement` source/fill layer added once when
   `map` becomes non-null. This is the "boring reuse" option: it draws the airport's *real*
   pavement footprint (width, length, bearing) instead of the old diagram's single decorative
   line, for zero new geometry code.
2. **Marker build** (a second `useEffect`, keyed on `[map, runways, stands]`): for each runway end,
   a `Marker` at `runway.threshold` whose element is a `<button>` labelled with the ident (mono,
   e.g. `"04R"`, `"04R·ILS"` when `runway.ils != null` — same badge rule as today's sidebar list);
   for each stand, a `Marker` at `stand.position` whose element is a `<button>` with
   `aria-label={\`Stand ${stand.name}\`}` and `aria-pressed`. Every marker's `<button>` click calls
   the matching `onSelectRunway`/`onSelectStand` prop — the same callback the sidebar/stands list
   already calls. Old markers are `.remove()`d before new ones are built, exactly like
   `useAircraftMarker`'s cleanup.
3. **Selection restyle** (a third, cheap `useEffect`, keyed on `[selectedRunway, selectedStand]`):
   toggles a `--selected` class and `aria-pressed` on the *existing* marker elements — it must
   **not** rebuild markers on every selection change (that would flash/refit the map on every
   click).
4. **Fit to content** (a fourth `useEffect`, keyed on `[map, runways, stands]`, running once data
   arrives): computes a plain `[[minLon, minLat], [maxLon, maxLat]]` bounding box from every
   threshold and stand position (no `LngLatBounds` class import needed — MapLibre's `fitBounds`
   accepts a bounds-like array directly, which keeps the stub simple, see §8) and calls
   `map.fitBounds(bounds, { padding: 40, animate: false, maxZoom: 17 })`. `animate: false` avoids a
   camera flourish every time the popover opens. When there are zero points (airport not loaded,
   or navdata has nothing for it), this effect is a no-op and the map stays at its initial
   center/zoom.

`StartAtMap` passes `useMapLibre({ center: airport?.position, zoom: airport ? 13 : MAP_HOME_ZOOM })`
so the very first frame is already near the right airport instead of flashing Madrid
(`MAP_HOME`) before `fitBounds` corrects it — `airport` is already resolved from the header's own
`useAirport()` call by the time an instructor opens the Start-at trigger, since the airport name is
already shown next to the ICAO input.

---

## 8. Test plan

### Shared test-infra changes (small, additive, backward compatible)

Both in `ui/src/test/maplibreStub.ts`:

- `Map`'s constructor records the options it was built with (`readonly options: Record<string, unknown>`),
  mirroring the pattern `Marker` already uses — needed to assert `useMapLibre`'s new
  `center`/`zoom` parameters actually reach the constructor.
- Add `fitBounds(): void {}` to `StubMap` — a required no-op, or `useStartAtMarkers`'s fit-to-content
  effect throws `TypeError: map.fitBounds is not a function` in every test that reaches it.

Neither change alters any existing test's behaviour (both are new, unused-by-old-code surface).

### New unit tests

**`ui/src/features/map/useMapLibre.test.tsx`** (new — the parameterization has no dedicated test
today because there was nothing to parameterize):
- No options → `Map.created[0].options` carries `MAP_HOME`'s `[lon, lat]` and `MAP_HOME_ZOOM`
  (regression pin for `MapPanel`'s unchanged behaviour).
- Explicit `{ center: [7.21, 43.65], zoom: 13 }` → those exact values reach the constructor.
- Re-rendering the host with a **different** options object does **not** construct a second `Map`
  (`Map.created.length` stays `1`) — the concrete regression test for "options are read once via a
  ref, never in the effect's dependency array."

**`ui/src/features/position/useStartAtMarkers.test.tsx`** (new — modelled directly on
`useAircraftMarker.test.tsx`'s `Harness` pattern, which bypasses `useMapLibre`'s `'load'` gate by
constructing `new StubMap()` directly and passing it straight into the hook under test):
- Given 2 runway ends and 4 stands (the shapes already fixed in `testFixtures.ts`:
  `RUNWAY_04R`/`RUNWAY_22L`, `STANDS` = A1/A2/T1/H1), `Marker.created.length === 6` after mount.
- Firing a real `fireEvent.click` on a stand marker's DOM element (`Marker.created[n].options.element`,
  a genuine jsdom `HTMLElement`) calls `onSelectStand('A1')` — **this is the real, non-vacuous test
  of "map click behaves exactly like list click"** that a full `StartAtPopover`-level render cannot
  give (see below for why), because it exercises the actual click handler wiring on a real DOM node
  without needing `maplibre-gl`'s `'load'` event to ever fire.
- Firing a click on a runway-threshold marker's element calls `onSelectRunway('04R')`.
- Re-rendering with `selectedStand: 'A1'` flips that marker's element to carry
  `aria-pressed="true"` **without** changing `Marker.created.length` (selection restyle does not
  rebuild).
- Re-rendering with a **different** `stands` array removes the old markers and builds new ones
  (`Marker.created.length` after equals the new count; the removed ones' `.remove()` was called —
  spy on the instance method).
- `vi.spyOn(map, 'addSource')` / `'addLayer'` show the pavement source/layer added once when `map`
  is non-null; the GeoJSON content itself is not re-derived here — it is already covered by
  `overlays.test.ts`'s existing tests for `runwayFeature`/`primaryRunwayEnds`, reused verbatim.
- Zero runways / zero stands → 0 markers, `fitBounds` not called (spy).

### Component-level tests

**`StartAtPopover.test.tsx`** — add `vi.mock('maplibre-gl', () => import('../../test/maplibreStub'))`
at the top (new requirement — the popover now transitively imports `maplibre-gl` via `StartAtMap`).
Fate of each existing case:

| Existing case | Fate |
|---|---|
| Escape closes and returns focus | **Unchanged** — chrome-level, does not touch the map. |
| Lists runway ends, badges ILS | **Unchanged** — sidebar list, untouched by this issue. |
| Parking filter narrows the stand list, count follows | **Unchanged** — stands list column, untouched. |
| Says so when parking fails to load | **Unchanged**. |
| "selects the same stand from the diagram and from the list" | **Rewritten.** In jsdom, the `maplibre-gl` stub's `Map` never fires `'load'` (by its own docstring), so `useMapLibre`'s `map` state never leaves `null`, `useStartAtMarkers`'s effects never run, and **no DOM marker for `StartAtMap` is ever produced inside a full `StartAtPopover` render** — the map-click path is genuinely unreachable at this render level. Replace with a test that selects the stand from the **list** (`getByRole('button', { name: 'Stand A1' })` — now matching thanks to the new `aria-label` on the list row, see §7) and asserts `store.getState().positionDesign.selectedStand === 'A1'` and `selectedRunway === null`. Add a one-line comment pointing at `useStartAtMarkers.test.tsx` as the suite that proves the map path dispatches identically, since both call sites share the literal same callback (§7). |

Add one new case: the trigger's accessible name follows the new copy —
`getByRole('button', { name: /^Start position/ })`.

**`PositionHeaderBar.test.tsx`** — add `vi.mock('maplibre-gl', ...)` defensively: it statically
imports `StartAtPopover` → `StartAtMap` → `useMapLibre` → `'maplibre-gl'` at module-load time
regardless of whether any test in this file opens the popover, and every other test file that
touches `maplibre-gl` in this codebase mocks it rather than relying on "importing without
instantiating happens to be safe." No behavioural change to any existing test in this file (none of
them currently open the Start-at popover, confirmed by `Grep`).

**`PositionPanel.test.tsx`** — add the same `vi.mock('maplibre-gl', ...)` (currently absent,
confirmed by `Grep`; this file's "picking a stand clears the runway tab selection…" test *does*
open the popover). Update
`screen.getByRole('button', { name: /^Start at/ })` → `/^Start position/`. The subsequent
`screen.findByRole('button', { name: 'Stand A1' })` needs **no change** — it will resolve to the
stands-list row now that it carries `aria-label="Stand A1"` (§7), preserving this test's assertions
about `selectedStand`/`selectedRunway`/the preview request body untouched.

**`BottomBar.test.tsx`**, **`CircuitDiagram.test.tsx`** — no change; neither renders
`PositionHeaderBar`/`StartAtPopover` (confirmed no match on `PositionHeaderBar|StartAtPopover|maplibre`).

**Deleted:** `standProjection.test.ts` (module deleted with it).

### What is `@pytest.mark.sim`

Nothing — this is a pure frontend change; no Python test is added, changed, or affected. `pytest`,
`pytest -m sim`, `ruff`, and `mypy` are all no-ops for this PR.

### Fixture strategy

No new fixtures needed. `ui/src/features/position/testFixtures.ts`'s existing `RUNWAYS` (2 ends,
one with ILS) and `STANDS` (4 stands across `gate`/`tie_down`/`hangar`) are real-shaped, small, and
already exercise every kind the new map needs to draw (an ILS badge, a plain end, three parking
kinds). No navdata file is read or committed — consistent with CLAUDE.md rule 4 (moot here since
nothing in this design touches the navdata pipeline at all).

### Verification commands

```bash
cd ui && npm run lint && npm run typecheck && npm test && npm run build
```
Python side is untouched — no expected change to `pytest`, `ruff check`, `ruff format --check`, or
`mypy`.

---

## 9. Parallelisation

This is a single, small, UI-only change with **no backend surface at all** — there is no
endpoints-and-models contract to fix before splitting backend/UI work, because there is no backend
work. One implementer, one tester, one branch (the current worktree branch,
`feature/position-startat-map`, already checked out from `origin/dev`).

Directories touched, all disjoint from any other in-flight manager work:
- `ui/src/features/position/` (new `StartAtMap.tsx`, `useStartAtMarkers.ts`; edited
  `PositionHeaderBar.tsx`, `StartAtPopover.tsx`, `position.css`, tests; deleted `AirportDiagram.tsx`,
  `standProjection.ts` + test).
- `ui/src/features/map/useMapLibre.ts` — one function's signature, in place, additive/optional
  parameters, its one existing consumer's call site unaffected.
- `ui/src/test/maplibreStub.ts` — two additive methods/fields, no existing behaviour changed.

**Ordering inside the branch, not across branches:** touch `useMapLibre.ts`'s signature and the
`maplibreStub.ts` additions **first** (it is the one piece both `StartAtMap.tsx` and its tests
depend on), then `useStartAtMarkers.ts` + its test can be written in parallel with the CSS/copy
changes to `PositionHeaderBar.tsx`/`position.css`, since neither depends on the other. This is not
a `SimAdapter`/`Capabilities`-style shared-foundation change (CLAUDE.md's "never parallelise" list
does not apply — no adapter, no navdata schema, no release/merge step), so it does not need a
separate solo pass by a different agent; it is simply the first ten minutes of this one branch's
work, done before the rest of it.

Nothing here should be split into concurrent `feature/*` worktrees — the whole change is a few
hundred lines across a handful of files in one feature area.

---

## 10. Open questions and risks

- **The map-click-vs-list-click parity is proven at the hook level (`useStartAtMarkers.test.tsx`),
  not at the full `StartAtPopover` integration level, in CI.** As established in §8, jsdom's
  `maplibre-gl` stub never fires `'load'`, so `StartAtMap`'s own `map` handle never leaves `null`
  inside a full popover render, and no marker is ever mounted there. This is not new to this
  issue — it is the same limitation `MapPanel.test.tsx` and `App.test.tsx` already accept for the
  Instructor Map tab. What would close it: a real-browser check (a Cloudflare-browser or local
  Chrome pass against the running dev server, clicking an actual stand marker and reading the
  Redux DevTools state) before merge, or a future Playwright/E2E harness — out of scope to build
  for this issue alone.
- **OSM tile availability on an offline LAN.** Unchanged risk from the existing Instructor Map tab:
  with no internet, the raster tiles do not load and the canvas stays blank/grey, but the pavement
  fill layer and every marker still render and remain clickable (client-side projection, no tile
  dependency) — strictly better than today's SVG having no equivalent "still works" story, since
  the SVG needs no network at all but also offers no zoom/pan ever. Worth a one-line callout in the
  PR description, not a blocker.
- **Popover width on a narrow tablet in portrait** (e.g. a ~810px-wide iPad). The `min()` clamp in
  §7 keeps the popover from running off-screen, but the resulting cramped three-column layout at
  that width cannot be checked by a jsdom test (no real layout engine) — flag it as a manual
  tablet-viewport screenshot check before merge, per this repo's tablet-first rule.
- **Degenerate `fitBounds` case** — an airport with exactly one runway end and no stands (or vice
  versa) produces a zero-area bounding box. MapLibre's own docs say `fitBounds` handles a
  single-point box by keeping the current zoom rather than throwing, but this is not exercised by
  the jsdom stub (whose `fitBounds` is a no-op) — another item for the manual pre-merge check
  alongside the tablet-width one, not something CI can catch given the stub's necessary limits.
- **Accessible name of the dialog itself.** `Popover.tsx`'s `role="dialog"` has no
  `aria-label`/`aria-labelledby` today, and this design does not add one (out of scope for #155,
  which is about the trigger's copy and the internal picker, not the dialog's own accessible name).
  Noting it here so a reviewer doesn't read the omission as an oversight; a follow-up issue could
  add `aria-label="Start position"` to the `Popover` instance cheaply if wanted.
