# Design — Position Manager API

**Status:** design fixed. **Issue:** [#9](https://github.com/Santisoutoo/open-instructor-station/issues/9).
**Phase:** 1 — Position Manager + Aircraft Control.
**Depends on:** #3/#4/#5 (`NavdataProvider`, landed in PRs #54/#55), #6 (`feature/placement-geodesy`).
**Blocks:** #10 (Position panel UI), and every later manager that repositions the aircraft
(Scenario Generator, Instructor Map drag-to-place, Session Recorder snapshots).

This document fixes the HTTP contract — endpoints, request models, response models, error codes —
before any handler is written, the same way `SimAdapter` and `NavdataProvider` were fixed before
their implementations. Once it is agreed, the backend, the tests and the UI panel proceed in
parallel.

Binding rules live in [`../../CLAUDE.md`](../../CLAUDE.md); layers in
[`../architecture.md`](../architecture.md); the navdata contract in
[`navdata-provider.md`](navdata-provider.md). This document never relaxes any of them.

**Two branches are in flight and are not on `dev` at the time of writing.** This design is written
against their *intent*, not their current code:

- **`feature/placement-geodesy` (#6)** extends `core/geodesy.py` with holding entries, ARINC 424
  positionable legs and procedure placements. Everything this document says about hold and
  procedure placements assumes that work lands; §11.4 states exactly what it must expose and what
  `core/placements.py` does in the meantime.
- **`feature/autopilot-setup` (#41)** adds autopilot fields to `AircraftSetup` and
  `can_control_autopilot` to the contract. This manager needs **neither**, and is designed so that
  it inherits them for free the day they land (§7.3).

---

## 0. Decisions at a glance

| # | Decision | Where |
|---|---|---|
| D1 | **Three endpoints, not fourteen.** One catalogue, one preview, one apply, dispatching on a pydantic **discriminated union** keyed on `kind`. `architecture.md`'s sketch of `POST /api/position/final` is deliberately not followed. | §4 |
| D2 | **`POST /api/position/preview` is safe and side-effect-free.** It resolves geometry, builds the pre-teleport setup and touches nothing. It does **not** require `can_set_position`. | §4.2, §7 |
| D3 | **Apply re-resolves from scratch.** A preview is never accepted as input to a write; the client cannot hand the server a coordinate. | §4.3, §6 |
| D4 | **The request model is a `core/` model.** `PlacementSpec` lives in `core/placements.py` and FastAPI serialises it, exactly as it already serialises `AircraftSetup` and `Capabilities`. There is no translation layer and no parallel API model. | §5.1, §11 |
| D5 | **Resolution lives in `core/placements.py`**, takes a `NavdataProvider` and returns a `ResolvedPlacement`. It never sees a `Request`, a status code or an adapter. | §6, §11 |
| D6 | **No `SimAdapter` or `Capabilities` change.** `can_set_position`, `can_set_aircraft_state`, `set_position` and `apply_setup` already exist and are sufficient. **This manager needs no serialised contract change.** | §9 |
| D7 | **No new dataref.** The X-Plane adapter is untouched by this issue. | §10 |
| D8 | **Applying an airborne placement requires `can_set_aircraft_state` as well as `can_set_position`** — a teleport without a commanded speed is the measured failure of issue #39. A ground placement requires only `can_set_position`. | §7.2 |
| D9 | **The composed setup is *filtered* against capabilities, not refused.** `POST /api/aircraft/setup` refuses, because it carries what the instructor typed; a placement's setup is *derived*, so dropping an untunable radio and saying so is the correct behaviour. | §7.3 |
| D10 | **Every error carries a stable machine code** in a typed body, not a prose `detail` string. | §8 |
| D11 | **A hold placement needs magnetic→true conversion and the project has no world magnetic model.** It uses the variation published by the fix or the airport, and **fails loudly** when neither exists rather than silently using a magnetic course as a true heading. | §8.2, §15.1 |
| D12 | `server/deps.py` gaining `get_navdata()` is a **shared, serialised addition**, specified verbatim in `navdata-provider.md` §12 and made once, alone, before this manager's tracks branch. | §14 |
| D13 | The catalogue endpoint optionally aggregates runways/parking/procedures, so a tablet populates every picker in **one** round-trip. That is the 5-second exit criterion, not tidiness. | §4.1 |
| D14 | **The `/api/navdata/*` router is part of this issue and does not exist yet.** It is specified verbatim in `navdata-provider.md` §12 and is a fourth parallel track here. | §4.5, §14.2 |

---

## 1. Scope

### 1.1 What this manager does

The Position Manager API is the HTTP surface that lets an instructor:

1. **Ask what is possible here** — which of the 14 placement types apply to an airport, a runway
   or a procedure, and which are unavailable *and why*, before anything is clicked.
2. **See where the aircraft will land before committing** — a *preview* that returns the resolved
   coordinate, the target altitude, the heading, the commanded speed and the full pre-teleport
   `AircraftSetup`, without touching the simulator.
3. **Apply it** — write the setup, then the position, and report back what the aircraft actually
   looks like afterwards, including how far the write missed by.
4. **Browse the navdata behind all of that** — airports, runways, stands, procedures, navaids,
   fixes and holds, plus the AIRAC cycle and index state (§4.5).

It covers these [`feature-spec.md`](../feature-spec.md) items from manager 1:

- Final approach at 20 / 15 / 10 / 8 / 5 / 3 NM, and short final.
- Base, downwind, crosswind (and upwind, which `core/geodesy.py` already implements).
- Gate and parking stand.
- Arbitrary coordinate, over a waypoint.
- A point on a SID, a STAR or an approach.
- In a holding.
- The **radio slice of manager 7** — NAV/ILS frequency and OBS course tuned from the runway's
  localizer — which the feature spec explicitly ships with this manager.

It sits in **Phase 1** and serves exit criterion 1 directly: *"From a tablet, the instructor places
the aircraft on a 10 NM ILS final with a coherent aircraft state in under 5 seconds."* Exit
criteria 2 and 4 belong to the navdata track; criterion 3 is discharged here by §9's finding that
no new capability is needed and by the one contract test §13.2 adds.

### 1.2 What is explicitly out of scope

| Out of scope | Owner |
|---|---|
| The UI panel itself — components, layout, visuals | #10, a separate session. §12 fixes only the API/slice seam it builds against. |
| Geodesy for holding entries and procedure legs | #6, `feature/placement-geodesy`. §11.4. |
| The *full* pre-teleport setup — flaps, gear, spoilers, autobrake, lights, mass | #8. It extends `Placement.to_setup()`; this API composes whatever that method returns and needs no change when it grows (§6.4). |
| Navdata parsing, indexing, cache invalidation | #3/#4/#5, landed. The *HTTP surface* over them is §4.5 and is in scope. |
| Anything in `adapters/` | Untouched (§9, §10). |
| Drag-to-reposition from a map | Phase 3, and it is `kind: "coordinate"` with a map-derived anchor — this same endpoint. |
| Saving a placement as a profile or scenario | Phase 2 (manager 14) / Phase 2 (manager 2). Both compose `PlacementSpec`, which is why it is a `core/` model. |
| Long-haul teleports across a scenery reload | An **adapter** defect, tracked as [#36](https://github.com/Santisoutoo/open-instructor-station/issues/36). This API makes it one tap away, so §15.2 escalates it. |

---

## 2. Boundaries, restated for this manager

Two sentences, because they decide the whole file layout:

- **`core/` never learns about HTTP.** `core/placements.py` takes a `NavdataProvider` and a
  `PlacementSpec` and returns a `ResolvedPlacement` or raises `PlacementResolutionError`. There is
  no status code, no `Request`, no `HTTPException` and no FastAPI import anywhere in `core/`.
- **`server/` never learns a dataref name.** It calls `adapter.apply_setup()` and
  `adapter.set_position()`. Whether that means `local_x/y/z`, `override_planepath` or SimConnect's
  `SIMCONNECT_DATA_INITPOSITION` is the adapter's business and nothing in this document mentions
  it outside §10.

`tests/core/navdata/test_core_boundaries.py` already walks the import graph of `core/` and fails on
`httpx`, `websockets`, `adapters.*` and dataref-shaped literals. `core/placements.py` and
`core/radio_tuning.py` land inside that guard for free — no new guard is needed, and none should
be added.

---

## 3. The placement catalogue — the 14 Phase 1 types

The `kind` of a `PlacementSpec` is one of exactly fourteen values. They are the discriminator of
the request union, the identifiers in the catalogue response, and the keys of the UI's display
table — one closed set, generated once into TypeScript.

```python
PlacementKind = Literal[
    "final", "short_final",
    "upwind", "crosswind", "downwind", "base",
    "gate", "stand",
    "coordinate", "waypoint",
    "sid", "star", "approach",
    "hold",
]
```

| # | `kind` | Anchor | Parameters (units explicit) | Altitude rule | Default `ias_kt` |
|---|---|---|---|---|---|
| 1 | `final` | runway end | `airport_icao`, `runway_ident`, `distance_nm` (0.1–50, **default 10.0**), `glideslope_deg` (optional) | `glideslope_altitude_ft(runway.elevation_ft, distance_nm, gs)`, feet MSL | `APPROACH_CATEGORY_VAT_KT[cat]` — B → **120 kt** |
| 2 | `short_final` | runway end | `airport_icao`, `runway_ident`, `glideslope_deg` (optional) | same, at `SHORT_FINAL_DISTANCE_NM = 1.0` NM → **+318.44 ft** over threshold on 3° | `APPROACH_CATEGORY_VAT_KT[cat]` |
| 3 | `upwind` | runway end | `airport_icao`, `runway_ident`, `side` (`left`\|`right`, default `left`), `pattern_altitude_ft`, `pattern_width_nm`, `leg_distance_nm` | `pattern_altitude_ft`, else `runway.elevation_ft + 1000` ft MSL | `APPROACH_CATEGORY_CIRCLING_IAS_KT[cat]` — B → **135 kt** |
| 4 | `crosswind` | runway end | as above | as above | circling |
| 5 | `downwind` | runway end | as above | as above | circling |
| 6 | `base` | runway end | as above | as above | circling |
| 7 | `gate` | parking, `kind == "gate"` | `airport_icao`, `name` | `stand.position.altitude_ft` (= airport elevation), feet MSL | `GROUND_IAS_KT` = **0.0** |
| 8 | `stand` | parking, **any** kind | `airport_icao`, `name` | as above | **0.0** |
| 9 | `coordinate` | none | `latitude`, `longitude`, `altitude_ft` (MSL), `heading_deg` (true, default 0) | verbatim from the request | **0.0** — the one placement whose default is stationary, per `core.geodesy.coordinate_placement` |
| 10 | `waypoint` | fix or navaid | `ident`, `region_code` (optional), `altitude_ft` (**required**, MSL), `heading_deg` (optional, true) | verbatim | `APPROACH_CATEGORY_CIRCLING_IAS_KT[cat]` as a generic manoeuvring speed |
| 11 | `sid` | procedure leg | `airport_icao`, `ident`, `transition` (optional), `sequence`, `altitude_ft` (optional override) | `leg.altitude.suggested_ft` (a band resolves to its **lower** bound); override wins | `leg.speed.suggested_kt`, else circling |
| 12 | `star` | procedure leg | as above | as above | as above |
| 13 | `approach` | procedure leg | as above | as above | as above |
| 14 | `hold` | published hold | `fix_ident`, `region_code` (optional), `airport_icao` (optional), `altitude_ft` (optional), `heading_deg` (optional, true) | `altitude_ft`, else `hold.min_altitude_ft`; neither → `altitude_required` | `hold.speed_kt`, else circling |

**Why the six named finals are a *parameter*, not six kinds.** `core.geodesy.FINAL_DISTANCES_NM`
names them, but from the API's point of view they differ only by a number. The catalogue advertises
`preset_distances_nm = (20.0, 15.0, 10.0, 8.0, 5.0, 3.0)` so the panel renders six chips; the
request carries `distance_nm`. Six kinds would be six discriminator branches, six request models
and six test parametrisations for one float.

**Why `short_final` *is* a separate kind.** It resolves to 1.0 NM but is labelled *"short final"*
rather than *"1 NM final"*, and an instructor picks it as a distinct exercise. It dispatches to
`core.geodesy.final_placement(runway, "short_final")` so the label comes from `core/`, not from a
string built in the server.

**Why `gate` and `stand` are two kinds over one navdata model.** `apt.dat` has one record type
(`1300`) with a `kind` field, and `navdata-provider.md` §5.6 rightly refuses to invent two Python
models. But the feature spec offers two *actions*, and they filter differently: `gate` matches only
`ParkingKind == "gate"`, `stand` matches any parking record by name. Two kinds, one resolver, one
model. An instructor asking for "gate R32" when R32 is a tie-down gets a 404 with the reason,
which is more useful than silently placing them on a tie-down.

**`upwind` is included although the feature spec lists only crosswind/downwind/base.**
`core.geodesy.PATTERN_PLACEMENTS` already implements all four legs on both sides; excluding upwind
would mean writing code to hide a working feature.

**`ias_kt` is required on `Placement` and therefore never absent.** Every row above states what
fills it when the request does not. An explicit `ias_kt` in the request always wins; `approach_category`
(ICAO PANS-OPS Doc 8168, `A`–`E`) selects the default; `DEFAULT_APPROACH_CATEGORY = "B"` when the
request states neither. This is the resolution of issue #39 and it is not re-litigated here.

---

## 4. REST endpoints

Three endpoints under `/api/position/`, all declared **`async def`** (they await the adapter) with
the synchronous navdata calls wrapped per §6.3. The `/api/navdata/` router is §4.5.

| Method | Path | Purpose | Safe? | Idempotent? |
|---|---|---|---|---|
| `GET` | `/api/position/placements` | What can be placed here, and what cannot and why | yes | yes |
| `POST` | `/api/position/preview` | Resolve a spec into a position + setup. **Writes nothing.** | **yes** | yes |
| `POST` | `/api/position/apply` | Resolve, then write setup and position | no | **yes** |

### 4.1 `GET /api/position/placements`

**Purpose.** One call answers "what can I do?" for the panel. Without an anchor it is the static
catalogue gated on capabilities and navdata state; with `airport_icao` it also returns the concrete
anchors so every picker is populated in a single round-trip.

**Query parameters**

| Name | Type | Default | Meaning |
|---|---|---|---|
| `airport_icao` | `str` | — | Resolve anchors for this airport. Case-insensitive, normalised. |
| `runway_ident` | `str` | — | Narrow `runways` to one end. Accepts `18L` or `RW18L`; `18L` is returned. |
| `include` | `str` (comma list of `runways`,`parking`,`procedures`) | `runways` | Which anchor collections to embed. |
| `parking_kind` | `ParkingKind` | — | Filter `parking`. |
| `procedure_kind` | `ProcedureKind` | — | Filter `procedures`. |

**Response** `200 PlacementCatalogue`.

`include` defaults to `runways` only, and that is load-bearing: LEMD has 100+ procedures and
several hundred stands. A tablet asking for a 10 NM final must not pay for them.

**Errors.** `404 airport_not_found` when `airport_icao` is given and unknown; `404 runway_not_found`
when `runway_ident` is given and unknown; `503 navdata_unavailable` (with `Retry-After`) when the
index is not ready **and** an anchor was requested. With no anchor requested the endpoint **always
returns 200**, with every navdata-dependent option marked `available: false` and a reason — the
panel must be able to render itself while the index builds.

### 4.2 `POST /api/position/preview`

**Purpose.** Turn a `PlacementSpec` into a `ResolvedPlacement` — coordinate, altitude, heading,
speed, the full pre-teleport `AircraftSetup`, the anchor it was resolved against, and warnings —
**without touching the simulator**.

**Request body:** `PlacementSpec` (§5.1). **Response:** `200 PlacementPreview`.

**It is safe.** No adapter write happens. The only adapter call is a read of
`get_aircraft_state()` to compute `distance_from_aircraft_nm` and to raise the long-teleport
warning, and it is best-effort: if the adapter is disconnected or the read fails, those two fields
are `null` and the preview still returns 200. A preview must work with no simulator running at
all — that is the `OIS_ADAPTER=fake OIS_NAVDATA=xplane_native` development loop
`navdata-provider.md` D3 exists to enable.

**It does not require `can_set_position`.** Seeing where a 10 NM final lands is useful against an
adapter that cannot move anything. `can_apply` in the body says whether the follow-up write is
permitted, and that is what the panel's button gates on.

**Errors:** §8, all of them.

### 4.3 `POST /api/position/apply`

**Purpose.** The command. Resolve the same spec, then:

1. `adapter.apply_setup(filtered_setup)` — the pre-teleport configuration, **before** the move.
2. `adapter.set_position(placement.position, placement.heading_deg)`.
3. `adapter.get_aircraft_state()` — the read-back.

**Request body:** `PlacementSpec`, identical to preview. **Response:** `200 PlacementResult`.

**Apply re-resolves; it never accepts a client-supplied coordinate (D3).** The body is the same
declarative spec, so an instructor who previewed and then applied gets the same answer — the
resolution is a pure function of (navdata, spec). Accepting the preview back would let a client
teleport the aircraft anywhere by editing a JSON field, and would make the two endpoints' results
diverge the moment navdata changed underneath.

**It is idempotent.** The spec states an absolute target, not a delta. Replaying it puts the
aircraft in the same place. Two rapid applies are harmless: the second is a teleport to the same
coordinate.

**It never fails on read-back divergence.** `position_error_nm`, `heading_error_deg` and
`altitude_error_ft` are reported in the body; a large error produces a `position_not_verified`
warning, not a 5xx. The instructor is told, and the aircraft is where the simulator put it —
inventing a failure status for a write that partially took would be worse than the truth. Against
`FakeSimAdapter` these are exactly 0.

**Errors:** everything in §8, plus `501 capability_unavailable` (§7.2) and `502 sim_unreachable`.

### 4.4 What is deliberately *not* an endpoint

- **No `POST /api/position/final`, `/gate`, `/hold`, …** (D1). Fourteen endpoints means fourteen
  handlers, fourteen response models and fourteen sets of error tests for one algorithm with a
  `match` statement in the middle. The discriminated union gives the generated TypeScript client a
  proper tagged union, which is strictly better ergonomics than fourteen hooks.
- **No WebSocket change.** Position is a command; the live picture already streams over
  `WS /ws/state`. After an apply the UI sees the new position on the next frame, ~250 ms later,
  and `PlacementResult.state` covers the gap.
- **No navdata lookups duplicated under `/api/position/`.** Runway, parking, procedure and fix
  lookups belong to the `/api/navdata/` router of §4.5. The catalogue's `anchors` block is an
  aggregation for the two-tap flow, not a second source of truth.

### 4.5 The `/api/navdata/` router — in scope, and not yet written

Issue #9 asks for `/api/navdata/*` as well as `/api/position/*`. **Those routes do not exist
today**: `server/` contains only `app.py` and `deps.py`, with no `navdata` reference anywhere in
it. They are, however, already **specified in full** in
[`navdata-provider.md` §12](navdata-provider.md) — paths, status codes, `Retry-After` semantics,
the threadpool rule (handlers are `def`, not `async def`, because `NavdataProvider` is
synchronous), and the `call_soon_threadsafe` hand-off that publishes `IndexProgress` frames onto
the existing WebSocket.

This design therefore does **not** re-specify them. It records that:

- They live in `server/navdata_api.py`, a new file, owned by a **fourth track** (§14.2) that is
  disjoint from the three below.
- They are what satisfies issue #9's *"Report the AIRAC cycle and cache state so the UI can show
  which navdata is loaded"* — via `GET /api/navdata/status`.
- The Position API depends on none of them: it calls `NavdataProvider` directly through
  `get_navdata()`. The two routers share only that dependency, which §14.1 makes once.

---

## 5. Pydantic models

Units are in the field name, always, following `core/models.py`: `_ft` is feet MSL unless the name
says AGL, `_kt` is indicated knots, `_deg` is **true** degrees for headings and bearings (`_mag_deg`
where magnetic), `_nm` is nautical miles, `_m` is metres, `_khz` is kilohertz, `_fpm` is feet per
minute.

### 5.0 What is reused, and from where — nothing is re-invented

| Model | Module | Used as |
|---|---|---|
| `Placement` | `core.geodesy` | the resolved geometry, verbatim, inside `ResolvedPlacement` |
| `AircraftSetup` | `core.models` | the pre-teleport payload, verbatim |
| `AircraftState` | `core.models` | the read-back after an apply |
| `GeoPosition` | `core.models` | every coordinate |
| `Runway`, `Ils` | `core.models` | the runway anchor and the radio source |
| `ApproachCategory`, `PatternSide`, `FinalPlacement` | `core.geodesy` | request fields |
| `Airport`, `AirportSummary`, `ParkingStand`, `Waypoint`, `Procedure`, `ProcedureSummary`, `ProcedureLeg`, `Hold`, `AltitudeConstraint`, `SpeedConstraint`, `NavdataState` | `core.navdata.models` | anchors and catalogue |
| `Capabilities` | `core.sim_adapter` | capability gating |

**New models introduced by this design: eight.** `PlacementSpec` (a union of eight member models),
`PlacementAnchor`, `ResolvedPlacement`, `PlacementWarning`, `PlacementPreview`, `PlacementResult`,
`PlacementCatalogue` (+ `PlacementOption`, `PlacementAnchors`), `PlacementErrorDetail`. The first
six live in `core/placements.py`; the catalogue and the error detail live in `server/position.py`
because they describe an HTTP response, not a placement.

### 5.1 `PlacementSpec` — the request union (`core/placements.py`)

```python
class PlacementSpecBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ias_kt: float | None = Field(
        default=None, ge=0.0, le=600.0,
        description="Indicated airspeed to command, knots. None takes the approach "
                    "category's default for this placement kind — see the catalogue "
                    "table. An explicit value always wins.",
    )
    approach_category: ApproachCategory | None = Field(
        default=None,
        description="ICAO approach category A–E (PANS-OPS Doc 8168), used only when "
                    "ias_kt is None. None means DEFAULT_APPROACH_CATEGORY ('B').",
    )
    tune_radios: bool = Field(
        default=True,
        description="Tune NAV1/ILS and set the OBS course from the runway localizer "
                    "when the anchor has one. Ignored when there is no ILS.",
    )
```

`extra="forbid"` is deliberate: a typo'd field name in a saved training profile must fail loudly at
load time rather than silently place the aircraft at a default.

#### Runway-anchored members

```python
class RunwaySpecBase(PlacementSpecBase):
    airport_icao: str = Field(min_length=2, max_length=7, description='e.g. "LEMD".')
    runway_ident: str = Field(min_length=1, max_length=5,
        description='Runway END, e.g. "32L". "RW32L" is accepted and normalised.')


class FinalSpec(RunwaySpecBase):
    kind: Literal["final"] = "final"
    distance_nm: float = Field(default=10.0, gt=0.0, le=50.0,
        description="Distance out from the displaced landing threshold, nautical miles.")
    glideslope_deg: float | None = Field(default=None, gt=0.0, le=10.0,
        description="Glidepath angle, degrees. None uses the runway's published ILS "
                    "glideslope when there is one, else DEFAULT_GLIDESLOPE_DEG (3.0).")


class ShortFinalSpec(RunwaySpecBase):
    kind: Literal["short_final"] = "short_final"
    glideslope_deg: float | None = Field(default=None, gt=0.0, le=10.0)


class PatternSpec(RunwaySpecBase):
    kind: Literal["upwind", "crosswind", "downwind", "base"]
    side: PatternSide = Field(default="left",
        description='Which side the circuit is flown on: "left" (standard) or "right".')
    pattern_altitude_ft: float | None = Field(default=None,
        description="Circuit altitude, feet MSL. None uses the threshold elevation plus "
                    "DEFAULT_PATTERN_ALTITUDE_AGL_FT (1000 ft AGL).")
    pattern_width_nm: float = Field(default=DEFAULT_PATTERN_WIDTH_NM, gt=0.0, le=10.0,
        description="Centreline to downwind leg, nautical miles.")
    leg_distance_nm: float = Field(default=DEFAULT_PATTERN_LEG_DISTANCE_NM, gt=0.0, le=20.0,
        description="How far beyond the departure end upwind/crosswind sit, and how far "
                    "before the threshold base sits, nautical miles.")
```

**One model carries four `kind` values.** Pydantic v2 allows a discriminated-union member whose
discriminator is a multi-value `Literal`; all four map to `PatternSpec`. If that proves awkward in
the OpenAPI schema, the fallback is four one-line subclasses each pinning a single `Literal` —
same wire format, same TypeScript union, no other change. The implementer decides after
generating the schema once; the **contract does not move either way**.

#### Airport-surface members

```python
class ParkingSpec(PlacementSpecBase):
    kind: Literal["gate", "stand"]
    airport_icao: str = Field(min_length=2, max_length=7)
    name: str = Field(min_length=1, description='Stand or gate name, e.g. "R32". '
                                                "Matched case-insensitively.")
```

`kind == "gate"` matches only `ParkingKind == "gate"`; `kind == "stand"` matches any parking record.
`ias_kt` defaults to `GROUND_IAS_KT` (0.0) for both, and an explicit non-zero `ias_kt` on a parking
placement produces a `speed_on_ground_placement` warning rather than an error — an instructor
staging a high-speed taxi test is not wrong, merely unusual.

#### Free and navdata-anchored members

```python
class CoordinateSpec(PlacementSpecBase):
    kind: Literal["coordinate"] = "coordinate"
    latitude: float = Field(ge=-90.0, le=90.0, description="Degrees, WGS84, positive north.")
    longitude: float = Field(ge=-180.0, le=180.0, description="Degrees, WGS84, positive east.")
    altitude_ft: float = Field(description="Feet above mean sea level.")
    heading_deg: float = Field(default=0.0, ge=0.0, le=360.0, description="TRUE degrees.")


class WaypointSpec(PlacementSpecBase):
    kind: Literal["waypoint"] = "waypoint"
    ident: str = Field(min_length=1, max_length=5, description='e.g. "GOXOL", "NVS".')
    region_code: str | None = Field(default=None, max_length=2,
        description='ICAO region, e.g. "LE". Disambiguates a non-unique ident.')
    terminal_airport_icao: str | None = Field(default=None,
        description="Scope to a terminal fix of this airport.")
    altitude_ft: float = Field(description="Feet MSL. Required: a navdata fix carries no altitude.")
    heading_deg: float | None = Field(default=None, ge=0.0, le=360.0,
        description="TRUE degrees. None leaves core.geodesy.waypoint_placement to choose "
                    "(next fix, then previous fix, then 0°).")


class ProcedureSpec(PlacementSpecBase):
    kind: Literal["sid", "star", "approach"]
    airport_icao: str = Field(min_length=2, max_length=7)
    ident: str = Field(min_length=1, description='Procedure identifier, e.g. "BARD3B", "I32L".')
    transition: str | None = Field(default=None, description='e.g. "ADUXO", "RW32L". None = common route.')
    sequence: int = Field(ge=0, description="The leg's sequence number from the source record "
                                            "(10, 20, 30 …), as carried by ProcedureLeg.sequence.")
    altitude_ft: float | None = Field(default=None,
        description="Override, feet MSL. None uses the leg's altitude constraint "
                    "(AltitudeConstraint.suggested_ft — a band resolves to its LOWER bound).")


class HoldSpec(PlacementSpecBase):
    kind: Literal["hold"] = "hold"
    fix_ident: str = Field(min_length=1, max_length=5)
    region_code: str | None = Field(default=None, max_length=2)
    airport_icao: str | None = Field(default=None, description="None selects an enroute hold.")
    altitude_ft: float | None = Field(default=None,
        description="Feet MSL. None uses the hold's min_altitude_ft; when the hold "
                    "publishes neither, the request fails with altitude_required.")
    entry: HoldEntry | None = Field(default=None,
        description='Where in the pattern to place: "fix" | "inbound" | "outbound" | "abeam". '
                    "None means at the fix, established inbound. See §11.4.")
    heading_deg: float | None = Field(default=None, ge=0.0, le=360.0,
        description="TRUE degrees, overriding the magnetic→true conversion of the published "
                    "inbound course. Required when no magnetic variation is available (§8.2).")


PlacementSpec = Annotated[
    FinalSpec | ShortFinalSpec | PatternSpec | ParkingSpec
    | CoordinateSpec | WaypointSpec | ProcedureSpec | HoldSpec,
    Field(discriminator="kind"),
]
```

### 5.2 `PlacementAnchor` — what it was resolved against

```python
AnchorKind = Literal["runway", "parking", "coordinate", "waypoint", "procedure_leg", "hold"]


class PlacementAnchor(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: AnchorKind
    label: str = Field(min_length=1, description='e.g. "LEMD 32L", "LEMD stand R32", "GOXOL".')
    position: GeoPosition = Field(description="The anchor point itself — the displaced landing "
                                              "threshold, the stand, the fix. NOT the placement.")
    airport_icao: str | None = None
    runway: Runway | None = Field(default=None,
        description="Reused core.models.Runway, carrying its Ils when there is one. Embedded so "
                    "the panel can draw the extended centreline without a second fetch.")
    parking: ParkingStand | None = None
    waypoint: Waypoint | None = None
    procedure: ProcedureSummary | None = None
    leg: ProcedureLeg | None = None
    hold: Hold | None = None
```

Exactly one of `runway` / `parking` / `waypoint` / (`procedure` + `leg`) / `hold` is set, or none of
them for a bare coordinate. The payload is fat for a runway anchor (≈20 fields plus the `Ils`);
that is the point — it saves the map a round-trip and it is the same data the panel needs to render
the preview.

### 5.3 `ResolvedPlacement` — the answer

```python
class ResolvedPlacement(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: PlacementKind
    placement: Placement = Field(description="core.geodesy.Placement: position (with altitude_ft "
                                             "in feet MSL), heading_deg TRUE, ias_kt, label.")
    setup: AircraftSetup = Field(description="The state to apply BEFORE the teleport. Every field "
                                             "that is None means 'leave that aspect untouched'.")
    anchor: PlacementAnchor
    distance_from_anchor_nm: float | None = Field(default=None, ge=0.0,
        description="Along-track distance from the anchor to the placement, nautical miles. "
                    "None for a coordinate or a waypoint placement (distance is zero by "
                    "construction and the field would be noise).")
    height_above_anchor_ft: float | None = Field(default=None,
        description="placement.altitude_ft minus the anchor's elevation, feet.")
    glideslope_deg: float | None = Field(default=None,
        description="The glidepath actually used, degrees — the published ILS value when there "
                    "was one, otherwise DEFAULT_GLIDESLOPE_DEG. Finals only.")
    ils: Ils | None = Field(default=None, description="The ILS the radios were tuned from, if any.")
    airac_cycle: str | None = Field(default=None,
        description='The navdata cycle this was resolved against, e.g. "2607". Carried so a saved '
                    "profile can be diffed against a later cycle (manager 14).")
    warnings: tuple[PlacementWarning, ...] = ()
```

### 5.4 `PlacementWarning` — never silent, never fatal

```python
PlacementWarningCode = Literal[
    "nominal_glideslope_used",        # runway has no published GS; 3.0° assumed
    "no_ils_published",               # tune_radios asked, runway has no localizer
    "pattern_altitude_defaulted",     # 1000 ft AGL assumed
    "altitude_from_constraint_band",  # a B-band leg resolved to its lower bound
    "no_speed_constraint",            # leg published no speed; category default used
    "speed_on_ground_placement",      # non-zero ias_kt on a gate/stand
    "airborne_placement_at_zero_speed",  # coordinate above field elevation with ias_kt 0
    "ground_elevation_estimated",     # parking altitude is the airport datum, not the stand
    "long_teleport",                  # > LONG_TELEPORT_WARNING_NM from the aircraft
    "setup_field_dropped",            # a setup field the adapter cannot write was removed
    "position_not_verified",          # read-back diverged beyond tolerance (apply only)
    "magnetic_variation_assumed",     # hold heading converted from a nearby variation source
]


class PlacementWarning(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: PlacementWarningCode
    message: str = Field(min_length=1, description="Shown to the instructor verbatim.")
    field: str | None = Field(default=None, description="The spec or setup field concerned.")
```

`airborne_placement_at_zero_speed` is the one that matters: it is issue #39's crash, caught before
the write, in words. It fires when `placement.ias_kt == 0` and the placement is more than 100 ft
above the nearest known ground elevation. It is a **warning, not an error** — an instructor may
legitimately want a stationary aircraft in the air for a demonstration, and refusing would be the
application overruling the user.

### 5.5 Response envelopes

```python
class PlacementPreview(BaseModel):
    resolved: ResolvedPlacement
    can_apply: bool = Field(description="True when POST /api/position/apply would be accepted.")
    blocked_reason: str | None = Field(default=None,
        description="Why apply is refused. None when can_apply is true.")
    distance_from_aircraft_nm: float | None = Field(default=None, ge=0.0,
        description="Geodesic distance from the aircraft's current position, nautical miles. "
                    "None when the adapter could not be read — a preview never depends on a sim.")
    dropped_setup_fields: list[str] = Field(default_factory=list,
        description="Fields of `resolved.setup` this adapter cannot write and that apply "
                    "would therefore omit.")


class PlacementResult(BaseModel):
    resolved: ResolvedPlacement
    applied_setup: AircraftSetup = Field(description="What was actually written, after capability "
                                                     "filtering. Echoed because AircraftState "
                                                     "carries no configuration.")
    dropped_setup_fields: list[str]
    state: AircraftState = Field(description="The aircraft as read back after the write.")
    position_error_nm: float = Field(ge=0.0,
        description="Geodesic distance between the commanded position and the read-back, "
                    "nautical miles. 0.0 against FakeSimAdapter.")
    altitude_error_ft: float = Field(description="Read-back minus commanded, feet.")
    heading_error_deg: float = Field(description="Signed shortest angular difference, degrees, "
                                                 "in [-180, 180].")
```

### 5.6 Catalogue models (`server/position.py`)

```python
class PlacementOption(BaseModel):
    id: PlacementKind
    label: str = Field(description='e.g. "Final approach", "Downwind".')
    anchor: AnchorKind
    available: bool
    reason: str | None = Field(default=None, description="Why not. None when available.")
    requires_navdata: bool = Field(description="False only for `coordinate`.")
    preset_distances_nm: tuple[float, ...] = Field(default=(),
        description="Finals only: (20, 15, 10, 8, 5, 3).")
    pattern_sides: tuple[PatternSide, ...] = Field(default=(),
        description="Circuit legs only: (left, right).")


class PlacementAnchors(BaseModel):
    airport: AirportSummary
    runways: list[Runway] = Field(default_factory=list,
        description="Every runway END, each carrying its Ils when there is one.")
    parking: list[ParkingStand] = Field(default_factory=list)
    procedures: list[ProcedureSummary] = Field(default_factory=list)


class PlacementCatalogue(BaseModel):
    adapter: str
    navdata_provider: str
    navdata_state: NavdataState = Field(description='"unavailable" | "building" | "ready" | "error".')
    airac_cycle: str | None = None
    can_apply: bool = Field(description="True when the adapter can honour a write at all.")
    blocked_reason: str | None = None
    options: list[PlacementOption] = Field(description="All 14, always, in display order.")
    anchors: PlacementAnchors | None = Field(default=None,
        description="Populated only when airport_icao was supplied.")
```

**All 14 options are always returned**, in display order, unavailable ones included with a reason.
Omitting them would make a control silently disappear, which is exactly the failure mode hard rule
3 exists to prevent.

---

## 6. How it composes

### 6.1 The call path, once, end to end

```
POST /api/position/apply  { "kind": "final", "airport_icao": "LEMD",
                            "runway_ident": "32L", "distance_nm": 10 }
  │
  ├─ server/position.py
  │     spec: PlacementSpec  ← FastAPI parses the discriminated union
  │     provider = get_navdata()            (server/deps.py singleton)
  │     adapter  = get_adapter()            (server/deps.py singleton)
  │     current  = await adapter.get_aircraft_state()      # best effort
  │
  ├─ core/placements.py :: resolve_placement(provider, spec, current_position=…)
  │     │
  │     ├─ provider.get_runway("LEMD", "32L")            → core.models.Runway (+ Ils)
  │     ├─ glideslope = runway.ils.glideslope_deg or DEFAULT_GLIDESLOPE_DEG
  │     ├─ core.geodesy.final_approach_point(runway, 10.0, glideslope)
  │     │        → GeoPosition, altitude_ft = elev + 3184.36 ft on a 3° path
  │     ├─ Placement(position=…, heading_deg=runway.true_bearing_deg,
  │     │            ias_kt=APPROACH_CATEGORY_VAT_KT["B"], label="LEMD 32L 10 NM final")
  │     ├─ setup = placement.to_setup()                  # altitude, heading, ias  (#8 extends this)
  │     ├─ setup = core.radio_tuning.tune_ils(setup, runway.ils)   # ils/nav1 kHz, obs1 mag deg
  │     └─ ResolvedPlacement(placement, setup, anchor, warnings, airac_cycle)
  │
  ├─ server/capability_gate.py :: filter_setup(setup, adapter.capabilities)
  │        → (applied_setup, dropped_setup_fields)
  │
  ├─ await adapter.apply_setup(applied_setup)      # BEFORE the move
  ├─ await adapter.set_position(placement.position, placement.heading_deg)
  ├─ state = await adapter.get_aircraft_state()
  └─ PlacementResult(…, position_error_nm=distance_and_bearing(commanded, read_back)[0])
```

`preview` is the same path with the last four steps replaced by "compute `can_apply` and return".

### 6.2 Where each rule lives, and why

| Decision | Module | Why not elsewhere |
|---|---|---|
| Which glidepath angle | `core/placements.py` | It is a data preference (published over nominal), not geometry and not HTTP. |
| Where the point is | `core/geodesy.py` | Pure WGS84 maths, already tested to 0.01 ft. |
| What speed to command | `core/geodesy.py` (`_resolve_ias_kt`) | Already the resolution of #39. Not re-implemented. |
| Which altitude a constraint band means | `core/navdata/models.py` (`AltitudeConstraint.suggested_ft`) | Already decided there, once, so preview and apply cannot disagree. |
| Which radios to tune | `core/radio_tuning.py` | Sim-agnostic, reused by scenarios later. |
| Which setup fields the adapter can write | `server/capability_gate.py` | It is a property of the *deployment*, not of the placement. |
| How a failure becomes a status code | `server/position.py` | The only place that may know what HTTP is. |
| How the aircraft is actually moved | `adapters/xplane/` | §10. |

### 6.3 Sync navdata inside an async route

`NavdataProvider` is synchronous by design (`navdata-provider.md` §3). These routes are
`async def` because they await the adapter. The provider calls therefore go through
`await asyncio.to_thread(resolve_placement, provider, spec, current)` — one thread hop per request,
against a query that costs microseconds, in exchange for never blocking the event loop that is also
serving the 4 Hz state stream to a tablet.

This is the **only** place in the project where a `core/` call is thread-hopped, and it is stated
here so nobody "optimises" it away and stalls the WebSocket under a procedure lookup.

### 6.4 Why #8 and #41 cost this manager nothing

- **#8 (full pre-teleport setup)** extends `Placement.to_setup()` to also set flaps, gear,
  spoilers, autobrake, lights and mass. §6.1 calls `to_setup()` and passes the result through
  `filter_setup`. When #8 lands, placements start arriving configured and **not one line of
  `server/position.py` changes**.
- **#41 (autopilot)** adds fields to `AircraftSetup` and `can_control_autopilot`. `filter_setup`
  drops any field whose capability is undeclared, so an adapter without autopilot support silently
  loses those fields and reports them in `dropped_setup_fields`. Nothing here needs to know they
  exist.

That is the test of whether the composition is right: both in-flight branches are additive to this
manager.

---

## 7. Capability gating

### 7.1 The gate is published before it is needed

`GET /api/position/placements` resolves every option against `adapter.capabilities` and
`provider.status()` and returns `available` + `reason` per option and `can_apply` +
`blocked_reason` for the manager as a whole. The panel disables on that. Nobody should ever reach
a 501 — reaching one means a caller ignored the catalogue, exactly as `CapabilityNotSupported`'s
docstring says.

### 7.2 What apply requires (D8)

| Placement | Required capabilities | Rationale |
|---|---|---|
| Ground (`gate`, `stand`, or any placement whose resolved `ias_kt == 0` and altitude ≤ anchor elevation + 100 ft) | `can_set_position` | Nothing needs to be commanded but the position. |
| **Airborne** (everything else) | `can_set_position` **and** `can_set_aircraft_state` | A teleport with no commanded speed is issue #39's measured crash: perfect geometry, 0.2 m error, aircraft in the terrain because it was below stall speed. An adapter that cannot write speed must not be allowed to place an aircraft on a final. |

When a required capability is missing, `apply` returns **`501`** with
`code = "capability_unavailable"` and a reason naming the flag — the same status
`POST /api/aircraft/setup` already uses, for the same reason: the request is well-formed, the
server has no implementation behind it.

`preview` requires neither (D2).

### 7.3 Filtering, not refusing (D9)

`server/capability_gate.py`:

```python
DEFAULT_SETUP_CAPABILITY = "can_set_aircraft_state"

#: AircraftSetup fields whose capability is NOT the default. Fields absent from
#: this mapping fall back to DEFAULT_SETUP_CAPABILITY, so a field added to
#: AircraftSetup is gated correctly on the day it appears.
SETUP_FIELD_CAPABILITY: Mapping[str, str] = {
    "autopilot_master": "can_control_autopilot",
    "autopilot_nav": "can_control_autopilot",
    "autopilot_app": "can_control_autopilot",
    "autopilot_hdg": "can_control_autopilot",
    "flight_director": "can_control_autopilot",
    "target_altitude_ft": "can_control_autopilot",
    "target_ias_kt": "can_control_autopilot",
    "target_heading_deg": "can_control_autopilot",
    "target_vertical_speed_fpm": "can_control_autopilot",
    "gross_weight_kg": "can_set_fuel_payload",
    "fuel_kg": "can_set_fuel_payload",
}


def filter_setup(setup: AircraftSetup, capabilities: Capabilities) -> tuple[AircraftSetup, list[str]]:
    """Drop every set field the adapter cannot write. Returns (kept, dropped_names)."""
```

**Why this differs from `POST /api/aircraft/setup`, which refuses the whole write.** That endpoint
carries exactly what the instructor typed; dropping half of it would be lying about what happened.
A placement's setup is *derived* — the instructor asked for "10 NM final", not for
`nav1_freq_khz = 110100`. Dropping a radio the adapter cannot tune still produces a correct
placement, and `dropped_setup_fields` plus a `setup_field_dropped` warning tells the instructor
what did not happen. Silently doing nothing would be wrong; refusing the placement would be worse.

**The one exception is speed**, and it is not handled by filtering: §7.2 refuses the whole apply,
because a placement without its commanded speed is not a degraded placement, it is a crash.

`server/capability_gate.py` is a **new file**. It deliberately does *not* refactor `_CONTROL_FIELDS`
out of `server/app.py`: that file is being edited by `feature/autopilot-setup` right now, and a
merge conflict in the shared app module is a worse cost than a ten-line mapping that overlaps it.
A follow-up issue converges the two once #41 has landed on `dev` — recorded in §15.5 so it is a
decision, not an oversight.

---

## 8. Errors

### 8.1 The error body

Every error this manager raises returns a **typed** body, so the generated client can branch on a
code instead of matching prose:

```python
PlacementErrorCode = Literal[
    "airport_not_found", "runway_not_found", "parking_not_found",
    "procedure_not_found", "leg_not_found", "leg_not_positionable",
    "fix_not_found", "fix_ambiguous", "hold_not_found",
    "altitude_required", "magnetic_variation_unavailable",
    "navdata_unavailable", "capability_unavailable", "sim_unreachable",
]


class PlacementErrorDetail(BaseModel):
    code: PlacementErrorCode
    message: str = Field(description="Shown to the instructor verbatim.")
    airport_icao: str | None = None
    runway_ident: str | None = None
    ident: str | None = None
    sequence: int | None = None
    path_terminator: str | None = Field(default=None,
        description="Set for leg_not_positionable: the ARINC terminator that cannot be placed.")
    candidates: list[Waypoint] = Field(default_factory=list,
        description="Set for fix_ambiguous: every fix matching the ident, so the panel can ask.")
    navdata_status: NavdataStatus | None = Field(default=None,
        description="Set for navdata_unavailable, so a UI that raced the index build gets the "
                    "state instead of a stack trace.")


class PlacementErrorResponse(BaseModel):
    detail: PlacementErrorDetail
```

Every route declares `responses={404: …, 409: …, 422: …, 501: …, 502: …, 503: …}` with this model,
so the codes land in the OpenAPI schema and in the TypeScript client.

### 8.2 The table

| Situation | Status | `code` | Notes |
|---|---|---|---|
| Airport not in the index | `404` | `airport_not_found` | `provider.get_airport()` returned `None`. |
| Runway end not at that airport | `404` | `runway_not_found` | `18L` vs `RW18L` both accepted first. |
| Gate/stand name not at that airport | `404` | `parking_not_found` | `gate` also 404s when the name exists but is not a gate — the message says so. |
| Procedure/transition not published | `404` | `procedure_not_found` | |
| No leg with that `sequence` | `404` | `leg_not_found` | |
| **Leg is `CA`/`VA`/`FM`/`VM`/`CD`/`CI`/`CR`/`VD`/`VI`/`VR`/`FA`/`FC`/`FD`/`HA`/`HF`/`HM`/`PI`** | `422` | `leg_not_positionable` | Body carries `path_terminator` and `ProcedureLeg.unpositionable_reason` verbatim. **422, not 404**: the leg exists and is displayable, it simply has no defensible coordinate (`architecture.md` risk 4). |
| Leg is positionable but its fix did not resolve | `422` | `leg_not_positionable` | Same code, different `message` — the provider already distinguishes the two in `unpositionable_reason`. |
| Fix ident not in the index | `404` | `fix_not_found` | Searched as a fix, then as a navaid. |
| Fix ident matches >1 region and no `region_code` given | `409` | `fix_ambiguous` | `candidates` lists them; the panel asks. Guessing "the nearest" here would place the aircraft on the wrong continent. |
| No published hold at that fix | `404` | `hold_not_found` | |
| Altitude needed and neither request nor navdata supplies one | `422` | `altitude_required` | `waypoint` without `altitude_ft` is caught by pydantic (also 422); this is for a hold or a leg with no constraint. |
| **Hold inbound course is magnetic and no variation source exists** | `422` | `magnetic_variation_unavailable` | D11. The message asks for an explicit `heading_deg`. |
| Navdata index absent, building or errored | `503` + `Retry-After` | `navdata_unavailable` | `Retry-After: 5` while `building`, `60` while `unavailable`/`error`. Body carries `navdata_status`. Matches `navdata-provider.md` §12 exactly. |
| Adapter does not declare a required flag | `501` | `capability_unavailable` | §7.2. Apply only. |
| Adapter raised anything else (connection refused, timeout, write error) | `502` | `sim_unreachable` | We are a gateway to the simulator; `502 Bad Gateway` is literally the case. Never a 500. |
| Malformed body (unknown `kind`, latitude 91, `extra` field) | `422` | FastAPI's own validation body | Not remapped — the standard shape is what the generated client expects. |

### 8.3 The AIRAC-staleness case, explicitly

There is no "stale cache" error, and that is deliberate. The provider's cache key is a fingerprint
whose primary component is the AIRAC cycle (`navdata-provider.md` D6); a mismatch **deletes and
rebuilds**. So a stale cycle surfaces as `state == "building"` → `503` + `Retry-After: 5`, and the
panel shows the progress it is already receiving over the WebSocket. The only staleness this
manager reports is informational: `ResolvedPlacement.airac_cycle`, carried so that a training
profile saved on 2607 and reloaded on 2610 can be diffed (manager 14's "degrade gracefully"
requirement).

---

## 9. `SimAdapter` / `Capabilities` additions

**None. This design requires no change to `core/sim_adapter.py`, to `Capabilities`, to
`FakeSimAdapter` or to `adapters/xplane/`.**

That is stated as a positive finding, not an omission:

- `set_position(position, heading_deg)` and `apply_setup(setup)` are exactly the two operations the
  placement pipeline needs, in exactly that order.
- `can_set_position` and `can_set_aircraft_state` are exactly the two flags §7.2 gates on.
- `FakeSimAdapter` already declares both `True` and implements both faithfully, including the
  `heading % 360` normalisation and the `applied_setup` test affordance the contract suite uses.

**Consequence for scheduling:** the "never parallelise a contract change" rule does not bind this
manager. There is no serialised foundation step in `core/sim_adapter.py`, so the tracks in §14 can
be dispatched in a single message.

### 9.1 The one contract test this manager adds

The pipeline rests on an adapter-visible property that the suite does not currently assert: **that
a setup applied immediately before a teleport survives the teleport.** That is not obvious — the
X-Plane adapter freezes and releases the flight model around both calls, and a naive
implementation could have `set_position` clobber the speed `apply_setup` just wrote. Issue #39's
whole point is that arriving without the commanded speed kills the session.

So `tests/adapters/test_contract.py` gains one parametrised test:

```python
async def test_setup_then_position_arrives_at_the_commanded_speed(adapter): ...
```

It applies `AircraftSetup(ias_kt=…, altitude_ft=…, heading_deg=…)`, then teleports a short relative
hop (`HOP_DISTANCE_NM`, per that file's existing rules — no absolute coordinates, restore in a
`finally`), and asserts the read-back speed is the commanded one. It runs against the Fake in CI
and against X-Plane under `-m sim`.

**No capability flag is added, so no other contract test is required.** Every other guarantee this
manager needs is already asserted by the existing 24 cases.

---

## 10. Dataref mapping (X-Plane)

**No new dataref. `adapters/xplane/` is not touched by issue #9.**

The mapping already exists and is validated; it is reproduced here only so the reader can see that
the server never approaches it:

| Interface method | X-Plane, in `adapters/xplane/xplane_adapter.py` |
|---|---|
| `set_position` | Freeze (`override_planepath[0] = 1`) → write `local_x/y/z` (world coords are read-only and derived) → write the velocity vector `local_vx/vy/vz` + `psi` along the target heading → release in a `finally` → clear the crash state with `sim/operation/fix_all_systems`. |
| `apply_setup` | The same freeze around the attitude writes (issue #37), plus the per-field dataref writes. |
| world → local frame | `core/local_frame.py`, a rigid ECEF rotation from an origin *measured* from the aircraft. **`lat_ref`/`lon_ref` are never trusted.** |

Two consequences this manager must respect and does:

1. **The server writes setup then position, in that order** (§6.1), which is the order the adapter's
   freeze/release protocol expects.
2. **The server never asks the adapter to freeze, pause or unpause.** The feature spec's
   "pause the simulator, write, unpause" is an *adapter* implementation detail, and the adapter's
   validated procedure supersedes it. `server/` has no pause concept and must not acquire one.

**MSFS (Phase 5).** `set_position` maps to `SimConnect`'s `SIMCONNECT_DATA_INITPOSITION`, which
takes latitude/longitude/altitude/heading/airspeed **in one structure** — meaning the
setup-then-position split collapses into a single call there. That is entirely inside
`MSFSAdapter`; this API's request and response models are unchanged, which is precisely the Phase 5
measure of success. Expect `can_set_aircraft_state` to be narrower on MSFS (mass and some
configuration are locked), so `dropped_setup_fields` will be non-empty and §7.3's filtering is what
keeps placements working there at all.

---

## 11. `core/` logic

Two new modules. Both are pure, both are fully unit-testable with `InMemoryNavdataProvider` and no
simulator, and neither imports anything from `server/` or `adapters/`.

### 11.1 `core/placements.py`

Public surface:

```python
# Types
PlacementKind, AnchorKind, HoldEntry, PlacementWarningCode, PlacementErrorCode
FinalSpec, ShortFinalSpec, PatternSpec, ParkingSpec, CoordinateSpec,
WaypointSpec, ProcedureSpec, HoldSpec, PlacementSpec
PlacementAnchor, PlacementWarning, ResolvedPlacement
PlacementResolutionError            # carries .code and the context fields of §8.1

# Constants
LONG_TELEPORT_WARNING_NM: float = 100.0
GROUND_TOLERANCE_FT: float = 100.0
PLACEMENT_CATALOGUE: tuple[PlacementDescriptor, ...]   # the 14 rows of §3, as data

# The entry point
def resolve_placement(
    provider: NavdataProvider,
    spec: PlacementSpec,
    *,
    current_position: GeoPosition | None = None,
) -> ResolvedPlacement: ...

# The per-anchor resolvers, public so they are individually testable
def resolve_final(provider, spec: FinalSpec | ShortFinalSpec) -> ResolvedPlacement: ...
def resolve_pattern(provider, spec: PatternSpec) -> ResolvedPlacement: ...
def resolve_parking(provider, spec: ParkingSpec) -> ResolvedPlacement: ...
def resolve_coordinate(spec: CoordinateSpec) -> ResolvedPlacement: ...
def resolve_waypoint(provider, spec: WaypointSpec) -> ResolvedPlacement: ...
def resolve_procedure_leg(provider, spec: ProcedureSpec) -> ResolvedPlacement: ...
def resolve_hold(provider, spec: HoldSpec) -> ResolvedPlacement: ...

# Runway geometry for an arbitrary distance — see 11.4
def final_placement_at(runway, distance_nm, *, glideslope_deg=DEFAULT_GLIDESLOPE_DEG,
                       ias_kt=None, category=DEFAULT_APPROACH_CATEGORY) -> Placement: ...
```

`resolve_placement` is a `match` on `spec.kind` with `assert_never` in the default arm, mirroring
`core.geodesy.resolve_runway_placement`. It is the only function the server calls.

**`current_position` is a `GeoPosition`, not an adapter.** That is what keeps `core/` sim-free
while still producing the `long_teleport` warning. `None` simply suppresses the warning.

### 11.2 `core/radio_tuning.py`

```python
def tune_ils(setup: AircraftSetup, ils: Ils | None) -> tuple[AircraftSetup, tuple[PlacementWarning, ...]]:
    """Set ils_freq_khz, nav1_freq_khz and obs1_deg from a localizer.

    Assignment, never arithmetic: Ils.frequency_khz is already in AircraftSetup's
    unit (108 000–111 950 kHz) and Ils.localizer_mag_deg is already magnetic,
    which is what an OBS course is. A None `ils` returns the setup unchanged plus
    a `no_ils_published` warning.
    """


def tune_navaid(setup: AircraftSetup, navaid: Navaid, *, radio: Literal["nav1", "nav2"]) -> AircraftSetup:
    """Tune a VOR/LOC/DME onto a NAV radio. Refuses a navaid whose tunable_radio is not 'nav'."""
```

`tunable_radio` is checked rather than assumed: an NDB's 380 kHz would fail `nav1_freq_khz`'s
`ge=108_000` validation, and `navdata-provider.md` §5.5 added that field specifically to close this
seam. `AircraftSetup` has no `adf_freq_khz` today, so `tune_navaid` on an NDB raises
`ValueError` — a programmer error, caught in a unit test, never reachable from the API because the
`waypoint` placement does not tune anything.

### 11.3 What stays in `core/geodesy.py`

Nothing in this design changes `core/geodesy.py`. It is being edited by #6 and must not be edited
concurrently. `core/placements.py` **consumes**:
`final_approach_point`, `final_placement`, `pattern_placement`, `resolve_runway_placement`,
`coordinate_placement`, `waypoint_placement`, `glideslope_altitude_ft`, `distance_and_bearing`,
`point_at_distance_and_bearing`, `APPROACH_CATEGORY_VAT_KT`,
`APPROACH_CATEGORY_CIRCLING_IAS_KT`, `DEFAULT_APPROACH_CATEGORY`, `GROUND_IAS_KT`,
`FINAL_DISTANCES_NM`, `PATTERN_PLACEMENTS`, `DEFAULT_GLIDESLOPE_DEG`,
`DEFAULT_PATTERN_ALTITUDE_AGL_FT`, `SHORT_FINAL_DISTANCE_NM`, `Placement`.

### 11.4 The seam with `feature/placement-geodesy` (#6)

`core/geodesy.py` states today, in its own module docstring, that holding entries and procedure legs
are *deliberately absent* because both resolve against published navdata. #6 is what adds them.
This design's dependency on it is precise:

| What #6 is expected to expose | What `core/placements.py` does until it lands |
|---|---|
| A holding-entry placement taking a fix, an inbound **true** course, a turn direction, a leg length/time and an entry point | `resolve_hold` places **over the fix**, at the hold altitude, on the inbound course, and ignores `HoldSpec.entry` — returning a `hold_entry_not_implemented` note in `warnings`. The endpoint, the model and the tests do not change when #6 lands. |
| A procedure-leg placement resolving `AF`/`RF` arc geometry | `resolve_procedure_leg` uses `core.geodesy.waypoint_placement` on `leg.fix`, with `next_fix`/`previous_fix` taken from the adjacent positionable legs so the heading is the leg being flown. That is already correct for `IF`/`TF`/`CF`/`DF` — i.e. the overwhelming majority — and merely approximate at the midpoint of an arc. |
| `final_placement_at(runway, distance_nm, …)` for an arbitrary distance | It lives in `core/placements.py` for now, with a test asserting it reproduces `core.geodesy.final_placement` **exactly** for all seven named presets (label included). When #6 or a follow-up moves it next to `final_placement`, that test becomes the migration's proof. |

**The API contract is identical in both worlds.** That is the whole reason `entry` is in `HoldSpec`
from day one rather than added later: the UI generated against this schema does not regenerate.

---

## 12. UI panel outline

Issue #10, a separate session. This section fixes only the seam, following the conventions already
in `ui/src/api/instructorApi.ts` and `ui/src/features/aircraft/`.

### 12.1 Files — all new, no shared file edited

```
ui/src/features/position/
    positionApi.ts        # instructorApi.injectEndpoints — see below
    positionSlice.ts      # ONE RTK slice, client-side selection state only
    placements.ts         # display catalogue: labels, hints, widget kinds, keyed Record<PlacementKind, …>
    PositionPanel.tsx     # the tab
    PlacementPicker.tsx / PlacementPreviewCard.tsx
    *.test.tsx / *.test.ts
```

`ui/src/api/instructorApi.ts` is **not edited**. Endpoints are added with
`instructorApi.injectEndpoints({ endpoints: … })` and the two new tag types with
`instructorApi.enhanceEndpoints({ addTagTypes: ['PlacementCatalogue'] })`, both from
`positionApi.ts`. This is RTK Query's supported code-splitting mechanism and it makes "adding a
manager adds files rather than editing shared ones" literally true.

`ui/src/api/models.ts` gains alias lines for the new schemas. Every type is an alias into
`schema.d.ts`, regenerated by `npm run generate:api` — **no hand-written API types** (CLAUDE.md).
The server for that command starts as `uvicorn server.app:create_app --factory --port 8000`;
`server/app.py` exposes a factory, not a module-level `app`.

### 12.2 RTK Query endpoints

```ts
getPlacementCatalogue: builder.query<PlacementCatalogue, PlacementCatalogueArgs>({
  query: ({ airportIcao, runwayIdent, include }) => ({ url: 'position/placements', params: … }),
  providesTags: ['PlacementCatalogue'],
}),
previewPlacement: builder.mutation<PlacementPreview, PlacementSpec>({
  query: (spec) => ({ url: 'position/preview', method: 'POST', body: spec }),
  // No invalidatesTags: preview is SAFE. It writes nothing and must not evict the cache.
}),
applyPlacement: builder.mutation<PlacementResult, PlacementSpec>({
  query: (spec) => ({ url: 'position/apply', method: 'POST', body: spec }),
  invalidatesTags: ['AircraftState'],
}),
```

`previewPlacement` is a `mutation` purely because the argument is a body, not because it mutates.
The comment above it is mandatory in the implementation — a future reader will otherwise "fix" it
by adding `invalidatesTags`.

### 12.3 The slice

One slice, client-only state, exactly as `aircraftSlice` holds only optimistic bookkeeping:

```ts
interface PositionPanelState {
  airportIcao: string | null;
  runwayIdent: string | null;
  kind: PlacementKind | null;
  params: Partial<Record<string, number | string | boolean>>;  // widget values, per kind
  lastAppliedAt: string | null;   // ISO timestamp, for the "placed" toast
  lastError: string | null;
}
```

Server state — the catalogue, the preview, the result — lives in RTK Query and never here.

### 12.4 Gating and layout

- The whole tab is enabled iff `catalogue.can_apply || navdata_state === 'ready'`; the **Place**
  button is enabled iff `preview.can_apply`, showing `blocked_reason` when not.
- Each of the 14 options renders from `catalogue.options`, disabled entries greyed with `reason`
  visible — `Record<PlacementKind, PlacementDisplay>` in `placements.ts` makes a server-side
  addition fail the typecheck until the panel handles it, exactly as `controls.ts` does today.
- `warnings` render as a list under the preview; `airborne_placement_at_zero_speed` renders in the
  error colour without blocking the button.
- **Tablet-first.** Airport (remembered) → runway chips → placement chips → one large **PLACE**
  button. A remembered airport puts a 10 NM ILS final **two taps** from the tab, which is the Phase
  1 exit criterion. `include=runways` keeps that path to one catalogue fetch plus one preview.

---

## 13. Test plan

Everything below runs in CI against `FakeSimAdapter` + `InMemoryNavdataProvider`. No simulator, no
navdata file.

### 13.1 `core/` unit tests — `tests/core/test_placements.py`

Built on a hand-written `InMemoryNavdataProvider` fixture (§13.4). Concrete reference values,
because a placement test with no number in it tests nothing:

| Test | Assertion |
|---|---|
| 10 NM final, threshold elevation 2000 ft, 3° | `placement.position.altitude_ft == approx(5184.36, abs=0.01)` — 2000 + tan(3°)·10·6076.115486 |
| 3 NM final, threshold 0 ft, 3° | `955.31 ft (abs=0.01)` — 318.4357 ft/NM × 3 |
| `short_final`, threshold 0 ft, 3° | `318.44 ft (abs=0.01)`, label ends `"short final"` |
| 10 NM final on a runway whose `Ils.glideslope_deg = 3.20` | `3397.08 ft (abs=0.1)` above threshold, and `resolved.glideslope_deg == 3.20` |
| 10 NM final on a runway with **no** ILS | `glideslope_deg == 3.0`, warning `nominal_glideslope_used`, no radio fields in `setup` |
| Final heading | `placement.heading_deg == approx(runway.true_bearing_deg)` |
| Final distance | `distance_and_bearing(runway.threshold, placement.position)[0] == approx(10.0, abs=1e-6)` |
| `final_placement_at` vs the presets | For all seven names in `FINAL_DISTANCES_NM`, identical `position`, `heading_deg`, `ias_kt` **and `label`** to `core.geodesy.final_placement` |
| `left_downwind` altitude default | `runway.elevation_ft + 1000.0`, warning `pattern_altitude_defaulted` |
| `right_downwind` is the mirror of `left_downwind` | Equal cross-track distance from the centreline, opposite side |
| ias default, final, category C | `140.0` (`APPROACH_CATEGORY_VAT_KT["C"]`) |
| ias default, downwind, category C | `180.0` (`APPROACH_CATEGORY_CIRCLING_IAS_KT["C"]`) |
| ias default, no category | `120.0` — `DEFAULT_APPROACH_CATEGORY == "B"` |
| explicit `ias_kt` beats the category | `ias_kt=88` with `approach_category="D"` → `88.0` |
| gate placement | `ias_kt == 0.0`, `heading_deg == stand.heading_true_deg`, warning `ground_elevation_estimated` |
| `coordinate` at 5000 ft with no `ias_kt` | `ias_kt == 0.0` **and** warning `airborne_placement_at_zero_speed` |
| `coordinate` on the ground | `ias_kt == 0.0`, **no** warning |
| `waypoint` heading with a `next_fix` | Equals `distance_and_bearing(fix, next)[1]` |
| procedure leg with `B,FL140,10000` | `altitude_ft == 10000.0`, warning `altitude_from_constraint_band` |
| procedure leg with `J,05500,05500` | `altitude_ft == 5500.0`, no band warning |
| procedure leg with `-,210` speed | `ias_kt == 210.0` |
| **procedure leg with a `CA` terminator** | raises `PlacementResolutionError(code="leg_not_positionable")`, `path_terminator == "CA"` |
| `VA`, `FM`, `VM`, `HM`, `PI` | same, parametrised |
| positionable terminator with an unresolved fix | `code == "leg_not_positionable"`, different message |
| hold with a fix carrying `magnetic_variation_deg` | `heading_deg == (inbound_course_mag_deg + variation) % 360` |
| hold with **no** variation source and no `heading_deg` | raises `code == "magnetic_variation_unavailable"` |
| hold with an explicit `heading_deg` | uses it, no error |
| long teleport | `current_position` 200 NM away → warning `long_teleport`; 50 NM away → none |
| ILS tuning | `setup.ils_freq_khz == 110_100`, `setup.nav1_freq_khz == 110_100`, `setup.obs1_deg == 323.0` for an `Ils(frequency_khz=110_100, localizer_mag_deg=323.0)` |
| `tune_radios=False` | none of the three radio fields is set |
| unknown airport / runway / stand / procedure / fix / hold | each raises its own `PlacementErrorCode`, parametrised |
| every `PlacementKind` resolves | Parametrised over all 14 against the fixture world — a new kind cannot be added without a test |

`tests/core/test_radio_tuning.py` additionally asserts that `tune_navaid` refuses an NDB
(`tunable_radio == "adf"`) and a glideslope (`None`).

### 13.2 Contract test — `tests/adapters/test_contract.py`

One added case, parametrised over every adapter (§9.1):
`test_setup_then_position_arrives_at_the_commanded_speed`. It obeys that file's existing rules:
relative hop, no absolute coordinate or altitude, restore in a `finally`, no skips.

**No capability flag is added, so no other contract addition is required.**

### 13.3 Server tests — `tests/server/test_position_api.py`

`TestClient(create_app())` with `OIS_ADAPTER=fake` and a monkeypatched `get_navdata()` returning the
fixture provider.

| Test | Assertion |
|---|---|
| Catalogue with no anchor | `200`, exactly 14 options, `can_apply is True`, `anchors is None` |
| Catalogue with `airport_icao` | `anchors.runways` populated, `parking` and `procedures` **empty** (default `include`) |
| Catalogue with `include=parking,procedures` | both populated |
| Catalogue against `Capabilities(can_set_position=False)` | `200`, `can_apply is False`, `blocked_reason` names `can_set_position`, all 14 options still present |
| Catalogue while navdata is `building` | `200` with no anchor requested; `503` + `Retry-After: 5` with one |
| **Preview does not move the aircraft** | `GET /api/state` before and after are byte-identical |
| Preview against `can_set_position=False` | `200`, `can_apply is False` — preview is never gated |
| Preview with a disconnected adapter | `200`, `distance_from_aircraft_nm is None` |
| Apply a 10 NM final | `200`; `state.latitude/longitude` equal `resolved.placement.position` to 1e-9; `position_error_nm < 1e-6`; `altitude_error_ft == approx(0)`; `heading_error_deg == approx(0)` |
| Apply writes the setup **before** the position | An adapter double recording call order asserts `apply_setup` precedes `set_position` |
| Apply is idempotent | Two identical applies → identical `state` |
| Apply an airborne placement with `can_set_aircraft_state=False` | `501`, `code == "capability_unavailable"`, message names the flag; `GET /api/state` unchanged |
| Apply a **gate** placement with `can_set_aircraft_state=False` | `200` — ground placements need only `can_set_position` |
| Apply with `can_set_fuel_payload=False` and a setup carrying mass | `200`, `dropped_setup_fields == ["fuel_kg", "gross_weight_kg"]`, warning `setup_field_dropped` |
| Apply when the adapter raises | `502`, `code == "sim_unreachable"` |
| Unknown airport / runway / stand / procedure / leg / fix / hold | the status and `code` of §8.2, parametrised |
| `CA` leg | `422`, `code == "leg_not_positionable"`, `path_terminator == "CA"` |
| Ambiguous fix | `409`, `code == "fix_ambiguous"`, `len(candidates) >= 2` |
| Unknown `kind` in the body | `422`, FastAPI's validation shape |
| Extra field in the body | `422` (`extra="forbid"`) |
| **OpenAPI schema** | `GET /openapi.json` contains a `PlacementSpec` discriminator whose mapping has exactly the 14 kinds, and `PlacementErrorDetail` is referenced from the `404`/`409`/`422`/`501`/`502`/`503` responses. This is what guards the generated TypeScript union. |

The `/api/navdata/` router's own server tests belong to its track and follow
`navdata-provider.md` §11.

### 13.4 Fixture strategy

`tests/fixtures/navdata_world.py` builds an `InMemoryNavdataProvider` for a **fictional** airport
`ZZZZ`, hand-written in Python:

- Airport `ZZZZ`, elevation 2000 ft, `magnetic_variation_deg = -1.0`.
- Two runway ends, `09`/`27`, `true_bearing_deg` 90.0/270.0, `length_m = 3000`, `elevation_ft = 2000`.
  `09` carries an `Ils(frequency_khz=110_100, localizer_mag_deg=91.0, glideslope_deg=3.0)`; `27` has none.
- Parking: one `gate` `"A1"`, one `tie_down` `"T7"`.
- Fixes: `ZULU1` (enroute, unique), `DUPE` in two regions (for `fix_ambiguous`).
- One SID with an `IF`, a `TF` carrying `B,FL140,10000`, and a `CA` climb leg.
- One published hold at `ZULU1`; one at a fix with no variation source.

**No navdata file is committed, at any point.** The existing
`tests/core/navdata/test_no_navdata_committed.py` guard already enforces that repository-wide and
this manager adds nothing it needs to be relaxed for. Round coordinates are chosen so glideslope
and pattern arithmetic is checkable by hand.

### 13.5 `@pytest.mark.sim` — never in CI

`tests/sim/test_live_position_api.py`:

1. Read the aircraft's current position from the live adapter.
2. Build an **in-memory** provider containing a single synthetic runway derived from that
   position — so the test never depends on the user's navdata being present or on any particular
   airport being loaded.
3. `POST /api/position/preview` and assert it moved nothing.
4. `POST /api/position/apply` a 5 NM final; assert `position_error_nm < 0.05` and
   `abs(heading_error_deg) < 2.0`.
5. Restore the original position in a `finally`.

Distances stay short deliberately: issue #36 is that long hops trigger a scenery reload the adapter
cannot yet follow (§15.2), and this suite tests the API, not that defect.

### 13.6 The commands the implementer and tester run

```bash
pytest                       # unit + contract + server, no simulator
pytest -m sim                # X-Plane on :8086
ruff check . && ruff format --check .
mypy .
cd ui && npm run lint && npm run typecheck && npm test && npm run build
```

Nothing in this design needs anything else.

---

## 14. Parallelisation

### 14.1 The one serialised step, done first, alone

**`server/deps.py` gains `get_navdata()` / `reset_navdata()` and the `OIS_NAVDATA`,
`OIS_XPLANE_PATH`, `OIS_NAVDATA_CACHE_DIR` settings.** It does not exist on `dev` today (there is no
`navdata` reference anywhere in `server/`), it is specified verbatim in
[`navdata-provider.md` §12](navdata-provider.md), and both this manager and the navdata router need
it. It is shared wiring, so it follows the same rule as a `SimAdapter` contract change: **made once,
by one agent, before dependent work branches.** It is roughly fifteen lines mirroring
`get_adapter()`, and it performs no I/O on construction.

**There is no other serialised step.** In particular there is no `SimAdapter`/`Capabilities` change
(§9) and no navdata schema migration.

### 14.2 Tracks that can be dispatched in a single message

Once §14.1 has landed and this document is agreed, four tracks run concurrently on disjoint
directories:

| Track | Owns (write) | Reads | Barrier |
|---|---|---|---|
| **A — position backend** | `core/placements.py`, `core/radio_tuning.py`, `server/position.py`, `server/capability_gate.py`, one `include_router` line in `server/app.py` | this document, `core/geodesy.py`, `core/navdata/` | CI green on its PR |
| **B — position tests** | `tests/core/test_placements.py`, `tests/core/test_radio_tuning.py`, `tests/server/test_position_api.py`, `tests/fixtures/navdata_world.py`, one added case in `tests/adapters/test_contract.py`, `tests/sim/test_live_position_api.py` | this document only | The suite is written against §5 and §8 **without waiting for A** |
| **N — navdata router** | `server/navdata_api.py`, `tests/server/test_navdata_api.py`, one `include_router` line in `server/app.py` | `navdata-provider.md` §12 only | CI green on its PR |
| **C — UI panel (#10, separate session)** | `ui/src/features/position/**`, alias lines in `ui/src/api/models.ts`, regenerated `ui/src/api/schema.d.ts` | this document, then the real OpenAPI schema | `npm run generate:api` against A's server; until then, the models of §5 |

The write sets are disjoint. The single overlap — `server/app.py`'s `include_router` lines — is two
one-line additions in the same place; A and N coordinate by landing in either order, whichever PR
is second rebasing over a one-line change.

Within track A there is a further natural split (`core/placements.py` before `server/position.py`),
but it is a single agent's ordering, not a parallelisation.

### 14.3 What must never be parallelised here

- `server/deps.py`'s `get_navdata()` (§14.1).
- `core/geodesy.py` — being edited by `feature/placement-geodesy` (#6). **This manager does not
  touch it.** `final_placement_at` deliberately lives in `core/placements.py` for exactly this
  reason (§11.4).
- `server/app.py`'s `_CONTROL_FIELDS` — being edited by `feature/autopilot-setup` (#41). **This
  manager does not touch it** (§7.3).
- `core/navdata/schema.py` — single-owner by standing rule.
- Merges to `dev`/`main`, and release tagging.

### 14.4 Relative to the rest of Phase 1

This manager is a separate `feature/position-api` branch in its own git worktree, with its own
planner → implementer → tester cycle, opening one PR to `dev`. It runs concurrently with #8 and
#10; CI on each PR is the integration barrier. It merges **after** #6 if #6 is close, because
`resolve_hold` and `resolve_procedure_leg` get simpler when it lands — but it does not *block* on
it, because §11.4 defines behaviour in both worlds and the HTTP contract is identical either way.

---

## 15. Open questions and risks

### 15.1 Magnetic → true for holds — the only genuine unknown (D11)

`Hold.inbound_course_mag_deg` is magnetic (verified in `navdata-provider.md` §5.10);
`Placement.heading_deg` is true. The project has **no world magnetic model** and adding one
contradicts the PyInstaller bundle constraint, so the conversion must come from published
variation.

Two things are unresolved:

1. **Sign convention.** `Airport.magnetic_variation_deg` documents "positive east";
   `Navaid.magnetic_variation_deg` documents nothing. `earth_nav.dat` publishes variation with a
   convention that is not recorded anywhere in this repository.
   **What resolves it:** a five-minute check of `core/navdata/xplane_native/earth.py` against a
   known station (e.g. a US VOR with ~13°W variation) and a one-line docstring addition to
   `Navaid.magnetic_variation_deg`. It must happen **before** the hold placement is trusted, and
   the interim behaviour (§8.2: fail with `magnetic_variation_unavailable` unless `heading_deg` is
   supplied) is safe regardless of the answer.
2. **Whether it is acceptable at all** to use a *nearby* station's variation for a fix tens of
   miles away. The `magnetic_variation_assumed` warning exists to make that visible.
   **What resolves it:** a decision from the user on whether a hold placement without an explicit
   heading is worth having at all, or whether the panel should simply always ask.

### 15.2 Long teleports across a scenery reload — issue #36, which this API exposes

X-Plane relocates the local frame origin during a scenery reload, so the `local_x/y/z` written
before the reload denote a different world position and `_await_arrival` polls a target the
aircraft cannot converge on. That is [#36](https://github.com/Santisoutoo/open-instructor-station/issues/36),
an **adapter** defect, and it fails after a full 30 s wait.

**This API is what makes it reachable in one tap.** `{"kind": "final", "airport_icao": "KJFK"}` from
LEMD is a routine instructor action, not an edge case.

Mitigation here, and it is only a mitigation: `LONG_TELEPORT_WARNING_NM = 100.0` produces a
`long_teleport` warning in the preview, and a read-back beyond tolerance produces
`position_not_verified` in the result rather than a silent success. **The API never refuses a long
teleport** — refusing would hide an adapter bug behind a product limitation. #36 is the real fix
and it should land before Phase 1's exit criteria are demonstrated across airports.

### 15.3 Ground placements arrive at an estimated elevation

`apt.dat` publishes no per-stand elevation, so `ParkingStand.position.altitude_ft` is the airport
datum (`navdata-provider.md` §5.6). At an airport with sloping apron that is metres out, and a
teleport writes an MSL altitude into the local frame — so the aircraft may arrive slightly sunk or
slightly floating before the physics settles it.

Warned (`ground_elevation_estimated`), not solved. **What resolves it:** a measurement at a real
airport with a known apron slope, and, if it matters, an adapter-side "snap to ground" using the
simulator's own terrain probe — which would be a `SimAdapter` addition and therefore a serialised
contract change, out of scope for Phase 1.

### 15.4 Approach-category defaults are a guess, by construction

`APPROACH_CATEGORY_VAT_KT` is per category, not per airframe: within category C a light business jet
and a 737 land 15 kt apart. The catalogue's default is `B` (120 kt on final), which is deliberately
*fast* for a trainer and *slow* for a heavy — and slow is the failure that kills.

This is a documented limitation of `core/geodesy.py`, not something this API can fix. What it *can*
do, and does, is put `approach_category` in every request and `ias_kt` above it. **Open question for
the user:** should the panel remember a per-aircraft category (keyed on the loaded aircraft ICAO
the adapter could report), rather than defaulting to B on every session? That would need a new
`SimAdapter` read — a contract change, and therefore a Phase 2 decision, not a Phase 1 one.

### 15.5 Two places now map an `AircraftSetup` field to a capability

`server/app.py::_CONTROL_FIELDS` and `server/capability_gate.py::SETUP_FIELD_CAPABILITY` overlap.
That is a deliberate, temporary duplication (§7.3) taken to avoid a merge conflict with
`feature/autopilot-setup` in a shared file. **Follow-up issue:** once #41 is on `dev`, move
`_CONTROL_FIELDS`' capability column onto `SETUP_FIELD_CAPABILITY` so there is one source. A test
asserting the two agree for every field in `AircraftSetup.model_fields` should be added by track B
**now**, so the duplication cannot silently diverge in the meantime.

### 15.6 Preview/apply consistency depends on navdata not moving underneath

Resolution is a pure function of (navdata, spec), so preview and apply agree — unless the index
rebuilds between the two calls because a new AIRAC cycle appeared. The window is seconds wide and
the consequence is that the aircraft lands on a slightly different, *newer* procedure than the one
previewed.

Not solved, and deliberately so: adding an optimistic-concurrency token to defend a window that
opens once every 28 days would cost more than it saves. `ResolvedPlacement.airac_cycle` is carried
in both responses, so a UI that cares can compare them and re-preview. **Flagged rather than
papered over.**

---

## 16. Non-goals, recorded as decisions

- **No runway-threshold ("line up for takeoff") placement.** Not in the feature spec's Phase 1 list.
  It is a five-line addition to §3 the day it is wanted, and adding it now would make the catalogue
  15 without a spec item behind it.
- **No batch placement.** One aircraft, one placement, one request.
- **No undo.** Restoring a previous position is manager 12 (Session Recorder), and it restores
  through this same endpoint with a saved `CoordinateSpec`.
- **No terrain awareness.** The API will happily place an aircraft inside a hill at a coordinate the
  instructor asked for. Terrain data is not in scope for Phase 1 and inventing a partial check would
  give false confidence.
- **No persistence.** A `PlacementSpec` is not stored anywhere by this manager. It is a `core/`
  pydantic model precisely so that manager 14 can serialise it into a training profile and manager 2
  into a scenario YAML, without either of them importing anything from `server/`.
