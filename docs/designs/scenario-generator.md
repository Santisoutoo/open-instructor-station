# Flight Scenario Generator — design

**Status:** designed, not yet implemented.
**Issue:** [#17](https://github.com/Santisoutoo/open-instructor-station/issues/17), feature spec manager 2 ([`../feature-spec.md`](../feature-spec.md#2-flight-scenario-generator)), ⭐⭐⭐⭐⭐.
**Phase:** 2 — Weather + Failures → Scenario Generator ([`../roadmap.md`](../roadmap.md#phase-2--weather--failures--scenario-generator)). This manager is the second half of the phase and composes the first: Weather (#14/manager 3), Failures (#15/manager 4) and Fuel & Payload (#16/manager 9) must all be on `dev` before this one starts.
**Depends on:** `docs/designs/weather-manager.md`, `docs/designs/failures-manager.md` (both read in full), the shipped Position Manager (`docs/designs/position-manager.md`, `server/position_routes.py`, `core/geodesy.py`), and provisionally `docs/designs/fuel-payload.md` (not available at design time — see §10.1).
**Blocks:** Training Profiles (manager 14, same roadmap phase — "a training profile is a saved scenario with a name and metadata: same model, same validation, same execution path").

One click puts the student in a specific, repeatable training situation. This is the **composing** manager of Phase 2: it invents almost nothing of its own and instead validates, sequences and runs the building blocks the other three managers already expose.

Binding rules live in [`../../CLAUDE.md`](../../CLAUDE.md); layers in [`../architecture.md`](../architecture.md). This document never relaxes any of them.

---

## 1. Decisions at a glance

| # | Decision | Where |
|---|---|---|
| D1 | **Scenario YAML files live at `core/scenarios/data/*.yaml`**, discovered by a directory scan, not a top-level `scenarios/` — self-contained under the manager that owns the loader, same shape as `core/weather/presets.py`'s co-located data. Not covered by the navdata filename blocklist (`.yaml` is not `.dat`/`cycle_info.txt`/`.sqlite`), but the directory name is unambiguous regardless. | §2, §6.1 |
| D2 | **The scenario id IS the filename stem** (lowercase kebab-case, enforced by a regex), never a field inside the document. A file cannot collide with itself, and "add a scenario" is literally "add a correctly-named file" — no registry, no id field to keep in sync. | §6.1 |
| D3 | **`ScenarioDocument` reuses every other manager's own request/setup model verbatim** — `PlacementRequest` (moved to `core/placements.py`, D4), `AircraftSetup` (`core.models`), `WeatherRequest` (`core.weather.models`), `InjectFailureRequest` / `ArmFailureRequest` (`core.failures`). Nothing scenario-specific is reinvented; a typo'd field fails validation exactly as it would over that manager's own REST endpoint. | §4 |
| D4 | **Move the `PlacementRequest` union and its variant models from `server/position_routes.py` into a new `core/placements.py`.** Mechanical, wire-format-preserving; closes the gap `position-manager.md` §7.6 recorded as "the natural first step" of its own regret. `server/position_routes.py` imports them back and re-exports under the same `__all__`. Resolution logic (`_resolve_placement`, the notes, the schematic) **stays in `server/`** — only the models move. | §4.1, §9 |
| D5 | **Add a seventh placement kind, `RunwayThresholdPlacementRequest`** — on the runway centreline at the threshold, facing the runway heading, at 0 kt. Needed by 2 of the 14 shipped scenarios (takeoff-roll exercises) and not expressible by any existing placement type; anticipated but never wired (`core.geodesy.GROUND_IAS_KT`'s own docstring names "a runway threshold for a takeoff brief"). A small, additive extension of an already-shipped union. | §4.1, §10.3 |
| D6 | **Loading, validation and the capability pre-flight check are `core/` (`core/scenarios/`). Execution — the sequence of *awaited* adapter calls — is `server/` (`server/scenario_engine.py`).** No `core/` code ever holds a `SimAdapter` instance; Weather and Failures already established this split (`core.weather.resolve_request` + `server/weather_routes.py`'s `await adapter.set_weather`; `core.failure_scheduler` + `server/failure_routes.py`'s watcher). The feature spec's "the engine in `core/` … executes a plan" is honoured for the loading/validating half, deliberately not for the half that touches the simulator. | §5, §6.2 |
| D7 | **Steps 2 (aircraft state) and 3 (position) execute as one call** into a reused `execute_placement()` (extracted from the shipped `POST /api/position/apply`) whenever a position block is present, because that function already owns the correct state-before-teleport order (#37, #39). Re-deriving that sequencing here risks reintroducing exactly those two measured bugs. | §5.2, §6.2 |
| D8 | **Armed failures reuse the Failures Manager's own scheduler singleton** through an exported `arm_failure()`. A failure a scenario arms shows up in the same `/api/failures/status` the instructor is already watching, fired by the same watcher task — never a second, competing scheduler. | §5.3, §6.2 |
| D9 | **`POST /api/scenarios/{id}/run` starts a background task and returns immediately; `GET /api/scenarios/run` is polled.** REST + poll, no new WebSocket — mirrors the Failures Manager's watcher-plus-status-poll shape and the stated reasoning that embedding scenario progress into `AircraftState` would be wrong. Only one scenario runs at a time; a second `POST … /run` while one is in progress is `409`. | §3, §6.2 |
| D10 | **The pre-flight check is capability-only, never a navdata check.** Roadmap exit criterion 4 ("never attempted halfway through") is about *declared capabilities*, verified synchronously before the background task starts. A scenario naming an airport absent from this install's navdata still fails — but as a **step failure** reported through the poll, a different and unavoidable risk, never pretended away. | §3.2, §10.4 |
| D11 | **No single gating capability for the whole manager**, unlike Weather/Failures. Different scenarios need different capability subsets (TCAS needs `can_spawn_traffic`, most do not), so the tab always renders and availability is computed **per scenario**. | §3.1, §7 |
| D12 | **`GET /api/scenarios` re-parses the shipped directory on every call.** Fourteen small files, no cache, no invalidation problem — unlike navdata's SQLite cache, which exists because CIFP parsing is expensive and this is not. | §6.1 |
| D13 | **No user-writable scenario directory in this phase.** Manager 14 (Training Profiles, same roadmap phase) is what gives an instructor a writable location; it reuses this exact loader against a second directory. Phase 2 wires only the shipped, read-only `core/scenarios/data/`. | §10.5 |
| D14 | **Twelve named exercises ship as fourteen files.** The feature spec's "Low visibility — CAT I / CAT II / CAT III" is one row of a twelve-row table but names three distinct, already-shipped Weather presets; splitting it into three files costs zero extra code and exercises all three CAT minima the Weather Manager built. Roadmap exit criterion 1 is read as "every shipped scenario runs," not "exactly the literal number 12" — see §2.1 for the full list and the reasoning. | §2.1, §10.2 |
| D15 | **The UI adds its endpoints with `injectEndpoints` (`scenariosApi.ts`)** — the rule the Position Manager broke and Weather/Failures kept. Adding this manager adds files; `instructorApi.ts` is not edited. | §7.1 |

---

## 2. Scope

### 2.1 What this manager does

1. **A directory of declarative YAML scenarios**, each validated against one pydantic model, each composed entirely of the Position/Weather/Failures/Fuel-&-Payload managers' own vocabulary.
2. **A manifest** — every shipped scenario, whether it can run on the active adapter, and why not when it cannot (roadmap exit criterion 4's mechanism).
3. **A run engine** — the fixed order **set weather → set aircraft state → position the aircraft → arm scheduled failures → spawn traffic if `can_spawn_traffic`** — executed against the live adapter, with a poll-able per-step progress view.
4. **The Scenarios tab** of the Instructor Panel — a browsable list with availability reasons and a running-scenario progress view.

The fourteen shipped files, covering the feature spec's twelve named exercises (D14):

| # | Filename (`core/scenarios/data/`) | Nature | Blocks used | Capability(-ies) needed |
|---|---|---|---|---|
| 1 | `engine-failure-after-v1.yaml` | Failure, timed on the roll | position, aircraft_state, weather, failures (armed) | `can_set_position`, `can_set_aircraft_state`, `can_set_weather`, `can_inject_failures` |
| 2 | `wind-shear.yaml` | Weather | position, weather | `can_set_position`, `can_set_aircraft_state`, `can_set_weather` |
| 3 | `low-visibility-cat-i.yaml` | Weather | position, weather (`cat_i` preset) | same |
| 4 | `low-visibility-cat-ii.yaml` | Weather | position, weather (`cat_ii`) | same |
| 5 | `low-visibility-cat-iii.yaml` | Weather | position, weather (`cat_iii`) | same |
| 6 | `crosswind-landing.yaml` | Weather + position | position, weather (`crosswind` preset) | same |
| 7 | `tailwind-landing.yaml` | Weather + position | position, weather (explicit, D14 note below) | same |
| 8 | `bird-strike.yaml` | Failure | position, weather, failures (immediate) | + `can_inject_failures` |
| 9 | `tcas-resolution-advisory.yaml` | Traffic | position, weather, traffic | + `can_spawn_traffic` — **unavailable on every current adapter (D11's live example)** |
| 10 | `hydraulic-failure.yaml` | Failure | position, weather, failures (armed) | + `can_inject_failures` |
| 11 | `electrical-failure.yaml` | Failure | position, weather, failures (armed) | + `can_inject_failures` |
| 12 | `go-around.yaml` | Position + state | position, aircraft_state | `can_set_position`, `can_set_aircraft_state` |
| 13 | `unstable-approach.yaml` | Position + state | position, aircraft_state (overrides the stabilised default) | same |
| 14 | `rejected-takeoff.yaml` | Position + state + failure | position, aircraft_state, weather, failures (armed) | + `can_inject_failures` |

`crosswind-landing` uses the relative `crosswind` weather preset (it already resolves against a runway, per `weather-manager.md`). `tailwind-landing` has no matching preset — the seven shipped presets do not include one — so its weather block states an absolute, hand-computed wind (D14 sibling note): a scenario is already airport- and runway-specific through its `position` block, so a runway-specific wind number is no less portable than the rest of the file.

### 2.2 One fully worked example

`core/scenarios/data/engine-failure-after-v1.yaml`:

```yaml
name: "Engine failure after V1"
description: >
  Takeoff roll on runway 36 at ZZZZ. Engine 1 fails just after V1 (135 kt),
  forcing a continued takeoff on one engine.
tags: [failure, takeoff, engine]

position:
  type: runway_threshold
  airport_icao: ZZZZ
  runway_ident: "36"

aircraft_state:
  flaps_ratio: 0.2

weather:
  preset: cavok

failures:
  armed:
    - failure_id: engine.failure
      engine_index: 1
      trigger:
        type: speed_above
        ias_kt: 135.0
```

`rejected-takeoff.yaml` is the same shape with `trigger.ias_kt: 80.0` — an engine failure well before V1, at a speed that unambiguously calls for an abort rather than a continue, distinguishing the two scenarios by trigger threshold alone, not by a different mechanism.

### 2.3 What is explicitly out of scope

| Out of scope | Owner / reason |
|---|---|
| Traffic spawn geometry (paths, conflict timing) | Manager 13, Phase 3. `ScenarioTrafficBlock` only *declares* the need (§4.2); step 5 has no executable body until `SimAdapter.spawn_traffic()` exists. |
| A user-writable scenario directory | Manager 14, same phase (D13). |
| Scenario versioning / pinning what a student experienced against a shipped file that later changes | Not attempted. Session Recorder (manager 12) is the eventual home for "what actually happened," not this manager. |
| A cancel/abort endpoint for a running scenario | Not built (§10.6). An instructor can already reposition or clear failures manually mid-run; the run's remaining steps then fail honestly against a state it did not expect. |
| Full navdata pre-validation of every shipped scenario at manifest time | D10 — capability-only pre-flight; a bad airport reference fails at run time, as a step failure. |
| Mass/CG composition beyond raw `AircraftSetup.gross_weight_kg` / `fuel_kg` | Provisional until Fuel & Payload's design exists (§10.1). |

---

## 3. REST endpoints

New router `server/scenario_routes.py`, registered from `server/app.py` exactly as the others (`app.include_router(scenario_routes.router)`). Commands are REST; there is no WebSocket change (D9).

```
GET  /api/scenarios              -> ScenarioManifest
GET  /api/scenarios/{id}         -> ScenarioDetail
POST /api/scenarios/{id}/run     -> ScenarioRunStatus
GET  /api/scenarios/run          -> ScenarioRunStatus | null
```

| Method | Path | Purpose | Safe? | Capability |
|---|---|---|---|---|
| `GET` | `/scenarios` | Every shipped scenario with `available` + `reason`, computed per scenario against the active adapter's `Capabilities`. Always 200. | yes | none |
| `GET` | `/scenarios/{id}` | One scenario's full document plus its availability — for a detail/preview view before running. | yes | none |
| `POST` | `/scenarios/{id}/run` | Pre-flight check, then start the background run; returns the initial (all-`pending`) status. | no | per-scenario, checked here |
| `GET` | `/scenarios/run` | The current or most recently finished run's status. `null` body when nothing has run this session. | yes | none |

### 3.1 Errors

| Situation | Status | Detail |
|---|---|---|
| Unknown scenario id (`GET /{id}`, `POST /{id}/run`) | 404 | `"Scenario 'foo' is not defined."` |
| A required capability is not declared (`POST /run`) | 501 | `"Unavailable on this adapter — the 'xplane' adapter does not declare can_spawn_traffic, so 'tcas-resolution-advisory' cannot run."` (multiple missing flags joined by `, `) |
| A scenario is already running (`POST /run`) | 409 | `"A scenario is already running ('rejected-takeoff'); wait for it to finish before starting another."` |
| A step fails after the run has started (navdata absent, adapter I/O, `CapabilityNotSupported` escaping anyway) | *(none on `/run` — it already returned)* | Surfaces as `ScenarioRunStatus.status == "failed"` and the failing step's `error`, discovered through the poll (D10). |

### 3.2 Pre-flight, precisely (roadmap exit criterion 4)

`POST /run` synchronously, **before** creating the background task:

1. Load the scenario (404 if the id does not resolve to a shipped file).
2. `missing = core.scenarios.preflight.missing_capabilities(document, adapter.capabilities)`.
3. `missing` non-empty → 501, naming every missing flag. **The adapter is never called.**
4. Otherwise create the task and return the initial status.

This is the whole mechanism behind "never attempted halfway through": nothing in step 4 onward can discover a missing capability, because everything the plan will call was checked in step 2.

---

## 4. Pydantic models

New module **`core/scenarios/models.py`**. Units follow every reused model's own convention; nothing here introduces a new unit.

### 4.1 `core/placements.py` (new — moved and extended)

Moved verbatim from `server/position_routes.py` (D4): `RunwayPlacementRequest`, `ParkingPlacementRequest`, `CoordinatePlacementRequest`, `WaypointPlacementRequest`, `ProcedureLegPlacementRequest`, `HoldPlacementRequest`. `server/position_routes.py` becomes `from core.placements import (...)` and re-exports the same names under the same `__all__` — no wire-format change, no behavioural change.

One new arm (D5):

```python
class RunwayThresholdPlacementRequest(BaseModel):
    """On the runway centreline at the threshold, facing the runway heading,
    at 0 kt — lined up for a takeoff brief. Distinct from RunwayPlacementRequest,
    which is exclusively airborne final/pattern geometry; this is the one ground
    position anchored to a runway rather than to a parking stand. Resolves
    through core.geodesy.coordinate_placement(runway.threshold,
    runway.true_bearing_deg, ias_kt=GROUND_IAS_KT) — the construction
    GROUND_IAS_KT's own docstring already names ("a runway threshold for a
    takeoff brief") but never wired to a request.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["runway_threshold"]
    airport_icao: str = Field(min_length=2, max_length=7)
    runway_ident: str = Field(min_length=1)


PlacementRequest = Annotated[
    RunwayPlacementRequest
    | RunwayThresholdPlacementRequest
    | ParkingPlacementRequest
    | CoordinatePlacementRequest
    | WaypointPlacementRequest
    | ProcedureLegPlacementRequest
    | HoldPlacementRequest,
    Field(discriminator="type"),
]
```

`server/position_routes.py`'s `_resolve_placement` gains one `isinstance(request, RunwayThresholdPlacementRequest)` branch, resolving through `_runway()` + `coordinate_placement()` exactly as sketched above, returning an empty `PlacementSchematic()` (the runway schematic could be reused later; not required for this manager). This is a small, mechanical addition to a shipped file, made once in this manager's foundation track (§9), and `docs/designs/position-manager.md` gains a one-paragraph addendum recording it, per that document's own as-built convention.

### 4.2 `core/scenarios/models.py`

```python
class ScenarioFailuresBlock(BaseModel):
    """Reuses core.failures' own request models verbatim — no re-derivation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    immediate: tuple[InjectFailureRequest, ...] = ()
    armed: tuple[ArmFailureRequest, ...] = ()

    @model_validator(mode="after")
    def _not_empty(self) -> "ScenarioFailuresBlock":
        if not self.immediate and not self.armed:
            raise ValueError(
                "A scenario's failures block must list at least one immediate or armed failure."
            )
        return self


class ScenarioTrafficBlock(BaseModel):
    """Declares that this scenario needs traffic. No spawn geometry here — that
    is manager 13's model (Phase 3); this lets a scenario state the need today
    and be greyed out honestly until the capability exists anywhere."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str = Field(min_length=1)


class ScenarioDocument(BaseModel):
    """The validated shape of one scenario YAML file. core/-only: no HTTP, no
    dataref, no adapter import, no SimAdapter instance held anywhere near it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    tags: tuple[str, ...] = ()

    position: PlacementRequest | None = None
    aircraft_state: AircraftSetup | None = None
    weather: WeatherRequest | None = None
    failures: ScenarioFailuresBlock | None = None
    traffic: ScenarioTrafficBlock | None = None

    @model_validator(mode="after")
    def _at_least_one_block(self) -> "ScenarioDocument":
        if not any((self.position, self.aircraft_state, self.weather, self.failures, self.traffic)):
            raise ValueError(
                "A scenario must declare at least one of: position, aircraft_state, "
                "weather, failures, traffic."
            )
        return self
```

### 4.3 The loader's own types (`core/scenarios/loader.py`)

```python
@dataclass(frozen=True)
class LoadedScenario:
    id: str  # the filename stem — the id, D2
    document: ScenarioDocument
    source_path: Path


class ScenarioLoadError(Exception):
    """One file failed to parse or validate. Carried, never raised past the
    loader — one bad file must not take down the other thirteen."""

    def __init__(self, path: Path, error: Exception) -> None:
        self.path = path
        self.error = error
        super().__init__(f"{path}: {error}")
```

### 4.4 Server envelopes (`server/scenario_routes.py` — HTTP furniture)

```python
class ScenarioSummary(BaseModel):
    id: str
    name: str
    description: str
    tags: tuple[str, ...]
    available: bool
    reason: str | None  # populated iff available is False


class ScenarioDetail(ScenarioSummary):
    document: ScenarioDocument


class ScenarioManifest(BaseModel):
    adapter: str
    scenarios: tuple[ScenarioSummary, ...]  # sorted by id
    load_errors: tuple[str, ...] = ()  # "<path>: <message>" for a broken shipped file


ScenarioStepName = Literal["weather", "aircraft_state", "position", "failures", "traffic"]
ScenarioStepStatusValue = Literal["pending", "running", "done", "failed"]


class ScenarioStepStatus(BaseModel):
    name: ScenarioStepName
    status: ScenarioStepStatusValue
    detail: str | None = None  # short outcome sentence
    error: str | None = None  # set iff status == "failed"


class ScenarioRunStatus(BaseModel):
    scenario_id: str
    status: Literal["running", "completed", "failed"]
    steps: tuple[ScenarioStepStatus, ...]  # only the blocks this scenario declares
    started_at: datetime
    finished_at: datetime | None = None
```

---

## 5. `SimAdapter` / `Capabilities` additions

**None.** Every adapter call this manager makes — `apply_setup`, `set_position`, `set_weather`, `get_weather`, `inject_failure`, `get_aircraft_state` — already exists on `SimAdapter`, and every capability flag it checks — `can_set_position`, `can_set_aircraft_state`, `can_set_weather`, `can_inject_failures`, `can_spawn_traffic`, `can_control_autopilot`, `can_set_fuel_payload` — already exists on `Capabilities`. This manager is a **pure composition layer**: it reads the interface, it never extends it. `tests/adapters/test_contract.py` is untouched.

The only code changes this design requires outside `core/scenarios/` and `server/scenario_*.py` are the two small, ordinary refactors below — neither is a contract change and neither is subject to the "never parallelised" rule, but both touch already-shipped files and are made once, first, in this manager's own foundation track (§9).

### 5.1 `server/position_routes.py` — extract `execute_placement`

```python
async def execute_placement(
    request: ApplyPlacementRequest,
    *,
    adapter: SimAdapter,
    navdata: NavdataProvider,
) -> PlacementResult:
    """The body of POST /api/position/apply, factored out so the Scenario
    Generator's engine reuses the exact state-before-teleport sequencing
    (#37, #39) instead of re-deriving it (D7)."""
    # unchanged body of today's apply_placement route handler


@router.post("/apply", response_model=PlacementResult)
async def apply_placement(request: ApplyPlacementRequest) -> PlacementResult:
    return await execute_placement(request, adapter=get_adapter(), navdata=get_navdata())
```

Added to `server/position_routes.py.__all__`.

### 5.2 `server/failure_routes.py` — extract `arm_failure`

```python
async def arm_failure(request: ArmFailureRequest, *, adapter: SimAdapter) -> ArmedFailure:
    """The body of POST /api/failures/arm, factored out so the Scenario
    Generator arms into the SAME scheduler/watcher instance (D8) rather than
    running a second one. Starts the watcher task lazily, exactly as the
    route already does."""
```

If the Failures Manager ships without this factoring already in place, this manager's foundation track adds it as a same-shape, behaviour-preserving extraction — not a design change to that manager.

---

## 6. `core/` logic

### 6.1 `core/scenarios/loader.py` — the directory scan (the exit-criterion mechanism)

```python
SCENARIOS_DIR: Path = Path(__file__).parent / "data"
SCENARIO_ID_PATTERN: re.Pattern[str] = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def discover_scenario_files(directory: Path = SCENARIOS_DIR) -> tuple[Path, ...]:
    """Every *.yaml / *.yml directly under ``directory``, sorted by stem for a
    deterministic manifest order. Pure pathlib globbing (ruff PTH-compliant).
    A stem present as both .yaml and .yml is a load error for the second one
    found — two files cannot honestly share one id."""


def load_scenario_file(path: Path) -> LoadedScenario:
    """Parse and validate one file. Raises ScenarioLoadError — never a raw
    yaml.YAMLError or pydantic ValidationError — so every caller has one
    error type. The id is the stem; a stem that does not match
    SCENARIO_ID_PATTERN is itself a ScenarioLoadError."""


def load_all_scenarios(
    directory: Path = SCENARIOS_DIR,
) -> tuple[tuple[LoadedScenario, ...], tuple[ScenarioLoadError, ...]]:
    """Scan and load every file in one pass. Never raises on a single bad
    file — thirteen good scenarios are not held hostage by a fourteenth
    typo. This is THE mechanism the exit-criterion test exercises: point it
    at any directory, including one nothing else in the codebase names, and
    every well-formed file in it is discovered and validated."""
```

`directory` is a parameter, not baked into the function body, precisely so a test can point it at a fixture directory the production code never mentions (§8.1).

### 6.2 `core/scenarios/preflight.py`

```python
_AUTOPILOT_SETUP_FIELDS = frozenset(
    {
        "autopilot_master",
        "flight_director",
        "autopilot_nav",
        "autopilot_app",
        "autopilot_hdg",
        "target_altitude_ft",
        "target_ias_kt",
        "target_heading_deg",
        "target_vertical_speed_fpm",
    }
)
_FUEL_PAYLOAD_SETUP_FIELDS = frozenset({"gross_weight_kg", "fuel_kg"})


def setup_capability_requirements(setup: AircraftSetup) -> frozenset[str]:
    """Which Capabilities flags a non-empty AircraftSetup needs, mirroring
    apply_setup's own per-field gating (SimAdapter.apply_setup docstring):
    can_set_aircraft_state always, plus can_control_autopilot and/or
    can_set_fuel_payload when the corresponding fields are populated."""


def missing_capabilities(
    document: ScenarioDocument,
    capabilities: Capabilities,
) -> tuple[str, ...]:
    """Which capability flags this scenario needs but the adapter has not
    declared, in a stable order (weather, aircraft_state, position, failures,
    traffic). Pure: (document, Capabilities) in, flags out. No adapter
    instance, no I/O — the same posture as core.weather.presets.resolve_preset
    and core.failure_scheduler: core never holds a SimAdapter (D6)."""
```

Logic: `weather` present → `can_set_weather`; `aircraft_state` present → `setup_capability_requirements(aircraft_state)`; `position` present → `can_set_position` plus `setup_capability_requirements(position.to_setup-equivalent)` — evaluated conservatively as `{"can_set_aircraft_state"}` since every placement's `to_setup()` is non-empty (mirrors `server/position_routes.py`'s own `if setup.model_dump(exclude_none=True): _require_capability(...)`); `failures` non-empty → `can_inject_failures`; `traffic` present → `can_spawn_traffic`. Duplicates removed, order preserved.

### 6.3 The engine — `server/scenario_engine.py`

Deliberately **not** `core/` (D6). Module-owned singleton state, the same shape as the Failures Manager's watcher:

```python
_current_run: _RunState | None = None  # internal mutable dataclass
_current_task: asyncio.Task[None] | None = None


async def start_run(
    loaded: LoadedScenario, *, adapter: SimAdapter, navdata: NavdataProvider
) -> ScenarioRunStatus:
    """409 if a run is already in progress; 501 if missing_capabilities()
    is non-empty (§3.2). Otherwise creates the background task and returns
    the initial all-pending snapshot."""


def get_run_status() -> ScenarioRunStatus | None: ...


def reset_scenarios() -> None:
    """Cancels any running task and drops the singleton — the reset_failures()
    pattern, for tests."""
```

`_execute(document, *, adapter, navdata)` runs the fixed order, updating the step map before and after each block, stopping (remaining steps stay `pending`) on the first failure:

1. **weather** — if `document.weather`: look up `airport_icao`/`runway_ident` in navdata when named (`run_in_threadpool`, the established reason: blocking SQLite work must not stall `/ws/state`), `setup, notes = core.weather.presets.resolve_request(document.weather, runway_true_bearing_deg=…, field_elevation_ft=…)`, `await adapter.set_weather(setup)`. `detail = "; ".join(notes)`.
2. **aircraft_state** + **position** (D7, one call when position is present) — `document.position is not None` → `execute_placement(ApplyPlacementRequest(placement=document.position, setup=document.aircraft_state), adapter=adapter, navdata=navdata)`; else if only `document.aircraft_state` → `await adapter.apply_setup(document.aircraft_state)` directly. Both steps' statuses flip together when the fused call is used.
3. **failures** — if `document.failures`: inject every `immediate` entry (`await adapter.inject_failure(ref)`), then arm every `armed` entry through the exported `arm_failure()` (D8). `detail = f"{n_injected} injected, {n_armed} armed"`.
4. **traffic** — if `document.traffic`: **no executable body in Phase 2.** `SimAdapter.spawn_traffic()` does not exist yet (#13, Phase 3). Because the pre-flight check already guarantees `can_spawn_traffic` was `True` before this code could ever run, and no adapter declares it `True` today, this branch is provably unreachable in Phase 2 — a scenario with a traffic block is refused at `POST /run`, never reaches step 4. The branch is a single guarded no-op so #13 adds one call here, not a restructure.

A step raising `CapabilityNotSupported`, `HTTPException` (from `execute_placement`) or `ValueError` (from `resolve_request`, e.g. an unresolvable airport) marks that step `"failed"` with the message, sets the run `"failed"`, and stops. Full success sets `"completed"`.

---

## 7. UI panel outline

`ui/src/features/scenarios/` — a new tab. Adding it adds files; `instructorApi.ts` is not edited (D15).

### 7.1 Server state — RTK Query (`scenariosApi.ts`)

| Endpoint | Kind | Notes |
|---|---|---|
| `getScenarios` | query, tag `ScenarioManifest` | the list, `available` + `reason` per row |
| `getScenario` | query | one scenario's `ScenarioDetail` for a detail view |
| `runScenario` | mutation | `POST /run`; on success starts polling `getScenarioRun` |
| `getScenarioRun` | query, `pollingInterval: 1000` while `status === "running"`, stopped otherwise | the progress view's data source |

All types generated from `schema.d.ts` (hard rule 7). No hand-written API types.

### 7.2 Client state — one slice (`scenariosSlice.ts`)

```ts
interface ScenariosState {
  selectedScenarioId: string | null; // which detail/run view is open
}
```

Deliberately thin: unlike Weather/Failures there is no staging/editing surface here — a scenario is browsed and run, not composed in the UI.

### 7.3 Components

| File | Role |
|---|---|
| `ScenariosPanel.tsx` | The tab: list on the left/top, detail + run view on selection. |
| `ScenarioList.tsx` | Rows from the manifest — name, description, tags, a disabled state with `reason` inline when `available` is `false` (the TCAS row, greyed out with "the 'xplane' adapter does not declare can_spawn_traffic"). |
| `ScenarioDetail.tsx` | The selected scenario's blocks in plain language (position/weather/failures summarised from the document) and a **Run** button. |
| `ScenarioRunView.tsx` | The step-by-step progress: one row per declared step with a status icon (pending/running/done/failed) and its `detail`/`error`. |
| `gate.ts` | **No fail-closed capability gate at the tab level** (D11) — the list itself is the gate, per row. |

### 7.4 Divergence from the existing mock scaffolding

The task brief describes an existing mock at `ui/src/features/scenarios/` (`mock.ts`, `types.mock.ts`, `useScenarioRun.ts` ticking one step per 1200 ms) that this design could not directly inspect — it is not present in this working tree/branch. Based on the brief's description, the expected divergences when re-typing the mock against this design are:

- **`unavailableReason` → `reason`**, matching the `ScenarioSummary`/`WeatherManifest`/`FailureSupport` naming convention already established.
- **`steps: string[]` → `ScenarioStepStatus[]`.** The mock's flat label array, ticked client-side on a timer, is replaced by the server-reported per-step `status`/`detail`/`error` from `GET /api/scenarios/run`; `useScenarioRun.ts`'s local 1200 ms interval is replaced by RTK Query's `pollingInterval`.
- The mock's client-side execution engine is deleted outright — there is nothing left for it to simulate once the real endpoints exist.

Tablet-first: list rows and the Run button are ≥ 44 px; the run view's step rows use `tabular-nums` for any numeric detail; the whole panel fits one portrait screen without the schematic/staging-bar machinery Position/Weather need, since there is nothing to edit here.

---

## 8. Test plan

Everything below runs in CI against `FakeSimAdapter`; no navdata file, no simulator (hard rule 4). `FakeSimAdapter` declares `can_spawn_traffic = False` like every current adapter (per the shared `Capabilities` defaults), which is exactly what makes the TCAS scenario the live, CI-visible "greyed out with a reason" example.

### 8.1 `core/scenarios/` unit tests

`tests/core/scenarios/test_models.py`:

- A minimal one-block document validates for each of the five block types.
- A document with no blocks at all raises (`ValidationError`).
- An unknown top-level key raises (`extra="forbid"`).
- A `weather` block with neither `preset` nor `setup` raises — **delegated to `WeatherRequest`'s own validator**, proving reuse rather than reimplementation.
- A `failures` block with both lists empty raises.
- An `armed` entry with a mismatched `engine_index` raises — delegated to `ArmFailureRequest`/`FailureRef`'s own validator.
- `RunwayThresholdPlacementRequest` round-trips through `PlacementRequest`'s discriminator.

`tests/core/scenarios/test_loader.py`:

- `discover_scenario_files` returns files sorted by stem.
- A syntactically broken YAML file raises `ScenarioLoadError` wrapping `yaml.YAMLError`.
- A syntactically valid file that fails `ScenarioDocument` validation raises `ScenarioLoadError` wrapping the `ValidationError`.
- `load_all_scenarios(SCENARIOS_DIR)` (the real shipped directory) returns **zero errors** and the pinned set of 14 ids exactly (the catalogue-integrity test, mirroring `weather-manager.md`'s preset-integrity test — a shipped file added or renamed without updating this list fails loudly).
- A stem colliding across `.yaml`/`.yml` is a `ScenarioLoadError`.

**The exit-criterion test** (roadmap Phase 2, criterion 2), in the same module:

```python
FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "scenarios"
UNREFERENCED_ID = "unreferenced-fixture"


def test_discovers_a_scenario_never_named_in_the_source_tree() -> None:
    """Loads a scenario file that no Python source module names anywhere
    except this docstring and the mechanical check below — proving discovery
    is a directory scan, not a registry a new scenario must be added to."""
    loaded, errors = load_all_scenarios(FIXTURE_DIR)
    assert errors == ()
    assert [s.id for s in loaded] == [UNREFERENCED_ID]

    # Mechanical, not just a claim: no OTHER source file mentions this id. If
    # discovery ever regressed to a hardcoded list, the assertion above would
    # still pass by finding the file some other way — this is what catches it.
    offenders = [
        path
        for directory in ("core", "server", "adapters", "tests")
        for path in (REPO_ROOT / directory).rglob("*.py")
        if path != Path(__file__) and UNREFERENCED_ID in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
```

`tests/fixtures/scenarios/unreferenced-fixture.yaml` — one minimal valid document (a `position: coordinate` block is enough), living in a directory that contains **only** this file, so `SCENARIOS_DIR`'s default is never touched by the test.

`tests/core/scenarios/test_preflight.py`:

- `weather`-only document against `Capabilities()` (all `False`) → `("can_set_weather",)`.
- `position`-bearing document against all-`False` → `("can_set_position", "can_set_aircraft_state")`, in that order.
- `aircraft_state={"autopilot_master": True}` against `Capabilities(can_set_aircraft_state=True)` → `("can_control_autopilot",)`.
- The `tcas-resolution-advisory` document against `Capabilities()` → includes `"can_spawn_traffic"`.
- Every-flag-`True` `Capabilities` → `()` for every one of the 14 shipped documents (loaded via `load_all_scenarios()`), i.e. every shipped scenario is at least *checkable* without raising.

### 8.2 Contract tests

**None.** No new `SimAdapter`/`Capabilities` surface (§5).

### 8.3 Server tests — `tests/server/test_scenario_routes.py`

Against `TestClient` + `FakeSimAdapter`, `reset_scenarios()` between tests:

- `GET /scenarios` lists all 14 with `available=True` **except `tcas-resolution-advisory`**, whose `reason` names `can_spawn_traffic` — the live capability-gating demonstration, in CI.
- `POST /scenarios/tcas-resolution-advisory/run` → 501, same sentence.
- `POST /scenarios/{unknown}/run` and `GET /scenarios/{unknown}` → 404.
- `POST /scenarios/engine-failure-after-v1/run` → 200, `status="running"`, every declared step `"pending"`.
- Poll `GET /scenarios/run` with a bounded retry loop (the failures watcher-integration pattern) until `status != "running"`; assert `"completed"`; assert `adapter.get_weather()`, `adapter.get_aircraft_state()` and the armed-failure list all reflect the YAML's content — the read-back is the assertion, not the absence of an exception.
- Starting a second run while one is in progress → 409.
- A scenario whose position block names an airport absent from the (empty, in these tests) navdata index → the run completes with `status="failed"`, the `position` step's `error` set, remaining steps `"pending"` — D10 made concrete.
- `GET /scenarios/run` before anything has run → 200, body `null`.

### 8.4 `@pytest.mark.sim` — never in CI

One parametrised test iterating every `available=True` scenario from the live manifest (13 of the 14 — TCAS stays excluded until the bridge lands, live or not): `POST /run`, poll to completion, assert `"completed"`. Wrapped per-scenario in a `finally` that calls `POST /api/failures/clear-all` and restores the session's original position (the existing `tests/conftest.py` restore fixture) — a scenario that teleports leaves the aircraft somewhere the next one must not inherit. **Marked heavy on purpose**: 13 sequential placements, some of them long teleports with a scenery-reload wait, is minutes, not seconds — this is the `sim-validator` agent's job, never a merge gate.

### 8.5 Fixtures

`tests/fixtures/scenarios/unreferenced-fixture.yaml` only. No navdata fixture is needed beyond what `tests/server/conftest.py`'s existing in-Python `ZZZZ` world already provides for the position/weather steps.

### 8.6 UI tests (vitest)

`ScenarioList.test.tsx` — a row with `available=false` renders disabled with `reason`, is not clickable to run. `ScenarioRunView.test.tsx` — renders `ScenarioStepStatus[]` states correctly (pending/running/done/failed with `error`). `scenariosApi` polling — `getScenarioRun` stops polling once `status !== "running"` (a stubbed-fetch sequence test).

---

## 9. Parallelisation

**This manager is a hard barrier.** It starts only after Weather, Failures and Fuel & Payload are all merged to `dev` — it composes their real, shipped models, not a design document.

Inside the manager, once §3/§4 (endpoints + models) are fixed by this document:

| Track | What | Owns (disjoint) | May start |
|---|---|---|---|
| **0 — foundation, SERIALISED** | `core/placements.py` move + `RunwayThresholdPlacementRequest` + `execute_placement` extraction (§4.1, §5.1); `arm_failure` extraction if not already present (§5.2); `core/scenarios/models.py`; `core/scenarios/preflight.py` | `core/placements.py`, `core/scenarios/models.py`, `core/scenarios/preflight.py`, `server/position_routes.py` (extraction only), `server/failure_routes.py` (extraction only) | first, alone — touches already-shipped, actively-referenced files |
| **A — engine + server** | `core/scenarios/loader.py`, `server/scenario_engine.py`, `server/scenario_routes.py` + `include_router`, `tests/core/scenarios/`, `tests/server/test_scenario_routes.py` | `core/scenarios/loader.py`, `server/scenario_engine.py`, `server/scenario_routes.py`, `tests/core/scenarios/`, `tests/server/` | after Track 0 |
| **B — content** | The 14 YAML files (§2.1), `tests/fixtures/scenarios/unreferenced-fixture.yaml` | `core/scenarios/data/`, `tests/fixtures/scenarios/` | after Track 0 (needs the fixed field names, nothing from Track A) |
| **C — UI panel** | `ui/src/features/scenarios/*`, the `App.tsx` mount, `schema.d.ts` regeneration | `ui/` | after Track A's routes exist on the branch — the client is generated from the running server's OpenAPI schema |

Tracks A and B are dispatched **in one message** once Track 0 lands; Track C follows A. The tester writes §8.1/§8.3 against this document, before any implementation exists — the models and signatures above are the complete contract.

**Never parallelised:** Track 0; the phase-wide barrier itself (this manager waiting for the other three); merges to `dev`/`main`; release tagging. No `SimAdapter`/`Capabilities` change and no navdata schema change is made by this manager at all.

---

## 10. Open questions and risks

### 10.1 Fuel & Payload's design was not available

`docs/designs/fuel-payload.md` did not exist at design time. This design's `aircraft_state` block reuses raw `AircraftSetup.gross_weight_kg`/`fuel_kg` today, which is reachable but not ergonomic (an instructor authoring a scenario has to know a kilogram figure, not "Training load"). **What resolves it:** once that design lands, a small follow-up adds a `loadout: LoadoutPresetId | Loadout | None` field to `ScenarioDocument`, mirroring `WeatherRequest`'s preset-or-explicit shape, and `missing_capabilities()` gains a `can_set_fuel_payload` check for it. Also open: whether `Placement.to_setup()` itself grows a mass component from that manager, which would mean `can_set_fuel_payload` gates every position-block-bearing scenario, not just ones with an explicit `loadout`.

### 10.2 The "twelve vs fourteen" reading (D14)

Roadmap exit criterion 1 says "all 12 scenarios run end to end." This design ships 14 files for 12 named exercises and reads the criterion as "every shipped scenario," not the literal count. **What would resolve any disagreement:** a one-line confirmation from the user; nothing in the design depends on the exact number, and shipping fewer (collapsing the three CAT files into one) is a pure content edit with zero code impact either way.

### 10.3 The runway-threshold placement gap

D5 is a real, previously-unaddressed gap in the shipped Position Manager, not a scenario-specific workaround. Flagging it here rather than silently reusing `CoordinatePlacementRequest` with a manually-computed threshold coordinate (which a scenario author cannot do — a YAML file has no navdata access) is deliberate. **Resolution:** the small addition in §4.1/§5.1, plus the position-manager.md addendum it implies.

### 10.4 Distance-from-start / distance-along-track failure trigger — checked, not needed

Per the task brief's instruction to verify this explicitly: all 14 shipped scenarios were checked against the five trigger types Failures ships (`altitude_above/below`, `speed_above/below`, `delay`). None needs a distance-based trigger — "engine failure after V1" and "rejected take-off" are both expressed as `speed_above` at different thresholds (135 kt continue, 80 kt reject), which is sufficient and in fact clearer than a distance-along-the-runway would be. **No sixth trigger type is required for Phase 2.**

### 10.5 No user-writable scenario directory yet (D13)

An instructor cannot add their own scenario without a repo checkout in this phase — only the shipped, read-only directory is wired into the server. This is a deliberate boundary with Manager 14, not an oversight, but it means the feature-spec's "one click puts the student in a specific, repeatable training situation" is, for now, only ever a *shipped* situation. **Resolution:** Manager 14 passes a second, configurable directory (e.g. `OIS_SCENARIOS_DIR`, an app-data path) into the same `load_all_scenarios()`.

### 10.6 No cancel/abort for a running scenario

Noted and accepted for Phase 2 (§2.3). If instructors report needing to abort a long teleport mid-scenario, the fix is small — a `POST /api/scenarios/run/cancel` cancelling `_current_task` — but is not built speculatively.

### 10.7 Mid-run failures leave partially-applied state

A scenario that fails at the `failures` step after `weather` and `position` already succeeded leaves the aircraft in that partial state — deliberately (D10): re-running is the recovery, exactly how `/api/position/apply` already behaves on a partial failure. Worth restating because it is easy to misread "never attempted halfway through" (roadmap criterion 4, about *capabilities*) as a guarantee about *I/O failures*, which it is not and cannot honestly be.

### 10.8 `get_active_failures()` / mass concurrent scenarios and the failures watcher's cost

Inherited from `failures-manager.md` §10.9 (the ~30–40 sequential dataref reads polled at 2 s): a scenario that arms several failures at once adds no new load pattern beyond what that design already measures under `-m sim`. No new risk here, restated only so it is not missed when both managers run together for the first time.

---

## 11. Verification

```bash
pytest                       # unit + server, Fake only — must be green before any merge
pytest -m sim                # §8.4: 13 of 14 shipped scenarios against a live X-Plane
ruff check . && ruff format --check .
mypy .
cd ui && npm run lint && npm run typecheck && npm test && npm run build
```

Panel smoke (fake adapter + Vite dev server, one batched browser session): Scenarios tab loads → 14 rows, `tcas-resolution-advisory` greyed out with its reason → open `engine-failure-after-v1` → Run → progress view ticks weather → aircraft_state/position → failures → `completed` → console clean.

---

## Design-time caveat: filesystem state at write time

`docs/designs/fuel-payload.md` did not exist in this working tree at design time (§10.1), and
`ui/src/features/scenarios/` (the mock scaffolding referenced in the task brief) was likewise not
present in this checkout at read time (§7.4) — a consequence of the shared checkout being on a
git branch that did not yet carry the (separately landed) UI panel work, not a real absence. Both
are called out explicitly in the relevant sections rather than silently assumed; confirm §7's
divergence notes against the actual mock files (now on `dev`) before implementing Track C.
