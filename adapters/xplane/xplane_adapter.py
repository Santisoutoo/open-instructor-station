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

The validated procedure is five steps, and skipping any of them breaks
something:

1. Freeze the flight model (``override_planepath[0] = 1``).
2. Write ``local_x``/``local_y``/``local_z``.
3. Write the **velocity vector** (``local_vx/vy/vz``) and heading. Writing zeros
   drops the aircraft out of the sky at stall speed; this adapter carries the
   aircraft's current speed onto the new heading, converted from indicated to
   true airspeed for the density altitude it is being placed at (the local
   frame's velocity is a true one — see :meth:`XPlaneSimAdapter._write_velocity_vector`).
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

Aircraft *configuration* — flaps, gear, lights, radios — is not part of the
flight model's integration and is deliberately written outside the freeze, so a
setup that only changes a switch costs no pause.

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

from core.atmosphere import tas_from_ias
from core.geodesy import METRES_PER_NAUTICAL_MILE, distance_and_bearing
from core.local_frame import (
    LocalCoordinates,
    LocalFrameOrigin,
    origin_from_observation,
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
    "gear_handle_down": "sim/cockpit2/controls/gear_handle_down",
    "autobrake_level": "sim/cockpit2/switches/auto_brake_level",
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
_ARRIVAL_TIMEOUT_S = 30.0

#: Read-back tolerance after a teleport, in metres. The check runs while the
#: flight model is still frozen, so the aircraft is not moving and this only has
#: to absorb float noise — not a second of flight.
POSITION_WRITE_TOLERANCE_M = 50.0


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

        Yields:
            ``None``. The block runs with the flight model frozen.
        """
        await self._write("override_planepath", 1, index=0)
        try:
            await asyncio.sleep(_OVERRIDE_SETTLE_S)
            yield
        finally:
            await self._write("override_planepath", 0, index=0)
            await asyncio.sleep(_RELEASE_SETTLE_S)

    async def set_position(self, position: GeoPosition, heading_deg: float) -> None:
        """Teleport the aircraft, preserving its current speed on the new heading.

        Runs the five-step procedure documented at the top of this module. The
        arrival is verified *while the flight model is still frozen*, so the
        check measures placement rather than a second of subsequent flight.

        Args:
            position: Target position, ``altitude_ft`` interpreted as MSL.
            heading_deg: Target true heading in degrees.

        Raises:
            XPlaneRepositionFailed: if the aircraft did not arrive within
                :data:`POSITION_WRITE_TOLERANCE_M`. Never reports an unobserved
                success.
        """
        origin = await self.measure_local_frame_origin()
        target = world_to_local(origin, position)
        speed_kt = (await self.get_aircraft_state()).ias_kt

        async with self.frozen_flight_model():
            await self._write("local_x", target.x_m)
            await self._write("local_y", target.y_m)
            await self._write("local_z", target.z_m)
            await self._write_velocity_vector(heading_deg, speed_kt)
            await self._write("psi", heading_deg % 360.0)
            arrived = await self._await_arrival(position)

        await self.clear_crash_state()

        if not arrived:
            raise XPlaneRepositionFailed(
                f"The aircraft did not arrive within {POSITION_WRITE_TOLERANCE_M:.0f} m of "
                f"{position.latitude:.6f}, {position.longitude:.6f} after writing the local "
                "frame coordinates. The frame origin measurement or the local axis convention "
                "may be wrong on this build. Run spikes/xplane_connection.py, which prints the "
                "calibration residual, before trusting any further placement."
            )

    async def _write_velocity_vector(self, heading_deg: float, ias_kt: float) -> None:
        """Set the local velocity vector to ``ias_kt`` *indicated* along ``heading_deg``.

        Writing zeros instead is what drops a repositioned aircraft out of the
        sky below stall speed, so the caller's speed is always carried over.

        ``local_vx/vy/vz`` is a **true** velocity in metres per second, while
        every speed in this project's vocabulary is indicated (see
        :class:`core.models.AircraftSetup`). The two diverge with density
        altitude: at FL100 the same needle reading is 16 % faster through the
        air, so a 210 kt final placed there was arriving at 244 kt indicated.
        The requested speed is therefore converted to true airspeed first, from
        the aircraft's own altitude and the ambient temperature X-Plane
        reports — see :mod:`core.atmosphere`, which owns the maths.

        Two approximations survive the fix, both deliberate:

        * The MSL elevation derived from the local frame is used as the pressure
          altitude, which assumes standard pressure. A 30 hPa QNH deviation is
          worth about 1.5 % of true airspeed, against the 16 % this replaces.
        * The vector written is a *ground* velocity, so it is exact in still air
          and off by the along-track wind component otherwise. Correcting that
          needs the wind datarefs and is a separate piece of work.

        Args:
            heading_deg: True heading to fly, in degrees.
            ias_kt: Indicated airspeed in knots. Negative values are clamped to
                zero rather than flying the aircraft backwards.
        """
        altitude_m, temperature_c = await asyncio.gather(
            self._read("elevation"),
            self._read("temperature_ambient_deg_c"),
        )
        tas_kt = tas_from_ias(
            max(0.0, ias_kt),
            float(altitude_m) / _METRES_PER_FOOT,
            float(temperature_c),
        )
        speed_ms = tas_kt * _METRES_PER_SECOND_PER_KNOT
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

    async def _await_arrival(self, target: GeoPosition) -> bool:
        """Poll until the aircraft is at ``target``, or until the timeout.

        Returns as soon as it has arrived, so a short hop costs one round trip
        and only a scenery-reload-sized teleport pays the wait.
        """
        deadline = asyncio.get_running_loop().time() + _ARRIVAL_TIMEOUT_S
        while True:
            if await self._position_matches(target):
                return True
            if asyncio.get_running_loop().time() >= deadline:
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
        * **Configuration** — flaps, speedbrake, gear, autobrake, lights, radios.
          Switches and knobs, which the flight model reads rather than
          overwrites. They are written *outside* the freeze so that changing a
          light does not pause the simulation.

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
        await self._write_flight_model_state(setup)

    async def _write_configuration(self, setup: AircraftSetup) -> None:
        """Write the switch-and-knob half of a setup. No freeze required."""
        writes: list[tuple[str, float | int | bool]] = []

        if setup.flaps_ratio is not None:
            writes.append(("flap_ratio", setup.flaps_ratio))
        if setup.speedbrake_ratio is not None:
            writes.append(("speedbrake_ratio", setup.speedbrake_ratio))
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
            if setup.ias_kt is not None:
                heading = setup.heading_deg
                if heading is None:
                    heading = float(await self._read("psi"))
                await self._write_velocity_vector(heading, setup.ias_kt)

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
