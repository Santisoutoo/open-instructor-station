# Statistics & Landing Analysis — design

**Status:** designed, not yet implemented.
**GitHub issue:** [#23](https://github.com/Santisoutoo/open-instructor-station/issues/23).
**Phase:** 4 — Analysis and sessions ([`../roadmap.md`](../roadmap.md#phase-4--analysis-and-sessions)).
**Feature spec:** manager 11 ([`../feature-spec.md`](../feature-spec.md#11-statistics--landing-analysis)), ⭐⭐⭐⭐⭐.
**Depends on:** the Phase 0/1 contract (`core/sim_adapter.py`, `FakeSimAdapter`, the contract suite), `core/geodesy.py` (the runway frame, `glideslope_altitude_ft`, the approach-category tables), `core/models.py`'s `Runway`/`Ils`, and the `NavdataProvider`'s `get_runway()`.
**Blocks:** the **Session Recorder** (manager 12) and, in a weaker sense, the **Flight Plan helper** (manager 7). Both consume recorded state frames; §2 of this document defines that frame, and the roadmap's Phase 4 table — *"They share the state-frame model — fix it first"* — makes that definition this manager's first and non-parallelisable deliverable.

The debrief. The instructor flies a student down an approach and, thirty seconds after the
rollout, has the numbers: how fast the aeroplane hit the ground, how hard, how straight, how far
down the runway, and how well the localizer and glidepath were flown on the way in. Ten to
sixteen numbers and two charts turn *"that felt rough"* into something to work on.

Binding rules live in [`../../CLAUDE.md`](../../CLAUDE.md); layers in
[`../architecture.md`](../architecture.md). This document never relaxes them. Three things make
it harder than a numbers-in-numbers-out manager, and each gets an explicit section rather than a
passing mention:

1. **The UI already exists and has fixed a de-facto contract.** `ui/src/features/landing/` is a
   complete panel on `dev` — charts, grading, CSV/JSON export — driven by
   `ui/src/features/landing/types.mock.ts`. §5.1 adopts that shape, says what it adds to it, and
   §10.2 prices the re-typing.
2. **Phase 4's three managers share a state frame.** §2 defines it, says where it lives, and says
   what managers 12 and 7 get from it.
3. **The recording rate is the real architectural question.** Feature spec §11 requires 10–20 Hz;
   `WS /ws/state` runs at 4 Hz; hard rule 2 forbids solving it in `core/` and hard rule 1 forbids
   solving it with an in-sim component. §3 answers it, with the trade-offs and the one thing that
   must be measured before the answer can be trusted.

The Weather, Failures and Pushback designs are this project's house style; their staging,
manifest and gating conventions are reused here, not reinvented.

---

## 0. Decisions at a glance

| # | Decision | Where |
|---|---|---|
| D1 | **The Phase 4 state frame is `core.frames.StateFrame` — a monotonic timestamp plus an `AircraftState`, and nothing else.** No parallel "recorded state" model, no per-manager frame. `AircraftState` is already the one thing every adapter must produce; wrapping it in a timestamp is the whole of the recording abstraction, and the timestamp belongs to the *recorder*, not to the simulator's snapshot of itself. | §2 |
| D2 | **`AircraftState` gains exactly four required fields — `altitude_agl_ft`, `groundspeed_kt`, `normal_g`, `gear_ratio`.** Each is demanded by a named feature-spec §11 bullet and none is derivable from what is already there: G-force is an accelerometer reading, AGL is terrain the app does not model, groundspeed differs from IAS by the wind, and the arming criterion is literally *"gear down"*. Ten `AircraftState(...)` call sites in the whole repo; mypy finds all of them. This is the contract change, and it is the only one. | §6 |
| D3 | **No new `SimAdapter` method and no new `Capabilities` flag.** Every existing flag gates a *write*; this manager writes nothing. It reads `get_aircraft_state()` / `stream_state()`, both ungated on the protocol, and analyses the result in `core/`. A `can_record_landings` flag would be `True` on every adapter that exists or is planned — a flag that never gates anything is decoration, not a capability. What genuinely varies between adapters is the achievable *rate*, and that is a measured number, not a boolean (D6). | §6, §6.3 |
| D4 | **The high-rate buffer lives in `server/`, in a single fan-out `StatePump`.** `core/` gets a finished list of frames and no clock; the adapter gets one subscriber instead of today's N. The pump samples at the highest rate any subscriber currently asks for — 4 Hz idle, `RECORDER_SAMPLE_HZ` while the recorder is armed — and decimates for the slower ones. | §3 |
| D5 | **The high rate never crosses the network.** The UI is not a recorder: it gets the finished report and a *decimated* trace over REST, plus a 2 Hz recorder-status push on `WS /ws/landing`. Twenty samples a second are needed to differentiate a touchdown, not to draw one — a 660 px chart cannot resolve them. | §3.4, §4 |
| D6 | **The sample rate is measured, never declared.** The recorder timestamps every frame it accepts, so the achieved rate falls out of the data. `LandingReport.sample_rate_hz` carries it and the panel shows a plain-language warning below `MIN_TRUSTWORTHY_SAMPLE_HZ`. Nothing throws, nothing is hidden, and no adapter has to promise a rate it cannot keep. | §3.3, §5.3 |
| D7 | **Adopt the UI's `TraceSample` and `LandingReport` field shapes as the server contract**, with six named additions, and reclassify `TraceSample`: it is a *derived, runway-relative view*, not a recorded frame. That reclassification is what reconciles decision 1 with decision 2 — the panel was right about what it wants to draw and wrong only about where it comes from. | §5.1, §5.2 |
| D8 | **Localizer and glideslope deviation are computed geometrically from `Runway`/`Ils`, passed in as value objects.** `core/` never sees the `NavdataProvider` and never reads a receiver dataref. The angular references are the published antennas when navdata has them and documented geometric substitutes when it does not. | §8.2 |
| D9 | **Two-dot full-scale convention: `LOC_DEG_PER_DOT = 1.25`, `GS_DEG_PER_DOT = 0.35`** (so two dots = 2.5° localizer, 0.7° glideslope). Stated because the alternative five-dot HSI convention is equally defensible and a silent disagreement makes every deviation chart in the project wrong by a factor of 2.5. `Ils.localizer_width_deg` overrides it when published — it never is, from the X-Plane provider. `cross_track_m` is carried alongside the dots so the physical truth survives the convention. | §8.2 |
| D10 | **The world → runway-frame projection is promoted out of `server/position_routes.py` into `core/landing/geometry.py` and reused, not re-derived.** `_runway_schematic()` already does exactly this arithmetic (`distance_and_bearing` then trig on the bearing difference); this manager needs it too, so it moves to `core/` and the schematic calls it. One projection in the repo, not two. | §8.2 |
| D11 | **Arming is state-only; the runway is resolved at analysis time.** Gear down + below `ARM_MAX_AGL_FT` + descending is enough to start a cheap buffer, and it works with no navdata at all. When navdata *is* available the alignment test tightens it (feature spec's "inside the localizer capture region"), but it is never a precondition. | §8.3 |
| D12 | **Missing navdata degrades the report; it never fails it.** No runway found → the recording is kept, `runway` is `null`, the six runway-dependent numbers are `null` with a stated reason, and the ten that are pure aircraft physics are computed as normal. The panel shows the reason. This is hard rule 3's posture applied to data rather than to a capability. | §5.3, §12.2 |
| D13 | **A go-around is a first-class outcome, not a discarded recording.** `outcome="go_around"`, the trace is kept, `report` is `null`. Almost every number in the report is measured at or after a touchdown that never happened — but the deviation trace of a missed approach is a real debrief item, and throwing it away would be the expensive choice. | §8.3 |
| D14 | **The touchdown instant is interpolated, not snapped to a sample**, and a bounce does not disarm the recorder. At 20 Hz the aircraft travels ~3 m between samples; taking the first on-ground frame biases every touchdown number. The report describes the **first** touchdown and carries `bounce_count`, which the detection has to compute anyway to know when the rollout really started. | §8.4 |
| D15 | **Landings live in memory for the session, capped at `MAX_RETAINED_LANDINGS`.** Durability is the export endpoint; persistence across restarts is manager 12's store, whose model is `StateFrame` (D1). Inventing a second on-disk store beside `core/profiles/store.py` for data that manager 12 is about to own properly would be work done twice. | §5.4 |
| D16 | **PDF is deferred and replaced by print-to-PDF from the panel.** The charts already exist as SVG in the browser; a print stylesheet plus `window.print()` yields a PDF *containing them* at zero dependency cost, whereas a `core/`-side PDF would have to re-draw them in Python. `reportlab` is named as the fallback if a headless PDF is ever required, gated on a measured PyInstaller bundle delta. This is a deviation from feature spec §11 and is flagged as one. | §9.3 |
| D17 | **CSV and JSON export are generated in `core/`, and the UI's client-side builders are deleted.** `ui/src/features/landing/export.ts` currently formats CSV in TypeScript; the spec puts export in `core/`, and two implementations of one format drift. The buttons become links to the export endpoint. | §9, §10.2 |
| D18 | **Grading thresholds stay in the UI; only `vref_kt` comes from the server.** Grading is a teaching opinion, not a measurement, and it should be tunable without a backend release. The one thing the UI genuinely cannot know is the airframe's reference speed — `MOCK_VREF_KT = 92` is hardcoded today — so the manifest serves it from `AirframeInfo.vso_kias × VAT_FROM_VSO`, falling back to the approach-category table. | §5.5, §10.2 |
| D19 | **Request and response models live in `core/landing/models.py`, not in the router** — the Position Manager's recorded regret, kept out of this manager the way Weather (D6), Failures (D9) and Pushback (D9) kept it out of theirs. Manager 12 must be able to hand a stored recording to `core.landing.analyse_landing()` without importing anything from `server/`. | §5 |
| D20 | **The UI adds its endpoints with `injectEndpoints` from `landingApi.ts`** — which it already does. Adding this manager adds files; `instructorApi.ts` is not edited. | §10 |

---

## 1. Scope

### 1.1 What this manager does

1. **Record the approach at 10–20 Hz** — arming on approach detection, disarming after rollout,
   with the sampling and buffering entirely inside `server/` and the decisions inside `core/`.
2. **Analyse a buffer of frames into a report** — a pure `core/` function, no adapter, no clock,
   no provider, validated against hand-built fixture frames with known answers. This is roadmap
   Phase 4 exit criterion 1 verbatim.
3. **Compute localizer, glideslope and centreline deviation geometrically** from the runway's own
   data, so the analysis works on a grass strip and does not care what the student tuned.
4. **Serve the debrief** — the record (report + trace + runway context) over REST, the recorder's
   live status over a 2 Hz WebSocket.
5. **Export** — CSV and JSON generated in `core/`; PDF via the panel's print path (D16).
6. **Define the Phase 4 state frame** (§2) so managers 12 and 7 can branch off it.

Feature-spec coverage (manager 11), item by item: localizer deviation (trace + summary),
glideslope deviation (trace + summary), touchdown rate, G-force, pitch, roll, centreline
deviation, flare height *and* duration, floating distance *and* time, landing distance. Export
CSV, PDF (D16), JSON.

### 1.2 What is explicitly out of scope

| Out of scope | Why / owner |
|---|---|
| Persisting recordings across a server restart | **Session Recorder** (manager 12). D15. Its recordings are sequences of this manager's `StateFrame`; a second store here would be thrown away when it lands. |
| Replay / scrubbing a recording | Manager 12, rendered on the Instructor Map (its issue says so). This manager's trace is a chart, not a timeline you can fly. |
| Snapshots (position + state + weather + failures) | Manager 12. A snapshot is a **superset** of a `StateFrame` and deliberately not modelled here — stated so manager 12 does not try to force one into this model. |
| General "flight statistics" — live IAS/altitude/VS/attitude graphs outside an approach | The Aircraft Control and Telemetry panels already show live values; a continuous general-purpose recorder is manager 12's. This manager records approaches. |
| Grading policy, pass/fail thresholds, scoring | D18. The UI owns it. |
| Google Earth / KML export | Not in feature spec §11. Noted in the competitive inventory as a gap; not invented here. |
| Reading the aircraft's own LOC/GS receiver | Feature spec forbids it explicitly, and it would break every runway without an ILS. D8. |
| Take-off analysis, rejected take-off, climb performance | Not in §11. The frame model (§2) supports it later at no cost. |
| MSFS | Phase 5. Every field D2 adds has a SimConnect equivalent (`PLANE ALT ABOVE GROUND`, `GROUND VELOCITY`, `G FORCE`, `GEAR POSITION`) — *believed available, verify in the Phase 5 spike*. Nothing here assumes it. |

---

## 2. The Phase 4 state frame — the shared foundation

The roadmap's Phase 4 parallelisation row reads: *"Landing Analysis ∥ Session Recorder ∥ Flight
Plan — They share the state-frame model — fix it first."* This section is that fix. It is
delivered by Track 0 (§12.1), alone, before any of the three managers branches.

### 2.1 What the frame is

```python
# core/frames.py

class StateFrame(BaseModel):
    """One sample of the simulator's state, timestamped by whatever recorded it.

    The timestamp belongs to the RECORDER, not to the simulator: AircraftState
    is a snapshot of an aeroplane and carries no time of its own, and the
    interval between two frames is a property of the sampling loop that
    produced them. t_s is therefore seconds since that recording's own t0,
    taken from a MONOTONIC clock — never a wall clock, which can step
    backwards mid-approach and turn a sink rate into a climb.
    """

    model_config = ConfigDict(frozen=True)

    t_s: float = Field(ge=0.0, description="Seconds since the recording's first frame.")
    state: AircraftState
```

and one container:

```python
class FrameBuffer:
    """A bounded, append-only sequence of StateFrames, oldest dropped when full.

    Not a pydantic model: it is a deque with a cap and a t0, and it never
    reads a clock — the caller supplies t_s, which is what keeps core/
    testable without freezing time. `truncated` records whether anything was
    ever dropped, so a report built from it can say so.
    """
```

That is the whole of it. There is deliberately no `sim_time`, no sequence number, no source tag,
no wall clock per frame: a recording carries **one** `started_at: datetime` at its head (for
display and for filenames) and relative monotonic offsets thereafter.

### 2.2 Why it is `AircraftState` and not a new model

`AircraftState` is already the single thing every adapter must be able to produce, the thing
`stream_state()` yields, and the thing the UI already validates on arrival. A parallel
"recorded state" model would mean two shapes for one concept, a conversion between them at every
boundary, and a second thing for the MSFS adapter to satisfy in Phase 5. The cost of reusing it is
that it must grow four fields (§6.1) — a one-off, mechanical change to eleven construction sites
— and the benefit is that the fields grow for *every* consumer at once: the map gets AGL, the
Aircraft Control panel gets groundspeed, the failure scheduler could gain an `on_ground` trigger
it does not have today.

### 2.3 What the other two managers get from it

| Manager | Needs | Provided by |
|---|---|---|
| **12 — Session Recorder**, *recordings* | "A continuous stream of state frames, stored for replay and for feeding the Landing Analysis after the fact" (feature spec §12) | `StateFrame` + `FrameBuffer` verbatim. Its persisted recording is `{started_at, frames: list[StateFrame]}`; its replay iterates them; feeding the analysis is a direct in-process call to `core.landing.analyse_landing(frames, runway)` — **no endpoint, no HTTP, no import from `server/`** (D19). |
| **12 — Session Recorder**, *snapshots* | Position + aircraft state + weather + failures at an instant | **Not** a `StateFrame`. A snapshot is a superset with three more subsystems in it, and forcing it into this model would put a `WeatherState` on every one of 6 000 approach frames. Manager 12 defines `Snapshot` itself; it may *contain* a `StateFrame`. Stated here so the question is closed before that design starts. |
| **7 — Flight Plan helper** | Position and groundspeed over time, for progress along the plan and for ETE/ETA | `StateFrame.state.latitude/longitude/altitude_ft` and the `groundspeed_kt` D2 adds. **It needs no extension of its own** — worth saying plainly, because "all three share the frame" reads as though all three drove its shape, and manager 7 only consumes it. |

All three subscribe to the same `StatePump` (§3.2) rather than opening their own poll loop against
the adapter. That is the second half of the shared foundation and the reason it is Track 0's job
rather than three separate re-inventions.

---

## 3. The recording rate — where the buffer lives

### 3.1 The problem, stated with the real numbers

- Feature spec §11 and roadmap Phase 4 both require **10–20 Hz during the approach**, because
  touchdown rate and G-force are derivative-sensitive.
- `server/app.py:74` — `STATE_STREAM_INTERVAL_S = 0.25`, i.e. **4 Hz**, and the comment says why:
  *"smooth on a map without flooding a tablet."* That reasoning is correct and this design does not
  touch it.
- `WS /ws/state` (`server/app.py:374`) gives **every connected client its own**
  `adapter.stream_state(...)` generator. There is no fan-out hub, although
  `docs/architecture.md:241` states one as the intent.
- `server/failure_routes.py` runs a **second, independent** poll loop at 4 Hz whenever a failure is
  armed.
- `XPlaneSimAdapter.get_aircraft_state()` (`adapters/xplane/xplane_adapter.py:912`) issues **nine
  concurrent single-dataref HTTP GETs**, and `stream_state` (line 2551) is read-*then*-sleep, so
  the nominal interval is a floor, not a period.

Multiply those together: a naive recorder that simply opens a fourth loop at 20 Hz asks X-Plane's
Web API for **180 GETs per second from that loop alone**, on top of one 4 Hz loop per tablet and
one for the failure watcher. Issue #57 already records that these requests take ~4.1 s each without
Docker Desktop. The rate question is therefore not "where do we put a `deque`" but "how many times
per second is the simulator asked anything, and by whom".

### 3.2 The answer: one pump in `server/`, demand-driven

```
adapter.stream_state(pump_interval)  ──►  server/state_pump.py : StatePump
                                              │
                       ┌──────────────────────┼─────────────────────────┐
                       ▼                      ▼                         ▼
              WS /ws/state clients     failures watcher          LandingRecorder
              (decimated to 4 Hz)      (decimated to 4 Hz)    (every frame, buffered)
```

`StatePump` is a `server/` module-global — the exact shape `server/failure_routes.py`'s watcher and
`server/scenario_engine.py`'s run task already use, including a `reset_state_pump()` for tests. It
owns the **only** consumption of `adapter.stream_state()` in the process. Subscribers register with
the rate they want; the pump runs at the maximum of those rates and hands each subscriber every
Nth frame.

- Idle: the only subscribers are WS clients and possibly the failure watcher → the pump runs at
  4 Hz and **nothing changes from today's behaviour**.
- The recorder arms → it subscribes at `RECORDER_SAMPLE_HZ` → the pump escalates; `/ws/state`
  clients keep receiving 4 Hz because the pump decimates for them.
- The recorder disarms → the pump drops back to 4 Hz.

Escalation costs nothing when nobody is landing, which is most of a session.

Two properties the loop must have, both easy to get wrong:

- **Tick-skipping, never queueing.** If a sample is still outstanding when the next tick is due,
  the tick is skipped. A queue would turn a slow simulator into unbounded lag and a memory leak,
  and it would make the recorded timestamps a fiction.
- **The pump timestamps on arrival**, with `time.monotonic()`. That is honest — it is the time the
  server learned the value, not the time the simulator computed it — and it means `t_s` deltas are
  irregular. Every derivative in `core/` therefore divides by the *actual* `Δt` between the two
  frames it used, never by a nominal `1 / rate`. §8.4 pins this and §11.4 tests it with a
  deliberately jittered fixture.

### 3.3 Delivering the rate is an adapter-internal problem

Whether `XPlaneSimAdapter` can answer 20 times a second is **not visible at the interface**, and
that is the point — the same argument the Pushback design's D1 makes about the tug. `stream_state`
is already on the protocol. Three adapter-internal routes exist, in increasing order of effort:

1. **Batch the per-frame reads into one request.** The Web API supports filtered dataref queries;
   nine round-trips per frame — thirteen once §6.1's fields land — become one. *Verify in spike.*
2. **Replace polling with the Web API's WebSocket subscription.** `spikes/README.md:43` records an
   earlier spike observing that *"the WebSocket at `/api/v2` accepts a `dataref_subscribe_values`
   subscription and pushes ~10 live updates"*, and `adapters/xplane/xplane_adapter.py:2551`'s own
   docstring already names this as the intended replacement for polling. That would make the rate a
   function of the simulator's frame rate rather than of HTTP. **Observed once in a spike; the
   sustained rate is not measured. Verify in spike** (§13.1).
3. **Do neither**, and accept whatever rate comes out. The recorder still produces a report; D6
   makes the shortfall visible instead of silent.

None of the three changes `core/`, `server/`, the protocol or the UI. That is the test of whether
the layering is right, and it passes.

### 3.4 What was rejected, and why

| Alternative | Why not |
|---|---|
| **The buffer in the adapter** | The arming rules, the ring buffer and the disarm logic are sim-agnostic policy. Putting them in `adapters/xplane/` means writing them again for MSFS and testing them against neither the Fake nor `core/`. The adapter's job stops at "produce frames as fast as you can". |
| **The buffer in `core/`** | Forbidden by hard rule 2, and rightly: a buffer needs a clock and a subscription, both of which are I/O. `core/` gets the finished list. Note the deliberate split — the *decisions* (arm? disarm? touched down?) are pure functions in `core/landing/detect.py`; only the loop that calls them lives in `server/`. |
| **A second high-rate WebSocket to the browser, recording in Redux** | The UI would have to hold 6 000 frames, the analysis would move to TypeScript, and Phase 4 exit criterion 1 ("computed entirely in `core/`") would be unsatisfiable. It also puts 20 Hz on a LAN link to a tablet for data the tablet cannot draw. |
| **Raising `STATE_STREAM_INTERVAL_S` to 20 Hz for everyone** | Five times the tablet traffic and five times the sim load, permanently, so that a two-minute window per flight is well sampled. D4's escalation gets the same result for the cost of the window. |
| **An in-sim `bridge/` recorder** | Hard rule 1: everything outside AI traffic works without the bridge. Not negotiable, and not needed. |

---

## 4. REST endpoints and the live stream

All under `/api/landing/*`, in a new `server/landing_routes.py`, registered from `server/app.py`
with one `include_router` line — the only shared-file backend edit outside Track 0, matching every
manager since Weather.

```
GET    /api/landing/manifest                     -> LandingManifest
GET    /api/landing/recorder                     -> RecorderStatus
POST   /api/landing/recorder/arm                 -> RecorderStatus
POST   /api/landing/recorder/disarm              -> RecorderStatus
GET    /api/landing/records                      -> list[LandingSummary]
GET    /api/landing/records/{landing_id}         -> LandingRecord
DELETE /api/landing/records/{landing_id}         -> 204
GET    /api/landing/records/{landing_id}/export  -> text/csv | application/json
WS     /ws/landing                               -> RecorderStatus + landing-complete events
```

| Method | Path | Purpose | Safe? | Capability | Declared |
|---|---|---|---|---|---|
| `GET` | `/manifest` | Recorder configuration the UI must not hardcode: target rate, arming thresholds, `vref_kt`, the glide path used when a runway has no ILS. Always 200. | yes | none (D3) | `async def` — one `get_airframe()` read for `vref_kt` |
| `GET` | `/recorder` | Current `RecorderStatus`, for a client that missed the WS frames | yes | none | `def` |
| `POST` | `/recorder/arm` | Force the recorder armed, optionally against a stated `airport_icao`/`runway_ident`. For the cases auto-detection cannot see: a gear-up landing, a glider, a grass strip approached below the arm height. | no | none | `def` |
| `POST` | `/recorder/disarm` | Force it back to idle, discarding the in-progress buffer | no | none | `def` |
| `GET` | `/records` | The session's landings, newest first — summaries only, no trace | yes | none | `def` |
| `GET` | `/records/{id}` | One `LandingRecord`: report, runway context and a trace **decimated to `rate_hz`** (query param, default `TRACE_DISPLAY_HZ`) | yes | none | `def` |
| `DELETE` | `/records/{id}` | Drop one landing from the session | no | none | `def` |
| `GET` | `/records/{id}/export` | `format=csv\|json`, full-rate trace, `Content-Disposition: attachment` | yes | none | `def` — follows `server/profile_routes.py:399`'s export precedent exactly |
| `WS` | `/ws/landing` | Pushes `RecorderStatus` at `LANDING_STATUS_INTERVAL_S` (2 Hz) and one `landing_complete` event carrying the new `LandingSummary` | — | none | — |

### 4.1 Why a separate WebSocket, and why it is slow

The panel needs to know two things live: *"is the recorder armed right now"* (so the instructor
can see it caught the approach) and *"a landing just finished"* (so the list updates without a
refresh). Neither belongs on `/ws/state`: folding a recorder status into `AircraftState` would
change the frame shape for every consumer that has no landing dependency — the exact reasoning
`docs/designs/ai-traffic.md` D10 gives for `/ws/traffic`, applied to a different payload.

2 Hz, not 20. The status is a badge, not a control loop, and **the recording rate never leaves the
server** (D5).

### 4.2 Error conventions

FastAPI's `{"detail": "<one sentence>"}`, as everywhere else.

- Unknown `landing_id` → **404**, *"No recorded landing with that id — it may have been dropped
  when the session's oldest recordings were trimmed."*
- `POST /recorder/arm` with an `airport_icao`/`runway_ident` that navdata does not know → **404**
  with the navdata sentence; the app-level `NavdataUnavailable` handler already maps an absent
  index to **503**.
- `POST /recorder/arm` while already armed → **200**, idempotent, returning the current status.
  Arming an armed recorder is not an error.
- `format` outside `csv|json` → **422** from the `Literal`.
- **No 501 anywhere in this router.** There is no capability to be missing (D3).

---

## 5. Pydantic models

All in **`core/landing/models.py`** (D19), except `StateFrame`/`FrameBuffer` which are in
`core/frames.py` (§2, Track 0). Units live in the field names, per `core/models.py`'s convention.
Value models are `frozen=True`; request models add `extra="forbid"`.

### 5.1 `TraceSample` — adopted from the UI, reclassified

The panel's `types.mock.ts` defines a nine-field `TraceSample`. **All nine are adopted, unchanged
in name, unit, sign convention and meaning.** They were well chosen: `t_s`, `ias_kt`,
`altitude_agl_ft`, `vs_fpm`, `pitch_deg`, `roll_deg`, `loc_dev_dot`, `gs_dev_dot`,
`distance_from_threshold_m`.

What changes is what the type *is*. The mock's comment calls it "one frame of the recorded
approach"; it is not. `loc_dev_dot`, `gs_dev_dot` and `distance_from_threshold_m` cannot come out
of a simulator read — they are the aircraft's position projected into a runway frame, and they do
not exist until a runway has been identified. `TraceSample` is therefore the **derived,
runway-relative view** of a `StateFrame`, produced by `core.landing.analysis`. Recording produces
`StateFrame`; analysis produces `TraceSample`. Nothing in the panel has to change for that to be
true, which is the strongest evidence the shape was right.

Three fields are added:

```python
class TraceSample(BaseModel):
    """One analysed frame of the approach: the recorded state, expressed relative
    to the runway. Derived — see core.frames.StateFrame for what was recorded."""

    model_config = ConfigDict(frozen=True)

    t_s: float
    ias_kt: float
    altitude_agl_ft: float
    vs_fpm: float
    pitch_deg: float
    roll_deg: float
    loc_dev_dot: float | None   # None when the runway is unknown (D12)
    gs_dev_dot: float | None
    distance_from_threshold_m: float | None

    # --- added ---
    groundspeed_kt: float       # every along-track distance integrates THIS, not ias_kt:
                                # a 20 kt headwind is 300 m of float distance over 30 s.
    normal_g: float             # the trace behind peak_g; a G spike with no context is
                                # unreadable in a debrief.
    cross_track_m: float | None # the physical truth behind loc_dev_dot, kept so the
                                # dot convention (D9) destroys no information.
```

The three runway-dependent fields become `float | None` — the honest consequence of D12, and the
single largest re-typing cost in the panel (§10.2).

### 5.2 `LandingReport` — the UI's ten, plus six

All ten of the panel's numbers are adopted with their names, units and sign conventions:
`touchdown_vs_fpm`, `peak_g`, `pitch_at_touchdown_deg`, `roll_at_touchdown_deg`,
`centreline_offset_m`, `flare_duration_s`, `float_distance_m`, `touchdown_distance_m`,
`ias_at_threshold_kt`, `heading_vs_runway_deg`.

Six are added, each traceable to a feature-spec §11 bullet the ten do not cover:

| Added field | Type | Feature-spec bullet it satisfies |
|---|---|---|
| `flare_height_ft` | `float \| None` | *"Flare (**height** and duration)"* — the panel has only the duration. `None` when no flare was detectable (a flat arrival). |
| `float_duration_s` | `float` | *"Floating (distance/**time** in the flare)"* — the panel has only the distance. |
| `landing_roll_m` | `float \| None` | *"**Landing distance**"*. The panel's `touchdown_distance_m` is *where* the aircraft touched, measured from the threshold; this is *how far it then took to slow down*, integrated from `groundspeed_kt` from touchdown to the first frame at or below `ROLLOUT_STOP_KT`. `None` on a touch-and-go, where the aircraft never slowed — which is exactly when the number would otherwise be a lie. |
| `loc_dev_max_dot` | `float \| None` | *"**Localizer deviation**"* as a per-landing number, not only a chart: the worst absolute deviation inside `DEVIATION_WINDOW_NM` of the threshold. |
| `gs_dev_max_dot` | `float \| None` | *"**Glideslope deviation**"*, same window and rule. |
| `bounce_count` | `int` | Not a spec bullet. It is included because the touchdown detection must count bounces anyway to know when the rollout began (D14), and because *"which touchdown are these numbers from"* is otherwise unanswerable from the report alone. |

Plus two fields that are about the recording rather than the landing, and are the honesty
mechanism of D6:

```python
    sample_rate_hz: float        # measured mean, frames / (t_last - t_first)
    frame_count: int
```

### 5.3 Nullability — exactly which numbers need a runway

This table is the contract for D12 and the one the panel's formatter is written against.

| Computable with **no** runway | Requires a runway |
|---|---|
| `touchdown_vs_fpm`, `peak_g`, `pitch_at_touchdown_deg`, `roll_at_touchdown_deg`, `flare_height_ft`, `flare_duration_s`, `float_duration_s`, `float_distance_m`, `landing_roll_m`, `bounce_count`, `sample_rate_hz`, `frame_count` | `centreline_offset_m`, `touchdown_distance_m`, `ias_at_threshold_kt`, `heading_vs_runway_deg`, `loc_dev_max_dot`, `gs_dev_max_dot` |

`float_distance_m` and `landing_roll_m` land on the left because they integrate `groundspeed_kt`
over time, which needs no runway at all — a small but real payoff for D2 having added groundspeed.

### 5.4 Record, summary and status

```python
LandingOutcome = Literal["landed", "go_around", "aborted"]
#: "aborted" = the recorder disarmed on the MAX_RECORDING_S guard or on an
#: explicit POST /recorder/disarm. The trace is kept; report is None.


class RunwayContext(BaseModel):
    """Which runway the analysis was flown against, and on what assumptions —
    every substituted default is named, so a report can never quietly imply a
    published glide path it invented."""

    model_config = ConfigDict(frozen=True)

    airport_icao: str
    runway_ident: str
    true_bearing_deg: float
    glide_path_deg: float
    glide_path_source: Literal["ils", "default"]
    threshold_crossing_height_ft: float
    threshold_crossing_height_source: Literal["published", "default"]
    localizer_reference: Literal["ils_antenna", "runway_end_estimate"]


class LandingSummary(BaseModel):
    landing_id: str          # uuid4().hex, the ProfileStore id convention
    recorded_at: datetime    # UTC wall clock of the FIRST frame — the only wall
                             # clock in the whole model (§2.1)
    outcome: LandingOutcome
    runway: RunwayContext | None
    runway_unavailable_reason: str | None   # instructor-facing, D12
    touchdown_vs_fpm: float | None          # the headline number, for the picker
    sample_rate_hz: float


class LandingRecord(BaseModel):
    summary: LandingSummary
    report: LandingReport | None   # None for go_around / aborted (D13)
    samples: tuple[TraceSample, ...]
    touchdown_index: int | None    # index INTO THE SERVED TRACE, recomputed per
                                   # decimation (D5) — never an index into the
                                   # full-rate buffer
    trace_rate_hz: float           # what the served trace was decimated to
    truncated: bool                # the buffer dropped its oldest frames


#: "armed" = criteria met, buffering. "rollout" = on the ground, waiting for the
#: aircraft to slow (a bounce goes back to "armed", D14). A Literal, not an Enum:
#: every closed set in this project is a Literal (RunwaySurface, StationKind,
#: PushbackDirection) and it generates a cleaner union in schema.d.ts.
RecorderPhase = Literal["idle", "armed", "rollout", "analysing"]


class RecorderStatus(BaseModel):
    phase: RecorderPhase
    armed_manually: bool
    elapsed_s: float
    frame_count: int
    achieved_rate_hz: float
    runway_ident: str | None      # resolved early when navdata allows, for the badge
```

### 5.5 Manifest

```python
class LandingManifest(BaseModel):
    supported: bool = True        # always. Kept for shape-consistency with every
    reason: str | None = None     # other manager's manifest, and so the panel's
                                  # gate helper has the same signature everywhere.
    target_sample_hz: float = RECORDER_SAMPLE_HZ
    min_trustworthy_sample_hz: float = MIN_TRUSTWORTHY_SAMPLE_HZ
    trace_display_hz: float = TRACE_DISPLAY_HZ
    arm_max_agl_ft: float = ARM_MAX_AGL_FT
    default_glide_path_deg: float = DEFAULT_GLIDESLOPE_DEG   # from core.geodesy
    vref_kt: float | None         # D18: airframe Vref, for the UI's speed grading
    vref_source: Literal["airframe_vso", "approach_category", "unknown"]
```

`vref_kt` reuses what already exists: `AirframeInfo.vso_kias × core.geodesy.VAT_FROM_VSO` when the
airframe reports a stall speed, otherwise `APPROACH_CATEGORY_VAT_KT[DEFAULT_APPROACH_CATEGORY]`.
Issue #82 ("approach category is assumed, not read from the airframe") is the same gap seen from
another angle; `vref_source` makes the assumption visible rather than fixing it here.

### 5.6 Constants

```python
RECORDER_SAMPLE_HZ: float = 20.0          # top of the spec's 10-20 Hz band; the pump
                                          # escalates to it only while armed (D4)
MIN_TRUSTWORTHY_SAMPLE_HZ: float = 10.0   # bottom of the band; below it the report is
                                          # served with a warning, not withheld (D6)
TRACE_DISPLAY_HZ: float = 4.0             # what /records/{id} serves by default (D5)
LANDING_STATUS_INTERVAL_S: float = 0.5    # WS /ws/landing, 2 Hz

ARM_MAX_AGL_FT: float = 1500.0
ARM_MIN_GEAR_RATIO: float = 0.9
ARM_MIN_DESCENT_FPM: float = -100.0
ARM_ALIGNMENT_DEG: float = 45.0           # heading vs runway, when a runway is known
ARM_CAPTURE_RANGE_NM: float = 12.0
ARM_CAPTURE_HALF_ANGLE_DEG: float = 10.0  # feature spec 11's "localizer capture region"

GO_AROUND_AGL_FT: float = 1500.0          # climbed back through it, never touched down
ROLLOUT_SETTLE_S: float = 3.0
ROLLOUT_STOP_KT: float = 35.0             # taxi speed; also ends landing_roll_m
MAX_RECORDING_S: float = 900.0
MAX_FRAMES: int = 20_000                  # ~16 min at 20 Hz; oldest dropped, `truncated` set
MAX_RETAINED_LANDINGS: int = 20

FLARE_VS_THRESHOLD_FPM: float = -200.0    # the flare begins when the sink rate first
                                          # rises through this on the way to touchdown
FLOAT_VS_THRESHOLD_FPM: float = -100.0    # "nearly level" — floating, not descending
DEVIATION_WINDOW_NM: float = 3.0
LOC_DEG_PER_DOT: float = 1.25             # D9
GS_DEG_PER_DOT: float = 0.35              # D9
DEFAULT_TCH_FT: float = 50.0
RUNWAY_SEARCH_RADIUS_NM: float = 3.0      # touchdown point -> nearest runway
```

Every threshold above is a **stated default, not a measured one**. §13.4 records that and says
what would settle them.

---

## 6. `SimAdapter` / `Capabilities` additions

**This is a shared-foundation change. It is made once, alone, by one agent, before any Phase 4
work branches off it, and it must not run concurrently with any other contract change** (the
`CLAUDE.md` parallelisation policy; §12.1 sequences it).

### 6.1 Four fields on `AircraftState`

```python
class AircraftState(BaseModel):
    """A live snapshot of the user aircraft, as streamed over the WebSocket."""

    # ... the nine existing fields, unchanged ...

    altitude_agl_ft: float = Field(
        description="Height of the aircraft above the terrain directly below, in feet. "
        "The simulator's own radio-altimeter equivalent, NOT altitude_ft minus a field "
        "elevation: the ground before a threshold is not flat, and a flare height "
        "computed against field elevation is wrong by the terrain profile."
    )
    groundspeed_kt: float = Field(
        ge=0.0,
        description="Speed over the ground in knots. Differs from ias_kt by the wind and "
        "by density altitude; every along-track distance integrates this one.",
    )
    normal_g: float = Field(
        description="Normal load factor along the aircraft's vertical axis. 1.0 in level "
        "flight, 0.0 in free fall. Read, never derived: differentiating vertical_speed_fpm "
        "twice across a sampling interval produces noise, not a touchdown load.",
    )
    gear_ratio: float = Field(
        ge=0.0,
        le=1.0,
        description="Landing gear deployment, 0.0 fully retracted to 1.0 fully extended. "
        "A ratio rather than a bool because the transit state is real and because the "
        "arming rule (feature spec 11) says 'gear down', which is a threshold on this.",
    )
```

Required, no defaults, matching the model's "always complete" convention (`AircraftSetup` is the
sparse one). The blast radius is small and mechanical: **ten `AircraftState(...)` call sites
repo-wide** — `adapters/fake/fake_adapter.py:53`'s `DEFAULT_STATE`,
`adapters/xplane/xplane_adapter.py:927`'s read, and eight in tests, two of which splat a JSON
payload (`tests/server/test_app.py:67,76`) and need no edit at all. `mypy --strict` reports every
remaining one. `ui/src/api/models.ts`'s `NUMERIC_STATE_FIELDS` guard gains all four
(`on_ground` stays its separate boolean check), which is the only UI change Track 0 forces —
without it the runtime guard silently accepts frames missing the new fields.

**Why not a separate `RecorderFrame` model returned by a new adapter method?** It would mean a
second read path against the simulator, a second thing for MSFS to implement, and two models
describing one aeroplane. The four fields are useful beyond this manager (§2.2), which is the test
for whether they belong on the shared model.

### 6.2 No new method

`get_aircraft_state()` and `stream_state(interval_s)` are already on the protocol
(`core/sim_adapter.py:132` and `:314`) and neither is capability-gated. `stream_state`'s contract
is unchanged; only who calls it changes (§3.2).

### 6.3 No new `Capabilities` flag — the justification, both ways

**The case for a flag** (`can_record_landings`, or a numeric `max_state_rate_hz`): a hypothetical
adapter that cannot sample fast enough produces a report whose derivative numbers are misleading,
and hard rule 3 says unsupported features are disabled in the UI, never left to fail at runtime.

**Why it is still wrong.** Three reasons:

1. **Every existing flag gates a write.** `can_set_position`, `can_set_weather`,
   `can_inject_failures`, `can_spawn_traffic`, `can_control_camera`, `can_pushback` — each one
   answers "may this adapter change the simulator?". This manager changes nothing. Reading state is
   the one thing an adapter cannot be without: an adapter that cannot answer
   `get_aircraft_state()` is not connected.
2. **It would be `True` everywhere, forever.** Fake: yes. X-Plane: yes. MSFS: yes — SimConnect's
   state read is its most basic operation. A flag with no `False` case gates nothing and only adds
   a branch to every consumer.
3. **The real variable is continuous, and a boolean would lie about it.** "Can this adapter sample
   fast enough?" has the answer *"today, on this machine, with this scenery loaded, about
   14 Hz"* — which is neither `True` nor `False`. D6 reports the measurement instead: the
   recorder counts its own frames, `LandingReport.sample_rate_hz` carries the answer, and the panel
   shows *"Recorded at 6.2 Hz — below the 10 Hz this analysis assumes; touchdown rate and peak G
   are indicative only"* under the report. Nothing throws, nothing is hidden, and the instructor is
   told the truth rather than shown a disabled tab.

Hard rule 3 is satisfied in its spirit: the limitation is surfaced before it can mislead. It is
simply surfaced as a number, because that is what it is.

### 6.4 What `FakeSimAdapter` must do

- Report all four new fields from its in-memory state, defaulting to a coherent parked aeroplane:
  `altitude_agl_ft=0.0`, `groundspeed_kt=0.0`, `normal_g=1.0`, `gear_ratio=1.0`.
- Keep them coherent in `_advance()`: `groundspeed_kt` tracks the integration it already does from
  `ias_kt`, and `altitude_agl_ft` follows the altitude changes it already applies. It does **not**
  gain a terrain model, a landing-gear animation or an accelerometer — the Fake's state *is* its
  observable behaviour, the Failures design's ledger philosophy. `normal_g` stays 1.0 unless a test
  sets it.
- No new method, no new flag, nothing else.

The Fake deliberately does **not** learn to fly an approach. The analysis is tested from
hand-built frame sequences (§11.3, §11.4) and the recorder is tested by feeding frames straight
into `LandingRecorder.offer()` (§11.8) — neither needs a simulator that can land.

### 6.5 Contract tests to add — `tests/adapters/test_contract.py`

`CAPABILITY_COVERAGE` gains no entry, because no capability is added. What the suite does gain is
the state-shape coverage for D2's four fields, parametrised over both adapters as everything else
there is:

| Test | Pins |
|---|---|
| `test_state_reports_agl_groundspeed_g_and_gear` | All four fields present, finite, and inside their declared bounds on a freshly connected adapter. |
| `test_agl_is_zero_on_the_ground` | `on_ground` and `altitude_agl_ft` cannot disagree: on ground → AGL within `AGL_GROUND_TOLERANCE_FT` of 0. Live tolerance is looser than the Fake's, the `POSITION_TOLERANCE_M` precedent. |
| `test_normal_g_is_about_one_when_settled` | A stationary or steadily-flying aircraft reads `1.0 ± NORMAL_G_TOLERANCE`. The single test most likely to catch a wrong dataref or a units error (g vs m/s²). |
| `test_gear_ratio_tracks_the_gear_command` | `apply_setup(gear_down=True)` then `gear_down=False` moves `gear_ratio` towards 1.0 and 0.0. Live: allow the transit time — poll, do not assert instantly. |
| `test_groundspeed_is_consistent_with_ias_in_still_air` | On the Fake, exact. Live: within a wide tolerance and marked as a sanity check, not a wind measurement — the live tolerance is generous on purpose and §13.2 says why. |
| `test_stream_state_carries_the_new_fields` | The streamed frames are complete `AircraftState`s, not a reduced projection. |

---

## 7. Dataref mapping (X-Plane)

**This section describes `adapters/xplane/` only. No dataref name appears in `core/`.**

### 7.1 The four new reads

Every name below is a **candidate, not a verified fact**. They are resolved with the
`xplane-datarefs` MCP against a live simulator and confirmed in a spike before the adapter code is
written — the discipline the Failures design used for its low-confidence entries.

| `AircraftState` field | Candidate dataref | Unit in X-Plane | Conversion | Confidence |
|---|---|---|---|---|
| `altitude_agl_ft` | `sim/flightmodel/position/y_agl` | metres | `/ 0.3048` (`_METRES_PER_FOOT`, already in the adapter) | plausible, **verify in spike** |
| `groundspeed_kt` | `sim/flightmodel/position/groundspeed` | m/s | `× 1.943844` | plausible, **verify in spike** |
| `normal_g` | `sim/flightmodel/forces/g_nrml` | g (dimensionless) | none | plausible, **verify in spike** — and verify the *sign and datum*: a value of 0 at rest instead of 1 means it is a delta, not a load factor |
| `gear_ratio` | `sim/flightmodel2/gear/deploy_ratio[0]` | 0–1 array, per gear | take index 0, clamp | plausible, **verify in spike**. Fallback: `sim/aircraft/parts/acf_gear_deploy`. Note the existing write path uses `sim/cockpit2/controls/gear_handle_down` (`xplane_adapter.py:185`) — the *handle*, not the *gear*, and the arming rule wants the gear |

These join the nine keys `get_aircraft_state()` already reads
(`adapters/xplane/xplane_adapter.py:912-937`), taking the per-frame read count from 9 to 13 — which
is precisely why §3.3's batching item matters more after this change than before it.

### 7.2 Nothing else in the adapter changes

No new method, no new capability, no write path. `stream_state()` keeps its signature and its
docstring's stated intent (replace polling with the Web API subscription); §3.3 explains why that
intent is now worth acting on and §13.1 tracks it.

### 7.3 MSFS (Phase 5 target)

SimConnect exposes an equivalent for each of the four (`PLANE ALT ABOVE GROUND`,
`GROUND VELOCITY`, `G FORCE`, `GEAR POSITION` / `GEAR HANDLE POSITION`) — *believed, not verified;
Phase 5's spike settles it*. Because this manager adds no capability, an MSFS adapter that can read
state at all gets landing analysis for free, at whatever rate it sustains (D6). That is the
cleanest possible Phase 5 story and it is a direct consequence of D3.

---

## 8. `core/` logic

A new package, `core/landing/`, plus `core/frames.py` from Track 0. Fully unit-testable with no
simulator, no adapter, no provider and **no clock**. `pyproject.toml`'s explicit
`[tool.setuptools] packages` list gains `core.landing` — easy to forget, and the packaged
executable is where it would be noticed.

```
core/frames.py              StateFrame, FrameBuffer                (Track 0, shared)
core/landing/models.py      Everything in section 5
core/landing/geometry.py    The runway frame and the deviations
core/landing/detect.py      Arming, disarming, touchdown detection — pure decisions
core/landing/analysis.py    frames + runway -> LandingRecord
core/landing/export.py      CSV and JSON
```

### 8.1 What is reused rather than rebuilt

The reviewers treat a re-derived geodesy as a defect, and this manager can be built almost
entirely from what `core/` already has:

| Needed | Already exists |
|---|---|
| World point → runway frame (along-track, cross-track) | `server/position_routes.py:759 _runway_schematic()` does exactly this: `distance_and_bearing(runway.threshold, point)` then `x = d·cos(bearing − axis)`, `y = d·sin(bearing − axis)`. **Promoted to `core/landing/geometry.py` and called by both** (D10). |
| Geodesic distance and bearing | `core.geodesy.distance_and_bearing()` |
| Reference glidepath altitude at a distance | `core.geodesy.glideslope_altitude_ft(threshold_elevation_ft, distance_nm, glideslope_deg)` — the glideslope deviation is `actual − (that + TCH)` |
| Default glide path when a runway has no ILS | `core.geodesy.DEFAULT_GLIDESLOPE_DEG = 3.0` |
| Unit constants | `core.geodesy.METRES_PER_NAUTICAL_MILE`, `FEET_PER_NAUTICAL_MILE` |
| Runway geometry, thresholds, TCH, ILS course, glide path angle, antenna positions | `core.models.Runway` / `core.models.Ils` — all of it already modelled, including `threshold_crossing_height_ft` and `glideslope_position` |
| Reference approach speed | `core.geodesy.APPROACH_CATEGORY_VAT_KT`, `VAT_FROM_VSO`, `category_for_vat()`, `AirframeInfo.vso_kias` |
| Runway ident normalisation | `core.navdata.normalize.normalize_runway_ident()` |

**Nothing new is added to `core/geodesy.py`.** The only geodesy this manager writes is the
*inverse* of `_offset()` — the projection — and that already exists in `server/` and is being
moved, not written.

### 8.2 `core/landing/geometry.py`

```python
class RunwayFrame:
    """A runway expressed as the frame every approach number is measured in.

    Built once per analysis from a Runway (+ its Ils, when it has one), so
    the per-frame projection is arithmetic and the substituted defaults are
    decided once and recorded in RunwayContext (section 5.4) rather than
    re-guessed 6000 times.
    """

    @classmethod
    def from_runway(cls, runway: Runway) -> "RunwayFrame": ...

    def project(self, position: GeoPosition) -> tuple[float, float]:
        """(along_track_m, cross_track_m) from the DISPLACED LANDING THRESHOLD.

        along_track is positive DOWN THE RUNWAY, so an aircraft on final has a
        negative value -- exactly the convention the UI's
        `distance_from_threshold_m` already documents ("0 at the threshold,
        negative before it") and exactly what _runway_schematic() already
        computes (it places the departure end at +length_nm). Note that
        SchematicPoint.x_nm's own field description, "positive away from the
        threshold", reads ambiguously and means "along the axis": the geometry,
        not the sentence, is the contract, and moving the function is the moment
        to fix the sentence. cross_track is positive right seen from the
        approach, matching core.geodesy._offset()'s across-track convention and
        SchematicPoint.y_nm.
        """

    def localizer_deviation_deg(self, position: GeoPosition) -> float: ...
    def glidepath_deviation_ft(self, position: GeoPosition) -> float: ...
```

**Localizer.** `loc_dev_deg = degrees(atan2(cross_track_m, range_to_reference_m))`, where the
reference is:

- `ils.localizer_position` when the runway has an ILS — the real antenna, so the computed
  deviation matches the needle the student was looking at;
- otherwise the runway's stop end, estimated as `length_m` beyond the threshold along the
  centreline. A localizer is sited a few hundred metres further back still, so this slightly
  *over*states deviation close in; it is a stated approximation, recorded in
  `RunwayContext.localizer_reference` so a report never hides which one it used.

Dots: `loc_dev_dot = loc_dev_deg / LOC_DEG_PER_DOT`, unless `ils.localizer_width_deg` is published,
in which case the half-width is full scale and one dot is half of that. The X-Plane provider never
populates `localizer_width_deg` (`core/navdata/xplane_native/provider.py` sets every other `Ils`
field and not that one), so the constant is what will actually be used — which is why D9 states it
rather than leaving it implicit.

**Glideslope.** `reference_alt_ft = glideslope_altitude_ft(threshold_elevation_ft, |along_track|,
glide_path_deg) + tch_ft`, and `gs_dev_ft = altitude_ft − reference_alt_ft`. Converted to an angle
about the glideslope antenna when `ils.glideslope_position` exists, about the threshold otherwise,
then to dots by `GS_DEG_PER_DOT`. The glide path is `ils.glideslope_deg` when published and
`DEFAULT_GLIDESLOPE_DEG` otherwise (`RunwayContext.glide_path_source` records which); the TCH is
`runway.threshold_crossing_height_ft` when the CIFP carried it and `DEFAULT_TCH_FT` otherwise.

Two worked examples, both hand-checkable and both asserted in §11.2:

- 1.0 NM (1852 m) from the reference, 30 m right of centreline →
  `atan(30 / 1852) = 0.928036°` → `0.742429` dots right.
- Threshold elevation 2000 ft, TCH 50 ft, 3.00° path, 2.0 NM out, aircraft at 2700 ft MSL →
  reference `2000 + 50 + tan(3°) × 2 × 6076.115485564304 = 2686.871 ft` → `+13.129 ft` high →
  `atan(13.129 / 12152.231) = 0.061899°` → `0.176854` dots high.

**Accuracy.** This is a tangent-plane construction on top of a geodesic range and bearing, the same
one `_runway_schematic()` already uses and whose docstring calls out as display-grade. Over the
20 NM this manager ever looks at, the error is far below one pixel of a deviation chart. It is
**not** used to position anything — `core/local_frame.py`'s rigid ECEF rotation exists for that,
and the `CLAUDE.md` warning about 120 m of tangent-plane error at 40 km is about *placing* an
aeroplane, not about measuring where it was.

### 8.3 `core/landing/detect.py` — the state machine, as pure functions

```python
def should_arm(state: AircraftState, runway: Runway | None, config: ApproachConfig) -> bool:
    """Gear down, low, and going down -- and, when a runway is known, pointed at it.

    Takes an AircraftState, not a StateFrame: the decision is a function of
    where the aeroplane is, never of when it got there.

    Without a runway (D11): gear_ratio >= ARM_MIN_GEAR_RATIO,
    altitude_agl_ft <= ARM_MAX_AGL_FT, vertical_speed_fpm <= ARM_MIN_DESCENT_FPM.
    With one, additionally: within ARM_CAPTURE_RANGE_NM, inside
    +/-ARM_CAPTURE_HALF_ANGLE_DEG of the extended centreline, and heading within
    ARM_ALIGNMENT_DEG of the runway bearing -- feature spec 11's "inside the
    localizer capture region", which needs a runway and therefore cannot be a
    precondition for arming at all.
    """


def advance(
    phase: RecorderPhase,
    buffer: FrameBuffer,
    config: ApproachConfig,
) -> tuple[RecorderPhase, LandingOutcome | None]:
    """One step of the recorder's state machine. Pure: no clock, no I/O.

    The second element is the terminal outcome, or None while recording
    continues -- so the caller in server/ has exactly one thing to check.

    "armed"   -> "rollout"    first on_ground frame
    "armed"   -> "go_around"  climbed back through GO_AROUND_AGL_FT, never touched
    "armed"   -> "aborted"    buffer spans MAX_RECORDING_S
    "rollout" -> "armed"      airborne again within ROLLOUT_SETTLE_S: a BOUNCE, not
                              a go-around, and not a reason to stop recording (D14)
    "rollout" -> "landed"     on the ground for ROLLOUT_SETTLE_S AND
                              groundspeed_kt <= ROLLOUT_STOP_KT
    """
```

A gear-up landing never arms — the gear criterion is the feature spec's, and this design keeps it
rather than quietly widening it. `POST /api/landing/recorder/arm` is the answer, and it is why that
endpoint exists (§4). Stated so it is a documented limitation with a workaround rather than a bug
report waiting to happen.

### 8.4 `core/landing/analysis.py`

```python
def analyse_landing(
    frames: Sequence[StateFrame],
    runway: Runway | None,
    *,
    config: ApproachConfig = DEFAULT_APPROACH_CONFIG,
    outcome: LandingOutcome = "landed",
) -> LandingRecord:
    """A buffer of timestamped frames in, a LandingRecord out.

    The whole of roadmap Phase 4 exit criterion 1, and the reason this
    signature takes a Runway VALUE rather than a NavdataProvider: core/ must
    be callable from a test with two hand-written objects and no I/O
    whatsoever. `runway=None` is a first-class input, not an error (D12).
    """
```

The parts that are easy to get subtly wrong, and how each is defined:

- **The touchdown instant is interpolated (D14).** Between the last airborne frame and the first
  on-ground frame, `t_touchdown` is found by linearly interpolating `altitude_agl_ft` to zero, and
  `touchdown_vs_fpm`, pitch, roll and position are interpolated to that instant. At 20 Hz and
  120 kt the aircraft covers ~3 m per sample; snapping to the first on-ground frame biases every
  touchdown number in the same direction, every time. A cross-check on `on_ground` guards the case
  where AGL never quite reaches zero (a bumpy threshold, or a datum offset in the sim).
- **Every derivative divides by the actual `Δt`** between the two frames used, never by
  `1 / RECORDER_SAMPLE_HZ`. §3.2's arrival timestamps are jittery by construction and §11.1 tests
  with a jittered fixture for exactly this reason.
- **`peak_g` is a sampled maximum, and the report says so.** A touchdown impulse is shorter than a
  50 ms sampling interval; the recorded peak is a lower bound on the true one. It is comparable
  between landings recorded at the same rate — which is what a debrief actually uses it for — and
  is not an absolute measurement. `sample_rate_hz` travels with it so the comparison is never made
  across incomparable recordings.
- **The flare** begins at the last frame before touchdown where `vs_fpm` first rises through
  `FLARE_VS_THRESHOLD_FPM` and stays above it; `flare_height_ft` is the AGL there and
  `flare_duration_s` the interval to the interpolated touchdown. No flare detected → both `None`
  and `0.0` respectively, which is itself a debrief finding.
- **The float** is the sub-interval of the flare where `vs_fpm >= FLOAT_VS_THRESHOLD_FPM` —
  nearly level rather than descending. `float_duration_s` is its length and `float_distance_m` the
  integral of `groundspeed_kt` over it.
- **`landing_roll_m`** integrates `groundspeed_kt` from the interpolated touchdown to the first
  frame at or below `ROLLOUT_STOP_KT`; `None` if that frame never arrives.
- **`loc_dev_max_dot` / `gs_dev_max_dot`** are the maximum absolute values over frames inside
  `DEVIATION_WINDOW_NM` of the threshold and before touchdown. Deviations during the ground roll
  are meaningless, which the panel's `DeviationChart` already knew — it slices to `touchdownIndex`.

`analyse_landing` never raises for a data reason. An empty buffer, a buffer with one frame, a
buffer that never touched down: each returns a `LandingRecord` with the outcome that describes it
and `report=None`. The only exception it can raise is a `ValidationError` from a malformed frame,
which is a programming error, not an instructor's landing.

### 8.5 Where the navdata lookup happens

In `server/landing_recorder.py`, not in `core/`. After the recorder disarms, it takes the
interpolated touchdown position, asks the `NavdataProvider` for airports near it, takes their
runways, and picks the one whose extended centreline the touchdown point is closest to within
`RUNWAY_SEARCH_RADIUS_NM` and whose bearing is within `ARM_ALIGNMENT_DEG` of the touchdown
heading. Failure at any step — no index, no airport, no runway close enough — is not an error: it
sets `runway_unavailable_reason` and calls `analyse_landing(frames, None)` (D12).

Resolving the runway *after* the landing rather than before it is deliberate. It is the only moment
the answer is unambiguous: an aircraft on a 10 NM final to a parallel pair has not yet chosen, and
a recorder that guesses early gets the deviations for the wrong runway.

---

## 9. Exports

Generated in `core/landing/export.py`, from a `LandingRecord`. Pure string functions, no I/O; the
route wraps them in a `Response` with `Content-Disposition`, exactly as
`server/profile_routes.py:399` already does for profiles.

### 9.1 JSON

`LandingRecord.model_dump_json(indent=2)` over the **full-rate** trace. Nothing hand-rolled: the
model is the format, and it re-imports through `model_validate_json` — which is how manager 12
will hand a stored landing back to the analysis.

### 9.2 CSV

Header row, then one row per `TraceSample`, columns in the panel's existing order followed by the
three additions:

```
t_s,ias_kt,altitude_agl_ft,vs_fpm,pitch_deg,roll_deg,loc_dev_dot,gs_dev_dot,
distance_from_threshold_m,groundspeed_kt,normal_g,cross_track_m
```

`None` renders as an empty field. The report and the runway context go in `# `-prefixed comment
lines above the header — readable in a text editor, ignored by every spreadsheet's import, and it
keeps one file per landing instead of two. Python's `csv` module, which the repo does not import
anywhere today; no dependency.

### 9.3 PDF — deferred, with a replacement (D16)

Feature spec §11 asks for PDF and notes it is *"the only one that pulls a dependency, and it must
stay small enough not to bloat the PyInstaller bundle."* This design proposes not to pull the
dependency at all, and says so plainly rather than quietly dropping the format.

**What a `core/`-side PDF would actually cost.** The debrief is two charts and a table. The charts
exist today as hand-rolled SVG in `TraceChart.tsx` and `DeviationChart.tsx`. A Python PDF would
have to **re-draw them**, in a second implementation, in a second language, kept in sync by hand —
which is D17's argument against duplicated CSV, with more surface. On top of that:

| Candidate | Rough size | Notes |
|---|---|---|
| `reportlab` | ~2–3 MB wheel, includes a C accelerator and bundled fonts | The standard answer. BSD-licensed *(verify — the open-source distribution's licence terms must be read before adopting, not assumed)*. PyInstaller-friendly. Charts must be drawn from scratch. |
| `fpdf2` | ~0.2 MB, pure Python | Much smaller. **Licence needs checking before it goes anywhere near a proprietary bundle** *(verify)* — a copyleft dependency inside a single-file executable is a licensing question, not a packaging one. Charts still drawn from scratch. |
| `weasyprint` | Tens of MB with cairo/pango | Renders HTML, so the charts could be reused — and it is far too large for a bundle whose spec explicitly excludes `numpy` and `PIL` to stay small. Rejected. |

**The recommendation: print-to-PDF from the panel.** A `landing.print.css` stylesheet and a
"Print debrief" button calling `window.print()` produces a PDF **containing the real charts**, on
every platform, through a printer dialog every instructor already knows, for zero bytes of bundle
and zero new dependency. The panel's currently-disabled "Export PDF" button becomes an enabled
"Print debrief" — a strictly better state than today's honest-but-empty placeholder.

**When to revisit.** If a headless or batch PDF is ever needed — a scenario run that emails a
debrief, a report generated with no browser open — `reportlab` is the candidate, and the gate is a
**measured** `packaging/instructor-station.spec` bundle delta, not an estimate. Recorded as §13.5.

---

## 10. UI panel outline

`ui/src/features/landing/` **already exists on `dev`** and is complete against
`types.mock.ts`: `LandingPanel.tsx`, `TraceChart.tsx`, `DeviationChart.tsx`,
`LandingReportCard.tsx`, `grade.ts`, `format.ts`, `scale.ts`, `export.ts`, `landingApi.ts`,
`landingSlice.ts`, `mock.ts`, `landing.css` and their tests. This section is therefore not "what to
build" but "what changes", which is the honest way to price it.

### 10.1 What the panel gains

| Addition | Why |
|---|---|
| A **recorder status strip** at the top — idle / armed / rollout, elapsed, frame count, achieved rate — fed by `WS /ws/landing`, plus manual **Arm** and **Disarm** buttons | The instructor must be able to see that the approach is being caught, and to catch one the detection missed (§8.3's gear-up case). |
| A **rate warning** under the report when `sample_rate_hz < min_trustworthy_sample_hz` | D6. Plain language, naming the two numbers it affects. |
| A **"no navdata" banner** carrying `runway_unavailable_reason`, with the runway-dependent metrics rendered as `—` | D12. The instructor learns *why* six numbers are blank instead of wondering. |
| An **outcome badge** for `go_around` / `aborted` records, which show a trace and no report | D13. |
| `landing.print.css` and a **Print debrief** button | D16. |

### 10.2 The re-typing cost, file by file

| File | Change | Size |
|---|---|---|
| `types.mock.ts` | **Deleted.** Types become aliases in `ui/src/api/models.ts` over the regenerated `schema.d.ts` (`LandingRecord`, `LandingReport`, `LandingSummary`, `TraceSample`, `RecorderStatus`, `LandingManifest`) — `CLAUDE.md`'s "never hand-write API types", which the file's own header already anticipates. | delete + ~8 alias lines |
| `mock.ts`, `mock.test.ts` | **Deleted** once the endpoints land. Until then they keep the panel alive, exactly as `weather/mock.ts` and `traffic/mock.ts` do. | delete |
| `landingApi.ts` | `queryFn: () => withLatency(MOCK_LANDINGS)` becomes `query: () => '/landing/records'`, plus `getLandingRecord`, `getLandingManifest`, `armRecorder`, `disarmRecorder`. Still `injectEndpoints` (D20). | small |
| `landingSlice.ts` | `selectedId: LandingId \| null` → `string \| null` (server ids are `uuid4().hex`, not a four-value union), and a `recorderStatus` field fed by the WS — the `telemetrySlice` pattern. | small |
| `grade.ts` | **The largest change.** `MetricKey` gains six entries and every metric becomes nullable: `gradeMetric(key, value: number \| null): Grade \| 'unknown'`. It also stops being `keyof LandingReport` and becomes an explicit subset — `sample_rate_hz` and `frame_count` describe the *recording*, not the landing, and grading them would be meaningless. `MOCK_VREF_KT = 92` is replaced by the manifest's `vref_kt` (D18). The band table itself stays — grading is UI policy. | moderate |
| `format.ts` | Six new `MetricDescriptor` entries, and every formatter handles `null` → `'—'`. | moderate |
| `LandingReportCard.tsx` | **Nothing structural.** It already maps over `REPORT_METRICS`, so six more rows render for free; it needs a `data-grade="unknown"` style in `landing.css`. This is the payoff for adopting the shape (D7). | trivial |
| `TraceChart.tsx`, `DeviationChart.tsx`, `scale.ts` | **Unchanged apart from nullable-channel handling** in the deviation chart, which must break its polyline where the runway is unknown rather than plot a gap as zero. The trace charts' channels are all non-null. | trivial / small |
| `export.ts` | `landingToCsv` and `landingToJson` **deleted** (D17); `downloadText` deleted with them. The buttons become anchors to `/api/landing/records/{id}/export?format=…`. | delete |
| `export.test.ts` | Deleted with the builders. | delete |
| `LandingPanel.tsx` | The additions in §10.1; the picker keys on `landing_id`; `touchdownIndex` comes from `LandingRecord.touchdown_index`. | moderate |
| `landing.css` | Status strip, banners, `unknown` grade, and the new `landing.print.css`. | moderate |

Nothing in the panel is thrown away. The charts, the scales, the grading structure, the report card
and the layout survive intact — which is what "adopt the contract" bought, and the reason §5.1
adopted names and units rather than improving them.

### 10.3 Capability gating

**None.** There is no flag to gate on (D3), so no `gate.ts` and no disabled tab. What the panel
does instead — the rate warning and the missing-navdata banner — is the same discipline applied to
the things that genuinely vary: *tell the instructor what is limited and why, before it can
mislead*.

---

## 11. Test plan

Everything except §11.10 runs in CI against `FakeSimAdapter` and hand-built fixtures. No
simulator, no navdata files, no committed recordings.

### 11.1 `tests/core/test_frames.py` (Track 0)

`FrameBuffer` appends, caps at `MAX_FRAMES` dropping oldest, sets `truncated`, reports its span;
`StateFrame` rejects a negative `t_s`; a buffer never reads a clock (the test passes explicit
`t_s` values including deliberately irregular ones).

### 11.2 `tests/core/landing/test_geometry.py`

The hand-checkable numbers, each computed independently in the test with `math` rather than copied
from the implementation:

- On the centreline, 1 NM out → `cross_track_m == 0` within 1 mm, `loc_dev_dot == 0`,
  `along_track_m == -1852.0` within 1 mm (negative before the threshold, §8.2).
- 30 m right at 1 NM → `0.928036°` → `0.742429` dots, both within 1e-6.
- The glidepath example of §8.2: `+13.129 ft`, `0.176854` dots high.
- Exactly on a 3° path with a 50 ft TCH → `gs_dev_dot == 0` at 1, 3 and 10 NM.
- Sign conventions, all four: right of centreline is positive, left negative, above the path
  positive, below negative. The cheapest possible test for the single most likely bug.
- No ILS → `glide_path_source == "default"`, `3.0°` used, `localizer_reference ==
  "runway_end_estimate"`; with an ILS at 3.25° → `"ils"` and `3.25°`.
- Published `localizer_width_deg` overrides `LOC_DEG_PER_DOT`; absent, the constant is used.
- The promoted projection agrees with `server/position_routes.py`'s existing schematic output on
  the fixtures that module's tests already use — the regression guard for D10's move.

### 11.3 `tests/core/landing/test_detect.py`

Hand-built frame sequences, one per behaviour: arms on gear + AGL + descent; does not arm gear-up;
does not arm level at 500 ft; arms only inside the capture region when a runway is given;
go-around; bounce → ROLLOUT → ARMED → ROLLOUT with `bounce_count == 1`; rollout completes on
`ROLLOUT_SETTLE_S` **and** `ROLLOUT_STOP_KT`, not on either alone; `MAX_RECORDING_S` aborts.

### 11.4 `tests/core/landing/test_analysis.py` — the exit criterion

A fixture generator, `tests/core/landing/fixtures.py`, builds an **analytic** approach: constant
groundspeed, a 3° path, a flare of stated height and duration, a stated float, a stated touchdown
sink rate — so every report number has a closed-form expected value the test states independently.
This is roadmap Phase 4 exit criterion 1: *"validated against recorded fixture frames with known
answers, computed entirely in `core/` with no simulator involved."*

- The reference approach → all sixteen numbers within stated tolerances.
- **The same approach resampled with jittered `Δt`** (10–25 Hz, irregular) → the same answers
  within a wider tolerance. The test that proves §3.2's "divide by actual `Δt`" was honoured; a
  nominal-rate implementation fails it.
- The same approach at 4 Hz → `sample_rate_hz ≈ 4`, and the touchdown numbers drift measurably.
  Asserted as *drift*, not as correctness — this is the test that documents why 10–20 Hz is in the
  spec at all.
- `runway=None` → the nine runway-free numbers computed, the six runway-dependent ones `None`, no
  exception (D12).
- A go-around sequence → `outcome="go_around"`, `report is None`, `samples` non-empty (D13).
- Degenerate inputs: empty buffer, one frame, all-airborne, all-on-ground → an outcome and no
  raise.
- Touchdown interpolation: a fixture whose true touchdown falls exactly midway between two frames
  → the interpolated instant and sink rate are the midpoint values, not the on-ground frame's
  (D14).
- Bounce: the report describes the **first** touchdown; `bounce_count == 2`.

### 11.5 `tests/core/landing/test_export.py`

CSV header order matches §9.2 exactly (the column order the deleted `ui/.../export.ts` used, so a
saved workflow does not break); `None` renders empty; the `#` comment block parses back; JSON
round-trips through `model_validate_json` to an equal `LandingRecord`.

### 11.6 Contract tests

The six of §6.5, parametrised over both adapters, written by the tester from this document before
the implementation exists.

### 11.7 `tests/server/test_state_pump.py`

Against a stub adapter yielding a scripted `stream_state`: one subscriber at 4 Hz gets every 5th
frame of a 20 Hz pump; the pump idles at 4 Hz and escalates when a 20 Hz subscriber registers and
drops back when it leaves; a slow read causes a **skipped** tick, not a queued one (the test that
would otherwise only be found by a hanging server); cancellation stops the loop and releases the
adapter.

### 11.8 `tests/server/test_landing_routes.py`

`TestClient` + `FakeSimAdapter`, `reset_landings()` between tests. The recorder is driven by
feeding frames straight into `LandingRecorder.offer(t_s, state)` — no simulated flight, no clock,
no sleeping test.

- A full scripted approach fed through `offer()` produces one landing on `GET /records`, and its
  `GET /records/{id}` report matches §11.4's expectations end to end.
- `GET /records/{id}?rate_hz=2` decimates and `touchdown_index` still points at the touchdown
  **in the served trace** (D5's easiest bug).
- `GET /records/{id}/export?format=csv` returns `text/csv` with a `Content-Disposition` filename;
  `format=pdf` → 422.
- Unknown id → 404 with the stated sentence.
- `POST /recorder/arm` while armed → 200, idempotent; with an unknown ICAO → 404.
- `MAX_RETAINED_LANDINGS + 1` landings → the oldest is gone and its id 404s.
- `GET /manifest` echoes the §5.6 constants exactly, so the panel and the server cannot disagree.
- `WS /ws/landing` pushes a status frame and one `landing_complete` event.

### 11.9 UI tests (vitest)

`grade.test.ts` for the six new metrics and the `null` → `'unknown'` path; `format.test.ts` for
`—` rendering; `LandingPanel.test.tsx` for the rate warning, the no-navdata banner and the
go-around badge; `DeviationChart.test.tsx` for a trace with null deviations breaking the polyline
rather than plotting zeros.

### 11.10 `tests/sim/test_live_landing.py` — `@pytest.mark.sim`, never in CI

What only a live X-Plane can answer:

- **The rate.** Consume `stream_state(1 / RECORDER_SAMPLE_HZ)` for 30 s and report the achieved
  rate. This is §13.1's measurement and the single most important live test in this manager — the
  whole of §3 rests on it.
- `normal_g` reads ≈ 1.0 on a parked aircraft; `altitude_agl_ft` ≈ 0 parked; `gear_ratio` responds
  to `apply_setup(gear_down=…)` within the transit time.
- Placed on a 3 NM final with `core.geodesy.final_placement`, the geometry module computes
  `loc_dev_dot ≈ 0` and `gs_dev_dot ≈ 0` — the two halves of the project meeting: the placement
  code puts the aeroplane on the path, the analysis code agrees that it is on the path. Position
  restored in a `finally`.

The `sim-validator` agent's job, never a merge gate.

---

## 12. Parallelisation

### 12.1 Across Phase 4 — the serialisation point, stated first

The roadmap's Phase 4 row is *"Landing Analysis ∥ Session Recorder ∥ Flight Plan — they share the
state-frame model, fix it first."* Concretely:

**Track 0 — the Phase 4 foundation. One agent, alone, merged to `dev` before any of the three
managers branches. Never parallelised.**

Owns:
- `core/models.py` — the four `AircraftState` fields (§6.1)
- `adapters/fake/fake_adapter.py` — reporting them (§6.4)
- `adapters/xplane/xplane_adapter.py` — the four dataref reads (§7.1), **after** the spike that
  verifies the names
- `tests/adapters/test_contract.py` — the six tests of §6.5
- `core/frames.py` — `StateFrame`, `FrameBuffer` (§2)
- `tests/core/test_frames.py`
- `server/state_pump.py` — the fan-out pump, plus rewiring `WS /ws/state` and
  `server/failure_routes.py`'s watcher onto it (§3.2)
- `tests/server/test_state_pump.py`
- `ui/src/api/models.ts` — the four new fields in `NUMERIC_STATE_FIELDS`
- `pyproject.toml` — `core.landing` added to the explicit `[tool.setuptools] packages` list
  (`core/frames.py` needs no entry: it is a module inside an already-listed package, and getting
  that distinction wrong is only visible in the PyInstaller bundle)

It touches `core/sim_adapter.py` not at all — no method, no flag (D3) — which makes it a smaller
foundation commit than Pushback's or Camera's, and means it does **not** contend with any Phase 3
contract work still in flight.

Then the three managers proceed as independent `feature/*` branches in separate **git worktrees**,
each with its own PR to `dev`; CI on each PR is the integration barrier.

### 12.2 Inside this manager

After Track 0, dispatched **in one message**, disjoint directories:

**Track A — `core/` analysis.** `core/landing/{models,geometry,detect,analysis,export}.py` and the
promotion of the projection out of `server/position_routes.py` (D10). Owns `core/landing/` plus
that one function move.
*Deliverable: roadmap Phase 4 exit criterion 1, provable on its own with no server and no UI.*

**Track B — `server/`.** `server/landing_recorder.py` (the buffer, the pump subscription, the
navdata resolution) and `server/landing_routes.py` + `WS /ws/landing` + one `include_router` line.
Owns `server/`, `tests/server/`. Depends on Track A's model module only — which is why §5 spells
the models out completely, so Track B can be written against this document.

**Track C — the panel.** `ui/src/features/landing/*`. Its non-API work (§10.1's status strip,
banners, print stylesheet; `grade.ts`/`format.ts`'s nullability) proceeds from this document
immediately; the `schema.d.ts` regeneration and the mock deletion wait for Track B, the sequencing
every prior manager has used.

**Track D — the X-Plane dataref spike.** `spikes/landing_datarefs.py`: confirm the four names of
§7.1 and measure the achievable `stream_state` rate (§13.1). **This one runs first and blocks
nothing else** — but Track 0's adapter half must not be written until it reports. It is the only
piece of this manager that needs a live simulator.

**The tester does not wait:** §11.2–§11.5 are written against this document before Track A exists.

**Never parallelised, restated:** Track 0's files; merges to `dev`/`main`; release tagging. No
navdata schema is touched by this manager.

---

## 13. Open questions and risks

### 13.1 The achievable sample rate is unmeasured — and everything rests on it

**The single biggest unknown in this design.** `XPlaneSimAdapter.get_aircraft_state()` issues nine
(soon thirteen) HTTP GETs per frame, and no one has measured how many frames per second that
sustains. If it is 20 Hz, §3 is simply true. If it is 6 Hz, D6's warning fires on every real
landing and the feature ships degraded until §3.3's batching or WebSocket-subscription work lands.

**What resolves it:** Track D's spike — consume `stream_state(0.05)` for 30 s against a live sim,
with and without Docker Desktop (issue #57), and report the achieved rate. Then, if needed, measure
the same with the nine reads batched into one request, and with the Web API's
`dataref_subscribe_values` subscription that `spikes/README.md:43` records an earlier spike
observing. All three are adapter-internal (§3.3); none changes anything in this document.

### 13.2 The four dataref names are candidates, not facts

§7.1 marks every one. The `normal_g` datum is the one most likely to bite: a dataref that reads 0
at rest is a *delta* from 1 g, and every `peak_g` in the project would be wrong by exactly one with
no test in CI able to see it — which is precisely why §6.5's
`test_normal_g_is_about_one_when_settled` exists and runs live.

### 13.3 A paused or accelerated simulator distorts the time axis

The recorder timestamps on arrival (§3.2). If the instructor pauses X-Plane mid-approach, or runs
it at 2×, `t_s` is wall-clock-monotonic while the aeroplane's own time is not, and every derivative
in the report is wrong for that interval. Not handled in this design. **What would resolve it:** a
sim-time or paused flag on `AircraftState` — a *fifth* contract field, which is not worth adding
speculatively — or a heuristic that drops frames identical to their predecessor. Recorded rather
than solved; the instructor pausing mid-flare is not the common case.

### 13.4 Every arming and flare threshold is a stated default, not a measured one

`ARM_MAX_AGL_FT = 1500`, `FLARE_VS_THRESHOLD_FPM = -200`, `ROLLOUT_STOP_KT = 35` and the rest are
round, plausible numbers chosen for a light trainer. They are almost certainly wrong for an
airliner and possibly wrong for a glider. **What resolves it:** the first real sessions, plus
`ApproachConfig` being an argument to every `core/` function so a per-airframe profile can be
supplied later without touching a single algorithm. The design makes the numbers tunable; it does
not claim they are right.

### 13.5 PDF is deferred, which is a deviation from the feature spec

D16 and §9.3. If the print path proves unsatisfactory in a real debrief — a poor print stylesheet
is easy to produce — the fallback is `reportlab` behind a measured bundle delta. Flagged as a
deviation, not buried.

### 13.6 Localizer geometry without an ILS is an approximation

§8.2's runway-end estimate is a stated substitute for an antenna the navdata does not have. It
overstates deviation close in. **What resolves it:** either a real siting offset (a localizer sits
~300 m beyond the stop end — *verify against a published diagram, not from memory*) or accepting
it; `RunwayContext.localizer_reference` means the report can always be re-read knowing which was
used. ICAO's course width is also set per runway (nominally 210 m at the threshold) rather than
fixed at 2.5°; `Ils.localizer_width_deg` exists for it and the X-Plane provider never fills it in.
Deriving the width from runway length is a possible refinement, deliberately not taken now.

### 13.7 Landings do not survive a restart

D15. Acceptable while a debrief happens minutes after the flight and export gives a durable copy.
If it becomes a complaint before manager 12 lands, a `LandingStore` mirroring
`core/profiles/store.py` — same atomic-write idiom, same per-OS path helper — is roughly a day's
work and needs no model change, because `LandingRecord` already serialises losslessly (§9.1).

### 13.8 The fan-out pump is untested under real load

§11.7 tests the pump against a stub. What a stub cannot show is the pump escalating to 20 Hz
against a real X-Plane while two tablets stream and a failure watcher runs. The
`sim-validator`'s job, once §13.1 has an answer.

---

## 14. Verification

```bash
pytest && ruff check . && ruff format --check . && mypy .
cd ui && npm run lint && npm run typecheck && npm test && npm run build
```

Then, against `OIS_ADAPTER=fake` with the Vite dev server: open the Landing tab → the status strip
reads *idle* → feed the fake a scripted approach (the §11.8 harness, exposed as a small dev script)
→ the strip goes *armed*, then *rollout*, then a new landing appears in the picker without a
refresh → the report shows sixteen numbers, the deviation chart is drawn, Export CSV downloads a
file that opens in a spreadsheet, Print debrief opens a print preview containing the charts. Then
the same with navdata disabled → the banner explains the six blanks, and nothing throws.

Live-sim validation (`pytest -m sim`, §11.10) is the `sim-validator` agent's job and is not a merge
gate — but §13.1's measurement should be taken **before** Track 0's adapter half is written, not
after.
