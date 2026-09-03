"""Cockpit control catalog spike: pin the two open questions of
docs/designs/cockpit-control-catalog.md §10.3 and §10.4.

1. **§10.3** — is ``acf_relative_path`` exposed over the Web API as a
   readable string dataref on this build? The adapter already degrades
   honestly if not (``_read_acf_relative_path`` returns ``None``, and D7's
   change hook falls back to "re-probe the detection dataref on every
   cockpit call"), so this is a performance question, not a correctness
   one — this script settles it by reading it and printing the decoded
   value.
2. **§10.4, first half** — after swapping TO the Zibo, does a *fresh*
   ``GET /api/v2/datarefs`` (the unfiltered full index) list its
   ``laminar/*`` names? The design never depends on the answer (D5/D6 use
   per-name probes exclusively), but a "yes" would justify a one-request bulk
   pre-resolution later, if a catalog ever grows large enough for lazy
   first-use latency to be noticed.
3. **§10.4, second half** — does reloading the aircraft/a plugin re-register
   a dataref under a NEW numeric id without changing its name or the
   aircraft path? D7's second signal (a 404 on a previously-resolved id)
   exists for exactly this, whether or not it is ever observed for real; this
   script gives the operator a chance to trigger it and see whether the id
   for a known dataref changes.

Run against a live X-Plane 12.1+ with its Web API enabled, the Zibo Mod
B737-800X loaded::

    python spikes/cockpit_probe.py [--host localhost] [--port 8086]

This script performs raw HTTP calls alongside the typed adapter on purpose —
questions 2 and 3 need to see the Web API's own index and id assignment
directly, which the adapter does not expose (by design: application code
never needs it, only this kind of diagnostic does).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from adapters.xplane.cockpit_controls import COCKPIT_CATALOGS_DIR
from adapters.xplane.xplane_adapter import XPlaneNotReachable, XPlaneSimAdapter

#: The Zibo dataref this script checks for in the full index and re-resolves
#: after a reload — the same one adapters/xplane/cockpit_catalogs/zibo-b738/
#: aircraft.yaml uses for detection (read-back confirmed present/absent,
#: research §7).
ZIBO_PROBE_DATAREF = "laminar/B738/autopilot/mcp_alt_dial"


def rule(title: str) -> None:
    print(f"\n--- {title} " + "-" * max(0, 58 - len(title)))


def pause_for(instruction: str) -> None:
    print(f"\n  ACTION NEEDED: {instruction}")
    input("  Press Enter once done... ")


async def _lookup_raw(client: httpx.AsyncClient, name: str) -> int | None:
    """The same shape as ``cockpit_controls._lookup_id``, inlined so this
    script has no dependency on the adapter having connected yet."""
    response = await client.get("/api/v2/datarefs", params={"filter[name]": name})
    if response.status_code == 404:
        return None
    response.raise_for_status()
    for entry in response.json().get("data", []):
        if entry.get("name") == name:
            return int(entry["id"])
    return None


async def run(host: str, port: int) -> int:
    adapter = XPlaneSimAdapter(host=host, port=port)

    rule("CONNECT")
    try:
        await adapter.connect()
    except XPlaneNotReachable as exc:
        print(f"  FAILED: {exc}\n")
        print("  Checklist:")
        print("    * X-Plane 12.1 or newer is running and loaded into a flight")
        print("    * Settings > Network: the web server / Web API is enabled")
        print("    * the Zibo Mod B737-800X is the loaded aircraft")
        return 1
    print(f"  connected to {adapter.base_url}")
    print(f"  can_control_cockpit = {adapter.capabilities.can_control_cockpit}")
    print(f"  catalog root = {COCKPIT_CATALOGS_DIR}")

    try:
        rule("§10.3 -- acf_relative_path")
        path = await adapter._read_acf_relative_path()  # the diagnostic escape hatch
        if path is None:
            print("  acf_relative_path did NOT decode (missing, or not a byte-array dataref)")
            print("  D7 degrades to: re-probe the detection dataref on every cockpit call.")
        else:
            print(f"  acf_relative_path = {path!r}")

        rule("CATALOG DETECTION")
        catalog = await adapter.get_cockpit_catalog()
        if catalog.aircraft is None:
            print(f"  no catalog matched: {catalog.reason}")
        else:
            print(f"  detected: {catalog.aircraft.catalog_id} ({catalog.aircraft.label})")
            print(f"  detection_note: {catalog.detection_note}")

        rule("§10.4 (first half) -- full index after loading the Zibo")
        assert adapter._client is not None
        response = await adapter._client.get("/api/v2/datarefs")
        response.raise_for_status()
        names = {entry.get("name") for entry in response.json().get("data", [])}
        if ZIBO_PROBE_DATAREF in names:
            print(f"  {ZIBO_PROBE_DATAREF!r} IS present in the unfiltered full index.")
            print("  A bulk pre-resolution pass would be possible if ever wanted.")
        else:
            print(f"  {ZIBO_PROBE_DATAREF!r} is NOT present in the unfiltered full index.")
            print("  Per-name probing (D5/D6, already how this adapter works) remains required.")

        rule("§10.4 (second half) -- does a reload change the resolved id?")
        before_id = await _lookup_raw(adapter._client, ZIBO_PROBE_DATAREF)
        print(f"  {ZIBO_PROBE_DATAREF!r} currently resolves to id {before_id!r}")
        pause_for(
            "Reload the aircraft (or the Zibo's own plugins) in X-Plane now, WITHOUT "
            "changing the loaded airframe."
        )
        after_id = await _lookup_raw(adapter._client, ZIBO_PROBE_DATAREF)
        print(f"  {ZIBO_PROBE_DATAREF!r} now resolves to id {after_id!r}")
        if before_id is None or after_id is None:
            print("  could not compare -- the dataref was unresolved before or after the reload.")
        elif before_id == after_id:
            print("  SAME id after the reload -- no evidence of a plugin-reload id churn.")
        else:
            print("  DIFFERENT id after the reload -- D7's second signal is a real scenario here,")
            print("  not just a theoretical one. Update §10.4 in the design with this finding.")

        rule("DONE")
        print("  Write whatever changed above into")
        print("  docs/designs/cockpit-control-catalog.md §10.3/§10.4.")
        return 0
    finally:
        await adapter.disconnect()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8086)
    args = parser.parse_args()
    return asyncio.run(run(args.host, args.port))


if __name__ == "__main__":
    raise SystemExit(main())
