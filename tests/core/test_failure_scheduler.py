"""Unit tests for ``core.failure_scheduler.FailureScheduler``.

Pure and synchronous by design (failures-manager.md §6.2): every test drives a
fake monotonic clock and hand-built ``AircraftState`` frames directly, with no
asyncio, no adapter and no real time anywhere.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.failure_scheduler import FailureScheduler
from core.failures import (
    AltitudeBelowTrigger,
    ArmedFailure,
    ArmFailureRequest,
    DelayTrigger,
    SpeedAboveTrigger,
)
from core.models import AircraftState

ARMED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _state(*, altitude_ft: float = 3000.0, ias_kt: float = 100.0) -> AircraftState:
    """A minimal, otherwise-uninteresting frame — only altitude/speed vary per test."""
    return AircraftState(
        latitude=40.0,
        longitude=-3.0,
        altitude_ft=altitude_ft,
        heading_deg=0.0,
        ias_kt=ias_kt,
        vertical_speed_fpm=0.0,
        pitch_deg=0.0,
        roll_deg=0.0,
        on_ground=False,
    )


def _delay_request(delay_s: float = 5.0) -> ArmFailureRequest:
    return ArmFailureRequest(
        failure_id="instruments.pitot",
        trigger=DelayTrigger(type="delay", delay_s=delay_s),
    )


def _altitude_below_request(altitude_ft: float = 3000.0) -> ArmFailureRequest:
    return ArmFailureRequest(
        failure_id="instruments.pitot",
        trigger=AltitudeBelowTrigger(type="altitude_below", altitude_ft=altitude_ft),
    )


def _speed_above_request(ias_kt: float = 100.0) -> ArmFailureRequest:
    return ArmFailureRequest(
        failure_id="engine.failure",
        engine_index=1,
        trigger=SpeedAboveTrigger(type="speed_above", ias_kt=ias_kt),
    )


class TestDelayTrigger:
    def test_does_not_fire_before_the_deadline(self) -> None:
        scheduler = FailureScheduler()
        scheduler.arm(_delay_request(5.0), now_monotonic=1000.0, armed_at=ARMED_AT)
        fired = scheduler.evaluate(_state(), now_monotonic=1004.99)
        assert fired == ()

    def test_fires_on_the_inclusive_boundary(self) -> None:
        scheduler = FailureScheduler()
        scheduler.arm(_delay_request(5.0), now_monotonic=1000.0, armed_at=ARMED_AT)
        fired = scheduler.evaluate(_state(), now_monotonic=1005.0)
        assert len(fired) == 1
        assert fired[0].failure_id == "instruments.pitot"


class TestAltitudeBelowTrigger:
    def test_does_not_fire_above_the_threshold(self) -> None:
        scheduler = FailureScheduler()
        scheduler.arm(_altitude_below_request(3000.0), now_monotonic=0.0, armed_at=ARMED_AT)
        fired = scheduler.evaluate(_state(altitude_ft=3200.0), now_monotonic=1.0)
        assert fired == ()

    def test_fires_on_the_inclusive_boundary(self) -> None:
        scheduler = FailureScheduler()
        scheduler.arm(_altitude_below_request(3000.0), now_monotonic=0.0, armed_at=ARMED_AT)
        fired = scheduler.evaluate(_state(altitude_ft=3000.0), now_monotonic=1.0)
        assert len(fired) == 1

    def test_fires_below_the_threshold(self) -> None:
        scheduler = FailureScheduler()
        scheduler.arm(_altitude_below_request(3000.0), now_monotonic=0.0, armed_at=ARMED_AT)
        fired = scheduler.evaluate(_state(altitude_ft=2990.0), now_monotonic=1.0)
        assert len(fired) == 1

    def test_fires_on_the_first_evaluate_when_already_satisfied(self) -> None:
        """D7: level-triggered, not edge-triggered — armed already below the threshold."""
        scheduler = FailureScheduler()
        scheduler.arm(_altitude_below_request(3000.0), now_monotonic=0.0, armed_at=ARMED_AT)
        fired = scheduler.evaluate(_state(altitude_ft=2500.0), now_monotonic=0.0)
        assert len(fired) == 1


class TestSpeedAboveTrigger:
    def test_does_not_fire_below_the_threshold(self) -> None:
        scheduler = FailureScheduler()
        scheduler.arm(_speed_above_request(100.0), now_monotonic=0.0, armed_at=ARMED_AT)
        assert scheduler.evaluate(_state(ias_kt=60.0), now_monotonic=1.0) == ()
        assert scheduler.evaluate(_state(ias_kt=99.9), now_monotonic=2.0) == ()

    def test_fires_on_the_inclusive_boundary(self) -> None:
        scheduler = FailureScheduler()
        scheduler.arm(_speed_above_request(100.0), now_monotonic=0.0, armed_at=ARMED_AT)
        fired = scheduler.evaluate(_state(ias_kt=100.0), now_monotonic=1.0)
        assert len(fired) == 1
        assert fired[0].failure_id == "engine.failure"
        assert fired[0].engine_index == 1


class TestFiredEntriesAreRemoved:
    def test_a_second_evaluate_on_the_same_frame_returns_nothing(self) -> None:
        scheduler = FailureScheduler()
        scheduler.arm(_altitude_below_request(3000.0), now_monotonic=0.0, armed_at=ARMED_AT)
        first = scheduler.evaluate(_state(altitude_ft=2000.0), now_monotonic=1.0)
        second = scheduler.evaluate(_state(altitude_ft=2000.0), now_monotonic=1.0)
        assert len(first) == 1
        assert second == ()
        assert scheduler.armed == ()


class TestIndependentThresholds:
    def test_two_armed_entries_fire_independently(self) -> None:
        """The exact case X-Plane's global companion datarefs cannot express (D5)."""
        scheduler = FailureScheduler()
        low = scheduler.arm(_altitude_below_request(2000.0), now_monotonic=0.0, armed_at=ARMED_AT)
        high = scheduler.arm(_altitude_below_request(5000.0), now_monotonic=0.0, armed_at=ARMED_AT)

        at_3000 = scheduler.evaluate(_state(altitude_ft=3000.0), now_monotonic=1.0)
        assert [entry.armed_id for entry in at_3000] == [high.armed_id]
        assert [entry.armed_id for entry in scheduler.armed] == [low.armed_id]

        at_1000 = scheduler.evaluate(_state(altitude_ft=1000.0), now_monotonic=2.0)
        assert [entry.armed_id for entry in at_1000] == [low.armed_id]
        assert scheduler.armed == ()


