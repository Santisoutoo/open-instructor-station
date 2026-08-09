"""``/api/position/*`` — stage a placement, then commit it.

**Two endpoints, and the split is the whole design.** ``preview`` resolves a
placement request against navdata and geometry and touches no simulator;
``apply`` does it again and then writes. The UI stages on the first and commits
on the second, so an instructor always sees the altitude and the speed before a
student's aeroplane moves. The incumbent product teleports on the first click of
a tile, mid-lesson, with no way back — that is the failure this shape exists to
prevent.

``preview`` is a ``POST`` because its body is a discriminated union, not because
it mutates anything. It is side-effect-free and the tests assert as much.

**Order of operations on apply is not negotiable.** The setup is written
*before* the teleport:

1. a placement carries a required ``ias_kt`` because a parked aircraft put on a
   10 NM final at 0 kt falls out of the sky — measured, not theorised (#39);
2. attitude written into a running flight model does not stick, and the adapter
   freezes it around the move (#37).

Both are described in ``CLAUDE.md``. Reversing these two calls reintroduces the
first bug exactly.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.geodesy import (
    APPROACH_CATEGORY_CIRCLING_IAS_KT,
    APPROACH_CATEGORY_VAT_KT,
    DEFAULT_APPROACH_CATEGORY,
    DEFAULT_GLIDESLOPE_DEG,
    DEFAULT_PATTERN_LEG_DISTANCE_NM,
    DEFAULT_PATTERN_WIDTH_NM,
    FINAL_DISTANCES_NM,
    GROUND_IAS_KT,
    METRES_PER_NAUTICAL_MILE,
    ApproachCategory,
    Placement,
    RunwayPlacement,
    coordinate_placement,
    distance_and_bearing,
    hold_placement,
    point_at_distance_and_bearing,
    resolve_runway_placement,
    true_from_magnetic,
    waypoint_placement,
)
from core.models import AircraftSetup, AircraftState, GeoPosition, Runway
from core.navdata.models import Airport, Hold, ProcedureKind, ProcedureLeg
from core.navdata.provider import NavdataProvider
from core.sim_adapter import CapabilityNotSupported, SimAdapter
from server.deps import get_adapter, get_navdata

__all__ = [
    "CAPABILITY_UNAVAILABLE_STATUS",
    "UNPOSITIONABLE_STATUS",
    "ApplyPlacementRequest",
    "PlacementPreview",
    "PlacementRequest",
    "PlacementResult",
    "PlacementSchematic",
    "SchematicPoint",
    "router",
]

#: Mirrors ``server.app.CAPABILITY_UNAVAILABLE_STATUS``. Duplicated rather than
#: imported to keep the import edge one-way: ``app`` includes these routers.
CAPABILITY_UNAVAILABLE_STATUS = 501

#: A leg that carries no defensible coordinate. 422 rather than 404: the leg
#: exists and was found, it simply cannot be a position. The UI has already
#: disabled that row, so reaching this means a caller ignored the data.
UNPOSITIONABLE_STATUS = 422

router = APIRouter(prefix="/api/position", tags=["position"])


# ---------------------------------------------------------------------------
# The request union
# ---------------------------------------------------------------------------


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
    """In a published holding pattern, over its fix, established inbound.

    ``core.geodesy`` can also place at the other three points of the racetrack
    (``HOLD_PLACEMENTS``) and before the fix on an entry course
    (``hold_entry_placement``). Neither is exposed here yet: the fix is the one
    point of a hold an instructor names, and adding the rest is a request-model
    change with a UI control behind it rather than something to smuggle in.
    """

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
    | ParkingPlacementRequest
    | CoordinatePlacementRequest
    | WaypointPlacementRequest
    | ProcedureLegPlacementRequest
    | HoldPlacementRequest,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# The response models
# ---------------------------------------------------------------------------


class SchematicPoint(BaseModel):
    """One point of the preview diagram, already projected for the UI to draw.

    ``x_nm``/``y_nm`` are a runway-local tangent plane. The flat-earth error
    that makes such a frame unusable for *positioning* does not apply here:
    these coordinates only ever draw a diagram, and the authoritative answer is
    the ``position`` beside them. The UI does no geodesy.
    """

    label: str
    position: GeoPosition
    x_nm: float = Field(description="Along the centreline; positive away from the threshold.")
    y_nm: float = Field(description="Across it; positive right, seen from the approach.")
    role: Literal["threshold", "runway_end", "placement", "glidepath", "leg", "fix"]


class PlacementSchematic(BaseModel):
    """Everything the staging bar's SVG needs, and nothing it does not."""

    runway_ident: str | None = None
    runway_true_bearing_deg: float | None = None
    runway_length_m: float | None = None
    glidepath_deg: float | None = None
    points: tuple[SchematicPoint, ...] = ()


