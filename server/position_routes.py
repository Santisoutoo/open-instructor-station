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
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
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
    VAT_FROM_VSO,
    ApproachCategory,
    Placement,
    RunwayPlacement,
    category_for_vat,
    coordinate_placement,
    distance_and_bearing,
    hold_placement,
    point_at_distance_and_bearing,
    positionable_legs,
    procedure_leg_placement,
    resolve_runway_placement,
    true_from_magnetic,
    waypoint_placement,
)
from core.models import AircraftSetup, AircraftState, GeoPosition, Runway
from core.navdata.models import Hold, Procedure, ProcedureLeg, Waypoint
from core.navdata.provider import NavdataProvider, NavdataUnavailable
from core.placements import (
    CoordinatePlacementRequest,
    HoldPlacementRequest,
    ParkingPlacementRequest,
    PlacementRequest,
    ProcedureLegPlacementRequest,
    RunwayPlacementRequest,
    RunwayThresholdPlacementRequest,
    WaypointPlacementRequest,
)
from core.sim_adapter import CapabilityNotSupported, SimAdapter
from server.deps import get_adapter, get_airframe_info, get_navdata

__all__ = [
    "CAPABILITY_UNAVAILABLE_STATUS",
    "UNPOSITIONABLE_STATUS",
    "ApplyPlacementRequest",
    "CoordinatePlacementRequest",
    "HoldPlacementRequest",
    "ParkingPlacementRequest",
    "PlacementPreview",
    "PlacementRequest",
    "PlacementResult",
    "PlacementSchematic",
    "ProcedureLegPlacementRequest",
    "RunwayPlacementRequest",
    "RunwayThresholdPlacementRequest",
    "SchematicPoint",
    "SpeedProvenance",
    "WaypointPlacementRequest",
    "execute_placement",
    "router",
]

#: Mirrors ``server.app.CAPABILITY_UNAVAILABLE_STATUS``. Duplicated rather than
#: imported to keep the import edge one-way: ``app`` includes these routers.
CAPABILITY_UNAVAILABLE_STATUS = 501

#: A leg that carries no defensible coordinate. 422 rather than 404: the leg
#: exists and was found, it simply cannot be a position. The UI has already
#: disabled that row, so reaching this means a caller ignored the data.
UNPOSITIONABLE_STATUS = 422

#: Which rule produced a placement's speed when the caller named none, carried
#: as a token from the branch that was actually taken.
#:
#: **A resolved speed cannot be attributed after the fact.** A value clamped to
#: a published restriction can coincide exactly with a category table entry, and
#: labelling it by that coincidence credits a charted number to the category
#: chart and a category default to the chart — the exact inversion of the
#: distinction these notes exist to make.
#:
#: ``"unattributed"`` is the honest answer when the source genuinely cannot be
#: named, and the note falls back to a sentence that claims nothing.
SpeedProvenance = Literal[
    "threshold", "circling", "restriction", "minimum", "floor", "unattributed"
]

#: How close to the local ground a coordinate has to be before 0 kt reads as
#: "parked" rather than as "about to stall". A hundred feet is less than a
#: circuit's worth of altitude and well inside the error of using an airport
#: elevation as a terrain reference.
GROUND_TOLERANCE_FT = 100.0

#: How far to look for an airport to take that ground elevation from. Beyond
#: this the reference says nothing useful about the terrain under the point.
GROUND_REFERENCE_RADIUS_NM = 50.0

router = APIRouter(prefix="/api/position", tags=["position"])


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


def _runway(provider: NavdataProvider, icao: str, ident: str) -> Runway:
    runway = provider.get_runway(icao, ident)
    if runway is None:
        raise HTTPException(
            status_code=404,
            detail=f"Runway {ident.upper()} is not published at {icao.upper()}.",
        )
    return runway


def _leg(
    provider: NavdataProvider, request: ProcedureLegPlacementRequest
) -> tuple[Procedure, ProcedureLeg]:
    """The requested leg, with the procedure it belongs to — the neighbours give it a heading."""
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
    return procedure, leg


