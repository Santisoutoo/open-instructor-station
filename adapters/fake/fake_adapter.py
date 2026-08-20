"""``FakeSimAdapter`` — the reference implementation of the simulator contract.

This adapter is the yardstick: it declares **every** capability and implements
the whole protocol in memory, so the contract suite in
``tests/adapters/test_contract.py`` can define what "correct" means without a
simulator. All CI runs against it.

It performs no I/O whatsoever and is safe to import and construct anywhere.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from core.failures import (
    FAILURE_CATALOGUE,
    FAILURE_IDS,
    ActiveFailure,
    FailureId,
    FailureRef,
    FailureSupport,
    FailureSupportManifest,
)
from core.geodesy import point_at_distance_and_bearing
from core.models import (
    AircraftSetup,
    AircraftState,
    AirframeInfo,
    GeoPosition,
    LightsSetup,
    Loadout,
    LoadoutState,
    PayloadStation,
    TankFuel,
)
from core.sim_adapter import Capabilities, CapabilityNotSupported, SimAdapter
from core.traffic import (
    SECONDS_PER_HOUR,
    TrafficCapacityExceeded,
    TrafficContact,
    TrafficTrack,
    interpolate_track,
)
from core.weather.models import WeatherSetup, WeatherState, WindLayer

__all__ = ["FakeSimAdapter"]

#: Somewhere over Madrid Barajas (LEMD), 3000 ft, heading north at 250 kt.
DEFAULT_STATE = AircraftState(
    latitude=40.4936,
    longitude=-3.5668,
    altitude_ft=3000.0,
    heading_deg=0.0,
    ias_kt=250.0,
    vertical_speed_fpm=0.0,
    pitch_deg=0.0,
    roll_deg=0.0,
    on_ground=False,
)

#: A fully-populated CAVOK-ish day (weather-manager.md §5.2): one wind layer,
#: no clouds, ISA-ish sea-level numbers.
DEFAULT_WEATHER = WeatherState(
    wind_layers=[WindLayer(altitude_ft=0.0, direction_deg=270.0, speed_kt=8.0)],
    cloud_layers=[],
    visibility_m=20_000.0,
    qnh_hpa=1013.25,
    temperature_c=15.0,
    dewpoint_c=5.0,
    precipitation_ratio=0.0,
    runway_contamination="dry",
)

#: Two tanks, one occupied station (fuel-payload.md §5.2) — plausible,
#: distinctive, constructor-settable.
DEFAULT_LOADOUT = LoadoutState(
    tanks=[
        TankFuel(tank_index=0, fuel_kg=38.0),
        TankFuel(tank_index=1, fuel_kg=38.0),
    ],
    stations=[
        PayloadStation(station_index=0, kind="crew", label="Pilot", weight_kg=90.0),
    ],
)

_ALL_CAPABILITIES = Capabilities(
    can_set_position=True,
    can_set_aircraft_state=True,
    can_set_weather=True,
    can_inject_failures=True,
    can_spawn_traffic=True,
    can_control_autopilot=True,
    can_set_fuel_payload=True,
    can_control_camera=True,
    can_pushback=True,
)

_SECONDS_PER_MINUTE = 60.0

#: The Fake's own traffic capacity (ai-traffic.md §4.4). Chosen to mirror
#: X-Plane's real multiplayer-slot limit **for test realism only**: capacity is
#: adapter-owned (D6), so this is the Fake's own picked constant, not a value
#: read from ``core/traffic.py`` — and not one any other adapter inherits.
_FAKE_MAX_TRAFFIC = 19

#: How far apart the two samples of the finite-difference vertical speed are.
_VERTICAL_SPEED_SAMPLE_GAP_S = 1.0


@dataclass(frozen=True)
class _FakeTrafficEntity:
    """One spawned entity: its track and when the Fake's clock started it.

    Everything a :class:`~core.traffic.TrafficContact` needs that is not
    derived by :func:`~core.traffic.interpolate_track` — kind, scenario shape,
    callsign, label — already travels on the track itself; only the
    adapter-assigned id and the spawn instant live here.
    """

    traffic_id: str
    track: TrafficTrack
    spawned_at_monotonic: float


class FakeSimAdapter:
    """A simulator that lives entirely in a Python object.

    The aircraft flies: every :meth:`stream_state` tick advances it along its
    current heading at its current airspeed and applies its vertical speed, so
    a client watching the WebSocket can tell a live stream from a frozen one.
    """

    def __init__(
        self,
        initial_state: AircraftState | None = None,
        airframe: AirframeInfo | None = None,
        weather: WeatherState | None = None,
        loadout: LoadoutState | None = None,
    ) -> None:
        self._state = (initial_state or DEFAULT_STATE).model_copy(deep=True)
        self._connected = False
        # Non-flight settings the fake accepts and remembers so that
        # ``apply_setup`` is observably faithful.
        self._setup = AircraftSetup()
        # What get_airframe() reports. Constructor-settable so tests can hand
        # the fake a specific aircraft; the default is the honest "unknown".
        self._airframe = airframe or AirframeInfo()
        # What get_weather() reports; set_weather() merges into this.
        self._weather = (weather or DEFAULT_WEATHER).model_copy(deep=True)
        # What get_loadout() reports; apply_setup(loadout=...) replaces into this.
        self._loadout = (loadout or DEFAULT_LOADOUT).model_copy(deep=True)
        # Active failures, keyed by (failure_id, engine_index). No physics —
        # this ledger IS the fake's observable failure behaviour.
        self._failures: set[tuple[FailureId, int | None]] = set()
        # Spawned traffic, keyed by traffic_id. Contacts are derived from each
        # entity's track at read time (interpolate_track), never stored.
        self._traffic: dict[str, _FakeTrafficEntity] = {}

    # -- Identity ---------------------------------------------------------

    @property
    def name(self) -> str:
        """Adapter identifier."""
        return "fake"

    @property
    def capabilities(self) -> Capabilities:
        """Everything is supported — this is the reference implementation."""
        return _ALL_CAPABILITIES

    @property
    def is_connected(self) -> bool:
        """True between :meth:`connect` and :meth:`disconnect`."""
        return self._connected

    @property
    def applied_setup(self) -> AircraftSetup:
        """The accumulated result of every :meth:`apply_setup` call so far.

        Not part of the ``SimAdapter`` protocol — a test affordance that lets
        the contract suite check non-flight fields (lights, radios, gear) that
        do not surface in :class:`~core.models.AircraftState`.
        """
        return self._setup.model_copy(deep=True)

    # -- Lifecycle --------------------------------------------------------

    async def connect(self) -> None:
        """Mark the adapter connected. Idempotent, no I/O."""
        self._connected = True

    async def disconnect(self) -> None:
        """Mark the adapter disconnected. Idempotent, never raises."""
        self._connected = False

    # -- Reads ------------------------------------------------------------

    async def get_aircraft_state(self) -> AircraftState:
        """Return a copy of the current in-memory aircraft state."""
        return self._state.model_copy(deep=True)

    async def get_airframe(self) -> AirframeInfo:
        """The airframe handed to the constructor, or the all-``None`` default."""
        return self._airframe

    async def get_weather(self) -> WeatherState:
        """Return a copy of the current in-memory commanded weather."""
        if not self.capabilities.can_set_weather:
            raise CapabilityNotSupported(self.name, "can_set_weather")
        return self._weather.model_copy(deep=True)

    async def get_failure_support(self) -> FailureSupportManifest:
        """Every catalogue entry, supported iff this adapter declares the flag.

        A capability-free read (failures-manager.md D4): "no" is an answer,
        never an exception, so an adapter without ``can_inject_failures``
        still answers — every entry unsupported, with a stated reason.
        """
        supported = self.capabilities.can_inject_failures
        reason = None if supported else f"{self.name!r} does not declare can_inject_failures."
        return FailureSupportManifest(
            caveat=None,
            entries=tuple(
                FailureSupport(failure_id=spec.failure_id, supported=supported, reason=reason)
                for spec in FAILURE_CATALOGUE
            ),
        )

    async def get_active_failures(self) -> tuple[ActiveFailure, ...]:
        """The in-memory failure ledger, in catalogue order then engine index.

        A capability-free read: an adapter that cannot see failures returns
        ``()`` rather than raising.
        """
        if not self.capabilities.can_inject_failures:
            return ()
        order = {failure_id: index for index, failure_id in enumerate(FAILURE_IDS)}
        ordered = sorted(
            self._failures,
            key=lambda ref: (order[ref[0]], ref[1] if ref[1] is not None else 0),
        )
        return tuple(
            ActiveFailure(failure_id=failure_id, engine_index=engine_index)
            for failure_id, engine_index in ordered
        )

    async def get_loadout(self) -> LoadoutState:
        """Return a copy of the current in-memory loadout."""
        if not self.capabilities.can_set_fuel_payload:
            raise CapabilityNotSupported(self.name, "can_set_fuel_payload")
        return self._loadout.model_copy(deep=True)

    # -- Writes -----------------------------------------------------------

    async def set_weather(self, setup: WeatherSetup) -> None:
        """Merge every field of ``setup`` that is set into the in-memory weather.

        Scalars overlay when not ``None``; ``wind_layers``/``cloud_layers``
        replace wholesale when provided, including ``[]``. The merged dump is
        **re-validated** through ``WeatherState.model_validate`` rather than
        ``model_copy(update=...)`` — the weather design's own recorded lesson
        about the position router's merge bug (an unvalidated dict surviving
        to the adapter).
        """
        if not self.capabilities.can_set_weather:
            raise CapabilityNotSupported(self.name, "can_set_weather")
        merged = {**self._weather.model_dump(), **setup.model_dump(exclude_none=True)}
        self._weather = WeatherState.model_validate(merged)

    async def inject_failure(self, failure: FailureRef) -> None:
        """Fail the referenced system. Idempotent."""
        if not self.capabilities.can_inject_failures:
            raise CapabilityNotSupported(self.name, "can_inject_failures")
        self._failures.add((failure.failure_id, failure.engine_index))

    async def clear_failure(self, failure: FailureRef) -> None:
        """Repair the referenced system. Idempotent."""
        if not self.capabilities.can_inject_failures:
            raise CapabilityNotSupported(self.name, "can_inject_failures")
        self._failures.discard((failure.failure_id, failure.engine_index))

    async def clear_all_failures(self) -> None:
        """Repair every failure. Idempotent."""
        if not self.capabilities.can_inject_failures:
            raise CapabilityNotSupported(self.name, "can_inject_failures")
        self._failures.clear()

    async def set_position(
        self,
        position: GeoPosition,
        heading_deg: float,
        *,
        ias_kt: float | None = None,
        vertical_speed_fpm: float | None = None,
    ) -> None:
        """Teleport the in-memory aircraft.

        Args:
            position: Target position; ``altitude_ft`` is applied as MSL.
            heading_deg: Target true heading in degrees.
            ias_kt: Indicated airspeed to arrive at. ``None`` keeps the current
                one, which for the Fake means literally leaving the field alone.
            vertical_speed_fpm: Vertical speed to arrive with, positive up.
                ``None`` arrives **level**, not "keep the current one": the
                velocity vector a teleport writes is the whole velocity, and an
                aircraft placed without a stated descent is placed in level
                flight (see :meth:`core.sim_adapter.SimAdapter.set_position`).
        """
        updates: dict[str, Any] = {
            "latitude": position.latitude,
            "longitude": position.longitude,
            "altitude_ft": position.altitude_ft,
            "heading_deg": heading_deg % 360.0,
            "vertical_speed_fpm": vertical_speed_fpm if vertical_speed_fpm is not None else 0.0,
        }
        if ias_kt is not None:
            updates["ias_kt"] = ias_kt
        self._state = self._state.model_copy(update=updates)

    async def apply_setup(self, setup: AircraftSetup) -> None:
        """Apply every field of ``setup`` that is set, leaving the rest untouched.

        Raises:
            CapabilityNotSupported: for ``gross_weight_kg``/``fuel_kg``/``loadout``
                when this adapter does not declare ``can_set_fuel_payload`` — the
                whole call is refused, never half-applied, matching the real
                adapter's precedent for the same field group.
        """
        if not self.capabilities.can_set_fuel_payload and (
            setup.gross_weight_kg is not None
            or setup.fuel_kg is not None
            or setup.loadout is not None
        ):
            raise CapabilityNotSupported(self.name, "can_set_fuel_payload")

        provided = setup.model_dump(exclude_none=True)

        state_updates: dict[str, Any] = {
            field: provided[field]
            for field in (
                "altitude_ft",
                "ias_kt",
                "vertical_speed_fpm",
                "heading_deg",
                "pitch_deg",
                "roll_deg",
            )
            if field in provided
        }
        if "heading_deg" in state_updates:
            state_updates["heading_deg"] = float(state_updates["heading_deg"]) % 360.0
        if state_updates:
            self._state = self._state.model_copy(update=state_updates)

        self._setup = self._merge_setup(self._setup, setup)

        if setup.loadout is not None:
            loadout_updates = {
                field: value
                for field, value in (
                    ("tanks", setup.loadout.tanks),
                    ("stations", setup.loadout.stations),
                )
                if value is not None
            }
            if loadout_updates:
                self._loadout = self._loadout.model_copy(update=loadout_updates)

    @staticmethod
    def _merge_setup(current: AircraftSetup, incoming: AircraftSetup) -> AircraftSetup:
        """Overlay the set fields of ``incoming`` onto ``current``.

        Driven entirely by ``model_dump(exclude_none=True)``, so a scalar field
        added to :class:`~core.models.AircraftSetup` — the whole autopilot block
        of issue #41, for instance — is carried here with no change to this
        adapter. ``lights`` is the one exception, and only because a nested model
        has to be merged rather than replaced.
        """
        updates = incoming.model_dump(exclude_none=True)
        if "lights" in updates and current.lights is not None:
            lights = incoming.lights
            merged_lights = current.lights.model_dump()
            if lights is not None:
                merged_lights.update(lights.model_dump(exclude_none=True))
            updates["lights"] = LightsSetup(**merged_lights)
        elif "lights" in updates:
            updates["lights"] = incoming.lights
        if "loadout" in updates and current.loadout is not None:
            loadout = incoming.loadout
            merged_loadout = current.loadout.model_dump()
            if loadout is not None:
                merged_loadout.update(loadout.model_dump(exclude_none=True))
            updates["loadout"] = Loadout(**merged_loadout)
        elif "loadout" in updates:
            updates["loadout"] = incoming.loadout
        return current.model_copy(update=updates)

    # -- AI traffic -------------------------------------------------------

    async def get_traffic_contacts(self) -> tuple[TrafficContact, ...]:
        """Every live entity, sampled off its track at the Fake's own clock.

        A capability-free read: an adapter that cannot spawn traffic reports
        ``()`` rather than raising. An entity whose ``despawn_after_s`` has
        elapsed is dropped from the ledger as part of this read — lazy expiry,
        no background task, matching the Fake's "no physics beyond what it is
        asked to report" philosophy already used for failures.
        """
        if not self.capabilities.can_spawn_traffic:
            return ()
        now = monotonic()
        contacts: list[TrafficContact] = []
        for traffic_id, entity in list(self._traffic.items()):
            elapsed_s = now - entity.spawned_at_monotonic
            despawn_after_s = entity.track.despawn_after_s
            if (
                despawn_after_s is not None
                and elapsed_s >= entity.track.waypoints[-1].t_offset_s + despawn_after_s
            ):
                del self._traffic[traffic_id]
                continue
            contacts.append(self._contact_at(entity, elapsed_s))
        return tuple(contacts)

    async def spawn_traffic(self, track: TrafficTrack) -> TrafficContact:
        """Record one entity and return its initial contact — exactly ``waypoints[0]``.

        Raises:
            CapabilityNotSupported: without ``can_spawn_traffic``.
            TrafficCapacityExceeded: at :data:`_FAKE_MAX_TRAFFIC` entities — the
                Fake's own limit (ai-traffic.md D6), never a ``core/`` constant.
        """
        if not self.capabilities.can_spawn_traffic:
            raise CapabilityNotSupported(self.name, "can_spawn_traffic")
        if len(self._traffic) >= _FAKE_MAX_TRAFFIC:
            raise TrafficCapacityExceeded(self.name, _FAKE_MAX_TRAFFIC, len(self._traffic))
        entity = _FakeTrafficEntity(
            traffic_id=uuid4().hex,
            track=track,
            spawned_at_monotonic=monotonic(),
        )
        self._traffic[entity.traffic_id] = entity
        return self._contact_at(entity, 0.0)

    async def despawn_traffic(self, traffic_id: str) -> None:
        """Remove one entity. Idempotent — an unknown id is a no-op, not an error."""
        if not self.capabilities.can_spawn_traffic:
            raise CapabilityNotSupported(self.name, "can_spawn_traffic")
        self._traffic.pop(traffic_id, None)

    async def clear_all_traffic(self) -> None:
        """Despawn everything. Idempotent."""
        if not self.capabilities.can_spawn_traffic:
            raise CapabilityNotSupported(self.name, "can_spawn_traffic")
        self._traffic.clear()

    def _contact_at(self, entity: _FakeTrafficEntity, elapsed_s: float) -> TrafficContact:
        """One entity's contact, ``elapsed_s`` after its spawn.

        Position, heading, speed and ground flag come straight from
        :func:`~core.traffic.interpolate_track` — the shared reference
        implementation (ai-traffic.md D9). The vertical speed the sample does
        not carry is derived the honest way: a finite difference of the track's
        own interpolated altitude, so a descending approach-sequence aircraft
        reports the descent it is actually flying.
        """
        sample = interpolate_track(entity.track, elapsed_s)
        ahead = interpolate_track(entity.track, elapsed_s + _VERTICAL_SPEED_SAMPLE_GAP_S)
        vertical_speed_fpm = (
            (ahead.position.altitude_ft - sample.position.altitude_ft)
            / _VERTICAL_SPEED_SAMPLE_GAP_S
            * _SECONDS_PER_MINUTE
        )
        return TrafficContact(
            traffic_id=entity.traffic_id,
            kind=entity.track.kind,
            scenario_shape=entity.track.scenario_shape,
            callsign=entity.track.callsign,
            label=entity.track.label,
            latitude=sample.position.latitude,
            longitude=sample.position.longitude,
            altitude_ft=sample.position.altitude_ft,
            heading_deg=sample.heading_deg,
            ground_speed_kt=sample.ground_speed_kt,
            vertical_speed_fpm=vertical_speed_fpm,
            on_ground=sample.on_ground,
        )

    # -- Streaming --------------------------------------------------------

    async def stream_state(self, interval_s: float) -> AsyncGenerator[AircraftState, None]:
        """Yield the aircraft state every ``interval_s`` seconds, flying it forward.

        Each tick moves the aircraft ``ias_kt * interval_s / 3600`` nautical
        miles along its current heading and applies its vertical speed, so the
        stream is observably alive.
        """
        while True:
            self._advance(interval_s)
            yield self._state.model_copy(deep=True)
            await asyncio.sleep(interval_s)

    async def stream_traffic(
        self, interval_s: float
    ) -> AsyncGenerator[tuple[TrafficContact, ...], None]:
        """Yield the full traffic picture every ``interval_s`` seconds.

        The same shape as :meth:`stream_state`, and capability-free like the
        read it wraps: an adapter (or subclass) without ``can_spawn_traffic``
        yields ``()`` forever rather than raising, so the WS route iterates
        unconditionally.
        """
        while True:
            yield await self.get_traffic_contacts()
            await asyncio.sleep(interval_s)

    def _advance(self, elapsed_s: float) -> None:
        """Integrate the aircraft one step forward (great-circle, no wind)."""
        distance_nm = self._state.ias_kt * elapsed_s / SECONDS_PER_HOUR
        climb_ft = self._state.vertical_speed_fpm * elapsed_s / _SECONDS_PER_MINUTE
        if distance_nm == 0.0 and climb_ft == 0.0:
            return
        origin = GeoPosition(
            latitude=self._state.latitude,
            longitude=self._state.longitude,
            altitude_ft=self._state.altitude_ft,
        )
        moved = point_at_distance_and_bearing(origin, distance_nm, self._state.heading_deg)
        self._state = self._state.model_copy(
            update={
                "latitude": moved.latitude,
                "longitude": moved.longitude,
                "altitude_ft": self._state.altitude_ft + climb_ft,
            }
        )


if TYPE_CHECKING:  # pragma: no cover - static conformance check, never executed
    _CONFORMS: SimAdapter = FakeSimAdapter()
