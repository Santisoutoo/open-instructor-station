"""Lay a published procedure out to scale, anchored at the airport.

Pure geometry over :mod:`core.geodesy`, :mod:`core.models` and
:mod:`core.navdata.models` — no server, no I/O, no simulator. See
``docs/designs/procedure-approach-types-and-profile-view.md`` §4 for the
design this implements (decisions D7-D12) and the rationale below for the one
gap that design left open.

**The chain is walked, not projected.** A naive per-leg azimuthal projection
from the airport reference point would place every node at its true position
regardless of compression, which would draw nothing differently from an
uncompressed chart. Instead, each edge between consecutive legs gets a **true**
bearing and length (from the resolved fixes, when both ends have one) and a
**drawn** length — capped when compression applies — and the node positions
are the cumulative sum of those drawn vectors from the anchor. Compression
therefore only ever shortens the picture; it never moves a node off the true
bearing of the leg either side of it.

**Anchoring a SID needs more than the procedure.** Every other kind resolves
its own anchor from its own legs: an approach with a resolved runway-threshold
fix (``fix.kind == "runway"``) anchors there; a STAR or a circling approach
with none anchors at its last positioned fix. A SID's legs never touch a
runway fix at all — a departure climbs away from the threshold, it does not
carry it as a leg — so there is nothing in the procedure to anchor on. The
caller may supply the departure ``Runway`` for exactly this case: its
``threshold`` becomes the origin, *outside* the returned node list, and the
first leg is walked outward from it.
"""

from __future__ import annotations

import math
from statistics import median

from core.geodesy import distance_and_bearing, true_from_magnetic
from core.models import GeoPosition, Runway
from core.navdata.models import (
    Airport,
    AltitudeSource,
    LayoutNode,
    LayoutScale,
    LayoutSegment,
    Procedure,
    ProcedureLayout,
    ProcedureLeg,
)

__all__ = ["procedure_layout"]

#: A segment shorter than this is treated as zero-length (two legs sharing a fix, e.g. a
#: hold's entry and its own fix): the geodesic inverse between coincident points has no
#: meaningful bearing, so one is never trusted from it.
_EPSILON_NM = 1e-6

#: Drawn advance for a leg with no resolved fix — there is no coordinate to place it at.
NOMINAL_LEG_NM = 2.0

#: A geodesic segment longer than this multiple of the median compresses.
LONG_FACTOR = 3.0

#: Below this many non-zero geodesic segments, `median` is too noisy to police — nothing
#: compresses (and mathematically, one or two samples rarely could anyway).
_MIN_SEGMENTS_FOR_COMPRESSION = 3


def _vector(bearing_deg: float, length_nm: float) -> tuple[float, float]:
    """A true bearing and a length as an (east, north) NM offset."""
    rad = math.radians(bearing_deg)
    return length_nm * math.sin(rad), length_nm * math.cos(rad)


def _leg_ident(leg: ProcedureLeg) -> str:
    """The label the diagram shows for a leg — the same fallback the leg table already uses.

    A resolved fix names itself; an unresolved one still names itself via ``fix_ref`` (the
    raw ARINC key, kept for exactly this — see :attr:`ProcedureLeg.fix_ref`'s own docstring),
    which reads far better than the bare terminator code. Only a leg with neither (no fix at
    all, e.g. a ``CA``) falls back to its terminator.
    """
    if leg.fix is not None:
        return leg.fix.ident
    if leg.fix_ref is not None:
        return leg.fix_ref.ident
    return leg.path_terminator


