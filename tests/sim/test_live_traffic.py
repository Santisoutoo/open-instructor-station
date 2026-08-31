"""AI traffic against a live X-Plane with the ``bridge/`` plugin installed. Never runs in CI.

Phase 3 exit criterion 4 (``docs/designs/ai-traffic.md`` §1.1, §8.4): "With the
bridge installed, a TCAS RA scenario and a runway incursion scenario run in a
live X-Plane." This is that proof — the ``sim-validator`` agent's job, never a
merge gate, run with::

    pytest -m sim -k test_live_traffic

**Requires the optional bridge/ plugin.** Every test here connects and, if
:attr:`~adapters.xplane.xplane_adapter.XPlaneSimAdapter.capabilities`
``.can_spawn_traffic`` is ``False`` (the plugin is not installed, or its
flight loop is not ticking — the exact distinction :func:`adapters.xplane.
traffic_bridge.probe` exists to make), skips rather than fails: that is a
legitimate, contract-tested adapter state (§8.2's
``test_traffic_methods_refuse_without_the_capability``), not a bug this file
exists to find.

**Runway incursion and TCAS conflict geometry is built relative to wherever
the live aircraft already is**, exactly like ``tests/sim/test_live_xplane.py``
builds its teleport targets relative to ``home`` — no real navdata is read
(hard rule 4), so a synthetic :class:`~core.models.Runway` a short distance
ahead of the aircraft's current track stands in for "on short final."
Geometry that needs the aircraft to be moving (``runway_incursion_track``
raises for a stationary one, by design — ``core/traffic.py``'s own D8) skips
rather than fails when the aircraft is parked.

Every test cleans up with ``despawn_traffic``/``clear_all_traffic`` in a
``finally``, and each connects its own adapter — the same one-adapter-per-test
convention every other file in this directory already uses.

**What this file cannot assert, per §1.2/§8.4 as written**: whether the live
aircraft's own cockpit TCAS instrument actually raises a TA/RA against a
spawned intruder. No ``SimAdapter`` method reads a TCAS instrument's advisory
state. ``test_tcas_conflict_spawns_and_advances_then_despawns`` prints the
live geometry so a human watching the sim can correlate it with whatever the
instrument does — an observation, never a programmatic assertion, exactly the
posture the design's own wording ("run in a live X-Plane," not "and assert
the RA fired") calls for.
"""

from __future__ import annotations

import asyncio
import math
import os
import time
from typing import Any

import httpx
import pytest

from adapters.xplane import XPlaneSimAdapter, traffic_bridge
from core.geodesy import (
    METRES_PER_NAUTICAL_MILE,
    distance_and_bearing,
    point_at_distance_and_bearing,
)
from core.models import GeoPosition, Runway
from core.traffic import (
    TrafficCapacityExceeded,
    runway_incursion_track,
    taxi_traffic_track,
    tcas_conflict_track,
)

pytestmark = pytest.mark.sim

#: How far ahead of the live aircraft's own position the synthetic runway
#: threshold (runway incursion) is placed. Close enough that even a slow
#: light aircraft crosses it within this file's poll budgets.
_RUNWAY_AHEAD_NM = 0.5

#: §5.4/D6's own convention: a runway incursion vehicle crossing shortly
#: before the user arrives — "on short final."
_RUNWAY_LEAD_TIME_S = 5.0

_POLL_INTERVAL_S = 1.0
_RUNWAY_POLL_BUDGET_S = 90.0
_RUNWAY_CENTRELINE_TOLERANCE_M = 60.0

#: How long to let the TCAS intruder fly its track before checking it has
#: actually moved — a "did the bridge really drive this entity in real time"
#: check, not a wait for the full ~100 s TCAS_SEVERITY_PROFILES spawn-to-CPA
#: leg (ai-traffic.md §6.1): the contract suite's own
#: ``test_traffic_advances_along_its_track`` already pins the interpolation
#: maths exactly; this only needs to prove the bridge is live-driving it.
_TCAS_ADVANCE_WAIT_S = 8.0
#: TCAS_DEFAULT_CLOSURE_IAS_KT (250 kt) covers well over this in
#: _TCAS_ADVANCE_WAIT_S even allowing for a slow HTTP round trip either side.
_TCAS_MIN_ADVANCE_M = 200.0
_SPAWN_POSITION_TOLERANCE_M = 100.0

