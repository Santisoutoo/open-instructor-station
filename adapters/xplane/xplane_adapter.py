"""X-Plane 12.1+ adapter over the built-in Web API (REST, default port 8086).

Status: **repositioning VALIDATED against a live X-Plane 12 (LEMD, 2026-08-06).**

Writing a position is the project's key technical risk, and the measurements
that settled it are worth stating precisely, because two of them are traps:

* ``sim/flightmodel/position/latitude``/``longitude``/``elevation`` are
  **read-only**. The authoritative position is the local OpenGL frame
  (``local_x``/``local_y``/``local_z``), which *is* writable. The world
  coordinates are derived from it every frame, which makes reading them back
  the honest verdict on whether a write took effect.
* The world→local conversion normally needs ``XPLMWorldToLocal``, a plugin-only
  API. It can be done externally instead — see :mod:`core.local_frame`.
* **``lat_ref``/``lon_ref`` cannot be trusted.** On the validation run they
  advertised 39.0N/6.0W while the frame's true origin was 40.5N/4.0W — a 200 km
  error that would land every teleport in the wrong province. The origin is
  therefore *measured* from the aircraft's own position, which is known in both
  coordinate systems simultaneously. See :func:`core.local_frame.origin_from_observation`.
* **The frame origin is not stable either.** X-Plane relocates it during the
  scenery reload a long teleport provokes, and the coordinates written before
  the reload then denote a different place on earth — Madrid to Heathrow used to
  poll for the full budget and fail with the write having been accepted
  (issue #36). A measurement is therefore only good for as long as the frame it
  described, and :meth:`XPlaneSimAdapter.set_position` re-measures and re-aims
  rather than trusting the one it started with.

The validated procedure is five steps, and skipping any of them breaks
something:

1. Freeze the flight model (``override_planepath[0] = 1``).
2. Write ``local_x``/``local_y``/``local_z`` — and write them **again**, in the
   frame that is current afterwards, if the arrival poll says the aircraft is
   somewhere else because a scenery reload moved the frame under the write.
3. Write the **velocity vector** (``local_vx/vy/vz``) and heading. Writing zeros
   drops the aircraft out of the sky at stall speed; this adapter carries the
   aircraft's current speed onto the new heading, converted from indicated to
   true airspeed for the density altitude it is being placed *at* — the local
   frame's velocity is a true one. See
   :meth:`XPlaneSimAdapter._true_airspeed_kt`, which runs before the aircraft
   moves, because the atmosphere it needs is the one at the destination.
4. Release the override.
5. Clear the crash state (``sim/operation/fix_all_systems``). X-Plane reads a
   teleport as an impact and marks the aircraft as wrecked otherwise.

Measured accuracy on the validation run: placement exact, restore to the
original position within 0.00 m, crash flag clear throughout.

**The freeze is not a position concern — it is a flight-model concern.**
Anything written into ``sim/flightmodel/position/*`` is fought by a running
flight model, attitude included. Measured against X-Plane 12.4.3 at LEMD, a
heading commanded at 322.21 while the model was live came back 286.9 with the
aircraft sitting *inverted on the runway* (``phi = -180.0``); the identical
write with ``override_planepath`` engaged read back 322.2 while frozen and
322.3 — 0.09° — after the release. Steps 1 and 4 therefore wrap every
flight-model write in this module, not just repositioning, and they are shared
through one helper: :meth:`XPlaneSimAdapter.frozen_flight_model`. Residual
pitch and roll after the release is the aircraft settling onto its gear; that
is physically correct and is not something to tune away.

Aircraft *configuration* — flaps, trim, gear, lights, radios and the autopilot —
is not part of the flight model's integration and is deliberately written
outside the freeze, so a setup that only changes a switch costs no pause.

**The autopilot has no method of its own** (issue #41). It arrives through
:meth:`XPlaneSimAdapter.apply_setup` like every other switch, gated by
``can_control_autopilot``, and X-Plane's own shape is honoured rather than
flattened: the master switch and the flight director are one three-valued
dataref, and the lateral modes are selected by command because their status
datarefs are read-only. See :meth:`XPlaneSimAdapter._write_autopilot`.

This module imports cleanly with no simulator present and opens no sockets
until :meth:`XPlaneSimAdapter.connect` is awaited.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import math
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from itertools import pairwise
from typing import TYPE_CHECKING, Any

import httpx

from adapters.xplane.failure_datarefs import (
    FAILURE_DATAREFS,
    STATE_FAILED,
    STATE_WORKING,
    dataref_paths_for,
    iter_dataref_combos,
)
from core.atmosphere import (
    ISA_SEA_LEVEL_PRESSURE_PA,
    isa_deviation_c,
    pressure_ratio,
    tas_from_ias,
    temperature_from_deviation_c,
)
from core.failures import (
    FAILURE_CATALOGUE,
    ActiveFailure,
    FailureId,
    FailureRef,
    FailureSupport,
    FailureSupportManifest,
)
from core.geodesy import METRES_PER_NAUTICAL_MILE, distance_and_bearing
from core.local_frame import (
    LocalCoordinates,
    LocalFrameOrigin,
    origin_from_observation,
    origin_separation_m,
    world_to_local,
)
from core.models import (
    MAX_FUEL_TANKS,
    MAX_PAYLOAD_STATIONS,
    AircraftSetup,
    AircraftState,
    AirframeInfo,
    GeoPosition,
    Loadout,
    LoadoutState,
    PayloadStation,
    TankFuel,
)
from core.sim_adapter import Capabilities, CapabilityNotSupported, SimAdapter, WeatherRejected
from core.traffic import TrafficContact, TrafficTrack
from core.weather.models import (
    MAX_WIND_LAYERS,
    CloudLayer,
    CloudType,
    RunwayContamination,
    WeatherSetup,
    WeatherState,
    WindLayer,
)

__all__ = ["COMMANDS", "DATAREFS", "DEFAULT_BASE_URL", "OPTIONAL_DATAREFS", "XPlaneSimAdapter"]

DEFAULT_BASE_URL = "http://localhost:8086"

#: Every X-Plane dataref this adapter touches, keyed by the short internal name
#: used throughout the module. Nothing outside this mapping is hard-coded.
#:
#: Deliberately absent: ``lat_ref``/``lon_ref``. They advertise a frame origin
#: that does not match the frame the sim actually uses (see the module
#: docstring), so this adapter measures the origin instead of reading it.
DATAREFS: dict[str, str] = {
    # --- World position: READ-ONLY, derived from the local frame -----------
    "latitude": "sim/flightmodel/position/latitude",
    "longitude": "sim/flightmodel/position/longitude",
    "elevation": "sim/flightmodel/position/elevation",  # metres MSL
    # --- Authoritative local OpenGL frame: +x east, +y up, +z south --------
    "local_x": "sim/flightmodel/position/local_x",
    "local_y": "sim/flightmodel/position/local_y",
    "local_z": "sim/flightmodel/position/local_z",
    "local_vx": "sim/flightmodel/position/local_vx",  # metres/second
    "local_vy": "sim/flightmodel/position/local_vy",
    "local_vz": "sim/flightmodel/position/local_vz",
    # --- Attitude ----------------------------------------------------------
    "psi": "sim/flightmodel/position/psi",  # true heading, degrees
    "theta": "sim/flightmodel/position/theta",  # pitch, degrees
    "phi": "sim/flightmodel/position/phi",  # roll, degrees
    "indicated_airspeed": "sim/flightmodel/position/indicated_airspeed",  # kt
    "vh_ind_fpm": "sim/flightmodel/position/vh_ind_fpm",  # feet per minute
    "on_ground": "sim/flightmodel/failures/onground_any",
    # --- Ambient conditions ------------------------------------------------
    # Needed to turn an indicated airspeed into the true one the local frame's
    # velocity vector is expressed in. X-Plane 12 moved this out of the flat
    # `sim/weather/` namespace it occupied in X-Plane 11; on an older build
    # connect() reports it missing rather than silently skipping the correction.
    "temperature_ambient_deg_c": "sim/weather/aircraft/temperature_ambient_deg_c",
    # --- Repositioning control --------------------------------------------
    "override_planepath": "sim/operation/override/override_planepath",  # int array
    "has_crashed": "sim/flightmodel2/misc/has_crashed",  # read-only
    # --- Aircraft configuration -------------------------------------------
    "flap_ratio": "sim/cockpit2/controls/flap_ratio",
    "speedbrake_ratio": "sim/cockpit2/controls/speedbrake_ratio",
    "elevator_trim": "sim/cockpit2/controls/elevator_trim",  # -1 .. +1
    "gear_handle_down": "sim/cockpit2/controls/gear_handle_down",
    "autobrake_level": "sim/cockpit2/switches/auto_brake_level",
    # One value fanned out to every engine — the write path for
    # AircraftSetup.throttle_ratio.
    "throttle_ratio": "sim/cockpit2/engine/actuators/throttle_ratio_all",
    # --- Fuel & payload (mass-and-balance; docs/designs/fuel-payload.md §6) --
    # High confidence (§6.2): core flight-model weight datarefs present on
    # every aircraft, not an aircraft-specific quirk like the failure
    # catalogue's `rel_*` family. Read/written as whole float arrays, sliced
    # in Python against `_resolve_known_slot_count` — see that function's
    # docstring for why the slot count itself is a lower-confidence guess.
    # Deliberately absent from this mapping (§6.2, unresolved by design,
    # `spikes/fuel_payload_datarefs.py` is where this gets settled):
    #   * tank/station capacities (candidate `acf_tank_rat[]` or a direct
    #     capacity array) and tank/station moment arms — no known public
    #     dataref, "verify in spike"/"expect table-only" (§11.1).
    #   * `sim/flightmodel/weight/m_fixed` — a candidate single-scalar
    #     payload fallback for an aircraft reporting zero configured
    #     stations. Not wired in: the design itself flags that using it
    #     *alongside* `m_stations` double-counts mass, and which case that is
    #     is exactly what is unverified.
    #   * a usable structured CG readback — "not attempted from the live
    #     sim" (§6.2); CG is computed in `core/`, never read (§6.3).
    "fuel_tank_kg": "sim/flightmodel/weight/m_fuel",
    "payload_station_kg": "sim/flightmodel/weight/m_stations",
    # --- Autopilot ---------------------------------------------------------
    # The master switch and the flight director are ONE dataref in X-Plane:
    # 0 = off, 1 = flight director only, 2 = servos engaged. See
    # `_autopilot_mode_for`, which is where the two boolean fields are folded
    # back into it.
    "autopilot_mode": "sim/cockpit/autopilot/autopilot_mode",
    "autopilot_altitude_dial_ft": "sim/cockpit2/autopilot/altitude_dial_ft",
    "autopilot_airspeed_dial": "sim/cockpit2/autopilot/airspeed_dial_kts_mach",
    "autopilot_airspeed_is_mach": "sim/cockpit2/autopilot/airspeed_is_mach",
    "autopilot_heading_dial_deg": "sim/cockpit2/autopilot/heading_dial_deg_mag_pilot",
    "autopilot_vvi_dial_fpm": "sim/cockpit2/autopilot/vvi_dial_fpm",
    # --- Lights ------------------------------------------------------------
    "landing_lights": "sim/cockpit2/switches/landing_lights_on",
    "taxi_lights": "sim/cockpit2/switches/taxi_light_on",
    "nav_lights": "sim/cockpit2/switches/navigation_lights_on",
    "beacon_lights": "sim/cockpit2/switches/beacon_on",
    "strobe_lights": "sim/cockpit2/switches/strobe_lights_on",
    # --- Radios (X-Plane stores NAV frequencies in units of 10 kHz) --------
    "nav1_freq": "sim/cockpit/radios/nav1_freq_hz",
    "nav2_freq": "sim/cockpit/radios/nav2_freq_hz",
    "obs1": "sim/cockpit/radios/nav1_obs_degm",
    "obs2": "sim/cockpit/radios/nav2_obs_degm",
}

#: Datarefs this adapter uses when the build exposes them and lives without
#: when it does not, keyed like :data:`DATAREFS`. The difference is what
#: happens on a build that lacks one: a missing required dataref fails
#: ``connect()`` outright, a missing optional one degrades the read that
#: wanted it to "unknown". These feed :meth:`XPlaneSimAdapter.get_airframe`,
#: whose contract is exactly that degradation — their availability over the
#: Web API is unverified across 12.x builds, and an instructor station must
#: not refuse to connect because it cannot learn the aircraft's stall speed.
OPTIONAL_DATAREFS: dict[str, str] = {
    "acf_icao": "sim/aircraft/view/acf_ICAO",  # byte array, e.g. b"C172"
    "acf_vso": "sim/aircraft/overflow/acf_Vso",  # KIAS, landing configuration
    # --- Weather (X-Plane 12 "region" namespace, weather-manager.md §7) ----
    # Deliberately OPTIONAL rather than required, unlike the rest of this
    # module's mapping: repositioning is already live-validated and must not
    # start refusing to connect() because an unrelated, still-disabled
    # feature's datarefs (can_set_weather stays False below) happen to be
    # missing on some build — the same reasoning this dict's own docstring
    # already states for the airframe reads above. get_weather()/set_weather()
    # raise CapabilityNotSupported before ever touching these (the capability
    # flag is checked first), so they are unreachable regardless; the two
    # places that DO read them unconditionally today are
    # `_true_airspeed_kt`/`_write_velocity_vector` (issue #42), and both
    # degrade to the historical still-air/standard-pressure behaviour when a
    # key here is missing from `self._ids` — see `_qnh_hpa_or_standard` and
    # `_optional_wind_correction`.
    #
    # weather_source/weather_change_mode/weather_update_immediately are
    # UNVERIFIED beyond their names (§7.1, §11.1): spikes/weather_datarefs.py
    # is written to pin the enum values and confirm the Web API accepts the
    # write, but has not run against a live simulator in this session.
    "weather_source": "sim/weather/region/weather_source",
    "weather_change_mode": "sim/weather/region/change_mode",
    "weather_update_immediately": "sim/weather/region/update_immediately",
    # Wind, 13 levels (§7.2, "high" confidence for the three below).
    "wind_altitude_msl_m": "sim/weather/region/wind_altitude_msl_m",
    "wind_direction_degt": "sim/weather/region/wind_direction_degt",
    "wind_speed_msc": "sim/weather/region/wind_speed_msc",
    # Gust: mapped onto the shear pair on the strength of X-Plane's XP11
    # lineage, UNVERIFIED on 12.x (§7.2, §11.2).
    "wind_shear_speed_msc": "sim/weather/region/shear_speed_msc",
    "wind_shear_direction_degt": "sim/weather/region/shear_direction_degt",
    # Turbulence: scale (0-1 or 0-10) UNVERIFIED (§7.2, §11.3).
    "weather_turbulence": "sim/weather/region/turbulence",
    # Clouds, 3 slots (§7.2, "high" confidence for the names below).
    "cloud_base_msl_m": "sim/weather/region/cloud_base_msl_m",
    "cloud_tops_msl_m": "sim/weather/region/cloud_tops_msl_m",
    "cloud_coverage_percent": "sim/weather/region/cloud_coverage_percent",
    "cloud_type": "sim/weather/region/cloud_type",
    # Scalars (§7.2, "high" confidence).
    "weather_visibility_sm": "sim/weather/region/visibility_reported_sm",
    "weather_sealevel_pressure_pas": "sim/weather/region/sealevel_pressure_pas",
    "weather_sealevel_temperature_c": "sim/weather/region/sealevel_temperature_c",
    # Aloft ladders, 13 levels sharing the wind altitude grid (§7.2: "13
    # wind/atmosphere levels"). Temperature ladder shape UNVERIFIED; dewpoint
    # confidence is "medium".
    "weather_temperatures_aloft": "sim/weather/region/temperatures_aloft_deg_c",
    "weather_dewpoint": "sim/weather/region/dewpoint_deg_c",
    "weather_rain_percent": "sim/weather/region/rain_percent",
    "weather_runway_friction": "sim/weather/region/runway_friction",
    # Candidate tank-count dataref named in docs/designs/fuel-payload.md §6.2's
    # prose (not its confidence table) — "low confidence, verify in spike".
    # Optional rather than required: a build that lacks it, or a name that
    # turns out wrong, degrades to "use the whole array X-Plane returned" (see
    # `_resolve_known_slot_count`) instead of failing connect() for a
    # capability this adapter does not even offer yet (can_set_fuel_payload
    # stays False). No equivalent station-count candidate is named anywhere in
    # the design, so none is guessed here either.
    "acf_num_tanks": "sim/aircraft/overflow/acf_num_tanks",
}

#: Commands this adapter activates, keyed by short internal name.
COMMANDS: dict[str, str] = {
    # Repairs every failed system, which includes clearing the crash state a
    # teleport provokes. Step 5 of the repositioning procedure.
    "fix_all_systems": "sim/operation/fix_all_systems",
    # --- Autopilot lateral mode selection ---------------------------------
    # X-Plane exposes the *armed/captured* lateral mode as read-only status
    # datarefs (`nav_status`, `approach_status`, …) and selects it through
    # commands. There is deliberately no per-mode "off": the lateral modes are
    # mutually exclusive, so deselecting one means selecting another, and
    # wing-leveller is X-Plane's neutral one.
    "autopilot_nav": "sim/autopilot/NAV",
    "autopilot_approach": "sim/autopilot/approach",
    "autopilot_heading": "sim/autopilot/heading",
    "autopilot_wing_leveler": "sim/autopilot/wing_leveler",
}

_CAPABILITIES = Capabilities(
    can_set_position=True,
    can_set_aircraft_state=True,
    can_control_autopilot=True,
    # `pytest -m sim` passed against a live X-Plane 12.4.3 install
    # (weather-manager.md §7.3): a genuine bug the earlier session's shorter
    # observation window mistook for a permanent one -- see
    # _write_temperature_ladder's docstring -- plus a real cloud-settle bug
    # (only slot 0 was ever checked for convergence, and the timeout was far
    # too short for the ~55-60s cycle clouds actually need; see
    # _await_cloud_layers_settled's docstring for both).
    can_set_weather=True,
    # `pytest -m sim` passed against a live X-Plane 12.4.3 install
    # (failures-manager.md D11/§5.3): the §5.1 value enum is confirmed, and
    # inject/clear/clear-all/an indexed engine failure all round-trip for
    # real. See adapters/xplane/failure_datarefs.py's module docstring for
    # the live findings that got it there — a genuine spelling bug in the
    # vacuum instrument's second dataref, several "verify in spike" rows
    # resolved into fact, and two entries confirmed to have no matching
    # dataref on this build at all.
    can_inject_failures=True,
    can_spawn_traffic=False,
    # `pytest -m sim` passed against a live X-Plane 12.4.3 (fuel-payload.md
    # §6.4, §9.4): the dataref mapping is real, not a stub. Two live findings
    # along the way — see _write_loadout's docstring — the tank-count
    # dataref's namespace was wrong in the design, and the contract suite's
    # "wholesale replace" test needed to assert by mass, not list length,
    # since a real airframe's tank/station count is fixed, not shrinkable.
    can_set_fuel_payload=True,
    can_control_camera=False,
    can_pushback=False,
)

#: §5.4 — rendered once in the Failures panel, verbatim. Study-level add-ons
#: often run their own internal failure model and may ignore ``rel_*``
#: entirely; D10's read-back cannot detect that from the dataref side, because
#: the dataref itself still reports "failed" honestly.
_FAILURE_MANIFEST_CAVEAT = (
    "Aircraft with their own failure model (many study-level add-ons) may ignore "
    "simulator failures. Verify against your aircraft before a lesson depends on one."
)

_METRES_PER_FOOT = 0.3048
_METRES_PER_SECOND_PER_KNOT = 0.514444

#: Seconds to let the sim settle after engaging or releasing the override, and
#: after writing the position. Measured: one or two physics frames is enough,
#: these leave a wide margin over a loaded scenery reload.
_OVERRIDE_SETTLE_S = 0.3
_RELEASE_SETTLE_S = 1.0

#: Arrival is polled rather than assumed after a fixed delay. A short hop
#: settles in one frame, but a teleport of a few hundred kilometres triggers a
#: scenery reload, during which X-Plane relocates the local frame origin and the
#: derived world coordinates are briefly in transit. Polling handles both
#: without making the common case slow.
_ARRIVAL_POLL_S = 0.25

#: How long one write is given to show up before the adapter stops waiting and
#: asks *why* it has not (issue #36). This is the settle criterion, and the
#: number is chosen for what it rules out rather than for how long a reload
#: takes:
#:
#: The derived world coordinates lag a local-frame write by one or two frames —
#: tens of milliseconds. A slice is two orders of magnitude longer than that,
#: and every poll inside it is a *round trip X-Plane answered*. So when a slice
#: expires with the aircraft parked somewhere that is not the target, the sim
#: has demonstrably been running and publishing throughout, and "not there yet"
#: has been ruled out: the aircraft really is somewhere else, and the frame it
#: was aimed in is the prime suspect. A simulator stalled mid-reload does not
#: answer at all, so that case shows up as a slow poll and is absorbed by
#: :data:`_REPOSITION_TIMEOUT_S` rather than mistaken for a settled frame.
_ARRIVAL_ATTEMPT_S = 8.0

#: Total wall-clock budget for one :meth:`XPlaneSimAdapter.set_position`, across
#: every re-aim. Re-aiming must not turn a bounded failure into an unbounded
#: one, so the loop is bounded twice over: by this deadline and by
#: :data:`_MAX_REPOSITION_WRITES`.
_REPOSITION_TIMEOUT_S = 30.0

#: How many times one placement will aim at its target. The first write is the
#: common case. The second is the one that lands after a scenery reload has
#: moved the frame, which is the whole of issue #36. The third exists because a
#: re-measure can itself be overtaken by a second shift; a fourth would be
#: treating "the frame keeps moving" as something to out-wait, and it is not —
#: at that point the placement has failed and the instructor should be told.
_MAX_REPOSITION_WRITES = 3

#: Two frame-origin measurements further apart than this describe different
#: frames. Measured off the frozen aircraft they agree to millimetres; a scenery
#: shift moves the anchor by kilometres. The threshold sits between two scales
#: six orders of magnitude apart, which is why it has never needed tuning.
_ORIGIN_SHIFT_TOLERANCE_M = 50.0

#: Consecutive agreeing measurements required before a re-measured origin is
#: aimed with, and the gap between them. One measurement cannot tell a settled
#: frame from one sampled mid-shift; two that agree can.
_ORIGIN_STABLE_SAMPLES = 2
_ORIGIN_SAMPLE_S = 0.25

#: Read-back tolerance after a teleport, in metres. The check runs while the
#: flight model is still frozen, so the aircraft is not moving and this only has
#: to absorb float noise — not a second of flight.
POSITION_WRITE_TOLERANCE_M = 50.0

#: The three values of ``sim/cockpit/autopilot/autopilot_mode``. X-Plane models
#: the master switch and the flight director as one ladder rather than two
#: switches, which is physically right: servos without a flight director is not
#: a state a real autopilot has.
AUTOPILOT_MODE_OFF = 0
AUTOPILOT_MODE_FLIGHT_DIRECTOR = 1
AUTOPILOT_MODE_SERVOS = 2

#: Lateral-mode field -> the command that selects it, in the order they are
#: applied. The modes are mutually exclusive, so the last one activated wins:
#: the order runs from the least specific (heading) to the most specific
#: (approach), which is the sensible resolution of a contradictory setup.
_LATERAL_MODE_COMMANDS: tuple[tuple[str, str], ...] = (
    ("autopilot_hdg", "autopilot_heading"),
    ("autopilot_nav", "autopilot_nav"),
    ("autopilot_app", "autopilot_approach"),
)

# --- Weather (weather-manager.md §7) and the issue #42 corrections ---------

_METRES_PER_STATUTE_MILE = 1609.344
_PASCALS_PER_HPA = 100.0
_ISA_SEA_LEVEL_PRESSURE_HPA = ISA_SEA_LEVEL_PRESSURE_PA / _PASCALS_PER_HPA

#: Feet of pressure altitude per hectopascal of QNH deviation from standard,
#: derived from the ISA lapse itself (``core.atmosphere.pressure_ratio``) at
#: sea level rather than copied from the memorised "about 27 ft/hPa" rule of
#: thumb, so it tracks the ISA constants exactly if they ever change. Comes
#: out to ~27.3 ft/hPa. Used by :meth:`XPlaneSimAdapter._true_airspeed_kt`
#: (issue #42.2 — pressure altitude used to assume standard QNH).
_PRESSURE_ALTITUDE_FT_PER_HPA: float = _PASCALS_PER_HPA / (
    ISA_SEA_LEVEL_PRESSURE_PA * (pressure_ratio(0.0) - pressure_ratio(1.0))
)

#: X-Plane 12's region weather levels, shared by wind and the temperature/
#: dewpoint ladders (weather-manager.md D10: "13 wind/atmosphere levels").
_WEATHER_WIND_LEVELS = 13

#: X-Plane's own cloud-layer slot count. Not part of §7.2's confidence table
#: (which names the datarefs but not their array length); inferred from
#: X-Plane 12's documented weather API, which exposes exactly three cloud
#: layers — matching ``core.weather.models.MAX_CLOUD_LAYERS`` exactly. An
#: implementation assumption, not a table-sourced fact; unlike wind there is
#: no distribution step for clouds; each core layer maps to one slot 1:1.
_WEATHER_CLOUD_LAYERS = 3

#: Altitude spacing used to keep the padding levels above the highest given
#: wind layer strictly ascending (D10), and to give every level a distinct
#: altitude when a caller commands calm winds ([]). §7.2 states the
#: *requirement* (ascending, never a phantom shear at a stale altitude)
#: without prescribing a spacing; this is a plain implementation choice, not
#: a value carried over from the design's dataref table.
_WEATHER_PADDING_ALTITUDE_STEP_FT = 1_000.0

#: sim/weather/region/weather_source. **CONFIRMED against a live X-Plane
#: 12.4.3 install** (weather-manager.md §11.1, resolved): the dataref is
#: **read-only** — the Web API rejects a write to it outright, so it is never
#: written, only read back as the honest verdict on whether manual mode took.
#: ``0`` is the value X-Plane reports once ``change_mode`` has been switched
#: away from real weather (``1`` was the observed real-weather value on this
#: install). Empirically verified: writing ``change_mode=3`` +
#: ``update_immediately=1`` and then a distinctive visibility/QNH held those
#: values bit-for-bit for 120s of live polling — well past the 90s threshold
#: — while candidates ``0``, ``1`` and ``2`` each eventually drifted (at
#: roughly 50s, 35s and 60s respectively), meaning X-Plane's own weather
#: engine periodically reasserts itself under those modes but not under `3`.
_WEATHER_SOURCE_MANUAL = 0

#: sim/weather/region/change_mode. **CONFIRMED**, not merely carried from the
#: design's table: ``3`` is the one candidate (of 0-3 tried) whose manual
#: writes survived a live 120s hold with zero drift — see
#: :data:`_WEATHER_SOURCE_MANUAL`'s docstring for the comparison against the
#: other candidates.
_WEATHER_CHANGE_MODE_STATIC = 3

#: How long :meth:`_write_cloud_layers` waits for a cloud write to actually
#: land before giving up.
#:
#: **CONFIRMED, and a much larger number than this constant's first measured
#: value** (which found "up to ~4s"): cloud writes on a live X-Plane 12.4.3
#: install do not land smoothly or immediately at all — every slot holds an
#: unrelated, uniform stale value (observed: the *same* number across all
#: three slots, itself a leftover from an earlier write) for up to ~55s, then
#: every slot snaps to its correct, distinct commanded value in the same
#: instant. This matches Laminar's own documented real-weather refresh
#: interval — the same "≤60 s" figure :data:`WEATHER_HOLD_S` in
#: ``tests/adapters/test_contract.py`` already budgets for — applied here to
#: cloud writes specifically, which the original measurement session did not
#: wait long enough to discover. 70 s leaves margin past the observed ~55 s
#: cycle boundary without making a genuinely stuck write hang indefinitely.
_CLOUD_SETTLE_TIMEOUT_S = 70.0
_CLOUD_SETTLE_POLL_INTERVAL_S = 1.0
_CLOUD_SETTLE_BASE_TOLERANCE_M = 5.0
_CLOUD_SETTLE_COVERAGE_TOLERANCE = 0.02

#: sim/weather/region/cloud_type, a float enum, blendable — §7.2, "high"
#: confidence for the four values below.
_CLOUD_TYPE_TO_XPLANE: dict[CloudType, float] = {
    "cirrus": 0.0,
    "stratus": 1.0,
    "cumulus": 2.0,
    "cumulonimbus": 3.0,
}
_CLOUD_TYPE_FROM_XPLANE: tuple[CloudType, ...] = ("cirrus", "stratus", "cumulus", "cumulonimbus")

#: sim/weather/region/runway_friction, int enum 0-15 per §7.2's table: dry 0,
#: wet 1-3, puddles 4-6, snow 7-9, ice 10-12 (13-15 left unspecified by the
#: design; read back as "ice", the nearest defined band).
_RUNWAY_CONTAMINATION_TO_XPLANE: dict[RunwayContamination, int] = {
    "dry": 0,
    "wet": 2,
    "puddles": 5,
    "snow": 8,
    "ice": 11,
}
#: Band floors in descending order, so the first floor a value clears is its band.
_RUNWAY_FRICTION_BAND_FLOORS: tuple[tuple[int, RunwayContamination], ...] = (
    (10, "ice"),
    (7, "snow"),
    (4, "puddles"),
    (1, "wet"),
    (0, "dry"),
)

#: Multiplier between the model's 0-1 turbulence ratio and whatever range
#: sim/weather/region/turbulence[i] actually expects. **Partially checked
#: against a live X-Plane 12.4.3 install, still not fully confirmed** (§7.2,
#: §11.3): writing 5.0 round-tripped as 5.0 with no clamping to 1.0, which
#: rules out a hard-clamped 0-1 range at the Web API layer, but only a human
#: watching the sim's own weather UI while this value is written can confirm
#: what visible/felt turbulence 5.0 actually produces — the automatable half
#: of this question is answered, the sensory half is not. ``1.0`` (no
#: rescale) stays the placeholder until that observation happens.
_TURBULENCE_SCALE_UNVERIFIED = 1.0


def _angular_difference(from_deg: float, to_deg: float) -> float:
    """Shortest signed difference from ``from_deg`` to ``to_deg``, in ``(-180, 180]``.

    Used to interpolate a wind direction across the 000/360 wrap without ever
    turning "the long way round" (:meth:`XPlaneSimAdapter._wind_at_altitude`).
    """
    return (to_deg - from_deg + 180.0) % 360.0 - 180.0


def _runway_contamination_from_friction(value: int) -> RunwayContamination:
    """Invert :data:`_RUNWAY_CONTAMINATION_TO_XPLANE`'s bands on read-back."""
    for floor, contamination in _RUNWAY_FRICTION_BAND_FLOORS:
        if value >= floor:
            return contamination
    return "dry"


