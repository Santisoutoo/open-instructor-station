"""``XPNativeCifpSource``: per-file precedence, and a cache that is keyed right.

The caching rules here are invisible when they work and vicious when they do
not — a test that passes alone and fails in a full run — so each one gets its
own test rather than being trusted to review (design §7.2, §11.7).

The read-only cases run against the committed fixture tree; anything that needs
a file to change mid-test builds its own tree under ``tmp_path``. Every byte is
invented: hard rule 4, no navdata is ever committed.
"""

from __future__ import annotations

import os
from pathlib import Path

from core.models import GeoPosition
from core.navdata.models import FixRef, Waypoint
from core.navdata.xplane_native.cifp import XPNativeCifpSource

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "navdata" / "xp_root"

#: Ten fields, with the semicolon the format buries inside field 7. Invented data,
#: faithful shape - a fixture written to a parser's assumption proves nothing.
RUNWAY_RECORD = "RWY:RW09,     ,      ,02000, ,IZZA,1,050;N40000000,W003000000,0000;"


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _tree(
    root: Path, *, custom: dict[str, str] | None = None, default: dict[str, str] | None = None
) -> Path:
    """A minimal install tree holding only the CIFP files a test needs."""
    for icao, content in (custom or {}).items():
        _write(root / "Custom Data" / "CIFP" / f"{icao}.dat", content)
    for icao, content in (default or {}).items():
        _write(root / "Resources" / "default data" / "CIFP" / f"{icao}.dat", content)
    return root


def _runway_at(elevation: int) -> str:
    """A one-runway file whose elevation identifies which copy was read."""
    return f"RWY:RW09,     ,      ,0{elevation}, ,IZZA,1,050;N40000000,W003000000,0000;"


class TestLoading:
    def test_the_fixture_airport_parses(self) -> None:
        airport = XPNativeCifpSource(FIXTURE_ROOT).load("ZZZZ")
        assert airport is not None
        assert airport.icao == "ZZZZ"
        assert [r.ident for r in airport.runways] == ["09", "27", "32L", "32R"]
        assert len(airport.procedures) == 4

    def test_an_airport_with_no_cifp_file_is_a_normal_outcome(self) -> None:
        """31 269 airports have runways; 14 938 have procedures. None is not an error."""
        assert XPNativeCifpSource(FIXTURE_ROOT).load("ZZZX") is None

    def test_the_icao_is_normalised(self) -> None:
        source = XPNativeCifpSource(FIXTURE_ROOT)
        assert source.load(" zzzz ") is not None

    def test_constructing_the_source_performs_no_io(self, tmp_path: Path) -> None:
        """Import-safe, like every provider: nothing is read until something is asked."""
        source = XPNativeCifpSource(tmp_path / "does-not-exist")
        assert source.load("ZZZZ") is None

    def test_the_injected_resolver_is_used(self, tmp_path: Path) -> None:
        anywhere = Waypoint(
            ident="ZZANY", kind="fix", position=GeoPosition(latitude=40.0, longitude=-3.0)
        )
        record = ",".join(
            ["010", "5", "ZZSID", "", "ZZANY", "ZZ", "E", "A", "E   ", "", "", "TF"] + [""] * 26
        )
        root = _tree(tmp_path, custom={"ZZZZ": f"SID:{record};"})

        without = XPNativeCifpSource(root).load("ZZZZ")
        with_resolver = XPNativeCifpSource(root, resolve_fix=lambda _ref: anywhere).load("ZZZZ")

        assert without is not None
        assert with_resolver is not None
        assert without.procedures[0].legs[0].is_positionable is False
        assert with_resolver.procedures[0].legs[0].is_positionable is True


class TestPrecedence:
    """Resolved per file, on every load — the thousand-airport rule (design §9)."""

    def test_an_airport_published_only_in_default_data_is_found(self) -> None:
        """ZZZY exists nowhere else in the fixture tree, which is the point of it."""
        airport = XPNativeCifpSource(FIXTURE_ROOT).load("ZZZY")
        assert airport is not None
        assert [r.ident for r in airport.runways] == ["18"]
        assert airport.procedures[0].ident == "R18-Z"
        assert airport.procedures[0].approach_type == "rnav"
        assert airport.procedures[0].runway_idents == ("18",)

    def test_custom_data_wins_when_both_copies_exist(self, tmp_path: Path) -> None:
        root = _tree(
            tmp_path, custom={"ZZZZ": _runway_at(1111)}, default={"ZZZZ": _runway_at(2222)}
        )
        airport = XPNativeCifpSource(root).load("ZZZZ")
        assert airport is not None
        assert airport.runways[0].elevation_ft == 1111.0

    def test_a_zero_byte_custom_file_falls_through(self, tmp_path: Path) -> None:
        """Some navdata installers leave empty placeholders behind."""
        root = _tree(tmp_path, custom={"ZZZZ": ""}, default={"ZZZZ": _runway_at(2222)})
        airport = XPNativeCifpSource(root).load("ZZZZ")
        assert airport is not None
        assert airport.runways[0].elevation_ft == 2222.0

    def test_a_file_appearing_in_custom_data_later_takes_over(self, tmp_path: Path) -> None:
        """Precedence is resolved on every load, not remembered from the first one.

        Keying the cache on the *resolved* path is what makes this work: the
        winner flipping between directories changes the key by itself.
        """
        root = _tree(tmp_path, default={"ZZZZ": _runway_at(2222)})
        source = XPNativeCifpSource(root)
        first = source.load("ZZZZ")

        _write(root / "Custom Data" / "CIFP" / "ZZZZ.dat", _runway_at(1111))
        second = source.load("ZZZZ")

        assert first is not None
        assert second is not None
        assert first.runways[0].elevation_ft == 2222.0
        assert second.runways[0].elevation_ft == 1111.0


