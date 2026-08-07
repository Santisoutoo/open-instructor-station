"""Reader for ``apt.dat`` — airports, runways and parking positions.

``apt.dat`` is the biggest file the index touches by an order of magnitude:
380 MB and 12.35 million lines on a stock X-Plane 12, of which roughly 90% is
taxiway and pavement geometry (row codes ``110``-``116``) that this project
never reads.

**One optimisation is required, and it is the only one.** Every line is tested
against :data:`INTERESTING_PREFIXES` with :meth:`str.startswith` on the
*untouched* string, before any ``split()``. Splitting first and branching on the
row code afterwards is the difference between a one-minute build and a
five-minute one, and it is the single reason the user's first run is bearable.

Only land-airport headers (``1``) and their runways (``100``), ramp starts
(``1300``/``1301``) and metadata (``1302``) are read. Water runways (``101``)
and helipads (``102``) are out of scope for Phase 1, which is what keeps
``Runway.ident``'s three-character bound honest. Seaplane-base (``16``) and
heliport (``17``) headers *are* recognised, not to index them but because they
**end** the preceding airport's block: without them a heliport's ramp starts
would silently attach to the last land airport parsed.

Nothing here opens a file. The caller streams lines in, so the same parser
covers a real 380 MB install and a ten-line fixture.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field

from core.geodesy import (
    METRES_PER_NAUTICAL_MILE,
    distance_and_bearing,
    point_at_distance_and_bearing,
)
from core.models import GeoPosition, RunwaySurface
from core.navdata.models import ParkingKind, ParkingOperation

__all__ = [
    "INTERESTING_PREFIXES",
    "ParsedAirport",
    "ParsedParking",
    "ParsedRunwayEnd",
    "SkipSink",
    "iter_airports",
]

#: The only row codes this reader cares about, as raw line prefixes.
#:
#: Tested with ``str.startswith`` against the untouched line — a C-level scan of
#: a handful of short prefixes — so the 11 million taxiway rows of a real
#: ``apt.dat`` are rejected without ever being split. Both a space and a tab
#: separator are listed because the format permits either.
INTERESTING_PREFIXES: tuple[str, ...] = (
    "1 ", "1\t",
    "16 ", "16\t",
    "17 ", "17\t",
    "100 ", "100\t",
    "1300 ", "1300\t",
    "1301 ", "1301\t",
    "1302 ", "1302\t",
)  # fmt: skip

#: Called with ``(reason, line)`` for every record that could not be read. A
#: malformed record is skipped and counted; it never fails the build, because
#: real navdata always contains a handful of them and an instructor station that
#: refuses to start because one airport has a bad runway row is useless.
SkipSink = Callable[[str, str], None]

#: ``apt.dat`` surface codes, mapped onto the shared vocabulary.
_SURFACES: dict[int, RunwaySurface] = {
    1: "asphalt",
    2: "concrete",
    3: "grass",
    4: "dirt",
    5: "gravel",
    12: "dry_lakebed",
    13: "water",
    14: "snow",
    15: "transparent",
}

_PARKING_KINDS: frozenset[str] = frozenset({"gate", "hangar", "tie_down", "misc"})
_PARKING_OPERATIONS: frozenset[str] = frozenset(
    {"none", "general_aviation", "airline", "cargo", "military"}
)

#: Row codes that start a new airport block. Only ``1`` is indexed; the other
#: two are here so their contents do not leak into the airport before them.
_AIRPORT_HEADERS: frozenset[str] = frozenset({"1", "16", "17"})


@dataclass(frozen=True)
class ParsedRunwayEnd:
    """One end of one runway, with its geometry already resolved.

    ``apt.dat`` publishes the **pavement end** and the displacement separately;
    :attr:`threshold` is the displaced landing threshold, walked forward along
    the runway axis, because that is the point an aircraft on final aims at and
    the origin every approach placement is measured back from.
    """

    ident: str
    opposite_ident: str
    threshold_lat: float
    threshold_lon: float
    end_lat: float
    end_lon: float
    true_bearing_deg: float
    length_m: float
    displaced_threshold_m: float
    width_m: float | None
    surface: RunwaySurface | None


@dataclass(frozen=True)
class ParsedParking:
    """One ramp start: a gate, a stand, a hangar spot or a tie-down."""

    name: str
    latitude: float
    longitude: float
    heading_true_deg: float
    kind: ParkingKind
    aircraft_types: str | None
    operation: ParkingOperation | None
    airline_codes: str | None


@dataclass
class ParsedAirport:
    """One land airport and everything indexed from its block."""

    icao: str
    name: str
    elevation_ft: float
    has_tower: bool
    latitude: float | None = None
    longitude: float | None = None
    iata: str | None = None
    city: str | None = None
    country: str | None = None
    region_code: str | None = None
    transition_altitude_ft: int | None = None
    transition_level_ft: int | None = None
    magnetic_variation_deg: float | None = None
    runways: list[ParsedRunwayEnd] = field(default_factory=list)
    parking: list[ParsedParking] = field(default_factory=list)

    @property
    def runway_count(self) -> int:
        """Runway **ends**: ``18L`` and ``36R`` count as two, as they do everywhere else."""
        return len(self.runways)

    @property
    def longest_runway_m(self) -> float | None:
        """Longest pavement, used to rank a type-ahead hit above a nearby airstrip."""
        return max((r.length_m for r in self.runways), default=None)


def iter_airports(
    lines: Iterable[str], *, on_skip: SkipSink | None = None
) -> Iterator[ParsedAirport]:
    """Stream land airports out of ``apt.dat`` lines.

    Args:
        lines: The file, line by line. Not read eagerly — a 380 MB source is
            never held in memory.
        on_skip: Called with ``(reason, line)`` for each malformed record.

    Yields:
        One :class:`ParsedAirport` per land-airport block, in file order.
        Airports whose position cannot be established at all are skipped and
        reported: an airport with no coordinate cannot be searched, drawn or
        flown to, so indexing it would only produce a row that fails later.
    """
    skip = on_skip if on_skip is not None else _ignore_skip
    current: ParsedAirport | None = None

    for raw in lines:
        if not raw.startswith(INTERESTING_PREFIXES):
            continue

        # The longest code of interest is four characters, so the row code is
        # always complete within the first five. Splitting that slice keeps the
        # allocation to five bytes on the 10% of lines that got this far, and
        # zero on the 90% the prefix test already rejected.
        code = raw[:5].split(maxsplit=1)[0]

        if code in _AIRPORT_HEADERS:
            if current is not None:
                finished = _finalise(current, skip)
                if finished is not None:
                    yield finished
            current = _parse_airport_header(raw, skip) if code == "1" else None
            continue

        if current is None:
            # A row belonging to a seaplane base or heliport, or to a header we
            # could not parse. Deliberately dropped rather than misattributed.
            continue

        if code == "100":
            current.runways.extend(_parse_runway(raw, skip))
        elif code == "1300":
            stand = _parse_parking(raw, skip)
            if stand is not None:
                current.parking.append(stand)
        elif code == "1301":
            _apply_parking_metadata(current, raw)
        elif code == "1302":
            _apply_metadata(current, raw)

    if current is not None:
        finished = _finalise(current, skip)
        if finished is not None:
            yield finished


# ---------------------------------------------------------------------------
# Row readers
# ---------------------------------------------------------------------------


def _parse_airport_header(raw: str, skip: SkipSink) -> ParsedAirport | None:
    """``1 <elevation_ft> <deprecated> <deprecated> <code> <name...>``."""
    parts = raw.split(maxsplit=5)
    if len(parts) < 5:
        skip("airport header has too few fields", raw)
        return None

    elevation_ft = _as_float(parts[1])
    if elevation_ft is None:
        skip("airport header has a non-numeric elevation", raw)
        return None

    code = parts[4].strip().upper()
    if not 2 <= len(code) <= 7:
        skip("airport code is not 2-7 characters", raw)
        return None

    return ParsedAirport(
        icao=code,
        name=parts[5].strip() if len(parts) > 5 else code,
        elevation_ft=elevation_ft,
        # Field 3 is documented as deprecated and was historically the control
        # tower flag. It is the only tower signal the four row types this reader
        # reads carry, so it is taken at face value and no more is claimed.
        has_tower=_as_float(parts[2]) not in (None, 0.0),
    )


def _parse_runway(raw: str, skip: SkipSink) -> list[ParsedRunwayEnd]:
    """``100 <width> <surface> ... <ident1> <lat1> <lon1> <disp1> ... <ident2> <lat2> <lon2> ...``.

    A row describes a strip; the index stores its two **ends**, because a
    placement is always relative to one of them.
    """
    parts = raw.split()
    if len(parts) < 21:
        skip("runway row has too few fields", raw)
        return []

    width_m = _as_float(parts[1])
    surface = _SURFACES.get(_as_int(parts[2]) or -1, "unknown")

    first = _parse_runway_end(parts, 8, skip, raw)
    second = _parse_runway_end(parts, 17, skip, raw)
    if first is None or second is None:
        return []

    ident_a, lat_a, lon_a, displaced_a = first
    ident_b, lat_b, lon_b, displaced_b = second

    length_nm, bearing_a = distance_and_bearing(
        GeoPosition(latitude=lat_a, longitude=lon_a, altitude_ft=0.0),
        GeoPosition(latitude=lat_b, longitude=lon_b, altitude_ft=0.0),
    )
    if length_nm <= 0.0:
        skip("runway ends are coincident", raw)
        return []

    _, bearing_b = distance_and_bearing(
        GeoPosition(latitude=lat_b, longitude=lon_b, altitude_ft=0.0),
        GeoPosition(latitude=lat_a, longitude=lon_a, altitude_ft=0.0),
    )
    length_m = length_nm * METRES_PER_NAUTICAL_MILE

    return [
        _build_end(
            ident_a, ident_b, lat_a, lon_a, bearing_a, length_m, displaced_a, width_m, surface
        ),
        _build_end(
            ident_b, ident_a, lat_b, lon_b, bearing_b, length_m, displaced_b, width_m, surface
        ),
    ]


def _parse_runway_end(
    parts: list[str], offset: int, skip: SkipSink, raw: str
) -> tuple[str, float, float, float] | None:
    """Read ``<ident> <lat> <lon> <displaced_m>`` starting at ``offset``."""
    if len(parts) <= offset + 3:
        skip("runway end has too few fields", raw)
        return None

    ident = parts[offset].strip().upper()
    latitude = _as_float(parts[offset + 1])
    longitude = _as_float(parts[offset + 2])
    displaced_m = _as_float(parts[offset + 3]) or 0.0

    if not ident or len(ident) > 3:
        skip("runway ident is empty or longer than three characters", raw)
        return None
    if latitude is None or longitude is None:
        skip("runway end has a non-numeric coordinate", raw)
        return None
    if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
        skip("runway end is off the globe", raw)
        return None

    return ident, latitude, longitude, max(displaced_m, 0.0)


def _build_end(
    ident: str,
    opposite: str,
    latitude: float,
    longitude: float,
    bearing_deg: float,
    length_m: float,
    displaced_m: float,
    width_m: float | None,
    surface: RunwaySurface | None,
) -> ParsedRunwayEnd:
    """Walk the pavement end forward by the displacement to get the threshold.

    ``apt.dat`` publishes the start of the pavement; the landing threshold sits
    some way down the runway from it. At LEMD 18L those two points are ~496 m
    apart, which is 0.27 NM of error on a 10 NM final before any other source of
    error is considered. A zero displacement short-circuits so the threshold is
    bit-for-bit the published coordinate rather than a geodesic round trip.
    """
    if displaced_m > 0.0:
        walked = point_at_distance_and_bearing(
            GeoPosition(latitude=latitude, longitude=longitude, altitude_ft=0.0),
            displaced_m / METRES_PER_NAUTICAL_MILE,
            bearing_deg,
        )
        threshold_lat, threshold_lon = walked.latitude, walked.longitude
    else:
        threshold_lat, threshold_lon = latitude, longitude

    return ParsedRunwayEnd(
        ident=ident,
        opposite_ident=opposite,
        threshold_lat=threshold_lat,
        threshold_lon=threshold_lon,
        end_lat=latitude,
        end_lon=longitude,
        true_bearing_deg=bearing_deg,
        length_m=length_m,
        displaced_threshold_m=displaced_m,
        width_m=width_m if width_m is not None and width_m > 0.0 else None,
        surface=surface,
    )


def _parse_parking(raw: str, skip: SkipSink) -> ParsedParking | None:
    """``1300 <lat> <lon> <heading_true> <kind> <aircraft types> <name...>``."""
    parts = raw.split(maxsplit=6)
    if len(parts) < 6:
        skip("ramp start has too few fields", raw)
        return None

    latitude = _as_float(parts[1])
    longitude = _as_float(parts[2])
    heading = _as_float(parts[3])
    if latitude is None or longitude is None or heading is None:
        skip("ramp start has a non-numeric coordinate or heading", raw)
        return None

    kind_text = parts[4].strip().lower()
    kind: ParkingKind = kind_text if kind_text in _PARKING_KINDS else "misc"  # type: ignore[assignment]

    types = parts[5].strip()
    return ParsedParking(
        name=parts[6].strip() if len(parts) > 6 else kind_text,
        latitude=latitude,
        longitude=longitude,
        heading_true_deg=heading % 360.0,
        kind=kind,
        aircraft_types=types if types and types != "all" else None,
        operation=None,
        airline_codes=None,
    )


def _apply_parking_metadata(airport: ParsedAirport, raw: str) -> None:
    """``1301 <width code> <operation> <airline codes...>`` — decorates the ramp start above it.

    Row ``1301`` is not in the four codes this reader nominally handles, but the
    ``operation`` and ``airline_codes`` columns of the schema have no other
    source: without it every stand reads as unassigned and the UI cannot tell a
    cargo apron from an airline gate.
    """
    if not airport.parking:
        return

    parts = raw.split(maxsplit=3)
    if len(parts) < 3:
        return

    operation_text = parts[2].strip().lower()
    operation: ParkingOperation | None = (
        operation_text if operation_text in _PARKING_OPERATIONS else None  # type: ignore[assignment]
    )
    codes = parts[3].strip() if len(parts) > 3 else ""

    previous = airport.parking[-1]
    airport.parking[-1] = ParsedParking(
        name=previous.name,
        latitude=previous.latitude,
        longitude=previous.longitude,
        heading_true_deg=previous.heading_true_deg,
        kind=previous.kind,
        aircraft_types=previous.aircraft_types,
        operation=operation,
        airline_codes=codes or None,
    )


def _apply_metadata(airport: ParsedAirport, raw: str) -> None:
    """``1302 <key> <value...>`` — the airport's published metadata, key by key.

    Unknown keys are ignored rather than reported: the ``1302`` namespace is
    open-ended and every X-Plane release adds a few, so treating an unfamiliar
    one as a malformed record would count thousands of perfectly good rows.
    """
    parts = raw.split(maxsplit=2)
    if len(parts) < 3:
        return
    key = parts[1].strip().lower()
    value = parts[2].strip()
    if not value:
        return

    if key == "icao_code":
        code = value.upper()
        if 2 <= len(code) <= 7:
            airport.icao = code
    elif key == "iata_code":
        airport.iata = value.upper()
    elif key == "city":
        airport.city = value
    elif key == "country":
        airport.country = value
    elif key == "region_code":
        airport.region_code = value.upper()
    elif key == "datum_lat":
        airport.latitude = _as_float(value)
    elif key == "datum_lon":
        airport.longitude = _as_float(value)
    elif key == "transition_alt":
        airport.transition_altitude_ft = _as_altitude(value)
    elif key == "transition_level":
        airport.transition_level_ft = _as_altitude(value)
    elif key == "magnetic_variation":
        airport.magnetic_variation_deg = _as_float(value)


def _finalise(airport: ParsedAirport, skip: SkipSink) -> ParsedAirport | None:
    """Fill in the reference point and reject an airport that has no position at all.

    ``1302 datum_lat``/``datum_lon`` is the published reference point and wins.
    Failing that the runway ends, then the ramp starts, give a usable centre —
    an airport whose datum is missing is still perfectly searchable from the
    middle of its own pavement.
    """
    if airport.latitude is None or airport.longitude is None:
        centre = _centroid(airport)
        if centre is None:
            skip("airport has no datum, runway or ramp start to take a position from", airport.icao)
            return None
        airport.latitude, airport.longitude = centre
    return airport


def _centroid(airport: ParsedAirport) -> tuple[float, float] | None:
    points = [(r.threshold_lat, r.threshold_lon) for r in airport.runways]
    points += [(p.latitude, p.longitude) for p in airport.parking]
    if not points:
        return None
    return (
        sum(lat for lat, _ in points) / len(points),
        sum(lon for _, lon in points) / len(points),
    )


# ---------------------------------------------------------------------------
# Field readers — every one of them returns None rather than raising
# ---------------------------------------------------------------------------


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


def _as_altitude(text: str) -> int | None:
    """Read a transition altitude or level, published either in feet or as ``FL60``."""
    cleaned = text.strip().upper()
    if cleaned.startswith("FL"):
        level = _as_int(cleaned[2:])
        return level * 100 if level is not None else None
    value = _as_float(cleaned)
    return int(value) if value is not None else None


def _ignore_skip(reason: str, line: str) -> None:
    """Default :data:`SkipSink`: a caller that does not count still must not crash."""
    del reason, line
