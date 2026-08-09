"""Drive the X-Plane 12 *process*: start it somewhere specific, then shut it down.

The instructor station is external and never launches the simulator — that hard
rule is about the application. This is developer tooling: it exists so a live-sim
test run can be automated end to end without leaving a 300 W simulator burning on
the desk afterwards. Nothing here is imported by the app, and nothing here runs in
CI.

Everything below was measured against the X-Plane 12 installed on this machine,
because the folklore about all of it is wrong:

* **There is no ``--load_acf`` or ``--load_apt``.** ``X-Plane.exe --help`` prints
  the complete flag list and neither is in it. What exists and is useful here:
  ``--window=WxH``, ``--no_sound``, ``--no_joysticks``, ``--pref:``, ``--dref:``.
* **Left alone, X-Plane never starts flying.** It boots to the Quick Flight
  Loader screen and waits for a human. Measured: nine minutes after launch the
  Web API was answering HTTP 200 with an **empty** dataref index, because no
  flight existed to have datarefs about. ``_show_qfl_on_start 0`` in
  ``Output/preferences/X-Plane.prf`` is what fixes it — with that set, the sim
  boots straight into a flight and is ready in about a minute.
* **The boot position lives in ``Output/preferences/Freeflight.prf``**, under
  ``_last_start``, as one line of JSON. The accepted shapes come from the
  simulator's own parser error strings::

      {"runway_start": {"airport_id": "LEMD", "runway": "32L",
                        "final_distance_in_nautical_miles": 10.0}}
      {"ramp_start":   {"airport_id": "LEMD", "ramp": "<stand name>"}}
      {"lle_ground_start": {"latitude": .., "longitude": .., "heading_true": ..}}

* **Only the airport in that payload can be trusted.** Asking for LEBL 24R put
  the aircraft at LEBL on runway 02; asking for LEMD 18R put it at LEMD on the
  previous session's spot. So the boot position is used for what it is reliable
  at — loading the right corner of the world — and the exact runway or stand is
  set afterwards by ``place``, through the adapter's validated placement path.
  That also keeps the teleport short: no world-crossing hop, no scenery reload.

Choosing a boot position means **writing to the user's preferences**. Every file
is backed up first, to ``<name>.ois-backup`` beside the original; ``quit``
restores automatically and ``restore-prefs`` does it on demand. If a run dies
without restoring, the backup is still there and the next ``launch`` will not
overwrite it.

Usage (with the project's virtualenv)::

    python spikes/sim_lifecycle.py status
    python spikes/sim_lifecycle.py list --apt LEMD
    python spikes/sim_lifecycle.py launch --apt LEMD --rwy 32L
    python spikes/sim_lifecycle.py wait-ready --near-apt LEMD
    python spikes/sim_lifecycle.py place --apt LEMD --rwy 32L
    python spikes/sim_lifecycle.py quit

Exit codes are per subcommand and documented on each one; ``0`` always means the
thing asked for happened.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.xplane import XPlaneSimAdapter
from adapters.xplane.xplane_adapter import XPlaneNotReachable, XPlaneRepositionFailed
from core.geodesy import (
    METRES_PER_NAUTICAL_MILE,
    Placement,
    coordinate_placement,
    distance_and_bearing,
)
from core.models import GeoPosition
from core.navdata.sources import (
    APT_DAT_RELATIVE,
    discover_xplane_root,
)

#: The executable, relative to the installation root.
EXECUTABLE_RELATIVE = Path("X-Plane.exe")

#: The preferences file holding the start position.
FREEFLIGHT_RELATIVE = Path("Output/preferences/Freeflight.prf")

#: The main preferences file, which decides whether the menu blocks the boot.
XPLANE_PREFS_RELATIVE = Path("Output/preferences/X-Plane.prf")

#: Where the untouched preferences are parked while we own them.
BACKUP_SUFFIX = ".ois-backup"

#: The image name `tasklist` and `taskkill` know X-Plane by.
PROCESS_IMAGE = "X-Plane.exe"

#: The stock C172 — small, quick to load, and what the project validates against.
DEFAULT_AIRCRAFT = "Aircraft/Laminar Research/Cessna 172 SP/Cessna_172SP.acf"
DEFAULT_AIRPORT = "LEMD"

#: A cold start loads scenery, so readiness is minutes away, not seconds.
DEFAULT_READY_TIMEOUT_S = 600.0
DEFAULT_READY_INTERVAL_S = 10.0

#: How long the sim gets to honour `sim/operation/quit` before it is killed.
DEFAULT_GRACE_S = 60.0
DEFAULT_KILL_WAIT_S = 15.0

#: How far from the requested airport the aircraft may be and still count as
#: "started where we asked". Generous: it only has to separate *this* airport
#: from wherever the previous session left the aircraft.
DEFAULT_NEAR_RADIUS_NM = 10.0

_LATITUDE_DATAREF = "sim/flightmodel/position/latitude"
_LONGITUDE_DATAREF = "sim/flightmodel/position/longitude"
_QUIT_COMMAND = "sim/operation/quit"

_HTTP_TIMEOUT_S = 5.0
_PROCESS_POLL_S = 1.0


class LifecycleError(RuntimeError):
    """Something the caller has to fix: no install, no airport, a bad stand name."""


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


def resolve_root(configured: str | None) -> Path:
    """Find the X-Plane installation, or explain why we cannot."""
    root = discover_xplane_root(Path(configured) if configured else None)
    if root is None:
        raise LifecycleError(
            f"No X-Plane 12 installation found (configured: {configured or 'auto'}). "
            "Check %LOCALAPPDATA%\\x-plane_install_12.txt or pass --root."
        )
    if not (root / EXECUTABLE_RELATIVE).is_file():
        raise LifecycleError(f"{root} has no {EXECUTABLE_RELATIVE} — not a runnable install.")
    return root


def base_url() -> str:
    """The Web API base URL, honouring the same environment as the server."""
    host = os.environ.get("OIS_XPLANE_HOST", "localhost")
    port = os.environ.get("OIS_XPLANE_PORT", "8086")
    return f"http://{host}:{port}"


# ---------------------------------------------------------------------------
# The process
# ---------------------------------------------------------------------------


def is_running() -> bool:
    """True when an X-Plane process exists.

    ``tasklist`` rather than psutil: it is already on every Windows box and this
    script must not add a dependency to the project for a spike.
    """
    if os.name != "nt":
        return (
            subprocess.run(["pgrep", "-f", "X-Plane"], capture_output=True, check=False).returncode
            == 0
        )
    result = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {PROCESS_IMAGE}", "/NH"],
        capture_output=True,
        text=True,
        check=False,
    )
    return PROCESS_IMAGE.lower() in result.stdout.lower()


def kill_process() -> None:
    """Force the process down. The fallback when a polite quit is ignored."""
    if os.name != "nt":
        subprocess.run(["pkill", "-f", "X-Plane"], capture_output=True, check=False)
        return
    subprocess.run(["taskkill", "/IM", PROCESS_IMAGE, "/F"], capture_output=True, check=False)


def wait_process_gone(timeout_s: float) -> bool:
    """Poll until no X-Plane process is left, or the timeout expires."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not is_running():
            return True
        time.sleep(_PROCESS_POLL_S)
    return not is_running()


