"""Tests for the world ↔ local Cartesian frame conversion.

The headline cases are not synthetic. They are a **real sample measured from a
live X-Plane 12** parked at LEMD on 2026-08-06: the aircraft's world position
and its local-frame coordinates read in the same breath, plus the frame origin
recovered from them. Anything that breaks the conversion breaks these numbers.
"""

import math

import pytest

from core.geodesy import METRES_PER_NAUTICAL_MILE, distance_and_bearing
from core.local_frame import (
    LocalCoordinates,
    LocalFrameOrigin,
    local_to_world,
    origin_from_observation,
    origin_separation_m,
    world_to_local,
)
from core.models import GeoPosition

METRES_PER_FOOT = 0.3048

# --- The live calibration sample -------------------------------------------
# Read together from sim/flightmodel/position/{latitude,longitude,elevation}
# and .../{local_x,local_y,local_z} with the aircraft stationary at LEMD.
MEASURED_WORLD = GeoPosition(
    latitude=40.4566000814581,
    longitude=-3.5472865427878104,
    altitude_ft=581.9972664408039 / METRES_PER_FOOT,
)
MEASURED_LOCAL = LocalCoordinates(
    x_m=38403.6368185892,
    y_m=464.18933994981984,
    z_m=4721.243450821352,
)
#: The origin those two imply — X-Plane had anchored its frame at (40.5, -4.0),
#: 38.7 km from the aircraft.
MEASURED_ORIGIN = LocalFrameOrigin(
    latitude=40.500000406827404,
    longitude=-4.000003664115367,
    vertical_offset_m=-0.6120839158223248,
)


def test_origin_recovered_from_the_live_sample() -> None:
    """One (world, local) pair pins the frame down to centimetres."""
    origin = origin_from_observation(MEASURED_WORLD, MEASURED_LOCAL)

    # 1e-7 degrees is about 1 cm of latitude.
    assert origin.latitude == pytest.approx(MEASURED_ORIGIN.latitude, abs=1e-7)
    assert origin.longitude == pytest.approx(MEASURED_ORIGIN.longitude, abs=1e-7)
    assert origin.vertical_offset_m == pytest.approx(MEASURED_ORIGIN.vertical_offset_m, abs=1e-6)


def test_recovered_origin_is_the_one_the_sim_reported_rounded() -> None:
    """Sanity check on the recovered origin: X-Plane anchored at (40.5, -4.0)."""
    origin = origin_from_observation(MEASURED_WORLD, MEASURED_LOCAL)
    assert origin.latitude == pytest.approx(40.5, abs=1e-5)
    assert origin.longitude == pytest.approx(-4.0, abs=1e-5)


def test_world_to_local_reproduces_the_measured_coordinates() -> None:
    """The calibration case: project the sample and land on what the sim said."""
    local = world_to_local(MEASURED_ORIGIN, MEASURED_WORLD)

    assert local.x_m == pytest.approx(MEASURED_LOCAL.x_m, abs=0.001)
    assert local.y_m == pytest.approx(MEASURED_LOCAL.y_m, abs=0.001)
    assert local.z_m == pytest.approx(MEASURED_LOCAL.z_m, abs=0.001)


def test_local_to_world_reproduces_the_measured_position() -> None:
    """The same case, inverted."""
    world = local_to_world(MEASURED_ORIGIN, MEASURED_LOCAL)

    assert world.latitude == pytest.approx(MEASURED_WORLD.latitude, abs=1e-9)
    assert world.longitude == pytest.approx(MEASURED_WORLD.longitude, abs=1e-9)
    assert world.altitude_ft == pytest.approx(MEASURED_WORLD.altitude_ft, abs=1e-6)


def test_round_trip_world_local_world() -> None:
    """Converting out and back changes nothing that matters."""
    for latitude, longitude, altitude_ft in (
        (40.4566, -3.5473, 1909.0),
        (40.5399, -3.5473, 3909.0),  # the 5 NM north / +2000 ft teleport target
        (0.0, 0.0, 0.0),
        (-33.9461, 151.1772, 21.0),  # YSSY, southern hemisphere
        (78.2461, 15.4656, 88.0),  # ENSB, high latitude
    ):
        position = GeoPosition(latitude=latitude, longitude=longitude, altitude_ft=altitude_ft)
        origin = LocalFrameOrigin(latitude=round(latitude), longitude=round(longitude))

        result = local_to_world(origin, world_to_local(origin, position))

        assert result.latitude == pytest.approx(position.latitude, abs=1e-9)
        assert result.longitude == pytest.approx(position.longitude, abs=1e-9)
        assert result.altitude_ft == pytest.approx(position.altitude_ft, abs=1e-5)


