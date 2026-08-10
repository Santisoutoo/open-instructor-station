"""The navdata vocabulary: what the world looks like, in one place.

Units follow the rule of :mod:`core.models` — the unit is part of the field name
and is never ambiguous — with one addition that navdata forces and the rest of
the project does not need:

**Every directional field says which north it is measured from.** ``_true_deg``
or ``_mag_deg``, never a bare ``_deg``. CIFP courses are magnetic while
:mod:`core.geodesy` is true throughout, and magnetic-versus-true is the single
most common source of silently-wrong navigation values. **This module never
converts between the two**: converting needs a world magnetic model, which
``geographiclib`` has none of and which would cost more bundle size than it is
worth. Where the source publishes both, both are carried; where a true bearing
is needed and the source has none, it is computed geodesically from
coordinates.

This module imports from :mod:`core.models` and nothing in :mod:`core.models`
imports it back. That direction is one-way on purpose and is asserted by
``tests/core/navdata/test_core_boundaries.py``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from core.models import GeoPosition

__all__ = [
    "MANOEUVRE_TERMINATORS",
    "POSITIONABLE_TERMINATORS",
    "TRAJECTORY_TERMINATORS",
    "Airport",
    "AirportSummary",
    "AltitudeConstraint",
    "ApproachType",
    "Fix",
    "FixRef",
    "Hold",
    "IndexProgress",
    "Navaid",
    "NavaidKind",
    "NavdataState",
    "NavdataStatus",
    "ParkingKind",
    "ParkingOperation",
    "ParkingStand",
    "PathTerminator",
    "Procedure",
    "ProcedureKind",
    "ProcedureLeg",
    "ProcedureSummary",
    "SpeedConstraint",
    "TunableRadio",
    "Waypoint",
    "WaypointKind",
]


# ---------------------------------------------------------------------------
# Waypoints — the common anchor
# ---------------------------------------------------------------------------

WaypointKind = Literal["fix", "vor", "ndb", "dme", "tacan", "localizer", "runway", "airport", "gls"]


class Waypoint(BaseModel):
    """Anything positionable, reduced to what a placement needs.

    Procedure legs point at one of these and :meth:`NavdataProvider.resolve_fix`
    returns one, so the Position Manager consumes a single shape whether the
    anchor started life as a fix, a navaid, a runway threshold or an airport.
    """

    model_config = ConfigDict(frozen=True)

    ident: str = Field(min_length=1, description='Published identifier, e.g. "GOXOL".')
    kind: WaypointKind = Field(description="What kind of object this identifier names.")
    position: GeoPosition = Field(description="Where it is.")
    region_code: str | None = Field(
        default=None, description='ICAO region code, e.g. "LE". Idents are unique only within one.'
    )
    airport_icao: str | None = Field(
        default=None, description="Set for terminal-scoped waypoints; None for enroute ones."
    )
    name: str | None = Field(default=None, description="Plain-language name, when published.")


# ---------------------------------------------------------------------------
# Airports
# ---------------------------------------------------------------------------


class Airport(BaseModel):
    """One airport, as published by ``apt.dat``."""

    model_config = ConfigDict(frozen=True)

    icao: str = Field(min_length=2, max_length=7, description='ICAO code, e.g. "LEMD".')
    iata: str | None = Field(default=None, description='IATA code, e.g. "MAD".')
    name: str = Field(description="Published airport name.")
    city: str | None = None
    country: str | None = None
    region_code: str | None = Field(default=None, description='ICAO region code, e.g. "LE".')
    position: GeoPosition = Field(description="Airport reference point (the published datum).")
    elevation_ft: float = Field(description="Airport elevation, feet MSL.")
    transition_altitude_ft: int | None = Field(
        default=None, description="Published transition altitude, feet MSL."
    )
    transition_level_ft: int | None = Field(
        default=None, description="Published transition level, feet."
    )
    magnetic_variation_deg: float | None = Field(
        default=None, description="Published variation, degrees, positive east."
    )
    has_tower: bool = False
    runway_count: int = Field(default=0, ge=0)
    longest_runway_m: float | None = Field(default=None, gt=0.0)
    has_procedures: bool = Field(
        default=False,
        description=(
            "True when a CIFP file exists for this airport. Set from a directory listing, not "
            "from a parse, so the UI can disable the procedure tabs before any lazy load."
        ),
    )


class AirportSummary(BaseModel):
    """The subset of :class:`Airport` a list or a search result needs."""

    model_config = ConfigDict(frozen=True)

    icao: str = Field(min_length=2, max_length=7)
    iata: str | None = None
    name: str
    position: GeoPosition
    elevation_ft: float
    longest_runway_m: float | None = Field(default=None, gt=0.0)
    has_procedures: bool = False


# ---------------------------------------------------------------------------
# Navaids
# ---------------------------------------------------------------------------

NavaidKind = Literal[
    "vor", "vor_dme", "vortac", "dme", "ndb", "tacan", "localizer", "glideslope", "gls"
]

#: Which radio a navaid is tuned on. ``None`` means it is not tunable at all.
TunableRadio = Literal["nav", "adf"]


class Navaid(BaseModel):
    """A ground-based navigation aid.

    :attr:`tunable_radio` says where the frequency goes rather than merely
    whether it is usable, because the three cases are genuinely different: a VOR
    goes in NAV1, an NDB goes in the ADF, and a glideslope is not tuned by the
    instructor at all. A boolean would collapse the first two, and an NDB's
    380 kHz does not even pass ``AircraftSetup.nav1_freq_khz`` validation.
    """

    model_config = ConfigDict(frozen=True)

    ident: str = Field(min_length=1)
    kind: NavaidKind
    name: str | None = None
    position: GeoPosition
    frequency_khz: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Frequency in kHz. VHF navaids share the unit of AircraftSetup.nav1_freq_khz "
            "(108000-117950); NDBs are in their own band (190-1750). The source stores VHF in "
            "units of 10 kHz and NDBs in kHz, and both are normalised here."
        ),
    )
    channel: str | None = Field(default=None, description='TACAN channel, e.g. "112X".')
    range_nm: float | None = Field(default=None, ge=0.0, description="Published service volume.")
    magnetic_variation_deg: float | None = None
    region_code: str | None = None
    airport_icao: str | None = Field(default=None, description="Terminal navaids only.")
    runway_ident: str | None = Field(default=None, description="Localizers and glideslopes only.")
    tunable_radio: TunableRadio | None = Field(
        default="nav",
        description=(
            'Which radio tunes this: "nav" for VHF navaids and localizers, "adf" for NDBs, '
            "None for glideslopes, GLS and markers."
        ),
    )


# ---------------------------------------------------------------------------
# Parking
# ---------------------------------------------------------------------------

ParkingKind = Literal["gate", "hangar", "tie_down", "misc"]
ParkingOperation = Literal["none", "general_aviation", "airline", "cargo", "military"]


class ParkingStand(BaseModel):
    """A parking position, gate or stand.

    **One model, not two.** The feature spec lists "gate" and "parking stand"
    as separate placements, but ``apt.dat`` publishes one record type with a
    ``kind`` field. Splitting them in Python would invent a distinction the data
    does not make; the UI filters on :attr:`kind` and :attr:`operation`.
    """

    model_config = ConfigDict(frozen=True)

    airport_icao: str = Field(min_length=2, max_length=7)
    name: str = Field(description='Published stand name, e.g. "R32".')
    position: GeoPosition = Field(
        description=(
            "Where the aircraft's nose wheel sits. apt.dat carries no per-stand elevation, so "
            "altitude_ft is the airport elevation — harmless, because a stand placement puts the "
            "aircraft on the ground anyway."
        )
    )
    heading_true_deg: float = Field(
        ge=0.0, le=360.0, description="Heading of the parked aircraft, TRUE degrees."
    )
    kind: ParkingKind
    aircraft_types: tuple[str, ...] = Field(
        default=(), description='Accepted types: "heavy", "jets", "turboprops", "props", "helos".'
    )
    operation: ParkingOperation | None = None
    airline_codes: tuple[str, ...] = Field(
        default=(), description='ICAO airline codes the stand is assigned to, e.g. ("ibe", "baw").'
    )


# ---------------------------------------------------------------------------
# Fixes and holds
# ---------------------------------------------------------------------------


class Fix(BaseModel):
    """A named waypoint from ``earth_fix.dat``."""

    model_config = ConfigDict(frozen=True)

    ident: str = Field(min_length=1)
    position: GeoPosition
    region_code: str | None = None
    terminal_airport_icao: str | None = Field(
        default=None,
        description=(
            "The airport a terminal fix belongs to. None means enroute (the source spells this "
            "ENRT). Terminal scope is not decoration: it is what makes a procedure leg's 4-part "
            "ARINC key resolvable at all."
        ),
    )
    name: str | None = None


class Hold(BaseModel):
    """A published holding pattern from ``earth_hold.dat``.

    :attr:`inbound_course_mag_deg` is **magnetic**, verified rather than
    assumed: cross-checking this file against the ``HM`` legs of the same fixes
    in the CIFP — which are magnetic by ARINC definition — gives exact agreement
    at airports with double-digit variation, which is only possible if both are
    in the same frame.
    """

    model_config = ConfigDict(frozen=True)

    fix: Waypoint = Field(description="The fix the pattern is held over.")
    inbound_course_mag_deg: float = Field(
        ge=0.0, le=360.0, description="Inbound leg course, MAGNETIC degrees."
    )
    turn_direction: Literal["L", "R"]
    leg_time_min: float | None = Field(
        default=None, gt=0.0, description="Leg length as time. Exactly one of time/length is set."
    )
    leg_length_nm: float | None = Field(
        default=None, gt=0.0, description="Leg length as distance. Exactly one of time/length."
    )
    min_altitude_ft: float | None = None
    max_altitude_ft: float | None = None
    speed_kt: float | None = Field(default=None, ge=0.0)
    airport_icao: str | None = Field(default=None, description="None means an enroute hold.")


# ---------------------------------------------------------------------------
# Procedures
# ---------------------------------------------------------------------------

ProcedureKind = Literal["sid", "star", "approach"]

ApproachType = Literal[
    "ils",
    "loc",
    "rnav",
    "gps",
    "vor",
    "vor_dme",
    "ndb",
    "ndb_dme",
    "lda",
    "sdf",
    "gls",
    "mls",
    "igs",
    "unknown",
]

#: Legs that carry a resolvable fix — the ONLY ones offered as a placement.
POSITIONABLE_TERMINATORS: frozenset[str] = frozenset({"IF", "TF", "CF", "DF", "AF", "RF"})

#: Trajectory-dependent legs: no defensible coordinate without the flown path.
#: Displayed so an instructor can read the procedure, never offered as a position.
TRAJECTORY_TERMINATORS: frozenset[str] = frozenset(
    {"CA", "VA", "FM", "VM", "CD", "CI", "CR", "VD", "VI", "VR", "FA", "FC", "FD"}
)

#: Holds and procedure turns. Displayed, never offered.
MANOEUVRE_TERMINATORS: frozenset[str] = frozenset({"HA", "HF", "HM", "PI"})

PathTerminator = Literal[
    "IF", "TF", "CF", "DF", "AF", "RF",
    "CA", "VA", "FM", "VM", "CD", "CI", "CR", "VD", "VI", "VR", "FA", "FC", "FD",
    "HA", "HF", "HM", "PI",
]  # fmt: skip


class FixRef(BaseModel):
    """The 4-part ARINC 424 key a procedure leg names its fix with.

    Four fields and not one, because idents are **not** unique and terminal
    fixes are scoped to an airport. ``(section, subsection)`` says which table
    to look in — a ``D`` with a blank subsection is a VHF navaid, a ``P``/``C``
    is a terminal waypoint of this file's airport — and getting that wrong makes
    roughly half the legs of a typical SID unresolvable.
    """

    model_config = ConfigDict(frozen=True)

    ident: str = Field(min_length=1, description='e.g. "MD800", "NVS", "GOXOL".')
    region_code: str = Field(description='ICAO region code, e.g. "LE".')
    section: str = Field(description='ARINC 424 section: "D", "E", "P", "PN".')
    subsection: str = Field(description='ARINC 424 subsection: "C", "A", "I", "G" or blank.')
    airport_icao: str | None = Field(
        default=None, description="The CIFP file's airport, used to scope terminal fixes."
    )


class AltitudeConstraint(BaseModel):
    """An altitude restriction, straight off the leg record.

    Flight levels are normalised to feet with a flag, rather than kept as a
    string, so the conversion happens once here instead of in every consumer
    while the UI can still render the published form.
    """

    model_config = ConfigDict(frozen=True)

    descriptor: str = Field(description='Raw ARINC descriptor character: "+", "-", "B", "J", …')
    min_ft: float | None = Field(default=None, description="At-or-above bound, feet MSL.")
    max_ft: float | None = Field(default=None, description="At-or-below bound, feet MSL.")
    min_is_flight_level: bool = Field(
        default=False, description="True when the source published the lower bound as a level."
    )
    max_is_flight_level: bool = Field(
        default=False, description="True when the source published the upper bound as a level."
    )

    @property
    def suggested_ft(self) -> float | None:
        """The altitude to place an aircraft at, decided once here.

        A band resolves to its **lower** bound. An aircraft on a STAR enters a
        window from above and the crew targets the bottom of it; placing at the
        top of a ``FL140``/``10000`` window puts the aircraft 4000 ft high on a
        descent profile it then cannot fly.
        """
        if self.min_ft is not None:
            return self.min_ft
        return self.max_ft

    @computed_field  # type: ignore[prop-decorator]
    @property
    def display(self) -> str:
        """The constraint as an instructor would read it off a chart.

        A **computed field**, not a plain property, so it crosses the API: the leg table
        renders this string verbatim rather than reimplementing "at or above FL140" in
        TypeScript. Formatting a published constraint is navdata's job, and doing it twice
        is how the two copies come to disagree.
        """
        low = _format_altitude(self.min_ft, self.min_is_flight_level)
        high = _format_altitude(self.max_ft, self.max_is_flight_level)
        if low is not None and high is not None:
            return low if low == high else f"between {low} and {high}"
        if low is not None:
            return f"at or above {low}"
        if high is not None:
            return f"at or below {high}"
        return "unrestricted"


class SpeedConstraint(BaseModel):
    """A speed restriction, straight off the leg record."""

    model_config = ConfigDict(frozen=True)

    descriptor: str = Field(default="", description='Raw ARINC descriptor: "+", "-" or blank.')
    min_kt: float | None = Field(default=None, ge=0.0, description="At-or-above bound, knots.")
    max_kt: float | None = Field(default=None, ge=0.0, description="At-or-below bound, knots.")

    @property
    def suggested_kt(self) -> float | None:
        """The constraining bound: the ceiling if there is one, else the floor."""
        if self.max_kt is not None:
            return self.max_kt
        return self.min_kt

    @computed_field  # type: ignore[prop-decorator]
    @property
    def display(self) -> str:
        """The constraint as an instructor would read it off a chart.

        A computed field for the same reason as :attr:`AltitudeConstraint.display`: the UI
        shows this string and never formats a constraint itself.
        """
        if self.min_kt is not None and self.max_kt is not None:
            if self.min_kt == self.max_kt:
                return f"at {self.max_kt:g} kt"
            return f"between {self.min_kt:g} and {self.max_kt:g} kt"
        if self.max_kt is not None:
            return f"at or below {self.max_kt:g} kt"
        if self.min_kt is not None:
            return f"at or above {self.min_kt:g} kt"
        return "unrestricted"


class ProcedureLeg(BaseModel):
    """One leg of a published procedure.

    :attr:`is_positionable` is computed by the provider and carried here, so the
    UI never has to know ARINC 424 leg types. It requires **both** a positionable
    path terminator and a resolved fix, and :attr:`unpositionable_reason`
    distinguishes the two failures in words the UI shows verbatim — confusing
    "this leg has no defensible coordinate" with "this leg's fix is missing from
    the index" would be a silent bug.

    Unpositionable legs are still returned and still displayed: an instructor
    reading a SID needs to see the climb leg. They are simply not offered.
    """

    model_config = ConfigDict(frozen=True)

    sequence: int = Field(description="Sequence number from the source record: 10, 20, 30 …")
    path_terminator: PathTerminator

    is_positionable: bool = Field(
        description="True iff the terminator carries a fix AND that fix resolved."
    )
    unpositionable_reason: str | None = Field(
        default=None, description="Set iff is_positionable is False. Shown to the user verbatim."
    )

    fix_ref: FixRef | None = Field(
        default=None,
        description=(
            "The raw 4-part ARINC key, kept even when the fix did not resolve — it is what makes "
            "an unresolved fix diagnosable instead of merely absent."
        ),
    )
    fix: Waypoint | None = Field(default=None, description="The resolved fix, when there is one.")

    recommended_navaid: Waypoint | None = None
    theta_mag_deg: float | None = Field(
        default=None, ge=0.0, le=360.0, description="Bearing FROM the recommended navaid, magnetic."
    )
    rho_nm: float | None = Field(
        default=None, ge=0.0, description="Distance FROM the recommended navaid."
    )
    arc_radius_nm: float | None = Field(default=None, gt=0.0, description="RF legs only.")
    outbound_course_mag_deg: float | None = Field(default=None, ge=0.0, le=360.0)
    distance_nm: float | None = Field(default=None, ge=0.0)
    time_min: float | None = Field(
        default=None, gt=0.0, description="Holding legs are published in time, not distance."
    )
    turn_direction: Literal["L", "R"] | None = None
    vertical_angle_deg: float | None = Field(
        default=None, description="Published descent angle, negative for a descent."
    )

    altitude: AltitudeConstraint | None = None
    speed: SpeedConstraint | None = None
    transition_altitude_ft: int | None = None

    is_flyover: bool = False
    is_initial_approach_fix: bool = False
    is_final_approach_fix: bool = False
    is_missed_approach_point: bool = False
    is_missed_approach_leg: bool = False
    is_end_of_procedure: bool = False

    raw: str | None = Field(default=None, description="The source line. Diagnostics only.")


class ProcedureSummary(BaseModel):
    """Enough of a procedure to list it without parsing its legs."""

    model_config = ConfigDict(frozen=True)

    airport_icao: str = Field(min_length=2, max_length=7)
    kind: ProcedureKind
    ident: str = Field(description='e.g. "BARD3B", "I18LY".')
    transition: str | None = Field(
        default=None, description='Named transition, e.g. "ADUXO". None for the common route.'
    )
    runway_idents: tuple[str, ...] = Field(
        default=(),
        description=(
            'The real runways this serves, expanded: a "RW32B" transition becomes every 32* '
            "runway the airport actually has. Empty for a named (non-runway) transition."
        ),
    )
    approach_type: ApproachType | None = Field(default=None, description="Approaches only.")
    leg_count: int = Field(ge=0)
    positionable_leg_count: int = Field(ge=0)


class Procedure(BaseModel):
    """A published procedure with every leg resolved."""

    model_config = ConfigDict(frozen=True)

    airport_icao: str = Field(min_length=2, max_length=7)
    kind: ProcedureKind
    ident: str
    transition: str | None = None
    runway_idents: tuple[str, ...] = ()
    approach_type: ApproachType | None = None
    legs: tuple[ProcedureLeg, ...] = ()


# ---------------------------------------------------------------------------
# Status — the gate the UI reads before it enables anything
# ---------------------------------------------------------------------------

NavdataState = Literal["unavailable", "building", "ready", "error"]


class IndexProgress(BaseModel):
    """One frame of index-build progress, pushed over the live WebSocket."""

    model_config = ConfigDict(frozen=True)

    stage: Literal["airports", "runways", "parking", "navaids", "fixes", "holds", "finalising"]
    stage_index: int = Field(ge=1, description="1-based.")
    stage_count: int = Field(ge=1)
    fraction: float = Field(ge=0.0, le=1.0, description="Overall completion, 0.0 … 1.0.")
    detail: str | None = Field(
        default=None, description='Human-readable, e.g. "apt.dat — 8.1 M / 12.4 M lines".'
    )


class NavdataStatus(BaseModel):
    """What the provider can currently answer, and why not when it cannot.

    This is to navdata what ``GET /api/capabilities`` is to the simulator: **the
    UI disables what is unavailable and states the reason.** An instructor never
    discovers missing navdata by clicking a control that fails.

    Frozen, and published by whole-object assignment rather than field-by-field
    mutation, so a reader on a request thread never sees a torn mix of a build
    thread's updates.
    """

    model_config = ConfigDict(frozen=True)

    state: NavdataState
    reason: str | None = Field(
        default=None, description='Human-readable. Always set when state is not "ready".'
    )
    provider: str = Field(description='"xplane_native" | "in_memory" | "msfs_bgl".')
    source_root: str | None = Field(
        default=None, description="The resolved install path, as a string so it serialises."
    )
    airac_cycle: str | None = Field(default=None, description='e.g. "2607".')
    cycle_valid_from: date | None = None
    cycle_valid_to: date | None = None
    built_at: datetime | None = None
    airport_count: int | None = Field(default=None, ge=0)
    runway_count: int | None = Field(default=None, ge=0)
    navaid_count: int | None = Field(default=None, ge=0)
    fix_count: int | None = Field(default=None, ge=0)
    progress: IndexProgress | None = Field(
        default=None, description='Populated only while state is "building".'
    )


def _format_altitude(value: float | None, is_flight_level: bool) -> str | None:
    """Render one altitude bound the way the source published it."""
    if value is None:
        return None
    if is_flight_level:
        return f"FL{round(value / 100):03d}"
    return f"{value:g} ft"
