"""Sim-agnostic AI traffic vocabulary, geometry builders and track interpolation.

The traffic manager's `core/` half (ai-traffic.md §3, §6.1): entity kinds, the
waypoint-and-timing :class:`TrafficTrack` an adapter's ``spawn_traffic`` takes,
the discriminated spawn-request union the server resolves, the live
:class:`TrafficContact` read model, and the four geometry builders that turn an
instructor's intent into a concrete, timed track.

No dataref, no XPPython3, no bridge protocol detail belongs anywhere near this
module. Everything here is pure computation over :mod:`core.models`,
:mod:`core.geodesy` and :mod:`core.atmosphere` — and deliberately adds **zero**
new geodesic primitives (ai-traffic.md D11): every builder calls the functions
the Position Manager already proved, verbatim.

Units follow every other model in the project: ``_ft`` is feet MSL, ``_kt`` is
knots, ``_deg`` is degrees, ``_s`` is seconds, ``_nm`` is nautical miles,
``_m`` is metres.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.atmosphere import tas_from_ias
from core.geodesy import (
    APPROACH_CATEGORY_VAT_KT,
    DEFAULT_GLIDESLOPE_DEG,
    METRES_PER_NAUTICAL_MILE,
    ApproachCategory,
    distance_and_bearing,
    final_approach_point,
    point_at_distance_and_bearing,
)
from core.models import AircraftState, GeoPosition, Runway

__all__ = [
    "APPROACH_SEQUENCE_DEFAULT_DISTANCES_NM",
    "RUNWAY_INCURSION_DEFAULT_OFFSET_M",
    "RUNWAY_INCURSION_DEFAULT_SPEED_KT",
    "TAXI_DEFAULT_SPEED_KT",
    "TCAS_DEFAULT_CLOSURE_IAS_KT",
    "TCAS_SEVERITY_PROFILES",
    "TCAS_TRACK_LEAD_TIME_S",
    "ApproachSequenceSpawnRequest",
    "CustomTrackSpawnRequest",
    "RunwayIncursionSpawnRequest",
    "TaxiTrafficSpawnRequest",
    "TcasConflictSpawnRequest",
    "TcasSeverity",
    "TcasSeverityProfile",
    "TrafficCapacityExceeded",
    "TrafficContact",
    "TrafficKind",
    "TrafficSample",
    "TrafficScenarioShape",
    "TrafficSpawnRequest",
    "TrafficTrack",
    "TrafficWaypoint",
    "approach_sequence_tracks",
    "interpolate_track",
    "runway_incursion_track",
    "taxi_traffic_track",
    "tcas_conflict_track",
]

_SECONDS_PER_HOUR = 3600.0

# ---------------------------------------------------------------------------
# Entity vocabulary (§3.1)
# ---------------------------------------------------------------------------

#: What kind of thing a traffic entity is — never *which livery*; per-model
#: visual fidelity is a bridge implementation detail (ai-traffic.md §1.2).
TrafficKind = Literal["aircraft", "ground_vehicle", "bird"]

#: Which scenario shape a track was built for — carried for display/label
#: purposes only. The adapter and the bridge never branch on it: a track is a
#: track regardless of how it was produced (feature-spec's own "it does not
#: make decisions").
TrafficScenarioShape = Literal[
    "tcas_conflict", "runway_incursion", "approach_sequence", "taxi_traffic", "custom"
]


# ---------------------------------------------------------------------------
# The track — what the bridge is handed (§3.2)
# ---------------------------------------------------------------------------


class TrafficWaypoint(BaseModel):
    """One timed point on a traffic entity's path."""

    model_config = ConfigDict(frozen=True)

    position: GeoPosition = Field(description="Target position; altitude_ft is feet MSL.")
    speed_kt: float = Field(
        ge=0.0,
        description=(
            "Ground speed in knots for the leg starting here. Indicated airspeed for kind="
            "'aircraft' entities flying, a plain ground speed for 'ground_vehicle'/'bird' — "
            "there is no indicated-airspeed reading for a truck."
        ),
    )
    heading_deg: float | None = Field(
        default=None,
        ge=0.0,
        lt=360.0,
        description=(
            "True heading to face AT this waypoint. None: the consumer derives it from the "
            "bearing to the next waypoint (or holds the previous leg's heading on the final "
            "waypoint) — the same fallback order core.geodesy.waypoint_placement uses for a "
            "bare fix."
        ),
    )
    t_offset_s: float = Field(ge=0.0, description="Seconds after spawn this point is reached.")
    on_ground: bool = Field(default=False, description="True for a taxiing or stationary point.")


