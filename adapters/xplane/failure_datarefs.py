"""X-Plane failure dataref mapping — docs/designs/failures-manager.md §5.2.

**Verified against a live X-Plane 12.4.3 install** (:mod:`spikes.failure_datarefs`,
§10.8): the §5.1 value enum (0 = working, 6 = inoperative now) holds — a
dataref was written to 6, read back 6, written to 0, read back 0, restored.
That live session also dumped every one of the 795 datarefs this build
publishes under ``sim/operation/failures/`` and cross-referenced it against
every row below, resolving several "verify in spike" entries into fact,
finding a genuine transcription bug (``instruments.vacuum``'s second dataref
was misspelled ``rel_vacum2``; it is ``rel_vacuum2``, and the wrong name meant
this entry was silently unsupported despite its first dataref resolving
fine), and confirming two entries (``engine.partial_power``,
``airframe.lightning_strike``) have no matching dataref on this build *at
all* — not merely undocumented. ``adapters/xplane/xplane_adapter.py`` then
ran the ``can_inject_failures`` contract suite under ``pytest -m sim``
(inject, clear, clear-all, an indexed engine failure) against this same
install — all passing — before the flag flipped ``True``.

Two things make an entry still shipping unsupported safe (D11, §5.3):

* Every dataref named below is resolved against the Web API's own dataref
  index at :meth:`~adapters.xplane.xplane_adapter.XPlaneSimAdapter.connect`
  time, the same two-tier ``DATAREFS``/``OPTIONAL_DATAREFS`` pattern the rest
  of the adapter already uses for exactly this purpose (an unresolvable
  identifier degrades a control instead of failing the connection or raising
  at call time).
* :attr:`FailureDatarefMapping.unsupported_reason` is set on every catalogue
  entry that has no candidate identifier at all, or whose candidate's
  semantics could not be confirmed this session (``flight_controls.spoilers``,
  ``airframe.pressurisation`` — see their own entries below) — these ship
  permanently unsupported until a human edits this file with a fact a further
  session produces.
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
            "CONFIRMED against a live install (795 datarefs enumerated under "
            "sim/operation/failures/, searched): X-Plane publishes no standard "
            "partial-power failure; use engine.failure or a fuel-system failure."
        ),
    ),
    FailureDatarefMapping(
        failure_id="fuel.leak",
        # CONFIRMED against a live install: sim/operation/failures/rel_fuel_leak exists.
        dataref_templates=(f"{_PREFIX}rel_fuel_leak",),
        confidence="high",
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
        # CONFIRMED against a live X-Plane 12.4.3 install (spikes/failure_datarefs.py):
        # §5.2's own comment claimed the "vacuum" / "vacum2" spelling mismatch between
        # the two idents was deliberate, "not a transcription error" — it was one. The
        # real second dataref is rel_vacuum2 (both u's), not rel_vacum2; the wrong name
        # never resolved, so this entry silently degraded to unsupported (D11) despite
        # rel_vacuum itself resolving fine. Both names now confirmed present.
        dataref_templates=(f"{_PREFIX}rel_vacuum", f"{_PREFIX}rel_vacuum2"),
        confidence="high",
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
            "CONFIRMED against a live install: no simple actuator-style dataref exists "
            "(unlike flight_controls.flaps's rel_flap_act). A candidate family does "
            "exist — sim/operation/failures/rel_fcon_rspo_{1,2}_{lft,rgt}_"
            "{cntr,gone,lock,mxdn,mxup} — but its five-way fly-by-wire failure-mode "
            "taxonomy per side does not match this catalogue's simple binary relay "
            "convention (§5.1: 0 = working, 6 = inoperative now); which sub-mode, if "
            "any, behaves as that simple relay was not determined this session and "
            "needs a follow-up rather than a guess."
        ),
    ),
    FailureDatarefMapping(
        failure_id="gear.stuck",
        # CONFIRMED against a live install: the single-actuator candidate
        # (sim/operation/failures/rel_gear_act) exists — "the actuator that drives
        # gear extension/retraction jams" matches "no longer responds to the handle"
        # (FailureSpec's own description). Medium, not high: the loaded aircraft's
        # gear is fixed (does not retract), so the behavioural effect of this failure
        # could not be observed, only that the dataref itself resolves and accepts
        # the write. The per-leg rel_lagear1-5/rel_lagear_6-10 family also exists and
        # was considered — it reads as a multi-gear-leg complex-aircraft model, a
        # worse fit for a single generic "gear.stuck" entry than one actuator ref.
        dataref_templates=(f"{_PREFIX}rel_gear_act",),
        confidence="medium",
    ),
    FailureDatarefMapping(
        failure_id="gear.brakes",
        # CONFIRMED against a live install: exactly the left/right pair the design's
        # own candidate note anticipated — sim/operation/failures/rel_lbrakes and
        # rel_rbrakes, both real dataref idents on this build.
        dataref_templates=(f"{_PREFIX}rel_lbrakes", f"{_PREFIX}rel_rbrakes"),
        confidence="high",
    ),
    FailureDatarefMapping(
        failure_id="airframe.pressurisation",
        dataref_templates=(),
        confidence="low",
        unsupported_reason=(
            "CONFIRMED against a live install: two candidates exist, "
            "sim/operation/failures/rel_depres_fast and rel_depres_slow, but the "
            "catalogue wants one generic 'pressurisation fails' entry and nothing in "
            "either name settles which single one that is (or whether both should "
            "fire together). The loaded C172 is unpressurised, so neither candidate's "
            "actual effect could be observed this session — needs a follow-up with a "
            "pressurised airframe loaded, or Laminar's own documentation for the pair."
        ),
    ),
    FailureDatarefMapping(
        failure_id="airframe.smoke",
        dataref_templates=(f"{_PREFIX}rel_smoke_cpit",),
        confidence="medium",
    ),
    FailureDatarefMapping(
        failure_id="airframe.bird_strike",
        # CONFIRMED against a live install: sim/operation/failures/rel_bird_strike
        # exists (per-engine rel_bird_strike_eng1/eng2 variants also exist, but this
        # catalogue entry does not take an engine index, so the generic ident is the
        # right one). Medium, not high: the loaded aircraft could not be used to
        # observe an actual visible effect from injecting this failure.
        dataref_templates=(f"{_PREFIX}rel_bird_strike",),
        confidence="medium",
    ),
    FailureDatarefMapping(
        failure_id="airframe.lightning_strike",
        dataref_templates=(),
        confidence="low",
        unsupported_reason=(
            "CONFIRMED against a live install: no dataref under "
            "sim/operation/failures/ matches 'lightning' at all (795 datarefs "
            "enumerated and searched) — this is not an unconfirmed guess anymore, "
            "X-Plane genuinely does not expose a lightning-strike failure on this "
            "build. Stays unsupported."
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