def _decode_dataref_text(raw: Any) -> str | None:
    """Turn a byte-array dataref value into text, or ``None`` when it will not.

    The Web API serialises byte-array datarefs as base64 strings; older spikes
    have also seen them arrive as plain lists of integers. Both are accepted,
    NUL padding is stripped, and anything that fails to decode degrades to
    ``None`` — these feed :class:`~core.models.AirframeInfo`, whose whole
    contract is that unknown is an answer.
    """
    data: bytes
    if isinstance(raw, str):
        try:
            data = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            # Not base64 after all — some builds serve short byte arrays as
            # the decoded string directly.
            data = raw.encode("utf-8", errors="replace")
        else:
            # A short plain string can be valid base64 by accident ("C172"
            # decodes to three bytes of garbage). If the decode produced
            # something unprintable, the raw string was the value all along.
            if not _extract_text(data) and raw.strip():
                data = raw.encode("utf-8", errors="replace")
    elif isinstance(raw, list) and all(isinstance(item, int) for item in raw):
        try:
            data = bytes(item & 0xFF for item in raw)
        except ValueError:
            return None
    else:
        return None
    return _extract_text(data)


def _extract_text(data: bytes) -> str | None:
    """The printable prefix of a NUL-padded byte buffer, or ``None``.

    Strict on purpose: a buffer that is not clean printable ASCII up to its
    first NUL is treated as "not text at all" rather than salvaged, because the
    caller uses that verdict to tell real base64 apart from a plain string that
    merely decodes as base64.
    """
    prefix = data.split(b"\x00", 1)[0]
    try:
        text = prefix.decode("ascii")
    except UnicodeDecodeError:
        return None
    if not all(character.isprintable() for character in text):
        return None
    return text.strip() or None