# ---------------------------------------------------------------------------
# The Web API
# ---------------------------------------------------------------------------


def api_is_up(url: str) -> bool:
    """True when the Web API answers. Says nothing about a flight being loaded."""
    try:
        response = httpx.get(f"{url}/api/v2/datarefs", timeout=_HTTP_TIMEOUT_S)
    except httpx.HTTPError:
        return False
    return response.status_code == httpx.codes.OK


def resolve_dataref_ids(url: str, names: tuple[str, ...]) -> dict[str, int]:
    """Map dataref paths to their numeric ids.

    The whole index is fetched and filtered here, the way the adapter does it:
    ``filter[name]`` is documented for commands, and relying on it for datarefs
    would make readiness detection depend on an endpoint detail we have not
    verified on every 12.x build.
    """
    response = httpx.get(f"{url}/api/v2/datarefs", timeout=_HTTP_TIMEOUT_S)
    response.raise_for_status()
    payload: Any = response.json()
    wanted = set(names)
    found: dict[str, int] = {}
    for entry in payload.get("data", []):
        name = entry.get("name")
        if name in wanted:
            found[str(name)] = int(entry["id"])
    return found


def read_dataref(url: str, dataref_id: int) -> float | None:
    """Read one dataref value, or ``None`` when it cannot be read right now."""
    try:
        response = httpx.get(f"{url}/api/v2/datarefs/{dataref_id}/value", timeout=_HTTP_TIMEOUT_S)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    payload: Any = response.json()
    value = payload.get("data")
    if not isinstance(value, (int, float)):
        return None
    return float(value)


