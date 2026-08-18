"""Bridge transport spike: measure the three §10.4 unknowns of the AI Traffic design.

THROWAWAY (docs/designs/ai-traffic.md §10.4). Never imported by the
application, never in CI. Requires the companion XPPython3 plugin
``spikes/PI_OISBridgeSpike.py`` installed in
``<X-Plane 12>/Resources/plugins/PythonPlugins/`` *before* the simulator was
started — see that file's docstring for install/removal instructions.

It drives the §5.1 request/poll protocol from outside, over the Web API, and
measures:

a) **Latency** — command→ack round trip under flight-loop scheduling: write a
   ``ping`` to ``ois/traffic/command``, poll ``ois/traffic/command_ack`` until
   the matching ``seq`` appears, ~50 timed iterations, report median/worst.
b) **Payload ceiling** — write ``echo`` commands of increasing JSON size
   (256 B → 64 KB, plus one past the plugin's declared 64 KB capacity) and
   compare what the plugin received (length + sha256) with what was sent.
   Also sends one realistic 8-waypoint approach_sequence ``TrafficTrack``
   (§3.2 field names) end to end, and reads the resulting contact back from
   ``ois/traffic/contacts`` — the full spawn→contact loop.
c) **Spawn mechanisms** — asks the plugin to probe (1) the multiplayer
   aircraft slots (``sim/multiplayer/position/plane1_*``: acquirePlanes,
   disableAIForPlane, write, read back after 10 flight loops) and (2) the
   XPLMInstance path (lookupObjects → loadObject → createInstance) for ground
   vehicles / birds. Findings are printed verbatim for §10.4.

Run (X-Plane loaded into a flight, plugin installed)::

    python spikes/bridge_transport.py [--host localhost] [--port 8086]

Exit codes: ``0`` all measurements taken; ``1`` X-Plane or the spike plugin's
datarefs not reachable (install/launch order problem — the Web API indexes
datarefs at startup); ``2`` the transport answered but a measurement failed.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
import hashlib
import json
import math
import statistics
import time
from typing import Any

import httpx

HEARTBEAT_DATAREF = "ois/bridge/heartbeat_s"
COMMAND_DATAREF = "ois/traffic/command"
ACK_DATAREF = "ois/traffic/command_ack"
CONTACTS_DATAREF = "ois/traffic/contacts"

SPIKE_DATAREFS = (HEARTBEAT_DATAREF, COMMAND_DATAREF, ACK_DATAREF, CONTACTS_DATAREF)

#: §5.2's liveness gap: two heartbeat reads this far apart must strictly increase.
PROBE_GAP_S = 0.5

#: Timed ping iterations for measurement (a), after a short warmup.
LATENCY_ITERATIONS = 50
LATENCY_WARMUP = 3

#: Payload sizes for measurement (b). The plugin's command buffer declares
#: 65536 bytes; the final size probes one step beyond that declared capacity.
PAYLOAD_SIZES_B = (256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 66000)

#: How long to keep polling for one ack before giving up.
ACK_TIMEOUT_S = 10.0

#: The slot/instance probes span multiple flight loops on the plugin side.
PROBE_ACK_TIMEOUT_S = 30.0


class SpikeError(RuntimeError):
    """A measurement could not be taken; the message says why."""


class BridgeClient:
    """Minimal Web API client for the four spike datarefs."""

    def __init__(self, host: str, port: int) -> None:
        self.base_url = f"http://{host}:{port}"
        self._client = httpx.Client(base_url=self.base_url, timeout=10.0)
        self._ids: dict[str, int] = {}
        self._seq = 0

    def close(self) -> None:
        self._client.close()

    # -- plumbing ----------------------------------------------------------

    def resolve_ids(self) -> list[str]:
        """Resolve the spike datarefs' numeric ids. Returns the missing names."""
        missing: list[str] = []
        for name in SPIKE_DATAREFS:
            response = self._client.get("/api/v2/datarefs", params={"filter[name]": name})
            response.raise_for_status()
            entries = response.json().get("data", [])
            if entries:
                self._ids[name] = int(entries[0]["id"])
            else:
                missing.append(name)
        return missing

    def read_raw(self, name: str) -> Any:
        response = self._client.get(f"/api/v2/datarefs/{self._ids[name]}/value")
        response.raise_for_status()
        return response.json()["data"]

    def read_bytes(self, name: str) -> bytes:
        raw = self.read_raw(name)
        if raw is None:
            return b""
        if isinstance(raw, str):
            try:
                return base64.b64decode(raw, validate=True)
            except (binascii.Error, ValueError):
                return raw.encode("utf-8", errors="replace")
        if isinstance(raw, list):
            return bytes(value & 0xFF for value in raw)
        raise SpikeError(f"unexpected data-dataref wire shape for {name}: {type(raw).__name__}")

    def read_json(self, name: str) -> Any:
        payload = self.read_bytes(name).split(b"\x00", 1)[0]
        if not payload:
            return None
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None

    def write_command_raw(self, payload: bytes) -> httpx.Response:
        """PATCH the command dataref. Returns the response, never raises for status."""
        return self._client.patch(
            f"/api/v2/datarefs/{self._ids[COMMAND_DATAREF]}/value",
            json={"data": base64.b64encode(payload).decode("ascii")},
        )

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def send_and_wait(
        self, command: dict[str, Any], timeout_s: float = ACK_TIMEOUT_S
    ) -> tuple[dict[str, Any], float, int]:
        """Write one command and poll the ack until its ``seq`` answers.

        Returns ``(ack, round_trip_s, polls)``. The clock starts *before* the
        PATCH: the round trip is what ``spawn_traffic`` would actually wait.
        """
        payload = json.dumps(command).encode("utf-8")
        started = time.perf_counter()
        response = self.write_command_raw(payload)
        if response.status_code >= 400:
            raise SpikeError(
                f"command write refused: HTTP {response.status_code} {response.text[:200]}"
            )
        polls = 0
        deadline = started + timeout_s
        while time.perf_counter() < deadline:
            polls += 1
            ack = self.read_json(ACK_DATAREF)
            if isinstance(ack, dict) and ack.get("seq") == command.get("seq"):
                return ack, time.perf_counter() - started, polls
        raise SpikeError(
            f"no ack for seq={command.get('seq')} op={command.get('op')} "
            f"within {timeout_s:.0f}s ({polls} polls)"
        )