def _hold_variation(provider: NavdataProvider, hold: Hold) -> tuple[float, str]:
    """The magnetic variation to convert a hold's published course with, and a note.

    A published inbound course is magnetic and ``core.geodesy`` is true
    throughout, so something has to supply the variation. This project carries
    no world magnetic model on purpose, which leaves whatever the airport record
    published — and when there is none, zero, meaning the magnetic value is used
    unconverted. The note says which of the two happened, because silently
    treating a magnetic course as true is the commonest way to be quietly wrong
    in navigation, and the instructor is the one who can tell whether it matters
    where they are flying.
    """
    airport = provider.get_airport(hold.airport_icao) if hold.airport_icao is not None else None
    course = hold.inbound_course_mag_deg
    if airport is not None and airport.magnetic_variation_deg is not None:
        variation = airport.magnetic_variation_deg
        return variation, (
            f"Inbound course {course:g}° magnetic converted to "
            f"{true_from_magnetic(course, variation):.1f}° true using {airport.icao}'s "
            f"published variation of {variation:+g}°."
        )
    return 0.0, (
        f"Inbound course {course:g}° is MAGNETIC and was used unconverted: no magnetic "
        f"variation is published for this fix, and this station carries no world "
        f"magnetic model."
    )


def _local_ground_elevation_ft(provider: NavdataProvider, position: GeoPosition) -> float:
    """A ground reference for an arbitrary coordinate, in feet MSL.

    **Zero is not the ground.** Comparing an altitude against sea level to
    decide whether a point is parked or flying reads Schiphol (-11 ft) and the
    Dead Sea (-1,410 ft) as impossible, and — the failure that matters — hands
    an *airborne* point below sea level the reassuring sentence instead of the
    stall warning.

    This station carries no terrain service, but it does hold every airport in
    the user's install: the nearest one is a far better ground reference than
    sea level, and where there is none within
    :data:`GROUND_REFERENCE_RADIUS_NM` — mid-ocean — sea level is the right
    answer anyway.

    A coordinate placement is the one placement that needs no navdata at all, so
    an unusable index must not be allowed to turn it into a 503: the reference
    degrades to sea level and the placement still works.
    """
    try:
        nearby = provider.airports_near(position, GROUND_REFERENCE_RADIUS_NM, limit=1)
    except NavdataUnavailable:
        return 0.0
    return nearby[0].elevation_ft if nearby else 0.0


def request_category(request: PlacementRequest) -> tuple[ApproachCategory, str | None]:
    """The approach category to resolve speeds with, and the note that discloses it.

    A fallback chain, most specific source first:

    1. **The category stated in the request.** The instructor's word is final.
       No note of its own: the speed notes already name the category they used,
       and the instructor chose it.
    2. **Derived from the loaded airframe** (issue #82): the stall speed the
       adapter reported at connect, through the published PANS-OPS arithmetic —
       ``Vso → 1.3·Vso = V_AT → band``. The note states that whole chain,
       because a derived category and a guessed one must never read the same.
       The airframe is a cache and can be stale after a mid-session aircraft
       swap — see :func:`server.deps.get_airframe_info` for why that is
       accepted.
    3. **The project's category B default**, with today's honest story
       unchanged: the speed notes call the result a category default and tell
       the instructor to set a speed if they know the airframe.

    **The wire says "not stated" with ``null``, not with "B".** Every one of these fields
    could have carried its default in the schema instead, but then a generated client would
    be forced to send a category on every request and the server could never tell an
    instructor who chose B from one who said nothing — which is exactly the distinction the
    preview's notes exist to report.
    """
    stated = getattr(request, "category", None)
    if stated is not None:
        return stated, None
    airframe = get_airframe_info()
    if airframe.vso_kias is not None:
        vat_kt = VAT_FROM_VSO * airframe.vso_kias
        category = category_for_vat(vat_kt)
        return category, (
            f"Category {category} — derived from the loaded airframe "
            f"(Vso {airframe.vso_kias:g} kt, V_AT {vat_kt:.0f} kt)."
        )
    return DEFAULT_APPROACH_CATEGORY, None


