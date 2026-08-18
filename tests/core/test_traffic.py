"""Numeric tests for the AI-traffic vocabulary and geometry builders.

Written from ``docs/designs/ai-traffic.md`` §8.1, before the implementation —
the numbers here are checked against independently computed reference values,
never against the implementation's own output:

* 10 NM flown in 180 s is a 200.0 kt ground speed, exactly.
* A user 6.0 NM out at a sea-level TAS of 120 kt arrives in
  ``6.0 / 120.0 * 3600 = 180.0`` s.
* A 3° glidepath at 10 NM is ``tan(3°) * 10 * 6076.115486 ≈ 3184.4`` ft.
"""

from itertools import pairwise

import pytest
from pydantic import TypeAdapter, ValidationError

from core.atmosphere import tas_from_ias
from core.geodesy import (
    distance_and_bearing,
    glideslope_altitude_ft,
    point_at_distance_and_bearing,
)
from core.models import AircraftState, GeoPosition, Runway
from core.traffic import (
    TCAS_SEVERITY_PROFILES,
    ApproachSequenceSpawnRequest,
    CustomTrackSpawnRequest,
    RunwayIncursionSpawnRequest,
    TaxiTrafficSpawnRequest,
    TcasConflictSpawnRequest,
    TrafficSpawnRequest,
    TrafficTrack,
    TrafficWaypoint,
    approach_sequence_tracks,
    interpolate_track,
    runway_incursion_track,
    taxi_traffic_track,
    tcas_conflict_track,
)

# --------------------------------------------------------------------------
# Reference geometry, built independently of any builder under test
# --------------------------------------------------------------------------

#: Start of the interpolation reference track (design §8.1).
TRACK_START = GeoPosition(latitude=40.0, longitude=-3.0, altitude_ft=5000.0)

#: End of that track: exactly 10 NM due east, same altitude — so the leg is a
#: straight, level geodesic whose length is known by construction.
TRACK_END = point_at_distance_and_bearing(TRACK_START, 10.0, 90.0)

#: The leg is flown in 180 s: 10 NM / 180 s * 3600 s/h = 200.0 kt, exactly.
LEG_TIME_S = 180.0
DERIVED_GROUND_SPEED_KT = 200.0


def _reference_track() -> TrafficTrack:
    """The §8.1 two-waypoint track.

    The waypoints' own ``speed_kt`` fields are deliberately NOT the 200 kt the
    leg's distance/time implies, so a ``ground_speed_kt`` that was copied from
    either waypoint instead of derived from the pair is caught, not blessed.
    """
    return TrafficTrack(
        kind="aircraft",
        callsign="TFC01",
        label="interpolation reference leg",
        waypoints=(
            TrafficWaypoint(position=TRACK_START, speed_kt=250.0, t_offset_s=0.0),
            TrafficWaypoint(position=TRACK_END, speed_kt=180.0, t_offset_s=LEG_TIME_S),
        ),
    )


def _waypoint_at(track: TrafficTrack, t_offset_s: float) -> TrafficWaypoint:
    """The waypoint reached at exactly ``t_offset_s``, or a loud failure."""
    for waypoint in track.waypoints:
        if waypoint.t_offset_s == pytest.approx(t_offset_s, abs=1e-6):
            return waypoint
    pytest.fail(
        f"no waypoint at t_offset_s={t_offset_s}; "
        f"track has {[waypoint.t_offset_s for waypoint in track.waypoints]}"
    )


# --------------------------------------------------------------------------
# Model validation
# --------------------------------------------------------------------------


def test_track_first_waypoint_must_be_at_t_zero() -> None:
    """Spawn is t=0: a track starting anywhere else is rejected by the model."""
    with pytest.raises(ValidationError):
        TrafficTrack(
            kind="aircraft",
            callsign="TFC01",
            label="starts late",
            waypoints=(
                TrafficWaypoint(position=TRACK_START, speed_kt=100.0, t_offset_s=5.0),
                TrafficWaypoint(position=TRACK_END, speed_kt=100.0, t_offset_s=10.0),
            ),
        )


