"""Sim-agnostic fuel-and-payload vocabulary and mass-and-balance arithmetic.

``core.fuel_payload`` is manager 9: the instructor-facing preset catalogue
(:data:`~core.fuel_payload.models.FUEL_PAYLOAD_PRESETS`), the request/result
models :class:`~core.fuel_payload.models.FuelPayloadRequest` and
:class:`~core.fuel_payload.models.MassAndBalanceResult`, the hand-authored
mass/CG limits fallback table
(:data:`~core.fuel_payload.limits.AIRCRAFT_MASS_LIMITS_TABLE`), and the pure
arithmetic that turns a :class:`~core.models.LoadoutState` and a resolved
:class:`~core.fuel_payload.limits.ResolvedMassLimits` into a
:class:`~core.fuel_payload.models.MassAndBalanceResult`
(:func:`~core.fuel_payload.mass_and_balance.compute_mass_and_balance`).

No HTTP, no dataref name, no simulator import — CG is computed here, never
read from a dataref (docs/designs/fuel-payload.md §6.3).

The design this package implements is ``docs/designs/fuel-payload.md``.
"""

from __future__ import annotations
