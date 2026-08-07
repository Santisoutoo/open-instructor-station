"""The runway threshold convention, pinned with real LEMD 18L numbers.

``Runway.threshold`` is the **displaced landing threshold** and ``length_m`` is
the **pavement length**. Two navdata sources populate this model with different
conventions — the CIFP ``RWY:`` record publishes the displaced threshold,
``apt.dat`` publishes the pavement end — so conflating them is not a
hypothetical: it is the default outcome of not looking.

Every number below comes from real LEMD 18L data, quoted in
``docs/designs/navdata-provider.md``:

* CIFP: ``RWY:RW18L,     ,      ,01922, ,IML ,3,   ;N40314122,W003333368,1640;``
* ``apt.dat``: pavement end ``40.5325838, -3.5593800``, displaced 494 m,
  pavement length 3497.5 m.

The two anchor points are ~496 m apart. On a 10 NM final that is 0.27 NM of
error, so a change that quietly swaps one for the other has to fail here.
"""

import pytest
from geographiclib.geodesic import Geodesic
from pydantic import ValidationError

from core.geodesy import METRES_PER_NAUTICAL_MILE, final_approach_point
from core.models import GeoPosition, Runway

#: Exact, by definition of the international foot.
METRES_PER_FOOT = 0.3048

# --------------------------------------------------------------------------
# LEMD 18L, from the two sources, decoded here rather than assumed
# --------------------------------------------------------------------------


def _dms(degrees: int, minutes: int, seconds: float, *, negative: bool = False) -> float:
    """Packed CIFP ``DDMMSSss`` coordinate as signed decimal degrees.

    The CIFP ``RWY:`` record stores coordinates as ``[NS]DDMMSSss`` /
    ``[EW]DDDMMSSss``, where the trailing two digits are **hundredths of a
    second**. ``N40314122`` is therefore 40° 31' 41.22", not 40° 31' 41.22 mrad
    of anything else.
    """
    value = degrees + minutes / 60.0 + seconds / 3600.0
    return -value if negative else value


#: CIFP ``N40314122,W003333368`` — the displaced landing threshold.
LEMD_18L_CIFP_THRESHOLD = GeoPosition(
    latitude=_dms(40, 31, 41.22),
    longitude=_dms(3, 33, 33.68, negative=True),
    altitude_ft=0.0,
)

#: ``apt.dat`` ``100`` row end coordinate — the start of the pavement.
LEMD_18L_APT_PAVEMENT_END = GeoPosition(
    latitude=40.5325838,
    longitude=-3.5593800,
    altitude_ft=0.0,
)

#: Trailing field of the CIFP ``RWY:`` record: ``1640``. The design doc settles
#: the unit — it is the displaced threshold distance in **feet**, agreeing with
#: ``apt.dat``'s 494 m to within a few metres. Reading it as metres would put
#: the threshold 1.1 km down a 3.5 km runway.
LEMD_18L_CIFP_DISPLACEMENT_FT = 1640.0
LEMD_18L_CIFP_DISPLACEMENT_M = LEMD_18L_CIFP_DISPLACEMENT_FT * METRES_PER_FOOT  # 499.872 m

#: ``apt.dat`` displaced-threshold distance for the same runway end, in metres.
LEMD_18L_APT_DISPLACEMENT_M = 494.0

#: Pavement length between the 18L and 36R end coordinates in ``apt.dat``.
LEMD_18L_PAVEMENT_LENGTH_M = 3497.5

#: CIFP ``RWY:`` field ``01922`` — threshold elevation in feet MSL.
LEMD_18L_THRESHOLD_ELEVATION_FT = 1922.0

#: Geodesic from the 18L end to the 36R end in ``apt.dat``.
LEMD_18L_TRUE_BEARING_DEG = 179.76


def _lemd_18l() -> Runway:
    """LEMD 18L, populated the way the navdata provider is specified to."""
    return Runway(
        airport_icao="LEMD",
        ident="18L",
        threshold=LEMD_18L_CIFP_THRESHOLD,
        true_bearing_deg=LEMD_18L_TRUE_BEARING_DEG,
        length_m=LEMD_18L_PAVEMENT_LENGTH_M,
        elevation_ft=LEMD_18L_THRESHOLD_ELEVATION_FT,
        pavement_end=LEMD_18L_APT_PAVEMENT_END,
        displaced_threshold_m=LEMD_18L_CIFP_DISPLACEMENT_M,
        landing_distance_m=LEMD_18L_PAVEMENT_LENGTH_M - LEMD_18L_CIFP_DISPLACEMENT_M,
    )


def _separation_m(a: GeoPosition, b: GeoPosition) -> tuple[float, float]:
    """``(distance_m, initial_true_bearing_deg)`` between two positions."""
    result = Geodesic.WGS84.Inverse(a.latitude, a.longitude, b.latitude, b.longitude)
    return float(result["s12"]), float(result["azi1"]) % 360.0


# --------------------------------------------------------------------------
# The two anchor points really are different points
# --------------------------------------------------------------------------


