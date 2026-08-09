# Open Instructor Station — Project Instructions

External instructor station for flight simulators. A desktop/LAN application that lets an
instructor reposition the aircraft, set weather, inject failures, run training scenarios and
watch a live map — **without ever alt-tabbing into the simulator**.

X-Plane 12 is the reference target. MSFS comes later through the same abstraction.

Never copy code from third-party projects (Little Navmap is GPL-3 — study its design, never its
code). Documentation, code, comments and commit messages are written in **English**.

---

## Hard rules (do not revisit without asking)

1. **The app is 100% external.** It connects to the simulator over the network. The user never
   opens or launches anything inside the sim. In-sim components (`bridge/`) are *optional*
   add-ons, and every feature outside AI traffic must work without them.
2. **`core/` never talks to a simulator.** It depends only on the `SimAdapter` interface. If you
   find yourself importing `httpx` or a dataref name into `core/`, the design is wrong.
3. **Capabilities, not failures.** Each adapter declares what it supports
   (`can_set_position`, `can_set_weather`, `can_inject_failures`, `can_spawn_traffic`, …).
   Unsupported features are *disabled in the UI*, never left to throw at runtime.
4. **Navdata is read from the user's own simulator install and never redistributed.**
   No `apt.dat`, `earth_*.dat`, CIFP file or derived database is ever committed. Test fixtures
   use hand-written minimal samples or public-domain FAA CIFP extracts only.
5. **Map tiles: OpenStreetMap / open sources only.**
6. **The stack is settled** (see below). Do not propose rewrites in another language.

---

## Layout

```
core/       Sim-agnostic logic: geodesy, navdata, scenarios, weather presets,
            failure catalog, landing analysis. Depends only on SimAdapter.
adapters/   fake/    FakeSimAdapter — full interface in memory. ALL CI tests run against it.
            xplane/  X-Plane 12.1+ Web API (REST + WebSocket, default port 8086).
            msfs/    later (SimConnect, Windows only).
server/     FastAPI app wiring core + the active adapter. Serves the UI over the LAN
            (tablet use is a first-class scenario) and pushes live state over WebSocket.
ui/         React + TypeScript (strict) + Redux Toolkit + MapLibre GL.
bridge/     OPTIONAL XPPython3 plugin, only for what the Web API cannot do (AI traffic).
spikes/     Throwaway validation scripts. Not imported by the app, not covered by tests.
docs/       feature-spec.md (the 15 managers), roadmap.md (phases), architecture.md,
            designs/<feature>.md (one design doc per manager, written before coding).
tests/      core/ + adapters/ run in CI. sim/ is marked `@pytest.mark.sim` and never runs in CI.
```

Each feature "manager" is self-contained: core logic + server endpoints + UI panel. Adding a new
manager must not require touching the others.

---

## Stack

- **Backend:** Python 3.12+, FastAPI, `geographiclib` for geodesy (pure Python — keeps the
  PyInstaller bundle small; only reach for `pyproj` if real projections show up).
- **Frontend:** TypeScript **strict**, React, **Redux Toolkit** for all state
  (`createSlice` / `createAsyncThunk` / `configureStore`; RTK Query for server state).
  Never plain Redux, Zustand or Context for global state.
- **API types:** the UI client is generated from FastAPI's OpenAPI schema. **Never hand-write
  API types** in the frontend.
- **Packaging:** single executable via PyInstaller that starts the local server and opens the
  browser. Tauri is a later nice-to-have, not architecture.
- **Scenarios are data:** declarative YAML (initial position + aircraft state + weather +
  scheduled failures + traffic). New scenarios must not require code changes.

---

## Testing

- `core/` logic requires tests. No exceptions.
- Everything in CI runs against `FakeSimAdapter`. **CI never needs a simulator.**
- The `SimAdapter` contract suite (`tests/adapters/test_contract.py`) is parametrised over
  adapters: it runs against the Fake in CI, and against the real X-Plane adapter under
  `-m sim`. **Every new capability added to the interface must extend this suite.**
