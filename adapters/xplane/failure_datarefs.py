"""X-Plane failure dataref mapping — docs/designs/failures-manager.md §5.2.

**No simulator has verified any of this yet.** Every row below is transcribed
verbatim from the design document, including its confidence label and its
"verify in spike" caveats — nothing here was invented to fill a gap. The spike
that turns a guess into a fact is :mod:`spikes.failure_datarefs` (§10.8); until
it runs against a live install, this file is best-effort transcription, not
measurement.

Two things make it safe to ship anyway (D11, §5.3):

* Every dataref named below is resolved against the Web API's own dataref
  index at :meth:`~adapters.xplane.xplane_adapter.XPlaneSimAdapter.connect`
  time, the same two-tier ``DATAREFS``/``OPTIONAL_DATAREFS`` pattern the rest
  of the adapter already uses for exactly this purpose (an unresolvable
  identifier degrades a control instead of failing the connection or raising
  at call time).
* :attr:`FailureDatarefMapping.unsupported_reason` is set on every catalogue
  entry that has no candidate identifier at all — there is nothing to probe,
  so these ship permanently unsupported until a human edits this file with a
  fact the spike produced.

``adapters/xplane/xplane_adapter.py`` still declares ``can_inject_failures =
False`` regardless of what this file resolves (docs/designs/failures-manager.md
D11 plus this session's explicit instruction): the enum in §5.1 — which value
means "working" and which means "failed now" — is quoted from X-Plane's
published dataref documentation and is itself unverified against a live
install. Flipping the flag on unverified dataref *behaviour* (as opposed to
unverified dataref *names*, which this module already degrades safely) would
be exactly the dishonest capability declaration hard rule 3 forbids.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import MappingProxyType
from typing import Literal, NamedTuple

from core.failures import CATALOGUE_BY_ID, FAILURE_IDS, FailureId

__all__ = [
    "FAILURE_DATAREFS",
    "STATE_FAILED",
    "STATE_WORKING",
    "FailureDatarefMapping",
    "dataref_paths_for",
    "iter_dataref_combos",
]

#: §5.1 — the ``sim/operation/failures/rel_*`` value convention. Quoted from
#: X-Plane's published dataref documentation; **must be verified against the
#: live install's ``DataRefs.txt`` in the spike** before being trusted as fact
#: (§10.8). The design's correctness does not depend on the exact numerals,
#: only on "there is a *failed now* value and a *working* value" — but the
#: adapter writes these two literals, so if the spike finds them wrong this is
#: the one place to correct.
#:
#: Modes 1-5 (MTBF, exact time, exact speed, exact altitude AGL, key press) are
#: deliberately never written: they are single *global* companion datarefs
#: shared by every armed failure in the sim's own UI, which cannot express two
#: failures armed on two different conditions (D5) — arming lives in
#: ``core/failure_scheduler.py`` instead, and the adapter's whole failure
#: vocabulary is "fail now" (6) and "repair" (0).
STATE_WORKING = 0
STATE_FAILED = 6

FailureDatarefConfidence = Literal["high", "medium", "low"]


class FailureDatarefMapping(NamedTuple):
    """One catalogue entry resolved to zero or more X-Plane dataref templates.

    ``dataref_templates`` are full dataref paths under
    ``sim/operation/failures/``, with ``{n}`` standing for the 0-based engine
    suffix on an indexed entry — the wire's 1-based ``engine_index`` minus one
    (§5.2's header note). Non-indexed templates carry no ``{n}`` and
    ``str.format`` simply ignores the unused keyword.

    An entry can carry **more than one** template (``electrical.system`` needs
    both buses written for a *total* failure to mean what it says) — all of
    them must resolve for the entry to count as supported; a partial resolve
    is treated the same as none, which is the conservative reading of D11.

    ``dataref_templates == ()`` means the design has no candidate name at all
    yet (the "verify in spike" rows with nothing to guess) — there is nothing
    to probe, so ``unsupported_reason`` is always set and the entry ships
    permanently unsupported until a human upgrades this file with a fact.
    """

    failure_id: FailureId
    dataref_templates: tuple[str, ...]
    confidence: FailureDatarefConfidence
    unsupported_reason: str | None = None


_PREFIX = "sim/operation/failures/"

#: §5.2's mapping table, transcribed row for row. Order matches
#: ``FAILURE_IDS`` (checked below) but is not itself load-bearing — lookups are
#: always by id, never by position.
_ENTRIES: tuple[FailureDatarefMapping, ...] = (
    FailureDatarefMapping(
        failure_id="engine.failure",
        dataref_templates=(f"{_PREFIX}rel_engfai{{n}}",),
        confidence="high",
    ),
    FailureDatarefMapping(
        failure_id="engine.fire",
        dataref_templates=(f"{_PREFIX}rel_engfir{{n}}",),
        confidence="high",
    ),
    FailureDatarefMapping(
        failure_id="engine.partial_power",
        dataref_templates=(),
        confidence="low",
        unsupported_reason=(
            "X-Plane publishes no standard partial-power failure; use engine.failure "
            "or a fuel-system failure."
        ),
    ),
    FailureDatarefMapping(
        failure_id="fuel.leak",
        dataref_templates=(),
        confidence="low",
        unsupported_reason=(
            "The X-Plane 12 failure UI lists a fuel leak, but the dataref ident is "
            "unconfirmed — verify against a live install's DataRefs.txt "
            "(spikes/failure_datarefs.py)."
        ),
    ),
    FailureDatarefMapping(
        failure_id="electrical.system",
        # Both buses — a total electrical failure, which is what the scenario needs.
        dataref_templates=(f"{_PREFIX}rel_esys", f"{_PREFIX}rel_esys2"),
        confidence="medium",
    ),
    FailureDatarefMapping(
        failure_id="electrical.generator",
        dataref_templates=(f"{_PREFIX}rel_genera{{n}}",),
        confidence="high",
    ),
    FailureDatarefMapping(
        failure_id="hydraulics.system",
        dataref_templates=(f"{_PREFIX}rel_hydpmp", f"{_PREFIX}rel_hydpmp2"),
        confidence="medium",
    ),
    FailureDatarefMapping(
        failure_id="instruments.pitot",
        dataref_templates=(f"{_PREFIX}rel_pitot",),  # pilot side
        confidence="high",
    ),
    FailureDatarefMapping(
        failure_id="instruments.static",
        dataref_templates=(f"{_PREFIX}rel_static",),  # pilot side
        confidence="high",
    ),
    FailureDatarefMapping(
        failure_id="instruments.vacuum",
        # Names as given in §5.2, verbatim, including the "vacuum" / "vacum2" spelling
        # mismatch between the two idents — not a transcription error here.
        dataref_templates=(f"{_PREFIX}rel_vacuum", f"{_PREFIX}rel_vacum2"),
        confidence="medium",
    ),
    FailureDatarefMapping(
        failure_id="instruments.airspeed",
        dataref_templates=(f"{_PREFIX}rel_ss_asi",),
        confidence="high",
    ),
    FailureDatarefMapping(
        failure_id="instruments.attitude",
        dataref_templates=(f"{_PREFIX}rel_ss_ahz",),
        confidence="high",
    ),
    FailureDatarefMapping(
        failure_id="instruments.altimeter",
        dataref_templates=(f"{_PREFIX}rel_ss_alt",),
        confidence="high",
    ),
    FailureDatarefMapping(
        failure_id="instruments.directional_gyro",
        dataref_templates=(f"{_PREFIX}rel_ss_dgy",),
        confidence="high",
    ),
    FailureDatarefMapping(
        failure_id="instruments.turn_coordinator",
        dataref_templates=(f"{_PREFIX}rel_ss_tsi",),
        confidence="high",
    ),
    FailureDatarefMapping(
        failure_id="instruments.vsi",
        dataref_templates=(f"{_PREFIX}rel_ss_vvi",),
        confidence="high",
    ),
    FailureDatarefMapping(
        failure_id="avionics.com1",
        dataref_templates=(f"{_PREFIX}rel_com1",),
        confidence="high",
    ),
    FailureDatarefMapping(
        failure_id="avionics.com2",
        dataref_templates=(f"{_PREFIX}rel_com2",),
        confidence="high",
    ),
    FailureDatarefMapping(
        failure_id="avionics.nav1",
        dataref_templates=(f"{_PREFIX}rel_nav1",),
        confidence="high",
    ),
    FailureDatarefMapping(
        failure_id="avionics.nav2",
        dataref_templates=(f"{_PREFIX}rel_nav2",),
        confidence="high",
    ),
    FailureDatarefMapping(
        failure_id="avionics.gps",
        dataref_templates=(f"{_PREFIX}rel_gps",),
        confidence="medium",
    ),
    FailureDatarefMapping(
        failure_id="avionics.transponder",
        dataref_templates=(f"{_PREFIX}rel_xpndr",),
        confidence="medium",
    ),
    FailureDatarefMapping(
        failure_id="flight_controls.flaps",
        # The actuator fails; the surface freezes where it is (FailureSpec.description
        # says exactly that — "flaps failed" reads as "flaps up" otherwise).
        dataref_templates=(f"{_PREFIX}rel_flap_act",),
        confidence="medium",
    ),
    FailureDatarefMapping(
        failure_id="flight_controls.spoilers",
        dataref_templates=(),
        confidence="low",
        unsupported_reason=(
            "No candidate dataref ident yet — verify against a live install's "
            "DataRefs.txt (spikes/failure_datarefs.py)."
        ),
    ),
    FailureDatarefMapping(
        failure_id="gear.stuck",
        dataref_templates=(),
        confidence="low",
        unsupported_reason=(
            "Candidates only, not verified: a per-leg rel_lagear* family vs a single "
            "actuator ref — verify against a live install's DataRefs.txt "
            "(spikes/failure_datarefs.py) before mapping either."
        ),
    ),
    FailureDatarefMapping(
        failure_id="gear.brakes",
        dataref_templates=(),
        confidence="low",
        unsupported_reason=(
            "Candidates only, not verified: a left/right pair, both to be written for "
            "one entry — verify against a live install's DataRefs.txt "
            "(spikes/failure_datarefs.py)."
        ),
    ),
    FailureDatarefMapping(
        failure_id="airframe.pressurisation",
        dataref_templates=(),
        confidence="low",
        unsupported_reason=(
            "No candidate dataref ident yet — verify against a live install's "
            "DataRefs.txt (spikes/failure_datarefs.py)."
        ),
    ),
    FailureDatarefMapping(
        failure_id="airframe.smoke",
        dataref_templates=(f"{_PREFIX}rel_smoke_cpit",),
        confidence="medium",
    ),
    FailureDatarefMapping(
        failure_id="airframe.bird_strike",
        dataref_templates=(),
        confidence="low",
        unsupported_reason=(
            "Present in the X-Plane 12 failure UI, but its dataref ident is "
            "unconfirmed — verify against a live install's DataRefs.txt "
            "(spikes/failure_datarefs.py)."
        ),
    ),
    FailureDatarefMapping(
        failure_id="airframe.lightning_strike",
        dataref_templates=(),
        confidence="low",
        unsupported_reason=(
            "Present in the X-Plane 12 failure UI, but its dataref ident is "
            "unconfirmed — verify against a live install's DataRefs.txt "
            "(spikes/failure_datarefs.py)."
        ),
    ),
)

FAILURE_DATAREFS: MappingProxyType[FailureId, FailureDatarefMapping] = MappingProxyType(
    {entry.failure_id: entry for entry in _ENTRIES}
)

#: The ``CATALOGUE_BY_ID`` drift guard, restated here: every catalogue id must
#: have a row in this file (even if that row is "unsupported, no candidate"),
#: and this file must never invent an id the catalogue does not have.
assert set(FAILURE_DATAREFS) == set(FAILURE_IDS), (
    "adapters/xplane/failure_datarefs.py is out of sync with core/failures.py's "
    "FAILURE_IDS — every catalogue entry needs a row here, even an unsupported one."
)


def dataref_paths_for(failure_id: FailureId, engine_index: int | None) -> tuple[str, ...]:
    """The concrete dataref paths one ``(failure_id, engine_index)`` combination needs.

    ``engine_index`` is 1-based (the wire convention); the 0-based suffix
    X-Plane's own naming uses is derived here so callers never repeat that
    arithmetic. Returns ``()`` for an entry with no known dataref at all.

    Args:
        failure_id: A catalogue id.
        engine_index: 1-based engine index for an indexed entry, ``None`` for
            a non-indexed one. Not validated against
            ``FailureSpec.takes_engine_index`` — callers already know which
            shape they are asking for; see :func:`iter_dataref_combos` for the
            enumeration that does respect it.

    Returns:
        Full dataref paths, e.g. ``("sim/operation/failures/rel_engfai0",)``.
    """
    mapping = FAILURE_DATAREFS[failure_id]
    suffix = "" if engine_index is None else str(engine_index - 1)
    return tuple(template.format(n=suffix) for template in mapping.dataref_templates)


def iter_dataref_combos() -> Iterator[tuple[FailureId, int | None]]:
    """Every ``(failure_id, engine_index)`` combination worth probing at connect time.

    Non-indexed entries yield exactly one combo, ``engine_index=None``.
    Indexed entries yield one per wire-visible engine index, 1..8 —
    ``FailureRef.engine_index``'s own bound (§3.1: ``ge=1, le=8``). Entries
    with no known dataref (``dataref_templates == ()``) are skipped entirely:
    there is nothing to probe, and :attr:`FailureDatarefMapping.unsupported_reason`
    already answers "why not" without a network round trip.
    """
    for failure_id, mapping in FAILURE_DATAREFS.items():
        if not mapping.dataref_templates:
            continue
        spec = CATALOGUE_BY_ID[failure_id]
        if spec.takes_engine_index:
            for engine_index in range(1, 9):
                yield (failure_id, engine_index)
        else:
            yield (failure_id, None)
