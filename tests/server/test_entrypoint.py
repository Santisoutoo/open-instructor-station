"""The executable entry point — ``server/__main__.py`` and ``packaging/launcher.py``.

Issue #45. None of this was covered, and two of its decisions fail in shapes that
are hard to notice:

* :func:`ui_dist_path` picks between the PyInstaller bundle and the source
  checkout. Get it wrong and the executable starts, answers ``/api/health``
  perfectly, and serves a **blank page** — everything except the actual product
  appears to work.
* :func:`_should_open_browser` decides whether a browser is launched. Get it
  wrong and CI hangs waiting on a browser that never opens.

The frozen half is exercised by monkeypatching ``sys.frozen`` / ``sys._MEIPASS``
and laying the bundle out under ``tmp_path``, so no PyInstaller build is needed
and the whole module runs in CI in milliseconds. The layout used here —
``<bundle>/ui/dist`` — is the one ``packaging/instructor-station.spec`` declares
in its ``datas``; that pair is the contract these tests pin.
"""

import importlib.util
import ipaddress
import logging
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from types import ModuleType, TracebackType
from typing import Self

import pytest
import uvicorn
from fastapi.testclient import TestClient

import server.__main__ as entrypoint
import server.app
from server.__main__ import (
    WILDCARD_HOSTS,
    _bind_bundled_ui,
    _browse_host,
    _is_frozen,
    _lan_ip,
    _log_reachable_urls,
    _open_browser_when_ready,
    _should_open_browser,
    _url_for,
    _wait_for_port,
    main,
    ui_dist_path,
)
from server.app import create_app
from server.deps import Settings

#: Marker written into the fake bundle's ``index.html``. If the executable ever
#: serves a blank page instead of this, the test that asserts it fails.
INDEX_HTML = "<!doctype html><title>Open Instructor Station</title><div id=root></div>"

#: A built asset, to prove the mount serves the whole tree and not just ``/``.
ASSET_JS = "export const marker = 'bundled-asset';"

#: Recorded ``uvicorn.run`` calls: one ``(positional args, keyword args)`` pair
#: per call, so a test can assert the server was started exactly once.
UvicornCalls = list[tuple[tuple[object, ...], dict[str, object]]]


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _unfrozen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test from a plain interpreter, whatever ran before it."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.delenv("OIS_OPEN_BROWSER", raising=False)


@pytest.fixture(autouse=True)
def _restore_app_ui_dist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Register ``server.app.UI_DIST`` for restoration.

    ``_bind_bundled_ui`` rebinds it as a module attribute; without this, a frozen
    test would leave every later test serving a temporary directory that no
    longer exists.
    """
    monkeypatch.setattr(server.app, "UI_DIST", server.app.UI_DIST)


def _freeze(monkeypatch: pytest.MonkeyPatch, bundle_root: Path) -> None:
    """Make the process look like a running PyInstaller one-file bundle."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_root), raising=False)


@pytest.fixture
def bundle_root(tmp_path: Path) -> Path:
    """A directory laid out the way PyInstaller extracts the bundle at run time."""
    dist = tmp_path / "ui" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (dist / "assets" / "app.js").write_text(ASSET_JS, encoding="utf-8")
    return tmp_path


def _join_browser_threads(timeout: float = 5.0) -> None:
    """Wait for any thread ``main`` started, so assertions are not racing it."""
    for thread in threading.enumerate():
        if thread.name == "open-browser":
            thread.join(timeout)
            assert not thread.is_alive(), "the browser thread outlived its join timeout"


# ---------------------------------------------------------------------------
# ui_dist_path: the source checkout
# ---------------------------------------------------------------------------


def test_ui_dist_path_points_at_the_checkout_ui_dist() -> None:
    """From source, the built frontend lives beside the sources, not in a bundle."""
    path = ui_dist_path()
    assert path.is_absolute()
    assert path.parts[-2:] == ("ui", "dist")
    # Anchored on something only the real repository root has: proof the two
    # `.parent` hops landed on the checkout and not one directory off.
    assert (path.parent.parent / "pyproject.toml").is_file()
    assert (path.parent.parent / "server" / "__main__.py").is_file()


def test_ui_dist_path_agrees_with_the_directory_the_app_mounts() -> None:
    """The invariant that makes a source run work without any rebinding.

    ``server.app`` derives ``UI_DIST`` from its own ``__file__``. If the two ever
    disagree, a checkout serves one directory and the executable another.
    """
    assert ui_dist_path() == server.app.UI_DIST