- Tests needing a live sim are marked `@pytest.mark.sim` and excluded by default.
- Never skip or xfail a test to make a run green. Fix the code or report the failure.

Commands:

```bash
pytest                       # unit + contract (sim tests excluded by default)
pytest -m sim                # requires X-Plane running with its Web API on :8086
ruff check . && ruff format --check .
mypy .
cd ui && npm run lint && npm run typecheck && npm test && npm run build
```

---

## Git workflow

| Branch | Purpose |
|---|---|
| `main` | Releases only. Tagged `v*`. Never commit directly. |
| `dev` | Stable integration. All feature work merges here first. |
| `feature/<name>` | New functionality. |
| `bug/<name>` | Fixes. |
| `docs/<name>` | Documentation only. |
| `chore/<name>` | Tooling, CI, dependencies. |

- **CI must be green before any merge.** Required checks: `lint-py`, `test-py`, `lint-ui`,
  `test-ui`. A red pipeline is never merged, never bypassed, never `--no-verify`'d.
- Flow: `feature/*` → PR → `dev` → (when a release is cut) PR `dev` → `main` → tag `v*`.
- **Conventional Commits**: `feat(position): place aircraft on a N-NM final`,
  `fix(xplane): retry websocket on 1006`, `docs(roadmap): …`, `chore(ci): …`.
- Commit or push only when asked. Never force-push `main` or `dev`.

---

## Parallelisation policy

**Parallelise whenever the work is genuinely independent.** This is a standing rule, not a
per-task decision.

- **Across managers in a phase:** independent managers are developed as parallel `feature/*`
  branches, each with its own planner → implementer → tester cycle. Use **git worktrees** so
  concurrent agents never share a working tree. Each branch opens its own PR to `dev`; CI on
  each PR is the integration barrier.
- **Inside a manager:** once the planner has fixed the contract (endpoints + models), the
  backend and the UI panel proceed in parallel, and the tester writes the contract suite
  against the design without waiting for the implementation.
- **Dispatch rule:** when launching subagents for independent work, launch them in a single
  message so they run concurrently. Give each one a disjoint set of directories.
- **Never parallelise** changes to the `SimAdapter` / `Capabilities` contract (shared
  foundation), navdata SQLite schema migrations, merges to `dev`/`main`, or release tagging.

---

## Subagents (`.claude/agents/`)

| Agent | Use for |
|---|---|
| `planner` | Design a manager before any code: endpoints, models, datarefs, test plan → `docs/designs/<feature>.md`. Read-only. |
| `implementer` | Build the design on a `feature/*` branch. Leaves a PR ready; never merges. |
| `tester` | Write and run unit + contract tests against `FakeSimAdapter`. Never green-washes. |
| `sim-validator` | Automated live validation, unattended: starts X-Plane if it is not up, runs `pytest -m sim` + an E2E smoke (read datarefs → teleport → restore), shuts down and reports. Never runs in CI. |

---

## Skills (`.claude/skills/`)

| Skill | Use for |
|---|---|
| `sim-lifecycle` | Driving the X-Plane 12 **process**: launch at an airport, wait for a real flight, place the aircraft, quit, restore the user's preferences. Developer tooling — `spikes/sim_lifecycle.py`, never imported by the app, never in CI. Rule 1 forbids *the application* launching a simulator; it does not forbid the test harness. **Only shut down a simulator you started.** |

---

## Known gotchas

