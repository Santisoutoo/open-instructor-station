# Design — `NavdataProvider`

**Status:** design fixed. **Issue:** [#3](https://github.com/Santisoutoo/open-instructor-station/issues/3).
**Phase:** 1 — Position Manager + Aircraft Control.
**Blocks:** #4 (CIFP parser), #5 (`apt.dat` + `earth_*` indexer), part of #6 (geodesy).

This document fixes the contract before any parser is written, the same way `SimAdapter` was fixed
before any adapter. It is written to be read by the four parallel tracks of Phase 1: everything
they need to agree on is here, and everything else is theirs.

The binding rules live in [`../../CLAUDE.md`](../../CLAUDE.md); the boundaries in
[`../architecture.md`](../architecture.md#navdata-pipeline). This document never relaxes either.

**All record layouts and decoding rules below were verified against a real X-Plane 12 install
(Navigraph AIRAC 2607 in `Custom Data/`, Laminar data in `Resources/default data/`). No byte of
that data is reproduced here beyond the few illustrative lines needed to specify a parser.**

---

## 0. What this is, in one paragraph

`NavdataProvider` is the read-only interface to **the world**: airports, runways, parking stands,
navaids, fixes, published holds and instrument procedures, read from the data files the user
already has on disk. `SimAdapter` is **the live simulator**. They are two different things and
this document keeps them apart on purpose (§2).

---

## 1. Decisions at a glance

| # | Decision | Where |
|---|---|---|
| D1 | The query interface is **synchronous**. Only the index build is a long-running job with progress. | §3 |
| D2 | `NavdataProvider` is a `Protocol` in `core/navdata/`, with **three implementations**: the X-Plane-native file reader, an in-memory fixture provider (the CI reference), and — Phase 5 — an MSFS BGL reader. | §2, §4 |
| D3 | It is **selected independently of the adapter**. `OIS_ADAPTER=fake` + `OIS_NAVDATA=xplane_native` is legal, supported, and the recommended dev loop. | §2 |
| D4 | `core.models.Runway` is **reused unchanged** and extended **additively** with optional fields. Nothing in `core/geodesy.py` or its tests changes. | §5.3 |
| D5 | `earth_*.dat` and `apt.dat` are **indexed into SQLite up front**; `CIFP/<ICAO>.dat` is **parsed lazily** and held in an in-process LRU, **not** persisted. | §7 |
| D6 | The cache key is a **fingerprint tuple** whose primary component is the AIRAC cycle. There are **no migrations**: a key mismatch deletes the file and rebuilds. | §8 |
| D7 | Source precedence is resolved **per file**, not per directory — verified necessary. | §9 |
| D8 | Installation discovery is **config → `x-plane_install_12.txt` → well-known roots → declared unavailable**. Never an exception at click time. | §10 |
| D9 | Spatial queries use a **bounding-box prefilter on indexed lat/lon + exact geodesic refine**. No R\*Tree, no FTS5 — no optional SQLite modules. | §6.4 |
| D10 | Not-found returns `None` / `[]`. Exceptions are for *broken*, never for *absent*. | §4.6 |
| D11 | Every directional field is suffixed `_true_deg` or `_mag_deg`. The provider **never converts** between the two. | §5.1 |
| D12 | The real file parser **runs in CI** against a committed hand-written fixture tree. Only the run against the user's own install is excluded. | §11 |
| D13 | Models that cross the navdata↔sim seam (`Runway`, `Ils`, `RunwaySurface`) live in `core/models.py`. **`core/navdata/models.py` imports from `core/models.py`, never the reverse.** | §5.0 |
| D14 | The finished cache is `journal_mode = DELETE` and every reader opens it `mode=ro&immutable=1`. **Never WAL.** | §6.5 |
| D15 | A published cache file is **never overwritten**. Each build writes a new generation and readers reopen on an epoch bump. | §8.4 |
| D16 | Cancellation is an explicit `threading.Event`, not a return value from the progress callback. | §3, §7.3 |

---

## 2. Boundaries

### 2.1 It is not part of `SimAdapter`

`SimAdapter` is *live sim state over a wire*: connect, read the aircraft, write position, stream.
`NavdataProvider` is *the static world on disk*: it has no connection, no lifecycle, no
capabilities, and it is equally useful with no simulator running at all.

Concretely, and testably:

- No `NavdataProvider` method takes or returns any type from `core.sim_adapter`.
- No `SimAdapter` method takes or returns any navdata model.
- Neither imports the other. `core/navdata/` does not import `core/sim_adapter.py`.
- The two are wired **independently** in `server/deps.py`: `get_adapter()` and `get_navdata()`
  are separate singletons, selected by separate settings.

That last point is the load-bearing one. `OIS_ADAPTER=fake OIS_NAVDATA=xplane_native` gives the
whole Position Manager — real airports, real procedures, real ILS frequencies — with no simulator
anywhere. That combination is the intended development and demo loop, and it is proof the two are
not entangled. The inverse, `OIS_ADAPTER=xplane OIS_NAVDATA=in_memory`, is equally legal and is
what the sim-validator uses to test repositioning without depending on the user's navdata.

**Why this matters in Phase 5.** MSFS stores navdata in binary BGL files with an entirely
different structure. It gets `MsfsNavdataProvider` satisfying this same Protocol, and the measure
of success is that **nothing in `core/`, `server/` or `ui/` changes** — the contract suite runs
against it unmodified. If `NavdataProvider` had been folded into `SimAdapter`, an MSFS user would
be forced to use MSFS navdata and an X-Plane user X-Plane navdata, and the two concerns would have
to be untangled under schedule pressure. That is the cost this separation avoids.

### 2.2 It does not know a simulator exists (hard rule 2)

`core/navdata/` reads files from a directory. It does not open a socket, does not know a dataref
name, does not import `httpx`, `websockets` or `SimConnect`, and does not care whether X-Plane is
running. `architecture.md` already states the principle: *"The provider lives in `core/`: it reads
files from disk, which is not talking to a simulator."*

**On naming.** The concrete reader is `core/navdata/xplane_native/`. This names a **file format**
(the Laminar `apt.dat 1200` / `earth_* 1200` / CIFP ARINC-424-subset specification, versioned by
the `1200`/`1150`/`1140`/`1100` header numbers in the files themselves), not a simulator. The
distinction is not a word game: a user can point the provider at an X-Plane data tree while flying
MSFS, and that works. BGL is likewise a format, and `core/navdata/msfs_bgl/` will sit beside it.

**Enforced, not aspired to.** `tests/core/navdata/test_core_boundaries.py` walks the import graph
of every module under `core/` and fails on `httpx`, `websockets`, `SimConnect`, `adapters.*`, or
any dataref-shaped string literal (`sim/`, `laminar/`), plus the two edges D13 forbids (§11.6).

**That file does not exist yet** — the rule it encodes has held so far by review alone. It is
created by the foundation work of this design, before the parallel tracks branch, precisely
because `core/navdata/` is the first part of `core/` big enough for the rule to be broken by
accident rather than by intent.

---

## 3. Sync or async — and why

**The query interface is synchronous.** Every read method is a plain `def`.

The reasoning, in order of weight:

1. **There is nothing to await.** This reads a local SQLite file and, occasionally, one 7 KB text
   file. `sqlite3` in the standard library is blocking and has no async API; wrapping it in
   `asyncio.to_thread` per call would add a thread hop and a context switch to a query that
   completes in tens of microseconds. `SimAdapter` is async because it talks to a network with
   real latency and a persistent stream. This does not.
2. **Async is contagious, and `core/` is where it hurts.** `core/geodesy.py` is synchronous pure
   functions and is the right shape. A synchronous `NavdataProvider` composes with it directly:
   the Position Manager's placement pipeline — resolve anchor, compute geodesy, build the setup —
   stays one readable synchronous function with no `await` in the middle of the maths.
3. **FastAPI already solves the only real problem.** A blocking call inside an `async def` route
   stalls the event loop. The fix is not to make `core/` async; it is to declare the navdata
   routes as **`def`**, which Starlette runs in its worker threadpool. This is a one-line
   convention in `server/`, documented in §12, and it costs nothing.
4. **Tests get simpler.** No `pytest-asyncio` on the navdata suite, no event loop fixtures, no
   async generators in the fixture provider.

**The one exception: the index build.** It takes 60–120 seconds on first run (§7.3) and must
report progress, and must be interruptible. It is exposed as a synchronous method taking a
progress callback and a cancellation event:

```python
def ensure_index(
    self,
    *,
    progress: Callable[[IndexProgress], None] | None = None,
    cancel: threading.Event | None = None,
    force: bool = False,
) -> NavdataStatus: ...
```

**D16 — cancellation is the `Event`, not the callback's return value.** The callback returns
`None` and therefore cannot signal anything; a design that says "the progress callback may signal
stop" while typing it `-> None` is specifying something the signature forbids. The build checks
`cancel.is_set()` once per insert batch (10 000 rows, §6.5) and once per progress emission — a
sub-second reaction with no per-row cost. On cancellation it deletes the partial `.tmp` file and
returns the **previous** status unchanged; a cancelled build never publishes and never degrades
what was already there. `threading.Event` is the right type because the build runs in a worker
thread and the canceller (`asyncio` shutdown, or a second `rebuild` request) does not.

`server/` runs it once at startup in a worker thread (`asyncio.to_thread`), and the callback
pushes `IndexProgress` frames onto the **existing** WebSocket state pump. The provider itself
stays synchronous and knows nothing about event loops, WebSockets or FastAPI — including how the
frames cross back into the loop, which is `server/`'s problem and is specified in §12.

**Progress emission is throttled at the source.** `apt.dat` is 12.35 M lines; a frame per line,
or per 1 000 lines, is a denial of service on the WebSocket for a bar that moves in pixels. The
build emits **at most one `IndexProgress` per 0.5 s or per 1% of overall `fraction`, whichever
comes first**, plus one unconditional frame at every stage boundary so no stage is invisible.

**Thread-safety, since the threadpool implies it.** `sqlite3` connections must not cross threads.
The provider holds a `threading.local()` with one **read-only** connection per thread, opened as

```python
sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
```

with `row_factory = sqlite3.Row`. `immutable=1` is load-bearing, not an optimisation — see D14
in §6.5 — and it is only sound because a published cache file is never written and never replaced
in place (D15, §8.4). Each thread-local connection also carries the **epoch** it was opened at and
is reopened when the provider's epoch has moved on (§8.4). This is all stated here because
discovering it as an intermittent Windows CI failure is the expensive way to learn it.

---

## 4. The interface

Lives in `core/navdata/provider.py`. `@runtime_checkable Protocol`, mirroring `SimAdapter`'s
shape so the two read the same way.

```python
@runtime_checkable
class NavdataProvider(Protocol):
    """Read-only access to the navigation world: airports, runways, parking,
    navaids, fixes, holds and instrument procedures.

    Implementations must be import-safe: constructing a provider performs no
    I/O. Nothing is read until `status()` or a query is called, and no index is
    built until `ensure_index()` is called.
    """

    # --- Identity and lifecycle -------------------------------------------

    #: "xplane_native" | "in_memory" | "msfs_bgl"
    @property
    def name(self) -> str: ...

    # Cheap. Never raises. Returns an immutable snapshot (§4.5), so it is safe
    # to call from any thread while a build is running. The navdata analogue of
    # GET /api/capabilities: the UI gates on this, exactly as it gates on
    # Capabilities.
    def status(self) -> NavdataStatus: ...

    # Build the index if the cache key does not match (or `force`).
    # Idempotent. Long-running. Safe to call from a worker thread.
    # `cancel` is checked per insert batch; a cancelled build publishes nothing.
    def ensure_index(
        self,
        *,
        progress: Callable[[IndexProgress], None] | None = None,
        cancel: threading.Event | None = None,
        force: bool = False,
    ) -> NavdataStatus: ...

    # --- Airports ----------------------------------------------------------

    def get_airport(self, icao: str) -> Airport | None: ...

    # Type-ahead over ICAO, IATA and name. Ranked, bounded. See §6.3.
    def search_airports(self, query: str, *, limit: int = 20) -> list[AirportSummary]: ...

    def airports_near(
        self, centre: GeoPosition, radius_nm: float, *, limit: int = 50
    ) -> list[AirportSummary]: ...

    # --- Runways -----------------------------------------------------------

    # One entry per runway END (18L and 36R are two Runways). Sorted by ident.
    def get_runways(self, icao: str) -> list[Runway]: ...

    # `ident` in apt.dat form: "18L", not "RW18L". Both accepted, "18L" returned.
    def get_runway(self, icao: str, ident: str) -> Runway | None: ...

    # --- Parking -----------------------------------------------------------

    # Gates and stands are one model with a `kind`. The UI filters; see §5.6.
    def get_parking(self, icao: str, *, kind: ParkingKind | None = None) -> list[ParkingStand]: ...

    # --- Procedures --------------------------------------------------------

    # Summaries only — LEMD has 100+ procedures and the UI lists before it draws.
    def get_procedures(
        self, icao: str, *, kind: ProcedureKind | None = None
    ) -> list[ProcedureSummary]: ...

    # Legs fully resolved: every positionable leg already carries its fix.
    def get_procedure(
        self,
        icao: str,
        kind: ProcedureKind,
        ident: str,
        transition: str | None = None,
    ) -> Procedure | None: ...

    # --- Navaids and fixes -------------------------------------------------

    # A list: navaid idents are NOT globally unique. Sorted by ident, then region.
    def get_navaids(
        self,
        ident: str,
        *,
        region: str | None = None,
        kinds: Collection[NavaidKind] | None = None,
    ) -> list[Navaid]: ...

    # Sorted by distance ascending.
    def navaids_near(
        self,
        centre: GeoPosition,
        radius_nm: float,
        *,
        kinds: Collection[NavaidKind] | None = None,
        limit: int = 50,
    ) -> list[Navaid]: ...

    # Localizer + glideslope + category, ready to feed AircraftSetup.
    def get_ils(self, icao: str, runway_ident: str) -> Ils | None: ...

    def get_fixes(
        self,
        ident: str,
        *,
        region: str | None = None,
        terminal_airport: str | None = None,
    ) -> list[Fix]: ...

    def fixes_near(
        self, centre: GeoPosition, radius_nm: float, *, limit: int = 50
    ) -> list[Fix]: ...

    # The single place the 4-part ARINC key becomes a coordinate. See §5.8.
    def resolve_fix(self, ref: FixRef) -> Waypoint | None: ...

    # --- Holds -------------------------------------------------------------

    # Published holds from earth_hold.dat. Procedure holds (HM/HA/HF legs)
    # arrive through get_procedure() and are deliberately NOT merged (§5.10).
    def get_holds(
        self,
        *,
        fix_ident: str | None = None,
        region: str | None = None,
        airport_icao: str | None = None,
    ) -> list[Hold]: ...
```

### 4.1 Naming conventions

- `get_*` — one-or-`None`, or a list keyed by a parent (`get_runways(icao)`).
- `search_*` — free user text, ranked, always bounded by `limit`.
- `*_near` — spatial, always bounded by both a radius and a `limit`.

### 4.2 Why `list` and not iterators

Every result set is bounded by construction (an airport has <10 runways, <500 stands, <200
procedures; spatial queries carry a `limit`). Lists of pydantic models serialise straight into
FastAPI responses and into the generated UI client. A lazy iterator would leak the SQLite cursor's
thread affinity out of the provider — exactly the bug §3 exists to prevent.

### 4.3 Immutability

Every returned model is `frozen=True`, matching `GeoPosition`, `Runway` and `Capabilities`. Navdata
is read-only by definition; a frozen model makes accidental mutation of a cached CIFP parse
impossible rather than merely discouraged.

### 4.4 Identifier normalisation

Applied at the boundary, once, so no caller ever branches on a source quirk:

| Input | Normalised to |
|---|---|
| Runway ident `RW18L` (CIFP) / `18L` (apt.dat) | `18L` |
| Runway ident `RW32B` (CIFP "both parallels") | expanded to the airport's real idents — see §5.7 |
| ICAO codes | upper-case, stripped |
| Search text | casefolded, accent-stripped (`Suárez` → `suarez`) |

### 4.5 `NavdataStatus` — the gate

```python
class NavdataStatus(BaseModel, frozen=True):
    state: Literal["unavailable", "building", "ready", "error"]
    reason: str | None  # human-readable, always set when not "ready"
    provider: str  # "xplane_native" | "in_memory" | "msfs_bgl"
    source_root: str | None  # the resolved install path, as a string for JSON
    airac_cycle: str | None  # "2607"
    cycle_valid_from: date | None
    cycle_valid_to: date | None
    built_at: datetime | None
    airport_count: int | None
    runway_count: int | None
    navaid_count: int | None
    fix_count: int | None
    progress: IndexProgress | None  # populated only while state == "building"


class IndexProgress(BaseModel, frozen=True):
    stage: Literal["airports", "runways", "parking", "navaids", "fixes", "holds", "finalising"]
    stage_index: int  # 1-based
    stage_count: int
    fraction: float  # 0.0 … 1.0 overall
    detail: str | None  # "apt.dat — 8.1 M / 12.4 M lines"
```

`status()` is to navdata what `GET /api/capabilities` is to the simulator: **the UI disables what
is not available and states why.** An instructor never discovers missing navdata by clicking a
control that fails. This is the same discipline as hard rule 3, applied to a second axis.

**How `status()` and the build share state — one rule, because they run in different threads.**
The build thread **never mutates a shared status object**. It constructs a whole new frozen
`NavdataStatus` and publishes it by assigning a single attribute on the provider; `status()` does
nothing but return that reference. A single attribute assignment and a single attribute read are
individually atomic under the GIL, so a reader always sees one coherent status — the one before
the update or the one after — and never a half-written mix of `state="ready"` with a stale
`progress`. Building the frames field-by-field into a shared mutable object would make that
tearing possible, and it would surface as a UI that shows "ready" next to a progress bar at 62%.
This is the *only* synchronisation the provider needs: no lock, no queue.

### 4.6 Error model

Mirrors `CapabilityNotSupported` — narrow, and a caller bug rather than a runtime condition.

| Situation | Behaviour |
|---|---|
| Airport / runway / navaid / fix / procedure not found | `None` or `[]`. **Never an exception.** |
| No X-Plane install found | `status().state == "unavailable"`; queries raise `NavdataUnavailable`. |
| Index not built yet | `status().state == "building"` or `"unavailable"`; queries raise `NavdataUnavailable`. |
| A source file is corrupt / unreadable / a malformed record | The build logs and **skips the record**, counting it. `status().reason` carries the count. A record is never allowed to fail the whole build. |
| The build itself fails (I/O error, disk full) | `status().state == "error"`; `ensure_index()` raises `NavdataIndexError`. |

```python
class NavdataUnavailable(RuntimeError):
    """Raised when a query is made against a provider that has no usable data.

    **The UI is expected to gate on `status()`, not to catch this.** Seeing it
    means a caller ignored the status — a bug in the caller, exactly as
    `CapabilityNotSupported` is.
    """
```

The "skip the record, never fail the build" rule matters: real navdata always contains a handful
of malformed rows, and an instructor station that refuses to start because one airport in Chad has
a bad runway row is useless.

---

## 5. The models

### 5.0 Where each model lives, and the one rule that keeps it acyclic

**D13 — `core/navdata/models.py` imports from `core/models.py`. Never the reverse.** One
direction, stated once, checked by `test_core_boundaries.py` (§11.6).

That rule decides the split, and it is not a matter of taste: `Runway` stays in `core/models.py`
(D4 — `core/geodesy.py` consumes it), and §5.3 gives `Runway` an `ils: Ils | None` field. If `Ils`
lived in `core/navdata/models.py`, then `core/models.py` would import it from there while
`core/navdata/models.py` imports `GeoPosition` from `core/models.py` — **a guaranteed circular
import**, resolvable only with `TYPE_CHECKING` guards and `model_rebuild()` calls that every
future contributor would have to remember.

So:

| Module | Holds | Why |
|---|---|---|
| `core/models.py` | `GeoPosition`, `AircraftState`, `AircraftSetup`, `LightsSetup`, **`Runway`**, **`Ils`**, **`RunwaySurface`** | the shared vocabulary — anything referenced by a model on the sim side of the seam |
| `core/navdata/models.py` | `Airport`, `AirportSummary`, `Waypoint`, `Navaid`, `Fix`, `Hold`, `ParkingStand`, `Procedure`, `ProcedureLeg`, `ProcedureSummary`, `FixRef`, `AltitudeConstraint`, `SpeedConstraint`, `NavdataStatus`, `IndexProgress` | navdata-only vocabulary, nothing on the sim side refers to it |

`Ils` belongs in `core/models.py` on its merits anyway, not merely to dodge a cycle: its fields
feed `AircraftSetup` directly (`frequency_khz` → `ils_freq_khz`, `localizer_mag_deg` →
`obs1_deg`, §5.5), which makes it exactly as shared as `Runway` is. `RunwaySurface` follows
`Runway` for the same reason — it is a field of it.

Units follow the existing convention: **the unit is in the field name and is never ambiguous.**

### 5.1 Units and reference frames

| Quantity | Unit | Suffix |
|---|---|---|
| Navigational distance | nautical miles | `_nm` |
| Pavement / physical dimension | metres | `_m` |
| Altitude, elevation | feet MSL | `_ft` |
| Speed | knots indicated | `_kt` |
| Radio frequency | kilohertz (integer) | `_khz` |
| Direction, **true** | degrees `[0, 360)` | `_true_deg` |
| Direction, **magnetic** | degrees `[0, 360)` | `_mag_deg` |
| Angle (glideslope, vertical path) | degrees | `_deg` |

**D11 — there is no bare directional `_deg` field in any navdata model.** Magnetic-versus-true is
the single most common source of silently-wrong navigation values, and CIFP courses are magnetic
while `core/models.py` and `core/geodesy.py` are true throughout.

**The provider never converts between the two.** Converting requires a world magnetic model (WMM);
`geographiclib` has none and adding one contradicts the "keep the PyInstaller bundle small"
constraint in `CLAUDE.md`. Instead:

- Where the source gives both, both are carried (ILS: `earth_nav.dat` encodes true bearing **and**
  magnetic front course in one field — §6.6).
- Where the source gives one, it is carried in its own frame with the correct suffix.
- Where a true bearing is needed and the source has none, it is **computed geodesically** from
  coordinates: `Runway.true_bearing_deg` comes from the geodesic between the two runway-end
  coordinates in `apt.dat`, not from any published course. This is already what
  `core.geodesy.final_approach_point` consumes, and it is exact.

Verified consistency: at LEMD, the bearing computed from the 18L end to the 36R end in `apt.dat` is
**179.75°**, and `earth_nav.dat` publishes the 18L localizer true bearing as **179.763°** — two
independent sources agreeing to better than a fiftieth of a degree.

> **Follow-up for whoever owns `core/models.py`:** `AircraftSetup.obs1_deg` / `obs2_deg` are
> documented as "OBS course in degrees" without a frame. An OBS course is **magnetic**. This is a
> one-line docstring clarification, not a model change, and is out of scope for this document.

### 5.2 `Waypoint` — the common anchor

Everything positionable is a `Waypoint`. Procedure legs point at one; `resolve_fix` returns one.

```python
WaypointKind = Literal["fix", "vor", "ndb", "dme", "tacan", "localizer", "runway", "airport", "gls"]


class Waypoint(BaseModel, frozen=True):
    ident: str
    kind: WaypointKind
    position: GeoPosition
    region_code: str | None = None  # ICAO region, e.g. "LE"
    airport_icao: str | None = None  # set for terminal-scoped waypoints
    name: str | None = None
```

### 5.3 `Runway` — **reused, extended additively**

`core/models.py` already defines `Runway`, and `core/geodesy.py` consumes it in
`final_approach_point()` and `traffic_pattern_point()` — validated code with tests.

**Decision (D4): reuse it. Do not change a single existing field.** The additions are optional with
defaults, so:

- `tests/core/test_geodesy.py` constructs `Runway` with the current fields and keeps passing.
- `final_approach_point` and `traffic_pattern_point` read only `threshold`, `true_bearing_deg`,
  `length_m` and `elevation_ft` — untouched.
- `frozen=True` is preserved; the nested `Ils` is frozen too, so `Runway` stays hashable.

**Nothing breaks. There is no migration and no coordinated change.**

**Read the current `core/models.py` before touching this — part of what this section once
proposed has already landed.** Issue #49 pinned the threshold semantics and shipped
`pavement_end`, `displaced_threshold_m` and `landing_distance_m`, with validation constraints and
docstrings richer than anything reproduced here. Those three are now **existing fields**; treating
them as additions risks re-declaring them or, worse, dropping the `ge=0.0` / `gt=0.0` bounds that
are already enforced. The block below is annotated accordingly, and `core/models.py` — not this
document — is the authority on the exact `Field(...)` arguments:

```python
class Runway(BaseModel, frozen=True):
    # --- existing, unchanged ------------------------------------------------
    airport_icao: str = Field(min_length=2, max_length=7)
    ident: str = Field(min_length=1, max_length=3)  # "18L" — never "RW18L"
    threshold: GeoPosition  # the LANDING threshold (displaced) — see below
    true_bearing_deg: float = Field(ge=0.0, le=360.0)  # geodesic, computed
    length_m: float = Field(gt=0.0)
    elevation_ft: float

    # --- existing since #49: threshold-vs-pavement geometry -----------------
    pavement_end: GeoPosition | None = None  # undisplaced start of pavement
    displaced_threshold_m: float = Field(default=0.0, ge=0.0)
    landing_distance_m: float | None = Field(default=None, gt=0.0)

    # --- added by this design, all optional with defaults -------------------
    opposite_ident: str | None = None  # "36R"
    width_m: float | None = None
    surface: RunwaySurface | None = None  # asphalt|concrete|grass|gravel|water|snow|…
    threshold_crossing_height_ft: float | None = None
    ils: Ils | None = None  # populated by the provider — see below
```

**Semantics pinned down (these were ambiguous and are now not — and #49 wrote them into the
model's own docstring, which is where a reader will find them):**

- **`threshold` is the displaced landing threshold** — the point an aircraft on final aims at, and
  therefore the correct origin for `final_approach_point()`. At LEMD 18L the pavement starts
  494 m before it; a 10 NM final anchored on the wrong point is 0.27 NM off before any other error.
  A source that only knows the pavement end **walks it forward along the runway axis** by
  `displaced_threshold_m`; it never assigns the pavement end to `threshold`.
- **`length_m` is the pavement length** between the two `100`-row end coordinates in `apt.dat`
  (3497.5 m at LEMD 18L/36R), which is what `traffic_pattern_point()` wants for pattern geometry.
  Landing distance available is the separate `landing_distance_m`.
- **`elevation_ft` is the threshold elevation**, from CIFP `RWY:` when the airport has a CIFP file,
  falling back to the airport elevation from `apt.dat`.

**Why `ils` rides on `Runway`.** The single most important placement in the product is "10 NM ILS
final", and it needs threshold, bearing, elevation, ILS frequency and OBS course together. Making
that one lookup instead of two removes a step where a caller can forget the ILS and silently place
an aircraft on an untuned approach. The join is a single `LEFT JOIN` on an indexed column over a
handful of rows. `get_ils()` remains public for callers that want only the ILS.

### 5.4 `Airport`

```python
class Airport(BaseModel, frozen=True):
    icao: str
    iata: str | None = None
    name: str
    city: str | None = None
    country: str | None = None
    region_code: str | None = None
    position: GeoPosition  # airport reference point / datum
    elevation_ft: float
    transition_altitude_ft: int | None = None  # apt.dat 1302 transition_alt
    transition_level_ft: int | None = None
    magnetic_variation_deg: float | None = None
    has_tower: bool = False
    runway_count: int = 0
    longest_runway_m: float | None = None
    has_procedures: bool = False  # a CIFP/<ICAO>.dat file exists


class AirportSummary(BaseModel, frozen=True):
    icao: str
    iata: str | None = None
    name: str
    position: GeoPosition
    elevation_ft: float
    longest_runway_m: float | None = None
    has_procedures: bool = False
```

`has_procedures` is set at index time from the **existence** of a CIFP file — a directory listing,
not a parse. It lets the UI grey out the SID/STAR/approach tabs before any lazy load happens.

`transition_altitude_ft` feeds directly into procedure display and into the pre-teleport setup.

### 5.5 `Navaid` and `Ils`

```python
NavaidKind = Literal[
    "vor", "vor_dme", "vortac", "dme", "ndb", "tacan", "localizer", "glideslope", "gls"
]

#: Which radio a navaid is tuned on, or None when it is not tunable at all.
TunableRadio = Literal["nav", "adf"]


class Navaid(BaseModel, frozen=True):
    ident: str
    kind: NavaidKind
    name: str | None = None
    position: GeoPosition
    frequency_khz: int | None = None  # VHF: same unit as AircraftSetup.nav1_freq_khz
    channel: str | None = None  # TACAN channel, e.g. "112X"
    range_nm: float | None = None
    magnetic_variation_deg: float | None = None
    region_code: str | None = None
    airport_icao: str | None = None  # terminal navaids only
    runway_ident: str | None = None  # localizers / glideslopes
    tunable_radio: TunableRadio | None = "nav"  # None for GS, GLS, markers


class Ils(BaseModel, frozen=True):
    airport_icao: str
    runway_ident: str
    localizer_ident: str  # "IML"
    frequency_khz: int  # 108_000 … 111_950
    localizer_position: GeoPosition
    localizer_true_deg: float  # 179.763
    localizer_mag_deg: float  # 180.0  → feeds AircraftSetup.obs1_deg
    localizer_width_deg: float | None = None
    glideslope_deg: float | None = None  # 3.00 → feeds core.geodesy.glideslope_altitude_ft
    glideslope_position: GeoPosition | None = None
    category: Literal["I", "II", "III"] | None = None  # from CIFP RWY:, unrecognised → None
    has_dme: bool = False
```

**`Navaid.frequency_khz` is deliberately in the same unit as `AircraftSetup.nav1_freq_khz`
(108 000–117 950 kHz).** `earth_nav.dat` stores VHF frequencies in units of 10 kHz (`11630` =
116.30 MHz) and NDB frequencies in kHz directly (`380`). **Both conversions happen in the
provider**, so the Position Manager assigns `setup.nav1_freq_khz = navaid.frequency_khz` with no
arithmetic and no chance of a factor-of-ten error reaching the radios.

**`tunable_radio`, not a `usable_for_nav_radio: bool` — because an NDB is not a NAV radio.** A
boolean collapses three genuinely different cases into two. A VOR goes in NAV1; a **glideslope**
or marker is not tunable by the instructor at all; and an **NDB goes in the ADF**, whose band is
190–1750 kHz. That last one is the trap: `AircraftSetup` has no `adf_freq_khz` field today, and
an NDB's 380 kHz would fail `nav1_freq_khz`'s own `ge=108_000` validation, so a caller trusting
`usable_for_nav_radio == True` on an NDB gets a `ValidationError` at placement time. A three-state
field makes the correct destination readable off the model — `"nav"` → `nav1`/`nav2`/`ils`,
`"adf"` → the ADF once `AircraftSetup` gains it, `None` → not offered — and closes the seam
before the ADF field exists rather than after the first bug report.

| Kind | `tunable_radio` |
|---|---|
| `vor`, `vor_dme`, `vortac`, `dme`, `tacan`, `localizer` | `"nav"` |
| `ndb` | `"adf"` |
| `glideslope`, `gls` | `None` |

> **Follow-up for whoever owns `core/models.py`:** adding `adf_freq_khz: int | None`
> (`ge=190, le=1750`) to `AircraftSetup` is what makes an NDB placement tunable end to end. It is
> a pure addition behind an unchanged interface and is out of scope for this document.

Likewise `Ils.glideslope_deg` feeds `core.geodesy.glideslope_altitude_ft()` directly, and
`Ils.localizer_mag_deg` feeds `AircraftSetup.obs1_deg` directly. Every unit seam in the Phase 1
placement pipeline is closed here rather than at each call site.

### 5.6 `ParkingStand`

```python
ParkingKind = Literal["gate", "hangar", "tie_down", "misc"]
ParkingOperation = Literal["none", "general_aviation", "airline", "cargo", "military"]


class ParkingStand(BaseModel, frozen=True):
    airport_icao: str
    name: str  # "La Munoza", "R32"
    position: GeoPosition  # altitude_ft = airport elevation
    heading_true_deg: float  # heading of the parked aircraft
    kind: ParkingKind
    aircraft_types: tuple[str, ...] = ()  # "heavy"|"jets"|"turboprops"|"props"|"helos"
    operation: ParkingOperation | None = None
    airline_codes: tuple[str, ...] = ()  # ("ibe", "baw", …)
```

**One model, not two.** The feature spec lists "gate" and "parking stand" as separate placements,
but `apt.dat` has one record type (`1300`) with a `kind` field. Splitting them into two Python
models would invent a distinction the data does not make; the UI filters on `kind` and
`operation`. `apt.dat` carries no per-stand elevation, so `position.altitude_ft` is the airport
elevation — harmless, because a stand placement puts the aircraft on the ground anyway.

### 5.7 `Procedure` and `ProcedureLeg`

```python
ProcedureKind = Literal["sid", "star", "approach"]
ApproachType = Literal[
    "ils",
    "loc",
    "rnav",
    "gps",
    "vor",
    "vor_dme",
    "ndb",
    "ndb_dme",
    "lda",
    "sdf",
    "gls",
    "mls",
    "igs",
    "unknown",
]


class ProcedureSummary(BaseModel, frozen=True):
    airport_icao: str
    kind: ProcedureKind
    ident: str  # "BARD3B", "I18LY"
    transition: str | None  # "RW14R", "ADUXO", None
    runway_idents: tuple[str, ...]  # ("32L", "32R") — RW32B expanded
    approach_type: ApproachType | None  # approaches only
    leg_count: int
    positionable_leg_count: int


class Procedure(BaseModel, frozen=True):
    airport_icao: str
    kind: ProcedureKind
    ident: str
    transition: str | None
    runway_idents: tuple[str, ...]
    approach_type: ApproachType | None = None
    legs: tuple[ProcedureLeg, ...]
```

**Runway-transition expansion, which is a real trap.** A CIFP transition ident is not always a
runway: it may be a named transition (`ADUXO`), a runway (`RW14R`), `ALL`, or a **parallel group**
ending in `B` (`RW32B`, `RW14B`) meaning "both parallels". `runway_idents` is the expanded, real
list, resolved against the airport's actual runways at parse time:

| Transition | `runway_idents` |
|---|---|
| `RW14R` | `("14R",)` |
| `RW32B` | `("32L", "32R")` — every `32*` runway the airport actually has |
| `RW18` | `("18",)`, or every `18*` runway if no bare `18` exists |
| `ALL` or blank | every runway of the airport |
| `ADUXO` (a named transition) | `()` — and `transition` carries the name |

Expanding against the airport's real runway list, rather than assuming `L`/`R`, is what makes
`RW32B` correct at an airport with `32L`/`32C`/`32R`.

The recognised path terminators fall into three groups, and the first group is the one the whole
Position Manager turns on:

```python
#: Legs that carry a resolvable fix — the ONLY ones offered as a placement.
#: (CLAUDE.md; architecture.md, risk 4.)
POSITIONABLE_TERMINATORS: frozenset[str] = frozenset({"IF", "TF", "CF", "DF", "AF", "RF"})

#: Trajectory-dependent legs: no defensible coordinate without the flown path.
#: Displayed, never offered.
TRAJECTORY_TERMINATORS: frozenset[str] = frozenset(
    {"CA", "VA", "FM", "VM", "CD", "CI", "CR", "VD", "VI", "VR", "FA", "FC", "FD"}
)

#: Holds and procedure turns. Displayed, never offered.
MANOEUVRE_TERMINATORS: frozenset[str] = frozenset({"HA", "HF", "HM", "PI"})

PathTerminator = Literal[  # the union of the three sets above
    "IF", "TF", "CF", "DF", "AF", "RF",
    "CA", "VA", "FM", "VM", "CD", "CI", "CR", "VD", "VI", "VR", "FA", "FC", "FD",
    "HA", "HF", "HM", "PI",
]  # fmt: skip


class ProcedureLeg(BaseModel, frozen=True):
    sequence: int  # 10, 20, 30 … from the CIFP record
    path_terminator: PathTerminator

    # --- Positionability — the whole point --------------------------------
    is_positionable: bool
    unpositionable_reason: str | None  # set iff is_positionable is False

    # --- The fix ----------------------------------------------------------
    fix_ref: FixRef | None  # the raw 4-part ARINC key, always kept
    fix: Waypoint | None  # resolved; None if unresolvable

    # --- Geometry ---------------------------------------------------------
    recommended_navaid: Waypoint | None = None
    theta_mag_deg: float | None = None  # bearing FROM the recommended navaid
    rho_nm: float | None = None  # distance FROM the recommended navaid
    arc_radius_nm: float | None = None  # RF legs
    outbound_course_mag_deg: float | None = None
    distance_nm: float | None = None
    time_min: float | None = None  # holding legs use time, not distance
    turn_direction: Literal["L", "R"] | None = None
    vertical_angle_deg: float | None = None

    # --- Constraints, straight from the leg data --------------------------
    altitude: AltitudeConstraint | None = None
    speed: SpeedConstraint | None = None
    transition_altitude_ft: int | None = None

    # --- Role flags, decoded from the 4-char description code -------------
    is_flyover: bool = False
    is_initial_approach_fix: bool = False
    is_final_approach_fix: bool = False
    is_missed_approach_point: bool = False
    is_missed_approach_leg: bool = False
    is_end_of_procedure: bool = False

    raw: str | None = None  # the source line, for diagnostics only
```

**`is_positionable` is computed by the provider, never by the UI** (`architecture.md`, risk 4):

```python
is_positionable = path_terminator in POSITIONABLE_TERMINATORS and fix is not None
```

**Both conditions.** A `CA` leg is not positionable because there is no defensible coordinate for
it without the flown path. An `IF` leg whose fix cannot be resolved is *also* not positionable,
and confusing the two would be a silent bug. `unpositionable_reason` distinguishes them in words
the UI shows verbatim:

- `"trajectory-dependent leg (CA): no coordinate without the flown path"`
- `"fix MD800/LE not found in the index"`

Unpositionable legs are **returned and displayed** — an instructor reading a SID needs to see the
`CA` climb — they are simply not offered as placements.

**`fix_ref` is kept even when `fix` is `None`.** It is what makes an unresolved fix diagnosable
instead of merely absent, and it is what a future re-resolution pass would use.

### 5.8 `FixRef` — the ARINC 4-part key

The single non-obvious thing in the whole CIFP format. A leg names its fix with **four** fields,
not one, because idents are not unique and terminal fixes are scoped to an airport:

```python
class FixRef(BaseModel, frozen=True):
    ident: str  # "MD800", "NVS", "GOXOL"
    region_code: str  # "LE"
    section: str  # "D" | "E" | "P" | "PN"  (ARINC 424 section)
    subsection: str  # "C" | "A" | "I" | "G" | ""
    airport_icao: str | None  # the CIFP file's airport, for terminal scoping
```

Resolution table used by `resolve_fix()` — verified against real records:

| Section | Sub | Meaning | Resolved against |
|---|---|---|---|
| `D` | *(blank)* | VHF navaid (VOR/DME/TACAN) | `navaid` where kind ∈ {vor, vor_dme, vortac, dme, tacan} |
| `D` | `B` | NDB (enroute) | `navaid` where kind = ndb |
| `E` | `A` | Enroute waypoint | `fix` where `terminal_airport_icao IS NULL` |
| `P` | `C` | **Terminal** waypoint | `fix` where `terminal_airport_icao = <the CIFP file's airport>` |
| `P` | `A` | Airport reference point | `airport` |
| `P` | `G` | Runway threshold | `runway` of that airport |
| `P` | `I` | Localizer / ILS | `navaid` where kind = localizer |
| `P` | `N` | Terminal NDB | `navaid` where kind = ndb, scoped to the airport |

Matching is on `(ident, region_code)` plus the terminal scope. If more than one row still matches,
the nearest to the airport reference point wins, and the ambiguity is counted in the build stats.

**This table is why `earth_fix.dat` must be indexed with its terminal-airport column.** Row 3 of
`earth_fix.dat` is either the literal `ENRT` (enroute) or an airport ICAO (terminal). Collapsing
that column would make every `P/C` leg unresolvable — roughly half the legs of a typical SID.

### 5.9 Constraints

Constraints ride on the leg data, exactly as `CLAUDE.md` states, and feed the pre-teleport setup
with no second source and no guessing.

```python
class AltitudeConstraint(BaseModel, frozen=True):
    descriptor: str  # raw ARINC char: "+", "-", "B", "J", "V", …
    min_ft: float | None = None  # at-or-above bound
    max_ft: float | None = None  # at-or-below bound
    min_is_flight_level: bool = False  # so the UI can render "FL140" back
    max_is_flight_level: bool = False

    @property
    def suggested_ft(self) -> float | None: ...

    @property
    def display(self) -> str: ...  # "FL140A / 10000B", "at or above 6300", "at 5500"


class SpeedConstraint(BaseModel, frozen=True):
    descriptor: str  # "+", "-", or blank
    min_kt: float | None = None
    max_kt: float | None = None

    @property
    def suggested_kt(self) -> float | None: ...
```

**Normalisation, with the verified source forms:**

| Source | Meaning | Model |
|---|---|---|
| `+,02400` | at or above 2400 ft | `min_ft=2400, max_ft=None` |
| `-,05000` | at or below 5000 ft | `min_ft=None, max_ft=5000` |
| `B,FL140,10000` | between FL140 and 10000 | `min_ft=10000, max_ft=14000, max_is_flight_level=True` |
| `J,05500,05500` | at 5500 (glideslope intercept) | `min_ft=5500, max_ft=5500` |
| `-,210` (speed) | at or below 210 kt | `max_kt=210` |

Flight levels are normalised to feet (`FL245` → 24500) with a flag so the UI renders the published
form. Storing them as a string would push the conversion into every consumer.

**`suggested_ft` — the rule the Position Manager uses, defined once here:**

- `min_ft == max_ft` → that value ("at").
- only `min_ft` → `min_ft`.
- only `max_ft` → `max_ft`.
- a band → **`min_ft`**, the lower bound. An aircraft on a STAR enters a band from above and the
  crew targets the bottom of it; placing at the top of a `B,FL140,10000` window puts the aircraft
  4000 ft high on a descent profile it then cannot fly.

`suggested_kt` is the constraining bound (`max_kt` for `-`, `min_kt` for `+`).

Putting these on the model rather than in the Position Manager means the rule is stated once,
tested once, and identical in the UI preview and in the actual placement.

### 5.10 `Fix` and `Hold`

```python
class Fix(BaseModel, frozen=True):
    ident: str
    position: GeoPosition
    region_code: str | None = None
    terminal_airport_icao: str | None = None  # None == enroute (ENRT)
    name: str | None = None


class Hold(BaseModel, frozen=True):
    fix: Waypoint
    inbound_course_mag_deg: float
    turn_direction: Literal["L", "R"]
    leg_time_min: float | None = None  # exactly one of time/length is set
    leg_length_nm: float | None = None
    min_altitude_ft: float | None = None
    max_altitude_ft: float | None = None
    speed_kt: float | None = None
    airport_icao: str | None = None  # None == enroute
```

**`inbound_course_mag_deg` is magnetic — verified, not assumed.** Cross-checking
`earth_hold.dat` against the `HM` legs of the same fixes in CIFP (which are magnetic by ARINC
definition) gives exact agreement: KJFK `242.0` vs CIFP `2420`, KSEA `341.0` vs CIFP `3410`. KJFK
has ~13°W variation, so identical values across two independent files can only mean both are
magnetic.

**Two sources of holds, deliberately not merged.** `earth_hold.dat` gives *published* enroute and
terminal holds and is reached through `get_holds()`. CIFP `HM`/`HA`/`HF` legs give holds that are
*part of a procedure* and are reached through `get_procedure()`. They overlap but are not the same
set, and silently unioning them would produce duplicate holds at fixes that appear in both, with
no way for the UI to say which chart the instructor is looking at.

---

## 6. The SQLite schema

One file: `core/navdata/schema.py`, holding the DDL and `SCHEMA_VERSION`. **`CLAUDE.md` forbids
parallelising navdata schema changes** — this file has exactly one owner (the #5 indexer track)
and is never edited concurrently.

### 6.1 Design rules

1. **No optional SQLite modules.** No FTS5, no R\*Tree, no JSON1, no extensions. CI runs four
   Python × OS combinations and the modules compiled into CPython's bundled SQLite vary. Plain
   tables and B-tree indexes work everywhere.
2. **The database is derived and disposable.** It is never migrated, never repaired, never
   hand-edited. Any key mismatch deletes and rebuilds it (§8).
3. **Every index exists because a query in §6.3–6.5 needs it.** No speculative indexes: this file
   is written once per AIRAC cycle and the write cost is the user's first impression.
4. **Denormalised where it removes a join from a hot path.** Runway rows carry their airport's
   ICAO, not a surrogate key.

### 6.2 DDL

```sql
PRAGMA user_version = <SCHEMA_VERSION>;   -- integer; bumping it IS the migration

-- ---------------------------------------------------------------- metadata
CREATE TABLE meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
-- keys: schema_version, airac_cycle, cycle_valid_from, cycle_valid_to,
--       source_root, built_at, build_duration_s, skipped_record_count

CREATE TABLE source_file (
    role       TEXT PRIMARY KEY,   -- 'apt', 'earth_fix', 'earth_nav', 'earth_hold', 'cycle_info'
    path       TEXT NOT NULL,      -- resolved after precedence (§9)
    size_bytes INTEGER NOT NULL,
    mtime_ns   INTEGER NOT NULL
);

-- ---------------------------------------------------------------- airports
CREATE TABLE airport (
    icao                   TEXT PRIMARY KEY,
    iata                   TEXT,
    name                   TEXT NOT NULL,
    name_norm              TEXT NOT NULL,   -- casefolded, accent-stripped
    city                   TEXT,
    country                TEXT,
    region_code            TEXT,
    latitude               REAL NOT NULL,
    longitude              REAL NOT NULL,
    elevation_ft           REAL NOT NULL,
    transition_altitude_ft INTEGER,
    transition_level_ft    INTEGER,
    magnetic_variation_deg REAL,
    has_tower              INTEGER NOT NULL DEFAULT 0,
    runway_count           INTEGER NOT NULL DEFAULT 0,
    longest_runway_m       REAL,
    has_procedures         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX ix_airport_iata      ON airport(iata)      WHERE iata IS NOT NULL;
CREATE INDEX ix_airport_name_norm ON airport(name_norm);
CREATE INDEX ix_airport_pos       ON airport(latitude, longitude);

-- ---------------------------------------------------------------- runways
CREATE TABLE runway (
    id                     INTEGER PRIMARY KEY,
    airport_icao           TEXT NOT NULL,
    ident                  TEXT NOT NULL,   -- "18L"
    opposite_ident         TEXT,
    threshold_lat          REAL NOT NULL,   -- displaced landing threshold
    threshold_lon          REAL NOT NULL,
    end_lat                REAL NOT NULL,   -- undisplaced pavement end
    end_lon                REAL NOT NULL,
    true_bearing_deg       REAL NOT NULL,   -- geodesic, computed at index time
    length_m               REAL NOT NULL,
    displaced_threshold_m  REAL NOT NULL DEFAULT 0,
    width_m                REAL,
    surface                TEXT,
    elevation_ft           REAL NOT NULL,
    UNIQUE (airport_icao, ident)
);
CREATE INDEX ix_runway_airport ON runway(airport_icao);

-- ---------------------------------------------------------------- parking
CREATE TABLE parking (
    id               INTEGER PRIMARY KEY,
    airport_icao     TEXT NOT NULL,
    name             TEXT NOT NULL,
    latitude         REAL NOT NULL,
    longitude        REAL NOT NULL,
    heading_true_deg REAL NOT NULL,
    kind             TEXT NOT NULL,     -- gate|hangar|tie_down|misc
    aircraft_types   TEXT,              -- '|'-joined, as in apt.dat
    operation        TEXT,
    airline_codes    TEXT               -- space-joined, as in apt.dat
);
CREATE INDEX ix_parking_airport      ON parking(airport_icao);
CREATE INDEX ix_parking_airport_kind ON parking(airport_icao, kind);

-- ---------------------------------------------------------------- navaids
CREATE TABLE navaid (
    id                     INTEGER PRIMARY KEY,
    ident                  TEXT NOT NULL,
    kind                   TEXT NOT NULL,
    name                   TEXT,
    latitude               REAL NOT NULL,
    longitude              REAL NOT NULL,
    elevation_ft           REAL,
    frequency_khz          INTEGER,       -- already normalised (§5.5)
    channel                TEXT,
    range_nm               REAL,
    true_deg               REAL,          -- localizer true bearing
    mag_deg                REAL,          -- localizer magnetic front course
    glideslope_deg         REAL,          -- glideslope rows only
    magnetic_variation_deg REAL,
    region_code            TEXT,
    airport_icao           TEXT,
    runway_ident           TEXT,
    ils_category           TEXT
);
CREATE INDEX ix_navaid_ident        ON navaid(ident);
CREATE INDEX ix_navaid_ident_region ON navaid(ident, region_code);
CREATE INDEX ix_navaid_pos          ON navaid(latitude, longitude);
CREATE INDEX ix_navaid_runway       ON navaid(airport_icao, runway_ident)
                                    WHERE airport_icao IS NOT NULL;

-- ---------------------------------------------------------------- fixes
CREATE TABLE fix (
    id                    INTEGER PRIMARY KEY,
    ident                 TEXT NOT NULL,
    latitude              REAL NOT NULL,
    longitude             REAL NOT NULL,
    region_code           TEXT,
    terminal_airport_icao TEXT,        -- NULL == ENRT
    name                  TEXT
);
CREATE INDEX ix_fix_ident          ON fix(ident);
CREATE INDEX ix_fix_ident_region   ON fix(ident, region_code);
CREATE INDEX ix_fix_terminal       ON fix(terminal_airport_icao, ident)
                                   WHERE terminal_airport_icao IS NOT NULL;
CREATE INDEX ix_fix_pos            ON fix(latitude, longitude);

-- ---------------------------------------------------------------- holds
CREATE TABLE hold (
    id                     INTEGER PRIMARY KEY,
    fix_ident              TEXT NOT NULL,
    region_code            TEXT,
    airport_icao           TEXT,       -- NULL == ENRT
    fix_type               INTEGER,    -- 11 fix, 3 VOR, 2 NDB (same enum as earth_awy)
    inbound_course_mag_deg REAL NOT NULL,
    leg_time_min           REAL,
    leg_length_nm          REAL,
    turn_direction         TEXT NOT NULL,
    min_altitude_ft        REAL,
    max_altitude_ft        REAL,
    speed_kt               REAL
);
CREATE INDEX ix_hold_fix     ON hold(fix_ident, region_code);
CREATE INDEX ix_hold_airport ON hold(airport_icao) WHERE airport_icao IS NOT NULL;
```

**`earth_awy.dat` (airways) and `earth_msa.dat` (minimum sector altitudes) are indexed in a later
phase.** Nothing in Phase 1 queries them: airways belong to the Flight Plan helper (Phase 4) and
MSAs to the map (Phase 3). Parsing them now would add ~125 k rows and build time for zero Phase 1
value. Adding them later is a `SCHEMA_VERSION` bump and a rebuild, which costs the user one
progress bar — cheap by construction (§8).

### 6.3 The queries the UI actually makes

**Airport type-ahead** (`search_airports`) — the single hottest query, fired on every keystroke:

```sql
SELECT icao, iata, name, latitude, longitude, elevation_ft, longest_runway_m, has_procedures,
       CASE
           WHEN icao      =  :q      THEN 0
           WHEN icao   LIKE :q||'%'  THEN 1
           WHEN iata      =  :q      THEN 2
           WHEN name_norm LIKE :q||'%' THEN 3
           ELSE 4
       END AS rank
FROM airport
WHERE icao LIKE :q||'%' OR iata = :q OR name_norm LIKE '%'||:q||'%'
ORDER BY rank, longest_runway_m DESC NULLS LAST, icao
LIMIT :limit;
```

**This query is a full scan of the `airport` table, and that is fine — but do not let anyone
"optimise" it on a false premise.** It is tempting to claim `icao LIKE :q||'%'` rides the primary
key index. It does not, for two independent reasons: SQLite's LIKE optimisation requires the
pattern to be a literal or a bare bound parameter, and `:q||'%'` is a **concatenation
expression**, which disqualifies it outright; and the `OR name_norm LIKE '%'||:q||'%'` disjunct
has a leading wildcard, so no index could serve the `WHERE` clause as a whole regardless.

The honest justification is the measurement: 31 269 rows, scanned in **well under a millisecond**,
bounded by `LIMIT`, on a table that fits comfortably in the OS page cache after the first query.
A keystroke budget is ~16 ms; this uses a few percent of it. `ix_airport_name_norm` is kept
because it serves exact and prefix lookups elsewhere, not because it serves this scan.

If a future profile ever shows this query mattering — it will not at 31 k rows — the fix is
range predicates (`icao >= :q AND icao < :q || char(0x10FFFF)`) in a separate `UNION ALL` branch,
not FTS5 (§6.4). Ordering by `longest_runway_m DESC` puts LEMD above a Madrid airstrip, which is
what an instructor typing "madrid" wants.

**Runways for an airport:**

```sql
SELECT r.*, n.ident AS loc_ident, n.frequency_khz, n.true_deg, n.mag_deg,
       n.latitude AS loc_lat, n.longitude AS loc_lon, n.ils_category,
       g.glideslope_deg, g.latitude AS gs_lat, g.longitude AS gs_lon
FROM runway r
LEFT JOIN navaid n ON n.airport_icao = r.airport_icao
                  AND n.runway_ident = r.ident AND n.kind = 'localizer'
LEFT JOIN navaid g ON g.airport_icao = r.airport_icao
                  AND g.runway_ident = r.ident AND g.kind = 'glideslope'
WHERE r.airport_icao = :icao
ORDER BY r.ident;
```

Both joins hit `ix_navaid_runway`; `ix_runway_airport` drives the outer scan. This is the query
that makes `Runway.ils` free (§5.3).

### 6.4 Spatial queries without a spatial index

**D9: bounding-box prefilter on the composite `(latitude, longitude)` index, then an exact
geodesic refine in Python.**

```sql
SELECT * FROM navaid
WHERE latitude BETWEEN :lat_min AND :lat_max
  AND longitude BETWEEN :lon_min AND :lon_max
  AND (:kinds IS NULL OR kind IN (…));
```

then `core.geodesy.distance_and_bearing()` on each candidate, discard beyond `radius_nm`, sort by
distance, truncate to `limit`.

Box half-widths: `dlat = radius_nm / 60`, `dlon = radius_nm / (60 * cos(lat))`, clamped.
Antimeridian crossings split into two range predicates; above 85° latitude the longitude filter is
dropped entirely and the latitude band alone prefilters. A 50 NM box holds a few hundred navaids,
so the Python refine is trivial.

**Why not R\*Tree.** It would be faster in principle, but it is an optional SQLite compile-time
module. Depending on it means depending on how CPython was built on four CI targets *and* on
whatever Python the PyInstaller bundle ships. The measured cost of not having it is negligible;
the cost of a Windows-only "no such module: rtree" is a broken build. Same argument retires FTS5
in favour of `name_norm`.

### 6.5 Journal mode and connection settings

**Build-time:** `PRAGMA journal_mode = OFF`, `synchronous = OFF`, `page_size = 8192`, one
transaction per table, `executemany` in batches of 10 000. The file is disposable, so durability
guarantees during the build buy nothing and cost most of the build time. `ANALYZE` runs at the
end, before the atomic publish.

**D14 — the finished file is `journal_mode = DELETE`, and readers open it
`mode=ro&immutable=1`. It is never WAL.** This reverses an earlier "WAL at the end" note, and the
reversal is the point:

- **WAL solves a problem this file does not have.** WAL exists so readers do not block a
  concurrent *writer*. This database is written exactly once, by one thread, before anyone can
  open it, and is never written again — D-rule 2 of §6.1 in one sentence. There is no concurrency
  for WAL to buy anything back from.
- **WAL costs correctness at publication time.** A WAL database is *three* files — `.sqlite`,
  `-wal`, `-shm`. The atomic publish is a single `os.replace()`, which moves **one** of them. A
  build that ends in WAL without a full checkpoint and a clean close publishes a main file whose
  committed content is partly sitting in a sibling `-wal` that was left behind under the `.tmp`
  name. That is a corrupt or stale cache produced by an operation the design calls atomic.
- **WAL costs robustness at read time.** Opening a WAL database read-only requires SQLite to
  read — and in some paths create — the `-shm` file, so it depends on write permission in the
  cache directory and on the platform's shared-memory VFS. On a locked-down or network-mounted
  cache directory that fails, and it fails as "unable to open database file" on a file that is
  plainly there.

`journal_mode = DELETE` leaves **one self-contained file**, which is exactly what `os.replace()`
can move atomically. `immutable=1` then tells SQLite the file cannot change underneath it, which
skips all locking and `-shm` handling entirely: no lock files, no write permission needed, and
slightly faster reads. `immutable=1` is a *promise*, and §8.4 (D15) is what makes the promise
true — a published generation is never rewritten and never replaced in place.

**Read-side:** `sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)`, plus
`PRAGMA query_only = 1` as a second belt, one connection per thread (§3), reopened on an epoch
bump (§8.4).

### 6.6 Verified decoding rules

These cost hours to rediscover and are recorded once, here. Every one was checked against real
records.

**`RWY:` threshold coordinates are packed DDMMSSss.** `N40294171` = 40° 29' 41.71" = 40.4949194.
Latitude is `[NS]DDMMSSss` (9 chars), longitude `[EW]DDDMMSSss` (10 chars). The last two digits are
**hundredths of a second**, not thousandths.

**`RWY:` gives the *displaced* threshold; `apt.dat` gives the pavement end.** Verified at LEMD 18L:
`apt.dat` end `40.5325838, -3.5593800` with `displaced = 494 m`; CIFP `N40314122,W003333368` =
`40.5281167, -3.5593556`. The CIFP point lies **496.7 m** from the `apt.dat` end along the runway
axis (bearing 179.76°) — agreeing with `apt.dat`'s 494 m to within 3 m. The trailing CIFP field
(`1640`) is the **displaced threshold distance in feet** = 499.9 m: the same quantity, from a
third independent place in the data.

**`earth_nav.dat` localizer bearing is two numbers in one field.** Row type 4, field 7:
`64979.763`. Decode with **integer** arithmetic on the string (never float `%`):

```
whole, frac  = "64979", ".763"
magnetic_deg = whole // 360        # 64979 // 360 = 180
true_deg     = whole %  360 + frac # 179 + 0.763 = 179.763
```

Checked on two more: `116602.320` → mag 323, true 322.320 (LEMD 32L); `83392.745` → mag 231,
true 232.745.

**`earth_nav.dat` glideslope angle is packed the same way**, with a different multiplier. Row
type 6, field 7: `300179.763`:

```
whole          = 300179
glideslope_deg = whole // 1000 / 100      # 300 / 100 = 3.00
true_deg       = whole %  1000 + frac     # 179 + 0.763 = 179.763
```

The multiplier is 1000, not 100 000 — a true bearing never reaches 1000, so the split is
unambiguous. Sanity-checked across the whole file: this decoding yields 2.05° at PADQ 26, 5.5° at
**EGLC 27** (London City's published 5.5° approach) and 6.65° at LSZA 01 — all correct, which no
wrong multiplier would produce.

**Frequencies.** Row types 3/4/5/6/12/13: field 5 is in units of 10 kHz (`11150` → 111 500 kHz).
Row type 2 (NDB): field 5 is already kHz.

**`earth_fix.dat` field 4 is `ENRT` or an airport ICAO.** This is the terminal scope §5.8 depends
on; it must be indexed, not discarded.

**ILS category decoding is defensive — unrecognised means `None`, never a crash.** The CIFP
`RWY:` category field carries `0`/`1`/`2`/`3` for no-ILS through CAT III in the common case, but
real data also contains blanks and letter codes for LDA, IGS and localizer-only installations.
Only `1`/`2`/`3` map to `Ils.category` `"I"`/`"II"`/`"III"`; **everything else maps to `None`**,
which the model already permits. A closed `Literal` fed straight from a source field is a
`ValidationError` waiting for the first unusual airport, and §4.6's rule is that one odd record
never fails a build.

**`earth_hold.dat` and `earth_awy.dat` share a fix-type enum:** `11` = waypoint/fix, `3` = VOR,
`2` = NDB.

**CIFP records have 38 comma-separated fields** for `SID`/`STAR`/`APPCH`, terminated by `;`.
Field 0 is `<TYPE>:<sequence>`; the map used by this design is: 1 route/approach type, 2 procedure
ident, 3 transition ident, 4 fix ident, 5 fix region, 6 fix section, 7 fix subsection,
8 description code (4 chars), 9 turn direction, 10 RNP, **11 path terminator**, 13–16 recommended
navaid (ident/region/section/subsection), 17 arc radius, 18 theta, 19 rho, 20 outbound magnetic
course, 21 route distance or holding time (`T010` = 1.0 min), 22 altitude descriptor,
23 altitude 1, 24 altitude 2, 25 transition altitude, 26 speed descriptor, 27 speed limit,
28 vertical angle (`-343` = −3.43°). Courses are tenths of a degree (`3247` = 324.7°); distances
are tenths of a NM (`0138` = 13.8 NM). The remaining fields are approach-qualifier flags used only
by the description-code decoding in §5.7.

---

## 7. The lazy / indexed split

### 7.1 The split, and the numbers behind it

Measured on the user's install (Windows, AIRAC 2607):

| Source | Size | Rows | Handling |
|---|---|---|---|
| `apt.dat` (Global Airports) | **380 MB**, 12 351 496 lines | 31 269 airports | **Indexed up front** |
| `earth_fix.dat` | 15.0 MB, 250 562 lines | ~250 k fixes | **Indexed up front** |
| `earth_nav.dat` | 3.7 MB, 39 389 lines | ~39 k navaids | **Indexed up front** |
| `earth_hold.dat` | 2.1 MB, 28 890 lines | ~29 k holds | **Indexed up front** |
| `earth_awy.dat` | 4.7 MB, 110 929 lines | airways | **Deferred** to Phase 4 (§6.2) |
| `earth_msa.dat` | 0.7 MB, 14 771 lines | MSAs | **Deferred** to Phase 3 |
| `CIFP/*.dat` | 110.6 MB across **14 938 files**, mean 7.2 KB | procedures | **Lazy, per airport** |

The split follows from the shapes: the bulk files are large but few, so one pass amortises across
every query afterwards. CIFP is small per file but there are 14 938 of them, and an instructor
session touches perhaps five airports. Parsing all of them at start-up would burn minutes to
produce data that is 99.97% unused.

### 7.2 The lazy path

`get_procedures()`, `get_procedure()` and `get_runways()` all funnel through one memoised parse:

```python
def _parse_cifp(self, icao: str) -> CifpAirport | None:
    """Memoised on (icao, resolved_path, mtime_ns). Per instance, not per module."""
```

- One file, ~7 KB, one full parse — approximately a millisecond. No I/O concurrency needed, which
  is another reason the interface is synchronous (§3).
- The cache is bounded at **64 entries**, evicted least-recently-used: a few MB of parsed objects,
  and an instructor session never touches 64 airports.
- It is a plain `dict` behind a `threading.Lock`, held **on the provider instance**.
- Cleared by `ensure_index(force=True)` and on any cache-key change.
- A missing `CIFP/<ICAO>.dat` is a normal outcome (`None`), not an error: 31 269 airports have
  runways, 14 938 have procedures.

**Not `@lru_cache` on a module-level function, and not on a method either.** Both are wrong here,
for different reasons, and both are the kind of wrong that shows up as a test that passes alone
and fails in a full run:

- **A module-level `@lru_cache(maxsize=64)` keyed on `icao` alone is global mutable state keyed by
  the wrong thing.** The contract suite (§11.1) constructs several providers in one process —
  the fixture-tree provider and, under `-m navdata`, one on the developer's real install — and
  `reset_navdata()` builds fresh ones between tests. Keyed on `icao`, the second provider is
  served the **first provider's parse of a different file tree**. `ZZZZ` from the fixtures would
  answer a query against a real install, or vice versa, with no error anywhere.
- **`@lru_cache` on a method keeps `self` in the key**, so every provider instance ever created
  is pinned in the cache for the process's lifetime — a leak that `reset_navdata()` cannot undo.

Keying on `(icao, resolved_path, mtime_ns)` fixes both and buys a third property for free: because
the path is the one that **won §9's per-file precedence**, and because `mtime_ns` is part of the
key, the cache self-invalidates when a navdata update replaces that airport's file — including the
case where the winner flips from `Resources/default data/` to `Custom Data/` between calls.

**`get_runways()` triggers the lazy CIFP load.** This is a deliberate coupling: runway data is a
merge of two sources, and returning different `elevation_ft` and `threshold` values depending on
whether the CIFP file happened to be warm would be the worst possible bug. Precedence, applied on
every call:

| Field | Source |
|---|---|
| `threshold` | CIFP `RWY:` (DDMMSSss) if present, else `apt.dat` end walked forward by the displacement |
| `elevation_ft` | CIFP `RWY:` threshold elevation if present, else airport elevation |
| `threshold_crossing_height_ft`, `ils.category`, localizer ident | CIFP `RWY:` only |
| `true_bearing_deg`, `length_m`, `width_m`, `surface`, `displaced_threshold_m`, `pavement_end` | `apt.dat` only |
| `ils.*` (frequency, positions, courses, glideslope) | `earth_nav.dat` only |

CIFP wins on threshold geometry because it is the datum the procedures themselves are built on;
using `apt.dat` for the threshold and CIFP for the approach legs would put a small, permanent,
invisible offset between a placement and the procedure it claims to be on.

### 7.3 What happens on first run — the user's first impression

**This is the one moment where a design decision is directly visible to the user, so it gets
stated in full.**

Measured on the user's machine: iterating `apt.dat`'s 12.35 M lines with a byte-prefix filter and
no parsing takes **6.0 s**, and keeps 1 278 883 rows (10.4%). With field splitting, geodesic
bearing computation per runway and batched SQLite inserts, a realistic full build is **60–120 s**,
of which `apt.dat` is the overwhelming majority; `earth_*.dat` together are ~26 MB and a few
seconds.

The single biggest optimisation, and it is required: **filter on the raw line prefix before any
splitting.** 90% of `apt.dat` is taxiway and pavement geometry (rows `110`–`116`) that this
project never reads. Rejecting those with a `str.startswith` on the untouched line, before any
`split()`, is the difference between a one-minute build and a five-minute one.

**The sequence the user sees:**

1. The app starts **immediately**. The server, the WebSocket and every non-navdata feature —
   aircraft control, weather, the raw state panel — are live in the normal start-up time. The
   index build never blocks start-up.
2. `ensure_index()` runs in a worker thread from the server's lifespan hook. Navdata-dependent
   panels are **disabled with a reason**, drawn from `status()` — the same mechanism as an
   unsupported `Capabilities` flag, and for the same reason: a control that is not yet usable is
   disabled and explained, never left to fail.
3. The UI shows a real progress bar fed by `IndexProgress` over the existing WebSocket, with an
   explanation rather than a spinner:
   > **Indexing your X-Plane navigation data — AIRAC 2607.**
   > This happens once per navdata cycle. Airports 62% · about 40 seconds remaining.
4. On completion the panels enable themselves. No restart, no dialog.
5. **Every subsequent start is instant** — the cache is opened, `PRAGMA user_version` and the
   fingerprint are checked (a few file `stat()` calls), and it is ready. The build recurs only
   when the user updates their navdata (~every 28 days) or their scenery.

**The build is atomic, and partial results are never queryable.** It writes to a `.tmp` file,
closes it cleanly in `journal_mode = DELETE` (§6.5) so exactly one file exists, and only then
`os.replace()`s it onto a **fresh generation filename** that no reader currently holds open
(§8.4). Publishing a half-built index so airport search works 30 seconds sooner was considered and
rejected: silently incomplete navdata — an approach that exists but whose fixes have not been
indexed yet — is far worse than a progress bar. An instructor briefing a student must be able to
trust that "no procedures found" means there are none.

The build is **cancellable** through the `cancel` event of §3 and, being cheap and idempotent, is
simply restarted rather than resumed if it is interrupted. A cancelled or crashed build leaves
only an orphaned `.tmp`, which the next build removes; the previously published generation is
untouched and stays queryable throughout.

**If the build fails**, `status()` reports `error` with the reason, navdata panels stay disabled
with that reason shown, and `POST /api/navdata/rebuild` offers a retry. The rest of the
application is unaffected — the whole point of keeping `NavdataProvider` off `SimAdapter`.

---

## 8. Cache invalidation

**Phase 1 exit criterion 2: the cache rebuilds automatically when `cycle_info.txt` reports a new
AIRAC cycle.**

### 8.1 The key

The AIRAC cycle is the **primary** component but cannot be the only one, for two reasons that are
facts about this install, not hypotheticals:

- `apt.dat` lives under `Global Scenery/` and is **not** covered by any AIRAC cycle. It changes
  when the user updates X-Plane or its scenery, with no cycle bump at all.
- A `SCHEMA_VERSION` bump by this project must also force a rebuild.

So the key is a tuple, stored in `meta` and in `source_file`:

```
cache_key = (
    SCHEMA_VERSION,
    airac_cycle,                       # "2607"
    source_root,                       # the resolved install path
    {role: (path, size_bytes, mtime_ns) for each indexed source file},
)
```

`ensure_index()` recomputes it — a handful of `stat()` calls, microseconds — and rebuilds on any
mismatch. Cycle change ⇒ rebuild, satisfying the exit criterion, and scenery updates and schema
changes are covered by the same mechanism instead of a second one.

Content hashing was rejected: hashing 380 MB on every start-up would cost more than the check
saves. `(size, mtime_ns)` is the standard build-system trade-off and is correct for files the user
replaces wholesale via an installer.

### 8.2 Reading the cycle — a fallback ladder

`cycle_info.txt` is the documented source, but it is **not guaranteed to exist**: in this install
it is present in `Custom Data/` and **absent from `Resources/default data/`** (verified). So:

1. `<root>/Custom Data/cycle_info.txt` → the line `AIRAC cycle    : 2607`, plus
   `Valid (from/to): 09/JUL/2026 - 06/AUG/2026` for the validity dates.
2. `<root>/Resources/default data/cycle_info.txt`, same format.
3. `<root>/Custom Data/cycle.json` → `{"cycle":"2607","revision":"1","name":"X-Plane 12"}`.
4. The header line of the resolved `earth_nav.dat`:
   `1200 Version - data cycle 2607, build 20260701, metadata NavXP1200…`
5. None of the above → cycle is `None`, the key degrades to the file fingerprints alone, and
   `status().airac_cycle` is `None`. The provider still works; it just cannot tell the user which
   cycle they are on.

All four ladder steps were verified present in the real install, so this is not defensive
speculation — it is the actual shape of the data.

### 8.3 There are no migrations

**Bumping `SCHEMA_VERSION` *is* the migration.** On mismatch the provider deletes the cache file
and rebuilds from the user's install.

The alternative — writing `ALTER TABLE` scripts for a derived cache — buys nothing. The source of
truth is on the user's disk, regeneration takes 60–120 s and is already a supported, instrumented
path (it runs every 28 days anyway), and migration scripts would be dead code the moment the
schema stabilises. Making rebuilds cheap and routine is a better investment than making them
avoidable.

The consequence for the parallel tracks is deliberate and good: **the #5 indexer track can change
the schema freely during Phase 1** at the cost of one `SCHEMA_VERSION` bump — provided it does so
serially, as `CLAUDE.md` requires.

### 8.4 Location and concurrency

The cache lives in the platform user-cache directory, **never in the repository and never inside
the X-Plane install** (which may be on a read-only or network drive, and which is not ours to
write to):

| OS | Path |
|---|---|
| Windows | `%LOCALAPPDATA%\OpenInstructorStation\navdata\` |
| macOS | `~/Library/Caches/OpenInstructorStation/navdata/` |
| Linux | `${XDG_CACHE_HOME:-~/.cache}/open-instructor-station/navdata/` |

Overridable with `OIS_NAVDATA_CACHE_DIR`. `.gitignore` already excludes `*.sqlite` and
`navdata_cache/`; §11.4 adds a test that makes that mechanical.

#### D15 — generations: a published file is never overwritten

Filename: **`navdata-<cycle>-v<SCHEMA_VERSION>-g<N>.sqlite`**, where `N` is a monotonically
increasing generation number — the highest `N` present in the directory, plus one.

**Why the generation number exists, concretely.** `POST /api/navdata/rebuild` on an unchanged
install — the retry after a failed build, the "my scenery looks wrong" button — produces a file
with the same cycle and the same schema version as the one already published. Without a
generation, the build would `os.replace()` **onto the exact path that live thread-local
connections have open**. Two things then go wrong:

- On Windows, replacing a file that other handles have open depends on the sharing flags those
  handles were opened with; SQLite's Win32 VFS does not guarantee this succeeds, and the failure
  mode is a `PermissionError` from the publish step of an otherwise successful two-minute build.
- With `immutable=1` (D14), it is worse if it *succeeds*: readers have promised SQLite the bytes
  will not change, and the file underneath them just did. That is undefined behaviour by
  construction — wrong rows or a spurious "database disk image is malformed", not a clean error.

So the build publishes to a new path and the provider bumps an in-memory **epoch** counter.
Each thread-local connection records the epoch it was opened at; the accessor compares and, if it
is behind, closes and reopens against the current path. Reads in flight finish against the old
file, which is still intact on disk — an epoch bump is never observed mid-query.

Superseded generations are unlinked once no connection references them, and any that survive a
crash are swept at the next start-up, so the directory holds exactly one file in steady state. On
Windows an unlink may fail while a handle lingers; that is logged and retried at the next
start-up, never surfaced to the user — a stale file wastes disk, it does not break anything.

#### Two processes, one build

A packaged app and a dev server starting together must not both spend two minutes building.
Serialise them with an **advisory lock held on an open file handle** — `msvcrt.locking()` on
Windows, `fcntl.flock()` elsewhere — not with a "does `build.lock` exist?" check.

**The distinction is the whole point: an OS-held lock dies with the process.** A lock file whose
mere existence means "locked" is orphaned by exactly the events most likely to interrupt a
two-minute build — a crash, a power cut, a `SIGKILL` — and every subsequent start then waits
forever on a holder that no longer exists. Users cannot diagnose that, and "delete this file from
your AppData folder" is not an acceptable recovery step. A kernel-held lock is released by the
kernel when the holder dies, so the orphan case does not exist.

The loser waits for the lock with a **timeout (180 s**, comfortably above the 60–120 s build). On
acquiring it, it re-checks the cache key first: the winner has usually just published, so the
loser adopts that generation and builds nothing. If the timeout expires it does not build in
parallel — it reports `status().state == "error"` with a reason naming the other process, and
`POST /api/navdata/rebuild` remains available.

---

## 9. Source precedence

**`Custom Data/` wins over `Resources/default data/`, resolved per file:**

```python
def resolve(root: Path, name: str) -> Path | None:
    custom = root / "Custom Data" / name
    if custom.is_file() and custom.stat().st_size > 0:
        return custom
    default = root / "Resources" / "default data" / name
    return default if default.is_file() else None
```

**Per file, not per directory — and this is not pedantry.** In the real install:

- `Custom Data/` has no `earth_astro.dat` and no `DOF.DAT`; `Resources/default data/` has both.
- `Custom Data/CIFP/` contains **14 938** files while `Resources/default data/CIFP/` contains
  **15 911**. Roughly a thousand airports have procedures only in the default data.

A directory-level rule would silently lose those thousand airports. **The rule therefore applies
to each `CIFP/<ICAO>.dat` individually as well**, resolved on each lazy load, not to the `CIFP`
directory as a unit.

The empty-file check matters because some navdata installers leave zero-byte placeholders behind.

`source_file` records which path won for each role, and `status()` exposes it, so "why is this
airport's SID wrong" is answerable without guessing.

### 9.1 `apt.dat` is not subject to this rule

`apt.dat` is scenery, not navdata. **Phase 1 reads exactly one file:**
`<root>/Global Scenery/Global Airports/Earth nav data/apt.dat` (31 269 airports).

Custom Scenery packs can override airports, ordered by `Custom Scenery/scenery_packs.ini`.
**That is an explicit non-goal for Phase 1** and gets its own issue. Doing it correctly means
honouring pack order, per-airport replacement semantics and `1302` metadata merging, and it
multiplies the index build the user waits for in §7.3. The Global Airports file is the correct
90% answer, and a user with a custom LEMD gets Laminar's runway geometry — an offset of metres,
not of runways.

---

## 10. Installation discovery

```python
def discover_xplane_root(configured: Path | None = None) -> Path | None: ...
```

In order, first validating candidate wins:

1. **Explicit configuration** — `OIS_XPLANE_PATH` (`Settings.xplane_path`, following the existing
   `OIS_`-prefixed pattern in `server/deps.py`). Always wins. If it is set and invalid, that is an
   **error with the reason**, not a silent fallthrough to autodetect: a user who configured a path
   and got someone else's install would never work out why.
2. **X-Plane's own installation registry** — Laminar writes the list of installs to a per-user
   file, one path per line:
   | OS | Path |
   |---|---|
   | Windows | `%LOCALAPPDATA%\x-plane_install_12.txt` |
   | macOS | `~/Library/Preferences/x-plane_install_12.txt` |
   | Linux | `~/.x-plane/x-plane_install_12.txt` |
   Each line is validated; the first that passes wins. This is the mechanism the sim itself
   maintains, so it is right far more often than any guess.
3. **Well-known roots** — `C:\X-Plane 12`, `D:\X-Plane 12`,
   `<drive>\SteamLibrary\steamapps\common\X-Plane 12`, `~/X-Plane 12`,
   `/Applications/X-Plane 12`. Cheap, and covers the common case where step 2's file is missing.
4. **Nothing found** → `status().state == "unavailable"` with
   `reason = "No X-Plane 12 installation found. Set OIS_XPLANE_PATH or choose your X-Plane folder."`

**Both, then — config and autodetect.** Autodetect alone fails the many users with an install on a
second drive; config alone makes the first run a configuration exercise. Config first, autodetect
as the fallback, and the discovered path always shown in `status().source_root` so the user can
see what was picked and override it.

**Validation of a candidate root** (all must hold):

```
<root>/Resources/default data/earth_nav.dat                     exists
<root>/Global Scenery/Global Airports/Earth nav data/apt.dat    exists
```

Checking both catches a partially-copied or partially-installed tree, and it checks the
`Resources/` side specifically because `Custom Data/` may legitimately be empty on a stock install.

**When there is none, the application still starts.** Non-navdata features work; navdata panels
are disabled with the reason; the UI offers a folder picker that writes the path to config and
calls `POST /api/navdata/rebuild`. This is hard rule 3's discipline applied to a second axis:
**a missing prerequisite is a declared state, never a runtime failure.**

---

## 11. Test strategy

`core/` logic requires tests, no exceptions (`CLAUDE.md`). Navdata is read from the user's own
install and **never committed** (hard rule 4). Both hold simultaneously, as follows.

### 11.1 The contract suite

`tests/core/navdata/test_navdata_contract.py`, **parametrised over providers** — the same pattern
as `tests/adapters/test_contract.py`, for the same reason: an interface with one implementation is
a suggestion.

| Parametrisation | Data | Runs in CI |
|---|---|---|
| `InMemoryNavdataProvider` | hand-built pydantic objects in the test module | **yes** |
| `XPNativeNavdataProvider(fixture_root)` | the committed fixture tree (§11.2) | **yes** |
| `XPNativeNavdataProvider(discover_xplane_root())` | the developer's real install | no — `@pytest.mark.navdata` |

**The real parser runs in CI.** This is the key difference from the sim case: a simulator cannot
be installed on a GitHub runner, but a 200 KB fixture tree can be committed. So the actual
`apt.dat`, `earth_*.dat` and CIFP parsers — the code most likely to break — are covered by CI on
all four OS × Python combinations, without a byte of anyone's proprietary navdata.

`InMemoryNavdataProvider` exists for the same two reasons `FakeSimAdapter` does: it lets the
Position Manager's tests build exactly the airport a case needs, and a second implementation makes
X-Plane-format assumptions impossible to smuggle into `core/`.

**A new marker is required.** `pyproject.toml` currently has `addopts = ["-m", "not sim", …]`; it
becomes `-m "not sim and not navdata"`, with `navdata: requires the developer's own X-Plane
installation. Never runs in CI.` added to `markers`.

That marker, plus the additive `Runway` fields and the `Ils` / `RunwaySurface` models beside them
(§5.0), and one added deny-rule in `test_core_boundaries.py` (§11.6), are the **complete** list of
changes this design asks of files that already exist. Everything else it specifies is new files
under `core/navdata/`, `server/routers/` and `ui/src/features/navdata/`. Keeping that list short
and enumerated is what lets the four tracks of §13 start on the same day.

### 11.2 The fixture tree

`tests/fixtures/navdata/xp_root/` — a hand-written minimal X-Plane data tree, **under a 256 KB
total budget**, asserted by a test:

```
xp_root/
  Custom Data/
    cycle_info.txt                  hand-written, "AIRAC cycle : 2501"
    earth_fix.dat                   ~20 rows, invented idents, ENRT and terminal
    earth_nav.dat                   ~15 rows: VOR, DME, NDB, LOC, GS, TACAN
    earth_hold.dat                  ~5 rows, both time-legs and distance-legs
    CIFP/ZZZZ.dat                   one SID, one STAR, one approach
  Resources/default data/
    earth_fix.dat                   2 rows  — proves per-file precedence
    earth_nav.dat                   2 rows
    CIFP/ZZZY.dat                   — proves per-CIFP-file fallback (§9)
  Global Scenery/Global Airports/Earth nav data/
    apt.dat                         2 airports, 3 runways, 4 parking stands
```

**Everything is invented.** Airports use the `ZZ` block (`ZZZZ` is the ICAO code meaning "no
location"), and every fix, navaid and procedure ident is fabricated. Coordinates are chosen for
hand-computable geodesy — a threshold at exactly 40°00'00"N 003°00'00"W with a runway on a true
bearing of 090° makes the expected value of a 10 NM final something a reviewer can verify with a
calculator instead of trusting the code under test.

The fixtures deliberately include the ugly cases the parsers must survive: a displaced threshold,
a `RW32B` "both parallels" transition, a `CA` leg, an `IF` leg whose fix is deliberately absent
(so `unpositionable_reason` is exercised on both branches), a `B,FL140,10000` band, a `-,210`
speed limit, a malformed row that must be skipped rather than fatal, and a zero-byte file in
`Custom Data/` that must fall through to `default data` (§9).

### 11.3 Public-domain FAA extracts, and the rule that keeps them safe

A small set of real-world records makes the parsers honest about formats no hand-written fixture
would think to produce. They may come **only from the FAA's own CIFP publication**, which is a
work of the United States Government and in the public domain.

**Two prohibitions, both absolute:**

1. **Never from `Custom Data/`.** That is Navigraph/Jeppesen data. The `cycle_info.txt` shipped
   with it states in terms: *"may not be recompiled, interpreted, or distributed for any purpose
   without the written consent of Navigraph."*
2. **Never from `Resources/default data/` either.** Even for US airports whose content is
   FAA-derived, that file is Laminar's redistribution under Laminar's terms. Go to the FAA source.

Each extract is accompanied by `tests/fixtures/navdata/PROVENANCE.md` recording the source URL,
the AIRAC cycle, the retrieval date and a statement of public-domain status. Extracts are trimmed
to the few procedures a test asserts on.

### 11.4 The guard test

`tests/core/navdata/test_no_navdata_committed.py` walks the repository and **fails** if it finds,
outside `tests/fixtures/navdata/`:

- any file named `apt.dat`, `earth_*.dat`, `cycle_info.txt` or `cycle.json`;
- any directory named `CIFP`;
- any `*.sqlite` / `*.sqlite3`.

and additionally fails if the fixture tree exceeds its size budget or if `PROVENANCE.md` is
missing while FAA extracts are present.

Hard rule 4 is the rule most likely to be broken by accident — a debugging session that copies one
airport file "just for a minute" and a `git add -A`. `.gitignore` helps but does not catch a file
someone force-adds or a `CIFP/` directory under a new name. This test makes the rule mechanical,
runs in CI in milliseconds, and is the cheapest insurance in the project.

### 11.5 Golden-value tests

Table-driven, with hand-computed expected values, for the decoders that are easy to get subtly
wrong (§6.6):

- **DDMMSSss**: `N40294171` → `40.4949194`, `W003332833` → `-3.5578694`, `S33565000` →
  `-33.9472222`, `E151101200` → `151.1700000` — southern and eastern hemispheres, the 2-digit vs
  3-digit degree split, and a zero-hundredths case.
- **Packed localizer bearing**: `64979.763` → `(true 179.763, mag 180)`; `116602.320` →
  `(322.320, 323)`; `83392.745` → `(232.745, 231)`.
- **Packed glideslope**: `300179.763` → `3.00°`.
- **Frequencies**: `11150` → `111_500 kHz`; NDB `380` → `380 kHz`.
- **Constraints**: every row of the table in §5.9, including `suggested_ft` and `suggested_kt`.
- **Positionability**: every terminator in `PathTerminator`, asserting the six positionable ones
  and only those, plus the resolved-fix-is-`None` branch.

### 11.6 Boundary tests

- `test_core_boundaries.py` — `core/navdata/` imports nothing from `core/sim_adapter.py`,
  `adapters.*`, `httpx`, `websockets`, `SimConnect`, **and `core/models.py` imports nothing from
  `core/navdata/`** (D13). The last one is a one-line addition to the existing import-graph walk
  and it is what keeps the `Runway.ils` field from reintroducing a cycle: the failure it prevents
  is not subtle at runtime, but it is exactly the sort of thing a contributor "fixes" with a
  `TYPE_CHECKING` guard instead of moving the model back where it belongs.
- `test_provider_adapter_independence.py` — a server built with `OIS_ADAPTER=fake` and
  `OIS_NAVDATA=xplane_native(fixture_root)` serves navdata correctly, and one built with
  `OIS_ADAPTER=fake` and `OIS_NAVDATA=in_memory` serves the fixture provider. The two axes are
  independently selectable, proven rather than asserted.

### 11.7 Cache-lifecycle tests

The §6.5 / §8.4 rules are invisible in normal operation and expensive to debug when violated, so
each gets a cheap test against the fixture tree:

- **Journal mode.** After a build, the published file's `PRAGMA journal_mode` is `delete`, and no
  `-wal` or `-shm` sibling exists in the cache directory (D14).
- **Generations.** Two consecutive `ensure_index(force=True)` calls on an unchanged fixture tree
  produce **two different filenames**, and a connection opened before the second build still
  answers queries afterwards (D15). This is the test that would have caught the in-place
  `os.replace()`, and it fails loudly on Windows, which is where the bug lives.
- **Epoch reopen.** A query issued after a forced rebuild observes the new generation — i.e. a row
  added to the fixture tree between builds is visible without recreating the provider.
- **Cancellation.** `ensure_index(cancel=already_set_event)` publishes nothing, leaves the
  previous status intact, and leaves no `.tmp` behind (D16).
- **CIFP cache keying.** Two providers over two different fixture roots, alive in one process,
  each return **their own** `ZZZZ` procedures — the regression test for the module-level
  `@lru_cache` rejected in §7.2.

Add to the golden-value tests of §11.5: `tunable_radio` for one navaid of each kind (`"nav"` for
a VOR, `"adf"` for an NDB, `None` for a glideslope), and an ILS category field carrying an
unrecognised code, asserting `category is None` rather than a raised `ValidationError`.

---

## 12. Server surface

Listed so the UI track can generate its client and start immediately. All handlers are declared
**`def`, not `async def`** (§3), so Starlette runs them in the threadpool.

| Method | Path |
|---|---|
| `GET` | `/api/navdata/status` |
| `POST` | `/api/navdata/rebuild` |
| `GET` | `/api/navdata/airports?q=&limit=` |
| `GET` | `/api/navdata/airports/{icao}` |
| `GET` | `/api/navdata/airports/{icao}/runways` |
| `GET` | `/api/navdata/airports/{icao}/parking?kind=` |
| `GET` | `/api/navdata/airports/{icao}/procedures?kind=` |
| `GET` | `/api/navdata/airports/{icao}/procedures/{kind}/{ident}?transition=` |
| `GET` | `/api/navdata/navaids?ident=&region=` · `?lat=&lon=&radius_nm=&kinds=` |
| `GET` | `/api/navdata/fixes?ident=&region=` · `?lat=&lon=&radius_nm=` |
| `GET` | `/api/navdata/holds?fix_ident=&airport_icao=` |

`IndexProgress` frames go out on the **existing** WebSocket alongside live state — no second
socket. The UI is expected to gate on `GET /api/navdata/status`, exactly as it gates on
`GET /api/capabilities`.

**Status codes.** Not-found returns `404`. `NavdataUnavailable` returns **`503` with a
`Retry-After` header** and `status()` in the body, so a UI that raced the build gets the state
rather than a stack trace. `503`, not `409`: the request is not in conflict with the resource's
state — there is nothing to reconcile and nothing the client did wrong. The index is *temporarily
absent*, which is precisely what `503 Service Unavailable` means, and it is the one status whose
`Retry-After` tells the generated client how long to wait. `Retry-After: 5` while `building`,
`Retry-After: 60` while `unavailable` or `error`, where a human has to act.

**Crossing back into the event loop — the one thing `server/` must get right.** `ensure_index()`
runs in a worker thread (§3), so its progress callback fires **off the event loop**. Touching the
WebSocket pump from there is a data race on asyncio internals, and it is the kind that works in
development and drops frames or corrupts the connection under load. The server's callback
therefore does nothing but hand the frame across:

```python
loop = asyncio.get_running_loop()  # captured before to_thread()


def _on_progress(frame: IndexProgress) -> None:  # runs in the worker thread
    loop.call_soon_threadsafe(pump.publish_navdata_progress, frame)
```

`call_soon_threadsafe` is the only asyncio API safe to call from another thread, and this is the
only place in the project that needs it. Frame volume is already bounded at the source — one per
0.5 s or per 1% of progress (§3) — so this queues a handful of callbacks per second, not
thousands.

New settings in `server/deps.py`, alongside the existing `OIS_`-prefixed ones:

```
OIS_NAVDATA           = "xplane_native" | "in_memory"   (default: "xplane_native")
OIS_XPLANE_PATH       = <path>                          (default: autodetect)
OIS_NAVDATA_CACHE_DIR = <path>                          (default: platform cache dir)
```

`get_navdata()` is an `lru_cache(maxsize=1)` singleton built the same way `get_adapter()` is, and
`reset_navdata()` mirrors `reset_adapter()` for tests. **Constructing it performs no I/O**, in
keeping with the existing rule for adapters.

---

## 13. What each parallel track now owns

The contract is fixed; the four tracks are disjoint by file and can start together.

| Track | Owns | Depends on this document for |
|---|---|---|
| **#4 CIFP parser** | `core/navdata/xplane_native/cifp.py`, fixtures `CIFP/ZZZZ.dat` | `Procedure`, `ProcedureLeg`, `FixRef`, constraints, positionability, the §6.6 field map |
| **#5 `apt.dat` + `earth_*` indexer** | `core/navdata/schema.py`, `core/navdata/xplane_native/{apt,earth}.py`, the build job, the cache lifecycle | the DDL, the cache key, precedence, the §6.6 decoders, `IndexProgress`, D14–D16 |
| **#6 geodesy** | `core/geodesy.py` | nothing — `Runway`'s existing fields are unchanged (D4) |
| **UI panel** | `ui/src/features/navdata/` | the §12 endpoints and the generated types |

`core/navdata/schema.py` has exactly one owner and is never edited concurrently
(`CLAUDE.md`, parallelisation policy).

**One shared file needs a serial, up-front edit before the tracks branch:** adding `Ils`,
`RunwaySurface` and the new optional `Runway` fields to `core/models.py` (§5.0, §5.3). It is
shared vocabulary, so it follows the same rule as a `SimAdapter` contract change — **done once, by
one agent, before dependent work starts**, never in parallel. It is a handful of additive model
declarations and it unblocks #4, #5 and the UI's generated types simultaneously.

---

## 14. Non-goals for Phase 1

Recorded so they are decisions rather than omissions:

- **Airways (`earth_awy.dat`) and MSAs (`earth_msa.dat`)** — the schema has room; nothing in
  Phase 1 queries them. Phase 4 and Phase 3 respectively.
- **Custom Scenery airport overrides** (§9.1) — own issue.
- **Persisting parsed CIFP into SQLite** — the in-process LRU is sufficient at ~1 ms per airport.
  Revisit only if profiling shows procedure loading on the placement path; it is a pure addition
  behind an unchanged interface.
- **Magnetic-variation modelling (WMM)** — the provider carries frames, never converts (§5.1).
- **Helipads (`apt.dat` row 102) and water runways (row 101)** — row `100` only, which is why
  `Runway.ident`'s `max_length=3` still holds.
- **Terminal procedures for airports absent from `apt.dat`** — an airport must exist in the index
  to be reachable; a CIFP file alone does not create one.
- **Writing anything back to the user's X-Plane install** — the provider opens every source file
  read-only, always.