#: Opt-in gate for the capacity test (§8.4: "explicitly marked slow/opt-in --
#: spawning a capacity-full set of real traffic entities is not something to
#: do on every -m sim run"). No new pytest marker is registered for this:
#: pyproject.toml's marker list is shared-foundation config outside this
#: task's file scope, so the opt-in is a plain environment variable instead.
_CAPACITY_TEST_ENV_VAR = "OIS_RUN_TRAFFIC_CAPACITY_TEST"

#: Real X-Plane datarefs (not bridge-registered) used only by the TCAS-target
#: read-back test — the §10.4 spike's own "present and writable" findings.
_TCAS_MODES_ID_DATAREF = "sim/cockpit2/tcas/targets/modeS_id"
_TCAS_POSITION_TEMPLATE = "sim/cockpit2/tcas/targets/position/double/plane{slot}_{axis}"


def _here(state: Any) -> GeoPosition:
    return GeoPosition(
        latitude=state.latitude, longitude=state.longitude, altitude_ft=state.altitude_ft
    )


async def _closest_approach_m(
    adapter: XPlaneSimAdapter, traffic_id: str, target: GeoPosition, *, budget_s: float
) -> float:
    """Poll ``get_traffic_contacts()`` for ``budget_s`` seconds and return the
    smallest observed distance, in metres, from ``traffic_id`` to ``target``.

    Polling for a closest approach rather than computing one exact wall-clock
    offset to check at sidesteps the real HTTP/flight-loop jitter between
    "when this test's clock started" and "when the bridge's own heartbeat_s
    considers the entity spawned" — the same reasoning
    ``test_live_xplane.py``'s own arrival polling uses.
    """
    closest_m = math.inf
    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        for contact in await adapter.get_traffic_contacts():
            if contact.traffic_id != traffic_id:
                continue
            distance_nm, _ = distance_and_bearing(
                GeoPosition(
                    latitude=contact.latitude,
                    longitude=contact.longitude,
                    altitude_ft=contact.altitude_ft,
                ),
                target,
            )
            closest_m = min(closest_m, distance_nm * METRES_PER_NAUTICAL_MILE)
        await asyncio.sleep(_POLL_INTERVAL_S)
    return closest_m


async def test_tcas_conflict_spawns_and_advances_then_despawns() -> None:
    """Phase 3 exit criterion 4's TCAS half: spawn a head-on RA intruder ahead
    of the live aircraft, confirm the bridge places it and then live-drives
    it along the track, despawn it, and confirm it clears from ``contacts`` —
    not ``sim/multiplayer/position/plane*`` (§8.4: those slots never populate
    under XPLMInstance driving, per the §10.4 spike).
    """
    adapter = XPlaneSimAdapter()
    await adapter.connect()
    try:
        if not adapter.capabilities.can_spawn_traffic:
            pytest.skip("bridge/ plugin not installed on this connection")

        state = await adapter.get_aircraft_state()
        track = tcas_conflict_track(state, severity="head_on_ra")
        contact = await adapter.spawn_traffic(track)
        try:
            assert contact.traffic_id
            assert contact.kind == "aircraft"
            assert contact.scenario_shape == "tcas_conflict"

            spawn_distance_nm, _ = distance_and_bearing(
                GeoPosition(
                    latitude=contact.latitude,
                    longitude=contact.longitude,
                    altitude_ft=contact.altitude_ft,
                ),
                track.waypoints[0].position,
            )
            assert spawn_distance_nm * METRES_PER_NAUTICAL_MILE <= _SPAWN_POSITION_TOLERANCE_M, (
                "the bridge's own first-frame contact was nowhere near the track's spawn waypoint"
            )

            await asyncio.sleep(_TCAS_ADVANCE_WAIT_S)
            live_contacts = await adapter.get_traffic_contacts()
            live = next((c for c in live_contacts if c.traffic_id == contact.traffic_id), None)
            assert live is not None, "the intruder disappeared from contacts before it should have"
            advanced_nm, _ = distance_and_bearing(
                track.waypoints[0].position,
                GeoPosition(
                    latitude=live.latitude, longitude=live.longitude, altitude_ft=live.altitude_ft
                ),
            )
            advanced_m = advanced_nm * METRES_PER_NAUTICAL_MILE
            assert advanced_m >= _TCAS_MIN_ADVANCE_M, (
                f"the intruder only moved {advanced_m:.0f} m in {_TCAS_ADVANCE_WAIT_S:.0f}s -- "
                "the bridge does not appear to be live-driving the track"
            )
            print(
                f"[observation] TCAS intruder {advanced_m:.0f} m along its track after "
                f"{_TCAS_ADVANCE_WAIT_S:.0f}s, heading {live.heading_deg:.0f}, "
                f"speed {live.ground_speed_kt:.0f} kt -- watch the live aircraft's own TCAS "
                "instrument for a TA/RA; nothing here asserts it (§1.2, §8.4)."
            )
        finally:
            await adapter.despawn_traffic(contact.traffic_id)
            remaining = await adapter.get_traffic_contacts()
            still_there = [c for c in remaining if c.traffic_id == contact.traffic_id]
            assert not still_there, "the intruder was still reported after despawn_traffic"
    finally:
        await adapter.clear_all_traffic()
        await adapter.disconnect()