def test_round_trip_local_world_local() -> None:
    """The inverse round trip, including a vertical offset."""
    origin = MEASURED_ORIGIN
    for x_m, y_m, z_m in (
        (0.0, 0.0, 0.0),
        (38403.6, 464.2, 4721.2),
        (-12000.0, 3000.0, -45000.0),
    ):
        local = LocalCoordinates(x_m=x_m, y_m=y_m, z_m=z_m)

        result = world_to_local(origin, local_to_world(origin, local))

        assert result.x_m == pytest.approx(local.x_m, abs=1e-6)
        assert result.y_m == pytest.approx(local.y_m, abs=1e-6)
        assert result.z_m == pytest.approx(local.z_m, abs=1e-6)


def test_the_origin_itself_maps_to_the_frame_zero() -> None:
    """At the anchor point the frame reads (0, offset, 0) by construction."""
    origin = LocalFrameOrigin(latitude=40.5, longitude=-4.0)
    at_origin = GeoPosition(latitude=40.5, longitude=-4.0, altitude_ft=0.0)

    local = world_to_local(origin, at_origin)

    assert local.x_m == pytest.approx(0.0, abs=1e-9)
    assert local.y_m == pytest.approx(0.0, abs=1e-9)
    assert local.z_m == pytest.approx(0.0, abs=1e-9)


def test_axis_signs_are_east_up_south() -> None:
    """+x east, +y up, +z south — the convention the whole module rests on."""
    origin = LocalFrameOrigin(latitude=40.5, longitude=-4.0)

    east = world_to_local(origin, GeoPosition(latitude=40.5, longitude=-3.9))
    north = world_to_local(origin, GeoPosition(latitude=40.6, longitude=-4.0))
    high = world_to_local(origin, GeoPosition(latitude=40.5, longitude=-4.0, altitude_ft=1000.0))

    assert east.x_m > 0.0
    assert north.z_m < 0.0, "north must be negative z"
    assert high.y_m == pytest.approx(1000.0 * METRES_PER_FOOT, abs=0.001)


def test_horizontal_distance_matches_the_geodesic() -> None:
    """The frame is metric and true to scale over a teleport-sized hop."""
    origin = LocalFrameOrigin(latitude=40.5, longitude=-4.0)
    start = GeoPosition(latitude=40.4566, longitude=-3.5473)
    finish = GeoPosition(latitude=40.5399903, longitude=-3.5472865)

    a = world_to_local(origin, start)
    b = world_to_local(origin, finish)
    frame_distance_m = math.hypot(b.x_m - a.x_m, b.z_m - a.z_m)

    geodesic_nm, _ = distance_and_bearing(start, finish)
    assert frame_distance_m == pytest.approx(geodesic_nm * METRES_PER_NAUTICAL_MILE, abs=1.0)


def test_curvature_is_modelled_not_ignored() -> None:
    """A point 38.7 km out sits ~117 m below the origin's tangent plane.

    This is the term a flat-earth conversion drops, and it is the difference
    between arriving at the requested altitude and arriving inside a hill.
    """
    local = world_to_local(MEASURED_ORIGIN, MEASURED_WORLD)
    elevation_m = MEASURED_WORLD.altitude_ft * METRES_PER_FOOT

    drop_m = elevation_m - local.y_m
    assert drop_m == pytest.approx(117.8, abs=1.0)


def test_vertical_offset_shifts_only_the_up_axis() -> None:
    """The offset is a pure vertical datum shift, not a rotation."""
    plain = LocalFrameOrigin(latitude=40.5, longitude=-4.0)
    shifted = LocalFrameOrigin(latitude=40.5, longitude=-4.0, vertical_offset_m=-0.61)

    a = world_to_local(plain, MEASURED_WORLD)
    b = world_to_local(shifted, MEASURED_WORLD)

    assert b.x_m == pytest.approx(a.x_m)
    assert b.z_m == pytest.approx(a.z_m)
    assert b.y_m == pytest.approx(a.y_m - 0.61)