def _resolve(
    request: PlacementRequest, provider: NavdataProvider
) -> tuple[Placement, PlacementSchematic, list[str]]:
    """Resolve any request into a placement, its diagram and its provenance notes.

    ``core.geodesy`` raises :class:`ValueError` when a request cannot be honoured
    from the published data — a leg with no altitude constraint and no altitude
    given, for instance. That is a 422 with the module's own sentence, not a 500:
    the request is well formed and the *data* cannot answer it.
    """
    try:
        return _resolve_placement(request, provider)
    except ValueError as exc:
        raise HTTPException(status_code=UNPOSITIONABLE_STATUS, detail=str(exc)) from exc


def _resolve_placement(
    request: PlacementRequest, provider: NavdataProvider
) -> tuple[Placement, PlacementSchematic, list[str]]:
    notes: list[str] = []

    category, category_note = request_category(request)

    if isinstance(request, RunwayPlacementRequest):
        runway = _runway(provider, request.airport_icao, request.runway_ident)
        glideslope_deg, glideslope_source = _glideslope_deg(runway, request.glideslope_deg)
        placement = resolve_runway_placement(
            runway,
            request.placement,
            glideslope_deg=glideslope_deg,
            pattern_altitude_ft=request.pattern_altitude_ft,
            pattern_width_nm=request.pattern_width_nm or DEFAULT_PATTERN_WIDTH_NM,
            leg_distance_nm=request.leg_distance_nm or DEFAULT_PATTERN_LEG_DISTANCE_NM,
            ias_kt=request.ias_kt,
            category=category,
            # The published ILS rides along so a final's setup tunes NAV1 and
            # the OBS — the radios arrive with the geometry, never separately.
            ils=runway.ils,
        )
        distance_nm = FINAL_DISTANCES_NM.get(request.placement)  # type: ignore[arg-type]
        if distance_nm is not None:
            notes.append(
                f"{placement.altitude_ft:,.0f} ft — {glideslope_deg:g}° glidepath "
                f"({glideslope_source}) {distance_nm:g} NM from the {runway.ident} threshold at "
                f"{runway.elevation_ft:,.0f} ft."
            )
        elif request.pattern_altitude_ft is None:
            notes.append(
                f"{placement.altitude_ft:,.0f} ft — standard circuit height above the "
                f"{runway.ident} threshold."
            )
        # A final is flown at the threshold speed of the category, a circuit leg
        # at its circling speed — which of the two is the branch
        # ``resolve_runway_placement`` takes, not something to infer afterwards.
        notes.append(
            _speed_note(
                request.ias_kt,
                placement,
                category,
                provenance="threshold" if distance_nm is not None else "circling",
            )
        )
        # The derivation is disclosed only where the category shaped the speed:
        # an explicit ias_kt makes the category a bystander, and crediting a
        # bystander is the exact dishonesty these notes exist to avoid. The
        # same guard repeats at every category-resolved speed below.
        if request.ias_kt is None and category_note is not None:
            notes.append(category_note)
        schematic = _runway_schematic(runway, placement, request.placement, glideslope_deg)
        return placement, schematic, notes

    if isinstance(request, RunwayThresholdPlacementRequest):
        runway = _runway(provider, request.airport_icao, request.runway_ident)
        placement = coordinate_placement(
            runway.threshold, runway.true_bearing_deg, ias_kt=GROUND_IAS_KT
        )
        notes.append(
            f"On the centreline at {runway.ident}'s threshold, facing "
            f"{runway.true_bearing_deg:.0f}° true. 0 kt — lined up for a takeoff brief."
        )
        return placement, PlacementSchematic(), notes

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
            request.heading_deg or 0.0,
            ias_kt=request.ias_kt if request.ias_kt is not None else GROUND_IAS_KT,
        )
        # The only placement type whose altitude does not imply flight: a bare
        # coordinate is as likely a stand as a cruise level, so this is the one
        # place an altitude has to be measured against the ground to decide
        # whether 0 kt is defensible.
        ground_ft = _local_ground_elevation_ft(provider, request.position)
        notes.append(
            _speed_note(
                request.ias_kt,
                placement,
                category,
                on_ground=request.position.altitude_ft <= ground_ft + GROUND_TOLERANCE_FT,
            )
        )
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
        # A bare fix has no published band, so the category's circling speed is
        # used unclamped, as a generic manoeuvring speed.
        notes.append(_speed_note(request.ias_kt, placement, category, provenance="circling"))
        if request.ias_kt is None and category_note is not None:
            notes.append(category_note)
        return placement, PlacementSchematic(), notes

    if isinstance(request, ProcedureLegPlacementRequest):
        procedure, leg = _leg(provider, request)
        if request.altitude_ft is None and leg.altitude is not None:
            notes.append(f"Published constraint: {leg.altitude.display}.")
        if request.ias_kt is None and leg.speed is not None:
            notes.append(f"Published constraint: {leg.speed.display}.")
        # The surrounding legs are what give a leg a heading: an ARINC outbound
        # course is magnetic, and this project carries no magnetic model.
        neighbours = _neighbouring_fixes(procedure, leg)
        placement = procedure_leg_placement(
            leg,
            altitude_ft=request.altitude_ft,
            ias_kt=request.ias_kt,
            category=category,
            procedure_ident=procedure.ident,
            previous_fix=neighbours[0],
            next_fix=neighbours[1],
        )
        provenance, bound_kt = _constrained_speed_provenance(
            placement.ias_kt,
            category,
            min_kt=leg.speed.min_kt if leg.speed is not None else None,
            max_kt=leg.speed.max_kt if leg.speed is not None else None,
        )
        notes.append(
            _speed_note(
                request.ias_kt, placement, category, provenance=provenance, bound_kt=bound_kt
            )
        )
        if request.ias_kt is None and category_note is not None:
            notes.append(category_note)
        notes.append(f"{leg.path_terminator} leg {leg.sequence} of {procedure.ident}.")
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
    variation_deg, course_note = _hold_variation(provider, hold)
    notes.append(course_note)
    if request.altitude_ft is None and hold.min_altitude_ft is not None:
        notes.append(f"{hold.min_altitude_ft:,.0f} ft — the hold's published minimum.")
    if request.ias_kt is None and hold.speed_kt is not None:
        # A placard is a ceiling, not a target: the aircraft flies its own
        # manoeuvring speed clamped to it, never the placard itself.
        notes.append(f"Published speed restriction: at or below {hold.speed_kt:g} kt.")
    placement = hold_placement(
        hold,
        magnetic_variation_deg=variation_deg,
        altitude_ft=request.altitude_ft,
        ias_kt=request.ias_kt,
        category=category,
    )
    provenance, bound_kt = _constrained_speed_provenance(
        placement.ias_kt, category, min_kt=None, max_kt=hold.speed_kt
    )
    notes.append(
        _speed_note(request.ias_kt, placement, category, provenance=provenance, bound_kt=bound_kt)
    )
    if request.ias_kt is None and category_note is not None:
        notes.append(category_note)
    return placement, PlacementSchematic(), notes


