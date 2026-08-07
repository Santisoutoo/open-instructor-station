"""The seam between the procedure parser and the index.

Runway data is a **merge of two sources** — ``apt.dat`` publishes the pavement
and the CIFP publishes the threshold geometry the procedures are actually built
on — so the indexed provider needs the CIFP without owning it, and the CIFP
parser needs the index's fix resolution without owning that.

This module is the interface between them, and it exists so the two can be
built in parallel: the provider consumes :class:`CifpSource`, the parser
implements it, and wiring them together at the end is one line.

:class:`NullCifpSource` is what the provider uses until the parser lands. It
reports every airport as having no procedures, which is a *correct* answer for
an airport with no CIFP file and a *degraded* one otherwise — never a crash.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from core.models import GeoPosition
from core.navdata.models import FixRef, Procedure, Waypoint

__all__ = [
    "CifpAirport",
    "CifpRunway",
    "CifpSource",
    "FixResolver",
    "NullCifpSource",
]

#: How a CIFP parser turns a leg's 4-part ARINC key into a coordinate.
#: Injected rather than imported, so the parser never depends on SQLite and can
#: be tested against a handful of hand-built waypoints.
FixResolver = Callable[[FixRef], Waypoint | None]


class CifpRunway(BaseModel):
    """The runway facts only the CIFP publishes.

    These override ``apt.dat`` where they overlap, because the CIFP threshold is
    the datum the procedures themselves are built on: using ``apt.dat`` for the
    threshold and the CIFP for the approach legs would put a small, permanent,
    invisible offset between a placement and the procedure it claims to be on.
    """

    model_config = ConfigDict(frozen=True)

    ident: str = Field(min_length=1, max_length=3, description='"18L", never "RW18L".')
    threshold: GeoPosition | None = Field(
        default=None, description="The displaced landing threshold, from the RWY: record."
    )
    elevation_ft: float | None = Field(default=None, description="Threshold elevation, feet MSL.")
    displaced_threshold_m: float | None = Field(
        default=None,
        ge=0.0,
        description="Displacement in metres. The source publishes it in feet; converted here.",
    )
    threshold_crossing_height_ft: float | None = Field(default=None, ge=0.0)
    localizer_ident: str | None = Field(default=None, description='e.g. "IML".')
    ils_category: str | None = Field(
        default=None,
        description=(
            'Raw category as published, e.g. "1". Left unmapped here so the caller decides how '
            "to render an unrecognised code — an odd value never fails a parse."
        ),
    )


class CifpAirport(BaseModel):
    """Everything one ``CIFP/<ICAO>.dat`` file has to say."""

    model_config = ConfigDict(frozen=True)

    icao: str = Field(min_length=2, max_length=7)
    runways: tuple[CifpRunway, ...] = ()
    procedures: tuple[Procedure, ...] = ()
    skipped_record_count: int = Field(
        default=0,
        ge=0,
        description=(
            "Malformed records skipped while parsing. Real navdata always contains a few, and a "
            "single bad row must never fail the file."
        ),
    )

    def runway(self, ident: str) -> CifpRunway | None:
        """The record for one runway end, or ``None``."""
        wanted = ident.strip().upper().removeprefix("RW")
        return next((r for r in self.runways if r.ident == wanted), None)


@runtime_checkable
class CifpSource(Protocol):
    """Lazy, per-airport access to parsed procedures.

    There are ~15 000 CIFP files and an instructor session touches perhaps five,
    so this is loaded on demand and never indexed up front: parsing them all at
    start-up would burn minutes to produce data that is 99.97% unused.
    """

    def load(self, icao: str) -> CifpAirport | None:
        """Parse one airport's procedures, or return ``None`` when it has no CIFP file.

        A missing file is a **normal outcome**, not an error: every airport has
        runways, only about half have published procedures.
        """
        ...

    def invalidate(self) -> None:
        """Drop any cached parses. Called when the navdata cache key changes."""
        ...


class NullCifpSource:
    """A :class:`CifpSource` that never finds anything.

    Used where procedures are genuinely out of scope — an in-memory provider
    built from hand-written models, or the indexed provider before the parser is
    wired in. Every airport reads as having no procedures, which the whole stack
    already handles as an ordinary case.
    """

    def load(self, icao: str) -> CifpAirport | None:
        return None

    def invalidate(self) -> None:
        return None
