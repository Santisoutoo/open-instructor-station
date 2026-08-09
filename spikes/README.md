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
