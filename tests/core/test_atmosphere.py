"""Tests for the ISA model and the IAS <-> TAS conversion.

The reference numbers are the published International Standard Atmosphere
table, not values read back out of this implementation: the pressure ratio, the
density ratio and the standard temperature at a spread of altitudes from sea
level to the stratosphere. A conversion with the maths inverted reproduces none
of them — which is why absolute values are asserted here and the round trip is
only a secondary check.
"""

import math

import pytest

from core.atmosphere import (
    ISA_LAPSE_RATE_C_PER_FT,
    ISA_SEA_LEVEL_TEMPERATURE_C,
    TROPOPAUSE_ALTITUDE_FT,
    density_altitude_ft,
    density_ratio,
    ias_from_tas,
    isa_deviation_c,
    isa_temperature_c,
    pressure_ratio,
    tas_from_ias,
    temperature_from_deviation_c,
)

#: ``(pressure altitude ft, standard temperature °C, pressure ratio, density
#: ratio)`` from the ISA tables. The last two rows sit at and above the
#: tropopause, where the pressure law changes from a power to an exponential.
ISA_TABLE = [
    (0.0, 15.0, 1.00000, 1.00000),
    (2_000.0, 11.038, 0.92981, 0.94277),
    (5_000.0, 5.094, 0.83205, 0.86167),
    (10_000.0, -4.812, 0.68770, 0.73848),
    (20_000.0, -24.624, 0.45954, 0.53281),
    (30_000.0, -44.436, 0.29696, 0.37413),
    (36_089.24, -56.500, 0.22336, 0.29708),
    (40_000.0, -56.500, 0.18509, 0.24617),
]


def test_isa_temperature_matches_the_standard_profile() -> None:
    """15 °C at sea level, -1.98 °C per 1 000 ft, -56.5 °C from the tropopause up."""
    for altitude_ft, temperature_c, _, _ in ISA_TABLE:
        assert isa_temperature_c(altitude_ft) == pytest.approx(temperature_c, abs=0.01)

    assert isa_temperature_c(0.0) == ISA_SEA_LEVEL_TEMPERATURE_C
    assert isa_temperature_c(1_000.0) == pytest.approx(15.0 - 1.9812, abs=1e-6)
    # The isothermal layer really is isothermal.
    assert isa_temperature_c(50_000.0) == pytest.approx(-56.5, abs=0.01)


def test_pressure_ratio_matches_the_standard_table() -> None:
    """The pressure ratio depends on pressure altitude alone, and it is the tabulated one."""
    for altitude_ft, _, delta, _ in ISA_TABLE:
        assert pressure_ratio(altitude_ft) == pytest.approx(delta, abs=5e-5)

    # The familiar landmark: half an atmosphere at about 18 000 ft.
    assert pressure_ratio(18_000.0) == pytest.approx(0.5, abs=0.001)


def test_density_ratio_matches_the_standard_table() -> None:
    """The density ratio on a standard day. This is the whole conversion."""
    for altitude_ft, _, _, sigma in ISA_TABLE:
        assert density_ratio(altitude_ft) == pytest.approx(sigma, abs=5e-5)


def test_pressure_ratio_is_continuous_across_the_tropopause() -> None:
    """The power law and the exponential must agree where they meet.

    The pressure ratio falls by about 1.1e-5 per foot up there, so straddling
    the boundary by a thousandth of a foot leaves only that slope between the
    two branches.
    """
    below = pressure_ratio(TROPOPAUSE_ALTITUDE_FT - 0.001)
    above = pressure_ratio(TROPOPAUSE_ALTITUDE_FT + 0.001)
    assert below == pytest.approx(above, abs=1e-7)


def test_sea_level_standard_day_leaves_the_speed_alone() -> None:
    """The invariant that catches an inverted conversion: density ratio 1, IAS = TAS."""
    assert density_ratio(0.0) == pytest.approx(1.0, abs=1e-12)
    for speed_kt in (0.0, 65.0, 140.0, 210.0, 350.0):
        assert tas_from_ias(speed_kt, 0.0) == pytest.approx(speed_kt, abs=1e-9)
        assert ias_from_tas(speed_kt, 0.0) == pytest.approx(speed_kt, abs=1e-9)