- **Repositioning externally is SOLVED — no plugin needed.** Validated against X-Plane 12 at
  LEMD on 2026-08-06. The five-step procedure, in `adapters/xplane/xplane_adapter.py`:
  1. Freeze the flight model (`override_planepath[0] = 1`).
  2. Write `local_x/y/z` — `latitude`/`longitude`/`elevation` are **read-only** and derived, so
     reading them back is the honest verdict on whether a write took.
  3. Write the **velocity vector** (`local_vx/vy/vz`) and `psi`. Zeros drop the aircraft out of
     the sky below stall speed; carry the requested/current speed onto the new heading.
  4. Release the override.
  5. Clear the crash state (`sim/operation/fix_all_systems`) — X-Plane reads a teleport as an
     impact and renders the aircraft wrecked otherwise. Skipping this ends a training session.

  **Never trust `lat_ref`/`lon_ref`.** They advertised an origin 200 km from the real one on the
  validation run. The local frame origin is *measured* from the aircraft, which is known in both
  coordinate systems at once — `core.local_frame.origin_from_observation`. The world→local
  conversion that normally needs the plugin-only `XPLMWorldToLocal` lives in `core/local_frame.py`
  as a rigid ECEF rotation (not a flat-earth offset: 40 km out, the tangent-plane error is ~120 m,
  i.e. the difference between arriving at the requested altitude and arriving inside a hill).
  Long teleports still trigger a scenery reload — expect a pause.

- **The freeze is not just for position — attitude needs it too.** Writing
  `psi`/`theta`/`phi` into a *running* flight model does not stick: measured against X-Plane
  12.4.3 at LEMD, a commanded heading came out 7° off in the mild case and 164° off in the bad
  one, and an `apply_setup` call was observed leaving the aircraft **inverted on the runway**
  (`roll = -180`). The identical writes with `override_planepath` engaged land exactly: commanding
  123.0° on a stationary aircraft read back **123.19°**, and still held 123.46° six seconds later.
  **Both `set_position` and `apply_setup` now freeze** (issue #37), and `tests/conftest.py` freezes
  around its session restore. Any residual pitch/roll after the release is the aircraft settling
  onto its gear — that is physically correct, do not tune it away.
  **The release always goes in a `finally`** — a leaked override freezes the user's aircraft.

- **`set_position` preserves the aircraft's *current* speed, which is the wrong default for a
  placement — RESOLVED in `core/`.** Right for moving an aeroplane that is already flying, wrong
  for a placement: a parked aircraft put on a 10 NM final is handed 0 kt and falls out of the sky.
  Observed at LEMD 32L with the geometry perfect — 0.2 m placement error, 10.000 NM out, on the
  extended centreline — and the aircraft in terrain regardless, simply below stall speed. The same
  placement with `ias_kt=90` commanded held 89.3 kt and −651 fpm, which is a real approach.
  **A placement now commands its own speed** (issue #39): `core.geodesy.Placement` carries a
  **required** `ias_kt` — no default, so a new placement type cannot be written without answering
  the question — and `Placement.to_setup()` yields the `AircraftSetup` to apply *before* the
  teleport. The default is per placement type and per aircraft **ICAO approach category**
  (`APPROACH_CATEGORY_VAT_KT` on a final, `APPROACH_CATEGORY_CIRCLING_IAS_KT` on a circuit,
  category B when the caller states nothing, 0 kt only on the ground); an explicit `ias_kt` always
  wins. Speed is only half of it — the flaps and gear that make it a *stabilised* approach are the
  full pre-teleport setup (#8), which extends `to_setup()` rather than replacing it.
- **X-Plane 12 "real weather" mode continuously overwrites manual weather datarefs.** The
  Weather Manager must force manual mode before writing anything.
- **Navdata sources** (user's install, `Custom Data/` wins over `Resources/default data/`):
  `CIFP/<ICAO>.dat` (SID/STAR/APPCH/RWY, ARINC 424 subset — parse lazily, one file per airport),
  `earth_fix/nav/awy/hold/msa.dat`, `Global Scenery/.../apt.dat`. `cycle_info.txt` gives the
  AIRAC cycle — use it as the cache invalidation key.
- **ARINC 424 path terminators:** only legs carrying a resolvable fix (`IF`, `TF`, `CF`, `DF`,
  `AF`, `RF`) are positionable. Legs like `CA`/`VA`/`FM`/`VM` are trajectory-dependent — show
  them, do not offer them as positions.
- **MSFS will always be a feature subset**: weather injection is locked down by Asobo, failures
  via SimConnect are limited, and study-level aircraft use internal failure systems. L:var access
  goes through the MobiFlight WASM module (optional add-on, same pattern as `bridge/`).
