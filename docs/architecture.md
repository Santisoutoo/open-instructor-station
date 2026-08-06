# Architecture — Open Instructor Station

How the pieces fit together, why the boundaries are where they are, and what will break if they
move.

The binding rules live in [`../CLAUDE.md`](../CLAUDE.md). This document explains them; it never
relaxes them.

---

## Layers

```
                          ┌──────────────────────────────────────┐
                          │                ui/                   │
                          │  React + TypeScript (strict)         │
                          │  Redux Toolkit · RTK Query           │
                          │  MapLibre GL · OSM tiles             │
                          │  API types GENERATED from OpenAPI    │
                          └───────────────┬──────────────────────┘
                                          │  REST (commands)
                                          │  WebSocket (live state)
                                          ▼
                          ┌──────────────────────────────────────┐
                          │              server/                 │
                          │  FastAPI. Wires core + the ACTIVE    │
                          │  adapter. Serves the UI over the LAN │
                          │  (tablet is a first-class client).   │
                          │  Publishes state over WebSocket.     │
                          └───────┬──────────────────────┬───────┘
                                  │                      │
                                  ▼                      │
            ┌───────────────────────────────────┐        │
            │               core/               │        │
            │  Sim-agnostic logic:              │        │
            │  geodesy · navdata · scenarios    │        │
            │  weather presets · failure        │        │
            │  catalog · landing analysis       │        │
            │                                   │        │
            │  Depends ONLY on the SimAdapter   │        │
            │  INTERFACE. Never on an adapter.  │        │
            └────────────────┬──────────────────┘        │
                             │                           │
                             ▼                           ▼
            ╔══════════════════════════════════════════════════════╗
            ║        SimAdapter  +  Capabilities  (the contract)   ║
            ╚═══════┬═══════════════════┬══════════════════┬═══════╝
                    │                   │                  │
                    ▼                   ▼                  ▼
        ┌────────────────┐   ┌────────────────┐   ┌────────────────┐
        │ adapters/fake  │   │ adapters/xplane│   │ adapters/msfs  │
        │ In-memory.     │   │ Web API 12.1+  │   │ SimConnect     │
        │ ALL CI tests   │   │ REST + WS      │   │ Windows only   │
        │ run against it.│   │ port 8086      │   │ (Phase 5)      │
        └────────────────┘   └───────┬────────┘   └────────────────┘
                                     │
                                     │ optional, AI traffic only
                                     ▼
                             ┌────────────────┐
                             │    bridge/     │
                             │ XPPython3      │
                             │ plugin, IN-SIM │
                             │ can_spawn_     │
                             │ traffic        │
                             └────────────────┘

     spikes/   Throwaway validation scripts. Not imported by the app. Not tested.
```

---

## The dependency rule

**`core/` depends only on the `SimAdapter` interface. It never imports an adapter, and it never
learns what a simulator is.**

Concretely:

- `core/` must not import `httpx`, `websockets`, `SimConnect`, or anything else that speaks to a
  simulator.
- A dataref name must never appear in `core/`. Dataref strings are adapter vocabulary.
- If `core/` needs a value the interface does not expose, the fix is to **extend the interface**
  (and the contract suite, and every adapter), not to reach past it.

Direction of dependency, in one line:

```
ui  →  server  →  core  →  SimAdapter (interface)  ←  adapters/*
```

Adapters point *at* the contract; nothing points at an adapter except the composition root in
`server/`, which chooses one at start-up.

Why this is worth defending: everything valuable in the product — the geodesy behind a 10 NM
final, the glideslope maths, the failure catalogue, the landing analysis — is simulator-agnostic.
Keeping it that way is what makes Phase 5 (MSFS) a new adapter rather than a rewrite, and what
makes all of it testable without a simulator.

Each feature manager is self-contained: core logic + server endpoints + UI panel. Adding a
manager must not require touching another one.

---

## The `SimAdapter` + `Capabilities` contract

### `SimAdapter`

The single interface between the sim-agnostic half of the application and any simulator. It
covers, at maturity: connection lifecycle, reading live aircraft state, writing position, writing
aircraft state (configuration, radios, autopilot), writing weather, injecting and clearing
failures, spawning traffic, and issuing commands (pushback, cameras, views).

### `Capabilities`

**Capabilities, not failures.** Every adapter declares what it supports —
`can_set_position`, `can_set_weather`, `can_inject_failures`, `can_spawn_traffic`, … — and the
server publishes that declaration to the UI at connect time.

The rule this encodes: **unsupported features are disabled in the UI, never left to throw at
runtime.** An instructor mid-exercise must never discover a limitation by having a control fail.
This matters most for MSFS, whose capability set will be visibly smaller than X-Plane's, and for
`can_spawn_traffic`, which is `False` whenever the optional bridge is absent.

