# Pushback Manager — design

**Status:** designed, not yet implemented.
**GitHub issue:** [#21](https://github.com/Santisoutoo/open-instructor-station/issues/21).
**Phase:** 3 — Instructor Map + AI Traffic ([`../roadmap.md`](../roadmap.md#phase-3--instructor-map--ai-traffic)). Roadmap's own characterisation: *"small, command-shaped, independent."*
**Feature spec:** manager 8 ([`../feature-spec.md`](../feature-spec.md#8-pushback-manager)), priority —.
**Depends on:** the Phase 0/1 contract (`core.sim_adapter`, `FakeSimAdapter`, the contract suite) and the **already-validated** reposition procedure in `adapters/xplane/xplane_adapter.py` (freeze → write local frame → write velocity/heading → release → `fix_all_systems`) — this manager reuses it rather than inventing a second one.
**Blocks:** nothing. Not consumed by the Scenario Generator (feature spec's manager-2 composition list is position + state + weather + failures + traffic; pushback is absent from it) and not referenced by Training Profiles' saved fields. Independent of the Instructor Map and AI Traffic tracks this phase also delivers.

The instructor pushes the aircraft back from the gate — straight, left or right, a configurable
distance and turn angle — from the tablet, without touching the sim. Two possible mechanisms are
named in the feature spec (a native tug command, or a computed reposition); this design picks a
concrete resolution of that choice rather than leaving it open, and states exactly why.

Binding rules live in [`../../CLAUDE.md`](../../CLAUDE.md); layers in
[`../architecture.md`](../architecture.md). The Failures Manager design
([`failures-manager.md`](failures-manager.md)) and the Weather Manager design
([`weather-manager.md`](weather-manager.md)) are this phase's house style; their staging
(`preview`/`apply`) and per-entry support-manifest conventions are reused here, not reinvented.

---

## 0. Decisions at a glance

| # | Decision | Where |
|---|---|---|
| D1 | **One `SimAdapter` method, `pushback()`, not two.** The feature spec's "command path where available, computed path as fallback" is resolved as an **adapter-internal** implementation choice, invisible at the interface: `can_pushback` means "this adapter can execute a pushback," full stop. Whether that happens via a native tug command or a computed teleport is nobody's business outside `adapters/xplane/` — exactly hard rule 2 and the reasoning `architecture.md` gives for why `core/` and the interface stay sim-agnostic. | §4, §5 |
| D2 | **Phase 3 ships the computed (geodesic) path for X-Plane, not a native tug command.** No X-Plane pushback-truck command name is verified in this design (unlike, say, `fix_all_systems`, which is already proven). Rather than guess a name the way the Failures design flagged low-confidence datarefs, this design commits to the path that is **already validated**: `pushback()` reuses `XPlaneSimAdapter.set_position()` verbatim. A native, animated tug is a follow-up spike (§10.1), not a blocker for `can_pushback = True`. | §5 |
| D3 | **The manoeuvre is described by `distance_m` (arc length) and `angle_deg` (total heading change), never a radius.** The feature spec names "configurable distance" and "configurable angle" only; a radius is *derived* (`radius_m = distance_m / angle_rad`), not a third input the instructor has to reason about. | §3, §6 |
| D4 | **The arc is a circular-arc chord construction, not iterative integration.** A circular arc's chord bisects the angle between its start and end tangents — a closed-form identity, computed with exactly one call to `core.geodesy.point_at_distance_and_bearing` for the endpoint and one more per point for the path preview. No new geodesy primitive, no numeric integration loop. | §6 |
| D5 | **`direction` describes where the NOSE ends up, not which way the tail swings.** "Push right" means the final heading is rotated clockwise from the current one; "push left" is counter-clockwise. Stated explicitly because the opposite convention (tail-swing) is equally defensible and getting it backwards is a confusing, non-dangerous bug — flagged, not left implicit (§10.2). | §3 |
| D6 | **`preview` reads `get_aircraft_state()` and is otherwise capability-free** — a deliberate divergence from the Position Manager's D2 ("preview... never reads the adapter either"). Pushback is a **relative** manoeuvre: without knowing where the aircraft is now and which way it points, there is no geometry to preview. `get_aircraft_state()` carries no capability gate on the protocol, so this stays as permissive as a preview can be. | §2 |
| D7 | **`apply` (here: `execute`) re-resolves from scratch, inside the adapter, not the route.** The adapter's `pushback()` re-reads `get_aircraft_state()` itself, immediately before writing — not the position `preview` read a moment earlier — because staleness matters more here than for an airport-anchored placement: the target is defined relative to *right now*. Preview and execute call the exact same pure function, `core.pushback.pushback_target()`, so they can only disagree if the aircraft moved between the two calls (untrue for a parked aircraft on a ramp). | §2, §4 |
| D8 | **A precondition, not a capability: `on_ground` is checked with a dedicated `PushbackNotOnGround` exception, mapped to `409`.** Pushing back an airborne aircraft is nonsensical but not a capability question — 501 would be the wrong signal (the adapter *can* pushback; this aircraft, right now, cannot be pushed). The check lives in `core/pushback.py` so both the route and every adapter enforce it identically (defence in depth, the same posture the Failures design uses for `CapabilityNotSupported`). | §2, §6 |
| D9 | **The request model lives in `core/pushback.py`, not the router** — the Position Manager's recorded regret, not repeated (failures-manager.md D9, weather-manager.md D6 apply the same lesson). | §3 |
| D10 | **The UI adds its endpoints with `injectEndpoints` from `pushbackApi.ts`**, never editing `instructorApi.ts` directly — the rule the Position panel broke and every manager since has kept. | §7 |

---

## 1. Scope

### 1.1 What this manager does

1. **A sim-agnostic pushback geometry function** in `core/` — straight or arced, from the
   aircraft's current position and heading, with no simulator involved.
2. **A preview** of the resulting position, heading and path, computed from live telemetry,
   requiring no capability.
3. **Execution** — write the resulting position and heading, gated behind `can_pushback`, refusing
   with a clear reason when the aircraft is airborne.
4. **The Pushback tab** of the Instructor Panel — three direction buttons, two sliders (distance,
   angle), a small path schematic, and a stage-then-execute flow matching the Position/Weather
   panels' house style.

Feature-spec coverage (manager 8): push left/right/straight; configurable distance; configurable
angle; command path where available, computed path as fallback, gated by a capability (D1/D2).

Roadmap Phase 3 exit criteria this manager touches: none directly name Pushback (they are Map/
Traffic criteria); it is delivered as one of the phase's two small, independent tracks (roadmap's
own wording) and does not gate the phase's exit.

### 1.2 What is explicitly out of scope

| Out of scope | Why / owner |
|---|---|
| An animated, native tug truck | D2. A genuine visual improvement, not a functional one from the instructor's seat — both mechanisms leave the aircraft in the same place, facing the same way. Tracked as a follow-up spike, §10.1. |
| Collision/obstacle awareness (pushing into a building, another aircraft) | Not modelled. The instructor is trusted the same way the Position Manager trusts a placement — no world geometry beyond the runway/navdata this manager does not even read. |
| Scenario Generator integration | Feature spec's manager-2 composition list does not include pushback (§0 header). Additive later if asked for; nothing here blocks it. |
| Multi-step / curved-then-straight compound manoeuvres | One request is one arc-or-straight segment. A second pushback call chains naturally (the next preview reads the post-first-pushback state) without any new model. |
| MSFS | Phase 5. SimConnect exposes no pushback primitive either; `can_pushback` is plausibly `False` initially, upgraded the same way weather/failures are expected to be (§10.3). |

---

## 2. REST endpoints

All under `/api/pushback/*`, in a new `server/pushback_routes.py`, registered from `server/app.py`
with one `include_router` line — the only shared-file backend edit, the Weather/Failures/Fuel-
Payload precedent.

```
GET  /api/pushback/manifest -> PushbackManifest
POST /api/pushback/preview  -> PushbackPreview
POST /api/pushback/execute  -> PushbackResult
```

| Method | Path | Purpose | Safe? | Capability | Notes |
|---|---|---|---|---|---|
| `GET` | `/manifest` | Capability + reason, and the exact `max_distance_m`/`max_angle_deg` bounds so the UI's sliders never hardcode a second copy of the `PushbackRequest` field constraints. Always 200. | yes | none | `def`, no adapter I/O |
| `POST` | `/preview` | Read current state, compute the target position/heading/path via `core.pushback.pushback_target()`. **Writes nothing.** | yes | none (D6) | `async def` — the one adapter call is `get_aircraft_state()`, which is ungated |
| `POST` | `/execute` | Re-resolve inside the adapter (D7), write, read back. | no | `can_pushback` → 501 | `async def` |

### 2.1 Capability and precondition gating

- Adapter does not declare `can_pushback` → **501**, *"Unavailable on this adapter — the 'xplane'
  adapter does not declare can_pushback, so it cannot push the aircraft back."* Applies to
  `/execute` only; `/preview` and `/manifest` are never gated.
- Aircraft is airborne (`core.pushback.PushbackNotOnGround`, raised by the adapter and/or the
  route) → **409**, *"Cannot push back — the aircraft is airborne."* Checked by the route before
  calling the adapter **and** inside every adapter's `pushback()` (D8, defence in depth).
- `CapabilityNotSupported` escaping the adapter anyway is caught and mapped to 501 — the same
  defence-in-depth line every sibling manager keeps.

### 2.2 Validation errors — 422

- `angle_deg != 0` with `direction="straight"`, or `angle_deg <= 0` with `direction` in
  `("left", "right")` — a `model_validator` on `PushbackRequest` (§3), so the same rule applies
  whether the request came from the panel or (later) a scenario step.
- `distance_m`/`angle_deg` outside their `Field` bounds.

### 2.3 Everything else

FastAPI's `{"detail": "<one sentence>"}`, matching the shipped convention.

---

## 3. Pydantic models

All in **`core/pushback.py`** (D9). Units: `_m` is metres (ground manoeuvres are short enough that
metres, not feet, is the natural unit — the same choice `CameraOffset` makes, §camera doc), `_deg`
is degrees. Request models are `frozen=True, extra="forbid"`; value models are `frozen=True`.

```python
PushbackDirection = Literal["straight", "left", "right"]

PUSHBACK_MAX_DISTANCE_M: float = 200.0
PUSHBACK_MAX_ANGLE_DEG: float = 180.0
PUSHBACK_PATH_PREVIEW_POINTS: int = 8  # + the origin = 9 points total


class PushbackRequest(BaseModel):
    """One pushback instruction. direction describes where the NOSE ends up (D5):
    'right' rotates the final heading clockwise from the current one, 'left'
    counter-clockwise. angle_deg is the TOTAL heading change over the manoeuvre,
    not a rate — 0 for 'straight', required (> 0) otherwise, because an angle of
    0 on 'left'/'right' would be indistinguishable from 'straight'."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    direction: PushbackDirection
    distance_m: float = Field(
        gt=0.0,
        le=PUSHBACK_MAX_DISTANCE_M,
        description="Arc length (or straight length) the aircraft's reference point travels, metres.",
    )
    angle_deg: float = Field(
        default=0.0,
        ge=0.0,
        le=PUSHBACK_MAX_ANGLE_DEG,
        description="Total heading change through the manoeuvre, degrees. Must be 0 for "
        "'straight', and > 0 for 'left'/'right'.",
    )

    @model_validator(mode="after")
    def _angle_matches_direction(self) -> "PushbackRequest":
        if self.direction == "straight" and self.angle_deg != 0.0:
            raise ValueError("angle_deg must be 0 when direction is 'straight'.")
        if self.direction != "straight" and self.angle_deg <= 0.0:
            raise ValueError(
                f"direction={self.direction!r} needs angle_deg > 0; 0 is indistinguishable "
                "from 'straight'."
            )
        return self


class PushbackTarget(BaseModel):
    """The resolved outcome of one PushbackRequest, from a given starting state."""

    model_config = ConfigDict(frozen=True)

    position: GeoPosition
    heading_deg: float = Field(ge=0.0, le=360.0)
    path_preview: tuple[GeoPosition, ...] = Field(
        description="PUSHBACK_PATH_PREVIEW_POINTS + 1 points along the manoeuvre, current "
        "position first and target last, for drawing the path. Collinear (2 distinct "
        "endpoints suffice) when direction is 'straight'."
    )


class PushbackPreview(BaseModel):
    model_config = ConfigDict(frozen=True)

    request: PushbackRequest
    current_position: GeoPosition
    current_heading_deg: float = Field(ge=0.0, le=360.0)
    target: PushbackTarget


class PushbackResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    request: PushbackRequest
    target: PushbackTarget  # what was asked for, computed fresh at write time (D7)
    state: (
        AircraftState  # read back after the write — the honest verdict, PlacementResult's posture
    )


class PushbackManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    adapter: str
    supported: bool
    reason: str | None
    max_distance_m: float = PUSHBACK_MAX_DISTANCE_M
    max_angle_deg: float = PUSHBACK_MAX_ANGLE_DEG


class PushbackNotOnGround(ValueError):
    """Raised by core.pushback.require_on_ground() when the aircraft is airborne."""
```

Worked example, hand-checkable (D5): aircraft heading 090° (east), `direction="right"`,
`distance_m=30`, `angle_deg=90` → **`target.heading_deg == 180.0`** exactly (090 + 90, no trig
needed for the heading). The position is a circular-arc chord problem: `radius_m = 30 / (π/2) ≈
19.10 m`, `chord_m = 2·radius_m·sin(45°) ≈ 27.01 m`, at a true bearing of `back_bearing (270°) +
angle_deg/2 (45°) = 315°` from the start (§6, §8.1 pin the exact formula and an independent
assertion of it).

---

## 4. `SimAdapter` / `Capabilities` additions

**This is a shared-foundation change. It is made once, alone, by one agent, before any dependent
work branches off it, and must not run concurrently with the Camera Manager's own contract change**
(§9) — both touch `core/sim_adapter.py`, `adapters/fake/fake_adapter.py` and
`tests/adapters/test_contract.py`.

**No new capability flag.** `can_pushback` already exists on `Capabilities` — added ahead of this
design, declared `True` on `FakeSimAdapter` and `False` on `XPlaneSimAdapter`, and listed
`PENDING` in `tests/adapters/test_contract.py`'s `CAPABILITY_COVERAGE`. This design's contract
work is exactly: add the method, add the Fake's behaviour, resolve the `PENDING` entry. One method
is added to the `SimAdapter` protocol:

```python
async def pushback(self, request: PushbackRequest) -> None:
    """Push the aircraft backward per `request`, from wherever it is right now.

    Re-reads position and heading itself (core.pushback.pushback_target(), the
    same pure function POST /api/pushback/preview calls) rather than trusting a
    target resolved earlier — a pushback is defined relative to the CURRENT
    state, and re-resolving at write time is what keeps a delayed request
    honest (the same lesson issue #39 taught set_position about speed decay).

    Raises core.pushback.PushbackNotOnGround if the aircraft is airborne.
    Requires Capabilities.can_pushback.
    """
    ...
```

### 4.1 What `FakeSimAdapter` must do

- Keep declaring `can_pushback=True` (it already does).
- `pushback(request)`: raise `CapabilityNotSupported` if the flag is `False`; call
  `core.pushback.require_on_ground(self._state)` (raises `PushbackNotOnGround` if airborne); call
  `core.pushback.pushback_target(self._state, request)`; update `latitude`/`longitude`/
  `heading_deg` from the result, and set `ias_kt=0.0`, `vertical_speed_fpm=0.0` (a pushed-back
  aircraft is stationary).
- **No physics, no animation** — the Fake's state *is* its observable behaviour, exactly the
  Failures design's ledger philosophy.

### 4.2 Contract tests to add — `tests/adapters/test_contract.py`

`CAPABILITY_COVERAGE["can_pushback"]` moves from `PENDING` to
`"test_pushback_moves_the_aircraft_backward"`.

| Test | Pins |
|---|---|
| `test_pushback_moves_the_aircraft_backward` | From a known on-ground state, `direction="straight", distance_m=20`: `distance_and_bearing(before, after)` ≈ `(20 m in NM, back_bearing)`; heading unchanged. |
| `test_pushback_arc_rotates_heading_by_the_full_angle` | `direction="right", angle_deg=45` → `after.heading_deg == (before.heading_deg + 45) % 360` (exact, D5's hand-checkable half). `direction="left"` subtracts. |
| `test_pushback_refuses_when_airborne` | An airborne fixture state → `PushbackNotOnGround`, aircraft unmoved. |
| `test_pushback_refuses_without_the_capability` | A `FakeSimAdapter` subclass declaring `can_pushback=False` → `CapabilityNotSupported`. |
| `test_pushback_is_idempotent_in_direction_only` | Two identical requests move the aircraft twice by the same increment (not idempotent as a *state* — it is a relative command, like a throttle nudge — but each call is deterministic given its starting state). |

Live-only tolerance: reuse `POSITION_TOLERANCE_M`'s reasoning — a small
`PUSHBACK_TOLERANCE_M = {"fake": 0.1, "xplane": 5.0}` (tighter than the general position tolerance
because the manoeuvre itself is short and there is no re-acceleration to absorb).

---

## 5. Dataref mapping (X-Plane)

**This section describes `adapters/xplane/` only. No dataref name appears in `core/`.**

### 5.1 The chosen path (D2)

`XPlaneSimAdapter.pushback()`:

1. `state = await self.get_aircraft_state()`
2. `core.pushback.require_on_ground(state)`
3. `target = core.pushback.pushback_target(state, request)`
4. `await self.set_position(target.position, target.heading_deg, ias_kt=0.0, vertical_speed_fpm=0.0)`

Step 4 is the **already-validated** procedure from `architecture.md`'s "known technical risk #1":
freeze the flight model, write the local frame, write a (now zero) velocity vector and heading,
release, `fix_all_systems`. Nothing new is written to X-Plane by this manager — the entire
dataref surface it touches is the one `set_position` already uses.

### 5.2 The one real cross-manager interaction, restated

`fix_all_systems` (step 5 of `set_position`) repairs every active failure — exactly the
interaction `failures-manager.md` §5.5 already flags for *any* reposition, pushback included.
Nothing new here; the same recommendation (snapshot-and-reassert inside `set_position`) covers
this manager automatically once it lands, with no pushback-specific work.

### 5.3 The native tug (follow-up spike, not blocking)

If a future spike identifies a real X-Plane pushback/tow command, `pushback()` can try it first
and fall back to step 4 above on failure — an adapter-internal change with **zero interface
impact**, because `can_pushback` already means "pushback works," not "pushback is animated."
Tracked at §10.1.

### 5.4 MSFS (Phase 5 target)

SimConnect has no first-class pushback primitive either. The same computed-fallback strategy
(reuse whatever the MSFS adapter's own `set_position` equivalent turns out to be) is expected to
transfer unchanged — `can_pushback=True` is plausible from day one there, unlike weather/failures.

---

## 6. `core/` logic

One new module, fully unit-testable with no simulator, no adapter, no clock.

### `core/pushback.py`

Everything in §3, plus:

```python
def require_on_ground(state: AircraftState) -> None:
    """Raise PushbackNotOnGround if state.on_ground is False."""


def pushback_target(
    state: AircraftState,
    request: PushbackRequest,
    *,
    preview_points: int = PUSHBACK_PATH_PREVIEW_POINTS,
) -> PushbackTarget:
    """Resolve request into a PushbackTarget from state's current position/heading.

    Geometry (D3/D4): the aircraft's reference point follows a circular arc (or
    a straight line when angle_deg == 0) of radius `distance_m / radians(angle_deg)`,
    swept through angle_deg in the requested direction, starting tangent to the
    reciprocal of the current heading (state.heading_deg + 180).

    A circular arc's chord bisects the angle between its start and end
    tangents — the standard identity this function uses instead of numeric
    integration: chord_m = 2 * radius_m * sin(angle_rad / 2), at a bearing of
    back_bearing_deg + signed_angle_deg / 2 from the origin. Applying it at a
    fraction of the full angle for i in 0..preview_points produces the path
    preview on the SAME circle.

    direction='straight' is angle_deg == 0's degenerate case: chord == distance_m,
    bearing == back_bearing_deg, heading unchanged.
    """
```

The signed angle: `direction="right"` → `+angle_deg`; `"left"` → `-angle_deg`; `"straight"` →
`0.0` (D5). Final heading = `(state.heading_deg + signed_angle_deg) % 360`. Uses
`core.geodesy.point_at_distance_and_bearing` exclusively for every point — no ellipsoid maths of
its own, matching the project's "geodesy lives in one place" convention.

---

## 7. UI panel outline

`ui/src/features/pushback/` — a new tab of the Instructor Panel. Adding it adds files; per D10 it
does not edit `instructorApi.ts`. Built ahead of the backend against hand-typed mocks — the
established pattern already used by `features/weather`, `features/failures`, `features/traffic`:
a `types.mock.ts`/`mock.ts` pair that "dies at backend integration" (their own phrasing), replaced
by `ui/src/api/schema.d.ts` once the router regenerates the OpenAPI schema.

### 7.1 Components

| File | Role |
|---|---|
| `PushbackPanel.tsx` | The tab: gate → direction/distance/angle controls → path schematic → stage-then-execute bar, the Position/Weather house pattern. |
| `PushbackControls.tsx` | Three direction buttons (straight/left/right, large touch targets), a distance slider (0–`max_distance_m` from the manifest) and an angle slider (0–`max_angle_deg`, disabled and reset to 0 when direction is "straight"). |
| `PathPreview.tsx` | A small SVG schematic (Position Manager's D16 precedent: "a schematic, not a map" — no MapLibre dependency here either), drawing `target.path_preview` as a polyline with the aircraft's current heading arrow at the start and the resulting heading arrow at the end. |
| `gate.ts` | `pushbackGate(capabilities, isError)` — fail-closed, the established pattern verbatim: closed while loading, closed on error, closed without `can_pushback`. |
| `mock.ts`, `types.mock.ts` | Deterministic geometry mirroring `core.pushback.pushback_target()`'s formulas — same reasoning as `weather/mock.ts`'s note that "dies at backend integration." |
| `pushbackSlice.ts`, `pushbackApi.ts` | Below. |

Tablet-first: direction buttons ≥ 44 px, sliders with numeric readouts (instructors trust a
number over a slider position at a glance), the whole flow reachable in the two-tap budget the
feature spec sets for the most-used actions — here, "straight push, 20 m" is one tap (a default)
plus one confirm.

### 7.2 State — one RTK slice + injected endpoints

`pushbackApi.ts` uses `instructorApi.injectEndpoints` with tag `PushbackState`:

- `getPushbackManifest` (query, cached for the session),
- `previewPushback` (query despite being a `POST` — side-effect-free, keyed on the staged
  `PushbackRequest`, the `previewPlacement`/`previewWeather` precedent),
- `executePushback` (mutation, invalidates nothing server-side — there is no persisted pushback
  state to invalidate, only the live telemetry stream, which is a separate WebSocket concern).

`pushbackSlice.ts` holds **client state only**:

```ts
interface PushbackState {
  direction: PushbackDirection;
  distanceM: number;
  angleDeg: number;
}
```

All API types come from the regenerated `ui/src/api/schema.d.ts` once the backend lands;
`PushbackDirection` arrives as a closed union from the OpenAPI schema.

### 7.3 Capability gating, restated

Tab-level only: `can_pushback` via `pushbackGate`. There is no per-entry manifest to gate against
beyond that one flag (unlike Failures/Camera) — `distance_m`/`angle_deg` bounds are UI validation
against the manifest's echoed constants, not a capability question.

---

## 8. Test plan

Everything except §8.3 runs in CI against `FakeSimAdapter`. No navdata, no simulator-derived
fixtures — hand-built `AircraftState` frames only.

### 8.1 `core/` unit tests — `tests/core/test_pushback.py`

Concrete reference values, all asserted:

- **Straight:** origin at (40.0, -3.0), heading 090°, `distance_m=20` → `distance_and_bearing`
  from origin to `target.position` is `(20 / 1852 NM, 270°)` within 1 mm; `target.heading_deg ==
  90.0` exactly.
- **Right arc (the worked example, §3):** heading 090°, `direction="right", distance_m=30,
  angle_deg=90` → `target.heading_deg == 180.0` exactly (the hand-checkable half); chord distance
  `== 2 * (30 / (pi/2)) * sin(pi/4)` metres (computed independently, via `math`, in the test —
  ≈ 27.0095 m) at true bearing `315.0°` from the origin, both within 1 mm / 0.01°.
- **Left arc**, same inputs but `direction="left"` → `target.heading_deg == 0.0` (090 − 90),
  chord bearing `225°` (270 − 45).
- **`angle_deg=180` (a U-turn):** `target.heading_deg == (start + 180) % 360`; `radius_m ==
  distance_m / pi` exactly.
- `path_preview[0]` equals the origin within 1 mm; `path_preview[-1]` equals `target.position`
  exactly; `len(path_preview) == PUSHBACK_PATH_PREVIEW_POINTS + 1`; every intermediate point lies
  on the same circle (distance from the arc's centre is constant within 1 mm) for an arc case, and
  is collinear for the straight case.
- `require_on_ground`: an airborne state raises `PushbackNotOnGround`; an on-ground state does
  not raise.
- `PushbackRequest` validation: `direction="straight", angle_deg=5` → `ValidationError`;
  `direction="left", angle_deg=0` → `ValidationError`; `direction="right", angle_deg=45` → valid.

### 8.2 Contract tests

The suite of §4.2, parametrised over both adapters, written by the tester from this document
before the implementation exists.

### 8.3 `@pytest.mark.sim` — `tests/sim/test_live_pushback.py` (never in CI)

What only a live X-Plane proves, restoring position in a `finally`:

- `pushback(direction="straight", distance_m=15)` from a parked, on-ground aircraft →
  `get_aircraft_state()` afterward is within `PUSHBACK_TOLERANCE_M["xplane"]` of the computed
  target and the heading is unchanged.
- `pushback(direction="right", angle_deg=60, distance_m=25)` → heading rotated by 60° within
  1° (the same live tolerance the autopilot heading tests already use), position within tolerance.
- **On-ground precondition, live:** if the loaded aircraft is not already parked, the test uses
  the already-validated `set_position` to place it at a ground-elevation point with `ias_kt=0`
  first, then asserts `get_aircraft_state().on_ground is True` before proceeding — skipping with a
  clear reason if it is not (a live-only wrinkle, stated rather than silently retried forever).
- The §5.2 interaction (a failure survives / does not survive a pushback) is **not** re-tested
  here — it is `failures-manager.md`'s §8.4 test, and pushback needs no manoeuvre-specific variant
  of it.

### 8.4 Server tests — `tests/server/test_pushback_routes.py`

Against `TestClient` + `FakeSimAdapter`, `reset_adapter()` between tests:

- `/manifest` reports `supported=True` and the exact `PUSHBACK_MAX_DISTANCE_M`/
  `PUSHBACK_MAX_ANGLE_DEG` constants.
- `/preview` against a parked fake aircraft returns geometry matching §8.1's straight/arc cases,
  and needs no capability (a subclassed fake with `can_pushback=False` still answers `/preview`).
- `/execute` moves the fake's state and returns `PushbackResult.state` matching the preview's
  target.
- `/execute` against an airborne fake → 409 with the stated sentence.
- `/execute` against `can_pushback=False` → 501.
- 422: `angle_deg`/`direction` mismatch, out-of-bound `distance_m`.

### 8.5 UI tests (vitest)

- `gate.test.ts` — fail-closed on loading, error, missing flag.
- `mock.test.ts` — the mock's geometry matches `core.pushback`'s formulas on the same worked
  example (§3), so the pre-backend UI is not silently wrong.
- `PushbackControls.test.tsx` — angle slider disables and resets to 0 when direction switches to
  "straight"; the staged request sent to `previewPushback` is asserted with `toEqual` against a
  stubbed fetch (no field silently defaults, the Position/Failures panels' recorded discipline).
- `PathPreview.test.tsx` — renders the exact number of points the mock/preview returns.

---

## 9. Parallelisation

### 9.1 Across Phase 3

Pushback is one of the phase's two small, independent tracks (with Camera), each its own branch
in its own **git worktree**, its own PR to `dev`; CI is the integration barrier. **Both need a
contract change, and contract changes are never parallelised** — the §4 additions to
`core/sim_adapter.py`, `adapters/fake/fake_adapter.py` and `tests/adapters/test_contract.py` must
land serially with respect to Camera's equivalents (and, if concurrent, the Map/Traffic track's
`can_spawn_traffic` work, per the roadmap's own phase table). Practical sequencing: whichever of
Pushback/Camera's foundation commit lands first on `dev`, the other rebases onto it before adding
its own method.

### 9.2 Inside this manager

**Track 0 — the foundation (serialised, first, one agent):** `core/pushback.py`, the §4 protocol
method, `FakeSimAdapter`, the §4.2 contract tests.
Owns: `core/pushback.py`, `core/sim_adapter.py`, `adapters/fake/`, `tests/adapters/test_contract.py`, `tests/core/test_pushback.py`.

Then two tracks, dispatched **in one message**, disjoint directories:

**Track A — backend:** `server/pushback_routes.py` + the router registration line in
`server/app.py`, `tests/server/test_pushback_routes.py`.
Owns: `server/`, `tests/server/`.

**Track B — X-Plane mapping:** the `pushback()` implementation in `adapters/xplane/xplane_adapter.py`
(§5.1 — no new dataref, no new module needed), `tests/sim/test_live_pushback.py`.
Owns: `adapters/xplane/`, `tests/sim/`.

**Track C — the panel:** `ui/src/features/pushback/*` and the `pushbackApi.ts` injection.
Its pure logic (`gate.ts`, `mock.ts`, the slice) proceeds from this document alone, in parallel
with Track A/B; the RTK Query wiring against a real schema waits for Track A's regen, the same
sequencing every prior manager has used.

**The tester does not wait:** §8.1/§8.2's tests are written against this document before any
implementation exists.

**Never parallelised, restated:** Track 0's files; merges to `dev`/`main`; release tagging. No
navdata schema is touched by this manager.

---

## 10. Open questions and risks

### 10.1 A native tug command would make this an animation, not just a jump

Not researched in this design — no dataref/command name here is claimed as verified (D2's whole
point). **What resolves it:** a small spike, `spikes/pushback_commands.py`, dumping X-Plane's
command list for anything under `sim/ground_ops`/`sim/operation` that looks pushback-shaped, and
trying one against a live sim. Purely additive if found: `pushback()` tries it first, falls back
to §5.1 on failure or absence, and `can_pushback` does not change either way.

### 10.2 The left/right convention (D5) needs a first usability pass

"Push right rotates the nose clockwise" is this design's stated choice, not a verified instructor
expectation. **What resolves it:** the `sim-validator`/first manual session; if instructors
consistently read it backwards, flipping the sign in `core.pushback.pushback_target` is a one-line
change with no model/interface impact — the field is still called `direction`, still
`"left"|"right"|"straight"`.

### 10.3 MSFS's pushback surface is unresearched

Flagged in §5.4 as "plausible," not measured. Phase 5's problem, and the fallback-to-computed
design means it is very likely a small one — the same `set_position`-equivalent reuse strategy
this manager already uses for X-Plane.

### 10.4 `distance_m`/`angle_deg` upper bounds are arbitrary sanity limits

200 m and 180° are generous, round numbers, not derived from any tug's real operating envelope.
Cheap to tighten later if an instructor session shows they should be; not worth guessing more
precisely now.

---

## 11. Verification

```bash
pytest && ruff check . && ruff format --check . && mypy .
cd ui && npm run lint && npm run typecheck && npm test && npm run build
```

Then, against `OIS_ADAPTER=fake` with the Vite dev server: open the Pushback tab → stage a
straight 20 m push → preview draws a two-point line behind the aircraft → Execute → the fake's
aircraft (visible on the telemetry panel) has moved backward, heading unchanged → stage a 90°
right arc → preview draws a curved path → Execute → heading rotated by exactly 90°, plus a console
check. Live-sim validation (`pytest -m sim`, §8.3) is the `sim-validator` agent's job and is not a
merge gate.
