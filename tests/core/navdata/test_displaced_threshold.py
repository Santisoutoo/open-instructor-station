"""Both navdata sources must hand back the *displaced landing threshold*.

``Runway.threshold`` is the displaced landing threshold and ``length_m`` is the
pavement length. :mod:`tests.core.test_runway_semantics` pins that convention on
the model; what is pinned **here** is that the two readers which populate the
model actually honour it, because they read sources that publish different
things:

* ``apt.dat`` publishes the **pavement end** plus a displacement, so its reader
  has to walk the end forward along the runway axis;
* the CIFP ``RWY:`` record publishes the **displaced threshold** directly, plus
  the displacement in feet.

Either one silently handing back the pavement end costs 0.27 NM on a 10 NM final
at LEMD 18L, consistently and invisibly: the placement sits exactly on the
extended centreline, at exactly the requested distance, from the wrong origin.

**Every byte fed to a parser below is written in this file.** No ``apt.dat``,
CIFP file or derived index is committed anywhere (hard rule 4); the records are
hand-typed minimal samples in the published formats, and the tree they are
materialised into lives in ``tmp_path`` for the duration of one test. The LEMD
18L values are the published ones quoted in issue #40 and
``docs/designs/navdata-provider.md`` — the same numbers
``tests/core/test_runway_semantics.py`` already asserts on.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from core.geodesy import (
    METRES_PER_NAUTICAL_MILE,
    distance_and_bearing,
    final_approach_point,
)
from core.models import GeoPosition, Runway
from core.navdata.cifp_source import CifpRunway
from core.navdata.xplane_native.apt import ParsedRunwayEnd, iter_airports
from core.navdata.xplane_native.cifp import XPNativeCifpSource, parse_cifp
from core.navdata.xplane_native.provider import XPNativeNavdataProvider

# --------------------------------------------------------------------------
# LEMD 18L, as published
# --------------------------------------------------------------------------

#: Start of the paved surface for 18L. **Not** the point a final is measured
#: from, and the whole subject of this module.
PAVEMENT_END = GeoPosition(latitude=40.5325838, longitude=-3.5593800, altitude_ft=0.0)

#: The far end of the same strip. Derived, not published: it is
#: :data:`PAVEMENT_END` walked 3497.5 m down the published runway bearing, so
#: that a reader computing the pavement length from the two ends gets the
#: published number back and the fixture stays self-consistent.
OPPOSITE_END = GeoPosition(latitude=40.50108772, longitude=-3.55920717, altitude_ft=0.0)

#: Displacement of the 18L landing threshold, in metres, as ``apt.dat`` publishes it.
APT_DISPLACEMENT_M = 494.0

#: The same displacement as the CIFP ``RWY:`` record publishes it: 1640 **feet**.
CIFP_DISPLACEMENT_FT = 1640.0

#: Pavement length between the two ends.
PAVEMENT_LENGTH_M = 3497.5

#: Runway bearing, true degrees.
TRUE_BEARING_DEG = 179.76

#: Threshold elevation, feet MSL, from the CIFP record's field 3.
THRESHOLD_ELEVATION_FT = 1922.0

#: Geodesic separation between the pavement end and the CIFP threshold. The two
#: sources are two surveys, so this is a few metres off both published
#: displacements and two orders of magnitude away from zero — which is the only
#: thing that matters.
MEASURED_DISPLACEMENT_M = 496.06

#: How far apart two *thresholds* from different sources may be before they stop
#: being the same point. Generous next to 496 m, tight next to a pavement end.
SURVEY_TOLERANCE_M = 6.0

#: The CIFP ``RWY:`` record for LEMD 18L, hand-typed from the layout in
#: ``docs/designs/navdata-provider.md``. Field 7 packs the threshold crossing
#: height and the latitude around an embedded ``;``; field 9 is the displacement
#: in feet.
CIFP_TEXT = "RWY:RW18L,     ,      ,01922, ,IML ,3,   ;N40314122,W003333368,1640;\n"


def _apt_text(*, displacement_m: float) -> str:
    """A minimal hand-written ``apt.dat``: one airport, one runway strip.

    The ``100`` row is ``… <ident1> <lat1> <lon1> <displaced1> … <ident2> …``,
    and the coordinates it carries are the **pavement ends**.
    """
    return (
        "I\n"
        "1200 Version - hand-written fixture, not a byte from any installation\n"
        "1    1998 1 0 LEMD Madrid Barajas\n"
        "1302 icao_code LEMD\n"
        "1302 datum_lat 40.49360000\n"
        "1302 datum_lon -3.56680000\n"
        f"100 60.00 1 0 0.25 1 2 1 18L {PAVEMENT_END.latitude:.8f} "
        f"{PAVEMENT_END.longitude:.8f} {displacement_m:.2f} 0.00 1 0 0 1 "
        f"36R {OPPOSITE_END.latitude:.8f} {OPPOSITE_END.longitude:.8f} 0.00 0.00 1 0 0 1\n"
        "99\n"
    )


def _separation(a: GeoPosition, b: GeoPosition) -> tuple[float, float]:
    """``(metres, initial true bearing)`` between two positions."""
    distance_nm, bearing_deg = distance_and_bearing(a, b)
    return distance_nm * METRES_PER_NAUTICAL_MILE, bearing_deg


def _position(latitude: float, longitude: float) -> GeoPosition:
    return GeoPosition(latitude=latitude, longitude=longitude, altitude_ft=0.0)


# --------------------------------------------------------------------------
# Source 1: apt.dat publishes the pavement end and must walk it forward
# --------------------------------------------------------------------------


def _parse_apt(*, displacement_m: float = APT_DISPLACEMENT_M) -> ParsedRunwayEnd:
    airports = list(iter_airports(_apt_text(displacement_m=displacement_m).splitlines()))
    assert [a.icao for a in airports] == ["LEMD"]
    end = next(r for r in airports[0].runways if r.ident == "18L")
    return end


def test_apt_dat_walks_its_pavement_end_forward_to_the_threshold() -> None:
    """The row carries the pavement end; ``threshold_*`` must not simply echo it."""
    end = _parse_apt()

    assert (end.end_lat, end.end_lon) == (PAVEMENT_END.latitude, PAVEMENT_END.longitude)
    assert (end.threshold_lat, end.threshold_lon) != (end.end_lat, end.end_lon)

    walked_m, bearing_deg = _separation(
        _position(end.end_lat, end.end_lon), _position(end.threshold_lat, end.threshold_lon)
    )
    assert walked_m == pytest.approx(APT_DISPLACEMENT_M, abs=0.01)
    # Down the centreline, not off to one side.
    assert bearing_deg == pytest.approx(TRUE_BEARING_DEG, abs=0.05)


def test_apt_dat_reports_the_pavement_length_not_the_landing_distance() -> None:
    end = _parse_apt()
    assert end.length_m == pytest.approx(PAVEMENT_LENGTH_M, abs=0.5)
    assert end.displaced_threshold_m == pytest.approx(APT_DISPLACEMENT_M)
    # The number that would be wrong if length_m had been trimmed to the LDA.
    assert end.length_m - end.displaced_threshold_m == pytest.approx(3003.5, abs=0.5)


def test_apt_dat_leaves_an_undisplaced_threshold_bit_for_bit_alone() -> None:
    """No displacement means no geodesic round trip: the coordinate is the coordinate."""
    end = _parse_apt(displacement_m=0.0)
    assert (end.threshold_lat, end.threshold_lon) == (end.end_lat, end.end_lon)


# --------------------------------------------------------------------------
# Source 2: the CIFP publishes the threshold directly
# --------------------------------------------------------------------------


def _parse_cifp_runway() -> CifpRunway:
    airport = parse_cifp(CIFP_TEXT, icao="LEMD")
    assert airport.skipped_record_count == 0
    runway = airport.runway("18L")
    assert runway is not None
    return runway


def _cifp_threshold() -> GeoPosition:
    """The record's threshold, which a readable ``RWY:`` record always carries."""
    threshold = _parse_cifp_runway().threshold
    assert threshold is not None
    return threshold


