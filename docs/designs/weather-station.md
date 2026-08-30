# Weather Station — design

**Status:** designed, not yet implemented.
**Phase:** downstream of Phase 2 — Weather + Failures → Scenario Generator
([`../roadmap.md`](../roadmap.md#phase-2--weather--failures--scenario-generator)), which is
**complete**. This document is not itself a roadmap phase gate: like manager 15, the Instructor
Panel — which "appears in no single phase: it is the UI itself and gains one tab per phase, next
to the manager that tab drives" (roadmap.md's own words) — this is a UI-polish track layered onto
the already-shipped Weather Manager. It is developed alongside Phase 3's work
([`../roadmap.md`](../roadmap.md#phase-3--instructor-map--ai-traffic)) without blocking, or being
blocked by, that phase's own exit criteria.
**Feature spec:** manager 3 ([`../feature-spec.md`](../feature-spec.md#3-weather-manager)),
⭐⭐⭐⭐⭐ — the same spec item. This document adds no new spec line; it completes "full manual
control of the environment" beyond the preset-first UI the manager shipped with.
**Depends on:** the shipped Weather Manager ([`weather-manager.md`](weather-manager.md)) **as
built**. The code in `core/weather/`, `server/weather_routes.py` and `ui/src/features/weather/`
is ground truth for this document; nothing here reconciles against a design draft the way
`position-manager.md`'s as-built addenda do, because none of WS-1 through WS-7 has shipped yet —
this is greenfield framing on top of a finished manager, not a deviation record.
**Blocks:** Wave 1 (#182 free-form editing, #183 atmosphere profile, #184 saved-presets store +
routes), Wave 2 (#185 station layout recomposition), Wave 3 (#186 saved-presets UI, #187 ILS
minima control) — epic #179's Waves 1–3.

Turns the shipped, preset-first Weather Manager into a full "Weather Station": free-form manual
editing that coexists with preset staging, a draggable vertical atmosphere profile, saved user
presets, and an ILS-minima quick-set control. Seven decisions — WS-1 through WS-7 — were pinned
by the issue author (#180) before this document was written; they are transcribed here in full
house-style detail, never re-derived or weakened, alongside the genuinely open design surface
inside their boundaries: the saved-presets CRUD contract, the `SavedWeatherPreset` model, the
atmosphere-profile module's exact function signatures, and the RTK Query endpoint shapes.

**This document introduces no new dataref, no new `Capabilities` flag and no new `SimAdapter`
method, and no WebSocket change — weather-manager.md's D14 stands unmodified: weather stays a
command surface with a slow-moving read, not a streamed one.** Every new byte this document moves
is either client (Redux) state or app-data JSON on disk; the only simulator-facing call in the
whole series is the *existing* `POST /api/weather/apply`, unchanged (§2, §5).

Binding rules live in [`../../CLAUDE.md`](../../CLAUDE.md); layers in
[`../architecture.md`](../architecture.md). This document never relaxes any of them and never
contradicts, weakens or reinterprets WS-1 through WS-7.

---

## 0. Decisions at a glance

| # | Decision | Where |
|---|---|---|
| WS-1 | **Manual staging coexists with preset staging in the existing slice shape.** `staged: boolean` is unchanged; the source is *derived* (`staged && selectedPresetId !== null` → preset mode, `staged && selectedPresetId === null` → manual mode). The first `overrideSet` while un-staged now also sets `staged = true`; `stagingCleared` and the reset on `positionSlice.airportSelected` are untouched. | §4.1, §8.2 |
| WS-2 | **Manual mode makes NO `/preview` call** — a setup-only preview would just echo the setup back. Display is `mergeForDisplay(current, overrides)`, computed client-side; Apply sends `WeatherRequest{preset: null, setup: overrides}`, sparse, so weather-manager.md's D2/D3 (untouched-field, wholesale-list-replace) semantics hold unchanged. `resolve.ts` gains `buildManualWeatherRequest`; `buildWeatherRequest` is untouched. | §4.2, §8.2 |
| WS-3 | **The atmosphere profile is a pure prop-driven component**, `ProcedureDiagram`'s idiom exactly: a projection module plus an SVG component, no store access, no new dependency, ≥44 px percentage-positioned touch targets. Vertical linear ft-MSL scale, `0 → max(10000, highest tops/wind altitude + 2000)`, AGL secondary labels + a null-tolerant terrain band from `fieldElevationFt`. Draggable cloud base/tops edges (100 ft snap, `tops > base + 100` enforced at the emit boundary); draggable wind-layer altitudes; direction/speed stay numeric fields (drag-to-rotate deferred); every edit emits a whole replacement list through `overrideSet`. | §8.2 |
| WS-4 | **Saved user presets are JSON files — `core/profiles/store.py`'s idiom transplanted.** A deliberate, named deviation from "scenarios are YAML": that rule governs shipped scenario *content*; user-saved data (profiles, camera positions) already has a JSON-in-app-data-directory precedent. Location: `weather_presets/` under the app-data root. `SavedWeatherPreset{preset_id, name (1–60), description, setup: WeatherSetup, created_at, updated_at}`. Save is an **absolute snapshot** — fully-populated `setup`, explicit `[]`, never `null`; runway-relative stays a built-in-preset-only concept. Reapply is client-side via the existing `POST /api/weather/apply` — no second apply path. No capability gate. | §2, §3, §6 |
| WS-5 | **The ILS minima control is pure UI sugar over manual staging.** CAT I/II/III segmented control, editable RVR/visibility (m) and DH (ft AGL), prefilled 800 m/200 ft, 350 m/100 ft, 125 m/50 ft. Staging writes `visibility_m` plus one wholesale-replaced OVC stratus layer, `base_ft = field_elevation + DH + 50`, `tops_ft = base_ft + 2000`. Disabled with a reason when no airport is selected. No server change. | §4.3, §8.2 |
| WS-6 | **Panel recomposition.** Profile pane left (~60% landscape); right column: compact readouts, `PresetGrid` + saved presets, field editors extracted to `StationEditors.tsx`; `WeatherStagingBar` spans the bottom; portrait stacks. The pre-split makes Wave 3 file-disjoint. | §8.3 |
| WS-7 | **`ui/src/api/schema.d.ts` is regenerated exactly once**, in #186, after #184 (the server issue) is merged (`npm run generate:api`). No hand-written API types anywhere. | §8.1, §10 |

---

## 1. Scope

### 1.1 What this document adds

1. **Free-form manual weather editing** that coexists with preset staging inside the existing
   `weatherSlice` shape, with no separate mode-selection UI element — the first edit made with
   nothing staged *is* the entry into manual mode (WS-1, WS-2).
2. **A draggable vertical atmosphere profile** — a to-scale visualisation of wind and cloud
   layers, editable by dragging, alongside the existing numeric field editors (WS-3).
3. **Saved user weather presets** — save the currently resolved weather as a named, reusable
   snapshot; list, reapply, replace and delete them (WS-4).
4. **An ILS-minima quick-set control** (CAT I/II/III) that is sugar over the manual staging path,
   not a new server concept (WS-5).
5. **The panel recomposition** that hosts all of the above without breaking the shipped
   preset-grid flow, and that is structured so the three UI tracks that depend on it can proceed
   with the fewest possible file collisions (WS-6).

It covers no new item of feature-spec manager 3 that weather-manager.md did not already claim
("full manual control of the environment") — this document is that claim's completion in the UI,
not a new spec line.

### 1.2 What is explicitly out of scope

Per epic #179's own stated boundary:

| Out of scope | Owner / reason |
|---|---|
| METAR readout | #179; Instructor Map / later phase territory — the same boundary weather-manager.md §1.2 already draws for a real-world METAR fetch |
| Real-weather import | #179; a live internet fetch this station's LAN-tool posture (CLAUDE.md hard rule 1: 100% external) does not currently take on |
| Seasons / time-of-day | #179; not represented in `WeatherState`/`WeatherSetup` at all — a `core/weather/models.py` change, and this document makes none (§5) |

Everything weather-manager.md §1.2 already put out of scope (direct airframe ice, per-altitude
temperature ladders, snow depth, wind-shear *scenarios*, MSFS behaviour) stays out of scope here
too, unrevisited.

---

## 2. REST endpoints

**`GET /api/weather`, `GET /api/weather/manifest`, `POST /api/weather/preview` and
`POST /api/weather/apply` are UNCHANGED** — no new field, no new status code, no new semantics.
Manual staging, the atmosphere profile drag, and the ILS-minima control all eventually call the
same `POST /api/weather/apply` a preset does (WS-2, WS-5); saved-preset reapply does too (WS-4).
`/preview` is untouched and is never called in manual mode (WS-2). No WebSocket message exists or
is added for weather — weather-manager.md's D14 stands.

The **only** new endpoints are the saved-presets CRUD surface (WS-4), in a new
`server/weather_preset_routes.py`, prefix `/api/weather/saved-presets` — deliberately *not*
`/api/weather/presets`, because that vocabulary already means the seven built-in presets
(`WeatherPresetId`, `WeatherPreset`, the `WEATHER_PRESETS` catalogue); reusing "preset" bare for a
completely different, user-authored, capability-free resource would blur a distinction WS-4 itself
draws ("runway-relative stays a built-in-preset-only concept"). `server/app.py` gains one
`include_router` line — the only shared-file backend edit, the same shape every other manager's
own router registration already takes.

```
GET    /api/weather/saved-presets              -> list[SavedWeatherPreset]
POST   /api/weather/saved-presets               -> SavedWeatherPreset
GET    /api/weather/saved-presets/{preset_id}   -> SavedWeatherPreset
PUT    /api/weather/saved-presets/{preset_id}   -> SavedWeatherPreset
DELETE /api/weather/saved-presets/{preset_id}   -> 204
```

| Method | Path | Purpose | Safe? | Capability | Declared |
|---|---|---|---|---|---|
| `GET` | `/api/weather/saved-presets` | Every saved preset, newest `updated_at` first | yes | none — always 200 | `def` — a directory listing |
| `POST` | `/api/weather/saved-presets` | Save a new preset; the server assigns `preset_id` and timestamps | no | none | `def` |
| `GET` | `/api/weather/saved-presets/{preset_id}` | One saved preset, in full | yes | none | `def` |
| `PUT` | `/api/weather/saved-presets/{preset_id}` | Replace name/description/setup of an existing preset. Never creates. | no | none | `def` |
| `DELETE` | `/api/weather/saved-presets/{preset_id}` | Remove a saved preset | no | none | `def` |

None of the five is ever `501` or `503`: none touches the adapter or navdata, the same reasoning
`server/profile_routes.py`'s own module docstring states for training profiles ("None of the CRUD
endpoints or import/export touch the simulator or navdata … so none of them is ever 501 or 503").
This is WS-4's "no capability gate" made concrete at the HTTP layer.

### 2.1 Errors

| Situation | Status | Detail |
|---|---|---|
| `setup` in the create/replace body is not fully populated — any scalar field `None`, or `wind_layers`/`cloud_layers` `None` | 422 | pydantic model validator on `SavedWeatherPresetCreate`: `"A saved preset's setup must be fully populated — every field explicit, [] for calm wind / clear sky, never omitted. Missing: {fields}."` |
| `name` empty or over 60 characters | 422 | FastAPI's own field-length validation (`Field(min_length=1, max_length=60)`) |
| Unknown `preset_id` (`GET`, `PUT`) | 404 | `"No saved weather preset {preset_id!r}."` |
| Unknown `preset_id` (`DELETE`) | 404 | `"No saved weather preset {preset_id!r} — it may already be deleted."` (`profile_routes._MAY_BE_DELETED`'s exact phrasing) |
| A `preset_id` not shaped like one this store ever assigns (wrong length, non-hex, a traversal attempt) | 404 | same sentence as "unknown" — never reaches the filesystem (`_VALID_PRESET_ID`, §6) |
| The store itself fails (disk full, permission denied, corrupt file on read) | 500 | the store's own exception message; `WeatherPresetStoreError` → 500, mirroring `ProfileStoreError`/`CameraPositionStoreError` → 500 |

### 2.2 What is deliberately not an endpoint

- **No `POST /api/weather/saved-presets/{id}/apply`.** WS-4 is explicit: reapply goes through
  `POST /api/weather/apply` with a client-built `WeatherRequest{preset: null, setup: saved.setup}`
  — the same manual-mode path an edited field takes (§4.2). A second apply path would duplicate
  D7's "the server re-resolves from scratch" reasoning for no benefit, since a saved preset's
  `setup` is already fully resolved and absolute by construction (WS-4).
- **No summary/list-projection endpoint separate from `GET .../saved-presets`.** Unlike training
  profiles (whose list strips a heavyweight embedded `ScenarioDocument`), a `SavedWeatherPreset`
  is already small — one flat `WeatherSetup` — so the list returns the full model (§3).

---

## 3. Pydantic models

New package `core/weather_presets/models.py`. Units are entirely inherited from
`core.weather.models.WeatherSetup` (weather-manager.md D13) — this document introduces no new
unit and no new field vocabulary, only a wrapper with a name, a description and two timestamps.

```python
class SavedWeatherPresetCreate(BaseModel):
    """POST /api/weather/saved-presets and PUT .../{preset_id} body.

    Everything the instructor supplies; the server fills preset_id/created_at/updated_at.
    extra="forbid": a hand-edited body with a typo'd field fails loudly, the same
    convention TrainingProfileCreate and SaveCameraPositionRequest already establish.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=2000)
    setup: WeatherSetup = Field(
        description="An ABSOLUTE snapshot (WS-4): every field must be set, layer lists "
        "explicit ([] for calm/clear), never None. See _require_fully_populated."
    )

    @field_validator("setup")
    @classmethod
    def _setup_is_fully_populated(cls, setup: WeatherSetup) -> WeatherSetup:
        return _require_fully_populated(setup)


class SavedWeatherPreset(BaseModel):
    """One saved user preset, as stored and returned.

    Built by the store, never by a request body (server-assigned preset_id/timestamps) — the
    same posture SavedCameraPosition's own docstring states.
    """

    model_config = ConfigDict(frozen=True)

    preset_id: str = Field(
        min_length=32,
        max_length=32,
        description="Server-assigned uuid4 hex. Also the filename stem (<preset_id>.json).",
    )
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=2000)
    setup: WeatherSetup
    created_at: datetime = Field(description="UTC, set once at creation.")
    updated_at: datetime = Field(description="UTC, set on every save/replace.")

    @field_validator("setup")
    @classmethod
    def _setup_is_fully_populated(cls, setup: WeatherSetup) -> WeatherSetup:
        return _require_fully_populated(setup)


def _require_fully_populated(setup: WeatherSetup) -> WeatherSetup:
    """WS-4's 'absolute snapshot' rule, enforced once, shared by both models above.

    A sparse saved setup would be ambiguous on reapply: an omitted field means
    'leave untouched' everywhere else this model is used (weather-manager.md D2),
    so a saved preset with a None field would silently inherit whatever the
    environment happens to be at the moment it is reapplied, defeating the point
    of "saved" — a snapshot that is only sometimes a snapshot. Refusing this at
    the model boundary means every SavedWeatherPreset that exists on disk is,
    by construction, reproducible.
    """
    missing = [name for name, value in setup.model_dump().items() if value is None]
    if missing:
        raise ValueError(
            "A saved preset's setup must be fully populated — every field explicit, "
            f"[] for calm wind / clear sky, never omitted. Missing: {', '.join(sorted(missing))}."
        )
    return setup
```

Deliberately **not** here, and why:

- **No `format_version`** (unlike `TrainingProfile`). WS-4's field list is exact, and the stored
  payload is one `WeatherSetup` already versioned implicitly by the same wire schema every other
  weather endpoint shares. `TrainingProfile`'s versioning exists because it embeds a much heavier,
  independently-evolving `ScenarioDocument`; transplanting that machinery here uncritically would
  be scope the pinned decision did not ask for. Revisit only if this store's on-disk shape ever
  needs to change under an existing file.
- **No `SavedWeatherPresetSummary`/list-row projection.** §2.2 already states why: the full model
  is already the size a summary would be.

---

## 4. Client-side contracts

### 4.1 WS-1 — slice derivation, exact

```ts
// ui/src/features/weather/weatherSlice.ts

export type WeatherSource = 'preset' | 'manual';

/** Derived, never stored: WS-1's whole point is that `staged`/`selectedPresetId` already say
 * everything a `source` field would duplicate — storing it separately would be a second
 * source of truth that could drift from the two fields it is computed from. */
export function weatherSource(ui: WeatherUiState): WeatherSource | null {
  if (!ui.staged) return null;
  return ui.selectedPresetId === null ? 'manual' : 'preset';
}
```

Reducer change (the only one — WS-1 is explicit that `presetStaged`, `stagingCleared` and the
`airportSelected` reset stay exactly as shipped): `overrideSet` gains one line, setting
`staged = true` the first time it runs against an un-staged slice, before applying the field
write:

```ts
overrideSet(state, action: PayloadAction<{ field: keyof WeatherSetup; value: unknown }>) {
  if (!state.staged) {
    state.staged = true;   // NEW — the first edit with nothing staged enters manual mode
  }
  const { field, value } = action.payload;
  if (value === null || value === undefined) {
    delete state.overrides[field];
  } else {
    Object.assign(state.overrides, { [field]: value });
  }
},
```

**Edge case that must be handled outside the reducer, not inside it.** `overrideSet(field, null)`
deletes an override; a manual stage whose only edit is deleted this way reaches
`staged=true, selectedPresetId=null, overrides={}` — a manual stage with nothing to send.
`WeatherRequest{preset: null, setup: null}` is refused by the model's own validator (422,
weather-manager.md §2.2, "Neither `preset` nor `setup` in the request"). WS-1 pins the reducers
exactly as shipped plus the one line above, so the fix is **not** an auto-clear of `staged` inside
the reducer — that would be a second, un-pinned behaviour change. It lives one layer up, in the
component (§8.3): **Apply is disabled whenever `weatherSource(ui) === 'manual' && Object.keys(overrides).length === 0`**,
so `buildManualWeatherRequest` is only ever invoked with a non-empty overlay, and the staging bar
shows why ("no changes yet") rather than offering a button that would 422.

### 4.2 WS-2 — `buildManualWeatherRequest`

```ts
// ui/src/features/weather/resolve.ts — buildWeatherRequest is unchanged; this is new.

/** WS-2: the manual-mode counterpart to buildWeatherRequest. No preset id, no runway
 * context — a manual instruction needs neither, since there is nothing left to resolve
 * against navdata (every value in `overrides` is already an absolute number in the
 * model's own units). Precondition: `overrides` is non-empty — enforced by the caller
 * (§4.1's Apply-disabled guard), never by this function itself. */
export function buildManualWeatherRequest(overrides: WeatherSetup): WeatherRequest {
  return { preset: null, airport_icao: null, runway_ident: null, setup: overrides };
}
```

Display in manual mode never calls this or any server endpoint: it is
`mergeForDisplay(current, overrides)`, the existing function, called directly. This is the whole
reason WS-2 forbids a `/preview` call in manual mode — a preset needs `/preview` because its AGL
heights and runway-relative bearings need navdata to resolve; a manual edit is already an absolute
number, so "resolving" it server-side would just echo the request back.

### 4.3 WS-5 — ILS-minima resolution formula

```ts
// ui/src/features/weather/ilsMinima.ts (new — see §10, track #187; deliberately not added
// to resolve.ts, which track #182 owns and this track must not reopen)

export type IlsCategory = 'cat_i' | 'cat_ii' | 'cat_iii';

export const ILS_MINIMA_DEFAULTS: Record<IlsCategory, { rvrM: number; dhFt: number }> = {
  cat_i: { rvrM: 800, dhFt: 200 },
  cat_ii: { rvrM: 350, dhFt: 100 },
  cat_iii: { rvrM: 125, dhFt: 50 },
};

/** WS-5's pinned formula, verbatim: base = field elevation + DH + 50 ft buffer;
 * tops = base + 2000 ft. Replaces the whole cloud list (D3) with one OVC stratus layer. */
export function ilsMinimaOverrides(
  visibilityM: number,
  dhFt: number,
  fieldElevationFt: number,
): WeatherSetup {
  const baseFt = fieldElevationFt + dhFt + 50;
  const topsFt = baseFt + 2000;
  return {
    visibility_m: visibilityM,
    cloud_layers: [
      { base_ft: baseFt, tops_ft: topsFt, coverage_ratio: 1.0, cloud_type: 'stratus' },
    ],
  };
}
```

**Worked example** (§9 uses this number): CAT I at a 1 000 ft field — weather-manager.md's own
`ZZZZ` fixture elevation, kept for continuity — DH 200 ft → `base_ft = 1000 + 200 + 50 = 1250`,
`tops_ft = 3250`. This is deliberately not the same thickness as weather-manager.md's own `cat_i`
preset (1 250–3 500, a 2 250 ft layer): WS-5 pins its own, simpler `base + 2000` tops offset for
the quick-set control, and the two are not required to agree — both put the base at exactly
DH + 50 ft, which is the shared training intent (break out just above minima).

The control's staging goes through the **existing manual-mode path**: its onClick calls
`overrideSet` (twice, or once via a small dispatch helper covering both fields) — never
`presetStaged`. Concretely: staging an ILS minimum while nothing is staged enters manual mode
(WS-1's "first `overrideSet` while un-staged" rule, unmodified); staging one while a preset is
already staged is an override on top of it, exactly like typing into the numeric visibility field
would be — the control has no special-cased interaction with `selectedPresetId` at all.

**`fieldElevationFt`'s source** (needed by both WS-3 and WS-5, named by neither): `GET
/api/navdata/airports/{icao}` → `Airport.elevation_ft`. This endpoint already exists server-side
(`server/navdata_routes.py`); only its RTK Query wiring on the client is new (§8.1). It is keyed
on `airport_icao` alone, which is exactly what WS-5's own gate needs ("disabled … when no airport
is selected", not "no runway").

---

## 5. `SimAdapter` / `Capabilities` additions

**None.** No method is added to `SimAdapter`, no flag is added to `Capabilities`, and
`FakeSimAdapter` is untouched. Every surface this document adds either reads/writes app-data JSON
on disk (WS-4, §6) or stages a `WeatherRequest` that reaches the simulator through the *existing*
`POST /api/weather/apply` (WS-1/WS-2/WS-5) — a call already covered end to end by
weather-manager.md's own contract suite. **No case is added to
`tests/adapters/test_contract.py`.** This is the good outcome the planner brief explicitly calls
out: say so, and move on.

---

## 6. `core/` logic

New package `core/weather_presets/` — `core/profiles/store.py`'s idiom transplanted a third time.
**Deliberately an independent module, not an import of `core.profiles.store` or
`core.camera.store`**: `core/camera/store.py`'s own docstring already records the reasoning this
inherits — "adding a manager must not require touching another one" (architecture.md), and the
shared-helper extraction that would remove the duplication is explicitly deferred there to "a
separate, reviewable change — not something to do speculatively inside a feature branch." A third
~200-line copy of the same idiom is consistent with that precedent, not a regression from it.

`core/weather_presets/paths.py`:

```python
def default_weather_presets_root(*, environ: Mapping[str, str] | None = None) -> Path:
    """Identical branch structure to core.profiles.paths.default_profiles_root and
    core.camera.store.app_data_camera_positions_dir — Windows %APPDATA%, macOS Application
    Support, Linux XDG Base Directory — with the leaf directory name "weather_presets".
    `environ` injectable, same testing convention. Pure computation: never creates the
    directory."""
```

`core/weather_presets/models.py`: `SavedWeatherPresetCreate`, `SavedWeatherPreset` (§3).

`core/weather_presets/store.py`:

```python
_VALID_PRESET_ID = re.compile(r"^[0-9a-f]{32}$")


class WeatherPresetStoreError(RuntimeError):
    """The store itself failed. Never raised for "not found" — get()/replace()/delete()
    answer None/False instead, ProfileStoreError's own distinction, verbatim."""


class WeatherPresetStore:
    """One flat directory of <preset_id>.json files. No index."""

    def __init__(self, root: Path) -> None: ...

    def list(self) -> list[SavedWeatherPreset]:
        """Newest updated_at first. A file that fails to parse is skipped and logged,
        never raised — "a bad record never stops the browse"."""

    def get(self, preset_id: str) -> SavedWeatherPreset | None:
        """None when unknown OR when preset_id is not shaped like an id this store ever
        assigns (_VALID_PRESET_ID) — never builds a Path from untrusted input. Raises
        WeatherPresetStoreError when the file exists but will not parse."""

    def create(self, draft: SavedWeatherPresetCreate) -> SavedWeatherPreset:
        """Assigns uuid.uuid4().hex, created_at == updated_at, writes atomically."""

    def replace(self, preset_id: str, draft: SavedWeatherPresetCreate) -> SavedWeatherPreset | None:
        """None when preset_id is unknown — PUT never creates. Keeps preset_id/created_at,
        bumps updated_at."""

    def delete(self, preset_id: str) -> bool:
        """False when already gone or when preset_id is not shaped like a store-assigned id."""

    def _write(self, preset: SavedWeatherPreset) -> None:
        """self._root.mkdir(parents=True, exist_ok=True); write a .{id}.tmp sibling;
        Path.replace onto the real file — the atomic-publish idiom every other store here
        already uses."""
```

Every behaviour above is `core/profiles/store.py`'s, line for line: the traversal-shaped /
wrong-length / non-hex id guard runs before any `Path` is built; the directory is created lazily,
on first write, never in `__init__` (import-safe); `list()` skips and logs a corrupt file, `get()`
raises for the same failure — the "not found" vs "the store itself failed" distinction
`ProfileStoreError`'s own docstring draws.

`core/` never talks to a simulator (hard rule 2) and this package does not either — it is pure
pydantic and `pathlib`, exactly like `core/profiles/` and `core/camera/`.

---

## 7. Dataref mapping (X-Plane)

**Not applicable.** No adapter change exists anywhere in this document (§5). Nothing below any
line in this section could ever exist, because there is nothing to map.

---

## 8. UI panel outline

### 8.1 RTK Query additions

**Decision: extend the existing `ui/src/features/weather/weatherApi.ts`**, not a new
`weatherPresetsApi.ts`. Unlike `cameraApi.ts` (a whole separate manager, hence its own file,
`instructorApi.ts`'s own tag-list comment explains why), the saved-presets surface is still
`/api/weather/*` and `weatherApi.ts` already owns every other endpoint under that prefix. Adding a
manager must not require touching another one (architecture.md) — this is the *same* manager, so
that rule does not apply, and one file stays the single place to look for "everything weather."

One new tag type is added to `instructorApi.ts`'s central `tagTypes` array — the exact
`CameraPositions` precedent, comment and all: "Owned by `features/weather/weatherApi.ts`, declared
here because RTK Query resolves tag types at `createApi` time — `injectEndpoints` cannot add one."

```ts
tagTypes: [
  // … existing …
  'WeatherPresets',   // NEW — owned by features/weather/weatherApi.ts
],
```

Also new in `instructorApi.ts` itself (inline, exactly where `searchAirports`/`getRunways`/
`getIls`/`getParking`/`getProcedures`/`getHolds` already live — every other navdata read is inline
here, not in a per-feature file):

```ts
getAirport: builder.query<Airport, string>({
  query: (icao) => `navdata/airports/${icao}`,
  providesTags: (_result, _error, icao) => [{ type: 'Airport', id: icao }],
}),
```

This endpoint already exists server-side (`GET /api/navdata/airports/{icao}`,
`server/navdata_routes.py`) — this is client wiring only, never a server change, consistent with
WS-5's own pin. Both `instructorApi.ts` edits are assigned to track #185 (§10): that is the first
track that actually needs `fieldElevationFt` threaded through the recomposed panel.

New in `weatherApi.ts`:

| Endpoint | Kind | Notes |
|---|---|---|
| `listSavedWeatherPresets` | query, provides `WeatherPresets` | `GET saved-presets`; fetched when the saved-presets panel mounts |
| `createSavedWeatherPreset` | mutation, invalidates `WeatherPresets` | `POST saved-presets`; body's `setup` built from a fully-populated `mergeForDisplay(current, overrides)` (§8.3) |
| `replaceSavedWeatherPreset` | mutation, invalidates `WeatherPresets` | `PUT saved-presets/{id}` |
| `deleteSavedWeatherPreset` | mutation, invalidates `WeatherPresets` | `DELETE saved-presets/{id}` |

No `reapplySavedWeatherPreset` endpoint (§2.2) — reapplying stages the saved `setup` through the
existing manual-mode dispatch and then calls the existing `useApplyWeatherMutation`.

### 8.2 The atmosphere-profile projection module + component

`ui/src/features/weather/atmosphereProjection.ts` — pure, `procedureProjection.ts`'s idiom:

```ts
export const MIN_SCALE_TOP_FT = 10_000;
export const SCALE_TOP_MARGIN_FT = 2_000;
export const SNAP_FT = 100;
export const MIN_CLOUD_THICKNESS_FT = 100;

export interface AltitudeScale {
  readonly topFt: number;     // max(10000, highest wind altitude / cloud tops + 2000)
  readonly bottomFt: 0;
}

/** WS-3's scale rule, computed once from both layer lists so cloud tops and wind
 * layers share one axis. */
export function computeAltitudeScale(
  windLayers: readonly WindLayer[],
  cloudLayers: readonly CloudLayer[],
): AltitudeScale { /* … */ }

export function altitudeToY(altitudeFt: number, scale: AltitudeScale, viewboxHeightPx: number): number { /* … */ }
export function yToAltitude(yPx: number, scale: AltitudeScale, viewboxHeightPx: number): number { /* … */ }

/** Nearest 100 ft — WS-3's drag snap. */
export function snapAltitudeFt(altitudeFt: number): number { /* … */ }

export interface ProjectedCloudLayer {
  readonly layer: CloudLayer;
  readonly baseY: number;
  readonly topsY: number;
}
export interface ProjectedWindLayer {
  readonly layer: WindLayer;
  readonly y: number;
}

export function projectCloudLayers(
  layers: readonly CloudLayer[], scale: AltitudeScale, viewboxHeightPx: number,
): readonly ProjectedCloudLayer[] { /* … */ }

export function projectWindLayers(
  layers: readonly WindLayer[], scale: AltitudeScale, viewboxHeightPx: number,
): readonly ProjectedWindLayer[] { /* … */ }

/** Secondary AGL label, null-tolerant (WS-3): `null` field elevation means "MSL only",
 * never a thrown error and never a fabricated 0-ft ground reference. */
export function aglLabel(altitudeFt: number, fieldElevationFt: number | null): string | null { /* … */ }
```

Reference computation used again in §9: with `VIEWBOX_H = 480` px, a wind layer at 8 000 ft
against a scale topped at `max(10000, 8000+2000) = 10000` ft projects to
`y = 480 × (1 − 8000/10000) = 96`.

`ui/src/features/weather/AtmosphereProfile.tsx` — props-only, `ProcedureDiagram`'s shape exactly:

```ts
export interface AtmosphereProfileProps {
  readonly windLayers: readonly WindLayer[];
  readonly cloudLayers: readonly CloudLayer[];
  readonly fieldElevationFt: number | null;   // null-tolerant (WS-3)
  readonly disabled: boolean;                  // the existing weatherGate, threaded down
  readonly onCloudLayersChange: (layers: CloudLayer[]) => void;  // whole-list replace (D3)
  readonly onWindLayersChange: (layers: WindLayer[]) => void;    // whole-list replace (D3)
}

export function AtmosphereProfile(props: AtmosphereProfileProps) { /* … */ }
```

No `useSelector`, no RTK Query hook inside this component — both layer lists and
`fieldElevationFt` arrive as props from `WeatherPanel.tsx`, the exact boundary
`ProcedureDiagram.tsx`'s own docstring states ("Pure props → SVG, no store access").

Drawing: a terrain band (a filled rect from `bottomFt` to `fieldElevationFt`, omitted entirely
when `fieldElevationFt` is `null`); one horizontal band per cloud layer, `fill-opacity` from
`coverage_ratio`, a glyph per `cloud_type` (icon choice left to the implementer — §11.3, not a
contract question); a wind-barb column in a side gutter, one barb per wind layer rotated to
`direction_deg` (visual only — WS-3 defers drag-to-rotate; direction/speed stay numeric fields in
the field editors).

**The drag technique — `ProcedureDiagram`/`CircuitDiagram`'s dual-draw rule, extended to a
continuous drag.** Every draggable edge (a cloud base, a cloud tops, a wind-layer altitude) is
drawn twice:

1. An `aria-hidden` SVG shape (the band edge, or the barb) at its projected `y` — purely visual.
2. A native, **vertically-oriented `<input type="range">`**, absolutely positioned in **container
   percentages, never viewBox pixels** — `CircuitDiagram.tsx`'s own stated reason applies
   unchanged: the SVG scales down on a tablet, and a viewBox-pixel-positioned element drifts off
   its visual target on any narrower viewport. `min`/`max` bound to the altitude scale,
   `step={SNAP_FT}`, sized to at least 44 px along its own (rotated) width.

This reuses `SliderControl`'s already-established **commit-on-release** rule
(`ControlWidgets.tsx`: a local `draft` during drag, `onPointerUp`/`onKeyUp`/`onBlur` commit)
rather than dispatching `overrideSet` on every `onChange` — a drag from 2 500 ft to 4 000 ft sends
one command, not fifteen — and native range semantics give arrow-key accessibility for free,
without a hand-rolled pointer-event handler. On commit: the edited layer's altitude is snapped
(`snapAltitudeFt`), and the **whole** `cloud_layers`/`wind_layers` list — with only that one
layer's `base_ft`/`tops_ft`/`altitude_ft` replaced — is passed to `onCloudLayersChange` /
`onWindLayersChange`, which `WeatherPanel.tsx` wires straight to
`overrideSet({ field: 'cloud_layers', value: layers })` (D3's wholesale-replace). A cloud-edge
drag additionally clamps the dragged value so `tops_ft > base_ft + MIN_CLOUD_THICKNESS_FT` holds
**before** the value is ever committed, not after — the instructor never sees an invalid layer
flash on screen.

*The exact cross-browser CSS technique for a vertically-oriented range input is not settled here
— see §11.2.*

### 8.3 `WeatherPanel.tsx` recomposition (WS-6, track #185)

Component tree, top to bottom / left to right, landscape (portrait stacks under the same
breakpoint discipline `.weather-grid` already uses):

```
<WeatherPanel>
  <h2>Weather</h2>
  {gate reason paragraph, applied-flash — unchanged from the shipped panel}

  <div class="weather-station-grid">                    (* WS-6, new *)
    <AtmosphereProfile                                    (* #183's component, mounted here *)
      windLayers={resolved.wind_layers}
      cloudLayers={resolved.cloud_layers}
      fieldElevationFt={fieldElevationFt}                  (* new getAirport() read, §8.1 *)
      disabled={!gate.open}
      onCloudLayersChange={(layers) => setField('cloud_layers', layers)}
      onWindLayersChange={(layers) => setField('wind_layers', layers)}
    />
    <div class="weather-station-grid__right">
      <CurrentWeather current={current} />                 (* existing, unchanged *)
      <PresetGrid ... />                                    (* existing, unchanged behaviour *)
      <SavedPresetsPanel />                                 (* NEW STUB — #185 creates empty;
                                                                 #186 fills it in, Wave 3 *)
      <IlsMinimaControl
        fieldElevationFt={fieldElevationFt}                 (* NEW STUB — #185 creates empty;
        disabled={selectedIcao === null}                       #187 fills it in, Wave 3 *)
      />
      <StationEditors                                       (* NEW — wraps the existing
        resolved={resolved}                                    Wind/Cloud/Atmosphere editors,
        disabled={applyState.isLoading}                        #185 extracts them here *)
        onField={setField}
        onContamination={...}
      />
    </div>
  </div>

  <WeatherStagingBar ... />                                 (* existing, spans the bottom,
                                                                 unchanged *)
</WeatherPanel>
```

**The two stub components are the load-bearing mechanism that makes Wave 3 file-disjoint.**
`SavedPresetsPanel.tsx` and `IlsMinimaControl.tsx` are created by #185 as minimal placeholders
(e.g. `return null;`) and mounted at their final position in the grid. #186 and #187 then each
edit **only their own stub's file** in Wave 3, never touching `WeatherPanel.tsx` again — that is
what keeps the two Wave-3 tracks disjoint despite running concurrently. Without this pre-split,
both would need to edit `WeatherPanel.tsx` to mount their own new UI, which is exactly the
collision WS-6's "pre-split" sentence exists to avoid.

Also new in this track: the WS-1/WS-2 display/apply branching (`weatherSource`, skip
`usePreviewWeatherQuery` and use `mergeForDisplay(current, overrides)` directly in manual mode,
`buildManualWeatherRequest` in `commit()` when in manual mode, and §4.1's empty-overrides
Apply-disabled guard) is **already implemented by #182 in Wave 1** — this track's job is to route
that already-landed branching, and the already-shipped preset-mode branch, into the recomposed
layout, not to invent the branching itself.

`weather.css` gains `.weather-station-grid` — a two-column CSS grid on landscape/tablet-wide
(`grid-template-columns: 3fr 2fr`, tuned by the implementer to WS-6's "~60% landscape"; §11.5
records this as an approximate, not a pinned, figure), collapsing to one stacked column under the
same portrait breakpoint `.weather-grid` already treats as "tablet portrait."

### 8.4 Gating

**No new capability flag gates anything in this document** (§5). The existing `weatherGate`
(`gate.ts`) is unchanged and still closes the whole panel — including manual editing, the
atmosphere-profile drag, and the ILS-minima control — because every one of them ultimately stages
a `WeatherRequest` that only `POST /api/weather/apply` can commit, and that call still needs
`can_set_weather`; `weatherGate`'s own stated reasoning ("a weather preview cannot even show a
current-weather baseline to compose over") applies unchanged to manual mode's `mergeForDisplay`
baseline, which is `current` — itself only readable when the gate is open.

**What WS-4 actually pins**, precisely: the **saved-presets CRUD surface** (list/save/replace/
delete) is reachable regardless of `weatherGate`, because it touches neither the adapter nor
navdata — `SavedPresetsPanel` lets the instructor browse, save and delete presets even against an
adapter declaring `can_set_weather=False`. Only the "reapply" action inside it (which stages
through the ordinary manual path and then calls the ordinary `applyWeather` mutation) is subject
to the same gate everything else already is. `IlsMinimaControl`'s own, separate disablement
(`disabled={selectedIcao === null}`, WS-5) is additive to `weatherGate`, not a replacement for it.

Tablet-first notes: every new draggable input keeps the ≥44 px rule (§8.2); the saved-presets list
and the ILS segmented control reuse `.weather-tile`'s sizing; the two-column grid collapses at the
same width the rest of the Instructor Panel already treats as "portrait tablet."

---

## 9. Test plan

### 9.1 `core/` store tests — `tests/core/weather_presets/`

`test_store.py`, `tests/core/profiles/test_store.py`'s exact scenario set, transplanted:

- create → get round-trips exactly
- create assigns a 32-char uuid4-hex id
- create sets `created_at == updated_at`
- get on an unknown id → `None`
- directory is not created until the first write
- a traversal-shaped id (`../secret`) → `get` `None`, `delete` `False`, the file untouched
- an id of the wrong length, or non-hex → `None`
- `list()` on an empty/missing directory → `[]`
- `list()` skips a corrupt file without raising, and logs a warning
- `list()` sorts newest `updated_at` first (fixed-clock pattern, the same coarse-wall-clock
  reasoning `tests/core/profiles/test_store.py`'s own comment gives)
- `replace` on an unknown id → `None`, never creates
- `replace` keeps `preset_id`/`created_at`, bumps `updated_at`
- `delete` on an unknown id → `False`; `delete` twice → `False` the second time
- `get` on unparseable content → raises `WeatherPresetStoreError`, not `None`
- **new to this store, not in the profile suite**: `create`/`replace` with a sparse
  `WeatherSetup` (any one field `None`) raises `pydantic.ValidationError` before the store is
  ever touched — table-driven over every optional field of `WeatherSetup`, `wind_layers`/
  `cloud_layers` included explicitly (`None` refused, `[]` accepted)

`test_paths.py`: the three per-OS branches (`Windows`/`APPDATA`, `Darwin`/Application Support,
Linux/`XDG_DATA_HOME` + `~/.local/share` fallback), `environ` injected exactly as
`tests/core/profiles/test_paths.py`'s convention, leaf directory name `weather_presets`.

### 9.2 Server route tests — `tests/server/test_weather_preset_routes.py`

Against the Fake via `TestClient`: every CRUD route; the fully-populated-setup 422 (§2.1); both
404 sentences (plain vs "may already be deleted"); a store failure surfaced as 500 (a
monkeypatched store raising `WeatherPresetStoreError`); every route called against an adapter with
`can_set_weather=False` still answers ordinary 2xx/404 — **never 501** (§2.2's "no capability
gate" claim, asserted rather than trusted). `tests/server/test_weather_routes.py`'s existing
cases are asserted **unchanged** — no new test added there, no behaviour changed — so a diff on
that file during review is a red flag, not an expectation.

### 9.3 UI tests (vitest) — `ui/src/features/weather/`

- **`weatherSlice.test.ts`**: `weatherSource` returns `null`/`'preset'`/`'manual'` for the three
  reachable states; `overrideSet` on an un-staged slice sets `staged=true` with
  `selectedPresetId` still `null`; `overrideSet` on an already-preset-staged slice leaves
  `selectedPresetId` untouched (an override on top of a preset stays preset mode);
  `presetStaged`/`stagingCleared`/the `airportSelected` reset are re-asserted **unchanged**
  against the existing passing cases — a regression guard.
- **`resolve.test.ts`**: `buildManualWeatherRequest({ visibility_m: 5000 })` →
  `{ preset: null, airport_icao: null, runway_ident: null, setup: { visibility_m: 5000 } }`;
  existing `mergeForDisplay` cases stay as already tested.
- **`atmosphereProjection.test.ts`**: `computeAltitudeScale` — no layers → `topFt = 10000`; a
  cloud layer topping at 9 500 ft → `topFt = 11500`; a wind layer at 12 000 ft →
  `topFt = 14000`. Projection — the §8.2 worked reference (`VIEWBOX_H=480`, 8 000 ft against a
  10 000 ft-topped scale → `y=96`), plus `0` ft → `y=480` and `topFt` → `y=0`.
  `snapAltitudeFt(2530) === 2500`; `snapAltitudeFt(2551) === 2600`.
- **`AtmosphereProfile.test.tsx`**: the terrain band renders only when `fieldElevationFt !== null`;
  a drag-and-release on a cloud-tops range input calls `onCloudLayersChange` **once** (not per
  intermediate `onChange`) with the whole list, snapped, and with `tops_ft > base_ft + 100`
  enforced even when the raw drag would have violated it.
- **`ilsMinima.test.ts`**: `ilsMinimaOverrides(800, 200, 1000)` →
  `{ visibility_m: 800, cloud_layers: [{ base_ft: 1250, tops_ft: 3250, coverage_ratio: 1, cloud_type: 'stratus' }] }`
  — §4.3's worked example, verbatim.
- **`SavedPresetsPanel.test.tsx`** (#186): the list renders every returned preset; save builds a
  fully-populated `WeatherSetup` from `mergeForDisplay(current, overrides)` (asserted field by
  field, layer fields `[]` not omitted when empty); reapply dispatches the saved `setup` through
  the manual-mode path and hits **only** `POST /api/weather/apply` — never a
  `saved-presets/.../apply` URL, since none exists (§2.2).
- **`IlsMinimaControl.test.tsx`** (#187): each category button stages the pinned defaults
  (800/200, 350/100, 125/50); editing RVR/DH before staging carries the edited values, not the
  defaults; disabled with a stated reason when no airport is selected.

### 9.4 What is `@pytest.mark.sim`

**None of this document's own surface.** The saved-presets store/routes never reach the adapter or
navdata; every manual/saved-preset/ILS-minima staging path reuses `POST /api/weather/apply`, whose
live behaviour is already proven by weather-manager.md's own `-m sim` suite (its §9.5) and is not
re-verified here. If the panel smoke ever needs a live check, it is the existing `sim-validator`
weather step, unchanged.

### 9.5 Fixtures

None beyond what exists. The saved-presets store's tests are `tmp_path`-backed exactly like
`tests/core/profiles/test_store.py` (hard rule 4 — nothing here is a navdata fixture);
`fieldElevationFt` is read live through the existing `/api/navdata/airports/{icao}` endpoint at
request time, never cached in a fixture the way an embedded scenario placement is.

---

## 10. Parallelisation

Wave/dependency graph, from epic #179:

Wave 0 (#180, this document, **serial**) → Wave 1 (#182 free-form editing, #183 atmosphere
profile SVG delivered unmounted, #184 saved-presets store + routes — **3 parallel, file-disjoint
by construction**) → Wave 2 (#185 station layout recomposition, **serial** — `WeatherPanel.tsx` is
the shared file) → Wave 3 (#186 saved-presets UI + sole `schema.d.ts` regen, #187 ILS minima
control — **2 parallel**).

Dependency graph: `#180 → {#182, #183, #184}`; `{#182, #183} → #185`; `{#184, #185} → #186`;
`#185 → #187`.

| Track | What | Owns (disjoint) | May start |
|---|---|---|---|
| **#180 — this document, SERIALISED** | The full contract: endpoints, models, slice derivation, projection-module signatures, the CRUD table | `docs/designs/weather-station.md` | first, alone |
| **#182 — free-form manual editing** | WS-1's reducer change and `weatherSource`; WS-2's `buildManualWeatherRequest`; the manual-mode branch wired into the *shipped* `WeatherPanel.tsx` (skip preview, `mergeForDisplay` display, manual Apply, the §4.1 empty-overrides Apply-disabled guard); generalising the existing field editors so they render with nothing staged | `ui/src/features/weather/weatherSlice.ts`, `resolve.ts`, `WeatherPanel.tsx`, `WindLayerEditor.tsx`, `CloudLayerEditor.tsx`, `AtmosphereForm.tsx`, and their existing test files | after #180 |
| **#183 — atmosphere profile, delivered unmounted** | `atmosphereProjection.ts` + `AtmosphereProfile.tsx`, the drag-to-snap interaction, fully unit- and component-tested in isolation. **Not imported by `WeatherPanel.tsx` in this wave** — that is precisely what keeps it from contending with #182's concurrent edit to that same file | `ui/src/features/weather/atmosphereProjection.ts`, `AtmosphereProfile.tsx`, their tests | after #180 |
| **#184 — saved-presets store + routes** | `core/weather_presets/` in full (§6), `server/weather_preset_routes.py` (§2), plus two tiny shared-file edits: `server/app.py` (one `include_router` line) and `server/deps.py` (`WeatherPresetStore` singleton wiring, `Settings.weather_presets_root`, folded into `reset_adapter()`'s cache-clear alongside the profile/camera stores) | `core/weather_presets/`, `server/weather_preset_routes.py`, `server/app.py`, `server/deps.py`, `tests/core/weather_presets/`, `tests/server/test_weather_preset_routes.py` | after #180. Its two shared-file edits conflict with nothing else in Wave 1 — #182/#183 never touch `server/` |
| **#185 — station layout recomposition, SERIALISED** | Mounts #183's `AtmosphereProfile` (wired to live layers + `fieldElevationFt`); extracts the existing editors into `StationEditors.tsx`; the `.weather-station-grid` CSS; creates the two Wave-3 mount-point **stubs** `SavedPresetsPanel.tsx`/`IlsMinimaControl.tsx` (empty, so #186/#187 never need to touch `WeatherPanel.tsx`); adds `getAirport` and the `WeatherPresets` tag to `instructorApi.ts` | `ui/src/features/weather/WeatherPanel.tsx`, `StationEditors.tsx` (new), `SavedPresetsPanel.tsx`/`IlsMinimaControl.tsx` (new, stub), `weather.css`, `ui/src/api/instructorApi.ts` | after **both** #182 and #183 have merged |
| **#186 — saved-presets UI + sole `schema.d.ts` regen** | Fills in `SavedPresetsPanel.tsx`; the CRUD endpoints in `weatherApi.ts` (§8.1); runs `npm run generate:api` **once**, after #184 is merged | `ui/src/features/weather/SavedPresetsPanel.tsx`, `weatherApi.ts`, `ui/src/api/schema.d.ts` (and whatever else the regen emits) | after **both** #184 and #185 have merged |
| **#187 — ILS minima control** | Fills in `IlsMinimaControl.tsx`; `ilsMinimaOverrides` and the category catalogue (§4.3) in a new `ilsMinima.ts` — deliberately not `resolve.ts`, which #182 owns and this track must not reopen | `ui/src/features/weather/IlsMinimaControl.tsx`, `ilsMinima.ts` (new) | after #185 has merged |

**Dispatch:** `{#182, #183, #184}` in one message, three worktrees, once #180 is reviewed and
landed. `#185` dispatched alone once both #182 and #183 have merged. `{#186, #187}` dispatched in
one message once #185 has merged — #186 additionally needs #184 merged (its regen has to include
the saved-presets schema); #187 does not.

**Why the single `schema.d.ts` regen in #186 is safe:** no UI code in Wave 1 or Wave 2 references
the saved-presets routes' generated types — #182/#183/#185 never import a `SavedWeatherPreset`
type. The CRUD surface exists server-side from #184 onward, but nothing on the client points at it
until #186 writes `weatherApi.ts`'s new endpoints in the *same* PR as the regen, so
`pytest`/`lint-ui`/`typecheck` stay green on every intermediate merge to `dev` without ever
carrying a stale or a not-yet-generated type — the exact hazard WS-7 exists to prevent.

**Never parallelised:** #180 (this document); any later change to
`WeatherSetup`/`WeatherRequest`/`WeatherState` (weather-manager.md's own contract vocabulary,
unchanged and unreopened by this entire series — §5); #185 running concurrently with anything else
that also touches `WeatherPanel.tsx`; the `schema.d.ts` regen running more than once in the series
(WS-7); merges to `dev`/`main`; release tagging. No `SimAdapter`/`Capabilities` change and no
navdata schema migration exists anywhere in this document (§5, §7), so neither constraint from
CLAUDE.md's "never parallelise" list is even in play here beyond the generic merge/tag rule.

---

## 11. Open questions and risks

### 11.1 `fieldElevationFt`'s source — resolved while writing this document

Neither WS-3 nor WS-5 named where the profile/ILS-minima control gets a field elevation from.
`GET /api/navdata/airports/{icao}` → `Airport.elevation_ft` already exists server-side
(`server/navdata_routes.py`); only its RTK Query wiring (§8.1, track #185) is new. Recorded here
rather than silently assumed, because getting this wrong would have been exactly the kind of gap
only a live click-through catches.

### 11.2 The exact cross-browser CSS for a vertically-oriented native range input — genuinely open

`writing-mode: vertical-lr` + `direction: rtl`, Firefox's `orient="vertical"` attribute, and a
plain `transform: rotate(-90deg)` on a horizontal input are all in general use, but this document
cannot assert from the repository which combination behaves correctly with **both** pointer and
keyboard input on the tablet browsers the instructor actually uses — no existing component in this
codebase renders a vertical range input to check against (`SliderControl` is horizontal;
`ProcedureDiagram`/`CircuitDiagram` use tap targets, not continuous drag). **Resolution:** a short
spike inside #183, before the drag interaction ships — render each candidate technique, drive it
with a pointer and with arrow keys in the actual target browser, and record the winner in
`AtmosphereProfile.tsx`'s own docstring, the way `xplane_adapter.py` records its own live-measured
findings.

### 11.3 Cloud-type glyph / icon choice

Left to #185/#183's implementer — not a contract question, since nothing downstream (a test,
another track) depends on which glyph is drawn, only on the underlying layer data being correct.
No resolution needed unless a later design wants a shared icon set across the panel.

### 11.4 `StationEditors.tsx`'s internal composition

Whether it is a thin wrapper re-exporting the three existing editor components unchanged, or an
actual merge of their JSX into one component, is left to #185's implementer. WS-6 only pins that
the extraction happens and that it is what makes Wave 3 file-disjoint (§10), not its internal
shape.

### 11.5 The grid's exact breakpoint and column ratio

"~60% landscape" (WS-6) is an approximate figure, not a pinned exact number. #185's implementer
tunes it against the same tablet viewport width the rest of the Instructor Panel already targets;
no test in §9 asserts a specific pixel ratio.

### 11.6 Saved-presets directory growth

Whether `WeatherPresetStore`'s directory should ever be swept or capped (an instructor who saves
fifty near-identical CAT-I variants) is not addressed. `core/camera/store.py`'s own precedent
("few and small") is assumed to hold here too, and nothing in WS-4 asks for a cap. Revisit if
instructors report clutter — the same "revisit if instructors ask" posture weather-manager.md's
own §2.4 takes for "reset to real weather."

---

## 12. Verification

```bash
pytest                       # unit + contract — the saved-presets store/routes are ordinary
                              # unit-tested Python; no new sim mark exists anywhere in this series
ruff check . && ruff format --check .
mypy .
cd ui && npm run lint && npm run typecheck && npm test && npm run build
```

No `pytest -m sim` gate exists for this document's own surface (§9.4); the existing weather
`-m sim` suite (weather-manager.md §9.5) is unaffected and unrun by this work.

Panel smoke (fake adapter + Vite dev server, one batched browser session, run once the full series
has landed): stage a preset, edit one field on top of it (still preset mode) → dismiss → edit a
field with nothing staged (enters manual mode, no `/preview` request in the network log) → Apply →
drag a cloud-tops handle on the atmosphere profile, release, confirm one `overrideSet` and the
whole layer list correctly replaced → save the current weather as a named preset → reload the
saved-presets list, reapply it (confirm the request hits `/api/weather/apply`, nothing else) → tap
CAT I on the ILS-minima control, confirm the staged cloud layer's base sits at field elevation +
250 ft → console clean throughout.