def _neighbouring_fixes(
    procedure: Procedure, leg: ProcedureLeg
) -> tuple[Waypoint | None, Waypoint | None]:
    """The resolved fixes either side of ``leg`` in its own procedure.

    They are what give the placement a heading. Only positionable legs are
    considered, because an unresolved fix is no more use as a neighbour than it
    is as a destination.
    """
    placeable = positionable_legs(procedure)
    index = next(
        (i for i, candidate in enumerate(placeable) if candidate.sequence == leg.sequence),
        None,
    )
    if index is None:
        return None, None
    previous = placeable[index - 1].fix if index > 0 else None
    following = placeable[index + 1].fix if index + 1 < len(placeable) else None
    return previous, following


def _constrained_speed_provenance(
    resolved_kt: float,
    category: ApproachCategory,
    *,
    min_kt: float | None,
    max_kt: float | None,
) -> tuple[SpeedProvenance, float | None]:
    """Which branch of ``core.geodesy._constrained_ias_kt`` produced ``resolved_kt``.

    A published band can land the resolved speed on *any* value, including one
    that coincides exactly with a category table entry — a leg placarded at
    130 kt and a category B threshold speed of 120 kt are different facts that a
    130 kt answer cannot be asked to distinguish. So the branch is re-derived
    from the same **inputs** ``core.geodesy`` had, never from its output.

    The re-derivation mirrors a private rule of ``core.geodesy``, and a mirror
    can drift. It therefore checks itself against the speed that actually came
    back and answers ``"unattributed"`` when the two disagree: a note that says
    nothing is a small loss, and a note that credits a charted number to the
    category chart is the defect this function exists to remove.

    The honest fix is for ``core.geodesy`` to hand back the provenance beside
    the speed. That file belongs to another PR — see the report.
    """
    circling = APPROACH_CATEGORY_CIRCLING_IAS_KT[category]
    threshold = APPROACH_CATEGORY_VAT_KT[category]

    speed = circling
    provenance: SpeedProvenance = "circling"
    bound_kt: float | None = None
    if max_kt is not None and max_kt < speed:
        speed, provenance, bound_kt = max_kt, "restriction", max_kt
    if min_kt is not None and min_kt > speed:
        speed, provenance, bound_kt = min_kt, "minimum", min_kt
    if threshold > speed:
        speed, provenance, bound_kt = threshold, "floor", None

    if speed != resolved_kt:
        return "unattributed", None
    return provenance, bound_kt


