"""The X-Plane write/read paths added by the pre-teleport-setup contract.

Same construction as ``test_xplane_autopilot.py``: the contract suite says
*that* an adapter honours ``throttle_ratio``, ``ils_freq_khz``,
``vertical_speed_fpm`` and ``get_airframe()``; this file says *how* the X-Plane
one does, with no network and no sim. The transport is stubbed at
:meth:`XPlaneSimAdapter._read` / ``_write`` — the layer directly under the
mapping — so what is asserted is the set of dataref writes the adapter decided
on, not httpx.

The three decisions pinned here were all made in
``docs/designs/pre-teleport-setup.md``:

* ``ils_freq_khz`` is an **alias for NAV1** — X-Plane's ILS receiver is the
  NAV1 radio — and the explicit ``nav1_freq_khz`` wins when a setup carries
  both.
* The velocity vector's vertical component comes from ``vertical_speed_fpm``
  and defaults to **level**, never to "whatever it was".
* The airframe datarefs are **optional**: a build without them degrades
  ``get_airframe()`` to the all-``None`` model instead of failing anything.
"""

import base64
from typing import Any

import pytest

from adapters.xplane import DATAREFS
from adapters.xplane.xplane_adapter import (
    OPTIONAL_DATAREFS,
    XPlaneSimAdapter,
    _decode_dataref_text,
)
from core.models import AircraftSetup, AirframeInfo

_METRES_PER_FOOT = 0.3048


class _RecordingAdapter:
    """An adapter with its transport primitives replaced by recorders."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, reads: dict[str, Any] | None = None
    ) -> None:
        self.adapter = XPlaneSimAdapter()
        self.writes: list[tuple[str, Any]] = []
        self._reads = reads or {}

        async def read(key: str) -> Any:
            return self._reads[key]

        async def write(key: str, value: Any, index: int | None = None) -> None:
            self.writes.append((key, value))

        monkeypatch.setattr(self.adapter, "_read", read)
        monkeypatch.setattr(self.adapter, "_write", write)

    def written(self, key: str) -> Any:
        """The last value written to ``key``."""
        values = [value for written_key, value in self.writes if written_key == key]
        assert values, f"nothing was written to {key!r}; writes were {self.writes}"
        return values[-1]

    def keys_written(self) -> set[str]:
        return {key for key, _ in self.writes}


# --------------------------------------------------------------------------
# The names themselves
# --------------------------------------------------------------------------


def test_the_new_datarefs_are_real_paths() -> None:
    assert DATAREFS["throttle_ratio"] == "sim/cockpit2/engine/actuators/throttle_ratio_all"
    # acf_* (airframe) and weather/region/* (weather-manager.md §7, OPTIONAL for the
    # reasons documented next to that dict: repositioning must not start refusing to
    # connect() over an unrelated, still-disabled feature's datarefs).
    for path in OPTIONAL_DATAREFS.values():
        assert path.startswith("sim/aircraft/") or path.startswith("sim/weather/region/")


def test_optional_datarefs_are_not_required() -> None:
    """The optional set must never leak into the one ``connect()`` hard-fails on."""
    assert not set(OPTIONAL_DATAREFS) & set(DATAREFS)


# --------------------------------------------------------------------------
# Throttle and the ILS alias
# --------------------------------------------------------------------------


async def test_throttle_is_written_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _RecordingAdapter(monkeypatch)
    await recorder.adapter.apply_setup(AircraftSetup(throttle_ratio=0.3))
    assert recorder.written("throttle_ratio") == pytest.approx(0.3)


async def test_throttle_none_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _RecordingAdapter(monkeypatch)
    await recorder.adapter.apply_setup(AircraftSetup(flaps_ratio=0.5))
    assert "throttle_ratio" not in recorder.keys_written()


async def test_ils_frequency_tunes_nav1(monkeypatch: pytest.MonkeyPatch) -> None:
    """X-Plane's ILS receiver is the NAV1 radio, in the radio's 10 kHz units."""
    recorder = _RecordingAdapter(monkeypatch)
    await recorder.adapter.apply_setup(AircraftSetup(ils_freq_khz=110_300))
    assert recorder.written("nav1_freq") == 11_030


async def test_explicit_nav1_beats_the_ils_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two fields, one dataref: the explicit radio field wins over its alias."""
    recorder = _RecordingAdapter(monkeypatch)
    await recorder.adapter.apply_setup(AircraftSetup(nav1_freq_khz=113_500, ils_freq_khz=110_300))
    assert recorder.written("nav1_freq") == 11_350
    written = [value for key, value in recorder.writes if key == "nav1_freq"]
    assert written == [11_350], "the alias must not produce a second write"