async def test_runway_incursion_crosses_the_centreline_near_the_computed_time() -> None:
    """Phase 3 exit criterion 4's runway-incursion half: a vehicle timed
    against the live aircraft's own closing speed on a synthetic short final,
    asserted on the runway centreline at the crossing time — not assumed, the
    §4.5-style "poll for a closest approach" pattern used throughout this
    file.
    """
    adapter = XPlaneSimAdapter()
    await adapter.connect()
    try:
        if not adapter.capabilities.can_spawn_traffic:
            pytest.skip("bridge/ plugin not installed on this connection")

        state = await adapter.get_aircraft_state()
        if state.ias_kt <= 0.0:
            pytest.skip(
                "runway_incursion_track needs a moving aircraft to time the crossing against"
            )

        here = _here(state)
        threshold = point_at_distance_and_bearing(here, _RUNWAY_AHEAD_NM, state.heading_deg)
        runway = Runway(
            airport_icao="ZZZZ",
            ident="TS",
            threshold=GeoPosition(
                latitude=threshold.latitude,
                longitude=threshold.longitude,
                altitude_ft=state.altitude_ft,
            ),
            true_bearing_deg=state.heading_deg,
            length_m=1000.0,
            elevation_ft=state.altitude_ft,
        )
        track = runway_incursion_track(
            runway, state, lead_time_before_user_arrival_s=_RUNWAY_LEAD_TIME_S
        )
        contact = await adapter.spawn_traffic(track)
        try:
            assert contact.kind == "ground_vehicle"
            assert contact.scenario_shape == "runway_incursion"

            closest_m = await _closest_approach_m(
                adapter, contact.traffic_id, runway.threshold, budget_s=_RUNWAY_POLL_BUDGET_S
            )
            assert closest_m <= _RUNWAY_CENTRELINE_TOLERANCE_M, (
                f"the incursion vehicle never came within {_RUNWAY_CENTRELINE_TOLERANCE_M:.0f} m "
                f"of the runway centreline crossing point (closest observed: {closest_m:.1f} m)"
            )
        finally:
            await adapter.despawn_traffic(contact.traffic_id)
    finally:
        await adapter.clear_all_traffic()
        await adapter.disconnect()