def _speed_note(
    requested_kt: float | None,
    placement: Placement,
    category: ApproachCategory,
    *,
    provenance: SpeedProvenance = "unattributed",
    bound_kt: float | None = None,
    on_ground: bool = False,
) -> str:
    """State where the commanded speed came from, and warn when it cannot be flown.

    **The zero check keys on the resolved speed, never on who asked for it.** An
    explicit ``ias_kt: 0`` reproduces issue #39's measured crash exactly as
    surely as a defaulted one — perfect geometry, 0.2 m placement error, and the
    aircraft in the terrain because it is below stall speed — so a placement that
    is not on the ground is warned about whoever chose the number.

    It stays a **warning and not a refusal**: a stationary aircraft in the air is
    a legitimate demonstration, and refusing would be the station overruling the
    instructor.
    """
    if placement.ias_kt == GROUND_IAS_KT:
        if not on_ground:
            return (
                f"0 kt at {placement.altitude_ft:,.0f} ft — the aircraft is below stall speed and "
                "will fall out of the sky. Set a speed unless this point is on the ground."
            )
        if requested_kt is not None:
            return "0 kt, exactly as requested — this placement is on the ground."
        # Nothing was requested, so nothing may be reported "as requested":
        # this is the default a bare coordinate carries, and saying otherwise
        # credits the instructor with a number they never typed.
        return "0 kt — no speed was given, and a coordinate on the ground defaults to stationary."
    if requested_kt is not None:
        return f"{placement.ias_kt:g} kt, exactly as requested."

    circling = APPROACH_CATEGORY_CIRCLING_IAS_KT[category]
    if provenance == "threshold":
        return (
            f"{placement.ias_kt:g} kt — ICAO category {category} threshold speed (V_AT). This is "
            f"a category default, not this airframe's number; set a speed if you know it."
        )
    if provenance == "circling":
        return (
            f"{placement.ias_kt:g} kt — ICAO category {category} circling speed. This is a "
            f"category default, not this airframe's number; set a speed if you know it."
        )
    if provenance == "floor":
        return (
            f"{placement.ias_kt:g} kt — ICAO category {category} threshold speed (V_AT). The "
            f"published restriction is slower than that, and no chart may hand an aeroplane a "
            f"stall; set a speed if you know the airframe."
        )
    if provenance == "restriction" and bound_kt is not None:
        return (
            f"{placement.ias_kt:g} kt — the published restriction of at or below {bound_kt:g} kt, "
            f"which is slower than ICAO category {category}'s circling speed of {circling:g} kt."
        )
    if provenance == "minimum" and bound_kt is not None:
        return (
            f"{placement.ias_kt:g} kt — the published minimum of {bound_kt:g} kt, which is faster "
            f"than ICAO category {category}'s circling speed of {circling:g} kt."
        )
    return (
        f"{placement.ias_kt:g} kt — an ICAO category {category} default folded into the published "
        f"speed band. Set a speed if you know the airframe."
    )