def rule(title: str) -> None:
    print(f"\n--- {title} " + "-" * max(0, 58 - len(title)))


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


# -- §5.2 liveness probe ---------------------------------------------------


def check_liveness(client: BridgeClient) -> None:
    first = float(client.read_raw(HEARTBEAT_DATAREF))
    time.sleep(PROBE_GAP_S)
    second = float(client.read_raw(HEARTBEAT_DATAREF))
    print(f"  heartbeat_s: {first:.3f} -> {second:.3f} ({PROBE_GAP_S}s apart)")
    if second <= first:
        raise SpikeError(
            "heartbeat did not advance -- the plugin loaded but its flight loop is not ticking"
        )
    print("  §5.2 liveness probe recipe CONFIRMED: two reads, strictly increasing.")


# -- (a) latency -----------------------------------------------------------


def measure_latency(client: BridgeClient) -> dict[str, float]:
    for _ in range(LATENCY_WARMUP):
        client.send_and_wait({"op": "ping", "seq": client.next_seq()})
    samples: list[float] = []
    poll_counts: list[int] = []
    for _ in range(LATENCY_ITERATIONS):
        _, round_trip, polls = client.send_and_wait({"op": "ping", "seq": client.next_seq()})
        samples.append(round_trip)
        poll_counts.append(polls)
    ordered = sorted(samples)
    stats = {
        "iterations": float(LATENCY_ITERATIONS),
        "min_ms": ordered[0] * 1000.0,
        "median_ms": statistics.median(samples) * 1000.0,
        # Nearest-rank p95: the ceil(0.95 * n)-th ordered sample (1-based).
        "p95_ms": ordered[min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)] * 1000.0,
        "max_ms": ordered[-1] * 1000.0,
        "mean_polls": statistics.mean(poll_counts),
    }
    print(f"  {LATENCY_ITERATIONS} timed pings (after {LATENCY_WARMUP} warmup):")
    print(
        f"    min {stats['min_ms']:.1f} ms | median {stats['median_ms']:.1f} ms | "
        f"p95 {stats['p95_ms']:.1f} ms | worst {stats['max_ms']:.1f} ms"
    )
    print(f"    mean ack polls per command: {stats['mean_polls']:.1f}")
    return stats


# -- (b) payload ceiling ---------------------------------------------------