def read_position(url: str, ids: dict[str, int]) -> GeoPosition | None:
    """Read latitude/longitude, or ``None`` if they are absent or implausible.

    The Web API answers with HTTP 200 while X-Plane is still on the main menu,
    so "the API is up" is not "a flight is loaded". A position that is inside
    the coordinate ranges and not the null island is the cheap honest test.
    """
    latitude_id = ids.get(_LATITUDE_DATAREF)
    longitude_id = ids.get(_LONGITUDE_DATAREF)
    if latitude_id is None or longitude_id is None:
        return None
    latitude = read_dataref(url, latitude_id)
    longitude = read_dataref(url, longitude_id)
    if latitude is None or longitude is None:
        return None
    if abs(latitude) > 90.0 or abs(longitude) > 180.0:
        return None
    if abs(latitude) < 0.001 and abs(longitude) < 0.001:
        return None
    return GeoPosition(latitude=latitude, longitude=longitude)


def request_quit(url: str) -> bool:
    """Ask X-Plane to quit the way a user would. True when the command fired.

    Command activation over the Web API arrived in X-Plane 12.1.4. On anything
    older this returns False and the caller falls back to killing the process.
    """
    try:
        listing = httpx.get(
            f"{url}/api/v2/commands",
            params={"filter[name]": _QUIT_COMMAND},
            timeout=_HTTP_TIMEOUT_S,
        )
        listing.raise_for_status()
        payload: Any = listing.json()
        entries = payload.get("data", [])
        if not entries:
            return False
        command_id = int(entries[0]["id"])
        activation = httpx.post(
            f"{url}/api/v2/command/{command_id}/activate",
            json={"duration": 0},
            timeout=_HTTP_TIMEOUT_S,
        )
        activation.raise_for_status()
    except (httpx.HTTPError, KeyError, ValueError):
        return False
    return True


# ---------------------------------------------------------------------------
# apt.dat: enough of it to put an aeroplane on a runway or a stand
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Spot:
    """One place an aircraft can be put down, in true degrees."""

    name: str
    position: GeoPosition
    heading_true_deg: float


@dataclass(frozen=True)
class AirportLayout:
    """The subset of one airport's apt.dat entry this script needs."""

    icao: str
    name: str
    elevation_ft: float
    runways: dict[str, Spot]
    stands: dict[str, Spot]

    @property
    def reference(self) -> GeoPosition | None:
        """Any point on the field, for "did we start at the right airport?"."""
        for spot in (*self.runways.values(), *self.stands.values()):
            return spot.position
        return None