def _resolve_known_slot_count(candidate: Any, array_length: int, max_allowed: int) -> int:
    """How many of a fuel/payload array's slots this adapter treats as real.

    ``m_fuel``/``m_stations`` are fixed-size X-Plane arrays, and most
    aircraft do not use every slot. Which slots are "real" for the loaded
    airframe would ideally come from a tank/station count dataref, but
    ``docs/designs/fuel-payload.md`` §6.2 rates that "low confidence, verify
    in spike" and names only a tank-count candidate, not a station-count one
    — so this never invents a count. ``candidate`` is that optional reading
    (``None`` when the build lacks the dataref, or the caller has no
    candidate to offer, e.g. for stations); whenever it is missing or does
    not look like a sane slot count, the *whole* array X-Plane reported is
    used instead — an honest "we don't know which are real, so report
    everything the sim reports" fallback, not a guess.

    ``max_allowed`` guards :class:`core.models.TankFuel`/
    :class:`core.models.PayloadStation`'s own ``tank_index``/
    ``station_index`` bounds (``MAX_FUEL_TANKS``/``MAX_PAYLOAD_STATIONS``):
    whatever X-Plane's real array size turns out to be, this adapter must
    never construct a model those bounds reject.
    """
    count = array_length
    if candidate is not None:
        try:
            parsed = int(candidate)
        except (TypeError, ValueError):
            parsed = None
        if parsed is not None and 0 < parsed <= array_length:
            count = parsed
    return min(count, max_allowed)


class XPlaneNotReachable(RuntimeError):
    """The X-Plane Web API did not answer. Is the sim running with the API enabled?"""


class XPlaneRepositionFailed(RuntimeError):
    """The aircraft did not arrive where it was told to go."""


class XPlaneWeatherRejected(WeatherRejected):
    """X-Plane refused to hold the commanded weather, or this build does not expose it.

    Two distinct causes share this exception (weather-manager.md §2.2's 502
    mapping, §7.1 step 4): the sim would not switch — or would not stay in —
    manual weather mode, so writing values it has announced it will overwrite
    would be dishonest; or the region weather datarefs this build needs are
    not in the dataref index at all (they are declared OPTIONAL on this
    adapter, see :data:`OPTIONAL_DATAREFS`). Either way, ``set_weather``/
    ``get_weather`` must refuse rather than proceed on a guess.

    Subclasses :class:`core.sim_adapter.WeatherRejected`, the adapter-agnostic
    type ``server/weather_routes.py`` actually catches — the router never
    imports this class by name.
    """


