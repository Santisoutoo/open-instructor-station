"""Readers for ``earth_fix.dat``, ``earth_nav.dat`` and ``earth_hold.dat``.

Small files by ``apt.dat``'s standards — 26 MB and ~320 000 records together —
but the ones carrying the awkward encodings. **Every decoding rule below was
checked against real records**, and each of them costs hours to rediscover:

* a localizer's field 7 is *two* numbers in one, the magnetic front course and
  the true bearing, and it must be split with **integer** arithmetic on the
  digits rather than a float modulo, which loses the low digit of the fraction;
* a glideslope's field 7 packs the glidepath angle into the same field with a
  different multiplier;
* VHF frequencies are published in units of 10 kHz while NDB frequencies are
  already in kHz, and normalising both here is what lets the Position Manager
  assign a frequency straight into ``AircraftSetup`` with no arithmetic and no
  chance of a factor-of-ten error reaching the radios;
* ``earth_fix.dat``'s terminal-scope column is either the literal ``ENRT`` or an
  airport ICAO, and collapsing it would make roughly half the legs of a typical
  SID unresolvable.

Nothing here opens a file: the caller streams lines in.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

from core.navdata.models import NavaidKind, TunableRadio

__all__ = [
    "ParsedFix",
    "ParsedHold",
    "ParsedNavaid",
    "SkipSink",
    "decode_packed_glideslope",
    "decode_packed_localizer_bearing",
    "ndb_frequency_khz",
    "parse_earth_fix",
    "parse_earth_hold",
    "parse_earth_nav",
    "tunable_radio_for",
    "vhf_frequency_khz",
]

#: Called with ``(reason, line)`` for every record that could not be read.
SkipSink = Callable[[str, str], None]

_VERSION_LINE = re.compile(r"^\d{3,4}\s+Version\b")
_RUNWAY_IDENT = re.compile(r"^(?:\d{1,2}[A-Z]?|ALL)$")

#: The literal that means "this record is not scoped to an airport".
ENROUTE = "ENRT"

#: ``earth_nav.dat`` row codes, mapped onto :data:`~core.navdata.models.NavaidKind`.
#: Markers (7/8/9) and GBAS stations (15/16) are recognised and deliberately not
#: indexed: nothing in the product tunes, draws or positions against them.
_NAVAID_KINDS: dict[int, NavaidKind] = {
    2: "ndb",
    3: "vor",
    4: "localizer",
    5: "localizer",
    6: "glideslope",
    12: "dme",
    13: "dme",
    14: "gls",
}

#: Row codes whose ninth field is an airport and whose eleventh is a runway.
_TERMINAL_ROWS: frozenset[int] = frozenset({4, 5, 6, 7, 8, 9, 12, 14, 15, 16})

#: Which radio a navaid is tuned on. ``None`` means the instructor never tunes
#: it: a boolean would collapse "goes in NAV1" and "goes in the ADF", and an
#: NDB's 380 kHz does not even pass ``AircraftSetup.nav1_freq_khz`` validation.
_TUNABLE: dict[NavaidKind, TunableRadio | None] = {
    "vor": "nav",
    "vor_dme": "nav",
    "vortac": "nav",
    "dme": "nav",
    "tacan": "nav",
    "localizer": "nav",
    "ndb": "adf",
    "glideslope": None,
    "gls": None,
}


@dataclass(frozen=True)
class ParsedFix:
    """One row of ``earth_fix.dat``."""

    ident: str
    latitude: float
    longitude: float
    region_code: str | None
    terminal_airport_icao: str | None
    name: str | None = None


@dataclass(frozen=True)
class ParsedNavaid:
    """One row of ``earth_nav.dat``, with every packed field already decoded."""

    ident: str
    kind: NavaidKind
    latitude: float
    longitude: float
    name: str | None = None
    elevation_ft: float | None = None
    frequency_khz: int | None = None
    channel: str | None = None
    range_nm: float | None = None
    true_deg: float | None = None
    mag_deg: float | None = None
    glideslope_deg: float | None = None
    magnetic_variation_deg: float | None = None
    region_code: str | None = None
    airport_icao: str | None = None
    runway_ident: str | None = None


@dataclass(frozen=True)
class ParsedHold:
    """One row of ``earth_hold.dat``.

    :attr:`inbound_course_mag_deg` is **magnetic**, verified rather than
    assumed: the same fixes' ``HM`` legs in the CIFP — magnetic by ARINC
    definition — carry identical values at airports with double-digit variation,
    which is only possible if both are in the same frame.
    """

    fix_ident: str
    region_code: str | None
    airport_icao: str | None
    fix_type: int | None
    inbound_course_mag_deg: float
    leg_time_min: float | None
    leg_length_nm: float | None
    turn_direction: str
    min_altitude_ft: float | None
    max_altitude_ft: float | None
    speed_kt: float | None


# ---------------------------------------------------------------------------
# Verified decoders
# ---------------------------------------------------------------------------


def decode_packed_localizer_bearing(text: str) -> tuple[float, float] | None:
    """Split a localizer's multiuse field into ``(true_deg, magnetic_deg)``.

    Row type 4/5, field 7. The field carries **two** courses: the whole part is
    ``magnetic * 360 + true_whole`` and the fraction belongs to the true
    bearing. ``64979.763`` is 180 deg magnetic and 179.763 deg true.

    The split is done with **integer** arithmetic on the digit string, never a
    float modulo: ``64979.763 % 360`` is subject to binary rounding and the
    result is not exactly ``179.763``, which then propagates into every geodesic
    computed from it.

    Returns ``None`` when the field is not a packed bearing, so an odd record is
    skipped rather than fatal.
    """
    whole_text, _, fraction_text = text.strip().partition(".")
    if not whole_text.isdigit():
        return None
    whole = int(whole_text)
    fraction = float(f"0.{fraction_text}") if fraction_text.isdigit() else 0.0

    magnetic_deg = float(whole // 360)
    true_deg = float(whole % 360) + fraction
    if magnetic_deg >= 360.0 or true_deg >= 360.0:
        return None
    return true_deg, magnetic_deg


def decode_packed_glideslope(text: str) -> tuple[float, float] | None:
    """Split a glideslope's multiuse field into ``(glideslope_deg, true_deg)``.

    Row type 6, field 7, packed the same way as the localizer bearing but with a
    multiplier of **1000**: ``300179.763`` is a 3.00 deg glidepath on a true
    bearing of 179.763 deg. The multiplier is unambiguous because a true bearing
    never reaches 1000, and it is the one that reproduces the published 5.5 deg
    approach at London City and 6.65 deg at Lugano — no wrong multiplier does.
    """
    whole_text, _, fraction_text = text.strip().partition(".")
    if not whole_text.isdigit():
        return None
    whole = int(whole_text)
    fraction = float(f"0.{fraction_text}") if fraction_text.isdigit() else 0.0

    glideslope_deg = (whole // 1000) / 100.0
    true_deg = float(whole % 1000) + fraction
    if glideslope_deg <= 0.0 or true_deg >= 360.0:
        return None
    return glideslope_deg, true_deg


def vhf_frequency_khz(text: str) -> int | None:
    """Row types 3/4/5/6/12/13 publish VHF frequencies in units of 10 kHz.

    ``11150`` is 111.50 MHz, returned as ``111_500`` kHz — the same unit as
    ``AircraftSetup.nav1_freq_khz`` and ``AircraftSetup.ils_freq_khz``.
    """
    value = _as_int(text)
    return value * 10 if value is not None and value > 0 else None


def ndb_frequency_khz(text: str) -> int | None:
    """Row type 2 publishes NDB frequencies in kHz already: ``380`` is 380 kHz."""
    value = _as_int(text)
    return value if value is not None and value > 0 else None


def tunable_radio_for(kind: NavaidKind) -> TunableRadio | None:
    """Which radio tunes a navaid of this kind, or ``None`` when none does."""
    return _TUNABLE.get(kind)


# ---------------------------------------------------------------------------
# earth_fix.dat
# ---------------------------------------------------------------------------


def parse_earth_fix(
    lines: Iterable[str], *, on_skip: SkipSink | None = None
) -> Iterator[ParsedFix]:
    """Stream fixes out of ``earth_fix.dat``.

    Layout: ``<lat> <lon> <ident> <ENRT|airport ICAO> <region> <spec column>``.
    Older files stop after the ident; both shapes are read.
    """
    skip = on_skip if on_skip is not None else _ignore_skip

    for raw in lines:
        line = raw.strip()
        if _is_boilerplate(line):
            continue

        parts = line.split()
        if len(parts) < 3:
            skip("fix row has too few fields", line)
            continue

        latitude = _as_float(parts[0])
        longitude = _as_float(parts[1])
        if latitude is None or longitude is None or not _on_the_globe(latitude, longitude):
            skip("fix row has a non-numeric or out-of-range coordinate", line)
            continue

        ident = parts[2].strip().upper()
        if not ident:
            skip("fix row has no identifier", line)
            continue

        terminal = parts[3].strip().upper() if len(parts) > 3 else ENROUTE
        region = parts[4].strip().upper() if len(parts) > 4 else None

        yield ParsedFix(
            ident=ident,
            latitude=latitude,
            longitude=longitude,
            region_code=region or None,
            # ENRT is the source's spelling of "not scoped to an airport". It is
            # kept as NULL so a terminal-scoped query is an index lookup rather
            # than a string comparison against a magic word.
            terminal_airport_icao=None if terminal in {ENROUTE, ""} else terminal,
        )


# ---------------------------------------------------------------------------
# earth_nav.dat
# ---------------------------------------------------------------------------


def parse_earth_nav(
    lines: Iterable[str], *, on_skip: SkipSink | None = None
) -> Iterator[ParsedNavaid]:
    """Stream navaids out of ``earth_nav.dat``.

    Layout: ``<row> <lat> <lon> <elev_ft> <freq> <range_nm> <multiuse> <ident>
    <ENRT|airport> <region> [<runway>] <name...>``. The runway column exists
    only for terminal rows, so its presence is decided by the row code and the
    airport column together — and the candidate is sanity-checked, because a
    localizer's name field starts exactly where the runway's would.
    """
    skip = on_skip if on_skip is not None else _ignore_skip

    for raw in lines:
        line = raw.strip()
        if _is_boilerplate(line):
            continue

        parts = line.split()
        row_code = _as_int(parts[0]) if parts else None
        if row_code is None:
            skip("navaid row has no row code", line)
            continue
        if row_code not in _NAVAID_KINDS:
            # Markers and GBAS stations: recognised, not indexed, not an error.
            continue
        if len(parts) < 10:
            skip("navaid row has too few fields", line)
            continue

        navaid = _parse_navaid_row(row_code, parts, line, skip)
        if navaid is not None:
            yield navaid


def _parse_navaid_row(
    row_code: int, parts: list[str], line: str, skip: SkipSink
) -> ParsedNavaid | None:
    latitude = _as_float(parts[1])
    longitude = _as_float(parts[2])
    if latitude is None or longitude is None or not _on_the_globe(latitude, longitude):
        skip("navaid row has a non-numeric or out-of-range coordinate", line)
        return None

    ident = parts[7].strip().upper()
    if not ident:
        skip("navaid row has no identifier", line)
        return None

    terminal = parts[8].strip().upper()
    region = parts[9].strip().upper() or None
    runway_ident, name = _split_runway_and_name(row_code, terminal, parts)

    kind = _refine_kind(_NAVAID_KINDS[row_code], name)
    elevation_ft = _as_float(parts[3])
    multiuse = parts[6]

    true_deg: float | None = None
    mag_deg: float | None = None
    glideslope_deg: float | None = None
    magnetic_variation_deg: float | None = None

    if kind == "localizer":
        decoded = decode_packed_localizer_bearing(multiuse)
        if decoded is None:
            skip("localizer row has an undecodable bearing field", line)
            return None
        true_deg, mag_deg = decoded
    elif kind == "glideslope":
        decoded_gs = decode_packed_glideslope(multiuse)
        if decoded_gs is None:
            skip("glideslope row has an undecodable angle field", line)
            return None
        glideslope_deg, true_deg = decoded_gs
    else:
        magnetic_variation_deg = _as_float(multiuse)

    frequency_khz = (
        ndb_frequency_khz(parts[4])
        if kind == "ndb" and row_code == 2
        else vhf_frequency_khz(parts[4])
    )

    return ParsedNavaid(
        ident=ident,
        kind=kind,
        latitude=latitude,
        longitude=longitude,
        name=name or None,
        elevation_ft=elevation_ft,
        # A GBAS threshold point's "frequency" is a channel number, not a
        # tunable frequency; publishing it as one would put a nonsense value in
        # a NAV radio.
        frequency_khz=None if kind == "gls" else frequency_khz,
        channel=parts[4].strip() if kind == "gls" else None,
        range_nm=_as_float(parts[5]),
        true_deg=true_deg,
        mag_deg=mag_deg,
        glideslope_deg=glideslope_deg,
        magnetic_variation_deg=magnetic_variation_deg,
        region_code=region,
        airport_icao=None if terminal in {ENROUTE, ""} else terminal,
        runway_ident=runway_ident,
    )


def _split_runway_and_name(
    row_code: int, terminal: str, parts: list[str]
) -> tuple[str | None, str]:
    """Decide whether field 11 is a runway ident or the first word of the name."""
    if row_code in _TERMINAL_ROWS and terminal not in {ENROUTE, ""} and len(parts) > 10:
        candidate = parts[10].strip().upper()
        if _RUNWAY_IDENT.match(candidate):
            return candidate, " ".join(parts[11:])
    return None, " ".join(parts[10:])


def _refine_kind(kind: NavaidKind, name: str) -> NavaidKind:
    """Sharpen a row code with what the name says the installation actually is.

    ``earth_nav.dat`` uses one row code for the whole VOR family and one for
    standalone DME/TACAN; the distinction lives in the name's trailing word,
    which is where the source itself puts it.
    """
    upper = name.upper()
    if kind == "vor":
        if "VORTAC" in upper:
            return "vortac"
        if "VOR/DME" in upper or "VOR-DME" in upper:
            return "vor_dme"
        return "vor"
    if kind == "dme" and "TACAN" in upper:
        return "tacan"
    return kind


# ---------------------------------------------------------------------------
# earth_hold.dat
# ---------------------------------------------------------------------------


def parse_earth_hold(
    lines: Iterable[str], *, on_skip: SkipSink | None = None
) -> Iterator[ParsedHold]:
    """Stream published holds out of ``earth_hold.dat``.

    Layout: ``<fix ident> <ENRT|airport> <region> <fix type> <inbound course>
    <leg time min> <leg length nm> <turn> <min alt> <max alt> <speed>``. The
    fix-type enum is shared with ``earth_awy.dat``: 11 waypoint, 3 VOR, 2 NDB.

    A hold publishing **neither** a leg time nor a leg length is skipped and
    counted. Every consumer of a hold has to draw or fly one leg or the other,
    so a record carrying neither is not a degraded hold — it is not a hold.
    """
    skip = on_skip if on_skip is not None else _ignore_skip

    for raw in lines:
        line = raw.strip()
        if _is_boilerplate(line):
            continue

        parts = line.split()
        if len(parts) < 8:
            skip("hold row has too few fields", line)
            continue

        course = _as_float(parts[4])
        if course is None or not 0.0 <= course <= 360.0:
            skip("hold row has a non-numeric or out-of-range inbound course", line)
            continue

        turn = parts[7].strip().upper()
        if turn not in {"L", "R"}:
            skip("hold row has an unrecognised turn direction", line)
            continue

        leg_time = _positive(_as_float(parts[5]))
        leg_length = _positive(_as_float(parts[6]))
        if leg_time is None and leg_length is None:
            skip("hold row publishes neither a leg time nor a leg length", line)
            continue
        if leg_time is not None:
            # Exactly one measure survives. A hold that published both is held
            # on its time, which is what the ICAO pattern is defined by.
            leg_length = None

        terminal = parts[1].strip().upper()
        yield ParsedHold(
            fix_ident=parts[0].strip().upper(),
            region_code=parts[2].strip().upper() or None,
            airport_icao=None if terminal in {ENROUTE, ""} else terminal,
            fix_type=_as_int(parts[3]),
            inbound_course_mag_deg=course % 360.0,
            leg_time_min=leg_time,
            leg_length_nm=leg_length,
            turn_direction=turn,
            min_altitude_ft=_positive(_as_float(parts[8])) if len(parts) > 8 else None,
            max_altitude_ft=_positive(_as_float(parts[9])) if len(parts) > 9 else None,
            speed_kt=_positive(_as_float(parts[10])) if len(parts) > 10 else None,
        )


# ---------------------------------------------------------------------------
# Field readers — every one returns None rather than raising
# ---------------------------------------------------------------------------


def _is_boilerplate(line: str) -> bool:
    """True for the file header, the version line, the ``99`` terminator and comments."""
    return (
        not line
        or line in {"I", "A", "99"}
        or line.startswith(("#", "99 "))
        or _VERSION_LINE.match(line) is not None
    )


def _on_the_globe(latitude: float, longitude: float) -> bool:
    return -90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0


def _positive(value: float | None) -> float | None:
    """``0`` is how these files spell "not published"."""
    return value if value is not None and value > 0.0 else None


def _as_float(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _as_int(text: str) -> int | None:
    try:
        return int(text)
    except ValueError:
        return None


def _ignore_skip(reason: str, line: str) -> None:
    del reason, line
