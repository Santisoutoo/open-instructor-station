"""Identifier normalisation, applied at the boundary so no caller branches on a source quirk.

The two navdata sources spell the same runway differently — ``apt.dat`` says
``18L`` and the CIFP says ``RW18L`` — and the CIFP additionally uses transition
idents that are not runways at all: named transitions, ``ALL``, and *parallel
groups* like ``RW32B`` meaning "both 32s". Every one of those is resolved here,
once, against the airport's real runway list.

Pure functions over strings. No I/O, no models, no state.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable

__all__ = [
    "expand_runway_transition",
    "normalize_icao",
    "normalize_runway_ident",
    "normalize_search_text",
]


def normalize_icao(icao: str) -> str:
    """Upper-case and strip an ICAO code."""
    return icao.strip().upper()


def normalize_runway_ident(ident: str) -> str:
    """Reduce a runway identifier to its ``apt.dat`` form.

    ``"RW18L"`` and ``"18L"`` both become ``"18L"``. Leading zeros are kept —
    ``08R`` is how the source spells it and how a chart prints it.
    """
    cleaned = ident.strip().upper()
    if cleaned.startswith("RW"):
        cleaned = cleaned[2:]
    return cleaned


def normalize_search_text(text: str) -> str:
    """Casefold and strip accents, so ``"Suárez"`` is found by typing ``"suarez"``.

    Decomposes to NFD and drops the combining marks, which turns every accented
    Latin character into its base letter without a per-language table.
    """
    decomposed = unicodedata.normalize("NFD", text.strip())
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return unicodedata.normalize("NFC", without_marks).casefold()


def expand_runway_transition(transition: str, airport_runways: Iterable[str]) -> tuple[str, ...]:
    """Resolve a CIFP transition ident to the real runways it serves.

    Expansion is done **against the airport's actual runway list**, never by
    assuming a parallel pair exists. That is what makes ``RW32B`` right at an
    airport with 32L/32C/32R and right at one with only 32L/32R.

    Args:
        transition: The transition ident from the CIFP record. May be a runway
            (``"RW14R"``), a parallel group (``"RW32B"``), a bare runway number
            (``"RW18"``), ``"ALL"``, blank, or a named transition (``"ADUXO"``).
        airport_runways: The airport's real runway idents, in ``apt.dat`` form.

    Returns:
        The runway idents this transition serves, sorted. **Empty** for a named
        transition — the caller keeps the name in ``transition`` instead.

    Examples:
        >>> expand_runway_transition("RW32B", ["32L", "32R", "14L", "14R"])
        ('32L', '32R')
        >>> expand_runway_transition("ADUXO", ["32L"])
        ()
    """
    runways = sorted({normalize_runway_ident(r) for r in airport_runways})
    cleaned = transition.strip().upper()

    if not cleaned or cleaned == "ALL":
        return tuple(runways)

    if not cleaned.startswith("RW"):
        # A named transition, e.g. "ADUXO". It serves no specific runway.
        return ()

    ident = cleaned[2:]

    # An exact runway: "RW14R" -> "14R".
    if ident in runways:
        return (ident,)

    # A parallel group: "RW32B" means every 32* the airport really has. The B is
    # a group marker, not a designator, so it is stripped before matching.
    if ident.endswith("B"):
        number = ident[:-1]
        matches = tuple(r for r in runways if _runway_number(r) == number)
        if matches:
            return matches

    # A bare number: "RW18" at an airport that spells it "18L"/"18R".
    matches = tuple(r for r in runways if _runway_number(r) == ident)
    if matches:
        return matches

    # The transition names a runway this airport does not have. Report nothing
    # rather than guessing: a placement must never be offered on an invented
    # runway.
    return ()


def _runway_number(ident: str) -> str:
    """The numeric part of a runway ident: ``"32L"`` -> ``"32"``."""
    return "".join(ch for ch in ident if ch.isdigit())
