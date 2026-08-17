# Open Instructor Station — Codex Instructions

External instructor station for flight simulators. X-Plane 12 is the reference target; MSFS will
follow through the same abstraction. Documentation, code, comments, and commit messages are in
English.

## Non-negotiable architecture

1. The application is **100% external** and connects to the simulator over the network. The
   optional `bridge/` add-on is only for capabilities the simulator Web API cannot provide; all
   non-AI-traffic features must work without it.
2. `core/` is simulator-agnostic and only depends on the `SimAdapter` interface. Never import an
   HTTP client, a simulator SDK, or simulator dataref names into `core/`.
3. Use capabilities, not runtime failures: adapters declare what they support and the UI disables
   unsupported operations.
4. Read navdata from the user's simulator installation; never redistribute or commit navdata or
   derived databases. Fixtures must be hand-written minimal samples or public-domain FAA CIFP.
5. Use OpenStreetMap or other open map-tile sources only. The settled stack is Python/FastAPI and
   strict TypeScript/React/Redux Toolkit/MapLibre; do not propose a language rewrite.

## Repository layout

- `core/`: simulator-independent logic (geodesy, navdata, scenarios, weather, failures, landing
  analysis), depending only on `SimAdapter`.
- `adapters/`: `fake/` supports all CI tests, `xplane/` implements the X-Plane 12.1+ Web API, and
  `msfs/` is a later Windows-only SimConnect implementation.
- `server/`: FastAPI application, LAN UI serving, and live-state WebSockets.
- `ui/`: strict React/TypeScript, Redux Toolkit, and MapLibre GL. Generate API types from FastAPI
  OpenAPI; never hand-write frontend API types.
- `bridge/`: optional XPPython3 plugin for AI traffic only.
- `spikes/`: throwaway validation scripts, never imported by the app or included in CI.
- `docs/designs/`: feature design documents written before implementing a manager.

Each feature manager must remain self-contained: core logic, server endpoints, and UI panel. New
scenarios are declarative YAML and should not require code changes.

## Testing and verification

- All `core/` logic needs tests.
- CI uses `FakeSimAdapter` and never needs a running simulator.
- Extend `tests/adapters/test_contract.py` whenever `SimAdapter` or its capabilities change; it
  runs with Fake in CI and with the real X-Plane adapter under `-m sim`.
- Live-simulator tests use `@pytest.mark.sim` and are excluded by default. Never skip or xfail a
  test merely to obtain a green run.

Run the applicable checks:

```bash
pytest
pytest -m sim
ruff check . && ruff format --check .
mypy .
cd ui && npm run lint && npm run typecheck && npm test && npm run build
```

## Git workflow

- Do not commit directly to `main`; it is releases only. Integrate feature work into `dev` first.
- Use `feature/<name>`, `bug/<name>`, `docs/<name>`, or `chore/<name>` branches and Conventional
  Commits.
- CI must be green before merges. Do not bypass checks, force-push `main` or `dev`, commit, or push
  unless the user asks.

## Codex resources in this repository

- Reusable skills are in `.codex/skills/`; invoke them by name when appropriate. In particular,
  `sim-lifecycle` is the safe procedure for a real X-Plane process. Only shut down a simulator you
  started.
- The former Claude role prompts are preserved in `.codex/agents/` as reference playbooks:
  `planner`, `implementer`, `tester`, `sim-validator`, `reviewer-python`, and
  `reviewer-typescript`. They are not executable Codex agent definitions; use them as task
  instructions when the role is relevant.
- `.claude/` remains untouched for backward compatibility. `.claude/worktrees/` is runtime state
  and is deliberately not copied.
- The `xplane-datarefs` MCP server
  ([Santisoutoo/xplane-dataref-mcp](https://github.com/Santisoutoo/xplane-dataref-mcp)) provides
  dataref/command search and live read-only dataref access over the X-Plane Web API (:8086). For
  Codex it is registered as `[mcp_servers.xplane-datarefs]` in `~/.codex/config.toml` (Claude
  Code reads it from the repo's `.mcp.json`). Developer tooling only — never part of the
  application, never in CI; dataref writes are still validated with spikes and `pytest -m sim`.

## X-Plane operational notes

- External repositioning works without a plugin: freeze `override_planepath`, write local
  position, velocity and attitude, release in a `finally`, then clear crash state. Treat
  latitude/longitude/elevation as read-only derived values.
- Do not trust `lat_ref`/`lon_ref`; derive the local-frame origin from a live observation using
  `core.local_frame.origin_from_observation` and use the ECEF rotation implementation.
- A placement must set an appropriate IAS before teleporting; zero speed on a final will cause a
  stall. X-Plane real-weather mode overwrites manual datarefs, so force manual mode first.
- User `Custom Data/` takes precedence over default navdata. Only ARINC legs with a resolvable fix
  are positionable; show trajectory-dependent legs without offering positions.

For the complete historical rationale and validated measurements, see `CLAUDE.md`, which is kept
as the compatibility source during the transition.
