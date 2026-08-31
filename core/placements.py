"""The ``PlacementRequest`` discriminated union — sim-agnostic, no HTTP.

Moved verbatim out of ``server/position_routes.py`` (D4,
``docs/designs/scenario-generator.md`` §4.1, §9): the Position Manager's own
``docs/designs/position-manager.md`` §7.6 already named this as "the natural
first step" of its own regret — a request model importable only from a
``server/`` module cannot be reused by anything that validates a placement
without going over HTTP, and the Scenario Generator's YAML documents need to
validate against exactly this model, not a re-derivation of it.

``server/position_routes.py`` imports these names back and re-exports them
under its own ``__all__``: no wire-format change, no behavioural change.
Resolution logic (``_resolve_placement`` and everything around it) stays in
``server/`` — only the request models move.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.geodesy import ApproachCategory, RunwayPlacement
from core.models import GeoPosition
from core.navdata.models import ProcedureKind

__all__ = [
    "CoordinatePlacementRequest",
    "HoldPlacementRequest",
    "ParkingPlacementRequest",
    "PlacementRequest",
    "ProcedureLegPlacementRequest",
    "RunwayPlacementRequest",
    "RunwayThresholdPlacementRequest",
    "WaypointPlacementRequest",
]


class RunwayPlacementRequest(BaseModel):
    """A final or a circuit leg, relative to one runway end.

    **One request for both**, because ``core.geodesy.resolve_runway_placement``
    is one function for both. Splitting finals from circuit legs here would
    invent a taxonomy the geometry does not have.
    """

    type: Literal["runway"]
    airport_icao: str = Field(min_length=2, max_length=7)
    runway_ident: str = Field(min_length=1)
    placement: RunwayPlacement
    glideslope_deg: float | None = Field(default=None, gt=0.0, le=10.0)
    pattern_altitude_ft: float | None = None
    pattern_width_nm: float | None = Field(default=None, gt=0.0)
    leg_distance_nm: float | None = Field(default=None, gt=0.0)
    ias_kt: float | None = Field(default=None, ge=0.0)
    category: ApproachCategory | None = None


class RunwayThresholdPlacementRequest(BaseModel):
    """On the runway centreline at the threshold, facing the runway heading,
    at 0 kt — lined up for a takeoff brief. Distinct from RunwayPlacementRequest,
    which is exclusively airborne final/pattern geometry; this is the one ground
    position anchored to a runway rather than to a parking stand. Resolves
    through core.geodesy.coordinate_placement(runway.threshold,
    runway.true_bearing_deg, ias_kt=GROUND_IAS_KT) — the construction
    GROUND_IAS_KT's own docstring already names ("a runway threshold for a
    takeoff brief") but never wired to a request.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["runway_threshold"]
    airport_icao: str = Field(min_length=2, max_length=7)
    runway_ident: str = Field(min_length=1)


class ParkingPlacementRequest(BaseModel):
    """A gate, stand, tie-down or hangar position.

    Gates and stands are one request because ``apt.dat`` publishes one record
    type with a ``kind`` field — see ``ParkingStand``.
    """

    type: Literal["parking"]
    airport_icao: str = Field(min_length=2, max_length=7)
    stand_name: str = Field(min_length=1)


class CoordinatePlacementRequest(BaseModel):
    """An arbitrary latitude/longitude/altitude."""

    type: Literal["coordinate"]
    position: GeoPosition
    heading_deg: float | None = None
    #: Resolves to stationary. A bare coordinate is as likely a parking spot as
    #: a cruise level, so a caller putting the aircraft **airborne** must say so
    #: or it arrives below stall speed — and the preview's notes say so too.
    ias_kt: float | None = Field(default=None, ge=0.0)


class WaypointPlacementRequest(BaseModel):
    """Over a named fix, at a chosen altitude."""

    type: Literal["waypoint"]
    ident: str = Field(min_length=1)
    region_code: str | None = None
    terminal_airport: str | None = None
    altitude_ft: float
    heading_deg: float | None = None
    ias_kt: float | None = Field(default=None, ge=0.0)
    category: ApproachCategory | None = None


class ProcedureLegPlacementRequest(BaseModel):
    """On one leg of a published SID, STAR or approach."""

    type: Literal["procedure_leg"]
    airport_icao: str = Field(min_length=2, max_length=7)
    kind: ProcedureKind
    ident: str = Field(min_length=1)
    transition: str | None = None
    sequence: int = Field(description="The leg's own sequence number: 10, 20, 30 …")
    #: ``None`` takes the leg's published altitude constraint.
    altitude_ft: float | None = None
    #: ``None`` takes the leg's published speed constraint, then the category.
    ias_kt: float | None = Field(default=None, ge=0.0)
    category: ApproachCategory | None = None


class HoldPlacementRequest(BaseModel):
    """In a published holding pattern, over its fix, established inbound."""

    type: Literal["hold"]
    fix_ident: str = Field(min_length=1)
    region_code: str | None = None
    airport_icao: str | None = None
    #: ``None`` takes the hold's published minimum altitude.
    altitude_ft: float | None = None
    ias_kt: float | None = Field(default=None, ge=0.0)
    category: ApproachCategory | None = None


PlacementRequest = Annotated[
    RunwayPlacementRequest
    | RunwayThresholdPlacementRequest
    | ParkingPlacementRequest
    | CoordinatePlacementRequest
    | WaypointPlacementRequest
    | ProcedureLegPlacementRequest
    | HoldPlacementRequest,
    Field(discriminator="type"),
]