class PlacementPreview(BaseModel):
    """What *would* happen. Computed without touching the simulator."""

    request: PlacementRequest
    placement: Placement
    setup: AircraftSetup = Field(description="The state to apply before the teleport.")
    schematic: PlacementSchematic
    notes: tuple[str, ...] = Field(
        default=(),
        description=(
            "Where each pre-filled number came from — a published constraint, a glideslope "
            "computation, or a category default. The staging bar renders these verbatim so the "
            "instructor can tell a charted altitude from a guessed one."
        ),
    )


class ApplyPlacementRequest(BaseModel):
    """Commit a staged placement, with the staging bar's edits on top."""

    placement: PlacementRequest
    setup: AircraftSetup | None = Field(
        default=None,
        description=(
            "The instructor's edits. Merged OVER the preview's setup rather than replacing it, "
            "so a client that omits a field cannot silently drop the geometry-derived altitude."
        ),
    )


class PlacementResult(BaseModel):
    """What actually happened."""

    placement: Placement
    applied: AircraftSetup
    state: AircraftState


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _category(category: ApproachCategory | None) -> ApproachCategory:
    """The requested ICAO approach category, or the module-wide default.

    The request models spell every optional field ``| None`` so that "the caller
    said nothing" is distinguishable from "the caller said the default", but
    ``core.geodesy`` takes concrete values. Resolving here, once, keeps the
    default in exactly one place — ``core.geodesy`` — instead of copying its
    value into six pydantic ``Field`` declarations.
    """
    return DEFAULT_APPROACH_CATEGORY if category is None else category


def _or_default(value: float | None, default: float) -> float:
    """``value`` when the caller stated one, ``default`` otherwise."""
    return default if value is None else value


def _runway(provider: NavdataProvider, icao: str, ident: str) -> Runway:
    runway = provider.get_runway(icao, ident)
    if runway is None:
        raise HTTPException(
            status_code=404,
            detail=f"Runway {ident.upper()} is not published at {icao.upper()}.",
        )
    return runway


def _airport(provider: NavdataProvider, icao: str) -> Airport:
    airport = provider.get_airport(icao)
    if airport is None:
        raise HTTPException(
            status_code=404, detail=f"Airport {icao.upper()!r} is not in the navigation index."
        )
    return airport


def _leg(provider: NavdataProvider, request: ProcedureLegPlacementRequest) -> ProcedureLeg:
    procedure = provider.get_procedure(
        request.airport_icao, request.kind, request.ident, request.transition
    )
    if procedure is None:
        raise HTTPException(
            status_code=404,
            detail=f"Procedure {request.ident.upper()!r} is not published at "
            f"{request.airport_icao.upper()}.",
        )
    for leg in procedure.legs:
        if leg.sequence == request.sequence:
            break
    else:
        raise HTTPException(
            status_code=404,
            detail=f"Procedure {request.ident.upper()!r} has no leg {request.sequence}.",
        )
    if not leg.is_positionable or leg.fix is None:
        raise HTTPException(
            status_code=UNPOSITIONABLE_STATUS,
            detail=leg.unpositionable_reason
            or f"A {leg.path_terminator} leg carries no defensible coordinate.",
        )
    return leg


def _hold_variation_deg(hold: Hold, airport: Airport | None) -> tuple[float, str]:
    """The variation to hand ``core.geodesy``, saying plainly where it came from.

    ``core.geodesy`` is true throughout and every hold function takes
    ``magnetic_variation_deg`` as a **required** argument precisely so that no
    caller can forget the frame. This project carries no world magnetic model on
    purpose, so the only variation available is whatever the airport record
    published. When there is none, zero is passed — which leaves the published
    magnetic course unconverted — and the note says so, because silently
    treating a magnetic course as true is the single most common way to be
    quietly wrong in navigation.
    """
    course_mag_deg = hold.inbound_course_mag_deg
    if airport is not None and airport.magnetic_variation_deg is not None:
        variation = airport.magnetic_variation_deg
        return variation, (
            f"Inbound course {course_mag_deg:g}° magnetic converted to "
            f"{true_from_magnetic(course_mag_deg, variation):.1f}° true using "
            f"{airport.icao}'s published variation of {variation:+g}°."
        )
    return 0.0, (
        f"Inbound course {course_mag_deg:g}° is MAGNETIC and was used unconverted: no "
        f"magnetic variation is published for this fix, and this station carries no "
        f"world magnetic model."
    )


