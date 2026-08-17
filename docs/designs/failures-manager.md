# Failures Manager — design

**Status:** designed, not yet implemented.
**Phase:** 2 — Weather + Failures → Scenario Generator ([`../roadmap.md`](../roadmap.md)).
**Feature spec:** manager 4, [`../feature-spec.md`](../feature-spec.md#4-failures-manager), ⭐⭐⭐⭐⭐.
**Depends on:** nothing in Phase 2 — this manager reads no navdata and composes no other manager.
**Blocks:** manager 2 (Scenario Generator — scheduled failures are its building block), manager 14
(Training Profiles), manager 12 (snapshots include the failure set).

The instructor breaks the aeroplane on purpose, from the tablet, and un-breaks it in one tap.
Three modes — **immediate**, **armed** (fires on a condition) and **cleared** — plus a first-class
**CLEAR ALL** that resets the aircraft in a single action.

Binding rules live in [`../../CLAUDE.md`](../../CLAUDE.md); layers in
[`../architecture.md`](../architecture.md). This document never relaxes any of them. The
Position Manager design ([`position-manager.md`](position-manager.md)) is the house style and
the source of several lessons this design applies deliberately rather than re-learns.

---

## 0. Decisions at a glance

| # | Decision | Where |
|---|---|---|
| D1 | **The catalogue is `core/` data**: ~28 stable dotted string ids (`engine.fire`, `instruments.pitot`, …) as a closed `Literal`, each with label, category and an engine-index flag. No dataref name anywhere near it. | §3.1, §6 |
| D2 | **No `severity` field.** Where the simulator distinguishes severities they are distinct catalogue ids (`engine.failure` vs `engine.partial_power`); a scalar nobody maps to anything is dead data. | §3.1 |
| D3 | **No `armable` field either.** Arming is a server-side scheduler layered over *inject*, so every injectable failure is armable by construction — a per-entry flag could only ever be `True`. | §3.1, §6.2 |
| D4 | **Per-failure support is declared by the adapter** through a new `get_failure_support()` method, mirroring the `AircraftControlManifest` pattern: every catalogue id always appears, unsupported ones carry a stated reason. One `can_inject_failures` flag still gates the group; **no new capability flag is added**. | §4 |
| D5 | **Armed failures live in the server, never in the simulator.** X-Plane's own armed modes (values 1–5) use *global* companion datarefs — one shared trigger value for every armed failure — so two failures armed at different altitudes are inexpressible there, and armed state parked inside one simulator is invisible to the Fake, to MSFS, and to `GET /api/failures/status`. A `core/` trigger evaluator fed by the same telemetry the WebSocket publishes is the only honest home. The adapter only ever hears "fail now" and "clear". | §5.2, §6.2 |
| D6 | **Phase 2 ships five trigger types**: `altitude_above`, `altitude_below`, `speed_above`, `speed_below`, `delay`. Exactly the "time, speed, altitude" the spec names. Takeoff/landing triggers are a later additive arm of the same union. | §3.3 |
| D7 | **Triggers evaluate level, not edge**: an armed failure fires on the first evaluated frame that satisfies its condition, including the frame it was armed on. The UI shows the live value next to the trigger input so "this would fire immediately" is visible before arming. | §6.2 |
| D8 | **Trigger altitudes are feet MSL**, because that is what `AircraftState` carries. AGL triggers need an elevation source and are an open question, not a silent approximation. | §3.3, §10.6 |
| D9 | **Request/trigger models live in `core/failures.py`, not in the router.** The Position Manager put its request models in `server/` (its D4 deviation) and the recorded cost is that scenarios cannot express a placement without importing from `server/`. The Scenario Generator lands *this same phase* and must express "arm `engine.failure` at 100 kt" in YAML — so the models it validates against live in `core/` from day one. | §3, §6 |
| D10 | **`get_active_failures()` reads the simulator, not a server ledger.** The X-Plane teleport procedure ends with `sim/operation/fix_all_systems`, which repairs *every* failure — so a ledger lies the moment the Position Manager is used mid-exercise. The read-back is the honest source; the ledger is only a hint. | §4, §10.2 |
| D11 | **The X-Plane adapter probes its failure datarefs at connect time** through the Web API's dataref index. A name that does not resolve on this install makes that entry *unsupported with a reason* — a wrong guess in the mapping table degrades to a disabled control, never to a runtime throw. | §5.3 |
| D12 | **CLEAR ALL clears armed failures too.** "Reset the aircraft in one action" means the instructor is not surprised ten seconds later by a trigger they forgot. | §2 |
| D13 | **Inject fires immediately — no staging bar.** Position stages because a teleport is disruptive and hard to reverse; a failure is the *product* of this panel and is one tap from cleared. CLEAR ALL is the undo, and it is always on screen. | §7 |
| D14 | **Every error is FastAPI's `detail` sentence**, 501 for capability refusals, matching the shipped convention (`server/app.py`, position §10) rather than the typed error codes position designed and never built. | §2.3 |
| D15 | **The UI extends the API with `injectEndpoints` from `failuresApi.ts`** — the rule position stated and then broke (its §15.3 deviation). Adding this manager adds files; `instructorApi.ts` is not edited. | §7.2 |

---

## 1. Scope

### 1.1 What this manager does

1. **A sim-agnostic failure catalogue** in `core/` — every failure the feature spec lists, as
   stable string identifiers with metadata, independent of any simulator.
2. **A support manifest** — which catalogue entries the *active adapter on this install* can
   actually produce, with a reason for every entry it cannot. The UI disables per entry, never
   discovers by failing (hard rule 3).
3. **Immediate injection** and **clearing**, one failure at a time, plus **CLEAR ALL**.
4. **Armed failures** — a failure scheduled on altitude, speed or a time delay, evaluated by the
   server against the live telemetry stream, listed and disarmable until it fires.
5. **The Failures tab** of the Instructor Panel — catalogue browser grouped by category, an
   active/armed strip, and a large CLEAR ALL.

Feature-spec items covered: the full engines list (fire, total failure, partial power loss) and
the full systems list (electrical, hydraulic, pitot, radio, transponder, GPS, flaps, spoilers,
landing gear, brakes, fuel leak, generator, alternator, vacuum, pressurisation, smoke, bird
strike, lightning strike); the three modes; clear-all; per-entry adapter support declaration.

Roadmap Phase 2 exit criteria this manager serves directly: **#1** (the failure half of the 12
scenarios runs against the Fake in CI and against X-Plane under `-m sim`) and **#4** (*"scenarios
requiring an undeclared capability are reported as unavailable, never attempted"* — the support
manifest is precisely the mechanism the Scenario Generator will query).

### 1.2 What is explicitly out of scope

