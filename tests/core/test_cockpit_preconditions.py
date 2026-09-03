"""Unit tests for ``core.cockpit.preconditions`` (docs/designs/cockpit-control-catalog.md
§6.3, §8.1).

Written before the implementation exists (Wave 1 Track A of #220): every test
here is expected to fail with ``ModuleNotFoundError`` until ``core/cockpit/``
is built. That failure is the deliverable, not a bug in this file.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from core.cockpit.catalog import CockpitCatalogLoadError, load_catalog_dir
from core.cockpit.models import (
    CockpitCatalogDocument,
    CockpitControlSpec,
    ControlCondition,
    PreconditionGroup,
)
from core.cockpit.preconditions import (
    precondition_order,
    referenced_control_ids,
    unmet_preconditions,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "cockpit"
VERIFIED_ON = datetime.date(2026, 9, 2)


def _fake_trainer_document() -> CockpitCatalogDocument:
    return load_catalog_dir(FIXTURE_DIR / "fake-trainer")


def _hdg_sel_spec() -> CockpitControlSpec:
    """The ``hdg_sel`` control from the fake-trainer fixture: a toggle whose
    single precondition group is satisfied by ``fd_capt`` OR ``cmd_a``
    (docs/designs/cockpit-control-catalog.md §4.1)."""
    doc = _fake_trainer_document()
    (spec,) = [c.spec for c in doc.controls if c.control_id == "hdg_sel"]
    return spec


# ---------------------------------------------------------------------------
# unmet_preconditions — §8.1's pinned values
# ---------------------------------------------------------------------------


def test_unmet_preconditions_when_neither_condition_holds() -> None:
    spec = _hdg_sel_spec()
    result = unmet_preconditions(spec, {"fd_capt": False, "cmd_a": False})
    assert len(result) == 1
    assert result[0] == spec.preconditions[0]


def test_unmet_preconditions_satisfied_by_one_any_of_member() -> None:
    spec = _hdg_sel_spec()
    result = unmet_preconditions(spec, {"fd_capt": False, "cmd_a": True})
    assert result == ()


def test_unmet_preconditions_unknown_is_not_a_pass() -> None:
    """A referenced control reading ``None``, or simply absent from the
    states mapping, is treated as unsatisfied — "unknown" is never a pass."""
    spec = _hdg_sel_spec()
    result = unmet_preconditions(spec, {"fd_capt": None})  # cmd_a missing entirely
    assert len(result) == 1
    assert result[0] == spec.preconditions[0]


def test_unmet_preconditions_with_no_preconditions_is_empty() -> None:
    doc = _fake_trainer_document()
    (fd_capt,) = [c.spec for c in doc.controls if c.control_id == "fd_capt"]
    assert unmet_preconditions(fd_capt, {}) == ()


# ---------------------------------------------------------------------------
# referenced_control_ids
# ---------------------------------------------------------------------------


def test_referenced_control_ids_names_every_any_of_member() -> None:
    spec = _hdg_sel_spec()
    assert referenced_control_ids(spec) == frozenset({"fd_capt", "cmd_a"})


def test_referenced_control_ids_with_no_preconditions_is_empty() -> None:
    doc = _fake_trainer_document()
    (fd_capt,) = [c.spec for c in doc.controls if c.control_id == "fd_capt"]
    assert referenced_control_ids(fd_capt) == frozenset()


# ---------------------------------------------------------------------------
# precondition_order — §8.1's pinned value, plus the cycle rejection
# ---------------------------------------------------------------------------


def test_precondition_order_puts_the_dependency_first() -> None:
    doc = _fake_trainer_document()
    assert precondition_order(doc, ["hdg_sel", "fd_capt"]) == ("fd_capt", "hdg_sel")


def test_precondition_order_raises_on_a_cycle() -> None:
    """The pure function's own defence (§6.3), independent of the load-time
    rejection :func:`test_cockpit_catalog.py's <core.cockpit.catalog>`
    cycle fixture exercises."""
    doc = _fake_trainer_document()
    cyclic_a = next(c for c in doc.controls if c.control_id == "fd_capt").model_copy(
        update={
            "control_id": "cyc_a",
            "preconditions": [
                PreconditionGroup(
                    any_of=[ControlCondition(control_id="cyc_b", equals=True)],
                    hint="needs cyc_b",
                )
            ],
        }
    )
    cyclic_b = next(c for c in doc.controls if c.control_id == "cmd_a").model_copy(
        update={
            "control_id": "cyc_b",
            "preconditions": [
                PreconditionGroup(
                    any_of=[ControlCondition(control_id="cyc_a", equals=True)],
                    hint="needs cyc_a",
                )
            ],
        }
    )
    cyclic_doc = doc.model_copy(update={"controls": [*doc.controls, cyclic_a, cyclic_b]})
    with pytest.raises(ValueError, match=r".*"):
        precondition_order(cyclic_doc, ["cyc_a", "cyc_b"])


def test_cycle_fixture_is_rejected_at_load_time() -> None:
    """The load-time half of the same rule: a catalog directory whose
    controls reference each other cyclically never produces a document at
    all (§8.1's "cycle/" fixture)."""
    with pytest.raises(CockpitCatalogLoadError):
        load_catalog_dir(FIXTURE_DIR / "cycle")