def _course_bearing(
    leg: ProcedureLeg,
    airport: Airport,
    previous_bearing: float | None,
    runway: Runway | None,
) -> float:
    """The bearing to draw a fix-less (or fix-less-predecessor) edge along.

    Preference order: the leg's own published course, converted to true — the only frame
    this module works in — when a local magnetic variation is known; else whatever bearing
    the previous edge was drawn on, so a run of unpositioned legs continues in one direction
    rather than zig-zagging; else the runway heading, the only defensible default for the
    very first edge of a SID; else true north, so the node lands *somewhere* defensible
    rather than the function refusing to answer.
    """
    if leg.outbound_course_mag_deg is not None and airport.magnetic_variation_deg is not None:
        return true_from_magnetic(leg.outbound_course_mag_deg, airport.magnetic_variation_deg)
    if previous_bearing is not None:
        return previous_bearing
    if runway is not None:
        return runway.true_bearing_deg
    return 0.0


def _altitude(leg: ProcedureLeg, is_runway: bool) -> tuple[float, AltitudeSource] | None:
    """The published or runway altitude for one node, or ``None`` to interpolate later."""
    if leg.altitude is not None and leg.altitude.suggested_ft is not None:
        return leg.altitude.suggested_ft, "published"
    if is_runway and leg.fix is not None:
        return leg.fix.position.altitude_ft, "runway"
    return None


def _interpolate_altitudes(
    known: list[tuple[float, AltitudeSource] | None],
    cumulative_true_nm: list[float],
    airport_elevation_ft: float,
) -> list[tuple[float, AltitudeSource]]:
    """Fill every ``None`` by linear interpolation over cumulative true distance.

    A node with a known neighbour on only one side takes that neighbour's value outright
    (a flat extension, still honestly flagged ``"interpolated"``, not invented). A node with
    none on either side — nothing anywhere in the procedure is known — is drawn flat at the
    airport's own elevation and flagged ``"unknown"``, per D12: the picture must never invent
    a slope it has no evidence for.
    """
    resolved: list[tuple[float, AltitudeSource] | None] = list(known)
    known_indices = [i for i, value in enumerate(known) if value is not None]
    for i, value in enumerate(resolved):
        if value is not None:
            continue
        before = max((j for j in known_indices if j < i), default=None)
        after = min((j for j in known_indices if j > i), default=None)
        if before is not None and after is not None:
            alt_before = known[before][0]  # type: ignore[index]
            alt_after = known[after][0]  # type: ignore[index]
            span = cumulative_true_nm[after] - cumulative_true_nm[before]
            fraction = (
                (cumulative_true_nm[i] - cumulative_true_nm[before]) / span
                if span > _EPSILON_NM
                else 0.0
            )
            resolved[i] = (alt_before + (alt_after - alt_before) * fraction, "interpolated")
        elif before is not None:
            resolved[i] = (known[before][0], "interpolated")  # type: ignore[index]
        elif after is not None:
            resolved[i] = (known[after][0], "interpolated")  # type: ignore[index]
        else:
            resolved[i] = (airport_elevation_ft, "unknown")
    return resolved  # type: ignore[return-value]