def read_airport_layout(root: Path, icao: str) -> AirportLayout:
    """Scan apt.dat for one airport: its runway thresholds and its stands.

    A deliberately small, throwaway reader. The real indexer belongs in
    ``core/navdata/xplane_native`` and is being written separately; when it
    lands this function is deleted and ``NavdataProvider.get_runway`` /
    ``get_parking`` answer instead. Until then this is what turns "runway 32L"
    into a coordinate, and it is scoped to exactly that.

    Row codes read: ``1`` (header, carries the field elevation), ``100``
    (runway — both ends, each with its own threshold), ``1300`` (startup
    location: position and *true* heading).

    Runway headings are computed from one threshold to the other rather than
    taken from the ident: ``32L`` is a magnetic name rounded to ten degrees, and
    the simulator wants true degrees to a fraction of one.
    """
    icao = icao.strip().upper()
    apt_dat = root / APT_DAT_RELATIVE
    if not apt_dat.is_file():
        raise LifecycleError(f"No apt.dat at {apt_dat}.")

    name = ""
    elevation_ft = 0.0
    runways: dict[str, Spot] = {}
    stands: dict[str, Spot] = {}
    inside = False

    with apt_dat.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            fields = line.split()
            if not fields:
                continue
            code = fields[0]
            if code in {"1", "16", "17"}:
                # A new airport header ends the one we were reading.
                if inside:
                    break
                inside = len(fields) >= 5 and fields[4].upper() == icao
                if inside:
                    name = " ".join(fields[5:])
                    elevation_ft = _safe_float(fields[1], 0.0)
                continue
            if not inside:
                continue
            if code == "100" and len(fields) >= 20:
                _collect_runway(fields, runways)
            elif code == "1300" and len(fields) >= 7:
                stand = _safe_position(fields[1], fields[2])
                if stand is not None:
                    label = " ".join(fields[6:])
                    stands[label] = Spot(
                        name=label,
                        position=stand,
                        heading_true_deg=_safe_float(fields[3], 0.0) % 360.0,
                    )

    if not inside:
        raise LifecycleError(f"Airport {icao} is not in {apt_dat}.")
    return AirportLayout(
        icao=icao,
        name=name,
        elevation_ft=elevation_ft,
        runways=runways,
        stands=stands,
    )


def _collect_runway(fields: list[str], runways: dict[str, Spot]) -> None:
    """Add both ends of one row-100 runway, each pointing down the pavement."""
    near = _safe_position(fields[9], fields[10])
    far = _safe_position(fields[18], fields[19])
    if near is None or far is None:
        return
    _, bearing = distance_and_bearing(near, far)
    runways[fields[8].upper()] = Spot(
        name=fields[8].upper(), position=near, heading_true_deg=bearing
    )
    runways[fields[17].upper()] = Spot(
        name=fields[17].upper(), position=far, heading_true_deg=(bearing + 180.0) % 360.0
    )


def _safe_position(latitude: str, longitude: str) -> GeoPosition | None:
    try:
        return GeoPosition(latitude=float(latitude), longitude=float(longitude))
    except ValueError:
        return None


def _safe_float(value: str, fallback: float) -> float:
    try:
        return float(value)
    except ValueError:
        return fallback


# ---------------------------------------------------------------------------
# Preferences: choosing where the flight starts
# ---------------------------------------------------------------------------


def _split_lines(text: str) -> tuple[list[str], str]:
    separator = "\r\n" if "\r\n" in text else "\n"
    return text.split(separator), separator


def _set_key(lines: list[str], key: str, value: str) -> None:
    """Replace the ``<key> <value>`` line, appending it when it is absent."""
    replacement = f"{key} {value}"
    for position, line in enumerate(lines):
        if line.split(" ", 1)[0] == key:
            lines[position] = replacement
            return
    lines.append(replacement)


def _set_prefixed_key(lines: list[str], key: str, subject: str, value: str) -> None:
    """Replace a ``P <key> <subject> <value>`` line, appending when absent."""
    replacement = f"P {key} {subject} {value}"
    for position, line in enumerate(lines):
        fields = line.split()
        if len(fields) >= 3 and fields[0] == "P" and fields[1] == key and fields[2] == subject:
            lines[position] = replacement
            return
    lines.append(replacement)


def backup_path(preferences: Path) -> Path:
    """Where one untouched preferences file is parked while we own it."""
    return preferences.with_name(preferences.name + BACKUP_SUFFIX)


