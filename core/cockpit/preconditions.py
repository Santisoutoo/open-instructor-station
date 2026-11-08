"""Precondition evaluation and ordering — pure functions, no simulator (§6.3).

``unmet_preconditions`` is evaluated by an adapter against a fresh read of the
referenced controls immediately before acting (D9); ``precondition_order`` is
the mechanism ``core.cockpit.actuation.plan_setup_actuations`` uses to order a
batch of planned actuations so a dependency (e.g. a flight director) is
actuated before the control whose precondition names it (research §2).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from core.cockpit.models import (
    CockpitCatalogDocument,
    CockpitControlSpec,
    CockpitValue,
    ControlCondition,
    PreconditionGroup,
)

__all__ = ["precondition_order", "referenced_control_ids", "unmet_preconditions"]

#: Tolerance for a numeric ``equals`` comparison — mirrors
#: ``core.cockpit.actuation.is_on``'s own tolerance.
_NUMERIC_TOLERANCE = 1e-6


def referenced_control_ids(spec: CockpitControlSpec) -> frozenset[str]:
    """The ids an actuation of ``spec`` must read first."""
    return frozenset(
        condition.control_id for group in spec.preconditions for condition in group.any_of
    )


def _condition_satisfied(condition: ControlCondition, value: CockpitValue) -> bool:
    """``bool`` is a subtype of ``int`` in Python, so ``isinstance(x, (int, float))``
    already matches ``bool`` — this one numeric branch is symmetric over all four
    bool/numeric combinations (bool==bool, bool==numeric, numeric==bool,
    numeric==numeric), comparing at their 1.0/0.0 equivalent within tolerance.
    This mirrors ``core.cockpit.actuation.is_on``'s convention: a real adapter
    (e.g. X-Plane's Web API) reports every toggle-status dataref as a JSON float,
    never a Python bool, so a catalog's ``equals=True`` must match a live ``1.0``.
    A non-numeric ``equals`` (e.g. a string) never matches a numeric value, and
    vice versa — only the final fallback handles that case.
    """
    equals = condition.equals
    if isinstance(equals, (int, float)) and isinstance(value, (int, float)):
        return abs(float(value) - float(equals)) <= _NUMERIC_TOLERANCE
    return equals == value


def unmet_preconditions(
    spec: CockpitControlSpec, states: Mapping[str, CockpitValue | None]
) -> tuple[PreconditionGroup, ...]:
    """Every group with no satisfied member.

    A referenced control missing from ``states``, or reading ``None``, is
    unsatisfied — "unknown" is never a pass.
    """
    unmet: list[PreconditionGroup] = []
    for group in spec.preconditions:
        satisfied = False
        for condition in group.any_of:
            if condition.control_id not in states:
                continue
            value = states[condition.control_id]
            if value is None:
                continue
            if _condition_satisfied(condition, value):
                satisfied = True
                break
        if not satisfied:
            unmet.append(group)
    return tuple(unmet)


def precondition_order(
    document: CockpitCatalogDocument, control_ids: Iterable[str]
) -> tuple[str, ...]:
    """Topological order of ``control_ids`` over the document's precondition edges
    (dependency first). Raises ``ValueError`` on a cycle — also rejected at load time.

    Restricted to ``control_ids``: a referenced control outside that set is
    irrelevant to the requested order.
    """
    ids = list(control_ids)
    id_set = set(ids)
    by_id = {control.control_id: control for control in document.controls}
    for control_id in ids:
        if control_id not in by_id:
            raise ValueError(f"{control_id!r} is not a control in this document.")

    deps = {control_id: referenced_control_ids(by_id[control_id]) & id_set for control_id in ids}

    remaining = list(ids)
    resolved: set[str] = set()
    result: list[str] = []
    while remaining:
        progressed = False
        for control_id in list(remaining):
            if deps[control_id] <= resolved:
                result.append(control_id)
                resolved.add(control_id)
                remaining.remove(control_id)
                progressed = True
        if not progressed:
            raise ValueError(f"Precondition cycle detected among {sorted(remaining)!r}.")
    return tuple(result)
