# Camera Manager — design

**Status:** designed, not yet implemented.
**GitHub issue:** [#22](https://github.com/Santisoutoo/open-instructor-station/issues/22).
**Phase:** 3 — Instructor Map + AI Traffic ([`../roadmap.md`](../roadmap.md#phase-3--instructor-map--ai-traffic)). Roadmap's own characterisation: *"small, command-shaped, independent."*
**Feature spec:** manager 10 ([`../feature-spec.md`](../feature-spec.md#10-camera-manager)), priority —.
**Depends on:** the Phase 0/1 contract (`core.sim_adapter`, `FakeSimAdapter`, the contract suite). **Loosely related to, but explicitly not dependent on,** Training Profiles (manager 14, `docs/designs/training-profiles.md`) — the feature spec names it as the eventual persistence home for custom camera positions; this design does not wait for it (§1.2, §10.1).
**Blocks:** nothing. Independent of the Instructor Map and AI Traffic tracks this phase also delivers, and of the Pushback Manager (`pushback-manager.md`), this phase's other small track.

Switch the simulator's view — cockpit, tower, chase, wing, drone/free — from the tablet, and save
a named custom camera position to recall later. Almost entirely command-shaped, as the feature
spec says, with one genuine open question this design does not paper over: whether the X-Plane
Web API can reach the external camera's position at all without the optional in-sim bridge.

Binding rules live in [`../../CLAUDE.md`](../../CLAUDE.md); layers in
[`../architecture.md`](../architecture.md). The Failures Manager design
([`failures-manager.md`](failures-manager.md)) is this design's closest relative: a small, fixed
catalogue of ids, a per-entry adapter support manifest (its D4), and "no is an answer, never an
exception" reads. Where Training Profiles ([`training-profiles.md`](training-profiles.md)) already
solved "a small directory of JSON files in the user's app-data folder" (its D2/D5), this design
reuses that *pattern* rather than that *code*, and says exactly why (§10.1).

---

## 0. Decisions at a glance

| # | Decision | Where |
|---|---|---|
| D1 | **A closed five-view catalogue** (`cockpit`, `chase`, `tower`, `wing`, `drone`), mirroring `FailureId`'s `Literal` + tuple-catalogue shape, not `AircraftControlId`'s flatter list — because, exactly like failures, per-view adapter support genuinely varies and needs a reason, not just a bool. | §3.1 |
| D2 | **A per-view `CameraSupportManifest`, not a bigger `Capabilities` flag set.** `can_control_camera` (already declared, see §4) gates the group; which named views actually work on this install is the manifest's job — failures-manager.md's D4 argument transplanted whole: a flag per view would only ever grow, never shrink. | §3.1, §4 |
| D3 | **Custom saved positions are a separate sub-capability inside the same manifest, `custom_positions_supported: bool`,** not a second top-level `Capabilities` flag. The named views (fired by command) and free positioning (written as a pose) are plausibly different reliability tiers on the same adapter — see D7's honest uncertainty — and a manifest field carries that distinction without contract bloat. | §3.1, §4, §10.2 |
| D4 | **A saved position is stored as an *aircraft-relative* offset — forward/right/up metres plus a look-direction offset — never a world-frame coordinate.** Feature spec: "offsets relative to the aircraft." Recalling one always resolves fresh against the aircraft's CURRENT position and heading (the same "re-resolve at write time" posture the Pushback Manager's D7 uses), so a saved "three-quarter view from the left" stays that view as the aircraft moves between sessions, rather than pointing at a fixed patch of sky. | §3.2, §6 |
| D5 | **Camera pitch is world-frame (positive = looking toward the sky), the look-direction offset is aircraft-heading-relative.** Mixing conventions on purpose: an instructor's mental model of "look up/down" is independent of the aircraft's own attitude, but "look left/right" is naturally relative to which way the nose points. Stated explicitly because either axis could defensibly go either way. | §3.2 |
| D6 | **No read of the *current* named view.** `AircraftState` carries nothing camera-related, and X-Plane's own view-type dataref does not map cleanly onto this catalogue (a user-orbited camera has no honest catalogue id). The panel optimistically highlights the last view it requested — client state, never reconciled against a server read — rather than inventing a lossy mapping. | §4, §7 |
| D7 | **The X-Plane adapter's confidence in named-view commands and in offset writes is NOT the same, and the design says so rather than guessing one dataref/command set for both.** Named views are very likely reachable by firing a command (the same mechanism `fix_all_systems` already proves works over the Web API). Free camera *positioning* may need `XPLMCameraControl`, an SDK-only surface the Web API may not expose — i.e. it may need the optional `bridge/` plugin, the same pattern `can_spawn_traffic` already established. Flagged as the design's central open question (§10.2), not resolved by assertion. | §5, §10.2 |
| D8 | **Saved positions persist to a small JSON file store**, following Training Profiles' own D2/D5 (hand-rolled app-data directory, one file per record, no SQLite) but as an **independent module**, `core/camera/store.py` — not an import of Training Profiles' storage layer, which does not exist yet and which this manager must not block on (`CLAUDE.md`'s parallelisation policy: independent managers, disjoint directories). | §6, §10.1 |
| D9 | **`POST /api/camera/positions` (save) requires a live, resolvable current offset — 409 if there isn't one**, e.g. the adapter cannot currently read a free-camera pose. The same "state precondition, not a capability" posture the Pushback Manager's D8 uses for `PushbackNotOnGround`. | §2 |
| D10 | **The UI adds its endpoints with `injectEndpoints` from `cameraApi.ts`**, never editing `instructorApi.ts` directly. | §7 |

---

## 1. Scope

### 1.1 What this manager does

1. **A sim-agnostic camera-view catalogue** in `core/` — the five named views, with a per-view
   adapter support manifest.
2. **Named-view switching** — one command, one view, momentary (no staging, mirroring the
   Failures panel's D13: this *is* the product, one tap).
3. **Custom saved positions** — save the current free/drone camera pose under a name, list them,
   recall one (resolved fresh against the live aircraft state), delete one.
4. **The Camera tab** of the Instructor Panel — a view grid and a saved-positions list, disabled
   per-entry with a stated reason on adapters that cannot reach them.

Feature-spec coverage (manager 10): cockpit, drone/free, tower, wing, chase, custom saved
positions (stored as aircraft-relative offsets).

Roadmap Phase 3 exit criteria: none directly name Camera; delivered as one of the phase's two
small, independent tracks.

### 1.2 What is explicitly out of scope

| Out of scope | Why / owner |
|---|---|
| Integration with Training Profiles' storage | D8. Manager 14's own scope list (`training-profiles.md` §1.2) does not mention cameras either; a later join (saved positions becoming part of a profile) is additive to both, not designed here (§10.1). |
| A live camera feed / picture-in-picture in the instructor UI | Not asked for by the feature spec — this manager commands the *simulator's own* view, it does not stream video. |
| Smooth transitions/animation between views | Command-shaped, momentary, exactly the roadmap's characterisation. An instant cut is the baseline; easing is a rendering-layer concern this design does not touch. |
| Per-aircraft camera presets (a jet's "wing view" vs a glider's) | The five ids are generic; per-aircraft framing differences are the adapter's problem when it resolves a view id to a command, not a catalogue concern. |
| MSFS | Phase 5. SimConnect's camera system (`CAMERA STATE`, `CAMERA_SET_RELATIVE_POSITION`) is comparatively well documented — `can_control_camera=True` is plausible there sooner than weather/failures, noted at §10.3, not designed. |

---

## 2. REST endpoints

All under `/api/camera/*`, in a new `server/camera_routes.py`, registered from `server/app.py`
with one `include_router` line.

```
GET    /api/camera/manifest              -> CameraManifest
POST   /api/camera/view                  -> CameraCommandResult
GET    /api/camera/positions             -> list[SavedCameraPosition]
POST   /api/camera/positions             -> SavedCameraPosition
POST   /api/camera/positions/{id}/apply  -> CameraCommandResult
DELETE /api/camera/positions/{id}        -> 204 No Content
```

| Method | Path | Purpose | Safe? | Capability |
|---|---|---|---|---|
| `GET` | `/manifest` | Per-view support + `custom_positions_supported`, always 200. | yes | none |
| `POST` | `/view` | Switch to a named view now. Idempotent (setting the same view twice is a no-op outcome). | no | `can_control_camera` → 501; unsupported `view_id` → 501 with the manifest's own reason |
| `GET` | `/positions` | Every saved position, in creation order. | yes | none |
| `POST` | `/positions` | Read the current camera offset and save it under a name. | no | `can_control_camera` → 501; `custom_positions_supported=False` → 501; no resolvable current offset → **409** (D9) |
| `POST` | `/positions/{id}/apply` | Recall a saved position, resolved fresh against live state (D4). | no | same as `/positions`; unknown id → 404 |
| `DELETE` | `/positions/{id}` | Remove a saved position. | no | none — this is local storage, not a simulator write; unknown id → 404 |

### 2.1 Capability and precondition gating

- `/view`, `/positions` (POST), `/positions/{id}/apply` without `can_control_camera` → **501**,
  *"Unavailable on this adapter — the 'xplane' adapter does not declare can_control_camera, so it
  cannot control the camera."*
- `/positions` (POST), `/positions/{id}/apply` without `custom_positions_supported` → **501**,
  the manifest's own `custom_positions_reason` sentence.
- `/positions` (POST) when `get_camera_offset()` returns `None` → **409**, *"Cannot save a camera
  position right now — switch to the drone/free camera first."*
- `/positions/{id}/apply`, `DELETE /positions/{id}` on an unknown id → **404**.
- `CapabilityNotSupported` escaping the adapter anyway → 501, defence in depth.

### 2.2 Validation errors — 422

- Unknown `view_id` — free, from the closed `CameraViewId` `Literal`.
- `name` empty or over 60 characters on `POST /positions`.
- `CameraOffset` field values outside their `Field` bounds.

### 2.3 Everything else

FastAPI's `{"detail": "<one sentence>"}`.

---

## 3. Pydantic models

### 3.1 The catalogue — `core/camera/models.py`

```python
CameraViewId = Literal["cockpit", "chase", "tower", "wing", "drone"]


class CameraViewSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    view_id: CameraViewId
    label: str
    description: str


CAMERA_VIEW_CATALOGUE: tuple[CameraViewSpec, ...] = (
    CameraViewSpec(
        view_id="cockpit", label="Cockpit", description="The pilot's own forward-facing view."
    ),
    CameraViewSpec(
        view_id="chase", label="Chase", description="Follows the aircraft from behind and above."
    ),
    CameraViewSpec(
        view_id="tower",
        label="Tower",
        description="Fixed view from the nearest airport tower, when the scenery has one.",
    ),
    CameraViewSpec(
        view_id="wing", label="Wing", description="Mounted on the wing, looking along the fuselage."
    ),
    CameraViewSpec(
        view_id="drone",
        label="Drone / free",
        description="Freely positionable external camera — the base for custom saved positions.",
    ),
)
CAMERA_VIEW_IDS: tuple[CameraViewId, ...] = get_args(CameraViewId)


class CameraViewSupport(BaseModel):
    model_config = ConfigDict(frozen=True)

    view_id: CameraViewId
    supported: bool
    reason: str | None = None


class CameraSupportManifest(BaseModel):
    """What get_camera_support() answers."""

    model_config = ConfigDict(frozen=True)

    caveat: str | None = None
    views: tuple[CameraViewSupport, ...]  # exactly one per CAMERA_VIEW_IDS, catalogue order
    custom_positions_supported: bool
    custom_positions_reason: str | None = None
```

### 3.2 Offsets and requests — `core/camera/models.py`

```python
class CameraOffset(BaseModel):
    """A free/drone camera pose, expressed relative to the aircraft's own
    reference point and CURRENT heading (D4) — never a world-frame coordinate.
    Recalling a saved offset resolves it fresh every time (core.camera.geometry).
    """

    model_config = ConfigDict(frozen=True)

    forward_m: float = Field(
        ge=-500.0,
        le=500.0,
        description="Metres forward of the aircraft's reference point, along its current "
        "heading. Negative is aft.",
    )
    right_m: float = Field(
        ge=-500.0,
        le=500.0,
        description="Metres to the right of the reference point, perpendicular to the "
        "aircraft's current heading. Negative is left.",
    )
    up_m: float = Field(ge=-500.0, le=500.0, description="Metres above the reference point.")
    look_offset_deg: float = Field(
        ge=-180.0,
        le=180.0,
        description="Camera yaw relative to the aircraft's CURRENT heading (D5). 0 = looking "
        "the same way the aircraft points; +90 = looking to the right of the nose.",
    )
    pitch_deg: float = Field(
        ge=-90.0,
        le=90.0,
        description="Camera pitch, WORLD frame (D5), positive looking up toward the sky — "
        "independent of the aircraft's own pitch attitude.",
    )
    zoom_ratio: float = Field(
        default=1.0,
        gt=0.0,
        le=10.0,
        description="Field-of-view zoom multiplier; 1.0 is the adapter's default FOV.",
    )


class CameraPose(BaseModel):
    """An absolute, world-frame camera pose — what CameraOffset resolves to."""

    model_config = ConfigDict(frozen=True)

    position: GeoPosition
    heading_deg: float = Field(ge=0.0, le=360.0)
    pitch_deg: float = Field(ge=-90.0, le=90.0)
    zoom_ratio: float = Field(gt=0.0, le=10.0)


class CameraViewRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    view_id: CameraViewId


class SaveCameraPositionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str = Field(min_length=1, max_length=60)


class SavedCameraPosition(BaseModel):
    model_config = ConfigDict(frozen=True)

    position_id: str = Field(description="Server-assigned opaque id (uuid4 hex).")
    name: str
    offset: CameraOffset
    created_at: datetime  # UTC


class CameraCommandResult(BaseModel):
    """What /view and /positions/{id}/apply answer — an echo, not a read-back
    (D6: there is nothing honest to read back into)."""

    model_config = ConfigDict(frozen=True)

    view_id: CameraViewId | None = None
    offset: CameraOffset | None = None


class CameraManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    adapter: str
    caveat: str | None
    views: tuple[CameraViewSupport, ...]
    custom_positions_supported: bool
    custom_positions_reason: str | None
```

Worked example (D4/D5, hand-checkable): aircraft at heading 090°, `forward_m=50, right_m=0,
up_m=20, look_offset_deg=0, pitch_deg=0` → the resolved `CameraPose.position` is 50 m from the
aircraft at true bearing 090°, altitude `+ 20 / 0.3048 ≈ +65.6 ft`; `CameraPose.heading_deg ==
90.0` exactly (090 + 0).

---

## 4. `SimAdapter` / `Capabilities` additions

**This is a shared-foundation change. It is made once, alone, by one agent, before any dependent
work branches off it, and must not run concurrently with the Pushback Manager's own contract
change** (§9) — both touch `core/sim_adapter.py`, `adapters/fake/fake_adapter.py` and
`tests/adapters/test_contract.py`.

**No new capability flag.** `can_control_camera` already exists — declared `True` on
`FakeSimAdapter`, `False` on `XPlaneSimAdapter`, `PENDING` in `CAPABILITY_COVERAGE`. Four methods
are added to the `SimAdapter` protocol:

```python
async def get_camera_support(self) -> CameraSupportManifest:
    """Which views and which sub-features this adapter can reach, one entry per
    CAMERA_VIEW_IDS in catalogue order, plus custom_positions_supported. A
    capability-free read: an adapter without can_control_camera returns every
    view unsupported and custom_positions_supported=False, both with a stated
    reason — 'no' is an answer, never an exception."""


async def set_camera_view(self, view_id: CameraViewId) -> None:
    """Switch to the named view now. Requires can_control_camera; a view_id the
    manifest reports unsupported raises CapabilityNotSupported."""


async def get_camera_offset(self) -> CameraOffset | None:
    """The current free/drone camera pose, resolved against the current
    aircraft state, or None when there is nothing meaningful to report — not
    currently in a free-camera view, or the adapter cannot read one. A
    capability-free read, the get_airframe() posture: unknown is honest."""


async def set_camera_offset(self, offset: CameraOffset) -> None:
    """Position the free/drone camera at `offset`, resolved against the
    CURRENT aircraft state at write time (D4) — the same re-resolve-fresh
    posture core.pushback.pushback_target() uses. Requires can_control_camera
    AND the manifest's custom_positions_supported; raises
    CapabilityNotSupported otherwise."""
```

### 4.1 What `FakeSimAdapter` must do

- Keep declaring `can_control_camera=True`.
- `get_camera_support()`: every view `supported=True, reason=None`,
  `custom_positions_supported=True, custom_positions_reason=None`, `caveat=None`.
- Hold `self._camera_view: CameraViewId | None = None` and
  `self._camera_offset: CameraOffset | None = None`.
- `set_camera_view(view_id)`: `self._camera_view = view_id`; `self._camera_offset = None` —
  switching to any named view (including re-selecting "drone" without an explicit offset) clears
  the last free-camera pose, because the view alone does not imply one.
- `get_camera_offset()`: returns `self._camera_offset` verbatim (already `None` unless
  `set_camera_offset` ran more recently than any `set_camera_view` call).
- `set_camera_offset(offset)`: `self._camera_offset = offset`; `self._camera_view = "drone"`.
- **No rendering, no physics** — the Fake's state is its observable behaviour.

### 4.2 Contract tests to add — `tests/adapters/test_contract.py`

`CAPABILITY_COVERAGE["can_control_camera"]` moves from `PENDING` to
`"test_set_camera_view_is_accepted_for_every_supported_view"`.

| Test | Pins |
|---|---|
| `test_camera_support_covers_the_whole_catalogue` | `get_camera_support()` returns exactly one entry per `CAMERA_VIEW_IDS`, in order; every unsupported entry carries a non-empty `reason`. |
| `test_set_camera_view_is_accepted_for_every_supported_view` | For each `view_id` the manifest reports `supported=True`, `set_camera_view(view_id)` does not raise. |
| `test_camera_offset_round_trips` | `set_camera_offset(offset)` → `get_camera_offset()` returns it within `CAMERA_OFFSET_TOLERANCE`. Only run when the manifest's `custom_positions_supported` is `True`. |
| `test_switching_view_clears_the_offset_read` | `set_camera_offset(...)` then `set_camera_view("cockpit")` → `get_camera_offset()` returns `None`. |
| `test_camera_methods_refuse_without_the_capability` | A `FakeSimAdapter` subclass declaring `can_control_camera=False`: `set_camera_view`/`set_camera_offset` raise `CapabilityNotSupported`; `get_camera_support` reports every view unsupported and `custom_positions_supported=False`; `get_camera_offset` returns `None`. |
| `test_offset_methods_refuse_without_custom_positions_support` | A subclass with `can_control_camera=True` but a manifest forcing `custom_positions_supported=False`: `set_camera_offset` raises `CapabilityNotSupported`; named-view methods are unaffected. |

Live-only tolerance: `CAMERA_OFFSET_TOLERANCE = {"fake": 0.001, "xplane": 0.5}` (metres/degrees) —
mirrors `LOADOUT_KG_TOLERANCE`'s reasoning; only exercised once the X-Plane spike (§10.2) confirms
`custom_positions_supported` can honestly be `True` there.

---

## 5. Dataref mapping (X-Plane)

**This section describes `adapters/xplane/` only. No dataref name appears in `core/`.** No weather
mode is involved.

### 5.1 Named views — high confidence, command-based

X-Plane fires named views through simple commands, the same mechanism `fix_all_systems` already
proves reachable over the Web API (`POST /command/{id}/duration` or equivalent). A new mapping
module, `adapters/xplane/camera_commands.py`, in the style of `failure_datarefs.py`:

| `view_id` | Candidate command | Confidence |
|---|---|---|
| `cockpit` | a 3D-cockpit-forward view command | medium — verify exact name in spike |
| `chase` | `sim/view/chase` (or equivalent) | medium |
| `tower` | `sim/view/tower` (or equivalent) | medium |
| `wing` | a spot/external side view command | low |
| `drone` | `sim/view/circle` / an orbit or free-camera command | medium |

Every row is `verify in spike` — no name here is asserted as fact, the Failures design's own
honesty convention. Connect-time probing (the same pattern `failures-manager.md` D11 uses for its
`sim/operation/failures/*` idents) makes a wrong guess harmless: an unresolvable command marks
its `view_id` `supported=False` with a stated reason, never a runtime throw.

### 5.2 Custom offsets — the genuinely open question (D7)

Positioning an arbitrary external camera in 3D relative to the aircraft is, in the native X-Plane
SDK, `XPLMCameraControl` — a **plugin-only** API. Whether the equivalent is reachable as a plain
writable dataref through the Web API (some builds expose camera-adjacent datarefs under
`sim/graphics/view/*`, but their write semantics for a *free* external camera are unconfirmed) is
not established by this design. Two honest outcomes, both representable without any interface
change:

- **If a spike finds a writable dataref set:** `set_camera_offset`/`get_camera_offset` write/read
  it directly, `custom_positions_supported=True`.
- **If it does not:** the Phase 3 X-Plane adapter ships `custom_positions_supported=False` with
  `custom_positions_reason="Free-camera positioning needs the optional in-sim bridge on this
  X-Plane build."` — the exact shape `can_spawn_traffic` already uses for the bridge dependency —
  and named-view switching still works in full. The manifest's per-feature granularity (D3) is
  precisely what makes this degrade honestly instead of forcing an all-or-nothing
  `can_control_camera`.

Either way, **the Phase 3 X-Plane adapter foundation commit ships `can_control_camera=True` with
a conservative manifest** (named views probed at connect time per §5.1; `custom_positions_supported
=False` until the spike says otherwise) — the same "refusing stub first, upgrade after
verification" posture `weather-manager.md`'s D16 established.

### 5.3 MSFS (Phase 5 target)

SimConnect's `CAMERA_SET_RELATIVE_POSITION` and `CAMERA STATE` simvars are comparatively well
documented and plausibly cover both named views and free positioning without an add-on module —
noted, not designed (§10.3).

---

## 6. `core/` logic

Two new modules, both fully unit-testable with no simulator, no adapter, no I/O beyond the local
filesystem (`core/camera/store.py` — reading/writing the user's own app-data directory is not
simulator I/O and is not forbidden by hard rule 2, the same reasoning `core/navdata/` and the
Training Profiles design already rely on).

### `core/camera/geometry.py`

```python
def resolve_camera_pose(state: AircraftState, offset: CameraOffset) -> CameraPose:
    """offset -> an absolute CameraPose, resolved against state right now (D4).

    Two sequential geodesic hops via core.geodesy.point_at_distance_and_bearing:
    forward_m along state.heading_deg, then right_m along state.heading_deg + 90.
    up_m is added to altitude_ft (converted from metres). heading_deg =
    (state.heading_deg + offset.look_offset_deg) % 360; pitch_deg and
    zoom_ratio pass through unchanged (D5)."""


def derive_camera_offset(state: AircraftState, pose: CameraPose) -> CameraOffset:
    """The (approximate) inverse of resolve_camera_pose: decomposes the
    geodesic vector from the aircraft to `pose` onto the aircraft's
    forward/right axes via core.geodesy.distance_and_bearing plus trigonometry,
    for whichever adapter can read back an absolute camera pose.

    Round-trips resolve_camera_pose to within millimetres at the offset
    magnitudes this manager allows (<= 500 m) — the flat-plane trigonometric
    recovery of a two-hop geodesic composition is not exact, but the residual
    is many orders of magnitude below anything this feature or its tests can
    observe, unlike the 40 km-scale tangent-plane error architecture.md flags
    for long teleports."""
```

### `core/camera/models.py`

Everything in §3.

### `core/camera/store.py`

```python
def app_data_camera_positions_dir() -> Path:
    """%APPDATA%/OpenInstructorStation/camera_positions (Windows),
    ~/Library/Application Support/OpenInstructorStation/camera_positions (macOS),
    $XDG_DATA_HOME or ~/.local/share/OpenInstructorStation/camera_positions (Linux).
    A small, independent duplicate of training-profiles.md's D2 helper (§10.1) —
    same ~15 lines, same reasoning against adding platformdirs as a dependency."""


class CameraPositionStore:
    """A flat directory of one JSON file per SavedCameraPosition, no SQLite —
    training-profiles.md's D5 reasoning transplanted: user-authored, few, small."""

    def list(self) -> tuple[SavedCameraPosition, ...]: ...
    def save(self, name: str, offset: CameraOffset) -> SavedCameraPosition: ...
    def get(self, position_id: str) -> SavedCameraPosition | None: ...
    def delete(self, position_id: str) -> bool: ...
```

---

## 7. UI panel outline

`ui/src/features/camera/` — a new tab of the Instructor Panel. Per D10, does not edit
`instructorApi.ts`. Built ahead of the backend against `mock.ts`/`types.mock.ts`, the established
`features/weather`/`features/failures`/`features/traffic` pattern.

### 7.1 Components

| File | Role |
|---|---|
| `CameraPanel.tsx` | The tab: gate → view grid → saved-positions list. |
| `ViewGrid.tsx` | Five large buttons (one per `CameraViewId`), disabled per-entry with the manifest's `reason` inline when unsupported — the Failures panel's `FailureRow` disabled-with-reason pattern, not a hidden control. Tapping one fires `POST /view` immediately (D6 — momentary, no staging, the Failures panel's D13 reasoning: this *is* the product). The last requested view is highlighted client-side only (D6). |
| `SavedPositions.tsx` | A list of `SavedCameraPosition`s, each with an "Apply" and a small delete (✕) action; a "Save current" button that is disabled with a reason when `custom_positions_supported` is `False` or when the drone view is not currently active (mirrors the 409 precondition client-side, so the instructor is not surprised by a failed POST). |
| `SaveDialog.tsx` | A single text input (name, 1–60 chars) — the smallest possible form, inline rather than a modal where the layout allows it. |
| `gate.ts` | `cameraGate(capabilities, isError)` — fail-closed. |
| `mock.ts`, `types.mock.ts` | Deterministic view/offset fixtures; "dies at backend integration," the established phrasing. |
| `cameraSlice.ts`, `cameraApi.ts` | Below. |

Tablet-first: view buttons ≥ 44 px in a 2-column grid (fits one-handed reach); "switch to chase
view" is one tap; "recall my saved base-leg framing" is one tap once saved.

### 7.2 State — one RTK slice + injected endpoints

`cameraApi.ts` uses `instructorApi.injectEndpoints` with tag `CameraPositions`:

- `getCameraManifest` (query, cached for the session),
- `setCameraView` (mutation; no tag invalidated — there is no server-held camera state to
  refetch, D6),
- `getCameraPositions` (query, tag `CameraPositions`),
- `saveCameraPosition`, `applyCameraPosition`, `deleteCameraPosition` (mutations; the first and
  last invalidate `CameraPositions`).

`cameraSlice.ts` holds **client state only**:

```ts
interface CameraState {
  lastRequestedView: CameraViewId | null;   // optimistic highlight, D6 — never reconciled
  saveDraftName: string;
}
```

All API types come from the regenerated `ui/src/api/schema.d.ts` once the backend lands.

### 7.3 Capability gating, restated

- Tab-level: `can_control_camera` via `cameraGate`, fail-closed.
- View-level: `supported` from `/manifest`, disabled rows show `reason` inline.
- Saved-positions-level: `custom_positions_supported` from `/manifest`; "Save current" additionally
  checks (client-side, informational only — the server's 409 is the real gate) that the last
  requested view was `"drone"`.

---

## 8. Test plan

Everything except §8.3 runs in CI against `FakeSimAdapter`. No navdata, no simulator-derived
fixtures.

### 8.1 `core/` unit tests — `tests/core/test_camera_geometry.py`, `tests/core/test_camera_store.py`

Concrete reference values:

- **The worked example (§3):** heading 090°, `forward_m=50, right_m=0, up_m=20,
  look_offset_deg=0, pitch_deg=0` → `resolve_camera_pose` gives a position at true bearing 090°,
  distance `50 / 1852` NM from the aircraft (within 1 mm), altitude `state.altitude_ft +
  65.6167...` ft (`20 / 0.3048`, within 0.001 ft), `heading_deg == 90.0` exactly.
- **`right_m` only:** heading 000° (north), `forward_m=0, right_m=30` → position at true bearing
  090° (east — "right" of north), distance `30 / 1852` NM.
- **`look_offset_deg`:** heading 270°, `look_offset_deg=90` → `heading_deg == 0.0` (270 + 90 mod
  360, exact).
- **Round trip:** for a table of offsets up to the ±500 m bound, `derive_camera_offset(state,
  resolve_camera_pose(state, offset))` reproduces `offset` within 1 mm / 0.01° (D-transplanted
  claim from `core/camera/geometry.py`'s docstring, pinned as a test rather than left asserted in
  prose).
- `CameraPositionStore`: save → list contains it → get by id → delete → list no longer contains
  it; `app_data_camera_positions_dir()` resolved per platform with `sys.platform`/`XDG_DATA_HOME`
  monkeypatched (the `training-profiles.md` §"pure function, no filesystem touched" precedent),
  and a separate test that actually writes to a `tmp_path`-substituted directory to prove the
  JSON round-trips (`SavedCameraPosition.model_validate_json` on what was written).

### 8.2 Contract tests

The suite of §4.2, parametrised over both adapters, written by the tester from this document
before the implementation exists.

### 8.3 `@pytest.mark.sim` — `tests/sim/test_live_camera.py` (never in CI)

What only a live X-Plane proves, restoring the original view in a `finally`:

- `set_camera_view("chase")` (and every other `supported=True` entry the manifest reports) does
  not raise and the manual `sim-validator` smoke visually confirms the view changed.
- **If** `custom_positions_supported` is `True` on this install: `set_camera_offset(offset)` →
  `get_camera_offset()` round-trips within `CAMERA_OFFSET_TOLERANCE["xplane"]`.
- **If** it is `False`: a test asserting exactly that — `get_camera_support().custom_positions_supported
  is False` and a non-empty `custom_positions_reason` — so a silent regression (someone flips the
  manifest without updating this test) is caught, per the project's "never skip or xfail" rule.

### 8.4 Server tests — `tests/server/test_camera_routes.py`

Against `TestClient` + `FakeSimAdapter`, `reset_adapter()` between tests:

- `/manifest` reports every view supported and `custom_positions_supported=True` for the Fake.
- `/view` for each `view_id` returns 200 with the echoed `view_id`.
- `/view` with an unsupported `view_id` on a `can_control_camera=False` fake → 501.
- `/positions` (POST) without first requesting the `"drone"` view (adapter's `_camera_offset` is
  `None`) → 409 with the stated sentence.
- `/positions` (POST) after `set_camera_offset` has been called on the Fake directly (test
  setup) → 200, `list()` contains it, `apply` echoes the offset, `DELETE` removes it and a second
  `DELETE` → 404.
- 422: empty `name`, `name` over 60 chars, out-of-bound offset fields.

### 8.5 UI tests (vitest)

- `gate.test.ts` — fail-closed on loading, error, missing flag.
- `mock.test.ts` — the mock's `resolve_camera_pose` mirrors `core.camera.geometry`'s formulas on
  the worked example.
- `ViewGrid.test.tsx` — an unsupported view renders disabled with its reason; tapping a supported
  view issues exactly one `setCameraView` mutation with the exact `view_id`, asserted with
  `toEqual` against a stubbed fetch.
- `SavedPositions.test.tsx` — "Save current" disabled when `custom_positions_supported` is
  `False` or the last view was not `"drone"`; Apply/Delete issue exactly one request each.

---

## 9. Parallelisation

### 9.1 Across Phase 3

Camera is one of the phase's two small, independent tracks (with Pushback), each its own branch
in its own **git worktree**, its own PR to `dev`; CI is the integration barrier. **Both need a
contract change, and contract changes are never parallelised** — the §4 additions to
`core/sim_adapter.py`, `adapters/fake/fake_adapter.py` and `tests/adapters/test_contract.py` must
land serially with respect to Pushback's equivalents (and the Map/Traffic track's own
`can_spawn_traffic` work). Whichever of Camera/Pushback's foundation commit lands first on `dev`,
the other rebases onto it.

### 9.2 Inside this manager

**Track 0 — the foundation (serialised, first, one agent):** `core/camera/models.py`, the §4
protocol methods, `FakeSimAdapter`, the §4.2 contract tests.
Owns: `core/camera/models.py`, `core/sim_adapter.py`, `adapters/fake/`, `tests/adapters/test_contract.py`.

Then three tracks, dispatched **in one message**, disjoint directories:

**Track A — backend:** `server/camera_routes.py` + the router registration line in
`server/app.py`, `core/camera/geometry.py`, `core/camera/store.py`,
`tests/core/test_camera_geometry.py`, `tests/core/test_camera_store.py`,
`tests/server/test_camera_routes.py`.
Owns: `core/camera/geometry.py`, `core/camera/store.py`, `server/`, `tests/core/`, `tests/server/`.

**Track B — X-Plane mapping:** `adapters/xplane/camera_commands.py`, the four method
implementations in `adapters/xplane/xplane_adapter.py`, the connect-time probe, the §10.2 spike,
`tests/sim/test_live_camera.py`.
Owns: `adapters/xplane/`, `tests/sim/`, `spikes/`.

**Track C — the panel:** `ui/src/features/camera/*` and the `cameraApi.ts` injection.
Its pure logic (`gate.ts`, `mock.ts`, the slice) proceeds from this document alone, in parallel
with Track A/B; the RTK Query wiring against a real schema waits for Track A's regen.

**The tester does not wait:** §8.1/§8.2's tests are written against this document before any
implementation exists.

**Never parallelised, restated:** Track 0's files; merges to `dev`/`main`; release tagging. No
navdata schema is touched by this manager.

---

## 10. Open questions and risks

### 10.1 A shared app-data helper, deliberately not built yet

`core/camera/store.py::app_data_camera_positions_dir()` duplicates `training-profiles.md`'s D2
helper in spirit (~15 lines each). This is the same trade Training Profiles itself made in the
opposite direction (its D4, duplicating `PlacementRequest`'s shape as `ProfilePlacement`) — a
small, flagged duplication rather than a cross-manager dependency that would violate
`architecture.md`'s "adding a manager must not require touching another one." **What resolves it:**
if Training Profiles lands first (Phase 2, ahead of this Phase 3 manager) and its own helper
proves identical, a follow-up `chore/` factors both into `core/appdata.py` — cheap, and not worth
doing speculatively now.

### 10.2 Whether free-camera positioning needs the bridge — the design's central unknown

§5.2. Not resolved by this design; deliberately left as a manifest-degrading unknown rather than
an asserted dataref. **What resolves it:** the Track B spike, `spikes/camera_offset_probe.py` —
dump every dataref under `sim/graphics/view/` on a live install, attempt a write, read it back.
If the Web API cannot reach it, the honest next question (not designed here) is whether it is
worth adding to `bridge/`'s scope alongside AI traffic, given both would then share "needs the
in-sim plugin" — a product decision, not an architecture one, and out of this document's remit.

### 10.3 MSFS's camera surface is unresearched beyond "plausible"

§5.3. Phase 5's problem; SimConnect's own camera simvars look more complete than X-Plane's Web
API surface for this specific feature, which would make Camera one of the *easier* Phase 5
adapters rather than a limiting one — worth a note, not a design, this early.

### 10.4 The `wing` view has no confirmed X-Plane command at all (§5.1, lowest confidence row)

If the spike finds nothing, `wing` ships `supported=False` from day one on X-Plane — which is a
legitimate, honest outcome under D2's whole design (a manifest exists precisely so one missing
view degrades a control, not the manager).

---

## 11. Verification

```bash
pytest && ruff check . && ruff format --check . && mypy .
cd ui && npm run lint && npm run typecheck && npm test && npm run build
```

Then, against `OIS_ADAPTER=fake` with the Vite dev server: open the Camera tab → view grid shows
five enabled buttons → tap "Chase" → highlight moves → tap "Drone" → "Save current" enables → save
as "Base leg view" → appears in the saved list → tap "Apply" → highlight returns to "Drone" →
delete it → list empties, plus a console check. Live-sim validation (`pytest -m sim`, §8.3) is the
`sim-validator` agent's job and is not a merge gate.
