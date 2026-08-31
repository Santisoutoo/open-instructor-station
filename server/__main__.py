"""Console entry point: ``instructor-station``.

The packaged executable runs this too (via ``packaging/launcher.py``), so two
concerns beyond "start uvicorn" live here: the built UI has to be found whether
we run from a source checkout or from inside a PyInstaller bundle, and a
double-clicked executable should put a browser in front of the instructor
without being asked.
"""

from __future__ import annotations

import logging
import socket
import sys
import threading
import time
import webbrowser
from contextlib import suppress
from pathlib import Path

import uvicorn

from server.deps import Settings, get_settings

__all__ = ["main", "ui_dist_path"]

logger = logging.getLogger(__name__)

#: How long the browser thread waits for the port to answer before giving up.
BROWSER_WAIT_S = 30.0

#: Hosts meaning "every interface" — reachable over the LAN, not browsable as-is.
WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", "*", ""})


def _is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def ui_dist_path() -> Path:
    """Absolute path of the built frontend, bundled or in a source checkout.

    A one-file bundle extracts its data files to ``sys._MEIPASS``; a checkout
    keeps them next to the sources.
    """
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root is not None:
        return Path(bundle_root) / "ui" / "dist"
    return Path(__file__).resolve().parent.parent / "ui" / "dist"


def _bind_bundled_ui() -> None:
    """Point the app at the bundled UI before the app is built.

    ``server.app`` derives ``UI_DIST`` from its own ``__file__`` and mounts the
    directory only when it exists — correct for a checkout, and the reason a
    naive bundle serves the API with a blank page. Rebinding the attribute here
    keeps packaging concerns out of ``server/app.py``; if that module ever grows
    a resource helper of its own, this can go away.
    """
    if not _is_frozen():
        return
    from server import app as app_module

    app_module.UI_DIST = ui_dist_path()
    logger.info("Serving the bundled UI from %s", app_module.UI_DIST)


def _browse_host(host: str) -> str:
    """The address a browser on *this* machine should use to reach ``host``."""
    return "127.0.0.1" if host in WILDCARD_HOSTS else host


def _url_for(host: str, port: int) -> str:
    """An HTTP URL, bracketing IPv6 literals."""
    return f"http://[{host}]:{port}/" if ":" in host else f"http://{host}:{port}/"


def _lan_ip() -> str | None:
    """This machine's LAN address, or ``None`` when it has no route out."""
    with suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        # UDP "connect" sends nothing; it only makes the OS pick a source address.
        sock.connect(("8.8.8.8", 80))
        return str(sock.getsockname()[0])
    return None


def _wait_for_port(host: str, port: int, deadline: float) -> bool:
    """Poll until something accepts a TCP connection, or ``deadline`` passes."""
    while time.monotonic() < deadline:
        with suppress(OSError), socket.create_connection((host, port), timeout=0.5):
            return True
        time.sleep(0.2)
    return False


def _open_browser_when_ready(host: str, port: int) -> None:
    """Open the default browser once the server actually answers."""
    url = _url_for(host, port)
    if not _wait_for_port(host, port, time.monotonic() + BROWSER_WAIT_S):
        logger.warning(
            "Nothing answered on %s within %.0f s; not opening a browser", url, BROWSER_WAIT_S
        )
        return
    if not webbrowser.open(url):
        logger.warning("No browser could be opened; open %s yourself", url)


def _should_open_browser() -> bool:
    """Packaged runs open a browser. ``OIS_OPEN_BROWSER`` overrides either way.

    Reads through ``Settings`` (via ``get_settings()``) like every other
    ``OIS_*`` variable now — the string parsing itself lives in
    ``Settings._parse_open_browser``, not here. Kept as a zero-argument
    function reading the process-wide singleton, rather than taking a
    ``Settings`` explicitly, so a test setting ``OIS_OPEN_BROWSER`` via
    ``monkeypatch`` and re-reading through the (test-cleared) ``get_settings``
    cache sees its own value, exactly as before.
    """
    settings = get_settings()
    if settings.open_browser is None:
        return _is_frozen()
    return settings.open_browser


def _log_reachable_urls(settings: Settings) -> None:
    """Print where to point a browser, including the tablet's URL."""
    logger.info("Instructor station: %s", _url_for(_browse_host(settings.host), settings.port))
    if settings.host not in WILDCARD_HOSTS:
        return
    lan_ip = _lan_ip()
    if lan_ip is not None:
        logger.info("From a tablet on the same network: %s", _url_for(lan_ip, settings.port))


def main() -> None:
    """Run the instructor station server with the configured settings."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    _bind_bundled_ui()
    logger.info(
        "Starting Open Instructor Station on %s:%s with the %r adapter",
        settings.host,
        settings.port,
        settings.adapter,
    )
    _log_reachable_urls(settings)

    if _should_open_browser():
        threading.Thread(
            target=_open_browser_when_ready,
            args=(_browse_host(settings.host), settings.port),
            name="open-browser",
            daemon=True,
        ).start()

    uvicorn.run(
        "server.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
