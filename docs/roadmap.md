# Roadmap — Open Instructor Station

This document sequences the 15 managers of [`feature-spec.md`](feature-spec.md) into phases.
Each phase has a scope, the managers it delivers, and **exit criteria** that must be met before
the next phase starts.

The binding rules for all of this live in [`../CLAUDE.md`](../CLAUDE.md). This roadmap never
overrides them.

---

## Phase map

| Phase | Theme | Managers delivered | Status |
|---|---|---|---|
| **0** | Foundation | — (skeleton + contract + CI) | **Complete** |
| **1** | Position Manager + Aircraft Control | 1, 6, radios of 7 | **In progress** |
| **2** | Weather + Failures → Scenario Generator | 3, 4, 9 → 2, 14 | Planned |
| **3** | Instructor Map + AI Traffic | 5, 13, 8, 10 | Planned |
| **4** | Analysis and sessions | 11, 12, full 7 | Planned |
| **5** | Multi-sim and distribution | MSFS adapter, packaging | Planned |

Manager 15, the **Instructor Panel**, appears in no single phase: it is the UI itself and gains
one tab per phase, next to the manager that tab drives.

---

## Phase 0 — Foundation *(complete)*

Nothing user-visible. The purpose is to make every later phase cheap and to retire the project's
biggest technical unknown before any feature work starts. **Both goals met** — see the exit
criteria below.

### Scope

- **Monorepo layout** exactly as defined in `CLAUDE.md`: `core/`, `adapters/`, `server/`, `ui/`,
  `bridge/`, `spikes/`, `docs/`, `tests/`.
- **`SimAdapter` + `Capabilities` contract** — the single interface everything depends on.
- **`FakeSimAdapter`** — a full in-memory implementation of that interface. All CI tests run
  against it.
- **Minimal FastAPI server** — health, capabilities, and a **WebSocket** publishing live state.
- **Minimal RTK UI shell** — React + TypeScript strict + Redux Toolkit, connecting to the
  WebSocket and showing raw state. The seed of the Instructor Panel.
- **CI** — four required checks: `lint-py`, `test-py`, `lint-ui`, `test-ui`.
- **X-Plane connection spike** in `spikes/` — throwaway code, not imported by the app, not
  covered by tests.

### Exit criteria

1. ✅ **CI is green on `dev`** — all four checks passing.
2. ✅ **The contract suite passes against `FakeSimAdapter`** (`tests/adapters/test_contract.py`).
3. ✅ **Live repositioning in a real X-Plane 12** — validated at LEMD on 2026-08-06.

### The key technical risk: retired

Repositioning an aircraft from outside the simulator **works, with no plugin**. The measurements:

| Finding | Consequence |
|---|---|
| `latitude`/`longitude`/`elevation` are **read-only** | Write the local OpenGL frame (`local_x/y/z`) instead. The world coordinates are derived from it, which makes reading them back the honest verdict on a write. |
| `lat_ref`/`lon_ref` advertised an origin **200 km** from the real one (39.0N/6.0W vs 40.5N/4.0W) | Never trust them. The frame origin is *measured* from the aircraft, known in both coordinate systems at once — `core.local_frame.origin_from_observation`. Residual: 0.000000 m. |
| The world→local conversion normally needs plugin-only `XPLMWorldToLocal` | Done externally in `core/local_frame.py` as a rigid ECEF rotation. Not a flat-earth offset: 40 km out the tangent-plane error is ~120 m. |
| Writing zero velocity drops the aircraft below stall speed | Write the velocity vector along the target heading, never zeros. |
| X-Plane reads a teleport as an **impact** and wrecks the aircraft | Clear it with `sim/operation/fix_all_systems` as the last step. Missing this ends a training session. |

Measured on the validation run: placement exact, restore to the original position within **0.00 m**,
crash flag clear throughout. The UDP `VEHX`/`VEH1` fallback is **not needed** and stays unimplemented.

Phase 1 can therefore commit to the Position Manager knowing exactly how the aircraft moves.

---

## Phase 1 — Position Manager + Aircraft Control

**Managers: 1 (Position Manager), 6 (Aircraft Control), the radio-tuning slice of 7.**

The first phase that produces the product's reason to exist: an instructor places the aircraft
on a 10 NM ILS final and it arrives configured and flyable.

### Scope

**`NavdataProvider` in `core/`** — reads the user's own X-Plane installation. Nothing is
redistributed and nothing is committed (`CLAUDE.md`, hard rule 4).

