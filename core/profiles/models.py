"""The training profile document — name/metadata wrapped around a saved scenario.

**As-built deviation from the original design draft, flagged per the design's
own convention (see ``docs/designs/training-profiles.md``'s "Addendum:
as-built" section for the full reasoning):** ``TrainingProfile.scenario``
embeds :class:`core.scenarios.models.ScenarioDocument` directly. The design's
own §3.2/§3.3 sketched a parallel ``ProfileScenario``/``ProfileFailure``/
``ProfilePlacement`` family "in case" the Scenario Generator's own model
turned out differently — its own §10.1 flagged this as the expected
resolution once that model existed, and it does: ``ScenarioDocument`` already
composes ``core.placements.PlacementRequest``, ``core.weather.models.WeatherRequest``
and ``core.failures``' request models exactly as D4 called for, and its
``aircraft_state`` field already carries the "merged OVER the placement's own
derived setup" semantics §3.2 asked ``setup_overrides`` to have (both feed
``ApplyPlacementRequest.setup`` the same way — see
``server/position_routes.py::execute_placement``). Nothing here redeclares
any of that. ``core/`` never talks to a simulator (hard rule 2); this module
is pure pydantic.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from core.scenarios.models import ScenarioDocument

__all__ = [
    "PROFILE_FORMAT_VERSION",
    "ProfileSummary",
    "TrainingProfile",
    "TrainingProfileCreate",
]

#: Storage schema tag. Bump when ``TrainingProfile``'s own shape changes in a
#: way an older app version could not read — see §10.2 of the design for why
#: this alone does not solve cross-version sharing of the *embedded*
#: ``ScenarioDocument``.
PROFILE_FORMAT_VERSION = 1


class TrainingProfile(BaseModel):
    """A saved scenario with a name and metadata (feature spec §14, verbatim).

    ``extra="ignore"`` deliberately (D9): this document is written and read
    only by this application, across versions that may add fields over time.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    format_version: int = Field(default=PROFILE_FORMAT_VERSION, description="Storage schema tag.")
    profile_id: str = Field(
        min_length=32,
        max_length=32,
        description="Server-assigned uuid4 hex. Also the filename stem (<id>.json).",
    )
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    author: str | None = Field(default=None, max_length=200)
    created_at: datetime = Field(description="UTC, set once at creation.")
    updated_at: datetime = Field(description="UTC, set on every save/replace/import.")
    scenario: ScenarioDocument


class TrainingProfileCreate(BaseModel):
    """``POST /api/profiles`` and ``PUT /api/profiles/{id}`` body.

    Everything the instructor supplies; the server fills ``profile_id``,
    ``created_at``, ``updated_at``. ``extra="forbid"``: a hand-edited body
    that misspells a field should fail loudly, the same typo-catching
    convention ``weather-manager.md``/``failures-manager.md`` established.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    author: str | None = Field(default=None, max_length=200)
    scenario: ScenarioDocument


class ProfileSummary(BaseModel):
    """One row of ``GET /api/profiles``. Cheap: no navdata lookup, no adapter read."""

    model_config = ConfigDict(frozen=True)

    profile_id: str
    name: str
    description: str
    author: str | None
    created_at: datetime
    updated_at: datetime
    airport_icao: str | None = Field(
        default=None,
        description="Best-effort teaser straight off the embedded scenario's placement, "
        "when it has one and that placement names an airport. None for a coordinate "
        "placement, a profile with no position block, or a hold with no airport stated — "
        "and never a navdata lookup.",
    )
