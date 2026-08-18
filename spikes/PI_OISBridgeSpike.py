"""OIS bridge transport spike — the in-sim half (XPPython3 plugin).

THROWAWAY (docs/designs/ai-traffic.md §10.4). Never imported by the application,
never in CI, never shipped. It exists so ``spikes/bridge_transport.py`` can
measure the three §10.4 unknowns against a real X-Plane flight loop:

a) command→ack round-trip latency under flight-loop scheduling;
b) the ``data``-dataref payload-size ceiling over the Web API;
c) whether multiplayer aircraft slots can be driven externally-triggered, and
   what the SDK offers for ground vehicles / birds (XPLMInstance vs slots).

It registers exactly the §5.1 custom datarefs the real bridge would:

===========================  =====  ========  ==========================================
Dataref                      Type   Writable  Purpose
===========================  =====  ========  ==========================================
``ois/bridge/heartbeat_s``   float  no        seconds alive, advanced every flight loop
``ois/traffic/command``      data   yes       one pending JSON command (read-act-clear)
``ois/traffic/command_ack``  data   no        JSON ack for the last processed command
``ois/traffic/contacts``     data   no        JSON array of live spike entities
===========================  =====  ========  ==========================================

Install (for the duration of the spike run only — REMOVE afterwards):

1. Copy this file to ``<X-Plane 12>/Resources/plugins/PythonPlugins/PI_OISBridgeSpike.py``
   (requires the XPPython3 plugin, already installed on this machine).
2. Start X-Plane and load a flight (the Web API index is built at startup, so
   the plugin must be present *before* launch).
3. Run ``python spikes/bridge_transport.py`` from the repository root.
4. Delete the copied file and its ``__pycache__`` entry when done.

Commands understood (JSON written to ``ois/traffic/command``): ``ping``,
``echo`` (length + sha256 back), ``spawn``/``despawn``/``clear_all`` (the §5.1
vocabulary; a spawned track becomes a static entry in ``contacts``),
``probe_mp`` (unknown c, multiplayer slots) and ``probe_instance`` (unknown c,
XPLMInstance). Every ack carries the command's ``seq`` so the driver can poll
for its own answer.
"""

import hashlib
import json
import time
from typing import Any

import xp

HEARTBEAT_DATAREF = "ois/bridge/heartbeat_s"
COMMAND_DATAREF = "ois/traffic/command"
ACK_DATAREF = "ois/traffic/command_ack"
CONTACTS_DATAREF = "ois/traffic/contacts"

#: Fixed capacity the command buffer *reports* to X-Plane. The Web API's own
#: per-write ceiling relative to this reported size is measurement (b).
COMMAND_CAPACITY_B = 65536

#: The ack buffer also reports a fixed, NUL-padded size — the conservative
#: style that works even if the Web API caches dataref sizes at index time.
ACK_CAPACITY_B = 16384

#: How many flight loops probe_mp waits between writing the plane1 datarefs
#: and reading them back — long enough for X-Plane's own AI/physics to
#: overwrite them if it is going to.
MP_VERIFY_AFTER_LOOPS = 10

#: Library virtual paths tried for the XPLMInstance probe. The finding is the
#: *mechanism*, not the exact path — any hit proves object-load + instance.
INSTANCE_CANDIDATE_PATHS = (
    "lib/airport/vehicles/pushback/tug.obj",
    "lib/airport/vehicles/baggage_handling/belt_loader.obj",
    "lib/airport/vehicles/servicing/fuel_truck.obj",
    "lib/airport/vehicles/fuel/hyd_truck.obj",
    "lib/dynamic/birds/seagull.obj",
    "lib/dynamic/seagull.obj",
)


