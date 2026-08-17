"""Failure dataref discovery spike (docs/designs/failures-manager.md §10.8).

This is what turns adapters/xplane/failure_datarefs.py from "transcribed
verbatim from the design document" into fact. It is a diagnostic, not part of
the application: throwaway, never imported by anything under adapters/,
server/ or core/, never covered by tests, in the style of
spikes/xplane_connection.py.

What it does, in order:

1. **Dump every dataref under ``sim/operation/failures/``** from the Web API's
   dataref index and print it — this is the ground truth for every "verify in
   spike" row in the mapping table, and for the handful of idents this project
   guessed (``rel_esys``, ``rel_hydpmp``, …). Whatever is printed here is what
   belongs in ``failure_datarefs.py``, not what the design guessed.
2. **Read the value convention** (§5.1: 0 = working, 6 = inoperative now) off
   one dataref before touching it, so the "working" baseline is on record.
3. **Exercise inject/clear on one instrument** — ``instruments.pitot`` by
   default, chosen because it is a single dataref, high confidence, and safe:
   failing the pitot tube on a stationary aircraft has no consequence beyond
   the instrument reading, unlike an engine or gear failure.
4. **Restore** the dataref to its original value before exiting, in a
   ``finally`` — this spike must not leave a failure injected.

Run it with X-Plane loaded into a flight::

    python spikes/failure_datarefs.py [--host localhost] [--port 8086]
    python spikes/failure_datarefs.py --failure-dataref sim/operation/failures/rel_static

Exit codes: ``0`` the exercise ran and restored cleanly, ``1`` X-Plane not
reachable, ``2`` the exercised dataref did not read back the value it was
written (the value enum in §5.1 needs correcting before the adapter trusts
it).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from adapters.xplane.failure_datarefs import STATE_FAILED, STATE_WORKING

DEFAULT_FAILURE_DATAREF = "sim/operation/failures/rel_pitot"
FAILURE_PREFIX = "sim/operation/failures/"


def rule(title: str) -> None:
    """Print a section header."""
    print(f"\n--- {title} " + "-" * max(0, 58 - len(title)))


async def dump_failure_datarefs(client: httpx.AsyncClient) -> list[dict[str, object]]:
    """Every dataref under ``sim/operation/failures/`` this install publishes.

    This is the ground truth §5.2's "verify in spike" rows are waiting on —
    grep this output for the catalogue entries still marked unsupported in
    ``adapters/xplane/failure_datarefs.py`` (fuel leak, spoilers, gear, bird
    strike, lightning strike, pressurisation) and add whatever matches.
    """
    response = await client.get("/api/v2/datarefs")
    response.raise_for_status()
    entries = [
        entry
        for entry in response.json().get("data", [])
        if str(entry.get("name", "")).startswith(FAILURE_PREFIX)
    ]
    entries.sort(key=lambda entry: str(entry.get("name", "")))
    return entries


async def resolve_dataref_id(client: httpx.AsyncClient, name: str) -> int | None:
    """The numeric id of one dataref by its full path, or ``None`` if it does not exist."""
    response = await client.get("/api/v2/datarefs", params={"filter[name]": name})
    response.raise_for_status()
    entries = response.json().get("data", [])
    return int(entries[0]["id"]) if entries else None


async def read_value(client: httpx.AsyncClient, dataref_id: int) -> Any:
    response = await client.get(f"/api/v2/datarefs/{dataref_id}/value")
    response.raise_for_status()
    return response.json()["data"]


async def write_value(client: httpx.AsyncClient, dataref_id: int, value: int) -> None:
    response = await client.patch(
        f"/api/v2/datarefs/{dataref_id}/value",
        json={"data": value},
    )
    response.raise_for_status()


async def run(host: str, port: int, failure_dataref: str) -> int:
    """Run the spike. Returns the process exit code."""
    base_url = f"http://{host}:{port}"
    client = httpx.AsyncClient(base_url=base_url, timeout=5.0)
    try:
        try:
            probe = await client.get("/api/v2/datarefs")
            probe.raise_for_status()
        except httpx.HTTPError as exc:
            print(f"FAILED: could not reach the X-Plane Web API at {base_url}: {exc}")
            print("Checklist: X-Plane 12.1+ running and loaded into a flight, Web API enabled.")
            return 1

        rule("EVERY sim/operation/failures/* DATAREF ON THIS INSTALL")
        entries = await dump_failure_datarefs(client)
        for entry in entries:
            print(f"  {entry.get('name')}  (id {entry.get('id')})")
        print(f"\n  {len(entries)} datarefs found under {FAILURE_PREFIX!r}.")
        print(
            "  Cross-reference this list against every 'verify in spike' row in "
            "adapters/xplane/failure_datarefs.py."
        )

        rule(f"EXERCISE: {failure_dataref}")
        dataref_id = await resolve_dataref_id(client, failure_dataref)
        if dataref_id is None:
            print(f"  FAILED: {failure_dataref!r} does not exist on this install.")
            print("  Pick a name from the dump above with --failure-dataref.")
            return 1

        original = await read_value(client, dataref_id)
        print(f"  original value: {original!r} (expected 'working' = {STATE_WORKING})")

        try:
            print(f'  writing {STATE_FAILED} ("inoperative now", per §5.1)...')
            await write_value(client, dataref_id, STATE_FAILED)
            failed_readback = await read_value(client, dataref_id)
            print(f"  read back: {failed_readback!r}")
            if int(failed_readback) != STATE_FAILED:
                print(
                    f"  MISMATCH: wrote {STATE_FAILED}, read back {failed_readback!r}. "
                    "The §5.1 value enum needs correcting before the adapter trusts it."
                )
                return 2

            print(f'  writing {STATE_WORKING} ("working", per §5.1)...')
            await write_value(client, dataref_id, STATE_WORKING)
            cleared_readback = await read_value(client, dataref_id)
            print(f"  read back: {cleared_readback!r}")
            if int(cleared_readback) != STATE_WORKING:
                print(
                    f"  MISMATCH: wrote {STATE_WORKING}, read back {cleared_readback!r}. "
                    "The §5.1 value enum needs correcting before the adapter trusts it."
                )
                return 2
        finally:
            rule("RESTORE")
            await write_value(client, dataref_id, int(original) if original is not None else 0)
            restored = await read_value(client, dataref_id)
            print(f"  restored to: {restored!r}")

        rule("VERDICT")
        print("  The §5.1 value enum (0 = working, 6 = inoperative now) holds on this install.")
        print("  Promote every 'verify in spike' row this dump resolved into")
        print("  adapters/xplane/failure_datarefs.py, with its confidence set to 'high'.")
        return 0
    finally:
        await client.aclose()


def main() -> int:
    """Parse arguments and run the spike."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8086)
    parser.add_argument(
        "--failure-dataref",
        default=DEFAULT_FAILURE_DATAREF,
        help="Dataref path to exercise inject/clear on (default: pitot, single dataref, safe).",
    )
    args = parser.parse_args()
    return asyncio.run(run(args.host, args.port, args.failure_dataref))


if __name__ == "__main__":
    raise SystemExit(main())
