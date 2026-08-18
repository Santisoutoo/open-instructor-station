# AI Traffic Manager — design

**Status:** designed, not yet implemented.
**Issue:** [#20](https://github.com/Santisoutoo/open-instructor-station/issues/20), feature spec manager 13
([`../feature-spec.md`](../feature-spec.md#13-ai-traffic-manager)), ⭐⭐⭐⭐⭐.
**Phase:** 3 — Instructor Map + AI Traffic
([`../roadmap.md`](../roadmap.md#phase-3--instructor-map--ai-traffic)).
**Depends on:** `core/geodesy.py` (runway/geodesic primitives, reused verbatim rather than
re-derived), `core/atmosphere.py` (`tas_from_ias`), the shipped `NavdataProvider` (runway lookup),
[`../../bridge/README.md`](../../bridge/README.md) (the constraints this design must honour).
**Enables, but does not itself wire:** `core/scenarios/models.py`'s `ScenarioTrafficBlock` and the
guarded no-op traffic step in `server/scenario_engine.py`
([`scenario-generator.md`](scenario-generator.md) §6.3 step 4) — see §10.7.

This is **the first component in the whole project that runs inside the simulator.** Everything
before it has been reachable from outside X-Plane over its Web API; spawning and driving AI
aircraft, ground vehicles and birds is **the one thing that API cannot do**, which is the entire
reason the optional `bridge/` XPPython3 plugin exists at all. The consequence that shapes every
decision in this document is stated three times in the repository already (feature spec, roadmap,
`bridge/README.md`) and is restated once more, because it is the one rule this design must not
get wrong: **the application works 100% without the bridge, for everything except AI traffic.**

Binding rules live in [`../../CLAUDE.md`](../../CLAUDE.md); layers in
[`../architecture.md`](../architecture.md). This document never relaxes any of them. The Failures
Manager design ([`failures-manager.md`](failures-manager.md)) is the closest sibling in shape —
capability-free reads, idempotent writes, a catalogue-style pre-flight check — and several of its
lessons are applied here deliberately rather than re-learned.

---

## 0. Decisions at a glance

| # | Decision | Where |
|---|---|---|
| D1 | **`can_spawn_traffic` already exists** on `Capabilities` (added with the Weather/Failures/Fuel-Payload contract batch) and `FakeSimAdapter` already declares it `True`. **No new capability flag.** This design adds the *methods* the flag gates — today nothing implements them, so the flag is truthful but inert. | §4 |
| D2 | **The bridge is reached through the *same* Web API connection the adapter already holds**, via **custom datarefs the plugin registers** (`ois/traffic/*`), probed exactly like `OPTIONAL_DATAREFS` (`xplane_adapter.py` §187) — absence never fails `connect()`. No second port, no second client, no new transport code in `adapters/xplane/`'s connection lifecycle. This is the natural reading of "the bridge is reached through the X-Plane adapter" (architecture.md) and of `bridge/README.md`'s "keep the transport simple." | §5.1 |
| D3 | **`XPlaneSimAdapter.capabilities` becomes computed from instance state set at `connect()`-time** (bridge probe result), not the fixed module constant it is today. This is a small, additive change to the property's *implementation*, not to the `SimAdapter`/`Capabilities` *interface* — `capabilities` still returns a `Capabilities` instance, callers are unaffected. | §4.3, §10.1 |
| D4 | **`Capabilities` is not mutated mid-session.** `bridge/README.md`'s "the adapter flips `can_spawn_traffic` to `False`" is read as *practical effect*, not literal runtime mutation of the object `GET /api/capabilities` already returned — `Capabilities.model_config = ConfigDict(frozen=True)` and its own docstring ("an adapter's capabilities never change at runtime") are respected as written. A bridge that disappears mid-session is a **connectivity fault**, surfaced by the four write methods raising a plain error, not a capability flip. Flagged as a genuine, unresolved tension with `bridge/README.md`'s wording — see §10.1. | §4.3, §10.1 |
| D5 | **The adapter assigns `traffic_id`** (a fresh `uuid4` hex) at spawn time — never the bridge, never `core/`, never `server/`. Mirrors `ArmedFailure.armed_id`'s "server-assigned opaque id," moved one layer down because `FakeSimAdapter` needs the identical behaviour with no server involved. | §3.4, §4.1 |
| D6 | **Capacity limits are adapter-owned, never a `core/` constant.** X-Plane's real cap (19 multiplayer aircraft slots) is a fact about X-Plane, not about the project, and hard-coding it in `core/` would be exactly the mistake rule 2 forbids. Both adapters raise the same `core.traffic.TrafficCapacityExceeded(capacity, active_count)` so the server can build one message regardless of which adapter is active; each adapter chooses its own number. | §3.5, §4.2, §5.4 |
| D7 | **One discriminated request union, one spawn endpoint** — `TrafficSpawnRequest` (`tcas_conflict` / `runway_incursion` / `taxi_traffic` / `approach_sequence` / `custom`), resolved server-side into one or more `TrafficTrack`s, exactly the `PlacementRequest` shape. Four named scenario endpoints would have been four copies of the same resolve-then-spawn plumbing. | §2, §3.3 |
| D8 | **Traffic geometry is computed once, at spawn time, from a single read of the user aircraft's current state — not by a live server-side scheduler.** Unlike Failures' armed triggers (D5 of that design), there is no roadmap requirement for a traffic scenario to *wait* for a condition; "timed to the student's rollout" is satisfied by computing the whole track's internal timing (`t_offset_s` per waypoint) from where the aircraft is *right now* when the instructor taps Spawn. Simpler, and it is what the feature spec's own wording asks for ("traffic paths… are computed in `core/` and sent to the bridge as plain waypoint tracks" — tracks, not live-triggered spawns). Accepted limitation: if the student's speed changes materially after spawn, the timing drifts — same honesty class as Failures' wall-clock delay trigger. | §6.2, §10.3 |
| D9 | **`TrafficTrack` carries `t_offset_s` per waypoint (seconds after spawn), not absolute timestamps.** The bridge is a pure function of elapsed time since it received the track — it holds no clock synchronisation problem with the station. `core/traffic.py::interpolate_track` is the sim-agnostic reference implementation of "where is this entity right now," shared in spirit (not in code — see §10.2) between `FakeSimAdapter` and the bridge. | §3.2, §6.1 |
| D10 | **A dedicated `WS /ws/traffic` stream, owned by this manager's own router**, mirroring `WS /ws/state`. Traffic is architecture.md's own example of "everything continuous… is pushed," and it is a different shape from `AircraftState` (a list, not a singleton) — folding it into `/ws/state` would change that model's shape for every consumer, including ones (Aircraft Control) that have no traffic dependency. Declared here because this manager owns the `TrafficContact` model; the Instructor Map manager (separate design) is the primary consumer. | §2 |
| D11 | **Approach-sequence spawning reuses `core.geodesy.final_approach_point`/`glideslope_altitude_ft` verbatim.** "More aircraft on the ILS" is not new geometry — it is the Position Manager's own final-approach placement, called `n` times. No second implementation of a glidepath. | §6.2 |
| D12 | **Birds and ground vehicles get no dedicated geometry builder in this phase.** The feature spec lists them as spawnable *kinds*, not as a fifth scenario shape; `runway_incursion_track`'s crossing-path geometry already generalises to "something crosses the aircraft's path at a timed moment" for either, and the generic `custom` track type covers anything else. Flagged, not silently dropped — §10.5. | §3.3, §10.5 |
| D13 | **The UI adds its endpoints with `injectEndpoints` (`trafficApi.ts`)** and its own slice (`trafficSlice.ts`) — the rule Weather/Failures kept and Position broke. Adding this manager adds files; `instructorApi.ts` is not edited. | §7 |
| D14 | **The exit-criterion test for "bridge absent" is the centrepiece of the contract suite**, not an afterthought: `test_traffic_methods_refuse_without_the_capability` against a `FakeSimAdapter` subclass declaring `can_spawn_traffic=False` is what roadmap Phase 3 exit criterion 3 cashes out as, in CI, with no simulator. | §8.2 |

---

## 1. Scope

### 1.1 What this manager does

1. **A sim-agnostic traffic vocabulary** in `core/traffic.py` — entity kinds (`aircraft`,
   `ground_vehicle`, `bird`), a waypoint-and-timing track model, and a live-contact model. No
   dataref, no XPPython3, no bridge protocol detail anywhere near it.
2. **Four geometry builders** in `core/` that turn an instructor's intent into a concrete,
   timed `TrafficTrack`, computed against the runway/navdata/aircraft-state inputs already
   available to every other manager:
   - a **TCAS conflict** track, converging on the user aircraft's own projected position;
   - a **runway incursion** track, a crossing timed against the user's own closing speed on the
     runway;
   - an **approach sequence**, `n` aircraft on the same final at named distances, built on the
     Position Manager's own glideslope maths;
   - a **taxi traffic** track, an ordered list of ground points flown at a constant taxi speed.
3. **The `SimAdapter` methods that spawn, despawn and read back traffic**, gated behind the
   already-existing `can_spawn_traffic` flag (D1).
4. **The bridge transport contract** — what a custom-dataref channel through the existing X-Plane
   Web API connection must carry, described precisely enough that `adapters/xplane/` and the
   (separately built) `bridge/` plugin can be implemented against the same document without
   talking to each other first.
5. **The Traffic tab** of the Instructor Panel — spawn forms per scenario shape, a live contact
   list, clear-all.

Feature-spec items covered: the three spawnable kinds (aircraft, ground vehicles, birds) and all
four scenario shapes (TCAS conflict, runway incursion, taxi traffic, approach traffic).

Roadmap Phase 3 exit criteria this manager is responsible for:

- **#3**: *"With the bridge not installed, the application starts, every non-traffic feature
  works, and traffic controls are disabled with a stated reason — verified by a test running
  against an adapter declaring `can_spawn_traffic = False`."* This is a CI-provable, Fake-only
  test (§8.2, D14).
- **#4**: *"With the bridge installed, a TCAS RA scenario and a runway incursion scenario run in
  a live X-Plane."* `@pytest.mark.sim`, never in CI (§8.4).

Exit criteria **#1** and **#2** (the map showing traffic, drag-to-reposition) belong to the
Instructor Map manager (feature-spec manager 5), a sibling Phase 3 design this document does not
own — it only guarantees that manager a `WS /ws/traffic` stream and a `TrafficContact` model to
consume (§2, D10).

### 1.2 What is explicitly out of scope

| Out of scope | Why / owner |
|---|---|
| The Instructor Map's rendering of traffic, drag-to-reposition, click-to-place | Manager 5, a sibling Phase 3 design. This manager only ships the stream and the model it consumes. |
| Wiring `core/scenarios/models.py::ScenarioTrafficBlock` and the guarded no-op traffic step in `server/scenario_engine.py` to real geometry | Anticipated exactly for this moment by `scenario-generator.md` §6.3 step 4, but not required by any Phase 3 exit criterion. A small, mechanical follow-up — §10.7. |
| Whether a spawned aircraft actually trips the *aircraft's own* TCAS instrument | Depends on X-Plane's/the aircraft's own TCAS implementation reading the multiplayer slots the bridge writes to — a live, unverified question until the spike runs (§10.4). This manager's job ends at "the geometry is realistic and the entity is really there." |
| Taxiway-centreline routing (auto-computed ground paths between two named points) | Not attempted — `taxi_traffic_track` takes an explicit ordered point list from the caller (map clicks or a scenario file), the same boundary the Position Manager draws around SID/STAR legs vs. free geometry. §10.5. |
| A dedicated bird-flock or ground-vehicle geometry builder | D12 — generalises from `runway_incursion_track` or the generic `custom` track; not a blocking gap for this phase's exit criteria. |
| Persisting spawned traffic across a server restart | Same accepted loss as Failures' armed set (`failures-manager.md` §10.4) — traffic is regenerated by re-running a scenario or re-tapping Spawn. |
| Per-aircraft-model visual fidelity (which `.acf` the bridge spawns as) | Bridge implementation detail, resolved by the spike (§10.4), never surfaces in `core/` or the wire model — `TrafficKind` says *what kind of thing*, never *which livery*. |

---

## 2. REST endpoints

New router `server/traffic_routes.py`, registered from `server/app.py` exactly as
`position_routes`/`navdata_routes` are (`app.include_router(traffic_routes.router)`). The router
owns its own WebSocket route too (D10), so this manager adds one line to `server/app.py` and
touches nothing else there.

```
GET    /api/traffic/status         -> TrafficStatus
POST   /api/traffic/spawn          -> TrafficSpawnResult
DELETE /api/traffic/{traffic_id}   -> TrafficStatus
POST   /api/traffic/clear          -> TrafficStatus
WS     /ws/traffic                 -> live TrafficContact[] stream
```

| Method | Path | Purpose | Safe? | Idempotent? |
|---|---|---|---|---|
| `GET` | `/status` | Every live contact, plus the adapter's advertised `max_contacts` when known. Capability-free — an adapter without `can_spawn_traffic` answers `contacts: []`. | yes | yes |
| `POST` | `/spawn` | Resolve a `TrafficSpawnRequest` (§3.3) into one or more `TrafficTrack`s and spawn each. Returns every resulting `TrafficContact`. **Not** idempotent — spawning twice creates two entities, same posture as `POST /api/failures/arm`. | no | no |
| `DELETE` | `/{traffic_id}` | Despawn one entity. Idempotent: an unknown or already-gone id is a no-op, 200 either way — the same posture as `clear_failure` on a healthy system, because a client racing a `despawn_after_s` auto-clear should never see an error for something it did nothing wrong to ask for. | no | **yes** |
| `POST` | `/clear` | Despawn every entity this adapter is tracking. The one-tap reset, same shape as Failures' CLEAR ALL. | no | **yes** |
| `WS` | `/traffic` | Pushes the full contact list at `TRAFFIC_STREAM_INTERVAL_S` (2 Hz — traffic does not need the aircraft's 4 Hz; it is background picture, not a control loop) until the client disconnects. | — | — |

### 2.1 Capability gating

Mirrors `server/app.py`'s `CAPABILITY_UNAVAILABLE_STATUS = 501` convention verbatim:

- Adapter does not declare `can_spawn_traffic` → **501**, *"Unavailable on this adapter — the
  'xplane' adapter does not declare can_spawn_traffic, so traffic cannot be spawned."* Applies to
  `/spawn`, `DELETE /{traffic_id}`, `/clear`. `GET /status` and `WS /traffic` are never
  gated — reads degrade (empty list), the same posture as `/api/failures/status`.
- `TrafficCapacityExceeded` (D6) escaping `spawn_traffic` → **409**, *"At capacity: the 'xplane'
  adapter already has 19 of 19 traffic slots in use."* A well-formed request the adapter genuinely
  cannot honour *right now* — 409 rather than 501, because the reason is transient (despawn
  something and it succeeds), unlike a missing capability.
- A named-scenario request (`tcas_conflict`, `runway_incursion`, `approach_sequence`) whose
  `airport_icao`/`runway_ident` does not resolve against the current navdata index → **404**,
  *"Runway 'ZZZZ 36' is not in the current navdata index."* — the same convention
  `position_routes.py` already uses for an unresolvable runway.
- `CapabilityNotSupported` escaping the adapter anyway is caught and mapped to **501** — defence
  in depth, same as every other manager.

Nobody should reach the 501s: the panel disables spawn controls from `GET /api/capabilities`
before a request is ever sent (§7.4).

### 2.2 Validation errors — 422

- An unknown `type` discriminator, or a field forbidden for the chosen type (`extra="forbid"` on
  every variant).
- `distances_nm` empty on `approach_sequence`, `route` with fewer than 2 points on
  `taxi_traffic` — pydantic field constraints (`min_length`).
- `TrafficTrack.waypoints` not strictly time-ordered by `t_offset_s`, or the first waypoint's
  `t_offset_s != 0.0` — the model's own validator (§3.2), so a hand-authored `custom` track and a
  server-resolved one are checked identically.

---

## 3. Pydantic models

All in **`core/traffic.py`** unless stated (mirrors `failures-manager.md` D9's reasoning: this is
sim-agnostic vocabulary a future Scenario Generator step (§10.7) needs to construct with no HTTP
anywhere). Units follow every other model in the project: `_ft` is feet MSL, `_kt` is knots,
`_deg` is degrees, `_s` is seconds, `_nm` is nautical miles, `_m` is metres. All models
`frozen=True`; request models additionally `extra="forbid"`.

### 3.1 Entity vocabulary

```python
TrafficKind = Literal["aircraft", "ground_vehicle", "bird"]

#: Which scenario shape a track was built for — carried for display/label
#: purposes only. The adapter and the bridge never branch on it: a track is a
#: track regardless of how it was produced (feature-spec's own "it does not
#: make decisions").
TrafficScenarioShape = Literal[
    "tcas_conflict", "runway_incursion", "approach_sequence", "taxi_traffic", "custom"
]
```

### 3.2 The track — what the bridge is handed

```python
class TrafficWaypoint(BaseModel):
    """One timed point on a traffic entity's path."""

    model_config = ConfigDict(frozen=True)

    position: GeoPosition = Field(description="Target position; altitude_ft is feet MSL.")
    speed_kt: float = Field(
        ge=0.0,
        description=(
            "Ground speed in knots for the leg starting here. Indicated airspeed for kind="
            "'aircraft' entities flying, a plain ground speed for 'ground_vehicle'/'bird' — "
            "there is no indicated-airspeed reading for a truck."
        ),
    )
    heading_deg: float | None = Field(
        default=None,
        ge=0.0,
        lt=360.0,
        description=(
            "True heading to face AT this waypoint. None: the consumer derives it from the "
            "bearing to the next waypoint (or holds the previous leg's heading on the final "
            "waypoint) — the same fallback order core.geodesy.waypoint_placement uses for a "
            "bare fix."
        ),
    )
    t_offset_s: float = Field(ge=0.0, description="Seconds after spawn this point is reached.")
    on_ground: bool = Field(default=False, description="True for a taxiing or stationary point.")


class TrafficTrack(BaseModel):
    """A complete, timed path for one traffic entity — what SimAdapter.spawn_traffic takes.

    Every field here is something the bridge can act on with no further
    decision-making: "spawn at waypoints[0], move through the rest on schedule,
    despawn after despawn_after_s" is the whole vocabulary (bridge/README.md's
    "it spawns, it moves, it despawns. It does not make decisions.").
    """

    model_config = ConfigDict(frozen=True)

    kind: TrafficKind
    scenario_shape: TrafficScenarioShape = "custom"
    callsign: str = Field(min_length=1, max_length=12, description='e.g. "TFC01", "GND03".')
    label: str = Field(
        min_length=1, description='Human-readable description, e.g. "TCAS conflict, head-on".'
    )
    waypoints: tuple[TrafficWaypoint, ...] = Field(min_length=2)
    despawn_after_s: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Seconds after the LAST waypoint's t_offset_s before automatic despawn. None: the "
            "entity holds at the last waypoint until explicitly despawned."
        ),
    )

    @model_validator(mode="after")
    def _waypoints_are_time_ordered_from_zero(self) -> "TrafficTrack":
        offsets = [wp.t_offset_s for wp in self.waypoints]
        if offsets[0] != 0.0:
            raise ValueError("TrafficTrack.waypoints[0].t_offset_s must be 0.0 — spawn is t=0.")
        if offsets != sorted(offsets) or len(set(offsets)) != len(offsets):
            raise ValueError(
                "TrafficTrack.waypoints must be strictly increasing by t_offset_s, no ties."
            )
        return self
```

### 3.3 Spawn requests — one discriminated union (D7)

```python
class TcasConflictSpawnRequest(BaseModel):
    """Converge an intruder on the user aircraft's own projected track."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["tcas_conflict"]
    severity: TcasSeverity = "head_on_ra"  # see §6.2 for what each preset means, in seconds/ft/nm
    relative_bearing_deg: float = Field(
        default=180.0,
        ge=0.0,
        lt=360.0,
        description="Intruder's track relative to the user's own, at spawn: 180=head-on, "
        "90/270=crossing, 0=same-direction closure from ahead or overtaking from behind.",
    )
    miss_side: Literal["left", "right"] = "left"
    vertical_offset: Literal["above", "below"] = "above"
    closure_ias_kt: float | None = Field(default=None, ge=0.0)
    kind: TrafficKind = "aircraft"
    callsign: str = Field(default="TFC01", min_length=1, max_length=12)


class RunwayIncursionSpawnRequest(BaseModel):
    """A vehicle or aircraft crossing the runway, timed to the user's own closing speed."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["runway_incursion"]
    airport_icao: str = Field(min_length=2, max_length=7)
    runway_ident: str = Field(min_length=1, max_length=3)
    cross_at_along_track_nm: float = Field(
        default=0.0,
        description="Distance beyond the threshold, along the landing direction, "
        "where the crossing happens. 0.0 = at the threshold itself.",
    )
    lead_time_before_user_arrival_s: float = Field(
        default=8.0,
        description="How many seconds BEFORE the user would reach the crossing "
        "point the vehicle starts crossing it. Negative = the vehicle is still crossing "
        "slightly AFTER the user's projected arrival — the worse-case incursion.",
    )
    from_side: Literal["left", "right"] = "left"
    vehicle_speed_kt: float | None = Field(default=None, ge=0.0)
    kind: TrafficKind = "ground_vehicle"
    callsign: str = Field(default="GND01", min_length=1, max_length=12)


class ApproachSequenceSpawnRequest(BaseModel):
    """n aircraft on the same final, at named distances — reuses core.geodesy verbatim (D11)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["approach_sequence"]
    airport_icao: str = Field(min_length=2, max_length=7)
    runway_ident: str = Field(min_length=1, max_length=3)
    distances_nm: tuple[float, ...] = Field(min_length=1, max_length=8)
    ias_kt: float | None = Field(default=None, ge=0.0)
    category: ApproachCategory = "B"  # from core.geodesy, reused directly
    kind: TrafficKind = "aircraft"
    callsign_prefix: str = Field(default="SEQ", min_length=1, max_length=8)


class TaxiTrafficSpawnRequest(BaseModel):
    """A traffic entity ground-taxiing an explicit route (D12, §10.5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["taxi_traffic"]
    route: tuple[GeoPosition, ...] = Field(min_length=2, max_length=32)
    speed_kt: float | None = Field(default=None, ge=0.0)
    kind: TrafficKind = "aircraft"
    callsign: str = Field(default="TAXI01", min_length=1, max_length=12)


class CustomTrackSpawnRequest(BaseModel):
    """The escape hatch: a hand-built TrafficTrack, e.g. authored from map clicks."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["custom"]
    track: TrafficTrack


TrafficSpawnRequest = Annotated[
    TcasConflictSpawnRequest
    | RunwayIncursionSpawnRequest
    | ApproachSequenceSpawnRequest
    | TaxiTrafficSpawnRequest
    | CustomTrackSpawnRequest,
    Field(discriminator="type"),
]
```

### 3.4 Live contacts

```python
class TrafficContact(BaseModel):
    """One live traffic entity, as reported by the adapter. Always-complete, like
    AircraftState — a read, never a sparse write."""

    model_config = ConfigDict(frozen=True)

    traffic_id: str = Field(
        description="Adapter-assigned uuid4 hex (D5). Stable for the entity's lifetime."
    )
    kind: TrafficKind
    scenario_shape: TrafficScenarioShape
    callsign: str
    label: str
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    altitude_ft: float
    heading_deg: float = Field(ge=0.0, le=360.0)
    ground_speed_kt: float = Field(ge=0.0)
    vertical_speed_fpm: float
    on_ground: bool = False
```

### 3.5 Server envelopes (`server/traffic_routes.py`)

```python
class TrafficStatus(BaseModel):
    adapter: str
    contacts: tuple[TrafficContact, ...]
    max_contacts: int | None = Field(
        default=None, description="Adapter-advertised capacity (D6), None when unknown/unbounded."
    )


class TrafficSpawnResult(BaseModel):
    contacts: tuple[TrafficContact, ...]  # one per track spawned; >1 only for approach_sequence
```

`core.traffic.TrafficCapacityExceeded` (a plain `RuntimeError` subclass, D6):

```python
class TrafficCapacityExceeded(RuntimeError):
    def __init__(self, adapter_name: str, capacity: int, active_count: int) -> None:
        self.adapter_name = adapter_name
        self.capacity = capacity
        self.active_count = active_count
        super().__init__(
            f"{adapter_name!r} is at capacity: {active_count} of {capacity} traffic slots in use."
        )
```

---

## 4. `SimAdapter` / `Capabilities` additions

**This is a shared-foundation change. It is made once, alone, by one agent, before the Map track,
the bridge track and the UI track branch off it (§9), following the standing rule for contract
changes.**

### 4.1 No new capability flag (D1)

`can_spawn_traffic` already exists on `Capabilities` and `FakeSimAdapter` already declares it
`True`. Six methods are added to the `SimAdapter` Protocol:

```python
async def get_traffic_contacts(self) -> tuple[TrafficContact, ...]:
    """Every live traffic entity this adapter (or its bridge) currently reports.

    Capability-free read (the get_active_failures posture): an adapter without
    can_spawn_traffic, or whose bridge is not currently reachable, returns ()
    rather than raising. "No traffic" is always an honest, cheap answer.
    """


async def spawn_traffic(self, track: TrafficTrack) -> TrafficContact:
    """Spawn one entity following track and return its initial contact, carrying
    a fresh adapter-assigned traffic_id (D5).

    Requires can_spawn_traffic. Raises TrafficCapacityExceeded (D6) when the
    adapter is already at whatever limit it enforces — never silently refuses
    and never corrupts an existing entity's state instead.
    """


async def despawn_traffic(self, traffic_id: str) -> None:
    """Remove one entity. Idempotent: an unknown or already-gone id is a no-op,
    not an error — the same posture as clear_failure on a healthy system.
    Requires can_spawn_traffic.
    """


async def clear_all_traffic(self) -> None:
    """Despawn every entity this adapter is tracking. Idempotent.
    Requires can_spawn_traffic.
    """


def stream_traffic(self, interval_s: float) -> AsyncIterator[tuple[TrafficContact, ...]]:
    """Yield the full traffic picture roughly every interval_s seconds, mirroring
    stream_state's shape and reasoning: a plain method returning an async
    iterator so implementations can be async generators.

    Capability-free: an adapter without traffic support yields () forever
    rather than raising, so a caller (the WS route) can iterate unconditionally
    exactly like it does for state — no adapter.capabilities check needed
    before the loop starts.
    """
```

Nothing else on the interface changes. `AircraftState` is untouched — traffic never appears there
(D10's reasoning).

### 4.2 `core/traffic.py` also exports

`TrafficCapacityExceeded` (§3.5) — imported by both adapters and by `server/traffic_routes.py`'s
409 handler, so the exception type is defined once, sim-agnostically, even though *when* it fires
is entirely adapter-specific (D6).

### 4.3 What `XPlaneSimAdapter` must change, structurally (D3, D4)

`capabilities` today (`adapters/xplane/xplane_adapter.py`) returns a fixed module-level
`_CAPABILITIES` constant. This design requires it to become **computed from an instance
attribute set once, inside `connect()`**, from the bridge probe (§5.2):

```python
async def connect(self) -> None:
    ...  # existing dataref/command resolution, unchanged
    self._bridge_available = await self._probe_bridge(client)  # §5.2 — never raises
    self._capabilities = _CAPABILITIES.model_copy(
        update={"can_spawn_traffic": self._bridge_available}
    )


@property
def capabilities(self) -> Capabilities:
    return self._capabilities
```

This is the one place in this design that touches an already-shipped file's behaviour rather than
only adding to it, and it belongs in the shared-foundation track for the same reason §4.1 does:
every later track (bridge implementation, UI) is written against "capabilities are resolved once
at connect and never move again," and that has to be true before anyone builds on it. See §10.1
for the residual disagreement with `bridge/README.md`'s wording that this raises, unresolved on
purpose.

### 4.4 What `FakeSimAdapter` must do

- Already declares `can_spawn_traffic=True` — unchanged.
- New instance state: `self._traffic: dict[str, _FakeTrafficEntity]`, where an entity holds its
  `track: TrafficTrack`, `spawned_at_monotonic: float`, and the fields `TrafficContact` needs that
  are not derived (`traffic_id`, `kind`, `scenario_shape`, `callsign`, `label`).
- `spawn_traffic(track)` — generates `traffic_id = uuid4().hex`, raises
  `TrafficCapacityExceeded("fake", _FAKE_MAX_TRAFFIC, len(self._traffic))` when
  `len(self._traffic) >= _FAKE_MAX_TRAFFIC`. `_FAKE_MAX_TRAFFIC = 19` — chosen to mirror
  X-Plane's real multiplayer-slot limit **for test realism only**; it is the Fake's own picked
  constant, not a value read from `core/traffic.py` (D6). Records the entity, returns its
  `TrafficContact` computed via `interpolate_track(track, 0.0)` (§6.1) — i.e. exactly
  `waypoints[0]`.
- `despawn_traffic(traffic_id)` — `self._traffic.pop(traffic_id, None)`; no error either way.
- `clear_all_traffic()` — `self._traffic.clear()`.
- `get_traffic_contacts()` — for every entity, `interpolate_track(entity.track, monotonic() -
  entity.spawned_at_monotonic)` (§6.1) turned into a `TrafficContact`; an entity whose
  `despawn_after_s` has elapsed is dropped from the ledger as part of this read (lazy expiry — no
  background task needed, matching the Fake's "no physics beyond what it is asked to report"
  philosophy already used for failures).
- `stream_traffic(interval_s)` — `while True: yield await self.get_traffic_contacts(); await
  asyncio.sleep(interval_s)`, the same shape as `stream_state`.

### 4.5 Contract tests to add — `tests/adapters/test_contract.py`

`CAPABILITY_COVERAGE["can_spawn_traffic"]` moves from `PENDING` to
`"test_spawned_traffic_is_reported_active"`.

| Test | Pins |
|---|---|
| `test_spawned_traffic_is_reported_active` | Spawn a minimal two-waypoint `custom` track → `get_traffic_contacts()` contains a contact with a non-empty `traffic_id`, at `waypoints[0]`'s position → despawn in `finally`. The read-back is the assertion (the issue #39 lesson, restated once more). |
| `test_despawn_is_idempotent` | Spawn, despawn, despawn again (no error), read back empty. |
| `test_clear_all_traffic_leaves_none` | Spawn two, clear-all, read back empty. |
| `test_traffic_advances_along_its_track` | Spawn a track whose second waypoint is materially displaced and reached at `t_offset_s=2.0`; poll `get_traffic_contacts()` briefly until the reported position has moved measurably from `waypoints[0]` toward `waypoints[1]` (the live-suite "poll briefly" pattern already used for the failures watcher-integration test) — proves the adapter is actually advancing the entity, not just echoing the spawn point back forever. |
| `test_spawn_capacity_is_enforced` | Spawn up to the adapter's own reported/assumed capacity, then one more → `TrafficCapacityExceeded`, `finally: clear_all_traffic()`. On `xplane` this test is `-m sim`-only and skipped in CI in the sense that the fixture never runs there (19 real AI aircraft is heavy); it runs unconditionally against `fake`. |
| `test_traffic_methods_refuse_without_the_capability` | A `FakeSimAdapter` subclass declaring `can_spawn_traffic=False` (the standard refusal-test pattern): `spawn_traffic`/`despawn_traffic`/`clear_all_traffic` raise `CapabilityNotSupported`; `get_traffic_contacts()` returns `()`; `stream_traffic` yields `()` forever (take one item, assert it is `()`). **This is D14 — the CI-provable half of Phase 3 exit criterion 3.** |
| `test_stream_traffic_reflects_spawns` | Start `stream_traffic`, spawn one entity mid-stream, assert a subsequent tick includes it (the `stream_state` liveness pattern already proven for the aircraft feed). |

---

## 5. Bridge transport mapping (X-Plane)

**This section describes `adapters/xplane/` and, at the boundary, `bridge/`. No bridge-protocol
detail may appear in `core/`.** Not a weather design; no weather-mode forcing applies.

### 5.1 The transport (D2)

The bridge registers a small, fixed set of **custom datarefs** through XPPython3's
`XPLMRegisterDataAccessor`, exactly the mechanism any XPPython3 plugin uses to publish state, and
therefore datarefs the Web API's own index already exposes with no bridge-specific server code:

| Custom dataref | Type | Direction | Purpose |
|---|---|---|---|
| `ois/bridge/heartbeat_s` | float | bridge → adapter | Wall-clock seconds since the plugin loaded, written every flight-loop callback. A monotonically increasing value the adapter polls to tell "loaded and alive" from "loaded and hung." |
| `ois/traffic/command` | data (byte array) | adapter → bridge | One pending command, JSON-encoded UTF-8: `{"op": "spawn"|"despawn"|"clear_all", "traffic_id": str|null, "track": <TrafficTrack.model_dump()>|null}`. The bridge's flight loop reads it once, acts, and clears it. |
| `ois/traffic/command_ack` | data | bridge → adapter | JSON `{"traffic_id": str, "ok": bool, "error": str|null}` for the most recently processed command — how `spawn_traffic` learns its `traffic_id` was accepted (or that capacity was exceeded, §5.4) without a second round trip. |
| `ois/traffic/contacts` | data | bridge → adapter | JSON array of every live entity's current state — the wire shape mirrors `TrafficContact` minus `label`/`scenario_shape` (kept adapter-side, §5.3) — written every flight-loop tick from the bridge's own internal `interpolate_track`-equivalent. |

This is a **request/poll** protocol, not a queue: the adapter writes one command, polls
`command_ack` for a matching `traffic_id` (bounded by a short timeout, mirroring the existing
`XPlaneNotReachable` timeout pattern), and reads `contacts` on every `get_traffic_contacts()` /
`stream_traffic()` tick. A production concern flagged rather than resolved here: **at most one
command in flight at a time** is the simplest correct thing, and it is safe because
`server/traffic_routes.py` never issues two spawn/despawn calls concurrently against one adapter
instance (FastAPI request handlers for this router are not internally parallelised against each
other by anything this design adds) — but this is a real constraint on the bridge's own internal
loop that the spike (§10.4) must validate rather than assume.

### 5.2 Probing the bridge at connect time (mirrors D11 of `failures-manager.md`)

`adapters/xplane/traffic_bridge.py` (new module) exposes `async def probe(client: httpx.AsyncClient)
-> bool`: reads the dataref index precisely as `OPTIONAL_DATAREFS` already is (§4.3's `connect()`
snippet), looks for `ois/bridge/heartbeat_s`; absent → `False`, **never raises, never fails
`connect()`** (this is the whole point of "optional"). Present → resolves its id and reads it
twice, `_BRIDGE_PROBE_GAP_S` apart (a small constant, e.g. 0.5 s), requiring the second read to be
strictly greater — proving the flight loop is actually ticking, not just that the plugin loaded
and then froze. That result becomes `can_spawn_traffic` for the rest of this connection's
lifetime (D3/D4).

### 5.3 `TrafficTrack.model_dump()` over `data` datarefs — a real open question

X-Plane's Web API supports writing `data`-typed (byte array) custom datarefs, but the **maximum
payload size** for one write is a genuine unknown at design time — a `TrafficTrack` for
`approach_sequence` with several waypoints, JSON-encoded, is plausibly a few hundred bytes, well
inside anything reasonable, but this has not been measured against a real plugin-registered
`data` dataref. **This is exactly a "verify in spike" row**, in the same honesty class as
`failures-manager.md` §5.2's low-confidence dataref idents: the design's correctness does not
depend on the exact byte budget, only on "JSON over a data dataref is large enough for one
`TrafficTrack`," and if the spike (§10.4) finds it is not, the fallback is chunking the write
across several ticks — a bridge-internal detail, no interface change.

### 5.4 Capacity (D6)

`adapters/xplane/traffic_bridge.py::MAX_CONCURRENT_TRAFFIC_XPLANE = 19` — X-Plane's real
published limit on multiplayer aircraft slots (`sim/multiplayer/position/plane1` … `plane19`),
the mechanism the bridge is expected to drive for `kind="aircraft"` entities. `spawn_traffic`
raises `TrafficCapacityExceeded("xplane", MAX_CONCURRENT_TRAFFIC_XPLANE, active_count)` when the
bridge's `command_ack` reports refusal for that reason (the bridge, not the adapter, is the
source of truth for "how many slots are actually free," since a stock X-Plane AI-traffic setting
could also be consuming slots the bridge did not spawn).

Ground vehicles and birds may or may not share the same 19-slot budget — X-Plane's ground-service
vehicles are historically a *different* subsystem (`sim/operation/ground_traffic/*`, driven by
X-Plane's own ATC ground logic, not freely scriptable the way multiplayer aircraft slots are) — so
whether `kind="ground_vehicle"`/`"bird"` reuse the multiplayer-slot mechanism (visually
approximated as another aircraft model) or a different one entirely is **unresolved and explicitly
the spike's job to settle** (§10.4), not guessed here.

### 5.5 MSFS (Phase 5 target) — likely no bridge needed at all

Unlike X-Plane, **SimConnect exposes AI object creation directly** (`AICreateNonATCAircraft`,
`AICreateSimulatedObject`, and siblings) as part of its externally-reachable API — the same API
the MSFS adapter already has to use for everything else. If that holds up at implementation time,
the MSFS adapter's `spawn_traffic`/`despawn_traffic`/`get_traffic_contacts` would call SimConnect
**directly, with no bridge equivalent at all**, and `can_spawn_traffic` could be `True`
unconditionally rather than depending on an optional add-on. This is exactly the shape
`architecture.md`'s "if supporting MSFS requires touching `core/`, `server/` or `ui/`, the
abstraction was wrong" is testing for: `SimAdapter.spawn_traffic(track: TrafficTrack)` carries no
X-Plane-specific concept in its signature, so this design already accommodates it. Noted as a
target for the Phase 5 planner, not solved here — SimConnect's AI-object API has its own
real-world quirks (object persistence across a scenery reload, live callsign visibility to real
ATC) that a Phase 5 design should verify rather than assume away.

---

## 6. `core/` logic

Two new modules and one small, safe addition to an already-shipped one.

### 6.1 `core/traffic.py` — vocabulary, geometry, interpolation

Everything in §3 (`TrafficKind`, `TrafficWaypoint`, `TrafficTrack`, the spawn-request union,
`TrafficContact`, `TrafficCapacityExceeded`), plus:

```python
class TrafficSample(BaseModel):
    """Where a track-following entity is, at some elapsed time since spawn."""

    model_config = ConfigDict(frozen=True)
    position: GeoPosition
    heading_deg: float = Field(ge=0.0, le=360.0)
    ground_speed_kt: float = Field(ge=0.0)
    on_ground: bool


def interpolate_track(track: TrafficTrack, elapsed_s: float) -> TrafficSample:
    """Where a traffic entity following ``track`` is, ``elapsed_s`` after spawn.

    Before the first waypoint (never happens — t_offset_s[0] == 0.0 is enforced
    on the model) or exactly at or after the last, the entity sits at that
    waypoint, holding its heading. Between two waypoints it advances along the
    GEODESIC connecting them (core.geodesy.distance_and_bearing +
    point_at_distance_and_bearing) at the CONSTANT speed implied by their own
    distance and t_offset_s gap — not a blend of the two waypoints' stated
    speeds, so a track asking for 250 kt at one point and 180 kt at the next is
    honoured by how far apart the caller placed the waypoints in time, not by
    an invented deceleration curve. This mirrors core.geodesy's own "the
    initial bearing is close enough over a leg this short" convention (the
    _offset helper) rather than re-deriving arrival-bearing correction for legs
    that are, in every shipped builder, well under 20 NM.

    Pure, no I/O, no clock of its own — elapsed_s is an input, which is what
    makes this independently unit-testable AND makes it the shared reference
    implementation FakeSimAdapter uses and the bridge's own Python (also
    free to import core/, never the reverse — see §10.2) can mirror.
    """
```

Constants and geometry builders (units and defaults as in §3.3's request models):

```python
#: Named TCAS conflict presets. Deliberately NOT a physics model of TCAS's real
#: sensitivity-level table (which varies by altitude — see the prose note
#: below); these are round numbers chosen to reliably cross the published TA/RA
#: thresholds well before the geometry's own closest point of approach, giving
#: the student time to see the TA before the RA. Always overridable by the
#: request's own fields — the FINAL_THROTTLE honesty class.
TcasSeverity = Literal["head_on_ra", "crossing_ra", "ta_only"]


class TcasSeverityProfile(BaseModel):
    model_config = ConfigDict(frozen=True)
    spawn_lead_time_s: float  # total track duration from spawn to CPA
    vertical_miss_distance_ft: float
    horizontal_miss_distance_nm: float


TCAS_SEVERITY_PROFILES: Mapping[TcasSeverity, TcasSeverityProfile] = MappingProxyType(
    {
        "head_on_ra": TcasSeverityProfile(
            spawn_lead_time_s=100.0, vertical_miss_distance_ft=0.0, horizontal_miss_distance_nm=0.0
        ),
        "crossing_ra": TcasSeverityProfile(
            spawn_lead_time_s=100.0, vertical_miss_distance_ft=0.0, horizontal_miss_distance_nm=0.0
        ),
        "ta_only": TcasSeverityProfile(
            spawn_lead_time_s=90.0, vertical_miss_distance_ft=500.0, horizontal_miss_distance_nm=0.5
        ),
    }
)

TCAS_DEFAULT_CLOSURE_IAS_KT: float = 250.0
TCAS_TRACK_LEAD_TIME_S: float = 20.0  # how far past CPA the track continues before holding

RUNWAY_INCURSION_DEFAULT_OFFSET_M: float = (
    60.0  # how far off each side of the runway the vehicle starts/ends
)
RUNWAY_INCURSION_DEFAULT_SPEED_KT: float = 15.0  # a plausible airport service-vehicle speed

APPROACH_SEQUENCE_DEFAULT_DISTANCES_NM: tuple[float, ...] = (12.0, 8.0, 4.0)

TAXI_DEFAULT_SPEED_KT: float = 12.0


def tcas_conflict_track(
    user_state: AircraftState,
    *,
    severity: TcasSeverity = "head_on_ra",
    relative_bearing_deg: float = 180.0,
    miss_side: Literal["left", "right"] = "left",
    vertical_offset: Literal["above", "below"] = "above",
    closure_ias_kt: float | None = None,
    kind: TrafficKind = "aircraft",
    callsign: str = "TFC01",
) -> TrafficTrack:
    """An intruder converging on the user aircraft's own projected position.

    1. Extrapolate the user's own position forward severity's spawn_lead_time_s
       using its current ground speed (tas_from_ias(user_state.ias_kt,
       user_state.altitude_ft) — the "still air" approximation every other
       geometry function in this project already makes) and heading_deg.
    2. That point, offset horizontal_miss_distance_nm to miss_side of the
       INTRUDER's own track and vertical_miss_distance_ft vertical_offset from
       it, is the intruder's position at t=spawn_lead_time_s — its projected
       closest point of approach.
    3. The intruder's track direction is user_state.heading_deg +
       relative_bearing_deg. Walk backward along it from the CPA point to
       t=0.0 (the spawn point) and forward from it to
       t=spawn_lead_time_s + TCAS_TRACK_LEAD_TIME_S (where the track ends and
       the entity holds, or despawns if despawn_after_s is set by the caller).

    A zero-miss request (the "head_on_ra"/"crossing_ra" defaults) places the
    intruder EXACTLY at the user's own projected position at t=spawn_lead_time_s
    — verified in the test plan (§8.1) as a distance_and_bearing() of (0.0, …)
    between the two, not a hand-picked coordinate.
    """


def runway_incursion_track(
    runway: Runway,
    user_state: AircraftState,
    *,
    cross_at_along_track_nm: float = 0.0,
    lead_time_before_user_arrival_s: float = 8.0,
    from_side: Literal["left", "right"] = "left",
    vehicle_speed_kt: float | None = None,
    kind: TrafficKind = "ground_vehicle",
    callsign: str = "GND01",
) -> TrafficTrack:
    """A crossing timed against the user's OWN closing speed on the runway.

    1. crossing_point = point_at_distance_and_bearing(runway.threshold,
       cross_at_along_track_nm, runway.true_bearing_deg) — a point on the
       centreline, cross_at_along_track_nm beyond the threshold in the landing
       direction (0.0 = the threshold itself).
    2. distance_to_crossing_nm, _ = distance_and_bearing(user's position,
       crossing_point); t_user_arrival_s = distance_to_crossing_nm /
       tas_from_ias(user_state.ias_kt, user_state.altitude_ft) * 3600.
    3. t_cross_s = max(0.0, t_user_arrival_s - lead_time_before_user_arrival_s)
       — the vehicle is crossing the centreline at this elapsed time.
    4. The vehicle's own track is perpendicular to the runway axis
       (runway.true_bearing_deg +/- 90, per from_side), RUNWAY_INCURSION_
       DEFAULT_OFFSET_M off to one side at t=0.0, through crossing_point at
       t=t_cross_s, and the same offset on the opposite side at
       t=t_cross_s + (time to cover 2 * offset at vehicle_speed_kt).

    Accepted limitation, stated once and not re-litigated here: this reads
    user_state ONCE, at spawn time (D8) — a student who slows down after the
    instructor taps Spawn makes the vehicle arrive early relative to the
    (now slower) approach. Same honesty class as Failures' wall-clock delay
    trigger (failures-manager.md §10.3).
    """


def approach_sequence_tracks(
    runway: Runway,
    *,
    distances_nm: tuple[float, ...] = APPROACH_SEQUENCE_DEFAULT_DISTANCES_NM,
    ias_kt: float | None = None,
    category: ApproachCategory = "B",
    kind: TrafficKind = "aircraft",
    callsign_prefix: str = "SEQ",
) -> tuple[TrafficTrack, ...]:
    """One track per distance in distances_nm (D11): each starts at
    core.geodesy.final_approach_point(runway, distance, DEFAULT_GLIDESLOPE_DEG)
    — the EXACT function the Position Manager's own final placements call —
    descends down the same glidepath to the threshold, and continues onto the
    runway to a rollout point. No new descent-rate maths: the vertical_speed
    a stabilised final flies is the same formula _profile_setup() already
    uses in core/geodesy.py.
    """


def taxi_traffic_track(
    route: tuple[GeoPosition, ...],
    *,
    speed_kt: float = TAXI_DEFAULT_SPEED_KT,
    kind: TrafficKind = "aircraft",
    callsign: str = "TAXI01",
    label: str = "taxi traffic",
) -> TrafficTrack:
    """Turn an ordered list of ground points into a timed track at a constant
    speed. Every waypoint is on_ground=True. t_offset_s accumulates from the
    geodesic distance between consecutive points divided by speed_kt — no
    routing is invented; the caller (map clicks, or a scenario's own point
    list) supplies the path (D12, §10.5)."""
```

### 6.2 A small, safe addition to `core/geodesy.py`

None required. Every builder above calls existing public functions
(`point_at_distance_and_bearing`, `distance_and_bearing`, `final_approach_point`,
`glideslope_altitude_ft`) verbatim. This is deliberate (D11) — it is worth stating plainly that
this manager adds **zero** new geodesic primitives, only new callers of the ones the Position
Manager already proved.

### 6.3 The server's resolution layer — `server/traffic_routes.py`

Not `core/` (mirrors `failure_routes.py`'s watcher and `scenario_engine.py`'s executor — anything
that awaits `SimAdapter` lives in `server/`, per the standing D6 of `scenario-generator.md`).
`_resolve_spawn_requests(request: TrafficSpawnRequest, *, adapter: SimAdapter, navdata:
NavdataProvider) -> tuple[TrafficTrack, ...]`:

- `tcas_conflict` → one call to `adapter.get_aircraft_state()`, then
  `core.traffic.tcas_conflict_track(...)` → one track.
- `runway_incursion` → resolve the named runway via `navdata.runway(icao, ident)` (404 if
  absent — §2.1), one `get_aircraft_state()`, then `core.traffic.runway_incursion_track(...)` →
  one track.
- `approach_sequence` → resolve the runway, then
  `core.traffic.approach_sequence_tracks(...)` → `n` tracks.
- `taxi_traffic` → `core.traffic.taxi_traffic_track(route=request.route, ...)` → one track.
- `custom` → `request.track` verbatim, already validated.

`POST /spawn`'s handler then calls `await adapter.spawn_traffic(track)` once per resolved track
(sequentially — a multi-track `approach_sequence` spawning three aircraft is three awaited calls,
not a batch method on the interface; keeping `SimAdapter.spawn_traffic` singular is worth more
than saving two round trips), collecting every `TrafficContact` into the response. A failure
partway through (e.g. the second of three hits `TrafficCapacityExceeded`) leaves the
already-spawned entities spawned — the same "no partial-failure rollback" posture
`scenario-generator.md` §10.7 already accepts for its own multi-step run.

---

## 7. UI panel outline

`ui/src/features/traffic/` — a new tab of the Instructor Panel. Adding it adds files; per D13 it
does **not** edit `instructorApi.ts`.

### 7.1 Components

| File | Role |
|---|---|
| `TrafficPanel.tsx` | The tab: gate → contact list on top → spawn forms below, one per shape behind a segmented picker. |
| `ContactList.tsx` | Live entities from the WS-fed slice — kind icon, callsign, altitude, speed, a per-entity despawn ✕ — plus **CLEAR ALL**, same destructive styling and no-confirmation posture as the Failures panel's D13 (breaking is one tap, so is the fix). |
| `TcasConflictForm.tsx` | Severity picker (`head_on_ra` / `crossing_ra` / `ta_only`, with the plain-language sentence each implies — "the intruder crosses within 0 ft vertically about 100 s after you tap Spawn"), relative bearing, side, kind. One **Spawn** action. |
| `RunwayIncursionForm.tsx` | Runway picker (reuses the Position Manager's existing airport/runway selector component — not rebuilt here), crossing offset, lead time, side. |
| `ApproachSequenceForm.tsx` | Runway picker, a repeatable "distance out" list (defaults to `APPROACH_SEQUENCE_DEFAULT_DISTANCES_NM`), category. |
| `TaxiTrafficForm.tsx` | A route builder — reuses the Instructor Map's click-to-add-point affordance when that manager's map component exists on the branch (§9); until then, a plain lat/lon list editor is enough to exercise the endpoint. |
| `gate.ts` | `trafficGate(capabilities, isError)` — the `position/gate.ts`/`failures/gate.ts` pattern verbatim: closed while loading, closed on error, closed without `can_spawn_traffic`. |
| `trafficSlice.ts`, `trafficApi.ts` | Below. |

Tablet-first: **CLEAR ALL** and the contact list sit at the top, reachable with a thumb; every
form's Spawn button is ≥ 44 px; the severity/runway pickers are segmented controls, not free-text,
matching the rest of the panel's touch-first controls.

### 7.2 State

`trafficApi.ts` uses `instructorApi.injectEndpoints` with tag `Traffic`:

- `spawnTraffic`, `despawnTraffic`, `clearAllTraffic` (mutations, all invalidate `Traffic`).
- **No `getTrafficStatus` polling query** — unlike Failures' 2 s poll, traffic already has a live
  push (`WS /traffic`, D10), so a second, redundant poll would be the wrong tool exactly as a
  second REST poll of aircraft state next to `/ws/state` would be.

`trafficSlice.ts` is fed by the WebSocket connection, mirroring however the existing telemetry
slice consumes `/ws/state` (that hook is not in this manager's files — reused, not rebuilt):

```ts
interface TrafficState {
  contacts: TrafficContact[];       // replaced wholesale on every /ws/traffic frame
  connected: boolean;
  selectedShape: TrafficScenarioShape; // which spawn form tab is open — client-only
}
```

`spawnTraffic`/`despawnTraffic` are pending-reconciled against the *next* WS frame rather than
against their own REST response body, the same optimistic-then-reconciled posture the feature
spec's Aircraft Control section already prescribes for write latency.

All API types come from the regenerated `ui/src/api/schema.d.ts` — the discriminated
`TrafficSpawnRequest` union arrives as a proper tagged union, nothing hand-written.

### 7.3 Capability gating, restated

- Tab-level: `can_spawn_traffic` via `trafficGate`, fail-closed.
- No per-entry gating below that — unlike Failures (per-catalogue-entry support), traffic is a
  single yes/no capability once the bridge is present (D6's capacity limit is a runtime 409, not
  a static per-shape disablement).
- **The genuine residual risk (§10.1):** if the bridge disappears mid-session, `capabilities` does
  NOT change (D4), so the tab stays enabled and a spawn attempt fails with a plain error the panel
  has to surface as a toast/inline error rather than a disabled control — the one place in this
  manager where hard rule 3's "never discover a limitation by having a control fail" is not fully
  achieved, disclosed rather than hidden. See §10.1 for what would close the gap.

---

## 8. Test plan

Everything except §8.4 runs in CI against `FakeSimAdapter`. No navdata fixture beyond what
`tests/server/conftest.py`'s existing in-Python world already provides for the runway lookups.

### 8.1 `core/` unit tests — `tests/core/test_traffic.py`

Model validation:

- `TrafficTrack` with `waypoints[0].t_offset_s != 0.0` → `ValidationError`.
- `TrafficTrack` with out-of-order or tied `t_offset_s` → `ValidationError`.
- `TrafficSpawnRequest` round-trips through its discriminator for all five `type` values.

`interpolate_track`, against a hand-built two-waypoint track (start at `(40.0, -3.0, 5000 ft)`,
end at a point exactly 10 NM due east at `(40.0, -3.0, 5000 ft)` — i.e. same altitude, straight
line — reached at `t_offset_s=180.0`, i.e. a constant 200 kt ground speed over the leg):

- `elapsed_s=0.0` → position equals the start waypoint exactly.
- `elapsed_s=90.0` (halfway in time) → position is `distance_and_bearing(start, result) ≈ (5.0
  NM, 90°)` — halfway in *distance* too, because the leg is flown at constant speed.
- `elapsed_s=180.0` → position equals the end waypoint exactly.
- `elapsed_s=300.0` (past the end) → position still equals the end waypoint (holds).
- `ground_speed_kt` reported at any point strictly between the waypoints equals `200.0` (10 NM /
  180 s × 3600), computed from the pair's own distance/time, not copied from either waypoint's
  `speed_kt` field.

`tcas_conflict_track`, `severity="head_on_ra"` (zero miss distances), against a hand-built
`AircraftState` at `(40.0, -3.0, 10000 ft, heading=90.0, ias_kt=250.0)`:

- The track's waypoint whose `t_offset_s` equals `TCAS_SEVERITY_PROFILES["head_on_ra"]
  .spawn_lead_time_s` (100.0 s) has a `distance_and_bearing()` of **exactly `(0.0 NM, …)`** from
  the user's own extrapolated position at the same elapsed time — computed independently in the
  test via `point_at_distance_and_bearing(user_position, tas_from_ias(250.0, 10000.0) * 100.0 /
  3600.0, 90.0)`, never a hard-coded lat/lon (the same "assert the property, not a magic
  coordinate" discipline used throughout `core/geodesy.py`'s own test suite).
- The track's direction (bearing between its first two waypoints) is
  `normalise(90.0 + 180.0) = 270.0°` — the reciprocal, i.e. genuinely head-on.
- With `severity="ta_only"` the same CPA-time waypoint is `500.0` ft vertically displaced and
  `0.5` NM horizontally displaced from the user's projected point — read straight off
  `TCAS_SEVERITY_PROFILES`, so the test is a pin on the table, not a re-derivation.

`runway_incursion_track`, against a runway fixture at `elevation_ft=0`, `threshold=(0.0, 0.0)`,
`true_bearing_deg=0.0` (due north), and a user 6.0 NM due south of the threshold
(`cross_at_along_track_nm=0.0`) at `ias_kt=120.0`, `altitude_ft=0.0` (so `tas_from_ias ≈
120.0`, negligible density correction at sea level):

- `t_user_arrival_s = 6.0 / 120.0 * 3600 = 180.0` — the worked reference value the task's own
  instructions ask for.
- With `lead_time_before_user_arrival_s=20.0` → `t_cross_s = 160.0`, pinned exactly.
- With `lead_time_before_user_arrival_s=200.0` (larger than the arrival time itself) →
  `t_cross_s` clamped to `0.0` (the `max(0.0, …)` in the algorithm), not negative.

`approach_sequence_tracks`, against `DEFAULT_GLIDESLOPE_DEG=3.0` and `threshold_elevation_ft=0.0`:

- For `distances_nm=(10.0,)`, the spawn waypoint's `altitude_ft` equals
  `glideslope_altitude_ft(0.0, 10.0, 3.0)` — **the same reference value the task's instructions
  request**: `tan(3°) × 10 × 6076.115_486 ≈ 3184.4 ft`, asserted to within `0.5 ft` (the tolerance
  already used for `core/geodesy.py`'s own glideslope tests).
- `distances_nm=(12.0, 8.0, 4.0)` → three tracks returned, each independently correct against the
  same formula.

`taxi_traffic_track`: a 3-point route with known geodesic leg lengths → `t_offset_s` values match
`leg_length_nm / speed_kt × 3600` accumulated, exactly (no interpolation error at the waypoints
themselves — only `interpolate_track` interpolates *between* them).

### 8.2 Contract tests

The suite of §4.5, parametrised over both adapters. Written by the tester **from this document**,
before the implementation exists. `test_traffic_methods_refuse_without_the_capability` (D14) is
the CI-provable half of Phase 3 exit criterion 3 and must be reviewed against the exact wording of
that criterion before this manager is considered done.

### 8.3 Server tests — `tests/server/test_traffic_routes.py`

Against `TestClient` + `FakeSimAdapter`:

- `POST /spawn` with a `custom` track → 200, one contact, `traffic_id` present.
- `POST /spawn` with `tcas_conflict` → 200, one contact whose position is close to the user's
  current one scaled by the closure geometry (a coarse sanity bound, not a re-check of §8.1's
  exact maths — this test is about the HTTP plumbing, not the geometry).
- `POST /spawn` with `runway_incursion` naming a runway absent from the (in-memory) navdata fixture
  → 404.
- `GET /status` reflects a spawn; `DELETE /{traffic_id}` removes it, `DELETE` of an already-gone
  id → still 200; `POST /clear` empties everything.
- Capability refusal: a `FakeSimAdapter` subclass with `can_spawn_traffic=False` wired through
  `server/deps.py`'s override → `/spawn`, `DELETE`, `/clear` all 501 with the stated-adapter
  sentence; `/status` still 200 with `contacts: []` — the exact shape roadmap exit criterion 3
  asks a test to demonstrate, now proven at the HTTP layer too, not only at the adapter layer.
- Capacity: spawn to the Fake's `_FAKE_MAX_TRAFFIC` (19), one more → 409 with the exact sentence
  from `TrafficCapacityExceeded`.
- `WS /traffic`: connect, spawn one entity via REST from a second client, assert the next WS frame
  contains it — the `stream_state` liveness test's shape, applied to the new stream.

### 8.4 `@pytest.mark.sim` — `tests/sim/test_live_traffic.py` (never in CI)

What only a live X-Plane with the bridge installed proves — Phase 3 exit criterion 4:

- Spawn a `tcas_conflict` (`head_on_ra`) ahead of the live aircraft; poll `read_dataref` (via the
  `xplane-datarefs` MCP or the adapter's own read path) on one `sim/multiplayer/position/plane*`
  slot until it reports a position matching the spawned track; despawn, assert the slot clears.
- Spawn a `runway_incursion` timed against the live aircraft on a short final; assert the vehicle
  is on the runway centreline at the computed crossing time.
- **Whether the aircraft's own cockpit TCAS actually raises a TA/RA** is recorded as an
  *observation*, not asserted programmatically in Phase 3 — no adapter method reads a TCAS
  instrument's advisory state yet (§10.4), so this half of the exit criterion is validated by a
  human watching the sim, the same posture the roadmap's own wording ("run in a live X-Plane")
  implies rather than a stronger, unstated "and assert the RA fired."
- `test_spawn_capacity_is_enforced`'s live variant is explicitly marked slow/opt-in — spawning 19
  real AI aircraft is not something to do on every `-m sim` run.

### 8.5 Fixtures

No navdata file of any kind, per hard rule 4. `tests/server/conftest.py`'s existing in-memory
runway world (already used by `test_position_routes.py`) is reused unchanged for the
`runway_incursion`/`approach_sequence` server tests.

### 8.6 UI tests (vitest)

- `gate.test.ts` — fail-closed on loading, error, missing flag.
- `TcasConflictForm.test.tsx` / `RunwayIncursionForm.test.tsx` — submitting sends the exact
  `TrafficSpawnRequest` body (`toEqual` against a stubbed `fetch`, the position/failures pattern —
  no picker silently defaults a field).
- `ContactList.test.tsx` — CLEAR ALL issues exactly one `/clear` request; per-entity despawn
  issues the correct `traffic_id`.
- `trafficSlice.test.ts` — a `/ws/traffic` frame replaces `contacts` wholesale.

---

## 9. Parallelisation

### 9.1 Across Phase 3

This manager, the Instructor Map (manager 5), Pushback (manager 8) and Camera (manager 10) are
the four Phase 3 tracks, each its own `feature/*` branch in its own git worktree, each its own PR
to `dev`; CI on each PR is the integration barrier. **The one thing they all share is
`can_spawn_traffic`, and it needs no work from Map/Pushback/Camera** — those three managers do not
touch `Capabilities` or `SimAdapter` at all, so this manager's foundation track (§9.2, Track 0)
does not block them starting. The only real coupling is soft: the Instructor Map's traffic
rendering consumes `WS /ws/traffic` and `TrafficContact` (§2, D10), so Map's traffic-rendering
slice is easiest to write once this manager's Track 0 has landed on `dev` — but Map's own
aircraft-position rendering, runway/procedure geometry and drag-to-reposition do not depend on
this manager at all and can start immediately.

### 9.2 Inside this manager

**Track 0 — the foundation (serialised, first, one agent):** `core/traffic.py` (models +
geometry builders — the Fake and the contract suite need them), the §4.1 protocol methods,
`FakeSimAdapter`, the §4.5 contract tests, and the §4.3 change to `XPlaneSimAdapter.capabilities`
(structural only — the bridge probe itself is a stub returning `False` until Track B lands).
Owns: `core/traffic.py`, `core/sim_adapter.py`, `adapters/fake/`,
`adapters/xplane/xplane_adapter.py` (the `capabilities`/`connect()` change only),
`tests/adapters/test_contract.py`, `tests/core/test_traffic.py`.

Then three tracks, dispatched **in one message**, disjoint directories:

**Track A — backend (server):** `server/traffic_routes.py`, the `include_router` line in
`server/app.py`, `tests/server/test_traffic_routes.py`.
Owns: `server/traffic_routes.py`, `server/app.py` (one line), `tests/server/`.

**Track B — the bridge transport:** `adapters/xplane/traffic_bridge.py` (probe + command/ack/
contacts codec), the six method implementations in `adapters/xplane/xplane_adapter.py`,
`spikes/bridge_transport.py` (§10.4), and the actual `bridge/` XPPython3 plugin.
Owns: `adapters/xplane/traffic_bridge.py`, `adapters/xplane/xplane_adapter.py` (the six new
methods), `bridge/`, `tests/sim/test_live_traffic.py`, `spikes/bridge_transport.py`. **This track
is the slowest and the riskiest** (§10.4) — it should start first among the three even though it
is dispatched alongside the others, and nothing else in this manager blocks on it finishing: Track
A and the UI are fully exercisable against the Fake without a real bridge ever existing.

**Track C — the panel:** `ui/src/features/traffic/*` and the `trafficApi.ts` injection.
Sequenced **after Track A** (needs `schema.d.ts` regenerated from the running server), exactly the
precedent `failures-manager.md` §9.2 Track C already recorded. Pure logic (`gate.ts`, the slice
shape, the geometry-preset sentences for the severity picker) can be written from this document
while A runs; the wiring waits for the regen.

**The tester does not wait:** §8.1 and §8.2 are written against this document, before any
implementation exists.

**Never parallelised, restated:** Track 0; merges to `dev`/`main`; release tagging. No navdata
schema is touched by this manager.

---

## 10. Open questions and risks

### 10.1 D4's tension with `bridge/README.md`'s "the adapter flips `can_spawn_traffic` to `False`"

The clearest unresolved item in this document. `bridge/README.md` (§"Notes for whoever builds
it") states the fail-soft behaviour as a capability flip; `Capabilities`' own docstring says
capabilities never change at runtime, and mutating a `frozen=True` model that `GET
/api/capabilities` already handed to a connected UI client is not literally possible without
either dropping the freeze or re-fetching. §4.3/D4 resolves this by treating bridge loss as a
connectivity fault surfaced through the write methods failing, not a flag flip — but that leaves
the UI unable to *disable* the traffic tab proactively when the bridge dies mid-session (§7.3);
it can only show an error after a failed attempt, which is weaker than hard rule 3's stated
ideal. **What would resolve it:** a decision from the user on which is worse — (a) leaving `GET
/api/capabilities` as a one-shot fetch and accepting this manager's controls can fail visibly but
gracefully after a bridge crash, or (b) making capabilities genuinely re-fetchable (the UI
re-polls it periodically or on a WS-pushed "capabilities changed" event), which is a change with
consequences for every other manager's gating logic, not just this one, and should not be decided
inside a single manager's design.

### 10.2 Should `bridge/` import `core/traffic.py`?

§6.1 suggests the bridge's own interpolation logic should mirror `interpolate_track` "in spirit."
Whether it should do so **literally, by importing `core.traffic`** (XPPython3 plugins run a
regular CPython interpreter, so a pure-Python, I/O-free module is technically importable from
inside the sim) is left open. Doing so would guarantee the bridge and `FakeSimAdapter` compute
identical positions for identical tracks — valuable for the live/Fake behavioural parity this
project generally cares about — but it is the first time anything under `bridge/` would depend on
`core/`, and `architecture.md`'s dependency diagram does not currently draw that edge. **What
would resolve it:** confirm `bridge/` may depend on `core/` (never the reverse, never on
`adapters/`) as an explicit, documented exception, or accept the bridge re-implementing the same
handful of lines of geodesic interpolation independently and testing it against the same reference
values in §8.1.

### 10.3 No live-triggered traffic (D8)

Restated from the decision itself: a runway incursion computed from a single `get_aircraft_state()`
read at spawn time will arrive early or late if the student's speed changes materially afterward.
A live-triggered version (mirroring the Failures scheduler, §6.2 of `failures-manager.md`) is a
strictly bigger, strictly later feature — a server-side watcher re-aiming or re-timing an
already-spawned track against the live telemetry stream — deliberately not built speculatively.
**What would resolve it:** instructor feedback that the single-read timing is visibly wrong in
practice, at which point the fix is additive (a new `retime_traffic(traffic_id, new_track)` method
alongside the existing four, not a redesign).

### 10.4 The bridge transport itself needs a spike before Track B can finish with confidence

§5.1, §5.3 and §5.4 all name specific unknowns: the request/ack round-trip's timing behaviour
under X-Plane's flight-loop scheduling, the `data`-dataref payload-size ceiling, and whether ground
vehicles/birds share the aircraft multiplayer-slot mechanism or need a different one. All are
genuinely resolvable only against a running X-Plane with a minimal bridge plugin —
`spikes/bridge_transport.py`, throwaway, never imported by the app, never covered by tests, per
the `sim-lifecycle` skill's own conventions. **This is the single biggest schedule risk in Phase
3**, comparable to what the local-frame-origin problem was to Phase 0/1 — flagged explicitly
rather than estimated away, because until the spike runs, §5's design is the best available
reasoning from public X-Plane/XPPython3 documentation, not a measurement.

### 10.5 Taxiway routing is out of scope, and that is a real product gap

`taxi_traffic_track` takes an explicit point list because this project has never parsed taxiway
centrelines (Phase 1's `NavdataProvider` reads gates, stands, runways and procedures — not
`apt.dat`'s taxiway network records). "Taxi traffic" as a feature-spec scenario shape is therefore
shipped in Phase 3 only to the extent an instructor (or the Map's click-to-add-point UI) manually
lays out the route. **What would resolve it:** a future, additive `NavdataProvider` extension
parsing `apt.dat`'s taxiway/ground-route records and a pathfinding step in `core/traffic.py` — a
real, sizeable piece of work, not sketched further here because nothing in Phase 3's exit criteria
requires it.

### 10.6 `interpolate_track`'s constant-speed-per-leg assumption

Restated as a limitation, not a defect: a track asking for a hard deceleration between two
waypoints close together in distance but far apart in time will show the entity moving unrealistically
slowly for most of the leg and never accelerating smoothly — because position is linear in time
along the geodesic, not integrated from an acceleration profile. Acceptable for every builder this
design ships (none asks for aggressive speed changes mid-leg); worth a code comment pointing here
if a future builder needs one.

### 10.7 Wiring the Scenario Generator's traffic step

`scenario-generator.md` §6.3 step 4 already anticipated this moment: *"Because the pre-flight
check already guarantees `can_spawn_traffic` was `True` before this code could ever run, and no
adapter declares it `True` today, this branch is provably unreachable in Phase 2 — #13 adds one
call here, not a restructure."* That call is: extend `core/scenarios/models.py::
ScenarioTrafficBlock` with an optional `spawn: TrafficSpawnRequest` field, and replace
`server/scenario_engine.py`'s guarded no-op with `await adapter.spawn_traffic(track)` for each
resolved track. Not attempted in this design because it is not required by any Phase 3 exit
criterion and touches a file this manager does not otherwise own — flagged here so whoever revisits
either design finds the hook already named, and the touched files (`core/scenarios/models.py`,
`server/scenario_engine.py`) are known up front rather than discovered mid-change.

### 10.8 No 502 for an unreachable bridge specifically

Inherited from the same open item every prior design has recorded (`failures-manager.md` §10.7,
itself inherited from `position-manager.md`): a bridge command that times out surfaces as 500
today. When the project-wide 502 convention is settled, it is settled once, app-wide — this
manager follows, it does not fork.

### 10.9 `tcas_conflict_track` has no minimum spawn separation

A consequence of §6.1's own math, recorded here for a product decision rather than patched in
code: the intruder's spawn point is the CPA walked back `spawn_lead_time_s` along its own track
at its own speed, and the user's current position is the CPA walked back the same time along the
user's track at the user's speed. With `relative_bearing_deg=0` (a same-direction closure) and a
closure speed equal to the user's, those two walks are the *same* walk — the intruder spawns
**co-located with the user aircraft** — and any same-direction geometry with closure near the
user's speed spawns it arbitrarily close. The zero-speed degenerate case is now refused
(`closure_ias_kt` must be positive, at the schema and in the builder), but the co-location case
is well-formed by every rule this design states, and no minimum-spawn-separation requirement
exists anywhere in the document to refuse it against. **What would resolve it:** a product
decision on whether the builder should enforce a minimum spawn separation from the user aircraft
(refuse, or clamp the geometry) or whether an instructor asking for a same-speed
same-direction "conflict" is exercising a legitimate, if odd, freedom — decided once, here, not
improvised in a request validator.

---

## 11. Verification

```bash
pytest                       # unit + contract, Fake only — must be green before any merge
pytest -m sim                # §8.4: requires a live X-Plane AND the bridge plugin installed
ruff check . && ruff format --check .
mypy .
cd ui && npm run lint && npm run typecheck && npm test && npm run build
```

Panel smoke (fake adapter + Vite dev server, one batched browser session): Traffic tab loads →
spawn a `head_on_ra` TCAS conflict → contact appears in the list within one `/ws/traffic` frame →
despawn it → spawn a runway incursion → CLEAR ALL empties the list → console clean.
`pytest -m sim` against a real X-Plane with the bridge installed is the `sim-validator` agent's
job (§8.4) and is not a merge gate — Phase 3 exit criterion 4 is validated there, separately, once
Track B (§9.2) exists.