def test_the_cifp_record_publishes_the_displaced_threshold_not_the_pavement_end() -> None:
    from_pavement_m, bearing_deg = _separation(PAVEMENT_END, _cifp_threshold())
    assert from_pavement_m == pytest.approx(MEASURED_DISPLACEMENT_M, abs=0.5)
    assert bearing_deg == pytest.approx(TRUE_BEARING_DEG, abs=0.05)


def test_the_two_sources_agree_on_the_threshold_and_only_on_the_threshold() -> None:
    """The point of the whole module: same threshold, ~496 m from the pavement end."""
    cifp_threshold = _cifp_threshold()
    apt = _parse_apt()

    between_thresholds_m, _ = _separation(
        _position(apt.threshold_lat, apt.threshold_lon), cifp_threshold
    )
    assert between_thresholds_m < SURVEY_TOLERANCE_M

    from_pavement_m, _ = _separation(PAVEMENT_END, cifp_threshold)
    assert from_pavement_m > 100.0 * between_thresholds_m


def test_the_cifp_displacement_field_is_converted_from_feet() -> None:
    """1640 ft, and the model carries metres. Read as metres it is 1.1 km of a 3.5 km runway."""
    runway = _parse_cifp_runway()
    assert runway.displaced_threshold_m is not None
    assert runway.displaced_threshold_m == pytest.approx(CIFP_DISPLACEMENT_FT * 0.3048)
    assert abs(runway.displaced_threshold_m - APT_DISPLACEMENT_M) < SURVEY_TOLERANCE_M
    assert runway.elevation_ft == THRESHOLD_ELEVATION_FT


