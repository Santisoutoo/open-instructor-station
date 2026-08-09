"""International Standard Atmosphere, and the airspeed conversions that need it.

Pure functions — no simulator, no I/O, no global state, and no knowledge of how
any particular simulator names things. Altitudes cross the public API in
**feet**, speeds in **knots**, temperatures in **degrees Celsius**; ratios are
dimensionless fractions of the sea-level standard value.

An airspeed indicator is a pressure instrument. It measures dynamic pressure and
displays the speed that would produce it in sea-level standard air, so the same
needle reading means a faster and faster aeroplane as the air thins out. Setting
the two dynamic pressures equal, ``rho_0 * IAS^2 = rho * TAS^2``, gives the
relation this module exists for::

    TAS = IAS / sqrt(sigma)        sigma = rho / rho_0    (the density ratio)

All the work is in sigma, and sigma needs two inputs, because air thins for two
independent reasons. Pressure falls with height — hydrostatically, integrated
through the ISA temperature profile, which is what makes it a function of
*pressure* altitude alone — and density falls further when the air is warmer
than standard::

    sigma = delta / theta          delta = p / p_0        theta = T / T_0

which is exactly what *density altitude* names: the standard-atmosphere altitude
whose air is as thin as the air actually out there.

The size of the effect is why this is not a rounding detail. At 10 000 ft on a
standard day sigma is 0.7386 and 1/sqrt(sigma) is 1.164, so an aircraft
indicating 210 kt is truly doing 244 kt. Applying an indicated speed as though
it were a true one puts a 34 kt error into a simulated approach.

What this model deliberately does **not** include:

* **Compressibility.** The full chain is IAS -> CAS -> EAS -> TAS, and the
  ``EAS = CAS`` step holds only while the air can be treated as incompressible.
  This module assumes it throughout. The error is well under a knot at the
  speeds and altitudes an instructor station sets up — circuits, approaches,
  low-level work — and grows with Mach: near 250 kt at FL350 the incompressible
  formula overstates true airspeed by a couple of per cent. It is the right
  model for an approach and the wrong one for a cruise.
* **Instrument and position error.** ``IAS = CAS`` here. The real correction is
  a per-airframe calibration table that nothing outside the aircraft can know.
* **Humidity.** Water vapour is lighter than dry air, so real moist air is a
  little less dense than this says — under 1 % even hot and saturated.
* **Anything above 65 617 ft** (20 km). Only the two lowest ISA layers are
  modelled: the constant-lapse troposphere and the isothermal layer above it.
  No aeroplane an instructor station repositions goes higher.
"""

from __future__ import annotations

import math

__all__ = [
    "ISA_LAPSE_RATE_C_PER_FT",
    "ISA_SEA_LEVEL_DENSITY_KG_M3",
    "ISA_SEA_LEVEL_PRESSURE_PA",
    "ISA_SEA_LEVEL_TEMPERATURE_C",
    "TROPOPAUSE_ALTITUDE_FT",
    "density_altitude_ft",
    "density_ratio",
    "ias_from_tas",
    "isa_deviation_c",
    "isa_temperature_c",
    "pressure_ratio",
    "tas_from_ias",
    "temperature_from_deviation_c",
]

# --- ISA defining constants -------------------------------------------------
# The ISA is defined in metric units. Everything here is derived from those
# definitions rather than copied from a rounded imperial table, so the imperial
# values this module works in stay consistent with the metric ones to the last
# significant figure.

_METRES_PER_FOOT = 0.3048
_KELVIN_AT_ZERO_C = 273.15

ISA_SEA_LEVEL_TEMPERATURE_C: float = 15.0
ISA_SEA_LEVEL_PRESSURE_PA: float = 101_325.0
ISA_SEA_LEVEL_DENSITY_KG_M3: float = 1.225

#: Tropospheric lapse rate: 6.5 °C per kilometre, expressed per foot
#: (0.0019812 °C/ft, the familiar "2 °C per 1 000 ft").
ISA_LAPSE_RATE_C_PER_FT: float = 0.0065 * _METRES_PER_FOOT

