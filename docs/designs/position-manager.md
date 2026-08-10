# Position Manager — design

Covers issues **#9** (API endpoints) and **#10** (UI panel). This is the manager the product
exists for: put the aircraft where the lesson needs it, from a tablet, without alt-tabbing into
the simulator.

Everything it needs from `core/` already exists:

| What | Where |
|---|---|
| Placement geometry | `core/geodesy.py` — `Placement`, `resolve_runway_placement`, `coordinate_placement`, `waypoint_placement`, `procedure_leg_placement`, `hold_placement`, `positionable_legs`, `true_from_magnetic` |
| The static world | `core/navdata/provider.py` — the `NavdataProvider` protocol |
| The vocabulary | `core/navdata/models.py`, `core/models.py` (`Runway`, `GeoPosition`, `AircraftSetup`) |

**This branch adds nothing to `core/`.** `server/` is a façade over what is already there; the
panel is a consumer of the façade. See §3.4 for why the holding geometry that was originally
specified here no longer is.

**Status: both phases are implemented** on `feature/position-manager`.

---

## 1. What the incumbent gets right, and what it gets wrong

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

## 2. The two decisions that shape the panel

**Staging, not firing.** Selecting a placement never moves the aircraft. It *stages* it: the
server computes a preview, and a persistent bar shows what will be applied with the numbers
editable. One primary button commits. Two taps, no modal, and the instructor always sees the
altitude and the speed before a student's aeroplane jumps.

