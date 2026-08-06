# Spikes

Throwaway validation scripts. Not imported by the application, not covered by tests, not part of
the PyInstaller bundle. A spike exists to answer one question against real software; once it is
answered the answer belongs in `docs/` and in the adapter, not here.

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