#: Top of the modelled troposphere: 11 km. Above it the ISA temperature is
#: constant, which changes the pressure law from a power to an exponential.
TROPOPAUSE_ALTITUDE_FT: float = 11_000.0 / _METRES_PER_FOOT

_ISA_SEA_LEVEL_TEMPERATURE_K: float = ISA_SEA_LEVEL_TEMPERATURE_C + _KELVIN_AT_ZERO_C
_STANDARD_GRAVITY_M_PER_S2: float = 9.806_65
_DRY_AIR_GAS_CONSTANT_J_PER_KG_K: float = 287.052_87

#: ``g / (L * R)``, about 5.2559. Integrating the hydrostatic equation through a
#: constant lapse rate turns the temperature ratio into the pressure ratio by
#: raising it to this power. ``L`` there is the lapse rate per *metre*, which is
#: why it is converted back.
_PRESSURE_EXPONENT: float = _STANDARD_GRAVITY_M_PER_S2 / (
    (ISA_LAPSE_RATE_C_PER_FT / _METRES_PER_FOOT) * _DRY_AIR_GAS_CONSTANT_J_PER_KG_K
)

#: The density ratio is the pressure ratio divided by the temperature ratio, and
#: in the troposphere the temperature ratio is itself the base of the pressure
#: power law — so the density ratio is that same base raised to one less. Used to
#: invert a density ratio back into an altitude.
_DENSITY_EXPONENT: float = _PRESSURE_EXPONENT - 1.0

#: Depth at which the standard temperature profile would reach absolute zero.
#: The tropospheric formulae mean nothing below it. Nowhere on this planet is,
#: but the guard keeps a nonsense input from producing a confident nonsense
#: answer.
_ABSOLUTE_ZERO_ALTITUDE_FT: float = -_ISA_SEA_LEVEL_TEMPERATURE_K / ISA_LAPSE_RATE_C_PER_FT

_TROPOPAUSE_TEMPERATURE_K: float = (
    _ISA_SEA_LEVEL_TEMPERATURE_K - ISA_LAPSE_RATE_C_PER_FT * TROPOPAUSE_ALTITUDE_FT
)
_TROPOPAUSE_PRESSURE_RATIO: float = float(
    (_TROPOPAUSE_TEMPERATURE_K / _ISA_SEA_LEVEL_TEMPERATURE_K) ** _PRESSURE_EXPONENT
)
_TROPOPAUSE_DENSITY_RATIO: float = (
    _TROPOPAUSE_PRESSURE_RATIO * _ISA_SEA_LEVEL_TEMPERATURE_K / _TROPOPAUSE_TEMPERATURE_K
)

#: ``R * T / g`` in feet: in an isothermal layer the pressure decays
#: exponentially with this scale height, about 20 806 ft at tropopause
#: temperature.
_ISOTHERMAL_SCALE_HEIGHT_FT: float = (
    _DRY_AIR_GAS_CONSTANT_J_PER_KG_K * _TROPOPAUSE_TEMPERATURE_K / _STANDARD_GRAVITY_M_PER_S2
) / _METRES_PER_FOOT


def isa_temperature_c(pressure_altitude_ft: float) -> float:
    """Standard-day air temperature at a pressure altitude.

    Args:
        pressure_altitude_ft: Pressure altitude in feet.

    Returns:
        Temperature in degrees Celsius: 15 °C at sea level, falling by
        1.98 °C per 1 000 ft to -56.5 °C at the tropopause, and constant above
        it.
    """
    if pressure_altitude_ft >= TROPOPAUSE_ALTITUDE_FT:
        return _TROPOPAUSE_TEMPERATURE_K - _KELVIN_AT_ZERO_C
    return ISA_SEA_LEVEL_TEMPERATURE_C - ISA_LAPSE_RATE_C_PER_FT * pressure_altitude_ft