def procedure_layout(
    procedure: Procedure,
    airport: Airport,
    runway: Runway | None = None,
) -> ProcedureLayout:
    """Compute the to-scale lateral/vertical layout of one procedure.

    ``runway`` matters only when the procedure's own legs never resolve a runway-threshold
    fix — in practice, only ever a SID (see the module docstring). It is silently ignored
    whenever the procedure carries its own runway fix, and it is fine to pass ``None`` for
    every other kind.
    """
    legs = sorted(procedure.legs, key=lambda leg: leg.sequence)
    if not legs:
        return ProcedureLayout(
            airport_icao=procedure.airport_icao,
            kind=procedure.kind,
            ident=procedure.ident,
            transition=procedure.transition,
            approach_type=procedure.approach_type,
            anchor="last_fix",
            airport_x_nm=0.0,
            airport_y_nm=0.0,
            airport_elevation_ft=airport.elevation_ft,
            nodes=(),
            segments=(),
            total_true_length_nm=0.0,
            compressed_segment_count=0,
        )

    n = len(legs)
    fixes: list[GeoPosition | None] = [
        leg.fix.position if leg.fix is not None else None for leg in legs
    ]
    is_runway_leg = [leg.fix is not None and leg.fix.kind == "runway" for leg in legs]

    # --- edges: true bearing/length between every consecutive pair of legs -----------
    edge_true_nm: list[float] = []
    edge_bearing_deg: list[float] = []
    for i in range(n - 1):
        a, b = fixes[i], fixes[i + 1]
        if a is not None and b is not None:
            true_nm, bearing_deg = distance_and_bearing(a, b)
            if true_nm < _EPSILON_NM:
                bearing_deg = (
                    edge_bearing_deg[-1]
                    if edge_bearing_deg
                    else _course_bearing(legs[i + 1], airport, None, runway)
                )
        else:
            leg_b = legs[i + 1]
            true_nm = leg_b.distance_nm if leg_b.distance_nm is not None else NOMINAL_LEG_NM
            previous = edge_bearing_deg[-1] if edge_bearing_deg else None
            bearing_deg = _course_bearing(leg_b, airport, previous, runway)
        edge_true_nm.append(true_nm)
        edge_bearing_deg.append(bearing_deg)

    # --- compression: cap geodesic edges past LONG_FACTOR x their own median ---------
    is_geodesic_edge = [fixes[i] is not None and fixes[i + 1] is not None for i in range(n - 1)]
    nonzero_geodesic = [
        edge_true_nm[i]
        for i in range(n - 1)
        if is_geodesic_edge[i] and edge_true_nm[i] > _EPSILON_NM
    ]
    cap_nm = (
        LONG_FACTOR * median(nonzero_geodesic)
        if len(nonzero_geodesic) >= _MIN_SEGMENTS_FOR_COMPRESSION
        else math.inf
    )

    edge_drawn_nm: list[float] = []
    edge_scale: list[LayoutScale] = []
    for i in range(n - 1):
        this_cap = cap_nm if is_geodesic_edge[i] else NOMINAL_LEG_NM
        drawn_nm = min(edge_true_nm[i], this_cap)
        edge_drawn_nm.append(drawn_nm)
        edge_scale.append("compressed" if edge_true_nm[i] > this_cap + _EPSILON_NM else "to_scale")

    # --- anchor: a leg's own runway fix, else a supplied Runway, else the last fix ----
    runway_index = next((i for i in range(n) if is_runway_leg[i]), None)
    positioned_indices = [i for i in range(n) if fixes[i] is not None]

    xy: list[tuple[float, float]] = [(0.0, 0.0)] * n
    if runway_index is not None:
        anchor: str = "runway"
        origin_index = runway_index
        xy[origin_index] = (0.0, 0.0)
        for i in range(origin_index, n - 1):
            dx, dy = _vector(edge_bearing_deg[i], edge_drawn_nm[i])
            xy[i + 1] = (xy[i][0] + dx, xy[i][1] + dy)
        for i in range(origin_index - 1, -1, -1):
            dx, dy = _vector(edge_bearing_deg[i], edge_drawn_nm[i])
            xy[i] = (xy[i + 1][0] - dx, xy[i + 1][1] - dy)
        runway_position = fixes[origin_index]
        assert runway_position is not None
    elif runway is not None:
        anchor = "runway"
        # (0, 0) is the threshold itself — not a node. Leg 0 is walked outward from it.
        if fixes[0] is not None:
            first_true_nm, first_bearing_deg = distance_and_bearing(runway.threshold, fixes[0])
        else:
            first_true_nm = (
                legs[0].distance_nm if legs[0].distance_nm is not None else NOMINAL_LEG_NM
            )
            first_bearing_deg = _course_bearing(legs[0], airport, None, runway)
        first_cap = cap_nm if fixes[0] is not None else NOMINAL_LEG_NM
        first_drawn_nm = min(first_true_nm, first_cap)
        dx, dy = _vector(first_bearing_deg, first_drawn_nm)
        xy[0] = (dx, dy)
        for i in range(n - 1):
            dx, dy = _vector(edge_bearing_deg[i], edge_drawn_nm[i])
            xy[i + 1] = (xy[i][0] + dx, xy[i][1] + dy)
        runway_position = runway.threshold
    else:
        anchor = "last_fix"
        origin_index = positioned_indices[-1] if positioned_indices else n - 1
        xy[origin_index] = (0.0, 0.0)
        for i in range(origin_index, n - 1):
            dx, dy = _vector(edge_bearing_deg[i], edge_drawn_nm[i])
            xy[i + 1] = (xy[i][0] + dx, xy[i][1] + dy)
        for i in range(origin_index - 1, -1, -1):
            dx, dy = _vector(edge_bearing_deg[i], edge_drawn_nm[i])
            xy[i] = (xy[i + 1][0] - dx, xy[i + 1][1] - dy)
        runway_position = None

    # --- the airport's own drawn position --------------------------------------------
    if runway_position is not None:
        true_nm, bearing_deg = distance_and_bearing(runway_position, airport.position)
        dx, dy = _vector(bearing_deg, true_nm)  # a real airport sits close enough that this
        origin_xy = (0.0, 0.0)  # short hop is never worth compressing.
        airport_x_nm, airport_y_nm = origin_xy[0] + dx, origin_xy[1] + dy
    else:
        last_position = fixes[origin_index]
        if last_position is not None:
            true_nm, bearing_deg = distance_and_bearing(last_position, airport.position)
        else:
            true_nm, bearing_deg = 0.0, _course_bearing(legs[origin_index], airport, None, runway)
        drawn_nm = min(true_nm, cap_nm)
        dx, dy = _vector(bearing_deg, drawn_nm)
        airport_x_nm, airport_y_nm = xy[origin_index][0] + dx, xy[origin_index][1] + dy

    # --- altitude: published, runway, or interpolated between the nearest known ------
    known_altitudes = [_altitude(legs[i], is_runway_leg[i]) for i in range(n)]
    cumulative_true_nm = [0.0] * n
    for i in range(1, n):
        cumulative_true_nm[i] = cumulative_true_nm[i - 1] + edge_true_nm[i - 1]
    altitudes = _interpolate_altitudes(known_altitudes, cumulative_true_nm, airport.elevation_ft)

    nodes = tuple(
        LayoutNode(
            sequence=legs[i].sequence,
            ident=_leg_ident(legs[i]),
            x_nm=xy[i][0],
            y_nm=xy[i][1],
            altitude_ft=altitudes[i][0],
            altitude_source=altitudes[i][1],
            positioned=fixes[i] is not None,
            is_positionable=legs[i].is_positionable,
            is_missed_approach=legs[i].is_missed_approach_leg or legs[i].is_missed_approach_point,
            is_runway=is_runway_leg[i],
        )
        for i in range(n)
    )
    segments = tuple(
        LayoutSegment(
            from_sequence=legs[i].sequence,
            to_sequence=legs[i + 1].sequence,
            true_length_nm=edge_true_nm[i],
            drawn_length_nm=edge_drawn_nm[i],
            scale=edge_scale[i],
            bearing_deg=edge_bearing_deg[i] % 360.0,
        )
        for i in range(n - 1)
    )

    return ProcedureLayout(
        airport_icao=procedure.airport_icao,
        kind=procedure.kind,
        ident=procedure.ident,
        transition=procedure.transition,
        approach_type=procedure.approach_type,
        anchor=anchor,  # type: ignore[arg-type]
        airport_x_nm=airport_x_nm,
        airport_y_nm=airport_y_nm,
        airport_elevation_ft=airport.elevation_ft,
        nodes=nodes,
        segments=segments,
        total_true_length_nm=sum(edge_true_nm),
        compressed_segment_count=sum(1 for scale in edge_scale if scale == "compressed"),
    )