def build_echo_payload(seq: int, target_size_b: int) -> bytes:
    """An ``echo`` command whose JSON encoding is exactly ``target_size_b`` bytes."""
    skeleton = json.dumps({"op": "echo", "seq": seq, "blob": ""}).encode("utf-8")
    padding = target_size_b - len(skeleton)
    if padding < 0:
        raise SpikeError(f"target size {target_size_b} smaller than the echo skeleton")
    return json.dumps({"op": "echo", "seq": seq, "blob": "x" * padding}).encode("utf-8")


def measure_payload_ceiling(client: BridgeClient) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for size in PAYLOAD_SIZES_B:
        seq = client.next_seq()
        payload = build_echo_payload(seq, size)
        outcome: dict[str, Any] = {"size_b": size}
        try:
            ack, round_trip, _ = client.send_and_wait(json.loads(payload.decode("utf-8")))
        except SpikeError as exc:
            outcome["result"] = f"FAILED: {exc}"
            results.append(outcome)
            print(f"  {size:>6} B  {outcome['result']}")
            continue
        intact = ack.get("payload_len") == len(payload) and ack.get("sha256") == sha256_hex(payload)
        outcome["result"] = "intact" if intact else "TRUNCATED/CORRUPT"
        outcome["received_len"] = ack.get("received_len")
        outcome["payload_len"] = ack.get("payload_len")
        outcome["round_trip_ms"] = round_trip * 1000.0
        results.append(outcome)
        print(
            f"  {size:>6} B  {outcome['result']:<18} received_len={ack.get('received_len')} "
            f"rtt={round_trip * 1000.0:.1f} ms"
        )
    return results


def build_approach_sequence_track() -> dict[str, Any]:
    """An 8-waypoint LEMD 32L final, §3.2 field names — the realistic payload."""
    threshold_lat, threshold_lon = 40.462, -3.545
    waypoints: list[dict[str, Any]] = []
    for i in range(8):
        distance_nm = 10.0 - i * (10.0 / 7.0)
        waypoints.append(
            {
                "position": {
                    "latitude": round(threshold_lat - distance_nm * 0.0145, 6),
                    "longitude": round(threshold_lon + distance_nm * 0.0052, 6),
                    "altitude_ft": round(2000.0 + distance_nm * 318.0, 1),
                },
                "speed_kt": 130.0,
                "heading_deg": 324.0,
                "t_offset_s": round(i * 33.0, 1),
                "on_ground": False,
            }
        )
    return {
        "kind": "aircraft",
        "scenario_shape": "approach_sequence",
        "callsign": "TFC01",
        "label": "Bridge spike: approach sequence aircraft #1",
        "waypoints": waypoints,
        "despawn_after_s": 60.0,
    }


def measure_track_round_trip(client: BridgeClient) -> dict[str, Any]:
    track = build_approach_sequence_track()
    traffic_id = "spike-tfc-0001"
    command = {"op": "spawn", "seq": client.next_seq(), "traffic_id": traffic_id, "track": track}
    payload = json.dumps(command).encode("utf-8")
    print(f"  8-waypoint approach_sequence spawn command: {len(payload)} bytes JSON")
    ack, round_trip, _ = client.send_and_wait(command)
    intact = ack.get("ok") is True and ack.get("sha256") == sha256_hex(payload)
    print(
        f"  spawn ack: ok={ack.get('ok')} waypoints={ack.get('waypoints')} "
        f"sha_match={ack.get('sha256') == sha256_hex(payload)} rtt={round_trip * 1000.0:.1f} ms"
    )
    time.sleep(0.5)
    contacts = client.read_json(CONTACTS_DATAREF)
    contact_seen = isinstance(contacts, list) and any(
        contact.get("traffic_id") == traffic_id for contact in contacts
    )
    print(f"  contacts read back: {contacts if contact_seen else 'MISSING our contact'}")
    despawn_ack, _, _ = client.send_and_wait(
        {"op": "despawn", "seq": client.next_seq(), "traffic_id": traffic_id}
    )
    time.sleep(0.3)
    contacts_after = client.read_json(CONTACTS_DATAREF)
    emptied = contacts_after == []
    print(f"  after despawn (ok={despawn_ack.get('ok')}): contacts={contacts_after}")
    return {
        "command_bytes": len(payload),
        "spawn_intact": intact,
        "contact_seen": contact_seen,
        "despawn_ok": despawn_ack.get("ok") is True and emptied,
    }