def isa_deviation_c(temperature_c: float, pressure_altitude_ft: float) -> float:
    """How far the air is from a standard day, in degrees Celsius.

    "ISA+15" is this number. It is the portable half of a temperature
    observation: the deviation is roughly constant through an air mass, while the
    temperature itself is not — air cools with height whether the day is standard
    or not.

    Args:
        temperature_c: Observed outside air temperature in degrees Celsius.
        pressure_altitude_ft: The pressure altitude it was observed at.

    Returns:
        ``temperature_c`` minus the standard temperature for that altitude:
        positive in air warmer than standard, zero on a standard day.
    """
    return temperature_c - isa_temperature_c(pressure_altitude_ft)


def temperature_from_deviation_c(pressure_altitude_ft: float, deviation_c: float) -> float:
    """Air temperature at an altitude, given how far the day is off standard.

    The inverse of :func:`isa_deviation_c`. Together the pair estimate the
    temperature *somewhere else* from a single measurement: take the deviation
    where it was measured, and re-apply it at the altitude of interest.

    That assumes the real lapse rate matches the ISA's 1.98 °C per 1 000 ft. An
    inversion or an unusually dry, well-mixed layer breaks the assumption, but it
    is a far better one than carrying the raw temperature across. A 25 °C surface
    reading taken up to 10 000 ft unchanged puts about 5 % of error into the
    density ratio and pushes true airspeed the *wrong* way; its deviation taken up
    instead costs a fraction of a per cent on any ordinary day.

    Args:
        pressure_altitude_ft: Pressure altitude of interest, in feet.
        deviation_c: Departure from the standard temperature, in degrees Celsius
            — typically from :func:`isa_deviation_c` at another altitude.

    Returns:
        Estimated outside air temperature there, in degrees Celsius.
    """
    return isa_temperature_c(pressure_altitude_ft) + deviation_c


def pressure_ratio(pressure_altitude_ft: float) -> float:
    """Ambient static pressure as a fraction of sea-level standard pressure.

    A function of pressure altitude alone — that is what pressure altitude *is*.
    The actual temperature does not appear here: it moves the density, not the
    pressure a given altimeter reading corresponds to.

    Args:
        pressure_altitude_ft: Pressure altitude in feet.

    Returns:
        ``p / p_0``, dimensionless. 1.0 at sea level, 0.6877 at 10 000 ft,
        0.2234 at the tropopause.

    Raises:
        ValueError: below the depth at which the standard temperature profile
            would pass absolute zero (about -145 000 ft), where the model has no
            meaning.
    """
    if pressure_altitude_ft <= _ABSOLUTE_ZERO_ALTITUDE_FT:
        raise ValueError(
            f"pressure_altitude_ft={pressure_altitude_ft} is below the depth at which the "
            "standard atmosphere passes absolute zero; the ISA model does not extend there."
        )
    if pressure_altitude_ft <= TROPOPAUSE_ALTITUDE_FT:
        temperature_ratio = (
            isa_temperature_c(pressure_altitude_ft) + _KELVIN_AT_ZERO_C
        ) / _ISA_SEA_LEVEL_TEMPERATURE_K
        return float(temperature_ratio**_PRESSURE_EXPONENT)
    return _TROPOPAUSE_PRESSURE_RATIO * math.exp(
        -(pressure_altitude_ft - TROPOPAUSE_ALTITUDE_FT) / _ISOTHERMAL_SCALE_HEIGHT_FT
    )


