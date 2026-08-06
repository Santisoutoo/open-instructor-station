# Feature Specification — Open Instructor Station

> **This document describes the target state at project completion**, not what exists today.
> It is the complete catalogue of the 15 managers the application is meant to provide.
> Nothing here implies an order of work: [`roadmap.md`](roadmap.md) sequences these managers
> into phases and defines the exit criteria for each one.
>
> Priority stars (⭐) rank how central a manager is to the product. Five stars means the
> application is not credible as an instructor station without it.
>
> Binding rules for anything built from this spec live in [`../CLAUDE.md`](../CLAUDE.md).
> In particular: the application is 100% external, `core/` never talks to a simulator, every
> capability is declared by the adapter rather than discovered by failing, and navdata is read
> from the user's own simulator install and never redistributed.

---

## Table of contents

| # | Manager | Priority |
|---|---|---|
| 1 | [Position Manager](#1-position-manager) | ⭐⭐⭐⭐⭐ |
| 2 | [Flight Scenario Generator](#2-flight-scenario-generator) | ⭐⭐⭐⭐⭐ |
| 3 | [Weather Manager](#3-weather-manager) | ⭐⭐⭐⭐⭐ |
| 4 | [Failures Manager](#4-failures-manager) | ⭐⭐⭐⭐⭐ |
| 5 | [Instructor Map](#5-instructor-map) | ⭐⭐⭐⭐⭐ |
| 6 | [Aircraft Control](#6-aircraft-control) | ⭐⭐⭐⭐⭐ |
| 7 | [Flight Plan / Navigation Helper](#7-flight-plan--navigation-helper) | ⭐⭐⭐⭐ |
| 8 | [Pushback Manager](#8-pushback-manager) | — |
| 9 | [Fuel & Payload Manager](#9-fuel--payload-manager) | — |
| 10 | [Camera Manager](#10-camera-manager) | — |
| 11 | [Statistics & Landing Analysis](#11-statistics--landing-analysis) | ⭐⭐⭐⭐⭐ |
| 12 | [Session Recorder](#12-session-recorder) | — |
| 13 | [AI Traffic Manager](#13-ai-traffic-manager) | ⭐⭐⭐⭐⭐ |
| 14 | [Training Profiles](#14-training-profiles) | — |
| 15 | [Instructor Panel](#15-instructor-panel) | — (cross-cutting) |

---

## 1. Position Manager

**Priority: ⭐⭐⭐⭐⭐**

The core of the product. The instructor places the aircraft anywhere, instantly, with a state
that makes sense for that place — no manual re-configuration in the cockpit afterwards.

### Features

**Approach and traffic-pattern placements**

- Final approach at a chosen distance: **20, 15, 10, 8, 5, 3 NM**
- **Short final**
- **Base leg**
- **Downwind**
- **Crosswind**

**Airport placements**

- At any **gate**
- At any **parking stand**

**Free and procedural placements**

- At any **coordinate** (latitude / longitude / altitude)
- Over any **waypoint**
- At a point on a **SID**
- At a point on a **STAR**
- At a point on an **approach**
- In a **holding**

**Automatic setup before moving the aircraft.** Every placement configures a coherent aircraft
state *before* the reposition is written, so the aircraft arrives flyable:

| Group | Values set |
|---|---|
| Flight state | altitude, IAS, vertical speed, heading, pitch, roll |
| Mass | weight, fuel |
| Configuration | flaps, spoilers, landing gear, autobrake |
| Exterior | lights |
| Radios | NAV frequencies, ILS frequency, course (OBS) |

### Implementation notes

The placement pipeline is the same for every placement type; only the source of the anchor
point changes:

1. **Resolve the anchor.** Look up the runway threshold, waypoint, gate/stand or procedure leg
   fix through the `NavdataProvider` (see [architecture.md](architecture.md#navdata-pipeline)).
2. **Compute the target position** from the anchor using distance and bearing — direct and
   inverse geodesic problems solved with `geographiclib` in `core/`. Traffic-pattern legs
   (downwind, base, crosswind) are derived from the runway heading, the pattern side and a
   configurable pattern width.
3. **Compute the altitude.** For finals, follow the published or nominal glideslope
   (e.g. 3° ILS): `altitude = threshold_elevation + distance × tan(glideslope)`. For procedure
   legs, altitude and speed constraints come directly from the ARINC 424 leg data. For pattern
   legs, use the pattern altitude.
4. **Configure the aircraft state.** Build the full state payload (table above) from the
   placement profile: gear and flaps for a short final are not the same as for a 20 NM final.
   Tune NAV/ILS and set the OBS course from the runway's localizer data when there is one.
5. **Write the position.** Pause the simulator, write the state, write the position, unpause.
   Long teleports trigger a scenery reload — pausing around the write avoids the aircraft
   free-falling through unloaded terrain.

Repositioning is behind the `can_set_position` capability. **This is the project's key
technical risk** — see [architecture.md](architecture.md#known-technical-risks) for the
`local_x/y/z` problem and the legacy UDP `VEHX`/`VEH1` fallback.

Geodesy, glideslope maths and pattern geometry are pure `core/` logic and are fully unit
tested against known reference values. Nothing in this pipeline knows what a dataref is.

---

## 2. Flight Scenario Generator

**Priority: ⭐⭐⭐⭐⭐**

One click puts the student in a specific, repeatable training situation.

### Features

Twelve scenarios ship with the product:

| Scenario | Nature |
|---|---|
| Engine failure after V1 | Failure, timed on the take-off roll |
| Wind shear | Weather |
| Low visibility — CAT I / CAT II / CAT III | Weather |
| Crosswind landing | Weather + position |
| Tailwind landing | Weather + position |
| Bird strike | Failure |
| TCAS resolution advisory | Traffic |
| Hydraulic failure | Failure |
| Electrical failure | Failure |
| Go-around | Position + state |
| Unstable approach | Position + state |
| Rejected take-off | Position + state + failure |

Each scenario declares:

- **Initial position** (reusing the Position Manager)
- **Aircraft state** (configuration, speed, altitude, mass)
- **Weather** (a Weather Manager preset or an explicit set of values)
- **Active failures** — immediate or scheduled on a trigger (time, speed, altitude)
- **Traffic**, where applicable

### Implementation notes

**Scenarios are data, never code.** A scenario is a declarative YAML document composed of the
building blocks the other managers already expose. Adding a scenario must never require a code
change — that is the acceptance test for this manager.

The engine in `core/` loads the YAML, validates it against a pydantic model, and executes a
plan: set weather → set aircraft state → position the aircraft → arm scheduled failures →
spawn traffic if the adapter advertises `can_spawn_traffic`.

Scenarios that need a capability the active adapter does not declare are shown as unavailable
with the reason, never offered and then failed at runtime. A TCAS scenario on an adapter
without traffic support is greyed out; a wind shear scenario on MSFS is greyed out because
weather injection is locked down.

Scheduled failures need a trigger evaluator running against the live state stream — a small
`core/` state machine fed by the same telemetry the WebSocket publishes.

---

## 3. Weather Manager

**Priority: ⭐⭐⭐⭐⭐**

### Features

Full manual control of the environment:

- **Wind**: direction, strength, gusts
- **Turbulence**
- **Pressure**
- **Temperature**
- **Humidity**
- **Visibility**
- **Cloud cover** (layers: base, tops, coverage)
- **Precipitation**: rain, snow
- **Ice**

**Presets**: `CAVOK`, `CAT I`, `CAT II`, `CAT III`, `Storm`, `Crosswind`, `Mountain Wave`.

### Implementation notes

**X-Plane 12 "real weather" mode continuously overwrites manual weather datarefs.** The manager
must force the simulator into manual weather mode *before* writing anything, and verify the mode
stuck. This is the single most common cause of "the weather did not apply" reports, and it is
handled once, inside the adapter, not per-setting.

Wind and cloud layers are indexed collections of datarefs (layer 0..2); the adapter exposes them
as a typed list, not as raw indices.

Presets are pure `core/` data: a named mapping to a validated `WeatherState` model. Crosswind
presets are relative — "20 kt from 90° off the runway" — and are resolved against the active
runway at apply time, which is why the preset catalogue lives in `core/` next to the geodesy
rather than in the adapter.

Behind the `can_set_weather` capability. MSFS will declare it `False` or heavily reduced.

---

## 4. Failures Manager

**Priority: ⭐⭐⭐⭐⭐**

### Features

**Engines**

- Fire
- Total failure
- Partial power loss

**Systems**

- Electrical
- Hydraulic
- Pitot
- Radio
- Transponder
- GPS
- Flaps
- Spoilers
- Landing gear
- Brakes
- Fuel leak
- Generator
- Alternator
- Vacuum system
- Pressurisation
- Smoke
- Bird strike
- Lightning strike

### Implementation notes

The **failure catalogue lives in `core/`** as sim-agnostic identifiers with metadata (affected
system, whether it takes an engine index, severity levels, whether it can be armed on a
trigger). The **mapping from catalogue entry to dataref** lives in the X-Plane adapter, and a
different mapping will live in the MSFS adapter.

Failures support three modes: immediate, armed (fires on a condition — time, speed, altitude),
and cleared. "Clear all failures" is a first-class command; an instructor must be able to reset
the aircraft in one action.

The adapter declares `can_inject_failures`, and additionally reports *which* catalogue entries
it can actually produce, because coverage differs per simulator and per aircraft. Study-level
aircraft implement their own internal failure systems and may ignore the simulator's — the UI
surfaces failures the adapter cannot guarantee as "best effort".

---

## 5. Instructor Map

**Priority: ⭐⭐⭐⭐⭐**

The instructor's situational display: the whole exercise at a glance, on a second screen or a
tablet.

### Features

**Real-time display**

- Aircraft position and track
- AI traffic
- TCAS picture
- Waypoints
- Taxiways
- Runways
- ILS (localizer and glideslope geometry)
- STARs
- SIDs
- METAR

**Interaction**

- **Drag the aircraft** to a new position
- **Click to position** the aircraft
- Zoom and pan
- **Distance measurement** tool

### Implementation notes

MapLibre GL with **OpenStreetMap / open-source tiles only** — no proprietary basemaps, no
API-key providers.

Aircraft and traffic positions arrive over the **WebSocket** state stream at a rate suited to
smooth display; everything else (runways, navaids, procedures) is served on demand from the
`NavdataProvider` and cached client-side. The map never queries the simulator directly.

Drag-to-reposition and click-to-place are the Position Manager's "any coordinate" placement with
a map-derived anchor: the same `core/` pipeline, the same automatic setup, so a dragged aircraft
arrives configured rather than dropped.

Distance measurement uses the same geodesic solver as the placements, so the number the
instructor reads on the map is the number the placement uses.

---

## 6. Aircraft Control

**Priority: ⭐⭐⭐⭐⭐**

Live control of the aircraft from the instructor station while the student flies.

### Features

Real-time read and write of:

- Flaps
- Landing gear
- Trim
- Autopilot master
- Speed, heading, altitude, vertical speed selectors
- NAV mode, APP mode, HDG mode
- Flight director
- Lights

### Implementation notes

Two paths, deliberately separated:

- **Reads** come from the WebSocket state stream — the panel reflects the aircraft continuously,
  including changes the student makes in the cockpit.
- **Writes** are REST commands. They are idempotent where the underlying control is a value
  (set flap handle to 2) and momentary where it is a command (toggle a light).

Autopilot mode engagement is the most aircraft-dependent area of the whole product: default
aircraft use standard datarefs, study-level aircraft expose custom ones. The adapter provides a
default mapping and an aircraft-specific override layer keyed on the loaded aircraft ICAO/path.

The panel is the first place where write latency is visible to the instructor, so commands are
optimistically applied in the UI and reconciled against the next state frame — Redux Toolkit
handles this with a pending/confirmed flag per control.

---

## 7. Flight Plan / Navigation Helper

**Priority: ⭐⭐⭐⭐**

### Features

- **Import and export** flight plans
- **Sync** with compatible flight planning apps
- **Auto-tune** NAV radios
- Auto-tune **ILS frequencies**
- Set the **approach course**
- Read `.fms` (X-Plane) and `.pln` (MSFS / FSX) files
- **Interact with the FMC** on capable aircraft through their own APIs or custom datarefs

### Implementation notes

Parsing `.fms` and `.pln` is pure `core/` work — both are simple text/XML formats — and produces
the same internal `FlightPlan` model regardless of source. Export writes both formats back.

The radio auto-tune half of this manager is needed much earlier than the rest: placing the
aircraft on an ILS final is worthless if the radios are not tuned. That slice therefore ships
with the Position Manager and reuses the same localizer lookup.

FMC interaction is explicitly **best-effort and per-aircraft**. There is no general FMC API;
each study-level aircraft exposes its own. This is modelled as an optional plugin-style mapping
and never blocks anything else.

---

## 8. Pushback Manager

**Priority: —**

### Features

- Push **left**, **right** or **straight**
- Configurable **distance**
- Configurable **angle**

### Implementation notes

Cheap to build, high perceived value. Two possible implementations:

1. **Command-based** — drive the simulator's own pushback tug through commands where one exists.
2. **Geodesy-based** — compute the resulting position and reuse the Position Manager, which
   works everywhere but skips the animation.

Start with the command path where available and fall back to the computed path, gated by a
capability. Either way the geometry (a straight segment or an arc of a given angle and radius
from the current heading) is `core/` maths.

---

## 9. Fuel & Payload Manager

**Priority: —**

### Features

- Fuel quantity (per tank where the aircraft exposes tanks)
- Passengers
- Cargo
- Total weight
- **Centre of gravity**

**Presets**: `Ferry`, `Training`, `Full`, `Empty`.

### Implementation notes

Mass and balance is `core/` arithmetic over an aircraft's declared limits (max fuel, max zero
fuel weight, MTOW, CG envelope). The manager validates before writing: refusing an out-of-
envelope loadout with a clear reason is more useful to an instructor than silently accepting it.

This manager is a prerequisite for the Scenario Generator, because several scenarios (rejected
take-off, engine failure after V1) are only meaningful at a defined weight. It also feeds the
Position Manager's automatic setup, which sets weight and fuel as part of every placement.

---

## 10. Camera Manager

**Priority: —**

### Features

Switch the simulator view to:

- Cockpit
- Drone / free camera
- Tower
- Wing view
- Chase view
- Custom saved positions

### Implementation notes

Almost entirely command-based — a thin adapter surface mapping named views to simulator view
commands, plus a small amount of state for custom saved camera positions (stored as offsets
relative to the aircraft, persisted with training profiles).

Grouped with Pushback in the roadmap because both are small, command-shaped and independent of
everything else.

---

## 11. Statistics & Landing Analysis

**Priority: ⭐⭐⭐⭐⭐**

The debrief. What turns a session from "that felt rough" into a number the student can work on.

### Features

Recorded and computed per landing:

- **Localizer deviation**
- **Glideslope deviation**
- **Touchdown rate** (fpm)
- **G-force** at touchdown
- **Pitch** at touchdown
- **Roll** at touchdown
- **Centreline deviation**
- **Flare** (height and duration)
- **Floating** (distance/time in the flare)
- **Landing distance**

**Export**: CSV, PDF, JSON.

### Implementation notes

Recording runs at **10–20 Hz during the approach** — a higher rate than the display stream,
because touchdown rate and G-force are the derivative-sensitive numbers and a 1 Hz sample makes
them meaningless. The recorder arms itself on approach detection (gear down, below a height AGL,
inside the localizer capture region) and disarms after rollout.

Analysis is pure `core/`: a buffer of timestamped state frames in, a `LandingReport` out. That
means it is fully testable from recorded fixtures, with no simulator involved — the reference
approach in the test suite is a hand-built frame sequence with known answers.

Localizer and glideslope deviation are computed geometrically from the runway data rather than
read from the aircraft's receiver, so the analysis works on runways without an ILS and does not
depend on the student having tuned anything.

Export formats are generated in `core/` too; PDF is the only one that pulls a dependency, and it
must stay small enough not to bloat the PyInstaller bundle.

---

## 12. Session Recorder

**Priority: —**

### Features

- **Save scenarios** as executed
- **Repeat an exercise** identically
- **Replay** a recorded session
- **Restore previous states** (snapshot / rewind)

### Implementation notes

Two distinct things share this manager:

- **Snapshots** — a complete capture of position + aircraft state + weather + failures at an
  instant. Cheap, and immediately useful: "put us back where we were 30 seconds ago" is the most
  requested instructor action. A snapshot restores through exactly the same path a scenario
  applies through.
- **Recordings** — a continuous stream of state frames, stored for replay and for feeding the
  Landing Analysis after the fact.

Snapshots are a superset of what the Scenario Generator writes, which is why the two share a
model: saving a snapshot as a scenario file is the natural way to author new content, and
saving one as a Training Profile is manager 14.

---

## 13. AI Traffic Manager

**Priority: ⭐⭐⭐⭐⭐**

### Features

Spawn and control:

- **Aircraft**
- **Ground vehicles**
- **Birds**

Scenario shapes:

- **TCAS conflict** (leading to a resolution advisory)
- **Runway incursion**
- **Taxi traffic**
- **Approach traffic** (sequencing, spacing)

### Implementation notes

**This is the one thing the X-Plane Web API cannot do.** Spawning and driving AI aircraft
requires code running inside the simulator, which is what the optional **`bridge/`** XPPython3
plugin is for (see [`../bridge/README.md`](../bridge/README.md)).

Consequences, all of them binding:

- The whole manager sits behind the **`can_spawn_traffic`** capability.
- **Everything else in the application must work with the bridge absent.** The plugin is an
  add-on, never a dependency.
- With the bridge absent the traffic panel and the traffic-dependent scenarios (TCAS RA, runway
  incursion) are disabled in the UI with an explanation, never offered and then failed.

Traffic *paths* — the geometry of a converging TCAS conflict, an incursion timed to the
student's rollout, an approach sequence — are computed in `core/` and sent to the bridge as
plain waypoint tracks. The bridge stays as thin as possible: it spawns, it moves, it despawns.

---

## 14. Training Profiles

**Priority: —**

### Features

Save and reload a complete training setup:

- Airport
- Runway
- Distance
- Altitude
- Speed
- Aircraft configuration
- Weather
- Failures

Stored as **JSON / XML**, shareable between instructors.

### Implementation notes

A training profile is a saved scenario with a name and metadata — same model, same validation,
same execution path. Building it as a separate mechanism would be duplicated work.

Profiles are user data, stored outside the repository in the user's application data directory.
Import/export moves single files so an instructor can hand a colleague an exercise.

Because profiles reference airports and procedures by identifier, and navdata comes from the
user's own install, a profile authored on one AIRAC cycle must degrade gracefully when a
procedure has since been withdrawn: report what could not be resolved, apply the rest.

---

## 15. Instructor Panel

**Priority: — (cross-cutting)**

The centralised interface from which the instructor drives everything: position, weather,
failures, traffic, weight, fuel, cameras, radios, scenarios and aircraft state.

### Features

- One screen (or a tablet) that reaches every manager
- Live status of the connection, the simulator, the aircraft and the active scenario
- Capability-aware: controls the active adapter cannot support are visibly disabled with the
  reason, never silently missing and never left to fail

### Implementation notes

> **This manager is cross-cutting and is not built in a single step.** It *is* the UI. It comes
> into existence as the Phase 0 shell and then **grows one tab per phase**, alongside the
> manager that tab drives. There is no point in the roadmap where "build the Instructor Panel"
> is a task of its own, and there must never be a panel tab for a manager whose backend does not
> exist yet.

Structural rules that make that growth safe:

- Each manager owns **one RTK slice and one panel component**; adding a manager adds files
  rather than editing shared ones.
- All API types are **generated from FastAPI's OpenAPI schema**. Hand-written API types in the
  frontend are forbidden — see [`../CLAUDE.md`](../CLAUDE.md).
- The capability set fetched at connect time drives which tabs and controls are enabled, in one
  place, so no panel implements its own "is this supported" logic.
- The layout targets a **tablet over the LAN** as a first-class case, not a scaled-down desktop
  view: touch targets, one-handed reach, and the most-used action (place the aircraft on a
  final) never more than two taps away.
