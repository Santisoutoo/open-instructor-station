"""``core.profiles.models`` — the two ``extra`` policies (D9), and reuse of
``core.scenarios.models.ScenarioDocument`` (see this package's own
``__init__.py`` docstring for why there is no separate ``ProfileScenario``).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from core.failures import FailureRef
from core.profiles.models import PROFILE_FORMAT_VERSION, TrainingProfile, TrainingProfileCreate
from core.scenarios.models import ScenarioDocument, ScenarioFailuresBlock
from core.weather.models import WeatherRequest


def _scenario() -> ScenarioDocument:
    return ScenarioDocument(
        name="Test scenario",
        description="A minimal scenario for model tests.",
        weather=WeatherRequest(preset="cavok"),
    )


class TestTrainingProfileExtraIgnore:
    def test_tolerates_an_unknown_top_level_field(self) -> None:
        now = datetime.now(UTC)
        profile = TrainingProfile.model_validate(
            {
                "profile_id": "a" * 32,
                "name": "Circuit practice",
                "created_at": now,
                "updated_at": now,
                "scenario": _scenario().model_dump(mode="json"),
                "some_future_field": "from a newer app version",
            }
        )
        assert profile.name == "Circuit practice"
        assert not hasattr(profile, "some_future_field")

    def test_defaults_the_format_version(self) -> None:
        now = datetime.now(UTC)
        profile = TrainingProfile(
            profile_id="a" * 32, name="X", created_at=now, updated_at=now, scenario=_scenario()
        )
        assert profile.format_version == PROFILE_FORMAT_VERSION


class TestTrainingProfileCreateExtraForbid:
    def test_rejects_an_unknown_field(self) -> None:
        with pytest.raises(ValidationError):
            TrainingProfileCreate.model_validate(
                {
                    "name": "Circuit practice",
                    "scenario": _scenario().model_dump(mode="json"),
                    "typo_field": "oops",
                }
            )

    def test_a_well_formed_draft_validates(self) -> None:
        draft = TrainingProfileCreate(name="Circuit practice", scenario=_scenario())
        assert draft.scenario == _scenario()


class TestEmbeddedScenarioReuse:
    """No ``ProfileScenario``/``ProfileFailure`` — the embedded ``ScenarioDocument``
    carries its own validation, verbatim, exactly as it would over
    ``/api/scenarios``."""

    def test_an_engine_index_mismatched_against_the_catalogue_entry_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FailureRef(failure_id="fuel.leak", engine_index=1)  # fuel.leak takes none

    def test_a_scenario_with_no_declared_block_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ScenarioDocument(name="Empty", description="Nothing declared.")

    def test_failures_block_composes_into_the_profile(self) -> None:
        from core.failures import InjectFailureRequest

        scenario = ScenarioDocument(
            name="Failure profile",
            description="Carries an immediate failure.",
            failures=ScenarioFailuresBlock(
                immediate=(InjectFailureRequest(failure_id="airframe.smoke"),)
            ),
        )
        draft = TrainingProfileCreate(name="Smoke drill", scenario=scenario)
        assert draft.scenario.failures is not None
        assert draft.scenario.failures.immediate[0].failure_id == "airframe.smoke"
