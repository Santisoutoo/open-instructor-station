# The contract suite against a live simulator

**Status:** fixed in `bug/live-contract-suite` — closes
[#2](https://github.com/Santisoutoo/open-instructor-station/issues/2).
Affects `pytest -m sim` only — never CI.

## The problem

Three parametrisations of `tests/adapters/test_contract.py` were unreliable against a live
X-Plane 12:

| Test | Why |
|---|---|
| `test_set_position_moves_the_aircraft[xplane]` | Teleported Madrid → Heathrow, ~1250 km. That triggers a scenery reload, during which X-Plane relocates the local frame origin and the derived world coordinates are in transit. |
| `test_apply_setup_applies_only_the_provided_fields[xplane]` | Asserted altitude within 100 ft. If the previous test left the aircraft in free fall, it lost more than that between the write and the read-back. |
| `test_stream_state_tracks_a_moving_aircraft[xplane]` | Needed an aircraft that is actually moving. A parked one with brakes set will not accelerate no matter what velocity vector is written. |

### Root cause

The contract suite was designed against `FakeSimAdapter`, which is constructed fresh for every
test. A real simulator carries state across tests, so each one inherited whatever the previous
left behind — commonly an aircraft in free fall in a field, at a position that depended on test
execution order. **The failures described the test harness, not the adapter.**

### Rejected fix (tried, reverted, still rejected)

A fixture resetting the aircraft to a known airborne state before *each* test. Teleporting before
all 22 tests pushed the suite past 165 s and introduced fixture errors of its own. Repositioning
before every test is too blunt an instrument.

## What was done

### 1. Snapshot once, restore once — `live_aircraft_home` (`tests/conftest.py`)

A session-scoped, autouse fixture that reads the aircraft's position before the first live test
and teleports it back after the last, clearing the crash state on the way out. It is inert unless
tests carrying the `sim` marker were actually collected, so CI never opens a socket. Setup and
teardown run on their own `asyncio.run` loop, which keeps them independent of the per-test event
loop pytest-asyncio manages.

This also closes the side effect the old document warned about: `pytest -m sim` used to abandon
the user's aircraft wherever the last test dropped it.

### 2. Stabilise before each test, without teleporting — `_stabilise` (`tests/adapters/test_contract.py`)

Levels the attitude, rewrites the velocity vector and lifts the aircraft clear of the ground
**only when it is actually on it**. Rewriting the velocity vector is what does the real work: the
adapter writes `local_vy = 0` as part of it, so free fall stops. No teleport, no settle time, a
handful of writes.

It runs for *every* adapter, not just the live one, so CI exercises the helper rather than
leaving it as untested sim-only code.

The stabilised speed is 140 kt. That is deliberately modest: fast enough that a stream tick moves
the aircraft observably, slow enough that the ~1.3 s a live sim spends flying between a teleport
and the read-back stays well inside `POSITION_TOLERANCE_M`. **No tolerance in the suite was
loosened to make this pass.**

### 3. Every position test is now relative and self-restoring

The suite no longer contains a single absolute latitude, longitude or MSL altitude. Each position
test measures a short hop (`HOP_DISTANCE_NM = 5.0`) from wherever the aircraft already is, and
undoes it in a `finally`.

This is a **departure from the issue's framing**, and worth being explicit about. The issue treats
the Madrid → Heathrow distance as incidental. It is not incidental — it is the whole failure:

- An absolute target is unbounded. From an arbitrary starting position it can be a
  transcontinental jump, and it was not only `test_set_position_moves_the_aircraft` that had one —
  `test_set_position_sets_the_altitude` and `test_set_position_normalises_the_heading` both
  teleported to a hard-coded 40.0N/3.0W and never restored. They were landmines waiting for a user
  who starts somewhere other than Madrid.
- An absolute MSL altitude can be underground depending on where the user parked. Those are now
  relative too (`HOP_CLIMB_FT`).

The contract being asserted is "the aircraft ends up where you asked". The distance is not part of
it, and a 5 NM hop pins it exactly as well as 1250 km — the same distance
`tests/sim/test_live_xplane.py` has been teleporting reliably all along.

### 4. A skip removed, not added

`test_stream_state_tracks_a_moving_aircraft` used to skip itself when it found the aircraft
stationary. That is precisely the green-wash this issue exists to remove: it hid a broken harness
behind a passing run. The stabilisation now guarantees a moving aircraft, so the skip has become
an assertion — if the aircraft is not moving, the stabilisation is broken and the suite says so.

### 5. A latent race in `test_local_frame_origin_reproduces_the_aircraft_position`

Not in the issue, and found while validating. The test read the world coordinates and the local
frame coordinates in *separate* requests and compared them to within 1 m. The Web API serves each
read from whichever frame is current and offers no way to ask for a consistent snapshot, so a
moving aircraft slides between the reads: at 140 kt a handful of frames is tens of metres. The
test only ever passed because the aircraft happened to be parked — and stabilisation, by making
the aircraft reliably move, would have turned that latent flakiness into a deterministic failure.

It now stops the aircraft first (`ias_kt = 0.0`) so the reads describe one instant. The horizontal
assertions stayed at 1 m and are now genuinely tight; the up axis carries a 5 m budget for the
free fall that resumes the moment the velocity write lands — still four orders of magnitude
tighter than the 200 km error the test exists to catch.

## Known gap: long-haul repositioning is an *adapter* problem

Making the contract tests distance-agnostic removes the flakiness, but it does not make a 1250 km
teleport work. That failure is not in the harness:

> X-Plane relocates the local frame origin during a scenery reload. The `local_x/y/z` written
> before the reload then denote a *different* world position, and `_await_arrival` polls for up to
> 30 s against a target the aircraft can no longer converge on.

The fix belongs in `XPlaneSimAdapter.set_position`: detect that the frame origin has moved and
re-measure and re-write after the reload settles, rather than polling a stale target. That is an
adapter change and out of scope for this issue, which is about the harness. **It needs its own
issue before the Position Manager ships "reposition to another airport".**

## Verification

`pytest`, `ruff check`, `ruff format --check` and `mypy` are all green — see the PR.

**When this was written, `pytest -m sim` had *not* been run against a real X-Plane 12.** The
simulator was not running on the machine during this work and nothing was listening on
`localhost:8086`, so the live run in the definition of done could not be performed. That gap was
closed later — see [Live verification](#live-verification--2026-08-09) below. Rather than guess at
the time, the whole suite was validated
against a purpose-built stand-in X-Plane Web API that reproduces the exact conditions the issue
blames:

- the aircraft starts **parked on the ground with the brakes on**, so writing a velocity to it
  does nothing;
- gravity is integrated, so an aircraft left in the air **free-falls** and keeps accelerating;
- world coordinates are *derived* from the local frame every tick, as in the real sim.

Against that stand-in:

| Check | Result |
|---|---|
| Old suite | 2 failed, 22 passed — reproduces the reported breakage |
| New suite | **24 passed** |
| New suite, file order reversed | 24 passed — order-independent |
| Each formerly-failing test run alone | passes |
| New suite, started from a violent free fall (−85 m/s, 60° bank) | 24 passed |
| Aircraft position after a full run | restored to within ~0.2 mm, heading and altitude identical, crash flag clear, `override_planepath` released |

That covers the harness logic — fixture ordering and scoping, relative hops, restore-in-`finally`,
session snapshot/restore, and the stabilisation. It does **not** cover X-Plane's real physics or
Web API timing, which is what the live run below finally measured.

## Live verification — 2026-08-09

Run from `feature/sim-test-skill` against **X-Plane 12 at LEMD**, stock Cessna 172, with the
simulator started and shut down by `spikes/sim_lifecycle.py` (`launch` → `wait-ready` → `place` →
`pytest -m sim` → `quit`). Ready 34 s after launch; the pre-test placement on runway 32L landed
**0.0 m from the threshold with the commanded heading 322.2° read back as 322.2°**.

### Result: 19 passed, 5 failed, 83 s

**The harness holds.** Everything this document claims about fixture ordering and scoping, the
relative hops, restore-in-`finally`, the session snapshot/restore and the stabilisation survives
contact with real physics and real Web API timing. Nothing in the stand-in's verdict was
contradicted; the aircraft was returned home and the preferences restored on both runs.

**The five failures are all [#48](https://github.com/Santisoutoo/open-instructor-station/issues/48),
not this work.** Every one is a heading assertion, and the attitude freeze of #37 is present and
working (`adapters/xplane/xplane_adapter.py:417`, released in a `finally`):

| Test | Read back | Expected |
|---|---|---|
| `test_set_position_moves_the_aircraft[xplane]` | 268.19 | 270.0 ±1 |
| `test_set_position_normalises_the_heading[xplane]` | 93.53 | 90.0 ±1 |
| `test_apply_setup_applies_only_the_provided_fields[xplane]` | 293.29 | 123.0 ±1 |
| `test_apply_setup_with_nothing_set_changes_nothing[xplane]` | 234.40 | 230.54 ±1 |
| `test_live_xplane.py::test_apply_setup_writes_configuration` | 221.23 | 228.94 ±5 |

The 170° error on the third corroborates the 286.66° #48 measured for that same test. **The fourth
row is new**: `test_apply_setup_with_nothing_set_changes_nothing` is not in #48's affected list and
fails with the same signature, so a fix scoped to #48's current list will leave the suite red.

### A precondition the suite cannot see

On the validation machine, every Web API request cost **~4.1 s** (and occasionally 8.2 s) — the
same whether the response was 116 bytes or the 916 KB dataref index, and independent of frame rate,
which was a healthy 19.9 fps. `XPlaneSimAdapter` defaults to `timeout_s = 5.0` and `connect()`
fetches the full index as its first call, so **all 24 sim tests errored with `XPlaneNotReachable`**
before a single assertion ran.

Starting Docker Desktop dropped it to **~5 ms per request** (full index 746 ms) and the suite ran
normally. Comparing `127.0.0.1` against `localhost` does *not* diagnose this — both are equally
slow when the cause is present, so it is not name resolution. If a live run reports every adapter
call as unreachable on a simulator that is demonstrably up and flying, measure a single request
before touching the adapter.

## Rules for anyone adding a live test

A simulator, unlike the Fake, is a single shared persistent thing:

1. **Never assume a starting state.** The `adapter` fixture stabilises the aircraft, but where it
   is and what it is flying is whatever the user left loaded.
2. **Never use an absolute position or altitude.** Work relative to the aircraft's current state.
3. **Restore anything you move, in a `finally`.** `live_aircraft_home` is the safety net, not the
   plan.
4. **Never skip.** A test that cannot observe what it needs is a broken harness, not a skip.
