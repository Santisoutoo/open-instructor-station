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

from core.models import AircraftSetup, AircraftState, GeoPosition

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

    async def set_position(self, position: GeoPosition, heading_deg: float) -> None:
        """Teleport the aircraft to ``position`` facing ``heading_deg`` (true degrees).

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
        * ``gross_weight_kg`` / ``fuel_kg`` — :attr:`Capabilities.can_set_fuel_payload`.
        """
        ...

    def stream_state(self, interval_s: float) -> AsyncIterator[AircraftState]:
        """Yield aircraft states roughly every ``interval_s`` seconds until cancelled.

        Declared as a plain method returning an async iterator (not an ``async
        def``) so implementations can be async generators and callers can write
        ``async for state in adapter.stream_state(0.25)``.
        """
        ...
