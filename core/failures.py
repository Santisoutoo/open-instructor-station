"""The failure catalogue and its vocabulary — sim-agnostic, no dataref name.

Per docs/designs/failures-manager.md:

* :data:`FAILURE_IDS` — 30 stable dotted string ids (``engine.fire``,
  ``instruments.pitot``, …), the wire format, the YAML format and the
  profile format. Renaming one after release is a breaking change.
* :class:`FailureSpec` / :data:`FAILURE_CATALOGUE` / :data:`CATALOGUE_BY_ID`
  — the catalogue metadata, independent of any simulator (D1).
* :class:`FailureSupport` / :class:`FailureSupportManifest` — what an adapter
  answers from ``get_failure_support()`` (D4): every id always appears,
  unsupported ones carry a reason.
* The trigger union (D6: altitude/speed above-or-below, delay) and
  :class:`FailureRef` and its request subclasses (D9): these live here, not
  in a router, so the Scenario Generator's YAML validates against the exact
  model a REST call would.

Armed-failure bookkeeping (``ArmedFailure``, ``FailuresStatus``) and the
scheduler (``core/failure_scheduler.py``) are a later, separate track — this
module carries only the vocabulary the ``SimAdapter`` contract needs.
"""

from __future__ import annotations

from datetime import datetime
from types import MappingProxyType
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "CATALOGUE_BY_ID",
    "FAILURE_CATALOGUE",
    "FAILURE_IDS",
    "ActiveFailure",
    "AltitudeAboveTrigger",
    "AltitudeBelowTrigger",
    "ArmFailureRequest",
    "ArmedFailure",
    "ClearFailureRequest",
    "DelayTrigger",
    "FailureCategory",
    "FailureId",
    "FailureRef",
    "FailureSpec",
    "FailureSupport",
    "FailureSupportManifest",
    "FailureTrigger",
    "FailuresStatus",
    "InjectFailureRequest",
    "SpeedAboveTrigger",
    "SpeedBelowTrigger",
]

FailureCategory = Literal[
    "engine",
    "fuel",
    "electrical",
    "hydraulics",
    "instruments",
    "avionics",
    "flight_controls",
    "gear",
    "airframe",
]

FailureId = Literal[
    # -- engine (indexed) --
    "engine.failure",
    "engine.fire",
    "engine.partial_power",
    # -- fuel --
    "fuel.leak",
    # -- electrical --
    "electrical.system",
    "electrical.generator",
    # -- hydraulics --
    "hydraulics.system",
    # -- instruments --
    "instruments.pitot",
    "instruments.static",
    "instruments.vacuum",
    "instruments.airspeed",
    "instruments.attitude",
    "instruments.altimeter",
    "instruments.directional_gyro",
    "instruments.turn_coordinator",
    "instruments.vsi",
    # -- avionics --
    "avionics.com1",
    "avionics.com2",
    "avionics.nav1",
    "avionics.nav2",
    "avionics.gps",
    "avionics.transponder",
    # -- flight controls --
    "flight_controls.flaps",
    "flight_controls.spoilers",
    # -- gear & brakes --
    "gear.stuck",
    "gear.brakes",
    # -- airframe --
    "airframe.pressurisation",
    "airframe.smoke",
    "airframe.bird_strike",
    "airframe.lightning_strike",
]


class FailureSpec(BaseModel):
    """One catalogue entry. Sim-agnostic; knows no dataref."""

    model_config = ConfigDict(frozen=True)

    failure_id: FailureId
    label: str
    category: FailureCategory
    takes_engine_index: bool = False
    description: str


