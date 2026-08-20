"""``/api/camera/*`` — the manifest, the view grid's one command, and saved positions.

Per ``docs/designs/camera-manager.md`` §8.4. Against ``TestClient`` +
``FakeSimAdapter``, with the saved-position store redirected to ``tmp_path``:
these tests must never touch the developer's own application-data directory,
and a store that wrote there would silently accumulate junk between runs.

The distinction worth watching in this file is **501 versus 409**. An adapter
that cannot control the camera, and a manifest entry that reports a view or
free positioning unsupported, are 501s — the request is well-formed and the
server has no implementation behind it. "There is no free-camera pose to save
right now" is a 409 (D9): the adapter can do it, the simulator is simply not in
a state where there is anything to capture, and the instructor can fix that in
one tap.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server.deps
from adapters.fake import FakeSimAdapter
from core.camera.models import (
    CAMERA_VIEW_IDS,
    CameraOffset,
    CameraSupportManifest,
    CameraViewSupport,
)
from core.camera.store import CameraPositionStore
from core.sim_adapter import Capabilities
from server.app import create_app
from server.camera_routes import NO_LIVE_OFFSET_DETAIL
from server.deps import get_adapter, reset_adapter

OFFSET = CameraOffset(
    forward_m=25.0, right_m=-10.0, up_m=8.0, look_offset_deg=45.0, pitch_deg=-12.0, zoom_ratio=1.5
)

#: A 32-hex-character id the store could plausibly have assigned, but never did.
UNKNOWN_ID = "0123456789abcdef0123456789abcdef"


class _NoCameraAdapter(FakeSimAdapter):
    """A fake that declares every other capability but not ``can_control_camera``."""

    @property
    def name(self) -> str:
        return "no-camera"

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(can_set_position=True, can_set_aircraft_state=True)


class _NamedViewsOnlyAdapter(FakeSimAdapter):
    """``can_control_camera``, but no free-camera positioning (D3/D7, §5.2).

    The X-Plane adapter's plausible Phase 3 shape: the named views fire as
    commands, while ``XPLMCameraControl`` may need the optional in-sim bridge.
    The panel must still get its view grid.
    """

    _REASON = "Free-camera positioning needs the optional in-sim bridge on this X-Plane build."

    @property
    def name(self) -> str:
        return "named-views-only"

    async def get_camera_support(self) -> CameraSupportManifest:
        return CameraSupportManifest(
            caveat=None,
            views=tuple(
                CameraViewSupport(view_id=view_id, supported=True) for view_id in CAMERA_VIEW_IDS
            ),
            custom_positions_supported=False,
            custom_positions_reason=self._REASON,
        )


class _MissingWingViewAdapter(FakeSimAdapter):
    """One view unreachable, the rest fine (§10.4 — the lowest-confidence row)."""

    _REASON = "No usable command for the wing view on this install."

    @property
    def name(self) -> str:
        return "no-wing"

    async def get_camera_support(self) -> CameraSupportManifest:
        return CameraSupportManifest(
            caveat=None,
            views=tuple(
                CameraViewSupport(
                    view_id=view_id,
                    supported=view_id != "wing",
                    reason=None if view_id != "wing" else self._REASON,
                )
                for view_id in CAMERA_VIEW_IDS
            ),
            custom_positions_supported=True,
        )


@pytest.fixture(autouse=True)
def camera_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the saved-position store at ``tmp_path`` for every test in this file."""
    store = CameraPositionStore(tmp_path / "camera_positions")
    monkeypatch.setattr(server.deps, "_build_camera_position_store", lambda _settings: store)
    server.deps.reset_camera_position_store()
    yield
    server.deps.reset_camera_position_store()


@pytest.fixture
def client() -> TestClient:
    """A client whose adapter is the default ``FakeSimAdapter``. No navdata involved."""
    return TestClient(create_app())