def test_origin_recovery_works_when_the_sample_sits_on_the_origin() -> None:
    """Degenerate but legal: the search must not divide by a zero residual."""
    position = GeoPosition(latitude=12.5, longitude=-70.0, altitude_ft=100.0)
    local = world_to_local(LocalFrameOrigin(latitude=12.5, longitude=-70.0), position)

    origin = origin_from_observation(position, local)

    assert origin.latitude == pytest.approx(12.5, abs=1e-9)
    assert origin.longitude == pytest.approx(-70.0, abs=1e-9)


def test_origin_separation_is_zero_for_the_same_frame() -> None:
    """Two measurements of an unmoved frame must not look like a relocation."""
    assert origin_separation_m(MEASURED_ORIGIN, MEASURED_ORIGIN) == pytest.approx(0.0, abs=1e-9)


def test_origin_separation_measures_a_scenery_shift() -> None:
    """The case it exists for: LEMD's frame against Heathrow's, ~1250 km apart.

    This is the comparison ``XPlaneSimAdapter`` makes to decide whether the
    frame it aimed a teleport in still exists (issue #36).
    """
    madrid = LocalFrameOrigin(latitude=40.5, longitude=-4.0)
    heathrow = LocalFrameOrigin(latitude=51.5, longitude=-0.5)

    separation_m = origin_separation_m(madrid, heathrow)

    geodesic_nm, _ = distance_and_bearing(
        GeoPosition(latitude=40.5, longitude=-4.0),
        GeoPosition(latitude=51.5, longitude=-0.5),
    )
    # The chord, so it comes in a little under the surface distance — 0.1 % at
    # this range, which is why the function does not need a geodesic solve.
    assert separation_m == pytest.approx(geodesic_nm * METRES_PER_NAUTICAL_MILE, rel=2e-3)
    assert separation_m > 1_200_000.0


def test_origin_separation_agrees_with_the_geodesic_at_a_teleport_scale() -> None:
    """At the ranges that matter the chord and the geodesic are interchangeable."""
    origin = LocalFrameOrigin(latitude=40.5, longitude=-4.0)
    for latitude, longitude in ((40.6, -4.0), (40.5, -3.0), (41.5, -5.0)):
        moved = LocalFrameOrigin(latitude=latitude, longitude=longitude)
        geodesic_nm, _ = distance_and_bearing(
            GeoPosition(latitude=40.5, longitude=-4.0),
            GeoPosition(latitude=latitude, longitude=longitude),
        )
        assert origin_separation_m(origin, moved) == pytest.approx(
            geodesic_nm * METRES_PER_NAUTICAL_MILE, rel=1e-3
        )


def test_origin_separation_counts_the_vertical_datum() -> None:
    """Same anchor, different vertical offset, is still a different frame.

    Treating the two as equal would leave a re-aimed teleport at the wrong
    altitude while every horizontal check passed.
    """
    plain = LocalFrameOrigin(latitude=40.5, longitude=-4.0)
    shifted = LocalFrameOrigin(latitude=40.5, longitude=-4.0, vertical_offset_m=-120.0)

    assert origin_separation_m(plain, shifted) == pytest.approx(120.0, abs=1e-6)


def test_origin_separation_is_symmetric() -> None:
    a = LocalFrameOrigin(latitude=40.5, longitude=-4.0, vertical_offset_m=-0.61)
    b = LocalFrameOrigin(latitude=51.5, longitude=-0.5, vertical_offset_m=3.2)

    assert origin_separation_m(a, b) == pytest.approx(origin_separation_m(b, a))


def test_origin_recovery_round_trips_from_a_distant_frame() -> None:
    """Recover an origin 200 km away and reproduce the sample through it."""
    truth = LocalFrameOrigin(latitude=39.0, longitude=-6.0, vertical_offset_m=2.5)
    position = GeoPosition(latitude=40.4566, longitude=-3.5473, altitude_ft=1909.0)
    local = world_to_local(truth, position)

    recovered = origin_from_observation(position, local)

    assert recovered.latitude == pytest.approx(truth.latitude, abs=1e-7)
    assert recovered.longitude == pytest.approx(truth.longitude, abs=1e-7)
    assert recovered.vertical_offset_m == pytest.approx(truth.vertical_offset_m, abs=1e-4)
    again = world_to_local(recovered, position)
    assert again.x_m == pytest.approx(local.x_m, abs=1e-3)
    assert again.y_m == pytest.approx(local.y_m, abs=1e-3)
    assert again.z_m == pytest.approx(local.z_m, abs=1e-3)
