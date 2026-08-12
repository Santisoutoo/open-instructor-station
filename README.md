# Open Instructor Station

**An external, multi-sim instructor station for flight simulators.**

A desktop/LAN application that lets an instructor reposition the aircraft, set the weather,
inject failures, run training scenarios and watch a live map — **without ever alt-tabbing into
the simulator**.

Everything runs *outside* the sim and talks to it over the network. X-Plane 12 is the reference
target; MSFS comes later through the same adapter abstraction. Because the server is reachable
over the LAN, driving the station from a **tablet** is a first-class scenario.

---

## Status

**Phase 1 — Position Manager, Aircraft Control and the navdata foundation. In active
development.** See [`docs/roadmap.md`](docs/roadmap.md) for the phase plan.

Phase 0 (the skeleton) is complete, and with it the project's biggest technical unknown:
**repositioning an aircraft from outside X-Plane works, with no plugin** — validated in a live
sim at LEMD.

**Working today**

- The `SimAdapter` + `Capabilities` contract, and `FakeSimAdapter`, a full in-memory simulator.
- An X-Plane 12 adapter over the Web API (REST + WebSocket).
- A FastAPI server with live state over WebSocket, and aircraft setup/control endpoints.
- A React + Redux Toolkit UI with a live telemetry panel and an aircraft control panel.
- A double-clickable Windows executable.

**Planned** — weather, failures, scenarios, the instructor map, AI traffic, landing analysis and
the rest of the 15 managers described in [`docs/feature-spec.md`](docs/feature-spec.md).

---

## Requirements

| | |
|---|---|
| **Python** | 3.12 or newer |
| **Node** | 22 or newer |
| **Simulator** *(optional)* | X-Plane 12.1+ with its Web API enabled on port 8086 |

**You do not need a simulator to run the app or the tests.** The default adapter is
`FakeSimAdapter`, which implements the whole interface in memory, and CI never touches a
simulator.

---

## Quickstart

### 1. Start the backend

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
instructor-station
```

On Linux/macOS activate with `source .venv/bin/activate` instead.

The server starts on `http://localhost:8000`. Check it with
[`http://localhost:8000/api/health`](http://localhost:8000/api/health). It runs against the fake
simulator by default, so this works with nothing else installed.

### 2. Start the frontend

```powershell
cd ui
npm install
npm run dev
```

Open `http://localhost:5173`. The dev server proxies `/api` and `/ws` to the backend, and listens
on all interfaces so a tablet on the same network can use the same URL.

That is the whole development setup: two terminals, no simulator.

### 3. Connect it to X-Plane (optional)

In X-Plane, enable the Web API under **Settings → Network → "Accept incoming connections"**, then
confirm `http://localhost:8086/api/v2/datarefs` returns JSON in a browser. Then point the server
at it:

```powershell
$env:OIS_ADAPTER = "xplane"
instructor-station
```

Every setting is an `OIS_`-prefixed environment variable, and may also be put in a `.env` file:

| Variable | Default | |
|---|---|---|
| `OIS_ADAPTER` | `fake` | `fake` or `xplane` |
| `OIS_HOST` · `OIS_PORT` | `0.0.0.0` · `8000` | Bound to all interfaces on purpose — the tablet needs it |
| `OIS_XPLANE_HOST` · `OIS_XPLANE_PORT` | `localhost` · `8086` | Where X-Plane's Web API lives |
| `OIS_OPEN_BROWSER` | on when packaged | Set to `0` to keep the executable headless |

### The packaged executable

A single `.exe` that starts the server and opens a browser — no Python, no Node, no terminal. Build
the UI first, then the bundle:

```powershell
cd ui; npm ci; npm run build; cd ..
python -m PyInstaller packaging\instructor-station.spec --noconfirm --clean
```

The result is `dist/instructor-station.exe`. It is unsigned, so Windows SmartScreen warns on
first run. Tagging `v*` builds the same executable in CI and attaches it to a draft release.

---

## Project layout

One hard rule shapes everything: **`core/` depends only on the `SimAdapter` interface and never
on an adapter.** All the valuable logic is simulator-agnostic, which is what makes a second
simulator a new adapter rather than a rewrite.

| Directory | Contents |
|---|---|
| `core/` | Sim-agnostic logic: geodesy, navdata, scenarios, weather presets, failure catalog, landing analysis. |
| `adapters/fake/` | `FakeSimAdapter` — the full interface in memory. **All CI tests run against it.** |
| `adapters/xplane/` | X-Plane 12.1+ Web API (REST + WebSocket, default port 8086). |
| `server/` | FastAPI app wiring `core` + the active adapter. Serves the UI over the LAN and pushes live state over WebSocket. |
| `ui/` | React + TypeScript (strict) + Redux Toolkit. |
| `bridge/` | **Optional** XPPython3 plugin, only for what the Web API cannot do (AI traffic). |
| `spikes/` | Throwaway validation scripts. Not imported by the app, not covered by tests. |
| `docs/` · `tests/` · `packaging/` | Documentation, test suites, PyInstaller bundle. |

Full explanation in [`docs/architecture.md`](docs/architecture.md).

---

## Development

Run the whole verification suite before opening a PR — it is what CI runs:

```bash
pytest                       # unit + contract (sim tests excluded by default)
ruff check . && ruff format --check .
mypy .
cd ui && npm run lint && npm run typecheck && npm test && npm run build
```

`pytest -m sim` runs the tests that need a live X-Plane on port 8086. They are excluded by
default and never run in CI.

---

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md): branch strategy, Conventional Commits, the PR
checklist and the rules that are not negotiable (CI is never merged red, tests are never weakened
to make a run pass, navdata is never committed).

In short: branch off `dev`, open a PR back into `dev`, and keep all four CI checks green —
`lint-py`, `test-py`, `lint-ui`, `test-ui`. Bug reports and feature requests go through the
[issue templates](.github/ISSUE_TEMPLATE).

---

## Documentation

| Document | |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | **The binding project rules.** Hard rules, layout, stack, testing, git workflow, known gotchas. |
| [`docs/feature-spec.md`](docs/feature-spec.md) | The 15 managers — the complete target feature set. |
| [`docs/roadmap.md`](docs/roadmap.md) | Phases 0–5, with per-phase exit criteria. |
| [`docs/architecture.md`](docs/architecture.md) | Layers, the `SimAdapter` contract, navdata pipeline, packaging, technical risks. |
| [`docs/designs/`](docs/designs/) | One design doc per manager, written before any of its code. |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Branch strategy, commit conventions, PR checklist, local verification. |
| [`bridge/README.md`](bridge/README.md) | The optional in-sim plugin for AI traffic. |