# --------------------------------------------------------------------------
# The merge, where the two conventions actually meet
# --------------------------------------------------------------------------


@contextmanager
def _indexed_runway(
    tmp_path: Path, *, apt_displacement_m: float, with_cifp: bool
) -> Iterator[Runway]:
    """The full pipeline — index both hand-written sources, read LEMD 18L back.

    The tree is built under ``tmp_path`` and dropped with it. Nothing
    navdata-shaped is ever written into the repository.
    """
    root = tmp_path / "xp_root"
    scenery = root / "Global Scenery" / "Global Airports" / "Earth nav data"
    scenery.mkdir(parents=True)
    (scenery / "apt.dat").write_text(_apt_text(displacement_m=apt_displacement_m), encoding="utf-8")

    data = root / "Resources" / "default data"
    (data / "CIFP").mkdir(parents=True)
    if with_cifp:
        (data / "CIFP" / "LEMD.dat").write_text(CIFP_TEXT, encoding="utf-8")
    for name in ("earth_fix.dat", "earth_nav.dat", "earth_awy.dat", "earth_hold.dat"):
        (data / name).write_text("I\n1200 Version\n99\n", encoding="utf-8")
    (data / "cycle_info.txt").write_text("AIRAC cycle : 2501\n", encoding="utf-8")

    provider = XPNativeNavdataProvider(
        root,
        cache_dir=tmp_path / "cache",
        cifp_source=XPNativeCifpSource(root) if with_cifp else None,
    )
    status = provider.ensure_index()
    assert status.state == "ready", status.reason
    try:
        runway = provider.get_runway("LEMD", "18L")
        assert runway is not None
        yield runway
    finally:
        provider.close()


def test_the_indexed_runway_carries_the_displaced_threshold(tmp_path: Path) -> None:
    """Both sources present: threshold displaced, pavement end kept, length untouched."""
    with _indexed_runway(tmp_path, apt_displacement_m=APT_DISPLACEMENT_M, with_cifp=True) as runway:
        assert runway.pavement_end is not None
        assert runway.threshold != runway.pavement_end
        assert runway.pavement_end.latitude == pytest.approx(PAVEMENT_END.latitude)
        assert runway.pavement_end.longitude == pytest.approx(PAVEMENT_END.longitude)

        displacement_m, bearing_deg = _separation(runway.pavement_end, runway.threshold)
        assert displacement_m == pytest.approx(MEASURED_DISPLACEMENT_M, abs=0.5)
        assert bearing_deg == pytest.approx(TRUE_BEARING_DEG, abs=0.05)

        assert runway.length_m == pytest.approx(PAVEMENT_LENGTH_M, abs=0.5)
        assert runway.elevation_ft == THRESHOLD_ELEVATION_FT


