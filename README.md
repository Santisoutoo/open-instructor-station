# Open Instructor Station

**An external, multi-sim instructor station for flight simulators.**

A desktop/LAN application that lets an instructor reposition the aircraft, set the weather,
inject failures, run training scenarios and watch a live map — **without ever alt-tabbing into
the simulator**.

X-Plane 12 is the reference target. MSFS comes later through the same abstraction.

---

> ## ⚠️ Proprietary — All rights reserved
>
> **This is a private, proprietary project. No license is granted.**
>
> There is no `LICENSE` file and its absence is deliberate: under copyright law, code published
> without a license grants **no rights whatsoever** to copy, use, modify or distribute it. This
> repository is private and is not open source.
>
> - No permission is given to use, copy, modify, merge, publish, distribute or sublicense this
>   software or any part of it.
> - Do not add a license file or license headers.
> - Third-party code is never copied into this project. Little Navmap is GPL-3 — its design may
>   be studied, its code never reused.

---

## Status

**Phase 0 — Foundation. In active development.**

Phase 0 delivers the skeleton, not features: the monorepo layout, the `SimAdapter` +
`Capabilities` contract, `FakeSimAdapter`, a minimal FastAPI server with a WebSocket state
stream, a minimal Redux Toolkit UI shell, CI with four required checks, and the X-Plane
connection spike that retires the project's key technical risk.

The full target feature set (15 managers) is in [`docs/feature-spec.md`](docs/feature-spec.md);
the phased plan is in [`docs/roadmap.md`](docs/roadmap.md).

---

## Architecture

Five layers with one hard dependency rule: **`core/` depends only on the `SimAdapter` interface
and never on an adapter.** Everything valuable — geodesy, navdata, scenarios, landing analysis —
is simulator-agnostic, which is what makes a second simulator a new adapter rather than a
rewrite.

```
ui  →  server  →  core  →  SimAdapter (interface)  ←  adapters/{fake,xplane,msfs}
                                                              ↑
                                                     bridge/ (optional, in-sim,
                                                     AI traffic only)
```

| Directory | Contents |
|---|---|
| `core/` | Sim-agnostic logic: geodesy, navdata, scenarios, weather presets, failure catalog, landing analysis. Depends only on `SimAdapter`. |
| `adapters/fake/` | `FakeSimAdapter` — the full interface in memory. **All CI tests run against it.** |
| `adapters/xplane/` | X-Plane 12.1+ Web API (REST + WebSocket, default port 8086). |
| `adapters/msfs/` | Later (SimConnect, Windows only). Phase 5. |
| `server/` | FastAPI app wiring `core` + the active adapter. Serves the UI over the LAN and pushes live state over WebSocket. |
| `ui/` | React + TypeScript (strict) + Redux Toolkit + MapLibre GL. |
| `bridge/` | **Optional** XPPython3 plugin, only for what the Web API cannot do (AI traffic). |
| `spikes/` | Throwaway validation scripts. Not imported by the app, not covered by tests. |
| `docs/` | Feature spec, roadmap, architecture, and one design doc per manager. |
| `tests/` | `core/` + `adapters/` run in CI. `sim/` is marked `@pytest.mark.sim` and never runs in CI. |

Full explanation, including the navdata pipeline and the known technical risks:
[`docs/architecture.md`](docs/architecture.md).

---

## Requirements

| | |
|---|---|
| **Python** | 3.12 or newer |
| **Node** | 22 or newer |
| **Simulator** *(optional for development)* | X-Plane 12.1+ with its **Web API enabled on port 8086** |

**You do not need a simulator to develop or to run the tests.** Everything works against
`FakeSimAdapter`, and CI never touches a simulator.

To enable the X-Plane Web API: **Settings → Network → "Accept incoming connections"**, then
confirm `http://localhost:8086/api/v2/datarefs` returns JSON in a browser.

---

## Quickstart