def _profile_notes(placement: Placement, setup: AircraftSetup) -> tuple[str, ...]:
    """Disclose the configuration the placement's profile pre-filled.

    Read off the **emitted setup**, never off the table that produced it, so
    the note cannot disagree with what will be applied. The numbers are the
    airframe-generic hand-off constants of ``core.geodesy`` (see
    ``FINAL_THROTTLE``), stated verbatim precisely because they are generic:
    the instructor is the one who knows the airframe, and every one of them is
    overridable from the staging bar, whose edits win the merge.
    """
    gear = "gear down" if setup.gear_down else "gear up"
    flaps = "flaps up" if not setup.flaps_ratio else f"flaps {setup.flaps_ratio:.0%}"
    if placement.profile == "final":
        descent = ""
        if setup.vertical_speed_fpm is not None and placement.glideslope_deg is not None:
            descent = (
                f", descending {-setup.vertical_speed_fpm:,.0f} fpm on the "
                f"{placement.glideslope_deg:.1f}° slope"
            )
        notes: tuple[str, ...] = (
            f"Configured for a final: {gear}, {flaps}, throttle {setup.throttle_ratio:.0%}, "
            f"trim {setup.elevator_trim_ratio:+.2f}{descent}.",
        )
        if placement.ils is not None and setup.nav1_freq_khz is not None:
            notes += (
                f"NAV1 {setup.nav1_freq_khz / 1000.0:.2f} / OBS {setup.obs1_deg:.0f}° — "
                f"the published ILS for {placement.ils.runway_ident}.",
            )
        return notes
    if placement.profile == "circuit":
        return (
            f"Configured for the {placement.pattern_leg} leg: {gear}, {flaps}, "
            f"throttle {setup.throttle_ratio:.0%}.",
        )
    if placement.profile == "airborne":
        return (
            f"Configured for level flight: {gear}, {flaps}, throttle {setup.throttle_ratio:.0%}.",
        )
    # On the ground everything idles, and roll and vertical speed are left to
    # the terrain — which is why neither is named here.
    return (f"Configured for the ground: {gear}, {flaps}, throttle idle.",)


def _glideslope_deg(runway: Runway, requested_deg: float | None) -> tuple[float, str]:
    """The glidepath angle to place on, and where it came from.

    ``None`` takes the runway's **published** ILS glidepath when it has one.
    :class:`~core.models.Runway` carries its :class:`~core.models.Ils` precisely
    so this is a single lookup, and reaching for the 3° ICAO standard instead is
    not a harmless approximation: at a field whose published path is 3.8°, a
    10 NM final on 3° sits 851 ft *below* the glideslope the student is about to
    intercept — the wrong side of it, converging from underneath.
    """
    if requested_deg is not None:
        return requested_deg, "as requested"
    published_deg = runway.ils.glideslope_deg if runway.ils is not None else None
    if published_deg is not None:
        return published_deg, f"{runway.ident}'s published ILS glidepath"
    return DEFAULT_GLIDESLOPE_DEG, "the ICAO standard, as no ILS glidepath is published here"


