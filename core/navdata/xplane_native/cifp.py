"""The CIFP procedure parser: one airport's SIDs, STARs, approaches and runways.

``CIFP/<ICAO>.dat`` is X-Plane's ARINC 424 subset. One file per airport, ~7 KB,
about 15 000 of them — which is why it is parsed **lazily**, per airport, and
never indexed up front (design §7.1).

Two things about this module are deliberate and load-bearing:

**Fix resolution is injected, never imported.** A leg names its fix with the
4-part ARINC key :class:`~core.navdata.models.FixRef`, and turning that key into
a coordinate needs the whole navaid/fix index. Taking a
:data:`~core.navdata.cifp_source.FixResolver` callable instead of importing the
index keeps this file free of SQLite, keeps it testable against a handful of
hand-built waypoints, and keeps the two parallel tracks of Phase 1 from having
to land together.

**A malformed record is skipped and counted, never fatal.** Real navdata always
contains a few bad rows, and an instructor station that refuses to load an
airport because one leg has a truncated record is useless (design §4.6). The
count rides on :attr:`~core.navdata.cifp_source.CifpAirport.skipped_record_count`
so the caller can surface it.

Nothing here touches a simulator, and nothing here writes: every file is opened
read-only from the user's own installation.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Final, Literal, cast

from core.models import GeoPosition
from core.navdata.cifp_source import CifpAirport, CifpRunway, FixResolver
from core.navdata.models import (
    MANOEUVRE_TERMINATORS,
    POSITIONABLE_TERMINATORS,
    TRAJECTORY_TERMINATORS,
    AltitudeConstraint,
    ApproachType,
    FixRef,
    PathTerminator,
    Procedure,
    ProcedureKind,
    ProcedureLeg,
    SpeedConstraint,
    Waypoint,
)
from core.navdata.normalize import expand_runway_transition, normalize_icao, normalize_runway_ident
from core.navdata.sources import cifp_file

__all__ = [
    "XPNativeCifpSource",
    "decode_latitude",
    "decode_longitude",
    "parse_cifp",
]

TurnDirection = Literal["L", "R"]


# ---------------------------------------------------------------------------
# Record layout
# ---------------------------------------------------------------------------

#: The record prefixes this parser reads. Any other prefix — ``PRDAT:`` and
#: friends — is a record type the project does not use and is skipped **without**
#: counting: it is not malformed, it is simply not ours.
_RECORD_KINDS: Final[dict[str, ProcedureKind]] = {
    "SID": "sid",
    "STAR": "star",
    "APPCH": "approach",
}

#: ``SID``/``STAR``/``APPCH`` records carry 38 comma-separated fields. Only the
#: first 29 mean anything to this design (§6.6), so a record is accepted as soon
#: as it has those: a cycle that grows a 39th field, or trims an unused trailing
#: one, still parses. Fewer than 29 is a truncated record and is counted.
_MIN_PROCEDURE_FIELDS: Final = 29

# Field indices, from the verified map in design §6.6. Field 0 is the sequence
# number, because the record's ``TYPE:`` prefix is split off before the commas.
_F_SEQUENCE: Final = 0
_F_ROUTE_TYPE: Final = 1
_F_PROCEDURE_IDENT: Final = 2
_F_TRANSITION: Final = 3
_F_FIX: Final = 4  # ident / region / section / subsection at 4, 5, 6, 7
_F_DESCRIPTION_CODE: Final = 8
_F_TURN_DIRECTION: Final = 9
_F_PATH_TERMINATOR: Final = 11
_F_NAVAID: Final = 13  # ident / region / section / subsection at 13, 14, 15, 16
_F_ARC_RADIUS: Final = 17
_F_THETA: Final = 18
_F_RHO: Final = 19
_F_OUTBOUND_COURSE: Final = 20
_F_ROUTE_DISTANCE: Final = 21
_F_ALTITUDE_DESCRIPTOR: Final = 22
_F_ALTITUDE_1: Final = 23
_F_ALTITUDE_2: Final = 24
_F_TRANSITION_ALTITUDE: Final = 25
_F_SPEED_DESCRIPTOR: Final = 26
_F_SPEED_LIMIT: Final = 27
_F_VERTICAL_ANGLE: Final = 28

#: Every terminator the models recognise. One that is not here cannot be typed
#: as a :data:`~core.navdata.models.PathTerminator`, so the record is malformed.
_ALL_TERMINATORS: Final[frozenset[str]] = (
    POSITIONABLE_TERMINATORS | TRAJECTORY_TERMINATORS | MANOEUVRE_TERMINATORS
)

#: ARINC 424 approach route type (field 1) to the vocabulary in
#: :data:`~core.navdata.models.ApproachType`. Anything not listed — a TACAN
#: approach, a code a future cycle invents — reads as ``"unknown"`` rather than
#: failing the record: an approach an instructor can still fly, merely labelled
#: conservatively, beats an airport that will not load.
_APPROACH_ROUTE_TYPES: Final[dict[str, ApproachType]] = {
    "B": "loc",  # localizer back course
    "D": "vor_dme",
    "F": "rnav",  # FMS
    "G": "igs",
    "H": "rnav",  # RNP AR
    "I": "ils",
    "J": "gls",
    "L": "loc",
    "M": "mls",
    "N": "ndb",
    "P": "gps",
    "Q": "ndb_dme",
    "R": "rnav",
    "S": "vor",
    "U": "sdf",
    "V": "vor",
    "W": "mls",
    "X": "lda",
    "Y": "mls",
}

# The 4-character waypoint description code (field 8), by column. Columns are
# significant by position, so the code is padded rather than stripped — a
# missed-approach leg is spelled "   M" and stripping it loses the flag.
_DESCRIPTION_FLYOVER: Final = 1
_DESCRIPTION_FIX_ROLE: Final = 2
_DESCRIPTION_LEG_ROLE: Final = 3

_FLYOVER_CODES: Final[frozenset[str]] = frozenset({"B", "Y"})
_INITIAL_APPROACH_FIX_CODES: Final[frozenset[str]] = frozenset({"A", "C", "D"})
_FINAL_APPROACH_FIX_CODES: Final[frozenset[str]] = frozenset({"F"})
_MISSED_APPROACH_POINT_CODES: Final[frozenset[str]] = frozenset({"M"})
_MISSED_APPROACH_LEG_CODE: Final = "M"
_END_OF_PROCEDURE_CODE: Final = "E"

# Altitude descriptors (field 22). Everything not listed — blank, and the
# glideslope variants G/H/I/J — means "at altitude 1" (design §5.9).
_AT_OR_ABOVE_DESCRIPTORS: Final[frozenset[str]] = frozenset({"+", "V"})
_AT_OR_BELOW_DESCRIPTORS: Final[frozenset[str]] = frozenset({"-"})
_BETWEEN_DESCRIPTORS: Final[frozenset[str]] = frozenset({"B"})
_AT_OR_ABOVE_ALTITUDE_2_DESCRIPTORS: Final[frozenset[str]] = frozenset({"C"})

_METRES_PER_FOOT: Final = 0.3048
_TENTHS: Final = 10.0
_HUNDREDTHS: Final = 100.0
_THOUSANDTHS: Final = 1000.0
_FEET_PER_FLIGHT_LEVEL: Final = 100

_LATITUDE = re.compile(r"^([NS])(\d{2})(\d{2})(\d{2})(\d{2})$")
_LONGITUDE = re.compile(r"^([EW])(\d{3})(\d{2})(\d{2})(\d{2})$")

# ``RWY:`` field offsets, measured from the LATITUDE field rather than from the
# start of the record — see `_parse_runway_record` for why the coordinate is the
# anchor. Verified against 48 records at LEMD, KJFK, EGLL, KSEA, LEBL and KORD;
# the layout is now written into design §6.6 so it need never be rediscovered.
_RWY_ELEVATION_OFFSET: Final = -4
_RWY_LOCALIZER_OFFSET: Final = -2
_RWY_ILS_CATEGORY_OFFSET: Final = -1
_RWY_LONGITUDE_OFFSET: Final = 1
_RWY_DISPLACED_THRESHOLD_OFFSET: Final = 2

#: The runway an approach serves is encoded in its own ident — ``I32L`` is the
#: ILS to 32L — because the CIFP transition field is blank for the final segment.
#: A circling approach (``VOR-A``) has no digits and therefore no runway.
_APPROACH_IDENT_RUNWAY = re.compile(r"^[A-Z](\d{2})([LRC]?)")


# ---------------------------------------------------------------------------
# Coordinate decoding
# ---------------------------------------------------------------------------


def decode_latitude(value: str) -> float | None:
    """Decode a packed ``[NS]DDMMSSss`` latitude to signed decimal degrees.

    The last two digits are **hundredths of a second**, not thousandths — the
    single most expensive thing to get wrong in this file, because a factor of
    ten on the fractional second yields a plausible-looking coordinate a few
    metres from the right one.

    Returns:
        Decimal degrees, or ``None`` for anything that is not exactly nine
        characters in that shape — blanks included.
    """
    return _decode_packed(_LATITUDE, value, negative_hemisphere="S")


def decode_longitude(value: str) -> float | None:
    """Decode a packed ``[EW]DDDMMSSss`` longitude to signed decimal degrees.

    Ten characters, not nine: the degrees field carries three digits, so that
    ``E151101200`` reads as 151° 10' 12.00" and not as 15° 11' 01.20".
    """
    return _decode_packed(_LONGITUDE, value, negative_hemisphere="W")


def _decode_packed(
    pattern: re.Pattern[str], value: str, *, negative_hemisphere: str
) -> float | None:
    match = pattern.match(value.strip().upper())
    if match is None:
        return None
    hemisphere, degrees, minutes, seconds, hundredths = match.groups()
    arcseconds = int(seconds) + int(hundredths) / 100.0
    magnitude = int(degrees) + int(minutes) / 60.0 + arcseconds / 3600.0
    if magnitude > 180.0:
        # A degrees field the ellipsoid cannot hold. Unreadable is the honest
        # verdict; clamping would produce something that looks like a position.
        return None
    return -magnitude if hemisphere == negative_hemisphere else magnitude


# ---------------------------------------------------------------------------
# The public entry point
# ---------------------------------------------------------------------------


def parse_cifp(
    text: str,
    *,
    icao: str,
    resolve_fix: FixResolver | None = None,
) -> CifpAirport:
    """Parse one ``CIFP/<ICAO>.dat`` file.

    Args:
        text: The file's contents.
        icao: The airport the file belongs to. It scopes every terminal fix
            reference, so it comes from the filename rather than from the
            records, which do not repeat it.
        resolve_fix: Turns a leg's 4-part ARINC key into a coordinate. When it
            is ``None`` nothing resolves: every leg reads as unpositionable with
            a reason naming its fix, and the procedures are still returned —
            which is exactly what an instructor should see while the index is
            still building.

    Returns:
        Everything the file has to say. **Never raises on bad content**: a record
        that cannot be read is skipped and counted.
    """
    resolver = resolve_fix if resolve_fix is not None else _resolves_nothing
    airport_icao = normalize_icao(icao)

    runways: list[CifpRunway] = []
    builders: OrderedDict[tuple[ProcedureKind, str, str], _ProcedureBuilder] = OrderedDict()
    skipped = 0

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        prefix, separator, body = line.partition(":")
        if not separator:
            continue
        record_type = prefix.strip().upper()
        fields = body.rstrip().removesuffix(";").split(",")

        if record_type == "RWY":
            runway = _parse_runway_record(fields)
            if runway is None:
                skipped += 1
            else:
                runways.append(runway)
            continue

        kind = _RECORD_KINDS.get(record_type)
        if kind is None:
            continue

        parsed = _parse_procedure_record(kind, fields, line, airport_icao, resolver)
        if parsed is None:
            skipped += 1
            continue

        key, route_type, leg = parsed
        builder = builders.get(key)
        if builder is None:
            builder = _ProcedureBuilder(
                kind=key[0], ident=key[1], transition=key[2], route_type=route_type
            )
            builders[key] = builder
        builder.legs.append(leg)

    runway_idents = [runway.ident for runway in runways]
    procedures = tuple(builder.build(airport_icao, runway_idents) for builder in builders.values())

    return CifpAirport(
        icao=airport_icao,
        runways=tuple(runways),
        procedures=procedures,
        skipped_record_count=skipped,
    )


# ---------------------------------------------------------------------------
# RWY: records
# ---------------------------------------------------------------------------


def _parse_runway_record(fields: Sequence[str]) -> CifpRunway | None:
    """Decode one ``RWY:`` record, or ``None`` when it is unreadable.

    The layout is ten comma-separated fields **with a semicolon buried inside
    field 7** — the record's own terminator character, reused mid-record as the
    separator between the threshold crossing height and the latitude::

        RWY:RW18L,     ,      ,01922, ,IML ,3,   ;N40314122,W003333368,1640;
             0      1     2     3    4   5   6      7            8       9

        0  runway ident            5  localizer ident
        1  runway gradient         6  ILS category
        2  ellipsoidal height      7  threshold crossing height ";" LATITUDE
        3  threshold elevation     8  longitude
        4  (blank)                 9  displaced threshold distance, FEET

    Verified against 48 records at LEMD, KJFK, EGLL, KSEA, LEBL and KORD, and
    recorded in design §6.6. **The embedded semicolon is the trap**: splitting on
    commas and then matching a bare ``[NS]DDMMSSss`` against field 7 never
    matches, so a parser that misses it silently reads *no* runways from *every*
    real airport — and the CIFP threshold then loses the §7.2 precedence duel to
    ``apt.dat`` by default, which is exactly the invisible offset between a
    placement and its procedure that §7.2 exists to prevent.

    The read is anchored on the **latitude** rather than done from fixed indices.
    The coordinate pair is unmistakable by shape, so anchoring survives a record
    that gains or loses a leading column, and every other field is then taken at
    its verified offset from it.

    A record with no coordinate pair carries no threshold, which is the one thing
    this record type exists to provide, so it counts as malformed.
    """
    if not fields:
        return None

    ident = normalize_runway_ident(fields[0])
    if not ident or len(ident) > 3:
        return None

    anchor = _find_coordinate_pair(fields)
    if anchor is None:
        return None

    latitude = decode_latitude(_after_semicolon(fields[anchor]))
    longitude = decode_longitude(_at(fields, anchor + _RWY_LONGITUDE_OFFSET))
    if latitude is None or longitude is None:  # pragma: no cover - the anchor guarantees both
        return None

    elevation_ft = _parse_float(_at(fields, anchor + _RWY_ELEVATION_OFFSET))
    displaced_ft = _parse_float(_at(fields, anchor + _RWY_DISPLACED_THRESHOLD_OFFSET))
    crossing_height_ft = _parse_float(_before_semicolon(fields[anchor]))

    return CifpRunway(
        ident=ident,
        threshold=GeoPosition(
            latitude=latitude,
            longitude=longitude,
            altitude_ft=0.0 if elevation_ft is None else elevation_ft,
        ),
        elevation_ft=elevation_ft,
        # The source publishes the displacement in FEET and the model carries it
        # in metres — the unit change is the whole reason this line exists.
        displaced_threshold_m=(
            None if displaced_ft is None or displaced_ft < 0 else displaced_ft * _METRES_PER_FOOT
        ),
        threshold_crossing_height_ft=(
            None if crossing_height_ft is None or crossing_height_ft < 0 else crossing_height_ft
        ),
        localizer_ident=_at(fields, anchor + _RWY_LOCALIZER_OFFSET).strip() or None,
        # Carried raw. Only 1/2/3 are CAT I/II/III and real data also holds
        # blanks and letter codes for LDA, IGS and localizer-only installations;
        # mapping them here would turn one odd airport into a failed parse.
        ils_category=_at(fields, anchor + _RWY_ILS_CATEGORY_OFFSET).strip() or None,
    )


def _after_semicolon(value: str) -> str:
    """The part of a ``RWY:`` field following an embedded ``;``, or all of it."""
    return value.rpartition(";")[2]


def _before_semicolon(value: str) -> str:
    """The part preceding an embedded ``;``, or nothing when there is none."""
    head, separator, _ = value.partition(";")
    return head if separator else ""


def _find_coordinate_pair(fields: Sequence[str]) -> int | None:
    """Index of the field holding the latitude, given the next one is the longitude.

    The latitude is preceded in its own field by the threshold crossing height
    and a semicolon, so the match is made on the tail of the field rather than
    on the whole of it.
    """
    for index in range(len(fields) - 1):
        latitude = _after_semicolon(fields[index]).strip().upper()
        longitude = fields[index + 1].strip().upper()
        if _LATITUDE.match(latitude) and _LONGITUDE.match(longitude):
            return index
    return None


# ---------------------------------------------------------------------------
# SID: / STAR: / APPCH: records
# ---------------------------------------------------------------------------


@dataclass
class _ProcedureBuilder:
    """Legs accumulating under one ``(kind, ident, transition)`` key."""

    kind: ProcedureKind
    ident: str
    transition: str
    route_type: str
    legs: list[ProcedureLeg] = field(default_factory=list)

    def build(self, airport_icao: str, airport_runways: Sequence[str]) -> Procedure:
        if self.kind == "approach":
            # An approach's runway is in its own ident (``I32L``), not in the
            # transition field, which is blank for the final segment. Expanding
            # that blank instead would claim the ILS 32L serves every runway on
            # the field.
            runway_idents = _approach_runway_idents(self.ident, airport_runways)
            approach_type: ApproachType | None = _APPROACH_ROUTE_TYPES.get(
                self.route_type.strip().upper(), "unknown"
            )
        else:
            runway_idents = expand_runway_transition(self.transition, airport_runways)
            approach_type = None

        transition = self.transition.strip().upper()
        return Procedure(
            airport_icao=airport_icao,
            kind=self.kind,
            ident=self.ident,
            # The transition keeps the ident the source published — "RW14R",
            # "ADUXO" — while ``runway_idents`` carries its expansion. Blank and
            # "ALL" are the common route and name nothing.
            transition=None if transition in {"", "ALL"} else transition,
            runway_idents=runway_idents,
            approach_type=approach_type,
            legs=tuple(self.legs),
        )


def _parse_procedure_record(
    kind: ProcedureKind,
    fields: Sequence[str],
    raw: str,
    airport_icao: str,
    resolver: FixResolver,
) -> tuple[tuple[ProcedureKind, str, str], str, ProcedureLeg] | None:
    """Decode one procedure record into its grouping key, route type and leg."""
    if len(fields) < _MIN_PROCEDURE_FIELDS:
        return None

    sequence = _parse_int(fields[_F_SEQUENCE])
    procedure_ident = fields[_F_PROCEDURE_IDENT].strip().upper()
    terminator_text = fields[_F_PATH_TERMINATOR].strip().upper()
    if sequence is None or not procedure_ident or terminator_text not in _ALL_TERMINATORS:
        return None
    terminator = cast("PathTerminator", terminator_text)

    fix_ref = _build_fix_ref(fields, _F_FIX, airport_icao)
    fix = resolver(fix_ref) if fix_ref is not None else None
    navaid_ref = _build_fix_ref(fields, _F_NAVAID, airport_icao)
    navaid = resolver(navaid_ref) if navaid_ref is not None else None

    # BOTH conditions. A CA leg has no defensible coordinate at all; an IF leg
    # whose fix is missing from the index has one that could not be looked up.
    is_positionable = terminator in POSITIONABLE_TERMINATORS and fix is not None

    distance_nm, time_min = _parse_distance_or_time(fields[_F_ROUTE_DISTANCE])
    code = fields[_F_DESCRIPTION_CODE].ljust(4)

    try:
        leg = ProcedureLeg(
            sequence=sequence,
            path_terminator=terminator,
            is_positionable=is_positionable,
            unpositionable_reason=(
                None if is_positionable else _unpositionable_reason(terminator, fix_ref)
            ),
            fix_ref=fix_ref,
            fix=fix,
            recommended_navaid=navaid,
            theta_mag_deg=_parse_angle(fields[_F_THETA]),
            rho_nm=_non_negative(_parse_tenths(fields[_F_RHO])),
            # Three implied decimals, not one: ``002100`` is a 2.100 NM RF turn.
            # Read as tenths it becomes a 210 NM arc, which is not a turn at all.
            arc_radius_nm=_positive(_parse_thousandths(fields[_F_ARC_RADIUS])),
            outbound_course_mag_deg=_parse_angle(fields[_F_OUTBOUND_COURSE]),
            distance_nm=distance_nm,
            time_min=time_min,
            turn_direction=_parse_turn_direction(fields[_F_TURN_DIRECTION]),
            # ``-343`` is -3.43°: hundredths of a degree, and negative on every
            # descent, so the sign is carried rather than normalised away.
            vertical_angle_deg=_non_zero(_parse_hundredths(fields[_F_VERTICAL_ANGLE])),
            altitude=_parse_altitude_constraint(
                fields[_F_ALTITUDE_DESCRIPTOR], fields[_F_ALTITUDE_1], fields[_F_ALTITUDE_2]
            ),
            speed=_parse_speed_constraint(fields[_F_SPEED_DESCRIPTOR], fields[_F_SPEED_LIMIT]),
            transition_altitude_ft=_parse_int(fields[_F_TRANSITION_ALTITUDE]),
            is_flyover=code[_DESCRIPTION_FLYOVER] in _FLYOVER_CODES,
            is_initial_approach_fix=code[_DESCRIPTION_FIX_ROLE] in _INITIAL_APPROACH_FIX_CODES,
            is_final_approach_fix=code[_DESCRIPTION_FIX_ROLE] in _FINAL_APPROACH_FIX_CODES,
            is_missed_approach_point=code[_DESCRIPTION_FIX_ROLE] in _MISSED_APPROACH_POINT_CODES,
            is_missed_approach_leg=code[_DESCRIPTION_LEG_ROLE] == _MISSED_APPROACH_LEG_CODE,
            is_end_of_procedure=code[_DESCRIPTION_LEG_ROLE] == _END_OF_PROCEDURE_CODE,
            raw=raw,
        )
    except ValueError:
        # The last net under the per-field sanitising above. A record that still
        # fails model validation is malformed, and one bad leg must never cost
        # the instructor the other thirty.
        return None

    key = (kind, procedure_ident, fields[_F_TRANSITION].strip().upper())
    return key, fields[_F_ROUTE_TYPE], leg


def _unpositionable_reason(terminator: str, fix_ref: FixRef | None) -> str:
    """Why this leg is not offered as a placement, in the words the UI shows verbatim.

    The two cases are genuinely different and confusing them would be a silent
    bug: a ``CA`` leg has no defensible coordinate at all, whereas an ``IF`` leg
    whose fix is missing from the index has one that simply could not be looked
    up (design §5.7).
    """
    if terminator not in POSITIONABLE_TERMINATORS:
        return f"trajectory-dependent leg ({terminator}): no coordinate without the flown path"
    if fix_ref is None:
        return f"leg carries a {terminator} terminator but names no fix"
    return f"fix {fix_ref.ident}/{fix_ref.region_code} not found in the index"


def _approach_runway_idents(ident: str, airport_runways: Sequence[str]) -> tuple[str, ...]:
    """The runways an approach serves, read out of its own ident.

    ``I32L`` is the ILS to 32L; ``R18-Z`` is an RNAV to 18; ``VOR-A`` is a
    circling approach and serves no specific runway. The designator is expanded
    against the airport's real runway list for the same reason a transition is:
    ``D14`` at an airport that spells it ``14L``/``14R`` means both.
    """
    match = _APPROACH_IDENT_RUNWAY.match(ident.strip().upper())
    if match is None:
        return ()
    number, designator = match.groups()
    return expand_runway_transition(f"RW{number}{designator}", airport_runways)


def _build_fix_ref(fields: Sequence[str], base: int, airport_icao: str) -> FixRef | None:
    """The 4-part ARINC key at ``base`` … ``base + 3``, or ``None`` when unnamed."""
    ident = _at(fields, base).strip().upper()
    if not ident:
        return None
    return FixRef(
        ident=ident,
        region_code=_at(fields, base + 1).strip().upper(),
        section=_at(fields, base + 2).strip().upper(),
        subsection=_at(fields, base + 3).strip().upper(),
        airport_icao=airport_icao,
    )


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------


def _parse_altitude_constraint(
    descriptor_text: str, altitude_1: str, altitude_2: str
) -> AltitudeConstraint | None:
    """Decode ``descriptor, altitude 1, altitude 2`` into a constraint.

    Flight levels are normalised to feet with a flag, so the conversion happens
    once here rather than in every consumer while the UI can still render the
    published ``FL140``.
    """
    descriptor = descriptor_text.strip().upper()
    first = _parse_altitude(altitude_1)
    second = _parse_altitude(altitude_2)

    min_ft: float | None = None
    max_ft: float | None = None
    min_is_level = False
    max_is_level = False

    if descriptor in _BETWEEN_DESCRIPTORS:
        # "B" publishes the ceiling in altitude 1 and the floor in altitude 2.
        if first is not None:
            max_ft, max_is_level = first
        if second is not None:
            min_ft, min_is_level = second
    elif descriptor in _AT_OR_ABOVE_DESCRIPTORS:
        if first is not None:
            min_ft, min_is_level = first
    elif descriptor in _AT_OR_BELOW_DESCRIPTORS:
        if first is not None:
            max_ft, max_is_level = first
    elif descriptor in _AT_OR_ABOVE_ALTITUDE_2_DESCRIPTORS:
        if second is not None:
            min_ft, min_is_level = second
    elif first is not None:
        # Blank, and the glideslope descriptors G/H/I/J: "at altitude 1".
        min_ft, min_is_level = first
        max_ft, max_is_level = first

    if min_ft is None and max_ft is None:
        return None
    return AltitudeConstraint(
        descriptor=descriptor,
        min_ft=min_ft,
        max_ft=max_ft,
        min_is_flight_level=min_is_level,
        max_is_flight_level=max_is_level,
    )


def _parse_altitude(value: str) -> tuple[float, bool] | None:
    """One altitude bound: feet, and whether it was published as a flight level."""
    text = value.strip().upper()
    if not text:
        return None
    if text.startswith("FL"):
        digits = text[2:]
        if not digits.isdigit():
            return None
        return float(int(digits) * _FEET_PER_FLIGHT_LEVEL), True
    number = _parse_float(text)
    return None if number is None else (number, False)


def _parse_speed_constraint(descriptor_text: str, limit_text: str) -> SpeedConstraint | None:
    """Decode ``descriptor, speed limit``.

    A blank descriptor is a **ceiling**, not a target: an ARINC speed limit is
    published as "do not exceed" unless the record says otherwise, and reading
    it as a floor would have the Position Manager place an aircraft at the one
    speed the procedure forbids exceeding.
    """
    limit = _parse_float(limit_text)
    if limit is None or limit < 0:
        return None
    descriptor = descriptor_text.strip()
    if descriptor == "+":
        return SpeedConstraint(descriptor=descriptor, min_kt=limit)
    return SpeedConstraint(descriptor=descriptor, max_kt=limit)


# ---------------------------------------------------------------------------
# Scalar field helpers
# ---------------------------------------------------------------------------


def _at(fields: Sequence[str], index: int) -> str:
    """``fields[index]``, or an empty string when the record is shorter."""
    return fields[index] if 0 <= index < len(fields) else ""


def _parse_float(value: str) -> float | None:
    """A plain numeric field, or ``None`` for blanks and anything unreadable."""
    text = value.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_int(value: str) -> int | None:
    number = _parse_float(value)
    return None if number is None else int(number)


def _parse_tenths(value: str) -> float | None:
    """A fixed-point field with one implied decimal: ``0138`` is 13.8."""
    number = _parse_float(value)
    return None if number is None else number / _TENTHS


def _parse_hundredths(value: str) -> float | None:
    """A fixed-point field with two implied decimals: ``-343`` is -3.43."""
    number = _parse_float(value)
    return None if number is None else number / _HUNDREDTHS


def _parse_thousandths(value: str) -> float | None:
    """A fixed-point field with three implied decimals: ``002100`` is 2.100."""
    number = _parse_float(value)
    return None if number is None else number / _THOUSANDTHS


def _parse_angle(value: str) -> float | None:
    """A course or bearing in tenths of a degree: ``3247`` is 324.7°.

    Anything outside ``[0, 360]`` is dropped rather than wrapped. A course that
    does not fit the circle is a misread field, and inventing a plausible angle
    from it is worse than admitting the leg has none.
    """
    angle = _parse_tenths(value)
    if angle is None:
        return None
    return angle if 0.0 <= angle <= 360.0 else None


def _non_negative(value: float | None) -> float | None:
    return None if value is None or value < 0.0 else value


def _positive(value: float | None) -> float | None:
    return None if value is None or value <= 0.0 else value


def _non_zero(value: float | None) -> float | None:
    """A published zero in an optional field means "not applicable"."""
    return None if value is None or value == 0.0 else value


def _parse_distance_or_time(value: str) -> tuple[float | None, float | None]:
    """Field 21 is a route distance **or** a holding time — ``T010`` is 1.0 minute."""
    text = value.strip().upper()
    if not text:
        return None, None
    if text.startswith("T"):
        return None, _positive(_parse_tenths(text[1:]))
    return _non_negative(_parse_tenths(text)), None


def _parse_turn_direction(value: str) -> TurnDirection | None:
    turn = value.strip().upper()
    return cast("TurnDirection", turn) if turn in {"L", "R"} else None


def _resolves_nothing(ref: FixRef) -> Waypoint | None:
    """The default resolver: nothing resolves, so no leg is positionable."""
    return None


# ---------------------------------------------------------------------------
# The lazy, cached source
# ---------------------------------------------------------------------------

#: An instructor session touches perhaps five airports; 64 parsed files are a
#: few megabytes and are never all needed at once.
_DEFAULT_CACHE_SIZE: Final = 64


class XPNativeCifpSource:
    """A :class:`~core.navdata.cifp_source.CifpSource` over an X-Plane data tree.

    **The cache lives on the instance, keyed by ``(icao, resolved path, mtime)``
    — and both of the obvious alternatives are wrong** (design §7.2):

    * A module-level ``@lru_cache`` keyed on the ICAO alone is global state keyed
      by the wrong thing. Two sources over two different data trees are alive in
      one process during the contract suite, and the second would be served the
      first one's parse of a *different file*, with no error anywhere.
    * ``@lru_cache`` on a method keeps ``self`` in the key, pinning every source
      ever constructed for the lifetime of the process.

    Keying on the resolved path additionally makes the cache self-invalidating:
    that path is the one that won per-file precedence, so a navdata update which
    moves an airport from ``Resources/default data/`` to ``Custom Data/`` — or
    which merely rewrites its file — changes the key on its own.
    """

    def __init__(
        self,
        root: Path,
        *,
        resolve_fix: FixResolver | None = None,
        max_entries: int = _DEFAULT_CACHE_SIZE,
    ) -> None:
        """Construct the source. **Performs no I/O**, in keeping with the provider rule."""
        self._root = root
        self._resolve_fix = resolve_fix
        self._max_entries = max(1, max_entries)
        self._lock = Lock()
        self._cache: OrderedDict[tuple[str, str, int], CifpAirport] = OrderedDict()

    @property
    def root(self) -> Path:
        """The installation this source reads from."""
        return self._root

    def load(self, icao: str) -> CifpAirport | None:
        """Parse one airport's procedures, or ``None`` when it has no CIFP file.

        Precedence is resolved on **every** call rather than remembered once, so
        the ~1000 airports whose procedures live only in ``Resources/default
        data/`` are found, and an airport whose file appears in ``Custom Data/``
        after a navdata update is picked up without restarting anything.
        """
        airport_icao = normalize_icao(icao)
        path = cifp_file(self._root, airport_icao)
        if path is None:
            # A missing file is a normal outcome, not an error: every airport
            # has runways, only about half have published procedures.
            return None

        try:
            mtime_ns = path.stat().st_mtime_ns
        except OSError:
            return None

        key = (airport_icao, str(path), mtime_ns)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            # The file vanished or became unreadable between the stat and the
            # read. "No procedures" is the honest answer; it is not a crash.
            return None

        airport = parse_cifp(text, icao=airport_icao, resolve_fix=self._resolve_fix)

        with self._lock:
            self._cache[key] = airport
            self._cache.move_to_end(key)
            while len(self._cache) > self._max_entries:
                self._cache.popitem(last=False)
        return airport

    def invalidate(self) -> None:
        """Drop every cached parse. Called when the navdata cache key changes."""
        with self._lock:
            self._cache.clear()