class XPlaneSimAdapter:
    """Talks to X-Plane 12.1+ over its built-in Web API.

    Args:
        host: Hostname or IP running X-Plane.
        port: Web API port (X-Plane's default is 8086).
        timeout_s: Per-request HTTP timeout in seconds.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8086,
        timeout_s: float = 5.0,
    ) -> None:
        self._base_url = f"http://{host}:{port}"
        self._timeout_s = timeout_s
        self._client: httpx.AsyncClient | None = None
        self._ids: dict[str, int] = {}
        self._command_ids: dict[str, int] = {}
        self._failure_ids: dict[tuple[FailureId, int | None], tuple[int, ...]] = {}
        self._freeze_depth = 0
        # ai-traffic.md §4.3 (D3/D4): capabilities are computed once per
        # connection, from the bridge probe inside connect(), and never move
        # again for that connection's lifetime. Before connect() the honest
        # answer is the bridge-less baseline.
        self._bridge_available = False
        self._capabilities = _CAPABILITIES

    # -- Identity ---------------------------------------------------------

    @property
    def name(self) -> str:
        """Adapter identifier."""
        return "xplane"

    @property
    def capabilities(self) -> Capabilities:
        """What this connection supports — resolved once, inside :meth:`connect`.

        Everything except ``can_spawn_traffic`` is a static fact about this
        adapter; that one flag depends on whether the optional ``bridge/``
        plugin answered the connect-time probe (ai-traffic.md D3). It is never
        mutated mid-session (D4): a bridge that disappears later is a
        connectivity fault surfaced by the traffic write methods failing, not
        a capability flip.
        """
        return self._capabilities

    @property
    def is_connected(self) -> bool:
        """True once the dataref index has been fetched and resolved."""
        return self._client is not None and bool(self._ids)

    @property
    def base_url(self) -> str:
        """The Web API root, e.g. ``http://localhost:8086``."""
        return self._base_url

    # -- Lifecycle --------------------------------------------------------

    async def connect(self) -> None:
        """Resolve the ids of :data:`DATAREFS` and :data:`COMMANDS`.

        Raises:
            XPlaneNotReachable: if the Web API cannot be reached, or if the
                build is missing datarefs this adapter needs.
        """
        if self.is_connected:
            return
        client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout_s)
        try:
            response = await client.get("/api/v2/datarefs")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            await client.aclose()
            raise XPlaneNotReachable(
                f"Could not reach the X-Plane Web API at {self._base_url}. "
                "Start X-Plane 12.1 or newer and make sure its Web API is enabled."
            ) from exc

        # Optional datarefs ride the same index scan but never gate the
        # connect: absence just means the reads that want them answer
        # "unknown". Only the required set below can fail the connection.
        wanted = {path: key for key, path in (DATAREFS | OPTIONAL_DATAREFS).items()}
        # Failure datarefs (D11, §5.3) ride the identical scan and the identical
        # posture: every path this file has a guess for is resolved here, and a
        # guess that does not exist on this install simply never lands in
        # ``failure_index`` below — it degrades that one catalogue entry to
        # unsupported, it never fails this connect().
        failure_combo_by_path: dict[str, tuple[FailureId, int | None]] = {
            path: combo for combo in iter_dataref_combos() for path in dataref_paths_for(*combo)
        }
        index: dict[str, int] = {}
        failure_index: dict[str, int] = {}
        for entry in response.json().get("data", []):
            name = entry.get("name")
            key = wanted.get(name)
            if key is not None:
                index[key] = int(entry["id"])
            if name in failure_combo_by_path:
                failure_index[name] = int(entry["id"])

        missing = sorted(set(DATAREFS) - set(index))
        if missing:
            await client.aclose()
            raise XPlaneNotReachable(
                "The X-Plane dataref index is missing entries this adapter needs: "
                f"{', '.join(DATAREFS[key] for key in missing)}. "
                "This usually means an X-Plane version older than 12.1."
            )

        commands: dict[str, int] = {}
        for key, path in COMMANDS.items():
            command_response = await client.get("/api/v2/commands", params={"filter[name]": path})
            command_response.raise_for_status()
            entries = command_response.json().get("data", [])
            if not entries:
                await client.aclose()
                raise XPlaneNotReachable(f"X-Plane does not expose the command {path!r}.")
            commands[key] = int(entries[0]["id"])

        # A combo counts as supported only when *every* one of its datarefs
        # resolved — a partial resolve (one bus of two, say) is treated the
        # same as none, the conservative reading of D11: a half-mapped entry
        # would write an incomplete failure and call it done.
        failure_ids: dict[tuple[FailureId, int | None], tuple[int, ...]] = {}
        for combo in iter_dataref_combos():
            resolved = [failure_index.get(path) for path in dataref_paths_for(*combo)]
            if resolved and all(dataref_id is not None for dataref_id in resolved):
                failure_ids[combo] = tuple(
                    dataref_id for dataref_id in resolved if dataref_id is not None
                )

        # ai-traffic.md §4.3: capabilities are computed from the bridge probe,
        # once, here — and never move again for this connection's lifetime
        # (D4). The probe never raises and never fails the connect; an absent
        # bridge just means can_spawn_traffic stays False.
        self._bridge_available = await self._probe_bridge(client)
        self._capabilities = _CAPABILITIES.model_copy(
            update={"can_spawn_traffic": self._bridge_available}
        )

        self._client = client
        self._ids = index
        self._command_ids = commands
        self._failure_ids = failure_ids

    async def _probe_bridge(self, client: httpx.AsyncClient) -> bool:
        """Is the optional ``bridge/`` plugin loaded and alive on this connection?

        **Track B stub** (ai-traffic.md §5.2, §9.2): the real probe looks for
        the ``ois/bridge/heartbeat_s`` custom dataref in the index the same way
        :data:`OPTIONAL_DATAREFS` are found, then reads it twice a short gap
        apart, requiring the second read to be strictly greater — proving the
        flight loop is actually ticking, not just that the plugin loaded and
        then froze. Until that lands the honest answer is ``False`` — no
        bridge, no traffic. Absence never raises and never fails
        :meth:`connect`; that is the whole point of "optional".
        """
        del client  # unused until Track B implements the real probe
        return False

    async def disconnect(self) -> None:
        """Close the HTTP client. Idempotent, never raises."""
        client, self._client = self._client, None
        self._ids = {}
        self._command_ids = {}
        self._failure_ids = {}
        if client is not None:
            await client.aclose()

    # -- Dataref plumbing -------------------------------------------------

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None or not self._ids:
            raise XPlaneNotReachable("Adapter is not connected; await connect() first.")
        return self._client

    async def _read(self, key: str) -> Any:
        """Read one dataref value by its short :data:`DATAREFS` key."""
        self._require_client()
        return await self._read_by_id(self._ids[key])

    async def _write(self, key: str, value: float | int | bool, index: int | None = None) -> None:
        """Write one dataref value, optionally a single element of an array."""
        self._require_client()
        await self._write_by_id(self._ids[key], value, index=index)

    async def _read_by_id(self, dataref_id: int) -> Any:
        """Read one dataref value by its already-resolved numeric id.

        The escape hatch :meth:`_read` uses under a short :data:`DATAREFS` key,
        and the one the failure mapping uses directly: failure datarefs are
        resolved per ``(failure_id, engine_index)`` combo at :meth:`connect`
        time (D11, §5.3) rather than given a short key each, since there can be
        up to eight per indexed entry.
        """
        client = self._require_client()
        response = await client.get(f"/api/v2/datarefs/{dataref_id}/value")
        response.raise_for_status()
        return response.json()["data"]

    async def _write_by_id(
        self, dataref_id: int, value: float | int | bool, index: int | None = None
    ) -> None:
        """Write one dataref value by its already-resolved numeric id. See :meth:`_read_by_id`."""
        client = self._require_client()
        response = await client.patch(
            f"/api/v2/datarefs/{dataref_id}/value",
            json={"data": value},
            params=None if index is None else {"index": index},
        )
        response.raise_for_status()

    async def _activate(self, key: str) -> None:
        """Fire one X-Plane command by its short :data:`COMMANDS` key."""
        client = self._require_client()
        response = await client.post(
            f"/api/v2/command/{self._command_ids[key]}/activate",
            json={"duration": 0},
        )
        response.raise_for_status()

    # -- Reads ------------------------------------------------------------

    async def get_aircraft_state(self) -> AircraftState:
        """Read the user aircraft's position and attitude from X-Plane."""
        keys = (
            "latitude",
            "longitude",
            "elevation",
            "psi",
            "indicated_airspeed",
            "vh_ind_fpm",
            "theta",
            "phi",
            "on_ground",
        )
        raw = await asyncio.gather(*(self._read(key) for key in keys))
        values = dict(zip(keys, raw, strict=True))
        return AircraftState(
            latitude=float(values["latitude"]),
            longitude=float(values["longitude"]),
            altitude_ft=float(values["elevation"]) / _METRES_PER_FOOT,
            heading_deg=float(values["psi"]) % 360.0,
            ias_kt=max(0.0, float(values["indicated_airspeed"])),
            vertical_speed_fpm=float(values["vh_ind_fpm"]),
            pitch_deg=float(values["theta"]),
            roll_deg=float(values["phi"]),
            on_ground=bool(values["on_ground"]),
        )

    async def get_airframe(self) -> AirframeInfo:
        """What the sim reports about the loaded airframe. Every field degrades.

        Built from :data:`OPTIONAL_DATAREFS`, so a build that does not expose
        one of them — their Web API availability is unverified across 12.x —
        answers ``None`` for that field instead of failing. A value that does
        not decode or is out of range degrades the same way: this read informs
        a *default* (the approach category of issue #82), and a wrong guess
        made loudly downstream beats a connection refused here.

        **Deliberately does not populate ``mass_limits``.** ``acf_m_empty``/
        ``acf_m_max`` (docs/designs/fuel-payload.md §6.2, "medium/high
        confidence, read-only") would supply exactly two of
        :class:`~core.models.AirframeMassLimits`'s fields
        (``empty_weight_kg``/``max_takeoff_weight_kg``); the CG arm, fuel/
        station capacities and arms, and the CG envelope have no known
        dataref at all (§6.2, §11.1 — "verify in spike" / "not attempted").
        ``AirframeMassLimits`` is all-or-nothing by design (D5): reporting a
        model built from two live numbers and the rest fabricated would be
        exactly the invented data hard rule 3 forbids, so this method reads
        neither dataref and leaves ``mass_limits`` at its default ``None`` —
        ``core.fuel_payload.limits.resolve_mass_limits`` (the sibling backend
        track's fallback table, §6.2/D6) is expected to be the primary path,
        not a fallback, until the low-confidence datarefs are confirmed. A
        live-partial-plus-table merge is flagged, not built, at §11.4.
        """
        raw_icao, raw_vso = await asyncio.gather(
            self._read_optional("acf_icao"),
            self._read_optional("acf_vso"),
        )
        vso: float | None = None
        if raw_vso is not None:
            try:
                candidate = float(raw_vso)
            except (TypeError, ValueError):
                candidate = 0.0
            if candidate > 0.0:
                vso = candidate
        return AirframeInfo(icao_type=_decode_dataref_text(raw_icao), vso_kias=vso)

    # -- Weather ----------------------------------------------------------------
    #
    # can_set_weather is TRUE (weather-manager.md D16, §7.3): `pytest -m sim`
    # passed against a live X-Plane 12.4.3 install. §11.1's manual-mode
    # question is RESOLVED (weather_source is read-only; change_mode=3 +
    # update_immediately=1 holds manual weather for 120s+ with zero drift —
    # see _WEATHER_SOURCE_MANUAL's docstring). Two more findings closed the
    # gap between "resolved" and "flag flips": the sealevel_temperature_c
    # drift an earlier session called permanently broken turned out to be a
    # transient real-weather-engine interpolation, not structural (confirmed
    # holding for a full 100s once past it — see _write_temperature_ladder's
    # docstring); and cloud layers needed both a much longer settle timeout
    # (~55-60s, not 10s) and a bug fix (only slot 0 was ever checked for
    # convergence, so a wholesale-replace write's zeroed slot was never
    # confirmed — see _await_cloud_layers_settled's docstring for both).

    # -- Failures -----------------------------------------------------------
    #
    # can_inject_failures is TRUE (docs/designs/failures-manager.md D11/§5.3):
    # `pytest -m sim` passed against a live X-Plane 12.4.3. See
    # adapters/xplane/failure_datarefs.py's module docstring for the live
    # findings that got it there. Its two capability-free reads,
    # get_failure_support()/get_active_failures() (failures-manager.md §4:
    # "no is an answer, never an exception"), keep degrading honestly instead
    # of raising for whichever catalogue entries still ship unsupported.
    #
    # can_set_fuel_payload is TRUE (docs/designs/fuel-payload.md §6.4, §9.4):
    # `pytest -m sim` passed against a live X-Plane 12.4.3. See
    # _write_loadout's own docstring for the two live findings that got it
    # there — a wrong dataref namespace for the tank-count candidate, and a
    # contract-test assumption (array length shrinks) that does not hold for
    # a real airframe's fixed tank/station count.

    async def get_weather(self) -> WeatherState:
        """Read the commanded weather from the region datarefs (§7.2's closing paragraph).

        Reconstructs the typed ``wind_layers``/``cloud_layers`` lists by
        collapsing the padded duplicate levels :meth:`_write_wind_layers` left
        behind back into the layer they came from — adjacent levels with equal
        direction/speed/gust/turbulence are one layer.
        """
        if not self.capabilities.can_set_weather:
            raise CapabilityNotSupported(self.name, "can_set_weather")
        self._require_weather_datarefs(
            "wind_altitude_msl_m",
            "wind_direction_degt",
            "wind_speed_msc",
            "wind_shear_speed_msc",
            "weather_turbulence",
            "cloud_base_msl_m",
            "cloud_tops_msl_m",
            "cloud_coverage_percent",
            "cloud_type",
            "weather_visibility_sm",
            "weather_sealevel_pressure_pas",
            "weather_sealevel_temperature_c",
            "weather_dewpoint",
            "weather_rain_percent",
            "weather_runway_friction",
        )
        wind_layers = await self._read_wind_layers()
        cloud_layers = await self._read_cloud_layers()
        (
            visibility_sm,
            qnh_pa,
            temperature_c,
            dewpoint_raw,
            rain_percent,
            friction,
        ) = await asyncio.gather(
            self._read("weather_visibility_sm"),
            self._read("weather_sealevel_pressure_pas"),
            self._read("weather_sealevel_temperature_c"),
            self._read("weather_dewpoint"),
            self._read("weather_rain_percent"),
            self._read("weather_runway_friction"),
        )
        # dewpoint_deg_c is the 13-level ladder (§7.2); the surface entry
        # (index 0) is the field's answer, same convention as the write side.
        dewpoint_c = dewpoint_raw[0] if isinstance(dewpoint_raw, list) else dewpoint_raw
        return WeatherState(
            wind_layers=wind_layers,
            cloud_layers=cloud_layers,
            visibility_m=float(visibility_sm) * _METRES_PER_STATUTE_MILE,
            qnh_hpa=float(qnh_pa) / _PASCALS_PER_HPA,
            temperature_c=float(temperature_c),
            dewpoint_c=float(dewpoint_c),
            precipitation_ratio=float(rain_percent),
            runway_contamination=_runway_contamination_from_friction(int(friction)),
        )

    async def set_weather(self, setup: WeatherSetup) -> None:
        """Apply every field of ``setup`` that is not ``None`` (§7).

        Forces and verifies manual weather mode once (§7.1), then writes only
        the fields ``setup`` states, in the order §7.2's table lists them.
        Every dataref the requested fields need is checked present *before*
        anything is written, so a build missing one of them fails cleanly
        rather than leaving the weather half-applied.
        """
        if not self.capabilities.can_set_weather:
            raise CapabilityNotSupported(self.name, "can_set_weather")

        required = {"weather_source", "weather_change_mode", "weather_update_immediately"}
        if setup.wind_layers is not None:
            required |= {
                "wind_altitude_msl_m",
                "wind_direction_degt",
                "wind_speed_msc",
                "wind_shear_speed_msc",
                "wind_shear_direction_degt",
                "weather_turbulence",
            }
        if setup.cloud_layers is not None:
            required |= {
                "cloud_base_msl_m",
                "cloud_tops_msl_m",
                "cloud_coverage_percent",
                "cloud_type",
            }
        if setup.visibility_m is not None:
            required.add("weather_visibility_sm")
        if setup.qnh_hpa is not None:
            required.add("weather_sealevel_pressure_pas")
        if setup.temperature_c is not None:
            required |= {
                "weather_sealevel_temperature_c",
                "weather_temperatures_aloft",
                "wind_altitude_msl_m",
            }
        if setup.dewpoint_c is not None:
            required |= {
                "weather_dewpoint",
                "weather_sealevel_temperature_c",
                "wind_altitude_msl_m",
            }
        if setup.precipitation_ratio is not None:
            required.add("weather_rain_percent")
        if setup.runway_contamination is not None:
            required.add("weather_runway_friction")
        self._require_weather_datarefs(*required)

        await self._force_manual_weather_mode()

        if setup.wind_layers is not None:
            await self._write_wind_layers(setup.wind_layers)
        if setup.cloud_layers is not None:
            await self._write_cloud_layers(setup.cloud_layers)
        if setup.visibility_m is not None:
            await self._write(
                "weather_visibility_sm", setup.visibility_m / _METRES_PER_STATUTE_MILE
            )
        if setup.qnh_hpa is not None:
            await self._write("weather_sealevel_pressure_pas", setup.qnh_hpa * _PASCALS_PER_HPA)
        if setup.temperature_c is not None:
            await self._write_temperature_ladder(setup.temperature_c)
        if setup.dewpoint_c is not None:
            await self._write_dewpoint_ladder(setup.dewpoint_c)
        if setup.precipitation_ratio is not None:
            await self._write("weather_rain_percent", setup.precipitation_ratio)
        if setup.runway_contamination is not None:
            await self._write(
                "weather_runway_friction",
                _RUNWAY_CONTAMINATION_TO_XPLANE[setup.runway_contamination],
            )

    def _require_weather_datarefs(self, *keys: str) -> None:
        """Raise :class:`XPlaneWeatherRejected` naming any of ``keys`` this build lacks.

        These datarefs are declared OPTIONAL (see :data:`OPTIONAL_DATAREFS`),
        so unlike the required set, ``connect()`` never caught their absence —
        this is where it is finally checked, at the point something actually
        needs one of them.
        """
        missing = sorted(key for key in keys if key not in self._ids)
        if missing:
            raise XPlaneWeatherRejected(
                "This X-Plane build does not expose the region weather datarefs needed "
                f"for this call: {', '.join(missing)}. They are declared OPTIONAL on this "
                "adapter (weather-manager.md §7 — their availability across 12.x builds is "
                "unverified) precisely so a build lacking them keeps repositioning working; "
                "weather control simply cannot proceed on this build."
            )

    async def _force_manual_weather_mode(self) -> None:
        """§7.1: read weather_source; force manual + static if it is not already.

        **Confirmed against a live X-Plane 12.4.3 install**
        (weather-manager.md §11.1, resolved) — see :data:`_WEATHER_SOURCE_MANUAL`'s
        docstring for the measurement. ``weather_source`` itself is read-only;
        the write goes to ``change_mode``/``update_immediately`` and
        ``weather_source`` is only ever read back, as the honest verdict on
        whether the mode actually took.

        Raises:
            XPlaneWeatherRejected: if ``weather_source`` still does not read
                back the manual value after the write — never proceed to write
                values the sim has announced it will overwrite.
        """
        mode = int(await self._read("weather_source"))
        if mode != _WEATHER_SOURCE_MANUAL:
            await self._write("weather_update_immediately", 1)
            await self._write("weather_change_mode", _WEATHER_CHANGE_MODE_STATIC)
            mode = int(await self._read("weather_source"))
        if mode != _WEATHER_SOURCE_MANUAL:
            raise XPlaneWeatherRejected(
                "X-Plane did not switch sim/weather/region/weather_source into manual mode "
                f"(read back {mode}); refusing to write values the sim has announced it will "
                "overwrite."
            )

    async def _write_wind_layers(self, layers: list[WindLayer]) -> None:
        """Distribute at most :data:`MAX_WIND_LAYERS` layers over the 13 region levels.

        Levels ``0..len(layers)-1`` get the given layers verbatim. Every level
        above that repeats the highest given layer's direction/speed/gust/
        turbulence at an ascending altitude above it (D10) — never a phantom
        shear at whatever stale altitude a previous weather left in that
        level. An empty list commands calm air, ascending altitude, at every
        level.
        """
        count = len(layers)
        for level in range(_WEATHER_WIND_LEVELS):
            if level < count:
                layer = layers[level]
                altitude_ft = layer.altitude_ft
                direction_deg = layer.direction_deg
                speed_kt = layer.speed_kt
                gust_kt = layer.gust_increase_kt
                turbulence_ratio = layer.turbulence_ratio
            elif count:
                highest = layers[-1]
                altitude_ft = highest.altitude_ft + _WEATHER_PADDING_ALTITUDE_STEP_FT * (
                    level - count + 1
                )
                direction_deg = highest.direction_deg
                speed_kt = highest.speed_kt
                gust_kt = highest.gust_increase_kt
                turbulence_ratio = highest.turbulence_ratio
            else:
                altitude_ft = _WEATHER_PADDING_ALTITUDE_STEP_FT * level
                direction_deg = 0.0
                speed_kt = 0.0
                gust_kt = 0.0
                turbulence_ratio = 0.0
            await self._write("wind_altitude_msl_m", altitude_ft * _METRES_PER_FOOT, index=level)
            await self._write("wind_direction_degt", direction_deg, index=level)
            await self._write("wind_speed_msc", speed_kt * _METRES_PER_SECOND_PER_KNOT, index=level)
            await self._write(
                "wind_shear_speed_msc", gust_kt * _METRES_PER_SECOND_PER_KNOT, index=level
            )
            await self._write("wind_shear_direction_degt", 0.0, index=level)
            await self._write(
                "weather_turbulence", turbulence_ratio * _TURBULENCE_SCALE_UNVERIFIED, index=level
            )

    async def _write_cloud_layers(self, layers: list[CloudLayer]) -> None:
        """Write at most :data:`MAX_CLOUD_LAYERS` layers into X-Plane's 3 slots, then
        wait for them to actually settle before returning.

        Unlike wind there is no distribution step (§7.2): each core layer maps
        directly onto one slot. An empty list zeroes every slot's coverage,
        which :meth:`_read_cloud_layers` reads back as "no layer here".

        **Confirmed against a live X-Plane 12.4.3 install**: unlike
        visibility/QNH/wind, a cloud dataref write is not visible on
        read-back for up to ~55s — not a smooth transition, a single jump at
        a periodic cycle boundary (see :meth:`_await_cloud_layers_settled`'s
        own docstring for the full measurement). Laminar's own docs say cloud
        *rendering* transitions visually over the update interval; this
        adapter measured the *dataref itself* lagging on the same ~60s cycle
        the real-weather engine already documents elsewhere
        (``WEATHER_HOLD_S`` in ``tests/adapters/test_contract.py``), which the
        design's §7.1 confidence table did not anticipate. Returning before
        the write has settled means the very next ``get_weather()`` — which
        is exactly what ``apply``'s read-back does — observes a stale,
        in-flight value. :meth:`_await_cloud_layers_settled` closes that gap.
        """
        count = len(layers)
        for slot in range(_WEATHER_CLOUD_LAYERS):
            if slot < count:
                layer = layers[slot]
                base_ft, tops_ft = layer.base_ft, layer.tops_ft
                coverage_ratio = layer.coverage_ratio
                cloud_type_value = _CLOUD_TYPE_TO_XPLANE[layer.cloud_type]
            else:
                base_ft = tops_ft = coverage_ratio = 0.0
                cloud_type_value = _CLOUD_TYPE_TO_XPLANE["cumulus"]
            await self._write("cloud_base_msl_m", base_ft * _METRES_PER_FOOT, index=slot)
            await self._write("cloud_tops_msl_m", tops_ft * _METRES_PER_FOOT, index=slot)
            await self._write("cloud_coverage_percent", coverage_ratio, index=slot)
            await self._write("cloud_type", cloud_type_value, index=slot)
        await self._await_cloud_layers_settled(layers)

    async def _await_cloud_layers_settled(self, layers: list[CloudLayer]) -> None:
        """Best-effort wait for every touched slot's commanded base/coverage to land.

        **Confirmed against a live X-Plane 12.4.3 install, and a stranger
        shape than "gradual transition" this docstring originally guessed**:
        a cloud write does not converge smoothly at all. Every slot holds an
        unrelated, uniform stale value — observed: the *same* number across
        all three slots simultaneously, itself a leftover from an earlier
        write — for up to ~55s, then every slot snaps to its own correct,
        distinct commanded value in the same instant. See
        :data:`_CLOUD_SETTLE_TIMEOUT_S`'s own docstring for the full
        measurement. This method waits, but never raises, even once the
        timeout passes — a caller wanting the fully-settled value should
        treat the first `get_weather()` after a cloud-bearing `set_weather()`
        as provisional if it returns before the observed ~55s cycle boundary.

        **Checks every slot this write touched, not only slot 0** — an
        earlier version of this method checked slot 0 alone, so a
        wholesale-replace write that zeroed a *different* slot (D3: a
        shorter layer list omits — and must zero — the slots past its own
        length) was declared "settled" the instant slot 0 landed, without
        ever confirming the omitted slot actually reached zero.
        """
        count = len(layers)
        targets: list[tuple[float, float]] = [
            (
                (layers[slot].base_ft * _METRES_PER_FOOT, layers[slot].coverage_ratio)
                if slot < count
                else (0.0, 0.0)
            )
            for slot in range(_WEATHER_CLOUD_LAYERS)
        ]
        deadline = asyncio.get_running_loop().time() + _CLOUD_SETTLE_TIMEOUT_S
        while asyncio.get_running_loop().time() < deadline:
            base_array = await self._read("cloud_base_msl_m")
            coverage_array = await self._read("cloud_coverage_percent")
            if all(
                abs(float(base_array[slot]) - target_base_m) <= _CLOUD_SETTLE_BASE_TOLERANCE_M
                and abs(float(coverage_array[slot]) - target_coverage)
                <= _CLOUD_SETTLE_COVERAGE_TOLERANCE
                for slot, (target_base_m, target_coverage) in enumerate(targets)
            ):
                return
            await asyncio.sleep(_CLOUD_SETTLE_POLL_INTERVAL_S)

    async def _read_wind_level_altitudes_ft(self) -> list[float]:
        """The 13 region wind levels' altitudes, in feet MSL."""
        raw = await self._read("wind_altitude_msl_m")
        return [float(value) / _METRES_PER_FOOT for value in raw]

    async def _write_temperature_ladder(self, sea_level_temperature_c: float) -> None:
        """Sea-level temperature, plus the aloft ladder recomputed along the ISA lapse.

        The ladder shares the wind levels' altitude grid (D10: "13 wind/
        atmosphere levels" — the design's own wording; not independently
        confirmed here) so a warm day is warm all the way up rather than only
        at the beach. Ladder shape is "verify in spike" per §7.2.

        **A previous live session found this drifting continuously
        (~+0.7 °C/s) regardless of ``change_mode`` and concluded it was
        permanently broken — that finding was wrong, and a later session
        traced why.** ``sim/weather/region/sealevel_temperature_c`` holds a
        written value perfectly (confirmed for a full 100s, zero drift) once
        X-Plane's real-weather engine has finished whatever in-flight
        interpolation it was doing at the moment ``change_mode`` was forced —
        a fresh boot (or a build that was recently in real-weather mode)
        leaves that engine actively converging toward the live METAR
        temperature for several minutes, and a write issued *during* that
        window gets overwritten by the tail end of it, in either direction,
        looking exactly like permanent drift if the observation window is
        short. This is a transient startup condition, not a structural
        limitation of the dataref or of ``change_mode=3``.
        """
        await self._write("weather_sealevel_temperature_c", sea_level_temperature_c)
        altitudes_ft = await self._read_wind_level_altitudes_ft()
        deviation_c = isa_deviation_c(sea_level_temperature_c, 0.0)
        for level, altitude_ft in enumerate(altitudes_ft):
            await self._write(
                "weather_temperatures_aloft",
                temperature_from_deviation_c(altitude_ft, deviation_c),
                index=level,
            )

    async def _write_dewpoint_ladder(self, sea_level_dewpoint_c: float) -> None:
        """Surface dewpoint, plus upper levels clamped at or below the temperature ladder.

        §7.2, "medium" confidence: "surface entry from the field, upper
        entries kept at or below the recomputed temperature ladder" — a
        dewpoint above the local temperature is not physically representable.
        """
        await self._write("weather_dewpoint", sea_level_dewpoint_c, index=0)
        altitudes_ft = await self._read_wind_level_altitudes_ft()
        sea_level_temperature_c = float(await self._read("weather_sealevel_temperature_c"))
        deviation_c = isa_deviation_c(sea_level_temperature_c, 0.0)
        for level in range(1, len(altitudes_ft)):
            temperature_c = temperature_from_deviation_c(altitudes_ft[level], deviation_c)
            await self._write(
                "weather_dewpoint", min(sea_level_dewpoint_c, temperature_c), index=level
            )

    async def _read_wind_layers(self) -> list[WindLayer]:
        """Reconstruct the typed wind layers by collapsing padded duplicate levels.

        :meth:`_write_wind_layers` repeats the highest given layer's values at
        ascending altitudes above it, so consecutive levels sharing the same
        direction/speed/gust/turbulence are one commanded layer, not several.
        """
        altitudes_m, directions, speeds, shear_speeds, turbulences = await asyncio.gather(
            self._read("wind_altitude_msl_m"),
            self._read("wind_direction_degt"),
            self._read("wind_speed_msc"),
            self._read("wind_shear_speed_msc"),
            self._read("weather_turbulence"),
        )
        layers: list[WindLayer] = []
        previous_signature: tuple[float, float, float, float] | None = None
        for altitude_m, direction_deg, speed_msc, shear_msc, turbulence in zip(
            altitudes_m, directions, speeds, shear_speeds, turbulences, strict=True
        ):
            signature = (
                round(float(direction_deg), 3),
                round(float(speed_msc), 3),
                round(float(shear_msc), 3),
                round(float(turbulence), 3),
            )
            if signature == previous_signature:
                continue  # a padded duplicate of the previous layer (D10/§7.2)
            layers.append(
                WindLayer(
                    altitude_ft=float(altitude_m) / _METRES_PER_FOOT,
                    direction_deg=float(direction_deg) % 360.0,
                    speed_kt=float(speed_msc) / _METRES_PER_SECOND_PER_KNOT,
                    gust_increase_kt=float(shear_msc) / _METRES_PER_SECOND_PER_KNOT,
                    turbulence_ratio=float(turbulence) / _TURBULENCE_SCALE_UNVERIFIED,
                )
            )
            previous_signature = signature
        return layers[:MAX_WIND_LAYERS]

    async def _read_cloud_layers(self) -> list[CloudLayer]:
        """Reconstruct the typed cloud layers, skipping slots at zero coverage."""
        bases_m, tops_m, coverages, types = await asyncio.gather(
            self._read("cloud_base_msl_m"),
            self._read("cloud_tops_msl_m"),
            self._read("cloud_coverage_percent"),
            self._read("cloud_type"),
        )
        layers: list[CloudLayer] = []
        for base_m, top_m, coverage, cloud_type_value in zip(
            bases_m, tops_m, coverages, types, strict=True
        ):
            if float(coverage) <= 0.0:
                continue  # an empty slot -- §3.2's "[] commands clear skies", read back
            base_ft = float(base_m) / _METRES_PER_FOOT
            tops_ft = float(top_m) / _METRES_PER_FOOT
            if tops_ft <= base_ft:
                # CloudLayer requires tops_ft > base_ft; a degenerate read (a slot the
                # sim itself has not populated coherently) is nudged rather than
                # dropped, since coverage > 0 said this slot is meant to be a layer.
                tops_ft = base_ft + 1.0
            type_index = round(float(cloud_type_value))
            cloud_type = _CLOUD_TYPE_FROM_XPLANE[
                max(0, min(type_index, len(_CLOUD_TYPE_FROM_XPLANE) - 1))
            ]
            layers.append(
                CloudLayer(
                    base_ft=base_ft,
                    tops_ft=tops_ft,
                    coverage_ratio=min(1.0, float(coverage)),
                    cloud_type=cloud_type,
                )
            )
        return layers[:_WEATHER_CLOUD_LAYERS]

    async def _qnh_hpa_or_standard(self) -> float:
        """The commanded QNH, or the ISA standard value on a build missing the dataref.

        Issue #42.2. The fallback reproduces the historical assumption
        exactly (MSL elevation used as pressure altitude), so a build without
        the region weather datarefs degrades to the old behaviour rather than
        failing a placement.
        """
        if "weather_sealevel_pressure_pas" not in self._ids:
            return _ISA_SEA_LEVEL_PRESSURE_HPA
        return float(await self._read("weather_sealevel_pressure_pas")) / _PASCALS_PER_HPA

    async def _optional_wind_correction(self, altitude_ft: float) -> tuple[float, float]:
        """Best-effort wind at ``altitude_ft`` for issue #42.1.

        ``(0.0, 0.0)`` — no correction, reproducing the historical still-air
        assumption — on a build that does not expose the region wind
        datarefs. This is a read, not a write, so it needs none of
        ``set_weather``'s manual-mode forcing: whatever wind is currently in
        effect, real or manual, is what the aircraft is actually flying
        through, and that observation is what a placement needs.
        """
        keys = ("wind_altitude_msl_m", "wind_direction_degt", "wind_speed_msc")
        if not all(key in self._ids for key in keys):
            return 0.0, 0.0
        return await self._wind_at_altitude(altitude_ft)

    async def _wind_at_altitude(self, altitude_ft: float) -> tuple[float, float]:
        """Interpolate the commanded wind at ``altitude_ft`` from the raw 13 region levels.

        Reads the raw levels directly rather than the reconstructed,
        collapsed ``WeatherState`` — issue #42 needs the wind exactly where
        the aircraft is placed, which the collapsed <=3-layer view would have
        to re-expand to answer anyway.

        Returns:
            ``(direction_deg, speed_kt)``, linearly interpolated between the
            two bracketing levels (direction interpolated the short way round
            the 000/360 wrap), or clamped to the nearest end beyond the
            ladder.
        """
        altitudes_m, directions_deg, speeds_msc = await asyncio.gather(
            self._read("wind_altitude_msl_m"),
            self._read("wind_direction_degt"),
            self._read("wind_speed_msc"),
        )
        levels = sorted(
            zip(
                (float(value) / _METRES_PER_FOOT for value in altitudes_m),
                (float(value) for value in directions_deg),
                (float(value) / _METRES_PER_SECOND_PER_KNOT for value in speeds_msc),
                strict=True,
            )
        )
        if not levels:
            return 0.0, 0.0
        if altitude_ft <= levels[0][0]:
            return levels[0][1], levels[0][2]
        if altitude_ft >= levels[-1][0]:
            return levels[-1][1], levels[-1][2]
        for (lower_ft, lower_dir, lower_spd), (upper_ft, upper_dir, upper_spd) in pairwise(levels):
            if lower_ft <= altitude_ft <= upper_ft:
                fraction = (
                    0.0
                    if upper_ft == lower_ft
                    else (altitude_ft - lower_ft) / (upper_ft - lower_ft)
                )
                direction_deg = (
                    lower_dir + fraction * _angular_difference(lower_dir, upper_dir)
                ) % 360.0
                speed_kt = lower_spd + fraction * (upper_spd - lower_spd)
                return direction_deg, speed_kt
        return levels[-1][1], levels[-1][2]

    async def get_loadout(self) -> LoadoutState:
        """Read the current fuel and payload from ``m_fuel``/``m_stations``.

        Both arrays are read whole (the Web API returns the full fixed-size
        array on a plain read) and sliced in Python against
        :func:`_resolve_known_slot_count` — see that function for why the
        slice length itself is not fully trusted. Every slot in the resulting
        range becomes a :class:`~core.models.TankFuel`/
        :class:`~core.models.PayloadStation`, ``kind``/``label`` left at their
        defaults: X-Plane's arrays are bare masses at bare positions, and this
        adapter has no per-aircraft mapping to a "Pilot"/"Rear seats" label
        (§6.2's ``PayloadStation`` docstring).

        Raises:
            CapabilityNotSupported: if ``can_set_fuel_payload`` is ``False`` —
                not reachable on this adapter today, since the flag is
                ``True`` (§6.4, live-validated).
        """
        if not self.capabilities.can_set_fuel_payload:
            raise CapabilityNotSupported(self.name, "can_set_fuel_payload")

        raw_fuel, raw_stations, raw_tank_count = await asyncio.gather(
            self._read("fuel_tank_kg"),
            self._read("payload_station_kg"),
            self._read_optional("acf_num_tanks"),
        )
        tank_count = _resolve_known_slot_count(raw_tank_count, len(raw_fuel), MAX_FUEL_TANKS)
        # No station-count candidate is named anywhere in the design (see
        # OPTIONAL_DATAREFS's comment) — always the whole array, clamped.
        station_count = _resolve_known_slot_count(None, len(raw_stations), MAX_PAYLOAD_STATIONS)
        return LoadoutState(
            tanks=[
                TankFuel(tank_index=index, fuel_kg=max(0.0, float(raw_fuel[index])))
                for index in range(tank_count)
            ],
            stations=[
                PayloadStation(station_index=index, weight_kg=max(0.0, float(raw_stations[index])))
                for index in range(station_count)
            ],
        )

    # -- Failures -----------------------------------------------------------
    #
    # can_inject_failures stays False on this adapter (D11 plus this session's
    # explicit instruction — see the module docstring of
    # adapters/xplane/failure_datarefs.py for why). The four methods below are
    # nonetheless real implementations, not stubs: the dataref mapping and the
    # connect-time probing that makes a wrong guess degrade instead of throw
    # (§5.3) are both live, so flipping the flag once a spike has verified
    # §5.1's value enum against a real install is the only change this manager
    # still needs. Until then every one of these methods is dead code in
    # production — the capability check on the first line of each guarantees
    # it — but it is exercised by nothing less than the same
    # DATAREFS/OPTIONAL_DATAREFS-style resolution the rest of this adapter
    # already relies on, so there is nothing hand-wavy left to write once the
    # flag flips.

    async def get_failure_support(self) -> FailureSupportManifest:
        """Every catalogue entry, resolved against this adapter and this install.

        A capability-free read (failures-manager.md D4): "no" is an answer,
        never an exception. Without ``can_inject_failures`` declared, every
        entry is unsupported with that one reason — the flag gates the whole
        group before any per-entry question is even asked. With the flag
        declared, each entry is resolved against §5.2's mapping and this
        install's dataref index (§5.3): an entry with no known dataref at all
        carries :attr:`~adapters.xplane.failure_datarefs.FailureDatarefMapping.unsupported_reason`;
        an entry with a guess that did not resolve at :meth:`connect` time
        carries the same posture as any other optional dataref on this
        adapter — disabled, with a reason, never a runtime throw.
        """
        if not self.capabilities.can_inject_failures:
            reason = f"{self.name!r} does not declare can_inject_failures."
            return FailureSupportManifest(
                caveat=None,
                entries=tuple(
                    FailureSupport(failure_id=spec.failure_id, supported=False, reason=reason)
                    for spec in FAILURE_CATALOGUE
                ),
            )
        entries = []
        for spec in FAILURE_CATALOGUE:
            mapping = FAILURE_DATAREFS[spec.failure_id]
            if mapping.unsupported_reason is not None:
                entries.append(
                    FailureSupport(
                        failure_id=spec.failure_id,
                        supported=False,
                        reason=mapping.unsupported_reason,
                    )
                )
                continue
            representative_index = 1 if spec.takes_engine_index else None
            if (spec.failure_id, representative_index) in self._failure_ids:
                entries.append(FailureSupport(failure_id=spec.failure_id, supported=True))
            else:
                paths = ", ".join(dataref_paths_for(spec.failure_id, representative_index))
                entries.append(
                    FailureSupport(
                        failure_id=spec.failure_id,
                        supported=False,
                        reason=f"No {paths!r} dataref on this X-Plane install.",
                    )
                )
        return FailureSupportManifest(caveat=_FAILURE_MANIFEST_CAVEAT, entries=tuple(entries))

    async def inject_failure(self, failure: FailureRef) -> None:
        """Write :data:`~adapters.xplane.failure_datarefs.STATE_FAILED` to every mapped dataref.

        Idempotent: writing the same "failed now" value twice is a no-op as
        far as the simulator is concerned.
        """
        if not self.capabilities.can_inject_failures:
            raise CapabilityNotSupported(self.name, "can_inject_failures")
        for dataref_id in self._resolved_failure_dataref_ids(failure):
            await self._write_by_id(dataref_id, STATE_FAILED)

    async def clear_failure(self, failure: FailureRef) -> None:
        """Write :data:`~adapters.xplane.failure_datarefs.STATE_WORKING` to every mapped dataref."""
        if not self.capabilities.can_inject_failures:
            raise CapabilityNotSupported(self.name, "can_inject_failures")
        for dataref_id in self._resolved_failure_dataref_ids(failure):
            await self._write_by_id(dataref_id, STATE_WORKING)

    async def clear_all_failures(self) -> None:
        """Fire ``fix_all_systems`` and write "working" to every resolved failure dataref.

        Both (§5.1): the command is believed to repair everything, and the
        explicit zeros make the outcome independent of that belief.
        """
        if not self.capabilities.can_inject_failures:
            raise CapabilityNotSupported(self.name, "can_inject_failures")
        await self._activate("fix_all_systems")
        for dataref_ids in self._failure_ids.values():
            for dataref_id in dataref_ids:
                await self._write_by_id(dataref_id, STATE_WORKING)

    async def get_active_failures(self) -> tuple[ActiveFailure, ...]:
        """Read every resolved failure dataref; an entry is active iff any of them reads "failed".

        A capability-free read (D10): the simulator is the source of truth,
        never a ledger of what was asked for — a teleport's ``fix_all_systems``
        repairs every failure behind any ledger's back, so a read that trusted
        one would lie the moment the Position Manager is used mid-exercise.
        """
        if not self.capabilities.can_inject_failures:
            return ()
        active: list[ActiveFailure] = []
        for spec in FAILURE_CATALOGUE:
            engine_indices: tuple[int | None, ...] = (
                tuple(range(1, 9)) if spec.takes_engine_index else (None,)
            )
            for engine_index in engine_indices:
                dataref_ids = self._failure_ids.get((spec.failure_id, engine_index))
                if not dataref_ids:
                    continue
                values = await asyncio.gather(
                    *(self._read_by_id(dataref_id) for dataref_id in dataref_ids)
                )
                if any(int(value) == STATE_FAILED for value in values):
                    active.append(
                        ActiveFailure(failure_id=spec.failure_id, engine_index=engine_index)
                    )
        return tuple(active)

    def _resolved_failure_dataref_ids(self, failure: FailureRef) -> tuple[int, ...]:
        """The dataref ids one :class:`~core.failures.FailureRef` resolves to on this install.

        Raises:
            CapabilityNotSupported: the entry (or this specific engine index of
                it) did not resolve at :meth:`connect` time — an unsupported
                entry reached this far, which should never happen once the UI
                gates on :meth:`get_failure_support`, but this is the defence
                the design asks for regardless (§4: "an unsupported failure_id
                raises CapabilityNotSupported").
        """
        dataref_ids = self._failure_ids.get((failure.failure_id, failure.engine_index))
        if not dataref_ids:
            raise CapabilityNotSupported(self.name, "can_inject_failures")
        return dataref_ids

    async def _read_optional(self, key: str) -> Any | None:
        """Read one optional dataref, or ``None`` when this build lacks it."""
        if key not in self._ids:
            return None
        return await self._read(key)

    async def read_dataref(self, key: str) -> Any:
        """Read one dataref by its short :data:`DATAREFS` key.

        A deliberate escape hatch for diagnostics that need a raw value the
        typed API does not expose (the local frame coordinates, mostly).
        Application code should use :meth:`get_aircraft_state` instead.

        Args:
            key: A key of :data:`DATAREFS`, not a full dataref path.
        """
        return await self._read(key)

    async def write_dataref(
        self, key: str, value: float | int | bool, index: int | None = None
    ) -> None:
        """Write one dataref by its short :data:`DATAREFS`/:data:`OPTIONAL_DATAREFS` key.

        The write-side twin of :meth:`read_dataref` — a deliberate escape
        hatch for diagnostics (``spikes/weather_datarefs.py`` is the reason
        this exists: it needs to try candidate writes to weather datarefs this
        adapter does not yet expose a typed method for). Application code
        should use :meth:`set_position`/:meth:`apply_setup`/:meth:`set_weather`
        instead.

        Args:
            key: A key of :data:`DATAREFS` or :data:`OPTIONAL_DATAREFS`, not a
                full dataref path.
            value: The value to write.
            index: The array index to write, for indexed datarefs. ``None``
                writes the whole (scalar) dataref.
        """
        await self._write(key, value, index=index)

    async def measure_local_frame_origin(self) -> LocalFrameOrigin:
        """Measure the origin of X-Plane's local frame from the aircraft itself.

        The aircraft's position is readable in both coordinate systems at once,
        and that single pair pins the frame down exactly. This is deliberately
        *not* read from ``lat_ref``/``lon_ref``, which were measured to be wrong
        by 200 km — see the module docstring.

        Returns:
            The frame origin, including the vertical datum offset.
        """
        keys = ("latitude", "longitude", "elevation", "local_x", "local_y", "local_z")
        raw = await asyncio.gather(*(self._read(key) for key in keys))
        values = dict(zip(keys, raw, strict=True))
        return origin_from_observation(
            GeoPosition(
                latitude=float(values["latitude"]),
                longitude=float(values["longitude"]),
                altitude_ft=float(values["elevation"]) / _METRES_PER_FOOT,
            ),
            LocalCoordinates(
                x_m=float(values["local_x"]),
                y_m=float(values["local_y"]),
                z_m=float(values["local_z"]),
            ),
        )

    # -- Writes -----------------------------------------------------------

    @asynccontextmanager
    async def frozen_flight_model(self) -> AsyncIterator[None]:
        """Hold X-Plane's flight model still for the duration of the block.

        Steps 1 and 4 of the five-step procedure, in one place. Every write into
        ``sim/flightmodel/position/*`` belongs inside this — position, velocity
        *and* attitude. A running flight model resettles what you wrote within a
        frame or two, and the failure is not subtle: writing a 322.21° heading
        into a live model at LEMD produced 286.9° and left the aircraft inverted
        on the runway at ``phi = -180.0``. The same write inside this block read
        back 322.2° frozen and 322.3° after the release.

        On exit the override is released and the sim is given
        :data:`_RELEASE_SETTLE_S` to resume integrating, so the caller reads back
        a settled aircraft rather than one mid-transition. Whatever pitch and
        roll the aircraft has by then is it settling onto its landing gear — a
        physical result, not an error in the write.

        The release lives in a ``finally`` and that is the single most important
        line in this method: a leaked ``override_planepath`` freezes the user's
        aircraft indefinitely, with nothing in the UI to explain why.

        **It is re-entrant** (issue #48). A caller can hold one freeze around
        :meth:`set_position` or :meth:`apply_setup` *and* its own read-back, so
        the value it verifies is the value that was written rather than whatever
        the aircraft flew to afterwards — an airborne aircraft with nobody flying
        it was measured turning 4° to 170° between the write and the read. Only
        the outermost block writes ``override_planepath`` and pays the settle
        delays; nested blocks are no-ops. The nesting is a depth counter on a
        single task, not a cross-task lock: two concurrent tasks freezing the
        same adapter are not supported, and neither is anything else about
        driving one simulator from two places at once.

        Yields:
            ``None``. The block runs with the flight model frozen.
        """
        if self._freeze_depth == 0:
            await self._write("override_planepath", 1, index=0)
        self._freeze_depth += 1
        try:
            if self._freeze_depth == 1:
                await asyncio.sleep(_OVERRIDE_SETTLE_S)
            yield
        finally:
            self._freeze_depth -= 1
            if self._freeze_depth == 0:
                await self._write("override_planepath", 0, index=0)
                await asyncio.sleep(_RELEASE_SETTLE_S)

    async def set_position(
        self,
        position: GeoPosition,
        heading_deg: float,
        *,
        ias_kt: float | None = None,
        vertical_speed_fpm: float | None = None,
    ) -> None:
        """Teleport the aircraft, carrying ``ias_kt`` — or its current speed — onto the new heading.

        Runs the five-step procedure documented at the top of this module. The
        arrival is verified *while the flight model is still frozen*, so the
        check measures placement rather than a second of subsequent flight.

        **It aims more than once when it has to (issue #36).** A local-frame
        coordinate only means something in the frame it was computed in, and a
        teleport long enough to trigger a scenery reload moves that frame:
        Madrid to Heathrow used to write coordinates X-Plane accepted, land the
        aircraft somewhere else entirely, and then poll a target it could never
        converge on for the full budget. So a placement that has not arrived by
        the end of its slice is not waited out — the frame is re-measured, the
        target is recomputed in it, and the placement is written again. The
        convergence criterion is unchanged and is the only one that cannot lie:
        the aircraft's *world* position, which X-Plane derives from whatever
        frame is current, read back through :meth:`_position_matches`.

        The whole loop runs inside one freeze, which matters for the re-measure
        as much as for the write: the origin is recovered from the aircraft's own
        position read in two coordinate systems, and on a moving aircraft those
        reads describe two different instants.

        Args:
            position: Target position, ``altitude_ft`` interpreted as MSL.
            heading_deg: Target true heading in degrees.
            ias_kt: Indicated airspeed to arrive at. ``None`` reads the
                aircraft's current speed instead — see the note below on why a
                placement must not rely on that.
            vertical_speed_fpm: Vertical speed to arrive with, feet per minute,
                positive up. ``None`` arrives level. A caller that applied a
                setup carrying a descent must pass it here too, for exactly the
                reason ``ias_kt`` exists: the vector written here is the whole
                velocity, and it used to be unconditionally level (issue #81).

        Raises:
            XPlaneRepositionFailed: if the aircraft did not arrive within
                :data:`POSITION_WRITE_TOLERANCE_M` after
                :data:`_MAX_REPOSITION_WRITES` attempts or
                :data:`_REPOSITION_TIMEOUT_S`, whichever comes first. Never
                reports an unobserved success.
        """
        origin = await self.measure_local_frame_origin()
        # Reading the speed back is only right when the caller has no opinion. A
        # placement does: it has just applied a setup, the flight model was
        # released at the end of it, and the aircraft has been decelerating ever
        # since — so the value read here is the decayed one, and preserving it
        # faithfully is how a 120 kt final arrived at 83 kt (issue #39).
        speed_kt = ias_kt if ias_kt is not None else (await self.get_aircraft_state()).ias_kt
        # Resolved before the aircraft moves and against the *target* altitude:
        # the atmosphere the speed has to be true in is the destination's, and the
        # one the sim can be asked about is the departure's.
        tas_kt = await self._true_airspeed_kt(speed_kt, position.altitude_ft)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + _REPOSITION_TIMEOUT_S
        attempts = 0
        arrived = False

        async with self.frozen_flight_model():
            for attempt in range(_MAX_REPOSITION_WRITES):
                if attempt:
                    if loop.time() >= deadline:
                        break
                    # The previous aim missed. Either the write never took, or
                    # the frame it was expressed in no longer exists — and the
                    # second is both the likelier and the recoverable one.
                    origin = await self._settled_local_frame_origin(deadline)
                attempts += 1
                await self._write_placement(
                    position, heading_deg, tas_kt, origin, vertical_speed_fpm
                )
                arrived = await self._await_arrival(position, deadline)
                if arrived:
                    break

        await self.clear_crash_state()

        if not arrived:
            raise XPlaneRepositionFailed(
                f"The aircraft did not arrive within {POSITION_WRITE_TOLERANCE_M:.0f} m of "
                f"{position.latitude:.6f}, {position.longitude:.6f} after {attempts} attempt(s) "
                "at writing the local frame coordinates, each one aimed with a freshly measured "
                "frame origin. A frame that keeps moving is not the explanation at this point: "
                "the origin measurement or the local axis convention may be wrong on this build. "
                "Run spikes/xplane_connection.py, which prints the calibration residual, before "
                "trusting any further placement."
            )

    async def _write_placement(
        self,
        position: GeoPosition,
        heading_deg: float,
        tas_kt: float,
        origin: LocalFrameOrigin,
        vertical_speed_fpm: float | None = None,
    ) -> None:
        """Steps 2 and 3 of the procedure, expressed in one frame.

        Kept together because they share that frame and must not be split
        across a re-aim: the local axes are the east/up/north triad **at the
        anchor**, so an anchor that moved several hundred kilometres has rotated
        them by the convergence of the meridians between the two. A re-aim that
        rewrote the coordinates but kept the old velocity vector would put the
        aircraft in the right place flying a heading it was not asked for.

        Args:
            position: Target position, ``altitude_ft`` interpreted as MSL.
            heading_deg: Target true heading in degrees.
            tas_kt: True airspeed to carry onto that heading, in knots.
            origin: The frame ``position`` is to be projected into.
            vertical_speed_fpm: Vertical component of the arrival velocity,
                feet per minute, positive up. ``None`` arrives level.
        """
        target = world_to_local(origin, position)
        await self._write("local_x", target.x_m)
        await self._write("local_y", target.y_m)
        await self._write("local_z", target.z_m)
        await self._write_velocity_vector(
            heading_deg, tas_kt, vertical_speed_fpm, altitude_ft=position.altitude_ft
        )
        await self._write("psi", heading_deg % 360.0)

    async def _settled_local_frame_origin(self, deadline: float) -> LocalFrameOrigin:
        """Measure the frame origin, and keep measuring until it stops moving.

        Detecting that the frame moved is easy; knowing *when* the new one can
        be trusted is the actual problem, because a measurement taken mid-reload
        is exactly as wrong as the stale one it replaces. Two things make this
        safe, and neither is a fixed sleep:

        * **This is never called early.** It runs only after a whole
          :data:`_ARRIVAL_ATTEMPT_S` slice of *answered* polls has failed to see
          the aircraft arrive — see that constant for why that rules out "the
          derived coordinates have not caught up yet" and why a simulator
          stalled inside a reload cannot be mistaken for a settled one.
        * **One measurement is not enough to conclude anything.** Sampling the
          instant of a shift yields an origin that is already historical, so
          :data:`_ORIGIN_STABLE_SAMPLES` consecutive measurements must agree to
          within :data:`_ORIGIN_SHIFT_TOLERANCE_M` before one is aimed with.
          Off a frozen aircraft in a settled frame that is satisfied on the
          first two samples, so the common recovery costs one extra round trip.

        And if both are somehow fooled, the caller's arrival check still refuses
        the result: a bad origin costs one more attempt, not a false success.

        Args:
            deadline: Event-loop time the whole reposition must finish by.
                Reaching it returns the latest measurement rather than raising —
                the verdict belongs to the arrival check, not to this.

        Returns:
            The frame origin to aim the next placement with.
        """
        loop = asyncio.get_running_loop()
        origin = await self.measure_local_frame_origin()
        agreements = 0
        while agreements < _ORIGIN_STABLE_SAMPLES:
            if loop.time() >= deadline:
                return origin
            await asyncio.sleep(_ORIGIN_SAMPLE_S)
            latest = await self.measure_local_frame_origin()
            moved_m = origin_separation_m(origin, latest)
            agreements = 0 if moved_m > _ORIGIN_SHIFT_TOLERANCE_M else agreements + 1
            origin = latest
        return origin

    async def _true_airspeed_kt(self, ias_kt: float, altitude_ft: float | None = None) -> float:
        """Convert an indicated airspeed to the true one for where the aircraft is *going*.

        ``local_vx/vy/vz`` is a **true** velocity, while every speed in this
        project's vocabulary is indicated (see :class:`core.models.AircraftSetup`).
        The two diverge with density altitude: at FL100 the same needle reading is
        16 % faster through the air, so a 210 kt final placed there arrived at
        244 kt indicated. :mod:`core.atmosphere` owns the maths; this method only
        supplies it with an atmosphere.

        **The altitude that matters is the target one, and it is why this is a
        separate method.** A placement is normally a jump. An aircraft parked at
        LEMD and sent to a hold at FL100 is still on the ground at the moment the
        speed is resolved, so reading its altitude back would apply the 3 %
        correction for 2 000 ft where 16 % was needed — silently reinstating most
        of the defect the conversion exists to remove. The caller states the
        destination, and calls this **before** writing the position, so the
        conversion never races the derived world coordinates the sim republishes
        a frame or two after a teleport.

        The ambient temperature can only be read where the aircraft is now, so it
        is carried to the target altitude at constant ISA deviation rather than
        used as-is: air cools with height on a hot day too, and a surface reading
        applied unchanged at FL100 pushes true airspeed the wrong way. See
        :func:`core.atmosphere.temperature_from_deviation_c`.

        **Issue #42.2 — pressure altitude now uses the real QNH.** The MSL
        altitude used to be handed to :mod:`core.atmosphere` as though it were
        the pressure altitude, which assumes standard pressure; a 30 hPa QNH
        deviation is worth about 1.5 % of true airspeed, against the 16 % the
        indicated/true split above replaces. It is now corrected via
        :data:`_PRESSURE_ALTITUDE_FT_PER_HPA` using
        ``sim/weather/region/sealevel_pressure_pas`` (:meth:`_qnh_hpa_or_standard`),
        which degrades to the historical standard-pressure assumption on a
        build that does not expose the region weather datarefs (they are
        OPTIONAL, see :data:`OPTIONAL_DATAREFS`) rather than failing the
        placement outright.

        **Issue #42.1 — the along-track wind offset is not corrected here.**
        The vector this speed feeds into is a *ground* velocity
        (:meth:`_write_velocity_vector`), so it is exact in still air and off
        by the along-track wind component otherwise. That correction needs
        the *target* altitude's wind, which is why it lives in
        :meth:`_write_velocity_vector` itself (via
        :meth:`_optional_wind_correction`) rather than here: this method only
        ever returns a true airspeed, and the wind subtraction has to happen
        after the heading is known, on the ground-velocity vector.

        Args:
            ias_kt: Indicated airspeed in knots.
            altitude_ft: MSL altitude the speed is meant for, or ``None`` to use
                the aircraft's current one — correct only when nothing in the
                same operation is moving it vertically.

        Returns:
            True airspeed in knots.
        """
        altitude_m, temperature_c, qnh_hpa = await asyncio.gather(
            self._read("elevation"),
            self._read("temperature_ambient_deg_c"),
            self._qnh_hpa_or_standard(),
        )
        observed_msl_ft = float(altitude_m) / _METRES_PER_FOOT
        # Constant across the small vertical range a placement covers: QNH
        # describes the whole local atmosphere, not a function of altitude.
        qnh_offset_ft = (_ISA_SEA_LEVEL_PRESSURE_HPA - qnh_hpa) * _PRESSURE_ALTITUDE_FT_PER_HPA
        observed_pressure_altitude_ft = observed_msl_ft + qnh_offset_ft
        deviation_c = isa_deviation_c(float(temperature_c), observed_pressure_altitude_ft)
        target_msl_ft = observed_msl_ft if altitude_ft is None else altitude_ft
        target_pressure_altitude_ft = target_msl_ft + qnh_offset_ft
        return tas_from_ias(
            ias_kt,
            target_pressure_altitude_ft,
            temperature_from_deviation_c(target_pressure_altitude_ft, deviation_c),
        )

    async def _write_velocity_vector(
        self,
        heading_deg: float,
        tas_kt: float,
        vertical_speed_fpm: float | None = None,
        altitude_ft: float | None = None,
    ) -> None:
        """Set the local velocity vector so the aircraft indicates ``tas_kt`` on ``heading_deg``.

        Writing zeros instead is what drops a repositioned aircraft out of the
        sky below stall speed, so the caller's speed is always carried over.

        ``vertical_speed_fpm`` is the up axis of the same vector. ``None`` (and
        0.0) arrive level — the historical behaviour, and the right one for
        every placement that is not descending. A value makes the aircraft
        already going down (or up) the slope when the flight model takes over:
        without it, the descent rate a setup commanded was destroyed here one
        call later (issue #81 — the vertical twin of issue #39). The horizontal
        component deliberately stays the full TAS rather than its cosine
        projection: at a 3° glide the difference is 0.14 %, noise against the
        wind and pressure effects issue #42 tracks.

        **Issue #42.1 — the vector written here is a ground velocity, and the
        aircraft's indicated airspeed responds to its velocity through the
        *air*.** ``local_vx/vy/vz`` used to be exactly the air-relative vector,
        which is only correct in still air; a headwind component now reads
        low and a tailwind component reads high on the aircraft's own
        instruments once the flight model takes over. The commanded wind at
        ``altitude_ft`` (:meth:`_optional_wind_correction`) is subtracted from
        the ground vector before it is written, so what is commanded is the
        air-relative velocity and what is written is ``air velocity - wind
        velocity`` — the ground velocity that produces it. With a wind FROM
        ``direction_deg`` at ``speed_kt``, subtracting the vector that points
        along ``direction_deg`` (rather than adding the one the air mass
        itself moves along, ``direction_deg + 180``) is the same operation:
        a headwind reduces the ground speed needed to indicate a given TAS.

        This is the mechanical half only. The vector X-Plane consumes is a true
        one; turning the instructor's *indicated* speed into it belongs to
        :meth:`_true_airspeed_kt`, which the caller runs before the aircraft
        moves.

        Args:
            heading_deg: True heading to fly, in degrees.
            tas_kt: True airspeed in knots. Negative values are clamped to zero
                rather than flying the aircraft backwards.
            vertical_speed_fpm: Vertical speed in feet per minute, positive up.
                ``None`` means level.
            altitude_ft: MSL altitude to look the commanded wind up at.
                ``None`` skips the wind correction and reproduces the
                historical still-air behaviour — right when the caller
                genuinely does not know the target altitude (see
                ``_write_flight_model_state``'s "stay where you are" case).
                Also degrades this way on a build that does not expose the
                region wind datarefs (:data:`OPTIONAL_DATAREFS`).
        """
        wind_direction_deg, wind_speed_kt = (
            await self._optional_wind_correction(altitude_ft)
            if altitude_ft is not None
            else (0.0, 0.0)
        )
        speed_ms = max(0.0, tas_kt) * _METRES_PER_SECOND_PER_KNOT
        heading = math.radians(heading_deg % 360.0)
        wind_heading = math.radians(wind_direction_deg % 360.0)
        wind_speed_ms = wind_speed_kt * _METRES_PER_SECOND_PER_KNOT
        vertical_ms = (vertical_speed_fpm or 0.0) * _METRES_PER_FOOT / 60.0
        await self._write(
            "local_vx", speed_ms * math.sin(heading) - wind_speed_ms * math.sin(wind_heading)
        )
        await self._write("local_vy", vertical_ms)
        await self._write(
            "local_vz", -speed_ms * math.cos(heading) + wind_speed_ms * math.cos(wind_heading)
        )

    async def clear_crash_state(self) -> None:
        """Repair the aircraft if the sim decided the teleport was an impact.

        X-Plane reads a large position jump as a crash and renders the aircraft
        wrecked. ``sim/operation/fix_all_systems`` clears it. Cheap and
        idempotent, so it runs unconditionally after every reposition.
        """
        await self._activate("fix_all_systems")

    async def has_crashed(self) -> bool:
        """True if X-Plane currently considers the aircraft wrecked."""
        return bool(await self._read("has_crashed"))

    async def _await_arrival(self, target: GeoPosition, deadline: float) -> bool:
        """Poll until the aircraft is at ``target``, or until this attempt's slice ends.

        Returns as soon as it has arrived, so a short hop costs one round trip
        and only a scenery-reload-sized teleport pays any wait at all.

        The slice is :data:`_ARRIVAL_ATTEMPT_S` rather than the whole budget on
        purpose: waiting longer cannot make an aircraft that is in the wrong
        place arrive, and it is exactly the mistake issue #36 was — thirty
        seconds spent polling a target computed in a frame that no longer
        existed. Failing the slice is what tells the caller to go and look at
        the frame instead of waiting harder.

        Args:
            target: Where the aircraft was told to go.
            deadline: Event-loop time the whole reposition must finish by. The
                slice never runs past it.

        Returns:
            True if the aircraft reached ``target`` within
            :data:`POSITION_WRITE_TOLERANCE_M`.
        """
        loop = asyncio.get_running_loop()
        attempt_deadline = min(deadline, loop.time() + _ARRIVAL_ATTEMPT_S)
        while True:
            if await self._position_matches(target):
                return True
            if loop.time() >= attempt_deadline:
                return False
            await asyncio.sleep(_ARRIVAL_POLL_S)

    async def _position_matches(self, target: GeoPosition) -> bool:
        """True if the aircraft is within the write tolerance of ``target``."""
        latitude, longitude = await asyncio.gather(self._read("latitude"), self._read("longitude"))
        here = GeoPosition(latitude=float(latitude), longitude=float(longitude))
        distance_nm, _ = distance_and_bearing(here, target)
        return distance_nm * METRES_PER_NAUTICAL_MILE <= POSITION_WRITE_TOLERANCE_M

    async def apply_setup(self, setup: AircraftSetup) -> None:
        """Apply every field of ``setup`` that is set, leaving the rest untouched.

        The fields split in two, and the split is the whole point of this
        method's shape:

        * **Flight-model state** — attitude, vertical speed, altitude, airspeed.
          These are fought by a running flight model, so they are written inside
          :meth:`frozen_flight_model`. Without the freeze, a commanded heading
          came back 7° off in the mild case and 164° off in the bad one, and an
          ``apply_setup`` call was observed leaving the aircraft inverted on the
          runway (issue #37).
        * **Configuration** — flaps, speedbrake, trim, gear, autobrake, lights,
          radios and the autopilot. Switches and knobs, which the flight model
          reads rather than overwrites. They are written *outside* the freeze so
          that changing a light does not pause the simulation.

        The freeze is engaged only when there is flight-model state to write, so
        a configuration-only setup — and an empty one — costs nothing.

        Args:
            setup: The configuration to apply. ``None`` fields are skipped.

        Raises:
            CapabilityNotSupported: for ``gross_weight_kg``/``fuel_kg``/
                ``loadout`` while this adapter does not declare
                ``can_set_fuel_payload`` (§6.4 — the mapping exists, the flag
                is not yet flipped). The whole call is refused, never
                half-applied, matching :class:`~adapters.fake.FakeSimAdapter`'s
                precedent for the same field group.
        """
        if not self.capabilities.can_set_fuel_payload and (
            setup.gross_weight_kg is not None
            or setup.fuel_kg is not None
            or setup.loadout is not None
        ):
            raise CapabilityNotSupported(self.name, "can_set_fuel_payload")

        await self._write_configuration(setup)
        await self._write_autopilot(setup)
        await self._write_flight_model_state(setup)

    async def _write_configuration(self, setup: AircraftSetup) -> None:
        """Write the switch-and-knob half of a setup. No freeze required.

        ``ils_freq_khz`` is an alias for the NAV1 frequency: X-Plane's ILS
        receiver *is* the NAV1 radio, so there is exactly one dataref behind
        the two fields. When a setup carries both, the explicit
        ``nav1_freq_khz`` wins — a radio field beats its alias.
        """
        writes: list[tuple[str, float | int | bool]] = []

        if setup.flaps_ratio is not None:
            writes.append(("flap_ratio", setup.flaps_ratio))
        if setup.speedbrake_ratio is not None:
            writes.append(("speedbrake_ratio", setup.speedbrake_ratio))
        if setup.elevator_trim_ratio is not None:
            writes.append(("elevator_trim", setup.elevator_trim_ratio))
        if setup.throttle_ratio is not None:
            writes.append(("throttle_ratio", setup.throttle_ratio))
        if setup.gear_down is not None:
            writes.append(("gear_handle_down", int(setup.gear_down)))
        if setup.autobrake_level is not None:
            writes.append(("autobrake_level", setup.autobrake_level))
        nav1_khz = setup.nav1_freq_khz if setup.nav1_freq_khz is not None else setup.ils_freq_khz
        if nav1_khz is not None:
            writes.append(("nav1_freq", nav1_khz // 10))
        if setup.nav2_freq_khz is not None:
            writes.append(("nav2_freq", setup.nav2_freq_khz // 10))
        if setup.obs1_deg is not None:
            writes.append(("obs1", setup.obs1_deg))
        if setup.obs2_deg is not None:
            writes.append(("obs2", setup.obs2_deg))
        if setup.lights is not None:
            for field, key in (
                ("landing", "landing_lights"),
                ("taxi", "taxi_lights"),
                ("nav", "nav_lights"),
                ("beacon", "beacon_lights"),
                ("strobe", "strobe_lights"),
            ):
                value = getattr(setup.lights, field)
                if value is not None:
                    writes.append((key, int(value)))

        for key, value in writes:
            await self._write(key, value)

        if setup.loadout is not None:
            await self._write_loadout(setup.loadout)

    async def _write_loadout(self, loadout: Loadout) -> None:
        """Write fuel and payload — indexed array writes, no freeze (D11/§6.1).

        Mass is an input the flight model reads each frame, not flight-model
        state a running integration re-derives and fights (unlike attitude —
        see the module docstring and §6.1), so this belongs beside the other
        configuration writes above rather than inside
        :meth:`frozen_flight_model`.

        ``tanks``/``stations`` replace the known set **wholesale** (D10, same
        as the Weather Manager's wind/cloud layers): a slot named in the
        provided list gets its stated mass; every other slot this adapter
        currently treats as real gets zeroed, so a two-tank write followed by
        a one-tank write does not leave the first tank's fuel stranded from
        the previous call. ``None`` leaves that half of the loadout alone
        entirely — no read, no write.

        **Resolved against a live X-Plane 12.4.3 install** (previously an open
        question for the live-validation pass): ``m_fuel``/``m_stations`` are
        fixed-size, physical X-Plane arrays — the loaded aircraft (Cessna
        172SP) genuinely has 2 fuel tanks and, since no station-count dataref
        exists anywhere on this build (confirmed by search, not merely
        undocumented), 9 payload stations, always. "Wholesale replace" can
        only ever zero a *known* slot, never make it stop existing —
        :func:`get_loadout` was never wrong to keep reporting the full known
        set after a shorter write; the earlier concern was that
        ``test_loadout_replaces_tanks_and_stations_wholesale`` expected the
        returned list's *length* to shrink to match. That expectation was the
        thing to fix, not this method: a real airframe's tank count is not
        runtime-configurable, and "``[]`` empties it" is honestly satisfied by
        every known tank reading 0 kg, the same way draining a real tank does
        not make it cease to exist. The contract test now asserts by mass at
        each named index instead of by list length — see its own docstring.
        Also fixed in the same live session: the tank-count candidate dataref
        named in the design (``sim/aircraft/weight/acf_num_tanks``) does not
        exist on this build at all; the real dataref is
        ``sim/aircraft/overflow/acf_num_tanks`` (different namespace), which
        reads back ``2`` — exactly the loaded aircraft's real tank count.
        """
        if loadout.tanks is not None:
            await self._write_tank_masses(loadout.tanks)
        if loadout.stations is not None:
            await self._write_station_masses(loadout.stations)

    async def _write_tank_masses(self, tanks: list[TankFuel]) -> None:
        """Write ``tanks`` to ``m_fuel``, zeroing every other known tank slot."""
        raw_fuel, raw_tank_count = await asyncio.gather(
            self._read("fuel_tank_kg"),
            self._read_optional("acf_num_tanks"),
        )
        tank_count = _resolve_known_slot_count(raw_tank_count, len(raw_fuel), MAX_FUEL_TANKS)
        fuel_by_index = {tank.tank_index: tank.fuel_kg for tank in tanks}
        # The union covers a caller naming an index this adapter did not
        # consider "known" (e.g. a build whose count dataref undercounts);
        # anything at or past the array X-Plane actually reported cannot be
        # written and is skipped rather than sent out of bounds.
        for index in sorted(set(range(tank_count)) | set(fuel_by_index)):
            if index >= len(raw_fuel):
                continue
            await self._write("fuel_tank_kg", fuel_by_index.get(index, 0.0), index=index)

    async def _write_station_masses(self, stations: list[PayloadStation]) -> None:
        """Write ``stations`` to ``m_stations``, zeroing every other known station slot."""
        raw_stations = await self._read("payload_station_kg")
        # No station-count candidate is named in the design (OPTIONAL_DATAREFS's
        # comment) — always the whole array, clamped.
        station_count = _resolve_known_slot_count(None, len(raw_stations), MAX_PAYLOAD_STATIONS)
        weight_by_index = {station.station_index: station.weight_kg for station in stations}
        for index in sorted(set(range(station_count)) | set(weight_by_index)):
            if index >= len(raw_stations):
                continue
            await self._write("payload_station_kg", weight_by_index.get(index, 0.0), index=index)

    async def _write_autopilot(self, setup: AircraftSetup) -> None:
        """Write the autopilot half of a setup. No freeze required.

        The autopilot is a panel, not a flight-model integration variable, so
        this runs outside :meth:`frozen_flight_model` exactly like the rest of
        the switches. Three X-Plane facts shape the method:

        * **The master switch and the flight director share one dataref.**
          ``autopilot_mode`` is a ladder — off / flight director / servos — so
          the two boolean fields are folded into a single value against the
          current one; see :meth:`_autopilot_mode_for`.
        * **The lateral modes are selected by command, not written.** X-Plane
          publishes ``nav_status``/``approach_status`` as read-only, and the
          modes are mutually exclusive, so "NAV off" can only mean "select
          another lateral mode". Wing-leveller is the neutral one.
        * **The speed selector is shared between knots and Mach.** Asking for a
          speed in knots therefore takes the dial out of Mach first — the same
          shape as forcing manual weather mode before writing a wind.

        Args:
            setup: The setup to apply. ``None`` fields are skipped, and a setup
                carrying no autopilot field at all costs nothing — not even a
                read.
        """
        if setup.autopilot_master is not None or setup.flight_director is not None:
            current = int(await self._read("autopilot_mode"))
            await self._write(
                "autopilot_mode",
                self._autopilot_mode_for(current, setup.flight_director, setup.autopilot_master),
            )

        # `is True` rather than truthiness throughout: `None` means "leave this
        # mode alone" and must not read as "switch it off".
        selected = [
            command for field, command in _LATERAL_MODE_COMMANDS if getattr(setup, field) is True
        ]
        if selected:
            for command in selected:
                await self._activate(command)
        elif any(getattr(setup, field) is False for field, _ in _LATERAL_MODE_COMMANDS):
            await self._activate("autopilot_wing_leveler")

        if setup.target_altitude_ft is not None:
            await self._write("autopilot_altitude_dial_ft", setup.target_altitude_ft)
        if setup.target_ias_kt is not None:
            await self._write("autopilot_airspeed_is_mach", 0)
            await self._write("autopilot_airspeed_dial", setup.target_ias_kt)
        if setup.target_heading_deg is not None:
            await self._write("autopilot_heading_dial_deg", setup.target_heading_deg % 360.0)
        if setup.target_vertical_speed_fpm is not None:
            await self._write("autopilot_vvi_dial_fpm", setup.target_vertical_speed_fpm)

    @staticmethod
    def _autopilot_mode_for(current: int, flight_director: bool | None, master: bool | None) -> int:
        """Fold ``flight_director`` and ``master`` into one ``autopilot_mode`` value.

        The order is deliberate. The flight director is applied first because it
        is the lower rung of the ladder, then the master switch, so a
        contradictory setup (``flight_director=False`` together with
        ``autopilot_master=True``) resolves in favour of the servos — an engaged
        autopilot implies a flight director, never the other way round.

        Args:
            current: The mode X-Plane currently reports.
            flight_director: Requested flight director state, or ``None``.
            master: Requested servo state, or ``None``.

        Returns:
            The value to write to ``autopilot_mode``.
        """
        mode = current
        if flight_director is not None:
            mode = (
                max(mode, AUTOPILOT_MODE_FLIGHT_DIRECTOR) if flight_director else AUTOPILOT_MODE_OFF
            )
        if master is not None:
            mode = AUTOPILOT_MODE_SERVOS if master else min(mode, AUTOPILOT_MODE_FLIGHT_DIRECTOR)
        return mode

    async def _write_flight_model_state(self, setup: AircraftSetup) -> None:
        """Write the half of a setup the flight model would otherwise overwrite.

        Everything here goes inside :meth:`frozen_flight_model`, for the reasons
        in that method's docstring. The freeze is skipped entirely when the setup
        carries none of these fields — engaging it costs a pause and a settle,
        and there is nothing to protect.
        """
        # Attitude plus vertical speed: the fields that map straight onto a
        # single `sim/flightmodel/position/*` dataref.
        direct: list[tuple[str, float]] = []
        if setup.heading_deg is not None:
            direct.append(("psi", setup.heading_deg % 360.0))
        if setup.pitch_deg is not None:
            direct.append(("theta", setup.pitch_deg))
        if setup.roll_deg is not None:
            direct.append(("phi", setup.roll_deg))
        if setup.vertical_speed_fpm is not None:
            direct.append(("vh_ind_fpm", setup.vertical_speed_fpm))

        if not direct and setup.altitude_ft is None and setup.ias_kt is None:
            return

        # Resolved here, ahead of the freeze, because a setup that carries both an
        # altitude and a speed moves the aircraft before the speed is written: the
        # atmosphere the conversion needs is the one it is going to, and the only
        # one the sim can be asked about is the one it is leaving.
        tas_kt = (
            None
            if setup.ias_kt is None
            else await self._true_airspeed_kt(setup.ias_kt, setup.altitude_ft)
        )

        async with self.frozen_flight_model():
            for key, value in direct:
                await self._write(key, value)

            # Altitude is not assignable either: `elevation` is read-only and
            # derived from the local frame, so it goes through the up axis while
            # the horizontal position is left exactly where it was. Doing it
            # frozen also means the position it reads back is a single instant
            # rather than a moving aircraft sampled across several requests.
            if setup.altitude_ft is not None:
                await self._write_altitude(setup.altitude_ft)

            # Airspeed is not a dataref you can assign: it is derived from the
            # velocity vector, so it is written last, along whichever heading the
            # setup asked for (or the aircraft's current one). The vertical
            # speed rides the same vector: the `vh_ind_fpm` write above is the
            # indicator, this is the physics, and writing only the former left
            # the aircraft level (issue #81).
            if tas_kt is not None:
                heading = setup.heading_deg
                if heading is None:
                    heading = float(await self._read("psi"))
                # setup.altitude_ft is the same target _true_airspeed_kt resolved
                # tas_kt for above; None ("stay where you are") skips the issue #42
                # wind correction rather than re-reading the current elevation —
                # see _write_velocity_vector's altitude_ft docstring.
                await self._write_velocity_vector(
                    heading, tas_kt, setup.vertical_speed_fpm, altitude_ft=setup.altitude_ft
                )

    async def _write_altitude(self, altitude_ft: float) -> None:
        """Move the aircraft vertically, leaving its horizontal position alone."""
        origin = await self.measure_local_frame_origin()
        latitude, longitude = await asyncio.gather(self._read("latitude"), self._read("longitude"))
        local = world_to_local(
            origin,
            GeoPosition(
                latitude=float(latitude),
                longitude=float(longitude),
                altitude_ft=altitude_ft,
            ),
        )
        await self._write("local_y", local.y_m)

    # -- AI traffic -------------------------------------------------------
    # Track 0 stubs (ai-traffic.md §9.2): the capability plumbing is real —
    # can_spawn_traffic is resolved from the bridge probe at connect() — but
    # the probe is a stub returning False until Track B lands the bridge
    # transport (adapters/xplane/traffic_bridge.py), so the writes below can
    # only ever answer with the capability refusal, which is the truth.

    async def get_traffic_contacts(self) -> tuple[TrafficContact, ...]:
        """Capability-free read: with no probed bridge there is no traffic.

        Track B wires this to the bridge's ``ois/traffic/contacts`` dataref;
        until then "none" is the honest, cheap answer — never an exception.
        """
        return ()

    async def spawn_traffic(self, track: TrafficTrack) -> TrafficContact:
        """Refuse: this adapter never declares ``can_spawn_traffic`` today.

        The bridge probe is a Track B stub returning ``False``, so the flag is
        ``False`` on every connection and a caller reaching this ignored the
        capabilities — exactly what :class:`CapabilityNotSupported` means.
        """
        del track
        raise CapabilityNotSupported(self.name, "can_spawn_traffic")

    async def despawn_traffic(self, traffic_id: str) -> None:
        """Refuse — see :meth:`spawn_traffic`."""
        del traffic_id
        raise CapabilityNotSupported(self.name, "can_spawn_traffic")

    async def clear_all_traffic(self) -> None:
        """Refuse — see :meth:`spawn_traffic`."""
        raise CapabilityNotSupported(self.name, "can_spawn_traffic")

    # -- Streaming --------------------------------------------------------

    async def stream_state(self, interval_s: float) -> AsyncGenerator[AircraftState, None]:
        """Poll :meth:`get_aircraft_state` every ``interval_s`` seconds.

        Phase 0 polls over REST. The Web API's WebSocket (``/api/v2``) pushes
        dataref updates and will replace this once the subscription protocol is
        wired up.
        """
        while True:
            yield await self.get_aircraft_state()
            await asyncio.sleep(interval_s)

    async def stream_traffic(
        self, interval_s: float
    ) -> AsyncGenerator[tuple[TrafficContact, ...], None]:
        """Yield the full traffic picture every ``interval_s`` seconds.

        The same shape as :meth:`stream_state`, and capability-free like the
        read it wraps: without a bridge this yields ``()`` forever rather than
        raising, so the WS route iterates unconditionally.
        """
        while True:
            yield await self.get_traffic_contacts()
            await asyncio.sleep(interval_s)


if TYPE_CHECKING:  # pragma: no cover - static conformance check, never executed
    _CONFORMS: SimAdapter = XPlaneSimAdapter()
