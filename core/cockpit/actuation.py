"""Pure actuation rules, shared by every adapter (§6.2). No simulator, no I/O.

* :func:`validate_actuation` — the §2.2 kind/value mismatch table, raised as
  ``ValueError`` (422 at the route).
* :func:`is_on` / :func:`toggle_needs_press` — the guarded-toggle rule
  (research §1): press only when the read state disagrees with what is asked.
* :func:`dial_confirmed` — the read-back tolerance check (research §5's drum
  echo is the case the read-binding rule exists for).
* :func:`selector_index` / :func:`selector_steps` — resolve a selector's
  option index and the signed, non-wrapping step count between two indices.
* :func:`plan_setup_actuations` — turns the ``setup_overrides`` block plus an
  ``AircraftSetup`` into an ordered batch of actuations (D11), the mechanism
  Wave 2's Zibo data depends on without re-implementing it.
"""

from __future__ import annotations

from core.cockpit.models import (
    CockpitActuation,
    CockpitCatalogDocument,
    CockpitControlSpec,
    CockpitValue,
)
from core.cockpit.preconditions import precondition_order
from core.models import AircraftSetup

__all__ = [
    "dial_confirmed",
    "is_on",
    "plan_setup_actuations",
    "selector_index",
    "selector_steps",
    "toggle_needs_press",
    "validate_actuation",
]

#: Tolerance for comparing a numeric read-back against a toggle's ``on_value``.
_IS_ON_TOLERANCE = 1e-6

#: Tolerance for comparing a numeric read-back against a selector option's
#: value (the same 1e-6 as ``_IS_ON_TOLERANCE`` and ``core.cockpit.
#: preconditions._NUMERIC_TOLERANCE`` — one convention, three call sites).
_SELECTOR_TOLERANCE = 1e-6