class TestCaching:
    def test_a_second_load_returns_the_same_parse(self) -> None:
        source = XPNativeCifpSource(FIXTURE_ROOT)
        assert source.load("ZZZZ") is source.load("ZZZZ")

    def test_a_rewritten_file_is_reparsed(self, tmp_path: Path) -> None:
        """``mtime_ns`` is in the key, so a navdata update invalidates by itself."""
        root = _tree(tmp_path, custom={"ZZZZ": _runway_at(1111)})
        source = XPNativeCifpSource(root)
        first = source.load("ZZZZ")

        path = root / "Custom Data" / "CIFP" / "ZZZZ.dat"
        path.write_text(_runway_at(3333), encoding="utf-8")
        # Force the timestamp forward: a rewrite inside the filesystem's mtime
        # resolution would otherwise leave the key unchanged, and this test would
        # pass or fail on how fast the machine is.
        os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1_000_000_000))
        second = source.load("ZZZZ")

        assert first is not None
        assert second is not None
        assert second.runways[0].elevation_ft == 3333.0

    def test_invalidate_drops_every_parse(self) -> None:
        source = XPNativeCifpSource(FIXTURE_ROOT)
        first = source.load("ZZZZ")
        source.invalidate()
        second = source.load("ZZZZ")
        assert first is not None
        assert second is not None
        assert first is not second
        assert first == second

    def test_the_cache_is_bounded_and_evicts_least_recently_used(self, tmp_path: Path) -> None:
        """Bounded at 64 in production; two here so the eviction is observable."""
        root = _tree(
            tmp_path,
            custom={"ZZZA": _runway_at(1111), "ZZZB": _runway_at(2222), "ZZZC": _runway_at(3333)},
        )
        source = XPNativeCifpSource(root, max_entries=2)

        first_a = source.load("ZZZA")
        first_b = source.load("ZZZB")
        source.load("ZZZA")  # touch A, so B is now the least recently used
        source.load("ZZZC")  # evicts B

        # A survived and is still the same object; B was evicted and is reparsed.
        assert source.load("ZZZA") is first_a
        assert source.load("ZZZB") is not first_b

    def test_two_sources_over_two_trees_never_answer_for_each_other(self, tmp_path: Path) -> None:
        """The regression test for a module-level ``@lru_cache`` keyed on the ICAO.

        Both trees publish ``ZZZZ``, both sources are alive at once, and the
        second must not be served the first one's parse of a *different file*.
        Keyed on the ICAO alone that failure is completely silent — a fixture
        airport answering a query against a real install, or the reverse.
        """
        left = _tree(tmp_path / "left", custom={"ZZZZ": _runway_at(1111)})
        right = _tree(tmp_path / "right", custom={"ZZZZ": _runway_at(2222)})

        left_source = XPNativeCifpSource(left)
        right_source = XPNativeCifpSource(right)

        assert left_source.load("ZZZZ") is not None
        assert right_source.load("ZZZZ") is not None
        # And again, now that both caches are warm.
        first = left_source.load("ZZZZ")
        second = right_source.load("ZZZZ")
        assert first is not None
        assert second is not None
        assert first.runways[0].elevation_ft == 1111.0
        assert second.runways[0].elevation_ft == 2222.0

    def test_a_source_does_not_pin_another_sources_parse(self, tmp_path: Path) -> None:
        """``@lru_cache`` on a method keeps ``self`` alive for the process's life.

        A fresh source over the same tree must do its own parse rather than
        finding one keyed by a predecessor.
        """
        root = _tree(tmp_path, custom={"ZZZZ": _runway_at(1111)})
        first = XPNativeCifpSource(root).load("ZZZZ")
        second = XPNativeCifpSource(root).load("ZZZZ")
        assert first is not None
        assert second is not None
        assert first is not second
        assert first == second


class TestRobustness:
    def test_a_resolver_is_optional(self) -> None:
        """Without one the procedures still load; nothing is merely offered."""
        airport = XPNativeCifpSource(FIXTURE_ROOT).load("ZZZZ")
        assert airport is not None
        assert not any(
            leg.is_positionable for procedure in airport.procedures for leg in procedure.legs
        )

    def test_the_root_is_exposed_for_diagnostics(self) -> None:
        assert XPNativeCifpSource(FIXTURE_ROOT).root == FIXTURE_ROOT

    def test_a_malformed_file_still_loads_the_records_around_it(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, custom={"ZZZZ": f"RWY:RW99X,GARBAGE;\n{RUNWAY_RECORD}\n"})
        airport = XPNativeCifpSource(root).load("ZZZZ")
        assert airport is not None
        assert [r.ident for r in airport.runways] == ["09"]
        assert airport.skipped_record_count == 1

    def test_a_resolver_sees_the_four_part_arinc_key(self, tmp_path: Path) -> None:
        seen: list[FixRef] = []

        def record_ref(ref: FixRef) -> Waypoint | None:
            seen.append(ref)
            return None

        record = ",".join(
            ["010", "5", "ZZSID", "", "ZZANY", "ZZ", "P", "C", "E   ", "", "", "TF"] + [""] * 26
        )
        root = _tree(tmp_path, custom={"ZZZZ": f"SID:{record};"})
        XPNativeCifpSource(root, resolve_fix=record_ref).load("ZZZZ")

        assert seen == [
            FixRef(
                ident="ZZANY",
                region_code="ZZ",
                section="P",
                subsection="C",
                airport_icao="ZZZZ",
            )
        ]