class DataBuffer:
    """Backing store for one ``data``-typed custom dataref.

    ``fixed_capacity`` set: reads always report ``capacity`` bytes, content
    NUL-padded (the style that survives size-at-index-time caching).
    ``fixed_capacity`` unset: reads report the current content length only
    (the variable-size style — whether the Web API copes is itself a finding).
    """

    def __init__(self, capacity: int, fixed: bool) -> None:
        self.capacity = capacity
        self.fixed = fixed
        self.content = b""
        self.dirty = False
        self.last_write_count = 0

    def _readable(self) -> bytes:
        if self.fixed:
            return self.content[: self.capacity].ljust(self.capacity, b"\x00")
        return self.content

    def read(self, _ref_con: Any, values: Any, offset: int, count: int) -> int:
        data = self._readable()
        if values is None:
            return len(data)
        chunk = data[offset : offset + count]
        values.extend(chunk)
        return len(chunk)

    def write(self, _ref_con: Any, values: Any, offset: int, count: int) -> None:
        data = bytes(values[:count]) if count >= 0 else bytes(values)
        if offset == 0:
            self.content = data
        else:
            merged = bytearray(self.content.ljust(offset, b"\x00"))
            merged[offset : offset + len(data)] = data
            self.content = bytes(merged)
        self.last_write_count = len(data)
        self.dirty = True


def _payload_of(raw: bytes) -> bytes:
    """The JSON payload of a buffer: everything before the first NUL."""
    return raw.split(b"\x00", 1)[0]