| Out of scope | Why / owner |
|---|---|
| The Scenario Generator's YAML engine and its trigger *executor* wiring | Manager 2. It **consumes** `core/failures.py` (the trigger models) and `POST /api/failures/arm`; nothing here needs changing when it lands — that is the acceptance test for D9. |
| Takeoff/landing triggers (`on_next_takeoff`, `on_next_landing`) | A later additive arm of the trigger union (§10.5). Phase 2 ships time/speed/altitude, as the spec states. |
| AGL-referenced altitude triggers | Needs an elevation source (§10.6). MSL only in Phase 2. |
| Per-aircraft failure mappings for study-level aircraft (custom datarefs, L:vars) | The same override-layer problem as the autopilot (feature spec §6); Phase 2 ships the sim-standard path plus an honest caveat (§5.4, §10.1). |
| Copilot-side instrument failures, per-cell battery/bus granularity, per-wheel brakes | Additive catalogue rows later. The id scheme leaves room (`instruments.airspeed_copilot`). |
| Failure *effects* modelling in the Fake (an engine failure does not slow the fake aircraft) | The Fake records and reports failures faithfully; simulating failure physics in it would be building a simulator. Its state *is* its failure ledger. |
| Persisting armed failures across a server restart | Accepted loss in Phase 2 (§10.4). Scenarios re-arm on run; profiles re-arm on apply. |
| Random / MTBF failures (X-Plane's mode 1) | Not an instructor tool. An instructor fails a system on purpose. |

---

## 2. REST endpoints

All under `/api/failures/*`, in a new `server/failure_routes.py` registered from
`server/app.py` exactly as `position_routes` is. Commands are REST; the live aircraft picture
stays on `WS /ws/state`, which this manager does not touch.

```
GET    /api/failures/catalogue      -> FailureCatalogueResponse
GET    /api/failures/status         -> FailuresStatus
POST   /api/failures/inject         -> FailuresStatus
POST   /api/failures/arm            -> ArmedFailure
DELETE /api/failures/armed/{armed_id} -> FailuresStatus
POST   /api/failures/clear          -> FailuresStatus
POST   /api/failures/clear-all      -> FailuresStatus
```

| Method | Path | Purpose | Safe? | Idempotent? |
|---|---|---|---|---|
| `GET` | `/catalogue` | The whole catalogue, merged with the adapter's support manifest. Capability-free: it answers "what could I do here?" even when the answer is "nothing, and here is why per entry". | yes | yes |
| `GET` | `/status` | Active failures (read back from the simulator, D10) plus armed failures (the server's scheduler). The panel polls this. | yes | yes |
| `POST` | `/inject` | Fail one system **now**. Injecting an already-failed system is a no-op — the body states a target state, not a delta. | no | **yes** |
| `POST` | `/arm` | Register one armed failure with a trigger; returns the `ArmedFailure` with its server-assigned `armed_id`. **Not** idempotent — arming twice arms two (an instructor may genuinely want the same failure at two altitudes on two engines; deduplication would be the server overruling them). | no | no |
| `DELETE` | `/armed/{armed_id}` | Disarm one armed failure before it fires. 404 when the id does not exist (it may have fired already — the sentence says so). | no | yes |
| `POST` | `/clear` | Repair one active failure. Clearing something that is not failed is a no-op. | no | **yes** |
| `POST` | `/clear-all` | Repair **every** active failure *and* disarm every armed one (D12). The one-tap reset. | no | **yes** |

Every mutating endpoint returns the resulting `FailuresStatus` (except `/arm`, which returns the
created entry — the client already has the rest and RTK Query re-fetches on invalidation), so
the panel reconciles against what the server *did*, not what it asked for — the same posture as
`PlacementResult.state`.

### 2.1 Capability gating

Mirrors `server/app.py`'s 501 convention (`CAPABILITY_UNAVAILABLE_STATUS`) verbatim:

- Adapter does not declare `can_inject_failures` → **501**, *"Unavailable on this adapter — the
  'xplane' adapter does not declare can_inject_failures, so it cannot inject failures."* Applies
  to `/inject`, `/arm`, `/clear`, `/clear-all`. The two `GET`s are never gated — reads degrade
  (`/status` reports empty; `/catalogue` reports every entry unsupported with that reason).
- The specific catalogue entry is unsupported on this adapter → **501** carrying the manifest's
  own `reason` sentence for that entry. Same status, because it is the same situation: a
  well-formed request the active simulator has no implementation behind.
- `CapabilityNotSupported` escaping the adapter anyway is caught and mapped to 501 — defence in
  depth, same as `/api/aircraft/setup`.

Nobody should ever reach these: the panel disables per entry from `/catalogue` before a request
is sent, fail-closed while loading (§7.4).

### 2.2 Validation errors — 422

- Unknown `failure_id` — free, from the closed `FailureId` `Literal`.
- `engine_index` supplied for a non-indexed entry, or absent for an indexed one — a
  `model_validator` on the request models in `core/` (§3.4), so the Scenario Generator gets the
  identical validation when it parses YAML.
- Malformed trigger (negative delay, altitude out of range) — pydantic field constraints.

### 2.3 Everything else

FastAPI's `{"detail": "<one sentence written for the instructor>"}` (D14). An adapter exception
that is not `CapabilityNotSupported` propagates as 500 — the same open 502 question position
recorded (§10.7 here); this design does not fork the convention on its own.

---

## 3. Pydantic models

All in **`core/failures.py`** (D9) unless stated. Units follow `core/models.py`: `_ft` is feet
MSL, `_kt` is indicated knots, `_s` is seconds, `_fpm` is feet per minute. All models are
`frozen=True` — a catalogue entry, a trigger and an armed record are all values, and freezing
also honours the lesson of position §7.1's dropped-`frozen` deviation before manager 14 starts
serialising these into profiles. Request models additionally set `extra="forbid"`, so a typo'd
field in a scenario YAML fails loudly at load time instead of silently arming the wrong thing.

### 3.1 The catalogue

```python
FailureCategory = Literal[
    "engine",
    "fuel",
    "electrical",
    "hydraulics",
    "instruments",
    "avionics",
    "flight_controls",
    "gear",
    "airframe",
]

FailureId = Literal[
    # -- engine (indexed) --
    "engine.failure",
    "engine.fire",
    "engine.partial_power",
    # -- fuel --
    "fuel.leak",
    # -- electrical --
    "electrical.system",
    "electrical.generator",
    # -- hydraulics --
    "hydraulics.system",
    # -- instruments --
    "instruments.pitot",
    "instruments.static",
    "instruments.vacuum",
    "instruments.airspeed",
    "instruments.attitude",
    "instruments.altimeter",
    "instruments.directional_gyro",
    "instruments.turn_coordinator",
    "instruments.vsi",
    # -- avionics --
    "avionics.com1",
    "avionics.com2",
    "avionics.nav1",
    "avionics.nav2",
    "avionics.gps",
    "avionics.transponder",
    # -- flight controls --
    "flight_controls.flaps",
    "flight_controls.spoilers",
    # -- gear & brakes --
    "gear.stuck",
    "gear.brakes",
    # -- airframe --
    "airframe.pressurisation",
    "airframe.smoke",
    "airframe.bird_strike",
    "airframe.lightning_strike",
]


class FailureSpec(BaseModel):
    """One catalogue entry. Sim-agnostic; knows no dataref."""

    model_config = ConfigDict(frozen=True)

    failure_id: FailureId
    label: str  # "Engine fire" — short, for the row
    category: FailureCategory
    takes_engine_index: bool = False
    description: str  # one sentence for the UI hint, e.g. what "stuck" means


FAILURE_CATALOGUE: tuple[FailureSpec, ...]  # in a fixed display order, grouped by category
CATALOGUE_BY_ID: Mapping[FailureId, FailureSpec]
FAILURE_IDS: tuple[FailureId, ...] = get_args(FailureId)  # the CONTROL_IDS pattern
```

The full catalogue, with feature-spec traceability:

| `failure_id` | Label | Category | Indexed | Spec item |
|---|---|---|---|---|
| `engine.failure` | Engine failure | engine | ✔ | Engines — total failure |
| `engine.fire` | Engine fire | engine | ✔ | Engines — fire |
| `engine.partial_power` | Partial power loss | engine | ✔ | Engines — partial power loss |
| `fuel.leak` | Fuel leak | fuel | | Fuel leak |
| `electrical.system` | Total electrical failure | electrical | | Electrical |
| `electrical.generator` | Generator / alternator | electrical | ✔ | Generator + Alternator (one physical thing in every simulator this project targets — two catalogue rows would map to one dataref, so they are merged with a label naming both) |
| `hydraulics.system` | Hydraulic failure | hydraulics | | Hydraulic |
| `instruments.pitot` | Pitot blockage | instruments | | Pitot |
| `instruments.static` | Static port blockage | instruments | | (companion of pitot; the classic paired exercise) |
| `instruments.vacuum` | Vacuum system | instruments | | Vacuum system |
| `instruments.airspeed` | Airspeed indicator | instruments | | (individual instruments) |
| `instruments.attitude` | Attitude indicator | instruments | | " |
| `instruments.altimeter` | Altimeter | instruments | | " |
| `instruments.directional_gyro` | Directional gyro | instruments | | " |
| `instruments.turn_coordinator` | Turn coordinator | instruments | | " |
| `instruments.vsi` | Vertical speed indicator | instruments | | " |
| `avionics.com1` / `avionics.com2` | COM 1 / COM 2 | avionics | | Radio |
| `avionics.nav1` / `avionics.nav2` | NAV 1 / NAV 2 | avionics | | Radio |
| `avionics.gps` | GPS | avionics | | GPS |
| `avionics.transponder` | Transponder | avionics | | Transponder |
| `flight_controls.flaps` | Flaps stuck | flight_controls | | Flaps |
| `flight_controls.spoilers` | Spoilers stuck | flight_controls | | Spoilers |
| `gear.stuck` | Landing gear stuck | gear | | Landing gear |
| `gear.brakes` | Brake failure | gear | | Brakes |
| `airframe.pressurisation` | Pressurisation failure | airframe | | Pressurisation |
| `airframe.smoke` | Smoke in cockpit | airframe | | Smoke |
| `airframe.bird_strike` | Bird strike | airframe | | Bird strike |
| `airframe.lightning_strike` | Lightning strike | airframe | | Lightning strike |

**Ids are stable strings and are the wire format, the YAML format and the profile format.** They
are dotted `category.name`, lowercase, snake_case after the dot. Renaming one after release is a
breaking change to every saved profile — the catalogue integrity test pins the full set (§8.1).

**Engine index is the only index** (D2's sibling decision): hydraulic pumps, buses and brake
sides are folded into single instructor-intent entries whose adapter writes several datarefs.
`engine_index` is **1-based on the wire** (instructors say "engine 1"), `ge=1, le=8`; the adapter
converts to its own 0-based suffix.

### 3.2 Support

```python
class FailureSupport(BaseModel):
    """One catalogue entry resolved against one adapter."""

    model_config = ConfigDict(frozen=True)

    failure_id: FailureId
    supported: bool
    best_effort: bool = False  # supported, but delivery is not guaranteed (D4, §5.4)
    reason: str | None = None  # why unsupported; None when supported


class FailureSupportManifest(BaseModel):
    """What the adapter answers from get_failure_support()."""

    model_config = ConfigDict(frozen=True)

    caveat: str | None = None  # one adapter-level sentence, e.g. the study-aircraft warning
    entries: tuple[FailureSupport, ...]  # exactly one per FAILURE_IDS, in catalogue order
```

Server-side envelope (in `server/failure_routes.py`, because it merges server-known catalogue
metadata with adapter-known support — the exact split `AircraftControlManifest` uses):

```python
class FailureCatalogueEntry(BaseModel):
    failure_id: FailureId
    label: str
    category: FailureCategory
    takes_engine_index: bool
    description: str
    supported: bool
    best_effort: bool
    reason: str | None


class FailureCatalogueResponse(BaseModel):
    adapter: str
    caveat: str | None
    failures: list[FailureCatalogueEntry]  # catalogue order
```

### 3.3 Triggers

```python
class AltitudeAboveTrigger(BaseModel):
    """Fires when altitude_ft >= threshold. Inclusive, MSL (D7, D8)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["altitude_above"]
    altitude_ft: float = Field(ge=-2000.0, le=100_000.0, description="Feet MSL, inclusive.")


class AltitudeBelowTrigger(BaseModel):
    """Fires when altitude_ft <= threshold. Inclusive, MSL."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["altitude_below"]
    altitude_ft: float = Field(ge=-2000.0, le=100_000.0, description="Feet MSL, inclusive.")


class SpeedAboveTrigger(BaseModel):
    """Fires when ias_kt >= threshold. Inclusive. This is the V1-cut trigger:
    armed on the ground before the roll, it fires as the aircraft accelerates through V1."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["speed_above"]
    ias_kt: float = Field(ge=0.0, le=500.0, description="Knots indicated, inclusive.")


class SpeedBelowTrigger(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["speed_below"]
    ias_kt: float = Field(ge=0.0, le=500.0, description="Knots indicated, inclusive.")


class DelayTrigger(BaseModel):
    """Fires delay_s seconds of wall-clock time after arming. Wall clock, not sim
    time: the station cannot see sim time, and saying so beats pretending (§10.3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["delay"]
    delay_s: float = Field(gt=0.0, le=86_400.0, description="Seconds after arming.")


FailureTrigger = Annotated[
    AltitudeAboveTrigger
    | AltitudeBelowTrigger
    | SpeedAboveTrigger
    | SpeedBelowTrigger
    | DelayTrigger,
    Field(discriminator="type"),
]
```

Every optional-or-defaulted choice a trigger could have hidden is instead a distinct arm of the
union — the same "the discriminator is `type`" shape as `PlacementRequest`, so the generated
TypeScript client gets a proper tagged union.

### 3.4 Requests and state

```python
class FailureRef(BaseModel):
    """A failure instance: the id plus its engine index when the entry takes one.

    The validator is the reason these models live in core/: the Scenario
    Generator gets identical validation parsing YAML, with no HTTP anywhere.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    failure_id: FailureId
    engine_index: int | None = Field(
        default=None, ge=1, le=8, description="1-based. Required iff the entry is indexed."
    )

    @model_validator(mode="after")
    def _index_matches_catalogue(self) -> "FailureRef":
        spec = CATALOGUE_BY_ID[self.failure_id]
        if spec.takes_engine_index and self.engine_index is None:
            raise ValueError(f"{self.failure_id} takes an engine index (1-based); none given.")
        if not spec.takes_engine_index and self.engine_index is not None:
            raise ValueError(f"{self.failure_id} does not take an engine index.")
        return self


class InjectFailureRequest(FailureRef):
    """POST /api/failures/inject — nothing beyond the ref."""


class ClearFailureRequest(FailureRef):
    """POST /api/failures/clear."""


class ArmFailureRequest(FailureRef):
    """POST /api/failures/arm."""

    trigger: FailureTrigger


class ActiveFailure(FailureRef):
    """One failure the simulator reports as failed right now."""


class ArmedFailure(FailureRef):
    """One armed failure, as listed and as returned by /arm."""

    armed_id: str = Field(description="Server-assigned opaque id (uuid4 hex).")
    trigger: FailureTrigger
    armed_at: datetime = Field(description="UTC wall clock, for the panel's countdown display.")
    last_error: str | None = Field(
        default=None,
        description="Set when the trigger fired but injection failed; retried every frame.",
    )


class FailuresStatus(BaseModel):
    active: list[ActiveFailure]  # from adapter.get_active_failures() — the sim's truth (D10)
    armed: list[ArmedFailure]  # from the server's scheduler
```

---

## 4. `SimAdapter` / `Capabilities` additions

**This is a shared-foundation change. It is made once, alone, by one agent, before any dependent
work branches off it — and it must not run concurrently with the Weather or Fuel & Payload
managers' own contract changes** (§9).

**No new capability flag.** `can_inject_failures` already exists on `Capabilities` and is
sufficient: per-failure granularity is the manifest's job, not a flag explosion. Four methods are
added to the `SimAdapter` protocol:

```python
async def get_failure_support(self) -> FailureSupportManifest:
    """Which catalogue entries this adapter can inject, one entry per FAILURE_IDS,
    in catalogue order. A capability-free read (same posture as get_airframe):
    an adapter without can_inject_failures returns every entry unsupported with
    that stated reason — "no" is an answer, never an exception."""


async def inject_failure(self, failure: FailureRef) -> None:
    """Fail the referenced system immediately. Idempotent: injecting an
    already-failed system changes nothing. Requires can_inject_failures;
    an unsupported failure_id raises CapabilityNotSupported."""


async def clear_failure(self, failure: FailureRef) -> None:
    """Repair the referenced system. Idempotent; clearing a working system is a
    no-op. Requires can_inject_failures."""


async def clear_all_failures(self) -> None:
    """Repair every failure this adapter can see. Idempotent.
    Requires can_inject_failures."""


async def get_active_failures(self) -> tuple[ActiveFailure, ...]:
    """Read back which supported failures are failed *right now*, from the
    simulator itself — never from a ledger of what was asked for (D10: a
    teleport's fix_all_systems repairs everything behind the ledger's back).
    A capability-free read: an adapter that cannot see failures returns ()."""
```

Armed failures deliberately do **not** appear in this interface (D5). Arming is
`core/failure_scheduler.py` + the server; the adapter's whole vocabulary is *fail now*, *repair*,
*what is failed*.

### 4.1 What `FakeSimAdapter` must do

- Declare `can_inject_failures=True` (it already does — the all-capabilities reference).
- `get_failure_support()` — every entry `supported=True, best_effort=False, reason=None`,
  `caveat=None`.
- Keep `self._failures: set[tuple[FailureId, int | None]]`. `inject_failure` adds,
  `clear_failure` discards, `clear_all_failures` clears, `get_active_failures` returns the set
  as `ActiveFailure`s in a deterministic order (catalogue order, then engine index).
- Validate the ref against the catalogue the same way the models do (free — `FailureRef` already
  validated on construction).
- **No physics.** The fake's failure state *is* its observable behaviour; the contract asserts
  the ledger round-trip, not aerodynamics.

### 4.2 Contract tests to add — `tests/adapters/test_contract.py`

`CAPABILITY_COVERAGE["can_inject_failures"]` moves from `PENDING` to
`"test_injected_failure_is_reported_active"` — `test_every_capability_is_covered` forces exactly
this edit, which is the suite working as designed. New parametrised cases (fake in CI, xplane
under `-m sim`, every injection cleared in a `finally` per the live-suite rules):

| Test | Pins |
|---|---|
| `test_failure_support_covers_the_whole_catalogue` | `get_failure_support()` returns exactly one entry per `FAILURE_IDS`, in order; every unsupported entry carries a non-empty `reason`. |
| `test_injected_failure_is_reported_active` | inject `instruments.pitot` → `get_active_failures()` contains it → clear in `finally`. The read-back is the assertion, not the absence of an exception (the same lesson as issue #39: a write is not delivered until something reads it back). |
| `test_indexed_failure_carries_its_engine_index` | inject `engine.failure` engine 2 → active list contains `(engine.failure, 2)` and not `(engine.failure, 1)`. |
| `test_clear_failure_repairs_it` | inject, clear, read back absent. |
| `test_clear_all_failures_leaves_none_active` | inject two (one indexed, one not), clear-all, read back empty. |
| `test_inject_is_idempotent` | inject twice, active list contains it once, one clear repairs it. |
| `test_failure_methods_refuse_without_the_capability` | a `FakeSimAdapter` subclass declaring `can_inject_failures=False` (the existing refusal-test pattern): `inject`/`clear`/`clear_all` raise `CapabilityNotSupported`; `get_failure_support` returns all-unsupported-with-reason; `get_active_failures` returns `()`. |

Live-only tolerances: none needed — failure state is discrete. The one live-only difference is
latency, which the tests absorb by polling `get_active_failures` briefly rather than asserting
the first read.

---

## 5. Dataref mapping (X-Plane)

**This section describes `adapters/xplane/` only. No dataref name may appear in `core/`.**
This is not a weather design; no weather-mode forcing is involved — failure datarefs are not
overwritten by real weather.

### 5.1 The `sim/operation/failures/rel_*` family and its value convention

Every X-Plane failure is one int dataref in `sim/operation/failures/`, with this enum:

| Value | Meaning |
|---|---|
| 0 | always working |
| 1 | mean time until failure (random, driven by a *global* MTBF dataref) |
| 2 | exact time until failure (global companion value) |
| 3 | fail at exact speed, KIAS (global companion value) |
| 4 | fail at exact altitude, **AGL** (global companion value) |
| 5 | fail on key/button press |
| 6 | **inoperative now** |

**The adapter writes only 0 and 6.** Modes 1–5 are deliberately unused (D5): their trigger
values are single global companion datarefs shared across every armed failure, so "engine 1 at
100 kt and pitot below 3 000 ft" — a routine lesson — is inexpressible inside the simulator. The
enum above is quoted from X-Plane's published dataref documentation and **must be verified
against the live install's `DataRefs.txt` in the spike** (§10.8) before the adapter hard-codes
the constants; the design's correctness does not depend on the exact numerals, only on "there is
a *failed now* value and a *working* value".

- **Inject** = write `6` to every dataref mapped to the entry.
- **Clear** = write `0` to the same set.
- **Clear-all** = fire the command `sim/operation/fix_all_systems` (already in the adapter's
  `COMMANDS` map for the teleport procedure) **and** write `0` to every mapped dataref — the
  command is believed to repair everything, and the explicit zeros make the outcome independent
  of that belief.
- **`get_active_failures`** = read every *supported* mapped dataref; an entry is active iff any
  of its datarefs reads `6`. Values 1–5 (someone armed something in the sim's own UI) are **not**
  reported active — the system still works. This also means failures set from the simulator's
  own failure screen show up honestly in the station.

### 5.2 The mapping table — `adapters/xplane/failure_datarefs.py`

A new module, one mapping, in the style of the adapter's existing `DATAREFS` dict.
`{n}` is the 0-based engine suffix, from the wire's 1-based `engine_index - 1`.

| Catalogue id | Dataref(s) | Confidence |
|---|---|---|
| `engine.failure` | `sim/operation/failures/rel_engfai{n}` (0–7) | high |
| `engine.fire` | `sim/operation/failures/rel_engfir{n}` | high |
| `engine.partial_power` | **none known** — ships unsupported with reason *"X-Plane publishes no standard partial-power failure; use engine.failure or a fuel-system failure."* unless the spike finds one | — |
| `fuel.leak` | verify in spike (the XP12 failure UI lists a fuel leak; the dataref ident is unconfirmed) | low |
| `electrical.system` | `rel_esys` **and** `rel_esys2` (both buses — a *total* electrical failure, which is what the scenario needs) | medium |
| `electrical.generator` | `rel_genera{n}` | high |
| `hydraulics.system` | `rel_hydpmp` **and** `rel_hydpmp2` | medium |
| `instruments.pitot` | `rel_pitot` (pilot side) | high |
| `instruments.static` | `rel_static` (pilot side) | high |
| `instruments.vacuum` | `rel_vacuum` **and** `rel_vacum2` | medium |
| `instruments.airspeed` | `rel_ss_asi` | high |
| `instruments.attitude` | `rel_ss_ahz` | high |
| `instruments.altimeter` | `rel_ss_alt` | high |
| `instruments.directional_gyro` | `rel_ss_dgy` | high |
| `instruments.turn_coordinator` | `rel_ss_tsi` | high |
| `instruments.vsi` | `rel_ss_vvi` | high |
| `avionics.com1` / `com2` | `rel_com1` / `rel_com2` | high |
| `avionics.nav1` / `nav2` | `rel_nav1` / `rel_nav2` | high |
| `avionics.gps` | `rel_gps` | medium |
| `avionics.transponder` | `rel_xpndr` | medium |
| `flight_controls.flaps` | `rel_flap_act` — the actuator fails, the surface **freezes where it is**; `FailureSpec.description` says exactly that, because "flaps failed" reads as "flaps up" otherwise | medium |
| `flight_controls.spoilers` | verify in spike | low |
| `gear.stuck` | verify in spike (candidates: a per-leg `rel_lagear*` family vs a single actuator ref) | low |
| `gear.brakes` | verify in spike (candidates: left/right pair — both written for one entry) | low |
| `airframe.pressurisation` | verify in spike | low |
| `airframe.smoke` | `rel_smoke_cpit` | medium |
| `airframe.bird_strike` | verify in spike (present in the XP12 failure UI) | low |
| `airframe.lightning_strike` | verify in spike (present in the XP12 failure UI) | low |

### 5.3 Connect-time probing makes wrong names harmless (D11)

The Web API exposes the dataref index (the adapter already resolves its `DATAREFS` and
`OPTIONAL_DATAREFS` ids at `connect()`). Failure datarefs are resolved the **optional** way: an
ident that does not exist on this install marks its catalogue entries
`supported=False, reason="No 'sim/operation/failures/…' dataref on this X-Plane install."` and
never fails `connect()`. Consequences:

- Every "low confidence" row above is safe to ship: if the guess is wrong, the entry is visibly
  disabled with a reason instead of throwing on tap — hard rule 3 enforced mechanically.
- The spike (§10.8) then upgrades guesses to facts, and each corrected ident *lights the entry
  up* with no interface change anywhere.

### 5.4 The manifest caveat and `best_effort`

`FailureSupportManifest.caveat` on X-Plane:

> *"Aircraft with their own failure model (many study-level add-ons) may ignore simulator
> failures. Verify against your aircraft before a lesson depends on one."*

Per-entry `best_effort` stays `False` in Phase 2: the adapter cannot know per aircraft whether
`rel_*` is honoured, and marking everything best-effort would be noise pretending to be
information. The caveat is the honest, quiet form; per-aircraft mapping overlays are §10.1.

### 5.5 One real cross-manager interaction: teleports repair failures

The validated reposition procedure ends with `sim/operation/fix_all_systems` — which repairs
every active failure. An instructor who fails the vacuum pump and then repositions the aircraft
onto a practice approach would silently get a healthy aeroplane. **Recommendation:**
`XPlaneSimAdapter.set_position` snapshots the active failure datarefs before the teleport and
re-writes any `6`s after `fix_all_systems`, inside the same call. That is adapter-internal (no
interface change), verified under `-m sim` (§8.4). Until it is implemented, the panel's
`/status` poll at least *shows* the failures disappearing — D10 is what keeps the display honest
either way.

### 5.6 MSFS (Phase 5 target)

SimConnect has no working general failure-injection surface in MSFS — the FSX-era failure
SimVars are largely non-functional, and study-level aircraft use internal systems reachable only
via L:vars (MobiFlight WASM, optional add-on). Expected shape: `can_inject_failures=False`
initially, or `True` with a near-empty manifest built per aircraft from an L:var mapping layer.
The per-entry manifest is exactly the tool for that; nothing in `core/`, `server/` or `ui/`
changes, which is the Phase 5 measure of success.

---

## 6. `core/` logic

Two new modules, both fully unit-testable with no simulator, no adapter, no clock and no I/O.

### 6.1 `core/failures.py` — the catalogue and the vocabulary

Everything in §3: `FailureCategory`, `FailureId`, `FailureSpec`, `FAILURE_CATALOGUE`,
`CATALOGUE_BY_ID`, `FAILURE_IDS`, the trigger union, `FailureRef` and its subclasses,
`FailureSupport`, `FailureSupportManifest`, `ActiveFailure`, `ArmedFailure`, `FailuresStatus`.
Pure data and validation. Imports `core.models` (for nothing yet) and pydantic; nothing else.

### 6.2 `core/failure_scheduler.py` — the arming state machine

A pure, synchronous state machine. **No asyncio, no clock of its own, no adapter** — time and
telemetry are inputs, which is what makes it testable against a fake clock:

```python
class FailureScheduler:
    def arm(self, request: ArmFailureRequest, *, now_monotonic: float,
            armed_at: datetime) -> ArmedFailure: ...
    def disarm(self, armed_id: str) -> bool:          # False when unknown
    def disarm_all(self) -> None: ...
    @property
    def armed(self) -> tuple[ArmedFailure, ...]: ...  # stable order: armed_at, then armed_id
    def evaluate(self, state: AircraftState, *, now_monotonic: float
                 ) -> tuple[ArmedFailure, ...]:
        """Return every armed failure whose trigger is satisfied by this frame,
        removing them from the armed set. Level-triggered and inclusive (D7):
        altitude_above fires when state.altitude_ft >= trigger.altitude_ft, and
        an already-satisfied condition fires on the first frame evaluated."""
    def restore(self, entry: ArmedFailure, *, error: str) -> None:
        """Put a fired entry back (with last_error set) when injection failed;
        it will fire again on the next satisfying frame."""
```

Trigger semantics, pinned here once so the server and the tests cannot disagree:

| Trigger | Fires when | Units |
|---|---|---|
| `altitude_above` | `state.altitude_ft >= altitude_ft` | feet MSL |
| `altitude_below` | `state.altitude_ft <= altitude_ft` | feet MSL |
| `speed_above` | `state.ias_kt >= ias_kt` | knots indicated |
| `speed_below` | `state.ias_kt <= ias_kt` | knots indicated |
| `delay` | `now_monotonic - armed_monotonic >= delay_s` | seconds, server wall clock |

### 6.3 The server's watcher — `server/failure_routes.py`

The one place a timer can honestly run externally is the server, so it runs there: a
module-owned watcher task (the same module-singleton pattern as the navdata index worker)
consuming `adapter.stream_state(FAILURE_EVAL_INTERVAL_S)` with
`FAILURE_EVAL_INTERVAL_S = 0.25` — trigger latency is bounded by one frame. Lifecycle:

- Started lazily on the first `arm`; cancelled when the armed set empties. No armed failures →
  no background traffic.
- For each frame: `fired = scheduler.evaluate(state, now_monotonic=monotonic())`; for each fired
  entry `await adapter.inject_failure(ref)`; on exception, `scheduler.restore(entry, error=str(e))`
  — the entry stays armed with `last_error` visible in `/status`, and is retried on the next
  satisfying frame. An unreachable simulator therefore delays a firing instead of losing it.
- If the stream itself dies (adapter disconnected), the watcher backs off and re-enters while
  anything is armed. **Nothing evaluates while telemetry is down** — including delay triggers,
  whose deadline may pass; they fire on the first frame after telemetry resumes. Stated, not
  hidden: injecting into a dead simulator is impossible anyway, and "fires late, visibly" beats
  "fires never, silently".
- `reset_failures()` clears the scheduler and cancels the task, for tests — the `reset_adapter()`
  pattern from `server/deps.py`.

Armed state lives in this process's memory. Simulator reconnects preserve it; a server restart
loses it (accepted, §10.4).

---

## 7. UI panel outline

`ui/src/features/failures/` — a new tab of the Instructor Panel. Adding it adds files;
per D15 it does **not** edit `instructorApi.ts`.

### 7.1 Components

| File | Role |
|---|---|
| `FailuresPanel.tsx` | The tab: gate → active/armed strip on top → catalogue below. |
| `ActiveStrip.tsx` | Always visible, sticky. Active failures as red chips (label + engine index, tap-to-clear with a small ✕), armed failures as amber chips (label + trigger sentence + countdown for delays + disarm ✕, plus `last_error` when set), and **CLEAR ALL** — the largest control on the surface, destructive-styled, ≥ 44 px, enabled whenever `active.length + armed.length > 0`. No confirmation dialog: it is the *recovery* action, and making the fix slower than the break is backwards. |
| `FailureCatalogue.tsx` | Category-grouped list (accordion sections in catalogue order), search filter across labels. |
| `FailureRow.tsx` | One entry: label, description as hint text, engine-index segmented picker (1..2 shown by default, expandable) when `takes_engine_index`, then two actions: **Fail now** (immediate `inject`, D13) and **Arm…** (expands the row into the trigger editor — inline, never a modal). Unsupported entries render disabled with `reason` inline, exactly like unpositionable procedure legs. |
| `TriggerEditor.tsx` | Segmented trigger-type control, one numeric field with its unit label (`ft MSL`, `kt`, `s`), and — the D7 honesty affordance — the **live telemetry value** beside it (*"now: 3 250 ft"*, from the existing telemetry slice), so a condition that would fire immediately is visible before **Arm** is tapped. |
| `gate.ts` | `failuresGate(capabilities, isError)` — fail-closed, the `position/gate.ts` pattern verbatim: closed while loading, closed on error, closed without `can_inject_failures`, and the whole tab shows the reason while the catalogue stays browsable. |
| `format.ts` | Trigger → sentence (*"arms engine 1 failure at ≥ 100 kt"*), countdown formatting. Pure, no React (the `react-refresh` lint rule position recorded). |
| `failuresSlice.ts`, `failuresApi.ts` | Below. |

Tablet-first: the ActiveStrip is reachable with a thumb at the top of the tab; rows are 44 px+;
"fail engine 1" is two taps (expand engine section is pre-expanded when the category has active
failures). The caveat sentence (§5.4) renders once, under the panel title, in tertiary text.

### 7.2 State — one RTK slice + injected endpoints

`failuresApi.ts` uses `instructorApi.injectEndpoints` / `enhanceEndpoints` with a new tag
`FailuresStatus`:

- `getFailureCatalogue` (query; cached until adapter changes — effectively forever per session),
- `getFailuresStatus` (query; `pollingInterval: 2000` while the tab is mounted — the active set
  changes server-side when a trigger fires or a teleport repairs, and polling one small GET is
  the boring option; no WebSocket change, the same precedent as the navdata build),
- `injectFailure`, `armFailure`, `disarmFailure`, `clearFailure`, `clearAllFailures`
  (mutations; all invalidate `FailuresStatus`).

`failuresSlice.ts` holds **client state only** — server data never lands in it:

```ts
interface FailuresState {
  search: string;
  openCategory: FailureCategory | null;      // which accordion section is expanded
  armDraft: {                                // the inline trigger editor, one at a time
    failureId: FailureId;
    engineIndex: number | null;
    trigger: FailureTrigger;                 // generated union type from schema.d.ts
  } | null;
}
```

All API types come from the regenerated `ui/src/api/schema.d.ts`. `FailureId` and the trigger
union arrive as closed unions from the OpenAPI schema — nothing is hand-written.

### 7.3 Capability gating, restated

- Tab-level: `can_inject_failures` via `failuresGate`, fail-closed.
- Row-level: `supported` from `/catalogue`; disabled rows show `reason` inline.
- Nothing in the panel ever computes its own "is this supported" beyond those two inputs.

---

## 8. Test plan

Everything except §8.4 runs in CI against `FakeSimAdapter`. **No navdata, no fixtures from any
simulator install** — this manager needs neither, which makes the fixture strategy trivial:
hand-built `AircraftState` frames and the catalogue itself.

### 8.1 `core/` unit tests — `tests/core/test_failures.py`, `tests/core/test_failure_scheduler.py`

Catalogue integrity:

- `FAILURE_IDS` (from the `Literal`) and `{s.failure_id for s in FAILURE_CATALOGUE}` are equal —
  the `CONTROL_IDS` drift-guard pattern.
- Ids are unique, dotted, lowercase; every entry has a non-empty label and description; every
  `engine.*` entry that should take an index does (`engine.failure`, `engine.fire`,
  `engine.partial_power`, `electrical.generator` — pinned as an explicit set, so an accidental
  flag flip fails a test).
- The full id set is pinned verbatim (ids are the profile/YAML format; renaming must be loud).

`FailureRef` validation: `engine.failure` without an index → `ValidationError`;
`instruments.pitot` with one → `ValidationError`; `engine.fire` with `engine_index=2` → valid.

Scheduler, against a fake clock and hand-built frames (concrete reference values, all asserted
exactly):

- **Delay:** armed with `delay_s=5.0` at `now_monotonic=1000.0` → `evaluate` at `1004.99` fires
  nothing; at `1005.0` fires it (inclusive boundary).
- **Altitude below 3000 ft:** frames at 3200 → no, 3000.0 → **fires** (inclusive), and a
  separate case 2990 → fires; already-below-when-armed (frame 2500) fires on the first evaluate
  (D7 pinned).
- **Speed above 100 kt** (the V1 cut): frames 60, 99.9 → no; 100.0 → fires.
- Fired entries are removed: a second `evaluate` on the same frame returns nothing.
- Two armed entries with different thresholds fire independently on the right frames — the exact
  case X-Plane's global companion datarefs cannot express, pinned as the reason D5 exists.
- `disarm` before the satisfying frame → never fires; `disarm` of an unknown id → `False`.
- `restore` puts a fired entry back with `last_error` set, and it fires again on the next
  satisfying frame.

### 8.2 Contract tests

The suite of §4.2, parametrised over both adapters as always. These are written by the tester
**from this document, before the implementation exists** — the models in §3 and the signatures
in §4 are the complete contract.

### 8.3 Server tests — `tests/server/test_failure_routes.py`

Against `TestClient` + `FakeSimAdapter`, `reset_failures()` between tests:

- `/catalogue` merges catalogue metadata with the fake's manifest; every entry supported.
- `/inject` → `/status.active` contains it; repeated inject stays one entry; `/clear` empties it.
- `/clear-all` empties **both** lists (D12) — inject one, arm one, clear-all, assert both gone
  and the watcher task stops.
- 501 sentences from a subclassed fake with `can_inject_failures=False`, for all four mutating
  routes; both GETs still answer (all-unsupported catalogue, empty status).
- 422: unknown id, index mismatch both ways, negative delay.
- `DELETE /armed/{id}` unknown → 404 with the "may have already fired" sentence.
- **Watcher integration, live against the fake:** the fake flies — construct it descending
  (initial `vertical_speed_fpm=-1000`, `altitude_ft=3000`), arm `instruments.pitot` with
  `altitude_below=2800`, and poll `/status` with a ~5 s timeout until the entry moves from
  `armed` to `active`. This proves the whole loop — stream → scheduler → inject — with no
  simulator and no mocking of time.
- Injection retry: a fake whose `inject_failure` raises once then succeeds → entry stays armed
  with `last_error` set, then becomes active.

### 8.4 `@pytest.mark.sim` — `tests/sim/test_live_failures.py` (never in CI)

What only a live X-Plane proves:

- Inject `engine.failure` engine 1 → `read_dataref` on `rel_engfai0` returns the *failed now*
  value; clear → the *working* value. This validates the enum of §5.1 empirically.
- `clear_all_failures` after two injections leaves every mapped dataref at *working*.
- The §5.5 interaction: inject, `set_position` a short hop, assert the failure is still active
  afterwards (this test is the specification for the snapshot-and-re-assert recommendation; it
  fails honestly until that is implemented — never xfail it, per the testing rules).
- `get_failure_support` on the live install: every "high confidence" row of §5.2 resolves.

All in `finally`-protected blocks, per the live-suite rules; nothing here moves the aircraft
except the interaction test, which restores.

### 8.5 UI tests (vitest)

- `gate.test.ts` — fail-closed on loading, error, and missing flag.
- `format.test.ts` — trigger sentences and countdowns from fixed inputs.
- `FailureRow` / `TriggerEditor` — an unsupported row renders disabled with its reason; the
  editor sends the exact `ArmFailureRequest` body (asserted with `toEqual` against a stubbed
  `fetch`, the position pattern — no picker may quietly default a field).
- `ActiveStrip` — CLEAR ALL issues exactly one `clear-all` request; disabled when both lists are
  empty; `last_error` is rendered.
- `FailuresPanel` — inject path end to end against stubbed fetch: tap "Fail now" on an indexed
  entry without picking an engine is impossible (picker defaults to 1 and the body says so).

---

## 9. Parallelisation

### 9.1 Across Phase 2

This manager is one of the three independent Phase 2 tracks (Weather ∥ Failures ∥ Fuel &
Payload), on its own branch `feature/failures-manager` in its own **git worktree**, with its own
PR to `dev`; CI is the integration barrier. **But all three managers need contract changes, and
contract changes are never parallelised** — the §4 additions to `core/sim_adapter.py`,
`adapters/fake/fake_adapter.py` and `tests/adapters/test_contract.py` must land serially with
respect to Weather's and Fuel's equivalents. Practical sequencing: each manager's foundation
commit is made alone against the then-current `dev` (or the contract queue is agreed up front);
what is forbidden is two agents editing those three files concurrently.

### 9.2 Inside this manager

**Track 0 — the foundation (serialised, first, one agent):**
`core/failures.py` (catalogue + models — the Fake and the contract suite need them), the §4
protocol methods, `FakeSimAdapter`, and the §4.2 contract tests.
Owns: `core/failures.py`, `core/sim_adapter.py`, `adapters/fake/`, `tests/adapters/test_contract.py`, `tests/core/test_failures.py`.

Then two tracks, dispatched **in one message**, disjoint directories:

**Track A — backend:** `core/failure_scheduler.py`, `server/failure_routes.py` + the router
registration line in `server/app.py`, `tests/core/test_failure_scheduler.py`,
`tests/server/test_failure_routes.py`.
Owns: `core/failure_scheduler.py`, `server/`, `tests/core/`, `tests/server/`.

**Track B — X-Plane mapping:** `adapters/xplane/failure_datarefs.py`, the four method
implementations in `adapters/xplane/xplane_adapter.py`, the connect-time probe,
`tests/sim/test_live_failures.py`, and the spike `spikes/failure_datarefs.py` (§10.8).
Owns: `adapters/xplane/`, `tests/sim/`, `spikes/`.

**Track C — the panel:** `ui/src/features/failures/*` and the `failuresApi.ts` injection.
Sequenced **after Track A** on the same branch, because it needs `schema.d.ts` regenerated from
the running server — the exact reason position's four planned tracks collapsed to one branch,
learned once and applied here instead of re-learned. Track C's pure logic (`gate.ts`,
`format.ts`, the slice) can be written from this document while A runs; the wiring waits for the
regen.

**The tester does not wait:** the contract suite (§8.2) and the scheduler tests (§8.1) are
written against this document, before any implementation exists.

**Never parallelised, restated:** the Track 0 files; merges to `dev`/`main`; release tagging.
No navdata schema is touched by this manager.

---

## 10. Open questions and risks

### 10.1 Study-level aircraft ignore `rel_*` — how the manifest stays honest

The known risk from `architecture.md` §5, arriving early. The sim-side datarefs will *report*
failed (the read-back shows `6`) while the add-on aircraft's own systems fly on unbothered — so
even D10's read-back cannot detect the lie. Phase 2 answer: the adapter-level `caveat` (§5.4),
rendered once in the panel. The real fix is a per-aircraft mapping overlay keyed on the loaded
airframe (the same override-layer design the autopilot already anticipates), feeding per-entry
`best_effort` honestly. **What resolves it:** a live measurement against one study-level
aircraft (does the read-back show `6`? does the aircraft care?), then a decision on the overlay
format. Until then the caveat states exactly what is known.

### 10.2 `fix_all_systems` repairs failures behind the manager's back

§5.5. Recommendation is snapshot-and-re-assert inside `set_position`; the `-m sim` interaction
test is written first and specifies it. **Decision needed from the user** only if re-assertion
is judged surprising ("I teleported, why is the engine still on fire?" — this design's answer:
because you set it on fire and did not clear it; teleporting is not repairing).

### 10.3 Delay triggers run on wall clock, not sim time

A paused simulator does not pause a `delay` trigger. `AircraftState` carries no sim time, so the
station cannot honestly do better in Phase 2; the field description says "wall clock" and the UI
countdown makes the behaviour visible. **What resolves it:** a sim-time read on the contract
(a serialised addition), if instructors report it mattering.

### 10.4 Armed failures do not survive a server restart

Accepted for Phase 2: the scheduler is process memory. Scenarios re-arm when run; a mid-lesson
server crash loses armed (not active) failures. Persisting them would need a store and a startup
re-arm pass — cheap, but not before anyone has asked for it.

### 10.5 Takeoff/landing triggers

`on_ground` edges in `AircraftState` make `on_next_takeoff` / `on_next_landing` a small additive
arm of the trigger union with edge (not level) semantics — deliberately deferred so Phase 2
ships exactly the spec's "time, speed, altitude". No wire break when added.

### 10.6 Altitude triggers are MSL; instructors often think AGL

X-Plane's own mode 4 is AGL; ours is MSL because that is what telemetry carries. The UI labels
the field "ft MSL" and shows the live MSL value beside it. An AGL option needs an elevation
source — plausibly the nearest-airport reference the position notes already use — and is
deferred with that sketch recorded.

### 10.7 No 502 for an unreachable simulator

Inherited from position §10.2's open item; a failed adapter call surfaces as 500. When the 502
convention is settled it is settled once, app-wide — this manager follows, it does not fork.

### 10.8 The dataref idents and the value enum need one spike

Every "verify" row in §5.2 and the enum in §5.1. `spikes/failure_datarefs.py`: connect to a live
install, dump every dataref under `sim/operation/failures/`, exercise inject/clear on one
instrument, and record the results into `failure_datarefs.py` as facts. Throwaway, never
imported, never tested — and D11 means shipping *before* the spike is still safe, just with more
entries reading "unsupported on this install".

### 10.9 `get_active_failures` cost over REST

~30–40 sequential dataref reads per call on X-Plane, polled at 2 s by one panel. Probably fine
on a LAN; **measure under `-m sim`**. Fallbacks if it is not: batch via the Web API's WebSocket
dataref subscription, or read only (ledger ∪ previously-active) with a full sweep on panel open.
The interface does not change either way.

---

## 11. Verification

```bash
pytest && ruff check . && ruff format --check . && mypy .
cd ui && npm run lint && npm run typecheck && npm test && npm run build
```

Then, against `OIS_ADAPTER=fake` with the Vite dev server, one batched browser session: open the
Failures tab → catalogue grouped and searchable → fail engine 1 → chip appears in the strip →
arm pitot below the current altitude minus 500 ft while descending (fake flies; set a negative
VS from the Aircraft Control panel) → watch it fire → CLEAR ALL empties everything, plus a
console check. Live-sim validation (`pytest -m sim`, §8.4) is the `sim-validator` agent's job
and is not a merge gate.
