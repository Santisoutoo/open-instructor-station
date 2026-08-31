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
| `reviewer-python` | Report-only review of a PR/diff's Python (`core/`, `adapters/`, `server/`, `tests/`, `bridge/`): correctness, project rules, overengineering. Never edits, never merges. |
| `reviewer-typescript` | Report-only review of a PR/diff's frontend (`ui/`): correctness, project rules, overengineering. Never edits, never merges. |

---

## Skills (`.claude/skills/`)

| Skill | Use for |
|---|---|
| `sim-lifecycle` | Driving the X-Plane 12 **process**: launch at an airport, wait for a real flight, place the aircraft, quit, restore the user's preferences. Developer tooling — `spikes/sim_lifecycle.py`, never imported by the app, never in CI. Rule 1 forbids *the application* launching a simulator; it does not forbid the test harness. **Only shut down a simulator you started.** |

---

## MCP tooling (developer-only)

**`xplane-datarefs`** ([Santisoutoo/xplane-dataref-mcp](https://github.com/Santisoutoo/xplane-dataref-mcp),
PyPI, launched via `uvx` from the repo's `.mcp.json`) — searches ~10,000 datarefs and ~3,000
commands and reads live values over the same X-Plane Web API (:8086) the adapter uses.

- **Use it for:** dataref discovery when building an adapter mapping (the Phase 2
  Weather/Failures work is mostly this), live debugging against a running sim, and verifying a
  dataref hypothesis *before* writing adapter code or a spike.
- **Limits:** dataref access is **read-only** — writes are still validated with spikes and
  `pytest -m sim`. Needs a live simulator, and the Docker Desktop gotcha applies (~4.1 s per
  request without it). `execute_command` mutates the sim and is deliberately not pre-approved.
- Same status as `sim-lifecycle`: developer tooling only — **never part of the application,
  never in CI**. The app reaches the Web API exclusively through `adapters/xplane/`.

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

- **The frame origin moves during that reload, and a coordinate written before it lands
  somewhere else — RESOLVED in the adapter.** The `local_x/y/z` written before a scenery reload
  denote a *different* world position afterwards, so Madrid → Heathrow used to poll a target the
  aircraft could never reach for the full 30 s and then raise, with every write accepted
  (issue #36). `set_position` now **re-measures the origin and re-aims**, up to
  `_MAX_REPOSITION_WRITES` times inside one budget and one freeze. The interesting half is not
  detecting the shift but deciding when the new origin can be trusted: a re-measure is only taken
  after a whole `_ARRIVAL_ATTEMPT_S` slice of *answered* polls has failed — which rules out "the
  derived coordinates have not caught up yet", because a stalled simulator does not answer at all
  — and two consecutive measurements must agree before one is aimed with. The convergence
  criterion is unchanged and is the only thing that cannot lie: the world position X-Plane derives
  from whichever frame is current. **Never cache a frame origin across a teleport.**

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

  **Resolving the speed in `core/` was not enough to deliver it, and that gap survived for four
  days because only a live run could see it.** `apply_setup` releases the flight model when it
  finishes, the aircraft decelerates while it settles, and `set_position` then re-read that
  *decayed* IAS and faithfully carried it onto the new heading: 120 kt commanded, **82.8 kt**
  measured at LEMD on 2026-08-10. `set_position` therefore takes a keyword-only `ias_kt` —
  `None` preserves the current speed, a value commands it — and `apply` passes the resolved
  speed to **both** calls. The general lesson is worth more than the fix: a value written into
  one call is not delivered until something reads it back at the other end. The contract suite
  now asserts the read-back on both adapters.
- **X-Plane 12 "real weather" mode continuously overwrites manual weather datarefs.** The
  Weather Manager must force manual mode before writing anything.
- **Navdata sources** (user's install, `Custom Data/` wins over `Resources/default data/`):
  `CIFP/<ICAO>.dat` (SID/STAR/APPCH/RWY, ARINC 424 subset — parse lazily, one file per airport),
  `earth_fix/nav/awy/hold/msa.dat`, `Global Scenery/.../apt.dat`. `cycle_info.txt` gives the
  AIRAC cycle — use it as the cache invalidation key.
- **ARINC 424 path terminators:** only legs carrying a resolvable fix (`IF`, `TF`, `CF`, `DF`,
  `AF`, `RF`) are positionable. Legs like `CA`/`VA`/`FM`/`VM` are trajectory-dependent — show
  them, do not offer them as positions.
- **A capability flag that gates its own validation is a deadlock.** A `-m sim` suite that
  skips while its flag is `False` can never be the run that flips the flag to `True`. Pushback
  and camera hit exactly this in Phase 3: the honest resolution is to flip the flag when the
  code earns it structurally (pushback reuses the already-validated `set_position` procedure
  wholesale and adds zero new dataref surface; camera probes every candidate command at connect
  and degrades any that fails to resolve), state in the code that the flip asserts the code is
  right rather than that it has been flown, and let `pytest -m sim` settle it. What is *not*
  acceptable is a suite that silently passes vacuously — a live test whose assertions collapse
  when a flag is off must say so in its docstring, and must fail loudly (not skip) when the
  thing it exists to prove turns out false.

- **Geodesic hops do not hold their latitude — flat-trig inverses are off by far more than
  spherical excess.** Measured while building `core/camera/geometry.py`: the naive inverse of
  two geodesic offsets is wrong by `distance² / R × tan(latitude)` — **145 mm worst case over a
  ±500 m envelope across latitudes 0–75°**, five orders of magnitude past the micrometres a
  spherical-excess estimate predicts. Two re-projection refinement passes bring it to 12 nm.
  The measurement lives in that module's docstring and is pinned by a millimetre-tolerance
  round-trip test; any future "simplification" that drops the refinement will fail it.

- **`ui/src/api/schema.d.ts` drifts silently — regenerate it in any PR that touches a route.**
  `dev` shipped a generated client that was missing `GET /api/geodesy/measure` entirely, months
  after the server started serving it, and nothing failed: typecheck can only see the types it
  was handed. The schema is a generated artefact — when branches conflict on it, regenerate from
  the composed server (`create_app().openapi()` needs no running process) instead of hand-merging,
  and treat a hand edit as a rule-7 violation.

- **MSFS will always be a feature subset**: weather injection is locked down by Asobo, failures
  via SimConnect are limited, and study-level aircraft use internal failure systems. L:var access
  goes through the MobiFlight WASM module (optional add-on, same pattern as `bridge/`).
