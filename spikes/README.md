# Spikes

Throwaway validation scripts. Not imported by the application, not covered by tests, not part of
the PyInstaller bundle. A spike exists to answer one question against real software; once it is
answered the answer belongs in `docs/` and in the adapter, not here.

One exception, flagged so nobody deletes it during a clean-up: **`sim_lifecycle.py` is not
throwaway.** It answered its question and then became the thing the `sim-validator` agent and the
`sim-lifecycle` skill drive. It stays here because it is still developer tooling — outside the
application, outside the bundle, outside CI — but it has a consumer now.

## `xplane_connection.py`

**Question: can an external process read *and write* the aircraft position over the X-Plane 12.1+
Web API, with no plugin?**

That is the project's key technical risk. X-Plane's authoritative position lives in
`sim/flightmodel/position/local_x|local_y|local_z` (the OpenGL local frame);
`latitude`/`longitude`/`elevation` are *derived* from those every frame. Writing the derived
datarefs may simply be overwritten on the next frame, and the world→local conversion
(`XPLMWorldToLocal`) is a plugin-only API. Until this spike says otherwise,
`XPlaneSimAdapter.set_position` is unvalidated.

### Running it

1. Start X-Plane 12.1 or newer.
2. Enable the Web API: **Settings → Network → Web API** (default port 8086).
3. Load an aircraft and a location — preferably parked somewhere you do not mind leaving, because
   the spike moves the aircraft 5 NM north and does **not** put it back.
4. From the repository root, with the project's virtual environment:

```powershell
& .venv\Scripts\python.exe spikes\xplane_connection.py
# or against another machine on the LAN:
& .venv\Scripts\python.exe spikes\xplane_connection.py --host 192.168.1.20 --port 8086
```

### What the script does

| Step | What it proves |
|---|---|
| 1 | `GET /api/v2/datarefs` resolves the ids for latitude, longitude and elevation. |
| 2 | The WebSocket at `/api/v2` accepts a `dataref_subscribe_values` subscription and pushes ~10 live updates. |
| 3 | A position 5 NM north (computed with `core.geodesy`) is `PATCH`ed back, then read again — the before/after pair is printed so you can see whether it stuck. |
| 4 | A verdict line, and the next thing to try if it did not. |

### A successful run looks like this

