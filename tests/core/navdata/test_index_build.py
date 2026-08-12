"""The cache lifecycle: fingerprints, generations, journal mode, locking, cancellation.

Every rule tested here is invisible when it works and expensive to debug when it
does not, which is exactly why each gets a cheap test against the fixture tree.
Two of them would only ever fail on Windows — replacing a file that live
connections hold open, and a lock file orphaned by a crash — and "only on
Windows" plus "only under concurrency" is the worst possible place to discover a
design mistake.

The tree is **copied** into ``tmp_path`` before anything mutates it: the
committed fixtures are read-only source, and a test that edited them in place
would poison every other test in the session.
"""

from __future__ import annotations

import shutil
import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from core.navdata.models import IndexProgress
from core.navdata.provider import NavdataUnavailable
from core.navdata.schema import SCHEMA_VERSION
from core.navdata.xplane_native.build import (
    BuildLockTimeout,
    advisory_lock,
    cache_directory,
    generation_files,
    read_cache_key,
    read_only_uri,
    resolve_sources,
)
from core.navdata.xplane_native.provider import XPNativeNavdataProvider

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "navdata" / "xp_root"


@pytest.fixture
def install(tmp_path: Path) -> Path:
    """A writable copy of the fixture tree, so a test may edit its sources."""
    root = tmp_path / "xp_root"
    shutil.copytree(FIXTURE_ROOT, root)
    return root


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "cache"


@pytest.fixture
def provider(install: Path, cache_dir: Path) -> Iterator[XPNativeNavdataProvider]:
    built = XPNativeNavdataProvider(install, cache_dir=cache_dir)
    yield built
    # Windows will not delete a file that still has an open handle, and pytest
    # cleans tmp_path afterwards.
    built.close()


# --------------------------------------------------------------------------
# Source resolution and the cache key
# --------------------------------------------------------------------------


def test_custom_data_wins_per_file(install: Path) -> None:
    sources = resolve_sources(install)
    fix_path = sources.path("earth_fix")
    assert fix_path is not None
    assert fix_path.parent.name == "Custom Data"


def test_a_zero_byte_file_in_custom_data_falls_through_to_the_default_data(
    install: Path,
) -> None:
    """Some navdata installers leave empty placeholders behind.

    Treating one as "this install publishes no holds" would be a silent and
    permanent loss of every published hold, so an empty file is *absent*.
    """
    custom = install / "Custom Data" / "earth_hold.dat"
    assert custom.is_file()
    assert custom.stat().st_size == 0

    hold_path = resolve_sources(install).path("earth_hold")
    assert hold_path is not None
    assert hold_path.parent.name == "default data"


def test_apt_dat_is_read_from_the_scenery_tree_not_from_custom_data(install: Path) -> None:
    """``apt.dat`` is scenery, not navdata, and is not subject to the precedence rule."""
    apt_path = resolve_sources(install).path("apt")
    assert apt_path is not None
    assert apt_path.parent.name == "Earth nav data"
    assert "Global Airports" in apt_path.parts


def test_the_cache_key_carries_the_schema_version_the_cycle_and_every_fingerprint(
    install: Path,
) -> None:
    """Cycle change, scenery update and schema bump all land in one comparable string."""
    key = resolve_sources(install).cache_key
    assert f"v{SCHEMA_VERSION}" in key
    assert "cycle=2501" in key
    for role in ("apt", "earth_nav", "earth_fix", "earth_hold"):
        assert f"{role}=" in key


def test_the_cache_key_changes_when_a_source_file_does(install: Path) -> None:
    before = resolve_sources(install).cache_key
    fix_file = install / "Custom Data" / "earth_fix.dat"
    fix_file.write_text(fix_file.read_text(encoding="utf-8") + "  1.0 1.0 ZNEW ENRT LE 4530011\n")
    assert resolve_sources(install).cache_key != before


def test_a_missing_required_source_is_reported_rather_than_guessed(install: Path) -> None:
    (install / "Custom Data" / "earth_nav.dat").unlink()
    (install / "Resources" / "default data" / "earth_nav.dat").unlink()
    assert resolve_sources(install).missing_roles == ("earth_nav",)


def test_the_cache_directory_is_overridable(tmp_path: Path) -> None:
    assert cache_directory(tmp_path) == tmp_path
    assert cache_directory(None, environ={"OIS_NAVDATA_CACHE_DIR": str(tmp_path)}) == tmp_path


# --------------------------------------------------------------------------
# D14 — the published file is one self-contained, DELETE-journalled file
# --------------------------------------------------------------------------


def test_the_published_file_is_journal_mode_delete(
    provider: XPNativeNavdataProvider, cache_dir: Path
) -> None:
    """Never WAL. A WAL database is three files and an atomic rename moves one."""
    provider.ensure_index()
    path = provider.cache_path
    assert path is not None

    connection = sqlite3.connect(read_only_uri(path), uri=True)
    try:
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        connection.close()
    assert mode.lower() == "delete"