def test_ui_dist_path_does_not_depend_on_the_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A double-clicked executable inherits whatever CWD the shell had."""
    expected = ui_dist_path()
    monkeypatch.chdir(tmp_path)
    assert ui_dist_path() == expected


# ---------------------------------------------------------------------------
# ui_dist_path: the PyInstaller bundle
# ---------------------------------------------------------------------------


def test_ui_dist_path_uses_the_bundle_when_frozen(
    monkeypatch: pytest.MonkeyPatch, bundle_root: Path
) -> None:
    """``<sys._MEIPASS>/ui/dist`` — the destination declared in the .spec ``datas``."""
    _freeze(monkeypatch, bundle_root)
    assert ui_dist_path() == bundle_root / "ui" / "dist"
    assert ui_dist_path().is_dir()


def test_ui_dist_path_prefers_the_bundle_over_the_checkout(
    monkeypatch: pytest.MonkeyPatch, bundle_root: Path
) -> None:
    """The source path is never used once the bundle has been extracted."""
    checkout = ui_dist_path()
    _freeze(monkeypatch, bundle_root)
    assert ui_dist_path() != checkout


def test_is_frozen_is_false_in_a_normal_interpreter() -> None:
    assert _is_frozen() is False


def test_is_frozen_follows_sys_frozen(monkeypatch: pytest.MonkeyPatch, bundle_root: Path) -> None:
    _freeze(monkeypatch, bundle_root)
    assert _is_frozen() is True


# ---------------------------------------------------------------------------
# Binding the bundled UI onto the app
# ---------------------------------------------------------------------------


def test_bind_bundled_ui_leaves_a_source_checkout_alone() -> None:
    before = server.app.UI_DIST
    _bind_bundled_ui()
    mounted = server.app.UI_DIST
    assert mounted == before


def test_bind_bundled_ui_points_the_app_at_the_bundle(
    monkeypatch: pytest.MonkeyPatch, bundle_root: Path
) -> None:
    _freeze(monkeypatch, bundle_root)
    _bind_bundled_ui()
    mounted = server.app.UI_DIST
    assert mounted == bundle_root / "ui" / "dist"


def test_bind_bundled_ui_says_where_it_is_serving_from(
    monkeypatch: pytest.MonkeyPatch, bundle_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The console line an operator reads when the page comes up empty."""
    _freeze(monkeypatch, bundle_root)
    with caplog.at_level(logging.INFO, logger="server.__main__"):
        _bind_bundled_ui()
    assert str(bundle_root / "ui" / "dist") in caplog.text


def test_a_frozen_bundle_actually_serves_the_built_ui(
    monkeypatch: pytest.MonkeyPatch, bundle_root: Path
) -> None:
    """The blank-page regression, end to end.

    Freeze, bind, build the app: ``/`` must return the bundled ``index.html``,
    which is the whole point of the executable.
    """
    _freeze(monkeypatch, bundle_root)
    _bind_bundled_ui()
    with TestClient(create_app()) as client:
        root = client.get("/")
        asset = client.get("/assets/app.js")
    assert root.status_code == 200
    assert root.text == INDEX_HTML
    assert asset.status_code == 200
    assert asset.text == ASSET_JS


