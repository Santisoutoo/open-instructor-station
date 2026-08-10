"""``FakeSimAdapter`` — the reference implementation of the simulator contract.

This adapter is the yardstick: it declares **every** capability and implements
the whole protocol in memory, so the contract suite in
``tests/adapters/test_contract.py`` can define what "correct" means without a
simulator. All CI runs against it.

It performs no I/O whatsoever and is safe to import and construct anywhere.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from core.geodesy import point_at_distance_and_bearing
from core.models import AircraftSetup, AircraftState, GeoPosition, LightsSetup
from core.sim_adapter import Capabilities, SimAdapter

__all__ = ["FakeSimAdapter"]

#: Somewhere over Madrid Barajas (LEMD), 3000 ft, heading north at 250 kt.
DEFAULT_STATE = AircraftState(
    latitude=40.4936,
    longitude=-3.5668,
    altitude_ft=3000.0,
    heading_deg=0.0,
    ias_kt=250.0,
    vertical_speed_fpm=0.0,
    pitch_deg=0.0,
    roll_deg=0.0,
    on_ground=False,
)

_ALL_CAPABILITIES = Capabilities(
    can_set_position=True,
    can_set_aircraft_state=True,
    can_set_weather=True,
    can_inject_failures=True,
    can_spawn_traffic=True,
    can_control_autopilot=True,
    can_set_fuel_payload=True,
    can_control_camera=True,
    can_pushback=True,
)

_SECONDS_PER_HOUR = 3600.0
_SECONDS_PER_MINUTE = 60.0


class FakeSimAdapter:
    """A simulator that lives entirely in a Python object.

    The aircraft flies: every :meth:`stream_state` tick advances it along its
    current heading at its current airspeed and applies its vertical speed, so
    a client watching the WebSocket can tell a live stream from a frozen one.
    """

    def __init__(self, initial_state: AircraftState | None = None) -> None:
        self._state = (initial_state or DEFAULT_STATE).model_copy(deep=True)
        self._connected = False
        # Non-flight settings the fake accepts and remembers so that
        # ``apply_setup`` is observably faithful.
        self._setup = AircraftSetup()

    # -- Identity ---------------------------------------------------------

    @property
    def name(self) -> str:
        """Adapter identifier."""
        return "fake"

    @property
    def capabilities(self) -> Capabilities:
        """Everything is supported — this is the reference implementation."""
        return _ALL_CAPABILITIES

    @property
    def is_connected(self) -> bool:
        """True between :meth:`connect` and :meth:`disconnect`."""
        return self._connected

    @property
    def applied_setup(self) -> AircraftSetup:
        """The accumulated result of every :meth:`apply_setup` call so far.

        Not part of the ``SimAdapter`` protocol — a test affordance that lets
        the contract suite check non-flight fields (lights, radios, gear) that
        do not surface in :class:`~core.models.AircraftState`.
        """
        return self._setup.model_copy(deep=True)

    # -- Lifecycle --------------------------------------------------------

    async def connect(self) -> None:
        """Mark the adapter connected. Idempotent, no I/O."""
        self._connected = True

    async def disconnect(self) -> None:
        """Mark the adapter disconnected. Idempotent, never raises."""
        self._connected = False

    # -- Reads ------------------------------------------------------------

    async def get_aircraft_state(self) -> AircraftState:
        """Return a copy of the current in-memory aircraft state."""
        return self._state.model_copy(deep=True)

    # -- Writes -----------------------------------------------------------

    async def set_position(
        self, position: GeoPosition, heading_deg: float, *, ias_kt: float | None = None
    ) -> None:
        """Teleport the in-memory aircraft.

        Args:
            position: Target position; ``altitude_ft`` is applied as MSL.
            heading_deg: Target true heading in degrees.
            ias_kt: Indicated airspeed to arrive at. ``None`` keeps the current
                one, which for the Fake means literally leaving the field alone.
        """
        updates: dict[str, Any] = {
            "latitude": position.latitude,
            "longitude": position.longitude,
            "altitude_ft": position.altitude_ft,
            "heading_deg": heading_deg % 360.0,
        }
        if ias_kt is not None:
            updates["ias_kt"] = ias_kt
        self._state = self._state.model_copy(update=updates)

    async def apply_setup(self, setup: AircraftSetup) -> None:
        """Apply every field of ``setup`` that is set, leaving the rest untouched."""
        provided = setup.model_dump(exclude_none=True)

        state_updates: dict[str, Any] = {
            field: provided[field]
            for field in (
                "altitude_ft",
                "ias_kt",
                "vertical_speed_fpm",
                "heading_deg",
                "pitch_deg",
                "roll_deg",
            )
            if field in provided
        }
        if "heading_deg" in state_updates:
            state_updates["heading_deg"] = float(state_updates["heading_deg"]) % 360.0
        if state_updates:
            self._state = self._state.model_copy(update=state_updates)

        self._setup = self._merge_setup(self._setup, setup)

    @staticmethod
    def _merge_setup(current: AircraftSetup, incoming: AircraftSetup) -> AircraftSetup:
        """Overlay the set fields of ``incoming`` onto ``current``.

        Driven entirely by ``model_dump(exclude_none=True)``, so a scalar field
        added to :class:`~core.models.AircraftSetup` — the whole autopilot block
        of issue #41, for instance — is carried here with no change to this
        adapter. ``lights`` is the one exception, and only because a nested model
        has to be merged rather than replaced.
        """
        updates = incoming.model_dump(exclude_none=True)
        if "lights" in updates and current.lights is not None:
            lights = incoming.lights
            merged_lights = current.lights.model_dump()
            if lights is not None:
                merged_lights.update(lights.model_dump(exclude_none=True))
            updates["lights"] = LightsSetup(**merged_lights)
        elif "lights" in updates:
            updates["lights"] = incoming.lights
        return current.model_copy(update=updates)

    # -- Streaming --------------------------------------------------------

    async def stream_state(self, interval_s: float) -> AsyncGenerator[AircraftState, None]:
        """Yield the aircraft state every ``interval_s`` seconds, flying it forward.

        Each tick moves the aircraft ``ias_kt * interval_s / 3600`` nautical
        miles along its current heading and applies its vertical speed, so the
        stream is observably alive.
        """
        while True:
            self._advance(interval_s)
            yield self._state.model_copy(deep=True)
            await asyncio.sleep(interval_s)

    def _advance(self, elapsed_s: float) -> None:
        """Integrate the aircraft one step forward (great-circle, no wind)."""
        distance_nm = self._state.ias_kt * elapsed_s / _SECONDS_PER_HOUR
        climb_ft = self._state.vertical_speed_fpm * elapsed_s / _SECONDS_PER_MINUTE
        if distance_nm == 0.0 and climb_ft == 0.0:
            return
        origin = GeoPosition(
            latitude=self._state.latitude,
            longitude=self._state.longitude,
            altitude_ft=self._state.altitude_ft,
        )
        moved = point_at_distance_and_bearing(origin, distance_nm, self._state.heading_deg)
        self._state = self._state.model_copy(
            update={
                "latitude": moved.latitude,
                "longitude": moved.longitude,
                "altitude_ft": self._state.altitude_ft + climb_ft,
            }
        )


if TYPE_CHECKING:  # pragma: no cover - static conformance check, never executed
    _CONFORMS: SimAdapter = FakeSimAdapter()