```
X-Plane connection spike -> http://localhost:8086

[1/4] Resolved dataref ids: {'latitude': 1024, 'longitude': 1025, 'elevation': 1026}
[2/4] Opening WebSocket ws://localhost:8086/api/v2, subscribing to 3 datarefs
      update  1: {'1024': 40.493..., '1025': -3.566..., '1026': 609.6...}
      ...
      update 10: {'1024': 40.493..., '1025': -3.566..., '1026': 609.6...}
[3/4] BEFORE  lat=40.493600 lon=-3.566800
      TARGET  lat=40.576954 lon=-3.566800
      PATCH sim/flightmodel/position/latitude -> HTTP 200
      PATCH sim/flightmodel/position/longitude -> HTTP 200
      PATCH sim/flightmodel/position/elevation -> HTTP 200
      AFTER   lat=40.576951 lon=-3.566803
      moved 5.000 NM; 3 m from the target

[4/4] VERDICT
      REPOSITIONING OVER THE WEB API WORKS. ...
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Repositioning over the Web API works. |
| `1` | X-Plane was not reachable, or answered in an unexpected shape. The script prints what to check; it never dumps a traceback. |
| `2` | The API answered and the writes returned HTTP 200, but the aircraft did not move. Fall back to the legacy UDP `VEHX`/`VEH1` packet on port 49000 — the script prints the packet layout. |

### After the run

Record the outcome in `docs/` and update `adapters/xplane/xplane_adapter.py`: either delete the
"UNVALIDATED" warning from its module docstring, or implement the UDP fallback behind the same
`set_position` signature. Nothing else in the codebase should need to change — that is what the
`SimAdapter` seam is for.

## `weather_datarefs.py`

**Question: what value of `sim/weather/region/weather_source` actually means "manual", does the
Web API accept a write to it at all, and do gusts and turbulence use the datarefs
`docs/designs/weather-manager.md` §7.2 guesses at?**

Three separate unverified facts block flipping `XPlaneSimAdapter._CAPABILITIES.can_set_weather`
to `True` (§7.3): the manual-mode enum value (§11.1 — the one blocking unknown), whether gusts
ride the `shear_speed_msc`/`shear_direction_degt` pair or a dedicated dataref this adapter does
not know about (§11.2), and whether `sim/weather/region/turbulence` is scaled 0-1 or 0-10 (§11.3).
Not run against a live simulator as of the X-Plane adapter track of the Weather Manager (#14) — no
Docker Desktop and no running X-Plane were available in that session, so the mode-forcing sequence
in `XPlaneSimAdapter.set_weather` is written and ready for this spike's findings but unconfirmed.

### Running it

```powershell
& .venv\Scripts\python.exe spikes\weather_datarefs.py
# or against another machine on the LAN, with a longer hold window:
& .venv\Scripts\python.exe spikes\weather_datarefs.py --host 192.168.1.20 --hold-s 180
```

Load X-Plane into a flight with its weather still in the default **real weather** mode — the
manual-mode probe needs something to override. The script tries each candidate
`weather_source` value, writes a distinctive visibility after it, and watches for up to
`--hold-s` seconds (120 by default) whether real weather rewrites it — the operational definition
of "manual" used here, since no documentation for this exact enum exists in this repository. It
then pauses twice, asking you to set a gust and maximum turbulence in X-Plane's own weather
editor, and reads the region arrays back.

### After the run

Write the confirmed `weather_source` value into §7.1's table and into
`_WEATHER_SOURCE_MANUAL_UNVERIFIED` in `adapters/xplane/xplane_adapter.py` (dropping the
`_UNVERIFIED` suffix), correct the gust mapping if it is not the shear pair, and set
`_TURBULENCE_SCALE_UNVERIFIED` to whatever scale was observed. Only then does flipping
`can_set_weather = True` and running the §5.3 contract cases under `-m sim` become honest.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | A candidate `weather_source` value held for the full window; gust/turbulence findings printed. |
| `1` | X-Plane was not reachable, or this build does not expose the region weather datarefs at all (they are declared `OPTIONAL` on this adapter for exactly this case). |
| `2` | No candidate held. The script suggests the §11.1 fallback: check whether any region write flips the sim to manual by itself. |

## `bridge_transport.py` + `PI_OISBridgeSpike.py`

**Question: does the AI Traffic bridge transport of `docs/designs/ai-traffic.md` §5.1 actually
work, and at what cost?** Three unknowns, named in §10.4: (a) the command→ack round-trip latency
under flight-loop scheduling, (b) the `data`-dataref payload-size ceiling over the Web API —
is one JSON-encoded `TrafficTrack` safe in a single write? — and (c) whether AI/multiplayer
aircraft slots (`sim/multiplayer/position/plane1…`) can be driven for a spawned entity, and what
ground vehicles / birds need instead (XPLMInstance vs slots).

Two halves: `PI_OISBridgeSpike.py` is a **throwaway XPPython3 plugin** that registers the §5.1
custom datarefs (`ois/bridge/heartbeat_s`, `ois/traffic/command`, `ois/traffic/command_ack`,
`ois/traffic/contacts`) and answers commands from its flight loop; `bridge_transport.py` drives
the protocol from outside over the Web API and takes the measurements.

### Running it

1. Copy `spikes/PI_OISBridgeSpike.py` into
   `<X-Plane 12>/Resources/plugins/PythonPlugins/` (requires XPPython3). It must be there
   **before X-Plane starts** — the Web API indexes datarefs at startup.
2. Start X-Plane and load a flight (`spikes/sim_lifecycle.py launch` + `wait-ready` does this
   unattended).
3. From the repository root:

```powershell
& .venv\Scripts\python.exe spikes\bridge_transport.py
# or against another machine on the LAN:
& .venv\Scripts\python.exe spikes\bridge_transport.py --host 192.168.1.20 --port 8086
```

4. **Remove the plugin file (and its `__pycache__` entry) afterwards.** It is a measurement rig,
   not the real bridge, and nothing in the application ever depends on it.

### After the run

The measurements belong in `docs/designs/ai-traffic.md` §10.4 ("Spike findings"), where they
confirm or amend §5's transport design before Track B (`feature/traffic-bridge`) builds the real
plugin. They do not belong here.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All three measurements were taken; findings JSON printed. |
| `1` | X-Plane unreachable, or the `ois/*` datarefs are missing from the index (plugin not installed, or installed after launch). |
| `2` | The transport answered but a measurement failed; the output says which. |

## `sim_lifecycle.py`

**Question: can a test run drive the X-Plane 12 *process* — start it at a chosen airport, wait
for it to be flyable, shut it down — without a human clicking anything?**

Answered: yes. That is what unblocks automated live validation. Until this existed, `pytest -m sim`
and the `sim-validator` agent both required a person to have X-Plane already running, which is why
`docs/designs/live-contract-suite.md` had to record that the suite was **never run against a real
simulator**.

### This does not break hard rule 1

`CLAUDE.md` rule 1 — *"the app is 100% external, the user never opens or launches anything inside
the sim"* — is about **the application**. This script is not the application: nothing imports it,
it is excluded from the PyInstaller bundle and it never runs in CI. Launching an `.exe` from the
outside is not "opening something inside the simulator"; the instructor station still never does
it. Keep it that way — if this module ever acquires an importer under `core/`, `server/` or
`adapters/`, the rule has been broken.

### Subcommands

| Command | What it does |
|---|---|
| `status` | prints one of `not-running` / `menu` / `ready` |
| `list --apt LEMD` | the airport's runways and stands, straight from `apt.dat` |
| `launch --apt LEMD --rwy 32L` | writes the boot position and starts the process |
| `wait-ready --near-apt LEMD` | blocks until a flight is actually loaded there |
| `place --apt LEMD --rwy 32L` | puts the aircraft on the exact spot, via the adapter |
| `quit` | asks the sim to quit, kills it if it refuses, restores preferences |
| `restore-prefs` | restores preferences only, touching no process |

```powershell
& .venv\Scripts\python.exe spikes\sim_lifecycle.py launch --apt LEMD --rwy 32L
& .venv\Scripts\python.exe spikes\sim_lifecycle.py wait-ready --near-apt LEMD
& .venv\Scripts\python.exe spikes\sim_lifecycle.py place --apt LEMD --rwy 32L
& .venv\Scripts\python.exe spikes\sim_lifecycle.py quit
```

### What was measured, because the folklore is wrong

- **There is no `--load_acf` or `--load_apt`.** `X-Plane.exe --help` prints the whole flag list and
  neither is on it. What is: `--window=WxH`, `--no_sound`, `--no_joysticks`, `--pref:`, `--dref:`.
- **Left alone, X-Plane never starts flying.** It sits on the Quick Flight Loader screen waiting
  for a human. Measured: nine minutes after launch the Web API was answering **HTTP 200 with an
  empty dataref index**, because no flight existed to have datarefs about. `_show_qfl_on_start 0`
  in `Output/preferences/X-Plane.prf` is the fix; with it the sim is ready in about a minute.
  This is why "the API responds" is never the readiness test — `wait-ready` requires a plausible
  position, not a 200.
- **Only the *airport* in `_last_start` can be trusted.** Asking for LEBL 24R put the aircraft at
  LEBL on runway 02; asking for LEMD 18R put it at LEMD on the previous session's spot. So the
  boot position is used for the one thing it is reliable at — loading the right corner of the
  world — and `place` sets the exact spot afterwards through the adapter's validated path. That
  also keeps the teleport short, which sidesteps the scenery-reload failure of
  [#36](https://github.com/Santisoutoo/open-instructor-station/issues/36).

### It writes to the user's preferences

Choosing a boot position means editing `Output/preferences/Freeflight.prf` and `X-Plane.prf`. Both
are copied to `<name>.ois-backup` beside the original **before** the first edit, and only when a
backup is not already there — a previous run that died left the *pristine* copy, and overwriting it
would lose the user's settings for good. `quit` restores automatically; `restore-prefs` does it on
demand. If a run is killed, the backup survives and the next `launch` will not clobber it.

### Exit codes

Per subcommand, and documented on each one; `0` always means the thing asked for happened.
`status` is the exception — it always exits `0` because its answer is the word it prints, and three
states do not map onto success-or-failure.