def test_track_waypoints_must_be_strictly_time_ordered() -> None:
    with pytest.raises(ValidationError):
        TrafficTrack(
            kind="aircraft",
            callsign="TFC01",
            label="out of order",
            waypoints=(
                TrafficWaypoint(position=TRACK_START, speed_kt=100.0, t_offset_s=0.0),
                TrafficWaypoint(position=TRACK_END, speed_kt=100.0, t_offset_s=60.0),
                TrafficWaypoint(position=TRACK_START, speed_kt=100.0, t_offset_s=30.0),
            ),
        )


def test_track_waypoints_may_not_tie_on_time() -> None:
    """Two waypoints at the same instant is a contradiction, not a hold."""
    with pytest.raises(ValidationError):
        TrafficTrack(
            kind="aircraft",
            callsign="TFC01",
            label="tied offsets",
            waypoints=(
                TrafficWaypoint(position=TRACK_START, speed_kt=100.0, t_offset_s=0.0),
                TrafficWaypoint(position=TRACK_END, speed_kt=100.0, t_offset_s=0.0),
            ),
        )


#: One valid payload per ``type`` discriminator value, and the request class
#: each must resolve to.
_SPAWN_REQUEST_PAYLOADS: list[tuple[dict[str, object], type]] = [
    ({"type": "tcas_conflict"}, TcasConflictSpawnRequest),
    (
        {"type": "runway_incursion", "airport_icao": "LEMD", "runway_ident": "32L"},
        RunwayIncursionSpawnRequest,
    ),
    (
        {
            "type": "approach_sequence",
            "airport_icao": "LEMD",
            "runway_ident": "32L",
            "distances_nm": [10.0],
        },
        ApproachSequenceSpawnRequest,
    ),
    (
        {
            "type": "taxi_traffic",
            "route": [
                {"latitude": 40.0, "longitude": -3.0},
                {"latitude": 40.01, "longitude": -3.0},
            ],
        },
        TaxiTrafficSpawnRequest,
    ),
    ({"type": "custom", "track": _reference_track().model_dump()}, CustomTrackSpawnRequest),
]


@pytest.mark.parametrize(
    ("payload", "expected_type"),
    _SPAWN_REQUEST_PAYLOADS,
    ids=[str(payload["type"]) for payload, _ in _SPAWN_REQUEST_PAYLOADS],
)
def test_spawn_request_round_trips_through_its_discriminator(
    payload: dict[str, object], expected_type: type
) -> None:
    """Every ``type`` value resolves to its own request class, and survives a dump."""
    adapter: TypeAdapter[TrafficSpawnRequest] = TypeAdapter(TrafficSpawnRequest)
    request = adapter.validate_python(payload)
    assert type(request) is expected_type
    assert adapter.validate_python(request.model_dump()) == request


def test_spawn_request_rejects_an_unknown_type() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(TrafficSpawnRequest).validate_python({"type": "flock_of_geese"})


#: Every optional speed field across the request union, with a zero value.
#: Zero is never a meaningful speed there — ``None`` already means "use the
#: default" — so the schema itself refuses it (the server's 422) instead of
#: letting a degenerate motionless entity be built.
_ZERO_SPEED_PAYLOADS: list[dict[str, object]] = [
    {"type": "tcas_conflict", "closure_ias_kt": 0.0},
    {
        "type": "runway_incursion",
        "airport_icao": "LEMD",
        "runway_ident": "32L",
        "vehicle_speed_kt": 0.0,
    },
    {
        "type": "approach_sequence",
        "airport_icao": "LEMD",
        "runway_ident": "32L",
        "distances_nm": [10.0],
        "ias_kt": 0.0,
    },
    {
        "type": "taxi_traffic",
        "route": [
            {"latitude": 40.0, "longitude": -3.0},
            {"latitude": 40.01, "longitude": -3.0},
        ],
        "speed_kt": 0.0,
    },
]