FAILURE_CATALOGUE: tuple[FailureSpec, ...] = (
    FailureSpec(
        failure_id="engine.failure",
        label="Engine failure",
        category="engine",
        takes_engine_index=True,
        description="Total loss of engine power.",
    ),
    FailureSpec(
        failure_id="engine.fire",
        label="Engine fire",
        category="engine",
        takes_engine_index=True,
        description="An engine fire, requiring the fire checklist.",
    ),
    FailureSpec(
        failure_id="engine.partial_power",
        label="Partial power loss",
        category="engine",
        takes_engine_index=True,
        description="Partial loss of engine power, short of a full failure.",
    ),
    FailureSpec(
        failure_id="fuel.leak",
        label="Fuel leak",
        category="fuel",
        description="A fuel leak draining a tank over time.",
    ),
    FailureSpec(
        failure_id="electrical.system",
        label="Total electrical failure",
        category="electrical",
        description="Loss of every electrical bus.",
    ),
    FailureSpec(
        failure_id="electrical.generator",
        label="Generator / alternator",
        category="electrical",
        takes_engine_index=True,
        description=(
            "Failure of the engine-driven generator or alternator — one physical "
            "thing in every simulator this project targets."
        ),
    ),
    FailureSpec(
        failure_id="hydraulics.system",
        label="Hydraulic failure",
        category="hydraulics",
        description="Loss of hydraulic pressure.",
    ),
    FailureSpec(
        failure_id="instruments.pitot",
        label="Pitot blockage",
        category="instruments",
        description="Pitot tube blocked; airspeed indication becomes unreliable.",
    ),
    FailureSpec(
        failure_id="instruments.static",
        label="Static port blockage",
        category="instruments",
        description=(
            "Static port blocked; altimeter and airspeed indications become "
            "unreliable — the classic paired exercise with pitot."
        ),
    ),
    FailureSpec(
        failure_id="instruments.vacuum",
        label="Vacuum system",
        category="instruments",
        description="Vacuum pump failure; the gyroscopic instruments it drives spin down.",
    ),
    FailureSpec(
        failure_id="instruments.airspeed",
        label="Airspeed indicator",
        category="instruments",
        description="The airspeed indicator fails.",
    ),
    FailureSpec(
        failure_id="instruments.attitude",
        label="Attitude indicator",
        category="instruments",
        description="The attitude indicator fails.",
    ),
    FailureSpec(
        failure_id="instruments.altimeter",
        label="Altimeter",
        category="instruments",
        description="The altimeter fails.",
    ),
    FailureSpec(
        failure_id="instruments.directional_gyro",
        label="Directional gyro",
        category="instruments",
        description="The directional gyro fails.",
    ),
    FailureSpec(
        failure_id="instruments.turn_coordinator",
        label="Turn coordinator",
        category="instruments",
        description="The turn coordinator fails.",
    ),
    FailureSpec(
        failure_id="instruments.vsi",
        label="Vertical speed indicator",
        category="instruments",
        description="The vertical speed indicator fails.",
    ),
    FailureSpec(
        failure_id="avionics.com1",
        label="COM 1",
        category="avionics",
        description="The COM1 radio fails.",
    ),
    FailureSpec(
        failure_id="avionics.com2",
        label="COM 2",
        category="avionics",
        description="The COM2 radio fails.",
    ),
    FailureSpec(
        failure_id="avionics.nav1",
        label="NAV 1",
        category="avionics",
        description="The NAV1 receiver fails.",
    ),
    FailureSpec(
        failure_id="avionics.nav2",
        label="NAV 2",
        category="avionics",
        description="The NAV2 receiver fails.",
    ),
    FailureSpec(
        failure_id="avionics.gps",
        label="GPS",
        category="avionics",
        description="The GPS receiver fails.",
    ),
    FailureSpec(
        failure_id="avionics.transponder",
        label="Transponder",
        category="avionics",
        description="The transponder fails.",
    ),
    FailureSpec(
        failure_id="flight_controls.flaps",
        label="Flaps stuck",
        category="flight_controls",
        description=(
            "The flap actuator fails; the surface freezes exactly where it is, not retracted."
        ),
    ),
    FailureSpec(
        failure_id="flight_controls.spoilers",
        label="Spoilers stuck",
        category="flight_controls",
        description="The spoiler actuator fails; the surface freezes where it is.",
    ),
    FailureSpec(
        failure_id="gear.stuck",
        label="Landing gear stuck",
        category="gear",
        description="The landing gear jams and no longer responds to the handle.",
    ),
    FailureSpec(
        failure_id="gear.brakes",
        label="Brake failure",
        category="gear",
        description="The wheel brakes fail.",
    ),
    FailureSpec(
        failure_id="airframe.pressurisation",
        label="Pressurisation failure",
        category="airframe",
        description="Cabin pressurisation fails.",
    ),
    FailureSpec(
        failure_id="airframe.smoke",
        label="Smoke in cockpit",
        category="airframe",
        description="Smoke fills the cockpit.",
    ),
    FailureSpec(
        failure_id="airframe.bird_strike",
        label="Bird strike",
        category="airframe",
        description="A bird strike event.",
    ),
    FailureSpec(
        failure_id="airframe.lightning_strike",
        label="Lightning strike",
        category="airframe",
        description="A lightning strike event.",
    ),
)

CATALOGUE_BY_ID: MappingProxyType[FailureId, FailureSpec] = MappingProxyType(
    {spec.failure_id: spec for spec in FAILURE_CATALOGUE}
)

#: The ``CONTROL_IDS`` pattern (``server/app.py``): the closed ``Literal``'s
#: own members, derived rather than hand-copied, so the two cannot drift.
FAILURE_IDS: tuple[FailureId, ...] = get_args(FailureId)