def _edit_preferences(path: Path, edit: Callable[[list[str]], None]) -> None:
    """Apply ``edit`` to a preferences file, backing the original up first.

    The backup is taken only when there is not one already: a previous run that
    died before restoring left the *pristine* copy there, and replacing it with
    our own edit would lose the user's settings for good.
    """
    if not path.is_file():
        raise LifecycleError(f"No preferences file at {path}; start X-Plane once by hand first.")

    original = path.read_text(encoding="utf-8", errors="surrogateescape")
    backup = backup_path(path)
    if not backup.exists():
        backup.write_text(original, encoding="utf-8", errors="surrogateescape")

    lines, separator = _split_lines(original)
    edit(lines)
    path.write_text(separator.join(lines), encoding="utf-8", errors="surrogateescape")


def write_start_position(
    root: Path,
    start: dict[str, Any],
    *,
    airport: str,
    is_runway: bool,
    aircraft: str | None,
) -> None:
    """Set the boot-time flight: which airport, and no menu in the way.

    Two files, because X-Plane splits the job:

    * ``Freeflight.prf`` holds ``_last_start``, which decides the **airport**.
      Do not trust it for more than that — see :func:`command_place`.
    * ``X-Plane.prf`` holds ``_show_qfl_on_start``. Leave it at ``1`` and the
      simulator parks on the Quick Flight Loader screen waiting for a human to
      click, forever: measured, nine minutes in, the Web API was answering with
      an **empty** dataref index because no flight existed. Set to ``0`` it boots
      straight into the flight and is ready in about a minute.
    """
    _edit_preferences(
        root / FREEFLIGHT_RELATIVE,
        lambda lines: _write_freeflight(
            lines, start, airport=airport, is_runway=is_runway, aircraft=aircraft
        ),
    )
    _edit_preferences(
        root / XPLANE_PREFS_RELATIVE,
        lambda lines: _set_key(lines, "_show_qfl_on_start", "0"),
    )


def _write_freeflight(
    lines: list[str],
    start: dict[str, Any],
    *,
    airport: str,
    is_runway: bool,
    aircraft: str | None,
) -> None:
    _set_key(lines, "_last_start", json.dumps(start, separators=(",", ":")))
    _set_key(lines, "_airport", airport)
    _set_prefixed_key(lines, "_start_is_rwy", airport, "1" if is_runway else "0")
    _set_key(lines, "_default_to_ramps", "0" if is_runway else "1")
    if aircraft is not None:
        _set_key(lines, "_aircraft", aircraft)


def restore_preferences(root: Path) -> bool:
    """Put every preferences file we touched back. True if anything was restored."""
    restored = False
    for relative in (FREEFLIGHT_RELATIVE, XPLANE_PREFS_RELATIVE):
        preferences = root / relative
        backup = backup_path(preferences)
        if not backup.is_file():
            continue
        preferences.write_text(
            backup.read_text(encoding="utf-8", errors="surrogateescape"),
            encoding="utf-8",
            errors="surrogateescape",
        )
        backup.unlink()
        restored = True
    return restored


def resolve_spot(layout: AirportLayout, runway: str | None, stand: str | None) -> Spot | None:
    """Find the requested runway threshold or stand, or ``None`` if none was asked for.

    Raises with the list of valid names when the name does not exist — a wrong
    stand name should cost a second, not a five-minute launch.
    """
    if runway is not None and stand is not None:
        raise LifecycleError("Give --rwy or --stand, not both.")

    if stand is not None:
        found = layout.stands.get(stand)
        if found is None:
            raise LifecycleError(
                f"{layout.icao} has no stand named {stand!r}.\n"
                f"Available: {', '.join(sorted(layout.stands))}"
            )
        return found

    if runway is not None:
        ident = runway.upper().removeprefix("RW")
        found = layout.runways.get(ident)
        if found is None:
            raise LifecycleError(
                f"{layout.icao} has no runway {ident}.\n"
                f"Available: {', '.join(sorted(layout.runways))}"
            )
        return found

    return None