def test_known_ias_tas_pairs_on_a_standard_day() -> None:
    """100 kt indicated, converted at each tabulated altitude.

    100 kt makes the expected value read as the percentage error a naive
    implementation carries: 116.4 kt at 10 000 ft is a 16 % mistake.
    """
    for altitude_ft, _, _, sigma in ISA_TABLE:
        expected_kt = 100.0 / math.sqrt(sigma)
        assert tas_from_ias(100.0, altitude_ft) == pytest.approx(expected_kt, abs=0.02)

    # Spelled out, so the direction of the maths is visible in the file.
    assert tas_from_ias(100.0, 0.0) == pytest.approx(100.00, abs=0.01)
    assert tas_from_ias(100.0, 5_000.0) == pytest.approx(107.73, abs=0.01)
    assert tas_from_ias(100.0, 10_000.0) == pytest.approx(116.37, abs=0.01)
    assert tas_from_ias(100.0, 20_000.0) == pytest.approx(137.00, abs=0.01)
    assert tas_from_ias(100.0, 30_000.0) == pytest.approx(163.49, abs=0.01)
    assert tas_from_ias(100.0, 40_000.0) == pytest.approx(201.55, abs=0.01)


def test_the_defect_this_module_was_written_for() -> None:
    """210 kt on a 10 NM final at FL100 is 244 kt true, not 210."""
    tas_kt = tas_from_ias(210.0, 10_000.0)

    assert tas_kt == pytest.approx(244.37, abs=0.01)
    assert tas_kt - 210.0 == pytest.approx(34.4, abs=0.1)


def test_true_airspeed_exceeds_indicated_above_sea_level() -> None:
    """Monotonic in altitude, and the right way round at every one of them."""
    previous_kt = 150.0
    for altitude_ft in (1_000.0, 5_000.0, 10_000.0, 20_000.0, 35_000.0, 45_000.0):
        tas_kt = tas_from_ias(150.0, altitude_ft)
        assert tas_kt > previous_kt
        previous_kt = tas_kt


def test_below_sea_level_the_air_is_denser_and_true_is_slower() -> None:
    """A Dead Sea approach: the density ratio exceeds 1, so TAS drops below IAS."""
    assert density_ratio(-1_300.0) > 1.0
    assert tas_from_ias(120.0, -1_300.0) < 120.0


def test_hot_air_is_thinner_and_cold_air_thicker() -> None:
    """Temperature moves the density ratio independently of pressure altitude."""
    standard_c = isa_temperature_c(5_000.0)

    hot = density_ratio(5_000.0, standard_c + 20.0)
    standard = density_ratio(5_000.0)
    cold = density_ratio(5_000.0, standard_c - 20.0)

    assert hot < standard < cold
    assert tas_from_ias(100.0, 5_000.0, standard_c + 20.0) > tas_from_ias(100.0, 5_000.0)
    assert tas_from_ias(100.0, 5_000.0, standard_c - 20.0) < tas_from_ias(100.0, 5_000.0)


def test_passing_the_standard_temperature_matches_passing_nothing() -> None:
    """``None`` means "standard day", not "ignore temperature"."""
    for altitude_ft in (0.0, 7_500.0, 25_000.0, 41_000.0):
        explicit = density_ratio(altitude_ft, isa_temperature_c(altitude_ft))
        assert explicit == pytest.approx(density_ratio(altitude_ft), abs=1e-12)


def test_a_hot_day_costs_real_knots() -> None:
    """ISA+15 at FL100: 210 kt indicated is 251 kt true, not 244."""
    standard_c = isa_temperature_c(10_000.0)

    assert tas_from_ias(210.0, 10_000.0, standard_c + 15.0) == pytest.approx(251.11, abs=0.01)


def test_density_altitude_is_the_pressure_altitude_on_a_standard_day() -> None:
    """By definition. If this drifts, the pressure and temperature ratios disagree."""
    for altitude_ft in (0.0, 5_000.0, 18_000.0, 36_089.24, 40_000.0):
        assert density_altitude_ft(altitude_ft) == pytest.approx(altitude_ft, abs=1e-6)


def test_density_altitude_rises_on_a_hot_day() -> None:
    """5 000 ft pressure altitude at 30 °C is 7 801 ft of density altitude.

    The pilot's rule of thumb — 120 ft per °C above standard — puts it near
    7 990 ft; the difference is what the linearisation costs.
    """
    density_alt_ft = density_altitude_ft(5_000.0, 30.0)

    assert density_alt_ft == pytest.approx(7_800.7, abs=0.5)
    rule_of_thumb_ft = 5_000.0 + 120.0 * (30.0 - isa_temperature_c(5_000.0))
    assert density_alt_ft == pytest.approx(rule_of_thumb_ft, abs=250.0)


def test_density_altitude_inverts_the_density_ratio_in_both_layers() -> None:
    """The altitude it returns must reproduce the density ratio it was given."""
    for altitude_ft, temperature_c in (
        (0.0, 35.0),
        (5_000.0, None),
        (25_000.0, -50.0),
        (40_000.0, -40.0),
        (45_000.0, -70.0),
    ):
        sigma = density_ratio(altitude_ft, temperature_c)

        assert density_ratio(density_altitude_ft(altitude_ft, temperature_c)) == pytest.approx(
            sigma, rel=1e-9
        )


