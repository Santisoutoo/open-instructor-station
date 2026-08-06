# Known limitation: the contract suite against a live simulator

**Status:** open — tracked as [#2](https://github.com/Santisoutoo/open-instructor-station/issues/2).
Does not block Phase 1. Affects `pytest -m sim` only — never CI.

## What works

Against a live X-Plane 12, `pytest -m sim` passes 19 of 22 checks, and everything that matters
for Phase 0 is green:

- `tests/sim/test_live_xplane.py` — all of it, including the teleport, the local-frame
  calibration residual, and the assertion that a teleport does not leave the aircraft wrecked.
- `spikes/xplane_connection.py` — exits 0. Measured on the validation run: 5.000 NM placement,
  restore within 0.08 m, crash flag clear throughout.
- Every read-path and capability-declaration test in the contract suite.

## What does not

Three parametrisations of `tests/adapters/test_contract.py` are unreliable against a live sim:

| Test | Why |
|---|---|
| `test_set_position_moves_the_aircraft[xplane]` | Teleports Madrid → Heathrow, ~1250 km. That triggers a scenery reload, during which X-Plane relocates the local frame origin and the derived world coordinates are in transit. `set_position` now polls for arrival (30 s budget) instead of assuming a fixed settle, which is the right shape, but long-haul convergence is still not reliable. |
| `test_apply_setup_applies_only_the_provided_fields[xplane]` | Asserts altitude within 100 ft of the requested value. If the previous test left the aircraft in free fall, it loses more than that between the write and the read-back. |
| `test_stream_state_tracks_a_moving_aircraft[xplane]` | Needs an aircraft that is actually moving. A parked one with brakes set will not accelerate no matter what velocity vector is written. |

## Root cause

The contract suite was designed against `FakeSimAdapter`, which is constructed fresh for every
test. A real simulator carries state across tests, so each one inherits whatever the previous
left behind — commonly an aircraft in free fall in a field, at a position that depends on test
execution order. **The failures describe the test harness, not the adapter.**

## Rejected fix

A fixture resetting the aircraft to a known airborne state before each test. Tried and reverted:
teleporting before all 22 tests pushed the suite past 165 s and introduced fixture errors of its
own. Repositioning before every test is too blunt an instrument.

## Proposed fix

A session-scoped `sim_state` fixture that snapshots the aircraft once at the start of the run and
restores it once at the end, plus a lightweight per-test stabilisation that does **not** teleport:
level the attitude, set a speed, and lift clear of the ground only when the aircraft is on it.
Tests needing a specific position should set it themselves and restore it in a `finally`, as
`tests/sim/test_live_xplane.py` already does.

## Warning for anyone running the suite today

`pytest -m sim` moves the user aircraft and does **not** put it back. Reload your flight
afterwards.
