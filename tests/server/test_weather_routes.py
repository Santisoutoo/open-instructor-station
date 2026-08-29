"""``/api/weather/*`` — read, preview and apply the commanded weather.

Against the Fake via ``TestClient`` (weather-manager.md §9.3): every endpoint;
every error row of §2.2 including "no airport context never 503s even with the
index absent"; ``preview`` is side-effect-free; ``apply`` writes then reads
back and the response ``state`` is the Fake's post-write weather; the 501
sentence names the adapter and the flag; the manifest lists seven presets with
the §4 requirement flags.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

import server.deps
from adapters.fake import FakeSimAdapter
from core.navdata.in_memory import InMemoryNavdataProvider
from core.navdata.models import Airport
from core.navdata.provider import NavdataUnavailable
from core.sim_adapter import Capabilities, WeatherRejected
from core.weather.models import WeatherPresetId
from server.app import create_app
from server.deps import reset_adapter, reset_navdata
from server.weather_routes import CAPABILITY_UNAVAILABLE_STATUS, UNRESOLVABLE_STATUS
from tests.server.conftest import AIRPORT, build_provider


def _preview(client: TestClient, request: dict[str, Any]) -> dict[str, Any]:
    with client:
        response = client.post("/api/weather/preview", json=request)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


class TestGetWeather:
    def test_returns_the_fakes_commanded_weather(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/weather")
        assert response.status_code == 200
        body = response.json()
        assert body["visibility_m"] == pytest.approx(20_000.0)
        assert body["runway_contamination"] == "dry"


class TestGetWeatherManifest:
    def test_supported_on_the_default_fake(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/weather/manifest")
        assert response.status_code == 200
        body = response.json()
        assert body["adapter"] == "fake"
        assert body["supported"] is True
        assert body["reason"] is None

    def test_lists_all_seven_presets(self, client: TestClient) -> None:
        with client:
            body = client.get("/api/weather/manifest").json()
        ids = {entry["id"] for entry in body["presets"]}
        assert ids == {"cavok", "cat_i", "cat_ii", "cat_iii", "storm", "crosswind", "mountain_wave"}

    #: weather-manager.md §4's table, mirrored here so a preset edit that
    #: changes its requirements is a visible diff at the HTTP boundary too.
    _REQUIREMENTS: ClassVar[dict[WeatherPresetId, tuple[bool, bool]]] = {
        "cavok": (False, False),
        "cat_i": (False, True),
        "cat_ii": (False, True),
        "cat_iii": (False, True),
        "storm": (False, True),
        "crosswind": (True, True),
        "mountain_wave": (False, True),
    }

    def test_requirement_flags_match_the_design_table(self, client: TestClient) -> None:
        with client:
            body = client.get("/api/weather/manifest").json()
        by_id = {entry["id"]: entry for entry in body["presets"]}
        for preset_id, (requires_runway, requires_airport) in self._REQUIREMENTS.items():
            entry = by_id[preset_id]
            assert entry["requires_runway"] is requires_runway, preset_id
            assert entry["requires_airport"] is requires_airport, preset_id

    def test_does_not_touch_navdata(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Static data and capability flags only — the manifest never queries navdata."""
        called = False

        class WatchedProvider(InMemoryNavdataProvider):
            def get_airport(self, icao: str) -> Airport | None:
                nonlocal called
                called = True
                return super().get_airport(icao)

        provider = WatchedProvider(airports=[AIRPORT])
        monkeypatch.setattr(server.deps, "_build_navdata", lambda _settings: provider)
        reset_navdata()
        with client:
            response = client.get("/api/weather/manifest")
        assert response.status_code == 200
        assert called is False


class TestPreviewIsSideEffectFree:
    def test_preview_does_not_change_get_weather(self, client: TestClient) -> None:
        with client:
            before = client.get("/api/weather").json()
            client.post("/api/weather/preview", json={"preset": "storm"})
            after = client.get("/api/weather").json()
        assert before == after