### Backend

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
instructor-station
```

On Linux/macOS, activate with `source .venv/bin/activate` instead.

### Run with no simulator at all

The fake adapter implements the complete interface in memory, so the whole application runs
without X-Plane installed:

```powershell
$env:SIM_ADAPTER = "fake"
instructor-station
```

This is the normal development mode. The UI connects, the WebSocket streams state, positions
apply and read back — all in memory.

### Frontend dev server

```powershell
cd ui
npm install
npm run dev
```

The dev server proxies to the backend. The server also serves the built UI over the **LAN** —
using the station from a **tablet is a first-class scenario**, not an afterthought.

---

## The double-clickable executable

A single `.exe` that starts the server and opens a browser — no Python, no Node, no terminal.
It exists this early for **dogfooding**, not distribution: every phase from here on can be
tested the way a user will actually run it.

### Build

The UI must be built first — the spec bundles `ui/dist` into the executable and refuses to
build without it.

```powershell
pip install -e .[dev]
cd ui; npm ci; npm run build; cd ..
python -m PyInstaller packaging\instructor-station.spec --noconfirm --clean
```

The result is `dist/instructor-station.exe` (~18 MB, one file). It is **unsigned**, so Windows
SmartScreen warns on first run — code signing and an installer are separate work.

### Run

Double-click it. A console window opens, the server starts on `0.0.0.0:8000` with the fake
adapter, and the default browser opens at `http://127.0.0.1:8000/`. The console also prints the
LAN URL to type on the tablet. Ctrl-C in that window stops it.

Every setting is the same `OIS_`-prefixed environment variable as in development:

| Variable | Default | |
|---|---|---|
| `OIS_ADAPTER` | `fake` | `fake` or `xplane` |
| `OIS_HOST` · `OIS_PORT` | `0.0.0.0` · `8000` | Bound to all interfaces on purpose — the tablet needs it |
| `OIS_XPLANE_HOST` · `OIS_XPLANE_PORT` | `localhost` · `8086` | Where X-Plane's Web API lives |
| `OIS_OPEN_BROWSER` | on when packaged | Set to `0` to keep the executable headless |

Tagging `v*` runs [`.github/workflows/release.yml`](.github/workflows/release.yml), which builds
the same executable, smoke-tests it and attaches it to a **draft** release for a human to
publish.

---

## Tests

```bash
pytest                       # unit + contract (sim tests excluded by default)
pytest -m sim                # requires X-Plane running with its Web API on :8086
ruff check . && ruff format --check .
mypy .
cd ui && npm run lint && npm run typecheck && npm test && npm run build
```

- `core/` logic requires tests. No exceptions.
- The `SimAdapter` contract suite (`tests/adapters/test_contract.py`) is parametrised over
  adapters: the Fake in CI, the real X-Plane adapter under `-m sim`. **Every new capability must
  extend it.**
- Never skip or xfail a test to make a run green. Fix the code or report the failure.

---

## Branches and CI

| Branch | Purpose |
|---|---|
| `main` | Releases only. Tagged `v*`. Never commit directly. |
| `dev` | Stable integration. All feature work merges here first. |
| `feature/<name>` · `bug/<name>` · `docs/<name>` · `chore/<name>` | Everything else. |

Flow: `feature/*` → PR → `dev` → (when a release is cut) PR `dev` → `main` → tag `v*`.

Four required checks must be green before any merge: **`lint-py`**, **`test-py`**, **`lint-ui`**,
**`test-ui`**. A red pipeline is never merged, never bypassed, never `--no-verify`'d.

Commits follow **Conventional Commits** — see [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## Documentation

| Document | |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | **The binding project rules.** Hard rules, layout, stack, testing, git workflow, parallelisation policy, known gotchas. |
| [`docs/feature-spec.md`](docs/feature-spec.md) | The 15 managers — the complete target feature set. |
| [`docs/roadmap.md`](docs/roadmap.md) | Phases 0–5, with per-phase exit criteria. |
| [`docs/architecture.md`](docs/architecture.md) | Layers, the `SimAdapter` contract, navdata pipeline, packaging, technical risks. |
| [`docs/designs/`](docs/designs/) | One design doc per manager, written before any of its code. |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Branch strategy, commit conventions, PR checklist, local verification. |
| [`bridge/README.md`](bridge/README.md) | The optional in-sim plugin for AI traffic. |
