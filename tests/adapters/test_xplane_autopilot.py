"""The X-Plane autopilot write path, pinned without a simulator.

The contract suite says *that* an adapter honours the autopilot block of
``AircraftSetup``; this file says *how* the X-Plane one does it, and it does so
with no network and no sim. That matters because the two places this mapping can
go wrong are both silent:

* ``None`` read as "off" would disarm a mode the instructor never mentioned,
  every time an unrelated control was written;
* the master switch and the flight director share one three-valued dataref, so
  folding them wrongly turns "show me the bars" into "fly the aeroplane".

The transport is stubbed at :meth:`XPlaneSimAdapter._read` / ``_write`` /
``_activate`` — the layer directly under the mapping — so what is asserted is the
set of dataref writes and commands the adapter decided on, not httpx.
"""

from typing import Any

import pytest

from adapters.xplane import DATAREFS
from adapters.xplane.xplane_adapter import (
    AUTOPILOT_MODE_FLIGHT_DIRECTOR,
    AUTOPILOT_MODE_OFF,
    AUTOPILOT_MODE_SERVOS,
    COMMANDS,
    XPlaneSimAdapter,
)
from core.models import AircraftSetup


class _RecordingAdapter:
    """An adapter with its three transport primitives replaced by recorders."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, autopilot_mode: int = 0) -> None:
        self.adapter = XPlaneSimAdapter()
        self.writes: list[tuple[str, Any]] = []
        self.commands: list[str] = []
        self._reads = {"autopilot_mode": autopilot_mode}

        async def read(key: str) -> Any:
            return self._reads[key]

        async def write(key: str, value: Any, index: int | None = None) -> None:
            self.writes.append((key, value))

        async def activate(key: str) -> None:
            self.commands.append(key)

        monkeypatch.setattr(self.adapter, "_read", read)
        monkeypatch.setattr(self.adapter, "_write", write)
        monkeypatch.setattr(self.adapter, "_activate", activate)

    def written(self, key: str) -> Any:
        """The last value written to ``key``."""
        values = [value for written_key, value in self.writes if written_key == key]
        assert values, f"nothing was written to {key!r}; writes were {self.writes}"
        return values[-1]


# --------------------------------------------------------------------------
# The names themselves
# --------------------------------------------------------------------------


def test_every_autopilot_dataref_is_a_real_path() -> None:
    """Names are the whole risk here: ``connect()`` refuses a build missing any of them."""
    for key in (
        "autopilot_mode",
        "autopilot_altitude_dial_ft",
        "autopilot_airspeed_dial",
        "autopilot_airspeed_is_mach",
        "autopilot_heading_dial_deg",
        "autopilot_vvi_dial_fpm",
        "elevator_trim",
    ):
        assert DATAREFS[key].startswith("sim/")


def test_the_lateral_modes_are_selected_by_command() -> None:
    for key in (
        "autopilot_nav",
        "autopilot_approach",
        "autopilot_heading",
        "autopilot_wing_leveler",
    ):
        assert COMMANDS[key].startswith("sim/autopilot/")


# --------------------------------------------------------------------------
# The master / flight-director fold
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "flight_director", "master", "expected"),
    [
        # Engaging the autopilot always means servos, whatever it was doing.
        (AUTOPILOT_MODE_OFF, None, True, AUTOPILOT_MODE_SERVOS),
        (AUTOPILOT_MODE_FLIGHT_DIRECTOR, None, True, AUTOPILOT_MODE_SERVOS),
        # Disengaging drops the servos but leaves the bars up.
        (AUTOPILOT_MODE_SERVOS, None, False, AUTOPILOT_MODE_FLIGHT_DIRECTOR),
        # ... and cannot conjure bars that were not there.
        (AUTOPILOT_MODE_OFF, None, False, AUTOPILOT_MODE_OFF),
        # The flight director alone raises the floor, never the ceiling.
        (AUTOPILOT_MODE_OFF, True, None, AUTOPILOT_MODE_FLIGHT_DIRECTOR),
        (AUTOPILOT_MODE_SERVOS, True, None, AUTOPILOT_MODE_SERVOS),
        # Switching the bars off switches the servos off with them: an autopilot
        # flying without a flight director is not a state the aircraft has.
        (AUTOPILOT_MODE_SERVOS, False, None, AUTOPILOT_MODE_OFF),
        # A contradictory setup resolves in favour of the servos.
        (AUTOPILOT_MODE_OFF, False, True, AUTOPILOT_MODE_SERVOS),
        # Both asked for at once, the ordinary "engage" case.
        (AUTOPILOT_MODE_OFF, True, True, AUTOPILOT_MODE_SERVOS),
    ],
)
def test_autopilot_mode_fold(
    current: int, flight_director: bool | None, master: bool | None, expected: int
) -> None:
    assert XPlaneSimAdapter._autopilot_mode_for(current, flight_director, master) == expected


# --------------------------------------------------------------------------
# What a setup actually writes
# --------------------------------------------------------------------------


async def test_an_empty_setup_touches_no_autopilot_dataref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not even a read: an aircraft setup that says nothing about the AP costs nothing."""
    recording = _RecordingAdapter(monkeypatch)

    await recording.adapter._write_autopilot(AircraftSetup())

    assert recording.writes == []
    assert recording.commands == []