class TestPreviewResolution:
    def test_preset_alone_resolves(self, client: TestClient) -> None:
        body = _preview(client, {"preset": "cavok"})
        assert body["setup"]["visibility_m"] == pytest.approx(20_000.0)
        assert body["setup"]["cloud_layers"] == []

    def test_preset_with_runway_and_airport_resolves_crosswind(self, client: TestClient) -> None:
        body = _preview(
            client, {"preset": "crosswind", "airport_icao": "ZZZZ", "runway_ident": "36"}
        )
        layers = body["setup"]["wind_layers"]
        assert len(layers) == 1
        assert layers[0]["direction_deg"] == pytest.approx(90.0)

    def test_preset_with_override_merges(self, client: TestClient) -> None:
        body = _preview(
            client,
            {"preset": "cat_i", "airport_icao": "ZZZZ", "setup": {"visibility_m": 1200.0}},
        )
        assert body["setup"]["visibility_m"] == pytest.approx(1200.0)
        assert any("your override" in note for note in body["notes"])

    def test_setup_only_request_is_used_verbatim(self, client: TestClient) -> None:
        body = _preview(client, {"setup": {"visibility_m": 5000.0}})
        assert body["setup"]["visibility_m"] == pytest.approx(5000.0)

    def test_request_is_echoed_back(self, client: TestClient) -> None:
        request = {"preset": "cavok"}
        body = _preview(client, request)
        assert body["request"]["preset"] == "cavok"