def test_the_bundled_ui_does_not_shadow_the_api(
    monkeypatch: pytest.MonkeyPatch, bundle_root: Path
) -> None:
    """Mounting static files at ``/`` must not swallow ``/api/*``."""
    _freeze(monkeypatch, bundle_root)
    _bind_bundled_ui()
    with TestClient(create_app()) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_a_frozen_bundle_without_a_built_ui_still_serves_the_api(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A bundle built without ``ui/dist`` is broken, but must not be *dead*.

    The API has to keep answering so the failure is diagnosable instead of
    presenting as a process that will not start.
    """
    _freeze(monkeypatch, tmp_path)
    _bind_bundled_ui()
    assert not ui_dist_path().exists()
    with TestClient(create_app()) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/").status_code == 404


def test_the_server_starts_without_a_built_ui(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Running from source before ``npm run build`` has ever been run."""
    monkeypatch.setattr(server.app, "UI_DIST", tmp_path / "never-built")
    with TestClient(create_app()) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/state").status_code == 200
        assert client.get("/").status_code == 404


# ---------------------------------------------------------------------------
# _should_open_browser
# ---------------------------------------------------------------------------


def test_a_source_run_does_not_open_a_browser() -> None:
    assert _should_open_browser() is False


def test_a_ci_like_environment_never_opens_a_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guard against reintroducing a hang: CI runs unfrozen and unconfigured."""
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("OIS_OPEN_BROWSER", raising=False)
    assert _should_open_browser() is False


def test_a_packaged_run_opens_a_browser(monkeypatch: pytest.MonkeyPatch, bundle_root: Path) -> None:
    """Double-clicking an executable has to put something in front of the user."""
    _freeze(monkeypatch, bundle_root)
    assert _should_open_browser() is True


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "  Yes  ", "on"])
def test_ois_open_browser_forces_a_browser_on(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("OIS_OPEN_BROWSER", value)
    assert _should_open_browser() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "  ", "maybe"])
def test_ois_open_browser_forces_a_browser_off_even_when_packaged(
    monkeypatch: pytest.MonkeyPatch, bundle_root: Path, value: str
) -> None:
    _freeze(monkeypatch, bundle_root)
    monkeypatch.setenv("OIS_OPEN_BROWSER", value)
    assert _should_open_browser() is False


# ---------------------------------------------------------------------------
# The URLs printed for the operator and the tablet
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("host", sorted(WILDCARD_HOSTS))
def test_a_wildcard_bind_is_browsed_on_loopback(host: str) -> None:
    """``http://0.0.0.0:8000/`` is not a browsable address."""
    assert _browse_host(host) == "127.0.0.1"


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "192.168.1.20"])
def test_a_concrete_bind_is_browsed_as_is(host: str) -> None:
    assert _browse_host(host) == host


@pytest.mark.parametrize(
    ("host", "port", "expected"),
    [
        ("127.0.0.1", 8000, "http://127.0.0.1:8000/"),
        ("localhost", 9123, "http://localhost:9123/"),
        ("192.168.1.20", 8000, "http://192.168.1.20:8000/"),
        ("::1", 8000, "http://[::1]:8000/"),
        ("fe80::1c2b", 8000, "http://[fe80::1c2b]:8000/"),
    ],
)
def test_url_for_brackets_ipv6_literals(host: str, port: int, expected: str) -> None:
    assert _url_for(host, port) == expected


