"""File discovery, precedence and the AIRAC cycle ladder.

Every test here builds a fake installation tree under ``tmp_path``. Nothing
touches a real X-Plane install, and the "navdata" written is a handful of
invented bytes — these fixtures exist to exercise *path* logic, not parsing.

The precedence rule is the one with teeth: on a real install
``Custom Data/CIFP/`` has ~1000 fewer airports than
``Resources/default data/CIFP/``, so a directory-level rule silently loses a
thousand airports' procedures. It is resolved per file.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from core.navdata.sources import (
    cifp_file,
    discover_xplane_root,
    is_valid_xplane_root,
    read_cycle_info,
    resolve_data_file,
)

APT_DAT = "Global Scenery/Global Airports/Earth nav data/apt.dat"


def _write(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _make_install(root: Path) -> Path:
    """The minimum tree that counts as an X-Plane 12 installation."""
    _write(root / "Resources/default data/earth_nav.dat", "1200 Version\n")
    _write(root / APT_DAT, "1200 Version\n")
    return root


class TestRootValidation:
    def test_a_complete_tree_validates(self, tmp_path: Path) -> None:
        assert is_valid_xplane_root(_make_install(tmp_path))

    def test_a_tree_without_scenery_is_rejected(self, tmp_path: Path) -> None:
        """A half-copied install must not pass: it fails later, in a worse place."""
        _write(tmp_path / "Resources/default data/earth_nav.dat")
        assert not is_valid_xplane_root(tmp_path)

    def test_a_tree_without_navdata_is_rejected(self, tmp_path: Path) -> None:
        _write(tmp_path / APT_DAT)
        assert not is_valid_xplane_root(tmp_path)

    def test_a_missing_directory_is_not_an_exception(self, tmp_path: Path) -> None:
        assert not is_valid_xplane_root(tmp_path / "nope")


class TestDiscovery:
    def test_a_configured_path_wins(self, tmp_path: Path) -> None:
        root = _make_install(tmp_path / "install")
        assert discover_xplane_root(configured=root) == root

    def test_an_invalid_configured_path_does_not_fall_through(self, tmp_path: Path) -> None:
        """A user who configured a path and silently got someone else's install
        would never work out why. Report nothing and let the caller name the path."""
        assert discover_xplane_root(configured=tmp_path / "not-an-install") is None


class TestPrecedence:
    def test_custom_data_wins_over_default_data(self, tmp_path: Path) -> None:
        _write(tmp_path / "Custom Data/earth_nav.dat", "custom")
        _write(tmp_path / "Resources/default data/earth_nav.dat", "default")
        resolved = resolve_data_file(tmp_path, "earth_nav.dat")
        assert resolved is not None
        assert resolved.read_text(encoding="utf-8") == "custom"

    def test_default_data_is_used_when_custom_data_lacks_the_file(self, tmp_path: Path) -> None:
        _write(tmp_path / "Custom Data/earth_fix.dat", "custom")
        _write(tmp_path / "Resources/default data/earth_nav.dat", "default")
        resolved = resolve_data_file(tmp_path, "earth_nav.dat")
        assert resolved is not None
        assert resolved.read_text(encoding="utf-8") == "default"

    def test_a_zero_byte_file_falls_through(self, tmp_path: Path) -> None:
        """Some navdata installers leave empty placeholders behind."""
        _write(tmp_path / "Custom Data/earth_nav.dat", "")
        _write(tmp_path / "Resources/default data/earth_nav.dat", "default")
        resolved = resolve_data_file(tmp_path, "earth_nav.dat")
        assert resolved is not None
        assert resolved.read_text(encoding="utf-8") == "default"

    def test_neither_copy_present_returns_none(self, tmp_path: Path) -> None:
        assert resolve_data_file(tmp_path, "earth_nav.dat") is None

    def test_precedence_applies_per_cifp_file_not_per_directory(self, tmp_path: Path) -> None:
        """The thousand-airport bug, in miniature.

        ``Custom Data/CIFP/`` holds ZZZZ; ``default data/CIFP/`` holds both ZZZZ
        and ZZZY. A directory-level rule would answer "no procedures" for ZZZY.
        """
        _write(tmp_path / "Custom Data/CIFP/ZZZZ.dat", "custom-zzzz")
        _write(tmp_path / "Resources/default data/CIFP/ZZZZ.dat", "default-zzzz")
        _write(tmp_path / "Resources/default data/CIFP/ZZZY.dat", "default-zzzy")

        zzzz = cifp_file(tmp_path, "ZZZZ")
        zzzy = cifp_file(tmp_path, "ZZZY")
        assert zzzz is not None
        assert zzzy is not None
        assert zzzz.read_text(encoding="utf-8") == "custom-zzzz"
        assert zzzy.read_text(encoding="utf-8") == "default-zzzy"

    def test_an_airport_with_no_cifp_file_is_a_normal_outcome(self, tmp_path: Path) -> None:
        assert cifp_file(tmp_path, "ZZZX") is None


class TestCycleLadder:
    """Every rung was verified present on a real install — this is the data's shape."""

    def test_custom_data_cycle_info_is_read_first(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "Custom Data/cycle_info.txt",
            "AIRAC cycle    : 2607\nValid (from/to): 09/JUL/2026 - 06/AUG/2026\n",
        )
        _write(tmp_path / "Resources/default data/cycle_info.txt", "AIRAC cycle : 2501\n")

        info = read_cycle_info(tmp_path)
        assert info is not None
        assert info.cycle == "2607"
        assert info.valid_from == date(2026, 7, 9)
        assert info.valid_to == date(2026, 8, 6)

    def test_default_data_cycle_info_is_the_second_rung(self, tmp_path: Path) -> None:
        """On a real install this file is present in Custom Data and absent here —
        which is exactly why the ladder exists."""
        _write(tmp_path / "Resources/default data/cycle_info.txt", "AIRAC cycle : 2501\n")
        info = read_cycle_info(tmp_path)
        assert info is not None
        assert info.cycle == "2501"

    def test_cycle_json_is_the_third_rung(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "Custom Data/cycle.json",
            '{"cycle":"2607","revision":"1","name":"X-Plane 12"}',
        )
        info = read_cycle_info(tmp_path)
        assert info is not None
        assert info.cycle == "2607"

    def test_the_earth_nav_header_is_the_last_rung(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "Resources/default data/earth_nav.dat",
            "I\n1200 Version - data cycle 2607, build 20260701, metadata NavXP1200\n",
        )
        info = read_cycle_info(tmp_path)
        assert info is not None
        assert info.cycle == "2607"

    def test_no_cycle_anywhere_is_survivable(self, tmp_path: Path) -> None:
        """The key degrades to file fingerprints; the provider still works."""
        assert read_cycle_info(tmp_path) is None

    def test_a_malformed_cycle_json_falls_through_rather_than_raising(self, tmp_path: Path) -> None:
        _write(tmp_path / "Custom Data/cycle.json", "{ this is not json")
        _write(
            tmp_path / "Resources/default data/earth_nav.dat",
            "I\n1200 Version - data cycle 2501, build 1\n",
        )
        info = read_cycle_info(tmp_path)
        assert info is not None
        assert info.cycle == "2501"

    def test_an_unparseable_validity_line_keeps_the_cycle(self, tmp_path: Path) -> None:
        """The cycle is the cache key; the dates are decoration."""
        _write(
            tmp_path / "Custom Data/cycle_info.txt",
            "AIRAC cycle    : 2607\nValid (from/to): whenever - whenever\n",
        )
        info = read_cycle_info(tmp_path)
        assert info is not None
        assert info.cycle == "2607"
        assert info.valid_from is None
