"""The simulator contract.

This module is the single seam between the sim-agnostic core and any concrete
simulator. It declares three things and nothing else:

* :class:`Capabilities` — what an adapter can do.
* :class:`SimAdapter` — the async protocol every adapter implements.
* :class:`CapabilityNotSupported` — the error raised when a caller ignores the
  capability flags.

Adding a feature to the station means adding a capability flag *and* a case to
``tests/adapters/test_contract.py``. Never branch on ``adapter.name``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from core.failures import ActiveFailure, FailureRef, FailureSupportManifest
from core.models import AircraftSetup, AircraftState, AirframeInfo, GeoPosition, LoadoutState
from core.weather.models import WeatherSetup, WeatherState

__all__ = [
    "Capabilities",
    "CapabilityNotSupported",
    "SimAdapter",
]


class Capabilities(BaseModel):
    """What a given adapter supports, as declared by the adapter itself.

    All flags default to ``False``: a new capability is unsupported everywhere
    until an adapter opts in. This is a pydantic model rather than a plain
    dataclass so that it is served verbatim by ``GET /api/capabilities`` and
    lands in the OpenAPI schema the UI client is generated from.

    Immutable — an adapter's capabilities never change at runtime.
    """

    model_config = ConfigDict(frozen=True)

    can_set_position: bool = False
    can_set_aircraft_state: bool = False
    can_set_weather: bool = False
    can_inject_failures: bool = False
    can_spawn_traffic: bool = False
    #: The adapter honours the autopilot block of
    #: :class:`~core.models.AircraftSetup` — the mode flags
    #: (``autopilot_master``, ``flight_director``, ``autopilot_nav``,
    #: ``autopilot_app``, ``autopilot_hdg``) and the four selectors
    #: (``target_altitude_ft``, ``target_ias_kt``, ``target_heading_deg``,
    #: ``target_vertical_speed_fpm``). There is no separate autopilot method:
    #: the autopilot is written through :meth:`SimAdapter.apply_setup` like
    #: every other switch, and this flag is what gates those fields.
    can_control_autopilot: bool = False
    can_set_fuel_payload: bool = False
    can_control_camera: bool = False
    can_pushback: bool = False


class CapabilityNotSupported(RuntimeError):
    """Raised when an operation is invoked on an adapter that does not support it.

    **The UI is expected to disable unsupported actions, not to catch this.**
    Capability flags are published by ``GET /api/capabilities`` precisely so
    that no user can ever reach a control the active simulator cannot honour.
    Seeing this exception means a caller ignored the flags — it is a bug in the
    caller, not a runtime condition to recover from.
    """

    def __init__(self, adapter_name: str, capability: str) -> None:
        self.adapter_name = adapter_name
        self.capability = capability
        super().__init__(
            f"Adapter {adapter_name!r} does not support {capability!r}. "
            f"Check Capabilities.{capability} before calling."
        )


class WeatherRejected(RuntimeError):
    """Raised when the simulator refuses to accept or hold a commanded weather write.

    Adapter-agnostic on purpose: the caller (``server/weather_routes.py``) maps
    this to one HTTP status (502 — the simulator, not the request, is at
    fault) regardless of which adapter raised it. A concrete adapter defines
    its own subclass carrying whatever diagnostic detail it has (see
    ``adapters.xplane.xplane_adapter.XPlaneWeatherRejected``) rather than the
    router importing an adapter-specific exception type directly, which would
    break the moment a second adapter needs the same 502.
    """


@runtime_checkable
class SimAdapter(Protocol):
    """The async interface every simulator adapter implements.

    Implementations must be import-safe: constructing an adapter performs no
    I/O, and nothing happens on the network until :meth:`connect` is awaited.
    """

    @property
    def name(self) -> str:
        """Short adapter identifier, e.g. ``"fake"`` or ``"xplane"``."""
        ...

    @property
    def capabilities(self) -> Capabilities:
        """The set of operations this adapter supports."""
        ...

    @property
    def is_connected(self) -> bool:
        """True once :meth:`connect` succeeded and before :meth:`disconnect`."""
        ...

    async def connect(self) -> None:
        """Open the link to the simulator. Idempotent."""
        ...

    async def disconnect(self) -> None:
        """Close the link and release resources. Idempotent, never raises."""
        ...

    async def get_aircraft_state(self) -> AircraftState:
        """Read one snapshot of the user aircraft."""
        ...

    async def get_airframe(self) -> AirframeInfo:
        """What is known about the loaded airframe.

        A capability-free read, like :meth:`get_aircraft_state`: there is no
        flag to check first, because a read degrades instead of failing. An
        adapter that cannot see the airframe returns the all-``None``
        :class:`~core.models.AirframeInfo` — "unknown" is an answer, never an
        exception.
        """
        ...

    async def set_position(
        self,
        position: GeoPosition,
        heading_deg: float,
        *,
        ias_kt: float | None = None,
        vertical_speed_fpm: float | None = None,
    ) -> None:
        """Teleport the aircraft to ``position`` facing ``heading_deg`` (true degrees).

        ``ias_kt`` decides what the aircraft is flying when it gets there, and the
        two cases are genuinely different intents:

        * ``None`` — carry the speed the aircraft has now onto the new heading.
          Right for *moving* an aeroplane that is already flying.
        * a value — arrive at that indicated airspeed. Right for a *placement*,
          where the speed is part of what was asked for.

        The default is ``None`` because preserving is the safe answer for a
        caller that has no opinion. A placement always has one: a caller that
        applies a setup and then teleports must pass the speed here as well,
        because the aircraft decelerates between the two calls and an adapter
        that re-reads the state would faithfully preserve the decayed value
        (issue #39 — measured at 83 kt against 120 commanded).

        ``vertical_speed_fpm`` is the same lesson on the vertical axis (issue
        #81): the velocity vector a teleport writes used to be unconditionally
        level, so a descent rate commanded by ``apply_setup`` was destroyed one
        call later. ``None`` arrives level — right for every placement that is
        not descending — and a value becomes the vertical component of the
        arrival velocity, so an aircraft placed on a final is already going
        down the slope when the flight model takes over.

        Requires :attr:`Capabilities.can_set_position`.
        """
        ...

    async def apply_setup(self, setup: AircraftSetup) -> None:
        """Apply every field of ``setup`` that is not ``None``, leaving the rest untouched.

        **This is the only write path into the aircraft's configuration**, and
        that is a decision rather than an accident (issue #41). The autopilot in
        particular does *not* get its own method: arming a mode and dialling the
        selector it flies to is one instructor intent, and two calls would leave
        an aircraft reachable in the half-applied state between them.

        Most fields require :attr:`Capabilities.can_set_aircraft_state`. Two
        groups are gated separately and an adapter that is handed one of them
        without declaring the flag must raise :class:`CapabilityNotSupported`
        rather than silently ignore it or half-apply the setup:

        * the autopilot block — :attr:`Capabilities.can_control_autopilot`;
        * ``gross_weight_kg`` / ``fuel_kg`` / ``loadout`` —
          :attr:`Capabilities.can_set_fuel_payload`. When ``loadout`` and the
          scalar fields are both set, ``loadout`` is authoritative and the
          scalars are applied only when it is absent.
        """
        ...

    async def get_weather(self) -> WeatherState:
        """Read the commanded weather.

        Requires Capabilities.can_set_weather — one flag gates the pair. Weather is
        the one surface where the read has no consumer without the write: the panel
        that displays it is the panel that edits it, and an adapter that cannot
        control weather has no tab to feed. Splitting a can_read_weather off is a
        one-line change the day the MSFS adapter proves it can read but not write;
        it is deliberately not made on speculation.
        """
        ...

    async def set_weather(self, setup: WeatherSetup) -> None:
        """Apply every field of ``setup`` that is not None, leaving the rest untouched.

        List fields replace wholesale: a provided list is the new complete set of
        layers, [] commands calm/clear, None leaves the layers alone.

        The adapter is responsible for making the write STICK: a simulator whose
        own weather engine would overwrite manual values (X-Plane 12 real weather)
        must be forced into manual mode first, and the mode verified, inside this
        call — once per call, not per field. An adapter that cannot secure the
        mode raises rather than writing values it knows will be destroyed.

        Requires Capabilities.can_set_weather.
        """
        ...

    async def get_failure_support(self) -> FailureSupportManifest:
        """Which catalogue entries this adapter can inject, one entry per FAILURE_IDS,
        in catalogue order. A capability-free read (same posture as get_airframe):
        an adapter without can_inject_failures returns every entry unsupported with
        that stated reason — "no" is an answer, never an exception.
        """
        ...

    async def inject_failure(self, failure: FailureRef) -> None:
        """Fail the referenced system immediately. Idempotent: injecting an
        already-failed system changes nothing. Requires can_inject_failures;
        an unsupported failure_id raises CapabilityNotSupported.
        """
        ...

    async def clear_failure(self, failure: FailureRef) -> None:
        """Repair the referenced system. Idempotent; clearing a working system is a
        no-op. Requires can_inject_failures.
        """
        ...

    async def clear_all_failures(self) -> None:
        """Repair every failure this adapter can see. Idempotent.
        Requires can_inject_failures.
        """
        ...

    async def get_active_failures(self) -> tuple[ActiveFailure, ...]:
        """Read back which supported failures are failed *right now*, from the
        simulator itself — never from a ledger of what was asked for (a
        teleport's fix_all_systems repairs everything behind the ledger's back).
        A capability-free read: an adapter that cannot see failures returns ().
        """
        ...

    async def get_loadout(self) -> LoadoutState:
        """Read the current fuel and payload.

        Requires Capabilities.can_set_fuel_payload — one flag gates the pair,
        exactly the reasoning of get_weather()/set_weather(): fuel burns
        continuously and AircraftSetupResult does not carry configuration, so the
        panel that displays the loadout is the panel that edits it, and an
        adapter that cannot control fuel/payload has no tab to feed.
        """
        ...

    def stream_state(self, interval_s: float) -> AsyncIterator[AircraftState]:
        """Yield aircraft states roughly every ``interval_s`` seconds until cancelled.

        Declared as a plain method returning an async iterator (not an ``async
        def``) so implementations can be async generators and callers can write
        ``async for state in adapter.stream_state(0.25)``.
        """
        ...
