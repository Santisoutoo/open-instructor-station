"""Fuel & Payload dataref discovery: what does X-Plane actually publish?

``docs/designs/fuel-payload.md`` §6.2 rates most of the mass-and-balance
mapping high confidence — ``sim/flightmodel/weight/m_fuel``/``m_stations``,
the two core weight arrays every aircraft's flight model reads — but marks
everything else "verify in spike" or "not attempted from the live sim":

* A tank/station **count**, to know how many of ``m_fuel``/``m_stations``'s
  fixed slots are real for the loaded airframe rather than padding. §6.2's
  prose names one candidate, ``sim/aircraft/weight/acf_num_tanks``, and no
  candidate at all for stations.
* Tank/station **capacities** and **moment arms** — no known public dataref
  (§6.2, §11.1's "largest unresolved item"). Candidates floated: a direct
  capacity array, or ``sim/aircraft/overflow/acf_tank_rat[]`` (a ratio,
  not a capacity).
* A usable, structured **CG readback** — "not attempted from the live sim".

§11.1 names this exact task as the first step of the X-Plane adapter track:
"connect, enumerate everything under ``sim/aircraft/weight/`` and
``sim/flightmodel/weight/``, and record what is actually readable." This
script does that, plus the handful of specific candidates named above, and
prints what it found rather than asserting anything — the verdict is read by
a person, not by an exit code, because "no arm dataref exists" is itself a
valid, useful answer (§11.1: "the design does not need to change" if so).

This module is throwaway validation tooling (``CLAUDE.md``'s ``spikes/``
policy): never imported by the app, never covered by tests, needs a live
X-Plane loaded into a flight.

Run it with X-Plane loaded into a flight::

    python spikes/fuel_payload_datarefs.py [--host localhost] [--port 8086]

Exit codes: ``0`` the sim answered (regardless of what it did or did not
publish), ``1`` X-Plane not reachable.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

#: Namespace prefixes to enumerate wholesale — §11.1's instruction verbatim.
NAMESPACE_PREFIXES = ("sim/aircraft/weight/", "sim/flightmodel/weight/")

#: Specific candidates worth a direct read even if they fall outside the two
#: namespaces above, or turn out to need a base name match rather than a
#: prefix scan. Every one of these is named as an open question somewhere in
#: docs/designs/fuel-payload.md §6.2/§11.1 — none is invented here.
CANDIDATES = {
    "tank count": "sim/aircraft/weight/acf_num_tanks",
    "tank capacity ratio (NOT a capacity — §6.2)": "sim/aircraft/overflow/acf_tank_rat",
    "empty weight (medium/high confidence)": "sim/aircraft/weight/acf_m_empty",
    "max takeoff weight (medium/high confidence)": "sim/aircraft/weight/acf_m_max",
    "fuel array (high confidence, already mapped)": "sim/flightmodel/weight/m_fuel",
    "station array (high confidence, already mapped)": "sim/flightmodel/weight/m_stations",
    "fixed-weight fallback, unwired (§6.2)": "sim/flightmodel/weight/m_fixed",
}


def rule(title: str) -> None:
    """Print a section header."""
    print(f"\n--- {title} " + "-" * max(0, 58 - len(title)))


async def read_value(client: httpx.AsyncClient, dataref_id: int) -> Any:
    """Read one dataref's current value, or ``None`` on any HTTP error."""
    try:
        response = await client.get(f"/api/v2/datarefs/{dataref_id}/value")
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return f"<read failed: {exc}>"
    return response.json().get("data")


def summarise(value: Any) -> str:
    """A short, array-aware description of a dataref value."""
    if isinstance(value, list):
        preview = value[:12]
        suffix = ", ..." if len(value) > 12 else ""
        return f"array[{len(value)}] = {preview}{suffix}"
    return repr(value)


async def run(host: str, port: int) -> int:
    """Run the discovery. Returns the process exit code."""
    base_url = f"http://{host}:{port}"
    client = httpx.AsyncClient(base_url=base_url, timeout=5.0)

    rule("CONNECT")
    try:
        response = await client.get("/api/v2/datarefs")
        response.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"  FAILED: {exc}")
        print("  Checklist: X-Plane 12.1+ running and loaded into a flight, Web API enabled.")
        await client.aclose()
        return 1
    entries = response.json().get("data", [])
    print(f"  connected to {base_url}, {len(entries)} datarefs indexed")

    try:
        rule("NAMESPACE SCAN: sim/aircraft/weight/* and sim/flightmodel/weight/*")
        by_prefix: dict[str, list[dict[str, Any]]] = {prefix: [] for prefix in NAMESPACE_PREFIXES}
        for entry in entries:
            name = entry.get("name", "")
            for prefix in NAMESPACE_PREFIXES:
                if name.startswith(prefix):
                    by_prefix[prefix].append(entry)

        name_to_id = {entry["name"]: int(entry["id"]) for entry in entries}

        for prefix, found in by_prefix.items():
            print(f"\n  {prefix} ({len(found)} datarefs)")
            for entry in sorted(found, key=lambda e: e["name"]):
                value = await read_value(client, int(entry["id"]))
                print(f"    {entry['name']:55s} {summarise(value)}")

        rule("NAMED CANDIDATES (docs/designs/fuel-payload.md §6.2/§11.1)")
        for label, path in CANDIDATES.items():
            dataref_id = name_to_id.get(path)
            if dataref_id is None:
                print(f"  [MISSING] {path}\n            ({label})")
                continue
            value = await read_value(client, dataref_id)
            print(f"  [FOUND]   {path}\n            ({label})\n            = {summarise(value)}")

        rule("VERDICT")
        print("  This is a discovery dump, not a pass/fail check. Compare the two namespace")
        print("  scans above against docs/designs/fuel-payload.md §6.2's table: anything")
        print("  found there that looks like a capacity, a moment arm or a per-tank/station")
        print("  count resolves §11.1. Finding nothing is itself the answer §11.1 already")
        print("  names as plausible — the design does not need to change if so, only")
        print("  core/fuel_payload/limits.py's fallback table needs to grow.")
        return 0
    finally:
        await client.aclose()


def main() -> int:
    """Parse arguments and run the discovery."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8086)
    args = parser.parse_args()
    return asyncio.run(run(args.host, args.port))


if __name__ == "__main__":
    raise SystemExit(main())
