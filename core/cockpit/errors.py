"""Exceptions for the cockpit control catalog.

Per ``docs/designs/cockpit-control-catalog.md`` §3.5. Adapter-agnostic on
purpose — exactly ``WeatherRejected``'s reasoning (``core.sim_adapter``): the
router maps types, never an adapter's own subclass.
"""

from __future__ import annotations

__all__ = [
    "CockpitCatalogInactive",
    "CockpitControlUnknown",
    "CockpitPreconditionUnmet",
    "CockpitWriteRejected",
]


class CockpitCatalogInactive(RuntimeError):
    """No cockpit catalog is active for the loaded aircraft. Maps to 409."""


class CockpitControlUnknown(LookupError):
    """``control_id`` is absent from the active catalog's ``controls``. Maps to 404.

    When the id names a parked entry instead, ``parked_reason`` carries that
    entry's ``reason`` and is folded into the message so a caller can surface
    it without a second lookup.
    """

    def __init__(self, control_id: str, parked_reason: str | None = None) -> None:
        self.control_id = control_id
        self.parked_reason = parked_reason
        if parked_reason is not None:
            message = f"{control_id!r} is parked on this aircraft: {parked_reason}"
        else:
            message = f"{control_id!r} is not a control on the active cockpit catalog."
        super().__init__(message)


class CockpitPreconditionUnmet(RuntimeError):
    """One or more precondition groups are unmet. Maps to 409.

    ``hints`` carries every unmet group's ``hint``, joined with ``"; "`` into
    the exception message (§2.1).
    """

    def __init__(self, control_id: str, hints: tuple[str, ...]) -> None:
        self.control_id = control_id
        self.hints = hints
        super().__init__("; ".join(hints))


class CockpitWriteRejected(RuntimeError):
    """The simulator's read-back disagreed with a commanded write. Maps to 502."""
