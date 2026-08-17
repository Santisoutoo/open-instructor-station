# Training Profiles — design

**Status:** designed, not yet implemented.
**Phase:** 2 — Weather + Failures → Scenario Generator ([`../roadmap.md`](../roadmap.md#phase-2--weather--failures--scenario-generator)). Exit criteria this manager touches: none directly (they are all Scenario Generator criteria), but it must not regress criterion 4 ("scenarios requiring an undeclared capability are reported as unavailable, never attempted") — applying a profile is subject to the same rule.
**Feature spec:** manager 14 ([`../feature-spec.md`](../feature-spec.md#14-training-profiles)), priority —.
**GitHub issue:** #18.
**Depends on:** the Phase 1 contract (`core.sim_adapter`, `FakeSimAdapter`), the Position Manager (`server/position_routes.py`, shipped), and — read in full for this design — `weather-manager.md` and `failures-manager.md` (designed, not yet implemented; this document imports their `core/` models directly). **Blocked by** the Flight Scenario Generator (#17), which had not landed a design document when this one was written — see §10.1 for exactly what that blocks and what does not.
**Blocks:** nothing downstream in Phase 2. Manager 12 (Session Recorder, Phase 4) is expected to grow a "save this snapshot as a profile" action that writes through this manager's storage layer without changing it.

A training profile is a saved scenario with a name and metadata — same model, same validation,
same execution path (feature spec §14). This document's job is almost entirely: where profiles
live on disk, how they round-trip through JSON, how "apply" degrades gracefully when navdata or
a capability has moved on since the profile was authored, and how thin the UI can stay. It is
deliberately **not** a second scenario engine.

Binding rules live in [`../../CLAUDE.md`](../../CLAUDE.md); layers in
[`../architecture.md`](../architecture.md). This document never relaxes any of them. Where the
Position Manager's as-built record ([`position-manager.md`](position-manager.md)) recorded a
regret — request models stranded in `server/`, closing the door on reuse — this design inherits
the consequence rather than repeating the mistake blind: it says exactly where that regret now
costs this manager a small, flagged duplication (§0 D4, §10.1).

---

## 0. Decisions at a glance

| # | Decision | Where |
|---|---|---|
| D1 | **JSON only in Phase 2.** The feature spec mentions XML; it is not built. A profile is one `.json` file. XML export/import is a possible future addition, not designed here. | §1.2 |
| D2 | **The app-data directory is computed by hand, not via `platformdirs`.** `pyproject.toml` pins its dependency set deliberately (see its own comments on `ruff`/`mypy`/`pytest`); this manager needs exactly one directory on three platforms, which is ~15 lines with no new dependency, against a library whose author/appname/roaming-vs-local surface this project would use none of. | §6.1 |
| D3 | **No new `Capabilities` flag and no `SimAdapter` change.** Applying a profile composes the Position, Weather and Failures managers' own already-gated apply paths in-process; each component is refused (or degrades) exactly as it already does standalone. This section is explicitly empty of contract work — say so, don't invent it. | §4 |
| D4 | **A profile embeds a full scenario document, not a reference-with-overrides** — feature spec's "same model" taken literally. The embedded document composes `core.weather.models.WeatherRequest` and `core.failures.FailureRef`/`FailureTrigger` **directly** (both already `core/`-owned, per `weather-manager.md` D6 and `failures-manager.md` D9 — no duplication needed there). The one exception is position: `server/position_routes.py`'s `PlacementRequest` is **server-owned** (the Position Manager's own recorded deviation, its §7.6/§13), and `core/` cannot import `server/`. This design therefore declares a **provisional, core-owned `ProfilePlacement`** — field-for-field identical to `PlacementRequest`'s six arms — pinned by a shape-parity test (§8.1) so a future drift is caught immediately rather than surfacing as a mysterious 422. This is the single largest reconciliation dependency on the Scenario Generator; see §10.1. | §3.3, §10.1 |
| D5 | **Storage is a flat directory of JSON files, one per profile, no SQLite index.** Profiles are user-authored, few (tens, not thousands) and small (a few KB). A directory scan on `list()` costs nothing; inventing an index would be building infrastructure for a problem that does not exist yet. No navdata schema is touched by this manager at all. | §6.2 |
| D6 | **Import and export are HTTP file transfer, not server-local file paths.** The station is a LAN tool a tablet reaches over the network (hard rule 1); "hand a colleague a file" means a browser download and a browser upload, never a path on the machine running the server. | §2, §6.2 |
| D7 | **Import always assigns a fresh `profile_id`.** The uploaded document's own id (if any survived a previous export) is never trusted or reused — collision-proof, and re-importing the same file twice produces two profiles, exactly like copying a file twice in a folder. | §2.1, §6.2 |
| D8 | **`POST /api/profiles/{id}/apply` is (almost) always 200.** Partial application is reported *in the body* — `degraded: bool` plus a per-component outcome and reason — never as a 4xx/5xx. This is the feature spec's AIRAC-degradation requirement made literal: "report what could not be resolved, apply the rest" is a 200 with a report, not an error. Only "the profile itself does not exist" is a 404. | §2.2, §6.3 |
| D9 | **Two `extra` policies in the same document, on purpose.** The outer `TrainingProfile` wrapper (app-authored, never hand-typed) tolerates unknown fields (`extra="ignore"`) for forward compatibility across app versions sharing profiles. The embedded `ProfileScenario` and everything under it (plausibly hand-edited before a colleague gets it) forbids them (`extra="forbid"`), the same typo-catching convention `weather-manager.md`/`failures-manager.md` established. The tension this creates for cross-version sharing is flagged, not hidden, in §10.2. | §3.1, §3.2 |
| D10 | **`core/profiles/` holds models and storage only — no orchestration.** The task brief for this design asked for "the degradation resolver" in `core/`; it is not there. Resolving what degrades means calling the adapter through the Position/Weather/Failures managers' own apply paths, and `core/` never talks to a simulator (hard rule 2). The orchestration — including the partial-apply aggregation — lives in `server/profile_routes.py`. This is a deliberate narrowing of the brief, stated rather than silently done differently. | §6.3 |
| D11 | **The Save-current-setup UI reads, never writes, `positionSlice`'s and `weatherSlice`'s already-public staged state**, via selectors imported from Profiles' own new files. No existing slice file is edited. This is the one place this manager's UI reaches across a feature boundary, and it does so read-only and is expected to be superseded once the Scenario Generator's own staging area exists (§10.4). | §7.2 |
| D12 | **No rename, no duplicate, no versioning UI.** The panel creates, lists, applies, imports, exports and deletes. Delete's confirmation is the browser's native `confirm()` — the one destructive action here does not justify a bespoke dialog component. | §7.3 |
| D13 | **`PUT /api/profiles/{id}` exists at the API for symmetry but the Phase 2 UI never calls it.** Renaming/editing a saved profile is not asked for by the feature spec; the endpoint is cheap REST completeness for scripting and for a later UI, not scope creep now. | §2, §7.1 |
| D14 | **`pyproject.toml`'s `[tool.setuptools] packages` gains `"core.profiles"`.** A one-line, shared-file, low-collision-risk edit — flagged so it is sequenced rather than merged twice by mistake if Weather's `"core.weather"` addition lands the same week. | §9 |

---

## 1. Scope

### 1.1 What this manager does

1. **Save a complete training setup** — airport, runway, distance/leg, altitude, speed, aircraft
   configuration, weather, failures — as one named, described JSON document.
2. **List, load and delete** saved profiles.
3. **Apply** a profile: run its embedded scenario through the same paths the Position, Weather
   and Failures managers already expose, in one instructor action.
4. **Import** a file an instructor received, and **export** a file to hand to a colleague.
5. **Degrade gracefully** when the profile's placement references an airport, runway or procedure
   that no longer resolves on this install's navdata (a different AIRAC cycle, a different
   install): report what did not resolve, apply everything else.
6. **Offer it as a panel** — a browsable list, a save form, apply/import/export/delete actions.

Covers feature spec manager 14 in full for Phase 2 except the XML half (D1).

### 1.2 What is explicitly out of scope

| Out of scope | Owner / reason |
|---|---|
| XML storage format | Deferred (D1). JSON's shape does not need to change for XML to arrive later — it would be a second (de)serialiser over the same `TrainingProfile` model. |
| Building a scenario from scratch with full navdata pickers inside this panel | The Position Manager's own panel already does this well; the Save form composes what is already staged there rather than reimplementing airport/runway/procedure search (§7.2). |
| Capturing "everything the aircraft is doing right now" as a profile | That is the Session Recorder's **snapshot** mechanism (feature spec §12, Phase 4), which is explicitly a superset of what this manager writes. Feature spec's own words: *"saving one as a Training Profile is manager 14."* This manager consumes that capability later; it does not build it now. |
| Traffic in a profile | The feature spec's list for manager 14 (airport, runway, distance, altitude, speed, aircraft configuration, weather, failures) does not mention traffic, unlike the Scenario Generator's list (which explicitly includes it). `ProfileScenario` carries no traffic field in Phase 2 — see §10.3 for the additive path when Phase 3's `can_spawn_traffic` exists. |
| Rename, duplicate, version history | Not asked for (D12). |
| Profile sync across machines/cloud | Out of scope, almost certainly permanently — see §10.6. |
| A second scenario execution engine | The whole point of this manager (feature spec §14's own framing). Applying a profile calls the Position/Weather/Failures managers' existing apply functions in-process; nothing here re-implements geodesy, weather resolution or the failure catalogue. |

---

## 2. REST endpoints

All under `/api/profiles/*`, in a new `server/profile_routes.py`, registered from `server/app.py`
with one `include_router` line — the only shared-file edit on the backend besides `server/deps.py`
(§6.1) and `pyproject.toml` (D14).

```
GET    /api/profiles                    -> list[ProfileSummary]
POST   /api/profiles                    -> TrainingProfile
GET    /api/profiles/{profile_id}       -> TrainingProfile
PUT    /api/profiles/{profile_id}       -> TrainingProfile
DELETE /api/profiles/{profile_id}       -> 204 No Content
POST   /api/profiles/{profile_id}/apply -> ProfileApplyResult
POST   /api/profiles/import             -> TrainingProfile
GET    /api/profiles/{profile_id}/export -> application/json file download
```

**Deviation from the brief's shorthand, stated plainly (D13):** the task that produced this
design sketched `GET/POST/DELETE /api/profiles/{id}`. `POST` against a specific id reads as
"create with a client-chosen id," which this design does not offer — ids are server-assigned
(§3.1). The clean REST shape is `POST /api/profiles` to create (collection-level, server assigns
the id) and `GET`/`PUT`/`DELETE /api/profiles/{id}` against the created resource. `PUT` is the
idempotent "replace what is at this id" verb the brief's `POST` was reaching for.

| Method | Path | Purpose | Body | Capability |
|---|---|---|---|---|
| `GET` | `/api/profiles` | Every saved profile, summarised | — | none |
| `POST` | `/api/profiles` | Save a new profile | `TrainingProfileCreate` | none |
| `GET` | `/api/profiles/{id}` | One profile, in full | — | none |
| `PUT` | `/api/profiles/{id}` | Replace name/description/author/scenario of an existing profile | `TrainingProfileCreate` | none |
| `DELETE` | `/api/profiles/{id}` | Remove a profile | — | none |
| `POST` | `/api/profiles/{id}/apply` | Run the embedded scenario against the connected simulator | — | see §2.2/§6.3 — refused **per component**, never for the whole call |
| `POST` | `/api/profiles/import` | Upload a `.json` file exported from this or another instance | multipart file | none |
| `GET` | `/api/profiles/{id}/export` | Download the profile as a `.json` file (`Content-Disposition: attachment`) | — | none |

None of the CRUD endpoints or import/export touch the simulator or navdata, so none of them is
ever 501 or 503. Only `apply` reaches the adapter, and it reports refusal inside its 200 body
(D8) rather than at the HTTP layer — the one place this manager's error handling differs from
every sibling manager's, and the difference is deliberate (§6.3).

### 2.1 Validation errors — 422

- `TrainingProfileCreate`/`PUT` body fails pydantic validation (empty name, a `ProfileFailure`
  whose `engine_index` doesn't match its catalogue entry, a malformed `WeatherRequest`, an
  unknown `ProfilePlacement` discriminator) — FastAPI's own 422, the nested models' own
  validators doing the work for free (composition dividend of D4).
- `POST /api/profiles/import` — the uploaded bytes are not valid JSON, or do not validate as
  `TrainingProfileCreate`-shaped content — 422 with the pydantic error detail. No partial import:
  a malformed upload creates nothing.

### 2.2 Not-found — 404

- `GET`/`PUT`/`DELETE /api/profiles/{id}`, `POST /api/profiles/{id}/apply`,
  `GET /api/profiles/{id}/export` on an unknown id — `"No training profile {id!r}."` (`DELETE`
  and `export`: `"...it may already be deleted."` — same sentence shape as failures §2's
  `DELETE /armed/{id}`).

### 2.3 Everything else

Storage I/O failure (disk full, permission denied) on a write — 500, FastAPI's default. This
manager does not fork the "no 502 for infrastructure failure" open question the Weather and
Failures designs both left open (`weather-manager.md` §11, `failures-manager.md` §10.7); when
that convention is settled app-wide, this manager follows.

---

## 3. Pydantic models

All in **`core/profiles/models.py`** unless stated. Units follow the house convention
(`_ft`, `_kt`, `_deg`, `_kg`); this manager introduces none of its own since every unit-bearing
field is borrowed from `core.models`, `core.weather.models` or `core.failures`.

### 3.1 The profile itself

```python
PROFILE_FORMAT_VERSION = 1


class TrainingProfile(BaseModel):
    """A saved scenario with a name and metadata (feature spec §14, verbatim).

    ``extra="ignore"`` deliberately (D9): this document is written and read
    only by this application, across versions that may add fields to
    ProfileScenario over time — see the tension this creates in §10.2.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    format_version: int = Field(default=PROFILE_FORMAT_VERSION, description="Storage schema tag.")
    profile_id: str = Field(
        min_length=32,
        max_length=32,
        description="Server-assigned uuid4 hex. Also the filename stem (<id>.json).",
    )
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    author: str | None = Field(default=None, max_length=200)
    created_at: datetime = Field(description="UTC, set once at creation.")
    updated_at: datetime = Field(description="UTC, set on every save/replace/import.")
    scenario: ProfileScenario


class TrainingProfileCreate(BaseModel):
    """POST /api/profiles and PUT /api/profiles/{id} body — everything the
    instructor supplies. The server fills profile_id, created_at, updated_at."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    author: str | None = Field(default=None, max_length=200)
    scenario: ProfileScenario


class ProfileSummary(BaseModel):
    """One row of GET /api/profiles. Cheap: no navdata lookup, no adapter read."""

    model_config = ConfigDict(frozen=True)

    profile_id: str
    name: str
    description: str
    author: str | None
    created_at: datetime
    updated_at: datetime
    airport_icao: str | None = Field(
        default=None,
        description="Best-effort teaser straight off the embedded placement's airport field, "
        "when it has one (runway/parking/procedure_leg placements). None for a "
        "coordinate, waypoint or hold placement, and never a navdata lookup.",
    )
```

### 3.2 The embedded scenario

```python
class ProfileFailure(BaseModel):
    """One failure the profile carries. Reuses core.failures directly (D4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: FailureRef  # core.failures.FailureRef
    trigger: FailureTrigger | None = Field(
        default=None,
        description="None = injected immediately when the profile is applied. Set = armed "
        "with this trigger instead — the same five trigger types Failures offers.",
    )


class ProfileScenario(BaseModel):
    """The saved setup: one placement, an aircraft-setup overlay, optional weather, failures.

    This is the "same model" the feature spec asks for, built by composing the
    already-core-owned request models of the other Phase 2 managers rather than
    inventing a parallel one — see D4 for why `placement` is the one field that
    could not be composed the same way.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    placement: ProfilePlacement
    setup_overrides: AircraftSetup = Field(
        default_factory=AircraftSetup,
        description="Merged OVER the placement's own derived setup at apply time — exactly "
        "ApplyPlacementRequest.setup's semantics (position-manager.md §7.6).",
    )
    weather: WeatherRequest | None = Field(
        default=None,
        description="None = the profile does not touch weather.",
    )
    failures: tuple[ProfileFailure, ...] = Field(
        default=(), description="Applied independently; one outcome per entry (§4)."
    )
```

### 3.3 The placement — provisional and flagged (D4)

`core/profiles/models.py` redeclares the same six discriminated arms
`server/position_routes.py::PlacementRequest` carries, field-for-field identical. The inner
geometry types (`RunwayPlacement`, `ApproachCategory`, `ProcedureKind`) are already `core/`-owned
(`core.geodesy`, `core.navdata.models`) and are imported directly — only the outer request
wrapper is duplicated.

```python
class ProfileRunwayPlacement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["runway"]
    airport_icao: str = Field(min_length=2, max_length=7)
    runway_ident: str = Field(min_length=1)
    placement: RunwayPlacement  # core.geodesy
    glideslope_deg: float | None = Field(default=None, gt=0.0, le=10.0)
    pattern_altitude_ft: float | None = None
    pattern_width_nm: float | None = Field(default=None, gt=0.0)
    leg_distance_nm: float | None = Field(default=None, gt=0.0)
    ias_kt: float | None = Field(default=None, ge=0.0)
    category: ApproachCategory | None = None  # core.geodesy


class ProfileParkingPlacement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["parking"]
    airport_icao: str = Field(min_length=2, max_length=7)
    stand_name: str = Field(min_length=1)


class ProfileCoordinatePlacement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["coordinate"]
    position: GeoPosition  # core.models
    heading_deg: float | None = None
    ias_kt: float | None = Field(default=None, ge=0.0)


class ProfileWaypointPlacement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["waypoint"]
    ident: str = Field(min_length=1)
    region_code: str | None = None
    terminal_airport: str | None = None
    altitude_ft: float
    heading_deg: float | None = None
    ias_kt: float | None = Field(default=None, ge=0.0)
    category: ApproachCategory | None = None


class ProfileProcedureLegPlacement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["procedure_leg"]
    airport_icao: str = Field(min_length=2, max_length=7)
    kind: ProcedureKind  # core.navdata.models
    ident: str = Field(min_length=1)
    transition: str | None = None
    sequence: int
    altitude_ft: float | None = None
    ias_kt: float | None = Field(default=None, ge=0.0)
    category: ApproachCategory | None = None


class ProfileHoldPlacement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["hold"]
    fix_ident: str = Field(min_length=1)
    region_code: str | None = None
    airport_icao: str | None = None
    altitude_ft: float | None = None
    ias_kt: float | None = Field(default=None, ge=0.0)
    category: ApproachCategory | None = None


ProfilePlacement = Annotated[
    ProfileRunwayPlacement
    | ProfileParkingPlacement
    | ProfileCoordinatePlacement
    | ProfileWaypointPlacement
    | ProfileProcedureLegPlacement
    | ProfileHoldPlacement,
    Field(discriminator="type"),
]
```

**Contract note, pinned once so nobody has to remember it:** every field, type, constraint and
`type` literal value above must stay byte-identical to its counterpart in
`server/position_routes.py`. §8.1's shape-parity test enforces this mechanically; it is not a
matter of discipline.

### 3.4 The apply outcome — `server/profile_routes.py` (HTTP furniture)

These embed other managers' own response models directly — legitimate, since this file is
server-side composing server-side (§6.3).

```python
class ProfilePositionOutcome(BaseModel):
    applied: bool
    result: PlacementResult | None = None  # server.position_routes.PlacementResult
    reason: str | None = None  # set iff applied is False


class ProfileWeatherOutcome(BaseModel):
    attempted: bool  # False when the profile carries no weather block
    applied: bool
    result: WeatherApplyResult | None = None  # server.weather_routes.WeatherApplyResult
    reason: str | None = None


class ProfileFailureOutcome(BaseModel):
    ref: FailureRef
    applied: bool
    armed: bool  # True = registered with a trigger, not injected
    armed_id: str | None = None  # set iff armed is True and applied is True
    reason: str | None = None


class ProfileApplyResult(BaseModel):
    profile_id: str
    position: ProfilePositionOutcome
    weather: ProfileWeatherOutcome
    failures: tuple[ProfileFailureOutcome, ...]
    degraded: bool = Field(
        description="True iff any attempted component (position always attempted; weather "
        "only when the profile carries one; every failure entry) did not fully "
        "apply. False means every attempted component succeeded — not that the "
        "profile did everything it could theoretically do; a profile with no "
        "weather block is never 'degraded' for lacking one.",
    )
    notes: tuple[str, ...] = Field(
        default=(),
        description="Human sentences in position -> weather -> failures order, "
        "rendered verbatim by the panel.",
    )
```

---

## 4. `SimAdapter` / `Capabilities` additions

**None.** Applying a profile calls, in-process, exactly the apply functions the Position, Weather
and Failures managers already expose:

- `server.position_routes.apply_placement(ApplyPlacementRequest)` — already gated on
  `can_set_position` (and `can_set_aircraft_state` for a non-empty setup), already 501-or-succeed.
- `server.weather_routes`'s apply path — already gated on `can_set_weather` (`weather-manager.md`
  §2).
- `server.failure_routes`'s inject/arm paths — already gated on `can_inject_failures`, per-entry
  supportability already reported by `get_failure_support()` (`failures-manager.md` §4).

`server/profile_routes.py` calls each directly and catches the `HTTPException`/refusal each
already raises, turning it into an outcome + reason (§6.3) instead of letting it propagate — the
only place this manager touches those exceptions at all. **No `Capabilities` flag, no
`SimAdapter` method, no `FakeSimAdapter` change, no contract-suite addition.** This section is a
statement of absence, not an oversight: say it plainly rather than leave it unstated, per this
design's own instructions.

---

## 5. Dataref mapping (X-Plane)

**None.** This manager never talks to `adapters/xplane/` directly; it reaches the simulator only
through the Position/Weather/Failures managers' own adapter calls, which already own their
dataref mappings. Nothing is added to `adapters/xplane/` for Training Profiles. MSFS is identical
for the same reason: whatever capability subset MSFS declares, this manager degrades exactly as
the component managers already degrade — zero MSFS-specific code here, which is the Phase 5
measure of success stated in `architecture.md`.

---

## 6. `core/` logic

New package `core/profiles/` — models, storage, path computation. No HTTP, no adapter import, no
navdata provider import. Fully unit-testable with `tmp_path` and no simulator.

### 6.1 `core/profiles/paths.py` — where profiles live

```python
APP_NAME = "OpenInstructorStation"


def default_profiles_root(*, environ: Mapping[str, str] | None = None) -> Path:
    """The per-OS user application-data directory for training profiles.

    Pure computation, no I/O (constructing the path never creates it — the
    NavdataProvider precedent: nothing touches disk until something is
    actually read or written). ``environ`` is injectable for tests, following
    the exact pattern core/navdata/xplane_native/index.py's cache_directory()
    already established for OIS_NAVDATA_CACHE_DIR.

    * Windows: ``%APPDATA%/OpenInstructorStation/profiles``
    * macOS:   ``~/Library/Application Support/OpenInstructorStation/profiles``
    * Linux/other POSIX (XDG Base Directory spec):
      ``$XDG_DATA_HOME/OpenInstructorStation/profiles``, default
      ``~/.local/share/OpenInstructorStation/profiles``

    No third-party dependency (D2): this is one directory on three branches,
    not the author/appname/roaming-vs-local surface a full platformdirs
    dependency would bring in for a pyproject.toml that pins its dependency
    set deliberately.
    """
```

`server/deps.py`'s `Settings.profiles_root: str | None` overrides this exactly like
`navdata_root` overrides navdata autodetection — same field-naming and override convention, no
new pattern invented.

### 6.2 `core/profiles/store.py` — the storage layer

```python
class ProfileStoreError(RuntimeError):
    """The store itself failed — disk full, permission denied, corrupt write.
    Never raised for "not found"; see the NavdataProvider precedent this
    mirrors (core/navdata/provider.py's own docstring: not-found is never
    an exception)."""


class ProfileStore:
    """One flat directory of ``<profile_id>.json`` files. No index (D5).

    Import-safe: the constructor performs no I/O and does not create the
    directory. Every write ensures the directory exists immediately before
    writing; every read treats a missing directory as an empty store.
    """

    def __init__(self, root: Path) -> None: ...

    def list(self) -> list[ProfileSummary]:
        """Every profile, newest updated_at first. A file that fails to parse
        is skipped and logged, never raised — the same "a bad record never
        stops the browse" rule the navdata index build uses for a malformed
        apt.dat row."""

    def get(self, profile_id: str) -> TrainingProfile | None: ...

    def create(self, draft: TrainingProfileCreate) -> TrainingProfile:
        """Assigns profile_id (uuid4().hex), created_at = updated_at = now(UTC),
        writes atomically (temp file in the same directory, then Path.replace —
        the same atomic-publish idiom the navdata index build uses), returns
        the stored TrainingProfile."""

    def replace(self, profile_id: str, draft: TrainingProfileCreate) -> TrainingProfile | None:
        """None when profile_id does not exist (PUT never creates). Otherwise
        keeps profile_id and created_at, bumps updated_at, writes atomically."""

    def delete(self, profile_id: str) -> bool:
        """False when the file was already gone. Never raises for that case."""

    def import_bytes(self, raw: bytes) -> TrainingProfile:
        """Parses `raw` as TrainingProfileCreate-shaped JSON (any embedded
        profile_id/created_at/updated_at/format_version in the uploaded
        document are ignored — D7), assigns a FRESH id, stores it, returns it.
        Raises pydantic.ValidationError on malformed content (the router maps
        that to 422); raises ProfileStoreError on an I/O failure."""

    def export_bytes(self, profile_id: str) -> bytes | None:
        """The canonical model_dump_json() of the stored profile, or None
        when the id does not exist."""
```

### 6.3 What is deliberately **not** in `core/` (D10)

The task brief for this design asked for "the degradation resolver" here. It is not, and the
reason is structural rather than a preference: resolving *what degrades* means calling
`apply_placement`, the weather apply path and the failure inject/arm paths, every one of which
awaits `SimAdapter` — and `core/` never talks to a simulator (`CLAUDE.md` hard rule 2). Putting a
"try each component, catch what fails" function in `core/` would mean `core/` importing
`server/position_routes.py`, which is the exact layering violation D4 already worked around once
for the placement model; doing it again for the orchestration would defeat the point.

The orchestration therefore lives in **`server/profile_routes.py`**:

```python
async def _apply_position(profile: TrainingProfile) -> ProfilePositionOutcome: ...
async def _apply_weather(profile: TrainingProfile) -> ProfileWeatherOutcome: ...
async def _apply_failures(profile: TrainingProfile) -> tuple[ProfileFailureOutcome, ...]: ...


async def apply_profile(profile: TrainingProfile) -> ProfileApplyResult:
    """Runs the three above independently — one component's failure never
    prevents another's attempt (the AIRAC-degradation requirement, generalised
    to every reason a component can fail: missing navdata, missing capability,
    an unsupported failure entry). Aggregates degraded = any attempted
    component with applied=False."""
```

`_apply_position` translates `ProfilePlacement` into `server.position_routes.PlacementRequest`
via `PlacementRequest.model_validate(profile_placement.model_dump())` — safe because of the
shape-parity guarantee (§3.3, §8.1) — builds `ApplyPlacementRequest(placement=..., setup=setup_overrides)`,
calls `apply_placement(...)` directly (an in-process function call, not a self-HTTP round trip),
and catches `HTTPException` (404 unresolved navdata, 422 unpositionable leg, 501 missing
capability) into `applied=False, reason=exc.detail`. `_apply_weather` and `_apply_failures`
follow the identical shape against their own managers' apply functions once those exist.

---

## 7. UI panel outline

New tab of the Instructor Panel: `ui/src/features/profiles/` — adding files. Shared-file edits,
all one line each and **sequenced, not parallel**, with Fuel & Payload's equivalent edits landing
the same phase (§9): `ui/src/store/uiSlice.ts` (`TAB_IDS` gains `"profiles"`),
`ui/src/store/index.ts` (reducer map gains `profiles: profilesReducer`),
`ui/src/components/tabs.ts` (the tab registry gains an entry), `App.tsx` (mounts `ProfilesPanel`),
`server/app.py` (`include_router`), `pyproject.toml` (D14).

**Note (as-designed caveat):** at the time this design was written the current shapes of
`ui/src/store/uiSlice.ts`, `ui/src/components/tabs.ts` and `ui/src/components/ComingSoonPanel.tsx`
could not be read from the working tree (see the note at the end of this document) — this section
describes them by the naming and structure established for the Weather/Failures panels
(`weatherSlice.ts`, `failuresApi.ts`, `injectEndpoints`), which is the same convention this
manager follows. Confirm field/registry names against the actual files before implementing.

### 7.1 Server state — RTK Query (`profilesApi.ts`, `injectEndpoints`)

| Endpoint | Kind | Notes |
|---|---|---|
| `getProfiles` | query, tag `Profiles` | drives the list |
| `getProfile` | query, tag `{type: 'Profiles', id}` | fetched when a row expands |
| `createProfile` | mutation, invalidates `Profiles` | the Save form |
| `deleteProfile` | mutation, invalidates `Profiles` | |
| `applyProfile` | mutation, invalidates `AircraftState` (the shared instructorApi tag — a profile apply moves the aircraft) | |
| `importProfile` | mutation (multipart `FormData` body), invalidates `Profiles` | |
| `exportProfile` | **not** an RTK Query endpoint — a plain `<a href="/api/profiles/{id}/export" download>`, so the browser handles the download natively with zero client-side blob juggling |

`PUT` (`replaceProfile`) is defined in `profilesApi.ts` for completeness (D13) but no component
calls it in Phase 2.

### 7.2 Client state — one slice (`profilesSlice.ts`)

```ts
interface ProfilesState {
  saveDraft: {
    name: string;
    description: string;
    author: string;
    includeWeather: boolean; // snapshot state.weather.staged when true and it exists
    failures: ProfileFailureDraft[]; // composed locally — Failures has no "staged" concept
    // to read (failures-manager.md D13: it fires immediately)
  };
}
```

Server data never lands here. `SaveProfileForm.tsx` reads (D11) `state.position.staged` /
`state.position.setupOverrides` from `positionSlice` and, once Weather ships,
`state.weather.staged` from `weatherSlice` — both already public, both read-only imports, no
existing file edited. **Save is disabled with a stated reason when `state.position.staged` is
null** — the fail-closed convention every other panel uses, applied here to "nothing to save"
rather than to a capability.

### 7.3 Components

| File | Role |
|---|---|
| `ProfilesPanel.tsx` | The tab: `SaveProfileForm` collapsed at the top, `ProfileList` below, an `Import` button. |
| `ProfileList.tsx` | One row per profile: name, description, author, airport teaser, updated date. Per row: **Apply** (fires `/apply`, D8 — no staging bar, the profile *is* the staged thing), **Export** (native download link), **Delete** (`window.confirm()`, D12 — the only confirmation dialog in this manager). |
| `SaveProfileForm.tsx` | Name/description/author fields, an "include current weather" toggle, an inline failure-list builder reusing the Failures catalogue via `getFailureCatalogue` (RTK Query, already generated) and the same `FailureId`/`FailureTrigger` types — no new catalogue invented. Disabled with a reason when nothing is staged in Position (D11). |
| `ApplyResultBanner.tsx` | Renders a `ProfileApplyResult`: three lines (position/weather/failures), green when `applied`, amber with `reason` when not, and the aggregate `degraded` state as the banner's overall tone. Never a modal. |

### 7.4 Gating

No capability gate at the tab level (D3 — nothing here needs one). Per-component refusal is
rendered entirely from `ProfileApplyResult.reason` after an apply attempt; there is nothing to
disable in advance because a profile's own component viability (does this adapter support
weather? does this navdata still have this runway?) is not knowable until apply time — the same
reasoning that makes this manager's apply endpoint always-200 (D8) rather than pre-gated.

Tablet-first: rows are 44 px+ touch targets, Apply is the largest button on each row (the
single most common action in this panel), the Save form is collapsed by default so the list is
above the fold.

---

## 8. Test plan

Everything runs against `FakeSimAdapter`, no navdata file, no simulator (hard rule 4 — this
manager needs neither for its own logic; its `-m sim` exposure is entirely inherited from the
managers it composes).

### 8.1 `core/` unit tests — `tests/core/profiles/`

- **`test_paths.py`** — `default_profiles_root(environ=...)` parametrised over the three branches
  (`win32`/`APPDATA`, `darwin`, linux/`XDG_DATA_HOME` set and unset, falling back to
  `~/.local/share`); pure function, no filesystem touched, no monkeypatching of `sys.platform`
  needed beyond parametrising the function's own branch logic directly.
- **`test_store.py`** (`tmp_path`, following `tests/core/navdata/test_index_build.py`'s
  copy-into-`tmp_path` discipline — nothing here mutates a committed fixture because there is no
  committed fixture): `create` → `get` round-trips exactly; `list` returns newest-first and skips
  a hand-written corrupt `.json` file with a logged warning rather than raising;
  `replace` on an unknown id returns `None`; `delete` on an unknown id returns `False`;
  `import_bytes` ignores an embedded `profile_id` in the upload and assigns a new one (D7);
  `import_bytes` on malformed JSON raises `pydantic.ValidationError`; `export_bytes` output
  round-trips through `TrainingProfile.model_validate_json`.
- **`test_models.py`** — `ProfileFailure` rejects an engine index mismatched against its
  catalogue entry (free, from `FailureRef`'s own validator); `ProfileScenario` rejects an unknown
  field (`extra="forbid"`); `TrainingProfile` tolerates an unknown top-level field
  (`extra="ignore"`, D9) and still validates.
- **`tests/server/test_profile_placement_shape.py`** (needs both `core.profiles.models` and
  `server.position_routes`, hence under `tests/server/`, not `tests/core/`): for every one of the
  six placement arms, a representative `ProfilePlacement` instance's `model_dump()` validates
  cleanly through `server.position_routes.PlacementRequest.model_validate(...)` and the round
  trip is lossless. **This is the mechanical enforcement of D4's shape-parity promise** — a
  future edit to either union that is not mirrored in the other fails this test, not a live
  instructor's apply call.

### 8.2 Contract tests

None to add (§4). No `CAPABILITY_COVERAGE` entry, no new adapter method.

### 8.3 Server tests — `tests/server/test_profile_routes.py`

Against `TestClient` + `FakeSimAdapter`, a `tmp_path`-backed `ProfileStore` (dependency override,
the same pattern `reset_navdata()`/`reset_adapter()` already establish):

- Full CRUD round trip: `POST` → `GET` list contains it → `GET` by id → `PUT` changes
  name/description → `DELETE` → subsequent `GET` 404s with the "may already be deleted" sentence.
- Import/export round trip: `POST /import` with a hand-built JSON body → 201-equivalent response
  carries a **different** `profile_id` than any embedded one in the upload → `GET .../export`
  bytes parse back to an equal `TrainingProfile` except for `profile_id`/timestamps.
- 422 on a malformed import upload, with the pydantic detail surfaced.
- **The degradation test (the one the feature spec calls out by name):** build a profile whose
  `placement` is a `runway` placement naming an airport/runway **absent** from the test's minimal
  in-memory navdata fixture. `POST .../apply` → `200`, `position.applied is False`,
  `position.reason` names the runway, `degraded is True`, while `weather.applied is True` and
  every entry in `failures` has `applied is True` — proving "apply the rest" is not a slogan.
- A second degradation case: an adapter subclassed with `can_inject_failures=False` — the profile's
  position and weather still apply; every failure outcome is `applied=False` with the capability
  sentence; `degraded is True`.
- The happy path: every component of a fully-resolvable profile applies; `degraded is False`;
  `position.result`/`weather.result` echo what `apply_placement`/the weather apply path actually
  returned (not what was asked for — the honest-readback posture every sibling manager uses).

### 8.4 What only `-m sim` can prove

Nothing new. Whatever `-m sim` coverage the Position/Weather/Failures managers carry already
exercises the calls this manager makes; there is no profile-specific simulator behaviour to
validate. Stated explicitly rather than left implicit, per this design's own instructions.

### 8.5 Fixtures

None beyond `tmp_path` and the existing minimal in-memory navdata fixture the server test suite
already uses for the Position Manager's own tests (`tests/server/conftest.py`'s `ZZZZ`). No
navdata file of any kind is written to disk for this manager's own tests (hard rule 4).

### 8.6 UI tests (vitest) — `ui/src/features/profiles/`

`ProfileList.test.tsx` (Apply issues exactly one `POST .../apply`, asserted `toEqual` against a
stubbed `fetch`; Delete calls `window.confirm` before issuing the `DELETE`, and issues nothing
when the confirm is declined; Export renders an `<a href>` to the exact export URL, not a
`fetch`); `SaveProfileForm.test.tsx` (disabled with the stated reason when `position.staged` is
`null`; the composed `TrainingProfileCreate` body matches the staged placement + overrides +
locally-built failure list exactly, `toEqual`); `ApplyResultBanner.test.tsx` (renders each
component's reason when `applied` is false, renders green when `degraded` is false).

---

## 9. Parallelisation

This is a small, mostly-serial manager: **one implementer, one reviewer**, not a set of
concurrent tracks — inventing parallel tracks for a thin manager would be exactly the
over-engineering `CLAUDE.md`'s parallelisation policy warns against applying blindly.

- **No contract change** (§4), so there is no serialised foundation step the way Weather and
  Failures each need one — this manager can be built start to finish on one branch.
- **Real dependency:** `core.weather.models.WeatherRequest` and `core.failures.FailureRef`/
  `FailureTrigger` must exist and be stable (merged to `dev`, or at minimum frozen on their own
  branches) before `core/profiles/models.py` can import them. This manager should not start
  before Weather and Failures have landed their `core/` packages, matching the roadmap's own
  ordering ("the Scenario Generator waits for all three… Training Profiles" alongside it).
- **Sequenced, not parallel, with Fuel & Payload:** the shared-file edits of §7 (`uiSlice.ts`,
  `store/index.ts`, `tabs.ts`, `pyproject.toml`'s packages list) are one-line each but are the
  same files Fuel & Payload's own new tab touches. Land one PR, then the other; do not dispatch
  both tab-registration edits in the same message.
- **The tester writes §8.1/§8.3 against this document without waiting for the implementation** —
  the models here are complete enough that a failing test indicts the code, per house convention.

**Never parallelised:** merges to `dev`/`main`; release tagging. No navdata schema is touched by
this manager at all, so the navdata serialisation rule does not even apply here.

---

## 10. Open questions and risks

### 10.1 The Scenario Generator has not landed — this is the real dependency

`scenario-generator.md` did not exist when this design was written; this document was built
directly against the feature spec and roadmap instead, per instruction, rather than blocking.
Two things need reconciling once it lands:

1. **The placement duplication (D4).** If the Scenario Generator resolves its own, structurally
   identical need for a `core/`-owned placement request (it must have one — a YAML scenario
   parsed and validated in `core/` needs to express a position, and `core/` cannot import
   `server/position_routes.py` any more than this manager can) by defining, say,
   `core/scenarios/models.py::ScenarioPlacement`, then `core/profiles/models.py`'s six arms
   should be deleted and `ProfilePlacement` become an alias/import of that type — a mechanical
   change the shape-parity test (§8.1) will catch if it is missed. **What resolves it:** read
   `scenario-generator.md` the moment it lands and diff its placement model against §3.3 field
   for field.
2. **Whether `ProfileScenario` should simply *be* `core.scenarios.models.Scenario`.** Feature
   spec §14's "a training profile is a saved scenario with a name and metadata" argues for
   `TrainingProfile = metadata + Scenario` literally, collapsing `ProfileScenario` entirely into
   whatever the Scenario Generator defines (which per its own feature-spec item would also carry
   traffic, closing §10.3 below at the same time). This design's `ProfileScenario` is a deliberate
   narrower stand-in — everything the Scenario Generator's `Scenario` is expected to need (weather,
   failures, aircraft setup, position) minus traffic — chosen so this manager is buildable now.
   **What resolves it:** a decision at Scenario Generator design time on whether the two documents
   merge outright; if they do, this manager's diff is deleting `ProfileScenario` and wrapping
   `Scenario` instead, not a redesign.

### 10.2 `extra="forbid"` on the embedded scenario fights cross-version sharing (D9)

An instructor on a newer build exports a profile whose `ProfileScenario` has grown a field (say,
Phase 3's traffic block, §10.3); a colleague on an older build's `extra="forbid"` nested models
reject the import outright rather than degrading. This is the same shape of problem the
AIRAC-degradation requirement solves for navdata, but this design does not solve it for the
document's own schema. **What would resolve it:** either gate on `format_version` explicitly
(refuse only when the *major* format changed, ignore forward within a minor) or relax the nested
models to `extra="ignore"` too and accept losing typo-catching for hand-edited files, trading one
convention for the other. Not decided — flagged for whoever ships the first schema-changing
addition (most likely §10.3's traffic field).

### 10.3 Traffic — deliberately absent now, additive later

`ProfileScenario` carries no traffic field because the feature spec's own list for manager 14
does not mention it (§1.2). When Phase 3's `can_spawn_traffic` and the Scenario Generator's
traffic model exist, adding `traffic: tuple[...] = ()` to `ProfileScenario` is additive and
backward-compatible for *reading* old files (a missing field defaults to empty) but not
forward-compatible for *older* code reading a *newer* file, per §10.2.

### 10.4 The Save form's cross-slice read (D11) is a Phase 2 stopgap

Reading `positionSlice`/`weatherSlice` state directly from Profiles' own files is the minimum
viable integration before the Scenario Generator exists. Once it does, the more natural
integration is almost certainly "Save as profile" as a button on the Scenario Generator's own
staging surface (which will already hold the full composed document this manager currently
reconstructs by hand from two other tabs). **What resolves it:** revisit this section once
`scenario-generator.md` exists; if its staging area supersedes this, `SaveProfileForm.tsx` shrinks
to "attach a name to what the Scenario Generator already built" and the cross-slice reads are
deleted, not extended.

### 10.5 Profile size limits

Not designed. A profile is a few KB of JSON; nothing here bounds file count or total storage.
**What would resolve it:** wait for an instructor to report it mattering — inventing a quota
against zero observed usage is exactly the over-engineering this design tries to avoid elsewhere.

### 10.6 Cross-machine sync

Out of scope, and not expected to become in-scope: "shareable between instructors" is served
entirely by import/export (D6), which is already a manual, deliberate hand-off — not an
always-on sync the feature spec never asks for. Recorded so it is not silently reconsidered later
without this note being read.

### 10.7 Is partial apply (D8) the right default?

This design chooses "apply as much of the profile as possible" over "apply nothing unless
everything succeeds," directly because the feature spec states the AIRAC case in those terms. It
is not obviously the right choice pedagogically in every case — an instructor expecting a full
crosswind-at-minima exercise and silently getting only the weather (position refused because a
runway was renamed) has a different, and arguably worse, lesson than none at all, softened only
by `degraded` being visible in the response. **What would resolve it:** confirm this against the
Scenario Generator's own execute-plan semantics when that design lands — the two should agree,
and right now neither is validated against real instructor workflow.

---

## 11. Verification

```bash
pytest                       # unit + server tests, Fake only — must be green before any merge
ruff check . && ruff format --check .
mypy .                       # frozen models + Protocol conformance catch drift early
cd ui && npm run lint && npm run typecheck && npm test && npm run build
```

No `pytest -m sim` addition (§8.4). Panel smoke (fake adapter + Vite dev server, one batched
browser session): stage a runway placement in the Position tab → open Profiles → Save with a
name → the new row appears in the list → Apply → `ApplyResultBanner` shows all-green → Export
downloads a `.json` → delete the profile, import the exported file back → a new row with a new id
appears → console clean.

---

## Design-time caveat: filesystem state at write time

`docs/designs/scenario-generator.md` and `docs/designs/fuel-payload.md` did not exist yet at
design time. Several files this design's brief referenced as already present
(`ui/src/store/uiSlice.ts`, `ui/src/components/tabs.ts`, `ui/src/components/ComingSoonPanel.tsx`)
were not found on disk during research — a consequence of the shared checkout being on a git
branch that did not yet carry the (separately landed) UI panel work at the moment this design was
written, not a real absence. §7's shapes should be confirmed against the actual files once they
are back on `dev` before implementation starts; §9 and §10.1 already flag the resulting
reconciliation points explicitly.