def test_the_indexed_runway_is_self_consistent_about_its_displacement(tmp_path: Path) -> None:
    """``displaced_threshold_m`` describes the threshold the model actually carries."""
    with _indexed_runway(tmp_path, apt_displacement_m=APT_DISPLACEMENT_M, with_cifp=True) as runway:
        assert runway.pavement_end is not None
        measured_m, _ = _separation(runway.pavement_end, runway.threshold)
        assert runway.displaced_threshold_m == pytest.approx(measured_m, abs=0.5)

        assert runway.landing_distance_m is not None
        assert runway.landing_distance_m < runway.length_m
        assert runway.landing_distance_m == pytest.approx(
            runway.length_m - runway.displaced_threshold_m
        )


def test_a_cifp_displacement_survives_an_apt_dat_that_publishes_none(tmp_path: Path) -> None:
    """The regression this module exists for.

    Global Airports data does not always carry the displacement the CIFP does.
    When the CIFP threshold wins and ``apt.dat``'s zero is carried across with
    it, the runway reports ``threshold != pavement_end`` while claiming a
    displacement of 0.0 — and hands out the full 3497 m of pavement as landing
    distance available with 496 m of it lying before the threshold.
    """
    with _indexed_runway(tmp_path, apt_displacement_m=0.0, with_cifp=True) as runway:
        assert runway.pavement_end is not None
        assert runway.threshold != runway.pavement_end
        assert runway.displaced_threshold_m == pytest.approx(MEASURED_DISPLACEMENT_M, abs=0.5)
        assert runway.landing_distance_m is not None
        assert runway.landing_distance_m == pytest.approx(
            PAVEMENT_LENGTH_M - MEASURED_DISPLACEMENT_M, abs=1.0
        )


def test_without_a_cifp_the_apt_dat_walk_alone_reaches_the_same_threshold(
    tmp_path: Path,
) -> None:
    """Roughly half the world's airports have no CIFP file. The threshold is still displaced."""
    with _indexed_runway(
        tmp_path, apt_displacement_m=APT_DISPLACEMENT_M, with_cifp=False
    ) as runway:
        assert runway.pavement_end is not None
        displacement_m, _ = _separation(runway.pavement_end, runway.threshold)
        assert displacement_m == pytest.approx(APT_DISPLACEMENT_M, abs=0.01)
        assert runway.displaced_threshold_m == pytest.approx(APT_DISPLACEMENT_M)
        assert runway.length_m == pytest.approx(PAVEMENT_LENGTH_M, abs=0.5)


# --------------------------------------------------------------------------
# What it costs downstream
# --------------------------------------------------------------------------


def test_a_ten_mile_final_off_the_indexed_runway_is_anchored_on_the_threshold(
    tmp_path: Path,
) -> None:
    """0.27 NM — issue #40's number, reproduced from the parsers rather than asserted at them."""
    with _indexed_runway(tmp_path, apt_displacement_m=APT_DISPLACEMENT_M, with_cifp=True) as runway:
        assert runway.pavement_end is not None
        anchored_on_pavement = runway.model_copy(update={"threshold": runway.pavement_end})

        error_m, _ = _separation(
            final_approach_point(runway, 10.0),
            final_approach_point(anchored_on_pavement, 10.0),
        )
        assert error_m == pytest.approx(MEASURED_DISPLACEMENT_M, abs=0.5)
        assert error_m / METRES_PER_NAUTICAL_MILE == pytest.approx(0.27, abs=0.005)