async def test_only_the_requested_selectors_are_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``None`` means "leave this knob alone", and that has to be literally true."""
    recording = _RecordingAdapter(monkeypatch)

    await recording.adapter._write_autopilot(AircraftSetup(target_altitude_ft=9000.0))

    assert recording.writes == [("autopilot_altitude_dial_ft", 9000.0)]
    assert recording.commands == []


async def test_a_speed_in_knots_takes_the_dial_out_of_mach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dial is shared between knots and Mach; asking in knots has to mean knots."""
    recording = _RecordingAdapter(monkeypatch)

    await recording.adapter._write_autopilot(AircraftSetup(target_ias_kt=250.0))

    assert recording.writes == [
        ("autopilot_airspeed_is_mach", 0),
        ("autopilot_airspeed_dial", 250.0),
    ]


async def test_the_heading_bug_is_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    recording = _RecordingAdapter(monkeypatch)

    await recording.adapter._write_autopilot(AircraftSetup(target_heading_deg=360.0))

    assert recording.written("autopilot_heading_dial_deg") == pytest.approx(0.0)


async def test_engaging_the_autopilot_reads_the_current_mode_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording = _RecordingAdapter(monkeypatch, autopilot_mode=AUTOPILOT_MODE_FLIGHT_DIRECTOR)

    await recording.adapter._write_autopilot(AircraftSetup(autopilot_master=True))

    assert recording.written("autopilot_mode") == AUTOPILOT_MODE_SERVOS


async def test_selecting_a_lateral_mode_activates_its_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording = _RecordingAdapter(monkeypatch)

    await recording.adapter._write_autopilot(AircraftSetup(autopilot_app=True))

    assert recording.commands == ["autopilot_approach"]


async def test_deselecting_a_lateral_mode_falls_back_to_wing_leveller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """X-Plane has no per-mode "off" — the modes are exclusive, so off means neutral."""
    recording = _RecordingAdapter(monkeypatch)

    await recording.adapter._write_autopilot(AircraftSetup(autopilot_nav=False))

    assert recording.commands == ["autopilot_wing_leveler"]


async def test_contradictory_lateral_modes_settle_on_the_most_specific(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutually exclusive modes asked for together: the last activation wins, and it is APP."""
    recording = _RecordingAdapter(monkeypatch)

    await recording.adapter._write_autopilot(
        AircraftSetup(autopilot_hdg=True, autopilot_nav=True, autopilot_app=True)
    )

    assert recording.commands == ["autopilot_heading", "autopilot_nav", "autopilot_approach"]


async def test_a_mode_asked_for_wins_over_one_switched_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Turning NAV off while turning HDG on must not also fire the wing leveller."""
    recording = _RecordingAdapter(monkeypatch)

    await recording.adapter._write_autopilot(AircraftSetup(autopilot_nav=False, autopilot_hdg=True))

    assert recording.commands == ["autopilot_heading"]


async def test_elevator_trim_is_written_as_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Trim is a control, not a flight-model variable: no freeze, no autopilot involvement."""
    recording = _RecordingAdapter(monkeypatch)

    await recording.adapter._write_configuration(AircraftSetup(elevator_trim_ratio=-0.35))

    assert recording.writes == [("elevator_trim", -0.35)]
