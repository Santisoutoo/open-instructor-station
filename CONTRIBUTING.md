# Contributing

[`CLAUDE.md`](CLAUDE.md) is the binding source of truth for this project. This document is the
practical workflow that sits on top of it. Where the two ever appear to disagree, `CLAUDE.md`
wins.

Everything — code, comments, documentation, commit messages, PR descriptions — is written in
**English**.

Never copy code from third-party projects: Little Navmap is GPL-3, so its design may be studied
and its code never reused.

---

## Getting set up

The two-terminal development setup — backend, then frontend — is in the
[README quickstart](README.md#quickstart). You do **not** need a simulator: the default adapter
is `FakeSimAdapter` and it implements the whole interface in memory.

Bug reports and feature requests go through the templates in
[`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE). Always say which adapter you were running
(`fake` or `xplane`) — it is the first thing a triager needs.

---

## Branch strategy

| Branch | Purpose |
|---|---|
| `main` | **Releases only.** Tagged `v*`. **Never commit directly.** |
| `dev` | Stable integration. All feature work merges here first. |
| `feature/<name>` | New functionality. |
| `bug/<name>` | Fixes. |
| `docs/<name>` | Documentation only. |
| `chore/<name>` | Tooling, CI, dependencies. |

**Flow:** `feature/*` → PR → `dev` → (when a release is cut) PR `dev` → `main` → tag `v*`.

Rules that are not negotiable:

- **Never force-push `main` or `dev`.**
- Commit or push only when asked.
- Parallel work uses **git worktrees** so concurrent branches never share a working tree.

---

## Conventional Commits

Format: `type(scope): summary in the imperative, lowercase, no trailing period`.

Types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `perf`.
Scopes are the manager or the layer: `position`, `weather`, `failures`, `scenario`, `navdata`,
`map`, `traffic`, `analysis`, `xplane`, `msfs`, `fake`, `server`, `ui`, `ci`, `roadmap`.

Real examples from this domain:

```
feat(position): place aircraft on a N-NM final
feat(position): configure gear, flaps and radios before repositioning
feat(weather): force manual mode before writing wind
feat(navdata): parse CIFP APPCH records lazily per airport
feat(scenario): schedule engine failure on V1 trigger
feat(traffic): gate TCAS scenarios behind can_spawn_traffic
fix(xplane): retry websocket on 1006
fix(navdata): prefer Custom Data over Resources/default data
fix(analysis): compute touchdown rate in fpm, not m/s
test(adapters): extend contract suite for can_set_weather
docs(roadmap): sequence the scenario generator after weather
chore(ci): cache npm in lint-ui
```

Breaking changes to the `SimAdapter` / `Capabilities` contract get a `!` and a footer:

```
feat(adapters)!: add can_spawn_traffic to Capabilities

BREAKING CHANGE: every adapter must now declare can_spawn_traffic, and
tests/adapters/test_contract.py gains the traffic contract cases.
```

---

## CI must be green

Four required checks: **`lint-py`**, **`test-py`**, **`lint-ui`**, **`test-ui`**.

> **A red pipeline is never merged, never bypassed, never `--no-verify`'d.**

That is the whole rule and it has no exceptions — not for a small change, not for a docs-only
change that happened to trip something, not because another branch is waiting.

And the corollary that matters more:

> **Never make a run green by weakening it.** Do not skip a test, do not `xfail` it, do not
> loosen a `ruff` or `mypy` setting, do not add an ignore comment to silence a real finding.
> Fix the code, or report the failure.

`test-py` is a matrix job (`ubuntu-latest` / `windows-latest` × Python `3.12` / `3.13`), so
GitHub reports it as `test-py (ubuntu-latest, 3.12)` and friends. Branch protection must be
configured against those expanded names.

**CI never needs a simulator.** Everything in CI runs against `FakeSimAdapter`; sim tests are
marked `@pytest.mark.sim` and excluded by default. Never add a simulator to a workflow.

---

## Local verification — run before every PR

Exactly these commands, from `CLAUDE.md`:

```bash
pytest                       # unit + contract (sim tests excluded by default)
pytest -m sim                # requires X-Plane running with its Web API on :8086
ruff check . && ruff format --check .
mypy .
cd ui && npm run lint && npm run typecheck && npm test && npm run build
```

`pytest -m sim` is not part of the normal loop — it needs a live X-Plane and is run manually
(see the `sim-validator` agent in [`.claude/agents/`](.claude/agents/)). Everything else must
pass locally before you open a PR. CI is the safety net, not the first run.

---

## PR checklist

Copy this into the PR description and tick it honestly.

- [ ] **Tests added.** New behaviour is covered.
- [ ] **`core/` changes are covered.** `core/` logic requires tests — no exceptions.
- [ ] **Contract suite extended** if a `SimAdapter` capability was added or changed
      (`tests/adapters/test_contract.py`), and **`FakeSimAdapter` implements the new method**.
- [ ] **No navdata committed.** No `apt.dat`, `earth_*.dat`, CIFP file or derived database.
      Fixtures are hand-written minimal samples or public-domain FAA CIFP extracts only.
- [ ] **Docs updated** — `docs/designs/<feature>.md` reflects what was built;
      `docs/roadmap.md`, `docs/architecture.md` or `docs/feature-spec.md` updated if the change
      affects them.
- [ ] **`core/` still talks to no simulator** — no `httpx`, no dataref names, no adapter imports.
- [ ] **New features sit behind a capability flag** and are disabled in the UI when unsupported —
      never left to throw at runtime.
- [ ] **No hand-written API types in the frontend** — the client is generated from FastAPI's
      OpenAPI schema.
- [ ] **All four CI checks green.**
- [ ] Targets **`dev`**, not `main`.

### Reviewing

- PRs merge into `dev`. Only a release PR goes `dev` → `main`.
- The reviewer merges; agents never do.
- CI on each PR is the integration barrier for parallel branches — that is the mechanism, so it
  is never short-circuited.

---

## Branch protection

Branch protection **may** be configured as a **GitHub ruleset** on `main` and `dev`: require the
four checks, require a PR, block force-pushes.

> **If the account plan does not enforce rulesets on a private repository, the rule stands
> anyway, by convention.** Enforcement is a convenience; the rule is the rule. Do not merge red,
> do not push directly to `main` or `dev`, and do not force-push either of them — regardless of
> whether GitHub would stop you.

---

## Working with agents

Subagent definitions live in [`.claude/agents/`](.claude/agents/):

| Agent | Use for |
|---|---|
| `planner` | Design a manager before any code: endpoints, models, datarefs, test plan → `docs/designs/<feature>.md`. Read-only. |
| `implementer` | Build the design on a `feature/*` branch. Leaves a PR ready; **never merges**. |
| `tester` | Write and run unit + contract tests against `FakeSimAdapter`. Never green-washes. |
| `sim-validator` | Automated in-sim validation with X-Plane live: `pytest -m sim` + an E2E smoke (read → teleport → verify → restore). **Never runs in CI.** |

The order is **planner → implementer ∥ tester**: once the planner has fixed the contract, the
backend, the UI panel and the test suite proceed in parallel.

**Parallelise whenever the work is genuinely independent** — a standing rule from `CLAUDE.md`,
not a per-task decision. Give each concurrent agent a **disjoint set of directories** and its own
worktree, and launch them in a single message.

**Never parallelise:** `SimAdapter` / `Capabilities` contract changes, navdata SQLite schema
migrations, merges to `dev` / `main`, or release tagging.