| Source | Handling |
|---|---|
| `CIFP/<ICAO>.dat` | SID / STAR / APPCH / RWY records, ARINC 424 subset. **Parsed lazily, one file per airport** — there are thousands of them and a full parse at start-up is unacceptable. |
| `earth_fix.dat`, `earth_nav.dat`, `earth_awy.dat`, `earth_hold.dat` | Indexed into a **SQLite cache**. |
| `Global Scenery/.../apt.dat` | Airports, runways, gates and parking stands. Indexed into the same cache. |
| `cycle_info.txt` | Gives the **AIRAC cycle**, used as the **cache invalidation key**. |
| `Custom Data/` vs `Resources/default data/` | **`Custom Data/` takes precedence** when a file exists in both. |

**Positionable legs.** Only legs carrying a resolvable fix — `IF`, `TF`, `CF`, `DF`, `AF`, `RF` —
can be used as a position. Trajectory-dependent legs (`CA`, `VA`, `FM`, `VM`) are **displayed but
never offered** as placements: without knowing the aircraft's flown path there is no defensible
coordinate for them.

**Constraints come free.** Altitude and speed constraints for procedure placements are read
directly from the ARINC 424 leg data — no separate source and no guessing.

**Placements.** The full Position Manager set: 20/15/10/8/5/3 NM final, short final, base,
downwind, crosswind, gate, parking stand, arbitrary coordinate, over a waypoint, on a SID, on a
STAR, on an approach, in a holding.

**Automatic pre-teleport setup.** The complete state configuration from the feature spec:
altitude, IAS, vertical speed, heading, pitch, roll, weight, fuel, flaps, spoilers, gear,
autobrake, lights, NAV frequencies, ILS frequency and OBS course.

**Aircraft Control panel** — live read over the WebSocket, writes over REST.

### Exit criteria

1. **From a tablet, the instructor places the aircraft on a 10 NM ILS final with a coherent
   aircraft state in under 5 seconds.**
2. The navdata cache rebuilds automatically when `cycle_info.txt` reports a new AIRAC cycle.
3. Contract suite extended for every capability added (`can_set_position`, aircraft-state
   writes) and green against the Fake.
4. No navdata file of any kind is present in the repository.

---

## Phase 2 — Weather + Failures → Scenario Generator

**Managers: 3 (Weather), 4 (Failures), 9 (Fuel & Payload) → then 2 (Scenario Generator),
14 (Training Profiles).**

Three independent managers first; the Scenario Generator composes all of them and therefore
comes second.

### Scope

- **Weather Manager** — dataref mapping for wind, gusts, turbulence, pressure, temperature,
  humidity, visibility, cloud layers, rain, snow and ice, plus the presets (CAVOK, CAT I, CAT II,
  CAT III, Storm, Crosswind, Mountain Wave).
  **The adapter must force manual weather mode before writing anything** — X-Plane 12's real
  weather continuously overwrites manual settings, and every "the weather did not apply" bug
  traces back to this.
- **Failures Manager** — the sim-agnostic failure catalogue in `core/`, the dataref mapping in
  the adapter, immediate / armed / cleared modes, and a "clear all" command.
- **Fuel & Payload Manager** — fuel, passengers, cargo, weight, CG, with the Ferry / Training /
  Full / Empty presets and envelope validation.
- **Flight Scenario Generator** — the **declarative YAML** engine composing position + aircraft
  state + weather + scheduled failures (+ traffic where the capability exists), delivering all
  **12 scenarios** from the feature spec.
- **Training Profiles** — saved scenarios with metadata, exported as JSON/XML.

### Exit criteria

1. All **12 scenarios** run end to end against `FakeSimAdapter` in CI, and against a live
   X-Plane under `-m sim`.
2. **A new scenario can be added by writing a YAML file only** — demonstrated by a test that
   loads a scenario file not referenced anywhere in the code.
3. Weather written while X-Plane is in real-weather mode still applies (manual mode forced and
   verified).
4. Scenarios requiring an undeclared capability are reported as unavailable, never attempted.

---

## Phase 3 — Instructor Map + AI Traffic

**Managers: 5 (Instructor Map), 13 (AI Traffic), 8 (Pushback), 10 (Camera).**

### Scope

- **Instructor Map** — MapLibre GL with **OpenStreetMap tiles only**; live aircraft position over
  the WebSocket; runways, navaids and procedures served from the `NavdataProvider`;
  drag-to-reposition; click-to-place; distance measurement. Repositioning from the map reuses the
  Phase 1 pipeline unchanged.
- **AI Traffic** via the optional **`bridge/`** XPPython3 plugin — TCAS resolution advisories,
  runway incursions, taxi and approach traffic. Gated behind **`can_spawn_traffic`**.
  This is the **first component that runs inside the simulator**, and it stays optional:
  **everything else must still work with the bridge absent**.
- **Pushback Manager** and **Camera Manager** — small, command-shaped, independent.

### Exit criteria