def build_start(layout: AirportLayout, spot: Spot | None) -> tuple[dict[str, Any], str]:
    """Build the ``_last_start`` payload and a one-line description of it.

    Only the **airport** in this payload can be relied upon; the runway is a
    hint. Measured on X-Plane 12: asking for LEBL 24R put the aircraft at LEBL,
    on runway 02. Asking for LEMD 18R put it at LEMD, on the previous session's
    spot. The airport is what matters here — it loads the right scenery, so the
    placement that follows is a short hop rather than a world-crossing teleport
    with a scenery reload in the middle.
    """
    if spot is not None and spot.name in layout.stands:
        return (
            {"ramp_start": {"airport_id": layout.icao, "ramp": spot.name}},
            f"{layout.icao} stand {spot.name}",
        )
    runway = spot.name if spot is not None else _default_runway(layout)
    return (
        {"runway_start": {"airport_id": layout.icao, "runway": runway}},
        f"{layout.icao} runway {runway}",
    )


def _default_runway(layout: AirportLayout) -> str:
    """Any runway at the field, for when the caller only named an airport."""
    for ident in layout.runways:
        return ident
    raise LifecycleError(f"{layout.icao} has no runways in apt.dat; pass --stand.")


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def command_status(args: argparse.Namespace) -> int:
    """Print one of ``not-running`` / ``menu`` / ``ready`` on the first line.

    Always exits ``0``: the answer is the word, not the exit code. Three states
    do not map onto success-or-failure, and a caller that branches on an exit
    code here would eventually read "the sim is at the menu" as "the command
    broke".
    """
    url = base_url()
    running = is_running()
    if not running and not api_is_up(url):
        print("not-running")
        return 0
    try:
        ids = resolve_dataref_ids(url, (_LATITUDE_DATAREF, _LONGITUDE_DATAREF))
    except httpx.HTTPError:
        ids = {}
    position = read_position(url, ids) if ids else None
    if position is None:
        print("menu")
        print("  the process is up but no flight is loaded yet", file=sys.stderr)
        return 0
    print("ready")
    print(f"  aircraft at {position.latitude:.6f}, {position.longitude:.6f}")
    return 0


def command_list(args: argparse.Namespace) -> int:
    """Print the runways and stands of one airport. Exit ``0``, or ``2`` if unknown."""
    root = resolve_root(args.root)
    layout = read_airport_layout(root, args.apt)
    print(f"{layout.icao} {layout.name}".rstrip())
    print(f"  elevation: {layout.elevation_ft:.0f} ft")
    print(f"  runways ({len(layout.runways)}): {', '.join(sorted(layout.runways))}")
    print(f"  stands ({len(layout.stands)}):")
    for stand in sorted(layout.stands):
        print(f"    {stand}")
    return 0


def command_launch(args: argparse.Namespace) -> int:
    """Start X-Plane at the requested airport.

    Exit codes: ``0`` launched, ``2`` the airport or spot does not exist,
    ``3`` X-Plane is already running (nothing was touched).
    """
    root = resolve_root(args.root)
    if is_running():
        print("already-running")
        print("  refusing to launch a second instance", file=sys.stderr)
        return 3

    layout = read_airport_layout(root, args.apt)
    spot = resolve_spot(layout, args.rwy, args.stand)
    start, described = build_start(layout, spot)
    write_start_position(
        root,
        start,
        airport=layout.icao,
        is_runway="runway_start" in start,
        aircraft=args.acf,
    )

    command = [str(root / EXECUTABLE_RELATIVE)]
    if args.window:
        command.append(f"--window={args.window}")
    if args.no_sound:
        command.append("--no_sound")
    if args.no_joysticks:
        command.append("--no_joysticks")

    creation_flags = 0
    if os.name == "nt":
        creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        command,
        cwd=str(root),
        creationflags=creation_flags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    print("launched")
    print(f"  booting at: {described}")
    if spot is not None:
        print("  run `place` once ready to put the aircraft on the exact spot")
    print("  preferences backed up; `quit` or `restore-prefs` puts them back")
    return 0