class TrafficTrack(BaseModel):
    """A complete, timed path for one traffic entity — what SimAdapter.spawn_traffic takes.

    Every field here is something the bridge can act on with no further
    decision-making: "spawn at waypoints[0], move through the rest on schedule,
    despawn after despawn_after_s" is the whole vocabulary (bridge/README.md's
    "it spawns, it moves, it despawns. It does not make decisions.").
    """

    model_config = ConfigDict(frozen=True)

    kind: TrafficKind
    scenario_shape: TrafficScenarioShape = "custom"
    callsign: str = Field(min_length=1, max_length=12, description='e.g. "TFC01", "GND03".')
    label: str = Field(
        min_length=1, description='Human-readable description, e.g. "TCAS conflict, head-on".'
    )
    waypoints: tuple[TrafficWaypoint, ...] = Field(min_length=2)
    despawn_after_s: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Seconds after the LAST waypoint's t_offset_s before automatic despawn. None: the "
            "entity holds at the last waypoint until explicitly despawned."
        ),
    )

    @model_validator(mode="after")
    def _waypoints_are_time_ordered_from_zero(self) -> TrafficTrack:
        offsets = [wp.t_offset_s for wp in self.waypoints]
        if offsets[0] != 0.0:
            raise ValueError("TrafficTrack.waypoints[0].t_offset_s must be 0.0 — spawn is t=0.")
        if offsets != sorted(offsets) or len(set(offsets)) != len(offsets):
            raise ValueError(
                "TrafficTrack.waypoints must be strictly increasing by t_offset_s, no ties."
            )
        return self


# ---------------------------------------------------------------------------
# Spawn requests — one discriminated union (§3.3, D7)
# ---------------------------------------------------------------------------

#: Named TCAS conflict presets. Deliberately NOT a physics model of TCAS's real
#: sensitivity-level table (which varies by altitude); these are round numbers
#: chosen to reliably cross the published TA/RA thresholds well before the
#: geometry's own closest point of approach, giving the student time to see the
#: TA before the RA. Always overridable by the request's own fields — the
#: FINAL_THROTTLE honesty class.
TcasSeverity = Literal["head_on_ra", "crossing_ra", "ta_only"]


class TcasConflictSpawnRequest(BaseModel):
    """Converge an intruder on the user aircraft's own projected track."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["tcas_conflict"]
    severity: TcasSeverity = "head_on_ra"
    relative_bearing_deg: float = Field(
        default=180.0,
        ge=0.0,
        lt=360.0,
        description="Intruder's track relative to the user's own, at spawn: 180=head-on, "
        "90/270=crossing, 0=same-direction closure from ahead or overtaking from behind.",
    )
    miss_side: Literal["left", "right"] = "left"
    vertical_offset: Literal["above", "below"] = "above"
    # gt, not ge: zero is never a meaningful speed here — None already means
    # "use the default" — so the schema refuses it instead of building a
    # degenerate motionless conflict. Same for the three sibling requests.
    closure_ias_kt: float | None = Field(default=None, gt=0.0)
    kind: TrafficKind = "aircraft"
    callsign: str = Field(default="TFC01", min_length=1, max_length=12)


class RunwayIncursionSpawnRequest(BaseModel):
    """A vehicle or aircraft crossing the runway, timed to the user's own closing speed."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["runway_incursion"]
    airport_icao: str = Field(min_length=2, max_length=7)
    runway_ident: str = Field(min_length=1, max_length=3)
    cross_at_along_track_nm: float = Field(
        default=0.0,
        description="Distance beyond the threshold, along the landing direction, "
        "where the crossing happens. 0.0 = at the threshold itself.",
    )
    lead_time_before_user_arrival_s: float = Field(
        default=8.0,
        description="How many seconds BEFORE the user would reach the crossing "
        "point the vehicle starts crossing it. Negative = the vehicle is still crossing "
        "slightly AFTER the user's projected arrival — the worse-case incursion.",
    )
    from_side: Literal["left", "right"] = "left"
    vehicle_speed_kt: float | None = Field(default=None, gt=0.0)
    kind: TrafficKind = "ground_vehicle"
    callsign: str = Field(default="GND01", min_length=1, max_length=12)


