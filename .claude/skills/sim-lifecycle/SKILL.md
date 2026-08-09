---
name: sim-lifecycle
description: |
  Drive the X-Plane 12 process for an automated run: start it at a chosen airport, wait until a
  flight is actually loaded, place the aircraft on an exact runway or stand, then shut it down and
  put the user's preferences back. Use this whenever work needs a live simulator and it is not
  already running — `pytest -m sim`, an end-to-end smoke, a manual adapter check, the
  `sim-validator` agent — and use it again at the end to leave the machine as it was found.
  Triggers: "run the sim tests", "validate against a live sim", "launch X-Plane at LEMD", "is the
  sim up", "shut the simulator down", "restore my X-Plane preferences". Developer tooling only:
  never part of the application, never wired into CI.
version: 1.0.0
allowed-tools:
  - Bash
  - Read
  - Glob
---

# Skill: driving the X-Plane process

`spikes/sim_lifecycle.py` is a CLI that owns the simulator *process*. This skill is the procedure
for using it without wrecking someone's session.

Run everything from the repository root with the project's virtualenv:

```bash
./.venv/Scripts/python.exe spikes/sim_lifecycle.py <subcommand> [options]
```

## This does not break hard rule 1

`CLAUDE.md` rule 1 says the app is 100% external and the user never opens or launches anything
inside the sim. **That rule is about the application.** This script is developer tooling: nothing
imports it, it is not in the PyInstaller bundle, and it never runs in CI. Starting an `.exe` from
the outside is not "opening something inside the simulator" — the instructor station still never
does it, and nothing you do here may change that.

## The one rule that matters: you only shut down what you started

A running X-Plane may have a person sitting in front of it. Before anything else, establish who
owns the process, and remember the answer for the rest of the run.

```bash
./.venv/Scripts/python.exe spikes/sim_lifecycle.py status
```

| `status` says | What it means | What you do | At the end |
|---|---|---|---|
| `ready` | a flight is loaded | **adopt it.** Do not launch, do not restart. | **Never quit it.** Restore aircraft state only. |
| `not-running` | no process at all | `launch`, then `wait-ready` | `quit` — you started it, you end it |
| `menu` | process up, no flight | see below | only quit if you started it |

`menu` is the awkward one. It means either the sim is still booting, or it is parked on the Quick
Flight Loader waiting for a human. Give it `wait-ready`; if that times out, **stop and tell the
user**. Do not kill a process you did not start — that is somebody's simulator.

## The cycle

```bash
# 1. Start it where you want it. Refuses with exit 3 if one is already running.
./.venv/Scripts/python.exe spikes/sim_lifecycle.py launch --apt LEMD --rwy 32L

# 2. Wait for a real flight, not just an HTTP 200. Cold start = minutes, not seconds.
./.venv/Scripts/python.exe spikes/sim_lifecycle.py wait-ready --near-apt LEMD

# 3. Put the aircraft on the exact spot (see "the airport is the only reliable part" below).
./.venv/Scripts/python.exe spikes/sim_lifecycle.py place --apt LEMD --rwy 32L

# 4. ... do the actual work: pytest -m sim, a smoke, whatever you came for ...

# 5. Shut down and restore preferences. Only if step 1 was yours.
./.venv/Scripts/python.exe spikes/sim_lifecycle.py quit
```

`list --apt LEMD` prints the valid runway and stand names when you are not sure — a wrong stand
name should cost a second, not a five-minute launch.

## Exit codes

`0` always means the thing asked for happened. Branch on these, never on scraped text — except for
`status`, which always exits `0` because its answer is the word on the first line.

| Command | Codes |
|---|---|
| `launch` | `0` launched · `2` airport/spot unknown · `3` already running, nothing touched |
| `wait-ready` | `0` ready · `1` timed out, or the process died while booting |
| `place` | `0` placed · `1` sim unreachable · `2` airport/runway/stand unknown · `3` did not arrive |
| `quit` | `0` down (`graceful` or `forced` on stdout) · `1` still running, needs a human |
| any | `2` on a `LifecycleError` — a message the caller has to act on |

## Three things that were measured, and are not what you would guess

- **"The Web API responds" is not "the sim is ready."** Left alone, X-Plane sits on the Quick
  Flight Loader screen forever. Measured: nine minutes in, `GET /api/v2/datarefs` returned HTTP
  200 with an **empty** index, because no flight existed to have datarefs about. `launch` sets
  `_show_qfl_on_start 0` to fix it, and `wait-ready` gates on a *plausible position*, never on a
  status code. Do not write your own readiness poll against the API.
- **The airport is the only reliable part of the boot position.** Asking for LEBL 24R put the
  aircraft at LEBL on runway **02**; LEMD 18R put it at LEMD on the previous session's spot. So
  `launch` is only for loading the right corner of the world, and `place` is what actually honours
  `--rwy`/`--stand`, through the adapter's validated freeze → local frame → release path. Keeping
  the two separate also keeps the teleport short, which avoids the scenery-reload convergence
  failure of [#36](https://github.com/Santisoutoo/open-instructor-station/issues/36).
- **There is no `--load_acf` or `--load_apt`.** They are not in `X-Plane.exe --help`. The aircraft
  is chosen with `--acf` (which goes through the preferences file, not a flag).

## You are editing the user's preferences — treat that as a debt

`launch` rewrites `Freeflight.prf` and `X-Plane.prf`. Both are backed up to `<name>.ois-backup`
first, and *only if a backup is not already there*: a previous run that died left the pristine
copy, and overwriting it would destroy the user's settings permanently.

- `quit` restores automatically and prints `preferences restored`.
- If the run dies before that, the backup is still on disk. Recover with:
  ```bash
  ./.venv/Scripts/python.exe spikes/sim_lifecycle.py restore-prefs
  ```
- **If you cannot restore, say so loudly and first**, with the paths to the `.ois-backup` files, so
  the user can put them back by hand. Never end a run leaving that silent.

## What this skill does *not* do

It moves the process and the aircraft's starting spot. It does **not** capture or restore the
aircraft state, the weather mode or the failure set — that is the caller's job, and for a
validation run it is specified in `.claude/agents/sim-validator.md`. `tests/conftest.py` has its
own session-scoped snapshot/restore (`live_aircraft_home`) for `pytest -m sim`; this skill does not
replace it and must not fight it.
