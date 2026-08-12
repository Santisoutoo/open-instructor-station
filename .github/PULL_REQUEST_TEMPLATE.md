<!--
Title must follow Conventional Commits: type(scope): summary in the imperative, lowercase.
  feat(position): place aircraft on a N-NM final
  fix(xplane): retry websocket on 1006
PRs target `dev`. Only a release PR goes dev -> main.
-->

## What this changes

<!-- One paragraph. What behaviour is different after this PR? -->

Closes #

## How it was verified

<!-- What you actually ran, and what it said. If it was validated against a live sim, say so. -->

## Checklist

- [ ] **Tests added.** New behaviour is covered.
- [ ] **`core/` changes are covered.** `core/` logic requires tests — no exceptions.
- [ ] **Contract suite extended** if a `SimAdapter` capability was added or changed
      (`tests/adapters/test_contract.py`), and **`FakeSimAdapter` implements the new method**.
- [ ] **No navdata committed.** No `apt.dat`, `earth_*.dat`, CIFP file or derived database.
      Fixtures are hand-written minimal samples or public-domain FAA CIFP extracts only.
- [ ] **Docs updated** — `docs/designs/<feature>.md` reflects what was built; `docs/roadmap.md`,
      `docs/architecture.md` or `docs/feature-spec.md` updated if the change affects them.
- [ ] **`core/` still talks to no simulator** — no `httpx`, no dataref names, no adapter imports.
- [ ] **New features sit behind a capability flag** and are disabled in the UI when unsupported —
      never left to throw at runtime.
- [ ] **No hand-written API types in the frontend** — the client is generated from FastAPI's
      OpenAPI schema.
- [ ] **Local verification passed**: `pytest`, `ruff check . && ruff format --check .`, `mypy .`,
      and `npm run lint && npm run typecheck && npm test && npm run build` in `ui/`.
- [ ] **All four CI checks green** (`lint-py`, `test-py`, `lint-ui`, `test-ui`). Never merged red,
      never bypassed, never made green by weakening a test or a lint setting.
- [ ] Targets **`dev`**, not `main`.