# -- (c) spawn mechanisms --------------------------------------------------


def probe_spawn_mechanisms(client: BridgeClient) -> dict[str, Any]:
    findings: dict[str, Any] = {}
    rule("(c1) MULTIPLAYER AIRCRAFT SLOTS")
    ack, _, _ = client.send_and_wait(
        {"op": "probe_mp", "seq": client.next_seq()}, timeout_s=PROBE_ACK_TIMEOUT_S
    )
    findings["multiplayer"] = ack.get("mp_probe", ack)
    print(json.dumps(findings["multiplayer"], indent=2))

    rule("(c2) XPLMInstance (ground vehicles / birds)")
    ack, _, _ = client.send_and_wait(
        {"op": "probe_instance", "seq": client.next_seq()}, timeout_s=PROBE_ACK_TIMEOUT_S
    )
    findings["instance"] = {key: value for key, value in ack.items() if key not in ("seq", "op")}
    print(json.dumps(findings["instance"], indent=2))
    return findings


# -- main ------------------------------------------------------------------


def run(host: str, port: int) -> int:
    client = BridgeClient(host, port)
    failures: list[str] = []
    try:
        rule("CONNECT / RESOLVE (spike datarefs in the Web API index)")
        try:
            missing = client.resolve_ids()
        except httpx.HTTPError as exc:
            print(f"  FAILED: {exc}")
            print("  Is X-Plane running with the Web API enabled on this host/port?")
            return 1
        if missing:
            print(f"  MISSING from the dataref index: {', '.join(missing)}")
            print("  Install spikes/PI_OISBridgeSpike.py into PythonPlugins/ and")
            print("  RESTART X-Plane -- the Web API indexes datarefs at startup.")
            return 1
        print(f"  all four ois/* datarefs resolved at {client.base_url}")

        rule("LIVENESS (§5.2 probe recipe)")
        check_liveness(client)

        rule("(a) COMMAND->ACK LATENCY")
        latency = measure_latency(client)

        rule("(b) PAYLOAD CEILING (echo, 256 B -> 64 KB + one past capacity)")
        ceiling = measure_payload_ceiling(client)
        intact_sizes = [row["size_b"] for row in ceiling if row.get("result") == "intact"]

        rule("(b) REALISTIC TrafficTrack ROUND TRIP + contacts")
        track_result = measure_track_round_trip(client)
        if not (track_result["spawn_intact"] and track_result["contact_seen"]):
            failures.append("TrafficTrack round trip incomplete")
        if not track_result["despawn_ok"]:
            failures.append("despawn did not empty contacts")

        probes = probe_spawn_mechanisms(client)

        rule("VERDICT")
        print(f"  (a) median {latency['median_ms']:.1f} ms, worst {latency['max_ms']:.1f} ms")
        if intact_sizes:
            print(f"  (b) intact through {max(intact_sizes)} B; one TrafficTrack = ")
            print(
                f"      {track_result['command_bytes']} B in ONE write: "
                f"{'SAFE' if track_result['spawn_intact'] else 'NOT SAFE'}"
            )
        else:
            failures.append("no echo payload size survived intact")
        mp = probes.get("multiplayer", {})
        print(f"  (c) acquire_planes={mp.get('acquire_planes')}, deltas={mp.get('deltas')}")
        print(f"      instance: {probes.get('instance', {}).get('create_instance')}")
        print("\n  Full findings JSON (for docs/designs/ai-traffic.md §10.4):")
        print(
            json.dumps(
                {
                    "latency": latency,
                    "payload_ceiling": ceiling,
                    "traffic_track": track_result,
                    "spawn_mechanisms": probes,
                },
                indent=2,
            )
        )
        if failures:
            print("\n  FAILURES: " + "; ".join(failures))
            return 2
        return 0
    except SpikeError as exc:
        print(f"\n  MEASUREMENT FAILED: {exc}")
        return 2
    finally:
        with contextlib.suppress(SpikeError, httpx.HTTPError, KeyError):
            client.send_and_wait({"op": "clear_all", "seq": client.next_seq()}, timeout_s=3.0)
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8086)
    args = parser.parse_args()
    return run(args.host, args.port)


if __name__ == "__main__":
    raise SystemExit(main())