def _resolve(
    request: PlacementRequest, provider: NavdataProvider
) -> tuple[Placement, PlacementSchematic, list[str]]:
    """Resolve any request into a placement, its diagram and its provenance notes."""
    notes: list[str] = []

    if isinstance(request, RunwayPlacementRequest):
        runway = _runway(provider, request.airport_icao, request.runway_ident)
        category = _category(request.category)
        glideslope_deg = _or_default(request.glideslope_deg, DEFAULT_GLIDESLOPE_DEG)
        pattern_width_nm = _or_default(request.pattern_width_nm, DEFAULT_PATTERN_WIDTH_NM)
        leg_distance_nm = _or_default(request.leg_distance_nm, DEFAULT_PATTERN_LEG_DISTANCE_NM)
        placement = resolve_runway_placement(
            runway,
            request.placement,
            glideslope_deg=glideslope_deg,
            pattern_altitude_ft=request.pattern_altitude_ft,
            pattern_width_nm=pattern_width_nm,
            leg_distance_nm=leg_distance_nm,
            ias_kt=request.ias_kt,
            category=category,
        )
        distance_nm = FINAL_DISTANCES_NM.get(request.placement)  # type: ignore[arg-type]
        if distance_nm is not None:
            notes.append(
                f"{placement.altitude_ft:,.0f} ft — {glideslope_deg:g}° glidepath "
                f"{distance_nm:g} NM from the {runway.ident} threshold at "
                f"{runway.elevation_ft:,.0f} ft."
            )
        elif request.pattern_altitude_ft is None:
            notes.append(
                f"{placement.altitude_ft:,.0f} ft — standard circuit height above the "
                f"{runway.ident} threshold."
            )
        notes.append(_speed_note(request.ias_kt, placement, category))
        return placement, _runway_schematic(runway, placement, request, glideslope_deg), notes

    if isinstance(request, ParkingPlacementRequest):
        stands = provider.get_parking(request.airport_icao)
        wanted = request.stand_name.strip().casefold()
        stand = next((s for s in stands if s.name.strip().casefold() == wanted), None)
        if stand is None:
            raise HTTPException(
                status_code=404,
                detail=f"Stand {request.stand_name!r} is not published at "
                f"{request.airport_icao.upper()}.",
            )
        placement = coordinate_placement(stand.position, stand.heading_true_deg)
        notes.append(
            f"On the ground at {stand.name} ({stand.kind.replace('_', ' ')}), "
            f"facing {stand.heading_true_deg:.0f}° true. 0 kt: a stand is not flown."
        )
        return placement, PlacementSchematic(), notes

    if isinstance(request, CoordinatePlacementRequest):
        placement = coordinate_placement(
            request.position,
            _or_default(request.heading_deg, 0.0),
            ias_kt=_or_default(request.ias_kt, GROUND_IAS_KT),
        )
        if placement.ias_kt == GROUND_IAS_KT and request.position.altitude_ft > 0.0:
            # The warning is keyed on the RESOLVED speed, not on the requested
            # one: omitting ias_kt resolves to 0 kt just as surely as asking for
            # it does, and that is the case most likely to be an accident.
            notes.append(
                "0 kt at a non-zero altitude — the aircraft will be below stall speed. "
                "Set a speed unless this point is on the ground."
            )
        elif request.ias_kt is not None:
            notes.append(f"{placement.ias_kt:g} kt, exactly as requested.")
        else:
            notes.append("0 kt — a bare coordinate is stationary unless a speed is given.")
        return placement, PlacementSchematic(), notes

    if isinstance(request, WaypointPlacementRequest):
        fixes = provider.get_fixes(
            request.ident,
            region=request.region_code,
            terminal_airport=request.terminal_airport,
        )
        if not fixes:
            raise HTTPException(
                status_code=404,
                detail=f"Fix {request.ident.upper()!r} is not in the navigation index.",
            )
        fix = fixes[0]
        if len(fixes) > 1:
            notes.append(
                f"{len(fixes)} fixes are published as {fix.ident}; the one in region "
                f"{fix.region_code or 'unknown'} was used. Give a region to disambiguate."
            )
        category = _category(request.category)
        placement = waypoint_placement(
            fix.position,
            request.altitude_ft,
            ident=fix.ident,
            heading_deg=request.heading_deg,
            ias_kt=request.ias_kt,
            category=category,
        )
        if request.heading_deg is None:
            notes.append("Heading 000° — a bare fix carries no course, and none was given.")
        notes.append(_speed_note(request.ias_kt, placement, category))
        return placement, PlacementSchematic(), notes

    if isinstance(request, ProcedureLegPlacementRequest):
        leg = _leg(provider, request)
        assert leg.fix is not None  # guaranteed by _leg
        altitude_ft = request.altitude_ft
        if altitude_ft is None and leg.altitude is not None:
            altitude_ft = leg.altitude.suggested_ft
            if altitude_ft is not None:
                notes.append(
                    f"{altitude_ft:,.0f} ft — published constraint: {leg.altitude.display}."
                )
        if altitude_ft is None:
            raise HTTPException(
                status_code=UNPOSITIONABLE_STATUS,
                detail=f"Leg {request.sequence} publishes no altitude constraint, so an "
                f"altitude must be given.",
            )
        ias_kt = request.ias_kt
        if ias_kt is None and leg.speed is not None and leg.speed.suggested_kt is not None:
            ias_kt = leg.speed.suggested_kt
            notes.append(f"{ias_kt:g} kt — published constraint: {leg.speed.display}.")
        category = _category(request.category)
        placement = waypoint_placement(
            leg.fix.position,
            altitude_ft,
            ident=leg.fix.ident,
            ias_kt=ias_kt,
            category=category,
        )
        notes.append(_speed_note(ias_kt, placement, category))
        notes.append(
            f"{leg.path_terminator} leg {leg.sequence} of {request.ident.upper()}, "
            f"over {leg.fix.ident}."
        )
        return placement, PlacementSchematic(), notes

    holds = provider.get_holds(
        fix_ident=request.fix_ident,
        region=request.region_code,
        airport_icao=request.airport_icao,
    )
    if not holds:
        raise HTTPException(
            status_code=404,
            detail=f"No published hold at {request.fix_ident.upper()}.",
        )
    hold = holds[0]
    airport = provider.get_airport(hold.airport_icao) if hold.airport_icao is not None else None
    variation_deg, course_note = _hold_variation_deg(hold, airport)
    notes.append(course_note)
    category = _category(request.category)
    try:
        # Altitude, speed and the racetrack geometry are all resolved inside
        # core.geodesy: the published window, the speed placard and the leg
        # time are read there, once, rather than being re-derived here where
        # the two copies could disagree.
        placement = hold_placement(
            hold,
            magnetic_variation_deg=variation_deg,
            altitude_ft=request.altitude_ft,
            ias_kt=request.ias_kt,
            category=category,
        )
    except ValueError as exc:
        # The hold publishes no altitude and none was given. 422 rather than
        # 404: the hold was found, it simply cannot be placed on as it stands.
        raise HTTPException(status_code=UNPOSITIONABLE_STATUS, detail=str(exc)) from exc
    if request.altitude_ft is None:
        notes.append(f"{placement.altitude_ft:,.0f} ft — the hold's published altitude.")
    if request.ias_kt is None and hold.speed_kt is not None:
        notes.append(
            f"The hold is placarded at {hold.speed_kt:g} kt. That is a ceiling, not a "
            f"target: the category speed is used and only clamped by it."
        )
    notes.append(_speed_note(request.ias_kt, placement, category))
    return placement, PlacementSchematic(), notes