async def test_tcas_target_write_is_read_back() -> None:
    """§10.4's precondition for re-baselining ``MAX_CONCURRENT_TRAFFIC_XPLANE``
    toward the 64-entry TCAS table: a real TCAS-target write, actually
    verified by reading it back, rather than trusting X-Plane's own
    ``writable = true`` (the multiplayer-slot result was the reminder that it
    can lie). This test only records the finding — re-baselining the
    capacity constant itself is a follow-up for once a live run has actually
    confirmed this passes, not something to change speculatively from a run
    that has not happened.

    Reads ``sim/cockpit2/tcas/targets/modeS_id`` (a real, non-bridge X-Plane
    dataref) before and after spawning a TCAS conflict aircraft, and looks for
    a slot that went from empty (``0``) to claimed — implementation-agnostic
    to exactly which slot the bridge chose, so this does not depend on any
    private numbering scheme ``bridge/`` happens to use internally.
    """
    adapter = XPlaneSimAdapter()
    await adapter.connect()
    try:
        if not adapter.capabilities.can_spawn_traffic:
            pytest.skip("bridge/ plugin not installed on this connection")

        async with httpx.AsyncClient(base_url=adapter.base_url, timeout=10.0) as raw_client:
            modes_id_ref = await _resolve_dataref_id(raw_client, _TCAS_MODES_ID_DATAREF)
            if modes_id_ref is None:
                pytest.skip(f"{_TCAS_MODES_ID_DATAREF!r} not in this build's dataref index")

            before = await _read_raw_dataref(raw_client, modes_id_ref)
            state = await adapter.get_aircraft_state()
            track = tcas_conflict_track(state, severity="ta_only")
            contact = await adapter.spawn_traffic(track)
            try:
                await asyncio.sleep(1.0)  # let one bridge flight loop publish the write
                after = await _read_raw_dataref(raw_client, modes_id_ref)
                claimed_slots = [
                    slot
                    for slot, (was, now) in enumerate(zip(before, after, strict=True))
                    if was in (0, None) and now not in (0, None)
                ]
                if not claimed_slots:
                    pytest.fail(
                        "no modeS_id slot changed after spawning a TCAS conflict aircraft -- "
                        "the bridge's TCAS-target write did not take (ai-traffic.md §10.4's "
                        "open question)"
                    )
                slot = claimed_slots[0]
                lat_ref = await _resolve_dataref_id(
                    raw_client, _TCAS_POSITION_TEMPLATE.format(slot=slot, axis="lat")
                )
                lon_ref = await _resolve_dataref_id(
                    raw_client, _TCAS_POSITION_TEMPLATE.format(slot=slot, axis="lon")
                )
                assert lat_ref is not None and lon_ref is not None
                target_lat = await _read_raw_dataref(raw_client, lat_ref)
                target_lon = await _read_raw_dataref(raw_client, lon_ref)
                distance_nm, _ = distance_and_bearing(
                    GeoPosition(latitude=float(target_lat), longitude=float(target_lon)),
                    GeoPosition(latitude=contact.latitude, longitude=contact.longitude),
                )
                assert distance_nm * METRES_PER_NAUTICAL_MILE <= _SPAWN_POSITION_TOLERANCE_M, (
                    "the claimed TCAS-target slot's own position does not match the spawned "
                    "entity's contact position"
                )
            finally:
                await adapter.despawn_traffic(contact.traffic_id)
    finally:
        await adapter.clear_all_traffic()
        await adapter.disconnect()


async def test_spawn_capacity_is_enforced_live() -> None:
    """§8.4's slow/opt-in capacity test — real traffic entities, not the Fake's."""
    if not os.environ.get(_CAPACITY_TEST_ENV_VAR):
        pytest.skip(f"set {_CAPACITY_TEST_ENV_VAR}=1 to run this slow, traffic-heavy test")

    adapter = XPlaneSimAdapter()
    await adapter.connect()
    spawned: list[str] = []
    try:
        if not adapter.capabilities.can_spawn_traffic:
            pytest.skip("bridge/ plugin not installed on this connection")

        state = await adapter.get_aircraft_state()
        here = _here(state)
        for index in range(traffic_bridge.MAX_CONCURRENT_TRAFFIC_XPLANE):
            far = point_at_distance_and_bearing(here, 0.05, float(index * 17 % 360))
            track = taxi_traffic_track(
                route=(here, far), kind="ground_vehicle", callsign=f"CAP{index:02d}"
            )
            contact = await adapter.spawn_traffic(track)
            spawned.append(contact.traffic_id)

        overflow = taxi_traffic_track(
            route=(here, point_at_distance_and_bearing(here, 0.05, 0.0)),
            kind="ground_vehicle",
            callsign="CAPX",
        )
        with pytest.raises(TrafficCapacityExceeded):
            await adapter.spawn_traffic(overflow)
    finally:
        for traffic_id in spawned:
            await adapter.despawn_traffic(traffic_id)
        await adapter.clear_all_traffic()
        await adapter.disconnect()


async def _resolve_dataref_id(client: httpx.AsyncClient, path: str) -> int | None:
    """One-off resolve of a raw dataref path — the diagnostic escape hatch
    this file needs for two X-Plane datarefs (`modeS_id`, the per-slot TCAS
    position doubles) that are outside :data:`adapters.xplane.xplane_adapter.DATAREFS`/
    :data:`adapters.xplane.xplane_adapter.OPTIONAL_DATAREFS` on purpose —
    they exist only to verify a §10.4 open question, not for the adapter's
    general use, so they are not added to its production dataref mapping.
    """
    response = await client.get("/api/v2/datarefs", params={"filter[name]": path})
    response.raise_for_status()
    entries = response.json().get("data", [])
    return int(entries[0]["id"]) if entries else None


async def _read_raw_dataref(client: httpx.AsyncClient, dataref_id: int) -> Any:
    response = await client.get(f"/api/v2/datarefs/{dataref_id}/value")
    response.raise_for_status()
    return response.json()["data"]