Capability checks live in exactly one place on each side: the adapter declares, the UI gates. No
manager implements its own "is this supported" logic.

### Why `FakeSimAdapter` exists

Two reasons, both load-bearing:

1. **It is the CI reference implementation.** Everything in CI runs against it, so **CI never
   needs a simulator** — no X-Plane on a GitHub runner, ever. Tests are fast, deterministic and
   run on Linux and Windows alike.
2. **It forces the abstraction to be real.** An interface with one implementation is a
   suggestion. A second, in-memory implementation that must satisfy the same contract makes
   simulator-specific assumptions impossible to smuggle into `core/` — they simply fail against
   the Fake. The Fake is the reason the MSFS adapter in Phase 5 is expected to be additive.

The Fake implements the **full** interface in memory: it holds a position, a state, weather, a
failure set and traffic, and it answers reads with what was written.

### The contract suite

`tests/adapters/test_contract.py` is **parametrised over adapters**. It runs against the Fake in
CI and against the real X-Plane adapter under `pytest -m sim`.

**Every new capability added to the interface must extend this suite.** That is the mechanism
that keeps a second adapter honest: an adapter declaring `can_set_weather = True` must pass the
weather contract tests, or it is lying.

Contract changes are also the one thing that is **never parallelised** (`CLAUDE.md`,
parallelisation policy): the interface is shared foundation, changed once, by one agent, before
dependent work branches off it.

---

## Navdata pipeline

Navdata is read from **the user's own simulator install** and **never redistributed**. No
`apt.dat`, `earth_*.dat`, CIFP file or derived database is ever committed. Test fixtures use
hand-written minimal samples or public-domain FAA CIFP extracts only.

```
  X-Plane installation (the user's own)
  ─────────────────────────────────────
   Custom Data/            ──┐  Custom Data/ WINS over
   Resources/default data/ ──┘  Resources/default data/
        │
        ├── cycle_info.txt ─────────────► AIRAC cycle  ──► CACHE KEY
        │                                                 (cycle change ⇒ rebuild)
        ├── earth_fix.dat                  ┐
        ├── earth_nav.dat                  │  parsed once,
        ├── earth_awy.dat                  ├─ indexed into ──►  ┌──────────────┐
        ├── earth_hold.dat / earth_msa.dat │                    │  SQLite      │
        └── Global Scenery/…/apt.dat       ┘                    │  cache       │
                                                                │  (per AIRAC) │
        └── CIFP/<ICAO>.dat ──► parsed LAZILY, one file ───────►│              │
             SID / STAR / APPCH / RWY       per airport,        └──────┬───────┘
             ARINC 424 subset               on first request           │
                                                                       ▼
                                                        ┌──────────────────────────┐
                                                        │  NavdataProvider (core/) │
                                                        │  airports · runways      │
                                                        │  gates/stands · navaids  │
                                                        │  SIDs · STARs · APPCH    │
                                                        │  holdings · constraints  │
                                                        └──────────────────────────┘
```

Design points:

- **Lazy CIFP parsing.** There are thousands of `CIFP/<ICAO>.dat` files. Parsing them all at
  start-up is unacceptable; each is parsed on first request for that airport and then cached.
- **Bulk files are indexed.** `earth_*.dat` and `apt.dat` are large but few, so they are parsed
  once into the SQLite index.
- **The AIRAC cycle from `cycle_info.txt` is the cache invalidation key.** When the user updates
  their navdata, the cycle changes and the cache rebuilds. Nothing else invalidates it.
- **`Custom Data/` takes precedence** over `Resources/default data/` per file — that is where
  third-party navdata subscriptions land.
- **Only fix-carrying legs are positionable.** `IF`, `TF`, `CF`, `DF`, `AF`, `RF` resolve to a
  coordinate. `CA`, `VA`, `FM`, `VM` are trajectory-dependent: shown, never offered.
- **Constraints come from the leg data.** Altitude and speed restrictions for procedure
  placements are read straight out of ARINC 424 — no second source.

The provider lives in `core/`: it reads files from disk, which is not talking to a simulator.

---

## Request and stream paths

Two paths, deliberately different, and the split is not negotiable.

### REST — commands

```
UI ──POST /api/position/final ──► server ──► core (geodesy, navdata)
                                       └──► SimAdapter.set_position()
   ◄── result ────────────────────────────────────────────────────────
```

Every instructor action — place the aircraft, apply weather, inject a failure, run a scenario,
change a control — is a **request/response** over REST. The instructor gets a definite answer:
it applied, or it did not and here is why. Commands are idempotent where the underlying control
is a value, momentary where it is a command.

The UI's API client is **generated from FastAPI's OpenAPI schema**. Hand-writing API types in the
frontend is forbidden.

### WebSocket — live state

