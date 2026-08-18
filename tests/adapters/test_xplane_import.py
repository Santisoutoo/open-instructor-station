"""Import smoke test for the X-Plane adapter.

The point of this file is that ``adapters.xplane`` must import, construct and
report its capabilities on a machine with no simulator and no network. Nothing
here touches a socket.
"""

import pytest

from adapters.xplane import DATAREFS, XPlaneSimAdapter
from adapters.xplane.xplane_adapter import DEFAULT_BASE_URL, XPlaneNotReachable
from core.failures import FAILURE_IDS, FailureRef
from core.sim_adapter import Capabilities, CapabilityNotSupported, SimAdapter
from core.weather.models import WeatherSetup


def test_constructs_without_a_simulator() -> None:
    adapter = XPlaneSimAdapter()
    assert adapter.name == "xplane"
    assert adapter.is_connected is False
    assert adapter.base_url == DEFAULT_BASE_URL


def test_honours_host_and_port() -> None:
    adapter = XPlaneSimAdapter(host="192.168.1.20", port=9000)
    assert adapter.base_url == "http://192.168.1.20:9000"


def test_satisfies_the_protocol() -> None:
    assert isinstance(XPlaneSimAdapter(), SimAdapter)


def test_declares_only_the_phase_0_capabilities() -> None:
    capabilities = XPlaneSimAdapter().capabilities
    assert isinstance(capabilities, Capabilities)
    assert capabilities.can_set_position is True
    assert capabilities.can_set_aircraft_state is True
    assert capabilities.can_control_autopilot is True
    # can_set_fuel_payload flipped True: pytest -m sim passed against a live
    # X-Plane 12.4.3 (fuel-payload.md §6.4/§9.4) -- see xplane_adapter.py's
    # _write_loadout docstring for the live finding that resolved its own
    # "open question for the live-validation pass".
    assert capabilities.can_set_fuel_payload is True
    # Everything else arrives in a later phase and must stay off until then.
    assert capabilities.can_set_weather is False
    assert capabilities.can_inject_failures is False
    assert capabilities.can_spawn_traffic is False
    assert capabilities.can_control_camera is False
    assert capabilities.can_pushback is False


def test_datarefs_are_fully_qualified_names() -> None:
    assert DATAREFS["latitude"] == "sim/flightmodel/position/latitude"
    assert DATAREFS["longitude"] == "sim/flightmodel/position/longitude"
    assert DATAREFS["on_ground"] == "sim/flightmodel/failures/onground_any"
    assert all(name.startswith("sim/") for name in DATAREFS.values())
    # No duplicate dataref paths hiding behind two keys.
    assert len(set(DATAREFS.values())) == len(DATAREFS)


async def test_reads_refuse_to_run_while_disconnected() -> None:
    """No silent no-ops: an unconnected adapter says so."""
    adapter = XPlaneSimAdapter()
    with pytest.raises(XPlaneNotReachable):
        await adapter.get_aircraft_state()


async def test_disconnect_on_a_fresh_adapter_is_harmless() -> None:
    adapter = XPlaneSimAdapter()
    await adapter.disconnect()
    assert adapter.is_connected is False


async def test_phase_2_methods_refuse_without_their_capabilities() -> None:
    """The still-``False`` Phase 2 shared-foundation stubs (weather-manager.md
    D16, failures-manager.md D11/§5): both flags stay ``False`` on this
    adapter, and their gated methods raise immediately, with no socket
    touched (no ``connect()`` call in this test). ``can_set_fuel_payload`` is
    no longer in this set -- it flipped ``True`` (see
    ``test_declares_only_the_phase_0_capabilities``) once ``pytest -m sim``
    passed against a live simulator.
    """
    adapter = XPlaneSimAdapter()
    with pytest.raises(CapabilityNotSupported, match="can_set_weather"):
        await adapter.get_weather()
    with pytest.raises(CapabilityNotSupported, match="can_set_weather"):
        await adapter.set_weather(WeatherSetup(visibility_m=1000.0))
    with pytest.raises(CapabilityNotSupported, match="can_inject_failures"):
        await adapter.inject_failure(FailureRef(failure_id="instruments.pitot"))
    with pytest.raises(CapabilityNotSupported, match="can_inject_failures"):
        await adapter.clear_failure(FailureRef(failure_id="instruments.pitot"))
    with pytest.raises(CapabilityNotSupported, match="can_inject_failures"):
        await adapter.clear_all_failures()


async def test_phase_2_capability_free_reads_degrade_instead_of_raising() -> None:
    """``get_failure_support``/``get_active_failures`` are capability-free
    reads (failures-manager.md §4): "no" is an answer, never an exception.
    """
    adapter = XPlaneSimAdapter()
    manifest = await adapter.get_failure_support()
    assert [entry.failure_id for entry in manifest.entries] == list(FAILURE_IDS)
    assert all(not entry.supported and entry.reason for entry in manifest.entries)
    assert await adapter.get_active_failures() == ()
