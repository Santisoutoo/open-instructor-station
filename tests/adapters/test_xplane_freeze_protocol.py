"""The order in which :class:`XPlaneSimAdapter` writes datarefs, pinned in CI.

Issue #37 shipped because nothing outside a live simulator could see it: X-Plane
accepted every ``psi`` write and then quietly resettled the aircraft, once
leaving it inverted on the runway. ``FakeSimAdapter`` cannot reproduce that — it
does not model a flight model — and CI never talks to a simulator by design.

What *is* checkable without a simulator is the protocol: which datarefs the
adapter writes, in what order, and whether ``override_planepath`` is always
released. That is the part of the five-step procedure a refactor can silently
break, and it is what this file guards. The physics stays the ``-m sim`` suite's
job.

Nothing here opens a socket: :class:`_RecordingAdapter` replaces the three
methods that would.
"""

from __future__ import annotations

from typing import Any

import pytest

from adapters.xplane import xplane_adapter
from adapters.xplane.xplane_adapter import XPlaneSimAdapter
from core.models import AircraftSetup, GeoPosition, LightsSetup

#: The aircraft's starting position in the recorded fixture. Arbitrary, but
#: reused as the teleport target so ``_await_arrival`` succeeds on its first
#: poll instead of spending the timeout waiting for a simulator that is not there.
HOME = GeoPosition(latitude=40.4700, longitude=-3.5700, altitude_ft=2000.0)

OVERRIDE = "override_planepath"
ATTITUDE = ("psi", "theta", "phi")


class _RecordingAdapter(XPlaneSimAdapter):
    """An adapter that records dataref traffic instead of sending it.

    Subclassing at ``_read``/``_write``/``_activate`` is deliberate: everything
    above those three methods — the freeze discipline, the write ordering, the
    ``finally`` that releases the override — is the real adapter's code, running
    unmodified. Only the wire is replaced.
    """

    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, Any] = {
            "latitude": HOME.latitude,
            "longitude": HOME.longitude,
            "elevation": 609.6,  # 2000 ft in metres
            "local_x": 0.0,
            "local_y": 609.6,
            "local_z": 0.0,
            "local_vx": 0.0,
            "local_vy": 0.0,
            "local_vz": 0.0,
            "psi": 100.0,
            "theta": 0.0,
            "phi": 0.0,
            "indicated_airspeed": 120.0,
            "vh_ind_fpm": 0.0,
            "on_ground": 0,
            "temperature_ambient_deg_c": 15.0,
            OVERRIDE: 0,
            "has_crashed": 0,
        }
        self.writes: list[tuple[str, Any]] = []
        self.commands: list[str] = []
        #: Short key of a dataref whose write should blow up, to prove the
        #: override still comes off. ``None`` means every write succeeds.
        self.fail_on: str | None = None

    @property
    def is_connected(self) -> bool:
        """Always connected: there is no handshake to perform against a dict."""
        return True

    async def _read(self, key: str) -> Any:
        return self.values[key]

    async def _write(self, key: str, value: float | int | bool, index: int | None = None) -> None:
        self.writes.append((key, value))
        if key == self.fail_on:
            raise RuntimeError(f"simulated failure writing {key!r}")
        self.values[key] = value

    async def _activate(self, key: str) -> None:
        self.commands.append(key)

    @property
    def written_keys(self) -> list[str]:
        """The datarefs written, in order, with duplicates kept."""
        return [key for key, _ in self.writes]


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch) -> _RecordingAdapter:
    """A recording adapter with the settle delays taken out.

    The settles exist to give a simulator a physics frame or two. There is no
    simulator here, so waiting for one would only make the suite slow — the
    ordering being asserted is unaffected.
    """
    monkeypatch.setattr(xplane_adapter, "_OVERRIDE_SETTLE_S", 0.0)
    monkeypatch.setattr(xplane_adapter, "_RELEASE_SETTLE_S", 0.0)
    return _RecordingAdapter()


def assert_frozen_around(written: list[str], keys: tuple[str, ...]) -> None:
    """Assert every key in ``keys`` was written between the freeze and the release."""
    assert written.count(OVERRIDE) == 2, f"expected one freeze and one release, got {written}"
    engaged = written.index(OVERRIDE)
    released = written.index(OVERRIDE, engaged + 1)
    for key in keys:
        assert key in written, f"{key} was never written; got {written}"
        assert engaged < written.index(key) < released, (
            f"{key} was written outside the freeze; got {written}"
        )


# --------------------------------------------------------------------------
# apply_setup — the defect in issue #37
# --------------------------------------------------------------------------


