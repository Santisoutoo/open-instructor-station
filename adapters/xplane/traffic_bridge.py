"""Bridge transport: probe + command/ack/contacts codec for the optional ``bridge/`` plugin.

**adapters/xplane/'s half of the AI Traffic Manager's wire protocol**
(``docs/designs/ai-traffic.md`` §5, amended by the §10.4 spike findings of
2026-08-18). No dataref-specific detail leaks into ``core/`` — this module,
and the six ``SimAdapter`` methods in :mod:`adapters.xplane.xplane_adapter`
that call it, are the only place X-Plane's custom ``ois/*`` datarefs are
named.

The protocol is request/poll, **at most one command in flight** (§5.1): the
adapter writes a JSON command to ``ois/traffic/command``, polls
``ois/traffic/command_ack`` for a matching ``seq``, and reads
``ois/traffic/contacts`` on every ``get_traffic_contacts()``/
``stream_traffic()`` tick. Validated live against a real ``bridge/`` plugin
(§10.4): ~27 ms median command→ack round trip, the ack present on the very
first poll every time, no payload ceiling up to (and past) 64 KB — a realistic
8-waypoint ``approach_sequence`` spawn command is ~1.6 kB and round-trips
intact in one write. §5.3's chunking fallback is not needed.

Wire encoding for the ``data``-typed (byte array) datarefs mirrors what the
§10.4 spike's own driver (``spikes/bridge_transport.py::BridgeClient``)
measured working: writes are a base64 string in ``{"data": ...}``; reads come
back either as a base64 string or a plain list of 0-255 ints, and either shape
is accepted — the same tolerance :func:`adapters.xplane.xplane_adapter._decode_dataref_text`
already applies to the ``acf_icao`` byte-array dataref, generalised here to
JSON payloads instead of short text fields.

The bridge's own ``contacts`` wire shape carries :class:`~core.traffic.TrafficContact`
minus ``label``/``scenario_shape`` (§5.1) — those two fields are known only to
whoever built the track, so :class:`~adapters.xplane.xplane_adapter.XPlaneSimAdapter`
keeps its own per-``traffic_id`` ledger and this module never sees them.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import itertools
import json
import time
from typing import Any

import httpx

__all__ = [
    "ACK_DATAREF",
    "COMMAND_DATAREF",
    "CONTACTS_DATAREF",
    "HEARTBEAT_DATAREF",
    "MAX_CONCURRENT_TRAFFIC_XPLANE",
    "BridgeNotReachable",
    "BridgeTransport",
    "probe",
]

HEARTBEAT_DATAREF = "ois/bridge/heartbeat_s"
COMMAND_DATAREF = "ois/traffic/command"
ACK_DATAREF = "ois/traffic/command_ack"
CONTACTS_DATAREF = "ois/traffic/contacts"

#: The four custom datarefs this module resolves, keyed the same way
#: ``OPTIONAL_DATAREFS`` is elsewhere in this package. All four must resolve
#: for the bridge to count as present (a partial registration — the plugin
#: mid-load, or a stale build missing one accessor — is treated as absent,
#: never as a half-working bridge).
_BRIDGE_DATAREFS: dict[str, str] = {
    "heartbeat": HEARTBEAT_DATAREF,
    "command": COMMAND_DATAREF,
    "command_ack": ACK_DATAREF,
    "contacts": CONTACTS_DATAREF,
}

#: §5.2's liveness gap: two heartbeat reads this far apart must strictly
#: increase, proving the flight loop is actually ticking rather than the
#: plugin having loaded and then frozen — the exact failure mode the §10.4
#: spike observed (a heartbeat read twice immediately after `wait-ready`
#: stayed at 0.0 both times) and this recipe correctly refused.
_BRIDGE_PROBE_GAP_S = 0.5

#: How long one command waits for its matching ack before the adapter gives
#: up and reports the bridge unreachable. The §10.4 spike measured a ~27 ms
#: median round trip with the ack present on the very first poll every single
#: time (50/50 samples); this is a wide margin over that, mirroring the
#: existing ``XPlaneNotReachable`` timeout posture elsewhere in this package
#: rather than inventing a new one.
_ACK_TIMEOUT_S = 5.0
_ACK_POLL_INTERVAL_S = 0.02

#: X-Plane's real published multiplayer-slot cap (ai-traffic.md §5.4),
#: carried forward as the bridge-enforced capacity per the §10.4 spike
#: findings: the legacy multiplayer-slot mechanism does not work on a real
#: install (a resident plugin population holds the aircraft set), so the
#: bridge drives entities as XPLMInstance objects plus a TCAS-target entry
#: for ``kind="aircraft"`` instead — but the number stays 19 until a real
#: TCAS-target write has been exercised and its read-back asserted under
#: ``-m sim`` (§8.4); only then may it be re-baselined toward the 64-entry
#: TCAS table. The bridge is the source of truth for "how many slots are
#: actually free" (D6) — this constant is this adapter's own answer, used
#: only when an ack reports capacity refusal without a usable ``capacity``
#: field of its own.
MAX_CONCURRENT_TRAFFIC_XPLANE = 19


class BridgeNotReachable(RuntimeError):
    """The bridge did not answer a command in time, or the probe/read failed.

    Surfaces the D4 connectivity-fault posture: a bridge that disappears
    mid-session is not a capability flip, it is a write failing honestly.
    """


class BridgeTransport:
    """Drives the §5.1 request/poll protocol over one already-connected client.

    Holds no domain knowledge of :class:`~core.traffic.TrafficTrack`/
    :class:`~core.traffic.TrafficContact` — it moves JSON-shaped dicts across
    four already-resolved dataref ids and nothing else. The caller
    (:class:`~adapters.xplane.xplane_adapter.XPlaneSimAdapter`) is the one
    that knows what a ``spawn`` command or a contact record means.

    ``send_command`` serialises concurrent callers through an internal lock:
    the protocol's own "at most one command in flight" invariant (§5.1) is
    expected to hold because ``server/traffic_routes.py`` never issues two
    traffic writes concurrently against one adapter instance, but a
    transport-level lock costs nothing and turns a violated assumption into a
    queued wait instead of two commands racing on the same dataref.
    """

    def __init__(self, client: httpx.AsyncClient, dataref_ids: dict[str, int]) -> None:
        self._client = client
        self._ids = dataref_ids
        self._seq = itertools.count(1)
        self._lock = asyncio.Lock()

    async def read_heartbeat(self) -> float:
        """Raw ``ois/bridge/heartbeat_s`` read — used only by :func:`probe`."""
        return float(await self._read_raw(self._ids["heartbeat"]))

    async def read_contacts(self) -> list[dict[str, Any]]:
        """The bridge's live entity list, or ``[]`` for anything not a JSON array."""
        payload = await self._read_json(self._ids["contacts"])
        return payload if isinstance(payload, list) else []

    async def send_command(self, command: dict[str, Any]) -> dict[str, Any]:
        """Write one command, tag it with a fresh ``seq``, and poll for its ack.

        Returns the bridge's own ack dict verbatim — whether the command
        succeeded (``ok``) and why not (``error``/``error_kind``) is the
        caller's business, not this transport's.

        Raises:
            BridgeNotReachable: no ack carrying the matching ``seq`` arrived
                within :data:`_ACK_TIMEOUT_S`, or the write/poll itself
                could not reach the Web API.
        """
        async with self._lock:
            seq = next(self._seq)
            payload = json.dumps({**command, "seq": seq}).encode("utf-8")
            try:
                await self._write_bytes(self._ids["command"], payload)
                deadline = time.monotonic() + _ACK_TIMEOUT_S
                while time.monotonic() < deadline:
                    ack = await self._read_json(self._ids["command_ack"])
                    if isinstance(ack, dict) and ack.get("seq") == seq:
                        return ack
                    await asyncio.sleep(_ACK_POLL_INTERVAL_S)
            except httpx.HTTPError as exc:
                raise BridgeNotReachable(
                    f"Lost contact with the bridge while sending op={command.get('op')!r}: {exc}"
                ) from exc
            raise BridgeNotReachable(
                f"No ack from the bridge for op={command.get('op')!r} (seq={seq}) within "
                f"{_ACK_TIMEOUT_S:.0f}s — the bridge plugin may have stopped responding."
            )

    # -- data-dataref codec (§5.3) -----------------------------------------

    async def _read_raw(self, dataref_id: int) -> Any:
        response = await self._client.get(f"/api/v2/datarefs/{dataref_id}/value")
        response.raise_for_status()
        return response.json()["data"]

    async def _read_bytes(self, dataref_id: int) -> bytes:
        return _decode_data_dataref(await self._read_raw(dataref_id))

    async def _read_json(self, dataref_id: int) -> Any:
        payload = (await self._read_bytes(dataref_id)).split(b"\x00", 1)[0]
        if not payload:
            return None
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None

    async def _write_bytes(self, dataref_id: int, payload: bytes) -> None:
        response = await self._client.patch(
            f"/api/v2/datarefs/{dataref_id}/value",
            json={"data": base64.b64encode(payload).decode("ascii")},
        )
        response.raise_for_status()