def command_place(args: argparse.Namespace) -> int:
    """Put the aircraft on an exact runway threshold or stand, sim already running.

    This is the step that actually honours ``--rwy``/``--stand``. X-Plane's own
    boot-time start position gets the *airport* right and then does as it
    pleases with the rest, so the exact spot is set the way the rest of this
    project sets one: freeze, write the local frame, release — the adapter's
    validated placement path.

    Exit codes: ``0`` placed, ``1`` the simulator is not reachable,
    ``2`` the airport/runway/stand does not exist, ``3`` the aircraft did not
    arrive.
    """
    root = resolve_root(args.root)
    layout = read_airport_layout(root, args.apt)
    spot = resolve_spot(layout, args.rwy, args.stand)
    if spot is None:
        raise LifecycleError("Nothing to place: pass --rwy or --stand.")

    target = GeoPosition(
        latitude=spot.position.latitude,
        longitude=spot.position.longitude,
        altitude_ft=layout.elevation_ft,
    )
    placement = coordinate_placement(target, spot.heading_true_deg)
    return asyncio.run(_place(placement, layout.icao, spot))


async def _place(placement: Placement, icao: str, spot: Spot) -> int:
    """Apply one ground placement through the adapter, then read it back."""
    adapter = XPlaneSimAdapter(
        host=os.environ.get("OIS_XPLANE_HOST", "localhost"),
        port=int(os.environ.get("OIS_XPLANE_PORT", "8086")),
    )
    try:
        await adapter.connect()
    except XPlaneNotReachable as exc:
        print("unreachable")
        print(f"  {exc}", file=sys.stderr)
        return 1

    try:
        # Speed first, position second: the placement carries 0 kt for a spot on
        # the ground, and set_position flies the aircraft away on whatever speed
        # it finds if that is not zeroed first.
        await adapter.apply_setup(placement.to_setup())
        await adapter.set_position(placement.position, heading_deg=placement.heading_deg)
    except XPlaneRepositionFailed as exc:
        print("failed")
        print(f"  {exc}", file=sys.stderr)
        return 3
    finally:
        state = None
        with contextlib.suppress(Exception):
            state = await adapter.get_aircraft_state()
        await adapter.disconnect()

    print("placed")
    print(f"  {icao} {spot.name} at {spot.position.latitude:.6f}, {spot.position.longitude:.6f}")
    print(f"  commanded heading {placement.heading_deg:.1f} true")
    if state is not None:
        error_m = (
            distance_and_bearing(
                spot.position,
                GeoPosition(latitude=state.latitude, longitude=state.longitude),
            )[0]
            * METRES_PER_NAUTICAL_MILE
        )
        print(f"  read back {error_m:.1f} m away, heading {state.heading_deg:.1f}")
    return 0


def command_wait_ready(args: argparse.Namespace) -> int:
    """Block until a flight is loaded. Exit ``0`` ready, ``1`` timed out."""
    url = base_url()
    deadline = time.monotonic() + args.timeout
    started = time.monotonic()
    ids: dict[str, int] = {}
    target: GeoPosition | None = None

    if args.near_apt:
        root = resolve_root(args.root)
        target = read_airport_layout(root, args.near_apt).reference

    while time.monotonic() < deadline:
        if not is_running():
            print("failed")
            print("  the X-Plane process exited before it became ready", file=sys.stderr)
            return 1
        if api_is_up(url):
            if not ids:
                try:
                    ids = resolve_dataref_ids(url, (_LATITUDE_DATAREF, _LONGITUDE_DATAREF))
                except httpx.HTTPError:
                    ids = {}
            position = read_position(url, ids) if ids else None
            if position is not None and _close_enough(position, target, args.radius_nm):
                elapsed = time.monotonic() - started
                print("ready")
                print(f"  took {elapsed:.0f} s")
                print(f"  aircraft at {position.latitude:.6f}, {position.longitude:.6f}")
                return 0
        time.sleep(args.interval)

    print("timeout")
    print(f"  no flight loaded after {args.timeout:.0f} s", file=sys.stderr)
    return 1


def _close_enough(position: GeoPosition, target: GeoPosition | None, radius_nm: float) -> bool:
    """True when no airport was requested, or the aircraft is at the one that was."""
    if target is None:
        return True
    distance_nm, _ = distance_and_bearing(target, position)
    return distance_nm <= radius_nm


