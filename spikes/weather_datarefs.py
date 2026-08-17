"""X-Plane weather dataref spike: pin the manual-mode enum value and the two
gust/turbulence-scale unknowns (docs/designs/weather-manager.md §7.1, §7.2,
§10.1, §11.1-§11.3).

Three separate, genuinely unverified facts block flipping
``XPlaneSimAdapter._CAPABILITIES.can_set_weather`` to ``True`` (§7.3 — the
flag only flips in the PR that pins them and passes the §5.3 contract cases
under ``-m sim``), and this script exists to pin all three in one session:

1. **The manual-mode enum value(s)** for ``sim/weather/region/weather_source``
   — §11.1, the one blocking unknown. Neither the value that means "manually
   set" nor whether the Web API even accepts a write to this dataref is
   pinned anywhere in this repository yet. Verified **operationally**, not by
   reading documentation that does not exist for this build: for each
   candidate ``weather_source`` value, this script writes the candidate mode,
   writes a distinctive visibility, and watches it for up to
   ``--hold-s`` seconds (default 120, matching §11.5's assumption that real
   weather rewrites within its ~60 s update interval). If the value survives
   the whole window, the sim's own real-weather engine has stopped
   overwriting manual values — the only definition of "manual mode" that
   actually matters to :meth:`XPlaneSimAdapter.set_weather`.
2. **Whether gusts ride the shear pair** (``shear_speed_msc``/
   ``shear_direction_degt``) or a dedicated dataref this adapter does not
   know about yet — §11.2, on the strength of X-Plane 11's lineage only.
3. **The turbulence dataref's scale** — 0-1 or 0-10 — §11.3; community
   sources disagree.

Steps 2 and 3 need a live UI action this script cannot perform for you: it
pauses and asks you to set a gust and maximum turbulence in X-Plane's own
weather editor (the map's weather layer, or Settings -> Weather) before it
reads the region arrays back. There is no candidate write to try blind for
either.

Run it with X-Plane loaded into a flight, its weather still in the default
REAL WEATHER mode, so step 1 has something to override::

    python spikes/weather_datarefs.py [--host localhost] [--port 8086] [--hold-s 120]

This script does not implement §7.2's field writes and does not exercise
:meth:`XPlaneSimAdapter.set_weather`/``get_weather`` at all — it only pins the
unknowns that block trusting them. Once run, its findings belong in
``docs/designs/weather-manager.md`` §7.1's table and in
``adapters/xplane/xplane_adapter.py``'s ``_WEATHER_SOURCE_MANUAL_UNVERIFIED``,
``_TURBULENCE_SCALE_UNVERIFIED`` and the shear-based gust mapping (rename the
"UNVERIFIED" constants and comments once confirmed, or correct them) — not
here.

Exit codes: ``0`` a manual-mode candidate held for the full window, ``1``
X-Plane not reachable or missing the region weather datarefs entirely
(they are OPTIONAL on this adapter — see ``adapters/xplane/xplane_adapter.py``'s
``OPTIONAL_DATAREFS``), ``2`` no candidate held.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.xplane import XPlaneSimAdapter
from adapters.xplane.xplane_adapter import XPlaneNotReachable

#: sim/weather/region/weather_source candidates to try, in order. Not sourced
#: from anywhere authoritative — plausible small integers for an enum with an
#: unknown range, tried cheaply before giving up. Extend this list rather than
#: guessing harder if none of them hold.
WEATHER_SOURCE_CANDIDATES = (0, 1, 2, 3)

#: sim/weather/region/change_mode candidate for "static" (§7.1's table states
#: 3 with a "verify value in spike" note). Only one candidate: the design
#: already names it, this script confirms rather than searches.
WEATHER_CHANGE_MODE_STATIC_CANDIDATE = 3

#: A visibility value implausible enough that seeing anything else back means
#: "something (real weather or a rejected write) touched this", not float
#: noise. Chosen far from both a typical CAVOK day (10+ SM) and a typical IFR
#: day (a fraction of an SM).
DISTINCTIVE_VISIBILITY_SM = 4.321

#: How often to poll while holding, in seconds.
POLL_INTERVAL_S = 5.0

REQUIRED_WEATHER_KEYS = (
    "weather_source",
    "weather_change_mode",
    "weather_update_immediately",
    "weather_visibility_sm",
    "wind_shear_speed_msc",
    "wind_shear_direction_degt",
    "wind_direction_degt",
    "wind_speed_msc",
    "weather_turbulence",
)


def rule(title: str) -> None:
    """Print a section header."""
    print(f"\n--- {title} " + "-" * max(0, 58 - len(title)))


def pause_for(instruction: str) -> None:
    """Block on Enter, printing what the user needs to do first."""
    print(f"\n  ACTION NEEDED: {instruction}")
    input("  Press Enter once done... ")


async def find_manual_mode(adapter: XPlaneSimAdapter, hold_s: float) -> int | None:
    """Try each candidate ``weather_source`` value; return the one that holds, or None.

    Operational definition of "manual" (module docstring, point 1): the
    candidate is written, a distinctive visibility is written after it, and
    the visibility is polled for ``hold_s`` seconds. A real-weather engine
    that is still active overwrites it well inside that window; a genuinely
    manual mode does not touch it at all.
    """
    original_source = await adapter.read_dataref("weather_source")
    original_visibility = await adapter.read_dataref("weather_visibility_sm")
    print(f"  starting weather_source = {original_source!r}")
    print(f"  starting visibility_sm  = {original_visibility!r}")

    for candidate in WEATHER_SOURCE_CANDIDATES:
        rule(f"CANDIDATE weather_source = {candidate}")
        await adapter.write_dataref("weather_update_immediately", 1)
        await adapter.write_dataref("weather_change_mode", WEATHER_CHANGE_MODE_STATIC_CANDIDATE)
        await adapter.write_dataref("weather_source", candidate)
        await asyncio.sleep(1.0)

        read_back = await adapter.read_dataref("weather_source")
        print(f"  weather_source read back: {read_back!r}")
        if int(read_back) != candidate:
            print("  the write did not stick at all -- not this candidate's value")
            continue

        await adapter.write_dataref("weather_visibility_sm", DISTINCTIVE_VISIBILITY_SM)
        print(f"  wrote a distinctive visibility_sm = {DISTINCTIVE_VISIBILITY_SM}")

        held = True
        deadline = time.monotonic() + hold_s
        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_INTERVAL_S)
            current = float(await adapter.read_dataref("weather_visibility_sm"))
            elapsed = hold_s - (deadline - time.monotonic())
            print(f"    t+{elapsed:5.1f}s  visibility_sm = {current:.3f}")
            if abs(current - DISTINCTIVE_VISIBILITY_SM) > 0.01:
                print("    CHANGED -- something is still overwriting manual values")
                held = False
                break

        if held:
            print(f"\n  HELD for the full {hold_s:.0f}s window.")
            print(f"  weather_source={candidate} is manual on this build.")
            return candidate

    print("\n  no candidate held. Restoring the original weather_source.")
    await adapter.write_dataref("weather_source", original_source)
    return None


async def probe_gust_and_turbulence(adapter: XPlaneSimAdapter) -> None:
    """Read the shear pair and the turbulence array after a live UI action (§11.2, §11.3)."""
    rule("GUST MAPPING (§11.2)")
    pause_for(
        "In X-Plane's own weather editor, set a SURFACE wind with a gust "
        "(e.g. 20 kt gusting 35) at the CURRENT layer, then come back here."
    )
    shear_speed = await adapter.read_dataref("wind_shear_speed_msc")
    shear_direction = await adapter.read_dataref("wind_shear_direction_degt")
    wind_speed = await adapter.read_dataref("wind_speed_msc")
    wind_direction = await adapter.read_dataref("wind_direction_degt")
    print(f"  wind_speed_msc         = {wind_speed!r}")
    print(f"  wind_direction_degt    = {wind_direction!r}")
    print(f"  shear_speed_msc        = {shear_speed!r}")
    print(f"  shear_direction_degt   = {shear_direction!r}")
    print(
        "\n  If shear_speed_msc rose above 0 and roughly matches the gust you set,\n"
        "  §7.2's mapping onto the shear pair is confirmed. If it stayed at 0,\n"
        "  the gust is modelled somewhere else -- search the dataref index for\n"
        "  'gust' via the xplane-datarefs MCP tool."
    )

    rule("TURBULENCE SCALE (§11.3)")
    pause_for("Slide the CURRENT layer's turbulence to MAXIMUM in X-Plane's weather editor.")
    turbulence = await adapter.read_dataref("weather_turbulence")
    print(f"  turbulence = {turbulence!r}")
    print(
        "\n  If this reads ~1.0, the dataref's scale is 0-1 (no rescale needed).\n"
        "  If it reads ~10.0, it is 0-10 and _TURBULENCE_SCALE_UNVERIFIED must\n"
        "  become 10.0 in adapters/xplane/xplane_adapter.py."
    )


async def run(host: str, port: int, hold_s: float) -> int:
    """Run the spike. Returns the process exit code."""
    adapter = XPlaneSimAdapter(host=host, port=port)

    rule("CONNECT")
    try:
        await adapter.connect()
    except XPlaneNotReachable as exc:
        print(f"  FAILED: {exc}\n")
        print("  Checklist:")
        print("    * X-Plane 12.1 or newer is running and loaded into a flight")
        print("    * Settings > Network: the web server / Web API is enabled")
        return 1
    print(f"  connected to {adapter.base_url}")

    try:
        rule("WEATHER DATAREF AVAILABILITY")
        # Reaching into the private dataref index is deliberate here (the same
        # thing the test suite does directly, e.g. test_xplane_setup_mapping.py):
        # this is a diagnostic script, and there is no public "is this dataref
        # available" query on the adapter.
        missing = [key for key in REQUIRED_WEATHER_KEYS if key not in adapter._ids]
        if missing:
            print(f"  MISSING on this build: {', '.join(missing)}")
            print(
                "  These are declared OPTIONAL on this adapter precisely for this case --\n"
                "  weather control cannot proceed here. Nothing else in this script can run."
            )
            return 1
        print("  all required region weather datarefs are present in the dataref index.")

        rule("MANUAL WEATHER MODE (§7.1, §11.1)")
        print(
            f"  This section writes to your simulator's weather for up to {hold_s:.0f}s per\n"
            "  candidate. Make sure real weather is enabled and there is nothing else\n"
            "  depending on the current weather right now."
        )
        manual_value = await find_manual_mode(adapter, hold_s)

        await probe_gust_and_turbulence(adapter)

        rule("VERDICT")
        if manual_value is None:
            print("  No candidate weather_source value made manual weather hold.")
            print("  Fallback per §11.1: check whether ANY region write (e.g. visibility)")
            print("  flips the sim to manual by itself on this build, by watching")
            print("  weather_source's own value across a plain field write.")
            return 2
        print(f"  weather_source = {manual_value} is confirmed MANUAL on this build.")
        print("  Write this into docs/designs/weather-manager.md §7.1's table and into")
        print("  _WEATHER_SOURCE_MANUAL_UNVERIFIED in adapters/xplane/xplane_adapter.py")
        print("  (rename it once confirmed -- drop the _UNVERIFIED suffix).")
        return 0
    finally:
        await adapter.disconnect()


def main() -> int:
    """Parse arguments and run the spike."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8086)
    parser.add_argument(
        "--hold-s",
        type=float,
        default=120.0,
        help="Seconds to watch a candidate manual mode before declaring it holds (§11.5).",
    )
    args = parser.parse_args()
    return asyncio.run(run(args.host, args.port, args.hold_s))


if __name__ == "__main__":
    raise SystemExit(main())
