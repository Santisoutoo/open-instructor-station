# Weather Manager — design

**Status:** designed, not yet implemented.
**Phase:** 2 — Weather + Failures → Scenario Generator ([`../roadmap.md`](../roadmap.md#phase-2--weather--failures--scenario-generator)).
**Feature spec:** manager 3 ([`../feature-spec.md`](../feature-spec.md#3-weather-manager)), ⭐⭐⭐⭐⭐.
**Depends on:** the Phase 0/1 contract (`core/sim_adapter.py`, `FakeSimAdapter`, the contract suite), the `NavdataProvider` (for runway-relative presets only), `core/atmosphere.py`.
**Blocks:** the Scenario Generator (manager 2) and Training Profiles (manager 14) — both compose weather and **wait for this manager**, per the Phase 2 parallelisation table.

Full manual control of the environment from the instructor station: wind, gusts, turbulence,
pressure, temperature, humidity, visibility, cloud layers, precipitation and icing conditions,
plus seven presets — `CAVOK`, `CAT I`, `CAT II`, `CAT III`, `Storm`, `Crosswind`,
`Mountain Wave`.

The one gotcha that shapes everything in `adapters/`: **X-Plane 12's real-weather mode
continuously overwrites manual weather datarefs.** The adapter forces manual mode before writing
anything, verifies the mode stuck, and the contract suite asserts a written value is still there
after the simulator's own update cycle has had a chance to destroy it. Roadmap Phase 2 exit
criterion 3 is exactly this, and it is handled **once, inside the adapter** — never per-setting,
never in `core/`, never in `server/`.

Binding rules live in [`../../CLAUDE.md`](../../CLAUDE.md); layers in
[`../architecture.md`](../architecture.md) (known risk 2 is this manager's). This document never
relaxes any of them. Where the Position Manager's as-built record
([`position-manager.md`](position-manager.md)) records a regret, this design states which lesson
it takes and does not repeat the mistake.

---

## 0. Decisions at a glance

| # | Decision | Where |
|---|---|---|
| D1 | **Two new `SimAdapter` methods, `get_weather()` / `set_weather()`, both behind the existing `can_set_weather` flag. No new capability flag.** The flag has existed since Phase 0; this manager gives it a contract. | §5 |
| D2 | **`set_weather` takes a sparse `WeatherSetup` — `None` means "leave that aspect untouched"** — exactly the `AircraftSetup` pattern. Presets are partial by nature (`Crosswind` states wind and nothing else), so partial semantics are the only ones that compose. | §3.2 |
| D3 | **Layer lists replace wholesale.** A provided `wind_layers` / `cloud_layers` list replaces the whole set; `[]` is a meaningful command (calm / clear skies); `None` leaves the layers alone. Element-wise merging of indexed layers has no defensible semantics. | §3.2 |
| D4 | **Read and write models are distinct**: `WeatherState` (every field required) and `WeatherSetup` (every field optional), mirroring `AircraftState` / `AircraftSetup`. | §3 |
| D5 | **Presets are `core/` data, and their relative parts are resolved by a pure `core/` function at apply time.** Runway-offset wind and AGL cloud bases resolve against a runway bearing and a field elevation passed in as plain numbers — `core/` never sees the provider. | §4, §6 |
| D6 | **The request model lives in `core/weather/models.py`, not in the router.** This is the Position Manager's recorded regret (its §7.6/§13: request models stranded in `server/` closed the door on scenario reuse) taken as a lesson: the Scenario Generator's YAML weather block deserialises into this same model with no import from `server/`. | §3.4, §6 |
| D7 | **Two POSTs — `preview` and `apply` — one request shape.** Preview resolves the preset and merges overrides, writes nothing, needs no capability. Apply re-resolves from scratch; a client can never hand the server a resolved setup and call it a preset. Same staging pattern the Position panel established (its D2/D3). | §2 |
| D8 | **`GET /api/weather/manifest` mirrors `GET /api/aircraft/controls`**: supported-or-not with a stated reason, plus the preset catalogue with per-preset requirements, so the UI hand-writes nothing and disables with reasons. | §2.3 |
| D9 | **Manual-mode forcing is an adapter concern, executed once per `set_weather` call, with a read-back verification that raises when the mode did not stick.** Architecture known risk 2, verbatim. | §5.3, §7 |
| D10 | **Wind and cloud layers are typed lists of at most 3**, the instructor-facing model. X-Plane 12's 13 wind levels are an adapter detail: the given layers are distributed over the levels and the levels above the highest given layer carry its values, so a one-layer preset means *uniform* wind, never a phantom shear. | §3.1, §7.4 |
| D11 | **Humidity is delivered as dewpoint.** METARs state temperature/dewpoint; fog is a spread of the two, which is exactly what the CAT presets need; and it is what X-Plane 12 actually models (`dewpoint_deg_c`). A humidity percentage would be converted twice and displayed never. | §3.1 |
| D12 | **"Ice" means icing *conditions* — cold saturated cloud and runway contamination.** Direct airframe ice injection (`sim/flightmodel/failures/frm_ice`, pitot ice) is a **Failures Manager** item and is out of scope here, recorded so the two managers cannot both claim it. | §1.2 |
| D13 | **Units are aviation-native and live in the field names**: `_kt`, `_ft` MSL, `_deg` true, `_c`, `qnh_hpa`, `visibility_m`, ratios 0–1. Every conversion to X-Plane's units (m/s, metres, Pa, statute miles) happens in the adapter and nowhere else. | §3.1, §7.2 |
| D14 | **No WebSocket change.** Weather is a command surface with a slow-moving read; the panel reads `GET /api/weather` on load and gets the post-write state in every apply response. Streaming actual conditions for the map is Phase 3's problem. | §2.4 |
| D15 | **The UI adds its endpoints with `injectEndpoints` from `ui/src/features/weather/weatherApi.ts`** — the rule the Position panel broke (its §15.3 deviation edited `instructorApi.ts` directly). Adding this manager adds files. | §8 |
| D16 | **The X-Plane adapter grows a refusing stub in the foundation commit** (`can_set_weather = False`, methods raise `CapabilityNotSupported`), so the protocol change lands green everywhere before the adapter track starts, and everything downstream reports "unavailable" honestly in the interim. | §5.2, §10 |

---

## 1. Scope

### 1.1 What this manager does

1. **Read the commanded weather** — one `WeatherState` snapshot of what the simulator has been
   told to do.
2. **Write it, sparsely** — any subset of: wind layers (direction, speed, gusts, turbulence),
   cloud layers (base, tops, coverage, type), visibility, QNH, temperature, dewpoint,
   precipitation, runway contamination. Untouched aspects stay untouched.
3. **Apply a preset** — the seven from the feature spec, resolved at apply time: `Crosswind` is
   "20 kt from 90° off the active runway" and the CAT ceilings are heights above *the chosen
   field*, so both resolve against navdata the moment the instructor picks an airport.
4. **Survive real-weather mode** — the adapter forces manual mode and verifies it stuck; a
   written value is still in force after the sim's own update cycle (roadmap exit criterion 3).
5. **Offer it as a panel** — a preset grid as the two-tap path, an editor for the full state,
   staged and previewed before anything is applied, disabled with a reason on adapters that
   cannot do weather (roadmap exit criterion 4's UI half).

It covers every feature-spec item of manager 3. It sits in **Phase 2** and must land before the
Scenario Generator, which composes it.

### 1.2 What is explicitly out of scope

| Out of scope | Owner / reason |
|---|---|
| Direct airframe ice, pitot ice, windscreen ice | **Failures Manager** (manager 4). They are failure injections with failure semantics (immediate / armed / cleared), not environment state. D12. |
| METAR display, real-world weather fetch | Instructor Map, Phase 3. This manager never fetches anything from the internet. |
| Per-altitude temperature ladders, thermals, wave-height sea state | Not instructor-facing. Temperature is one sea-level value; the adapter recomputes the aloft ladder along the ISA lapse (`core/atmosphere.py`) so the sim's profile stays coherent. |
| Snow *depth* on the ground / winter textures | Dataref availability across 12.x is unverified (§10.4). Runway contamination (wet/snow/ice friction) **is** in scope. |
| Weather over the WebSocket | D14. |
| Wind shear *scenarios* | The Scenario Generator composes them from this manager's layered wind. |
| MSFS | Phase 5. Expected to declare `can_set_weather = False` (Asobo locks weather injection); nothing here may assume otherwise. |

---

## 2. REST endpoints

All under `/api/weather/*`, in a new `server/weather_routes.py` (`server/app.py` gains one
`include_router` line — the only shared-file edit on the backend). Path and error conventions
follow `server/position_routes.py`: FastAPI `detail` sentences written for the instructor,
**501** for a missing capability, **404** for absent navdata objects, **422** for requests the
data cannot answer, **503** (app-level handler, already registered) when navdata is needed and
unavailable.

```
GET  /api/weather            -> WeatherState
GET  /api/weather/manifest   -> WeatherManifest
POST /api/weather/preview    -> WeatherPreview
POST /api/weather/apply      -> WeatherApplyResult
```

| Method | Path | Purpose | Safe? | Capability | Declared |
|---|---|---|---|---|---|
| `GET` | `/api/weather` | The commanded weather, read from the adapter | yes | `can_set_weather` → 501 | `async def` — awaits the adapter |
| `GET` | `/api/weather/manifest` | Supported-or-not with reason, plus the preset catalogue | yes | none — always 200 | `def` — pure data |
| `POST` | `/api/weather/preview` | Resolve preset + overrides into the exact `WeatherSetup` that *would* be written, with provenance notes. **Writes nothing, reads no adapter.** | **yes** | none | `def` — navdata read + arithmetic, threadpool |
| `POST` | `/api/weather/apply` | Re-resolve, `set_weather`, read back | no | `can_set_weather` → 501 | `async def` |

### 2.1 One request shape for preview and apply

Both POSTs take the same body, `WeatherRequest` (§3.4): an optional preset id, the optional
airport/runway context a relative preset needs, and an optional sparse `WeatherSetup` that is
either the whole instruction (no preset) or an overlay merged **over** the resolved preset.
Apply re-resolves from scratch — the resolution is a pure function of (navdata, request), so a
previewed request applies to the same answer, and a client cannot smuggle in a hand-built
"resolved preset" (D7, the Position Manager's D3 argument unchanged).

Order of operations in `apply`:

1. Resolve the navdata context in the threadpool (`run_in_threadpool`, same reasoning as the
   position router: blocking SQLite work must not stall the event loop serving `/ws/state`):
   runway → `true_bearing_deg`, airport → `elevation_ft`. Only when the request names them.
2. `core.weather.resolve_request(...)` → the merged `WeatherSetup` + notes (§6).
3. Gate: `can_set_weather` or 501.
4. `await adapter.set_weather(setup)` — inside which the adapter forces manual mode (§7).
5. `state = await adapter.get_weather()` — the read-back is the honest verdict.
6. Return `WeatherApplyResult(applied=setup, state=state, notes=notes)`.

**Idempotent**: the body states absolute targets, never deltas.

### 2.2 Errors

| Situation | Status | Detail |
|---|---|---|
| Neither `preset` nor `setup` in the request | 422 | `"A weather request must carry a preset, a setup, or both."` (pydantic model validator, so it lands in the schema) |
| Preset needs a runway (`Crosswind`) and none given | 422 | `"The 'crosswind' preset is relative to a runway; give airport_icao and runway_ident."` |
| Preset needs a field elevation (AGL clouds/wind) and no airport given | 422 | `"The 'cat_i' preset states cloud heights above the field; give airport_icao."` |
| Unknown preset id | 422 | FastAPI's own validation body — `WeatherPresetId` is a closed `Literal` |
| Airport / runway not in the index | 404 | `"Runway 32L is not published at LEMD."` — same sentences as the position router |
| Navdata index absent / building / errored, and the request needed it | 503 + `Retry-After` | the existing app-level `NavdataUnavailable` handler; a request with **no** airport context never touches navdata and can never 503 |
| Adapter does not declare `can_set_weather` (`GET /api/weather`, `POST …/apply`) | 501 | `"Unavailable on this adapter — the 'xplane' adapter does not declare can_set_weather, so it cannot control the weather."` |
| `CapabilityNotSupported` raised by the adapter anyway | 501 | defence in depth, same as `/api/aircraft/setup` |
| Adapter reports the weather mode would not stick (§7.3) | 502 | the adapter's own sentence, verbatim — the simulator refused, we are a gateway to it. This is the `502` the position doc listed as a missing follow-up; weather is where it first has a concrete producer. |

### 2.3 The manifest

`GET /api/weather/manifest` is this manager's `GET /api/aircraft/controls`: the single place the
panel learns what it may offer. It answers without touching navdata or the simulator (capability
flags are static; the preset catalogue is `core/` data), so it is always 200 and always fast.

### 2.4 What is deliberately not an endpoint

- **No `POST /api/weather/wind`, `/clouds`, …** One sparse model, one write path — fourteen
  endpoints for one merge was wrong for positions and is wrong here.
- **No preset-list endpoint separate from the manifest.** One round-trip populates the panel.
- **No WebSocket change** (D14).
- **No "reset to real weather".** Handing control back to X-Plane's real weather is a mode
  change the instructor makes in the sim if they want it; offering it externally would mean the
  station owns a mode it cannot then verify. Revisit if instructors ask.

---

## 3. Pydantic models

Units follow `core/models.py` house convention and are in the field name or its description:
`_ft` is feet MSL, `_kt` indicated knots (wind speeds: knots, full stop — there is no IAS/TAS
ambiguity for wind), `_deg` **true** degrees, `_c` Celsius, `_hpa` hectopascals, `_m` metres,
ratios are dimensionless 0–1. Everything below lives in **`core/weather/models.py`** (D6) except
the two response envelopes, which are HTTP furniture and live in `server/weather_routes.py`.

### 3.1 The layers

```python
MAX_WIND_LAYERS = 3
MAX_CLOUD_LAYERS = 3

CloudType = Literal["cirrus", "stratus", "cumulus", "cumulonimbus"]

RunwayContamination = Literal["dry", "wet", "puddles", "snow", "ice"]


class WindLayer(BaseModel):
    """One wind stratum. Direction is where the wind blows FROM, true degrees."""

    model_config = ConfigDict(frozen=True)

    altitude_ft: float = Field(ge=0.0, description="Layer altitude, feet MSL.")
    direction_deg: float = Field(
        ge=0.0,
        le=360.0,
        description="Direction the wind blows FROM, TRUE degrees (METAR convention, "
        "and what the simulator's dataref expects). ATIS/tower winds are "
        "magnetic; converting for display is the UI's business, not this model's.",
    )
    speed_kt: float = Field(ge=0.0, description="Sustained wind speed, knots.")
    gust_increase_kt: float = Field(
        default=0.0,
        ge=0.0,
        description="Peak gust above the sustained speed, knots. 20 kt gusting 30 is "
        "speed_kt=20, gust_increase_kt=10.",
    )
    turbulence_ratio: float = Field(
        default=0.0, ge=0.0, le=1.0, description="0 = smooth, 1 = severe."
    )


class CloudLayer(BaseModel):
    """One cloud stratum. Base below tops, both MSL."""

    model_config = ConfigDict(frozen=True)

    base_ft: float = Field(description="Cloud base, feet MSL.")
    tops_ft: float = Field(description="Cloud tops, feet MSL. Must exceed base_ft (validator).")
    coverage_ratio: float = Field(
        ge=0.0,
        le=1.0,
        description="Sky cover 0–1. Octas are display: FEW≈0.2, SCT≈0.44, BKN≈0.75, OVC=1.0.",
    )
    cloud_type: CloudType = Field(default="cumulus")
```

Validators: `CloudLayer` — `tops_ft > base_ft`. Both list fields (below) — at most 3 entries,
sorted ascending by altitude/base, no two layers within 100 ft of each other (a zero-thickness
sandwich is a data error, not a weather).

### 3.2 The state and the setup

```python
class WeatherState(BaseModel):
    """The commanded weather, fully populated — what get_weather() returns."""

    wind_layers: list[WindLayer] = Field(description="Ascending by altitude. May be empty (calm).")
    cloud_layers: list[CloudLayer] = Field(description="Ascending by base. May be empty (clear).")
    visibility_m: float = Field(
        ge=0.0,
        description="Surface visibility in METRES (CAT minima "
        "are metres; the adapter converts to the sim's unit).",
    )
    qnh_hpa: float = Field(ge=900.0, le=1100.0, description="Sea-level pressure, hectopascals.")
    temperature_c: float = Field(ge=-60.0, le=60.0, description="Sea-level temperature, Celsius.")
    dewpoint_c: float = Field(
        ge=-60.0,
        le=60.0,
        description="Sea-level dewpoint, Celsius. "
        "Never above temperature_c (validator clamps on read, refuses on "
        "write). This is the feature spec's 'humidity' (D11).",
    )
    precipitation_ratio: float = Field(
        ge=0.0,
        le=1.0,
        description="0 = none, 1 = torrential. "
        "Falls as snow when the temperature says so — the phase "
        "is the simulator's decision, not a second field.",
    )
    runway_contamination: RunwayContamination = Field(description="Surface state for friction.")


class WeatherSetup(BaseModel):
    """The sparse write model. None means 'leave that aspect of the weather untouched'.

    Layer-list semantics (D3): None = untouched; a list REPLACES the whole set of
    layers; [] commands calm winds / clear skies. There is no per-layer merge.
    """

    wind_layers: list[WindLayer] | None = None
    cloud_layers: list[CloudLayer] | None = None
    visibility_m: float | None = Field(default=None, ge=0.0)
    qnh_hpa: float | None = Field(default=None, ge=900.0, le=1100.0)
    temperature_c: float | None = Field(default=None, ge=-60.0, le=60.0)
    dewpoint_c: float | None = Field(default=None, ge=-60.0, le=60.0)
    precipitation_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    runway_contamination: RunwayContamination | None = None
```

Both models are as narrow as the feature spec allows on purpose. What is *not* here, and why:
no `turbulence` scalar outside the wind layers (turbulence is a property of an air mass at an
altitude — a global knob would fight the layered one); no `wind_shear` field (shear **is** two
layers that disagree — the Scenario Generator's wind-shear scenario is data over this model, no
code); no ISA-deviation or per-level temperature (out of scope, §1.2).

### 3.3 The presets

```python
WeatherPresetId = Literal[
    "cavok", "cat_i", "cat_ii", "cat_iii", "storm", "crosswind", "mountain_wave"
]


class PresetWindLayer(BaseModel):
    """A preset's wind stratum: altitude AGL, direction absolute or runway-relative."""

    model_config = ConfigDict(frozen=True)

    altitude_agl_ft: float = Field(ge=0.0, description="Above the chosen field's elevation.")
    direction_deg: float | None = Field(
        default=None,
        description="TRUE degrees, absolute. Exactly one of this and offset is set (validator).",
    )
    offset_from_runway_deg: float | None = Field(
        default=None,
        ge=-180.0,
        le=180.0,
        description="Added to the runway's true bearing; +90 = wind from the right.",
    )
    speed_kt: float = Field(ge=0.0)
    gust_increase_kt: float = Field(default=0.0, ge=0.0)
    turbulence_ratio: float = Field(default=0.0, ge=0.0, le=1.0)


class PresetCloudLayer(BaseModel):
    """A preset's cloud stratum, heights above the field."""

    model_config = ConfigDict(frozen=True)

    base_agl_ft: float
    tops_agl_ft: float  # > base_agl_ft (validator)
    coverage_ratio: float = Field(ge=0.0, le=1.0)
    cloud_type: CloudType


class WeatherPreset(BaseModel):
    """One named preset. Pure data — resolution is core.weather.presets.resolve_preset."""

    model_config = ConfigDict(frozen=True)

    id: WeatherPresetId
    label: str  # "CAT II", "Crosswind", …
    description: str  # one sentence for the tile
    wind_layers: tuple[PresetWindLayer, ...] | None = None
    cloud_layers: tuple[PresetCloudLayer, ...] | None = None
    setup: WeatherSetup = WeatherSetup()  # the absolute scalar part

    @property
    def requires_runway(self) -> bool: ...  # any wind layer with an offset
    @property
    def requires_airport(self) -> bool: ...  # any AGL content (wind or cloud layers)
```

Why AGL inside presets and MSL on the wire: a preset is authored once for every airport on
Earth — "ceiling 120 ft" only means CAT II *above the field* — while the simulator, and
therefore `WeatherState`/`WeatherSetup`, speaks MSL. The conversion is done exactly once, in
`resolve_preset`, and the resolved MSL values are what preview shows and apply writes. This is
the same shape as the feature spec's note that crosswind presets "are resolved against the
active runway at apply time, which is why the preset catalogue lives in `core/`".

### 3.4 The request and the envelopes

In `core/weather/models.py` (D6 — the Scenario Generator's YAML weather block validates against
this exact model):

```python
class WeatherRequest(BaseModel):
    """One weather instruction: a preset, an explicit setup, or a preset with overrides."""

    model_config = ConfigDict(frozen=True, extra="forbid")  # a typo'd field in a scenario
    # YAML must fail loudly at load
    # time — the position models
    # dropped this and regretted it

    preset: WeatherPresetId | None = None
    airport_icao: str | None = Field(default=None, min_length=2, max_length=7)
    runway_ident: str | None = Field(default=None, min_length=1, max_length=3)
    setup: WeatherSetup | None = None  # the whole instruction, or the overlay over the preset

    # model_validator: at least one of preset / setup.
```

In `server/weather_routes.py` (HTTP furniture only):

```python
class WeatherPreview(BaseModel):
    request: WeatherRequest
    setup: WeatherSetup  # resolved + merged: exactly what apply would write
    notes: tuple[str, ...] = ()  # provenance sentences, rendered verbatim by the UI


class WeatherApplyResult(BaseModel):
    applied: WeatherSetup  # what was written
    state: WeatherState  # the read-back — the honest verdict
    notes: tuple[str, ...] = ()


class WeatherPresetInfo(BaseModel):
    id: WeatherPresetId
    label: str
    description: str
    requires_runway: bool
    requires_airport: bool


class WeatherManifest(BaseModel):
    adapter: str
    supported: bool
    reason: str | None  # "The 'msfs' adapter does not declare can_set_weather."
    presets: list[WeatherPresetInfo]
```

`notes` follows the Position Manager's staging-bar convention — sentences the UI renders and
never re-derives:

- `"Wind 090° at 20 kt gusting 25 — 90° right of runway 36's true bearing of 000°."`
- `"Cloud base 1,250 ft MSL — 250 ft above ZZZZ's field elevation of 1,000 ft (CAT I ceiling)."`
- `"visibility_m 1,200 — your override; the CAT I preset states 800."`

The position doc's warning about prose notes (its §7.4 deviation: substring matching is brittle)
is acknowledged and accepted again, deliberately: this panel renders notes as a block under the
staged values and never branches on them, so no code is added until something needs to branch.

---

## 4. The preset catalogue — exact values

`core/weather/presets.py::WEATHER_PRESETS: Mapping[WeatherPresetId, WeatherPreset]`. Pure data.
Presets are **partial** (D2): a field a preset does not state is left untouched, which is what
makes them compose — `CAVOK` then `Crosswind` is a clear day with a crosswind, and an
instructor's manual visibility tweak survives a later `Crosswind` application.

| Preset | Wind (AGL) | Clouds (AGL) | Vis (m) | QNH (hPa) | Temp / Dew (°C) | Precip | Contamination |
|---|---|---|---|---|---|---|---|
| **`cavok`** | — (untouched) | `[]` — clear | 20 000 | 1013.25 | 15 / 5 | 0.0 | dry |
| **`cat_i`** | — | OVC (1.0) stratus 250–2 500 | 800 | — | 12 / 12 | 0.2 | wet |
| **`cat_ii`** | — | OVC (1.0) stratus 120–2 000 | 350 | — | 10 / 10 | 0.1 | wet |
| **`cat_iii`** | 0 ft: from 360° at 3 kt | OVC (1.0) stratus 50–1 500 | 125 | — | 8 / 8 | 0.0 | wet |
| **`storm`** | 0 ft: from 240° at 25 G+15, turb 0.7 | 0.75 cumulonimbus 4 000–35 000 | 3 000 | 998.0 | 22 / 20 | 1.0 | puddles |
| **`crosswind`** | 0 ft: **offset +90°** at 20 G+5, turb 0.2 | — | — | — | — | — | — |
| **`mountain_wave`** | 0 ft: 270° at 15; 8 000 ft: 270° at 35, turb 0.3; 24 000 ft: 270° at 65, turb 0.6 | — | — | — | — | — | — |

Reasoning worth pinning:

- **The CAT ceilings sit just above their decision heights** (CAT I DH 200 ft → base 250;
  CAT II DH 100 → base 120; CAT III → base 50), so a well-flown approach breaks out at minima —
  the training point — rather than never or trivially early. Visibilities are the RVR minima
  families (800 / 350 / 125 m).
- **Saturated air in every CAT preset** (`dewpoint = temperature`): fog and stratus are a zero
  spread, and it is the dewpoint that makes the visibility physically coherent rather than a
  floating number (D11).
- **`cat_iii` states a 3 kt wind** because radiation fog does not survive wind; the other CAT
  presets leave wind untouched so they compose with `crosswind`.
- **`crosswind` states wind and nothing else** — the feature spec's "relative" preset in its
  purest form. `+90°` means wind from the right; an instructor wanting it from the left applies
  an override or the UI offers both signs.
- **`mountain_wave` is absolute** (from 270°, strengthening and roughening with altitude): the
  station has no ridge-line data to be relative to, and the training value is the profile, not
  the compass direction. Its layers are AGL so it works at Innsbruck and at sea level alike;
  `requires_airport` is therefore true.
- **`cavok` resets the sky and the air-mass scalars and leaves wind alone.** QNH 1013.25 and
  15 °C are ISA, so "CAVOK then whatever the exercise needs" starts every scenario from the
  same atmosphere.

Resolution reference values (these are the unit-test numbers, §9.1): against the test world's
airport `ZZZZ` (elevation 1 000 ft, runway 36 true bearing 000°): `crosswind` resolves to a
surface layer **from 090.0° true at 20 kt gusting 25**; `cat_i` resolves to a stratus layer
**base 1 250 ft MSL, tops 3 500 ft MSL**; `mountain_wave`'s middle layer resolves to
**9 000 ft MSL**.

---

## 5. `SimAdapter` / `Capabilities` additions

> **This section is a shared-foundation change and is never parallelised.** It is made once,
> alone, on the branch, before the backend / adapter / UI tracks branch off it (§10, track W0).

### 5.1 The contract

**No new capability flag.** `can_set_weather` has existed on `Capabilities` since Phase 0 with
`PENDING` coverage in the contract suite; this manager retires the `PENDING`. Two methods are
added to the `SimAdapter` protocol:

```python
async def get_weather(self) -> WeatherState:
    """Read the commanded weather.

    Requires Capabilities.can_set_weather — one flag gates the pair. Weather is
    the one surface where the read has no consumer without the write: the panel
    that displays it is the panel that edits it, and an adapter that cannot
    control weather has no tab to feed. Splitting a can_read_weather off is a
    one-line change the day the MSFS adapter proves it can read but not write;
    it is deliberately not made on speculation.
    """
    ...


async def set_weather(self, setup: WeatherSetup) -> None:
    """Apply every field of ``setup`` that is not None, leaving the rest untouched.

    List fields replace wholesale: a provided list is the new complete set of
    layers, [] commands calm/clear, None leaves the layers alone.

    The adapter is responsible for making the write STICK: a simulator whose
    own weather engine would overwrite manual values (X-Plane 12 real weather)
    must be forced into manual mode first, and the mode verified, inside this
    call — once per call, not per field. An adapter that cannot secure the
    mode raises rather than writing values it knows will be destroyed.

    Requires Capabilities.can_set_weather.
    """
    ...
```

Why a method pair rather than weather fields on `AircraftSetup`: weather is not aircraft state —
it has its own read model, its own gating flag, its own mode-forcing semantics, and a different
consumer (the region, not the airframe). Overloading `apply_setup` would tangle two capability
gates in one merge.

### 5.2 What each adapter must do

**`FakeSimAdapter`** (full implementation, foundation commit):

- Holds `self._weather: WeatherState`, initialised to `DEFAULT_WEATHER` — a fully-populated
  CAVOK-ish day: one wind layer (`altitude_ft=0, direction_deg=270, speed_kt=8`), no clouds,
  `visibility_m=20_000`, `qnh_hpa=1013.25`, `temperature_c=15`, `dewpoint_c=5`,
  `precipitation_ratio=0`, `runway_contamination="dry"`. Constructor-settable
  (`FakeSimAdapter(weather=...)`), the same affordance pattern as `airframe`.
- `get_weather()` returns a deep copy.
- `set_weather(setup)` merges: scalars overlay when not `None`; `wind_layers` / `cloud_layers`
  replace wholesale when provided, including `[]`. Rejects nothing (it declares the flag).
- No I/O, import-safe, exactly as today.

**`XPlaneSimAdapter`** (refusing stub in the foundation commit, D16): keeps
`can_set_weather=False`; both methods `raise CapabilityNotSupported(self.name,
"can_set_weather")`. This keeps the `TYPE_CHECKING` protocol-conformance assignments and mypy
green the moment the protocol grows, and it means the Scenario Generator's "unavailable, never
attempted" path is exercisable immediately. The adapter track (§10, W2) then implements §7 and
flips the flag in the same PR that passes the weather contract cases under `-m sim`.

### 5.3 Contract-suite additions

`tests/adapters/test_contract.py` (this file edit is part of the serialised foundation work —
it is the designed mechanism: `CAPABILITY_COVERAGE` moves `can_set_weather` from `PENDING` to a
real test name, and `test_every_capability_is_covered` enforces it):

```python
CAPABILITY_COVERAGE["can_set_weather"] = "test_set_weather_round_trips"

WEATHER_READBACK_TOLERANCE = {  # per-adapter, same pattern as POSITION_TOLERANCE_M
    "fake": {
        "dir_deg": 0.1,
        "speed_kt": 0.1,
        "vis_ratio": 0.001,
        "qnh_hpa": 0.1,
        "temp_c": 0.1,
        "base_ft": 1.0,
        "coverage": 0.01,
    },
    "xplane": {
        "dir_deg": 5.0,
        "speed_kt": 2.0,
        "vis_ratio": 0.10,
        "qnh_hpa": 1.0,
        "temp_c": 1.0,
        "base_ft": 250.0,
        "coverage": 0.15,
    },
}
WEATHER_HOLD_S = {"fake": 0.2, "xplane": 90.0}  # see §10.5 — the xplane number must
# outlast the sim's own update cycle
```

New cases, all skipping (never failing) on an adapter without the flag, exactly the house
pattern:

1. **`test_set_weather_round_trips`** — write a full, distinctive setup (two wind layers, one
   broken cumulus layer, vis 5 000 m, QNH 1002, 22/18 °C, precip 0.4, wet); `get_weather()`
   returns it within the tolerance table. This is the flag's coverage entry.
2. **`test_set_weather_applies_only_the_provided_fields`** — write everything, then write
   `WeatherSetup(visibility_m=2_000)`; only visibility moved. The `None`-means-untouched half
   of D2.
3. **`test_set_weather_replaces_layer_lists_wholesale`** — write two cloud layers, then one,
   then `[]`; read back one, then zero. The D3 semantics, pinned.
4. **`test_set_weather_holds_across_the_sims_update_cycle`** — write, wait
   `WEATHER_HOLD_S[adapter.name]`, read back: still the written values. Against the Fake this
   is nearly free and pins the contract's *meaning*; against X-Plane **this is roadmap Phase 2
   exit criterion 3** — the run starts from whatever weather mode the user left the sim in,
   commonly real weather, and only an adapter that forced and verified manual mode passes.
   Restores nothing (weather is not positional state; the session-restore fixture does not
   apply) — a live run ends with test weather, which the docstring says out loud.
5. **`test_weather_methods_refuse_without_the_capability`** — on an adapter whose flag is
   `False`, both methods raise `CapabilityNotSupported` naming `can_set_weather`; skips when
   the flag is declared. Bites the X-Plane stub today (in CI it never runs against xplane;
   under `-m sim` before W2 lands it proves the stub honest) and the MSFS adapter in Phase 5.
6. **`test_get_weather_returns_a_valid_state`** — shape test: a `WeatherState`, layers sorted,
   dewpoint ≤ temperature, ratios in range.

---

## 6. `core/` logic

New package `core/weather/` — models (`models.py`, §3), presets (`presets.py`, §4), and the
resolver. No HTTP, no datarefs, no provider import; fully unit-testable, and everything the
Scenario Generator will need arrives importable from `core/` (D6).

```python
# core/weather/presets.py

WEATHER_PRESETS: Mapping[WeatherPresetId, WeatherPreset]  # §4, data


def resolve_preset(
    preset: WeatherPreset,
    *,
    runway_true_bearing_deg: float | None = None,
    field_elevation_ft: float | None = None,
) -> tuple[WeatherSetup, tuple[str, ...]]:
    """Resolve a preset's relative parts into an absolute WeatherSetup, with notes.

    Raises ValueError when the preset needs context it was not given
    (requires_runway and no bearing; requires_airport and no elevation).
    Pure: (preset, bearing, elevation) in, (setup, notes) out — the server
    passes numbers it looked up in navdata; core never sees the provider.
    """


def merge_setup(base: WeatherSetup, overlay: WeatherSetup) -> WeatherSetup:
    """Overlay the set fields of ``overlay`` onto ``base`` and RE-VALIDATE.

    model_validate on the merged dump, not model_copy(update=...) — the
    position router's merge bug (a nested dict surviving un-validated to the
    adapter) is a lesson, not a tradition. Layer lists follow D3: an overlay
    list replaces the base list.
    """


def resolve_request(
    request: WeatherRequest,
    *,
    runway_true_bearing_deg: float | None = None,
    field_elevation_ft: float | None = None,
) -> tuple[WeatherSetup, tuple[str, ...]]:
    """The one entry point preview, apply and (later) the scenario engine share:
    resolve the preset if any, merge request.setup over it, note the provenance
    of every resolved number and every override that displaced a preset value."""
```

Also in `core/weather/models.py`, because the adapter needs it and it is pure arithmetic:
nothing. The unit conversions (kt→m/s, ft→m, hPa→Pa, m→SM) are **adapter** code — they exist
only because X-Plane's units differ, which is precisely the kind of knowledge `core/` must not
hold. The ISA ladder the adapter uses for temperatures aloft is already in `core/atmosphere.py`
(`isa_temperature_c`, `isa_deviation_c`) and is reused, not duplicated.

---

## 7. Dataref mapping (X-Plane)

**This section describes `adapters/xplane/` only. No name below may appear in `core/` or
`server/`.** All entries extend the module's `DATAREFS` dict; writes go through the existing
`_write(key, value, index)` (the Web API's indexed-write path already used for
`override_planepath[0]`).

X-Plane 12 replaced the flat XP11 `sim/weather/*` namespace with a **region-based system**:
`sim/weather/region/*` is the writable commanded weather; `sim/weather/aircraft/*` is the
read-only sampled actuals at the aircraft. This adapter reads and writes **`region`** — the
instructor's question is "what did I command", and the region datarefs echo the commanded values
immediately even while the visuals (clouds especially) catch up over the next update cycle.

### 7.1 The mode — force manual, verify, then write

The single most common cause of "the weather did not apply", handled once, at the top of every
`set_weather` call:

```
1. write update_immediately = 1                    # changes take effect now, not in ≤60 s
2. write change_mode        = 3 (static)            # stop autonomous evolution
3. read weather_source back                          # NEVER written -- confirmed read-only
4. if it did not read 0 -> raise XPlaneWeatherRejected (the server maps it to 502)
   — never write values the sim has announced it will destroy
5. proceed with the field writes
```

| Internal key | Dataref | Type / unit | Confidence |
|---|---|---|---|
| `weather_source` | `sim/weather/region/weather_source` | int enum — real weather (`1`) vs. manually set (`0`) | **CONFIRMED, live 2026-08-17 against X-Plane 12.4.3**: read-only (`is_writable: false` in the Web API's own dataref index) — never written, only read back as the verdict. See §11.1. |
| `weather_change_mode` | `sim/weather/region/change_mode` | int enum; `3` = static | **CONFIRMED**: of candidates `0`-`3`, only `3` held a distinctive visibility/QNH for the full 120 s live test with zero drift; `0`/`1`/`2` each eventually drifted (§11.1, §11.5). |
| `weather_update_immediately` | `sim/weather/region/update_immediately` | int bool; note: Laminar documents cloud changes as excepted — clouds still transition visually over the update interval, but the *dataref read-back* is immediate, so `get_weather` is not affected | **Partially wrong, confirmed live**: the cloud dataref read-back is *not* immediate either — measured converging over several seconds to (in one adversarial case) more than 10 s. See §11.8. |

### 7.2 The fields

Every write converts from the model's aviation units at the adapter boundary (D13).

| `WeatherSetup` field | Dataref(s) | Sim unit | Conversion | Confidence |
|---|---|---|---|---|
| `wind_layers[i].altitude_ft` | `sim/weather/region/wind_altitude_msl_m[i]` | metres MSL | ×0.3048 | high |
| `wind_layers[i].direction_deg` | `sim/weather/region/wind_direction_degt[i]` | true degrees | none | high |
| `wind_layers[i].speed_kt` | `sim/weather/region/wind_speed_msc[i]` | m/s | ×0.514444 | high |
| `wind_layers[i].gust_increase_kt` | `sim/weather/region/shear_speed_msc[i]` (+ `shear_direction_degt[i]` left at 0) | m/s | ×0.514444 | **verify in spike** — whether XP12 models gusts through the shear pair or a dedicated dataref (§10.2) |
| `wind_layers[i].turbulence_ratio` | `sim/weather/region/turbulence[i]` | float, scale **0–1 or 0–10** | measured against the sim's own UI slider in the spike | verify scale |
| `cloud_layers[i].base_ft` / `tops_ft` | `sim/weather/region/cloud_base_msl_m[i]` / `cloud_tops_msl_m[i]` | metres MSL | ×0.3048 | high |
| `cloud_layers[i].coverage_ratio` | `sim/weather/region/cloud_coverage_percent[i]` | 0–1 | none | high |
| `cloud_layers[i].cloud_type` | `sim/weather/region/cloud_type[i]` | float enum, blendable: cirrus 0, stratus 1, cumulus 2, cumulonimbus 3 | nearest value; read-back rounds | high |
| `visibility_m` | `sim/weather/region/visibility_reported_sm` | statute miles | ÷1609.344 | high |
| `qnh_hpa` | `sim/weather/region/sealevel_pressure_pas` | Pascals | ×100 | high |
| `temperature_c` | `sim/weather/region/sealevel_temperature_c`, plus the aloft ladder `temperatures_aloft_deg_c[13]` recomputed along the ISA lapse from the written sea-level value (via `core/atmosphere.py`) so a warm day is warm all the way up instead of only at the beach | °C | none | **CONFIRMED BROKEN, live 2026-08-17**: `sealevel_temperature_c` does not hold a written value — measured drifting ~+0.7 °C/s regardless of `change_mode`, unaffected by `thermal_rate_ms=0`. Blocks the capability flag on its own. See §11.9. |
| `dewpoint_c` | `sim/weather/region/dewpoint_deg_c[i]` — surface entry from the field, upper entries kept at or below the recomputed temperature ladder | °C | none | Inherits §11.9's problem — the clamp is computed from the same drifting sea-level temperature. |
| `precipitation_ratio` | `sim/weather/region/rain_percent` | 0–1; the sim decides rain vs. snow from temperature | none | high |
| `runway_contamination` | `sim/weather/region/runway_friction` | int enum 0–15: dry 0, wet 1–3, puddles 4–6, snow 7–9, ice 10–12 | dry→0, wet→2, puddles→5, snow→8, ice→11 (mid-band); read-back maps bands back | high |

**Distributing ≤3 layers over 13 levels (D10):** X-Plane 12 carries 13 wind/atmosphere levels.
The adapter writes the N given layers into levels `0..N-1` at their stated altitudes, then pins
every remaining level to the values of the highest given layer at ascending altitudes above it.
Consequence, and the reason for the rule: a single-layer `crosswind` preset produces **uniform**
wind from the surface up — never an invented shear at whatever stale altitudes the previous
weather left in levels 3–12. Verified under `-m sim` by reading the full arrays back.

`get_weather()` reads the same region datarefs, converts back, and reconstructs the typed lists
— collapsing the pinned duplicate levels back into the layers they came from (adjacent levels
with equal direction/speed/turbulence are one layer).

### 7.3 Adapter capability change

`_CAPABILITIES` in `adapters/xplane/xplane_adapter.py` flips `can_set_weather=True` **in the
same PR that implements §7.1–7.2 and passes the §5.3 cases under `-m sim`** — never before. The
comment "the rest arrive in later phases" shrinks by one line.

### 7.4 MSFS (Phase 5 target)

Weather injection is locked down by Asobo: expect `can_set_weather = False`, the manifest to
say so, the panel to disable with that reason, and the Scenario Generator to grey out every
weather-dependent scenario — all of which falls out of the capability gate with zero code. If a
partial surface ever opens (SimConnect METAR-string injection exists but fights the same
real-weather engine), the sparse `WeatherSetup` lets an MSFS adapter honour a subset — and
refuse fields it cannot, per the `apply_setup` precedent.

---

## 8. UI panel outline

New tab of the Instructor Panel: `ui/src/features/weather/` — **adding files, not editing
shared ones**, with exactly two shared-file edits: mounting `WeatherPanel` in `App.tsx`, and
nothing else (`weatherApi.ts` uses `injectEndpoints`/`enhanceEndpoints` on the existing api
object, D15).

### 8.1 Server state — RTK Query (`weatherApi.ts`)

| Endpoint | Kind | Notes |
|---|---|---|
| `getWeatherManifest` | query | fetched on mount; drives the gate and the preset grid |
| `getWeather` | query, tag `Weather` | the current commanded state, shown as the editor's baseline |
| `previewWeather` | **query** despite being a `POST` — side-effect-free by design, so caching and de-duplication are free (the `previewPlacement` precedent) | keyed on the staged `WeatherRequest` |
| `applyWeather` | mutation, invalidates `Weather` | the only call that touches the simulator |

All types come from the regenerated `ui/src/api/schema.d.ts`. Nothing is hand-written (hard
rule 7).

### 8.2 Client state — one slice (`weatherSlice.ts`)

```ts
interface WeatherPanelState {
  selectedPresetId: WeatherPresetId | null;
  airportIcao: string | null;        // context for relative presets; prefilled from the
  runwayIdent: string | null;        // Position panel's selection when there is one
  overrides: WeatherSetup;           // the sparse overlay the editor accumulates
  staged: WeatherRequest | null;     // what Apply will send
}
```

Server data never lands in the slice. Reducers: `presetSelected`, `contextChanged`,
`overrideEdited`, `staged`, `cleared` — and, the lesson from `positionSlice`'s tests, a
selected preset and its overrides are **cleared when the airport context changes**: a staged
CAT III resolved against the previous field is the dangerous leftover here.

### 8.3 Components, top to bottom

1. **`PresetGrid`** — seven large tiles (this is the two-tap path on a tablet: tile → Apply).
   Tiles with `requires_runway` / `requires_airport` show the airport/runway picker state
   inline and stay disabled until the context exists, with the reason as text.
2. **`WindLayerEditor`** — up to 3 rows: altitude ft, direction °, speed kt, gust kt,
   turbulence slider. Add/remove row; "calm" writes `[]`.
3. **`CloudLayerEditor`** — up to 3 rows: base ft, tops ft, coverage (octa chips mapping to
   ratios), type. "Clear skies" writes `[]`.
4. **`AtmosphereForm`** — visibility m, QNH hPa, temperature °C, dewpoint °C (clamped ≤ temp
   in the form), precipitation slider, contamination chips.
5. **`WeatherStagingBar`** — persistent, bottom: the resolved values from `previewWeather` with
   `notes` underneath in tertiary text, one solid **Apply weather** button. Success reports the
   read-back state ("Applied — wind 090° at 20 kt, vis 800 m"), never the request; failures
   render inline, never a modal.

### 8.4 Gating (`gate.ts`)

One gate, from `getWeatherManifest`, and it **fails closed** on loading and on error — the
`commitGate` precedent: "I could not find out" counts as unsupported, or hard rule 3 is a claim
rather than a property. `supported: false` disables the editors and the Apply button and renders
`reason` verbatim; the panel body stays visible so the instructor can see *what* is unavailable.
Preview stays enabled regardless — it needs no simulator.

Tablet-first: 44 px minimum touch targets, sliders sized for thumbs, the preset grid above the
fold, `tabular-nums` on every numeric readout, and the whole editor collapsible so the grid plus
the staging bar fit one portrait screen.

---

## 9. Test plan

Everything below CI runs against `FakeSimAdapter` — no simulator, no navdata file (hard rule 4;
the fixture world is the existing in-Python `ZZZZ` from `tests/server/conftest.py`, extended
with nothing).

### 9.1 `core/` unit tests — `tests/core/weather/`

Concrete reference values, all computable by hand:

- **Model validation**: `tops_ft <= base_ft` refused; 4 layers refused; `dewpoint_c >
  temperature_c` refused on `WeatherSetup`; unsorted layers refused; `WeatherRequest` with
  neither preset nor setup refused; an unknown extra field refused (`extra="forbid"` — the
  scenario-YAML typo case, asserted now so it cannot be dropped silently as it was for
  positions).
- **`resolve_preset` geometry**: `crosswind` at runway bearing 000° → surface wind from
  **090.0°**; at 233° → **323.0°**; offset −90 at 000° → **270.0°**. `cat_i` at field elevation
  1 000 ft → base **1 250 ft MSL**, tops **3 500 ft MSL**; at Schiphol-like −11 ft → base
  **239 ft MSL** (negative elevations must not clamp). `mountain_wave` middle layer at
  ZZZZ → **9 000 ft MSL**.
- **`resolve_preset` refusals**: `crosswind` without a bearing raises `ValueError` naming the
  preset; `cat_i` without an elevation likewise; `cavok` resolves with neither.
- **`merge_setup`**: override `visibility_m=1200` over resolved `cat_i` → 1 200; overlay
  `cloud_layers=[]` over `storm` → clear; the merged result is re-validated (a deliberately
  malformed overlay dict cannot survive to the adapter).
- **Notes provenance**: the crosswind sentence carries both the offset and the runway bearing;
  an override produces the "your override" sentence.
- **Preset catalogue integrity**: every `WeatherPresetId` has an entry; `requires_runway` /
  `requires_airport` derived values match §4's table exactly (a table-driven test, so a preset
  edit that changes its requirements is a visible diff here).

### 9.2 Contract tests — `tests/adapters/test_contract.py`

The six cases of §5.3, parametrised over `fake` (CI) and `xplane` (`-m sim`), plus the
mechanical guarantee that already exists: `test_every_capability_is_covered` fails the build if
`can_set_weather` had stayed `PENDING`.

### 9.3 Server tests — `tests/server/test_weather_routes.py`

Against the Fake via `TestClient`: every endpoint; every error row of §2.2 including "no
airport context never 503s even with the index absent"; `preview` is side-effect-free
(`get_weather` unchanged across the call — the `TestPreviewIsSideEffectFree` pattern);
`apply` writes then reads back and the response `state` is the Fake's post-write weather; the
501 sentence names the adapter and the flag; the manifest lists seven presets with the §4
requirement flags.

### 9.4 UI tests (vitest) — `ui/src/features/weather/`

`gate.test.ts` (closed on loading, closed on error, closed on `supported:false`, reason
rendered); `weatherSlice.test.ts` (context change clears the staged preset — the dangerous
leftover); `PresetGrid.test.tsx` (each tile stages the exact `WeatherRequest`, asserted with
`toEqual`; relative tiles disabled without context, with the reason visible);
`WeatherStagingBar.test.tsx` against a stubbed `fetch` (staging issues a preview and **no**
apply; apply sends the staged request verbatim; the confirmation reports the read-back; a 501
renders inline).

### 9.5 What only `-m sim` can prove — `tests/sim/` (never in CI)

- The §5.3 cases against the live adapter — above all
  **`test_set_weather_holds_across_the_sims_update_cycle` starting from real-weather mode**,
  which is roadmap exit criterion 3 made executable.
- The 13-level distribution: write one layer, read all 13 back, assert no phantom shear.
- The unit conversions land: write 20 kt, read `wind_speed_msc` ≈ **10.289**; write vis 800 m,
  read `visibility_reported_sm` ≈ **0.497**; write QNH 1013.25, read
  `sealevel_pressure_pas` = **101 325**.
- The `sim-validator` smoke gains one step: apply `cat_i` at the aircraft's nearest airport,
  read back, restore nothing (weather is not restored — stated in the run report).

### 9.6 Fixtures

None beyond what exists. No weather file format exists to be tempted by; presets are code-side
data; the navdata world is the committed-nothing in-Python `ZZZZ`.

---

## 10. Parallelisation

Per the standing policy in `CLAUDE.md`. Phase-2-wide: Weather ∥ Failures ∥ Fuel & Payload as
separate `feature/*` branches in separate worktrees; the Scenario Generator waits for all
three. Inside this manager:

| Track | What | Owns (disjoint) | May start |
|---|---|---|---|
| **W0 — foundation, SERIALISED** | §5 in full: `core/weather/models.py`, protocol methods, Fake implementation + `DEFAULT_WEATHER`, X-Plane refusing stub (D16), the six contract cases, `CAPABILITY_COVERAGE` entry | `core/weather/models.py`, `core/sim_adapter.py`, `adapters/fake/`, the stub lines in `adapters/xplane/`, `tests/adapters/test_contract.py` | first, alone — this is the contract change and is **never parallelised** |
| **W1 — backend** | `core/weather/presets.py` + resolver, `server/weather_routes.py`, `include_router` in `app.py`, `tests/core/weather/`, `tests/server/test_weather_routes.py` | `core/weather/presets.py`, `server/`, `tests/core/weather/`, `tests/server/` | after W0 |
| **W2 — X-Plane adapter** | the §10.1/10.2 spike, then §7: mode forcing, field writes, layer distribution, flag flip, `tests/sim/` additions | `adapters/xplane/`, `spikes/weather_datarefs.py`, `tests/sim/` | after W0; **the spike first** |
| **W3 — UI panel** | `ui/src/features/weather/*`, the `App.tsx` mount, `schema.d.ts` regeneration | `ui/` | after W1's routes exist on the branch — the client is generated from the running server's OpenAPI schema, and hand-writing types to start earlier is forbidden (the position doc's §20 records exactly this constraint) |

W1 and W2 are dispatched **in a single message** once W0 is merged to the feature branch; W3
follows W1 within the branch. The tester writes §9.2 and §9.3 against this document without
waiting for any implementation — the models above are complete enough that a test that fails
against the eventual code indicts the code.

**Never parallelised:** W0; any later change to `WeatherState`/`WeatherSetup` (they are contract
vocabulary); merges to `dev`/`main`; release tagging. No navdata schema is touched by this
manager at all.

---

## 11. Open questions and risks

### 11.1 The manual-mode dataref values — RESOLVED, confirmed live 2026-08-17

**`sim/weather/region/weather_source` is read-only.** Confirmed via the Web API's own dataref
index (`is_writable: false`) against a live X-Plane 12.4.3 install — the fallback path this
section originally sketched ("if `weather_source` proves read-only, determine whether any region
write flips the sim to manual by itself") is exactly what happened, and it works cleanly:
writing `sim/weather/region/change_mode = 3` plus `update_immediately = 1` switches
`weather_source` from `1` (its value under real weather) to `0`, and a distinctive
visibility/QNH written immediately after **held bit-for-bit for a 120 s live poll** — well past
the 90 s threshold §11.5 assumed. Candidates `change_mode = 0`, `1` and `2` were also tried and
each eventually drifted (at roughly 50 s, 35 s and 60 s respectively), meaning X-Plane's own
weather engine periodically reasserts itself under those modes but not under `3`. The adapter
(`adapters/xplane/xplane_adapter.py::_force_manual_weather_mode`) now writes
`change_mode`/`update_immediately` only and reads `weather_source` back purely as the verdict,
never as a write target — writing to a read-only dataref would have raised at the HTTP layer.

**`can_set_weather` does not flip yet regardless** — two new, confirmed-not-speculative problems
surfaced while validating this fix live; see §11.8 and §11.9.

### 11.2 Gusts: shear datarefs or dedicated?

§7.2 maps `gust_increase_kt` onto `shear_speed_msc[i]` on the strength of X-Plane's lineage
(XP11 modelled gusts through shear) — unverified on 12.x. Same spike, same session: set a gust
in the sim's own weather UI, read the region arrays, see where it landed. **Still open** — this
needs a human watching the sim's own UI while a value is written, which this session's live
access did not include (no one was at the keyboard to operate X-Plane's menus).

### 11.3 Turbulence scale — partially checked, still not fully confirmed

`turbulence[13]` is a float whose full-scale value (1 or 10) differs between community sources.
**Checked live**: writing `5.0` directly round-tripped as `5.0` with no clamping to `1.0`, which
rules out a hard 0–1 clamp at the Web API layer — but only a human watching the sim's own weather
UI while this value is written can confirm what visible/felt turbulence `5.0` actually produces,
and that observation still did not happen this session (same reason as §11.2). The core model
stays 0–1 regardless; only the adapter's multiplier changes once this is settled.

### 11.4 Snow depth and winter surfaces

Explicit snow-on-ground control appears to have arrived in later 12.x builds with uncertain
dataref names (earlier builds hid it in `sim/private/`). Out of scope (§1.2);
`runway_contamination="snow"` covers the friction half. **Resolution when wanted:** a spike
against the user's installed build; if a public dataref exists, it is one added field on
`WeatherSetup` and one row in §7.2.

### 11.5 How long must the hold test wait? — RESOLVED

`WEATHER_HOLD_S["xplane"] = 90.0` was correct: `change_mode = 3` held for a live-measured 120 s
with zero drift, comfortably past the 90 s bar. The three *wrong* candidates give the number its
justification retroactively — they drifted at 50 s, 35 s and 60 s respectively, so a shorter
threshold (say 30 s) would have wrongly certified `change_mode = 0` as stable.

### 11.6 Region scope

The region datarefs command the weather region the aircraft occupies. Whether a very long
teleport (Position Manager) lands the aircraft in a differently-weathered region — and whether
the instructor's commanded weather should follow the aircraft — is unknown. Accepted for
Phase 2: weather is commanded where the aircraft is, and a `-m sim` observation during the
validator smoke (teleport far, read weather) records the actual behaviour for the scenario
engine to design against.

### 11.7 Architecture known risks touched

Risk 2 (real weather overwrites) is this manager's core and is resolved by §7.1 + §5.3 case 4.
Risk 5 (MSFS subset) is honoured by D16's posture: everything downstream of the flag degrades
to "disabled with a reason" with zero weather-specific code.

### 11.8 Cloud writes converge slowly — CONFIRMED, new finding, blocks the flag

Not anticipated by §7.2's confidence table, which rated the cloud fields "high" confidence on
naming alone. Live-measured against X-Plane 12.4.3: a written cloud layer (`cloud_base_msl_m`,
`cloud_coverage_percent`) does **not** appear on the very next read — one measurement was still
stale after 1 s and had converged by 4 s; a later, more adversarial measurement (writing a
*second*, different layer immediately after the first) was still only partway to the new target
after a full 10 s wait. This reads as a genuine gradual transition, matching this design's own
§7.1 note that "Laminar documents cloud changes as excepted — clouds still transition visually
over the update interval" — except the transition turned out to affect the *dataref read-back*
too, not only the rendering, which §7.1 had assumed stayed immediate.

**Resolution shipped this session**: `_write_cloud_layers` now calls
`_await_cloud_layers_settled`, which polls for up to 10 s and **returns regardless of whether the
target was reached** — it does not raise, because the convergence time has no observed upper
bound and blocking (or refusing) indefinitely would be worse than an occasionally-stale
read-back. **Still open**: whether 10 s is long enough in the common case, and whether the
contract suite's round-trip test (`test_set_weather_round_trips`) needs its own wait-and-retry
instead of asserting immediately after `set_weather` returns — right now that test fails against
this adapter for exactly this reason, which is why `can_set_weather` has not flipped.

### 11.9 `sealevel_temperature_c` does not hold a written value at all — CONFIRMED, blocks the flag

The most serious new finding. `sim/weather/region/sealevel_temperature_c` was measured drifting
continuously (~+0.7 °C/s in one run) **regardless of `change_mode`**, independent of whether the
13-level aloft ladder was also written, and unaffected by
`sim/weather/region/thermal_rate_ms` (already `0.0` in the failing case, ruling out the one
obvious lever). A direct write is visible for well under a second before the drift resumes — this
is not the same "eventually converges" shape as §11.8's clouds; the sim appears to be actively
computing this value from something other than the region weather engine, most plausibly a
day/night thermal simulation this design assumed was part of the same system `change_mode`
disables. `_write_temperature_ladder`'s docstring now states this plainly and the write is kept
as best-effort (matching the rest of the adapter's posture on unresolved fields) rather than
silently removed.

**No dataref that stops the drift was found this session.** `weather_dewpoint`'s ladder writes
inherit the same problem, since §7.2's dewpoint clamp is computed from this same sea-level
temperature. **Resolution needed**: a further live session, ideally with someone able to watch
X-Plane's own environment/time-of-day settings while probing — candidates worth trying next:
`sim/time/*` datarefs (freezing simulated time), or a region dataref this session's `search_datarefs
"weather region"` sweep did not surface because it lives outside the `sim/weather/region/`
namespace entirely.

---

## 12. Verification

```bash
pytest                       # unit + contract, Fake only — must be green before any merge
pytest -m sim                # W2's gate: the weather contract against a live X-Plane,
                             # started in real-weather mode on purpose
ruff check . && ruff format --check .
mypy .                       # the protocol conformance assignments catch a missing method
cd ui && npm run lint && npm run typecheck && npm test && npm run build
```

Panel smoke (fake adapter + Vite dev server, one batched browser session): manifest loads with
seven presets → `crosswind` tile disabled until an airport/runway is picked, with the reason →
pick ZZZZ 36 → preview shows wind from 090° at 20 kt with the provenance sentence → Apply →
the confirmation reports the read-back → console clean. No live simulator is needed; the
real-sim proof is `pytest -m sim` and the `sim-validator`'s smoke, and neither is a merge gate.
