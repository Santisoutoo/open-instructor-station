"""Entry point frozen into the packaged executable.

``packaging/instructor-station.spec`` points PyInstaller at this file, which does
nothing the console script does not — it delegates straight to
:func:`server.__main__.main` — except keep a double-clicked console window open
long enough for a crash to be read. PyInstaller needs a plain script as its
entry point, so this cannot simply be ``server/__main__.py``.

Not imported by the application; it only ever runs as ``__main__``.
"""

from __future__ import annotations

import multiprocessing
import sys
import traceback
from contextlib import suppress

from server.__main__ import main


def _pause_if_interactive() -> None:
    """Hold a double-clicked console window open so the traceback is readable."""
    if sys.stdin is None or not sys.stdin.isatty():
        return
    with suppress(Exception):
        input("\nThe instructor station stopped. Press Enter to close this window... ")


def run() -> int:
    """Run the server, returning a process exit code."""
    try:
        main()
    except KeyboardInterrupt:
        return 130
    except Exception:
        traceback.print_exc()
        _pause_if_interactive()
        return 1
    return 0


if __name__ == "__main__":
    # Harmless when nothing forks, required the moment anything does.
    multiprocessing.freeze_support()
    sys.exit(run())