def test_cifp_threshold_and_apt_pavement_end_are_496_m_apart() -> None:
    """The whole reason the convention has to be stated: they are not the same point."""
    distance_m, bearing_deg = _separation_m(LEMD_18L_APT_PAVEMENT_END, LEMD_18L_CIFP_THRESHOLD)
    assert pytest.approx(496.06, abs=0.5) == distance_m
    # And it lies *down the runway*, not off to one side: the displacement is
    # along the centreline, so the bearing matches the runway bearing.
    assert pytest.approx(LEMD_18L_TRUE_BEARING_DEG, abs=0.05) == bearing_deg


def test_cifp_displacement_field_is_feet_not_metres() -> None:
    """``1640`` read as feet agrees with apt.dat's 494 m; read as metres it is nonsense."""
    assert pytest.approx(499.872, abs=1e-3) == LEMD_18L_CIFP_DISPLACEMENT_M
    # Three independent sources — apt.dat's metres, the CIFP trailing field and
    # the measured geodesic separation — inside a 6 m band.
    measured_m, _ = _separation_m(LEMD_18L_APT_PAVEMENT_END, LEMD_18L_CIFP_THRESHOLD)
    assert abs(LEMD_18L_CIFP_DISPLACEMENT_M - LEMD_18L_APT_DISPLACEMENT_M) < 6.0
    assert abs(LEMD_18L_CIFP_DISPLACEMENT_M - measured_m) < 6.0
    # Taken as metres it would sit 1.1 km inside a 3.5 km runway. Guard the unit.
    assert LEMD_18L_CIFP_DISPLACEMENT_FT > LEMD_18L_PAVEMENT_LENGTH_M / 3.0


# --------------------------------------------------------------------------
# The model states which is which
# --------------------------------------------------------------------------


def test_threshold_is_the_displaced_landing_threshold() -> None:
    runway = _lemd_18l()
    assert runway.threshold == LEMD_18L_CIFP_THRESHOLD
    assert runway.pavement_end == LEMD_18L_APT_PAVEMENT_END
    assert runway.threshold != runway.pavement_end


def test_length_is_the_pavement_length_and_landing_distance_is_shorter() -> None:
    runway = _lemd_18l()
    assert runway.length_m == LEMD_18L_PAVEMENT_LENGTH_M
    assert runway.landing_distance_m is not None
    assert runway.landing_distance_m < runway.length_m
    assert (
        pytest.approx(runway.displaced_threshold_m, abs=1e-9)
        == runway.length_m - runway.landing_distance_m
    )


def test_threshold_is_the_pavement_end_walked_forward_by_the_displacement() -> None:
    """The relation a source that only knows the pavement end has to apply."""
    runway = _lemd_18l()
    assert runway.pavement_end is not None
    walked = Geodesic.WGS84.Direct(
        runway.pavement_end.latitude,
        runway.pavement_end.longitude,
        runway.true_bearing_deg,
        runway.displaced_threshold_m,
    )
    distance_m, _ = _separation_m(
        GeoPosition(latitude=float(walked["lat2"]), longitude=float(walked["lon2"])),
        runway.threshold,
    )
    # Within the 6 m the three published displacement values disagree by.
    assert distance_m < 6.0


# --------------------------------------------------------------------------
# What conflating them costs, in the geodesy that consumes the model
# --------------------------------------------------------------------------


def test_anchoring_a_ten_mile_final_on_the_pavement_end_is_a_quarter_mile_wrong() -> None:
    """0.27 NM at 10 NM out — the number in issue #40, reproduced end to end."""
    correct = _lemd_18l()
    assert correct.pavement_end is not None
    wrong = correct.model_copy(update={"threshold": correct.pavement_end})

    correct_point = final_approach_point(correct, 10.0)
    wrong_point = final_approach_point(wrong, 10.0)

    error_m, _ = _separation_m(correct_point, wrong_point)
    assert pytest.approx(496.06, abs=0.5) == error_m
    assert pytest.approx(0.27, abs=0.005) == error_m / METRES_PER_NAUTICAL_MILE


# --------------------------------------------------------------------------
# The new fields are additive
# --------------------------------------------------------------------------


def test_runway_without_the_optional_detail_still_validates() -> None:
    """Callers built before the extra fields existed keep working, undisplaced."""
    runway = Runway(
        airport_icao="LEMD",
        ident="18L",
        threshold=LEMD_18L_CIFP_THRESHOLD,
        true_bearing_deg=LEMD_18L_TRUE_BEARING_DEG,
        length_m=LEMD_18L_PAVEMENT_LENGTH_M,
        elevation_ft=LEMD_18L_THRESHOLD_ELEVATION_FT,
    )
    assert runway.pavement_end is None
    assert runway.displaced_threshold_m == 0.0
    assert runway.landing_distance_m is None


def test_runway_stays_frozen_and_hashable() -> None:
    """The model is frozen; the added fields must not cost that."""
    assert Runway.model_config["frozen"] is True
    assert hash(_lemd_18l()) == hash(_lemd_18l())


def test_displacement_cannot_be_negative() -> None:
    """A negative displacement would put the threshold before the pavement."""
    with pytest.raises(ValidationError):
        Runway(
            airport_icao="LEMD",
            ident="18L",
            threshold=LEMD_18L_CIFP_THRESHOLD,
            true_bearing_deg=LEMD_18L_TRUE_BEARING_DEG,
            length_m=LEMD_18L_PAVEMENT_LENGTH_M,
            elevation_ft=LEMD_18L_THRESHOLD_ELEVATION_FT,
            displaced_threshold_m=-1.0,
        )