def is_on(value: CockpitValue | None, on_value: float) -> bool:
    """A toggle's status as a bool.

    ``bool`` passes through; numbers compare to ``on_value`` with a 1e-6
    tolerance; ``None`` and strings are ``False``.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return abs(float(value) - on_value) <= _IS_ON_TOLERANCE
    return False


def toggle_needs_press(current: CockpitValue | None, requested: bool, on_value: float) -> bool:
    """Research §1: press only when the read state disagrees.

    An unknown current (``None``) counts as disagreeing — one press is the
    safest guess, and the read-back decides.
    """
    if current is None:
        return True
    return is_on(current, on_value) != requested


def dial_confirmed(written: float, read_back: CockpitValue | None, tolerance: float) -> bool:
    """``abs(read_back - written) <= tolerance``.

    A ``None`` or non-numeric read is never confirmed.
    """
    if read_back is None or isinstance(read_back, bool) or not isinstance(read_back, (int, float)):
        return False
    return abs(float(read_back) - written) <= tolerance


def selector_index(spec: CockpitControlSpec, value: CockpitValue | None) -> int | None:
    """Position of ``value`` among ``spec.options``, or ``None``.

    Numeric options (``int``/``float``/``bool`` — ``bool`` is an ``int``
    subtype in Python) compare within ``_SELECTOR_TOLERANCE``, never by exact
    Python type: a real adapter's Web API reports every numeric dataref as a
    JSON float, so an option declared ``value: 0`` (an ``int``, the catalog
    YAML's natural spelling) must still match a live read-back of ``0.0``.
    Mirrors ``is_on`` and ``core.cockpit.preconditions._condition_satisfied``
    — the same "X-Plane never sends a Python int or bool" lesson (issue #223
    live verification; the identical disease #247 fixed for preconditions).
    String options still compare by exact equality, and a numeric value never
    matches a string option or vice versa.
    """
    if spec.options is None:
        return None
    if isinstance(value, (int, float)):
        for index, option in enumerate(spec.options):
            if (
                isinstance(option.value, (int, float))
                and abs(float(value) - float(option.value)) <= _SELECTOR_TOLERANCE
            ):
                return index
        return None
    for index, option in enumerate(spec.options):
        if not isinstance(option.value, (int, float)) and value == option.value:
            return index
    return None


def selector_steps(current_index: int, target_index: int, option_count: int) -> int:
    """Signed clicks from ``current_index`` to ``target_index``, no wrap-around
    (a rotary selector has stops). Raises ``ValueError`` for an out-of-range index.
    """
    if not 0 <= current_index < option_count or not 0 <= target_index < option_count:
        raise ValueError(
            f"Selector index out of range: current={current_index}, target={target_index}, "
            f"option_count={option_count}."
        )
    return target_index - current_index


def validate_actuation(spec: CockpitControlSpec, actuation: CockpitActuation) -> None:
    """Raise ``ValueError`` with a one-sentence reason on any kind/value mismatch (§2.2)."""
    value = actuation.value
    delta = actuation.delta
    control_id = spec.control_id

    if spec.kind == "press":
        if value is not None or delta is not None:
            raise ValueError(
                f"{control_id!r} is a press control and takes neither value nor delta."
            )
        return

    if spec.kind == "toggle":
        if delta is not None:
            raise ValueError(f"{control_id!r} is a toggle and does not take delta.")
        if not isinstance(value, bool):
            raise ValueError(f"{control_id!r} is a toggle and requires a bool value.")
        return

    if spec.kind == "dial":
        if delta is not None:
            raise ValueError(f"{control_id!r} is a dial and does not take delta.")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{control_id!r} is a dial and requires a numeric value.")
        assert spec.min_value is not None
        assert spec.max_value is not None
        if not spec.min_value <= float(value) <= spec.max_value:
            raise ValueError(
                f"{control_id!r}: {value} is outside [{spec.min_value}, {spec.max_value}]."
            )
        return

    if spec.kind == "encoder":
        if value is not None:
            raise ValueError(f"{control_id!r} is an encoder and takes delta, not value.")
        if delta is None:
            raise ValueError(f"{control_id!r} is an encoder and requires delta.")
        assert spec.max_delta is not None
        if abs(delta) > spec.max_delta:
            raise ValueError(
                f"{control_id!r}: |delta|={abs(delta)} exceeds max_delta={spec.max_delta}."
            )
        return

    if spec.kind == "selector":
        if delta is not None:
            raise ValueError(f"{control_id!r} is a selector and does not take delta.")
        if value is None:
            raise ValueError(f"{control_id!r} is a selector and requires a value.")
        assert spec.options is not None
        # selector_index (not a second hand-rolled equality check, the
        # now-fixed duplicate _selector_matches used to be — issue #223 live
        # verification): one tolerant match rule for "is this value one of
        # my options", shared by validation and actuation alike.
        if selector_index(spec, value) is None:
            raise ValueError(f"{control_id!r}: {value!r} is not among its options.")
        return


def _actuation_value(setup: AircraftSetup, field_name: str) -> CockpitValue:
    value = getattr(setup, field_name)
    assert value is not None
    if isinstance(value, bool):
        return value
    return float(value)


def plan_setup_actuations(
    document: CockpitCatalogDocument, setup: AircraftSetup
) -> tuple[CockpitActuation, ...]:
    """Every set ``AircraftSetup`` field with an entry in ``setup_overrides``, as
    actuations, ordered so that any control appearing in another planned control's
    preconditions comes first (stable topological order over the precondition
    graph; ties keep ``setup_overrides`` declaration order). A bool field becomes
    ``value=bool``, a float field ``value=float``. Fields set to ``None`` are absent.
    """
    provided = setup.model_dump(exclude_none=True)

    planned: list[tuple[str, CockpitValue]] = []
    for field_name, control_id in document.setup_overrides.items():
        if field_name not in provided:
            continue
        planned.append((control_id, _actuation_value(setup, field_name)))

    if not planned:
        return ()

    control_ids = [control_id for control_id, _ in planned]
    ordered_ids = precondition_order(document, control_ids)
    value_by_control_id = dict(planned)
    return tuple(
        CockpitActuation(control_id=control_id, value=value_by_control_id[control_id])
        for control_id in ordered_ids
    )