def test_a_wildcard_bind_advertises_the_tablet_url(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Using the station from a tablet is a first-class scenario — say the URL."""
    monkeypatch.setattr(entrypoint, "_lan_ip", lambda: "192.168.1.20")
    settings = Settings(host="0.0.0.0", port=8000)
    with caplog.at_level(logging.INFO, logger="server.__main__"):
        _log_reachable_urls(settings)
    assert "http://127.0.0.1:8000/" in caplog.text
    assert "http://192.168.1.20:8000/" in caplog.text


def test_a_concrete_bind_never_looks_up_the_lan_address(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Bound to loopback, there is no tablet URL to advertise — and no lookup."""
    calls: list[None] = []

    def _fail() -> str | None:
        calls.append(None)
        return "192.168.1.20"

    monkeypatch.setattr(entrypoint, "_lan_ip", _fail)
    settings = Settings(host="127.0.0.1", port=9123)
    with caplog.at_level(logging.INFO, logger="server.__main__"):
        _log_reachable_urls(settings)
    assert "http://127.0.0.1:9123/" in caplog.text
    assert calls == []


def test_a_machine_with_no_route_out_still_prints_its_local_url(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(entrypoint, "_lan_ip", lambda: None)
    settings = Settings(host="0.0.0.0", port=8000)
    with caplog.at_level(logging.INFO, logger="server.__main__"):
        _log_reachable_urls(settings)
    assert "http://127.0.0.1:8000/" in caplog.text
    assert "tablet" not in caplog.text


# ---------------------------------------------------------------------------
# _lan_ip
# ---------------------------------------------------------------------------


class _FakeSocket:
    """A UDP socket that never touches the network."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.connected: tuple[str, int] | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def connect(self, address: tuple[str, int]) -> None:
        self.connected = address

    def getsockname(self) -> tuple[str, int]:
        return ("192.168.1.20", 54321)


class _UnroutableSocket(_FakeSocket):
    """A machine with no route out: the UDP connect fails."""

    def connect(self, address: tuple[str, int]) -> None:
        raise OSError("network is unreachable")


def test_lan_ip_reports_the_source_address_the_os_would_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "socket", _FakeSocket)
    assert _lan_ip() == "192.168.1.20"


def test_lan_ip_is_none_when_the_machine_has_no_route_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An offline laptop must not crash the startup banner."""
    monkeypatch.setattr(socket, "socket", _UnroutableSocket)
    assert _lan_ip() is None


def test_lan_ip_returns_an_ipv4_address_or_nothing() -> None:
    """Run for real: whatever this machine has, the contract is IPv4 or ``None``."""
    address = _lan_ip()
    if address is not None:
        assert ipaddress.ip_address(address).version == 4


# ---------------------------------------------------------------------------
# Waiting for the port, then opening the browser
# ---------------------------------------------------------------------------


def test_wait_for_port_returns_once_something_is_listening() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = int(listener.getsockname()[1])
        assert _wait_for_port("127.0.0.1", port, time.monotonic() + 5.0) is True


def test_wait_for_port_does_not_connect_once_the_deadline_has_passed() -> None:
    """A deadline already in the past means no attempt at all."""
    started = time.monotonic()
    assert _wait_for_port("127.0.0.1", 9, time.monotonic() - 1.0) is False
    assert time.monotonic() - started < 0.5


def test_wait_for_port_gives_up_when_nothing_ever_answers() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    # The port is closed again before the poll starts: nothing can answer.
    assert _wait_for_port("127.0.0.1", port, time.monotonic() + 0.4) is False


def test_the_browser_opens_on_the_url_the_server_answers_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[str] = []

    def _open(url: str) -> bool:
        opened.append(url)
        return True

    monkeypatch.setattr(entrypoint, "_wait_for_port", lambda *_args: True)
    monkeypatch.setattr(webbrowser, "open", _open)
    _open_browser_when_ready("127.0.0.1", 8000)
    assert opened == ["http://127.0.0.1:8000/"]


def test_no_browser_is_opened_when_the_server_never_answers(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Nothing on the port means a broken start, not a browser on a dead URL."""

    def _must_not_open(url: str) -> bool:
        raise AssertionError(f"a browser was opened on a dead server: {url}")

    monkeypatch.setattr(entrypoint, "_wait_for_port", lambda *_args: False)
    monkeypatch.setattr(webbrowser, "open", _must_not_open)
    with caplog.at_level(logging.WARNING, logger="server.__main__"):
        _open_browser_when_ready("127.0.0.1", 8000)
    assert "http://127.0.0.1:8000/" in caplog.text


def test_a_headless_machine_is_told_which_url_to_open_by_hand(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """``webbrowser.open`` returning False is normal on a server without a GUI."""
    monkeypatch.setattr(entrypoint, "_wait_for_port", lambda *_args: True)
    monkeypatch.setattr(webbrowser, "open", lambda _url: False)
    with caplog.at_level(logging.WARNING, logger="server.__main__"):
        _open_browser_when_ready("192.168.1.20", 9123)
    assert "http://192.168.1.20:9123/" in caplog.text


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


@pytest.fixture
def uvicorn_calls(monkeypatch: pytest.MonkeyPatch) -> UvicornCalls:
    """Capture the ``uvicorn.run`` call instead of starting a server."""
    calls: UvicornCalls = []

    def _record(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(uvicorn, "run", _record)
    monkeypatch.setattr(entrypoint, "_lan_ip", lambda: "192.168.1.20")
    return calls


@pytest.fixture
def browser_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    """Record what ``main`` hands the browser thread, opening nothing.

    Used by every ``main`` test, including the ones that assert *no* browser:
    a regression must show up as a failed assertion, never as a real browser
    window on the machine running the suite.
    """
    calls: list[tuple[str, int]] = []

    def _record(host: str, port: int) -> None:
        calls.append((host, port))

    monkeypatch.setattr(entrypoint, "_open_browser_when_ready", _record)
    return calls


def test_main_starts_uvicorn_on_the_configured_host_and_port(
    monkeypatch: pytest.MonkeyPatch,
    uvicorn_calls: UvicornCalls,
    browser_calls: list[tuple[str, int]],
) -> None:
    monkeypatch.setenv("OIS_HOST", "127.0.0.1")
    monkeypatch.setenv("OIS_PORT", "9123")
    main()
    _join_browser_threads()
    assert len(uvicorn_calls) == 1
    args, kwargs = uvicorn_calls[0]
    # An import string plus factory=True, not an app object: that is what lets
    # `_bind_bundled_ui` run before `create_app` is ever called.
    assert args == ("server.app:create_app",)
    assert kwargs["factory"] is True
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 9123
    assert browser_calls == []


def test_main_does_not_open_a_browser_from_a_source_checkout(
    monkeypatch: pytest.MonkeyPatch,
    uvicorn_calls: UvicornCalls,
    browser_calls: list[tuple[str, int]],
) -> None:
    """The CI hang guard, at the level that would actually hang."""
    monkeypatch.setenv("OIS_HOST", "0.0.0.0")
    monkeypatch.setenv("OIS_PORT", "8000")
    main()
    _join_browser_threads()
    assert browser_calls == []
    assert len(uvicorn_calls) == 1


def test_main_opens_the_browser_on_loopback_when_bound_to_every_interface(
    monkeypatch: pytest.MonkeyPatch,
    uvicorn_calls: UvicornCalls,
    browser_calls: list[tuple[str, int]],
) -> None:
    """uvicorn binds ``0.0.0.0``; the browser must still be sent to ``127.0.0.1``."""
    monkeypatch.setenv("OIS_HOST", "0.0.0.0")
    monkeypatch.setenv("OIS_PORT", "9123")
    monkeypatch.setenv("OIS_OPEN_BROWSER", "1")
    main()
    _join_browser_threads()
    assert browser_calls == [("127.0.0.1", 9123)]
    assert uvicorn_calls[0][1]["host"] == "0.0.0.0"


def test_main_binds_the_bundled_ui_before_starting_the_server(
    monkeypatch: pytest.MonkeyPatch,
    bundle_root: Path,
    uvicorn_calls: UvicornCalls,
    browser_calls: list[tuple[str, int]],
) -> None:
    """The packaged path, in the order that matters: bind, then serve."""
    _freeze(monkeypatch, bundle_root)
    main()
    _join_browser_threads()
    mounted = server.app.UI_DIST
    assert mounted == bundle_root / "ui" / "dist"
    assert len(uvicorn_calls) == 1
    # Frozen and unconfigured: a double-clicked executable opens a browser.
    assert browser_calls == [("127.0.0.1", 8000)]


def test_main_reports_the_adapter_it_is_starting_with(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    uvicorn_calls: UvicornCalls,
    browser_calls: list[tuple[str, int]],
) -> None:
    monkeypatch.setenv("OIS_HOST", "127.0.0.1")
    with caplog.at_level(logging.INFO, logger="server.__main__"):
        main()
    _join_browser_threads()
    assert "fake" in caplog.text
    assert "http://127.0.0.1:8000/" in caplog.text
    assert browser_calls == []


# ---------------------------------------------------------------------------
# packaging/launcher.py — the script PyInstaller actually freezes
# ---------------------------------------------------------------------------


@pytest.fixture
def launcher() -> ModuleType:
    """Load ``packaging/launcher.py`` by path.

    ``packaging/`` is not an importable package (and the name collides with the
    PyPI ``packaging`` distribution), so the frozen entry point is loaded from
    its file — which also asserts the path the ``.spec`` points at still exists.
    """
    path = Path(entrypoint.__file__).resolve().parent.parent / "packaging" / "launcher.py"
    assert path.is_file(), f"the .spec's entry point is missing: {path}"
    spec = importlib.util.spec_from_file_location("ois_packaging_launcher", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_launcher_delegates_to_the_console_entry_point(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The executable and ``instructor-station`` must run the same code."""
    assert launcher.main is main
    calls: list[None] = []
    monkeypatch.setattr(launcher, "main", lambda: calls.append(None))
    assert launcher.run() == 0
    assert calls == [None]


def test_ctrl_c_is_a_clean_stop_not_a_crash(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ctrl-C is how the operator stops the station; 130 is the shell's word for it."""

    def _interrupted() -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(launcher, "main", _interrupted)
    monkeypatch.setattr("builtins.input", lambda *_args: "")
    assert launcher.run() == 130


def test_a_crash_exits_nonzero_and_prints_the_traceback(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _explode() -> None:
        raise RuntimeError("port 8000 is already in use")

    monkeypatch.setattr(launcher, "main", _explode)
    # Never block: under `pytest -s` stdin is a real tty and the pause would run.
    monkeypatch.setattr("builtins.input", lambda *_args: "")
    assert launcher.run() == 1
    stderr = capsys.readouterr().err
    assert "RuntimeError" in stderr
    assert "port 8000 is already in use" in stderr


def test_the_launcher_does_not_pause_when_it_is_not_interactive(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Piped or redirected — a service run must not wait for a keypress."""

    def _must_not_prompt(*_args: object) -> str:
        raise AssertionError("a non-interactive run blocked on input()")

    monkeypatch.setattr("builtins.input", _must_not_prompt)
    monkeypatch.setattr(launcher.sys, "stdin", None)
    launcher._pause_if_interactive()
