"""OIS bridge — the optional XPPython3 plugin serving the AI Traffic Manager.

Production plugin (docs/designs/ai-traffic.md §5.1/§5.2, amended by the §10.4
spike findings of 2026-08-18). Installed by the user into
``<X-Plane 12>/Resources/plugins/PythonPlugins/`` — see ``bridge/README.md``.
The application never installs, launches or requires it: everything except AI
traffic works without this file existing (hard rule 1).

It registers the four §5.1 custom datarefs:

===========================  =====  ========  ==========================================
Dataref                      Type   Writable  Purpose
===========================  =====  ========  ==========================================
``ois/bridge/heartbeat_s``   float  no        seconds alive, advanced every flight loop
``ois/traffic/command``      data   yes       one pending JSON command (read-act-clear)
``ois/traffic/command_ack``  data   no        JSON ack for the last processed command
``ois/traffic/contacts``     data   no        JSON array of live entities, every loop
===========================  =====  ========  ==========================================

Protocol: request/poll, at most one command in flight (§5.1 — validated live at
~27 ms round trip, ack present on the first poll). Commands are ``spawn`` /
``despawn`` / ``clear_all``; the exact JSON shapes and every ack field are
documented in ``bridge/README.md`` so the adapter half
(``adapters/xplane/traffic_bridge.py``) is written against the same text.

Spawn mechanism (§10.4 findings): entities are **XPLMInstance objects** —
``lookupObjects`` → ``loadObject`` → ``createInstance`` →
``instanceSetPosition`` — for all three kinds. The legacy multiplayer-slot
route is dead on a real install (resident plugins hold the aircraft set;
writes do not stick). ``kind="aircraft"`` entities additionally get a
TCAS-target entry (``override_TCAS`` + ``modeS_id``), implemented but
**write-unverified**: every TCAS write is guarded so a failure degrades to
instance-only (visible, maybe not on TCAS), and ``tests/sim/`` owns the
read-back verdict.

Pure XPPython3 + stdlib. ``core/`` is deliberately NOT imported (§10.2 —
architecture.md draws no bridge→core edge): the few lines of track
interpolation are re-implemented below, mirroring
``core.traffic.interpolate_track`` semantics exactly and pinned against the
same §8.1 reference values in comments.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import Any

import xp

# ---------------------------------------------------------------------------
# §5.1 custom datarefs
# ---------------------------------------------------------------------------

HEARTBEAT_DATAREF = "ois/bridge/heartbeat_s"
COMMAND_DATAREF = "ois/traffic/command"
ACK_DATAREF = "ois/traffic/command_ack"
CONTACTS_DATAREF = "ois/traffic/contacts"

#: Fixed capacity the command buffer reports to X-Plane. The §10.4 spike found
#: no Web API payload ceiling up to (and past) this size; the realistic worst
#: case, an 8-waypoint approach_sequence spawn command, is ~1.6 kB.
COMMAND_CAPACITY_B = 65536

#: The ack buffer reports a fixed, NUL-padded size — the conservative style
#: that survives the Web API caching dataref sizes at index time.
ACK_CAPACITY_B = 16384

#: Bridge-enforced entity capacity — the source of truth for "how many slots
#: are actually free" (§5.4, D6). Stays at the designed 19 until a real
#: TCAS-target write has been exercised and read back under ``-m sim``; only
#: then may it be re-baselined toward the 64-entry TCAS table (§10.4).
MAX_ENTITIES = 19

# ---------------------------------------------------------------------------
# Object library candidates, per TrafficKind
# ---------------------------------------------------------------------------

#: Virtual library paths tried, in order, when an entity of each kind is first
#: spawned. The first path ``lookupObjects`` resolves wins and is cached for
#: the session. A kind with no resolvable path degrades honestly: the entity
#: still exists (tracked, published in contacts, TCAS-listed if aircraft) but
#: has no visual, and the spawn ack's ``error`` field says so (§10.4 — the tug
#: is proven to resolve; birds did not on the spike install; the aircraft
#: candidates are unvalidated guesses to be refined by the first live run).
OBJECT_CANDIDATE_PATHS: dict[str, tuple[str, ...]] = {
    "aircraft": (
        "lib/airport/aircraft/737-800.obj",
        "lib/airport/aircraft/747-400.obj",
        "lib/airport/aircraft/airliner.obj",
        "lib/airport/aircraft/ga_fixed.obj",
    ),
    "ground_vehicle": (
        # Resolved live on 2026-08-18 (→ Tug_GT110.obj) and instanced fine.
        "lib/airport/vehicles/pushback/tug.obj",
        "lib/airport/vehicles/baggage_handling/belt_loader.obj",
        "lib/airport/vehicles/servicing/fuel_truck.obj",
    ),
    "bird": (
        "lib/dynamic/birds/seagull.obj",
        "lib/dynamic/seagull.obj",
    ),
}

# ---------------------------------------------------------------------------
# TCAS-target datarefs (§10.4 — present and writable, writes unverified)
# ---------------------------------------------------------------------------

TCAS_OVERRIDE_DATAREF = "sim/operation/override/override_TCAS"
TCAS_MODES_ID_DATAREF = "sim/cockpit2/tcas/targets/modeS_id"
TCAS_PSI_DATAREF = "sim/cockpit2/tcas/targets/position/psi"
TCAS_SLOT_DOUBLE_TEMPLATE = "sim/cockpit2/tcas/targets/position/double/plane{slot}_{axis}"

#: TCAS target table size measured live (modeS_id is an int array of 64;
#: entry 0 is the user aircraft, so usable slots are 1..63).
TCAS_TABLE_SIZE = 64

#: Arbitrary private 24-bit Mode S base for bridge-owned targets; slot index
#: is added so every entry is unique and non-zero.
TCAS_MODES_ID_BASE = 0xA50000

# ---------------------------------------------------------------------------
# Geodesy — stdlib re-implementation (§10.2)
# ---------------------------------------------------------------------------

#: Mean Earth radius in nautical miles (6 371 000 m / 1 852 m). core/ computes
#: on the WGS-84 ellipsoid via geographiclib; this spherical mirror agrees to
#: well under 0.5% over the sub-20 NM legs every shipped builder produces.
_EARTH_RADIUS_NM = 3440.065

_SECONDS_PER_HOUR = 3600.0
_SECONDS_PER_MINUTE = 60.0
_M_PER_FT = 0.3048


def _distance_and_bearing_nm(
    lat1_deg: float, lon1_deg: float, lat2_deg: float, lon2_deg: float
) -> tuple[float, float]:
    """Great-circle distance (NM) and initial true bearing (deg) from 1 to 2.

    Mirrors ``core.geodesy.distance_and_bearing``'s contract (spherical here,
    ellipsoidal there — tolerance noted on ``_EARTH_RADIUS_NM``).
    """
    phi1 = math.radians(lat1_deg)
    phi2 = math.radians(lat2_deg)
    dphi = phi2 - phi1
    dlam = math.radians(lon2_deg - lon1_deg)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    distance_nm = 2.0 * _EARTH_RADIUS_NM * math.asin(min(1.0, math.sqrt(a)))
    y = math.sin(dlam) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    bearing_deg = math.degrees(math.atan2(y, x)) % 360.0
    return distance_nm, bearing_deg


def _point_at_nm(
    lat_deg: float, lon_deg: float, distance_nm: float, bearing_deg: float
) -> tuple[float, float]:
    """The point ``distance_nm`` from (lat, lon) along the initial ``bearing_deg``.

    Mirrors ``core.geodesy.point_at_distance_and_bearing``'s contract.
    """
    delta = distance_nm / _EARTH_RADIUS_NM
    theta = math.radians(bearing_deg)
    phi1 = math.radians(lat_deg)
    lam1 = math.radians(lon_deg)
    phi2 = math.asin(
        math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta)
    )
    lam2 = lam1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2),
    )
    return math.degrees(phi2), (math.degrees(lam2) + 540.0) % 360.0 - 180.0


# ---------------------------------------------------------------------------
# Track interpolation — mirror of core.traffic.interpolate_track (§6.1, §10.2)
# ---------------------------------------------------------------------------


def _leg_bearing_deg(a: dict[str, Any], b: dict[str, Any]) -> float | None:
    """Initial bearing of the leg a→b, or ``None`` for coincident points."""
    distance_nm, bearing_deg = _distance_and_bearing_nm(
        a["latitude"], a["longitude"], b["latitude"], b["longitude"]
    )
    return bearing_deg if distance_nm > 0.0 else None


def _heading_at_waypoint(waypoints: list[dict[str, Any]], index: int) -> float:
    """The heading an entity faces AT a waypoint — the exact fallback chain of
    ``core.traffic._heading_at_waypoint``: the stated heading, else the bearing
    to the next waypoint, else the previous leg's heading, else due north.
    """
    stated = waypoints[index].get("heading_deg")
    if stated is not None:
        return float(stated)
    if index + 1 < len(waypoints):
        bearing = _leg_bearing_deg(waypoints[index]["position"], waypoints[index + 1]["position"])
        if bearing is not None:
            return bearing
    if index > 0:
        bearing = _leg_bearing_deg(waypoints[index - 1]["position"], waypoints[index]["position"])
        if bearing is not None:
            return bearing
    return 0.0


def _sample_track(track: dict[str, Any], elapsed_s: float) -> dict[str, Any]:
    """Where a track-following entity is, ``elapsed_s`` after spawn.

    Semantics are ``core.traffic.interpolate_track``'s, re-implemented over the
    wire dict (§10.2 — the bridge does not import core/): at or past the last
    waypoint the entity holds it at ground speed 0; between two waypoints it
    advances along the geodesic at the CONSTANT speed implied by the pair's own
    distance and t_offset_s gap, never a blend of the waypoints' stated speeds;
    altitude is linear in time; heading follows the leg bearing, with the
    waypoint fallback chain at fraction 0; on_ground is the leg start's.

    Reference values this mirror must reproduce (§8.1, the same pins
    ``tests/core/test_traffic.py`` holds ``interpolate_track`` to, within the
    spherical-vs-WGS-84 tolerance noted on ``_EARTH_RADIUS_NM``): a leg from
    (40.0, -3.0) to a point 10 NM due east, reached at ``t_offset_s=180.0``, is
    flown at 10 / 180 x 3600 = 200.0 kt; at ``elapsed_s=90.0`` the entity is
    5.0 NM along on bearing ~= 90 deg; at 180.0 s (and any later time) it sits on
    the end waypoint exactly, ground speed 0.

    Additionally reports ``vertical_speed_fpm`` from the current leg's altitude
    slope — the contacts wire shape (§5.1) carries it and ``TrafficSample``
    does not, so it is derived here rather than invented adapter-side.
    """
    waypoints: list[dict[str, Any]] = track["waypoints"]
    last_index = len(waypoints) - 1
    if elapsed_s >= waypoints[last_index]["t_offset_s"]:
        last = waypoints[last_index]
        position = last["position"]
        return {
            "latitude": position["latitude"],
            "longitude": position["longitude"],
            "altitude_ft": position["altitude_ft"],
            "heading_deg": _heading_at_waypoint(waypoints, last_index),
            "ground_speed_kt": 0.0,
            "vertical_speed_fpm": 0.0,
            "on_ground": bool(last.get("on_ground", False)),
        }
    elapsed_s = max(elapsed_s, 0.0)

    # The leg the entity is on: the last waypoint at or before elapsed_s.
    index = 0
    for candidate in range(last_index):
        if waypoints[candidate]["t_offset_s"] <= elapsed_s:
            index = candidate
    start, end = waypoints[index], waypoints[index + 1]
    start_position, end_position = start["position"], end["position"]
    leg_time_s = end["t_offset_s"] - start["t_offset_s"]  # > 0, model-enforced upstream
    fraction = (elapsed_s - start["t_offset_s"]) / leg_time_s
    leg_distance_nm, leg_bearing_deg = _distance_and_bearing_nm(
        start_position["latitude"],
        start_position["longitude"],
        end_position["latitude"],
        end_position["longitude"],
    )

    if leg_distance_nm > 0.0:
        latitude, longitude = _point_at_nm(
            start_position["latitude"],
            start_position["longitude"],
            leg_distance_nm * fraction,
            leg_bearing_deg,
        )
        heading_deg = leg_bearing_deg if fraction > 0.0 else _heading_at_waypoint(waypoints, index)
    else:
        # A stationary gap in time: the entity waits at the waypoint (its
        # altitude may still interpolate — a climb in place).
        latitude, longitude = start_position["latitude"], start_position["longitude"]
        heading_deg = _heading_at_waypoint(waypoints, index)

    altitude_delta_ft = end_position["altitude_ft"] - start_position["altitude_ft"]
    return {
        "latitude": latitude,
        "longitude": longitude,
        "altitude_ft": start_position["altitude_ft"] + fraction * altitude_delta_ft,
        "heading_deg": heading_deg,
        "ground_speed_kt": leg_distance_nm / leg_time_s * _SECONDS_PER_HOUR,
        "vertical_speed_fpm": altitude_delta_ft / leg_time_s * _SECONDS_PER_MINUTE,
        "on_ground": bool(start.get("on_ground", False)),
    }


def _validate_track(track: Any) -> str | None:
    """A wire-level sanity check on a spawn command's track. Returns the
    refusal reason, or ``None`` when the track is actionable.

    Deliberately shallow: the station's own ``TrafficTrack`` model has already
    validated the real invariants before the JSON ever crossed the wire; this
    only refuses shapes the flight loop could not act on without crashing.
    """
    if not isinstance(track, dict):
        return "track must be an object"
    if track.get("kind") not in OBJECT_CANDIDATE_PATHS:
        return f"unknown kind {track.get('kind')!r}"
    waypoints = track.get("waypoints")
    if not isinstance(waypoints, list) or len(waypoints) < 2:
        return "track needs at least 2 waypoints"
    previous_t = -1.0
    for waypoint in waypoints:
        if not isinstance(waypoint, dict) or not isinstance(waypoint.get("position"), dict):
            return "every waypoint needs a position object"
        position = waypoint["position"]
        for key in ("latitude", "longitude", "altitude_ft"):
            if not isinstance(position.get(key), int | float):
                return f"waypoint position missing numeric {key!r}"
        t_offset_s = waypoint.get("t_offset_s")
        if not isinstance(t_offset_s, int | float):
            return "every waypoint needs a numeric t_offset_s"
        if t_offset_s <= previous_t:
            return "waypoints must be strictly increasing by t_offset_s"
        previous_t = float(t_offset_s)
    if waypoints[0]["t_offset_s"] != 0.0:
        return "waypoints[0].t_offset_s must be 0.0 — spawn is t=0"
    return None


# ---------------------------------------------------------------------------
# data-dataref backing store (productionised from the validated spike skeleton)
# ---------------------------------------------------------------------------


class DataBuffer:
    """Backing store for one ``data``-typed custom dataref.

    ``fixed`` set: reads always report ``capacity`` bytes, content NUL-padded —
    the style that survives the Web API caching dataref sizes at index time.
    ``fixed`` unset: reads report the current content length only (validated
    live for ``contacts`` in the §10.4 spike run).
    """

    def __init__(self, capacity: int, fixed: bool) -> None:
        self.capacity = capacity
        self.fixed = fixed
        self.content = b""
        self.dirty = False

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
        self.dirty = True


def _payload_of(raw: bytes) -> bytes:
    """The JSON payload of a buffer: everything before the first NUL."""
    return raw.split(b"\x00", 1)[0]


# ---------------------------------------------------------------------------
# TCAS-target table — guarded, degrade-to-instance-only (§10.4)
# ---------------------------------------------------------------------------


class TcasTargets:
    """Guarded writer for X-Plane's TCAS-target override.

    The §10.4 spike measured ``override_TCAS`` and ``modeS_id`` present and
    ``writable = true`` — and, in the same session, proved that ``writable``
    does not imply a write sticks (the multiplayer-slot result). So every
    write here is guarded: the first failure marks the whole table failed for
    the session and every aircraft entity degrades to instance-only — visible,
    maybe not on TCAS — with the degradation reported in the spawn ack.
    ``tests/sim/test_live_traffic.py`` owns the read-back verdict; nothing here
    claims the writes work, only that they are attempted safely.
    """

    def __init__(self) -> None:
        self.failed = False
        self.failure_reason: str | None = None
        self._override_ref: Any = None
        self._modes_ref: Any = None
        self._psi_ref: Any = None
        self._slots: dict[str, int] = {}  # traffic_id -> table index (1..63)
        self._slot_refs: dict[int, tuple[Any, Any, Any]] = {}

    def find_refs(self) -> None:
        try:
            self._override_ref = xp.findDataRef(TCAS_OVERRIDE_DATAREF)
            self._modes_ref = xp.findDataRef(TCAS_MODES_ID_DATAREF)
            self._psi_ref = xp.findDataRef(TCAS_PSI_DATAREF)  # optional; None tolerated
        except Exception as exc:
            self._fail(f"findDataRef raised: {exc!r}")
            return
        if self._override_ref is None or self._modes_ref is None:
            self._fail("override_TCAS / modeS_id datarefs not found")

    def _fail(self, reason: str) -> None:
        if not self.failed:
            self.failed = True
            self.failure_reason = reason
            xp.log(f"[OIS bridge] TCAS-target writes disabled for this session: {reason}")

    def _position_refs(self, slot: int) -> tuple[Any, Any, Any] | None:
        cached = self._slot_refs.get(slot)
        if cached is not None:
            return cached
        refs = tuple(
            xp.findDataRef(TCAS_SLOT_DOUBLE_TEMPLATE.format(slot=slot, axis=axis))
            for axis in ("lat", "lon", "ele")
        )
        if any(ref is None for ref in refs):
            return None  # this slot is unusable; not a whole-table failure
        self._slot_refs[slot] = (refs[0], refs[1], refs[2])
        return self._slot_refs[slot]

    def acquire(self, traffic_id: str) -> bool:
        """Take a free table slot for an entity. False = degrade to instance-only."""
        if self.failed:
            return False
        used = set(self._slots.values())
        slot = next((s for s in range(1, TCAS_TABLE_SIZE) if s not in used), None)
        if slot is None or self._position_refs(slot) is None:
            return False
        try:
            xp.setDatavi(self._modes_ref, [TCAS_MODES_ID_BASE + slot], slot)
            xp.setDatai(self._override_ref, 1)
        except Exception as exc:
            self._fail(f"modeS_id/override write raised: {exc!r}")
            return False
        self._slots[traffic_id] = slot
        return True

    def update(
        self, traffic_id: str, latitude: float, longitude: float, elevation_m: float, psi_deg: float
    ) -> None:
        slot = self._slots.get(traffic_id)
        if slot is None or self.failed:
            return
        refs = self._position_refs(slot)
        if refs is None:
            return
        lat_ref, lon_ref, ele_ref = refs
        try:
            xp.setDatad(lat_ref, latitude)
            xp.setDatad(lon_ref, longitude)
            xp.setDatad(ele_ref, elevation_m)
            if self._psi_ref is not None:
                xp.setDatavf(self._psi_ref, [psi_deg], slot)
        except Exception as exc:
            self._fail(f"target position write raised: {exc!r}")

    def release(self, traffic_id: str) -> None:
        slot = self._slots.pop(traffic_id, None)
        if slot is None or self.failed:
            return
        try:
            xp.setDatavi(self._modes_ref, [0], slot)
            if not self._slots:
                xp.setDatai(self._override_ref, 0)
        except Exception as exc:
            self._fail(f"target release write raised: {exc!r}")

    def release_all(self) -> None:
        for traffic_id in list(self._slots):
            self.release(traffic_id)


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


@dataclass
class Entity:
    """One live traffic entity the bridge is driving."""

    traffic_id: str
    track: dict[str, Any]
    kind: str
    callsign: str
    spawned_hb: float
    instance: Any = None
    has_tcas_slot: bool = False
    last_sample: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


class PythonInterface:
    """XPPython3 entry point."""

    def __init__(self) -> None:
        self._accessors: list[Any] = []
        self._flight_loop_id: Any = None
        self._t0 = 0.0
        self.heartbeat_s = 0.0
        self._command = DataBuffer(COMMAND_CAPACITY_B, fixed=True)
        self._ack = DataBuffer(ACK_CAPACITY_B, fixed=True)
        self._contacts = DataBuffer(0, fixed=False)
        self._entities: dict[str, Entity] = {}
        self._tcas = TcasTargets()
        #: kind -> loaded object handle, or None after every candidate missed.
        self._objects: dict[str, Any] = {}
        #: kind -> the real path that resolved (None recorded on a full miss).
        self._object_paths: dict[str, str | None] = {}
        self._probe: Any = None
        self._probe_failed = False
        self._last_loop_error: str | None = None

    # -- XPPython3 lifecycle ----------------------------------------------

    def XPluginStart(self) -> tuple[str, str, str]:
        # Accessors are registered at Start, before any flight loads: the Web
        # API indexes datarefs at startup, so a later registration would be
        # invisible to the station (§10.4 findings, carried-forward caveat).
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
        xp.log("[OIS bridge] datarefs registered")
        return (
            "OIS Bridge",
            "ois.bridge",
            "Open Instructor Station AI-traffic bridge (optional add-on)",
        )

    def XPluginEnable(self) -> int:
        self._tcas.find_refs()
        try:
            self._probe = xp.createProbe(xp.ProbeY)
        except Exception as exc:
            self._probe = None
            xp.log(f"[OIS bridge] terrain probe unavailable: {exc!r}")
        self._flight_loop_id = xp.createFlightLoop(self._flight_loop)
        xp.scheduleFlightLoop(self._flight_loop_id, -1.0)
        xp.log("[OIS bridge] flight loop scheduled (every frame)")
        return 1

    def XPluginDisable(self) -> None:
        if self._flight_loop_id is not None:
            xp.destroyFlightLoop(self._flight_loop_id)
            self._flight_loop_id = None
        self._clear_all_entities()
        if self._probe is not None:
            try:
                xp.destroyProbe(self._probe)
            except Exception as exc:
                xp.log(f"[OIS bridge] destroyProbe failed: {exc!r}")
            self._probe = None

    def XPluginStop(self) -> None:
        for kind, handle in self._objects.items():
            if handle is not None:
                try:
                    xp.unloadObject(handle)
                except Exception as exc:
                    xp.log(f"[OIS bridge] unloadObject({kind}) failed: {exc!r}")
        self._objects.clear()
        for accessor in self._accessors:
            xp.unregisterDataAccessor(accessor)
        self._accessors.clear()
        xp.log("[OIS bridge] stopped")

    def XPluginReceiveMessage(self, _from: int, _message: int, _param: Any) -> None:
        pass

    # -- Flight loop -------------------------------------------------------

    def _flight_loop(self, _since: float, _elapsed: float, _counter: int, _ref: Any) -> float:
        self.heartbeat_s = time.monotonic() - self._t0
        if self._command.dirty:
            self._command.dirty = False
            raw = self._command.content
            self._command.content = b""  # read once, act, clear (§5.1)
            try:
                self._process_command(raw)
            except Exception as exc:
                # A command that blew up still gets an ack — the adapter's
                # poll must never wait a full timeout on a bridge-side bug.
                self._write_ack({"seq": None, "traffic_id": None, "ok": False, "error": repr(exc)})
        try:
            self._advance_and_publish()
        except Exception as exc:
            # Never let a drive-loop bug kill the flight loop; log throttled
            # (once per distinct error, not once per frame at 60 fps).
            message = repr(exc)
            if message != self._last_loop_error:
                self._last_loop_error = message
                xp.log(f"[OIS bridge] entity drive error: {message}")
        return -1.0

    # -- Command processing (§5.1: spawn / despawn / clear_all) ------------

    def _process_command(self, raw: bytes) -> None:
        payload = _payload_of(raw)
        try:
            command = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            self._write_ack(
                {
                    "seq": None,
                    "traffic_id": None,
                    "ok": False,
                    "error": f"undecodable command: {exc!r}",
                }
            )
            return

        op = command.get("op")
        base = {
            "seq": command.get("seq"),
            "op": op,
            "traffic_id": command.get("traffic_id"),
            "heartbeat_s": self.heartbeat_s,
        }
        if op == "spawn":
            self._op_spawn(base, command)
        elif op == "despawn":
            self._op_despawn(base, command)
        elif op == "clear_all":
            count = len(self._entities)
            self._clear_all_entities()
            self._write_ack({**base, "ok": True, "error": None, "despawned": count})
        else:
            self._write_ack({**base, "ok": False, "error": f"unknown op {op!r}"})

    def _op_spawn(self, base: dict[str, Any], command: dict[str, Any]) -> None:
        traffic_id = command.get("traffic_id")
        track = command.get("track")
        if not isinstance(traffic_id, str) or not traffic_id:
            self._write_ack({**base, "ok": False, "error": "spawn needs a traffic_id"})
            return
        refusal = _validate_track(track)
        if refusal is not None:
            self._write_ack({**base, "ok": False, "error": refusal})
            return
        assert isinstance(track, dict)  # narrowed by _validate_track
        if traffic_id in self._entities:
            self._write_ack(
                {**base, "ok": False, "error": f"traffic_id {traffic_id!r} already exists"}
            )
            return
        if len(self._entities) >= MAX_ENTITIES:
            # §5.4/D6: the bridge is the source of truth for capacity; the
            # adapter turns error_kind == "capacity" into TrafficCapacityExceeded.
            self._write_ack(
                {
                    **base,
                    "ok": False,
                    "error": (
                        f"capacity: {len(self._entities)} of {MAX_ENTITIES} traffic slots in use"
                    ),
                    "error_kind": "capacity",
                    "capacity": MAX_ENTITIES,
                    "active_count": len(self._entities),
                }
            )
            return

        kind = str(track["kind"])
        callsign = str(track.get("callsign") or traffic_id[:8])
        degradations: list[str] = []

        first_position = track["waypoints"][0]["position"]
        handle, object_path = self._resolve_object(
            kind, first_position["latitude"], first_position["longitude"]
        )
        instance: Any = None
        if handle is None:
            degradations.append(
                f"no library object resolved for kind {kind!r} — entity has no visual"
            )
        else:
            try:
                instance = xp.createInstance(handle)
            except Exception as exc:
                degradations.append(f"createInstance failed: {exc!r} — entity has no visual")

        has_tcas_slot = False
        if kind == "aircraft":
            has_tcas_slot = self._tcas.acquire(traffic_id)
            if not has_tcas_slot:
                reason = self._tcas.failure_reason or "no free TCAS-target slot"
                degradations.append(f"no TCAS-target entry ({reason}) — may not appear on TCAS")

        entity = Entity(
            traffic_id=traffic_id,
            track=track,
            kind=kind,
            callsign=callsign,
            spawned_hb=self.heartbeat_s,
            instance=instance,
            has_tcas_slot=has_tcas_slot,
        )
        self._entities[traffic_id] = entity
        self._drive_entity(entity, 0.0)  # place it this very frame

        # A degraded spawn is still a spawn: ok stays True (the entity exists,
        # moves and is reported); the error field carries the honest caveat.
        self._write_ack(
            {
                **base,
                "ok": True,
                "error": "; ".join(degradations) if degradations else None,
                "object_path": object_path,
                "tcas_target": has_tcas_slot,
            }
        )

    def _op_despawn(self, base: dict[str, Any], command: dict[str, Any]) -> None:
        traffic_id = command.get("traffic_id")
        if not isinstance(traffic_id, str) or not traffic_id:
            self._write_ack({**base, "ok": False, "error": "despawn needs a traffic_id"})
            return
        existed = self._despawn_entity(traffic_id)
        # Idempotent by design (§4.1): an unknown or already-gone id is a
        # no-op, acked ok=True — the adapter never raises for it.
        self._write_ack({**base, "ok": True, "error": None, "existed": existed})

    # -- Entity lifecycle --------------------------------------------------

    def _resolve_object(
        self, kind: str, latitude: float, longitude: float
    ) -> tuple[Any, str | None]:
        """The loaded object handle for a kind, resolving and caching on first use."""
        if kind in self._objects:
            return self._objects[kind], self._object_paths[kind]
        found: list[str] = []

        def _collect(path: str, _ref: Any) -> None:
            found.append(path)

        for candidate in OBJECT_CANDIDATE_PATHS[kind]:
            try:
                xp.lookupObjects(candidate, latitude, longitude, _collect)
            except Exception as exc:
                xp.log(f"[OIS bridge] lookupObjects({candidate!r}) failed: {exc!r}")
            if found:
                break
        handle: Any = None
        path: str | None = None
        if found:
            path = found[0]
            try:
                handle = xp.loadObject(path)
            except Exception as exc:
                xp.log(f"[OIS bridge] loadObject({path!r}) failed: {exc!r}")
                handle, path = None, None
        self._objects[kind] = handle
        self._object_paths[kind] = path
        return handle, path

    def _despawn_entity(self, traffic_id: str) -> bool:
        entity = self._entities.pop(traffic_id, None)
        if entity is None:
            return False
        if entity.instance is not None:
            try:
                xp.destroyInstance(entity.instance)
            except Exception as exc:
                xp.log(f"[OIS bridge] destroyInstance({traffic_id}) failed: {exc!r}")
            entity.instance = None
        if entity.has_tcas_slot:
            self._tcas.release(traffic_id)
            entity.has_tcas_slot = False
        return True

    def _clear_all_entities(self) -> None:
        for traffic_id in list(self._entities):
            self._despawn_entity(traffic_id)

    def _drive_entity(self, entity: Entity, elapsed_s: float) -> None:
        """Sample the entity's track and push the result into the sim."""
        sample = _sample_track(entity.track, elapsed_s)
        entity.last_sample = sample
        elevation_m = sample["altitude_ft"] * _M_PER_FT
        x, y, z = xp.worldToLocal(sample["latitude"], sample["longitude"], elevation_m)
        if sample["on_ground"]:
            y = self._terrain_y(x, y, z)
        if entity.instance is not None:
            xp.instanceSetPosition(entity.instance, (x, y, z, 0.0, sample["heading_deg"], 0.0))
        if entity.has_tcas_slot:
            self._tcas.update(
                entity.traffic_id,
                sample["latitude"],
                sample["longitude"],
                elevation_m,
                sample["heading_deg"],
            )

    def _terrain_y(self, x: float, y: float, z: float) -> float:
        """Local-frame terrain height under (x, z), falling back to the track's
        own altitude — an on_ground waypoint carries the navdata elevation,
        which can sit metres off X-Plane's mesh, and a runway-incursion vehicle
        floating above (or buried in) the runway defeats the scenario.
        """
        if self._probe is None or self._probe_failed:
            return y
        try:
            info = xp.probeTerrainXYZ(self._probe, x, y, z)
            if info.result == xp.ProbeHitTerrain:
                return float(info.locationY)
        except Exception as exc:
            self._probe_failed = True
            xp.log(f"[OIS bridge] terrain probe failed, using track altitudes: {exc!r}")
        return y

    # -- contacts (§5.1: TrafficContact minus label/scenario_shape) ---------

    def _advance_and_publish(self) -> None:
        contacts: list[dict[str, Any]] = []
        for entity in list(self._entities.values()):
            elapsed_s = self.heartbeat_s - entity.spawned_hb
            despawn_after_s = entity.track.get("despawn_after_s")
            last_t = entity.track["waypoints"][-1]["t_offset_s"]
            if despawn_after_s is not None and elapsed_s >= last_t + float(despawn_after_s):
                self._despawn_entity(entity.traffic_id)
                continue
            self._drive_entity(entity, elapsed_s)
            sample = entity.last_sample
            contacts.append(
                {
                    "traffic_id": entity.traffic_id,
                    "kind": entity.kind,
                    "callsign": entity.callsign,
                    "latitude": sample["latitude"],
                    "longitude": sample["longitude"],
                    "altitude_ft": sample["altitude_ft"],
                    "heading_deg": sample["heading_deg"],
                    "ground_speed_kt": sample["ground_speed_kt"],
                    "vertical_speed_fpm": sample["vertical_speed_fpm"],
                    "on_ground": sample["on_ground"],
                }
            )
        self._contacts.content = json.dumps(contacts).encode("utf-8")

    # -- plumbing ----------------------------------------------------------

    def _write_ack(self, ack: dict[str, Any]) -> None:
        self._ack.content = json.dumps(ack).encode("utf-8")