1. The map shows live aircraft movement and correct runway/procedure geometry for an airport
   loaded from the user's own navdata.
2. Dragging the aircraft on the map repositions it with full automatic setup.
3. With the bridge **not installed**, the application starts, every non-traffic feature works,
   and traffic controls are disabled with a stated reason — verified by a test running against an
   adapter declaring `can_spawn_traffic = False`.
4. With the bridge installed, a TCAS RA scenario and a runway incursion scenario run in a live
   X-Plane.

---

## Phase 4 — Analysis and sessions

**Managers: 11 (Statistics & Landing Analysis), 12 (Session Recorder), 7 in full.**

### Scope

- **Landing Analysis** — recording at **10–20 Hz during the approach**, arming on approach
  detection and disarming after rollout; localizer/glideslope/centreline deviation, touchdown
  rate, G-force, pitch, roll, flare, floating, landing distance; export to CSV, PDF and JSON.
- **Session Recorder** — snapshots (position + state + weather + failures) with restore, full
  session recording, and replay.
- **Flight Plan / Navigation Helper in full** — `.fms` and `.pln` import/export, sync with
  compatible planning apps, and best-effort FMC interaction on capable aircraft.

### Exit criteria

1. A landing produces a complete report whose numbers are validated against **recorded fixture
   frames with known answers**, computed entirely in `core/` with no simulator involved.
2. A snapshot taken mid-approach restores the aircraft to the same position, state, weather and
   failure set.
3. A `.fms` and a `.pln` file round-trip through import and export without loss of the fields the
   internal model represents.

---

## Phase 5 — Multi-sim and distribution

### Scope

- **`MSFSAdapter`** — SimConnect, **Windows-only**, with a **deliberately reduced capability
  set**: weather injection is locked down by Asobo, SimConnect failures are limited, study-level
  aircraft use their own failure systems, and L:var access goes through the **MobiFlight WASM
  module** (an optional add-on, exactly the same pattern as `bridge/`).
  The measure of success here is that **nothing in `core/`, `server/` or `ui/` changes** to
  support a second simulator — if it does, the abstraction was wrong.
- **Packaging** — polished **PyInstaller single executable** bundling `ui/dist`, starting the
  local server and opening the browser.
- **Optional Tauri shell** — a nice-to-have desktop wrapper, explicitly not architecture.

### Exit criteria

1. The contract suite passes against `MSFSAdapter` under `-m sim` for every capability it
   declares `True`.
2. Features the MSFS adapter cannot support are disabled in the UI with a reason; none of them
   fails at runtime.
3. The single executable launches the server and the UI on a clean Windows machine with no Python
   installed.
4. Zero simulator-specific code exists outside `adapters/`.

---

## Parallelisation

The policy is stated in [`../CLAUDE.md`](../CLAUDE.md) and repeated here because the phase plan
depends on it:

- **Parallelise whenever the work is genuinely independent** — a standing rule, not a per-task
  decision.
- **Across managers in a phase:** independent managers are developed as parallel `feature/*`
  branches, each with its own planner → implementer → tester cycle. Use **git worktrees** so
  concurrent agents never share a working tree. Each branch opens its own PR to `dev`; **CI on
  each PR is the integration barrier**.
- **Inside a manager:** once the planner has fixed the contract (endpoints + models), the backend
  and the UI panel proceed in parallel, and the tester writes the contract suite against the
  design without waiting for the implementation.
- **Dispatch rule:** launch subagents for independent work **in a single message** so they run
  concurrently, each with a **disjoint set of directories**.
- **Never parallelise:** changes to the `SimAdapter` / `Capabilities` contract, navdata SQLite
  schema migrations, merges to `dev` / `main`, or release tagging.

### What runs in parallel, per phase

| Phase | Parallel tracks | Serialisation point |
|---|---|---|
| **1** | CIFP parser ∥ `apt.dat` + `earth_nav` parser ∥ traffic-pattern geodesy ∥ Aircraft Control panel | The SQLite schema is defined once, up front, and never edited concurrently |
| **2** | Weather ∥ Failures ∥ Fuel & Payload | **The Scenario Generator waits for all three** — it composes them |
| **3** | Map ∥ traffic bridge ∥ Pushback / Camera | `can_spawn_traffic` is a contract change: made once, alone, before the bridge work starts |
| **4** | Landing Analysis ∥ Session Recorder ∥ Flight Plan | They share the state-frame model — fix it first |
| **5** | `MSFSAdapter` ∥ packaging | — |

Phase 0 is deliberately **not** parallelised across the contract: the `SimAdapter` /
`Capabilities` interface is the shared foundation everything else is built on, and it is written
once, by one agent, before the Fake and the server branch off it.
