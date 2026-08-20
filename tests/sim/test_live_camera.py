"""Camera control against a live X-Plane. Never runs in CI.

Per ``docs/designs/camera-manager.md`` §8.3. Run with a simulator loaded and
its Web API enabled::

    pytest -m sim

**What only a live run can prove.** The contract suite already pins the shape
of every camera answer against both adapters; what it cannot do is put the
camera back where the user had it, because ``SimAdapter`` exposes no read of
the current named view (D6) — there is no honest catalogue id for a camera the
user has orbited by hand. These tests therefore do the next honest thing: they
leave the simulator on :data:`~tests.adapters.test_contract.CAMERA_RESTING_VIEW`
in a ``finally``, which is where a session starts, and say plainly that this is
a *reset*, not a restore. Anyone running this while framing a shot loses the
framing, not the flight.

Nothing here moves the aircraft, so unlike the repositioning suite this file
leaves the flight itself untouched.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from adapters.xplane import XPlaneSimAdapter
from core.camera.models import CAMERA_VIEW_IDS, CameraOffset, CameraViewId
from core.sim_adapter import SimAdapter
from tests.adapters.test_contract import CAMERA_OFFSET_TOLERANCE, CAMERA_RESTING_VIEW

pytestmark = pytest.mark.sim

#: The pose the round trip writes when the install can take one. Small enough
#: to sit inside any hangar, asymmetric on every axis so a dropped or swapped
#: field cannot pass by coincidence.
PROBE_OFFSET = CameraOffset(
    forward_m=25.0,
    right_m=-10.0,
    up_m=8.0,
    look_offset_deg=45.0,
    pitch_deg=-12.0,
    zoom_ratio=1.5,
)


async def _supported_view_ids(adapter: SimAdapter) -> tuple[CameraViewId, ...]:
    manifest = await adapter.get_camera_support()
    return tuple(entry.view_id for entry in manifest.views if entry.supported)


@pytest.fixture
async def live_adapter() -> AsyncIterator[XPlaneSimAdapter]:
    """A connected X-Plane adapter that leaves the camera at the resting view.

    The reset is in the fixture's teardown rather than in each test's own
    ``finally`` so that a test failing *mid-sequence* — the case that actually
    leaves a camera somewhere odd — still triggers it.
    """
    adapter = XPlaneSimAdapter()
    await adapter.connect()
    try:
        yield adapter
    finally:
        try:
            if CAMERA_RESTING_VIEW in await _supported_view_ids(adapter):
                await adapter.set_camera_view(CAMERA_RESTING_VIEW)
        finally:
            await adapter.disconnect()


async def test_camera_support_covers_the_catalogue_live(
    live_adapter: XPlaneSimAdapter,
) -> None:
    """The manifest answers, in full, whatever this install can actually reach.

    Deliberately asserts no particular view is supported: which named views
    resolve is a property of the X-Plane build and its command set (§5.1), and
    a test that demanded ``chase`` would be asserting the simulator's
    vocabulary rather than the adapter's honesty.
    """
    manifest = await live_adapter.get_camera_support()

    assert tuple(entry.view_id for entry in manifest.views) == CAMERA_VIEW_IDS
    for entry in manifest.views:
        if not entry.supported:
            assert entry.reason, f"{entry.view_id!r} is unsupported without saying why"


async def test_every_supported_named_view_is_accepted(
    live_adapter: XPlaneSimAdapter,
) -> None:
    """Each view the manifest advertises really switches, one after another.

    A live *acceptance* check only: the Web API answering does not prove the
    render changed, which is what the ``sim-validator`` agent's visual smoke is
    for. And acceptance is exactly the half that matters right now — every
    command name in ``adapters/xplane/camera_commands.py`` is still a §5.1
    candidate, so a view can perfectly well resolve, activate, and frame
    something other than its label. Only a human looking at the screen settles
    that; this test settles whether the name exists and fires.

    The X-Plane mapping has landed and ``can_control_camera`` is now ``True``
    (§5.2's "conservative manifest" posture), so the disjunction below no
    longer has a false branch to hide in: it has collapsed into ``assert
    supported``, and the loop runs for real. Which means a build that resolves
    *none* of the five §5.1 candidates fails this test — deliberately. That is
    not a false alarm and must not be softened into a skip: it is the finding
    that every guessed command name is wrong, and the only thing that would
    produce it is the case the spike exists to rule out. The adapter still
    degrades honestly in that state (a manifest of five unsupported views with
    reasons, and no runtime throw); this test is what stops it degrading
    honestly in silence.
    """
    supported = await _supported_view_ids(live_adapter)
    assert supported or not live_adapter.capabilities.can_control_camera, (
        "the adapter declares can_control_camera but advertises no usable view"
    )

    for view_id in supported:
        await live_adapter.set_camera_view(view_id)


async def test_custom_positions_either_round_trip_or_say_why_not(
    live_adapter: XPlaneSimAdapter,
) -> None:
    """The design's central open question (D7/§10.2), pinned either way.

    If this install can position the free camera, the pose written must read
    back within :data:`~tests.adapters.test_contract.CAMERA_OFFSET_TOLERANCE` —
    the issue-#39 lesson, that a value written into one call is not delivered
    until something reads it back at the other end.

    If it cannot, the manifest must *say so*, with a reason. That branch is not
    a skip and is not decoration: it is what stops someone flipping
    ``custom_positions_supported`` to ``True`` without a spike behind it and
    nobody noticing.
    """
    manifest = await live_adapter.get_camera_support()

    if not manifest.custom_positions_supported:
        assert manifest.custom_positions_reason, (
            "free-camera positioning is unsupported without a stated reason"
        )
        return

    tolerance = CAMERA_OFFSET_TOLERANCE[live_adapter.name]
    await live_adapter.set_camera_offset(PROBE_OFFSET)
    read_back = await live_adapter.get_camera_offset()

    assert read_back is not None, (
        "the adapter accepted a camera offset and then reported none; "
        "get_camera_offset() must answer with the pose the free camera sits at"
    )
    assert read_back.forward_m == pytest.approx(PROBE_OFFSET.forward_m, abs=tolerance)
    assert read_back.right_m == pytest.approx(PROBE_OFFSET.right_m, abs=tolerance)
    assert read_back.up_m == pytest.approx(PROBE_OFFSET.up_m, abs=tolerance)
    assert read_back.look_offset_deg == pytest.approx(PROBE_OFFSET.look_offset_deg, abs=tolerance)
    assert read_back.pitch_deg == pytest.approx(PROBE_OFFSET.pitch_deg, abs=tolerance)
    assert read_back.zoom_ratio == pytest.approx(PROBE_OFFSET.zoom_ratio, abs=tolerance)
