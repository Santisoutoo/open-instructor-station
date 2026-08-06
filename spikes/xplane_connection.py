"""Spike: can we read *and write* the aircraft position over the X-Plane Web API?

Answering that is the whole point of Phase 0. Run it against a live X-Plane
12.1+ and read the verdict at the bottom. Throwaway script: not imported by the
app, not covered by tests.

    python spikes/xplane_connection.py [--host localhost] [--port 8086]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import httpx
from websockets.asyncio.client import connect

from core.geodesy import METRES_PER_NAUTICAL_MILE, distance_and_bearing
from core.geodesy import point_at_distance_and_bearing as offset
from core.models import GeoPosition

WANTED: dict[str, str] = {
    "latitude": "sim/flightmodel/position/latitude",
    "longitude": "sim/flightmodel/position/longitude",
    "elevation": "sim/flightmodel/position/elevation",
}
TELEPORT_NM = 5.0
SETTLE_S = 2.0
TOLERANCE_M = 250.0
FEET_PER_METRE = 1.0 / 0.3048


async def resolve_ids(client: httpx.AsyncClient) -> dict[str, int]:
    """Step 1: GET the dataref index and pick out the ids we need."""
    response = await client.get("/api/v2/datarefs")
    response.raise_for_status()
    by_name = {entry["name"]: int(entry["id"]) for entry in response.json()["data"]}
    ids = {key: by_name[path] for key, path in WANTED.items() if path in by_name}
    missing = sorted(set(WANTED) - set(ids))
    if missing:
        raise RuntimeError(f"dataref index has no entry for: {[WANTED[key] for key in missing]}")
    print(f"[1/4] Resolved dataref ids: {ids}")
    return ids


async def read_position(client: httpx.AsyncClient, ids: dict[str, int]) -> GeoPosition:
    """Read latitude/longitude/elevation (elevation is metres MSL) as a GeoPosition."""
    values: dict[str, float] = {}
    for key, dataref_id in ids.items():
        response = await client.get(f"/api/v2/datarefs/{dataref_id}/value")
        response.raise_for_status()
        values[key] = float(response.json()["data"])
    return GeoPosition(
        latitude=values["latitude"],
        longitude=values["longitude"],
        altitude_ft=values["elevation"] * FEET_PER_METRE,
    )


async def watch_websocket(ws_url: str, ids: dict[str, int], updates: int = 10) -> None:
    """Step 2: subscribe over the WebSocket and print live updates."""
    print(f"[2/4] Opening WebSocket {ws_url}, subscribing to {len(ids)} datarefs")
    subscription = {
        "req_id": 1,
        "type": "dataref_subscribe_values",
        "params": {"datarefs": [{"id": dataref_id} for dataref_id in ids.values()]},
    }
    async with connect(ws_url) as socket:
        await socket.send(json.dumps(subscription))
        seen = 0
        while seen < updates:
            raw = await asyncio.wait_for(socket.recv(), timeout=10.0)
            message = json.loads(raw)
            if message.get("type") != "dataref_update_values":
                continue
            seen += 1
            print(f"      update {seen:>2}: {message['data']}")


async def attempt_teleport(client: httpx.AsyncClient, ids: dict[str, int]) -> bool:
    """Step 3: write a position 5 NM north, read it back, and say whether it stuck."""
    before = await read_position(client, ids)
    target = offset(before, TELEPORT_NM, 0.0)
    print(f"[3/4] BEFORE  lat={before.latitude:.6f} lon={before.longitude:.6f}")
    print(f"      TARGET  lat={target.latitude:.6f} lon={target.longitude:.6f}")

    writes = (
        ("latitude", target.latitude),
        ("longitude", target.longitude),
        ("elevation", target.altitude_ft / FEET_PER_METRE),
    )
    for key, value in writes:
        response = await client.patch(f"/api/v2/datarefs/{ids[key]}/value", json={"data": value})
        print(f"      PATCH {WANTED[key]} -> HTTP {response.status_code}")

    await asyncio.sleep(SETTLE_S)
    after = await read_position(client, ids)
    print(f"      AFTER   lat={after.latitude:.6f} lon={after.longitude:.6f}")

    moved_nm, _ = distance_and_bearing(before, after)
    error_nm, _ = distance_and_bearing(after, target)
    error_m = error_nm * METRES_PER_NAUTICAL_MILE
    print(f"      moved {moved_nm:.3f} NM; {error_m:.0f} m from the target")
    return error_m <= TOLERANCE_M


def verdict(worked: bool) -> int:
    """Step 4: print the actionable conclusion and return the process exit code."""
    print("\n[4/4] VERDICT")
    if worked:
        print("      REPOSITIONING OVER THE WEB API WORKS. The aircraft landed on the")
        print("      requested position; XPlaneSimAdapter.set_position can stay as it is.")
        return 0
    print("      REPOSITIONING OVER THE WEB API DOES NOT WORK: X-Plane recomputed")
    print("      latitude/longitude from local_x/y/z on the next frame.")
    print("      NEXT THING TO TRY: the legacy UDP VEHX/VEH1 packet on port 49000")
    print(r"      ('VEHX\0' + int index + double lat/lon/alt + float psi/theta/phi),")
    print("      which positions the aircraft without a plugin. Pause the sim around")
    print("      long teleports so the scenery reload does not fight the write.")
    return 2


async def run(host: str, port: int) -> int:
    """Run the whole spike and return the process exit code."""
    async with httpx.AsyncClient(base_url=f"http://{host}:{port}", timeout=10.0) as client:
        ids = await resolve_ids(client)
        await watch_websocket(f"ws://{host}:{port}/api/v2", ids)
        return verdict(await attempt_teleport(client, ids))


def main() -> int:
    """Parse arguments, run the spike, and turn every failure into advice."""
    parser = argparse.ArgumentParser(description="X-Plane Web API connection spike")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8086)
    args = parser.parse_args()

    print(f"X-Plane connection spike -> http://{args.host}:{args.port}\n")
    try:
        return asyncio.run(run(args.host, args.port))
    except (httpx.HTTPError, OSError) as exc:
        print(f"\nCANNOT REACH X-PLANE at {args.host}:{args.port}")
        print(f"  ({type(exc).__name__}: {exc})")
        print("  1. Start X-Plane 12.1 or newer.")
        print("  2. Settings > Network > enable the Web API (default port 8086).")
        print("  3. Load an aircraft and a location, then run this script again.")
        return 1
    except (RuntimeError, TimeoutError, KeyError) as exc:
        print(f"\nSPIKE FAILED: {type(exc).__name__}: {exc}")
        print("  The Web API answered but not in the shape this script expects.")
        print("  Check the X-Plane version (the /api/v2 schema needs 12.1 or newer).")
        return 1


if __name__ == "__main__":
    sys.exit(main())
