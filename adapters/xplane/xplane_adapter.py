"""X-Plane 12.1+ adapter over the built-in Web API (REST, default port 8086).

Status: **SKELETON — REPOSITIONING IS UNVALIDATED.**

Reading state via ``GET /api/v2/datarefs/{id}/value`` is well-trodden. *Writing*
a position is the project's key technical risk and has not yet been confirmed
against a live simulator:

* X-Plane's authoritative aircraft position lives in
  ``sim/flightmodel/position/local_x|local_y|local_z`` (the OpenGL local frame).
  ``latitude``/``longitude``/``elevation`` are *derived* from those every frame,
  and the world→local conversion (``XPLMWorldToLocal``) is a plugin-only API.
  Writing the derived datarefs may therefore be silently overwritten on the
  next frame.
* If it does not stick, the fallback is the legacy UDP ``VEHX``/``VEH1`` packet,
  which repositions the aircraft without any plugin.
* Long teleports trigger a scenery reload — pause the sim around them.

Run ``python spikes/xplane_connection.py`` against a live X-Plane to settle
this. Until then :meth:`XPlaneSimAdapter.set_position` writes the derived
datarefs **and reads them back**, raising if the write did not take effect. It
never reports success it has not observed.

This module imports cleanly with no simulator present and opens no sockets
until :meth:`XPlaneSimAdapter.connect` is awaited.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

import httpx

from core.geodesy import METRES_PER_NAUTICAL_MILE, distance_and_bearing
from core.models import AircraftSetup, AircraftState, GeoPosition
from core.sim_adapter import Capabilities, CapabilityNotSupported, SimAdapter

__all__ = ["DATAREFS", "DEFAULT_BASE_URL", "XPlaneSimAdapter"]

DEFAULT_BASE_URL = "http://localhost:8086"

#: Every X-Plane dataref this adapter touches, keyed by the short internal name
#: used throughout the module. Nothing outside this mapping is hard-coded.
DATAREFS: dict[str, str] = {
    # --- Position and attitude (read + attempted write) ------------------
    "latitude": "sim/flightmodel/position/latitude",
    "longitude": "sim/flightmodel/position/longitude",
    "elevation": "sim/flightmodel/position/elevation",  # metres MSL
    "psi": "sim/flightmodel/position/psi",  # true heading, degrees
    "theta": "sim/flightmodel/position/theta",  # pitch, degrees
    "phi": "sim/flightmodel/position/phi",  # roll, degrees
    "indicated_airspeed": "sim/flightmodel/position/indicated_airspeed",  # kt
    "vh_ind_fpm": "sim/flightmodel/position/vh_ind_fpm",  # feet per minute
    "on_ground": "sim/flightmodel/failures/onground_any",
    # --- Authoritative OpenGL local frame (the VEHX fallback territory) ---
    "local_x": "sim/flightmodel/position/local_x",
    "local_y": "sim/flightmodel/position/local_y",
    "local_z": "sim/flightmodel/position/local_z",
    # --- Aircraft configuration ------------------------------------------
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
    # --- Radios (X-Plane stores NAV frequencies in units of 10 kHz) -------
    "nav1_freq": "sim/cockpit/radios/nav1_freq_hz",
    "nav2_freq": "sim/cockpit/radios/nav2_freq_hz",
    "obs1": "sim/cockpit/radios/nav1_obs_degm",
    "obs2": "sim/cockpit/radios/nav2_obs_degm",
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
#: Read-back tolerance after a teleport, in metres. Generous enough to survive
#: one physics frame of movement, tight enough to catch a write that did not
#: take effect at all.
POSITION_WRITE_TOLERANCE_M = 200.0


class XPlaneNotReachable(RuntimeError):
    """The X-Plane Web API did not answer. Is the sim running with the API enabled?"""


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
        """Fetch ``/api/v2/datarefs`` and resolve the ids of :data:`DATAREFS`.

        Raises:
            XPlaneNotReachable: if the Web API cannot be reached.
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

        self._client = client
        self._ids = index

    async def disconnect(self) -> None:
        """Close the HTTP client. Idempotent, never raises."""
        client, self._client = self._client, None
        self._ids = {}
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

    async def _write(self, key: str, value: float | int | bool) -> None:
        """Write one dataref value by its short :data:`DATAREFS` key."""
        client = self._require_client()
        response = await client.patch(
            f"/api/v2/datarefs/{self._ids[key]}/value",
            json={"data": value},
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

    # -- Writes -----------------------------------------------------------

    async def set_position(self, position: GeoPosition, heading_deg: float) -> None:
        """Teleport the aircraft. **Unvalidated — see the module docstring.**

        Writes ``latitude``/``longitude``/``elevation``/``psi`` and then reads
        the position back. If the aircraft did not move to within
        :data:`POSITION_WRITE_TOLERANCE_M`, raises ``NotImplementedError`` with
        the next thing to try, rather than reporting a success that did not
        happen.

        Args:
            position: Target position, ``altitude_ft`` interpreted as MSL.
            heading_deg: Target true heading in degrees.

        Raises:
            NotImplementedError: if writing the derived datarefs does not move
                the aircraft, meaning the UDP ``VEHX`` fallback is required.
        """
        await asyncio.gather(
            self._write("latitude", position.latitude),
            self._write("longitude", position.longitude),
            self._write("elevation", position.altitude_ft * _METRES_PER_FOOT),
            self._write("psi", heading_deg % 360.0),
        )
        # Give the sim a frame to settle, then verify. Never claim success blind.
        await asyncio.sleep(0.5)
        if not await self._position_matches(position):
            raise NotImplementedError(
                "Writing sim/flightmodel/position/latitude|longitude|elevation did not "
                "move the aircraft: X-Plane recomputed them from local_x/y/z on the next "
                "frame. Repositioning over the Web API is not available on this build. "
                "Next thing to try: the legacy UDP VEHX/VEH1 packet on port 49000, which "
                "positions the aircraft without a plugin. See spikes/xplane_connection.py."
            )

    async def _position_matches(self, target: GeoPosition) -> bool:
        """True if the aircraft is within the write tolerance of ``target``."""
        actual = await self.get_aircraft_state()
        here = GeoPosition(latitude=actual.latitude, longitude=actual.longitude)
        distance_nm, _ = distance_and_bearing(here, target)
        return distance_nm * METRES_PER_NAUTICAL_MILE <= POSITION_WRITE_TOLERANCE_M

    async def apply_setup(self, setup: AircraftSetup) -> None:
        """Apply every field of ``setup`` that is set, leaving the rest untouched.

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

        writes: list[tuple[str, float | int | bool]] = []

        if setup.altitude_ft is not None:
            writes.append(("elevation", setup.altitude_ft * _METRES_PER_FOOT))
        if setup.heading_deg is not None:
            writes.append(("psi", setup.heading_deg % 360.0))
        if setup.pitch_deg is not None:
            writes.append(("theta", setup.pitch_deg))
        if setup.roll_deg is not None:
            writes.append(("phi", setup.roll_deg))
        if setup.vertical_speed_fpm is not None:
            writes.append(("vh_ind_fpm", setup.vertical_speed_fpm))
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

        if setup.ias_kt is not None:
            raise NotImplementedError(
                "Setting indicated airspeed on X-Plane has no established write path: "
                "sim/flightmodel/position/indicated_airspeed is derived from the "
                "velocity vector (local_vx/vy/vz), which must be written in the OpenGL "
                "frame together with the aircraft attitude. Blocked on the same spike as "
                "repositioning (spikes/xplane_connection.py)."
            )
        if setup.ils_freq_khz is not None:
            raise NotImplementedError(
                "ILS tuning is not wired up yet: X-Plane exposes the ILS receiver through "
                "the NAV radios, so this needs the approach's localiser frequency routed "
                "to nav1_freq_hz. Arrives with the Navigation manager."
            )

        for key, value in writes:
            await self._write(key, value)

    # -- Streaming --------------------------------------------------------

    async def stream_state(self, interval_s: float) -> AsyncGenerator[AircraftState, None]:
        """Poll :meth:`get_aircraft_state` every ``interval_s`` seconds.

        Phase 0 polls over REST. The Web API's WebSocket (``/api/v2``) pushes
        dataref updates and will replace this once the spike has validated the
        subscription protocol.
        """
        while True:
            yield await self.get_aircraft_state()
            await asyncio.sleep(interval_s)


if TYPE_CHECKING:  # pragma: no cover - static conformance check, never executed
    _CONFORMS: SimAdapter = XPlaneSimAdapter()
