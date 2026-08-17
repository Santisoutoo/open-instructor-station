"""Where training profiles live on disk — the per-OS user application-data directory.

Follows the exact pattern ``core/navdata/xplane_native/build.py::cache_directory``
already established for ``OIS_NAVDATA_CACHE_DIR``: a runtime branch over three
real destinations (``platform.system()``, not ``sys.platform`` — the same
reasoning that module's own comment gives), and ``environ`` injectable so a
test never has to monkeypatch the process environment. No third-party
dependency (D2 of ``docs/designs/training-profiles.md``): this is one
directory on three branches, not the author/appname/roaming-vs-local surface a
full ``platformdirs`` dependency would bring in for a ``pyproject.toml`` that
pins its dependency set deliberately.
"""

from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from pathlib import Path

__all__ = ["APP_NAME", "default_profiles_root"]

APP_NAME = "OpenInstructorStation"


def default_profiles_root(*, environ: Mapping[str, str] | None = None) -> Path:
    """The per-OS user application-data directory for training profiles.

    Pure computation, no I/O — constructing the path never creates it, the
    same posture ``core.navdata.provider.NavdataProvider`` takes: nothing
    touches disk until something is actually read or written.

    * Windows: ``%APPDATA%/OpenInstructorStation/profiles``
    * macOS:   ``~/Library/Application Support/OpenInstructorStation/profiles``
    * Linux/other POSIX (XDG Base Directory spec):
      ``$XDG_DATA_HOME/OpenInstructorStation/profiles``, falling back to
      ``~/.local/share/OpenInstructorStation/profiles``

    ``environ`` is injectable for tests — the exact convention
    ``cache_directory`` uses for ``OIS_NAVDATA_CACHE_DIR`` — so a test never
    has to monkeypatch ``os.environ`` itself to exercise a branch.
    """
    env = environ if environ is not None else os.environ

    system = platform.system()
    if system == "Windows":
        base = env.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
        return root / APP_NAME / "profiles"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME / "profiles"

    xdg = env.get("XDG_DATA_HOME")
    root = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return root / APP_NAME / "profiles"