class PythonInterface:
    """XPPython3 entry point."""

    def __init__(self) -> None:
        self._accessors: list[Any] = []
        self._flight_loop_id: Any = None
        self._t0 = 0.0
        self.heartbeat_s = 0.0
        self.loop_count = 0
        self._command = DataBuffer(COMMAND_CAPACITY_B, fixed=True)
        self._ack = DataBuffer(ACK_CAPACITY_B, fixed=True)
        self._contacts = DataBuffer(0, fixed=False)
        #: traffic_id -> {"track": dict, "spawned_hb": float}
        self._entities: dict[str, dict[str, Any]] = {}
        self._mp_probe: dict[str, Any] | None = None
        self._mp_acquired = False
        self._instance: Any = None
        self._instance_obj: Any = None
        self._instance_destroy_at_loop: int | None = None
        self._user_refs: dict[str, Any] = {}

    # -- XPPython3 lifecycle ----------------------------------------------

    def XPluginStart(self) -> tuple[str, str, str]:
        self._t0 = time.monotonic()
        self._accessors.append(
            xp.registerDataAccessor(
                HEARTBEAT_DATAREF,
                dataType=xp.Type_Float,
                writable=0,
                readFloat=lambda _ref: self.heartbeat_s,
            )
        )
        self._accessors.append(
            xp.registerDataAccessor(
                COMMAND_DATAREF,
                dataType=xp.Type_Data,
                writable=1,
                readData=self._command.read,
                writeData=self._command.write,
            )
        )
        self._accessors.append(
            xp.registerDataAccessor(
                ACK_DATAREF,
                dataType=xp.Type_Data,
                writable=0,
                readData=self._ack.read,
            )
        )
        self._accessors.append(
            xp.registerDataAccessor(
                CONTACTS_DATAREF,
                dataType=xp.Type_Data,
                writable=0,
                readData=self._contacts.read,
            )
        )
        xp.log("[OIS spike] datarefs registered")
        return (
            "OIS Bridge Spike",
            "ois.bridge.spike",
            "Throwaway transport measurement plugin (open-instructor-station §10.4)",
        )

    def XPluginEnable(self) -> int:
        for name in ("local_x", "local_y", "local_z"):
            self._user_refs[name] = xp.findDataRef(f"sim/flightmodel/position/{name}")
        self._flight_loop_id = xp.createFlightLoop(self._flight_loop)
        xp.scheduleFlightLoop(self._flight_loop_id, -1.0)
        xp.log("[OIS spike] flight loop scheduled (every frame)")
        return 1

    def XPluginDisable(self) -> None:
        if self._flight_loop_id is not None:
            xp.destroyFlightLoop(self._flight_loop_id)
            self._flight_loop_id = None
        self._teardown_probes()

    def XPluginStop(self) -> None:
        for accessor in self._accessors:
            xp.unregisterDataAccessor(accessor)
        self._accessors.clear()
        xp.log("[OIS spike] stopped")

    def XPluginReceiveMessage(self, _from: int, _message: int, _param: Any) -> None:
        pass

    # -- Flight loop -------------------------------------------------------

    def _flight_loop(self, _since: float, _elapsed: float, _counter: int, _ref: Any) -> float:
        self.loop_count += 1
        self.heartbeat_s = time.monotonic() - self._t0
        try:
            if self._command.dirty:
                self._command.dirty = False
                raw = self._command.content
                self._command.content = b""  # read once, act, clear (§5.1)
                self._process_command(raw)
            self._finish_mp_probe_if_due()
            self._destroy_instance_if_due()
            self._publish_contacts()
        except Exception as exc:
            xp.log(f"[OIS spike] flight loop error: {exc!r}")
            self._write_ack({"seq": -1, "ok": False, "error": repr(exc)})
        return -1.0

    # -- Command processing ------------------------------------------------

    def _process_command(self, raw: bytes) -> None:
        payload = _payload_of(raw)
        try:
            command = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            self._write_ack(
                {
                    "seq": -1,
                    "ok": False,
                    "error": f"undecodable command: {exc!r}",
                    "received_len": self._command.last_write_count,
                    "payload_len": len(payload),
                }
            )
            return

        op = command.get("op")
        seq = command.get("seq", -1)
        base = {
            "seq": seq,
            "op": op,
            "received_len": self._command.last_write_count,
            "payload_len": len(payload),
            "loop_count": self.loop_count,
            "heartbeat_s": self.heartbeat_s,
        }
        if op == "ping":
            self._write_ack({**base, "ok": True})
        elif op == "echo":
            self._write_ack({**base, "ok": True, "sha256": hashlib.sha256(payload).hexdigest()})
        elif op == "spawn":
            self._op_spawn(base, command)
        elif op == "despawn":
            traffic_id = command.get("traffic_id")
            existed = self._entities.pop(traffic_id, None) is not None
            self._write_ack({**base, "ok": existed, "traffic_id": traffic_id})
        elif op == "clear_all":
            count = len(self._entities)
            self._entities.clear()
            self._write_ack({**base, "ok": True, "despawned": count})
        elif op == "probe_mp":
            self._start_mp_probe(base)
        elif op == "probe_instance":
            self._op_probe_instance(base)
        else:
            self._write_ack({**base, "ok": False, "error": f"unknown op {op!r}"})

    def _op_spawn(self, base: dict[str, Any], command: dict[str, Any]) -> None:
        track = command.get("track")
        traffic_id = command.get("traffic_id")
        if not isinstance(track, dict) or not traffic_id:
            self._write_ack({**base, "ok": False, "error": "spawn needs traffic_id and track"})
            return
        payload = _payload_of(self._command.content) or json.dumps(command).encode()
        self._entities[traffic_id] = {"track": track, "spawned_hb": self.heartbeat_s}
        self._write_ack(
            {
                **base,
                "ok": True,
                "traffic_id": traffic_id,
                "waypoints": len(track.get("waypoints", [])),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )

    # -- contacts ----------------------------------------------------------

    def _publish_contacts(self) -> None:
        contacts = []
        for traffic_id, entity in self._entities.items():
            track = entity["track"]
            waypoint = (track.get("waypoints") or [{}])[0]
            position = waypoint.get("position", {})
            contacts.append(
                {
                    "traffic_id": traffic_id,
                    "callsign": track.get("callsign"),
                    "kind": track.get("kind"),
                    "latitude": position.get("latitude"),
                    "longitude": position.get("longitude"),
                    "altitude_ft": position.get("altitude_ft"),
                    "speed_kt": waypoint.get("speed_kt"),
                    "heading_deg": waypoint.get("heading_deg"),
                    "on_ground": waypoint.get("on_ground", False),
                    "alive_s": round(self.heartbeat_s - entity["spawned_hb"], 3),
                }
            )
        self._contacts.content = json.dumps(contacts).encode("utf-8")

    # -- unknown (c): multiplayer slots ------------------------------------

    def _start_mp_probe(self, base: dict[str, Any]) -> None:
        results: dict[str, Any] = {}
        try:
            total, active, controller = xp.countAircraft()
            results["count_aircraft"] = {
                "total": total,
                "active": active,
                "controller_plugin": controller,
            }
        except Exception as exc:
            results["count_aircraft"] = repr(exc)

        try:
            results["nth_aircraft_model_1"] = xp.getNthAircraftModel(1)
        except Exception as exc:
            results["nth_aircraft_model_1"] = repr(exc)

        try:
            self._mp_acquired = bool(xp.acquirePlanes())
            results["acquire_planes"] = self._mp_acquired
        except Exception as exc:
            results["acquire_planes"] = repr(exc)

        if self._mp_acquired:
            try:
                xp.setActiveAircraftCount(2)
                results["set_active_aircraft_count_2"] = True
            except Exception as exc:
                results["set_active_aircraft_count_2"] = repr(exc)
            try:
                xp.disableAIForPlane(1)
                results["disable_ai_for_plane_1"] = True
            except Exception as exc:
                results["disable_ai_for_plane_1"] = repr(exc)

        refs: dict[str, Any] = {}
        dataref_report: dict[str, Any] = {}
        for short, name in (
            ("x", "sim/multiplayer/position/plane1_x"),
            ("y", "sim/multiplayer/position/plane1_y"),
            ("z", "sim/multiplayer/position/plane1_z"),
            ("psi", "sim/multiplayer/position/plane1_psi"),
            ("v_x", "sim/multiplayer/position/plane1_v_x"),
        ):
            ref = xp.findDataRef(name)
            refs[short] = ref
            dataref_report[name] = {
                "exists": ref is not None,
                "writable": bool(ref is not None and xp.canWriteDataRef(ref)),
            }
        results["plane1_datarefs"] = dataref_report

        for name in (
            "sim/operation/override/override_TCAS",
            "sim/cockpit2/tcas/targets/modeS_id",
            "sim/cockpit2/tcas/targets/position/double/plane1_lat",
        ):
            ref = xp.findDataRef(name)
            entry: dict[str, Any] = {
                "exists": ref is not None,
                "writable": bool(ref is not None and xp.canWriteDataRef(ref)),
            }
            if ref is not None and name.endswith("modeS_id"):
                try:
                    entry["array_size"] = xp.getDatavi(ref, None)
                except Exception as exc:
                    entry["array_size"] = repr(exc)
            results[name] = entry

        written: dict[str, float] = {}
        try:
            user_x = xp.getDatad(self._user_refs["local_x"])
            user_y = xp.getDatad(self._user_refs["local_y"])
            user_z = xp.getDatad(self._user_refs["local_z"])
            written = {"x": user_x + 200.0, "y": user_y + 50.0, "z": user_z + 200.0, "psi": 123.0}
            xp.setDatad(refs["x"], written["x"])
            xp.setDatad(refs["y"], written["y"])
            xp.setDatad(refs["z"], written["z"])
            xp.setDataf(refs["psi"], written["psi"])
            results["write_attempted"] = True
        except Exception as exc:
            results["write_attempted"] = repr(exc)

        self._mp_probe = {
            "base": base,
            "results": results,
            "written": written,
            "refs": refs,
            "verify_at_loop": self.loop_count + MP_VERIFY_AFTER_LOOPS,
        }

    def _finish_mp_probe_if_due(self) -> None:
        probe = self._mp_probe
        if probe is None or self.loop_count < probe["verify_at_loop"]:
            return
        self._mp_probe = None
        results = probe["results"]
        refs = probe["refs"]
        written = probe["written"]
        if written:
            try:
                read_back = {
                    "x": xp.getDatad(refs["x"]),
                    "y": xp.getDatad(refs["y"]),
                    "z": xp.getDatad(refs["z"]),
                    "psi": xp.getDataf(refs["psi"]),
                }
                results["read_back_after_loops"] = MP_VERIFY_AFTER_LOOPS
                results["read_back"] = read_back
                results["deltas"] = {
                    key: round(read_back[key] - written[key], 6) for key in written
                }
            except Exception as exc:
                results["read_back"] = repr(exc)
        self._write_ack({**probe["base"], "ok": True, "mp_probe": results})

    # -- unknown (c): XPLMInstance -----------------------------------------

    def _op_probe_instance(self, base: dict[str, Any]) -> None:
        results: dict[str, Any] = {
            "sdk_has_create_instance": hasattr(xp, "createInstance"),
            "sdk_has_load_object": hasattr(xp, "loadObject"),
        }
        found: list[str] = []
        lookups: dict[str, int] = {}
        for candidate in INSTANCE_CANDIDATE_PATHS:
            try:
                count = xp.lookupObjects(candidate, 0.0, 0.0, lambda path, _ref: found.append(path))
            except Exception as exc:
                lookups[candidate] = -1
                results.setdefault("lookup_errors", {})[candidate] = repr(exc)
                continue
            lookups[candidate] = count
        results["lookup_counts"] = lookups
        results["first_real_paths"] = found[:3]

        if found:
            try:
                self._instance_obj = xp.loadObject(found[0])
                results["load_object"] = self._instance_obj is not None
            except Exception as exc:
                results["load_object"] = repr(exc)
            if self._instance_obj is not None:
                try:
                    self._instance = xp.createInstance(self._instance_obj)
                    user_x = xp.getDatad(self._user_refs["local_x"])
                    user_y = xp.getDatad(self._user_refs["local_y"])
                    user_z = xp.getDatad(self._user_refs["local_z"])
                    xp.instanceSetPosition(
                        self._instance, (user_x + 50.0, user_y + 5.0, user_z + 50.0, 0.0, 0.0, 0.0)
                    )
                    results["create_instance"] = True
                    results["instance_set_position"] = True
                    self._instance_destroy_at_loop = self.loop_count + 60
                except Exception as exc:
                    results["create_instance"] = repr(exc)
        self._write_ack({**base, "ok": bool(results.get("create_instance") is True), **results})

    def _destroy_instance_if_due(self) -> None:
        if (
            self._instance_destroy_at_loop is None
            or self.loop_count < self._instance_destroy_at_loop
        ):
            return
        self._instance_destroy_at_loop = None
        self._teardown_instance()

    # -- teardown ----------------------------------------------------------

    def _teardown_instance(self) -> None:
        if self._instance is not None:
            try:
                xp.destroyInstance(self._instance)
            except Exception as exc:
                xp.log(f"[OIS spike] destroyInstance failed: {exc!r}")
            self._instance = None
        if self._instance_obj is not None:
            try:
                xp.unloadObject(self._instance_obj)
            except Exception as exc:
                xp.log(f"[OIS spike] unloadObject failed: {exc!r}")
            self._instance_obj = None

    def _teardown_probes(self) -> None:
        self._teardown_instance()
        if self._mp_acquired:
            try:
                xp.releasePlanes()
            except Exception as exc:
                xp.log(f"[OIS spike] releasePlanes failed: {exc!r}")
            self._mp_acquired = False

    # -- plumbing ----------------------------------------------------------

    def _write_ack(self, ack: dict[str, Any]) -> None:
        self._ack.content = json.dumps(ack).encode("utf-8")