```
adapter ──► server state pump ──► WebSocket ──► UI (RTK slices)
  live aircraft state, traffic, connection health, scenario status
```

Everything continuous — position, attitude, speeds, configuration, traffic, connection health —
is **pushed**. The UI never polls. The map, the Aircraft Control panel and the Landing Analysis
recorder all consume the same stream at the rate each needs (display rate for the map and the
panels, 10–20 Hz during an approach for the recorder).

The stream is fan-out: one adapter subscription, many connected clients. A tablet joining an
in-progress session is a normal case, not a special one — the server serves the UI over the LAN
and tablet use is a first-class scenario.

### Where the bridge fits

The optional `bridge/` XPPython3 plugin is reached **through the X-Plane adapter**, never
directly from `core/` or `server/`. Its presence flips `can_spawn_traffic`; its absence disables
traffic features in the UI and changes nothing else. See [`../bridge/README.md`](../bridge/README.md).

---

## Packaging

The shipped artefact is a **single executable built with PyInstaller** that:

1. Starts the local FastAPI server.
2. Serves the pre-built `ui/dist` bundle from inside the executable.
3. Opens the browser at the local URL.

Consequences that shape earlier decisions:

- **Dependencies stay small.** `geographiclib` is chosen over `pyproj` precisely because it is
  pure Python and keeps the bundle small; `pyproj` is only justified if real projections appear.
- The UI is **built ahead of packaging** (`npm run build`) and bundled as static assets. There is
  no Node runtime in the artefact.
- The LAN server is the same server in development and in the packaged app, so the tablet case
  needs no separate mode.
- **Tauri is a later nice-to-have, not architecture.** A desktop shell around the same server
  changes packaging, not layers.

Release automation lives in `.github/workflows/release.yml`, triggered on `v*` tags, producing a
**draft** GitHub Release. The PyInstaller spec is expected to be finalised when Phase 5 packaging
lands.

---

## Known technical risks

These are the same gotchas recorded in [`../CLAUDE.md`](../CLAUDE.md), restated here with their
architectural consequences.

### 1. Repositioning the aircraft externally — the project's key technical risk

X-Plane's real position lives in **`local_x/y/z`** (the OpenGL frame);
**`latitude`/`longitude`/`elevation` are derived**, and the world→local conversion
(`XPLMWorldToLocal`) is a **plugin-only API**. If writing lat/lon over the Web API does not
stick, the fallback is the **legacy UDP `VEHX`/`VEH1` packet**, which positions the aircraft
without a plugin.

**Long teleports trigger a scenery reload — pause around them.**

Architectural consequence: this is validated by a **Phase 0 spike**, and the fallback decision is
made **before Phase 1 starts**. Whichever transport wins is confined to the X-Plane adapter;
`core/` sees only `SimAdapter.set_position()`.

### 2. X-Plane 12 real weather overwrites manual weather

**X-Plane 12's "real weather" mode continuously overwrites manual weather datarefs.** The Weather
Manager must **force manual mode before writing anything**.

Architectural consequence: mode forcing belongs **inside the adapter**, executed once per weather
write, not per setting and not in `core/`. Verifying the mode stuck is part of the weather
contract test.

### 3. Navdata sources and precedence

Read from the user's install, `Custom Data/` wins over `Resources/default data/`:
`CIFP/<ICAO>.dat` (SID/STAR/APPCH/RWY, ARINC 424 subset — **parse lazily, one file per
airport**), `earth_fix/nav/awy/hold/msa.dat`, `Global Scenery/.../apt.dat`. `cycle_info.txt`
gives the AIRAC cycle — **use it as the cache invalidation key**.

Architectural consequence: the `NavdataProvider` owns file discovery, precedence and caching, so
no other component ever touches a `.dat` file. Nothing derived from these files is committed.

### 4. ARINC 424 path terminators

Only legs carrying a resolvable fix — **`IF`, `TF`, `CF`, `DF`, `AF`, `RF`** — are positionable.
Legs like **`CA`/`VA`/`FM`/`VM` are trajectory-dependent — show them, do not offer them as
positions.**

Architectural consequence: positionability is a property computed by the `NavdataProvider` and
carried on the leg model, so the UI never has to know ARINC 424 leg types.

### 5. MSFS will always be a feature subset

**Weather injection is locked down by Asobo, failures via SimConnect are limited, and
study-level aircraft use internal failure systems. L:var access goes through the MobiFlight WASM
module** — an optional add-on, the same pattern as `bridge/`.

Architectural consequence: this is exactly what `Capabilities` is for. The MSFS adapter declares
less, the UI disables more, and no code outside `adapters/msfs/` changes. If supporting MSFS
requires touching `core/`, `server/` or `ui/`, the abstraction was wrong and that is the signal
to fix it.