class TestPreviewErrors:
    def test_neither_preset_nor_setup_is_422(self, client: TestClient) -> None:
        with client:
            response = client.post("/api/weather/preview", json={})
        assert response.status_code == 422

    def test_unknown_preset_id_is_422(self, client: TestClient) -> None:
        """``WeatherPresetId`` is a closed ``Literal`` — FastAPI's own body validation."""
        with client:
            response = client.post("/api/weather/preview", json={"preset": "hurricane"})
        assert response.status_code == 422

    def test_crosswind_without_runway_is_422(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/weather/preview", json={"preset": "crosswind", "airport_icao": "ZZZZ"}
            )
        assert response.status_code == UNRESOLVABLE_STATUS
        assert "crosswind" in response.json()["detail"]
        assert "runway" in response.json()["detail"]

    def test_cat_i_without_airport_is_422(self, client: TestClient) -> None:
        with client:
            response = client.post("/api/weather/preview", json={"preset": "cat_i"})
        assert response.status_code == UNRESOLVABLE_STATUS
        assert "cat_i" in response.json()["detail"]

    def test_unknown_airport_is_404(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/weather/preview", json={"preset": "cat_i", "airport_icao": "ZZQQ"}
            )
        assert response.status_code == 404

    def test_unknown_runway_is_404(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/weather/preview",
                json={"preset": "crosswind", "airport_icao": "ZZZZ", "runway_ident": "99"},
            )
        assert response.status_code == 404

    def test_a_request_with_no_airport_never_503s_even_when_navdata_is_broken(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """weather-manager.md §2.2: no airport context never touches navdata."""

        class BrokenProvider(InMemoryNavdataProvider):
            def get_airport(self, icao: str) -> Airport | None:
                raise NavdataUnavailable("in_memory", "The index has not been built.")

        monkeypatch.setattr(server.deps, "_build_navdata", lambda _settings: BrokenProvider())
        reset_navdata()
        broken_client = TestClient(create_app())
        with broken_client:
            response = broken_client.post("/api/weather/preview", json={"preset": "cavok"})
        assert response.status_code == 200

    def test_a_request_naming_an_airport_503s_when_navdata_is_broken(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class BrokenProvider(InMemoryNavdataProvider):
            def get_airport(self, icao: str) -> Airport | None:
                raise NavdataUnavailable("in_memory", "The index has not been built.")

        monkeypatch.setattr(server.deps, "_build_navdata", lambda _settings: BrokenProvider())
        reset_navdata()
        broken_client = TestClient(create_app(), raise_server_exceptions=False)
        with broken_client:
            response = broken_client.post(
                "/api/weather/preview", json={"preset": "cat_i", "airport_icao": "ZZZZ"}
            )
        assert response.status_code == 503


class TestApplyWeather:
    def test_apply_writes_then_reads_back(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/weather/apply", json={"preset": "storm", "airport_icao": "ZZZZ"}
            )
        assert response.status_code == 200
        body = response.json()
        assert body["applied"]["visibility_m"] == pytest.approx(3_000.0)
        assert body["state"]["visibility_m"] == pytest.approx(3_000.0)
        assert body["state"]["runway_contamination"] == "puddles"

    def test_apply_response_state_matches_a_subsequent_get(self, client: TestClient) -> None:
        with client:
            apply_response = client.post(
                "/api/weather/apply", json={"preset": "cat_ii", "airport_icao": "ZZZZ"}
            )
            get_response = client.get("/api/weather")
        assert apply_response.json()["state"] == get_response.json()

    def test_apply_re_resolves_rather_than_trusting_a_client_supplied_setup(
        self, client: TestClient
    ) -> None:
        """D7: apply resolves from the request, never from a client-sent resolved setup."""
        with client:
            response = client.post(
                "/api/weather/apply",
                json={"preset": "crosswind", "airport_icao": "ZZZZ", "runway_ident": "36"},
            )
        assert response.status_code == 200
        applied_layers = response.json()["applied"]["wind_layers"]
        assert applied_layers[0]["direction_deg"] == pytest.approx(90.0)

    def test_apply_with_unresolvable_preset_is_422_and_writes_nothing(
        self, client: TestClient
    ) -> None:
        with client:
            before = client.get("/api/weather").json()
            response = client.post("/api/weather/apply", json={"preset": "crosswind"})
            after = client.get("/api/weather").json()
        assert response.status_code == UNRESOLVABLE_STATUS
        assert before == after


class TestWeatherRejected:
    """§2.2: the simulator, not the request, is at fault -- 502, not 4xx."""

    @pytest.fixture
    def rejecting_client(self, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        class RejectingAdapter(FakeSimAdapter):
            async def get_weather(self) -> Any:
                raise WeatherRejected("the sim would not switch to manual weather mode")

            async def set_weather(self, setup: Any) -> None:
                raise WeatherRejected("the sim would not switch to manual weather mode")

        provider = build_provider()
        monkeypatch.setattr(server.deps, "_build_navdata", lambda _settings: provider)
        monkeypatch.setattr(server.deps, "_build_adapter", lambda _s: RejectingAdapter())
        reset_adapter()
        reset_navdata()
        return TestClient(create_app())

    def test_get_weather_is_502(self, rejecting_client: TestClient) -> None:
        with rejecting_client:
            response = rejecting_client.get("/api/weather")
        assert response.status_code == 502
        assert "manual weather mode" in response.json()["detail"]

    def test_apply_is_502(self, rejecting_client: TestClient) -> None:
        with rejecting_client:
            response = rejecting_client.post("/api/weather/apply", json={"preset": "cavok"})
        assert response.status_code == 502
        assert "manual weather mode" in response.json()["detail"]


class TestCapabilityGating:
    @pytest.fixture
    def incapable_client(self, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        class NoWeatherAdapter(FakeSimAdapter):
            @property
            def capabilities(self) -> Capabilities:
                return super().capabilities.model_copy(update={"can_set_weather": False})

        provider = build_provider()
        monkeypatch.setattr(server.deps, "_build_navdata", lambda _settings: provider)
        monkeypatch.setattr(server.deps, "_build_adapter", lambda _s: NoWeatherAdapter())
        reset_adapter()
        reset_navdata()
        return TestClient(create_app())

    def test_get_weather_is_501(self, incapable_client: TestClient) -> None:
        with incapable_client:
            response = incapable_client.get("/api/weather")
        assert response.status_code == CAPABILITY_UNAVAILABLE_STATUS
        assert "can_set_weather" in response.json()["detail"]
        assert "'fake'" in response.json()["detail"]

    def test_apply_is_501(self, incapable_client: TestClient) -> None:
        with incapable_client:
            response = incapable_client.post("/api/weather/apply", json={"preset": "cavok"})
        assert response.status_code == CAPABILITY_UNAVAILABLE_STATUS
        assert "can_set_weather" in response.json()["detail"]

    def test_manifest_reports_unsupported_with_a_reason(self, incapable_client: TestClient) -> None:
        with incapable_client:
            response = incapable_client.get("/api/weather/manifest")
        assert response.status_code == 200
        body = response.json()
        assert body["supported"] is False
        assert "can_set_weather" in body["reason"]

    def test_preview_still_works_without_the_capability(self, incapable_client: TestClient) -> None:
        """Staging is navdata and arithmetic: it does not need a simulator at all."""
        with incapable_client:
            response = incapable_client.post("/api/weather/preview", json={"preset": "cavok"})
        assert response.status_code == 200
