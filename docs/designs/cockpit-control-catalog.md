# Cockpit Control Catalog — design

**Status:** designed, not yet implemented.
**GitHub issues:** epic [#225](https://github.com/Santisoutoo/open-instructor-station/issues/225); this document is Wave 0, [#219](https://github.com/Santisoutoo/open-instructor-station/issues/219). Wave 1: [#220](https://github.com/Santisoutoo/open-instructor-station/issues/220) (core/adapters/server), [#221](https://github.com/Santisoutoo/open-instructor-station/issues/221) (UI). Wave 2: [#222](https://github.com/Santisoutoo/open-instructor-station/issues/222) (Zibo MCP), [#223](https://github.com/Santisoutoo/open-instructor-station/issues/223) (Zibo overhead), [#224](https://github.com/Santisoutoo/open-instructor-station/issues/224) (Zibo pedestal/quadrant/lights). Related bug: [#217](https://github.com/Santisoutoo/open-instructor-station/issues/217).
**Phase:** post-3 addition to manager 6 (Aircraft Control) — the "aircraft-specific override layer keyed on the loaded aircraft" that [`../feature-spec.md`](../feature-spec.md#6-aircraft-control) §6 already anticipates. No roadmap phase names it; it does not gate any phase exit. Roadmap Phase 5's exit criterion 4 (*"zero simulator-specific code outside `adapters/`"*) is the constraint that most shapes it (§5, §6).
**Feature spec:** manager 6, "Autopilot mode engagement is the most aircraft-dependent area of the whole product … The adapter provides a default mapping and an aircraft-specific override layer keyed on the loaded aircraft ICAO/path."
**Research it implements:** [`../research/zibo-737-autopilot-dataref-mapping.md`](../research/zibo-737-autopilot-dataref-mapping.md) — every design constraint below that cites a section number (§1–§8) refers to that document.
**Depends on:** the Phase 0/1 contract (`core.sim_adapter`, `FakeSimAdapter`, the contract suite). **Live work on the Zibo additionally depends on #217** (§10.1).
**Blocks:** #220, #221 (Wave 1); through them #222–#224 (Wave 2).

A data-driven, per-aircraft catalog of cockpit controls — each with an id, a label, a panel group,
a control kind, an adapter-private binding, a read-back and preconditions — so that the instructor
can operate *every* interactive control of a study-level aircraft from the tablet, and adding a
control is a data edit, never a code change. `AircraftSetup` stays the typed path for flight-state
setup; this is the separate path for "each individual button, switch and dial".

Binding rules live in [`../../CLAUDE.md`](../../CLAUDE.md); layers in
[`../architecture.md`](../architecture.md). The Camera Manager
([`camera-manager.md`](camera-manager.md)) and Pushback Manager ([`pushback-manager.md`](pushback-manager.md))
designs are the house format and the precedent for the *contract-foundation split* this document
prescribes (§9): a small foundation PR merged alone (their commits `95763fd feat(camera): contract
foundation` and `e2f9d48 feat(pushback): contract foundation`), then parallel execution + UI work.
The Failures Manager's per-entry support manifest and the Scenario Generator's YAML loader
(`core/scenarios/loader.py`) are reused as *patterns*, not code.

---

## 0. Decisions at a glance

| # | Decision | Where |
|---|---|---|
| D1 | **One new flag, `can_control_cockpit`, and it is a static declaration: "this adapter has the catalog machinery."** `Capabilities` is frozen and resolved once at `connect()` (its own docstring; `test_capabilities_are_stable`). Therefore *which aircraft catalog is active* can never live in the flag — it is **manifest state**, read capability-free (`get_camera_support`/`get_failure_support` posture): "no catalog for the loaded aircraft" is an answer with a reason, never an exception. An aircraft swap bumps a manifest `revision`; the flag never moves. | §3.4, §4 |
| D2 | **Five control kinds, closed:** `toggle` (press command + status dataref; apply = read-back-and-press-if-different, never an unconditional press — §1), `press` (no state), `dial` (absolute write + read-back), `encoder` (inc/dec repeat commands, delta only, no absolute set — the 737 V/S wheel's shape), `selector` (multi-position: value write, or bounded inc/dec stepping towards a target). | §3.1, §6.2 |
| D3 | **Catalog files are YAML under `adapters/<sim>/cockpit_catalogs/<catalog-id>/`, never under `core/`.** They contain dataref and command names; hard rule 2 forbids those in `core/`. `core/cockpit/` owns the *schema*, the *loader* and the *pure logic*; the binding block is opaque strings core validates only structurally. Core's test fixtures use invented binding strings. | §3.2, §5, §6 |
| D4 | **One directory per aircraft, one root file plus one file per panel, merged by the loader; a duplicate id across files is a load error.** This makes Wave 2's three issues disjoint at the *file* level (`mcp.yaml`, `overhead.yaml`, `pedestal.yaml`, `lights.yaml`), so three worktrees never conflict. | §3.2, §6.1, §9.3 |
| D5 | **Detection is a live per-name probe, `GET /api/v2/datarefs?filter[name]=<detect.dataref_exists>`.** Never `adapter.name`, never `acf_ICAO` (both 737s read `B738`, §7), never the cached full dataref index (`connect()`'s scan — proven stale after an aircraft swap, §7). A miss is a **404** on the real Web API (§7's `invalid_dataref_name`; #217's repro for commands). | §5.2 |
| D6 | **Binding ids resolve lazily, per control, per name, cached, invalidated on aircraft change.** Never eagerly on connect: every lookup is one HTTP round trip, and under the documented Docker Desktop gotcha that is ~4.1 s each — a 300-entry catalog resolved eagerly would take twenty minutes. A design constraint, not an optimisation. | §5.3 |
| D7 | **The aircraft-change hook is lazy and two-signalled.** Every cockpit method first checks `acf_relative_path` (a cheap *change* signal, §7 — a path convention, never the identity) against the last-seen value; a change re-runs the probe and drops every cached id. Independently, an `invalid_dataref_id`/`invalid_command_id` 404 on any cockpit read or write is treated as the same signal: invalidate, re-detect, retry once. `refresh_cockpit_catalog()` forces it. No background task. | §4, §5.4 |
| D8 | **Every write is confirmed by a read-back inside the adapter, or it raises.** Toggle → status dataref equals the requested state; dial → the *designated* read binding (which may differ from the write: speed writes `mcp_speed_dial_kts` and reads *it*, never the slow drum echoes `kts2`/`kts_mach`, §5) within the entry's `readback_tolerance` after its `settle_s`; selector → position equals target. Failure is `CockpitWriteRejected` → 502, the `WeatherRejected` precedent. "A value written into one call is not delivered until something reads it back" (CLAUDE.md, issue #39). | §5.5, §6.2 |
| D9 | **Preconditions are data, evaluated in `core/`, enforced by the adapter (409), displayed by the UI.** `preconditions: [{any_of: [...], hint}]` — all groups must hold, each group is satisfied by any one condition. §2's finding (lateral-mode presses are inert with FD off) is `any_of: [fd_capt on, fd_fo on, cmd_a on, cmd_b on]` on `hdg_sel`/`vorloc`/`app`. The same data orders `AircraftSetup` overrides (D11). | §3.1, §6.3 |
| D10 | **"Park, don't guess" is a first-class catalog section.** `parked:` lists controls that exist on the aircraft but have no verified mapping (V/S, IAS/Mach changeover, LNAV-without-a-route) with a reason; the UI renders them disabled-with-reason, never as an enabled control. Every actuable entry carries a required `verified_on` date. | §3.2, §7 |
| D11 | **`AircraftSetup` autopilot fields route through the catalog when the active catalog declares `setup_overrides`.** The mechanism (a `setup_overrides` block, `core.cockpit.actuation.plan_setup_actuations()` ordering FD/master before lateral modes by the precondition graph, and a hook in `_write_autopilot`) ships **data-independent in Wave 1 Track B**; #222 supplies the data. This deviates from #222's wording — flagged for the user in §10.2, not silently reassigned. | §6.4, §5.6, §10.2 |
| D12 | **The Fake's synthetic catalog is a Python constant, not a YAML read.** `FakeSimAdapter` "performs no I/O whatsoever" (its docstring). One control of every kind, one precondition, one parked entry, a press log and a `load_cockpit_catalog()` swap affordance, so the contract suite covers everything — including an aircraft swap — in CI. | §4.1 |
| D13 | **Read-back display is a scoped REST snapshot, polled, not a new WebSocket.** `GET /api/cockpit/state?panel=<id>` reads only the visible panel's readable controls. A per-dataref REST read is what the X-Plane adapter has today (its `stream_state` docstring: "Phase 0 polls over REST"); streaming a hundreds-of-entries catalog at telemetry rate would be a new subscription protocol, out of scope (§10.5). Snapshots carry `catalog_id`/`revision`, so polling detects an aircraft swap for free. | §2, §7.2 |
| D14 | **#217 is not folded into the foundation.** It is its own tiny `bug/` PR, parallel with the foundation (disjoint files), landed before any live work: with the Zibo loaded, `connect()` currently aborts on the first optional camera command miss, so no `-m sim` run and no Wave 2 verification is possible until it ships. | §10.1 |
| D15 | **Live verification is a single "sim slot", serialised; authoring is parallel.** Three agents never drive one X-Plane concurrently. One generic live sweep parametrised over catalog entries, scoped with `-k`, run once per Wave 2 PR by `sim-validator`, in a fixed order; entries that fail read-back move to `parked` before merge. | §8.4, §9.3 |

---

## 1. Scope

### 1.1 What this manager does

1. **A sim-agnostic catalog schema and loader** in `core/cockpit/` — control kinds, panels,
   preconditions, parked entries, `AircraftSetup` overrides, and a YAML directory loader.
2. **A new capability and adapter surface** — `can_control_cockpit`, `get_cockpit_catalog()`,
   `refresh_cockpit_catalog()`, `read_cockpit_states()`, `actuate_cockpit_control()`.
3. **X-Plane execution** — command activation vs dataref patch per kind, read-back confirmation,
   guarded toggles, live aircraft detection by dataref probe, per-name lazy id resolution, and the
   aircraft-change hook.
4. **REST endpoints** under `/api/cockpit/*` and the regenerated `ui/src/api/schema.d.ts`.
5. **A generic Cockpit Controls tab** that renders whatever catalog the server reports, grouped by
   panel, searchable, one widget per kind, gated on the flag, showing confirmed state only.
6. **The Zibo B737-800X catalog directory skeleton** (`aircraft.yaml` with the read-back-confirmed
   detection dataref) — the data files themselves are Wave 2.

Feature-spec coverage (manager 6): the "aircraft-specific override layer keyed on the loaded
aircraft"; reads/writes of autopilot master, FD, HDG/NAV/APP, selectors, lights and trim on
aircraft whose generic datarefs are dead (the headline result of the research).

### 1.2 What is explicitly out of scope

| Out of scope | Why / owner |
|---|---|
| Any Zibo mapping *data* beyond the detection root file | Wave 2 (#222–#224). This document ships the machinery and the Fake's synthetic catalog only. |
| V/S target, IAS/Mach changeover, LNAV without a route | Parked (§6 no settable dataref; §5 inconclusive; §2 needs an FMC route). Listed in `parked:`, never mapped. |
| A WebSocket stream of cockpit state | D13; §10.5. |
| Aircraft other than the Zibo | Additive: a new directory under `cockpit_catalogs/`. The generic stock-aircraft path stays `AircraftSetup`. |
| Scenario steps that actuate catalog controls | Scenarios are data (hard rule 8) and could carry `cockpit: [{control_id, value}]` steps later; the actuation model here is designed to be embeddable, but the scenario schema is not touched. |
| MSFS | Phase 5; §5.7 states what transfers. |
| FMC route injection (#215) | Separate issue; the LNAV precondition will reference it when it lands. |

---

## 2. REST endpoints

All under `/api/cockpit/*`, in a new `server/cockpit_routes.py`, registered from `server/app.py`
with one `include_router` line — the only shared backend edit, the Camera/Pushback precedent.

```
GET  /api/cockpit/catalog            -> CockpitCatalogManifest
POST /api/cockpit/catalog/refresh    -> CockpitCatalogManifest
GET  /api/cockpit/state?panel=<id>   -> CockpitStateSnapshot
POST /api/cockpit/actuate            -> CockpitActuationResult
```

| Method | Path | Purpose | Safe? | Gate | Notes |
|---|---|---|---|---|---|
| `GET` | `/catalog` | The active catalog for the loaded aircraft: panels, controls (binding-free), parked entries, revision. Always 200. | yes | none — capability-free (D1). Without the flag: `supported=false`, `reason` set, empty lists. | Runs the lazy change check (D7) as a side effect, so a swapped aircraft is noticed on the next fetch. |
| `POST` | `/catalog/refresh` | Force re-detection and drop every cached id. Idempotent. | no (adapter I/O, no aircraft state change) | `can_control_cockpit` → 501 | The panel's "Re-detect aircraft" button. |
| `GET` | `/state` | Confirmed values of the readable controls, optionally scoped to one panel. | yes | `can_control_cockpit` → 501 | Unknown `panel` → 404. No active catalog → 200 with `catalog_id=null`, empty `states`. |
| `POST` | `/actuate` | One actuation, confirmed by read-back. | no | `can_control_cockpit` → 501 | Body `CockpitActuation`. |

### 2.1 Capability and precondition gating

- `/catalog/refresh`, `/state`, `/actuate` without `can_control_cockpit` → **501**, *"Unavailable on
  this adapter — the 'xplane' adapter does not declare can_control_cockpit, so it cannot operate
  cockpit controls."*
- `/actuate` with no active catalog (`CockpitCatalogInactive`) → **409**, *"No cockpit catalog is
  active for the loaded aircraft — re-detect, or load an aircraft with a catalog."*
- `/actuate` with an unmet precondition (`CockpitPreconditionUnmet`) → **409**, detail = the hints
  of every unmet group joined by "; " — e.g. *"HDG SEL needs a flight director or CMD engaged."*
  A state precondition, not a capability (pushback-manager.md D8).
- `/actuate` on an id absent from `controls` (`CockpitControlUnknown`) → **404**; if the id is in
  `parked`, the detail is *"'mcp_vs' is parked on this aircraft: <reason>."*
- `/actuate` whose read-back disagrees (`CockpitWriteRejected`) → **502**, the adapter's own
  sentence (which names the control, the requested value and the value read back).
- `CapabilityNotSupported` escaping the adapter anyway → 501, defence in depth.

### 2.2 Validation errors — 422

- `CockpitActuation` shape: both `value` and `delta` set; `delta` non-integer.
- Kind/value mismatch, checked by the route against the active catalog via
  `core.cockpit.actuation.validate_actuation()` (§6.2): a `bool` for a `dial`, a `delta` for a
  `toggle`, a `value` for an `encoder`, a value outside `[min_value, max_value]`, a selector value
  not among `options`, a `press` with either field set, `|delta| > max_delta`.

### 2.3 Everything else

FastAPI's `{"detail": "<one sentence>"}`.

---

## 3. Pydantic models

All in **`core/cockpit/models.py`** (request models in `core/`, not the router — the Position
Manager's recorded regret). Value models `frozen=True`; request models `frozen=True,
extra="forbid"`. Units are carried **per entry** in `unit` (dials/encoders) — a catalog of many
aircraft cannot have one unit per kind — and the unit vocabulary is fixed below so the UI can
format it.

### 3.1 The catalog schema — what a file declares

```python
CockpitControlKind = Literal["toggle", "press", "dial", "encoder", "selector"]

#: What a control's state or requested value can be. Order matters to pydantic's
#: union matching: bool before int before float, so `True` stays a bool.
CockpitValue = bool | int | float | str

#: Unit vocabulary for dial/encoder entries. Closed so the UI formats every one.
CockpitUnit = Literal[
    "ft", "kt", "mach", "deg", "fpm", "ratio", "count", "khz", "mhz", "psi", "units"
]

CONTROL_ID_PATTERN = r"^[a-z0-9]+(?:_[a-z0-9]+)*$"  # snake_case, e.g. mcp_alt, fd_capt
CATALOG_ID_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"  # kebab-case, e.g. zibo-b738


class CockpitPanel(BaseModel):
    """One group in the panel picker. Catalog-defined — different aircraft, different panels."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    panel_id: str = Field(pattern=CONTROL_ID_PATTERN)
    label: str = Field(min_length=1, max_length=40)
    order: int = Field(ge=0, description="Display order, ascending.")


class ControlCondition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    control_id: str = Field(pattern=CONTROL_ID_PATTERN)
    equals: CockpitValue = Field(description="The state the referenced control must be in.")


class PreconditionGroup(BaseModel):
    """Satisfied when ANY condition holds. A control's list of groups must ALL hold (D9)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    any_of: list[ControlCondition] = Field(min_length=1)
    hint: str = Field(
        min_length=1, max_length=120, description="Shown to the instructor when the group is unmet."
    )


class SelectorOption(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    value: int | str = Field(
        description="The value the read binding reports / the write binding takes."
    )
    label: str = Field(min_length=1, max_length=30)


class CockpitControlSpec(BaseModel):
    """The PUBLISHED half of a control — what the server and UI see. No binding (D3)."""

    model_config = ConfigDict(frozen=True)

    control_id: str = Field(pattern=CONTROL_ID_PATTERN)
    label: str = Field(min_length=1, max_length=60)
    panel_id: str = Field(pattern=CONTROL_ID_PATTERN)
    kind: CockpitControlKind
    hint: str | None = Field(default=None, max_length=120)
    preconditions: list[PreconditionGroup] = Field(default_factory=list)
    readable: bool = Field(
        description="True when the adapter can report this control's state. "
        "Derived from the binding at load time: always True for toggle/dial/"
        "selector, False for press, binding-dependent for encoder."
    )
    # --- toggle ---
    on_label: str = "On"
    off_label: str = "Off"
    # --- dial / encoder ---
    unit: CockpitUnit | None = None
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = Field(
        default=None,
        gt=0.0,
        description="Dial: the UI stepper increment (NOT enforced on writes — "
        "X-Plane accepts any value; the sim rounds if it wants to). "
        "Encoder: the value change one click produces, in `unit`, for display.",
    )
    readback_tolerance: float = Field(
        default=0.0, ge=0.0, description="Dial: |read_back - written| allowed, in `unit`."
    )
    # --- encoder ---
    max_delta: int | None = Field(
        default=None, ge=1, le=200, description="Largest |delta| one actuation may request."
    )
    # --- selector ---
    options: list[SelectorOption] | None = Field(default=None, min_length=2)
    # --- provenance (D10) ---
    verified_on: date = Field(
        description="Date the entry was read-back confirmed on a live sim. Required."
    )
    live_sweep: bool = Field(
        default=True,
        description="False when the generic live sweep must not flip this control "
        "(battery off, start levers, TO/GA). Requires live_sweep_note.",
    )
    live_sweep_note: str | None = Field(default=None, max_length=120)
```

Per-kind field rules, enforced by a `model_validator(mode="after")` on `CockpitControlSpec`:

| kind | required | forbidden | `readable` |
|---|---|---|---|
| `toggle` | — | `unit`, `min_value`, `max_value`, `step`, `max_delta`, `options` | `True` |
| `press` | — | everything above plus `on_label`/`off_label` must be defaults | `False` |
| `dial` | `unit`, `min_value`, `max_value`, `step` (`min < max`) | `max_delta`, `options` | `True` |
| `encoder` | `unit`, `step`, `max_delta` | `min_value`, `max_value`, `options` | binding-dependent |
| `selector` | `options` (values unique, labels unique) | `unit`, `min_value`, `max_value`, `step`, `max_delta` | `True` |

`live_sweep=False` without `live_sweep_note` is a validation error.

### 3.2 The file-side models — binding and document

```python
class CockpitBinding(BaseModel):
    """Adapter-private. Every field is an OPAQUE string to core/ (D3): a dataref path, a
    command path, an MSFS event — core validates only which fields are present per kind.
    An optional `[i]` suffix on `read`/`write` denotes an array element (adapter-parsed).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    press: str | None = None  # toggle/press: the command fired
    read: str | None = None  # toggle/dial/selector/encoder: where the state is read
    write: str | None = None  # dial/selector: where the value is written
    inc: str | None = None  # encoder/stepped selector: the "one click up" command
    dec: str | None = None  # encoder/stepped selector: the "one click down" command
    on_value: float = Field(default=1.0, description="toggle: the `read` value meaning ON.")
    settle_s: float = Field(
        default=0.0, ge=0.0, le=5.0, description="Wait before the first read-back attempt."
    )
```

Per-kind binding rules (`CockpitControlDefinition`'s validator):

| kind | required | optional | forbidden |
|---|---|---|---|
| `toggle` | `press`, `read` | `on_value`, `settle_s` | `write`, `inc`, `dec` |
| `press` | `press` | `settle_s` | `read`, `write`, `inc`, `dec` |
| `dial` | `write` | `read` (defaults to `write`), `settle_s` | `press`, `inc`, `dec` |
| `encoder` | `inc`, `dec` | `read` (→ `readable=True`), `settle_s` | `press`, `write` |
| `selector` | `read`, and exactly one of {`write`} or {`inc` and `dec`} | `settle_s` | `press` |

```python
class CockpitControlDefinition(CockpitControlSpec):
    """A spec plus its binding — what a catalog FILE contains. `readable` is not written
    in files; the loader derives it from the binding and rejects a file that states it."""

    binding: CockpitBinding

    @property
    def spec(self) -> CockpitControlSpec: ...  # the published half, binding dropped


class CockpitDetection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    dataref_exists: str = Field(
        min_length=1, description="Opaque to core/: the adapter probes this name per-name (D5)."
    )


class CockpitAircraft(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    catalog_id: str = Field(pattern=CATALOG_ID_PATTERN)
    label: str = Field(min_length=1, max_length=60)  # "Zibo Mod B737-800X"
    path_hints: list[str] = Field(
        default_factory=list,
        description="Substrings of the sim's aircraft path that suggest this "
        "aircraft is loaded. NEVER used for detection — only so a live test "
        "can fail loudly when the aircraft looks loaded but the probe is "
        "negative (§8.4), and for the manifest's detection note.",
    )
    verified_against: str | None = Field(
        default=None, max_length=120
    )  # "Zibo 4.05.33, X-Plane 12.4.3"


class ParkedControl(BaseModel):
    """Exists on the aircraft, has no verified mapping (D10). Rendered disabled with the reason."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    control_id: str = Field(pattern=CONTROL_ID_PATTERN)
    label: str = Field(min_length=1, max_length=60)
    panel_id: str = Field(pattern=CONTROL_ID_PATTERN)
    reason: str = Field(min_length=1, max_length=200)
    since: date


class CockpitCatalogDocument(BaseModel):
    """One aircraft's whole catalog, after the loader has merged its directory (D4)."""

    model_config = ConfigDict(frozen=True)

    aircraft: CockpitAircraft
    detect: CockpitDetection
    panels: list[CockpitPanel] = Field(min_length=1)
    controls: list[CockpitControlDefinition] = Field(default_factory=list)
    parked: list[ParkedControl] = Field(default_factory=list)
    setup_overrides: dict[str, str] = Field(
        default_factory=dict,
        description="AircraftSetup field name -> control_id (D11). A bool field maps to a toggle, "
        "a float field to a dial.",
    )
```

Document-level validation (`model_validator`): `panel_id`s unique; every `controls[*].panel_id`
and `parked[*].panel_id` names a panel; `control_id`s unique across `controls` **and** `parked`;
every `ControlCondition.control_id` names a control with `readable=True`; the `equals` value is
type-compatible with that control's kind (toggle → bool, selector → one of its option values,
dial → float); the precondition graph is acyclic; every `setup_overrides` key is in
`AircraftSetup.model_fields` and the target control's kind matches the field's type. Sections
`panels`/`controls`/`parked`/`setup_overrides` may be spread across files (§6.1).

### 3.3 State and actuation — the wire models

```python
class CockpitControlState(BaseModel):
    model_config = ConfigDict(frozen=True)
    control_id: str
    value: CockpitValue | None = Field(
        description="None for a control that is not readable, or "
        "whose read failed — 'unknown' is an answer."
    )


class CockpitStateSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    catalog_id: str | None = Field(description="None when no catalog is active.")
    revision: int = Field(ge=0)
    states: list[CockpitControlState]


class CockpitActuation(BaseModel):
    """One instructor intent. `value` for toggle/dial/selector, `delta` for encoder, neither for press."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    control_id: str = Field(pattern=CONTROL_ID_PATTERN)
    value: CockpitValue | None = None
    delta: int | None = Field(default=None, description="Signed click count for an encoder.")

    @model_validator(mode="after")
    def _one_intent(self) -> "CockpitActuation":
        if self.value is not None and self.delta is not None:
            raise ValueError("An actuation carries either value or delta, never both.")
        return self


class CockpitActuationResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    requested: CockpitActuation
    state: CockpitControlState = Field(
        description="The CONFIRMED state read back after the write. "
        "value=None only for press, or an encoder without a read binding."
    )
    actions_taken: int = Field(
        ge=0,
        description="Presses/writes performed. 0 means the control was "
        "already in the requested state — the guarded-toggle rule made visible.",
    )
    catalog_id: str
    revision: int
```

### 3.4 The manifest

```python
class CockpitCatalog(BaseModel):
    """What SimAdapter.get_cockpit_catalog() answers. Binding-free (D3)."""

    model_config = ConfigDict(frozen=True)

    supported: bool = Field(description="The adapter declares can_control_cockpit.")
    reason: str | None = Field(
        description="Why nothing is actuable: no flag, or no catalog detected "
        "for the loaded aircraft. None when `aircraft` is set."
    )
    aircraft: CockpitAircraft | None
    revision: int = Field(
        ge=0, description="Bumped on every (re)detection. 0 before any detection."
    )
    detection_note: str | None = Field(
        description="Human text: what was probed and what the sim's "
        "aircraft path currently reads, e.g. 'Probed laminar/… — found; "
        "aircraft path Aircraft/B737-800X/b738.acf'."
    )
    panels: list[CockpitPanel]
    controls: list[CockpitControlSpec]
    parked: list[ParkedControl]


class CockpitCatalogManifest(CockpitCatalog):
    """The REST shape: the catalog plus the adapter's name (the CameraManifest precedent)."""

    adapter: str
```

`detection_note` may contain a dataref name — it is human diagnostic text produced by the
adapter, the same way `CameraViewSupport.reason` names the candidate command; `core/` never
parses it.

### 3.5 Exceptions — `core/cockpit/errors.py`

```python
class CockpitCatalogInactive(RuntimeError): ...  # no aircraft catalog detected → 409


class CockpitControlUnknown(LookupError):  # id not in the active catalog → 404
    def __init__(self, control_id: str, parked_reason: str | None = None) -> None: ...


class CockpitPreconditionUnmet(RuntimeError):  # → 409
    def __init__(self, control_id: str, hints: tuple[str, ...]) -> None: ...


class CockpitWriteRejected(RuntimeError): ...  # read-back disagreed → 502 (WeatherRejected posture)
```

Adapter-agnostic on purpose, exactly `WeatherRejected`'s reasoning: the router maps types, never an
adapter's own subclass.

---

## 4. `SimAdapter` / `Capabilities` additions

**This is a shared-foundation change. It is made once, alone, by one agent, on one branch, before
any dependent work branches off it, and is never parallelised** with any other change to
`core/sim_adapter.py`, `adapters/fake/fake_adapter.py` or `tests/adapters/test_contract.py`
(CLAUDE.md parallelisation policy). Two of the suite's own structural tests make the split
*mechanically* impossible to do otherwise: `test_every_capability_is_covered` fails the moment
the flag exists without a `CAPABILITY_COVERAGE` entry, and `test_fake_adapter_declares_every_capability`
fails unless the Fake declares it. Flag, Fake behaviour and contract tests are one PR.

**One new flag:**

```python
#: The adapter carries the per-aircraft cockpit control catalog machinery
#: (docs/designs/cockpit-control-catalog.md D1): it can detect a catalogued
#: aircraft, read control states back and actuate controls by kind. A STATIC
#: declaration — which catalog (if any) is active for the loaded aircraft is
#: manifest state on get_cockpit_catalog(), never this flag: an aircraft swap
#: mid-session bumps the manifest's revision and leaves this untouched.
can_control_cockpit: bool = False
```

**Four methods** added to the `SimAdapter` protocol:

```python
async def get_cockpit_catalog(self) -> CockpitCatalog:
    """The active per-aircraft control catalog, binding-free. A capability-free
    read (the get_failure_support posture): an adapter without
    can_control_cockpit answers supported=False with a reason and empty lists;
    one WITH the flag but no catalog for the loaded aircraft answers
    aircraft=None with a reason. "No" is an answer, never an exception.
    Runs the adapter's aircraft-change check first (D7), so the answer is for
    the aircraft loaded NOW."""


async def refresh_cockpit_catalog(self) -> CockpitCatalog:
    """Force re-detection: re-probe, drop every cached binding id, bump the
    revision even when the same catalog is detected again. Idempotent.
    Requires can_control_cockpit."""


async def read_cockpit_states(
    self, control_ids: Sequence[str] | None = None
) -> CockpitStateSnapshot:
    """Confirmed values of the readable controls named — or of every readable
    control when None — read from the simulator now, never from a ledger of
    what was asked for (the get_active_failures lesson). A control that is not
    readable, or whose read fails, reports value=None rather than raising.
    Raises CockpitControlUnknown for an id outside the active catalog. With no
    active catalog returns catalog_id=None and no states. Requires
    can_control_cockpit."""


async def actuate_cockpit_control(self, actuation: CockpitActuation) -> CockpitActuationResult:
    """One actuation, by kind (D2), CONFIRMED by read-back before returning (D8):

    * toggle  — read the status first; press only if it disagrees with the
                requested bool (research §1: these are edges, not sets);
                read back; actions_taken is 0 or 1.
    * press   — fire once; actions_taken 1; state.value None.
    * dial    — write, wait settle_s, read the designated read binding back
                within readback_tolerance.
    * encoder — fire inc/dec |delta| times; read back when readable.
    * selector — write the value, or step inc/dec towards it (bounded by the
                option count, never wrapping), reading back after each step.

    Preconditions (D9) are evaluated against a fresh read of the referenced
    controls immediately before acting; unmet → CockpitPreconditionUnmet,
    nothing written. Raises CockpitCatalogInactive with no active catalog,
    CockpitControlUnknown for an unknown/parked id, ValueError for a kind/
    value mismatch (core.cockpit.actuation.validate_actuation), and
    CockpitWriteRejected when the read-back disagrees after the adapter's
    retry window. Requires can_control_cockpit."""
```

### 4.1 What `FakeSimAdapter` must do

- Declare `can_control_cockpit=True` in `_ALL_CAPABILITIES`.
- Hold `self._cockpit_document: CockpitCatalogDocument | None = FAKE_COCKPIT_CATALOG`,
  `self._cockpit_values: dict[str, CockpitValue]` seeded from `FAKE_COCKPIT_INITIAL_VALUES`,
  `self._cockpit_revision: int = 1`, and `self._cockpit_presses: list[str]` (press log).
- **`adapters/fake/cockpit_catalog.py`** — a Python constant (D12), `FAKE_COCKPIT_CATALOG`,
  catalog id `fake-trainer`, label "Fake trainer", detect `dataref_exists="fake/cockpit/present"`,
  four panels (`mcp` "MCP / autopilot" 0, `overhead` "Overhead" 1, `pedestal` "Pedestal" 2,
  `lights` "Lights" 3) and these controls (bindings are invented strings like `fake/fd/press`):

  | id | kind | panel | details | initial |
  |---|---|---|---|---|
  | `fd_capt` | toggle | mcp | on/off labels "On"/"Off" | `False` |
  | `cmd_a` | toggle | mcp | | `False` |
  | `hdg_sel` | toggle | mcp | preconditions `[{any_of: [fd_capt==True, cmd_a==True], hint: "HDG SEL needs a flight director or CMD A engaged."}]` | `False` |
  | `mcp_alt` | dial | mcp | ft, 0–50000, step 100, tolerance 0 | `5000.0` |
  | `mcp_hdg` | dial | mcp | deg, 0–360, step 1 | `90.0` |
  | `battery` | toggle | overhead | `live_sweep=False`, note "Cutting battery power breaks every later read-back." | `True` |
  | `irs_l` | selector | overhead | options `0 OFF, 1 ALIGN, 2 NAV, 3 ATT`, binding `read` + `write` | `0` |
  | `stab_trim` | encoder | pedestal | units, step 0.5, max_delta 20, binding `inc`/`dec`/`read` | `4.0` |
  | `toga` | press | pedestal | `live_sweep=False`, note "TO/GA arms thrust; not for a sweep on the ground." | — |
  | `landing_lights` | toggle | lights | | `False` |
  | `chime_test` | press | overhead | sweep-safe press control, `live_sweep=True` | — |

  Parked: `mcp_vs`, "V/S", panel `mcp`, reason "No settable vertical-speed dataref exists on the
  reference aircraft (research §6)." `setup_overrides`: `{flight_director: fd_capt,
  autopilot_master: cmd_a, autopilot_hdg: hdg_sel, target_altitude_ft: mcp_alt,
  target_heading_deg: mcp_hdg}`. Every `verified_on` is `2026-09-02`.
- `get_cockpit_catalog()`: if the flag is off → `supported=False`, reason
  `"'fake' does not declare can_control_cockpit."`, `aircraft=None`, revision 0, empty lists. If
  `_cockpit_document is None` → `supported=True`, `aircraft=None`, reason `"No cockpit catalog is
  active for the loaded aircraft."`. Otherwise the document's published projection with the
  current revision and `detection_note="Synthetic catalog; nothing was probed."`.
- `refresh_cockpit_catalog()`: raise `CapabilityNotSupported` without the flag; `revision += 1`;
  return the catalog.
- `read_cockpit_states(ids)`: gate; `CockpitControlUnknown` for an id not in `controls`;
  `value=None` for non-readable controls; otherwise `_cockpit_values[id]`.
- `actuate_cockpit_control(a)`: gate → `CockpitCatalogInactive` if no document → lookup
  (`CockpitControlUnknown`, carrying the parked reason when applicable) →
  `validate_actuation(spec, a)` → `unmet_preconditions(spec, values)` → by kind: toggle appends
  the press binding to `_cockpit_presses` **only if** `toggle_needs_press(...)` and flips the
  value; press appends; dial sets the value; encoder adds `delta * step`; selector sets the value.
  Returns the confirmed state and `actions_taken`.
- **Test affordances** (not on the protocol, the `applied_setup` precedent): `cockpit_presses`
  (read-only copy of the press log) and `load_cockpit_catalog(document: CockpitCatalogDocument |
  None) -> None`, which replaces the document, reseeds values from the document's dials/selectors
  (`min_value` / first option / `False` / `0.0`) unless `FAKE_COCKPIT_INITIAL_VALUES` covers the
  id, and bumps the revision — the CI-visible surface of "the aircraft was swapped".
- **No physics** — the value dict *is* the Fake's observable behaviour (the failures ledger
  philosophy).

### 4.2 Contract tests to add — `tests/adapters/test_contract.py`

`CAPABILITY_COVERAGE["can_control_cockpit"] = "test_actuate_toggle_round_trips"`. New module
constant `COCKPIT_READBACK_TOLERANCE = {"fake": 0.0, "xplane": None}` — `None` means "use the
entry's own `readback_tolerance`". Helper `_first_control(adapter, kind, *, live_sweep=True)`
returns the first actuable spec of that kind from the adapter's own catalog, or `None`. Every
per-kind test skips with the sentence *"<name>: the active cockpit catalog has no <kind> control
marked live_sweep"* when there is none — an **environmental** skip against a live simulator with
an uncatalogued aircraft loaded (the `grounded_adapter` precedent), stated in each docstring, and
never a skip against the Fake, whose synthetic catalog has every kind. The Zibo-specific loud
failure lives in `tests/sim/` (§8.4).

| Test | Pins |
|---|---|
| `test_cockpit_catalog_is_consistent` | Capability-free, no skip guard, every adapter. With the flag off: `supported=False`, non-empty `reason`, empty lists. With the flag on: `aircraft is None` ⇒ non-empty `reason`; `aircraft` set ⇒ `reason is None`, `revision >= 1`, control ids unique and disjoint from parked ids, every `panel_id` in `panels`, every precondition references a `readable` control, every parked entry has a reason, no control carries a binding field (the manifest is binding-free: `"binding" not in spec.model_dump()`). |
| `test_actuate_toggle_round_trips` | **The coverage entry.** First `toggle`: read `v0`; actuate `not v0` → `state.value == (not v0)`, `actions_taken == 1`; actuate `not v0` again → `actions_taken == 0` and the state unchanged (the guarded-toggle rule, research §1); restore `v0` in `finally`. |
| `test_actuate_dial_round_trips` | First `dial`: read `v0`; target = `v0 + step` if within range else `v0 - step`; actuate → `state.value == target` within tolerance; `read_cockpit_states([id])` agrees; restore in `finally`. |
| `test_actuate_selector_round_trips` | First `selector`: cycle to the option after the current one (wrapping to the first) → read back equals; restore. |
| `test_actuate_encoder_moves_by_delta` | First `encoder`: `delta=+2` then `delta=-2`; when `readable`, the read-back moved by `2*step` within tolerance and returned within tolerance; when not readable, both calls complete and `state.value is None`. |
| `test_press_control_is_accepted` | First `press` with `live_sweep=True`: actuate with neither field → `actions_taken == 1`, `state.value is None`. |
| `test_actuate_refuses_unmet_precondition` | For the first control with preconditions: drive the referenced controls to an unmet state (only if every one of them is a toggle/selector the test can restore); actuate → `CockpitPreconditionUnmet` whose message contains the group hint; the control's own state unchanged. Then satisfy one `any_of` member → the actuation succeeds. Restore everything in `finally`. Against the Fake this is exactly `hdg_sel` with `fd_capt` (research §2's finding in CI). |
| `test_read_cockpit_states_reports_requested_ids_only` | `read_cockpit_states([a, b])` returns exactly those two, in that order; `read_cockpit_states()` returns every `readable` control once; a non-readable id yields `value=None`, not an exception. |
| `test_actuate_unknown_control_raises` | `"no_such_control"` → `CockpitControlUnknown`; a parked id → `CockpitControlUnknown` whose message contains the parked reason. |
| `test_actuate_rejects_kind_mismatch` | `dial` with `value=True`, `toggle` with `delta=1`, `encoder` with `value=1.0`, `press` with `value=True`, dial value above `max_value` → `ValueError`, nothing written (state unchanged). |
| `test_refresh_bumps_the_revision` | `r0 = catalog.revision`; `refresh_cockpit_catalog()` → `revision > r0`; a second `get_cockpit_catalog()` reports the same new revision. Live: the same catalog re-detected. |
| `test_cockpit_methods_refuse_without_the_capability` | Fake-only, restricted subclass: `refresh`/`read_cockpit_states`/`actuate` raise `CapabilityNotSupported` matching `can_control_cockpit`; `get_cockpit_catalog()` answers `supported=False` with a reason. |
| `test_swapping_the_aircraft_replaces_the_catalog` | Fake-only, via `load_cockpit_catalog`: load a second synthetic document (`fake-other`, one toggle) → `catalog_id` changes, revision increases, the old ids raise `CockpitControlUnknown`; load `None` → `aircraft is None`, `read_cockpit_states()` returns `catalog_id=None`, actuate raises `CockpitCatalogInactive`. |
| `test_cockpit_state_and_result_carry_the_revision` | `read_cockpit_states().revision == get_cockpit_catalog().revision`; `actuate(...).revision` likewise — the UI's swap detector (D13). |

The whole per-kind block writes only the first control of each kind and restores it; a live run
against the Zibo touches at most six controls.

---

## 5. Dataref mapping (X-Plane)

**This section describes `adapters/xplane/` only. No dataref name appears in `core/`.** No
weather mode is involved. Nothing here needs `bridge/`.

### 5.1 Files

| File | Role |
|---|---|
| `adapters/xplane/cockpit_catalogs/README.md` | The file format, the verification method (research doc's standard), the sweep flags, and "park, don't guess". |
| `adapters/xplane/cockpit_catalogs/zibo-b738/aircraft.yaml` | **Shipped by Wave 1 Track B.** `aircraft` (`catalog_id: zibo-b738`, `label: "Zibo Mod B737-800X"`, `path_hints: ["B737-800X"]`, `verified_against: "Zibo 4.05.33, X-Plane 12.4.3, 2026-09-02"`), `detect: {dataref_exists: laminar/B738/autopilot/mcp_alt_dial}` (§7, read-back confirmed both present and absent), and the four panels. No controls. |
| `adapters/xplane/cockpit_catalogs/zibo-b738/{mcp,overhead,pedestal,lights}.yaml` | Wave 2, one issue each (D4): #222 → `mcp.yaml`; #223 → `overhead.yaml`; #224 → `pedestal.yaml` + `lights.yaml`. |
| `adapters/xplane/cockpit_controls.py` | The runtime: catalog directory loading (via `core.cockpit.catalog`), the detection probe, lazy per-name id resolution with its cache, the per-kind executors, the read-back window, the aircraft-change check. Imported by `xplane_adapter.py`; keeps that file from growing another thousand lines. |

### 5.2 Detection — the probe (D5)

```
GET /api/v2/datarefs?filter[name]=laminar/B738/autopilot/mcp_alt_dial
  200 {"data": [{"id": <int>, "name": "...", ...}]}   -> present
  404 {"error_code": "invalid_dataref_name", ...}      -> absent  (research §7, live)
```

- `_lookup_id(client, collection: Literal["datarefs", "commands"], path) -> int | None` — one
  helper for both collections, answering `None` on **404 or an empty `data` list**, raising only
  on other HTTP errors. This is #217's fix generalised (§10.1); `_lookup_command_id` becomes a
  thin wrapper.
- `connect()` gains, after the existing steps and before capabilities are frozen: load every
  catalog directory (`core.cockpit.catalog.load_all_catalogs(COCKPIT_CATALOGS_DIR)`; a directory
  that fails to load is logged and skipped, never fails the connect), then
  `await self._detect_cockpit_catalog(client)`: for each loaded document in directory order,
  probe `detect.dataref_exists`; the **first** hit is the active catalog; none → `aircraft=None`
  with reason `"No cockpit catalog matched the loaded aircraft (<acf_relative_path or 'path
  unknown'>)."`. Sets `_cockpit_revision += 1` on every detection, hit or miss.
- **Never** the full index. `connect()`'s existing `GET /api/v2/datarefs` scan stays for the
  generic `DATAREFS`; the cockpit runtime does not read it at all.
- `OPTIONAL_DATAREFS` gains `"acf_relative_path": "sim/aircraft/view/acf_relative_path"` (a
  string dataref, decoded exactly as `get_airframe` decodes `acf_icao`). Optional: a build without
  it degrades D7's cheap signal to "re-probe the detection dataref on every cockpit call", which
  is one round trip and still correct.
- `can_control_cockpit=True` on `_CAPABILITIES` **once Track B lands** (the foundation ships
  `False` with refusing stubs, the camera precedent) — a claim that the code is right, earned
  structurally per the CLAUDE.md gotcha: the probe uses the per-name lookup the research verified
  raw against the Web API, the write executors use the identical `PATCH`/`activate` calls the
  research used, and a negative probe degrades to an honest empty manifest. `pytest -m sim`
  (§8.4) settles it.

### 5.3 Binding resolution — lazy, per name (D6)

- `_cockpit_ids: dict[str, int]` keyed by binding string (path without any `[i]` suffix), filled
  on first use by `_lookup_id`, per collection: `press`/`inc`/`dec` → `commands`; `read`/`write`
  → `datarefs`. A `None` result is cached as `None` for this revision so a broken name costs one
  lookup, and the control's actuation raises `CockpitWriteRejected("… does not resolve on this
  aircraft")` — the file said it was verified; the sim disagrees; that is a 502, not a silent
  skip.
- Array element syntax `path[i]`: reads fetch the whole array and index locally; writes use the
  existing `_write_by_id(..., index=i)`.
- **A background warm-up is deliberately not designed.** With the 4.1 s/request gotcha a warm-up
  is worse than useless; without it, first-use latency is a few milliseconds per control.
- The cache is dropped wholesale on any revision bump.

### 5.4 The aircraft-change hook (D7)

`_ensure_cockpit_current()` runs at the top of `get_cockpit_catalog`, `read_cockpit_states` and
`actuate_cockpit_control`:

1. Read `acf_relative_path` (one round trip; skipped when the dataref is unavailable, in which
   case step 2 always runs).
2. If it differs from `_cockpit_last_path` (or the dataref is unavailable): re-run
   `_detect_cockpit_catalog`, clear `_cockpit_ids`, bump the revision, store the new path.

Second signal: any cockpit read/write answered `404` with `error_code` in
`{"invalid_dataref_id", "invalid_command_id"}` → run steps 2's actions unconditionally and retry
the operation **once**; a second failure propagates as `CockpitWriteRejected`. This covers a
plugin reload that re-registers datarefs under new ids without changing the path — an unverified
possibility (§10.4) that the design survives either way.

`refresh_cockpit_catalog()` = step 2 unconditionally.

### 5.5 Execution per kind (D8)

All calls are the ones the research used raw and the adapter already has:
`GET /api/v2/datarefs/{id}/value`, `PATCH /api/v2/datarefs/{id}/value {"data": v}`,
`POST /api/v2/command/{id}/activate {"duration": 0}`.

| kind | sequence |
|---|---|
| `toggle` | read `read` → `core.toggle_needs_press(current, requested, on_value)` → if needed, activate `press` → wait `settle_s` → read-back window: up to `_COCKPIT_READBACK_ATTEMPTS = 4` reads spaced `_COCKPIT_READBACK_GAP_S = 0.15` until `is_on(value, on_value) == requested`, else `CockpitWriteRejected`. |
| `press` | activate `press`; no read-back (`state.value=None`); wait `settle_s` only so a chained call sees the effect. |
| `dial` | patch `write` with `float(value)` → wait `settle_s` → read-back window on `read` (defaults to `write`) until `dial_confirmed(value, read_back, readback_tolerance)`. The window absorbs a frame of latency; it does **not** absorb the §5 speed-drum echo, which is why `read` must name `mcp_speed_dial_kts` itself in the #222 file, never `kts2`/`kts_mach`. |
| `encoder` | activate `inc` (`delta > 0`) or `dec` (`delta < 0`) `\|delta\|` times, sequentially (never concurrently — X-Plane serialises commands per frame and a burst can coalesce); read-back when `readable`, no tolerance check (an encoder's per-click effect is aircraft logic; the read is reported, not asserted). |
| `selector` | with `write`: patch then read-back window until `value == target`. With `inc`/`dec`: read current, `core.selector_steps(current_index, target_index, len(options))` signed steps, bounded, no wrap; after each step read back; stop when the target is read; more than `len(options)` steps → `CockpitWriteRejected`. |

Preconditions: `read_cockpit_states` of the referenced ids first, `core.unmet_preconditions()`,
raise before touching anything. No freeze — panel switches are not flight-model integration
variables (the `_write_autopilot` reasoning).

### 5.6 `AircraftSetup` through the catalog (D11)

`_write_autopilot(setup)` gains one branch at the top: if a catalog is active and
`plan := plan_setup_actuations(document, setup)` is non-empty, execute each actuation via the §5.5
executors in the returned order (FD/master before lateral modes, by the precondition graph —
research §2's "not field-declaration order"), then fall through to the generic path **only for
the fields the overrides did not cover**. On the stock 737-800 (negative probe) nothing changes.
The wiring is mechanism only; Wave 1 Track B tests it against a synthetic catalog in the
MockTransport suite; #222 supplies the real `setup_overrides` and the live proof.

### 5.7 The Zibo data — worked example of the file format

**This is #222's file, not Track B's.** Shown to fix the format and because every row is
read-back confirmed in the research (§1–§5). Anything not in this table is parked until retested.

```yaml
# adapters/xplane/cockpit_catalogs/zibo-b738/mcp.yaml
controls:
  - control_id: fd_capt
    label: Flight director (captain)
    panel_id: mcp
    kind: toggle
    verified_on: 2026-09-02
    binding: {press: laminar/B738/autopilot/flight_director_toggle,
              read:  laminar/B738/autopilot/flight_director_pos}
  - control_id: fd_fo
    label: Flight director (F/O)
    panel_id: mcp
    kind: toggle
    verified_on: 2026-09-02
    binding: {press: laminar/B738/autopilot/flight_director_fo_toggle,
              read:  laminar/B738/autopilot/flight_director_fo_pos}
  - control_id: cmd_a
    label: CMD A
    panel_id: mcp
    kind: toggle
    on_label: Engaged
    verified_on: 2026-09-02
    binding: {press: laminar/B738/autopilot/cmd_a_press, read: laminar/B738/autopilot/cmd_a_status}
  - control_id: cmd_b
    label: CMD B
    panel_id: mcp
    kind: toggle
    on_label: Engaged
    verified_on: 2026-09-02
    binding: {press: laminar/B738/autopilot/cmd_b_press, read: laminar/B738/autopilot/cmd_b_status}
  - control_id: ap_disconnect
    label: A/P disengage
    panel_id: mcp
    kind: press
    verified_on: 2026-09-02
    binding: {press: laminar/B738/autopilot/disconnect_button}
  - control_id: hdg_sel
    label: HDG SEL
    panel_id: mcp
    kind: toggle
    on_label: Armed
    verified_on: 2026-09-02
    preconditions:
      - any_of: [{control_id: fd_capt, equals: true}, {control_id: fd_fo, equals: true},
                 {control_id: cmd_a, equals: true}, {control_id: cmd_b, equals: true}]
        hint: HDG SEL needs a flight director or CMD engaged (the press is inert otherwise).
    binding: {press: laminar/B738/autopilot/hdg_sel_press, read: laminar/B738/autopilot/hdg_sel_status}
  - control_id: vorloc
    label: VOR LOC
    panel_id: mcp
    kind: toggle
    on_label: Armed
    verified_on: 2026-09-02
    preconditions: [<same group as hdg_sel>]
    binding: {press: laminar/B738/autopilot/vorloc_press, read: "laminar/B738/ap/nav_status[0]"}
  - control_id: app
    label: APP
    panel_id: mcp
    kind: toggle
    on_label: Armed
    verified_on: 2026-09-02
    preconditions: [<same group as hdg_sel>]
    binding: {press: laminar/B738/autopilot/app_press, read: laminar/B738/autopilot/app_status}
  - control_id: mcp_alt
    label: Altitude
    panel_id: mcp
    kind: dial
    unit: ft
    min_value: 0
    max_value: 50000
    step: 100
    verified_on: 2026-09-02
    binding: {write: laminar/B738/autopilot/mcp_alt_dial}      # read defaults to write; §3 says either reads back
  - control_id: mcp_hdg
    label: Heading
    panel_id: mcp
    kind: dial
    unit: deg
    min_value: 0
    max_value: 360
    step: 1
    verified_on: 2026-09-02
    binding: {write: laminar/B738/autopilot/mcp_hdg_dial}
  - control_id: mcp_speed
    label: IAS
    panel_id: mcp
    kind: dial
    unit: kt
    min_value: 100
    max_value: 340
    step: 1
    verified_on: 2026-09-02
    binding: {write: laminar/B738/autopilot/mcp_speed_dial_kts,
              read:  laminar/B738/autopilot/mcp_speed_dial_kts}   # explicit: NEVER kts2 / kts_mach (§5)
parked:
  - {control_id: mcp_vs, label: Vertical speed, panel_id: mcp, since: 2026-09-02,
     reason: "No settable V/S dataref exists on the Zibo; every laminar/B738/*vvi* dataref is read-only and vs_press selects the mode, not a value (research §6)."}
  - {control_id: ias_mach_changeover, label: C/O (IAS/Mach), panel_id: mcp, since: 2026-09-02,
     reason: "change_over_press produced no change in one session; retest needed before mapping (research §5)."}
  - {control_id: lnav, label: LNAV, panel_id: mcp, since: 2026-09-02,
     reason: "Confirmed to need an active FMC route; not exercised with one loaded (research §2, #215)."}
setup_overrides:
  flight_director: fd_capt
  autopilot_master: cmd_a
  autopilot_hdg: hdg_sel
  autopilot_nav: vorloc
  autopilot_app: app
  target_altitude_ft: mcp_alt
  target_heading_deg: mcp_hdg
  target_ias_kt: mcp_speed
  # target_vertical_speed_fpm deliberately absent: parked. The generic write is a no-op on the
  # Zibo too (§6) — the honest outcome is that the field does nothing here, and the UI's typed
  # Aircraft panel already says "not wired" when a field has no path.
```

Not shown: `vs_press` (selects VS mode; a toggle candidate with `vs_status` — live-confirmed in
§6's retest and eligible for #222 as `vs_mode`, distinct from the parked V/S *value*).

### 5.8 What differs on MSFS (Phase 5 target)

The binding keys are generic verbs (`press`/`read`/`write`/`inc`/`dec`); only the *values* are
sim-specific. An `adapters/msfs/cockpit_catalogs/<id>/` directory would carry `press: "K:AP_MASTER"`
(a SimConnect event), `read: "A:AUTOPILOT MASTER,bool"` (a simvar), `write: "L:..."` (an L:var
through the MobiFlight WASM module, the `bridge/`-style optional add-on). Detection would be a
simvar/`ATC MODEL` probe. Nothing in `core/`, `server/` or `ui/` changes — the roadmap's Phase 5
measure of success.

---

## 6. `core/` logic

Package `core/cockpit/`, fully unit-testable with no simulator, no adapter, no clock; file I/O is
limited to the loader reading a directory it is handed (the `core/scenarios/loader.py`
precedent).

### 6.1 `core/cockpit/catalog.py` — the loader

```python
CATALOG_ROOT_FILENAME = "aircraft.yaml"


class CockpitCatalogLoadError(Exception):
    """One directory failed to load. Carries .path and .error (ScenarioLoadError's shape)."""


def discover_catalog_dirs(root: Path) -> tuple[Path, ...]:
    """Every immediate subdirectory of root containing aircraft.yaml, sorted by name.
    A missing root is empty, not an error."""


def load_catalog_dir(directory: Path) -> CockpitCatalogDocument:
    """Merge aircraft.yaml (aircraft, detect, panels — REQUIRED here, forbidden elsewhere)
    with every other *.yaml/*.yml in the directory (controls, parked, setup_overrides —
    each optional, concatenated / dict-merged in filename order). A key appearing in the
    wrong file, a duplicate control_id or setup_overrides key across files, a directory
    name that differs from aircraft.catalog_id, or `readable` stated in a file is a
    CockpitCatalogLoadError; so is any pydantic ValidationError, wrapped."""


def load_all_catalogs(
    root: Path,
) -> tuple[tuple[CockpitCatalogDocument, ...], tuple[CockpitCatalogLoadError, ...]]:
    """Never raises on one bad directory — the scenario loader's posture."""


def publish(
    document: CockpitCatalogDocument, *, revision: int, detection_note: str | None
) -> CockpitCatalog:
    """The binding-free projection (D3): supported=True, aircraft, panels sorted by order,
    controls in file order with `spec` applied, parked, revision."""
```

### 6.2 `core/cockpit/actuation.py` — pure rules

```python
def validate_actuation(spec: CockpitControlSpec, actuation: CockpitActuation) -> None:
    """Raise ValueError with a one-sentence reason on any kind/value mismatch (§2.2)."""


def is_on(value: CockpitValue | None, on_value: float) -> bool:
    """A toggle's status as a bool. bool passes through; numbers compare to on_value
    with a 1e-6 tolerance; None and strings are False."""


def toggle_needs_press(current: CockpitValue | None, requested: bool, on_value: float) -> bool:
    """Research §1: press only when the read state disagrees. An unknown current (None)
    counts as disagreeing — one press is the safest guess, and the read-back decides."""


def dial_confirmed(written: float, read_back: CockpitValue | None, tolerance: float) -> bool:
    """abs(read_back - written) <= tolerance; a None or non-numeric read is never confirmed."""


def selector_index(spec: CockpitControlSpec, value: CockpitValue | None) -> int | None:
    """Position of value among spec.options, or None."""


def selector_steps(current_index: int, target_index: int, option_count: int) -> int:
    """Signed clicks from current to target with NO wrap-around (a rotary selector has stops).
    Raises ValueError for indices outside [0, option_count)."""


def plan_setup_actuations(
    document: CockpitCatalogDocument, setup: AircraftSetup
) -> tuple[CockpitActuation, ...]:
    """Every set AircraftSetup field with an entry in setup_overrides, as actuations,
    ordered so that any control appearing in another planned control's preconditions
    comes first (stable topological order over the precondition graph; ties keep
    setup_overrides declaration order). A bool field becomes value=bool, a float field
    value=float. Fields set to None are absent (None means untouched)."""
```

### 6.3 `core/cockpit/preconditions.py`

```python
def unmet_preconditions(
    spec: CockpitControlSpec, states: Mapping[str, CockpitValue | None]
) -> tuple[PreconditionGroup, ...]:
    """Every group with no satisfied member. A referenced control missing from `states`
    or reading None is unsatisfied (unknown is not a pass). Numeric equals uses
    is_on()'s tolerance for floats; bools and strings compare exactly."""


def precondition_order(
    document: CockpitCatalogDocument, control_ids: Iterable[str]
) -> tuple[str, ...]:
    """Topological order of control_ids over the document's precondition edges
    (dependency first). Raises ValueError on a cycle — also rejected at load time."""


def referenced_control_ids(spec: CockpitControlSpec) -> frozenset[str]:
    """The ids an actuation of spec must read first."""
```

### 6.4 `core/cockpit/models.py`, `core/cockpit/errors.py`

Everything in §3.

---

## 7. UI panel outline

`ui/src/features/cockpit/` — a new tab of the Instructor Panel, id `cockpit`, label "Cockpit".
Adding it touches the four shared registry files every manager touches and nothing else:
`ui/src/components/tabs.ts` (one entry — shipped `gated: true` like every recent tab, lifted by
#253 once the schematic view landed), `ui/src/store/index.ts`
(one reducer), `ui/src/store/uiSlice.ts` (`TabId` union), and the `tagTypes` list in
`ui/src/api/instructorApi.ts` (two tags — the file itself records that `injectEndpoints` cannot
add one). The foundation PR already adds the type aliases to `ui/src/api/models.ts`.

### 7.1 Components

| File | Role |
|---|---|
| `CockpitPanel.tsx` | The tab: gate → aircraft banner → search → panel picker → Schematic / List toggle → either the schematic board + tray or the flat control list (+ parked rows). Owns the one `useRotaryDraft` shared by the slot under the wheel and the tray's editor, and the one write (#253). |
| `AircraftBanner.tsx` | `aircraft.label` + `detection_note`, or the manifest `reason` with a "Re-detect aircraft" button (`refreshCockpitCatalog`). Shows the revision as a small stale-state indicator when a snapshot's revision disagrees with the catalog's. |
| `PanelPicker.tsx` | Horizontal segmented buttons from `panels` (sorted by `order`), ≥ 44 px, scrollable on narrow tablets. Selection is client state. |
| `ControlSearch.tsx` | One text input filtering by label/id across **all** panels; a non-empty search flattens the picker into "Search results". |
| `ControlList.tsx` | Rows for the selected panel (or the search hits), each a `ControlRow`. Virtualisation is not needed at a few hundred rows of simple DOM; revisit only if measured. |
| `ControlRow.tsx` | Label, hint, unmet-precondition hint (client-computed from the snapshot with the same `any_of` rule, informational — the server's 409 is the gate), and the kind widget. |
| `ViewModeToggle.tsx` | Schematic / List radio group (≥ 44 px per option). Hidden while a search is active — hits span panels, only the list can show them; disabled with "No schematic for {aircraft}" when the catalog id has no layout (#253). |
| `layouts/` | Position-only tables keyed by `control_id` (`types.ts` contract, `index.ts` registry with `layoutFor(catalog_id)` / `slotIndex` / `slotRect`, `fake-trainer.ts`, `zibo-b738/{mcp,overhead,pedestal,lights}.ts`). Detents, readout formats (`khz` = MHz×100, `octal` squawk) and spring-back positions are checked-in table data — never parsed from a catalog `hint` or `unit`. `zibo-b738/ids.ts` pins the 73 + 20 catalog ids; a control the layout does not place still renders in a "Not on the diagram" strip, a slot the catalog no longer publishes is simply not drawn (#253). |
| `SchematicPanel.tsx` | One panel as a board: `splitByLayout` → one glyph + one HTML overlay per placed control, the unplaced strip as a plain `ControlList`. Owns no state. |
| `SchematicSvg.tsx`, `glyphs.tsx` | The `aria-hidden` `<svg viewBox>`: decorations plus one glyph per slot (`Pushbutton`, `Knob`, `Rocker`, `RotarySelector` — pointer at the **option index**, never the value —, `Lever`, `Display`) with `data-state="on\|off\|unknown\|parked\|pending\|unmet"`. No SVG `<text>`: labels are HTML overlays with `clamp()` sizes (the `CircuitDiagram` lesson). |
| `SchematicSlot.tsx` | The HTML overlay at the slot's `%` box: caption, `<output>` with the **confirmed** value, a draft line only while this control's draft is dirty, and the 44 px transparent hit target (`touch-action: none`). Toggles, presses and two-position selectors commit on tap; rotaries and wider selectors focus the tray; the wheel and `ArrowUp/Down`, `PageUp/Down`, `Home/End` edit the shared draft, `Enter` commits it, `Escape` discards. Parked → `aria-disabled` + the reason as `title`. |
| `SchematicTray.tsx` | Sticky under the board: the full `ControlRow` for the focused control (this is where the rotary `[−][field][+] Set` editor lives — it cannot fit inside a knob slot on a tablet), `ParkedRow` with the reason for a parked one, "Tap a control on the diagram" otherwise. |
| `widgets/ToggleControl.tsx` | A two-state switch showing the **confirmed** value; locked with a spinner while pending; the optimistic value is never shown as confirmed (#221's acceptance). |
| `widgets/PressControl.tsx` | One button; brief "sent" flash on success. |
| `widgets/RotaryControl.tsx` | Dial **and** encoder (replaced `DialControl`/`EncoderControl` in #253). `<output>` with the confirmed value, a `[−step][field][+step]` row, `Set` and `Discard`. The mouse wheel (native non-passive listener, 50 px per notch, scroll-up = increase), the arrow/Page/Home/End keys and the `±` buttons only ever edit a **draft**; exactly one write leaves on `Enter`/`Set` — the Aircraft panel's stepper discipline extended to the wheel: no notch ever moves the student. Dial: clamped or wrapped into range, snapped to the layout's detents. Encoder: notches accumulate into one `{ delta }` saturating at `±max_delta` (hold-to-repeat via `useRepeatPress` on the draft only), so a trim change is one request instead of one per tick — a deliberate change from the original one-POST-per-click design. The draft clears on commit; a failed write surfaces through the panel's error banner. |
| `widgets/useRotaryDraft.ts`, `widgets/rotary.ts`, `widgets/useWheelNotches.ts` | The draft hook (`RotaryDraftHandle`: every mutation carries its `spec`, a different `control_id` starts a fresh draft so a notch on an unfocused knob lands on that knob), the pure maths (`clampOrWrap`, `snapToDetent`, `nudgeDial`, `nudgeEncoder`, `formatValue`, `wheelNotches`) and the wheel listener. |
| `widgets/SelectorControl.tsx` | A segmented control of `options`; the confirmed option highlighted. |
| `ParkedRow.tsx` | Disabled row with the `reason` inline — never hidden (hard rule 3, the Failures panel's disabled-with-reason pattern). |
| `gate.ts` | `cockpitGate(capabilities, isError)` — fail-closed, the `cameraGate` pattern verbatim. |
| `filter.ts` | Pure: `visibleControls(catalog, panelId, search)`, `unmetHints(spec, snapshot)`, `splitByLayout(controls, parked, slots)`, `selectedOptionIndex(spec, value)` (numeric tolerance shared with the precondition rule, so a float read-back never leaves the glyph and the selector pointing at different stops). |
| `fixtures.ts` | Deterministic catalog/snapshot fixtures mirroring the Fake's synthetic catalog (§4.1), typed from `schema.d.ts`. |
| `cockpitSlice.ts`, `cockpitApi.ts` | Below. |
| `cockpit.css`, `schematic.css` | Tablet-first: rows ≥ 48 px, sticky picker + search; the board is a container-query fitted box with `aspect-ratio` and a `minWidthPx` below which it scrolls horizontally rather than shrinking hit targets under 44 px. Custom properties only — both themes are a value swap. |

Tablet-first: "engage CMD A" is picker tap + one switch tap; "set MCP altitude 4000" is picker tap
+ knob tap + type (or wheel) + Set — inside the feature spec's two-tap budget for the common
actions. Search, List mode and an aircraft without a layout all fall back to the flat list.

### 7.2 State — one RTK slice + injected endpoints

`cockpitApi.ts` uses `instructorApi.injectEndpoints` with tags `CockpitCatalog`, `CockpitState`:

- `getCockpitCatalog` (query, `providesTags: ['CockpitCatalog']`),
- `getCockpitState` (query, arg `{ panel?: string }`, `providesTags: ['CockpitState']`;
  `pollingInterval: 2000` set **by the component** and only while the tab is visible and a
  catalog is active — the `getNavdataStatus` reasoning),
- `actuateCockpitControl` (mutation; on success `updateQueryData('getCockpitState', …)` with the
  confirmed `state` so the row reflects the read-back immediately; if `result.revision` differs
  from the cached catalog's, `invalidatesTags: ['CockpitCatalog', 'CockpitState']`),
- `refreshCockpitCatalog` (mutation, invalidates both tags).

`cockpitSlice.ts` holds **client state only**:

```ts
interface CockpitState {
  selectedPanelId: string | null;          // null = first panel by order
  viewMode: 'schematic' | 'list';          // how the instructor likes the cockpit drawn (#253)
  focusedControlId: string | null;         // the slot the schematic tray is editing (#253)
  search: string;
  pending: Record<string, true>;           // control_id -> a write is in flight (locks the widget)
  lastError: string | null;                // the last 409/422/502 detail, shown once at the top
}
```

Reducers: `panelSelected` (also clears the focus), `viewModeSet` (also clears the focus),
`slotFocused`, `searchChanged`, `actuationStarted`, `actuationSettled` (success or failure — both
unlock), `errorDismissed`, and an `extraReducers` case on `telemetryCleared` resetting everything
**except `viewMode`** (the `aircraftSlice` precedent: a lost link makes every belief stale — the
view mode is a preference, not a belief about the sim). The rotary draft is deliberately not in
the store: it is transient text tied to one widget's lifetime (`useRotaryDraft`).

All API types come from the regenerated `ui/src/api/schema.d.ts`; `CockpitControlKind` and
`CockpitUnit` arrive as closed unions.

### 7.3 Capability gating, restated

- Tab-level: `can_control_cockpit` via `cockpitGate`, fail-closed.
- Catalog-level: `supported=false` or `aircraft=null` → the banner with `reason` and the
  re-detect button; no widgets.
- Row-level: `parked` entries disabled with their reason; controls with unmet preconditions stay
  **enabled** (the server decides) but show the hint — an instructor may intend to satisfy it
  next.

---

## 8. Test plan

Everything except §8.4 runs in CI against `FakeSimAdapter` or an `httpx.MockTransport`. No
navdata, no simulator-derived fixtures: the only fixtures are hand-written YAML with invented
binding strings and the Fake's Python constant.

### 8.1 `core/` unit tests — `tests/core/test_cockpit_models.py`, `test_cockpit_catalog.py`, `test_cockpit_actuation.py`, `test_cockpit_preconditions.py`

Fixture directory `tests/core/fixtures/cockpit/` containing `fake-trainer/{aircraft.yaml,
mcp.yaml, overhead.yaml}` (the Fake's catalog in file form, bindings `fake/...`) plus broken
variants, each one directory: `dup-id/` (same id in two files), `no-root/` (no `aircraft.yaml`),
`bad-panel/` (control references an undefined panel), `pre-unreadable/` (precondition on a
`press`), `cycle/` (a→b→a preconditions), `bad-override/` (`setup_overrides: {no_such_field: x}`),
`readable-stated/` (a file writes `readable: true`), `id-mismatch/` (directory `foo`, catalog id
`bar`).

Concrete reference values:

- `selector_steps(0, 3, 4) == 3`; `selector_steps(3, 0, 4) == -3`; `selector_steps(2, 2, 4) == 0`;
  `selector_steps(3, 0, 4)` is **not** `+1` (no wrap); `selector_steps(4, 0, 4)` → `ValueError`.
- `toggle_needs_press(1.0, True, 1.0) is False`; `toggle_needs_press(0, True, 1.0) is True`;
  `toggle_needs_press(None, False, 1.0) is True`; `toggle_needs_press(True, True, 1.0) is False`.
- `dial_confirmed(4000.0, 4000, 0.0) is True` (research §3's altitude); `dial_confirmed(160.0, 104,
  0.0) is False` (research §5's drum echo — the case the read binding rule exists for);
  `dial_confirmed(316.0, 316.0000001, 0.0) is False` and `True` with tolerance `0.01`;
  `dial_confirmed(1.0, None, 5.0) is False`.
- `is_on(1, 1.0) is True`; `is_on(0.9999999, 1.0) is True`; `is_on("1", 1.0) is False`.
- `validate_actuation`: every row of §2.2 raises `ValueError`; `dial` value `50000` (== max) is
  valid; `dial` value `3550` with step 100 is valid (step not enforced); `encoder` `delta=-20`
  with `max_delta=20` valid, `-21` raises; `selector` value `"NAV"` when options are ints raises.
- `unmet_preconditions(hdg_sel, {fd_capt: False, cmd_a: False}) == (group,)`; with `cmd_a: True`
  → `()`; with `fd_capt: None` and `cmd_a` missing → `(group,)` (unknown is not a pass).
- `plan_setup_actuations(doc, AircraftSetup(autopilot_hdg=True, flight_director=True))` returns
  `(fd_capt=True, hdg_sel=True)` **in that order** regardless of `setup_overrides` declaration
  order; `AircraftSetup(target_altitude_ft=4000)` → `(mcp_alt value=4000.0)`; an empty setup →
  `()`; a field with no override → absent.
- `precondition_order(doc, ["hdg_sel", "fd_capt"]) == ("fd_capt", "hdg_sel")`; the `cycle/`
  fixture raises at load.
- Loader: `fake-trainer` loads with exactly 11 controls (10 + `chime_test`), 1 parked, 4 panels,
  `readable` is `False` for `toga`/`chime_test`, `True` for `stab_trim` (has `read`); each broken
  directory raises `CockpitCatalogLoadError` naming the file; `load_all_catalogs` over the whole
  fixture root returns one document and the expected number of errors; a missing root returns
  `((), ())`.
- `publish(doc, revision=3, detection_note=None)`: no control's dump contains `"binding"`;
  panels sorted by `order`; `revision == 3`.
- Models: `CockpitActuation(control_id="x", value=1, delta=1)` raises; `CockpitControlSpec` per-kind
  rules table (one test per forbidden/required cell); `live_sweep=False` without a note raises.
- **Consistency guard**: `FAKE_COCKPIT_CATALOG` (the Python constant) equals
  `load_catalog_dir(fixtures/fake-trainer)` field-for-field, so the YAML fixture and the Fake can
  never drift.

### 8.2 Contract tests

The suite of §4.2, parametrised over both adapters, written by the tester from this document
before the implementation exists.

### 8.3 Server tests — `tests/server/test_cockpit_routes.py`

Against `TestClient` + `FakeSimAdapter`, `reset_adapter()` between tests:

- `GET /catalog` → 200, `adapter == "fake"`, `supported`, 11 controls, 1 parked, 4 panels, no
  `binding` key anywhere in the JSON, `revision >= 1`.
- `GET /state?panel=mcp` → only `mcp`'s readable ids (5); `GET /state` → every readable id;
  `panel=nope` → 404.
- `POST /actuate {fd_capt, true}` → 200, `actions_taken 1`, `state.value true`; again → 200,
  `actions_taken 0`.
- `{hdg_sel, true}` with FD off → 409 whose detail contains "flight director"; after `fd_capt` on
  → 200.
- `{mcp_alt, 60000}` → 422; `{mcp_alt, true}` → 422; `{stab_trim, delta: 2}` → 200 and the value
  moved by `1.0`; `{toga}` → 200 `state.value null`.
- `{mcp_vs, true}` → 404 whose detail contains "parked"; `{ghost, true}` → 404.
- After `adapter.load_cockpit_catalog(None)` (via `server.deps.get_adapter()`): `/catalog` 200
  with `aircraft null` + reason, `/state` 200 empty, `/actuate` 409.
- `POST /catalog/refresh` → 200, revision incremented.
- A `NoCockpitAdapter` subclass (flag off): `/catalog` 200 `supported false`; `/state`,
  `/actuate`, `/catalog/refresh` → 501.
- A Fake subclass whose `actuate_cockpit_control` raises `CockpitWriteRejected("…")` → 502 with
  that sentence.

### 8.4 X-Plane in CI — `tests/adapters/test_xplane_cockpit.py` (MockTransport, the `test_xplane_camera.py` shape)

`_FakeWebApi` extended to script *aircraft*: a set of published dataref names, a set of command
names, a value store, an `acf_relative_path` string, a `swap_to(...)` method, and — **corrected
from the camera mock** — a `filter[name]` miss answers **404** `{"error_code":
"invalid_dataref_name" | "invalid_command_name"}`, and a read/write on a retired id answers 404
`invalid_dataref_id`/`invalid_command_id`. Uses a temporary catalog root (monkeypatched
`COCKPIT_CATALOGS_DIR`) holding the `fake-trainer` fixture directory with **fake-namespaced** names
(`fake/...`) the mock publishes; no `laminar/*` names in CI.

- Probe positive → `aircraft.catalog_id == "fake-trainer"`, revision 1; probe negative (name
  unpublished → 404) → `aircraft is None`, reason names the path; the full index endpoint
  **is not requested** by the cockpit runtime (assert on the request log after connect's own
  scan).
- Lazy resolution: after connect, zero `filter[name]` requests for bindings; the first toggle
  actuation issues exactly two lookups (`press`, `read`) and the second issues none.
- Toggle: with the status already `1`, actuating `True` issues **no** `activate` and one read;
  with `0`, one activate; the mock flips the status on activate.
- Dial: one `PATCH` then reads until the value matches; a mock that echoes a *different* value
  → `CockpitWriteRejected` after exactly `_COCKPIT_READBACK_ATTEMPTS` reads.
- Selector with `inc`/`dec`: from index 0 to 3 issues 3 `inc` activations, each followed by a
  read; from 3 to 0, 3 `dec`.
- Encoder: `delta=-3` → 3 sequential `dec` activations.
- Precondition: `hdg_sel` with `fd_capt` status `0` → `CockpitPreconditionUnmet`, no activate.
- Aircraft change by path: `swap_to(path="Other/plane.acf", published=…)` → the next
  `get_cockpit_catalog()` re-probes, revision 2, ids cache empty (next actuation looks up again).
- Aircraft change by stale id: same path, ids retired → the first actuation gets 404, re-detects,
  retries once, succeeds; revision bumped once.
- `refresh_cockpit_catalog()` → one probe request, revision +1, cache cleared.
- `acf_relative_path` unpublished → every cockpit call re-probes (one `filter[name]` per call) and
  still works.
- `_write_autopilot` with an active synthetic catalog and `AircraftSetup(autopilot_hdg=True,
  flight_director=True)` → activations in the order `fd_capt.press`, `hdg_sel.press` and **no**
  generic `sim/autopilot/heading` activation; with no active catalog → the generic path unchanged
  (the existing `test_xplane_autopilot.py` expectations still hold).
- `_lookup_id` answers `None` on 404 and on `{"data": []}`, raises on 500 (#217's regression
  test lives in the bug PR against the camera mock; this one covers the generalised helper).
- Catalog file smoke, parametrised over every directory under the real
  `adapters/xplane/cockpit_catalogs/`: loads without error; every `verified_on` ≤ today; every
  binding string starts with `sim/` or `laminar/` (or the catalog's declared namespace); the Zibo
  root's `detect.dataref_exists == "laminar/B738/autopilot/mcp_alt_dial"`. This is the CI gate
  Wave 2's data PRs run against.

### 8.5 `@pytest.mark.sim` — never in CI

**`tests/sim/test_live_cockpit_catalog.py`** — the generic sweep, and the honest resolution of
the deadlock gotcha:

- `test_detection_matches_the_loaded_aircraft`: read `acf_relative_path` through the adapter; for
  every catalog whose `path_hints` match the path, assert the probe **detected that catalog** —
  a Zibo that looks loaded but is not detected **fails loudly**, never skips (docstring says so);
  for a path matching no catalog, assert `aircraft is None` with a reason. Also asserts
  `can_control_cockpit is True` on the live adapter — the flag that gates its own validation
  must not be allowed to hide a negative result.
- The per-entry sweep: parametrised at collection time over every `controls[*]` of every catalog
  directory (YAML read only), ids `<catalog_id>::<panel_id>::<control_id>`, so
  `pytest -m sim tests/sim/test_live_cockpit_catalog.py -k "zibo-b738::mcp"` scopes one panel.
  At runtime: skip with reason when that catalog is not the active one (environmental);
  skip with the entry's `live_sweep_note` when `live_sweep=False`; otherwise, by kind: toggle
  flip-and-back with read-back both ways; dial `+step` then restore; selector next-option then
  restore; encoder `+1`/`-1`; press fire once (only `live_sweep=True` presses). Every restore in
  a `finally`. Run **on the ground, parked, engines running if the aircraft was loaded that way**
  — the session fixture from `tests/conftest.py` applies.
- `test_stock_aircraft_has_no_catalog_and_generic_setup_still_works`: only meaningful when the
  loaded aircraft matches no catalog; asserts the generic autopilot path (`apply_setup` heading
  dial round trip from the existing contract test) is unaffected — #222's stock-737 acceptance.

**Live verification ownership (D15, question B):** one running X-Plane is one "sim slot".
Authoring Wave 2 catalogs is parallel (three worktrees; the read-only `xplane-datarefs` MCP may be
used concurrently for *discovery*); **write verification is serialised**: each Wave 2 PR is
labelled `needs-live-validation`, and a single `sim-validator` pass per PR — in the order #222
(MCP, smallest and the research already covers it) → #223 (overhead) → #224 (pedestal/lights) —
runs `pytest -m sim tests/sim/test_live_cockpit_catalog.py -k "zibo-b738::<panel>"` plus
`test_detection_matches_the_loaded_aircraft`. Entries that fail read-back are moved to `parked`
with the observed reason before merge; the PR description lists them. Three agents driving one
simulator concurrently is forbidden — a read-back racing another agent's write is exactly the
"value written into one call, read at the other end" failure this project keeps relearning.

### 8.6 UI tests (vitest)

- `gate.test.ts` — fail-closed on loading, error, missing flag.
- `filter.test.ts` — panel scoping, search across panels, `unmetHints` on the §4.1 `hdg_sel` case.
- `ControlRow.test.tsx` — one widget per kind renders from `fixtures.ts`; a toggle shows the
  snapshot's value, not the clicked one, until the mutation resolves (assert with a deferred
  stubbed fetch); a `dial` "Set" issues exactly one `actuateCockpitControl` with
  `{control_id, value}` asserted by `toEqual`; an encoder `+` issues `{control_id, delta: 1}`.
- `ParkedRow.test.tsx` — disabled, reason visible, no click handler.
- `AircraftBanner.test.tsx` — `aircraft: null` shows the reason and the re-detect button; the
  button issues one `refreshCockpitCatalog`.
- `cockpitSlice.test.ts` — `actuationStarted`/`actuationSettled` lock/unlock; `telemetryCleared`
  resets.
- `cockpitApi.test.ts` — a result whose `revision` differs from the cached catalog's invalidates
  `CockpitCatalog`.

---

## 9. Parallelisation

### 9.1 Question A — the contract-foundation split for #220

**Foundation PR — `feature/cockpit-catalog-foundation`, one worktree, one branch, merged alone
first.** Two agents work it *sequentially* on the same branch: the **tester** first writes §8.1,
§8.2 and §8.3 from this document (red), then the **implementer** makes them green. Owns, and is
the only PR that may touch:

| Path | What |
|---|---|
| `core/cockpit/__init__.py`, `models.py`, `errors.py`, `catalog.py`, `actuation.py`, `preconditions.py` | §3, §6 |
| `core/sim_adapter.py` | the flag + four methods (§4) |
| `adapters/fake/fake_adapter.py`, `adapters/fake/cockpit_catalog.py` | §4.1 |
| `adapters/xplane/xplane_adapter.py` — **stubs only** | `can_control_cockpit=False`; `get_cockpit_catalog` → `supported=False` with reason; the three others raise `CapabilityNotSupported`. Required because `_CONFORMS: SimAdapter = XPlaneSimAdapter()` and the `runtime_checkable` Protocol (`test_satisfies_the_protocol_at_runtime`) break otherwise — the camera foundation's exact precedent. |
| `server/cockpit_routes.py`, one `include_router` line in `server/app.py` | §2 |
| `tests/adapters/test_contract.py`, `tests/core/test_cockpit_*.py`, `tests/core/fixtures/cockpit/`, `tests/server/test_cockpit_routes.py` | §4.2, §8.1, §8.3 |
| `ui/src/api/schema.d.ts` (regenerated from `create_app().openapi()`), `ui/src/api/models.ts` (aliases only) | rule 7 |

**The caller's framing ("tester extends `test_contract.py` in parallel with the UI") conflicts
with two things and is resolved here:** CLAUDE.md never parallelises contract files, and the
suite's own `test_every_capability_is_covered` makes the coverage entry inseparable from the flag.
The contract suite is therefore *inside* the foundation, written first. What the tester does
genuinely in parallel comes after the merge (Track B-tests below).

**After the foundation merges to `dev`, dispatch in one message, disjoint directories:**

**Track B — X-Plane execution (#220's second half):** `adapters/xplane/cockpit_controls.py`,
`adapters/xplane/cockpit_catalogs/README.md`, `adapters/xplane/cockpit_catalogs/zibo-b738/aircraft.yaml`,
the real implementations + `can_control_cockpit=True` + `acf_relative_path` + `_lookup_id` +
the `_write_autopilot` hook in `adapters/xplane/xplane_adapter.py`, `spikes/cockpit_probe.py`
(§10.4's spike).
Owns: `adapters/xplane/`, `spikes/`.

**Track B-tests — the tester, in parallel with Track B:** `tests/adapters/test_xplane_cockpit.py`
(§8.4) and `tests/sim/test_live_cockpit_catalog.py` (§8.5), written from §5 of this document in
its own worktree; its PR targets `dev` and merges after Track B's (CI on it is red until then,
which is the point — it is the acceptance suite for B).
Owns: `tests/adapters/test_xplane_cockpit.py`, `tests/sim/test_live_cockpit_catalog.py`.

**Track C — the panel (#221):** `ui/src/features/cockpit/*` plus the four shared registry edits
(`tabs.ts`, `store/index.ts`, `uiSlice.ts` `TabId`, `instructorApi.ts` `tagTypes`). Proceeds from
the foundation's regenerated schema and `/ui-fake` against the Fake's synthetic catalog; needs
nothing from Track B.
Owns: `ui/`.

**Track D — #217 (`bug/xplane-lookup-404`):** may run *concurrently with the foundation* (disjoint
files: the `_lookup_command_id` guard in `xplane_adapter.py` lines ~996–1001 and the camera mock
in `tests/adapters/test_xplane_camera.py` corrected to 404 + a regression test). Must merge
before Track B starts live work; Track B rebases onto it. If Track D is not merged when Track B
begins, Track B carries the identical guard and Track D closes as superseded — never two PRs
editing the same function concurrently.

### 9.2 Never parallelised, restated

The foundation's files; `core/sim_adapter.py` in any PR other than the foundation; merges to
`dev`/`main`; release tagging. No navdata schema is touched by this manager.

### 9.3 Question B — Wave 2 (#222, #223, #224)

Three worktrees, three `feature/zibo-<panel>` branches, dispatched in one message once Track B is
on `dev`. Disjoint by construction (D4):

| Issue | Owns | CI gate |
|---|---|---|
| #222 | `adapters/xplane/cockpit_catalogs/zibo-b738/mcp.yaml` (controls + parked + `setup_overrides`), `tests/adapters/test_zibo_mcp_catalog.py` (panel-specific facts: the §5.7 read binding for speed is `mcp_speed_dial_kts`; V/S, C/O and LNAV are parked; `setup_overrides` omits `target_vertical_speed_fpm`) | §8.4's catalog smoke + its own file |
| #223 | `.../overhead.yaml`, `tests/adapters/test_zibo_overhead_catalog.py` | same |
| #224 | `.../pedestal.yaml`, `.../lights.yaml`, `tests/adapters/test_zibo_pedestal_lights_catalog.py`, and a note in the PR on which generic `LightsSetup` datarefs work on the Zibo | same |

No Wave 2 issue edits `aircraft.yaml`, any `.py` under `adapters/xplane/` other than its own
test file, or anything under `core/`, `server/`, `ui/`. If a Wave 2 author finds the *machinery*
lacking (a sixth kind, a binding verb), that is a separate `feature/` PR on the foundation files,
serialised, and the data PR waits — never a machinery change smuggled into a data PR.

**Authoring parallel, verification serial** — §8.5's sim slot. Each Wave 2 PR is complete when
its file loads in CI **and** its `sim-validator` pass is green; the pass is scheduled, not raced.

---

## 10. Open questions and risks

### 10.1 Issue #217 — what the API does, and whether #217 blocks this work

**What X-Plane's Web API actually returns on a `filter[name]` miss: a 404**, for both
collections. `/api/v2/commands`: #217's live repro (`404 Not Found for url
'.../api/v2/commands?filter[name]=sim/view/3d_cockpit_cmd_look'` with the Zibo loaded).
`/api/v2/datarefs`: research §7, checked raw against the API — `"invalid_dataref_name"` once
Zibo is unloaded. **There is no dataref sibling of `_lookup_command_id` in the adapter today:**
`filter[name]` appears exactly once (`xplane_adapter.py:996`); datarefs are resolved solely by
the full-index scan in `connect()`. The detection probe is therefore *new* code and will be
written with the 404 guard from day one (§5.2's `_lookup_id`).

**Why CI never caught #217:** `tests/adapters/test_xplane_camera.py::_FakeWebApi` answers a
command miss with `200 {"data": []}` — the mock models the API wrongly, so the code's
`raise_for_status()` path was never exercised. The fix must handle **both** 404 and an empty
list, and the mock must be corrected to 404 with a regression test, or the same bug ships a
third time (the issue notes it has been fixed locally twice and lost).

**Verdict:** #217 is **not** a prerequisite for the foundation slice — the foundation touches no
X-Plane HTTP path (its X-Plane changes are refusing stubs). It **is a hard prerequisite for every
live step of this epic**: with the Zibo loaded, `connect()` aborts on the first optional camera
command miss, so no `pytest -m sim`, no Track B live check and no Wave 2 verification can run
until it lands. **Recommendation:** its own tiny `bug/` PR (Track D, §9.1), run concurrently with
the foundation, not folded into it — the foundation stays a pure contract change, and the bug
ships even if the foundation review stalls. Track B then generalises the guard into `_lookup_id`.

### 10.2 D11 moves "re-wire `AircraftSetup` through the override layer" from #222 into Wave 1 — a decision for the user

#222's text scopes the re-wiring as Wave 2 work. This design ships the *mechanism*
(`setup_overrides`, `plan_setup_actuations`, the `_write_autopilot` hook) in Track B, tested with
a synthetic catalog, and leaves #222 with *data + live proof* only. Reason: it makes all three
Wave 2 issues genuinely `parallel-ok` (pure data, zero Python outside their own test file) and
puts the one piece of ordering logic (§2's FD-before-lateral) under a CI test instead of a
live-only one. **What resolves it:** the user confirms, and #222's description is edited to say
"supplies `setup_overrides` and live-verifies `apply_setup` on the Zibo"; or the user keeps
#222's scope and Track B ships the hook disabled behind an empty override map — same code, later
wiring.

### 10.3 Whether `acf_relative_path` is exposed over the Web API as a readable string

`OPTIONAL_DATAREFS` today reads only `acf_ICAO` (a byte array). `acf_relative_path` is the same
kind of dataref and §7 read it live through the MCP, which uses the same API — high confidence,
but the adapter has never decoded it. The design degrades honestly if it is absent (§5.2), so
this is a performance question (one extra probe per call), not a correctness one. **What resolves
it:** Track B's first live run; `spikes/cockpit_probe.py` prints it.

### 10.4 Does a *fresh* full-index fetch list Zibo datarefs after swapping *to* Zibo?

§7 proves the index is stale for **absence** after swapping away. It says nothing about whether
a fresh `GET /api/v2/datarefs` after loading Zibo lists the new `laminar/*` names — the design
does not depend on the answer (D5/D6 never use the index), but a "yes" would allow a one-request
bulk pre-resolution of *present* ids on top of the per-name absence check, useful if a catalog
ever grows large enough for lazy first-use latency to be noticed. Also unverified: whether a
plugin reload re-registers datarefs under new ids without a path change (D7's second signal
exists for exactly this). **What resolves it:** `spikes/cockpit_probe.py` — swap stock → Zibo,
fetch the index, grep; reload the Zibo, compare ids.

### 10.5 No WebSocket stream for cockpit state (D13)

The live picture of the cockpit is polled per visible panel. The X-Plane adapter's own
`stream_state` already documents the intended successor ("the Web API's WebSocket … will replace
this once the subscription protocol is wired up"). When that lands for telemetry, cockpit state
subscribes to the same mechanism through a `stream_cockpit_states(interval_s)` method — a
contract addition, serialised, not designed here. **What resolves it:** a measured need; two
seconds of polling latency on a panel whose writes confirm themselves synchronously is expected
to be fine.

### 10.6 Selector semantics on Zibo are unverified in the research

The research verified toggles and dials only. Zibo selectors (IRS mode, light knobs) may be
`write`-able ints, `inc`/`dec` command pairs, or both; the schema supports both (D2), and a
selector whose kind is misjudged fails its read-back loudly rather than silently. **What resolves
it:** #223's own verification pass, the first selector to enter a catalog.

### 10.7 Encoder read-back has no assertion

By design (§5.5): an encoder's per-click effect is aircraft logic (trim units per click, V/S
wheel detents). The live sweep reports the delta observed but cannot know the right answer.
A future `step_tolerance` could tighten this once a few encoders are measured. Not worth
guessing a number now.

### 10.8 Known risks from `architecture.md` this manager touches

- **Risk 1 (repositioning / `fix_all_systems`)** — not touched; no freeze, no teleport.
- **Risk 2 (real weather)** — not touched.
- **Risk 5 (MSFS subset)** — the opaque binding block (§5.8) is the design's answer; the catalog
  format is sim-neutral, the files are per adapter.
- **New (recorded here):** a catalog entry marked `live_sweep=True` that is *not* safe to flip
  (a fuel cutoff mis-flagged) will be flipped by the sweep. Mitigated by the `finally` restore
  and by running the sweep parked on the ground; the README asks authors to err on
  `live_sweep=False`.

---

## 11. Verification

```bash
pytest && ruff check . && ruff format --check . && mypy .
cd ui && npm run lint && npm run typecheck && npm test && npm run build
```

Then, against `OIS_ADAPTER=fake` with the Vite dev server (`/ui-fake`): open the Cockpit tab →
banner shows "Fake trainer" → picker shows MCP / Overhead / Pedestal / Lights → tap HDG SEL →
409 hint "needs a flight director or CMD A" appears → tap FD on → switch confirms → tap HDG SEL →
confirms → set Altitude 4000 → confirms with the read-back value → Stab trim `+` twice → value
reads 5.0 → IRS L to NAV → confirms → V/S row is disabled with its reason → search "light" shows
Landing lights from another panel → "Re-detect aircraft" bumps the revision, plus a console
check. Live-sim validation (`pytest -m sim`, §8.5) is the `sim-validator` agent's job, serialised
per §9.3, and is not a merge gate for the foundation or the UI.