def test_round_trip_ias_tas_ias() -> None:
    """Secondary check: the inverse really is the inverse."""
    for altitude_ft, temperature_c in (
        (0.0, None),
        (3_500.0, 28.0),
        (10_000.0, -4.812),
        (24_000.0, None),
        (41_000.0, -60.0),
    ):
        tas_kt = tas_from_ias(185.0, altitude_ft, temperature_c)

        assert ias_from_tas(tas_kt, altitude_ft, temperature_c) == pytest.approx(185.0, rel=1e-12)


def test_zero_speed_stays_zero() -> None:
    """A parked aircraft is parked at every altitude."""
    assert tas_from_ias(0.0, 10_000.0) == 0.0
    assert ias_from_tas(0.0, 10_000.0) == 0.0


def test_isa_deviation_is_zero_on_a_standard_day() -> None:
    """The definition, at every altitude and in both layers."""
    for altitude_ft in (0.0, 5_000.0, 18_000.0, 36_089.24, 45_000.0):
        assert isa_deviation_c(isa_temperature_c(altitude_ft), altitude_ft) == pytest.approx(
            0.0, abs=1e-9
        )


def test_isa_deviation_is_signed_the_way_pilots_say_it() -> None:
    """ISA+15 means 15 °C warmer than standard, whatever the altitude."""
    assert isa_deviation_c(30.0, 0.0) == pytest.approx(15.0, abs=1e-9)
    assert isa_deviation_c(0.0, 0.0) == pytest.approx(-15.0, abs=1e-9)
    # A -4.812 °C standard day at 10 000 ft: 10.188 °C is the same ISA+15.
    assert isa_deviation_c(10.188, 10_000.0) == pytest.approx(15.0, abs=0.001)


def test_temperature_from_deviation_inverts_isa_deviation() -> None:
    for altitude_ft, temperature_c in ((0.0, 30.0), (7_500.0, -2.0), (41_000.0, -70.0)):
        deviation_c = isa_deviation_c(temperature_c, altitude_ft)

        assert temperature_from_deviation_c(altitude_ft, deviation_c) == pytest.approx(
            temperature_c, abs=1e-9
        )


def test_carrying_a_deviation_up_cools_the_air_with_height() -> None:
    """A 25 °C surface reading is ISA+10, which is 5.2 °C at 10 000 ft — not 25.

    This is the whole point of the pair: the air aloft is colder than the air at
    the field even on a hot day, and the *deviation* is what survives the trip.
    """
    deviation_c = isa_deviation_c(25.0, 0.0)

    assert deviation_c == pytest.approx(10.0, abs=1e-9)
    assert temperature_from_deviation_c(10_000.0, deviation_c) == pytest.approx(5.188, abs=0.01)


def test_carrying_the_deviation_beats_carrying_the_temperature() -> None:
    """The error this pair removes, in knots of true airspeed.

    210 kt indicated at 10 000 ft on an ISA+10 day is 248.9 kt true. Taking the
    25 °C surface temperature up unchanged claims 257.6 kt — an 8.7 kt overshoot,
    because it models air far thinner up there than it is.
    """
    surface_c = 25.0
    aloft_c = temperature_from_deviation_c(10_000.0, isa_deviation_c(surface_c, 0.0))

    correct_kt = tas_from_ias(210.0, 10_000.0, aloft_c)
    naive_kt = tas_from_ias(210.0, 10_000.0, surface_c)

    assert correct_kt == pytest.approx(248.88, abs=0.01)
    assert naive_kt == pytest.approx(257.59, abs=0.01)
    assert naive_kt - correct_kt == pytest.approx(8.7, abs=0.1)


def test_the_constants_come_from_the_metric_definitions() -> None:
    """6.5 °C/km expressed per foot, 11 km expressed in feet."""
    lapse_rate = ISA_LAPSE_RATE_C_PER_FT
    tropopause_ft = TROPOPAUSE_ALTITUDE_FT

    assert lapse_rate == pytest.approx(0.0019812, abs=1e-10)
    assert tropopause_ft == pytest.approx(36_089.24, abs=0.01)


def test_temperature_below_absolute_zero_is_rejected() -> None:
    """Nonsense in, exception out — never a negative density."""
    with pytest.raises(ValueError, match="absolute zero"):
        density_ratio(10_000.0, -300.0)
    with pytest.raises(ValueError, match="absolute zero"):
        tas_from_ias(150.0, 10_000.0, -273.15)


def test_an_altitude_the_model_cannot_reach_is_rejected() -> None:
    """Below -145 000 ft the standard profile passes absolute zero."""
    with pytest.raises(ValueError, match="absolute zero"):
        pressure_ratio(-200_000.0)