async def test_apply_setup_freezes_the_flight_model_around_attitude(
    adapter: _RecordingAdapter,
) -> None:
    """Heading, pitch and roll must be written with the flight model held still.

    Written into a running model they do not stick: measured against X-Plane
    12.4.3 at LEMD, a heading commanded at 322.21 read back 286.9 and the
    aircraft ended up inverted on the runway at roll -180.
    """
    await adapter.apply_setup(AircraftSetup(heading_deg=322.21, pitch_deg=0.0, roll_deg=0.0))

    assert_frozen_around(adapter.written_keys, ATTITUDE)
    assert adapter.writes[0] == (OVERRIDE, 1)
    assert adapter.writes[-1] == (OVERRIDE, 0)


async def test_apply_setup_freezes_around_altitude_and_airspeed(
    adapter: _RecordingAdapter,
) -> None:
    """Altitude and airspeed are flight-model state too, not configuration."""
    await adapter.apply_setup(AircraftSetup(altitude_ft=4000.0, ias_kt=140.0))

    assert_frozen_around(adapter.written_keys, ("local_y", "local_vx", "local_vz"))


async def test_apply_setup_normalises_the_heading_it_writes(adapter: _RecordingAdapter) -> None:
    """360 is the only out-of-range heading the model lets through, and it maps to 0."""
    await adapter.apply_setup(AircraftSetup(heading_deg=360.0))
    assert ("psi", 0.0) in adapter.writes


async def test_apply_setup_releases_the_override_when_a_write_fails(
    adapter: _RecordingAdapter,
) -> None:
    """The worst failure this adapter has is a leaked override.

    It freezes the user's aircraft indefinitely with nothing in the UI to
    explain why, so the release lives in a ``finally`` and this test is what
    keeps it there.
    """
    adapter.fail_on = "psi"

    with pytest.raises(RuntimeError, match="simulated failure"):
        await adapter.apply_setup(AircraftSetup(heading_deg=322.21))

    assert (OVERRIDE, 0) in adapter.writes, "the override was left engaged after a failed write"
    assert adapter.writes[-1] == (OVERRIDE, 0)


async def test_apply_setup_does_not_freeze_for_configuration_only(
    adapter: _RecordingAdapter,
) -> None:
    """Switches and knobs are not fought by the flight model, so nothing pauses.

    Freezing here would cost the instructor a visible hitch in the simulation
    every time a light was toggled.
    """
    await adapter.apply_setup(
        AircraftSetup(
            flaps_ratio=0.5,
            gear_down=True,
            nav1_freq_khz=110_300,
            lights=LightsSetup(landing=True),
        )
    )

    assert OVERRIDE not in adapter.written_keys
    assert adapter.written_keys == [
        "flap_ratio",
        "gear_handle_down",
        "nav1_freq",
        "landing_lights",
    ]


async def test_apply_setup_with_nothing_set_writes_nothing(adapter: _RecordingAdapter) -> None:
    await adapter.apply_setup(AircraftSetup())
    assert adapter.writes == []


async def test_apply_setup_writes_configuration_outside_the_freeze(
    adapter: _RecordingAdapter,
) -> None:
    """A mixed setup freezes for the state and leaves the switches out of it."""
    await adapter.apply_setup(AircraftSetup(heading_deg=270.0, flaps_ratio=1.0))

    written = adapter.written_keys
    assert written.index("flap_ratio") < written.index(OVERRIDE)
    assert_frozen_around(written, ("psi",))


# --------------------------------------------------------------------------
# set_position — unchanged behaviour, guarded through the refactor
# --------------------------------------------------------------------------


async def test_set_position_still_runs_the_five_step_procedure(
    adapter: _RecordingAdapter,
) -> None:
    """The shared helper must not have dropped a step out of repositioning."""
    await adapter.set_position(HOME, heading_deg=270.0)

    assert_frozen_around(
        adapter.written_keys,
        ("local_x", "local_y", "local_z", "local_vx", "local_vy", "local_vz", "psi"),
    )
    # Step 5: X-Plane reads a teleport as an impact and wrecks the aircraft.
    assert adapter.commands == ["fix_all_systems"]


async def test_set_position_releases_the_override_when_a_write_fails(
    adapter: _RecordingAdapter,
) -> None:
    adapter.fail_on = "local_x"

    with pytest.raises(RuntimeError, match="simulated failure"):
        await adapter.set_position(HOME, heading_deg=270.0)

    assert adapter.writes[-1] == (OVERRIDE, 0)


# --------------------------------------------------------------------------
# The helper itself
# --------------------------------------------------------------------------


async def test_frozen_flight_model_releases_on_an_exception(adapter: _RecordingAdapter) -> None:
    with pytest.raises(ZeroDivisionError):
        async with adapter.frozen_flight_model():
            raise ZeroDivisionError

    assert adapter.writes == [(OVERRIDE, 1), (OVERRIDE, 0)]