class FailureSupport(BaseModel):
    """One catalogue entry resolved against one adapter."""

    model_config = ConfigDict(frozen=True)

    failure_id: FailureId
    supported: bool
    best_effort: bool = False
    reason: str | None = None


class FailureSupportManifest(BaseModel):
    """What the adapter answers from ``get_failure_support()``."""

    model_config = ConfigDict(frozen=True)

    caveat: str | None = None
    entries: tuple[FailureSupport, ...]


# ---------------------------------------------------------------------------
# Triggers (D6: five closed types — altitude/speed above-or-below, delay)
# ---------------------------------------------------------------------------


class AltitudeAboveTrigger(BaseModel):
    """Fires when ``altitude_ft >= threshold``. Inclusive, MSL."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["altitude_above"]
    altitude_ft: float = Field(ge=-2000.0, le=100_000.0, description="Feet MSL, inclusive.")


class AltitudeBelowTrigger(BaseModel):
    """Fires when ``altitude_ft <= threshold``. Inclusive, MSL."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["altitude_below"]
    altitude_ft: float = Field(ge=-2000.0, le=100_000.0, description="Feet MSL, inclusive.")


class SpeedAboveTrigger(BaseModel):
    """Fires when ``ias_kt >= threshold``. Inclusive.

    This is the V1-cut trigger: armed on the ground before the roll, it fires
    as the aircraft accelerates through V1.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["speed_above"]
    ias_kt: float = Field(ge=0.0, le=500.0, description="Knots indicated, inclusive.")


class SpeedBelowTrigger(BaseModel):
    """Fires when ``ias_kt <= threshold``. Inclusive."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["speed_below"]
    ias_kt: float = Field(ge=0.0, le=500.0, description="Knots indicated, inclusive.")


class DelayTrigger(BaseModel):
    """Fires ``delay_s`` seconds of wall-clock time after arming.

    Wall clock, not sim time: the station cannot see sim time, and saying so
    beats pretending.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["delay"]
    delay_s: float = Field(gt=0.0, le=86_400.0, description="Seconds after arming.")


FailureTrigger = Annotated[
    AltitudeAboveTrigger
    | AltitudeBelowTrigger
    | SpeedAboveTrigger
    | SpeedBelowTrigger
    | DelayTrigger,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# References and requests
# ---------------------------------------------------------------------------


class FailureRef(BaseModel):
    """A failure instance: the id plus its engine index when the entry takes one.

    The validator is the reason this model lives in ``core/``: the Scenario
    Generator gets identical validation parsing YAML, with no HTTP anywhere.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    failure_id: FailureId
    engine_index: int | None = Field(
        default=None, ge=1, le=8, description="1-based. Required iff the entry is indexed."
    )

    @model_validator(mode="after")
    def _index_matches_catalogue(self) -> FailureRef:
        spec = CATALOGUE_BY_ID[self.failure_id]
        if spec.takes_engine_index and self.engine_index is None:
            raise ValueError(f"{self.failure_id} takes an engine index (1-based); none given.")
        if not spec.takes_engine_index and self.engine_index is not None:
            raise ValueError(f"{self.failure_id} does not take an engine index.")
        return self


class InjectFailureRequest(FailureRef):
    """``POST /api/failures/inject`` — nothing beyond the ref."""


class ClearFailureRequest(FailureRef):
    """``POST /api/failures/clear`` — nothing beyond the ref."""


class ArmFailureRequest(FailureRef):
    """``POST /api/failures/arm``."""

    trigger: FailureTrigger


class ActiveFailure(FailureRef):
    """One failure the simulator reports as failed right now."""


class ArmedFailure(FailureRef):
    """One armed failure, as listed and as returned by ``/arm``.

    Built by :class:`~core.failure_scheduler.FailureScheduler`, never by a
    request body — the server assigns ``armed_id`` and ``armed_at``.
    """

    armed_id: str = Field(description="Server-assigned opaque id (uuid4 hex).")
    trigger: FailureTrigger
    armed_at: datetime = Field(description="UTC wall clock, for the panel's countdown display.")
    last_error: str | None = Field(
        default=None,
        description="Set when the trigger fired but injection failed; retried every frame.",
    )


class FailuresStatus(BaseModel):
    """``GET /api/failures/status`` — the whole picture the panel polls.

    ``active`` is read back from the simulator itself, never from a server-side
    ledger (D10): a teleport's ``fix_all_systems`` repairs everything behind
    any ledger's back. ``armed`` comes from the scheduler, which is the only
    honest home for arming state (D5).
    """

    model_config = ConfigDict(frozen=True)

    active: list[ActiveFailure]
    armed: list[ArmedFailure]