# --------------------------------------------------------------------------
# The vertical component of the velocity vector
# --------------------------------------------------------------------------


async def test_velocity_vector_carries_the_descent(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _RecordingAdapter(monkeypatch)
    await recorder.adapter._write_velocity_vector(90.0, 100.0, -600.0)
    assert recorder.written("local_vy") == pytest.approx(-600.0 * _METRES_PER_FOOT / 60.0)


async def test_velocity_vector_defaults_to_level(monkeypatch: pytest.MonkeyPatch) -> None:
    """``None`` is level — the historical behaviour, now a decision rather than
    a hard-coded zero (issue #81)."""
    recorder = _RecordingAdapter(monkeypatch)
    await recorder.adapter._write_velocity_vector(90.0, 100.0)
    assert recorder.written("local_vy") == 0.0


async def test_vertical_speed_does_not_shrink_the_horizontal_speed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The horizontal component stays the full TAS — the cosine correction at a
    3° glide is 0.14 %, and dropping it is a documented decision (issue #42
    owns the residual)."""
    level = _RecordingAdapter(monkeypatch)
    await level.adapter._write_velocity_vector(90.0, 100.0)
    descending = _RecordingAdapter(monkeypatch)
    await descending.adapter._write_velocity_vector(90.0, 100.0, -600.0)
    assert descending.written("local_vx") == level.written("local_vx")
    assert descending.written("local_vz") == level.written("local_vz")


# --------------------------------------------------------------------------
# get_airframe: optional datarefs degrade, never fail
# --------------------------------------------------------------------------


async def test_get_airframe_degrades_to_unknown_without_the_datarefs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A build that does not expose the airframe datarefs answers "unknown"."""
    recorder = _RecordingAdapter(monkeypatch)
    # connect() never indexed the optional keys: _ids stays empty.
    assert await recorder.adapter.get_airframe() == AirframeInfo()


async def test_get_airframe_decodes_the_indexed_datarefs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    icao_b64 = base64.b64encode(b"C172\x00\x00\x00").decode("ascii")
    recorder = _RecordingAdapter(monkeypatch, reads={"acf_icao": icao_b64, "acf_vso": 48.0})
    recorder.adapter._ids = {"acf_icao": 1, "acf_vso": 2}
    airframe = await recorder.adapter.get_airframe()
    assert airframe.icao_type == "C172"
    assert airframe.vso_kias == pytest.approx(48.0)


async def test_get_airframe_rejects_a_nonsense_stall_speed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A zero or negative Vso is "unknown", not a number to derive a speed from."""
    recorder = _RecordingAdapter(monkeypatch, reads={"acf_icao": None, "acf_vso": 0.0})
    recorder.adapter._ids = {"acf_icao": 1, "acf_vso": 2}
    airframe = await recorder.adapter.get_airframe()
    assert airframe.vso_kias is None


# --------------------------------------------------------------------------
# The byte-array decoder
# --------------------------------------------------------------------------


def test_decode_base64_strips_nul_padding() -> None:
    raw = base64.b64encode(b"B738\x00\x00\x00\x00").decode("ascii")
    assert _decode_dataref_text(raw) == "B738"


def test_decode_accepts_a_list_of_ints() -> None:
    assert _decode_dataref_text([67, 49, 55, 50, 0, 0]) == "C172"


def test_decode_prefers_the_plain_string_over_accidental_base64() -> None:
    """ "C172" is valid base64 by accident and decodes to unprintable garbage —
    the plain string was the value all along."""
    assert _decode_dataref_text("C172") == "C172"


def test_decode_degrades_on_garbage() -> None:
    assert _decode_dataref_text(None) is None
    assert _decode_dataref_text(12.5) is None
    assert _decode_dataref_text([1.5, "x"]) is None
    assert _decode_dataref_text("") is None
