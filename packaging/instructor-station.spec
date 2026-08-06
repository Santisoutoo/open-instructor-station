# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the double-clickable instructor station.

Build (from the repository root, with the UI already built):

    python -m PyInstaller packaging/instructor-station.spec --noconfirm --clean

Produces ``dist/instructor-station.exe`` on Windows: one file, no Python and no
Node runtime required on the target machine. Unsigned — signing, installers and
auto-update are deliberately out of scope.

Two things this spec has to get right:

* ``ui/dist`` is bundled as data under the same relative path it has in a
  checkout. A one-file executable extracts it to ``sys._MEIPASS`` at run time,
  and ``server/__main__.py`` points the app at it before the app is built.
  Without that the executable starts, answers the API and serves a blank page.
* The console stays attached (``console=True``). It is how the operator reads
  the LAN URL to type on the tablet, and how they stop the server with Ctrl-C.
"""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 — SPECPATH is injected by PyInstaller
UI_DIST = ROOT / "ui" / "dist"

if not UI_DIST.is_dir():
    raise SystemExit(
        f"The built frontend is missing: {UI_DIST}\n"
        "Build it first:  cd ui && npm ci && npm run build"
    )

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    # Destination keeps the checkout-relative layout: <bundle>/ui/dist.
    datas=[(str(UI_DIST), "ui/dist")],
    # Both adapters are imported lazily inside server.deps._build_adapter; naming
    # them keeps the packaged app able to switch adapters through OIS_ADAPTER.
    # uvicorn, anyio, pydantic and websockets are covered by bundled hooks.
    hiddenimports=[
        "adapters.fake",
        "adapters.xplane",
        "server.app",
        "server.deps",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Dev-only and heavyweight trees that nothing at run time imports. Keeping the
    # bundle small is the same reason core/ uses geographiclib over pyproj.
    excludes=[
        "IPython",
        "PIL",
        "matplotlib",
        "mypy",
        "numpy",
        "pytest",
        "tkinter",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="instructor-station",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