def _decode_data_dataref(raw: Any) -> bytes:
    """Decode a ``data``-typed dataref's JSON value into bytes.

    Mirrors the tolerance :func:`adapters.xplane.xplane_adapter._decode_dataref_text`
    already applies, and the §10.4 spike's own driver: the Web API answers a
    byte-array dataref either as a base64 string or as a plain list of 0-255
    ints. Anything else — including a decode failure — degrades to empty
    bytes rather than raising, so a single malformed read never takes down a
    ``get_traffic_contacts()`` poll.
    """
    if raw is None:
        return b""
    if isinstance(raw, str):
        try:
            return base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            return raw.encode("utf-8", errors="replace")
    if isinstance(raw, list):
        try:
            return bytes(value & 0xFF for value in raw)
        except TypeError:
            return b""
    return b""


async def probe(client: httpx.AsyncClient) -> BridgeTransport | None:
    """Is the optional ``bridge/`` plugin loaded and alive on this connection? (§5.2)

    Resolves all four ``ois/*`` custom datarefs from the dataref index — the
    same ``GET /api/v2/datarefs`` scan pattern
    :data:`~adapters.xplane.xplane_adapter.OPTIONAL_DATAREFS` already uses —
    then reads the heartbeat twice, :data:`_BRIDGE_PROBE_GAP_S` apart,
    requiring the second read to be strictly greater than the first.

    **Never raises.** Every failure mode this connect-time check can hit — the
    index fetch itself failing, one or more of the four datarefs missing, a
    non-numeric heartbeat, a heartbeat that does not advance — returns
    ``None``. That is the whole point of "optional": an absent or misbehaving
    bridge must never fail :meth:`~adapters.xplane.xplane_adapter.XPlaneSimAdapter.connect`.

    Returns:
        A :class:`BridgeTransport` already primed with the four resolved
        dataref ids, or ``None`` when no live bridge was found. Deliberately
        returns the transport rather than a plain ``bool`` (a small,
        documented departure from §5.2's ``-> bool`` sketch): the caller
        needs the resolved ids for every later traffic call regardless, and
        resolving them a second time would mean a second full index fetch.
    """
    try:
        response = await client.get("/api/v2/datarefs")
        response.raise_for_status()
    except httpx.HTTPError:
        return None

    wanted = {path: key for key, path in _BRIDGE_DATAREFS.items()}
    ids: dict[str, int] = {}
    for entry in response.json().get("data", []):
        key = wanted.get(entry.get("name"))
        if key is None:
            continue
        try:
            ids[key] = int(entry["id"])
        except (KeyError, TypeError, ValueError):
            return None
    if set(ids) != set(_BRIDGE_DATAREFS):
        return None  # partial or absent registration — treated as no bridge

    transport = BridgeTransport(client, ids)
    try:
        first = await transport.read_heartbeat()
        await asyncio.sleep(_BRIDGE_PROBE_GAP_S)
        second = await transport.read_heartbeat()
    except (httpx.HTTPError, TypeError, ValueError):
        return None
    if second <= first:
        return None
    return transport