def _client_for(adapter: FakeSimAdapter, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(server.deps, "_build_adapter", lambda _settings: adapter)
    reset_adapter()
    return TestClient(create_app())


@pytest.fixture
def no_camera_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    yield _client_for(_NoCameraAdapter(), monkeypatch)
    reset_adapter()


@pytest.fixture
def named_views_only_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    yield _client_for(_NamedViewsOnlyAdapter(), monkeypatch)
    reset_adapter()


@pytest.fixture
def no_wing_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    yield _client_for(_MissingWingViewAdapter(), monkeypatch)
    reset_adapter()


def _stage_a_free_camera_pose(offset: CameraOffset = OFFSET) -> None:
    """Put the adapter in the state ``POST /positions`` needs.

    Written through the adapter rather than an endpoint (§8.4's own "called on
    the Fake directly") because no endpoint sets an arbitrary free-camera pose:
    the instructor flies the drone camera inside the simulator and the station
    only *captures* where it ended up. Through the public coroutine rather than
    the fake's private attribute, so this stays a test of the behaviour the
    contract suite pins.
    """
    asyncio.run(get_adapter().set_camera_offset(offset))


# ---------------------------------------------------------------------------
# GET /manifest
# ---------------------------------------------------------------------------


class TestManifest:
    def test_the_fake_supports_every_view_and_custom_positions(self, client: TestClient) -> None:
        response = client.get("/api/camera/manifest")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["adapter"] == "fake"
        assert tuple(entry["view_id"] for entry in body["views"]) == CAMERA_VIEW_IDS
        assert all(entry["supported"] for entry in body["views"])
        assert body["custom_positions_supported"] is True

    def test_it_answers_without_the_capability(self, no_camera_client: TestClient) -> None:
        """Capability-free (§2.1): "nothing, and here is why" is still a 200."""
        response = no_camera_client.get("/api/camera/manifest")

        assert response.status_code == 200, response.text
        body = response.json()
        assert tuple(entry["view_id"] for entry in body["views"]) == CAMERA_VIEW_IDS
        assert not any(entry["supported"] for entry in body["views"])
        assert all(entry["reason"] for entry in body["views"])
        assert body["custom_positions_supported"] is False
        assert body["custom_positions_reason"]

    def test_free_positioning_can_be_unsupported_while_the_views_work(
        self, named_views_only_client: TestClient
    ) -> None:
        """D3's whole point: one manifest, two independent answers."""
        body = named_views_only_client.get("/api/camera/manifest").json()

        assert all(entry["supported"] for entry in body["views"])
        assert body["custom_positions_supported"] is False
        assert "bridge" in body["custom_positions_reason"]


# ---------------------------------------------------------------------------
# POST /view
# ---------------------------------------------------------------------------


class TestSetView:
    @pytest.mark.parametrize("view_id", CAMERA_VIEW_IDS)
    def test_every_catalogue_view_is_accepted(self, client: TestClient, view_id: str) -> None:
        response = client.post("/api/camera/view", json={"view_id": view_id})

        assert response.status_code == 200, response.text
        assert response.json() == {"view_id": view_id, "offset": None}

    def test_it_is_idempotent(self, client: TestClient) -> None:
        """Asking twice for the same view is a no-op outcome, not an error (§2)."""
        assert client.post("/api/camera/view", json={"view_id": "chase"}).status_code == 200
        assert client.post("/api/camera/view", json={"view_id": "chase"}).status_code == 200

    def test_without_the_capability_it_is_501(self, no_camera_client: TestClient) -> None:
        response = no_camera_client.post("/api/camera/view", json={"view_id": "chase"})

        assert response.status_code == 501, response.text
        assert "can_control_camera" in response.json()["detail"]

    def test_an_unsupported_view_is_501_with_the_manifests_own_reason(
        self, no_wing_client: TestClient
    ) -> None:
        response = no_wing_client.post("/api/camera/view", json={"view_id": "wing"})

        assert response.status_code == 501, response.text
        assert response.json()["detail"] == _MissingWingViewAdapter._REASON

    def test_the_other_views_still_work_on_that_adapter(self, no_wing_client: TestClient) -> None:
        """One missing view degrades a control, never the manager (D2/§10.4)."""
        assert no_wing_client.post("/api/camera/view", json={"view_id": "chase"}).status_code == 200

    def test_an_unknown_view_id_is_422(self, client: TestClient) -> None:
        """Free, from the closed ``CameraViewId`` literal (§2.2)."""
        assert client.post("/api/camera/view", json={"view_id": "orbit"}).status_code == 422

    def test_an_extra_field_is_422(self, client: TestClient) -> None:
        response = client.post("/api/camera/view", json={"view_id": "chase", "zoom": 2})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# The saved positions
# ---------------------------------------------------------------------------


class TestSavedPositions:
    def test_the_list_starts_empty(self, client: TestClient) -> None:
        response = client.get("/api/camera/positions")

        assert response.status_code == 200, response.text
        assert response.json() == []

    def test_saving_without_a_live_free_camera_pose_is_409(self, client: TestClient) -> None:
        """D9. The adapter can position the camera; there is just nothing to capture yet."""
        response = client.post("/api/camera/positions", json={"name": "Base leg"})

        assert response.status_code == 409, response.text
        assert response.json()["detail"] == NO_LIVE_OFFSET_DETAIL

    def test_the_full_save_list_apply_delete_cycle(self, client: TestClient) -> None:
        _stage_a_free_camera_pose()

        saved = client.post("/api/camera/positions", json={"name": "Base leg view"})
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["name"] == "Base leg view"
        assert body["offset"] == OFFSET.model_dump()

        listed = client.get("/api/camera/positions")
        assert [entry["position_id"] for entry in listed.json()] == [body["position_id"]]

        applied = client.post(f"/api/camera/positions/{body['position_id']}/apply")
        assert applied.status_code == 200, applied.text
        assert applied.json() == {"view_id": None, "offset": OFFSET.model_dump()}

        deleted = client.delete(f"/api/camera/positions/{body['position_id']}")
        assert deleted.status_code == 204
        assert client.get("/api/camera/positions").json() == []
        assert client.delete(f"/api/camera/positions/{body['position_id']}").status_code == 404

    def test_switching_to_a_named_view_reinstates_the_409(self, client: TestClient) -> None:
        """The precondition is live state, not a one-off (§4.1: a named view clears the pose)."""
        _stage_a_free_camera_pose()
        assert client.post("/api/camera/positions", json={"name": "First"}).status_code == 200

        assert client.post("/api/camera/view", json={"view_id": "cockpit"}).status_code == 200
        assert client.post("/api/camera/positions", json={"name": "Second"}).status_code == 409

    def test_applying_an_unknown_id_is_404(self, client: TestClient) -> None:
        response = client.post(f"/api/camera/positions/{UNKNOWN_ID}/apply")

        assert response.status_code == 404, response.text
        assert UNKNOWN_ID in response.json()["detail"]

    def test_deleting_an_unknown_id_is_404(self, client: TestClient) -> None:
        response = client.delete(f"/api/camera/positions/{UNKNOWN_ID}")

        assert response.status_code == 404, response.text
        assert "may already be deleted" in response.json()["detail"]

    def test_listing_and_deleting_need_no_capability(self, no_camera_client: TestClient) -> None:
        """Local storage, not a simulator write (§2) — never 501."""
        assert no_camera_client.get("/api/camera/positions").status_code == 200
        assert no_camera_client.delete(f"/api/camera/positions/{UNKNOWN_ID}").status_code == 404

    def test_saving_without_the_capability_is_501(self, no_camera_client: TestClient) -> None:
        response = no_camera_client.post("/api/camera/positions", json={"name": "Base leg"})

        assert response.status_code == 501, response.text
        assert "can_control_camera" in response.json()["detail"]

    def test_saving_without_custom_position_support_is_501(
        self, named_views_only_client: TestClient
    ) -> None:
        """The manifest's own sentence, not a generic one (§2.1)."""
        response = named_views_only_client.post("/api/camera/positions", json={"name": "Wing"})

        assert response.status_code == 501, response.text
        assert response.json()["detail"] == _NamedViewsOnlyAdapter._REASON

    def test_applying_without_custom_position_support_is_501(
        self, named_views_only_client: TestClient
    ) -> None:
        response = named_views_only_client.post(f"/api/camera/positions/{UNKNOWN_ID}/apply")

        assert response.status_code == 501, response.text
        assert response.json()["detail"] == _NamedViewsOnlyAdapter._REASON

    def test_positions_survive_a_new_client(self, client: TestClient) -> None:
        """The store is a directory, not process memory — a restart keeps the framing."""
        _stage_a_free_camera_pose()
        saved = client.post("/api/camera/positions", json={"name": "Persistent"}).json()

        fresh = TestClient(create_app())
        assert [entry["position_id"] for entry in fresh.get("/api/camera/positions").json()] == [
            saved["position_id"]
        ]

    @pytest.mark.parametrize("name", ["", "x" * 61])
    def test_a_bad_name_is_422(self, client: TestClient, name: str) -> None:
        """1-60 characters (§2.2). Checked before the adapter is ever asked."""
        assert client.post("/api/camera/positions", json={"name": name}).status_code == 422

    def test_a_60_character_name_is_accepted(self, client: TestClient) -> None:
        _stage_a_free_camera_pose()
        response = client.post("/api/camera/positions", json={"name": "x" * 60})
        assert response.status_code == 200, response.text

    def test_an_extra_field_is_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/camera/positions", json={"name": "Base leg", "offset": OFFSET.model_dump()}
        )
        assert response.status_code == 422