def density_ratio(pressure_altitude_ft: float, temperature_c: float | None = None) -> float:
    """Air density as a fraction of sea-level standard density.

    ``sigma = delta / theta``: the pressure has fallen by ``delta``, and air
    warmer than standard is thinner still by the temperature ratio ``theta``.

    Args:
        pressure_altitude_ft: Pressure altitude in feet.
        temperature_c: Actual outside air temperature in degrees Celsius.
            ``None`` means a standard day — the ISA temperature for that
            altitude — in which case the result depends on the altitude alone.

    Returns:
        ``rho / rho_0``, dimensionless. 1.0 in sea-level standard air, 0.7385 at
        10 000 ft on a standard day, less than that on a hot one.

    Raises:
        ValueError: if ``temperature_c`` is at or below absolute zero, or the
            altitude is outside the modelled range.
    """
    if temperature_c is None:
        temperature_c = isa_temperature_c(pressure_altitude_ft)
    temperature_k = temperature_c + _KELVIN_AT_ZERO_C
    if temperature_k <= 0.0:
        raise ValueError(
            f"temperature_c={temperature_c} is at or below absolute zero, which no "
            "atmosphere reaches."
        )
    return pressure_ratio(pressure_altitude_ft) * _ISA_SEA_LEVEL_TEMPERATURE_K / temperature_k


def density_altitude_ft(pressure_altitude_ft: float, temperature_c: float | None = None) -> float:
    """Pressure altitude at which the standard atmosphere is this thin.

    The inverse of :func:`density_ratio` on a standard day. It is what the
    aircraft's performance — and its airspeed indicator — actually respond to,
    and it equals the pressure altitude only when the day is standard.

    Args:
        pressure_altitude_ft: Pressure altitude in feet.
        temperature_c: Actual outside air temperature in degrees Celsius, or
            ``None`` for a standard day, which hands ``pressure_altitude_ft``
            straight back.

    Returns:
        Density altitude in feet. Higher than the pressure altitude when the air
        is warmer than standard, by roughly 120 ft per °C of deviation.

    Raises:
        ValueError: if ``temperature_c`` is at or below absolute zero, or the
            altitude is outside the modelled range.
    """
    sigma = density_ratio(pressure_altitude_ft, temperature_c)
    if sigma >= _TROPOPAUSE_DENSITY_RATIO:
        temperature_ratio = float(sigma ** (1.0 / _DENSITY_EXPONENT))
        return (1.0 - temperature_ratio) * _ISA_SEA_LEVEL_TEMPERATURE_K / ISA_LAPSE_RATE_C_PER_FT
    return TROPOPAUSE_ALTITUDE_FT + _ISOTHERMAL_SCALE_HEIGHT_FT * math.log(
        _TROPOPAUSE_DENSITY_RATIO / sigma
    )


def tas_from_ias(
    ias_kt: float,
    pressure_altitude_ft: float,
    temperature_c: float | None = None,
) -> float:
    """Convert an indicated airspeed to a true airspeed.

    Args:
        ias_kt: Indicated airspeed in knots. Taken as calibrated and
            incompressible — see the module docstring.
        pressure_altitude_ft: Pressure altitude in feet.
        temperature_c: Outside air temperature in degrees Celsius, or ``None``
            for a standard day.

    Returns:
        True airspeed in knots, ``ias_kt / sqrt(sigma)``. Never below the
        indicated speed above sea level, and equal to it in sea-level standard
        air.

    Raises:
        ValueError: if ``temperature_c`` is at or below absolute zero, or the
            altitude is outside the modelled range.
    """
    return ias_kt / math.sqrt(density_ratio(pressure_altitude_ft, temperature_c))


def ias_from_tas(
    tas_kt: float,
    pressure_altitude_ft: float,
    temperature_c: float | None = None,
) -> float:
    """Convert a true airspeed to the indicated airspeed it would show.

    The exact inverse of :func:`tas_from_ias`.

    Args:
        tas_kt: True airspeed in knots.
        pressure_altitude_ft: Pressure altitude in feet.
        temperature_c: Outside air temperature in degrees Celsius, or ``None``
            for a standard day.

    Returns:
        Indicated airspeed in knots, ``tas_kt * sqrt(sigma)``.

    Raises:
        ValueError: if ``temperature_c`` is at or below absolute zero, or the
            altitude is outside the modelled range.
    """
    return tas_kt * math.sqrt(density_ratio(pressure_altitude_ft, temperature_c))