class ApproachSequenceSpawnRequest(BaseModel):
    """n aircraft on the same final, at named distances — reuses core.geodesy verbatim (D11)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["approach_sequence"]
    airport_icao: str = Field(min_length=2, max_length=7)
    runway_ident: str = Field(min_length=1, max_length=3)
    distances_nm: tuple[float, ...] = Field(min_length=1, max_length=8)
    ias_kt: float | None = Field(default=None, gt=0.0)
    category: ApproachCategory = "B"
    kind: TrafficKind = "aircraft"
    callsign_prefix: str = Field(default="SEQ", min_length=1, max_length=8)


class TaxiTrafficSpawnRequest(BaseModel):
    """A traffic entity ground-taxiing an explicit route (D12, §10.5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["taxi_traffic"]
    route: tuple[GeoPosition, ...] = Field(min_length=2, max_length=32)
    speed_kt: float | None = Field(default=None, gt=0.0)
    kind: TrafficKind = "aircraft"
    callsign: str = Field(default="TAXI01", min_length=1, max_length=12)


class CustomTrackSpawnRequest(BaseModel):
    """The escape hatch: a hand-built TrafficTrack, e.g. authored from map clicks."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["custom"]
    track: TrafficTrack


TrafficSpawnRequest = Annotated[
    TcasConflictSpawnRequest
    | RunwayIncursionSpawnRequest
    | ApproachSequenceSpawnRequest
    | TaxiTrafficSpawnRequest
    | CustomTrackSpawnRequest,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Live contacts (§3.4)
# ---------------------------------------------------------------------------


class TrafficContact(BaseModel):
    """One live traffic entity, as reported by the adapter. Always-complete, like
    AircraftState — a read, never a sparse write."""

    model_config = ConfigDict(frozen=True)

    traffic_id: str = Field(
        description="Adapter-assigned uuid4 hex (D5). Stable for the entity's lifetime."
    )
    kind: TrafficKind
    scenario_shape: TrafficScenarioShape
    callsign: str
    label: str
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    altitude_ft: float
    heading_deg: float = Field(ge=0.0, le=360.0)
    ground_speed_kt: float = Field(ge=0.0)
    vertical_speed_fpm: float
    on_ground: bool = False


class TrafficCapacityExceeded(RuntimeError):
    """An adapter is already at whatever traffic limit it enforces (D6).

    Capacity limits are **adapter-owned, never a `core/` constant**: X-Plane's
    real cap (19 multiplayer aircraft slots) is a fact about X-Plane, not about
    the project. The exception type is defined once, sim-agnostically, so the
    server can build one 409 message regardless of which adapter is active;
    each adapter chooses its own number.
    """

    def __init__(self, adapter_name: str, capacity: int, active_count: int) -> None:
        self.adapter_name = adapter_name
        self.capacity = capacity
        self.active_count = active_count
        super().__init__(
            f"{adapter_name!r} is at capacity: {active_count} of {capacity} traffic slots in use."
        )


# ---------------------------------------------------------------------------
# Interpolation (§6.1, D9)
# ---------------------------------------------------------------------------


class TrafficSample(BaseModel):
    """Where a track-following entity is, at some elapsed time since spawn."""

    model_config = ConfigDict(frozen=True)
    position: GeoPosition
    heading_deg: float = Field(ge=0.0, le=360.0)
    ground_speed_kt: float = Field(ge=0.0)
    on_ground: bool


def _leg_bearing_deg(a: GeoPosition, b: GeoPosition) -> float | None:
    """Initial true bearing of the geodesic a→b, or ``None`` for coincident points."""
    distance_nm, bearing_deg = distance_and_bearing(a, b)
    return bearing_deg if distance_nm > 0.0 else None


def _heading_at_waypoint(track: TrafficTrack, index: int) -> float:
    """The heading an entity faces AT a waypoint, per TrafficWaypoint.heading_deg's
    own fallback order: the stated heading, else the bearing to the next
    waypoint, else the previous leg's heading, else due north — the same chain
    :func:`core.geodesy.waypoint_placement` uses for a bare fix.
    """
    waypoints = track.waypoints
    stated = waypoints[index].heading_deg
    if stated is not None:
        return stated
    if index + 1 < len(waypoints):
        bearing = _leg_bearing_deg(waypoints[index].position, waypoints[index + 1].position)
        if bearing is not None:
            return bearing
    if index > 0:
        bearing = _leg_bearing_deg(waypoints[index - 1].position, waypoints[index].position)
        if bearing is not None:
            return bearing
    return 0.0


def interpolate_track(track: TrafficTrack, elapsed_s: float) -> TrafficSample:
    """Where a traffic entity following ``track`` is, ``elapsed_s`` after spawn.

    Before the first waypoint (never happens — t_offset_s[0] == 0.0 is enforced
    on the model) or exactly at or after the last, the entity sits at that
    waypoint, holding its heading. Between two waypoints it advances along the
    GEODESIC connecting them (core.geodesy.distance_and_bearing +
    point_at_distance_and_bearing) at the CONSTANT speed implied by their own
    distance and t_offset_s gap — not a blend of the two waypoints' stated
    speeds, so a track asking for 250 kt at one point and 180 kt at the next is
    honoured by how far apart the caller placed the waypoints in time, not by
    an invented deceleration curve (see ai-traffic.md §10.6 for the limitation
    this accepts). This mirrors core.geodesy's own "the initial bearing is
    close enough over a leg this short" convention (the _offset helper) rather
    than re-deriving arrival-bearing correction for legs that are, in every
    shipped builder, well under 20 NM.

    Pure, no I/O, no clock of its own — elapsed_s is an input, which is what
    makes this independently unit-testable AND makes it the shared reference
    implementation FakeSimAdapter uses and the bridge's own Python can mirror.
    """
    waypoints = track.waypoints
    last_index = len(waypoints) - 1
    if elapsed_s >= waypoints[last_index].t_offset_s:
        last = waypoints[last_index]
        return TrafficSample(
            position=last.position,
            heading_deg=_heading_at_waypoint(track, last_index),
            ground_speed_kt=0.0,
            on_ground=last.on_ground,
        )
    elapsed_s = max(elapsed_s, 0.0)

    # The leg the entity is on: the last waypoint at or before elapsed_s.
    index = 0
    for candidate in range(last_index):
        if waypoints[candidate].t_offset_s <= elapsed_s:
            index = candidate
    start, end = waypoints[index], waypoints[index + 1]
    leg_time_s = end.t_offset_s - start.t_offset_s  # > 0, strict ordering is model-enforced
    fraction = (elapsed_s - start.t_offset_s) / leg_time_s
    leg_distance_nm, leg_bearing_deg = distance_and_bearing(start.position, end.position)

    if leg_distance_nm > 0.0:
        moved = point_at_distance_and_bearing(
            start.position, leg_distance_nm * fraction, leg_bearing_deg
        )
        heading_deg = leg_bearing_deg if fraction > 0.0 else _heading_at_waypoint(track, index)
    else:
        # A stationary gap in time: the entity waits at the waypoint (its
        # altitude may still interpolate — a climb in place).
        moved = start.position
        heading_deg = _heading_at_waypoint(track, index)

    altitude_ft = start.position.altitude_ft + fraction * (
        end.position.altitude_ft - start.position.altitude_ft
    )
    return TrafficSample(
        position=GeoPosition(
            latitude=moved.latitude, longitude=moved.longitude, altitude_ft=altitude_ft
        ),
        heading_deg=heading_deg,
        ground_speed_kt=leg_distance_nm / leg_time_s * _SECONDS_PER_HOUR,
        on_ground=start.on_ground,
    )


# ---------------------------------------------------------------------------
# Geometry builders (§6.1) — constants first, in the design's own order
# ---------------------------------------------------------------------------


class TcasSeverityProfile(BaseModel):
    """What one named TCAS severity preset means, in seconds, feet and miles."""

    model_config = ConfigDict(frozen=True)
    spawn_lead_time_s: float  # total track duration from spawn to CPA
    vertical_miss_distance_ft: float
    horizontal_miss_distance_nm: float


TCAS_SEVERITY_PROFILES: Mapping[TcasSeverity, TcasSeverityProfile] = MappingProxyType(
    {
        "head_on_ra": TcasSeverityProfile(
            spawn_lead_time_s=100.0, vertical_miss_distance_ft=0.0, horizontal_miss_distance_nm=0.0
        ),
        "crossing_ra": TcasSeverityProfile(
            spawn_lead_time_s=100.0, vertical_miss_distance_ft=0.0, horizontal_miss_distance_nm=0.0
        ),
        "ta_only": TcasSeverityProfile(
            spawn_lead_time_s=90.0, vertical_miss_distance_ft=500.0, horizontal_miss_distance_nm=0.5
        ),
    }
)

TCAS_DEFAULT_CLOSURE_IAS_KT: float = 250.0
TCAS_TRACK_LEAD_TIME_S: float = 20.0  # how far past CPA the track continues before holding

#: What each severity reads as in a contact list.
_TCAS_SEVERITY_LABELS: Mapping[TcasSeverity, str] = MappingProxyType(
    {
        "head_on_ra": "TCAS conflict, head-on RA",
        "crossing_ra": "TCAS conflict, crossing RA",
        "ta_only": "TCAS conflict, TA only",
    }
)

RUNWAY_INCURSION_DEFAULT_OFFSET_M: float = (
    60.0  # how far off each side of the runway the vehicle starts/ends
)
RUNWAY_INCURSION_DEFAULT_SPEED_KT: float = 15.0  # a plausible airport service-vehicle speed

APPROACH_SEQUENCE_DEFAULT_DISTANCES_NM: tuple[float, ...] = (12.0, 8.0, 4.0)

TAXI_DEFAULT_SPEED_KT: float = 12.0


def tcas_conflict_track(
    user_state: AircraftState,
    *,
    severity: TcasSeverity = "head_on_ra",
    relative_bearing_deg: float = 180.0,
    miss_side: Literal["left", "right"] = "left",
    vertical_offset: Literal["above", "below"] = "above",
    closure_ias_kt: float | None = None,
    kind: TrafficKind = "aircraft",
    callsign: str = "TFC01",
) -> TrafficTrack:
    """An intruder converging on the user aircraft's own projected position.

    1. Extrapolate the user's own position forward severity's spawn_lead_time_s
       using its current ground speed (tas_from_ias(user_state.ias_kt,
       user_state.altitude_ft) — the "still air" approximation every other
       geometry function in this project already makes) and heading_deg.
    2. That point, offset horizontal_miss_distance_nm to miss_side of the
       INTRUDER's own track and vertical_miss_distance_ft vertical_offset from
       it, is the intruder's position at t=spawn_lead_time_s — its projected
       closest point of approach.
    3. The intruder's track direction is user_state.heading_deg +
       relative_bearing_deg. Walk backward along it from the CPA point to
       t=0.0 (the spawn point) and forward from it to
       t=spawn_lead_time_s + TCAS_TRACK_LEAD_TIME_S (where the track ends and
       the entity holds, or despawns if despawn_after_s is set by the caller).

    A zero-miss request (the "head_on_ra"/"crossing_ra" defaults) places the
    intruder EXACTLY at the user's own projected position at t=spawn_lead_time_s.

    Raises:
        ValueError: for a non-positive closure speed — a motionless "intruder"
            is three co-located waypoints, not a conflict.
    """
    intruder_ias_kt = TCAS_DEFAULT_CLOSURE_IAS_KT if closure_ias_kt is None else closure_ias_kt
    if intruder_ias_kt <= 0.0:
        raise ValueError(
            f"closure_ias_kt must be a positive speed in knots, got {intruder_ias_kt!r}."
        )
    profile = TCAS_SEVERITY_PROFILES[severity]
    lead_s = profile.spawn_lead_time_s

    user_position = GeoPosition(
        latitude=user_state.latitude,
        longitude=user_state.longitude,
        altitude_ft=user_state.altitude_ft,
    )
    user_gs_kt = tas_from_ias(user_state.ias_kt, user_state.altitude_ft)
    user_projected = point_at_distance_and_bearing(
        user_position, user_gs_kt * lead_s / _SECONDS_PER_HOUR, user_state.heading_deg
    )

    intruder_track_deg = (user_state.heading_deg + relative_bearing_deg) % 360.0
    intruder_altitude_ft = user_state.altitude_ft + (
        profile.vertical_miss_distance_ft
        if vertical_offset == "above"
        else -profile.vertical_miss_distance_ft
    )
    cpa = user_projected
    if profile.horizontal_miss_distance_nm > 0.0:
        offset_bearing_deg = intruder_track_deg + (-90.0 if miss_side == "left" else 90.0)
        cpa = point_at_distance_and_bearing(
            user_projected, profile.horizontal_miss_distance_nm, offset_bearing_deg
        )
    cpa = GeoPosition(
        latitude=cpa.latitude, longitude=cpa.longitude, altitude_ft=intruder_altitude_ft
    )

    intruder_gs_kt = tas_from_ias(intruder_ias_kt, intruder_altitude_ft)
    # Negative distance walks backwards along the same geodesic, so spawn→CPA
    # measures exactly the distance the intruder covers in lead_s. The intruder
    # flies level: the vertical miss is built into its altitude, not a profile.
    spawn_point = point_at_distance_and_bearing(
        cpa, -(intruder_gs_kt * lead_s / _SECONDS_PER_HOUR), intruder_track_deg
    )
    end_point = point_at_distance_and_bearing(
        cpa, intruder_gs_kt * TCAS_TRACK_LEAD_TIME_S / _SECONDS_PER_HOUR, intruder_track_deg
    )

    return TrafficTrack(
        kind=kind,
        scenario_shape="tcas_conflict",
        callsign=callsign,
        label=_TCAS_SEVERITY_LABELS[severity],
        waypoints=(
            TrafficWaypoint(position=spawn_point, speed_kt=intruder_ias_kt, t_offset_s=0.0),
            TrafficWaypoint(position=cpa, speed_kt=intruder_ias_kt, t_offset_s=lead_s),
            TrafficWaypoint(
                position=end_point,
                speed_kt=intruder_ias_kt,
                t_offset_s=lead_s + TCAS_TRACK_LEAD_TIME_S,
            ),
        ),
    )


def runway_incursion_track(
    runway: Runway,
    user_state: AircraftState,
    *,
    cross_at_along_track_nm: float = 0.0,
    lead_time_before_user_arrival_s: float = 8.0,
    from_side: Literal["left", "right"] = "left",
    vehicle_speed_kt: float | None = None,
    kind: TrafficKind = "ground_vehicle",
    callsign: str = "GND01",
) -> TrafficTrack:
    """A crossing timed against the user's OWN closing speed on the runway.

    1. crossing_point = point_at_distance_and_bearing(runway.threshold,
       cross_at_along_track_nm, runway.true_bearing_deg) — a point on the
       centreline, cross_at_along_track_nm beyond the threshold in the landing
       direction (0.0 = at the threshold itself).
    2. distance_to_crossing_nm, _ = distance_and_bearing(user's position,
       crossing_point); t_user_arrival_s = distance_to_crossing_nm /
       tas_from_ias(user_state.ias_kt, user_state.altitude_ft) * 3600.
    3. t_cross_s = max(0.0, t_user_arrival_s - lead_time_before_user_arrival_s)
       — the vehicle is crossing the centreline at this elapsed time.
    4. The vehicle's own track is perpendicular to the runway axis
       (runway.true_bearing_deg +/- 90, per from_side),
       RUNWAY_INCURSION_DEFAULT_OFFSET_M off to one side at t=0.0, through
       crossing_point at t=t_cross_s, and the same offset on the opposite side
       at t=t_cross_s + (time to cover 2 * offset at vehicle_speed_kt).

    Accepted limitation, stated once and not re-litigated here: this reads
    user_state ONCE, at spawn time (D8) — a student who slows down after the
    instructor taps Spawn makes the vehicle arrive early relative to the
    (now slower) approach. Same honesty class as Failures' wall-clock delay
    trigger (failures-manager.md §10.3).

    Raises:
        ValueError: for a stationary user aircraft (its arrival time is
            undefined, so no honest crossing time exists) or a non-positive
            vehicle speed.
    """
    speed_kt = RUNWAY_INCURSION_DEFAULT_SPEED_KT if vehicle_speed_kt is None else vehicle_speed_kt
    if speed_kt <= 0.0:
        raise ValueError(f"vehicle_speed_kt must be a positive speed in knots, got {speed_kt!r}.")
    user_gs_kt = tas_from_ias(user_state.ias_kt, user_state.altitude_ft)
    if user_gs_kt <= 0.0:
        raise ValueError(
            "Cannot time a runway incursion against a stationary aircraft: its arrival "
            "at the crossing point is undefined."
        )

    on_centreline = point_at_distance_and_bearing(
        runway.threshold, cross_at_along_track_nm, runway.true_bearing_deg
    )
    crossing_point = GeoPosition(
        latitude=on_centreline.latitude,
        longitude=on_centreline.longitude,
        altitude_ft=runway.elevation_ft,
    )
    user_position = GeoPosition(
        latitude=user_state.latitude,
        longitude=user_state.longitude,
        altitude_ft=user_state.altitude_ft,
    )
    distance_to_crossing_nm, _ = distance_and_bearing(user_position, crossing_point)
    t_user_arrival_s = distance_to_crossing_nm / user_gs_kt * _SECONDS_PER_HOUR
    t_cross_s = max(0.0, t_user_arrival_s - lead_time_before_user_arrival_s)

    # A vehicle coming FROM the left crosses towards the right: its heading is
    # the runway axis + 90°, and it starts one offset behind the centreline
    # along its own (negative) track.
    vehicle_heading_deg = (
        runway.true_bearing_deg + (90.0 if from_side == "left" else -90.0)
    ) % 360.0
    offset_nm = RUNWAY_INCURSION_DEFAULT_OFFSET_M / METRES_PER_NAUTICAL_MILE
    start_point = point_at_distance_and_bearing(crossing_point, -offset_nm, vehicle_heading_deg)
    end_point = point_at_distance_and_bearing(crossing_point, offset_nm, vehicle_heading_deg)
    # §6.1 as written: the far side is reached at the time 2x offset takes at
    # the vehicle's speed, counted from the crossing moment.
    t_end_s = t_cross_s + (2.0 * offset_nm) / speed_kt * _SECONDS_PER_HOUR

    waypoints: list[TrafficWaypoint] = []
    if t_cross_s > 0.0:
        # The staging leg is a timing artifact — its stated speed is the creep
        # the schedule implies, not the commanded crossing speed.
        staging_speed_kt = offset_nm / t_cross_s * _SECONDS_PER_HOUR
        waypoints.append(
            TrafficWaypoint(
                position=start_point, speed_kt=staging_speed_kt, t_offset_s=0.0, on_ground=True
            )
        )
    # When t_cross_s clamps to 0.0 the vehicle is already crossing at spawn:
    # the track starts on the centreline (two tied t=0 waypoints would be
    # rejected by the model, and rightly — spawn is t=0, once).
    waypoints.append(
        TrafficWaypoint(
            position=crossing_point, speed_kt=speed_kt, t_offset_s=t_cross_s, on_ground=True
        )
    )
    waypoints.append(
        TrafficWaypoint(position=end_point, speed_kt=0.0, t_offset_s=t_end_s, on_ground=True)
    )

    return TrafficTrack(
        kind=kind,
        scenario_shape="runway_incursion",
        callsign=callsign,
        label=f"Runway incursion, {runway.airport_icao} {runway.ident}",
        waypoints=tuple(waypoints),
    )


def approach_sequence_tracks(
    runway: Runway,
    *,
    distances_nm: tuple[float, ...] = APPROACH_SEQUENCE_DEFAULT_DISTANCES_NM,
    ias_kt: float | None = None,
    category: ApproachCategory = "B",
    kind: TrafficKind = "aircraft",
    callsign_prefix: str = "SEQ",
) -> tuple[TrafficTrack, ...]:
    """One track per distance in distances_nm (D11): each starts at
    core.geodesy.final_approach_point(runway, distance, DEFAULT_GLIDESLOPE_DEG)
    — the EXACT function the Position Manager's own final placements call —
    descends down the same glidepath to the threshold, and continues onto the
    runway to a rollout point.

    Timing uses the same convention core/geodesy.py's descent arithmetic is
    built on: in the still air of a placement, ground speed on a final equals
    IAS, so the glidepath leg simply takes distance_nm / ias_kt hours and the
    descent rate that implies is exactly the _profile_setup() formula — no new
    descent-rate maths.

    Raises:
        ValueError: for a non-positive approach speed or distance.
    """
    speed_kt = APPROACH_CATEGORY_VAT_KT[category] if ias_kt is None else ias_kt
    if speed_kt <= 0.0:
        raise ValueError(f"ias_kt must be a positive speed in knots, got {speed_kt!r}.")

    threshold = GeoPosition(
        latitude=runway.threshold.latitude,
        longitude=runway.threshold.longitude,
        altitude_ft=runway.elevation_ft,
    )
    # The rollout ends half the pavement down the runway — far enough to be
    # clearly a landed aircraft, never past the far end.
    rollout_distance_nm = (runway.length_m / 2.0) / METRES_PER_NAUTICAL_MILE
    rollout_point = point_at_distance_and_bearing(
        threshold, rollout_distance_nm, runway.true_bearing_deg
    )

    tracks: list[TrafficTrack] = []
    for index, distance_nm in enumerate(distances_nm):
        if distance_nm <= 0.0:
            raise ValueError(f"distances_nm must be positive, got {distance_nm!r}.")
        start = final_approach_point(runway, distance_nm, DEFAULT_GLIDESLOPE_DEG)
        t_threshold_s = distance_nm / speed_kt * _SECONDS_PER_HOUR
        # The ground roll decelerates from approach speed towards a stop, so
        # the leg is timed at half the approach speed — its average.
        t_rollout_s = t_threshold_s + rollout_distance_nm / (speed_kt / 2.0) * _SECONDS_PER_HOUR
        tracks.append(
            TrafficTrack(
                kind=kind,
                scenario_shape="approach_sequence",
                callsign=f"{callsign_prefix}{index + 1:02d}",
                label=f"{runway.airport_icao} {runway.ident} final, {distance_nm:g} NM",
                waypoints=(
                    TrafficWaypoint(position=start, speed_kt=speed_kt, t_offset_s=0.0),
                    TrafficWaypoint(
                        position=threshold,
                        speed_kt=speed_kt,
                        t_offset_s=t_threshold_s,
                        on_ground=True,
                    ),
                    TrafficWaypoint(
                        position=rollout_point,
                        speed_kt=0.0,
                        t_offset_s=t_rollout_s,
                        on_ground=True,
                    ),
                ),
            )
        )
    return tuple(tracks)


def taxi_traffic_track(
    route: tuple[GeoPosition, ...],
    *,
    speed_kt: float = TAXI_DEFAULT_SPEED_KT,
    kind: TrafficKind = "aircraft",
    callsign: str = "TAXI01",
    label: str = "taxi traffic",
) -> TrafficTrack:
    """Turn an ordered list of ground points into a timed track at a constant
    speed. Every waypoint is on_ground=True. t_offset_s accumulates from the
    geodesic distance between consecutive points divided by speed_kt — no
    routing is invented; the caller (map clicks, or a scenario's own point
    list) supplies the path (D12, §10.5).

    Raises:
        ValueError: for fewer than two route points or a non-positive speed.
    """
    if len(route) < 2:
        raise ValueError(f"A taxi route needs at least 2 points, got {len(route)}.")
    if speed_kt <= 0.0:
        raise ValueError(f"speed_kt must be a positive speed in knots, got {speed_kt!r}.")

    waypoints: list[TrafficWaypoint] = []
    t_offset_s = 0.0
    for index, point in enumerate(route):
        if index > 0:
            leg_distance_nm, _ = distance_and_bearing(route[index - 1], point)
            t_offset_s += leg_distance_nm / speed_kt * _SECONDS_PER_HOUR
        is_last = index == len(route) - 1
        waypoints.append(
            TrafficWaypoint(
                position=point,
                speed_kt=0.0 if is_last else speed_kt,
                t_offset_s=t_offset_s,
                on_ground=True,
            )
        )
    return TrafficTrack(
        kind=kind,
        scenario_shape="taxi_traffic",
        callsign=callsign,
        label=label,
        waypoints=tuple(waypoints),
    )
