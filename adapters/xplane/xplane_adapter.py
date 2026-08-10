"""X-Plane 12.1+ adapter over the built-in Web API (REST, default port 8086).

Status: **repositioning VALIDATED against a live X-Plane 12 (LEMD, 2026-08-06).**

Writing a position is the project's key technical risk, and the measurements
that settled it are worth stating precisely, because two of them are traps:

* ``sim/flightmodel/position/latitude``/``longitude``/``elevation`` are
  **read-only**. The authoritative position is the local OpenGL frame
  (``local_x``/``local_y``/``local_z``), which *is* writable. The world
  coordinates are derived from it every frame, which makes reading them back
  the honest verdict on whether a write took effect.
* The world→local conversion normally needs ``XPLMWorldToLocal``, a plugin-only
  API. It can be done externally instead — see :mod:`core.local_frame`.
* **``lat_ref``/``lon_ref`` cannot be trusted.** On the validation run they
  advertised 39.0N/6.0W while the frame's true origin was 40.5N/4.0W — a 200 km
  error that would land every teleport in the wrong province. The origin is
  therefore *measured* from the aircraft's own position, which is known in both
  coordinate systems simultaneously. See :func:`core.local_frame.origin_from_observation`.
* **The frame origin is not stable either.** X-Plane relocates it during the
  scenery reload a long teleport provokes, and the coordinates written before
  the reload then denote a different place on earth — Madrid to Heathrow used to
  poll for the full budget and fail with the write having been accepted
  (issue #36). A measurement is therefore only good for as long as the frame it
  described, and :meth:`XPlaneSimAdapter.set_position` re-measures and re-aims
  rather than trusting the one it started with.

The validated procedure is five steps, and skipping any of them breaks
something:

1. Freeze the flight model (``override_planepath[0] = 1``).
2. Write ``local_x``/``local_y``/``local_z`` — and write them **again**, in the
   frame that is current afterwards, if the arrival poll says the aircraft is
   somewhere else because a scenery reload moved the frame under the write.
3. Write the **velocity vector** (``local_vx/vy/vz``) and heading. Writing zeros
   drops the aircraft out of the sky at stall speed; this adapter carries the
   aircraft's current speed onto the new heading, converted from indicated to
   true airspeed for the density altitude it is being placed *at* — the local
   frame's velocity is a true one. See
   :meth:`XPlaneSimAdapter._true_airspeed_kt`, which runs before the aircraft
   moves, because the atmosphere it needs is the one at the destination.
4. Release the override.
5. Clear the crash state (``sim/operation/fix_all_systems``). X-Plane reads a
   teleport as an impact and marks the aircraft as wrecked otherwise.

Measured accuracy on the validation run: placement exact, restore to the
original position within 0.00 m, crash flag clear throughout.

**The freeze is not a position concern — it is a flight-model concern.**
Anything written into ``sim/flightmodel/position/*`` is fought by a running
flight model, attitude included. Measured against X-Plane 12.4.3 at LEMD, a
heading commanded at 322.21 while the model was live came back 286.9 with the
aircraft sitting *inverted on the runway* (``phi = -180.0``); the identical
write with ``override_planepath`` engaged read back 322.2 while frozen and
322.3 — 0.09° — after the release. Steps 1 and 4 therefore wrap every
flight-model write in this module, not just repositioning, and they are shared
through one helper: :meth:`XPlaneSimAdapter.frozen_flight_model`. Residual
pitch and roll after the release is the aircraft settling onto its gear; that
is physically correct and is not something to tune away.

Aircraft *configuration* — flaps, trim, gear, lights, radios and the autopilot —
is not part of the flight model's integration and is deliberately written
outside the freeze, so a setup that only changes a switch costs no pause.

**The autopilot has no method of its own** (issue #41). It arrives through
:meth:`XPlaneSimAdapter.apply_setup` like every other switch, gated by
``can_control_autopilot``, and X-Plane's own shape is honoured rather than
flattened: the master switch and the flight director are one three-valued
dataref, and the lateral modes are selected by command because their status
datarefs are read-only. See :meth:`XPlaneSimAdapter._write_autopilot`.

This module imports cleanly with no simulator present and opens no sockets
until :meth:`XPlaneSimAdapter.connect` is awaited.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import httpx

from core.atmosphere import isa_deviation_c, tas_from_ias, temperature_from_deviation_c
from core.geodesy import METRES_PER_NAUTICAL_MILE, distance_and_bearing
from core.local_frame import (
    LocalCoordinates,
    LocalFrameOrigin,
    origin_from_observation,
    origin_separation_m,
    world_to_local,
)
from core.models import AircraftSetup, AircraftState, GeoPosition
from core.sim_adapter import Capabilities, CapabilityNotSupported, SimAdapter

__all__ = ["COMMANDS", "DATAREFS", "DEFAULT_BASE_URL", "XPlaneSimAdapter"]

DEFAULT_BASE_URL = "http://localhost:8086"

#: Every X-Plane dataref this adapter touches, keyed by the short internal name
#: used throughout the module. Nothing outside this mapping is hard-coded.
#:
#: Deliberately absent: ``lat_ref``/``lon_ref``. They advertise a frame origin
#: that does not match the frame the sim actually uses (see the module
#: docstring), so this adapter measures the origin instead of reading it.
DATAREFS: dict[str, str] = {
    # --- World position: READ-ONLY, derived from the local frame -----------
    "latitude": "sim/flightmodel/position/latitude",
    "longitude": "sim/flightmodel/position/longitude",
    "elevation": "sim/flightmodel/position/elevation",  # metres MSL
    # --- Authoritative local OpenGL frame: +x east, +y up, +z south --------
    "local_x": "sim/flightmodel/position/local_x",
    "local_y": "sim/flightmodel/position/local_y",
    "local_z": "sim/flightmodel/position/local_z",
    "local_vx": "sim/flightmodel/position/local_vx",  # metres/second
    "local_vy": "sim/flightmodel/position/local_vy",
    "local_vz": "sim/flightmodel/position/local_vz",
    # --- Attitude ----------------------------------------------------------
    "psi": "sim/flightmodel/position/psi",  # true heading, degrees
    "theta": "sim/flightmodel/position/theta",  # pitch, degrees
    "phi": "sim/flightmodel/position/phi",  # roll, degrees
    "indicated_airspeed": "sim/flightmodel/position/indicated_airspeed",  # kt
    "vh_ind_fpm": "sim/flightmodel/position/vh_ind_fpm",  # feet per minute
    "on_ground": "sim/flightmodel/failures/onground_any",
    # --- Ambient conditions ------------------------------------------------
    # Needed to turn an indicated airspeed into the true one the local frame's
    # velocity vector is expressed in. X-Plane 12 moved this out of the flat
    # `sim/weather/` namespace it occupied in X-Plane 11; on an older build
    # connect() reports it missing rather than silently skipping the correction.
    "temperature_ambient_deg_c": "sim/weather/aircraft/temperature_ambient_deg_c",
    # --- Repositioning control --------------------------------------------
    "override_planepath": "sim/operation/override/override_planepath",  # int array
    "has_crashed": "sim/flightmodel2/misc/has_crashed",  # read-only
    # --- Aircraft configuration -------------------------------------------
    "flap_ratio": "sim/cockpit2/controls/flap_ratio",
    "speedbrake_ratio": "sim/cockpit2/controls/speedbrake_ratio",
    "elevator_trim": "sim/cockpit2/controls/elevator_trim",  # -1 .. +1
    "gear_handle_down": "sim/cockpit2/controls/gear_handle_down",
    "autobrake_level": "sim/cockpit2/switches/auto_brake_level",
    # --- Autopilot ---------------------------------------------------------
    # The master switch and the flight director are ONE dataref in X-Plane:
    # 0 = off, 1 = flight director only, 2 = servos engaged. See
    # `_autopilot_mode_for`, which is where the two boolean fields are folded
    # back into it.
    "autopilot_mode": "sim/cockpit/autopilot/autopilot_mode",
    "autopilot_altitude_dial_ft": "sim/cockpit2/autopilot/altitude_dial_ft",
    "autopilot_airspeed_dial": "sim/cockpit2/autopilot/airspeed_dial_kts_mach",
    "autopilot_airspeed_is_mach": "sim/cockpit2/autopilot/airspeed_is_mach",
    "autopilot_heading_dial_deg": "sim/cockpit2/autopilot/heading_dial_deg_mag_pilot",
    "autopilot_vvi_dial_fpm": "sim/cockpit2/autopilot/vvi_dial_fpm",
    # --- Lights ------------------------------------------------------------
    "landing_lights": "sim/cockpit2/switches/landing_lights_on",
    "taxi_lights": "sim/cockpit2/switches/taxi_light_on",
    "nav_lights": "sim/cockpit2/switches/navigation_lights_on",
    "beacon_lights": "sim/cockpit2/switches/beacon_on",
    "strobe_lights": "sim/cockpit2/switches/strobe_lights_on",
    # --- Radios (X-Plane stores NAV frequencies in units of 10 kHz) --------
    "nav1_freq": "sim/cockpit/radios/nav1_freq_hz",
    "nav2_freq": "sim/cockpit/radios/nav2_freq_hz",
    "obs1": "sim/cockpit/radios/nav1_obs_degm",
    "obs2": "sim/cockpit/radios/nav2_obs_degm",
}

#: Commands this adapter activates, keyed by short internal name.
COMMANDS: dict[str, str] = {
    # Repairs every failed system, which includes clearing the crash state a
    # teleport provokes. Step 5 of the repositioning procedure.
    "fix_all_systems": "sim/operation/fix_all_systems",
    # --- Autopilot lateral mode selection ---------------------------------
    # X-Plane exposes the *armed/captured* lateral mode as read-only status
    # datarefs (`nav_status`, `approach_status`, …) and selects it through
    # commands. There is deliberately no per-mode "off": the lateral modes are
    # mutually exclusive, so deselecting one means selecting another, and
    # wing-leveller is X-Plane's neutral one.
    "autopilot_nav": "sim/autopilot/NAV",
    "autopilot_approach": "sim/autopilot/approach",
    "autopilot_heading": "sim/autopilot/heading",
    "autopilot_wing_leveler": "sim/autopilot/wing_leveler",
}

_CAPABILITIES = Capabilities(
    can_set_position=True,
    can_set_aircraft_state=True,
    can_control_autopilot=True,
    # The rest arrive in later phases.
    can_set_weather=False,
    can_inject_failures=False,
    can_spawn_traffic=False,
    can_set_fuel_payload=False,
    can_control_camera=False,
    can_pushback=False,
)

_METRES_PER_FOOT = 0.3048
_METRES_PER_SECOND_PER_KNOT = 0.514444

#: Seconds to let the sim settle after engaging or releasing the override, and
#: after writing the position. Measured: one or two physics frames is enough,
#: these leave a wide margin over a loaded scenery reload.
_OVERRIDE_SETTLE_S = 0.3
_RELEASE_SETTLE_S = 1.0

#: Arrival is polled rather than assumed after a fixed delay. A short hop
#: settles in one frame, but a teleport of a few hundred kilometres triggers a
#: scenery reload, during which X-Plane relocates the local frame origin and the
#: derived world coordinates are briefly in transit. Polling handles both
#: without making the common case slow.
_ARRIVAL_POLL_S = 0.25

#: How long one write is given to show up before the adapter stops waiting and
#: asks *why* it has not (issue #36). This is the settle criterion, and the
#: number is chosen for what it rules out rather than for how long a reload
#: takes:
#:
#: The derived world coordinates lag a local-frame write by one or two frames —
#: tens of milliseconds. A slice is two orders of magnitude longer than that,
#: and every poll inside it is a *round trip X-Plane answered*. So when a slice
#: expires with the aircraft parked somewhere that is not the target, the sim
#: has demonstrably been running and publishing throughout, and "not there yet"
#: has been ruled out: the aircraft really is somewhere else, and the frame it
#: was aimed in is the prime suspect. A simulator stalled mid-reload does not
#: answer at all, so that case shows up as a slow poll and is absorbed by
#: :data:`_REPOSITION_TIMEOUT_S` rather than mistaken for a settled frame.
_ARRIVAL_ATTEMPT_S = 8.0

#: Total wall-clock budget for one :meth:`XPlaneSimAdapter.set_position`, across
#: every re-aim. Re-aiming must not turn a bounded failure into an unbounded
#: one, so the loop is bounded twice over: by this deadline and by
#: :data:`_MAX_REPOSITION_WRITES`.
_REPOSITION_TIMEOUT_S = 30.0

#: How many times one placement will aim at its target. The first write is the
#: common case. The second is the one that lands after a scenery reload has
#: moved the frame, which is the whole of issue #36. The third exists because a
#: re-measure can itself be overtaken by a second shift; a fourth would be
#: treating "the frame keeps moving" as something to out-wait, and it is not —
#: at that point the placement has failed and the instructor should be told.
_MAX_REPOSITION_WRITES = 3

#: Two frame-origin measurements further apart than this describe different
#: frames. Measured off the frozen aircraft they agree to millimetres; a scenery
#: shift moves the anchor by kilometres. The threshold sits between two scales
#: six orders of magnitude apart, which is why it has never needed tuning.
_ORIGIN_SHIFT_TOLERANCE_M = 50.0

#: Consecutive agreeing measurements required before a re-measured origin is
#: aimed with, and the gap between them. One measurement cannot tell a settled
#: frame from one sampled mid-shift; two that agree can.
_ORIGIN_STABLE_SAMPLES = 2
_ORIGIN_SAMPLE_S = 0.25

#: Read-back tolerance after a teleport, in metres. The check runs while the
#: flight model is still frozen, so the aircraft is not moving and this only has
#: to absorb float noise — not a second of flight.
POSITION_WRITE_TOLERANCE_M = 50.0

#: The three values of ``sim/cockpit/autopilot/autopilot_mode``. X-Plane models
#: the master switch and the flight director as one ladder rather than two
#: switches, which is physically right: servos without a flight director is not
#: a state a real autopilot has.
AUTOPILOT_MODE_OFF = 0
AUTOPILOT_MODE_FLIGHT_DIRECTOR = 1
AUTOPILOT_MODE_SERVOS = 2

#: Lateral-mode field -> the command that selects it, in the order they are
#: applied. The modes are mutually exclusive, so the last one activated wins:
#: the order runs from the least specific (heading) to the most specific
#: (approach), which is the sensible resolution of a contradictory setup.
_LATERAL_MODE_COMMANDS: tuple[tuple[str, str], ...] = (
    ("autopilot_hdg", "autopilot_heading"),
    ("autopilot_nav", "autopilot_nav"),
    ("autopilot_app", "autopilot_approach"),
)


class XPlaneNotReachable(RuntimeError):
    """The X-Plane Web API did not answer. Is the sim running with the API enabled?"""


class XPlaneRepositionFailed(RuntimeError):
    """The aircraft did not arrive where it was told to go."""


class XPlaneSimAdapter:
    """Talks to X-Plane 12.1+ over its built-in Web API.

    Args:
        host: Hostname or IP running X-Plane.
        port: Web API port (X-Plane's default is 8086).
        timeout_s: Per-request HTTP timeout in seconds.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8086,
        timeout_s: float = 5.0,
    ) -> None:
        self._base_url = f"http://{host}:{port}"
        self._timeout_s = timeout_s
        self._client: httpx.AsyncClient | None = None
        self._ids: dict[str, int] = {}
        self._command_ids: dict[str, int] = {}
        self._freeze_depth = 0

    # -- Identity ---------------------------------------------------------

    @property
    def name(self) -> str:
        """Adapter identifier."""
        return "xplane"

    @property
    def capabilities(self) -> Capabilities:
        """Phase 0 capabilities: position, aircraft state and autopilot only."""
        return _CAPABILITIES

    @property
    def is_connected(self) -> bool:
        """True once the dataref index has been fetched and resolved."""
        return self._client is not None and bool(self._ids)

    @property
    def base_url(self) -> str:
        """The Web API root, e.g. ``http://localhost:8086``."""
        return self._base_url

    # -- Lifecycle --------------------------------------------------------

    async def connect(self) -> None:
        """Resolve the ids of :data:`DATAREFS` and :data:`COMMANDS`.

        Raises:
            XPlaneNotReachable: if the Web API cannot be reached, or if the
                build is missing datarefs this adapter needs.
        """
        if self.is_connected:
            return
        client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout_s)
        try:
            response = await client.get("/api/v2/datarefs")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            await client.aclose()
            raise XPlaneNotReachable(
                f"Could not reach the X-Plane Web API at {self._base_url}. "
                "Start X-Plane 12.1 or newer and make sure its Web API is enabled."
            ) from exc

        wanted = {path: key for key, path in DATAREFS.items()}
        index: dict[str, int] = {}
        for entry in response.json().get("data", []):
            key = wanted.get(entry.get("name"))
            if key is not None:
                index[key] = int(entry["id"])

        missing = sorted(set(DATAREFS) - set(index))
        if missing:
            await client.aclose()
            raise XPlaneNotReachable(
                "The X-Plane dataref index is missing entries this adapter needs: "
                f"{', '.join(DATAREFS[key] for key in missing)}. "
                "This usually means an X-Plane version older than 12.1."
            )

        commands: dict[str, int] = {}
        for key, path in COMMANDS.items():
            command_response = await client.get("/api/v2/commands", params={"filter[name]": path})
            command_response.raise_for_status()
            entries = command_response.json().get("data", [])
            if not entries:
                await client.aclose()
                raise XPlaneNotReachable(f"X-Plane does not expose the command {path!r}.")
            commands[key] = int(entries[0]["id"])

        self._client = client
        self._ids = index
        self._command_ids = commands

    async def disconnect(self) -> None:
        """Close the HTTP client. Idempotent, never raises."""
        client, self._client = self._client, None
        self._ids = {}
        self._command_ids = {}
        if client is not None:
            await client.aclose()

    # -- Dataref plumbing -------------------------------------------------

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None or not self._ids:
            raise XPlaneNotReachable("Adapter is not connected; await connect() first.")
        return self._client

    async def _read(self, key: str) -> Any:
        """Read one dataref value by its short :data:`DATAREFS` key."""
        client = self._require_client()
        response = await client.get(f"/api/v2/datarefs/{self._ids[key]}/value")
        response.raise_for_status()
        return response.json()["data"]

    async def _write(self, key: str, value: float | int | bool, index: int | None = None) -> None:
        """Write one dataref value, optionally a single element of an array."""
        client = self._require_client()
        response = await client.patch(
            f"/api/v2/datarefs/{self._ids[key]}/value",
            json={"data": value},
            params=None if index is None else {"index": index},
        )
        response.raise_for_status()

    async def _activate(self, key: str) -> None:
        """Fire one X-Plane command by its short :data:`COMMANDS` key."""
        client = self._require_client()
        response = await client.post(
            f"/api/v2/command/{self._command_ids[key]}/activate",
            json={"duration": 0},
        )
        response.raise_for_status()

    # -- Reads ------------------------------------------------------------

    async def get_aircraft_state(self) -> AircraftState:
        """Read the user aircraft's position and attitude from X-Plane."""
        keys = (
            "latitude",
            "longitude",
            "elevation",
            "psi",
            "indicated_airspeed",
            "vh_ind_fpm",
            "theta",
            "phi",
            "on_ground",
        )
        raw = await asyncio.gather(*(self._read(key) for key in keys))
        values = dict(zip(keys, raw, strict=True))
        return AircraftState(
            latitude=float(values["latitude"]),
            longitude=float(values["longitude"]),
            altitude_ft=float(values["elevation"]) / _METRES_PER_FOOT,
            heading_deg=float(values["psi"]) % 360.0,
            ias_kt=max(0.0, float(values["indicated_airspeed"])),
            vertical_speed_fpm=float(values["vh_ind_fpm"]),
            pitch_deg=float(values["theta"]),
            roll_deg=float(values["phi"]),
            on_ground=bool(values["on_ground"]),
        )

    async def read_dataref(self, key: str) -> Any:
        """Read one dataref by its short :data:`DATAREFS` key.

        A deliberate escape hatch for diagnostics that need a raw value the
        typed API does not expose (the local frame coordinates, mostly).
        Application code should use :meth:`get_aircraft_state` instead.

        Args:
            key: A key of :data:`DATAREFS`, not a full dataref path.
        """
        return await self._read(key)

    async def measure_local_frame_origin(self) -> LocalFrameOrigin:
        """Measure the origin of X-Plane's local frame from the aircraft itself.

        The aircraft's position is readable in both coordinate systems at once,
        and that single pair pins the frame down exactly. This is deliberately
        *not* read from ``lat_ref``/``lon_ref``, which were measured to be wrong
        by 200 km — see the module docstring.

        Returns:
            The frame origin, including the vertical datum offset.
        """
        keys = ("latitude", "longitude", "elevation", "local_x", "local_y", "local_z")
        raw = await asyncio.gather(*(self._read(key) for key in keys))
        values = dict(zip(keys, raw, strict=True))
        return origin_from_observation(
            GeoPosition(
                latitude=float(values["latitude"]),
                longitude=float(values["longitude"]),
                altitude_ft=float(values["elevation"]) / _METRES_PER_FOOT,
            ),
            LocalCoordinates(
                x_m=float(values["local_x"]),
                y_m=float(values["local_y"]),
                z_m=float(values["local_z"]),
            ),
        )

    # -- Writes -----------------------------------------------------------

    @asynccontextmanager
    async def frozen_flight_model(self) -> AsyncIterator[None]:
        """Hold X-Plane's flight model still for the duration of the block.

        Steps 1 and 4 of the five-step procedure, in one place. Every write into
        ``sim/flightmodel/position/*`` belongs inside this — position, velocity
        *and* attitude. A running flight model resettles what you wrote within a
        frame or two, and the failure is not subtle: writing a 322.21° heading
        into a live model at LEMD produced 286.9° and left the aircraft inverted
        on the runway at ``phi = -180.0``. The same write inside this block read
        back 322.2° frozen and 322.3° after the release.

        On exit the override is released and the sim is given
        :data:`_RELEASE_SETTLE_S` to resume integrating, so the caller reads back
        a settled aircraft rather than one mid-transition. Whatever pitch and
        roll the aircraft has by then is it settling onto its landing gear — a
        physical result, not an error in the write.

        The release lives in a ``finally`` and that is the single most important
        line in this method: a leaked ``override_planepath`` freezes the user's
        aircraft indefinitely, with nothing in the UI to explain why.

        **It is re-entrant** (issue #48). A caller can hold one freeze around
        :meth:`set_position` or :meth:`apply_setup` *and* its own read-back, so
        the value it verifies is the value that was written rather than whatever
        the aircraft flew to afterwards — an airborne aircraft with nobody flying
        it was measured turning 4° to 170° between the write and the read. Only
        the outermost block writes ``override_planepath`` and pays the settle
        delays; nested blocks are no-ops. The nesting is a depth counter on a
        single task, not a cross-task lock: two concurrent tasks freezing the
        same adapter are not supported, and neither is anything else about
        driving one simulator from two places at once.

        Yields:
            ``None``. The block runs with the flight model frozen.
        """
        if self._freeze_depth == 0:
            await self._write("override_planepath", 1, index=0)
        self._freeze_depth += 1
        try:
            if self._freeze_depth == 1:
                await asyncio.sleep(_OVERRIDE_SETTLE_S)
            yield
        finally:
            self._freeze_depth -= 1
            if self._freeze_depth == 0:
                await self._write("override_planepath", 0, index=0)
                await asyncio.sleep(_RELEASE_SETTLE_S)

    async def set_position(self, position: GeoPosition, heading_deg: float) -> None:
        """Teleport the aircraft, preserving its current speed on the new heading.

        Runs the five-step procedure documented at the top of this module. The
        arrival is verified *while the flight model is still frozen*, so the
        check measures placement rather than a second of subsequent flight.

        **It aims more than once when it has to (issue #36).** A local-frame
        coordinate only means something in the frame it was computed in, and a
        teleport long enough to trigger a scenery reload moves that frame:
        Madrid to Heathrow used to write coordinates X-Plane accepted, land the
        aircraft somewhere else entirely, and then poll a target it could never
        converge on for the full budget. So a placement that has not arrived by
        the end of its slice is not waited out — the frame is re-measured, the
        target is recomputed in it, and the placement is written again. The
        convergence criterion is unchanged and is the only one that cannot lie:
        the aircraft's *world* position, which X-Plane derives from whatever
        frame is current, read back through :meth:`_position_matches`.

        The whole loop runs inside one freeze, which matters for the re-measure
        as much as for the write: the origin is recovered from the aircraft's own
        position read in two coordinate systems, and on a moving aircraft those
        reads describe two different instants.

        Args:
            position: Target position, ``altitude_ft`` interpreted as MSL.
            heading_deg: Target true heading in degrees.

        Raises:
            XPlaneRepositionFailed: if the aircraft did not arrive within
                :data:`POSITION_WRITE_TOLERANCE_M` after
                :data:`_MAX_REPOSITION_WRITES` attempts or
                :data:`_REPOSITION_TIMEOUT_S`, whichever comes first. Never
                reports an unobserved success.
        """
        origin = await self.measure_local_frame_origin()
        speed_kt = (await self.get_aircraft_state()).ias_kt
        # Resolved before the aircraft moves and against the *target* altitude:
        # the atmosphere the speed has to be true in is the destination's, and the
        # one the sim can be asked about is the departure's.
        tas_kt = await self._true_airspeed_kt(speed_kt, position.altitude_ft)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + _REPOSITION_TIMEOUT_S
        attempts = 0
        arrived = False

        async with self.frozen_flight_model():
            for attempt in range(_MAX_REPOSITION_WRITES):
                if attempt:
                    if loop.time() >= deadline:
                        break
                    # The previous aim missed. Either the write never took, or
                    # the frame it was expressed in no longer exists — and the
                    # second is both the likelier and the recoverable one.
                    origin = await self._settled_local_frame_origin(deadline)
                attempts += 1
                await self._write_placement(position, heading_deg, tas_kt, origin)
                arrived = await self._await_arrival(position, deadline)
                if arrived:
                    break

        await self.clear_crash_state()

        if not arrived:
            raise XPlaneRepositionFailed(
                f"The aircraft did not arrive within {POSITION_WRITE_TOLERANCE_M:.0f} m of "
                f"{position.latitude:.6f}, {position.longitude:.6f} after {attempts} attempt(s) "
                "at writing the local frame coordinates, each one aimed with a freshly measured "
                "frame origin. A frame that keeps moving is not the explanation at this point: "
                "the origin measurement or the local axis convention may be wrong on this build. "
                "Run spikes/xplane_connection.py, which prints the calibration residual, before "
                "trusting any further placement."
            )

    async def _write_placement(
        self,
        position: GeoPosition,
        heading_deg: float,
        tas_kt: float,
        origin: LocalFrameOrigin,
    ) -> None:
        """Steps 2 and 3 of the procedure, expressed in one frame.

        Kept together because they share that frame and must not be split
        across a re-aim: the local axes are the east/up/north triad **at the
        anchor**, so an anchor that moved several hundred kilometres has rotated
        them by the convergence of the meridians between the two. A re-aim that
        rewrote the coordinates but kept the old velocity vector would put the
        aircraft in the right place flying a heading it was not asked for.

        Args:
            position: Target position, ``altitude_ft`` interpreted as MSL.
            heading_deg: Target true heading in degrees.
            tas_kt: True airspeed to carry onto that heading, in knots.
            origin: The frame ``position`` is to be projected into.
        """
        target = world_to_local(origin, position)
        await self._write("local_x", target.x_m)
        await self._write("local_y", target.y_m)
        await self._write("local_z", target.z_m)
        await self._write_velocity_vector(heading_deg, tas_kt)
        await self._write("psi", heading_deg % 360.0)

    async def _settled_local_frame_origin(self, deadline: float) -> LocalFrameOrigin:
        """Measure the frame origin, and keep measuring until it stops moving.

        Detecting that the frame moved is easy; knowing *when* the new one can
        be trusted is the actual problem, because a measurement taken mid-reload
        is exactly as wrong as the stale one it replaces. Two things make this
        safe, and neither is a fixed sleep:

        * **This is never called early.** It runs only after a whole
          :data:`_ARRIVAL_ATTEMPT_S` slice of *answered* polls has failed to see
          the aircraft arrive — see that constant for why that rules out "the
          derived coordinates have not caught up yet" and why a simulator
          stalled inside a reload cannot be mistaken for a settled one.
        * **One measurement is not enough to conclude anything.** Sampling the
          instant of a shift yields an origin that is already historical, so
          :data:`_ORIGIN_STABLE_SAMPLES` consecutive measurements must agree to
          within :data:`_ORIGIN_SHIFT_TOLERANCE_M` before one is aimed with.
          Off a frozen aircraft in a settled frame that is satisfied on the
          first two samples, so the common recovery costs one extra round trip.

        And if both are somehow fooled, the caller's arrival check still refuses
        the result: a bad origin costs one more attempt, not a false success.

        Args:
            deadline: Event-loop time the whole reposition must finish by.
                Reaching it returns the latest measurement rather than raising —
                the verdict belongs to the arrival check, not to this.

        Returns:
            The frame origin to aim the next placement with.
        """
        loop = asyncio.get_running_loop()
        origin = await self.measure_local_frame_origin()
        agreements = 0
        while agreements < _ORIGIN_STABLE_SAMPLES:
            if loop.time() >= deadline:
                return origin
            await asyncio.sleep(_ORIGIN_SAMPLE_S)
            latest = await self.measure_local_frame_origin()
            moved_m = origin_separation_m(origin, latest)
            agreements = 0 if moved_m > _ORIGIN_SHIFT_TOLERANCE_M else agreements + 1
            origin = latest
        return origin

    async def _true_airspeed_kt(self, ias_kt: float, altitude_ft: float | None = None) -> float:
        """Convert an indicated airspeed to the true one for where the aircraft is *going*.

        ``local_vx/vy/vz`` is a **true** velocity, while every speed in this
        project's vocabulary is indicated (see :class:`core.models.AircraftSetup`).
        The two diverge with density altitude: at FL100 the same needle reading is
        16 % faster through the air, so a 210 kt final placed there arrived at
        244 kt indicated. :mod:`core.atmosphere` owns the maths; this method only
        supplies it with an atmosphere.

        **The altitude that matters is the target one, and it is why this is a
        separate method.** A placement is normally a jump. An aircraft parked at
        LEMD and sent to a hold at FL100 is still on the ground at the moment the
        speed is resolved, so reading its altitude back would apply the 3 %
        correction for 2 000 ft where 16 % was needed — silently reinstating most
        of the defect the conversion exists to remove. The caller states the
        destination, and calls this **before** writing the position, so the
        conversion never races the derived world coordinates the sim republishes
        a frame or two after a teleport.

        The ambient temperature can only be read where the aircraft is now, so it
        is carried to the target altitude at constant ISA deviation rather than
        used as-is: air cools with height on a hot day too, and a surface reading
        applied unchanged at FL100 pushes true airspeed the wrong way. See
        :func:`core.atmosphere.temperature_from_deviation_c`.

        Two approximations survive, both deliberate and both tracked by issue #42:

        * The MSL altitude is used as the pressure altitude, which assumes
          standard pressure. A 30 hPa QNH deviation is worth about 1.5 % of true
          airspeed, against the 16 % this replaces.
        * The vector built from the result is a *ground* velocity, so it is exact
          in still air and off by the along-track wind component otherwise.
          Correcting that needs the wind datarefs.

        Args:
            ias_kt: Indicated airspeed in knots.
            altitude_ft: MSL altitude the speed is meant for, or ``None`` to use
                the aircraft's current one — correct only when nothing in the
                same operation is moving it vertically.

        Returns:
            True airspeed in knots.
        """
        altitude_m, temperature_c = await asyncio.gather(
            self._read("elevation"),
            self._read("temperature_ambient_deg_c"),
        )
        observed_ft = float(altitude_m) / _METRES_PER_FOOT
        deviation_c = isa_deviation_c(float(temperature_c), observed_ft)
        target_ft = observed_ft if altitude_ft is None else altitude_ft
        return tas_from_ias(
            ias_kt,
            target_ft,
            temperature_from_deviation_c(target_ft, deviation_c),
        )

    async def _write_velocity_vector(self, heading_deg: float, tas_kt: float) -> None:
        """Set the local velocity vector to ``tas_kt`` **true** along ``heading_deg``.

        Writing zeros instead is what drops a repositioned aircraft out of the
        sky below stall speed, so the caller's speed is always carried over.

        This is the mechanical half only. The vector X-Plane consumes is a true
        one; turning the instructor's *indicated* speed into it belongs to
        :meth:`_true_airspeed_kt`, which the caller runs before the aircraft
        moves.

        Args:
            heading_deg: True heading to fly, in degrees.
            tas_kt: True airspeed in knots. Negative values are clamped to zero
                rather than flying the aircraft backwards.
        """
        speed_ms = max(0.0, tas_kt) * _METRES_PER_SECOND_PER_KNOT
        heading = math.radians(heading_deg % 360.0)
        await self._write("local_vx", speed_ms * math.sin(heading))
        await self._write("local_vy", 0.0)
        await self._write("local_vz", -speed_ms * math.cos(heading))

    async def clear_crash_state(self) -> None:
        """Repair the aircraft if the sim decided the teleport was an impact.

        X-Plane reads a large position jump as a crash and renders the aircraft
        wrecked. ``sim/operation/fix_all_systems`` clears it. Cheap and
        idempotent, so it runs unconditionally after every reposition.
        """
        await self._activate("fix_all_systems")

    async def has_crashed(self) -> bool:
        """True if X-Plane currently considers the aircraft wrecked."""
        return bool(await self._read("has_crashed"))

    async def _await_arrival(self, target: GeoPosition, deadline: float) -> bool:
        """Poll until the aircraft is at ``target``, or until this attempt's slice ends.

        Returns as soon as it has arrived, so a short hop costs one round trip
        and only a scenery-reload-sized teleport pays any wait at all.

        The slice is :data:`_ARRIVAL_ATTEMPT_S` rather than the whole budget on
        purpose: waiting longer cannot make an aircraft that is in the wrong
        place arrive, and it is exactly the mistake issue #36 was — thirty
        seconds spent polling a target computed in a frame that no longer
        existed. Failing the slice is what tells the caller to go and look at
        the frame instead of waiting harder.

        Args:
            target: Where the aircraft was told to go.
            deadline: Event-loop time the whole reposition must finish by. The
                slice never runs past it.

        Returns:
            True if the aircraft reached ``target`` within
            :data:`POSITION_WRITE_TOLERANCE_M`.
        """
        loop = asyncio.get_running_loop()
        attempt_deadline = min(deadline, loop.time() + _ARRIVAL_ATTEMPT_S)
        while True:
            if await self._position_matches(target):
                return True
            if loop.time() >= attempt_deadline:
                return False
            await asyncio.sleep(_ARRIVAL_POLL_S)

    async def _position_matches(self, target: GeoPosition) -> bool:
        """True if the aircraft is within the write tolerance of ``target``."""
        latitude, longitude = await asyncio.gather(self._read("latitude"), self._read("longitude"))
        here = GeoPosition(latitude=float(latitude), longitude=float(longitude))
        distance_nm, _ = distance_and_bearing(here, target)
        return distance_nm * METRES_PER_NAUTICAL_MILE <= POSITION_WRITE_TOLERANCE_M

    async def apply_setup(self, setup: AircraftSetup) -> None:
        """Apply every field of ``setup`` that is set, leaving the rest untouched.

        The fields split in two, and the split is the whole point of this
        method's shape:

        * **Flight-model state** — attitude, vertical speed, altitude, airspeed.
          These are fought by a running flight model, so they are written inside
          :meth:`frozen_flight_model`. Without the freeze, a commanded heading
          came back 7° off in the mild case and 164° off in the bad one, and an
          ``apply_setup`` call was observed leaving the aircraft inverted on the
          runway (issue #37).
        * **Configuration** — flaps, speedbrake, trim, gear, autobrake, lights,
          radios and the autopilot. Switches and knobs, which the flight model
          reads rather than overwrites. They are written *outside* the freeze so
          that changing a light does not pause the simulation.

        The freeze is engaged only when there is flight-model state to write, so
        a configuration-only setup — and an empty one — costs nothing.

        Args:
            setup: The configuration to apply. ``None`` fields are skipped.

        Raises:
            CapabilityNotSupported: for fields belonging to a capability this
                adapter does not declare (mass and fuel).
            NotImplementedError: for fields whose X-Plane write path has not
                been established yet.
        """
        if setup.gross_weight_kg is not None or setup.fuel_kg is not None:
            raise CapabilityNotSupported("xplane", "can_set_fuel_payload")

        if setup.ils_freq_khz is not None:
            raise NotImplementedError(
                "ILS tuning is not wired up yet: X-Plane exposes the ILS receiver through "
                "the NAV radios, so this needs the approach's localiser frequency routed "
                "to nav1_freq_hz. Arrives with the Navigation manager."
            )

        await self._write_configuration(setup)
        await self._write_autopilot(setup)
        await self._write_flight_model_state(setup)

    async def _write_configuration(self, setup: AircraftSetup) -> None:
        """Write the switch-and-knob half of a setup. No freeze required."""
        writes: list[tuple[str, float | int | bool]] = []

        if setup.flaps_ratio is not None:
            writes.append(("flap_ratio", setup.flaps_ratio))
        if setup.speedbrake_ratio is not None:
            writes.append(("speedbrake_ratio", setup.speedbrake_ratio))
        if setup.elevator_trim_ratio is not None:
            writes.append(("elevator_trim", setup.elevator_trim_ratio))
        if setup.gear_down is not None:
            writes.append(("gear_handle_down", int(setup.gear_down)))
        if setup.autobrake_level is not None:
            writes.append(("autobrake_level", setup.autobrake_level))
        if setup.nav1_freq_khz is not None:
            writes.append(("nav1_freq", setup.nav1_freq_khz // 10))
        if setup.nav2_freq_khz is not None:
            writes.append(("nav2_freq", setup.nav2_freq_khz // 10))
        if setup.obs1_deg is not None:
            writes.append(("obs1", setup.obs1_deg))
        if setup.obs2_deg is not None:
            writes.append(("obs2", setup.obs2_deg))
        if setup.lights is not None:
            for field, key in (
                ("landing", "landing_lights"),
                ("taxi", "taxi_lights"),
                ("nav", "nav_lights"),
                ("beacon", "beacon_lights"),
                ("strobe", "strobe_lights"),
            ):
                value = getattr(setup.lights, field)
                if value is not None:
                    writes.append((key, int(value)))

        for key, value in writes:
            await self._write(key, value)

    async def _write_autopilot(self, setup: AircraftSetup) -> None:
        """Write the autopilot half of a setup. No freeze required.

        The autopilot is a panel, not a flight-model integration variable, so
        this runs outside :meth:`frozen_flight_model` exactly like the rest of
        the switches. Three X-Plane facts shape the method:

        * **The master switch and the flight director share one dataref.**
          ``autopilot_mode`` is a ladder — off / flight director / servos — so
          the two boolean fields are folded into a single value against the
          current one; see :meth:`_autopilot_mode_for`.
        * **The lateral modes are selected by command, not written.** X-Plane
          publishes ``nav_status``/``approach_status`` as read-only, and the
          modes are mutually exclusive, so "NAV off" can only mean "select
          another lateral mode". Wing-leveller is the neutral one.
        * **The speed selector is shared between knots and Mach.** Asking for a
          speed in knots therefore takes the dial out of Mach first — the same
          shape as forcing manual weather mode before writing a wind.

        Args:
            setup: The setup to apply. ``None`` fields are skipped, and a setup
                carrying no autopilot field at all costs nothing — not even a
                read.
        """
        if setup.autopilot_master is not None or setup.flight_director is not None:
            current = int(await self._read("autopilot_mode"))
            await self._write(
                "autopilot_mode",
                self._autopilot_mode_for(current, setup.flight_director, setup.autopilot_master),
            )

        # `is True` rather than truthiness throughout: `None` means "leave this
        # mode alone" and must not read as "switch it off".
        selected = [
            command for field, command in _LATERAL_MODE_COMMANDS if getattr(setup, field) is True
        ]
        if selected:
            for command in selected:
                await self._activate(command)
        elif any(getattr(setup, field) is False for field, _ in _LATERAL_MODE_COMMANDS):
            await self._activate("autopilot_wing_leveler")

        if setup.target_altitude_ft is not None:
            await self._write("autopilot_altitude_dial_ft", setup.target_altitude_ft)
        if setup.target_ias_kt is not None:
            await self._write("autopilot_airspeed_is_mach", 0)
            await self._write("autopilot_airspeed_dial", setup.target_ias_kt)
        if setup.target_heading_deg is not None:
            await self._write("autopilot_heading_dial_deg", setup.target_heading_deg % 360.0)
        if setup.target_vertical_speed_fpm is not None:
            await self._write("autopilot_vvi_dial_fpm", setup.target_vertical_speed_fpm)

    @staticmethod
    def _autopilot_mode_for(current: int, flight_director: bool | None, master: bool | None) -> int:
        """Fold ``flight_director`` and ``master`` into one ``autopilot_mode`` value.

        The order is deliberate. The flight director is applied first because it
        is the lower rung of the ladder, then the master switch, so a
        contradictory setup (``flight_director=False`` together with
        ``autopilot_master=True``) resolves in favour of the servos — an engaged
        autopilot implies a flight director, never the other way round.

        Args:
            current: The mode X-Plane currently reports.
            flight_director: Requested flight director state, or ``None``.
            master: Requested servo state, or ``None``.

        Returns:
            The value to write to ``autopilot_mode``.
        """
        mode = current
        if flight_director is not None:
            mode = (
                max(mode, AUTOPILOT_MODE_FLIGHT_DIRECTOR) if flight_director else AUTOPILOT_MODE_OFF
            )
        if master is not None:
            mode = AUTOPILOT_MODE_SERVOS if master else min(mode, AUTOPILOT_MODE_FLIGHT_DIRECTOR)
        return mode

    async def _write_flight_model_state(self, setup: AircraftSetup) -> None:
        """Write the half of a setup the flight model would otherwise overwrite.

        Everything here goes inside :meth:`frozen_flight_model`, for the reasons
        in that method's docstring. The freeze is skipped entirely when the setup
        carries none of these fields — engaging it costs a pause and a settle,
        and there is nothing to protect.
        """
        # Attitude plus vertical speed: the fields that map straight onto a
        # single `sim/flightmodel/position/*` dataref.
        direct: list[tuple[str, float]] = []
        if setup.heading_deg is not None:
            direct.append(("psi", setup.heading_deg % 360.0))
        if setup.pitch_deg is not None:
            direct.append(("theta", setup.pitch_deg))
        if setup.roll_deg is not None:
            direct.append(("phi", setup.roll_deg))
        if setup.vertical_speed_fpm is not None:
            direct.append(("vh_ind_fpm", setup.vertical_speed_fpm))

        if not direct and setup.altitude_ft is None and setup.ias_kt is None:
            return

        # Resolved here, ahead of the freeze, because a setup that carries both an
        # altitude and a speed moves the aircraft before the speed is written: the
        # atmosphere the conversion needs is the one it is going to, and the only
        # one the sim can be asked about is the one it is leaving.
        tas_kt = (
            None
            if setup.ias_kt is None
            else await self._true_airspeed_kt(setup.ias_kt, setup.altitude_ft)
        )

        async with self.frozen_flight_model():
            for key, value in direct:
                await self._write(key, value)

            # Altitude is not assignable either: `elevation` is read-only and
            # derived from the local frame, so it goes through the up axis while
            # the horizontal position is left exactly where it was. Doing it
            # frozen also means the position it reads back is a single instant
            # rather than a moving aircraft sampled across several requests.
            if setup.altitude_ft is not None:
                await self._write_altitude(setup.altitude_ft)

            # Airspeed is not a dataref you can assign: it is derived from the
            # velocity vector, so it is written last, along whichever heading the
            # setup asked for (or the aircraft's current one).
            if tas_kt is not None:
                heading = setup.heading_deg
                if heading is None:
                    heading = float(await self._read("psi"))
                await self._write_velocity_vector(heading, tas_kt)

    async def _write_altitude(self, altitude_ft: float) -> None:
        """Move the aircraft vertically, leaving its horizontal position alone."""
        origin = await self.measure_local_frame_origin()
        latitude, longitude = await asyncio.gather(self._read("latitude"), self._read("longitude"))
        local = world_to_local(
            origin,
            GeoPosition(
                latitude=float(latitude),
                longitude=float(longitude),
                altitude_ft=altitude_ft,
            ),
        )
        await self._write("local_y", local.y_m)

    # -- Streaming --------------------------------------------------------

    async def stream_state(self, interval_s: float) -> AsyncGenerator[AircraftState, None]:
        """Poll :meth:`get_aircraft_state` every ``interval_s`` seconds.

        Phase 0 polls over REST. The Web API's WebSocket (``/api/v2``) pushes
        dataref updates and will replace this once the subscription protocol is
        wired up.
        """
        while True:
            yield await self.get_aircraft_state()
            await asyncio.sleep(interval_s)


if TYPE_CHECKING:  # pragma: no cover - static conformance check, never executed
    _CONFORMS: SimAdapter = XPlaneSimAdapter()