def test_no_wal_or_shm_sibling_is_left_in_the_cache_directory(
    provider: XPNativeNavdataProvider, cache_dir: Path
) -> None:
    provider.ensure_index()
    siblings = [p.name for p in cache_dir.iterdir() if p.suffix in {".sqlite-wal", ".sqlite-shm"}]
    assert siblings == []
    assert not list(cache_dir.glob("*-wal"))
    assert not list(cache_dir.glob("*-shm"))


def test_a_published_file_cannot_be_written_through_the_read_uri(
    provider: XPNativeNavdataProvider,
) -> None:
    provider.ensure_index()
    path = provider.cache_path
    assert path is not None

    connection = sqlite3.connect(read_only_uri(path), uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM airport")
    finally:
        connection.close()


# --------------------------------------------------------------------------
# D15 — generations: a published file is never overwritten
# --------------------------------------------------------------------------


def test_a_forced_rebuild_publishes_a_new_generation(
    provider: XPNativeNavdataProvider, cache_dir: Path
) -> None:
    """This is the test that would have caught an in-place ``os.replace()``.

    A rebuild on an unchanged install produces the same cycle and the same
    schema version as the file already published, so without a generation
    number the build would rename onto the exact path live connections hold
    open — a ``PermissionError`` on Windows at best, and undefined behaviour
    under ``immutable=1`` at worst.
    """
    provider.ensure_index()
    first = provider.cache_path
    provider.ensure_index(force=True)
    second = provider.cache_path

    assert first is not None
    assert second is not None
    assert first != second
    assert second.name.endswith(f"-v{SCHEMA_VERSION}-g2.sqlite")


def test_a_connection_opened_before_a_rebuild_still_answers_afterwards(
    provider: XPNativeNavdataProvider,
) -> None:
    """Reads in flight finish against the old file, which is still intact on disk."""
    provider.ensure_index()
    first = provider.cache_path
    assert first is not None

    held = sqlite3.connect(read_only_uri(first), uri=True)
    try:
        before = held.execute("SELECT COUNT(*) FROM airport").fetchone()[0]
        provider.ensure_index(force=True)
        after = held.execute("SELECT COUNT(*) FROM airport").fetchone()[0]
        assert before == after == 2
    finally:
        held.close()


def test_a_query_after_a_rebuild_observes_the_new_generation(
    provider: XPNativeNavdataProvider, install: Path
) -> None:
    """The epoch bump, from the caller's side: no provider is recreated.

    A row added to the install between builds becomes visible through the same
    provider object, which is only true if the thread-local connection noticed
    its epoch had moved and reopened.
    """
    provider.ensure_index()
    assert provider.get_fixes("ZNEW") == []

    fix_file = install / "Custom Data" / "earth_fix.dat"
    fix_file.write_text(
        fix_file.read_text(encoding="utf-8") + "  41.50000000   -3.50000000 ZNEW ENRT LE 4530011\n"
    )

    provider.ensure_index()
    assert [f.ident for f in provider.get_fixes("ZNEW")] == ["ZNEW"]


def test_generations_are_swept_so_the_directory_holds_one_file(
    provider: XPNativeNavdataProvider, cache_dir: Path
) -> None:
    provider.ensure_index()
    provider.ensure_index(force=True)
    provider.ensure_index(force=True)

    published = [path for _, path in generation_files(cache_dir)]
    assert provider.cache_path in published
    # On Windows a lingering handle can defer an unlink; a stale file wastes
    # disk and breaks nothing, so the assertion is that it does not accumulate
    # without bound rather than that it is always exactly one.
    assert len(published) <= 2


def test_generation_numbers_increase(provider: XPNativeNavdataProvider, cache_dir: Path) -> None:
    provider.ensure_index()
    provider.ensure_index(force=True)
    numbers = [generation for generation, _ in generation_files(cache_dir)]
    assert numbers == sorted(numbers)
    assert numbers[-1] >= 2


# --------------------------------------------------------------------------
# The fingerprint decides whether anything is rebuilt at all
# --------------------------------------------------------------------------


def test_an_unchanged_install_is_adopted_rather_than_rebuilt(
    provider: XPNativeNavdataProvider,
) -> None:
    """Every start after the first is instant: a few ``stat()`` calls and a compare."""
    provider.ensure_index()
    first = provider.cache_path
    provider.ensure_index()
    assert provider.cache_path == first


def test_a_second_provider_adopts_the_first_ones_index(install: Path, cache_dir: Path) -> None:
    """This is also what makes the loser of the build lock cheap: it adopts, it does not build."""
    first = XPNativeNavdataProvider(install, cache_dir=cache_dir)
    second = XPNativeNavdataProvider(install, cache_dir=cache_dir)
    try:
        first.ensure_index()
        second.ensure_index()
        assert second.cache_path == first.cache_path
        assert second.status().state == "ready"
    finally:
        first.close()
        second.close()


def test_a_cache_written_by_a_different_schema_version_is_not_adopted(
    provider: XPNativeNavdataProvider, cache_dir: Path
) -> None:
    """Bumping ``SCHEMA_VERSION`` *is* the migration; a stamped mismatch is simply unusable."""
    provider.ensure_index()
    path = provider.cache_path
    assert path is not None
    assert read_cache_key(path) is not None

    provider.close()
    connection = sqlite3.connect(path)
    try:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    finally:
        connection.close()

    assert read_cache_key(path) is None


# --------------------------------------------------------------------------
# D16 — cancellation
# --------------------------------------------------------------------------


def test_a_cancelled_build_publishes_nothing_and_leaves_the_previous_status(
    install: Path, cache_dir: Path
) -> None:
    provider = XPNativeNavdataProvider(install, cache_dir=cache_dir)
    try:
        before = provider.status()
        cancel = threading.Event()
        cancel.set()

        after = provider.ensure_index(cancel=cancel)

        assert after == before
        assert after.state == "unavailable"
        assert provider.cache_path is None
        assert generation_files(cache_dir) == []
    finally:
        provider.close()


def test_a_cancelled_build_leaves_no_temporary_file(install: Path, cache_dir: Path) -> None:
    provider = XPNativeNavdataProvider(install, cache_dir=cache_dir)
    try:
        cancel = threading.Event()
        cancel.set()
        provider.ensure_index(cancel=cancel)
        assert list(cache_dir.glob("*.tmp")) == []
    finally:
        provider.close()


def test_a_cancelled_build_does_not_degrade_an_index_that_was_already_published(
    provider: XPNativeNavdataProvider,
) -> None:
    provider.ensure_index()
    published = provider.cache_path
    ready = provider.status()

    cancel = threading.Event()
    cancel.set()
    provider.ensure_index(cancel=cancel, force=True)

    assert provider.cache_path == published
    assert provider.status() == ready
    assert provider.get_airport("ZZZZ") is not None


# --------------------------------------------------------------------------
# The advisory lock
# --------------------------------------------------------------------------


def test_the_lock_excludes_a_second_holder(tmp_path: Path) -> None:
    """An OS-held lock, not a "does the file exist?" check.

    The distinction is the whole point: a lock whose mere existence means
    "locked" is orphaned by a crash, and every later start then waits forever on
    a holder that no longer exists.
    """
    lock = tmp_path / "build.lock"
    with (
        advisory_lock(lock, timeout_s=1.0),
        pytest.raises(BuildLockTimeout),
        advisory_lock(lock, timeout_s=0.15, poll_s=0.02),
    ):
        pytest.fail("the lock was granted twice")


def test_the_lock_is_available_again_once_the_holder_leaves(tmp_path: Path) -> None:
    lock = tmp_path / "build.lock"
    with advisory_lock(lock, timeout_s=1.0):
        pass
    with advisory_lock(lock, timeout_s=1.0):
        pass


# --------------------------------------------------------------------------
# Progress
# --------------------------------------------------------------------------


def test_progress_covers_every_stage_and_never_goes_backwards(
    install: Path, cache_dir: Path
) -> None:
    """A bar that jumps back teaches a user to distrust it for the rest of the build."""
    provider = XPNativeNavdataProvider(install, cache_dir=cache_dir)
    frames: list[IndexProgress] = []
    try:
        provider.ensure_index(progress=frames.append)
    finally:
        provider.close()

    assert frames
    assert {f.stage for f in frames} == {
        "airports",
        "runways",
        "parking",
        "navaids",
        "fixes",
        "holds",
        "finalising",
    }
    fractions = [f.fraction for f in frames]
    assert fractions == sorted(fractions)
    assert all(0.0 <= f <= 1.0 for f in fractions)
    assert all(f.stage_count == 7 for f in frames)
    assert [f.stage_index for f in frames] == sorted(f.stage_index for f in frames)


def test_the_last_frame_reports_the_build_finished(install: Path, cache_dir: Path) -> None:
    provider = XPNativeNavdataProvider(install, cache_dir=cache_dir)
    frames: list[IndexProgress] = []
    try:
        provider.ensure_index(progress=frames.append)
    finally:
        provider.close()
    assert frames[-1].stage == "finalising"
    assert frames[-1].fraction == pytest.approx(1.0)


# --------------------------------------------------------------------------
# Availability
# --------------------------------------------------------------------------


def test_a_provider_with_no_install_declares_itself_unavailable(tmp_path: Path) -> None:
    """A missing prerequisite is a declared state, never a runtime failure."""
    provider = XPNativeNavdataProvider(tmp_path / "nothing-here", cache_dir=tmp_path / "cache")
    status = provider.ensure_index()
    assert status.state == "unavailable"
    assert status.reason
    assert "OIS_XPLANE_PATH" in status.reason


def test_querying_before_the_index_exists_raises_rather_than_lying(install: Path) -> None:
    """The UI gates on ``status()``. Seeing this exception means a caller ignored it."""
    provider = XPNativeNavdataProvider(install)
    with pytest.raises(NavdataUnavailable):
        provider.get_airport("ZZZZ")


def test_constructing_a_provider_performs_no_io(tmp_path: Path) -> None:
    """Import-safe by contract: nothing is read until ``status()`` or a query."""
    provider = XPNativeNavdataProvider(tmp_path / "does-not-exist", cache_dir=tmp_path / "cache")
    assert provider.status().state == "unavailable"
    assert provider.cache_path is None
    assert not (tmp_path / "cache").exists()