@pytest.mark.parametrize(
    "payload",
    _ZERO_SPEED_PAYLOADS,
    ids=[str(payload["type"]) for payload in _ZERO_SPEED_PAYLOADS],
)
def test_spawn_request_speed_fields_reject_zero(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(TrafficSpawnRequest).validate_python(payload)


# --------------------------------------------------------------------------
# interpolate_track
# --------------------------------------------------------------------------


def test_interpolate_at_zero_is_the_first_waypoint() -> None:
    sample = interpolate_track(_reference_track(), 0.0)
    assert sample.position.latitude == pytest.approx(TRACK_START.latitude, abs=1e-9)
    assert sample.position.longitude == pytest.approx(TRACK_START.longitude, abs=1e-9)
    assert sample.position.altitude_ft == pytest.approx(TRACK_START.altitude_ft, abs=1e-6)


def test_interpolate_halfway_in_time_is_halfway_in_distance() -> None:
    """Constant speed along the leg: 90 of 180 s is 5.0 of 10.0 NM, due east."""
    sample = interpolate_track(_reference_track(), LEG_TIME_S / 2.0)
    distance_nm, bearing_deg = distance_and_bearing(TRACK_START, sample.position)
    assert distance_nm == pytest.approx(5.0, abs=1e-3)
    assert bearing_deg == pytest.approx(90.0, abs=0.1)
    assert sample.position.altitude_ft == pytest.approx(5000.0, abs=0.1)


def test_interpolate_at_the_last_offset_is_the_last_waypoint() -> None:
    sample = interpolate_track(_reference_track(), LEG_TIME_S)
    assert sample.position.latitude == pytest.approx(TRACK_END.latitude, abs=1e-9)
    assert sample.position.longitude == pytest.approx(TRACK_END.longitude, abs=1e-9)
    assert sample.position.altitude_ft == pytest.approx(TRACK_END.altitude_ft, abs=1e-6)


def test_interpolate_past_the_end_holds_the_last_waypoint() -> None:
    sample = interpolate_track(_reference_track(), 300.0)
    assert sample.position.latitude == pytest.approx(TRACK_END.latitude, abs=1e-9)
    assert sample.position.longitude == pytest.approx(TRACK_END.longitude, abs=1e-9)
    assert sample.position.altitude_ft == pytest.approx(TRACK_END.altitude_ft, abs=1e-6)


@pytest.mark.parametrize("elapsed_s", [45.0, 90.0, 135.0])
def test_interpolate_derives_the_ground_speed_from_the_leg(elapsed_s: float) -> None:
    """10 NM in 180 s is 200.0 kt — derived from the pair, never copied.

    The reference track's waypoints state 250 and 180 kt precisely so that a
    ``ground_speed_kt`` echoing either field back fails here.
    """
    sample = interpolate_track(_reference_track(), elapsed_s)
    assert sample.ground_speed_kt == pytest.approx(DERIVED_GROUND_SPEED_KT, abs=1e-6)


# --------------------------------------------------------------------------
# tcas_conflict_track
# --------------------------------------------------------------------------

#: The §8.1 user aircraft: level at 10 000 ft, heading due east at 250 KIAS.
TCAS_USER = AircraftState(
    latitude=40.0,
    longitude=-3.0,
    altitude_ft=10_000.0,
    heading_deg=90.0,
    ias_kt=250.0,
    vertical_speed_fpm=0.0,
    pitch_deg=0.0,
    roll_deg=0.0,
)


def _user_projected_position(lead_time_s: float) -> GeoPosition:
    """Where the §8.1 user aircraft is ``lead_time_s`` after spawn.

    Computed independently of the builder: current ground speed is
    ``tas_from_ias`` (the still-air approximation the whole project makes),
    carried along the current heading — never a hard-coded coordinate.
    """
    ground_speed_kt = tas_from_ias(TCAS_USER.ias_kt, TCAS_USER.altitude_ft)
    return point_at_distance_and_bearing(
        GeoPosition(
            latitude=TCAS_USER.latitude,
            longitude=TCAS_USER.longitude,
            altitude_ft=TCAS_USER.altitude_ft,
        ),
        ground_speed_kt * lead_time_s / 3600.0,
        TCAS_USER.heading_deg,
    )


def test_head_on_ra_cpa_is_exactly_the_users_projected_position() -> None:
    """Zero miss distances: at CPA time the intruder IS where the user will be."""
    profile = TCAS_SEVERITY_PROFILES["head_on_ra"]
    track = tcas_conflict_track(TCAS_USER, severity="head_on_ra")

    cpa_waypoint = _waypoint_at(track, profile.spawn_lead_time_s)
    user_at_cpa = _user_projected_position(profile.spawn_lead_time_s)
    miss_nm, _ = distance_and_bearing(user_at_cpa, cpa_waypoint.position)
    assert miss_nm == pytest.approx(0.0, abs=1e-4)
    assert cpa_waypoint.position.altitude_ft == pytest.approx(TCAS_USER.altitude_ft, abs=1e-6)


def test_head_on_ra_intruder_track_is_the_reciprocal_heading() -> None:
    """relative_bearing 180° off a 90° user heading is an intruder tracking 270°."""
    track = tcas_conflict_track(TCAS_USER, severity="head_on_ra")
    _, bearing_deg = distance_and_bearing(track.waypoints[0].position, track.waypoints[1].position)
    assert bearing_deg == pytest.approx(270.0, abs=0.5)


def test_ta_only_offsets_read_straight_off_the_severity_table() -> None:
    """``ta_only`` misses by exactly the profile's 500 ft / 0.5 NM — a pin on
    ``TCAS_SEVERITY_PROFILES``, not a re-derivation of it."""
    profile = TCAS_SEVERITY_PROFILES["ta_only"]
    track = tcas_conflict_track(TCAS_USER, severity="ta_only")

    cpa_waypoint = _waypoint_at(track, profile.spawn_lead_time_s)
    user_at_cpa = _user_projected_position(profile.spawn_lead_time_s)

    horizontal_miss_nm, _ = distance_and_bearing(user_at_cpa, cpa_waypoint.position)
    assert horizontal_miss_nm == pytest.approx(profile.horizontal_miss_distance_nm, abs=1e-3)
    # vertical_offset defaults to "above": the intruder crosses 500 ft over.
    vertical_miss_ft = cpa_waypoint.position.altitude_ft - TCAS_USER.altitude_ft
    assert vertical_miss_ft == pytest.approx(profile.vertical_miss_distance_ft, abs=0.1)


def test_tcas_conflict_refuses_a_non_positive_closure_speed() -> None:
    """The same guard the three sibling builders have: a motionless "intruder"
    is three co-located waypoints, not a conflict."""
    with pytest.raises(ValueError, match="closure_ias_kt"):
        tcas_conflict_track(TCAS_USER, closure_ias_kt=0.0)


# --------------------------------------------------------------------------
# runway_incursion_track
# --------------------------------------------------------------------------

#: A due-north, sea-level runway with its threshold at (0, 0): every distance
#: and bearing below is readable by eye, and ``tas_from_ias(ias, 0.0)`` is the
#: indicated speed exactly, so the arrival-time arithmetic has no density term.
SEA_LEVEL_RUNWAY = Runway(
    airport_icao="TEST",
    ident="36",
    threshold=GeoPosition(latitude=0.0, longitude=0.0, altitude_ft=0.0),
    true_bearing_deg=0.0,
    length_m=3000.0,
    elevation_ft=0.0,
)


def _incursion_user() -> AircraftState:
    """The §8.1 user: 6.0 NM due south of the threshold, inbound at 120 KIAS.

    6.0 NM at a 120 kt sea-level TAS is ``6.0 / 120.0 * 3600 = 180.0`` s to
    the threshold — the worked reference value every assertion below leans on.
    """
    position = point_at_distance_and_bearing(SEA_LEVEL_RUNWAY.threshold, 6.0, 180.0)
    return AircraftState(
        latitude=position.latitude,
        longitude=position.longitude,
        altitude_ft=0.0,
        heading_deg=0.0,
        ias_kt=120.0,
        vertical_speed_fpm=0.0,
        pitch_deg=0.0,
        roll_deg=0.0,
    )


def _crossing_waypoint(track: TrafficTrack, crossing_point: GeoPosition) -> TrafficWaypoint:
    """The waypoint sitting on the centreline crossing point itself."""
    nearest = min(
        track.waypoints,
        key=lambda waypoint: distance_and_bearing(crossing_point, waypoint.position)[0],
    )
    offset_nm, _ = distance_and_bearing(crossing_point, nearest.position)
    assert offset_nm == pytest.approx(0.0, abs=1e-3), (
        f"no waypoint lies on the crossing point: the closest is {offset_nm:.4f} NM away"
    )
    return nearest


def test_incursion_crossing_time_is_the_users_arrival_minus_the_lead() -> None:
    """t_user_arrival 180.0 s, lead 20.0 s → the vehicle crosses at 160.0 s."""
    track = runway_incursion_track(
        SEA_LEVEL_RUNWAY, _incursion_user(), lead_time_before_user_arrival_s=20.0
    )
    crossing = _crossing_waypoint(track, SEA_LEVEL_RUNWAY.threshold)
    assert crossing.t_offset_s == pytest.approx(160.0, abs=1e-3)


def test_incursion_crossing_time_clamps_at_zero() -> None:
    """A lead longer than the arrival itself crosses at t=0.0, never negative."""
    track = runway_incursion_track(
        SEA_LEVEL_RUNWAY, _incursion_user(), lead_time_before_user_arrival_s=200.0
    )
    crossing = _crossing_waypoint(track, SEA_LEVEL_RUNWAY.threshold)
    assert crossing.t_offset_s == 0.0


# --------------------------------------------------------------------------
# approach_sequence_tracks
# --------------------------------------------------------------------------


def test_single_approach_spawn_sits_on_the_three_degree_glidepath() -> None:
    """10 NM out on a 3° path over a 0 ft threshold: tan(3°) * 10 * 6076.115486
    ≈ 3184.4 ft, within the 0.5 ft tolerance the geodesy suite already uses."""
    (track,) = approach_sequence_tracks(SEA_LEVEL_RUNWAY, distances_nm=(10.0,))
    spawn = track.waypoints[0]
    assert spawn.position.altitude_ft == pytest.approx(3184.4, abs=0.5)
    assert spawn.position.altitude_ft == pytest.approx(
        glideslope_altitude_ft(0.0, 10.0, 3.0), abs=0.5
    )


def test_approach_sequence_builds_one_track_per_distance() -> None:
    distances_nm = (12.0, 8.0, 4.0)
    tracks = approach_sequence_tracks(SEA_LEVEL_RUNWAY, distances_nm=distances_nm)
    assert len(tracks) == 3
    for distance_nm, track in zip(distances_nm, tracks, strict=True):
        spawn = track.waypoints[0]
        assert spawn.position.altitude_ft == pytest.approx(
            glideslope_altitude_ft(0.0, distance_nm, 3.0), abs=0.5
        )


# --------------------------------------------------------------------------
# taxi_traffic_track
# --------------------------------------------------------------------------


def test_taxi_track_accumulates_time_from_leg_lengths() -> None:
    """t_offset_s at each point is exactly the accumulated leg time.

    The route's leg lengths are known by construction (0.2 NM then 0.3 NM),
    and re-measured in the test with ``distance_and_bearing`` so the expected
    offsets are computed independently: at 12 kt, 60.0 s and then 150.0 s.
    """
    speed_kt = 12.0
    first = GeoPosition(latitude=40.0, longitude=-3.0, altitude_ft=0.0)
    second = point_at_distance_and_bearing(first, 0.2, 90.0)
    third = point_at_distance_and_bearing(second, 0.3, 0.0)
    route = (first, second, third)

    track = taxi_traffic_track(route, speed_kt=speed_kt)

    expected_offsets = [0.0]
    for a, b in pairwise(route):
        leg_nm, _ = distance_and_bearing(a, b)
        expected_offsets.append(expected_offsets[-1] + leg_nm / speed_kt * 3600.0)
    assert expected_offsets[1] == pytest.approx(60.0, abs=1e-6)
    assert expected_offsets[2] == pytest.approx(150.0, abs=1e-6)

    assert [waypoint.t_offset_s for waypoint in track.waypoints] == pytest.approx(
        expected_offsets, abs=1e-6
    )


def test_taxi_track_is_entirely_on_the_ground() -> None:
    first = GeoPosition(latitude=40.0, longitude=-3.0, altitude_ft=0.0)
    second = point_at_distance_and_bearing(first, 0.2, 90.0)
    track = taxi_traffic_track((first, second))
    assert all(waypoint.on_ground for waypoint in track.waypoints)