**A schematic, not a map.** The preview is a small SVG — runway, extended centreline, placement
point, heading vector, glidepath — drawn from geometry the API returns. No MapLibre (that is the
Instructor Map, issue #19), no new dependency, and it renders instantly on a tablet.

**Every airport, always.** Airport selection is search-as-you-type over the whole index
(~35 k airports). Nothing in this design names an airport, and the panel must behave identically
at LEMD and at a 600 m grass strip with no procedures — which is why every tab enables itself
from data (`has_procedures`, non-empty parking, non-empty runways) rather than from an
assumption.

---

## 3. Phase A — the API (issue #9) — IMPLEMENTED

`server/app.py` stays the shell and includes two routers. Navdata queries are **synchronous** by
protocol contract, so their routes are declared `def` (FastAPI runs them in the threadpool);
placement commit touches the adapter and is `async def`.

### 3.1 Wiring — `server/deps.py`

The navdata provider is a singleton chosen **independently of the simulator**:

```python
NavdataProviderName = Literal["xplane_native", "in_memory"]


class Settings(BaseSettings):
    ...
    navdata: NavdataProviderName = "xplane_native"
    navdata_root: str | None = None  # explicit X-Plane install; autodetected when None


def get_navdata() -> NavdataProvider: ...  # lru_cache(1)
def reset_navdata() -> None: ...
```

`reset_adapter()` clears the adapter, the navdata provider **and** the settings together: they
are read from one `Settings` object, so resetting one and leaving another cached would run a
test against a mismatched pair.

`_build_navdata` resolves the X-Plane root with `discover_xplane_root` and hands it to
`XPNativeCifpSource`. That is filesystem I/O, which the provider protocol forbids a *provider*
from doing in its constructor — doing it in the composition root is a different rule and is
deliberate: it runs once behind the cache, and the CIFP source needs a concrete tree because the
provider does not build one for itself. The two are mutually dependent (the source resolves its
legs' ARINC keys through the provider's index), so the resolver closure binds late.

### 3.2 `server/navdata_routes.py` — read-only façade

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
| `GET /api/navdata/fixes?ident=&region=&terminal_airport=` | `list[Fix]` |
| `GET /api/navdata/holds?fix_ident=&region=&airport_icao=` | `list[Hold]` |

Rules:

- **Absent is 404, broken is 503.** The provider returns `None` for a missing airport, so a 404
  means "no such thing". `NavdataUnavailable` becomes **503** with its own reason, registered
  **once as an app-level exception handler** rather than repeated as a `try` in twelve routes —
  every one of them can raise it and every one would answer identically. The UI gates on
  `status` and should never see a 503, exactly as it should never see a 501 from the adapter.
- `/airports/near` is declared **before** `/airports/{icao}` so the literal wins the match. There
  is a test for that specifically, because the failure mode is a silent 404 for the word "near".
- The index build runs on a module-owned worker thread with a module-level cancel `Event`. A
  second `POST /index` while one is running is an idempotent no-op returning the current status,
  so an impatient tablet cannot fork-bomb one SQLite file.
- No new WebSocket. The build is minutes-long and coarse; the panel polls `status` while
  `state == "building"`.

### 3.3 `server/position_routes.py` — the placement commands

One discriminated union so the generated TypeScript client can switch exhaustively:

```python
class RunwayPlacementRequest(BaseModel):
    type: Literal["runway"]
    airport_icao: str
    runway_ident: str
    placement: RunwayPlacement  # the Literal from core.geodesy
    glideslope_deg: float | None = None
    pattern_altitude_ft: float | None = None
    pattern_width_nm: float | None = None
    leg_distance_nm: float | None = None
    ias_kt: float | None = None
    category: ApproachCategory | None = None


class ParkingPlacementRequest(BaseModel):
    type: Literal["parking"]
    airport_icao: str
    stand_name: str  # matched case-insensitively


class CoordinatePlacementRequest(BaseModel):
    type: Literal["coordinate"]
    position: GeoPosition
    heading_deg: float | None = None
    ias_kt: float | None = None


class WaypointPlacementRequest(BaseModel):
    type: Literal["waypoint"]
    ident: str
    region_code: str | None = None
    terminal_airport: str | None = None
    altitude_ft: float
    heading_deg: float | None = None
    ias_kt: float | None = None
    category: ApproachCategory | None = None


class ProcedureLegPlacementRequest(BaseModel):
    type: Literal["procedure_leg"]
    airport_icao: str
    kind: ProcedureKind
    ident: str
    transition: str | None = None
    sequence: int  # the leg's own sequence number
    altitude_ft: float | None = None  # None -> AltitudeConstraint.suggested_ft
    ias_kt: float | None = None  # None -> SpeedConstraint.suggested_kt, else category
    category: ApproachCategory | None = None


class HoldPlacementRequest(BaseModel):
    type: Literal["hold"]
    fix_ident: str
    region_code: str | None = None
    airport_icao: str | None = None
    altitude_ft: float | None = None  # None -> the hold's min_altitude_ft
    ias_kt: float | None = None  # None -> the hold's speed_kt, else category
    category: ApproachCategory | None = None


PlacementRequest = Annotated[RunwayPlacementRequest | ..., Field(discriminator="type")]
```

`RunwayPlacementRequest` deliberately covers **both** finals and circuit legs, because
`resolve_runway_placement` already does — the API mirrors `core/` rather than inventing a second
taxonomy. A "gate" and a "parking stand" are likewise one request, because `apt.dat` publishes
one record type (see `ParkingStand`'s docstring).

**Every optional field is `| None`, never a default in the schema.** The obvious alternative —
`category: ApproachCategory = DEFAULT_APPROACH_CATEGORY` — reads better in Python and is wrong on
the wire twice over. It makes `openapi-typescript` emit the property as **required**, so a
generated client is forced to send a category on every request; and it destroys the distinction
between an instructor who chose B and one who said nothing, which is precisely what the preview's
notes exist to report. `request_category()` and the `or DEFAULT_*` fallbacks resolve them in one
place, and the notes say which happened.

**Two endpoints.**

```
POST /api/position/preview  ->  PlacementPreview
POST /api/position/apply    ->  PlacementResult
```

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


class PlacementPreview(BaseModel):
    request: PlacementRequest
    placement: Placement  # position, heading_deg, ias_kt, label
    setup: AircraftSetup  # Placement.to_setup(), the pre-teleport state
    schematic: PlacementSchematic
    notes: tuple[str, ...]


class ApplyPlacementRequest(BaseModel):
    placement: PlacementRequest
    setup: AircraftSetup | None = None  # the staging bar's edits


class PlacementResult(BaseModel):
    placement: Placement
    applied: AircraftSetup
    state: AircraftState
```

- **`preview` touches no simulator.** It resolves navdata, calls the `core.geodesy` function and
  projects the schematic. It is a `POST` because its body is a union, not because it mutates —
  and a test asserts the aircraft state is byte-identical before and after.
- **`notes` is what makes the staging bar honest.** Every pre-filled number says where it came
  from: `"4,184 ft — 3° glidepath 10 NM from the 36 threshold at 1,000 ft"`, `"120 kt — ICAO
  category B threshold speed (V_AT). This is a category default, not this airframe's number"`,
  `"6,000 ft — published constraint: at or above 6000 ft"`. The UI renders them verbatim and
  never re-derives them. An airborne coordinate requested at 0 kt gets a note saying the aircraft
  will be below stall speed.
- **What the schematic actually emits today.** For a runway-relative placement: three points —
  `threshold` at the origin, `runway_end` at the far end, and `placement`. Non-runway placements
  return an empty schematic. The `glidepath` / `leg` / `fix` roles exist in the union but are not
  emitted yet: the UI draws the glidepath wedge from `glidepath_deg` and the placement's own
  distance, which needs no extra points. Emitting a hold racetrack or a procedure-leg polyline is
  the natural extension and is Phase B's to ask for.
- `x_nm` / `y_nm` are a runway-local tangent plane. The flat-earth error the `local_frame` gotcha
  warns about does not apply: this frame **only ever draws a diagram**, and the authoritative
  answer is the `position` beside it.

`apply` merges the caller's non-`None` setup fields **over** the preview's, so a client sending
only a speed cannot silently drop the geometry-derived altitude. Order of operations, non-negotiable
(gotchas #37 and #39):

1. Resolve the placement.
2. `await adapter.apply_setup(merged_setup)` — speed, altitude, heading **before** the move.
3. `await adapter.set_position(placement.position, placement.heading_deg)`.
4. Read the state back and return it.

Gating: `can_set_position` undeclared → **501** with the adapter's reason (and
`can_set_aircraft_state` likewise when there is a setup to write). A leg whose `is_positionable`
is false → **422** carrying `unpositionable_reason` verbatim. `preview` needs neither capability
— staging is navdata and arithmetic, and it works against an adapter that cannot reposition at
all.

### 3.4 `core/` needed no addition after all

This design originally specified holding geometry here, and it was written. It was then
**deleted**: PR #64 landed `feature/placement-geodesy` on `dev` in parallel, with a far more
complete treatment of the same ground — `hold_placement`, `hold_entry_placement`,
`holding_pattern_point`, `procedure_leg_placement`, `procedure_placement`, `positionable_legs`,
`turn_radius_nm` and `true_from_magnetic`. Keeping a second, smaller implementation of the same
thing would have been the worst outcome available, so the merge took `dev`'s wholesale and the
router was rewritten against it. That closes the last bullet of **#6** without this branch
contributing to it.

Two of `dev`'s decisions changed the router's behaviour and are worth stating, because they are
better than what was specified here:

- **A published speed is a ceiling, not a target.** A hold placarded at 210 kt or a STAR leg at
  250 kt is a restriction the aircraft must stay under, and flying the placard would put a
  category A trainer a hundred knots over its manoeuvring speed. `_constrained_ias_kt` starts
  from the aircraft's own category speed and lets the chart only *clamp* it — never below the
  category's threshold speed, so a mis-parsed restriction cannot hand an aeroplane a stall.
  The preview's notes therefore read "Published speed restriction: at or below 210 kt", not
  "210 kt — the hold's published speed".
- **A leg's heading comes from its neighbours.** An ARINC outbound course is magnetic, so the
  router passes `procedure_leg_placement` the previous and next *positionable* fixes and lets it
  derive a true heading from the geometry.

**Magnetic versus true remains the trap.** `Hold.inbound_course_mag_deg` is magnetic and
`core/geodesy.py` is true throughout, and this project deliberately carries no world magnetic
model. `hold_placement` therefore requires a `magnetic_variation_deg`, and
`server/position_routes.py` supplies the airport's published one — adding a note saying so, or,
when the airport publishes none, passing zero and saying *that* in the notes instead. Guessing
silently is the one thing that must not happen.

`core.geodesy` raises `ValueError` when the published data cannot answer a request — a leg with
no altitude constraint and no altitude given. The router maps that to **422** with the module's
own sentence: the request is well formed, the data cannot answer it.

### 3.5 Tests — all in CI, no simulator

- `tests/server/conftest.py` builds a hand-written world: airport `ZZZZ` (the ICAO code reserved
  for "no code assigned", so it can never collide with a real one), runway 36 on a **true bearing
  of 000°** so pattern geometry reads by eye, its reciprocal 18, an ILS, a gate, a fix, a
  published hold, and a SID with one `CA` leg, one `TF` leg carrying constraints and one `TF` leg
  carrying none. **No navdata file is committed** (hard rule 4).
- `tests/core/test_hold_geodesy.py` — the three sectors tile the compass exactly once, every
  boundary is asserted explicitly, and left-hand is verified to be the mirror of right-hand.
- `tests/server/test_navdata_routes.py` — every route, plus 404-vs-503 and the `/near` shadowing.
- `tests/server/test_position_routes.py` — the numeric reference (3° at 10 NM over a 1,000 ft
  threshold is **4184.4 ft**, i.e. 318.44 ft/NM), `preview` proven side-effect-free, and the
  apply order asserted by **recording the calls** on a subclassed fake rather than by inspecting
  the response, because a response that looks right is exactly what the buggy order produced.

`tests/adapters/test_contract.py` is **not** extended: no new capability is introduced.

### 3.6 The client

`npm run generate:api` regenerates `ui/src/api/schema.d.ts` from the running server. Nothing in
`ui/` hand-writes an API shape.

---

## 4. Phase B — the panel (issue #10) — IMPLEMENTED

### 4.1 Shell

`App.tsx` becomes a two-column workspace: the Position panel takes roughly two thirds, with
Telemetry and Capabilities stacked beside it and reflowing underneath below ~900 px. The panel is
the first thing on the page, because it is the reason the page exists.

### 4.2 Structure, top to bottom

**1 — Airport bar.** A combobox, 250 ms debounce, over `GET /navdata/airports?q=`. Result
rows: ICAO in mono, name, longest runway, a 6 px dot when `has_procedures`. Before any typing it
lists the last five airports used (client state). The selection shows elevation and the AIRAC
cycle from `status`. `⌘K` / `Ctrl-K` focuses it, and the hint is visible, not folklore.

**2 — Runway selector.** One button per runway **end** — 18L and 36R are two buttons, because a
placement is always relative to one end. Each shows length, surface, and an ILS badge (frequency,
course, glidepath) when `…/ils` returns one.

**3 — Placement tabs**, each enabled only when its data exists:

- **Pattern & final** (default) — the spatial grid, reworked. An SVG runway sits in the middle;
  upwind, crosswind, downwind and base tiles for **both** circuit directions sit where they
  actually are relative to it; and a *finals rail* runs down the approach side with chips for
  `20 · 15 · 10 · 8 · 5 · 3 NM · Short`, each showing the glidepath altitude it resolves to.
  Tapping any of them stages it.
- **Procedures** — SID / STAR / Approach lists from `ProcedureSummary` (ident, transition,
  runways served, `positionable_leg_count` / `leg_count`). Selecting one loads its legs into a
  dense table: sequence, path terminator, fix (mono), altitude and speed constraints rendered
  from their `.display` properties. Positionable legs are tappable rows; the rest render
  **visible but disabled with `unpositionable_reason` inline** — issue #10 asks for exactly this,
  and it is why the reason string is computed server-side.
- **Gates & stands** — the parking list, filterable by `ParkingKind` and searchable by name.
- **Coordinate, waypoint & holds** — a lat/lon/altitude/heading form, a waypoint-ident search,
  and the published holds for the selected airport or fix.

**4 — Staging bar** (persistent, bottom, the hero of the surface). Appears the moment something
is staged:

- left: the SVG schematic drawn from `PlacementSchematic` — runway, centreline, the placement dot
  with its heading vector, the glidepath wedge and distance labels;
- right: the editable numbers — altitude ft, IAS kt, gear, flaps — pre-filled from
  `preview.setup`, each with its `notes` provenance underneath in tertiary text;
- one solid primary button, **Place aircraft**. It is the only solid button on the surface.

Edits re-run `preview` (debounced 300 ms) so the schematic and the notes stay truthful. Commit
posts to `/position/apply`; success flashes the bar for ≤ 300 ms and shows the resulting
altitude/speed from `PlacementResult.state`. Failures render **inline in the bar** — never a
modal, which is failure mode 5 of the incumbent.

### 4.3 Gating

Two gates, and both **fail closed** on a fetch error, exactly as
`ui/src/features/aircraft/controls.ts` already does for controls:

- `GET /api/capabilities` → no `can_set_position`: the panel renders, disabled, with the
  adapter's reason. It never posts and never catches. Note that `preview` still works, so the
  panel can stay explorable while only the commit button is dead.
- `GET /api/navdata/status` → anything but `ready` replaces the panel body with a status card:
  `building` shows a progress bar from `IndexProgress` (stage, fraction, detail) and polls;
  `unavailable` / `error` show `reason` and a **Build index** button hitting `POST /navdata/index`.

### 4.4 State — Redux Toolkit only

- `instructorApi` gains the endpoints above. New tags: `NavdataStatus`, `Airport`, `Runways`,
  `Parking`, `Procedures`. `applyPlacement` invalidates `AircraftState`.
- `ui/src/features/position/positionSlice.ts` holds **client state only**: selected ICAO,
  selected runway ident, active tab, the staged `PlacementRequest`, the user's setup overrides,
  and recent airports. Server data never lands here.
- Components under `ui/src/features/position/`: `PositionPanel`, `AirportSearch`,
  `RunwaySelector`, `PatternGrid`, `ProcedureList` (the leg table lives inside it), `ParkingList`,
  `CoordinateForm` (coordinate, waypoint and holds), `StagingBar`, `Schematic`.
- The pure logic sits in four files with no React in them at all, which is what makes it testable
  without rendering: `gate.ts` (both gates), `projection.ts` (fitting the runway frame into the
  viewBox), `placements.ts` (the tile catalogue and formatters) and `errors.ts`. The split is not
  only taste — `react-refresh/only-export-components` fails the lint when a component file also
  exports a function.

### 4.5 Visual system

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
- Status as 6 px dots, not badges. Sentence-case headers. Ghost buttons in toolbars.
- Touch targets ≥ 44 px — where density and the tablet disagree, the tablet wins.
- Micro-motion only: 80 ms row hover, ≤ 300 ms commit flash. No scroll reveals.
- No pie, donut or 3-D chart anywhere. The only graphic is the schematic.

### 4.6 Tests (vitest) — 45 new

- `gate.test.ts` — both gates, with the loading and unreachable cases asserted explicitly,
  because those are the ones that turn hard rule 3 from a claim into a property.
- `projection.test.ts` — the runway always in frame, the minimum span, and **no shearing**: a
  square 4 NM box must project square, or the diagram stops answering "how far out".
- `positionSlice.test.ts` — mostly about *clearing*. A staged placement that survives a change of
  airport is the dangerous bug here: the bar would still show a plausible diagram and the button
  would place the student at the previous field.
- `StagingBar.test.tsx` — renders against a stubbed `fetch` (not mocked hooks, so the request
  bodies are observable). Asserts that staging issues a `preview` and **no** `apply`; that the
  edits go up as a sparse overlay; that the confirmation reports the state that came back rather
  than what was asked for; that a 501 renders inline and not as a dialog.
- `errors.test.ts` — the server's `detail` reaches the instructor verbatim.

---

## 5. Delivery

Built as one branch, `feature/position-manager`, rather than the two planned: the panel needs
`schema.d.ts` regenerated from the running Phase-A server, so splitting them would have meant
either a merge in the middle or hand-written API types, and the second is forbidden.

Closes **#9** and **#10**. The last bullet of **#6** was closed on `dev` by PR #64 instead —
see §3.4.

CI is the integration barrier. Nothing here touches `SimAdapter` or `Capabilities`, so this work
is not on the never-parallelise list.

## 6. Verification

```bash
pytest && ruff check . && ruff format --check . && mypy .
cd ui && npm run lint && npm run typecheck && npm test && npm run build
```

Then, against `OIS_ADAPTER=fake OIS_NAVDATA=in_memory` with the Vite dev server, one batched
browser session: airport search → runway → stage a 10 NM final → check the schematic and the
notes → commit → read the applied state back, plus a console check. No live simulator is needed
for either phase; a real-sim smoke is the `sim-validator` agent's job and is not a merge gate.
