# Position Manager — design

**Status:** shipped. Both phases are on `dev`.
**Issues:** [#9](https://github.com/Santisoutoo/open-instructor-station/issues/9) (API),
[#10](https://github.com/Santisoutoo/open-instructor-station/issues/10) (panel).
**Phase:** 1 — Position Manager + Aircraft Control.
**Depends on:** #3/#4/#5 (`NavdataProvider`, PRs #54/#55), #6 (`feature/placement-geodesy`, PR #64).
**Blocks:** every later manager that repositions the aircraft — Scenario Generator, Instructor
Map drag-to-place, Session Recorder snapshots.

This is the manager the product exists for: put the aircraft where the lesson needs it, from a
tablet, without alt-tabbing into the simulator.

**This document is the design of record *and* the as-built record.** It was reconciled from two
divergent copies — the planner's design, written before any handler existed, and the
implementation session's account of what shipped. Where the two disagreed, the **shipped code
won**: every endpoint, field name, status code and model below was read out of `dev` rather than
copied forward from the design. Where the design specified something that was not built, or was
built differently, the section says so under a **Deviation** heading and states the reason when
the code or the commit history records one. Where no reason is recorded, it says that too rather
than inventing one.

Binding rules live in [`../../CLAUDE.md`](../../CLAUDE.md); layers in
[`../architecture.md`](../architecture.md); the navdata contract in
[`navdata-provider.md`](navdata-provider.md). This document never relaxes any of them.

---

## 0. Decisions at a glance

| # | Decision | Shipped | Where |
|---|---|---|---|
| D1 | **Endpoints, not one per placement type.** One request union dispatching on a discriminator, rather than `architecture.md`'s sketch of `POST /api/position/final`. | yes, as **two** endpoints — the catalogue was not built (§6.2) | §6 |
| D2 | **`POST /api/position/preview` is safe and side-effect-free.** It resolves geometry, builds the pre-teleport setup and touches nothing. It does not require `can_set_position`. | yes, and stronger: it never reads the adapter either | §6.1, §9 |
| D3 | **Apply re-resolves from scratch.** A preview is never accepted as input to a write; the client cannot hand the server a coordinate. | yes — the client may send a *setup overlay*, never a position | §6.1 |
| D4 | **The request model is a `core/` model.** | **no** — the request models live in `server/position_routes.py` | §7.6 |
| D5 | **Resolution lives in `core/placements.py`**, takes a `NavdataProvider`, never sees a `Request`. | **no** — `core/placements.py` was never created; resolution is in the router over `core.geodesy` | §13 |
| D6 | **No `SimAdapter` or `Capabilities` change.** `can_set_position`, `can_set_aircraft_state`, `set_position` and `apply_setup` already exist and are sufficient. | yes | §11 |
| D7 | **No new dataref.** The X-Plane adapter is untouched by this manager. | yes | §12 |
| D8 | **An airborne placement requires `can_set_aircraft_state` as well as `can_set_position`**; a ground placement requires only `can_set_position`. | partly — the second capability is required whenever the setup is non-empty, which is always | §9.2 |
| D9 | **The composed setup is *filtered* against capabilities, not refused.** | **no** — `server/capability_gate.py` was never created | §9.3 |
| D10 | **Every error carries a stable machine code** in a typed body. | **no** — errors are FastAPI's `detail` sentence | §10 |
| D11 | **A hold placement needs magnetic→true conversion and the project has no world magnetic model.** | yes, but it **never fails** — it falls back to zero variation and says so | §10.3, §18.1 |
| D12 | `server/deps.py` gaining `get_navdata()` is a **shared, serialised addition**, made once before dependent work branches. | yes | §14 |
| D13 | The catalogue endpoint aggregates anchors so a tablet populates every picker in one round-trip. | **no** — the panel fetches `/api/navdata/*` per picker | §6.2 |
| D14 | **The `/api/navdata/*` router is part of this issue.** | yes, as `server/navdata_routes.py` | §6.3 |
| D15 | **Staging, not firing.** Selecting a placement never moves the aircraft; a persistent bar shows what will be applied and one button commits. | yes | §5 |
| D16 | **A schematic, not a map.** The preview diagram is an SVG drawn from geometry the API returns — no MapLibre, no new dependency. | yes | §5, §7.3 |

---

## 1. Scope

### 1.1 What this manager does

1. **See where the aircraft will land before committing** — a *preview* that returns the resolved
   coordinate, the target altitude, the heading, the commanded speed, the full pre-teleport
   `AircraftSetup`, a diagram and a set of provenance notes, without touching the simulator.
2. **Apply it** — write the setup, then the position, and report back what the aircraft actually
   looks like afterwards.
3. **Browse the navdata behind all of that** — airports, runways, stands, procedures, navaids,
   fixes and holds, plus the AIRAC cycle and index state (§6.3).
4. **Offer it as a panel** — search-as-you-type airport selection, a spatial circuit grid, a
   procedure leg table, a stand list, a coordinate/fix form and a staging bar.

It covers these [`feature-spec.md`](../feature-spec.md) items from manager 1:

- Final approach at 20 / 15 / 10 / 8 / 5 / 3 NM, and short final.
- Base, downwind, crosswind and upwind, on both circuit sides.
- Gate and parking stand.
- Arbitrary coordinate, over a waypoint.
- A point on a SID, a STAR or an approach.
- In a holding — at the API. There is no hold surface in the panel (§15.7).

It sits in **Phase 1** and serves exit criterion 1 directly: *"From a tablet, the instructor
places the aircraft on a 10 NM ILS final with a coherent aircraft state in under 5 seconds."*

> **Deviation — the radio slice of manager 7 was not delivered.** The design took NAV/ILS
> frequency and OBS course tuned from the runway localizer as in scope, with a
> `core/radio_tuning.py` and a `tune_radios` request flag. Neither exists: `Placement.to_setup()`
> sets altitude, heading and speed and nothing else, and no request carries `tune_radios`. Nothing
> in the code or the commit history records why. `Runway` already carries its `Ils`, so the
> addition is small when it is wanted; it stays a stated gap rather than a silent one.

### 1.2 What is explicitly out of scope

| Out of scope | Owner |
|---|---|
| The *full* pre-teleport setup — flaps, gear, spoilers, autobrake, lights, mass | #8. It extends `Placement.to_setup()`; this API composes whatever that method returns and needs no change when it grows. |
| Navdata parsing, indexing, cache invalidation | #3/#4/#5, landed. The *HTTP surface* over them is §6.3 and is in scope. |
| Anything in `adapters/` | Untouched (§11, §12). |
| Drag-to-reposition from a map | Phase 3, and it is a `coordinate` request with a map-derived anchor — this same endpoint. |
| Saving a placement as a profile or scenario | Phase 2 (managers 14 and 2). |
| Long-haul teleports across a scenery reload | An **adapter** defect, [#36](https://github.com/Santisoutoo/open-instructor-station/issues/36), **since resolved** in `adapters/xplane/` — see §18.2. |

---

## 2. Boundaries, restated for this manager

- **`server/` never learns a dataref name.** It calls `adapter.apply_setup()` and
  `adapter.set_position()`. Whether that means `local_x/y/z`, `override_planepath` or SimConnect's
  `SIMCONNECT_DATA_INITPOSITION` is the adapter's business and nothing in this document mentions
  it outside §12.
- **`core/` never learns about HTTP.** `core/geodesy.py` takes models and returns a `Placement`;
  it raises `ValueError` when the published data cannot answer a request. There is no status code,
  no `Request` and no FastAPI import anywhere in `core/`.
  `tests/core/navdata/test_core_boundaries.py` walks the import graph and enforces it.

> **Deviation — `core/` does not own the resolution.** The design put a `resolve_placement`
> entry point in `core/placements.py` and left the router as a thin HTTP skin. What shipped
> resolves in `server/position_routes.py::_resolve_placement`: the router does the navdata lookup,
> chooses the glidepath, computes the neighbouring fixes for a procedure leg, and writes the
> provenance notes, calling `core.geodesy` for the geometry only. The `core/` boundary is intact —
> the router imports no dataref and `core/` imports no FastAPI — but the *reuse* boundary is not:
> a scenario runner that wants the same placements will have to call the router's private
> functions or reimplement them. See §13 for what this costs and what it would take to move.

---

## 3. The placement catalogue

### 3.1 The fourteen Phase 1 placement types

| # | Placement | Anchor | Parameters | Altitude rule | Default `ias_kt` |
|---|---|---|---|---|---|
| 1 | final, 20/15/10/8/5/3 NM | runway end | `airport_icao`, `runway_ident`, `placement`, `glideslope_deg` (optional) | `glideslope_altitude_ft(runway.elevation_ft, distance, gs)`, feet MSL | `APPROACH_CATEGORY_VAT_KT[cat]` — B → **120 kt** |
| 2 | short final | runway end | as above | same, at `SHORT_FINAL_DISTANCE_NM = 1.0` NM → **+318.44 ft** over the threshold on 3° | `APPROACH_CATEGORY_VAT_KT[cat]` |
| 3–6 | upwind, crosswind, downwind, base | runway end | `airport_icao`, `runway_ident`, `placement`, `pattern_altitude_ft`, `pattern_width_nm`, `leg_distance_nm` | `pattern_altitude_ft`, else `runway.elevation_ft + 1000` ft | `APPROACH_CATEGORY_CIRCLING_IAS_KT[cat]` — B → **135 kt** |
| 7–8 | gate, stand | parking record | `airport_icao`, `stand_name` | `stand.position.altitude_ft` (the airport datum) | `GROUND_IAS_KT` = **0.0** |
| 9 | coordinate | none | `position` (`GeoPosition`), `heading_deg`, `ias_kt` | verbatim from the request | **0.0**, and warned about when airborne |
| 10 | waypoint | fix | `ident`, `region_code`, `terminal_airport`, `altitude_ft` (**required**), `heading_deg` | verbatim | `APPROACH_CATEGORY_CIRCLING_IAS_KT[cat]` as a generic manoeuvring speed |
| 11–13 | SID, STAR, approach leg | procedure leg | `airport_icao`, `kind`, `ident`, `transition`, `sequence`, `altitude_ft` | `leg.altitude.suggested_ft` (a band resolves to its **lower** bound); an override wins | the leg's speed band, clamped (§7.4) |
| 14 | hold | published hold | `fix_ident`, `region_code`, `airport_icao`, `altitude_ft` | `altitude_ft`, else the hold's published lower altitude | the hold's placard, clamped (§7.4) |

**`ias_kt` is required on `Placement` and therefore never absent.** An explicit `ias_kt` in the
request always wins; `category` selects the default; `DEFAULT_APPROACH_CATEGORY = "B"` when the
request states neither. This is the resolution of issue #39 and it is not re-litigated here.

**`upwind` is included although the feature spec lists only crosswind/downwind/base.**
`core.geodesy.PATTERN_PLACEMENTS` implements all four legs on both sides; excluding upwind would
mean writing code to hide a working feature.

### 3.2 How the fourteen map onto the wire

The design made the fourteen a closed `PlacementKind` literal and the discriminator of the request
union. **They are not the discriminator.** What shipped is six request types keyed on `type`, and
the fourteen live inside them:

| Wire `type` | Covers | Discriminated further by |
|---|---|---|
| `runway` | 1–6 | `placement: RunwayPlacement` — the 15 values of `core.geodesy.RUNWAY_PLACEMENTS` (7 finals, 8 circuit legs) |
| `parking` | 7–8 | nothing; one `stand_name` lookup over every parking kind |
| `coordinate` | 9 | — |
| `waypoint` | 10 | — |
| `procedure_leg` | 11–13 | `kind: ProcedureKind` |
| `hold` | 14 | — |

> **Deviation — six request types, not fourteen kinds, and the discriminator is `type`.**
> Three consequences worth stating, because a client reads them all:
>
> - **Finals are not a `distance_nm` parameter.** The design made the six named finals one
>   `distance_nm` float so an arbitrary distance was expressible. What shipped names them —
>   `final_20nm` … `final_3nm`, `short_final` — because that is what `core.geodesy` already
>   enumerates, and `resolve_runway_placement` is one function over finals *and* circuit legs. The
>   API mirrors `core/` rather than inventing a second taxonomy. The cost is that a 12 NM final
>   cannot be requested; the design's `final_placement_at` helper, which would have made it
>   possible, was never written (§13).
> - **`gate` and `stand` are one request.** `apt.dat` publishes one record type with a `kind`
>   field, so a name lookup is a name lookup. The design's gate-only filter — asking for "gate R32"
>   when R32 is a tie-down should 404 — is not implemented: any parking record matching the name
>   is placed on, case-insensitively.
> - **`upwind`/`crosswind`/`downwind`/`base` and the four `sid`/`star`/`approach` kinds are not
>   top-level.** They are a `placement` and a `kind` field inside their request. A generated
>   TypeScript client still gets a proper tagged union, on `type`, with six arms.

---

## 4. What the incumbent gets right, and what it gets wrong

FS-FlightControl v1.7.9 was studied hands-on (UX only — never its code, same rule as Little
Navmap). Its Position module: ICAO box, airport info and stand list down the left; two large
runway-end buttons across the top; mode tabs (Approach Training / SID-STAR Waypoints / Airwork /
Custom Location); and a **3×3 grid of placements laid out spatially like a circuit** around a
runway diagram:

```
Downwind Left   |   Take Off        |  Downwind Right
Vectors Left    |   3 NM Final      |  Vectors Right
Base Left       |   8 NM Final      |  Base Right
```

An options strip at the bottom carries IAS, pitch, gear, flaps and an altitude override.

**Worth keeping:** the spatial grid. It matches the mental model an instructor already has — they
do not read "left_downwind" off a list, they point at where the aeroplane should be.

**What to beat:**

1. **A tile click teleports immediately.** No preview, no confirmation, no undo, mid-lesson.
2. Finals are two fixed tiles (3 and 8 NM); the spec calls for 20/15/10/8/5/3 and short.
3. The options strip is detached from the tile it modifies — IAS is set for "whatever comes
   next", not for *this* placement.
4. Presets paginate with Back/Add/Next instead of scrolling and searching.
5. Sixteen ungrouped buttons in a flat two-row nav; ~60 % of a 2560×1440 window left empty;
   errors arrive as stacking modal dialogs.

---

## 5. The two decisions that shape the panel

**Staging, not firing.** Selecting a placement never moves the aircraft. It *stages* it: the
server computes a preview, and a persistent bar shows what will be applied with the numbers
editable. One primary button commits. Two taps, no modal, and the instructor always sees the
altitude and the speed before a student's aeroplane jumps.

**A schematic, not a map.** The preview is a small SVG — runway, extended centreline, placement
point, heading vector, glidepath — drawn from geometry the API returns. No MapLibre (that is the
Instructor Map, issue #19), no new dependency, and it renders instantly on a tablet.

**Every airport, always.** Airport selection is search-as-you-type over the whole index. Nothing
in this design names an airport, and the panel must behave identically at LEMD and at a 600 m
grass strip with no procedures — which is why every tab enables itself from data
(`has_procedures`, non-empty parking, non-empty runways) rather than from an assumption.

---

## 6. REST endpoints

### 6.1 `/api/position/*` — the placement commands

```
POST /api/position/preview  ->  PlacementPreview
POST /api/position/apply    ->  PlacementResult
```

| Method | Path | Purpose | Safe? | Idempotent? | Declared |
|---|---|---|---|---|---|
| `POST` | `/api/position/preview` | Resolve a request into a placement, a setup, a diagram and its notes. **Writes nothing.** | **yes** | yes | `def` — every call is a navdata read and arithmetic, so FastAPI runs it in the threadpool |
| `POST` | `/api/position/apply` | Resolve, then write setup and position | no | **yes** | `async def` — it awaits the adapter |

**`preview` touches no simulator at all.** It resolves navdata, calls the `core.geodesy` function
and projects the schematic. It is a `POST` because its body is a union, not because it mutates,
and `tests/server/test_position_routes.py::TestPreviewIsSideEffectFree` asserts the aircraft state
is unchanged across the call. It requires no capability: staging is navdata and arithmetic, and it
works against an adapter that cannot reposition at all.

> **Deviation — `preview` reads nothing from the adapter, so it reports no distance from the
> aircraft.** The design had it read `get_aircraft_state()` best-effort to fill
> `distance_from_aircraft_nm` and to raise a long-teleport warning. Neither field exists. The
> result is a preview that is trivially sim-independent, and a panel that cannot say "that is
> 340 NM away" before the button is pressed. Issue #36 — the defect that made the warning worth
> having — has since been fixed in the adapter (§18.2).

**`apply` takes the staged request plus the staging bar's edits:**

```python
class ApplyPlacementRequest(BaseModel):
    placement: PlacementRequest
    setup: AircraftSetup | None = None  # the instructor's sparse overlay
```

Order of operations, non-negotiable (gotchas #37 and #39):

1. Re-resolve the placement — in the threadpool, because this route is `async def` and the
   resolution is the same blocking SQLite/CIFP work `preview` does. Running it inline would stall
   the event loop that also serves the ~4 Hz `/ws/state` push, during the one operation the
   instructor is watching.
2. Merge the caller's non-`None` setup fields **over** the resolved setup, then re-validate.
3. Fold an edited `altitude_ft` / `heading_deg` back into the *placement*.
4. `await adapter.apply_setup(merged)` — speed, altitude, heading **before** the move.
5. `await adapter.set_position(placement.position, placement.heading_deg)`.
6. Read the state back and return it.

**Apply re-resolves; it never accepts a client-supplied coordinate.** The body carries the same
declarative request, so an instructor who previewed and then applied gets the same answer — the
resolution is a pure function of (navdata, request). Accepting the preview back would let a client
teleport the aircraft anywhere by editing a JSON field.

**It is idempotent.** The request states an absolute target, not a delta.

Two subtleties in that sequence are load-bearing and were both found by review after the first
implementation (commit `9e960f1`):

- **The merge re-validates.** `model_dump` is recursive and `model_copy(update=…)` stores what it
  is handed without validating, so `{"lights": {"landing": true}}` reached the adapter as a plain
  `dict` and died on `setup.lights.landing` — a 500 *after* `apply_setup` had started writing.
  `AircraftSetup.model_validate(merged)` rebuilds every sub-model, which covers any nested field
  added later rather than `lights` alone.
- **An edit moves the placement.** `altitude_ft` and `heading_deg` look like setup and are not:
  they are geometry, and `set_position` is authoritative for both and runs *last*. An edit left in
  the setup alone was overwritten a moment later — measured on a 10 NM final, an altitude edited
  to 1234 ft arrived as 4184.36 and a heading edited to 99° arrived as 0° — so two of the staging
  bar's four controls did nothing while `PlacementResult.applied` reported success.
  `_placed_as_edited` displaces the geometry instead of fighting it, and the edited fields stay in
  the setup as well, which is what makes `applied` honest.

> **Deviation — `apply` accepts a setup overlay.** The design had `apply` take a bare
> `PlacementSpec`, identical to `preview`, with capability *filtering* the only transformation.
> The staging bar's editable numbers made an overlay necessary. D3 survives intact: the overlay
> can carry an altitude, a heading, a speed or a gear position, never a latitude and longitude.

### 6.2 The catalogue endpoint that was not built

The design specified a third endpoint:

```
GET /api/position/placements?airport_icao=&runway_ident=&include=&parking_kind=&procedure_kind=
    -> PlacementCatalogue { adapter, navdata_provider, navdata_state, airac_cycle,
                            can_apply, blocked_reason, options[14], anchors? }
```

Its job was to answer "what can I do here?" in one round-trip — all fourteen options always
returned, unavailable ones included with a `reason`, plus the concrete anchors so a tablet
populated every picker at once. That was D13's five-second exit criterion, and D1's claim that
nobody should ever reach a 501 rested on it.

> **Deviation — it does not exist, and nothing in the code or the commit history says why.**
> What replaces it:
>
> - **Availability** comes from `GET /api/capabilities` and `GET /api/navdata/status`, read
>   directly by the panel and resolved in `ui/src/features/position/gate.ts` (§15.5). Both gates
>   fail closed, so hard rule 3 still holds; it is enforced client-side from two general
>   endpoints instead of server-side from one specific one.
> - **Anchors** come from `/api/navdata/*`, one request per picker, lazily as tabs are opened.
>   The two-tap path to a 10 NM final therefore costs a `status` read, an airport search, a
>   runways fetch and a preview rather than one catalogue call and one preview.
> - **The options are not enumerated by the server.** The panel's tile catalogue is
>   `ui/src/features/position/placements.ts` — labels, hints and grid positions written against
>   the generated `RunwayPlacementName` enum. The design's "a server-side addition fails the
>   typecheck until the panel handles it" property survives, one step removed: coverage is pinned
>   by `placements.test.ts`, whose `Record<RunwayPlacementName, …>` keys are checked by the
>   compiler and compared against `ALL_RUNWAY_PLACEMENTS` at runtime. What is lost is the
>   *reason* an option is unavailable: the server no longer supplies one, so a tile is either
>   rendered or the whole tab is.

### 6.3 `/api/navdata/*` — the read-only façade

`server/navdata_routes.py`. Every route is declared `def`, not `async def`: the provider protocol
is synchronous by contract — it reads a local SQLite file and `sqlite3` has no async API — and
FastAPI runs a synchronous route in its threadpool, which is exactly right for a blocking call
that completes in microseconds.

| Route | Returns |
|---|---|
| `GET /api/navdata/status` | `NavdataStatus` |
| `POST /api/navdata/index?force=` | `NavdataStatus` — starts a build in a worker thread, returns immediately |
| `GET /api/navdata/airports?q=&limit=` | `list[AirportSummary]` |
| `GET /api/navdata/airports/near?lat=&lon=&radius_nm=&limit=` | `list[AirportSummary]` |
| `GET /api/navdata/airports/{icao}` | `Airport` (404 when absent) |
| `GET /api/navdata/airports/{icao}/runways` | `list[Runway]` — every runway **end** |
| `GET /api/navdata/airports/{icao}/runways/{runway_ident}/ils` | `Ils` (404 when absent) |
| `GET /api/navdata/airports/{icao}/parking?kind=` | `list[ParkingStand]` |
| `GET /api/navdata/airports/{icao}/procedures?kind=` | `list[ProcedureSummary]` |
| `GET /api/navdata/airports/{icao}/procedures/{kind}/{ident}?transition=` | `Procedure` (404) |
| `GET /api/navdata/navaids?ident=&region=&kinds=` **or** `?lat=&lon=&radius_nm=&kinds=&limit=` | `list[Navaid]` |
| `GET /api/navdata/fixes?ident=&region=&terminal_airport=` | `list[Fix]` |
| `GET /api/navdata/holds?fix_ident=&region=&airport_icao=` | `list[Hold]` |

Rules:

- **Absent is 404, broken is 503.** The provider returns `None` for a missing airport, so a 404
  means "no such thing". `NavdataUnavailable` becomes **503**, registered **once as an app-level
  exception handler** in `server/app.py` rather than repeated as a `try` in every route — all of
  them can raise it and all of them would answer identically. The 503 carries the provider's
  reason, the **whole of `status()`** in the body, and a `Retry-After`: **5 s** while `building`,
  because the thing the client is waiting for is finishing on its own, and **60 s** while
  `unavailable` or in `error`, because a human has to act. The handler is `def` for the same
  reason the routes are — Starlette dispatches a sync exception handler through its threadpool.
- `/airports/near` is declared **before** `/airports/{icao}` so the literal wins the match. There
  is a test for that specifically, because the failure mode is a silent 404 for the word "near".
- **`/navaids` takes two query forms on one path**, because they answer the same question from the
  two directions an instructor asks it: "where is BRA?" and "what can I tune from here?".
  Supplying both forms, or neither, is a **422** rather than a server-invented precedence or a
  request for every navaid on Earth. It returns a list either way: navaid identifiers are not
  globally unique.
- The index build runs on a module-owned worker thread with a module-level cancel `Event`. A
  second `POST /index` while one is running is an idempotent no-op returning the current status,
  so an impatient tablet cannot fork-bomb one SQLite file.
- **No new WebSocket.** The build is minutes-long and coarse; the panel polls `status` while
  `state == "building"` and stops polling when it is not.

> **Deviation — three, all small and all recorded in the commit history.**
>
> - The module is `server/navdata_routes.py`, not `server/navdata_api.py`.
> - The airport search parameter on the wire is **`q`**, not `query`. It shipped as `query` and
>   was renamed in commit `19fa90a` — *"where the design says `?q=`. Renamed while it is still
>   free"* — with the RTK Query caller updated, the parameter name pinned by a test on each side,
>   and `ui/src/api/schema.d.ts` regenerated. The RTK Query *argument* is still called `query`,
>   because `query` is also RTK Query's own key for the request descriptor and two of them in one
>   object literal reads as a mistake.
> - `GET /api/navdata/navaids` was missing entirely from the first implementation although
>   `NavdataProvider.get_navaids` and `navaids_near` were both there; it was added in the same
>   commit, along with the `Retry-After` and the status body on the 503.

### 6.4 What is deliberately *not* an endpoint

- **No `POST /api/position/final`, `/gate`, `/hold`, …** Fourteen endpoints means fourteen
  handlers, fourteen response models and fourteen sets of error tests for one algorithm with a
  dispatch in the middle.
- **No WebSocket change.** Position is a command; the live picture already streams over
  `WS /ws/state`. After an apply the UI sees the new position on the next frame, and
  `PlacementResult.state` covers the gap.
- **No navdata lookups duplicated under `/api/position/`.** Runway, parking, procedure and fix
  lookups belong to the `/api/navdata/` router.

---

## 7. Models

Units are in the field name, always, following `core/models.py`: `_ft` is feet MSL unless the name
says AGL, `_kt` is indicated knots, `_deg` is **true** degrees for headings and bearings
(`_mag_deg` where magnetic), `_nm` is nautical miles, `_m` is metres, `_khz` is kilohertz.

### 7.0 What is reused, and from where

| Model | Module | Used as |
|---|---|---|
| `Placement` | `core.geodesy` | the resolved geometry, verbatim |
| `AircraftSetup` | `core.models` | the pre-teleport payload, verbatim |
| `AircraftState` | `core.models` | the read-back after an apply |
| `GeoPosition` | `core.models` | every coordinate |
| `Runway`, `Ils` | `core.models` | the runway anchor and the schematic |
| `ApproachCategory`, `RunwayPlacement` | `core.geodesy` | request fields |
| `Airport`, `AirportSummary`, `ParkingStand`, `Fix`, `Waypoint`, `Navaid`, `Procedure`, `ProcedureSummary`, `ProcedureLeg`, `Hold`, `AltitudeConstraint`, `SpeedConstraint`, `NavdataStatus` | `core.navdata.models` | the navdata façade |
| `Capabilities` | `core.sim_adapter` | capability gating |

Everything below is new and lives in `server/position_routes.py`.

### 7.1 The request union

```python
class RunwayPlacementRequest(BaseModel):
    type: Literal["runway"]
    airport_icao: str = Field(min_length=2, max_length=7)
    runway_ident: str = Field(min_length=1)
    placement: RunwayPlacement  # the Literal from core.geodesy
    glideslope_deg: float | None = Field(default=None, gt=0.0, le=10.0)
    pattern_altitude_ft: float | None = None
    pattern_width_nm: float | None = Field(default=None, gt=0.0)
    leg_distance_nm: float | None = Field(default=None, gt=0.0)
    ias_kt: float | None = Field(default=None, ge=0.0)
    category: ApproachCategory | None = None


class ParkingPlacementRequest(BaseModel):
    type: Literal["parking"]
    airport_icao: str = Field(min_length=2, max_length=7)
    stand_name: str = Field(min_length=1)  # matched case-insensitively


class CoordinatePlacementRequest(BaseModel):
    type: Literal["coordinate"]
    position: GeoPosition
    heading_deg: float | None = None
    ias_kt: float | None = Field(default=None, ge=0.0)


class WaypointPlacementRequest(BaseModel):
    type: Literal["waypoint"]
    ident: str = Field(min_length=1)
    region_code: str | None = None
    terminal_airport: str | None = None
    altitude_ft: float
    heading_deg: float | None = None
    ias_kt: float | None = Field(default=None, ge=0.0)
    category: ApproachCategory | None = None


class ProcedureLegPlacementRequest(BaseModel):
    type: Literal["procedure_leg"]
    airport_icao: str = Field(min_length=2, max_length=7)
    kind: ProcedureKind
    ident: str = Field(min_length=1)
    transition: str | None = None
    sequence: int  # the leg's own sequence number: 10, 20, 30 …
    altitude_ft: float | None = None  # None -> AltitudeConstraint.suggested_ft
    ias_kt: float | None = Field(default=None, ge=0.0)
    category: ApproachCategory | None = None


class HoldPlacementRequest(BaseModel):
    type: Literal["hold"]
    fix_ident: str = Field(min_length=1)
    region_code: str | None = None
    airport_icao: str | None = None
    altitude_ft: float | None = None  # None -> the hold's published lower altitude
    ias_kt: float | None = Field(default=None, ge=0.0)
    category: ApproachCategory | None = None


PlacementRequest = Annotated[
    RunwayPlacementRequest
    | ParkingPlacementRequest
    | CoordinatePlacementRequest
    | WaypointPlacementRequest
    | ProcedureLegPlacementRequest
    | HoldPlacementRequest,
    Field(discriminator="type"),
]
```

**Every optional field is `| None`, never a default in the schema.** The obvious alternative —
`category: ApproachCategory = DEFAULT_APPROACH_CATEGORY` — reads better in Python and is wrong on
the wire twice over. It makes `openapi-typescript` emit the property as **required**, so a
generated client is forced to send a category on every request; and it destroys the distinction
between an instructor who chose B and one who said nothing, which is precisely what the preview's
notes exist to report. `request_category()` and the `or DEFAULT_*` fallbacks resolve them in one
place, and the notes say which happened.

> **Deviation — field names, and two model settings.** Against the design's `PlacementSpec`:
> `approach_category` → `category`; `ParkingSpec.name` → `stand_name`;
> `WaypointSpec.terminal_airport_icao` → `terminal_airport`; `CoordinateSpec`'s three scalars →
> one nested `position: GeoPosition`; `FinalSpec.distance_nm` → a named `placement`;
> `HoldSpec.entry` and `HoldSpec.heading_deg` are absent (§10.3). `tune_radios` is absent (§1.1).
>
> The request models are **not frozen and do not forbid extra fields.** The design set
> `model_config = ConfigDict(frozen=True, extra="forbid")` so that a typo'd field in a saved
> training profile failed loudly at load time rather than silently placing the aircraft at a
> default. Nothing records why it was dropped. It matters more the day manager 14 serialises a
> request into a profile than it does today, and it is a one-line addition per model — but adding
> it later is a breaking change for any client that has been sending an extra field, so it is
> cheaper now than then.

### 7.2 The `Placement` these resolve to

`core.geodesy.Placement` is frozen and carries exactly four fields — `position` (whose
`altitude_ft` is the target altitude, feet MSL), `heading_deg` (true, `[0, 360)`), `ias_kt` and a
human-readable `label`. `ias_kt` has **no default on purpose**: it is the one field that cannot be
inferred from geometry, and leaving it out is precisely the defect that put an aircraft on a
perfect 10 NM final at 0 kt.

`Placement.to_setup()` yields the `AircraftSetup` to apply **before** the teleport, setting
altitude, heading and speed and leaving every other field `None` — which an adapter reads as
*leave that aspect untouched*. The remaining thirteen fields are issue #8's, and it extends this
method rather than replacing it, so nothing in `server/position_routes.py` changes when it lands.

### 7.3 The schematic

```python
class SchematicPoint(BaseModel):
    label: str
    position: GeoPosition
    x_nm: float  # along the centreline; positive AWAY from the threshold
    y_nm: float  # across it; positive right, seen from the approach
    role: Literal["threshold", "runway_end", "placement", "glidepath", "leg", "fix"]


class PlacementSchematic(BaseModel):
    runway_ident: str | None = None
    runway_true_bearing_deg: float | None = None
    runway_length_m: float | None = None
    glidepath_deg: float | None = None  # finals only; None on a circuit leg
    points: tuple[SchematicPoint, ...] = ()
```

This pair has no counterpart in the original design — it is what makes D16's "a schematic, not a
map" expressible, and it is the reason the UI does no geodesy.

**What it actually emits today.** For a runway-relative placement: three points — `threshold` at
the origin, `runway_end` at the far end, and `placement`. Every non-runway placement returns an
empty `PlacementSchematic()`. The `glidepath` / `leg` / `fix` roles exist in the union but are not
emitted: the UI draws the glidepath wedge from `glidepath_deg` and the placement's own distance,
which needs no extra points. A hold racetrack or a procedure-leg polyline is the natural
extension.

`_runway_schematic` takes the **resolved** glidepath angle rather than the request, so the diagram
can never disagree with the altitude that was actually computed from it.

`x_nm` / `y_nm` are a runway-local tangent plane. The flat-earth error the `local_frame` gotcha
warns about does not apply: this frame **only ever draws a diagram**, and the authoritative answer
is the `position` beside it.

### 7.4 The response envelopes

```python
class PlacementPreview(BaseModel):
    request: PlacementRequest
    placement: Placement
    setup: AircraftSetup  # Placement.to_setup(), the pre-teleport state
    schematic: PlacementSchematic
    notes: tuple[str, ...] = ()


class PlacementResult(BaseModel):
    placement: Placement  # after _placed_as_edited
    applied: AircraftSetup
    state: AircraftState  # the read-back
```

**`notes` is what makes the staging bar honest.** Every pre-filled number says where it came from,
and the UI renders the sentence verbatim and never re-derives it:

- `"4,184 ft — 3° glidepath (36's published ILS glidepath) 10 NM from the 36 threshold at
  1,000 ft."`
- `"120 kt — ICAO category B threshold speed (V_AT). This is a category default, not this
  airframe's number; set a speed if you know it."`
- `"Published constraint: at or above 6000 ft."`
- `"0 kt at 5,000 ft — the aircraft is below stall speed and will fall out of the sky. Set a speed
  unless this point is on the ground."`

Three rules behind those sentences are worth writing down, because each one was a bug first:

- **The zero-speed warning keys on the *resolved* speed, never on who asked for it.** An explicit
  `ias_kt: 0` on an airborne placement reproduces issue #39's measured crash exactly as surely as
  a defaulted one, and the first implementation affirmed it — *"0 kt, as requested"*. It stays a
  **warning and not a refusal**: a stationary aircraft in the air is a legitimate demonstration,
  and refusing would be the station overruling the instructor.
- **Zero is not the ground.** Deciding "parked or flying" by comparing an altitude against sea
  level reads Schiphol (−11 ft) and the Dead Sea (−1,410 ft) as impossible and — the failure that
  matters — hands an *airborne* point below sea level the reassuring sentence instead of the stall
  warning. `_local_ground_elevation_ft` takes the nearest airport within
  `GROUND_REFERENCE_RADIUS_NM = 50.0` as the reference, degrading to sea level mid-ocean *and*
  when the index is unusable, so a coordinate placement — the one placement that needs no navdata
  at all — never turns into a 503.
- **A published speed is a ceiling, not a target.** A hold placarded at 210 kt or a STAR leg at
  250 kt is a restriction the aircraft must stay under, and flying the placard would put a
  category A trainer a hundred knots over its manoeuvring speed. `core.geodesy._constrained_ias_kt`
  starts from the aircraft's own category speed and lets the chart only *clamp* it — never below
  the category's threshold speed, so a mis-parsed restriction cannot hand an aeroplane a stall.
  The note therefore reads *"Published speed restriction: at or below 210 kt"*, not *"210 kt — the
  hold's published speed"*.

  Attributing that speed afterwards is impossible: a leg placarded at 130 kt and a category B
  threshold speed of 120 kt are different facts a 130 kt answer cannot be asked to distinguish. So
  `_constrained_speed_provenance` re-derives the branch from the same **inputs** `core.geodesy`
  had, checks itself against the speed that actually came back, and answers `"unattributed"` when
  the two disagree — with a sentence that claims nothing. The honest fix is for `core.geodesy` to
  hand the provenance back beside the speed.

> **Deviation — `notes` replaced the typed `PlacementWarning`, and the read-back diagnostics were
> not built.** The design specified a `PlacementWarning { code, message, field }` over a closed
> `PlacementWarningCode` literal, wrapped in a `ResolvedPlacement` that also carried the anchor it
> resolved against, `distance_from_anchor_nm`, `height_above_anchor_ft`, `glideslope_deg`, `ils`
> and `airac_cycle`; a `PlacementPreview` carrying `can_apply`, `blocked_reason`,
> `distance_from_aircraft_nm` and `dropped_setup_fields`; and a `PlacementResult` carrying
> `applied_setup`, `dropped_setup_fields`, `position_error_nm`, `altitude_error_ft` and
> `heading_error_deg`, with a divergent read-back producing a `position_not_verified` warning
> rather than a 5xx.
>
> None of that shipped. The consequences a client should know about:
>
> - **A UI cannot branch on a warning.** `notes` is prose. `StagingBar` picks the right sentence
>   for each field by substring — `notes.find(n => n.includes('glidepath'))` — which works and is
>   brittle in exactly the way a code was meant to prevent.
> - **The response says nothing about how far the write missed by.** `PlacementResult.state` is
>   the read-back and a caller can compute the error itself, but the server does not, and there is
>   no `position_not_verified`. Against `FakeSimAdapter` the error is exactly 0; against X-Plane it
>   is whatever the adapter's own arrival check accepted.
> - **`airac_cycle` is not carried on a placement.** The panel reads it from
>   `GET /api/navdata/status` instead (`airacLabel` in `gate.ts`), which is fine for display and
>   useless for the thing the design wanted it for: diffing a saved training profile against a
>   later cycle (manager 14).
> - **`can_apply` / `blocked_reason` are not in the preview.** The panel computes them from
>   `GET /api/capabilities` (§15.5).

### 7.5 What `PlacementAnchor` would have been

The design's `PlacementAnchor` embedded the runway (with its `Ils`), the stand, the fix, the
procedure and leg, or the hold, in every response — deliberately fat, so the panel could draw the
extended centreline without a second fetch. It was not built; the panel fetches those objects from
`/api/navdata/*` itself and the schematic (§7.3) carries the two numbers the diagram needs. Worth
revisiting when the Instructor Map wants to draw a placement it did not request.

### 7.6 Why the request models are not `core/` models

D4 put `PlacementSpec` in `core/placements.py` so managers 2 and 14 could serialise a placement
into a scenario YAML or a training profile without importing anything from `server/`. Since
`core/placements.py` was never created (§13), the request models live in the router and that
option is closed for now: a scenario file that wants to express "10 NM final at LEMD 32L" either
imports from `server/` — which inverts the dependency — or defines its own shape. Moving the six
models to `core/` is mechanical and changes no wire format; it is the natural first step of the
follow-up in §13.

---

## 8. How it composes

```
POST /api/position/apply
  { "placement": { "type": "runway", "airport_icao": "LEMD",
                   "runway_ident": "32L", "placement": "final_10nm" },
    "setup": { "ias_kt": 140 } }
  │
  ├─ server/position_routes.py :: apply_placement            (async def)
  │     adapter  = get_adapter()                             (server/deps.py singleton)
  │     _require_capability(adapter, "can_set_position", …)   → 501 if undeclared
  │
  ├─ run_in_threadpool(_resolve, request.placement, get_navdata())
  │     │
  │     ├─ provider.get_runway("LEMD", "32L")               → core.models.Runway (+ Ils)
  │     ├─ _glideslope_deg(runway, None)                    → published ILS angle, or 3.0°
  │     ├─ core.geodesy.resolve_runway_placement(runway, "final_10nm", …)
  │     │        → Placement(position, heading_deg, ias_kt, label)
  │     ├─ _speed_note(…) / the glidepath note              → the provenance sentences
  │     └─ _runway_schematic(runway, placement, …)          → PlacementSchematic
  │
  ├─ setup = _merge_setup(placement.to_setup(), request.setup)     # re-validated
  ├─ placement = _placed_as_edited(placement, setup)               # an edit moves the geometry
  ├─ _require_capability(adapter, "can_set_aircraft_state", …) when the setup is non-empty
  │
  ├─ await adapter.apply_setup(setup)                              # BEFORE the move
  ├─ await adapter.set_position(placement.position, placement.heading_deg)
  └─ PlacementResult(placement, applied=setup, state=await adapter.get_aircraft_state())
```

`preview` is the same resolution with the last four steps replaced by "return it", and it runs on
the threadpool implicitly by being declared `def`.

### 8.1 Where each rule lives, and why

| Decision | Module | Why not elsewhere |
|---|---|---|
| Where the point is | `core/geodesy.py` | Pure WGS84 maths, tested to 0.01 ft. |
| What speed to command, and how a published band clamps it | `core/geodesy.py` (`_resolve_ias_kt`, `_constrained_ias_kt`) | Already the resolution of #39. Not re-implemented. |
| Which altitude a constraint band means | `core/navdata/models.py` (`AltitudeConstraint.suggested_ft`) | Decided there, once, so preview and apply cannot disagree. |
| Which glidepath angle | `server/position_routes.py` (`_glideslope_deg`) | It is a data preference — published over nominal. **The design put this in `core/`** (§13). |
| Which fixes give a leg its heading | `server/position_routes.py` (`_neighbouring_fixes`) | It needs the whole `Procedure`, which is a navdata lookup. |
| Where a number came from | `server/position_routes.py` (`_speed_note`, `_constrained_speed_provenance`) | Presentation. It mirrors a private rule of `core.geodesy` and says `"unattributed"` when the mirror disagrees. |
| How a failure becomes a status code | `server/position_routes.py` | The only place that may know what HTTP is. |
| How the aircraft is actually moved | `adapters/xplane/` | §12. |

### 8.2 Why #8 and #41 cost this manager nothing

- **#8 (full pre-teleport setup)** extends `Placement.to_setup()` to also set flaps, gear,
  spoilers, autobrake, lights and mass. The router calls `to_setup()` and merges the overlay over
  it. When #8 lands, placements start arriving configured and **not one line of
  `server/position_routes.py` changes.**
- **#41 (autopilot)** adds fields to `AircraftSetup` and `can_control_autopilot`. Those fields
  simply pass through; the adapter refuses what it cannot honour (§9.3).

---

## 9. Capability gating

### 9.1 The gate is published before it is needed

Nobody should reach a 501. The panel reads `GET /api/capabilities` and disables the commit before
a request is ever sent — reaching a 501 means a caller ignored it, exactly as
`CapabilityNotSupported`'s docstring says. `preview` is never gated.

### 9.2 What `apply` requires

```python
_require_capability(adapter, "can_set_position", "reposition the aircraft")
...
if setup.model_dump(exclude_none=True):
    _require_capability(
        adapter, "can_set_aircraft_state", "set the speed and altitude a placement needs"
    )
```

A missing flag is **501** with a sentence naming the adapter and the flag: *"Unavailable on this
adapter — the 'fake' adapter does not declare can_set_position, so it cannot reposition the
aircraft."* The same status `POST /api/aircraft/setup` uses, for the same reason: the request is
well-formed, the server has no implementation behind it. `CapabilityNotSupported` raised from the
adapter anyway is caught and mapped to the same status as defence in depth.

> **Deviation — D8's ground/airborne split is not what the code does.** The design required
> `can_set_aircraft_state` only for an *airborne* placement, so a gate or stand needed nothing but
> `can_set_position`. What shipped requires it whenever the merged setup has any field set — and
> `Placement.to_setup()` always sets altitude, heading and speed, including for a stand at 0 kt.
> In practice **both capabilities are required for every placement**, and the UI's `commitGate`
> asserts exactly that, unconditionally.
>
> The outcome is more conservative than the design and defensible on its own terms: a stand
> placement still writes a heading and an altitude, and an adapter that cannot write them will
> place the aircraft facing the wrong way. But it is not what D8 says, and an adapter that can
> reposition and nothing else — a plausible MSFS shape — is refused outright rather than allowed
> to do ground placements.

### 9.3 There is no capability filtering

> **Deviation — `server/capability_gate.py` was never created.** D9 specified `filter_setup()` over
> a `SETUP_FIELD_CAPABILITY` mapping, dropping every set field the adapter cannot write and
> reporting them in `dropped_setup_fields` plus a `setup_field_dropped` warning — on the reasoning
> that a placement's setup is *derived* rather than typed, so dropping an untunable radio and
> saying so beats refusing the placement.
>
> What shipped writes the whole merged setup and lets the adapter refuse what it cannot honour;
> `tests/adapters/test_contract.py::test_apply_setup_refuses_capability_gated_fields_it_cannot_honour`
> pins that behaviour. So an `apply` carrying a field behind `can_control_autopilot` or
> `can_set_fuel_payload` on an adapter without them fails the *whole* call rather than degrading.
> Today nothing produces such a field — `to_setup()` sets three, all behind
> `can_set_aircraft_state` — so the divergence is latent. **It stops being latent the day #8 lands**
> and `to_setup()` starts setting mass, which is behind `can_set_fuel_payload`: at that point every
> placement on an adapter without fuel/payload control begins failing, and this section is the
> reason why.
>
> One consequence is a small gain: the design's §15.5 worried that
> `server/app.py::_CONTROL_FIELDS` and `SETUP_FIELD_CAPABILITY` would be two places mapping a
> setup field to a capability. Only one exists, so there is nothing to converge.
>
> **Update (#8 closed):** #8 landed without emitting mass — `gross_weight_kg` / `fuel_kg` were
> split off to the Fuel & Payload Manager (#16, Phase 2); see `pre-teleport-setup.md` § *Deferred,
> with rationale*. So `to_setup()` still sets only `can_set_aircraft_state` fields and the
> divergence above **remains latent**: nothing yet produces a `can_set_fuel_payload` field, so no
> placement can trip the whole-call refusal. This section stops being latent when #16 makes
> `to_setup()` emit mass, which is where the capability-filtering decision is revisited.

---

## 10. Errors

### 10.1 The shape

Every error is FastAPI's own body — `{"detail": "<one sentence>"}` — and the sentence is written
for the instructor, not for a machine. `ui/src/features/position/errors.ts` surfaces it verbatim.

> **Deviation — D10 was not honoured.** The design specified a typed `PlacementErrorDetail` over a
> closed `PlacementErrorCode` literal (`airport_not_found`, `leg_not_positionable`,
> `fix_ambiguous`, `magnetic_variation_unavailable`, …), with context fields — `path_terminator`,
> `candidates`, `navdata_status` — and every route declaring `responses={404: …, 409: …, …}` so
> the codes landed in the OpenAPI schema and in the generated TypeScript client. None of that
> shipped, and no reason is recorded. A client can therefore branch on the **status** but not on
> *which* 404 it received, and every message is prose it must render rather than interpret. The
> one exception is the 503, which does carry a structured body — the whole of `status()` — because
> the navdata handler needed it (§6.3).

### 10.2 The table, as shipped

| Situation | Status | Detail |
|---|---|---|
| Airport not in the index (navdata routes) | `404` | `"<what> is not in the navigation index."` |
| Runway end not at that airport | `404` | `"Runway 32L is not published at LEMD."` |
| Stand name not at that airport | `404` | `"Stand 'R32' is not published at LEMD."` |
| Procedure/transition not published | `404` | `"Procedure 'BARD3B' is not published at LEMD."` |
| No leg with that `sequence` | `404` | `"Procedure 'BARD3B' has no leg 40."` |
| Fix ident not in the index | `404` | `"Fix 'GOXOL' is not in the navigation index."` |
| No published hold at that fix | `404` | `"No published hold at GOXOL."` |
| **Leg is `CA`/`VA`/`FM`/`VM`/… — not positionable** | `422` | `ProcedureLeg.unpositionable_reason` **verbatim**, falling back to `"A CA leg carries no defensible coordinate."` **422, not 404**: the leg exists and is displayable, it simply has no defensible coordinate. |
| The published data cannot answer the request — a leg or hold with no altitude constraint and none given | `422` | `core.geodesy`'s own `ValueError` sentence. The request is well formed and the *data* cannot answer it. |
| `/navaids` given both query forms, or neither | `422` | the sentence naming both forms |
| Malformed body — unknown `type`, latitude 91 | `422` | FastAPI's own validation body, not remapped |
| Adapter does not declare a required flag | `501` | the sentence of §9.2 |
| Navdata index absent, building or errored | `503` + `Retry-After` | the provider's reason, plus the whole of `status()` in the body |

> **Deviation — three error cases in the design have no equivalent.**
>
> - **`409 fix_ambiguous` does not exist.** A `waypoint` request whose ident matches more than one
>   fix takes **the first match** and adds a note: *"3 fixes are published as DUPE; the one in
>   region LE was used. Give a region to disambiguate."* The design refused to guess, on the
>   grounds that guessing places the aircraft on the wrong continent. What shipped guesses and
>   says so. The note reaches the staging bar before the button is pressed, which is the mitigation;
>   it is weaker than a refusal and it is worth reconsidering.
> - **`502 sim_unreachable` does not exist.** An adapter that raises anything other than
>   `CapabilityNotSupported` propagates as a **500**. The design's reasoning — we are a gateway to
>   the simulator, `502 Bad Gateway` is literally the case — still stands and would be a small
>   `try` around the two adapter calls.
> - **`422 magnetic_variation_unavailable` does not exist** — see §10.3.

### 10.3 Magnetic versus true, for holds

`Hold.inbound_course_mag_deg` is magnetic and `core/geodesy.py` is true throughout, and this
project deliberately carries no world magnetic model. `hold_placement` therefore *requires* a
`magnetic_variation_deg`, and `_hold_variation` supplies it from the hold's airport record — adding
a note saying so:

> *"Inbound course 137° magnetic converted to 136.0° true using LEMD's published variation of
> -1°."*

When the airport publishes none, or the hold is enroute and has no airport, it passes **zero** and
says *that* instead:

> *"Inbound course 137° is MAGNETIC and was used unconverted: no magnetic variation is published
> for this fix, and this station carries no world magnetic model."*

> **Deviation — D11 was reversed: it degrades instead of failing.** The design was explicit that a
> hold placement with no variation source must **fail loudly** with
> `422 magnetic_variation_unavailable` and ask the caller for an explicit `heading_deg`, rather
> than silently use a magnetic course as a true heading. What shipped uses it unconverted and puts
> the fact in the notes, and `HoldPlacementRequest` carries no `heading_deg` for the caller to
> override with. The reason is written into `_hold_variation`'s docstring: *"the instructor is the
> one who can tell whether it matters where they are flying."* Both positions are defensible; the
> shipped one places the aircraft up to ~20° off in a high-variation region unless the instructor
> reads the note. Adding `heading_deg` to the request would restore the design's escape hatch
> without changing the default.

### 10.4 The AIRAC-staleness case, explicitly

There is no "stale cache" error, and that is deliberate. The provider's cache key is a fingerprint
whose primary component is the AIRAC cycle; a mismatch **deletes and rebuilds**. So a stale cycle
surfaces as `state == "building"` → 503 + `Retry-After: 5`, and the panel shows the progress bar
it is already polling for.

---

## 11. `SimAdapter` / `Capabilities` additions

**None. This manager requires no change to `core/sim_adapter.py`, to `Capabilities`, to
`FakeSimAdapter` or to `adapters/xplane/`.**

That is a positive finding, not an omission:

- `set_position(position, heading_deg)` and `apply_setup(setup)` are exactly the two operations
  the placement pipeline needs, in exactly that order.
- `can_set_position` and `can_set_aircraft_state` are exactly the two flags §9.2 gates on.
- `FakeSimAdapter` already declares both and implements both faithfully, including the
  `heading % 360` normalisation and the `applied_setup` affordance the contract suite uses.

**Consequence for scheduling:** the "never parallelise a contract change" rule does not bind this
manager.

> **Deviation — the one contract test the design asked for was not added.** §9.1 of the design
> specified a single parametrised case,
> `test_setup_then_position_arrives_at_the_commanded_speed`, on the grounds that the pipeline rests
> on an adapter-visible property the suite does not assert: **that a setup applied immediately
> before a teleport survives the teleport.** That is not obvious — the X-Plane adapter freezes and
> releases the flight model around both calls, and a naive implementation could have
> `set_position` clobber the speed `apply_setup` just wrote, which is issue #39 all over again.
> `tests/adapters/test_contract.py` has no such case. The order is asserted at the *server* level
> instead (`TestApplyOrdersTheWrites`, by recording calls on a subclassed fake), which proves the
> router calls them in the right order and proves nothing about whether the second call undoes the
> first on real hardware. This is the single most valuable test still missing from this manager.

---

## 12. Dataref mapping (X-Plane)

**No new dataref. `adapters/xplane/` is not touched by this manager.** The mapping is reproduced
here only so the reader can see that the server never approaches it:

| Interface method | X-Plane, in `adapters/xplane/xplane_adapter.py` |
|---|---|
| `set_position` | Freeze (`override_planepath[0] = 1`) → write `local_x/y/z` (world coords are read-only and derived) → write the velocity vector `local_vx/vy/vz` + `psi` along the target heading → release in a `finally` → clear the crash state with `sim/operation/fix_all_systems`. Re-measures the frame origin and re-aims across a scenery reload (#36). |
| `apply_setup` | The same freeze around the attitude writes (issue #37), plus the per-field dataref writes. |
| world → local frame | `core/local_frame.py`, a rigid ECEF rotation from an origin *measured* from the aircraft. **`lat_ref`/`lon_ref` are never trusted.** |

Two consequences this manager respects:

1. **The server writes setup then position, in that order**, which is the order the adapter's
   freeze/release protocol expects.
2. **The server never asks the adapter to freeze, pause or unpause.** The feature spec's "pause the
   simulator, write, unpause" is an *adapter* implementation detail, and the adapter's validated
   procedure supersedes it. `server/` has no pause concept and must not acquire one.

**MSFS (Phase 5).** `set_position` maps to SimConnect's `SIMCONNECT_DATA_INITPOSITION`, which takes
latitude/longitude/altitude/heading/airspeed **in one structure** — the setup-then-position split
collapses into a single call there. That is entirely inside `MSFSAdapter`; this API's models are
unchanged, which is precisely the Phase 5 measure of success. Expect `can_set_aircraft_state` to be
narrower on MSFS, which is where §9.3's missing filtering will be felt first.

---

## 13. `core/` logic

**No `core/` module was added by this manager.** Everything it needs already existed or arrived
from #6:

| What | Where |
|---|---|
| Placement geometry | `core/geodesy.py` — `Placement`, `resolve_runway_placement`, `coordinate_placement`, `waypoint_placement`, `procedure_leg_placement`, `procedure_placement`, `hold_placement`, `hold_entry_placement`, `holding_pattern_point`, `positionable_legs`, `turn_radius_nm`, `true_from_magnetic` |
| The static world | `core/navdata/provider.py` — the `NavdataProvider` protocol |
| The vocabulary | `core/navdata/models.py`, `core/models.py` (`Runway`, `Ils`, `GeoPosition`, `AircraftSetup`) |

This branch originally wrote its own holding geometry and then **deleted it**: PR #64 landed
`feature/placement-geodesy` (#6) on `dev` in parallel with a far more complete treatment of the
same ground. Keeping a second, smaller implementation of the same thing would have been the worst
outcome available, so the merge took `dev`'s wholesale and the router was rewritten against it.
Two of `dev`'s decisions changed the router's behaviour and are better than what was specified
here — a published speed is a ceiling rather than a target, and a leg's heading comes from its
neighbours (§7.4, §8.1).

> **Deviation — `core/placements.py` and `core/radio_tuning.py` do not exist.** The design put
> `resolve_placement(provider, spec) -> ResolvedPlacement` and seven per-anchor resolvers in
> `core/placements.py`, with `PlacementResolutionError` carrying a code, a
> `PLACEMENT_CATALOGUE` of the fourteen rows as data, `LONG_TELEPORT_WARNING_NM`,
> `GROUND_TOLERANCE_FT`, and a `final_placement_at(runway, distance_nm, …)` for arbitrary final
> distances; and radio tuning in `core/radio_tuning.py`.
>
> What exists instead: `_resolve_placement` in `server/position_routes.py`, `GROUND_TOLERANCE_FT`
> as a router constant, no catalogue-as-data, no arbitrary final distance, no radio tuning, and no
> long-teleport constant. The reason is partly visible in the history — the first implementation
> was recovered from uncommitted working-tree state (commit `45b260f`) and committed verbatim
> "without review or edits, so it survives", then completed in place rather than restructured.
>
> What it costs, concretely:
>
> - **Reuse.** Managers 2 (scenarios) and 14 (training profiles) cannot resolve a placement
>   without importing from `server/`.
> - **Testability.** The placement logic is only reachable through `TestClient`. It is thoroughly
>   tested that way (§16), but the tests are HTTP tests.
> - **A `12 NM final` is not expressible**, because `final_placement_at` was the thing that would
>   have decoupled a distance from a named preset.
>
> The migration is mechanical and changes no wire format: move the six request models and
> `_resolve_placement` into `core/placements.py`, keep the `HTTPException` mapping in the router,
> and have the resolver raise a typed error instead — which is also the cheapest route to §10's
> machine codes.

---

## 14. Server wiring — `server/deps.py`

The navdata provider is a singleton chosen **independently of the simulator** — the fake adapter
over a real X-Plane install is the intended development loop, and the real adapter over in-memory
navdata is how repositioning is tested without depending on anyone's install:

```python
NavdataProviderName = Literal["xplane_native", "in_memory"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OIS_", env_file=".env", extra="ignore")
    adapter: AdapterName = "fake"
    xplane_host: str = "localhost"
    xplane_port: int = 8086
    navdata: NavdataProviderName = "xplane_native"
    navdata_root: str | None = None  # explicit X-Plane install; autodetected when None
    host: str = "0.0.0.0"
    port: int = 8000


@lru_cache(maxsize=1)
def get_navdata() -> NavdataProvider: ...
def reset_navdata() -> None: ...  # drops only the provider
def reset_adapter() -> None: ...  # drops settings, adapter AND provider
```

`reset_adapter()` clears all three together: they are read from one `Settings` object, so
resetting one and leaving another cached would run a test against a mismatched pair.

`_build_navdata` resolves the X-Plane root with `discover_xplane_root` and hands it to
`XPNativeCifpSource`. That is filesystem I/O, which the provider protocol forbids a *provider* from
doing in its constructor — doing it in the composition root is a different rule and is deliberate:
it runs once behind the cache, and the CIFP source needs a concrete tree because the provider does
not build one for itself. The two are mutually dependent (the source resolves its legs' ARINC keys
through the provider's index), so the resolver closure binds late. Constructing a provider builds
no index; `POST /api/navdata/index` does, and until it has run the provider honestly reports itself
as unavailable.

`server/app.py` stays the shell: it includes both routers and registers the `NavdataUnavailable`
handler.

> **Deviation — `OIS_XPLANE_PATH` and `OIS_NAVDATA_CACHE_DIR` are `OIS_NAVDATA_ROOT` and nothing.**
> The design named three settings; two shipped, under one name (`navdata_root`), and the cache
> directory is the provider's own concern.

---

## 15. The panel

### 15.1 Shell

`App.tsx` is a two-column workspace: the Position panel and the aircraft controls take the left
two thirds, with Telemetry and Capabilities stacked beside them and reflowing underneath on a
tablet in portrait. The panel is the first thing on the page, because it is the reason the page
exists.

### 15.2 Structure, top to bottom

**1 — Airport bar** (`AirportSearch.tsx`). A combobox, **250 ms** debounce, over
`GET /navdata/airports?q=`. Result rows: ICAO in mono, name, longest runway, a dot when
`has_procedures`. Before any typing it lists the last five airports used (client state). The
selection shows elevation and the AIRAC cycle from `status`. `⌘K` / `Ctrl-K` focuses it, and the
hint is rendered in the label rather than left as folklore. A failed search reports itself rather
than rendering an empty list — an empty list is indistinguishable from "no such airport".

**2 — Runway selector** (`RunwaySelector.tsx`). One button per runway **end** — 18L and 36R are two
buttons, because a placement is always relative to one end. Each shows length, surface, and an ILS
badge (frequency, course, glidepath) when `…/ils` returns one; a 404 there is an ordinary outcome
and the badge simply does not render.

**3 — Placement tabs**, each enabled only when its data exists:

| Tab id | Label | Component |
|---|---|---|
| `pattern` (default) | Pattern & final | `PatternGrid.tsx` |
| `procedures` | Procedures | `ProcedureList.tsx` |
| `parking` | Gates & stands | `ParkingList.tsx` |
| `coordinate` | Coordinate & fix | `CoordinateForm.tsx` |

- **Pattern & final** — the incumbent's spatial grid, reworked. An SVG runway sits in the middle;
  upwind, crosswind, downwind and base tiles for **both** circuit directions sit where they
  actually are relative to it; and a *finals rail* runs down the approach side with chips for
  `20 · 15 · 10 · 8 · 5 · 3 NM · Short`. Tapping any of them stages it.
- **Procedures** — SID / STAR / Approach lists from `ProcedureSummary`. Selecting one loads its legs
  into a dense table: sequence, path terminator, fix (mono), altitude and speed constraints rendered
  from their `.display` computed fields. Positionable legs are tappable rows; the rest render
  **visible but disabled with `unpositionable_reason` inline** — issue #10 asks for exactly this,
  and it is why the reason string is computed server-side and never re-derived in TypeScript.
- **Gates & stands** — the parking list, filterable by `ParkingKind` and searchable by name.
- **Coordinate & fix** — a lat/lon/altitude/heading/speed form and a fix-ident + altitude form. The
  speed field is not optional in spirit and the form says why: a free coordinate is the one
  placement whose speed defaults to zero, and an instructor putting the aircraft airborne must
  state a speed or it arrives below stall.

**4 — Staging bar** (`StagingBar.tsx`; persistent, bottom, the hero of the surface):

- left: the SVG schematic drawn from `PlacementSchematic` — runway, centreline, the placement dot
  with its heading vector, the glidepath wedge and distance labels, plus the placement's label;
- right: four editable controls — **altitude ft, IAS kt, heading °, landing gear** — pre-filled
  from `preview.setup` with the matching `notes` sentence underneath in tertiary text. Numbers are
  rounded for display, which is safe because an untouched field is never sent: the overlay carries
  only what was edited, so the server's full-precision value is what gets applied;
- one solid primary button, **Place aircraft**. It is the only solid button on the surface.

Commit posts to `/position/apply` and reports the state that came **back** — *"Placed at 4,184 ft,
120 kt."* — not what was asked for. Failures render **inline in the bar**, never a modal, which is
failure mode 5 of the incumbent.

> **Deviation — three things the as-built account claimed that the code does not do.**
>
> - **Edits do not re-run `preview`.** The account said they did, debounced 300 ms, so the diagram
>   and notes stayed truthful. They do not: `usePreviewPlacementQuery` is keyed on the staged
>   request alone, and the edits are merged client-side (`{...preview.setup, ...overrides}`) and
>   posted as a sparse overlay. The schematic therefore shows the *computed* geometry while the
>   numbers show the *edited* one. For an altitude edit that is a visible inconsistency — the
>   server would place the aircraft where `_placed_as_edited` puts it, not where the diagram
>   shows. The 250 ms debounce that does exist is the airport search's.
> - **The confirmation flash is `FLASH_MS = 2400`**, not "≤ 300 ms". 2.4 s is long enough to read
>   a sentence, which is what it now carries.
> - **The editable controls are altitude, IAS, heading and gear** — not "altitude, IAS, gear,
>   flaps". `AircraftSetup` has no flap field the bar exposes.

### 15.3 State — Redux Toolkit only

- `ui/src/api/instructorApi.ts` gains the navdata and position endpoints and the tag types
  `NavdataStatus` and `Airport`.
- `ui/src/features/position/positionSlice.ts` holds **client state only**:

  ```ts
  interface PositionState {
    selectedIcao: string | null;
    selectedRunwayIdent: string | null;
    activeTab: PositionTab;                                       // pattern|procedures|parking|coordinate
    openProcedure: { kind: string; ident: string; transition: string | null } | null;
    staged: PlacementRequest | null;
    setupOverrides: AircraftSetup;                                // the sparse overlay
    recentIcaos: string[];                                        // RECENT_AIRPORT_LIMIT = 5
  }
  ```

  Server data never lands here.
- `previewPlacement` is an RTK Query **query**, not a mutation, despite being a `POST`: it is
  side-effect-free by design, and modelling it as a query is what lets the staging bar re-run it
  and get caching and de-duplication for free. `applyPlacement` is a mutation and invalidates
  `AircraftState`.
- Components under `ui/src/features/position/`: `PositionPanel`, `AirportSearch`, `RunwaySelector`,
  `PatternGrid`, `ProcedureList` (the leg table lives inside it), `ParkingList`, `CoordinateForm`,
  `StagingBar`, `Schematic`.
- The pure logic sits in four files with no React in them at all, which is what makes it testable
  without rendering: `gate.ts` (both gates), `projection.ts` (fitting the runway frame into the
  viewBox), `placements.ts` (the tile catalogue and the formatters) and `errors.ts`. The split is
  not only taste — `react-refresh/only-export-components` fails the lint when a component file also
  exports a function.

> **Deviation — the shared API module is edited, not extended.** The design was explicit that
> `ui/src/api/instructorApi.ts` must **not** be edited: endpoints were to be added from a
> `ui/src/features/position/positionApi.ts` with `injectEndpoints`, and tag types with
> `enhanceEndpoints`, which is RTK Query's supported code-splitting mechanism and makes "adding a
> manager adds files rather than editing shared ones" literally true. What shipped adds both
> directly to `instructorApi.ts`. Every later manager will now edit the same file, which is exactly
> the merge-conflict surface the rule existed to avoid. The slice is also
> `positionSlice.ts` with different fields from the design's `PositionPanelState`.

### 15.4 Visual system

`ui-craft-dense-dashboard` at CRAFT 7 / DENSITY 9 / MOTION 3, applied by **evolving** the existing
dark tokens rather than replacing the theme. The panel's own rules live in
`ui/src/features/position/position.css`, imported by `PositionPanel`; only the shell layout was
touched in `ui/src/index.css`. That follows the rule that adding a manager must not require
touching the others.

- `font-variant-numeric: tabular-nums` on every numeric readout; mono on every identifier (ICAO,
  runway, fix, frequency). **IBM Plex was not adopted**: the app already ships a coherent
  system-font stack with a monospace pair, and adding `@fontsource` would have put two font
  families into a PyInstaller bundle to change nothing an instructor can act on.
- 4/8 px spacing grid; 40–44 px rows in the leg and parking tables; sticky `thead` past ~15 rows;
  `scrollbar-gutter: stable` on every scroll container; `overflow-x: auto` around every table.
- Status as dots, not badges. Sentence-case headers. Ghost buttons in toolbars.
- Touch targets ≥ 44 px — where density and the tablet disagree, the tablet wins.
- Micro-motion only: 80 ms row hover. No scroll reveals.
- No pie, donut or 3-D chart anywhere. The only graphic is the schematic.

### 15.5 Gating

Two gates, and both **fail closed** on a fetch or a loading state, exactly as
`ui/src/features/aircraft/controls.ts` already does for controls. Hard rule 3 is only true if "I
could not find out" counts as unsupported — otherwise a server that is merely slow reads as fully
capable and the panel offers a button that cannot work.

- **`commitGate(capabilities, isError)`** — `GET /api/capabilities`. Closed while loading, closed
  on error, closed without `can_set_position`, closed without `can_set_aircraft_state`. When it is
  closed the panel still renders and stays fully explorable — `preview` needs no simulator — and
  only the commit button dies, showing the reason.
- **`navdataGate(status, isError)`** — `GET /api/navdata/status`. Anything but `ready` replaces the
  panel body with a status card: `building` shows a progress bar from `IndexProgress` and polls at
  `BUILD_POLL_MS = 1000` **only while building**; `unavailable` shows the reason and a **Build
  index** button hitting `POST /navdata/index`; `error` shows the reason and **no** button — an
  index that has never been built is one click from working, while one that failed will fail again
  the same way until a human fixes the install, and offering a button that re-runs a known failure
  is worse than saying what went wrong.

### 15.6 What is not in the panel

- **No hold surface.** `HoldPlacementRequest` is served by the API and typed in the generated
  client, `useGetHoldsQuery` is exported from `instructorApi.ts`, and **nothing renders either**.
  The as-built account described the fourth tab as "Coordinate, waypoint & holds"; it is
  "Coordinate & fix". A hold can only be placed by posting to the API directly.
- **No `glideslope_deg`, `pattern_width_nm` or `leg_distance_nm` control.** The API accepts all
  three; the panel sends none, so every circuit is the default 1.0 NM wide with 1.5 NM legs and
  every final is on the published or standard glidepath.
- **No approach-category selector.** Every placement the panel makes is category B (§18.4).

---

## 16. Tests

Everything runs in CI against `FakeSimAdapter` and `InMemoryNavdataProvider`. No simulator, no
navdata file.

### 16.1 The fixture world

`tests/server/conftest.py` builds it in Python: airport **`ZZZZ`** — the ICAO code reserved for "no
code assigned", so it can never collide with a real one — elevation 1000 ft, runway **36 on a true
bearing of 000°** so pattern geometry reads by eye, its reciprocal 18, an ILS on 36, a gate, one
fix, three navaids carrying a deliberate ident collision — navaid idents are not globally unique,
which is the whole reason `/navaids` returns a list — a published hold placarded at 210 kt, and a
SID with one `CA` leg, one `TF` leg carrying an altitude band and a speed constraint, and one `TF`
leg carrying neither.
**No navdata file is committed** (hard rule 4);
`tests/core/navdata/test_no_navdata_committed.py` enforces that repository-wide.

> **Deviation — the fixture is not `tests/fixtures/navdata_world.py`** and the airport is not the
> design's `ZZZZ` at 2000 ft with runways 09/27. Same idea, different numbers; every reference
> value below is the shipped one.

### 16.2 Python

- **`tests/server/test_position_routes.py`** — the numeric reference is a 3° glidepath 10 NM out
  over a 1,000 ft threshold: **4184.4 ft**, i.e. 318.44 ft/NM. It covers preview geometry, the
  schematic projection, the notes, every non-runway placement type, procedure legs (including a
  `CA` leg refused with its own reason and an unconstrained leg needing an altitude), holds,
  capability gating, request validation — and four groups that each pin a fixed defect:
  `TestApplyOrdersTheWrites` asserts the order by **recording the calls** on a subclassed fake
  rather than by inspecting the response, because a response that looks right is exactly what the
  buggy order produced; `TestAnEditedGeometryFieldActuallyTakes` asserts an edited altitude and
  heading reach the aircraft and that `applied` describes the outcome and not the request;
  `TestTheMergedSetupIsValidated` asserts a nested edit survives as a model and not a dict;
  `TestApplyResolvesNavdataOffTheEventLoop` asserts both routes resolve in the threadpool by
  checking for a running loop from inside the provider.
- **`tests/server/test_navdata_routes.py`** — every route, 404-vs-503, the `/near` shadowing, the
  `Retry-After` values, and the wire parameter `q`.
- **`tests/core/test_geodesy_navdata.py`** — the hold and procedure geometry that arrived with
  PR #64: the three entry sectors tile the compass exactly once with every boundary asserted, a
  left-hand hold is the mirror of a right-hand one, the turn-radius criteria cross at ~170 kt, and
  the racetrack is level and rotates with its inbound course.
- **`tests/adapters/test_contract.py` is not extended** — no new capability is introduced. See the
  deviation in §11 for the one case that should have been added anyway.

### 16.3 TypeScript (vitest)

129 cases across fourteen files under `ui/src/features/position/` — 45 with the panel itself, 84
added afterwards to cover the pickers.

- `gate.test.ts` — both gates, with the loading and unreachable cases asserted explicitly, because
  those are the ones that turn hard rule 3 from a claim into a property.
- `projection.test.ts` — the runway always in frame, the minimum span, and **no shearing**: a
  square 4 NM box must project square, or the diagram stops answering "how far out".
- `positionSlice.test.ts` — mostly about *clearing*. A staged placement that survives a change of
  airport is the dangerous bug here: the bar would still show a plausible diagram and the button
  would place the student at the previous field.
- `StagingBar.test.tsx` — renders against a stubbed `fetch` (not mocked hooks, so the request
  bodies are observable). Asserts that staging issues a `preview` and **no** `apply`; that the
  edits go up as a sparse overlay; that the confirmation reports the state that came back; that a
  501 renders inline and not as a dialog.
- The picker tests assert every staged request with `toEqual`, so no picker can quietly fill in an
  `ias_kt` of 0 and put an aeroplane on a final below stall speed; `PositionPanel.test.tsx` walks
  that path end to end — coordinate tab, 4,000 ft, no speed — and requires the server's stall
  warning to reach the screen.
- `Schematic.test.tsx` measures the heading vector against the runway axis and not against the
  screen, with hand-computed coordinates.
- `errors.test.ts` — the server's `detail` reaches the instructor verbatim.

> **Deviation — `tests/sim/test_live_position_api.py` does not exist.** The design specified a
> `@pytest.mark.sim` suite that built a synthetic in-memory runway from the live aircraft's own
> position, previewed, applied a 5 NM final, asserted `position_error_nm < 0.05` and restored in a
> `finally`. `tests/sim/` contains only `test_live_xplane.py`, which exercises the adapter. Live
> validation of the *API* is therefore the `sim-validator` agent's ad-hoc smoke rather than a
> suite.

### 16.4 The client

`npm run generate:api` regenerates `ui/src/api/schema.d.ts` from the running server. Nothing in
`ui/` hand-writes an API shape.

---

## 17. Parallelisation

**The one serialised step** was `server/deps.py` gaining `get_navdata()` / `reset_navdata()` and
the `OIS_NAVDATA` / `OIS_NAVDATA_ROOT` settings — shared wiring, so it followed the same rule as a
`SimAdapter` contract change: made once, before dependent work branched. There was no other:
no `SimAdapter`/`Capabilities` change (§11) and no navdata schema migration.

**What must never be parallelised here:** `server/deps.py`'s `get_navdata()`;
`core/navdata/schema.py` (single-owner by standing rule); merges to `dev`/`main`; release tagging.

> **Deviation — the four planned tracks became one branch.** The design split the work into
> A (position backend), B (position tests), N (navdata router) and C (the UI panel), on disjoint
> write sets, dispatched in a single message. It shipped as one branch, `feature/position-manager`,
> covering all four. The stated reason is real: the panel needs `schema.d.ts` regenerated from the
> running Phase-A server, so splitting the API from the panel would have meant either a merge in
> the middle or hand-written API types, and the second is forbidden. Track B — tests written
> against the design without waiting for the implementation — did not happen either; the tests
> were written after the code, which is visible in the fact that the design's error codes and
> models have no tests asserting their absence.

---

## 18. Open questions and risks

### 18.1 Magnetic → true for holds

Two things are still unresolved:

1. **Sign convention.** `Airport.magnetic_variation_deg` documents "positive east";
   `Navaid.magnetic_variation_deg` documents nothing, and `earth_nav.dat` publishes variation with
   a convention that is not recorded anywhere in this repository. **What resolves it:** a check of
   `core/navdata/xplane_native/earth.py` against a known station and a one-line docstring addition.
2. **Whether a nearby station's variation is acceptable at all** for a fix tens of miles away.

Since §10.3's fallback uses zero rather than refusing, both questions are *live* rather than
deferred: a hold at an airport with no published variation is placed on a magnetic course used as
a true one today, with only a note to say so.

### 18.2 Long teleports — resolved in the adapter

X-Plane relocates the local frame origin during a scenery reload, so `local_x/y/z` written before
the reload denoted a different world position. That was #36, and this API is what made it reachable
in one tap: `{"type": "runway", "airport_icao": "KJFK", …}` from LEMD is a routine instructor
action, not an edge case. **It has since been fixed in `adapters/xplane/`**: `set_position`
re-measures the origin and re-aims, taking a re-measure only after a whole slice of *answered*
polls has failed and requiring two consecutive measurements to agree.

The design's mitigation here — a `long_teleport` warning at 100 NM and a `position_not_verified`
result — was never implemented and is now largely unnecessary. What remains is the pause: a long
teleport still triggers a scenery reload, and the panel says nothing about it before the button is
pressed.

### 18.3 Ground placements arrive at an estimated elevation

`apt.dat` publishes no per-stand elevation, so `ParkingStand.position.altitude_ft` is the airport
datum. At an airport with a sloping apron that is metres out, and a teleport writes an MSL altitude
into the local frame — so the aircraft may arrive slightly sunk or slightly floating before the
physics settles it. The design warned about this with a `ground_elevation_estimated` code; with no
warning model (§7.4) it is not reported at all. **What resolves it:** a measurement at a real
airport with a known apron slope, and, if it matters, an adapter-side "snap to ground" using the
simulator's own terrain probe — a `SimAdapter` addition and therefore a serialised contract
change, out of scope for Phase 1.

### 18.4 Approach-category defaults are a guess, by construction

`APPROACH_CATEGORY_VAT_KT` is per category, not per airframe: within category C a light business
jet and a 737 land 15 kt apart. The default is `B` (120 kt on final), deliberately *fast* for a
trainer and *slow* for a heavy — and slow is the failure that kills. The API puts `category` in
every request and `ias_kt` above it; **the panel exposes neither**, so every placement made from
the UI is category B unless the instructor edits the speed in the staging bar afterwards. That is
the largest gap between the API's honesty and the panel's.

**Open question:** should the panel remember a per-aircraft category, keyed on the loaded aircraft
ICAO the adapter could report? That needs a new `SimAdapter` read — a contract change, and
therefore a Phase 2 decision.

### 18.5 Preview/apply consistency depends on navdata not moving underneath

Resolution is a pure function of (navdata, request), so preview and apply agree — unless the index
rebuilds between the two calls because a new AIRAC cycle appeared. The window is seconds wide and
the consequence is that the aircraft lands on a slightly different, *newer* procedure than the one
previewed. Not solved, deliberately: an optimistic-concurrency token to defend a window that opens
once every 28 days would cost more than it saves. The design carried `airac_cycle` in both
responses so a UI that cared could compare them; that field was not built (§7.4), so today nothing
can detect it.

---

## 19. Non-goals, recorded as decisions

- **No runway-threshold ("line up for takeoff") placement.** Not in the feature spec's Phase 1
  list. It is a small addition to §3 the day it is wanted.
- **No batch placement.** One aircraft, one placement, one request.
- **No undo.** Restoring a previous position is manager 12 (Session Recorder), and it restores
  through this same endpoint with a `coordinate` request.
- **No terrain awareness.** The API will happily place an aircraft inside a hill at a coordinate
  the instructor asked for. Terrain data is not in scope for Phase 1 and inventing a partial check
  would give false confidence.
- **No persistence.** A placement request is not stored anywhere by this manager.

---

## 20. Delivery

Built as one branch, `feature/position-manager`, rather than the four tracks planned (§17): the
panel needs `schema.d.ts` regenerated from the running Phase-A server, so splitting them would have
meant either a merge in the middle or hand-written API types, and the second is forbidden.

Closes **#9** and **#10**. The last bullet of **#6** was closed on `dev` by PR #64 instead (§13).

CI is the integration barrier. Nothing here touches `SimAdapter` or `Capabilities`, so this work
was not on the never-parallelise list.

**The follow-ups this document records, in the order they are worth doing:**

1. The contract test that a setup applied before a teleport survives it (§11) — the one missing
   test that could hide issue #39 on real hardware.
2. ~~Capability filtering, or at least a decision, before #8 lands and starts setting mass (§9.3).~~
   **Decided:** #8 closed without emitting mass (deferred to #16), so the gap stays latent; the
   filtering decision is revisited with #16. See §9.3's update.
3. `heading_deg` on `HoldPlacementRequest`, so the magnetic fallback has an escape hatch (§10.3).
4. Move the request models and the resolver into `core/placements.py` (§13, §7.6), which is also
   the cheapest route to §10's machine error codes.
5. A hold surface in the panel, or an explicit decision that the API-only hold is enough (§15.6).
6. `502` for an unreachable simulator (§10.2).

## 21. Verification

```bash
pytest && ruff check . && ruff format --check . && mypy .
cd ui && npm run lint && npm run typecheck && npm test && npm run build
```

Then, against `OIS_ADAPTER=fake OIS_NAVDATA=in_memory` with the Vite dev server, one batched
browser session: airport search → runway → stage a 10 NM final → check the schematic and the
notes → commit → read the applied state back, plus a console check. No live simulator is needed for
either phase; a real-sim smoke is the `sim-validator` agent's job and is not a merge gate.