def command_quit(args: argparse.Namespace) -> int:
    """Shut X-Plane down and restore the preferences. Exit ``1`` if it survives."""
    url = base_url()
    root: Path | None
    try:
        root = resolve_root(args.root)
    except LifecycleError:
        root = None

    if not is_running():
        print("not-running")
        if root is not None and restore_preferences(root):
            print("  preferences restored")
        return 0

    outcome = "forced"
    if request_quit(url) and wait_process_gone(args.grace):
        outcome = "graceful"
    else:
        kill_process()
        if not wait_process_gone(args.kill_wait):
            print("failed")
            print(
                f"  X-Plane is STILL running. Close it by hand: "
                f"Stop-Process -Name {PROCESS_IMAGE.removesuffix('.exe')} -Force",
                file=sys.stderr,
            )
            return 1

    print(outcome)
    if root is not None and restore_preferences(root):
        print("  preferences restored")
    return 0


def command_restore_prefs(args: argparse.Namespace) -> int:
    """Put the preferences back without touching the process. Always exit ``0``."""
    root = resolve_root(args.root)
    print("restored" if restore_preferences(root) else "nothing-to-restore")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Assemble the subcommand parser."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--root", default=None, help="X-Plane installation root (default: auto)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="not-running / menu / ready")
    status.set_defaults(handler=command_status)

    listing = subparsers.add_parser("list", help="list an airport's runways and stands")
    listing.add_argument("--apt", required=True)
    listing.set_defaults(handler=command_list)

    launch = subparsers.add_parser("launch", help="start X-Plane at a chosen airport")
    launch.add_argument("--apt", default=DEFAULT_AIRPORT)
    launch.add_argument("--rwy", default=None, help='runway end, e.g. "32L"')
    launch.add_argument("--stand", default=None, help="startup location name from apt.dat")
    launch.add_argument("--acf", default=DEFAULT_AIRCRAFT, help="aircraft path, relative to root")
    launch.add_argument("--window", default="1280x720", help='window size, or "" for full screen')
    launch.add_argument("--no-sound", dest="no_sound", action="store_true", default=True)
    launch.add_argument("--sound", dest="no_sound", action="store_false")
    launch.add_argument("--no-joysticks", dest="no_joysticks", action="store_true", default=False)
    launch.set_defaults(handler=command_launch)

    place = subparsers.add_parser("place", help="put the aircraft on an exact runway or stand")
    place.add_argument("--apt", required=True)
    place.add_argument("--rwy", default=None, help='runway end, e.g. "32L"')
    place.add_argument("--stand", default=None, help="startup location name from apt.dat")
    place.set_defaults(handler=command_place)

    wait = subparsers.add_parser("wait-ready", help="block until a flight is loaded")
    wait.add_argument("--timeout", type=float, default=DEFAULT_READY_TIMEOUT_S)
    wait.add_argument("--interval", type=float, default=DEFAULT_READY_INTERVAL_S)
    wait.add_argument("--near-apt", dest="near_apt", default=None)
    wait.add_argument("--radius-nm", dest="radius_nm", type=float, default=DEFAULT_NEAR_RADIUS_NM)
    wait.set_defaults(handler=command_wait_ready)

    quit_parser = subparsers.add_parser("quit", help="shut X-Plane down and restore preferences")
    quit_parser.add_argument("--grace", type=float, default=DEFAULT_GRACE_S)
    quit_parser.add_argument(
        "--kill-wait", dest="kill_wait", type=float, default=DEFAULT_KILL_WAIT_S
    )
    quit_parser.set_defaults(handler=command_quit)

    restore = subparsers.add_parser("restore-prefs", help="restore preferences only")
    restore.set_defaults(handler=command_restore_prefs)

    return parser


def main() -> int:
    """Parse arguments and dispatch."""
    args = build_parser().parse_args()
    handler: Any = args.handler
    try:
        return int(handler(args))
    except LifecycleError as exc:
        print("error", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
