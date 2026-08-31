# Instructor Map — design

**Status:** designed, not yet implemented (backend integration). A UI-only interaction
**prototype already exists on `dev`** under `ui/src/features/map/` — it is the starting point
for this design, not something to rewrite. Its own code says so:
`types.mock.ts`'s docstring reads *"PROVISIONAL mock-only view models — replace with generated
schema.d.ts types at backend integration; never import outside this feature"*, and `mock.ts`'s
reads *"Dies at backend integration — the real overlay comes from the user's own navdata."* This
document is that backend integration.

**Issue:** [#19](https://github.com/Santisoutoo/open-instructor-station/issues/19) — Instructor
Map.
**Phase:** 3 — Instructor Map + AI Traffic
([`../roadmap.md`](../roadmap.md#phase-3--instructor-map--ai-traffic)).
**Feature spec:** manager 5 ([`../feature-spec.md`](../feature-spec.md#5-instructor-map)), ⭐⭐⭐⭐⭐.
**Depends on:** the Phase 1 Position Manager (`server/position_routes.py`,
[`position-manager.md`](position-manager.md)) for repositioning, the `NavdataProvider`
(`navdata-provider.md`) for overlays, the existing `/ws/state` push, and — softly, for one chip
only — the Weather Manager (`weather-manager.md`) for METAR display.
**Blocks:** nothing. Manager 13 (AI Traffic) is a parallel Phase 3 track, not a dependent.

The instructor's situational display: the whole exercise at a glance, live aircraft position,
navaids, procedures and runway/ILS geometry over OpenStreetMap tiles, with drag-to-reposition,
click-to-place and a distance-measurement tool.

Binding rules live in [`../../CLAUDE.md`](../../CLAUDE.md); layers in
[`../architecture.md`](../architecture.md). Hard rule 5 (OSM/open tiles only) is already honoured
by the prototype's `useMapLibre.ts` and is not revisited here. This document never relaxes any of
them. Where the Position Manager's as-built record
([`position-manager.md`](position-manager.md)) records a regret, this design takes the lesson —
see D13.

---

## 0. Decisions at a glance

| # | Decision | Where |
|---|---|---|
| D1 | **No `SimAdapter` or `Capabilities` change.** The map reads `GET /api/capabilities`, `WS /ws/state` and `GET /api/navdata/*`, and writes through the existing `POST /api/position/apply`. Every read and write this manager needs already exists. | §4 |
| D2 | **No new `core/` module.** The one new endpoint (§2.1) is a thin wrapper around `core.geodesy.distance_and_bearing`, which already exists and is already tested to reference values. | §6 |
| D3 | **Overlay geometry (runway rectangles, ILS feathers, hold racetracks, procedure polylines) is built client-side** from real navdata models, using the same spherical approximation the prototype's `measure.ts` already uses for drawing. Exact WGS84 geodesy is reserved for the measurement tool's *settled* reading and for the reposition *write*, never for decoration. | §6, §7.4 |
| D4 | **Two independent data-loading strategies.** Points and lines near the current viewport (airports, navaids, fixes, runways/ILS) are fetched **viewport-driven**, debounced and zoom-gated. Procedures (SID/STAR/approach) are **reference-airport-driven** — a picker, not a viewport query — because an airport can publish 100+ of them and drawing all of them unasked is noise, not situational awareness. | §7.5, §7.6 |
| D5 | **Reposition reuses the Phase 1 pipeline unchanged, through two commit paths, never a third write path.** Both drag and click stage a `CoordinatePlacementRequest`; the map offers **"Apply here"** (calls the same `POST /api/position/apply` mutation the Position panel already uses) and **"Send to Position tab"** (the existing hand-off, for full setup editing). Nothing new is written to the simulator from this manager's own code. | §2, §7.7 |
| D6 | **A staged reposition defaults its altitude, heading and IAS from the aircraft's own last telemetry frame**, not from zero. This is the feature-spec's own words: *"a dragged aircraft arrives configured rather than dropped."* A bare `0/0/0` coordinate is only what an instructor gets before any telemetry has arrived at all. | §7.7 |
| D7 | **A coordinate placement needs no navdata and never 503s** — an existing Position Manager property (`_local_ground_elevation_ft` degrades to sea level when the index is unusable). Consequence: this manager's reposition path works even before the user has built a navdata index; only the **overlay layers** gate on `NavdataStatus`. | §7.6, §10 |
| D8 | **Capability gating for reposition is imported, not reimplemented.** `commitGate` from `features/position/gate.ts` gates the drag handle and both commit buttons — `can_set_position` **and** `can_set_aircraft_state`, exactly as Position requires them. | §7.7 |
| D9 | **The measure tool shows the fast client-side (spherical) reading live while dragging a point, then replaces it with the exact server-side WGS84 reading once both points are settled.** This reconciles the feature-spec's *"the same geodesic solver as the placements"* requirement with a responsive drag interaction — a round trip on every mouse-move would be laggy, a spherical approximation as the final answer would contradict the spec. | §2.1, §7.4 |
| D10 | **METAR is a formatted view of the *commanded* `WeatherState` (Weather Manager, Phase 2), not a live internet fetch.** No new external dependency, no new "is it OK to call the internet" question. It is **absent**, not merely disabled, until the Weather Manager's `GET /api/weather` exists, and disabled with a reason when `can_set_weather` is false thereafter. | §1.2, §7.9 |
| D11 | **Taxiways are out of scope.** `apt.dat` rows `110`–`116` are deliberately not parsed by the `NavdataProvider` — a stated performance decision in its own design (`navdata-provider.md`: *"90% of apt.dat is taxiway and pavement geometry ... that this project never reads"*). There is no data to draw. Recorded as a follow-up requiring a `NavdataProvider` parsing extension — a navdata schema change, never parallelised. | §1.2, §10 |
| D12 | **AI traffic and the TCAS picture belong to manager 13, not this one.** The map's layer registry reserves a `traffic` key so manager 13 can add rendering later by adding files, not by editing this manager's. Nothing here spawns, moves or renders a second target. | §1.2, §7.3 |
| D13 | **New RTK Query endpoints are added via `injectEndpoints` in a new `ui/src/features/map/mapApi.ts`, not by editing `instructorApi.ts` directly.** This is the Position Manager's own recorded regret (`weather-manager.md`'s D15: *"the rule the Position panel broke"*) taken as a lesson: adding this manager adds files. | §7.2 |
| D14 | **The existing prototype's file layout, slice and pure `measure.ts` survive.** This design lists exactly which files change and which are added; nothing already on `dev` is rewritten wholesale. | §7 |
| D15 | **Pure decision logic is factored out of the imperative MapLibre hooks and unit-tested directly**, independent of whether the jsdom `maplibre-gl` stub actually fires an event — today it does not (`Map.on()`/`Marker` methods are no-ops). The stub gets a small, explicit extension to exercise drag/click wiring where that wiring itself needs a test. | §7.7, §8 |

---

## 1. Scope

### 1.1 What this manager does

1. **Show the live aircraft** — position, track (a short trail) and heading, driven by the
   existing `WS /ws/state` feed, at whatever rate that stream already runs (~4 Hz,
   `server/app.py::STATE_STREAM_INTERVAL_S`, unchanged).
2. **Show the world around it** — runways, ILS localizer/glideslope geometry, navaids, waypoints
   (fixes), and the SIDs/STARs/approaches of a chosen reference airport, all read from the
   `NavdataProvider` through endpoints that already exist.
3. **Show a formatted METAR chip** for the reference airport, derived from the Weather Manager's
   commanded `WeatherState` — soft dependency, D10.
4. **Reposition the aircraft from the map** — drag the aircraft marker, or click a point in
   "reposition" mode — through the **same** placement pipeline the Position Manager already
   ships (`POST /api/position/apply`, a `coordinate` request), never a parallel path.
5. **Measure distance and bearing** between two tapped points, with the exact answer computed
   the same way a placement's geometry is (`core.geodesy`).
6. **Pan, zoom, and follow the aircraft**, already built in the prototype.

It covers the "Real-time display" and "Interaction" bullets of
[`feature-spec.md`](../feature-spec.md#5-instructor-map) manager 5, **except** taxiways (D11) and
AI traffic / TCAS (D12). It sits in **Phase 3** and serves roadmap exit criteria 1 and 2 directly
(criteria 3 and 4 belong to manager 13's traffic work, not this design).

### 1.2 What is explicitly out of scope

| Out of scope | Owner / reason |
|---|---|
| Taxiway geometry | D11 — the navdata layer does not parse it. A future `NavdataProvider` extension, scoped separately. |
| AI traffic, ground vehicles, birds, TCAS resolution advisories | Manager 13. `can_spawn_traffic` and the traffic stream shape are its contract change, made once, alone, before this design's `traffic` layer key is filled in. |
| Pushback and camera controls | Managers 8 and 10 — grouped with this manager in the roadmap phase, designed separately. |
| A live, real-world METAR feed from the internet | Not designed here. D10 makes the map's METAR a *derived display* of the commanded weather instead — see §10 for the open question if a real feed is later wanted. |
| Editing the *staged setup* (altitude, heading, IAS, flaps, …) from the map | The Position panel's staging bar already does this in full; "Send to Position tab" is the map's door into it (D5). The map's own "Apply here" only ever carries the coordinate-derived defaults of D6. |
| Any new `SimAdapter` method or capability flag | D1. |
| Holding-pattern *placement* (choosing a hold as a position) | Already the Position Manager's (`HoldPlacementRequest`). This manager may *draw* a published hold (§7.4) but never places on one. |

---

## 2. REST endpoints

### 2.1 The one new endpoint

```
GET /api/geodesy/measure?lat1=&lon1=&lat2=&lon2=  -> MeasureResult
```

New file `server/geodesy_routes.py`, included once in `server/app.py`
(`app.include_router(geodesy_routes.router)`) — the only shared-file edit this manager needs on
the backend, matching the precedent `weather-manager.md`'s D15 set for itself.

| Method | Path | Purpose | Safe? | Capability | Declared |
|---|---|---|---|---|---|
| `GET` | `/api/geodesy/measure` | The exact WGS84 distance and initial true bearing between two points | yes | none — pure arithmetic, no adapter, no navdata | `def` — Starlette's threadpool; there is nothing to await |

Request: four required query floats, `lat1`/`lon1`/`lat2`/`lon2`, `Query(ge=-90/le=90)` and
`Query(ge=-180/le=180)` respectively — the same bounds `GeoPosition` already enforces. No body: a
`GET` with scalar params, matching `/api/navdata/airports/near`'s convention rather than
inventing a `POST` for a side-effect-free read.

Response:

```python
class MeasureResult(BaseModel):
    distance_nm: float
    initial_bearing_true_deg: float = Field(ge=0.0, lt=360.0)
```

Implementation is exactly:

```python
a = GeoPosition(latitude=lat1, longitude=lon1)
b = GeoPosition(latitude=lat2, longitude=lon2)
distance_nm, bearing_deg = distance_and_bearing(a, b)
return MeasureResult(distance_nm=distance_nm, initial_bearing_true_deg=bearing_deg)
```

Error cases: only FastAPI's own `422` for out-of-range coordinates. There is no 404, no 503 (no
navdata involved), no 501 (no capability involved) — this is the simplest endpoint in the
project, deliberately.

### 2.2 Endpoints reused verbatim, no change

Everything else this manager needs already exists and is unchanged by this design:

| Method | Path | Used for |
|---|---|---|
| `GET` | `/api/capabilities` | gating the drag handle and both reposition commit paths (D8) |
| `WS` | `/ws/state` | the live aircraft marker and trail |
| `GET` | `/api/navdata/status` | gating the overlay layers only (D7) |
| `GET` | `/api/navdata/airports/near` | viewport-driven airport points |
| `GET` | `/api/navdata/airports/{icao}/runways` | runway rectangles **and** ILS geometry (`Runway.ils`) for the reference airport, or any airport in view once selected |
| `GET` | `/api/navdata/navaids` (near form) | viewport-driven navaid points |
| `GET` | `/api/navdata/fixes` (near form) | viewport-driven waypoint points |
| `GET` | `/api/navdata/airports/{icao}/procedures` | the SID/STAR/approach picker for the reference airport |
| `GET` | `/api/navdata/airports/{icao}/procedures/{kind}/{ident}` | the legs of a toggled-on procedure, drawn as a polyline |
| `GET` | `/api/navdata/holds` | published holds near/at the reference airport (optional first pass, §7.4) |
| `POST` | `/api/position/apply` | committing a drag or click reposition (D5) |
| `GET` | `/api/weather` *(Weather Manager, soft dependency)* | the METAR chip's source data (D10) |

**No endpoint is duplicated under a `/api/map/` prefix.** Runway, navaid, fix and procedure
lookups belong to `/api/navdata/`; position writes belong to `/api/position/`. This mirrors
`position-manager.md`'s own §6.4 rule.

---

## 3. Pydantic models

### 3.0 New

Only one, in `server/geodesy_routes.py`:

```python
class MeasureResult(BaseModel):
    """The exact geodesic answer between two points, WGS84."""

    distance_nm: float = Field(description="Geodesic distance, nautical miles.")
    initial_bearing_true_deg: float = Field(
        ge=0.0, lt=360.0, description="Initial true bearing from point 1 to point 2, degrees."
    )
```

Units follow the project-wide convention (`_nm`, `_deg` true unless suffixed `_mag_deg`) — same
rule `position-manager.md` §7 states and this document does not repeat.

### 3.1 Reused, unchanged

| Model | Module | Used as |
|---|---|---|
| `AircraftState` | `core.models` | the live telemetry frame (WS), and the source of a staged reposition's default altitude/heading/IAS (D6) |
| `GeoPosition` | `core.models` | every coordinate on the wire |
| `Capabilities` | `core.sim_adapter` | reposition gating (D8) |
| `NavdataStatus` | `core.navdata.models` | overlay gating (D7) |
| `AirportSummary`, `Airport` | `core.navdata.models` | viewport airport points, reference-airport picker |
| `Runway`, `Ils` | `core.models` | runway rectangles and ILS feathers |
| `Navaid` | `core.navdata.models` | navaid points |
| `Fix`, `Waypoint` | `core.navdata.models` | waypoint points |
| `Procedure`, `ProcedureSummary`, `ProcedureLeg`, `ProcedureKind` | `core.navdata.models` | the procedure picker and its polylines |
| `Hold` | `core.navdata.models` | published-hold racetracks (optional first pass) |
| `CoordinatePlacementRequest`, `PlacementRequest`, `ApplyPlacementRequest`, `PlacementResult` | `server.position_routes` | the reposition write (D5) |
| `WeatherState` | `core.weather.models` | the METAR chip's source (D10, soft dependency) |

**Nothing in this manager introduces a new response envelope beyond `MeasureResult`.** Every
overlay is drawn from a model that already has a public HTTP surface.

---

## 4. `SimAdapter` / `Capabilities` additions

**None.** This is a positive finding, exactly as `position-manager.md` §11 recorded for itself:

- The map's reposition write is `POST /api/position/apply`, which already calls
  `adapter.apply_setup()` then `adapter.set_position()` — the two methods the Phase 1 pipeline
  needs, unchanged.
- The map's live picture is the existing `adapter.stream_state()` fan-out over `/ws/state`,
  already serving multiple connected clients (a tablet running the Map tab and a desktop running
  the Position tab at once is already the normal case, per `architecture.md`'s "Request and
  stream paths" section).
- Gating reads `can_set_position` and `can_set_aircraft_state`, both already declared by every
  adapter (`FakeSimAdapter` included).

**No contract test is added** to `tests/adapters/test_contract.py`. This section's rule bites the
other way here: since nothing is added to the contract, there is nothing new for the suite to
cover — the existing `set_position`/`apply_setup` contract tests already prove the property this
manager depends on.

**Consequence for scheduling:** the "never parallelise a contract change" rule does not bind this
manager. Every track in §9 can start immediately.

---

## 5. Dataref mapping (X-Plane)

**None.** This manager adds no dataref, touches no file under `adapters/xplane/`, and needs no
mode precondition. It reaches the simulator exclusively through endpoints the Position Manager
and the WebSocket state pump already expose (D1).

This is also why MSFS needs no note here: the map is adapter-agnostic by construction, exactly as
`feature-spec.md` states for it — *"The map never queries the simulator directly."* Whatever
`adapters/msfs/` declares for `can_set_position` / `can_set_aircraft_state` in Phase 5, the map's
behaviour (offer or disable the reposition tools) follows automatically from the same capability
gate every other panel already uses. Nothing here would need to change to support a second
simulator, which is exactly Phase 5's own measure of success.

---

## 6. `core/` logic

**No new module.** The map's one exact-geodesy need (§2.1) is served entirely by
`core.geodesy.distance_and_bearing(a: GeoPosition, b: GeoPosition) -> tuple[float, float]`, which
already exists, is already imported by `server/position_routes.py`, and is already covered by
`tests/core/test_geodesy.py` to known reference values (round-trip tests at 0.5/10/250 NM, every
30–45° of bearing, `abs=1e-6` NM).

Decorative overlay geometry — runway rectangles, ILS feathers, hold racetracks, procedure
polylines — is deliberately **not** `core/` logic (D3). It draws no conclusion an instructor acts
on the way a placement's altitude does; it exists to look right on a map. Building it in `core/`
would mean adding a GeoJSON dependency and a geometry module to the sim-agnostic layer for a
concern that is purely presentational, and the existing prototype's `measure.ts` already states
the applicable rule in its own docstring: *"Anything that must be exact goes through the server's
geodesy, never through this file."* This design keeps that boundary and extends its scope from
"the prototype's mock airport" to "any airport the navdata provider returns."

**Design for the Fake first, restated for this manager.** Every read this manager performs
resolves against `FakeSimAdapter` (for `AircraftState`/`Capabilities`) and either the in-memory
or the fixture `NavdataProvider` (for overlays) — nothing here requires a live simulator to
exercise in CI, and the one write path is the same `apply`/`preview` pair already proven against
the Fake.

---

## 7. UI panel outline

### 7.1 What already exists (starting point, D14)

| File | Role | Change needed |
|---|---|---|
| `ui/src/components/tabs.ts` | registers the `map` tab, `keepMounted: true` | none |
| `ui/src/features/map/MapPanel.tsx` | layout, layer toggles, tool buttons | extend: capability gating on the reposition tool + drag handle, METAR chip mount point, procedure picker mount point |
| `ui/src/features/map/mapSlice.ts` | client-only chrome state | extend, §7.2 |
| `ui/src/features/map/useMapLibre.ts` | the MapLibre instance lifecycle, the OSM style | none |
| `ui/src/features/map/useMapOverlays.ts` | pushes GeoJSON into MapLibre sources | rewire from `MOCK_AIRPORT` to real data, §7.6 |
| `ui/src/features/map/useAircraftMarker.ts` | the live aircraft glyph, follow camera, trail | extend: draggable + `dragend`, §7.7 |
| `ui/src/features/map/useMapInteractions.ts` | click → measure/reposition dispatch | unchanged in shape; factor the click decision into a pure function, §7.7/D15 |
| `ui/src/features/map/MapStagingBar.tsx` | the bar under a staged reposition | extend: "Apply here", default computation, §7.7 |
| `ui/src/features/map/measure.ts` | spherical geodesy, pure functions | unchanged — stays the *live* readout, D9 |
| `ui/src/features/map/mock.ts`, `types.mock.ts` | the demo-fixture overlay | retained **only** as a test/offline fallback, no longer the production data source, §7.6 |
| `ui/src/test/maplibreStub.ts` | jsdom stand-in for `maplibre-gl` | small extension, §7.7/D15/§8 |

### 7.2 New: `ui/src/features/map/mapApi.ts` (D13)

```ts
export const mapApi = instructorApi.injectEndpoints({
  endpoints: (builder) => ({
    getAirportsNear: builder.query<
      AirportSummary[],
      { lat: number; lon: number; radiusNm: number; limit?: number }
    >({
      query: ({ lat, lon, radiusNm, limit = 30 }) => ({
        url: 'navdata/airports/near',
        params: { lat, lon, radius_nm: radiusNm, limit },
      }),
    }),
    getNavaidsNear: builder.query<
      Navaid[],
      { lat: number; lon: number; radiusNm: number; kinds?: NavaidKind[]; limit?: number }
    >({
      query: ({ lat, lon, radiusNm, kinds, limit = 100 }) => ({
        url: 'navdata/navaids',
        params: { lat, lon, radius_nm: radiusNm, limit, ...(kinds ? { kinds } : {}) },
      }),
    }),
    getFixesNear: builder.query<
      Fix[],
      { lat: number; lon: number; radiusNm: number; limit?: number }
    >({
      query: ({ lat, lon, radiusNm, limit = 150 }) => ({
        url: 'navdata/fixes',
        params: { lat, lon, radius_nm: radiusNm, limit },
      }),
    }),
    measureGeodesic: builder.query<MeasureResult, { a: LatLon; b: LatLon }>({
      query: ({ a, b }) => ({
        url: 'geodesy/measure',
        params: { lat1: a.lat, lon1: a.lon, lat2: b.lat, lon2: b.lon },
      }),
    }),
  }),
});

export const {
  useGetAirportsNearQuery,
  useGetNavaidsNearQuery,
  useGetFixesNearQuery,
  useMeasureGeodesicQuery,
} = mapApi;
```

`kinds` must serialize as **repeated** query keys (`kinds=vor&kinds=ndb`), matching FastAPI's
`Annotated[list[NavaidKind] | None, Query()]` on the server. Flagged in §10 as an implementation
detail worth a unit test on the query builder itself, not assumed.

`getRunways`, `getProcedures`, `getProcedure` are **not** re-declared here — they already exist
on `instructorApi` and this manager imports those hooks directly.

### 7.3 `mapSlice.ts` — additive changes only

```ts
export type MapLayerKey =
  | 'runways'
  | 'ils'
  | 'navaids'
  | 'waypoints'   // new
  | 'procedures'  // new
  | 'metar'       // new
  | 'traffic'     // new — reserved for manager 13, unused here (D12)
  | 'trail';

export interface MapState {
  // ...unchanged fields (layers, follow, mode, measureA/B, staged, trail)...

  /** The airport whose procedures are offered in the left rail, or `null`. */
  referenceIcao: string | null;
  /** Which procedures are toggled ON for drawing. Several may be shown at once. */
  openProcedures: { kind: ProcedureKind; ident: string; transition: string | null }[];
}
```

Two new reducers, `referenceAirportSelected` and `procedureLayerToggled`. Everything else in the
slice — `mode`, `measureA`/`measureB`, `staged`, `trail` — is untouched: the docstring's own rule
("what the map chrome needs to survive a tab switch") still applies. The **viewport** (map centre
and zoom, used to drive §7.6) is deliberately **not** added to the slice — it is local hook
state, not global state, exactly as the MapLibre instance itself is (`useMapLibre`'s own
docstring: "never mirrored into Redux"). It does not need Redux's cross-component visibility, and
putting a value that changes on every frame of a pan into the store would mean every connected
selector re-runs on every pan pixel.

### 7.4 New: `ui/src/features/map/overlays.ts` — real-navdata geometry builders

Generalises what `mock.ts` prototyped, now fed by real models instead of a hand-written fixture:

```ts
export function runwayFeature(runway: Runway): Feature<Polygon, RunwayProperties>;
export function ilsFeature(runway: Runway): Feature<LineString, IlsProperties> | null; // null when runway.ils is null
export function navaidFeature(navaid: Navaid): Feature<Point, NavaidProperties>;
export function fixFeature(fix: Fix): Feature<Point, FixProperties>;
export function procedureLineFeature(procedure: Procedure): Feature<LineString, ProcedureProperties>;
export function holdFeature(hold: Hold): Feature<LineString, HoldProperties>;
```

All pure functions, all built on `destinationPoint`/`distanceNm` from the existing `measure.ts` —
no new geodesy, per D3. Notes on the two least-trivial builders:

- **`ilsFeature`** draws the feather from `runway.ils.localizer_position` back along the
  reciprocal of `localizer_true_deg` (the approach course), for a fixed nominal length
  (`ILS_FEATHER_LENGTH_NM = 10`, matching typical localizer service volume) and a half-angle from
  `localizer_width_deg` when published, else a nominal `2.5°`. This is a direct generalisation of
  the prototype's `mock.ts::ilsFeature`, which hard-coded exactly this shape for one fixture
  airport.
- **`procedureLineFeature`** connects the `position` of every leg whose `fix` is not `null`, in
  `sequence` order. **A trajectory-dependent leg (`CA`/`VA`/`FM`/`VM`, no fix) breaks the line
  rather than inventing a point for it** — the same "displayed, never guessed at" discipline
  `architecture.md`'s risk 4 states for placements, applied here to drawing. The gap is visible on
  the map, which is honest: an instructor reading a SID with a climbing turn sees the line stop
  and resume, not a straight segment across airspace the aircraft will not actually fly straight
  through.
- **`holdFeature`** uses `hold.inbound_course_mag_deg` **unconverted** — the same graceful
  degradation `position-manager.md` §10.3 chose for the *placement* case (D11 there, reversed):
  this project carries no world magnetic model, and a decorative racetrack a few degrees off true
  is a cosmetic problem, not a safety one, on a manager whose actual placements are computed
  server-side with the correct precedent. Flagged again in §10 because it is the one overlay type
  that inherits a known imprecision.

### 7.5 New: `ui/src/features/map/useOverlayData.ts` — viewport-driven fetching

```ts
export function useOverlayData(map: MapLibreMap | null): OverlayData;

interface OverlayData {
  runways: Runway[];
  navaids: Navaid[];
  fixes: Fix[];
  airports: AirportSummary[];
}
```

Behaviour:

1. Tracks the map's centre and zoom in **local `useState`**, updated on a debounced `moveend`
   (~400 ms) — not on every `move` frame, and not in Redux (§7.3).
2. At `zoom ≥ AIRPORT_MIN_ZOOM` (constant, first guess `9`), calls `getAirportsNear` with a
   radius derived from the current viewport's diagonal.
3. For every airport returned, **and** at `zoom ≥ RUNWAY_MIN_ZOOM` (first guess `10`), calls the
   existing `useGetRunwaysQuery(icao)` — which already carries `.ils` (confirmed in
   `navdata-provider.md` §5.3: *"the single most important placement ... needs threshold,
   bearing, elevation, ILS frequency and OBS course together"*), so **no separate ILS fetch is
   needed**.
4. At the same airport-visible threshold, calls `getNavaidsNear` and, at a **higher** zoom
   (`FIXES_MIN_ZOOM`, first guess `11`), `getFixesNear` — fixes are far denser than navaids
   (`earth_fix.dat` versus `earth_nav.dat`), and drawing them at a continental zoom would be a
   starfield, not situational awareness.
5. Every query result caches in RTK Query's own store keyed on its params; panning back over
   already-seen ground re-uses the cache instead of re-fetching.

This hook, `useMapOverlays` (§7.6) and `overlays.ts` are the only places that know these
thresholds and radii exist — the panel component does not.

### 7.6 `useMapOverlays.ts` — rewired, gated on `NavdataStatus`

Replaces the hard-coded `MOCK_AIRPORT` source with `useOverlayData`'s live result, converted
through `overlays.ts`. Gates on the existing `GET /api/navdata/status`:

- `state !== "ready"` (`unavailable` / `building` / `error`): the overlay sources are set to
  empty `FeatureCollection`s and the panel shows the same kind of status card the Position panel
  already renders for this state (`navdataGate` from `features/position/gate.ts`, **imported**,
  not duplicated — mirroring D8's reuse of `commitGate`).
- `state === "ready"`: real data flows.

**The reposition path is not gated on this** (D7) — dragging or clicking the aircraft works
before the index is ever built, because a `coordinate` placement needs no navdata at all. Only
the decorative layers wait on it.

`mock.ts`/`types.mock.ts` are retained, unexported outside the feature, as the fixture used by
`MapPanel.test.tsx` and any Storybook-style isolated rendering — never imported by the production
data path once `useOverlayData` exists.

### 7.7 Reposition: drag, click, defaults, and the two commit paths

**New: `ui/src/features/map/reposition.ts`** — pure functions, unit-tested directly (D15):

```ts
/** What a staged map point resolves to before the instructor commits it. */
export function defaultCoordinateRequest(
  point: LatLon,
  telemetry: AircraftState | null,
): CoordinatePlacementRequest {
  return {
    type: 'coordinate',
    position: {
      latitude: point.lat,
      longitude: point.lon,
      altitude_ft: telemetry?.altitude_ft ?? 0,
    },
    heading_deg: telemetry?.heading_deg ?? null,
    ias_kt: telemetry?.ias_kt ?? null,
  };
}
```

D6's rule, made concrete: a drag or click carries the aircraft's **current** altitude, heading
and IAS onto the new point by default, so sliding an aircraft sideways on the map preserves the
flight it is already in. `null` for heading/IAS (no telemetry yet) is exactly what
`CoordinatePlacementRequest` already accepts and what the server already resolves sensibly (a
default heading of 0°, `GROUND_IAS_KT` with a stall-speed note if the result reads as airborne —
the existing Position pipeline's own behaviour, reused verbatim).

**`useAircraftMarker.ts` — extended:**

- `new Marker({ element, rotationAlignment: 'map', pitchAlignment: 'map', draggable: gate.open })`
  where `gate` is `commitGate(capabilities, isError)` **imported from
  `features/position/gate.ts`** (D8) — the marker is simply not draggable on an adapter that
  cannot reposition, hard rule 3 applied at the DOM level.
- `marker.on('dragend', () => dispatch(repositionStaged(marker.getLngLat())))` — reuses the
  **existing** `repositionStaged` action from `mapSlice`, unchanged. `MapPanel.tsx` already
  renders `MapStagingBar` whenever `staged !== null`, **independent of the armed tool `mode`**
  (confirmed in the current code — the render condition has no `mode` check), so a drag does not
  need to first arm "reposition" mode. This keeps drag and the click-to-place tool as the two
  independent gestures the feature spec lists them as.

**`MapStagingBar.tsx` — extended:**

Adds an "Apply here" primary action, alongside the existing "Send to Position tab" and "Discard":

```tsx
const [applyPlacement, applyState] = useApplyPlacementMutation();
const telemetry = useAppSelector((state) => state.telemetry.latest);
const capabilities = useGetCapabilitiesQuery();
const gate = commitGate(capabilities.data, capabilities.isError);

// "Apply here"
onClick={() => {
  applyPlacement({ placement: defaultCoordinateRequest(staged, telemetry), setup: null });
}}
disabled={!gate.open}
```

- **"Apply here"** commits immediately through `POST /api/position/apply` — the *identical*
  mutation the Position panel's own commit button calls. No new write path exists anywhere in
  this manager (D5).
- **"Send to Position tab"** is the prototype's existing hand-off, unchanged, for an instructor
  who wants to edit the altitude/heading/speed/flaps/etc. before committing — the Position
  panel's full staging bar remains the only place that happens.
- A failed apply shows the mutation's error `detail` inline, the same "prose, verbatim" contract
  `position-manager.md` §10.1 already establishes; this manager invents no new error shape.

### 7.8 Measure tool — D9

`measure.ts` is unchanged: `distanceNm`/`initialBearingDeg` still drive the **live** chip while
`measureA`/`measureB` are being placed, because a value on every mouse-move must not round-trip.
Once both points are set, `MapPanel.tsx` also calls `useMeasureGeodesicQuery({ a: measureA, b:
measureB })` (skipped while either is `null`) and **replaces** the displayed distance/bearing
with the server's answer as soon as it resolves, leaving the spherical value as the instant
placeholder. The two values differ by well under the display's own rounding (`toFixed(1)` NM,
integer degrees) at any distance an instructor is likely to measure inside a training area, so
the swap is not visually jarring — it is a precision upgrade, not a correction the instructor
notices.

### 7.9 METAR chip — D10, soft dependency

**New: `ui/src/features/map/metar.ts`** (pure formatting) and a small `MetarChip` component,
mounted when an airport marker or the reference-airport picker is engaged. Reads
`useGetWeatherQuery()` (from the Weather Manager's own RTK Query surface, once it exists) and
formats the returned `WeatherState` into a compact display string (wind, visibility, cloud base,
QNH, temperature/dewpoint) — explicitly labelled in the UI as derived from the commanded weather,
not a live real-world observation, so an instructor never mistakes a manually-set `CAT III` fog
for what is actually happening outside the window.

**This slice ships only once `GET /api/weather` exists.** If the Weather Manager has not landed
when this manager's implementation starts, `MetarChip` is not rendered at all rather than calling
an endpoint that does not exist — fails closed, same discipline as every other gate in this
project. It is small enough to be its own follow-up PR without blocking §7.1–§7.8.

### 7.10 Tablet-first layout notes

Unchanged from the prototype's existing three-zone chrome (left layer rail, centre canvas, right
tool rail) — already touch-sized (`map-tool` buttons), already `keepMounted` so a tab switch
never re-pays the WebGL/tile cost. The two additions to the right rail (reference-airport picker,
"Apply here"/"Send to Position tab" pair) follow the same button sizing; no new layout primitive
is introduced.

---

## 8. Test plan

### 8.1 `core/` unit tests

**None new.** `core.geodesy.distance_and_bearing` already has a reference-value suite in
`tests/core/test_geodesy.py`; the new endpoint's test (§8.2) cites it rather than duplicating it:
`distance_and_bearing(MADRID, point_at_distance_and_bearing(MADRID, 25.0, 137.0))` already asserts
`(25.0 NM, 137.0°)` to `abs=1e-6`. No `core/` behaviour changes, so no `core/` test changes.

### 8.2 `server/` tests — `tests/server/test_geodesy_routes.py` (new)

- `GET /api/geodesy/measure?lat1=40.4168&lon1=-3.7038&lat2=<25nm@137>` returns `distance_nm ≈
  25.0` and `initial_bearing_true_deg ≈ 137.0`, the same golden pair §8.1 cites — proving the
  route is a faithful wrapper and nothing more.
- Symmetry: swapping the two points returns the reciprocal bearing (mirrors
  `test_distance_is_symmetric` in `core/`).
- Out-of-range latitude (`lat1=91`) is `422`.
- No new tests are needed for `/api/navdata/airports/near`, `/navaids`, `/fixes` or
  `/procedures/*` — they are unchanged, and `tests/server/test_navdata_routes.py` already covers
  them (near-form and ident-form, the dual-query-form `422`, precedence of `/near` over
  `/{icao}`). This manager only adds **callers**, not new server behaviour, for those routes.

### 8.3 Contract suite

**No addition** (§4) — there is no new capability.

### 8.4 `@pytest.mark.sim`

No new sim-marked tests are proposed by this design. The one thing worth a live check is not a
`pytest` concern: whether MapLibre GL's own `Marker({ draggable: true })` correctly suppresses the
underlying map pan-drag while the marker itself is being dragged. That is browser/WebGL behaviour,
not simulator behaviour, and belongs in a manual/live UI smoke check rather than `-m sim` (which
gates on a running X-Plane, not a running browser). Recorded as an open question, §10.

### 8.5 UI unit tests (no maplibre needed)

- `overlays.ts` — one test per builder against a hand-built `Runway`/`Ils`/`Navaid`/`Fix`/
  `Procedure`/`Hold` fixture, asserting the emitted GeoJSON's coordinate count and, for
  `ilsFeature`, that the feather's two outer points sit at the expected bearing ±half-width from
  the localizer using `measure.ts`'s own `initialBearingDeg` as the check (dog-fooding the same
  module that draws it, exactly as the prototype's `mock.ts` already does informally).
- `procedureLineFeature` — asserts a trajectory-only leg (no `fix`) produces a **break**, not an
  interpolated point: the line's coordinate count must equal the count of fix-carrying legs, not
  the total leg count.
- `reposition.ts::defaultCoordinateRequest` — with telemetry present, asserts altitude/heading/IAS
  are carried verbatim from the frame; with `telemetry = null`, asserts `heading_deg`/`ias_kt` are
  `null` and `altitude_ft` is `0`.
- `mapSlice.ts` — extend the existing reducer tests with `referenceAirportSelected` and
  `procedureLayerToggled`, following the file's existing style exactly (already exercised for
  `layerToggled`, `modeSelected`, etc.).
- `mapApi.ts` — a serialization test asserting `kinds` produces **repeated** query keys, not a
  comma-joined string or a JSON array — the concrete risk flagged in §7.2/§10.

### 8.6 UI component tests (jsdom, maplibre stubbed)

Extends the existing `MapPanel.test.tsx` style (chrome and dispatch only, WebGL dormant):

- Capability-gated reposition: with `can_set_position: false`, the "Reposition" tool button is
  disabled and carries the stated reason (mirrors `PositionPanel.test.tsx`'s existing gate
  assertions).
- `MapStagingBar`'s "Apply here" dispatches `useApplyPlacementMutation` with the exact
  `defaultCoordinateRequest` shape, given a preloaded `telemetry.latest` — asserted by inspecting
  the mocked mutation's call args, the same pattern `AircraftControlPanel.test.tsx` already uses
  for `useApplyAircraftSetupMutation`.
- **New: `maplibreStub.ts` gets a small extension** — `Map`/`Marker` `on()` should record
  registered handlers in a map keyed by event name, with a `trigger(event, payload)` test helper,
  so a `dragend`/`click` handler can actually be exercised in jsdom instead of only asserting it
  was *registered*. This is the concrete resolution of D15: today the stub's `on()` is a no-op,
  so `useMapInteractions`' and the new drag handler's *behaviour* (what gets dispatched) is
  currently only provable by extracting it into a pure function and testing that function
  directly (§8.5) plus a live smoke check (§10) — the stub extension closes that gap for CI.

### 8.7 Fixture strategy

No new navdata fixtures — this manager reads through endpoints already exercised by
`tests/server/test_navdata_routes.py` against the existing `tests/fixtures/navdata/` tree
(hand-written, `NavdataProvider`'s own rule, respected unchanged). UI tests use hand-built
in-memory `Runway`/`Navaid`/`Fix`/`Procedure` objects matching the generated types, exactly as
`ProcedureList.test.tsx` and `RunwaySelector.test.tsx` already do — never a copy of real navdata.

---

## 9. Parallelisation

No `SimAdapter`/`Capabilities` change (§4) and no navdata schema change (§1.2's D11 explicitly
defers that) — **nothing in this manager is on the "never parallelise" list**, so every track
below can be dispatched in one message once this design is fixed.

| Track | Owns | Depends on |
|---|---|---|
| **A — backend** | `server/geodesy_routes.py`, its `app.py` include line, `tests/server/test_geodesy_routes.py` | nothing |
| **B — overlays & data plumbing** | `ui/src/features/map/mapApi.ts`, `overlays.ts`, `useOverlayData.ts`, `useMapOverlays.ts` (rewire), the reference-airport/procedure picker component, their tests | Track A only for `MeasureResult`'s generated type (`npm run generate:api` after A merges); the navdata near-endpoints and `getRunways`/`getProcedures`/`getProcedure` already exist today |
| **C — reposition** | `reposition.ts`, `useAircraftMarker.ts` (drag), `MapStagingBar.tsx` ("Apply here"), `gate.ts` re-export, their tests | nothing new — `POST /api/position/apply` already exists |
| **D — measure exactness** | the `measureGeodesic` query wiring in `MapPanel.tsx`, its test | Track A |
| **E — METAR chip** | `metar.ts`, `MetarChip` | the Weather Manager's `GET /api/weather` (external to this manager; can ship as a follow-up PR after Phase 2's Weather Manager lands, without blocking A–D) |
| **F — test infra** | the `maplibreStub.ts` extension (§8.6) | nothing; do this **first and once** — both B and C exercise it, and one file edited by two concurrent branches is friction worth avoiding even though it is not a "never parallelise" rule violation |

**Dispatch:** F first (small, ~20 lines, unblocks the drag/click tests B and C both want), then
A/B/C/D/E in one message as four to five parallel `feature/*` branches in separate git worktrees,
each with its own PR to `dev`. The tester can write §8.2's and §8.5's tests against this design
immediately, without waiting for any implementation, exactly as the parallelisation policy
prescribes for a fixed contract.

**What must not be parallelised inside this manager:** nothing beyond the ordinary "backend and
UI panel proceed in parallel once the contract is fixed" rule — there is no schema, no capability,
and only one shared backend file (`server/app.py`'s one include line), touched once by Track A.

---

## 10. Open questions and risks

1. **Is a formatted-from-`WeatherState` METAR (D10) actually what the feature spec meant, or was
   a live real-world text feed intended?** The Weather Manager's own design explicitly hands
   METAR to this manager and states it "never fetches anything from the internet" for *itself*,
   which reads as permission for this manager to be the one that could — but CLAUDE.md is silent
   on whether the app is allowed to call an external METAR service at all (hard rule 5 only pins
   down map *tiles*). Resolution: a product decision from the user. If a live feed is wanted, it
   is a small, separable addition to §7.9 behind its own capability-free "best effort, offline
   degrades to nothing" contract — not a redesign.
2. **Taxiways (D11) are unbuilt because the data layer does not parse them.** Resolution: a
   scoped follow-up issue against `NavdataProvider` (parsing `apt.dat` rows `110`–`116`), sized
   and prioritised independently, and — per the navdata schema rule — never parallelised with
   other schema work.
3. **The `traffic` layer key (D12) is reserved, not filled.** Manager 13's design needs to state
   the WebSocket message shape for multiple targets (today `/ws/state` carries exactly one
   `AircraftState`, no traffic array) before this manager's `useOverlayData` can grow a traffic
   source. Resolution: manager 13's own design document, not this one.
4. **Marker-drag versus map-pan gesture conflict.** MapLibre GL JS's `Marker({ draggable: true })`
   is documented to capture the drag and suppress the underlying map pan, but this project has not
   yet verified that against the real WebGL runtime (the jsdom stub cannot, by construction — its
   `Map.on()` never fires). Resolution: a manual smoke check the first time Track C's PR is
   reviewed, on a real browser against a running server, before merge.
5. **Viewport-query tuning (zoom thresholds, radii, `limit`s in §7.5) are first guesses, not
   measurements.** A busy AIRAC region (western Europe: dense VORs, dense fixes) could make the
   default thresholds either too eager (slow pans) or too conservative (a sparse-feeling map at a
   zoom an instructor expects detail at). Resolution: a tuning pass against a real install once
   Track B is live — this needs the user's own navdata, which by rule 4 is never a CI fixture, so
   it is inherently a manual measurement, not a test.
6. **The hold racetrack overlay (`holdFeature`, §7.4) inherits the magnetic-variation imprecision
   `position-manager.md` §10.3 already accepted for the *placement* case.** It is cosmetic here,
   not safety-relevant (the actual hold *placement* remains correct, computed server-side with the
   airport's variation when known). Flagged so a future contributor does not assume the map's
   racetrack orientation is authoritative for anything.
7. **`kinds` array serialization (§7.2) needs to match FastAPI's repeated-key expectation** and is
   not yet proven against `fetchBaseQuery`'s default behaviour. Resolution: the unit test in
   §8.5 is the gate; if the default serializer does not produce repeated keys, `mapApi.ts` supplies
   a custom `paramsSerializer` — a small, contained fix, not a design change.
