"""Shared fixtures for the Fuel & Payload core test suite.

The §7.1 C172 entry is the "computable by hand" worked table this whole
package's tests are pinned against — see ``docs/designs/fuel-payload.md`` §7.1.
"""

from __future__ import annotations

import pytest

from core.fuel_payload.limits import AIRCRAFT_MASS_LIMITS_TABLE, ResolvedMassLimits
from core.models import LoadoutState


@pytest.fixture
def c172_limits() -> ResolvedMassLimits:
    """The §7.1 table entry, wrapped as an adapter-sourced ``ResolvedMassLimits``.

    ``source="table"`` here (not "adapter") because that is what
    ``resolve_mass_limits`` would actually report for this entry — tests that
    care about the distinction construct their own ``AirframeInfo`` instead.
    """
    return ResolvedMassLimits(limits=AIRCRAFT_MASS_LIMITS_TABLE["C172"].limits, source="table")


@pytest.fixture
def empty_current() -> LoadoutState:
    """A current loadout reporting nothing — the honest starting point for a preset."""
    return LoadoutState(tanks=[], stations=[])