def _speed_note(
    requested_kt: float | None, placement: Placement, category: ApproachCategory
) -> str:
    """State where the commanded speed came from — the caller, or the category table.

    The third case is real and not a fallback: a published speed restriction
    clamps the category's manoeuvring speed rather than replacing it, so the
    commanded value matches neither table. Calling that "threshold speed" would
    be the note quietly disagreeing with the number beside it.
    """
    if requested_kt is not None:
        return f"{placement.ias_kt:g} kt, as requested."
    if placement.ias_kt == GROUND_IAS_KT:
        return "0 kt — this placement is on the ground."
    if placement.ias_kt == APPROACH_CATEGORY_CIRCLING_IAS_KT[category]:
        table = "circling speed"
    elif placement.ias_kt == APPROACH_CATEGORY_VAT_KT[category]:
        table = "threshold speed (V_AT)"
    else:
        table = "manoeuvring speed, clamped by a published restriction"
    return (
        f"{placement.ias_kt:g} kt — ICAO category {category} {table}. This is a category "
        f"default, not this airframe's number; set a speed if you know it."
    )


def _runway_schematic(
    runway: Runway,
    placement: Placement,
    request: RunwayPlacementRequest,
    glideslope_deg: float,
) -> PlacementSchematic:
    """Project the runway and the placement into the runway's own tangent plane."""
    axis = runway.true_bearing_deg
    length_nm = runway.length_m / METRES_PER_NAUTICAL_MILE
    departure_end = point_at_distance_and_bearing(runway.threshold, length_nm, axis)

    distance_nm, bearing_deg = distance_and_bearing(runway.threshold, placement.position)
    relative_rad = math.radians(bearing_deg - axis)
    points = [
        SchematicPoint(
            label=runway.ident,
            position=runway.threshold,
            x_nm=0.0,
            y_nm=0.0,
            role="threshold",
        ),
        SchematicPoint(
            label=runway.opposite_ident or "",
            position=departure_end,
            x_nm=length_nm,
            y_nm=0.0,
            role="runway_end",
        ),
        SchematicPoint(
            label=placement.label,
            position=placement.position,
            x_nm=distance_nm * math.cos(relative_rad),
            y_nm=distance_nm * math.sin(relative_rad),
            role="placement",
        ),
    ]
    is_final = request.placement in FINAL_DISTANCES_NM
    return PlacementSchematic(
        runway_ident=runway.ident,
        runway_true_bearing_deg=axis,
        runway_length_m=runway.length_m,
        glidepath_deg=glideslope_deg if is_final else None,
        points=tuple(points),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _require_capability(adapter: SimAdapter, flag: str, what: str) -> None:
    """Refuse up front when the adapter has not declared what this needs."""
    if not bool(getattr(adapter.capabilities, flag, False)):
        raise HTTPException(
            status_code=CAPABILITY_UNAVAILABLE_STATUS,
            detail=f"Unavailable on this adapter — the {adapter.name!r} adapter does not "
            f"declare {flag}, so it cannot {what}.",
        )


def _merge_setup(base: AircraftSetup, override: AircraftSetup | None) -> AircraftSetup:
    """The instructor's edits on top of the geometry's, field by field."""
    if override is None:
        return base
    edits = override.model_dump(exclude_none=True)
    return base.model_copy(update=edits)


@router.post("/preview", response_model=PlacementPreview)
def preview_placement(request: PlacementRequest) -> PlacementPreview:
    """Resolve a placement without moving anything.

    Synchronous, because everything it does is a navdata query and arithmetic —
    it never awaits the simulator, and that is the point.
    """
    placement, schematic, notes = _resolve(request, get_navdata())
    return PlacementPreview(
        request=request,
        placement=placement,
        setup=placement.to_setup(),
        schematic=schematic,
        notes=tuple(notes),
    )


@router.post("/apply", response_model=PlacementResult)
async def apply_placement(request: ApplyPlacementRequest) -> PlacementResult:
    """Place the aircraft. Setup first, then the teleport — see the module docstring."""
    adapter = get_adapter()
    _require_capability(adapter, "can_set_position", "reposition the aircraft")

    placement, _schematic, _notes = _resolve(request.placement, get_navdata())
    setup = _merge_setup(placement.to_setup(), request.setup)

    if setup.model_dump(exclude_none=True):
        _require_capability(
            adapter, "can_set_aircraft_state", "set the speed and altitude a placement needs"
        )

    try:
        # Speed, altitude and heading BEFORE the move. Reversing these two lines
        # puts a parked aircraft on a final at 0 kt (#39).
        await adapter.apply_setup(setup)
        await adapter.set_position(placement.position, placement.heading_deg)
    except CapabilityNotSupported as exc:  # defence in depth; gated above
        raise HTTPException(status_code=CAPABILITY_UNAVAILABLE_STATUS, detail=str(exc)) from exc

    return PlacementResult(
        placement=placement,
        applied=setup,
        state=await adapter.get_aircraft_state(),
    )
