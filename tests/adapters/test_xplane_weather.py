"""Cloud write confirmation uses all active fields and confirms removed slots."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from adapters.xplane import xplane_adapter as module
from adapters.xplane.xplane_adapter import XPlaneSimAdapter
from core.sim_adapter import WeatherRejected
from core.weather.models import CloudLayer


def cloud() -> CloudLayer:
    return CloudLayer(base_ft=2000, tops_ft=5000, coverage_ratio=0.75, cloud_type="stratus")


def cloud_readings() -> dict[str, list[float]]:
    return {
        "cloud_base_msl_m": [2000 * 0.3048, 0, 0],
        "cloud_tops_msl_m": [5000 * 0.3048, 0, 0],
        "cloud_coverage_percent": [0.75, 0, 0],
        "cloud_type": [1, 2, 2],
    }


@pytest.mark.parametrize(
    ("key", "slot", "stale"),
    [
        ("cloud_base_msl_m", 0, 1000.0),
        ("cloud_tops_msl_m", 0, 1000.0),
        ("cloud_coverage_percent", 0, 0.25),
        ("cloud_type", 0, 2.0),
        ("cloud_coverage_percent", 1, 0.01),
        ("cloud_coverage_percent", 2, 0.5),
    ],
)
async def test_cloud_waits_for_every_active_field_and_removed_slot(
    monkeypatch: pytest.MonkeyPatch, key: str, slot: int, stale: float
) -> None:
    adapter = XPlaneSimAdapter()
    readings = cloud_readings()
    correct = readings[key][slot]
    readings[key][slot] = stale

    async def read(name: str) -> Any:
        return readings[name]

    async def settle(_: float) -> None:
        readings[key][slot] = correct

    sleep = AsyncMock(side_effect=settle)
    monkeypatch.setattr(adapter, "_read", read)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    await adapter._await_cloud_layers_settled([cloud()])
    sleep.assert_awaited_once()


async def test_cloud_wait_accepts_reader_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = XPlaneSimAdapter()
    readings = cloud_readings()
    readings["cloud_base_msl_m"][0] += 1.0
    readings["cloud_tops_msl_m"][0] -= 1.0
    readings["cloud_coverage_percent"][0] += 0.005
    readings["cloud_type"][0] = 1.2
    # Inactive slots can retain geometry without producing a returned cloud.
    readings["cloud_base_msl_m"][1] = 3000
    readings["cloud_tops_msl_m"][1] = 5000

    async def read(name: str) -> Any:
        return readings[name]

    monkeypatch.setattr(adapter, "_read", read)
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    await adapter._await_cloud_layers_settled([cloud()])
    sleep.assert_not_awaited()


async def test_cloud_timeout_rejects_unconfirmed_weather(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = XPlaneSimAdapter()
    readings = cloud_readings()
    readings["cloud_tops_msl_m"][0] = 1000

    async def read(name: str) -> Any:
        return readings[name]

    monkeypatch.setattr(adapter, "_read", read)
    monkeypatch.setattr(module, "_CLOUD_SETTLE_TIMEOUT_S", 0.01)
    monkeypatch.setattr(module, "_CLOUD_SETTLE_POLL_INTERVAL_S", 0.0)
    with pytest.raises(WeatherRejected, match=r"cloud layers.*timed out"):
        await adapter._await_cloud_layers_settled([cloud()])


async def test_empty_cloud_list_waits_for_clear_sky(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = XPlaneSimAdapter()
    readings = cloud_readings()
    writes: list[tuple[str, float, int | None]] = []

    async def read(name: str) -> Any:
        return readings[name]

    async def write(name: str, value: float, index: int | None = None) -> None:
        writes.append((name, value, index))
        assert index is not None
        readings[name][index] = value

    monkeypatch.setattr(adapter, "_read", read)
    monkeypatch.setattr(adapter, "_write", write)
    await adapter._write_cloud_layers([])
    assert [write for write in writes if write[0] == "cloud_coverage_percent"] == [
        ("cloud_coverage_percent", 0.0, slot) for slot in range(3)
    ]
    assert await adapter._read_cloud_layers() == []
