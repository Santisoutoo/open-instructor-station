"""X-Plane connection diagnostic: can this machine drive the simulator?

Originally the Phase 0 spike that settled whether an external application can
reposition the aircraft at all. That question is answered — it can, and the
adapter does it — so this script now serves as the diagnostic you run when
something is wrong, or on a new X-Plane build, before trusting any placement.

It exercises the whole chain end to end:

1. Connect and resolve the dataref index.
2. **Measure** the local frame origin from the aircraft and print the residual.
   This is the step that matters: ``lat_ref``/``lon_ref`` were observed to
   advertise an origin 200 km from the real one, so the origin is derived from
   the aircraft's own position instead of trusted.
3. Teleport 5 NM north (plus 2000 ft if the aircraft is on the ground, so the
   result is unambiguous), then read the position back.
4. Restore the original position and report the error.

Run it with X-Plane loaded into a flight::

    python spikes/xplane_connection.py [--host localhost] [--port 8086]

Exit codes: ``0`` everything works, ``1`` X-Plane not reachable, ``2`` the
simulator answered but repositioning did not work.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.xplane import XPlaneSimAdapter
from adapters.xplane.xplane_adapter import (
    XPlaneNotReachable,
    XPlaneRepositionFailed,
)
from core.geodesy import (
    METRES_PER_NAUTICAL_MILE,
    distance_and_bearing,
    point_at_distance_and_bearing,
)
from core.local_frame import LocalCoordinates, world_to_local
from core.models import GeoPosition

TELEPORT_NM = 5.0
GROUND_CLEARANCE_FT = 2000.0
RESIDUAL_WARNING_M = 1.0


def rule(title: str) -> None:
    """Print a section header."""
    print(f"\n--- {title} " + "-" * max(0, 58 - len(title)))


async def run(host: str, port: int) -> int:
    """Run the diagnostic. Returns the process exit code."""
    adapter = XPlaneSimAdapter(host=host, port=port)

    rule("CONNECT")
    try:
        await adapter.connect()
    except XPlaneNotReachable as exc:
        print(f"  FAILED: {exc}\n")
        print("  Checklist:")
        print("    * X-Plane 12.1 or newer is running and loaded into a flight")
        print("      (the main menu is not enough - the datarefs mean nothing there)")
        print("    * Settings > Network: the web server / Web API is enabled")
        print(f"    * Nothing else is holding {adapter.base_url}")
        return 1
    print(f"  connected to {adapter.base_url}")

    try:
        state = await adapter.get_aircraft_state()
        home = GeoPosition(
            latitude=state.latitude,
            longitude=state.longitude,
            altitude_ft=state.altitude_ft,
        )
        rule("CURRENT STATE")
        print(f"  lat {state.latitude:.8f}  lon {state.longitude:.8f}")
        print(f"  alt {state.altitude_ft:9.1f} ft   heading {state.heading_deg:5.1f}")
        print(f"  IAS {state.ias_kt:9.1f} kt   on ground: {state.on_ground}")
        print(f"  crash flag: {await adapter.has_crashed()}")

        rule("LOCAL FRAME CALIBRATION")
        origin = await adapter.measure_local_frame_origin()
        local = LocalCoordinates(
            x_m=float(await adapter.read_dataref("local_x")),
            y_m=float(await adapter.read_dataref("local_y")),
            z_m=float(await adapter.read_dataref("local_z")),
        )
        projected = world_to_local(origin, home)
        residual = max(
            abs(projected.x_m - local.x_m),
            abs(projected.y_m - local.y_m),
            abs(projected.z_m - local.z_m),
        )
        print(f"  origin measured : {origin.latitude:.6f}, {origin.longitude:.6f}")
        print(f"  vertical offset : {origin.vertical_offset_m:.3f} m")
        print(f"  aircraft local  : x {local.x_m:.1f}  y {local.y_m:.1f}  z {local.z_m:.1f}")
        print(f"  residual        : {residual:.6f} m")
        if residual > RESIDUAL_WARNING_M:
            print("  WARNING: the residual should be ~0. The local axis convention may")
            print("           differ on this build; placement cannot be trusted.")

        rule(f"TELEPORT {TELEPORT_NM:.0f} NM NORTH")
        target_ll = point_at_distance_and_bearing(home, TELEPORT_NM, 0.0)
        target = GeoPosition(
            latitude=target_ll.latitude,
            longitude=target_ll.longitude,
            altitude_ft=home.altitude_ft + (GROUND_CLEARANCE_FT if state.on_ground else 0.0),
        )
        print(
            f"  target: {target.latitude:.8f}, {target.longitude:.8f} @ {target.altitude_ft:.0f} ft"
        )

        try:
            await adapter.set_position(target, heading_deg=state.heading_deg)
        except XPlaneRepositionFailed as exc:
            print(f"\n  VERDICT: REPOSITIONING FAILED\n  {exc}\n")
            print("  Next thing to try: the legacy UDP VEHX/VEH1 packet on port 49000,")
            print("  which positions the aircraft without a plugin.")
            return 2

        after = await adapter.get_aircraft_state()
        travelled_nm, bearing = distance_and_bearing(
            home, GeoPosition(latitude=after.latitude, longitude=after.longitude)
        )
        print(
            f"  arrived: {after.latitude:.8f}, {after.longitude:.8f} @ {after.altitude_ft:.0f} ft"
        )
        print(f"  moved {travelled_nm:.3f} NM on bearing {bearing:.1f}")
        print(f"  crash flag after teleport: {await adapter.has_crashed()}")

        rule("RESTORE")
        await adapter.set_position(home, heading_deg=state.heading_deg)
        restored = await adapter.get_aircraft_state()
        error_nm, _ = distance_and_bearing(
            home, GeoPosition(latitude=restored.latitude, longitude=restored.longitude)
        )
        print(f"  back at {restored.latitude:.8f}, {restored.longitude:.8f}")
        print(f"  error vs original: {error_nm * METRES_PER_NAUTICAL_MILE:.2f} m")
        print(f"  crash flag: {await adapter.has_crashed()}")

        rule("VERDICT")
        print("  Repositioning WORKS over the Web API. No plugin required.")
        print("  The instructor station can drive this simulator.")
        return 0
    finally:
        await adapter.disconnect()


def main() -> int:
    """Parse arguments and run the diagnostic."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8086)
    args = parser.parse_args()
    return asyncio.run(run(args.host, args.port))


if __name__ == "__main__":
    raise SystemExit(main())
