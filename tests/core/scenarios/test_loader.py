"""Unit tests for ``core.scenarios.loader`` (docs/designs/scenario-generator.md §6.1, §8.1).

Catalogue-integrity assertions against the real shipped directory
(``core/scenarios/data/``) live in ``test_scenario_catalogue.py`` — this
module covers the loader's *mechanism* only: discovery order, error
wrapping, id collisions, and the exit-criterion proof that a scenario is
addable by writing a YAML file only.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from core.scenarios.loader import (
    ScenarioLoadError,
    discover_scenario_files,
    load_all_scenarios,
    load_scenario_file,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "scenarios"
UNREFERENCED_ID = "unreferenced-fixture"

#: The smallest document that satisfies ``ScenarioDocument`` (one block, no
#: navdata dependency) — used wherever a test needs a syntactically and
#: semantically valid scenario body without caring about its content.
_MINIMAL_VALID_YAML = """
name: "Minimal"
description: "The smallest valid scenario body."
position:
  type: coordinate
  position:
    latitude: 40.4
    longitude: -3.5
    altitude_ft: 2000.0
  ias_kt: 90.0
"""


class TestDiscoverScenarioFiles:
    def test_returns_files_sorted_by_stem(self, tmp_path: Path) -> None:
        (tmp_path / "zebra.yaml").write_text(_MINIMAL_VALID_YAML, encoding="utf-8")
        (tmp_path / "alpha.yaml").write_text(_MINIMAL_VALID_YAML, encoding="utf-8")
        (tmp_path / "middle.yml").write_text(_MINIMAL_VALID_YAML, encoding="utf-8")

        files = discover_scenario_files(tmp_path)

        assert [path.stem for path in files] == ["alpha", "middle", "zebra"]

    def test_ignores_non_yaml_files(self, tmp_path: Path) -> None:
        (tmp_path / "scenario.yaml").write_text(_MINIMAL_VALID_YAML, encoding="utf-8")
        (tmp_path / "README.md").write_text("not a scenario", encoding="utf-8")

        files = discover_scenario_files(tmp_path)

        assert [path.name for path in files] == ["scenario.yaml"]

    def test_a_missing_directory_is_treated_as_empty(self, tmp_path: Path) -> None:
        assert discover_scenario_files(tmp_path / "does-not-exist") == ()


class TestLoadScenarioFile:
    def test_a_valid_file_loads(self, tmp_path: Path) -> None:
        path = tmp_path / "engine-failure.yaml"
        path.write_text(_MINIMAL_VALID_YAML, encoding="utf-8")

        loaded = load_scenario_file(path)

        assert loaded.id == "engine-failure"
        assert loaded.source_path == path
        assert loaded.document.name == "Minimal"

    def test_broken_yaml_raises_scenario_load_error_wrapping_yaml_error(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "broken.yaml"
        path.write_text("name: [unterminated\n  description: oops", encoding="utf-8")

        with pytest.raises(ScenarioLoadError) as excinfo:
            load_scenario_file(path)

        assert excinfo.value.path == path
        assert isinstance(excinfo.value.error, yaml.YAMLError)

    def test_valid_yaml_failing_document_validation_raises_scenario_load_error(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "invalid-document.yaml"
        # Syntactically fine YAML; semantically invalid — no name, no blocks.
        path.write_text("description: has no name and no blocks\n", encoding="utf-8")

        with pytest.raises(ScenarioLoadError) as excinfo:
            load_scenario_file(path)

        assert excinfo.value.path == path
        assert isinstance(excinfo.value.error, ValidationError)

    def test_a_stem_not_matching_the_id_pattern_is_a_load_error(self, tmp_path: Path) -> None:
        path = tmp_path / "Not_Kebab_Case.yaml"
        path.write_text(_MINIMAL_VALID_YAML, encoding="utf-8")

        with pytest.raises(ScenarioLoadError):
            load_scenario_file(path)


class TestLoadAllScenarios:
    def test_one_bad_file_does_not_take_down_the_others(self, tmp_path: Path) -> None:
        (tmp_path / "good-one.yaml").write_text(_MINIMAL_VALID_YAML, encoding="utf-8")
        (tmp_path / "good-two.yaml").write_text(_MINIMAL_VALID_YAML, encoding="utf-8")
        (tmp_path / "bad.yaml").write_text("name: [unterminated", encoding="utf-8")

        loaded, errors = load_all_scenarios(tmp_path)

        assert sorted(item.id for item in loaded) == ["good-one", "good-two"]
        assert len(errors) == 1
        assert errors[0].path == tmp_path / "bad.yaml"

    def test_a_stem_colliding_across_yaml_and_yml_is_a_load_error(self, tmp_path: Path) -> None:
        (tmp_path / "duplicate.yaml").write_text(_MINIMAL_VALID_YAML, encoding="utf-8")
        (tmp_path / "duplicate.yml").write_text(_MINIMAL_VALID_YAML, encoding="utf-8")

        loaded, errors = load_all_scenarios(tmp_path)

        # The first one found (sorted: "duplicate.yaml" before "duplicate.yml")
        # loads; the second is the collision error. Only one id ever surfaces.
        assert [item.id for item in loaded] == ["duplicate"]
        assert len(errors) == 1
        assert errors[0].path == tmp_path / "duplicate.yml"
        assert "more than one file" in str(errors[0].error)

    def test_an_empty_directory_loads_with_nothing_and_no_errors(self, tmp_path: Path) -> None:
        loaded, errors = load_all_scenarios(tmp_path)
        assert loaded == ()
        assert errors == ()


class TestDiscoveryIsAScanNotARegistry:
    """The exit-criterion test (roadmap Phase 2, criterion 2).

    Loads a scenario file that no Python source module names anywhere except
    this docstring and the mechanical check below — proving discovery is a
    directory scan, not a registry a new scenario must be added to.
    """

    def test_discovers_a_scenario_never_named_in_the_source_tree(self) -> None:
        loaded, errors = load_all_scenarios(FIXTURE_DIR)
        assert errors == ()
        assert [scenario.id for scenario in loaded] == [UNREFERENCED_ID]

        # Mechanical, not just a claim: no OTHER source file mentions this id.
        # If discovery ever regressed to a hardcoded list, the assertion
        # above would still pass by finding the file some other way — this
        # is what catches it.
        this_file = Path(__file__).resolve()
        offenders = [
            path
            for directory in ("core", "server", "adapters", "tests")
            for path in (REPO_ROOT / directory).rglob("*.py")
            if path.resolve() != this_file and UNREFERENCED_ID in path.read_text(encoding="utf-8")
        ]
        assert offenders == []
