"""Unit tests for ``core.cockpit.catalog`` (docs/designs/cockpit-control-catalog.md
§6.1, §8.1).

Written before the implementation exists (Wave 1 Track A of #220): every test
here is expected to fail with ``ModuleNotFoundError`` until ``core/cockpit/``
is built. That failure is the deliverable, not a bug in this file.

Fixture directory: ``tests/core/fixtures/cockpit/`` — one valid catalog
(``fake-trainer/``, a file-form mirror of the Fake's synthetic catalog, D12)
and eight broken variants, each isolating exactly one load-time rule (§8.1):

* ``dup-id/`` — the same ``control_id`` defined by two files.
* ``no-root/`` — no ``aircraft.yaml``. Not discoverable by
  :func:`discover_catalog_dirs` at all (it only walks directories that
  contain ``aircraft.yaml``); loaded only via a direct
  :func:`load_catalog_dir` call.
* ``bad-panel/`` — a control names a ``panel_id`` no panel declares.
* ``pre-unreadable/`` — a precondition references a control that is not
  ``readable`` (a ``press``).
* ``cycle/`` — a precondition cycle (``a`` needs ``b``, ``b`` needs ``a``).
* ``bad-override/`` — ``setup_overrides`` names a field
  :class:`~core.models.AircraftSetup` does not have.
* ``readable-stated/`` — a file states ``readable`` explicitly, which is
  forbidden (the loader derives it from the binding).
* ``id-mismatch/`` — the directory name and ``aircraft.catalog_id`` disagree.

Every one of the seven directories above except ``no-root/`` DOES carry an
``aircraft.yaml`` and is therefore discoverable — this is what pins the exact
error count in :func:`test_load_all_catalogs_over_the_whole_fixture_root`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.cockpit.catalog import (
    CockpitCatalogLoadError,
    discover_catalog_dirs,
    load_all_catalogs,
    load_catalog_dir,
    publish,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "cockpit"

#: Every broken fixture directory that DOES carry an ``aircraft.yaml`` and is
#: therefore discovered by a directory scan — everything except ``no-root/``.
DISCOVERABLE_BROKEN_DIRS = (
    "bad-override",
    "bad-panel",
    "cycle",
    "dup-id",
    "id-mismatch",
    "pre-unreadable",
    "readable-stated",
)


# ---------------------------------------------------------------------------
# discover_catalog_dirs
# ---------------------------------------------------------------------------


def test_discover_catalog_dirs_finds_every_directory_with_an_aircraft_yaml() -> None:
    dirs = discover_catalog_dirs(FIXTURE_DIR)
    names = [path.name for path in dirs]
    assert "no-root" not in names, "no-root/ has no aircraft.yaml and must not be discovered"
    assert set(names) == {"fake-trainer", *DISCOVERABLE_BROKEN_DIRS}


def test_discover_catalog_dirs_is_sorted_by_name() -> None:
    dirs = discover_catalog_dirs(FIXTURE_DIR)
    names = [path.name for path in dirs]
    assert names == sorted(names)


def test_discover_catalog_dirs_over_a_missing_root_is_empty() -> None:
    assert discover_catalog_dirs(FIXTURE_DIR / "does-not-exist") == ()


# ---------------------------------------------------------------------------
# load_catalog_dir — the valid fixture
# ---------------------------------------------------------------------------


def test_fake_trainer_loads_with_the_expected_shape() -> None:
    doc = load_catalog_dir(FIXTURE_DIR / "fake-trainer")

    assert doc.aircraft.catalog_id == "fake-trainer"
    assert len(doc.panels) == 4
    assert len(doc.controls) == 11  # 10 + chime_test, §8.1
    assert len(doc.parked) == 1

    by_id = {c.control_id: c for c in doc.controls}
    assert by_id["toga"].spec.readable is False
    assert by_id["chime_test"].spec.readable is False
    assert by_id["stab_trim"].spec.readable is True

    assert doc.parked[0].control_id == "mcp_vs"
    assert doc.setup_overrides == {
        "flight_director": "fd_capt",
        "autopilot_master": "cmd_a",
        "autopilot_hdg": "hdg_sel",
        "target_altitude_ft": "mcp_alt",
        "target_heading_deg": "mcp_hdg",
    }


def test_fake_trainer_panel_ids() -> None:
    doc = load_catalog_dir(FIXTURE_DIR / "fake-trainer")
    assert {panel.panel_id for panel in doc.panels} == {"mcp", "overhead", "pedestal", "lights"}


# ---------------------------------------------------------------------------
# load_catalog_dir — each broken directory, naming its offending file
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", DISCOVERABLE_BROKEN_DIRS)
def test_broken_directory_raises_a_load_error(name: str) -> None:
    with pytest.raises(CockpitCatalogLoadError) as excinfo:
        load_catalog_dir(FIXTURE_DIR / name)
    # The error carries the offending file, inside this fixture's own
    # directory — never a bare exception with nothing to point the author at.
    assert excinfo.value.path.is_relative_to(FIXTURE_DIR / name)


def test_no_root_raises_a_load_error_for_the_missing_aircraft_yaml() -> None:
    """Never discovered by a scan (no ``aircraft.yaml``); loaded directly."""
    with pytest.raises(CockpitCatalogLoadError):
        load_catalog_dir(FIXTURE_DIR / "no-root")


# ---------------------------------------------------------------------------
# load_all_catalogs
# ---------------------------------------------------------------------------


def test_load_all_catalogs_over_the_whole_fixture_root() -> None:
    loaded, errors = load_all_catalogs(FIXTURE_DIR)
    assert [doc.aircraft.catalog_id for doc in loaded] == ["fake-trainer"]
    assert len(errors) == len(DISCOVERABLE_BROKEN_DIRS)


def test_load_all_catalogs_never_raises_on_one_bad_directory() -> None:
    """A typo in one aircraft's catalog does not take the others down."""
    loaded, _errors = load_all_catalogs(FIXTURE_DIR)
    assert len(loaded) == 1


def test_load_all_catalogs_over_a_missing_root_is_empty() -> None:
    assert load_all_catalogs(FIXTURE_DIR / "does-not-exist") == ((), ())


# ---------------------------------------------------------------------------
# publish — the binding-free projection (D3)
# ---------------------------------------------------------------------------


def test_publish_strips_every_binding() -> None:
    doc = load_catalog_dir(FIXTURE_DIR / "fake-trainer")
    catalog = publish(doc, revision=3, detection_note=None)
    for spec in catalog.controls:
        assert "binding" not in spec.model_dump()


def test_publish_sorts_panels_by_order() -> None:
    doc = load_catalog_dir(FIXTURE_DIR / "fake-trainer")
    catalog = publish(doc, revision=3, detection_note=None)
    orders = [panel.order for panel in catalog.panels]
    assert orders == sorted(orders)


def test_publish_carries_the_given_revision() -> None:
    doc = load_catalog_dir(FIXTURE_DIR / "fake-trainer")
    catalog = publish(doc, revision=3, detection_note=None)
    assert catalog.revision == 3


def test_publish_reports_supported_and_the_aircraft() -> None:
    doc = load_catalog_dir(FIXTURE_DIR / "fake-trainer")
    catalog = publish(doc, revision=1, detection_note="probed and found")
    assert catalog.supported is True
    assert catalog.aircraft == doc.aircraft
    assert catalog.detection_note == "probed and found"