class TestDisarm:
    def test_disarm_before_the_satisfying_frame_prevents_it_firing(self) -> None:
        scheduler = FailureScheduler()
        entry = scheduler.arm(_altitude_below_request(3000.0), now_monotonic=0.0, armed_at=ARMED_AT)
        assert scheduler.disarm(entry.armed_id) is True
        fired = scheduler.evaluate(_state(altitude_ft=1000.0), now_monotonic=1.0)
        assert fired == ()
        assert scheduler.armed == ()

    def test_disarm_of_an_unknown_id_returns_false(self) -> None:
        scheduler = FailureScheduler()
        assert scheduler.disarm("not-a-real-id") is False

    def test_disarm_all_clears_every_entry(self) -> None:
        scheduler = FailureScheduler()
        scheduler.arm(_altitude_below_request(3000.0), now_monotonic=0.0, armed_at=ARMED_AT)
        scheduler.arm(_speed_above_request(100.0), now_monotonic=0.0, armed_at=ARMED_AT)
        scheduler.disarm_all()
        assert scheduler.armed == ()
        assert scheduler.evaluate(_state(altitude_ft=0.0, ias_kt=999.0), now_monotonic=1.0) == ()


class TestRestore:
    def test_restore_puts_a_fired_entry_back_with_last_error_set(self) -> None:
        scheduler = FailureScheduler()
        scheduler.arm(_altitude_below_request(3000.0), now_monotonic=0.0, armed_at=ARMED_AT)
        fired = scheduler.evaluate(_state(altitude_ft=1000.0), now_monotonic=1.0)
        assert len(fired) == 1
        entry = fired[0]
        assert entry.last_error is None

        scheduler.restore(entry, error="simulator unreachable")
        assert len(scheduler.armed) == 1
        assert scheduler.armed[0].last_error == "simulator unreachable"
        assert scheduler.armed[0].armed_id == entry.armed_id

    def test_a_restored_entry_fires_again_on_the_next_satisfying_frame(self) -> None:
        scheduler = FailureScheduler()
        fired = scheduler.arm(_altitude_below_request(3000.0), now_monotonic=0.0, armed_at=ARMED_AT)
        first = scheduler.evaluate(_state(altitude_ft=1000.0), now_monotonic=1.0)
        scheduler.restore(first[0], error="boom")

        second = scheduler.evaluate(_state(altitude_ft=1000.0), now_monotonic=2.0)
        assert len(second) == 1
        assert second[0].armed_id == fired.armed_id
        assert second[0].last_error == "boom"
        assert scheduler.armed == ()

    def test_a_restored_delay_trigger_keeps_its_original_deadline(self) -> None:
        """A failed retry must not silently reset a delay trigger's own deadline."""
        scheduler = FailureScheduler()
        scheduler.arm(_delay_request(5.0), now_monotonic=1000.0, armed_at=ARMED_AT)
        fired = scheduler.evaluate(_state(), now_monotonic=1005.0)
        scheduler.restore(fired[0], error="boom")

        # Still past the ORIGINAL deadline (1000 + 5 = 1005), so it fires again
        # immediately rather than waiting another 5 s from the retry.
        again = scheduler.evaluate(_state(), now_monotonic=1005.1)
        assert len(again) == 1


class TestArmedOrdering:
    def test_armed_is_stably_ordered_by_armed_at_then_armed_id(self) -> None:
        scheduler = FailureScheduler()
        later = datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)
        first = scheduler.arm(_altitude_below_request(1000.0), now_monotonic=0.0, armed_at=ARMED_AT)
        second = scheduler.arm(_speed_above_request(50.0), now_monotonic=0.0, armed_at=later)
        assert [entry.armed_id for entry in scheduler.armed] == [first.armed_id, second.armed_id]

    def test_arming_is_not_idempotent(self) -> None:
        """Arming the same failure twice arms two entries (§2 — an instructor may want it)."""
        scheduler = FailureScheduler()
        first = scheduler.arm(_speed_above_request(80.0), now_monotonic=0.0, armed_at=ARMED_AT)
        second = scheduler.arm(_speed_above_request(80.0), now_monotonic=0.0, armed_at=ARMED_AT)
        assert first.armed_id != second.armed_id
        assert len(scheduler.armed) == 2


def test_arm_returns_the_created_armed_failure() -> None:
    scheduler = FailureScheduler()
    entry = scheduler.arm(_delay_request(1.0), now_monotonic=0.0, armed_at=ARMED_AT)
    assert isinstance(entry, ArmedFailure)
    assert entry.armed_id
    assert entry.armed_at == ARMED_AT
    assert entry.last_error is None