def _runway_schematic(
    runway: Runway,
    placement: Placement,
    placement_name: RunwayPlacement,
    glideslope_deg: float,
) -> PlacementSchematic:
    """Project the runway and the placement into the runway's own tangent plane.

    Takes the **resolved** glidepath angle rather than the request, so the diagram can
    never disagree with the altitude that was actually computed from it.
    """
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
    is_final = placement_name in FINAL_DISTANCES_NM
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
    """The instructor's edits on top of the geometry's, field by field.

    **The merged result is re-validated, and that is the whole point of the
    detour through dictionaries.** ``model_dump`` is recursive, so a nested model
    such as ``lights`` comes out as a plain ``dict``; ``model_copy(update=...)``
    stores whatever it is handed **without validating it**. The pair therefore
    produces an ``AircraftSetup`` whose ``lights`` is a ``dict``, which type
    checks fine and then explodes inside the adapter — ``getattr(setup.lights,
    "landing")`` on a ``dict`` — as a 500, *after* ``apply_setup`` has already
    started writing.

    ``model_validate`` rebuilds every sub-model, so the fix holds for any nested
    field added later rather than for ``lights`` alone. ``{"lights": {}}`` is the
    same hazard and is covered by the same line: ``exclude_none`` empties the
    sub-dictionary but keeps the key, so the value is ``{}`` and not ``None``.

    The merge is field-by-field at the **top** level: an edit that names a nested
    model replaces that model whole. Nothing in ``Placement.to_setup()`` sets a
    nested field, so there is nothing to lose today, and a deep merge would have
    to invent a meaning for "unset this switch" that the wire has no way to say.
    """
    if override is None:
        return base
    merged = base.model_dump()
    merged.update(override.model_dump(exclude_none=True))
    return AircraftSetup.model_validate(merged)


def _placed_as_edited(placement: Placement, setup: AircraftSetup) -> Placement:
    """Fold the setup's *geometric* fields back into the placement.

    ``altitude_ft`` and ``heading_deg`` look like setup, and they are not: they
    are geometry, and ``set_position`` is authoritative for both. It writes the
    altitude out of ``placement.position`` and the heading out of
    ``placement.heading_deg``, and it runs **after** ``apply_setup`` — so an
    instructor's edit written as part of the setup is overwritten a moment
    later. Measured on a 10 NM final: an altitude edited to 1234 ft arrived as
    4184.36, a heading edited to 99° arrived as 0°.

    Two of the staging bar's four editable controls therefore did nothing, and
    ``PlacementResult.applied`` reported the *write* rather than the outcome —
    confidently telling the instructor a value took when the read-back proves it
    did not. A response that misreports the aircraft's state is worse than one
    that refuses.

    So an edit **moves the placement**, and the geometry it displaces is
    replaced rather than fought. The edited fields stay in the setup as well:
    ``set_position`` then writes the same numbers, which is what makes
    ``applied`` honest.

    The result is rebuilt through the constructor rather than ``model_copy`` so
    it is validated — ``heading_deg`` is ``[0, 360)`` on a ``Placement`` and the
    wire allows 360.0.
    """
    if setup.altitude_ft is None and setup.heading_deg is None:
        return placement
    altitude_ft = placement.position.altitude_ft if setup.altitude_ft is None else setup.altitude_ft
    heading_deg = placement.heading_deg if setup.heading_deg is None else setup.heading_deg % 360.0
    return Placement(
        position=GeoPosition(
            latitude=placement.position.latitude,
            longitude=placement.position.longitude,
            altitude_ft=altitude_ft,
        ),
        heading_deg=heading_deg,
        ias_kt=placement.ias_kt,
        label=placement.label,
        # The profile and what feeds it survive the edit: moving a final up or
        # down its glidepath does not stop it being a final on that ILS.
        profile=placement.profile,
        ils=placement.ils,
        glideslope_deg=placement.glideslope_deg,
        pattern_leg=placement.pattern_leg,
    )


