# Open Instructor Station — Project Instructions

External instructor station for flight simulators. A desktop/LAN application that lets an
instructor reposition the aircraft, set weather, inject failures, run training scenarios and
watch a live map — **without ever alt-tabbing into the simulator**.

X-Plane 12 is the reference target. MSFS comes later through the same abstraction.

**This is a private, proprietary project.** No license file. Do not add license headers. Never
copy code from third-party projects (Little Navmap is GPL-3 — study its design, never its code).
Documentation, code, comments and commit messages are written in **English**.

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
| `sim-validator` | Automated in-sim validation: with X-Plane live, run `pytest -m sim` + an E2E smoke (read datarefs → teleport → restore) and report. Never runs in CI. |

---

## Known gotchas

- **Repositioning the aircraft externally is the project's key technical risk.** X-Plane's real
  position lives in `local_x/y/z` (OpenGL frame); `latitude/longitude/elevation` are derived and
  the world→local conversion (`XPLMWorldToLocal`) is a plugin-only API. If writing lat/lon over
  the Web API does not stick, fall back to the legacy UDP `VEHX`/`VEH1` packet, which positions
  the aircraft without a plugin. Long teleports trigger a scenery reload — pause around them.
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