# ``def``, not ``async def``, and that is load-bearing. Everything this route
# does is a navdata query and arithmetic — SQLite reads and, for a procedure, a
# lazy CIFP parse, none of which have an async API. FastAPI runs a synchronous
# route in its threadpool, which is exactly right for a blocking call; declaring
# it ``async def`` would run the same work on the event loop and stall the ~4 Hz
# telemetry push to the tablet while it ran. The same reasoning is written out in
# ``server/navdata_routes.py``. (Kept as a comment and not in the docstring: a
# route docstring is published as the OpenAPI operation description, and the UI
# client is generated from that.)
@router.post("/preview", response_model=PlacementPreview)
def preview_placement(request: PlacementRequest) -> PlacementPreview:
    """Resolve a placement without moving anything.

    Synchronous, because everything it does is a navdata query and arithmetic —
    it never awaits the simulator, and that is the point.
    """
    placement, schematic, notes = _resolve(request, get_navdata())
    setup = placement.to_setup()
    return PlacementPreview(
        request=request,
        placement=placement,
        setup=setup,
        schematic=schematic,
        notes=(*notes, *_profile_notes(placement, setup)),
    )


async def execute_placement(
    request: ApplyPlacementRequest,
    *,
    adapter: SimAdapter,
    navdata: NavdataProvider,
) -> PlacementResult:
    """Place the aircraft. Setup first, then the teleport — see the module docstring.

    Factored out of ``POST /api/position/apply`` so the Scenario Generator's
    engine reuses this exact state-before-teleport sequencing (#37, #39)
    instead of re-deriving it — a plain function taking its adapter and
    navdata explicitly, rather than reaching for the request-scoped
    dependencies itself, is what makes it callable from a background task
    with no HTTP request behind it.
    """
    _require_capability(adapter, "can_set_position", "reposition the aircraft")

    # Off the event loop, on purpose. This route has to be ``async def`` because
    # the adapter calls below are awaited, but resolving the placement is the
    # same blocking navdata work ``preview`` does — SQLite reads and, for a
    # procedure, a lazy CIFP parse. Run inline it would stall the loop that also
    # serves ``/ws/state``, so the telemetry feed the instructor is watching
    # freezes during the one operation where the aircraft is moving. Do not
    # "optimise" this hop away.
    placement, _schematic, _notes = await run_in_threadpool(_resolve, request.placement, navdata)
    setup = _merge_setup(placement.to_setup(), request.setup)
    # An edited altitude or heading has to move the PLACEMENT, because
    # set_position writes both and runs last — an edit left in the setup alone is
    # overwritten a moment later and the response then reports a value that never
    # took. See _placed_as_edited. This is also what makes the returned
    # ``placement`` and ``applied`` describe the aircraft rather than the request.
    placement = _placed_as_edited(placement, setup)

    if setup.model_dump(exclude_none=True):
        _require_capability(
            adapter, "can_set_aircraft_state", "set the speed and altitude a placement needs"
        )

    try:
        # Speed, altitude and heading BEFORE the move. Reversing these two lines
        # puts a parked aircraft on a final at 0 kt (#39).
        await adapter.apply_setup(setup)
        # The speed goes in again here, and that is not redundant: apply_setup
        # releases the flight model when it finishes, the aircraft decelerates
        # while it settles, and an adapter left to read the speed for itself
        # would carry the decayed value onto the new heading. Measured at LEMD:
        # 120 kt commanded, 83 kt on arrival. The descent rate is the same
        # lesson on the vertical axis (#39): the teleport writes the whole
        # velocity vector, so anything not re-delivered here arrives level.
        await adapter.set_position(
            placement.position,
            placement.heading_deg,
            ias_kt=setup.ias_kt,
            vertical_speed_fpm=setup.vertical_speed_fpm,
        )
    except CapabilityNotSupported as exc:  # defence in depth; gated above
        raise HTTPException(status_code=CAPABILITY_UNAVAILABLE_STATUS, detail=str(exc)) from exc

    return PlacementResult(
        placement=placement,
        applied=setup,
        state=await adapter.get_aircraft_state(),
    )


@router.post("/apply", response_model=PlacementResult)
async def apply_placement(request: ApplyPlacementRequest) -> PlacementResult:
    """Place the aircraft. Setup first, then the teleport — see the module docstring."""
    return await execute_placement(request, adapter=get_adapter(), navdata=get_navdata())
