# Fuel & Payload Manager — design

**Status:** designed, not yet implemented.
**Issue:** [#16](https://github.com/Santisoutoo/open-instructor-station/issues/16).
**Phase:** 2 — Weather + Failures + Fuel & Payload → Scenario Generator ([`../roadmap.md`](../roadmap.md#phase-2--weather--failures--scenario-generator)).
**Feature spec:** manager 9 ([`../feature-spec.md`](../feature-spec.md#9-fuel--payload-manager)).
**Depends on:** the Phase 0/1 contract (`core/sim_adapter.py`, `FakeSimAdapter`, the contract suite), `AirframeInfo`/`get_airframe()` (issues #8/#82), the existing `AircraftSetup.gross_weight_kg`/`fuel_kg` fields (issue #8, deliberately left unimplemented and deferred here — see `pre-teleport-setup.md`, *"Deferred, with rationale"*).
**Blocks:** the Scenario Generator (manager 2) — rejected-takeoff and engine-failure-after-V1 scenarios are "only meaningful at a defined weight" per the roadmap — and, later and out of this manager's scope, the Position Manager's automatic setup, which the feature spec names as a future consumer of this manager's numbers.

This manager gives the instructor station mass-and-balance: fuel per tank, passengers, cargo,
total weight, centre of gravity, four presets (`Ferry`, `Training`, `Full`, `Empty`), and envelope
validation that **refuses** an out-of-envelope loadout with a stated reason rather than silently
accepting it.

Binding rules live in [`../../CLAUDE.md`](../../CLAUDE.md); layers in
[`../architecture.md`](../architecture.md). The Weather Manager design
([`weather-manager.md`](weather-manager.md)) and the Failures Manager design
([`failures-manager.md`](failures-manager.md)) are this phase's house style; the Position Manager
design ([`position-manager.md`](position-manager.md)) is the style both of them extended, and its
recorded regrets — request models stranded in `server/`, `instructorApi.ts` edited directly
instead of `injectEndpoints` — are not repeated here.

---

## 0. Decisions at a glance

| # | Decision | Where |
|---|---|---|
| D1 | **Mass and payload extend `AircraftSetup` through a new nested `loadout: Loadout \| None` field, the same way `LightsSetup` does — there is no separate `set_loadout` method.** Weather and Failures broke the "`apply_setup` is the only write path" precedent because they are not aircraft configuration: weather has its own read model, its own mode-forcing, a different consumer (the region, not the airframe); failures have armed/immediate/cleared semantics no configuration field has. Mass has none of that — a loadout is exactly the same class of fact as flaps or gear, already half-modelled on `AircraftSetup` as `gross_weight_kg`/`fuel_kg`, and the interface's *only* existing `CapabilityNotSupported` raise site is precisely this field pair. Extending it keeps one write path, one half-applied-state risk (zero), and reuses the fixture the contract suite already carries (`CAPABILITY_GATED_SETUPS["can_set_fuel_payload"]`). | §5.1 |
| D2 | **`gross_weight_kg`/`fuel_kg` are kept, unchanged, as a coarse total-mass write path** for any caller that wants "set the total to X" without a breakdown (a bare scenario step, say). This manager **never sends them** — it always resolves and sends a complete `loadout`. When both are present in one `AircraftSetup` (not produced by this manager, but possible from another caller), `loadout` is authoritative and the scalars are applied only when `loadout` is absent — the same "explicit field beats its alias" precedent `ils_freq_khz`/`nav1_freq_khz` already set. | §5.1, §5.2 |
| D3 | **One new read method, `get_loadout() -> LoadoutState`, gated by `can_set_fuel_payload`** — mirrors `get_weather()`'s reasoning exactly: fuel burns continuously and payload is invisible in `AircraftState`/`AircraftSetupResult` (which "does not carry configuration," per its own docstring), so a panel that displays the current loadout needs a dedicated read, and the flag that gates writing it gates reading it too. | §5.1 |
| D4 | **Both `preview` and `apply` require `can_set_fuel_payload`**, unlike the sibling managers' capability-free previews. Mass-and-balance is a whole-aircraft computation: a partial "just top up tank 1" instruction cannot be validated without the mass of everything else, and there is no sim-agnostic way to invent it. `preview` therefore reads the current loadout via `get_loadout()`, seeds the resolution from it, and layers the preset/overlay on top — which is exactly why it needs the capability the sibling previews do not. Flagged as a deliberate divergence, not an oversight. | §2, §5.1 |
| D5 | **`AirframeInfo` gains one new field, `mass_limits: AirframeMassLimits \| None`**, not ten flat fields. It is all-or-nothing: an adapter that cannot supply the *complete* set (empty weight, MTOW, tank/station capacities and arms, CG envelope) reports `None` rather than a half-populated model, so "we know MTOW but nothing about CG" — a genuinely awkward partial state — never has to be represented. | §3.1 |
| D6 | **A `core/` fallback table, keyed by ICAO type, supplies mass/CG limits when the adapter cannot** — `core/fuel_payload/limits.py::AIRCRAFT_MASS_LIMITS_TABLE`, the same "airframe arrives as an input" philosophy as `APPROACH_CATEGORY_VAT_KT`, generalised to authored per-type constants. `resolve_mass_limits(airframe)` prefers the adapter's numbers, falls back to the table by `icao_type`, and returns `None` — "unverifiable," never invented — when neither knows. Every table entry carries a `source_note` disclaimer the manifest surfaces verbatim, because these are illustrative POH-derived numbers, not certified data. | §6.2 |
| D7 | **An unknown airframe never blocks `apply`.** When `resolve_mass_limits` returns `None`, `within_envelope` is `None` (not `False`), the response carries a *"mass and balance cannot be verified for this airframe"* note, and the write proceeds — the same posture as the Position Manager's zero-speed warning and the hold's unconverted-magnetic-course note: the station discloses what it cannot know rather than either inventing a number or refusing on the strength of ignorance. | §6.2, §7 |
| D8 | **A loadout that *is* verifiably out of envelope is refused by default (422), with an explicit `override_envelope: bool = False` escape hatch on `apply`.** The feature spec is explicit that refusing is "more useful... than silently accepting," which is a stronger stance than the zero-speed warning's "warn, never refuse" — the difference being that here the station genuinely *can* compute the answer. The override exists because an aft-CG spin-awareness demonstration is a legitimate lesson, not a data-entry mistake, and the station does not get to overrule a deliberate instructor choice; it must be an explicit, named opt-in rather than the default. | §2.2, §6.3 |
| D9 | **Presets are two capacity fractions — `fuel_fraction`, `station_fraction` — applied uniformly to every known tank and station**, resolved against `AirframeMassLimits` at request time (mirrors weather's AGL-resolved-at-apply-time presets). Phase 2 does **not** model named seats, crew, or a loading order/priority between stations. This is a real, disclosed limitation: §7's worked table shows a preset resolving *outside* the envelope (`full`, aft CG) precisely because "fill every station equally" is not how a trainer is loaded in practice. Presets are resolved then validated like everything else; nothing about being a preset exempts it from the envelope check. | §4, §11.3 |
| D10 | **Fuel and station lists replace wholesale** — `tanks: None` / `stations: None` means "leave those untouched" on the raw `Loadout` write type, `[]` means "empty every one," a provided list is the complete new set. Identical semantics to the Weather Manager's wind/cloud layers (its D3), for the identical reason: no defensible per-index merge. This manager's own resolver, however, always sends a *complete* list (§0 D4) — the partial semantics remain available to other callers of `AircraftSetup.loadout`. | §3.1 |
| D11 | **No dedicated mode to force.** Unlike weather, there is nothing analogous to X-Plane's real-weather engine fighting a manual write. Unlike position/attitude, mass is not part of the flight model's per-frame integration — X-Plane's own docs and the existing adapter's own categorisation (`_write_configuration` vs `_write_flight_model_state`) treat weight the way they treat flaps: an input the physics reads, not a state it re-derives and overwrites. Loadout writes therefore go in `_write_configuration`, outside `frozen_flight_model` — validated by the reasoning in §6.1, not assumed. | §6.1 |
| D12 | **The request model lives in `core/fuel_payload/models.py`, not the router** — the Position Manager's recorded regret (its §7.6), applied deliberately this time, exactly as the Weather and Failures designs already did. | §3.4, §7.1 |
| D13 | **Two POSTs, `preview` and `apply`, one request shape** — the staging pattern the Position and Weather Managers established. `apply` re-resolves from scratch; a client can never hand the server a resolved loadout and call it a preset. | §2.1 |
| D14 | **`GET /api/fuel-payload/manifest` mirrors `GET /api/aircraft/controls`/the weather manifest**: capability + reason, the resolved mass limits and their provenance, tank/station counts, the preset catalogue — one round-trip, always 200. | §2.3 |
| D15 | **The X-Plane adapter grows a refusing stub in the foundation commit** (`can_set_fuel_payload` stays `False`; `get_loadout` and the `loadout`-carrying branch of `apply_setup` raise `CapabilityNotSupported`), so the protocol change lands green everywhere before the adapter track starts. Mirrors the weather design's D16 exactly. | §5.2, §9 |
| D16 | **The UI adds its endpoints with `injectEndpoints` from `ui/src/features/fuel-payload/fuelPayloadApi.ts`** — never editing `instructorApi.ts` directly, the rule the Position panel broke. | §8.1 |
| D17 | **This manager touches no navdata and adds no `SimAdapter` method beyond `get_loadout`.** Unlike Weather (runway/airport context for presets) and Position (the whole navdata façade), a loadout preset needs only the airframe's own limits — no 503, no `NavdataProvider` import anywhere in this design. | §2.2, §11 |

---

## 1. Scope

### 1.1 What this manager does

1. **Read the current loadout** — one `LoadoutState` snapshot: every known fuel tank and payload
   station, as the simulator has them right now.
2. **Stage and validate a candidate loadout** — resolve a preset, a manual overlay, or both, seeded
   from the current state for anything neither states, and compute gross weight, fuel total, CG
   and an envelope verdict with human-readable violation sentences. **Writes nothing.**
3. **Apply it** — write the resolved loadout, refusing (422) when it is verifiably outside the
   envelope unless the instructor explicitly overrides, then read back and recompute the
   mass-and-balance result from what the simulator actually reports.
4. **Apply a preset** — `Ferry`, `Training`, `Full`, `Empty`, resolved against the airframe's known
   tank/station capacities at request time.
5. **Offer it as a panel** — preset tiles, a tank/station editor, a mass-and-balance readout with a
   CG-vs-envelope graphic, staged and previewed before commit, disabled with a reason on adapters
   that cannot do fuel/payload.

Feature-spec coverage (manager 9, `docs/feature-spec.md`): fuel quantity per tank where the
aircraft exposes tanks; passengers; cargo; total weight; centre of gravity; the four presets;
envelope validation that refuses rather than silently accepts.

Roadmap Phase 2 exit criteria this manager serves: **#1** indirectly — rejected-takeoff and
engine-failure-after-V1 scenarios "are only meaningful at a defined weight," and this manager is
the stated prerequisite for them; **#4** — an adapter that has not declared `can_set_fuel_payload`
reports every fuel/payload control unavailable through the manifest, never attempted.

### 1.2 What is explicitly out of scope

| Out of scope | Owner / reason |
|---|---|
| Wiring a resolved loadout into `Placement.to_setup()` — "automatic" weight/fuel per placement | Feature spec names this as a *future* consumer, not this manager's own surface. `pre-teleport-setup.md` explicitly split mass off to this manager and #8 shipped without emitting it — see "Deferred, with rationale." Wiring it back in reopens `position-manager.md` §9.3's whole-call-refusal question (an adapter without `can_set_fuel_payload` would then refuse *every* placement) and is a Position Manager change, flagged, not solved, at §11.4. |
| Named seats, individual passenger identity, per-passenger weight entry | Presets and the editor work in aggregate station mass (D9). |
| A CG-envelope table for every aircraft in existence | A small hand-authored table for common trainer types (§6.2); everything else degrades to "unverifiable," never silently in-envelope. |
| Real-time fuel-burn simulation | The simulator's own flight model does this continuously; this manager reads and sets a snapshot. |
| Fuel jettison, dump procedures, engine-driven fuel transfer between tanks | Not instructor-facing controls in the feature spec; an additive `core/` command later if asked for. |
| The Aircraft Control panel's `AircraftControlId`/`_CONTROL_FIELDS` catalogue in `server/app.py` | Untouched. Fuel & Payload is its own panel with its own manifest, exactly like Weather and Failures. |
| A new `NavdataProvider` dependency | None needed (D17) — no 503 path exists in this manager. |
| MSFS | Phase 5. SimConnect's `PAYLOAD STATION WEIGHT`/fuel-tank simvars are comparatively well documented, so `can_set_fuel_payload=True` is plausible sooner here than for Weather/Failures — noted at §6.4, not designed. |

---

## 2. REST endpoints

All under `/api/fuel-payload/*`, in a new `server/fuel_payload_routes.py`, registered from
`server/app.py` with one `include_router` line — the only shared-file backend edit, exactly the
Weather/Failures precedent.

```
GET  /api/fuel-payload/manifest  -> FuelPayloadManifest
GET  /api/fuel-payload           -> FuelPayloadState
POST /api/fuel-payload/preview   -> FuelPayloadPreview
POST /api/fuel-payload/apply     -> FuelPayloadApplyResult
```

| Method | Path | Purpose | Safe? | Capability | Declared |
|---|---|---|---|---|---|
| `GET` | `/manifest` | Capability + reason, resolved mass limits and their provenance, tank/station counts, preset catalogue | yes | none — always 200 | `def` — cached `AirframeInfo` read, no I/O |
| `GET` | `/fuel-payload` | The current loadout plus its computed mass-and-balance | yes | `can_set_fuel_payload` → 501 | `async def` — awaits `adapter.get_loadout()` |
| `POST` | `/preview` | Resolve preset + overlay, seeded from the current loadout, into the exact loadout and mass-and-balance result `apply` would produce. **Writes nothing.** | yes | `can_set_fuel_payload` → 501 (D4) | `async def` — needs `adapter.get_loadout()` as its baseline |
| `POST` | `/apply` | Re-resolve, refuse if out of envelope and not overridden, write, read back | no | `can_set_fuel_payload` → 501 | `async def` |

### 2.1 One request shape for preview and apply (D13)

```python
class FuelPayloadRequest(BaseModel):
    preset: FuelPayloadPresetId | None = None
    loadout: Loadout | None = None  # overlay over the preset, or the whole instruction
    override_envelope: bool = False  # ignored by preview; enforced by apply

    # model_validator: at least one of preset / loadout.
```

Order of operations in `apply`:

1. Gate: `can_set_fuel_payload` or 501.
2. `current = await adapter.get_loadout()`.
3. `limits = resolve_mass_limits(get_airframe_info())` — sync, cached, no simulator I/O (§6.2).
4. `resolved, result, notes = core.fuel_payload.resolve_request(request, current=current, limits=limits)`.
5. If `result.within_envelope is False` and not `request.override_envelope` → **422**, detail is
   `result.violations` joined into one sentence per line.
6. `await adapter.apply_setup(AircraftSetup(loadout=Loadout(tanks=resolved.tanks, stations=resolved.stations)))`.
7. `state = await adapter.get_loadout()` — the read-back, the honest verdict (mirrors weather's
   `state = await adapter.get_weather()`).
8. `verified = compute_mass_and_balance(state, limits)` — recomputed from what the simulator
   actually reports, never trusted from step 4.
9. Return `FuelPayloadApplyResult(applied=resolved, state=FuelPayloadState(loadout=state,
   mass_and_balance=verified), notes=notes)`.

`preview` is steps 2–4 with the last five replaced by "return it": `FuelPayloadPreview(request,
loadout=resolved, mass_and_balance=result, notes=notes)`.

**Idempotent.** The body states an absolute target loadout (via the preset/overlay resolution),
never a delta — even though the *resolution* is seeded from current state, the resolved answer for
a fixed `(current, request)` pair is the same every time it is computed, and re-applying it writes
the same numbers again.

### 2.2 Errors

| Situation | Status | Detail |
|---|---|---|
| Neither `preset` nor `loadout` in the request | 422 | `"A fuel/payload request must carry a preset, a loadout, or both."` |
| Preset given but tank/station capacities are unknown (`resolve_mass_limits` returned `None`) | 422 | `"The 'full' preset needs the airframe's known tank and station capacities; none are published for this aircraft and no fallback table entry exists for 'PA46'."` |
| Unknown `preset` id | 422 | FastAPI's own validation body — `FuelPayloadPresetId` is a closed `Literal` |
| `tank_index` / `station_index` in the overlay outside what the current loadout reports | 422 | `"Tank index 3 is not published for this aircraft (2 known tanks)."` — refused rather than silently creating a phantom tank |
| Resolved loadout is verifiably outside the envelope, `override_envelope` not set | 422 | `result.violations`, e.g. `"CG at 44.9 in is aft of the 40.2 in aft limit at 1,110 kg."` |
| Adapter does not declare `can_set_fuel_payload` (any endpoint but the manifest) | 501 | `"Unavailable on this adapter — the 'xplane' adapter does not declare can_set_fuel_payload, so it cannot set fuel or payload."` |
| `CapabilityNotSupported` raised by the adapter anyway | 501 | defence in depth, same as `/api/aircraft/setup` |

**No 503.** This manager reads no `NavdataProvider` (D17) — there is no code path that can raise
`NavdataUnavailable`.

### 2.3 The manifest

`GET /api/fuel-payload/manifest` is this manager's `GET /api/aircraft/controls`. It answers
without touching the simulator or the navdata index (capability flags are static, `AirframeInfo`
is the cache `load_airframe_info()` already populates at connect), so it is always 200 and always
fast — `def`, exactly like the manifest's siblings.

### 2.4 What is deliberately not an endpoint

- **No per-tank or per-station endpoint.** One resolver, one write path.
- **No preset-list endpoint separate from the manifest.**
- **No WebSocket change.** Fuel/payload is a command surface; the panel fetches on mount and after
  every apply. Unlike Failures' armed-trigger strip, nothing here needs a poll — the value only
  changes when the instructor or the engine (fuel burn, invisible to this manager by design)
  changes it, and re-fetching after an apply is enough.

---

## 3. Pydantic models

Units: `_kg` kilograms, `_in` inches aft of the airframe's datum (the standard US POH convention —
arbitrary per source, consistent only within one table entry or one adapter's reported numbers),
ratios 0–1. Everything not stated `frozen` follows the file it lives in: `core/models.py`'s
`Loadout`/`LoadoutState` are **not** frozen (mirrors `LightsSetup`, since `AircraftSetup` itself
is not frozen); everything in `core/fuel_payload/` **is** frozen, the Weather/Failures convention.

### 3.1 `core/models.py` additions — the write/read surface `AircraftSetup` needs

Placed here, not in `core/fuel_payload/`, for the same reason `Ils` lives beside `Runway`:
`AircraftSetup` needs `Loadout` directly, and the other direction would make `core/models.py` and
`core/fuel_payload/models.py` import each other.

```python
MAX_FUEL_TANKS = 8
MAX_PAYLOAD_STATIONS = 12


class TankFuel(BaseModel):
    """Fuel in one tank."""

    model_config = ConfigDict(frozen=True)

    tank_index: int = Field(
        ge=0,
        lt=MAX_FUEL_TANKS,
        description="0-based tank index, in the order get_loadout() reports — adapter-defined.",
    )
    fuel_kg: float = Field(ge=0.0, description="Fuel mass in this tank, kilograms.")


StationKind = Literal["crew", "passenger", "cargo", "other"]


class PayloadStation(BaseModel):
    """Mass at one payload station.

    The simulator itself does not distinguish what a station is FOR — X-Plane's
    ``m_stations`` array and MSFS's payload stations are both bare masses at
    bare positions. ``kind`` is an instructor-facing label, assigned here or by
    a future per-aircraft mapping table, never invented from the mass alone.
    """

    model_config = ConfigDict(frozen=True)

    station_index: int = Field(ge=0, lt=MAX_PAYLOAD_STATIONS, description="0-based, adapter order.")
    kind: StationKind = Field(default="other", description="Instructor-facing classification.")
    label: str = Field(default="", description='Display label, e.g. "Pilot". Blank when unknown.')
    weight_kg: float = Field(ge=0.0, description="Mass placed at this station, kilograms.")


class Loadout(BaseModel):
    """Fuel and payload — the sparse write model nested on AircraftSetup.

    None means "leave that aspect untouched"; a provided list REPLACES the
    whole set of tanks/stations, [] empties every one — the Weather Manager's
    wind/cloud-layer semantics (docs/designs/weather-manager.md D3), for the
    identical reason: there is no defensible per-index merge (D10).
    """

    tanks: list[TankFuel] | None = None
    stations: list[PayloadStation] | None = None


class LoadoutState(BaseModel):
    """Fully populated fuel and payload, as reported by get_loadout().

    Every known tank/station is present — mirrors AircraftState's "always
    complete" convention rather than AircraftSetup's "None means untouched"
    one (the same WeatherState/WeatherSetup split, D4 of the weather design).
    """

    tanks: list[TankFuel] = Field(description="Every known tank, in adapter order. [] if none.")
    stations: list[PayloadStation] = Field(description="Every known station, in adapter order.")


class CgEnvelopePoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    weight_kg: float = Field(ge=0.0)
    fwd_limit_in: float = Field(description="Forward CG limit at this weight, inches aft of datum.")
    aft_limit_in: float = Field(
        description="Aft CG limit at this weight. >= fwd_limit_in (validator)."
    )


class CgEnvelope(BaseModel):
    """A weight-vs-CG-limit polygon, linearly interpolated between points."""

    model_config = ConfigDict(frozen=True)

    points: tuple[CgEnvelopePoint, ...] = Field(
        min_length=2,
        description="Ascending by weight_kg. Outside the range is a validation failure — no "
        "straight-line extrapolation past a published envelope.",
    )


class AirframeMassLimits(BaseModel):
    """Static mass-and-balance facts about the loaded airframe. All-or-nothing (D5):
    an adapter that cannot supply the complete set reports None on AirframeInfo.mass_limits
    rather than a half-populated model."""

    model_config = ConfigDict(frozen=True)

    empty_weight_kg: float = Field(gt=0.0)
    empty_cg_arm_in: float
    max_takeoff_weight_kg: float = Field(gt=0.0)
    max_zero_fuel_weight_kg: float | None = Field(default=None, gt=0.0)
    max_fuel_kg: float = Field(gt=0.0)
    fuel_tank_capacities_kg: tuple[float, ...] = Field(min_length=1)
    fuel_tank_arms_in: tuple[float, ...] = Field(
        min_length=1, description="Same order/length as capacities."
    )
    payload_station_capacities_kg: tuple[float, ...] = Field(min_length=1)
    payload_station_arms_in: tuple[float, ...] = Field(min_length=1)
    cg_envelope: CgEnvelope

    # validators: fuel_tank_arms_in and fuel_tank_capacities_kg are the same
    # length; same for the station pair.
```

`AirframeInfo` (existing model) gains exactly one field:

```python
mass_limits: AirframeMassLimits | None = Field(
    default=None,
    description="None when neither the simulator nor the core/ fallback table knows this "
    "airframe's mass-and-balance facts — 'unknown' is an honest answer, never invented data.",
)
```

### 3.2 `core/fuel_payload/models.py` — the instructor-facing vocabulary

```python
FuelPayloadPresetId = Literal["ferry", "training", "full", "empty"]


class FuelPayloadPreset(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: FuelPayloadPresetId
    label: str
    description: str
    fuel_fraction: float = Field(
        ge=0.0, le=1.0, description="Fraction of each tank's known capacity."
    )
    station_fraction: float = Field(
        ge=0.0, le=1.0, description="Fraction of each station's known capacity."
    )


FUEL_PAYLOAD_PRESETS: Mapping[FuelPayloadPresetId, FuelPayloadPreset]  # §4


class FuelPayloadRequest(BaseModel):
    """One fuel/payload instruction: a preset, a manual loadout, or a preset with an overlay.

    Lives in core/ (D12), not the router — the Scenario Generator's YAML
    fuel/payload block validates against this exact model, same as
    core.weather.models.WeatherRequest and core.failures.ArmFailureRequest.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    preset: FuelPayloadPresetId | None = None
    loadout: Loadout | None = None
    override_envelope: bool = False

    # model_validator: at least one of preset / loadout.


class MassAndBalanceResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    gross_weight_kg: float
    fuel_kg: float
    payload_kg: float
    cg_arm_in: float | None = Field(default=None, description="None when limits are unknown.")
    limits_source: Literal["adapter", "table", "unknown"]
    within_envelope: bool | None = Field(
        default=None, description="None only when limits_source == 'unknown'."
    )
    violations: tuple[str, ...] = Field(
        default=(), description="Human sentences. Empty unless within_envelope is False."
    )
```

### 3.3 `server/fuel_payload_routes.py` — HTTP furniture only

```python
class FuelPayloadPresetInfo(BaseModel):
    id: FuelPayloadPresetId
    label: str
    description: str


class FuelPayloadManifest(BaseModel):
    adapter: str
    supported: bool
    reason: str | None
    icao_type: str | None
    limits_source: Literal["adapter", "table", "unknown"]
    limits_note: str | None = Field(
        default=None, description="The table entry's disclaimer, when limits_source == 'table'."
    )
    tank_count: int
    station_count: int
    presets: list[FuelPayloadPresetInfo]


class FuelPayloadState(BaseModel):
    loadout: LoadoutState
    mass_and_balance: MassAndBalanceResult


class FuelPayloadPreview(BaseModel):
    request: FuelPayloadRequest
    loadout: LoadoutState  # fully resolved — exactly what apply would write
    mass_and_balance: MassAndBalanceResult
    notes: tuple[str, ...] = ()


class FuelPayloadApplyResult(BaseModel):
    applied: LoadoutState
    state: FuelPayloadState  # the read-back, recomputed — the honest verdict
    notes: tuple[str, ...] = ()
```

### 3.4 `notes` provenance sentences

Same convention as Weather/Position — rendered verbatim, never re-derived:

- `"Fuel — 100% of 2 tanks (152.0 kg total, 76.0 kg each) — the 'ferry' preset."`
- `"Rear seats 21.25 kg, baggage 11.25 kg — the 'training' preset (10% of each station's known capacity); your override left station 0 (Pilot) unchanged at 90.0 kg."`
- `"Mass and balance cannot be verified for this airframe — no published or table CG envelope for 'PA46'. The write proceeds, unverified."`

---

## 4. The preset catalogue — exact values

`core/fuel_payload/presets.py::FUEL_PAYLOAD_PRESETS: Mapping[FuelPayloadPresetId, FuelPayloadPreset]`.
Pure data.

| Preset | `fuel_fraction` | `station_fraction` |
|---|---|---|
| `empty` | 0.0 | 0.0 |
| `training` | 0.5 | 0.10 |
| `ferry` | 1.0 | 0.0 |
| `full` | 1.0 | 1.0 |

Reasoning: `empty` is ramp weight, nobody aboard. `ferry` is the classic max-range, min-weight
configuration — full tanks, no payload. `training` is a light, safe, middle-of-the-envelope
loadout for a normal lesson. `full` is deliberately "everything to its stated maximum" and is
**not** guaranteed to resolve inside the envelope — see the worked table in §7, where it does not,
on purpose, because that is genuinely what "fill every seat and every tank on a light trainer"
does to a real aeroplane, and the point of this manager is to say so rather than hide it (D9).

---

## 5. `SimAdapter` / `Capabilities` additions

> **This section is a shared-foundation change and is never parallelised.** Per the task brief,
> **all three Phase 2 managers' contract changes land together in one `feature/phase2-contract`
> PR** — this section, Weather's §5 and Failures' §4 are made once, by one agent, before any of
> the three managers' backend/adapter/UI tracks branch off it.

### 5.1 The contract

**No new capability flag.** `can_set_fuel_payload` has existed on `Capabilities` since Phase 0
with `PENDING` coverage; this manager retires the `PENDING`. One method is added to the
`SimAdapter` protocol, and one existing field is added to `AircraftSetup`:

```python
async def get_loadout(self) -> LoadoutState:
    """Read the current fuel and payload.

    Requires Capabilities.can_set_fuel_payload — one flag gates the pair,
    exactly the reasoning of get_weather()/set_weather(): fuel burns
    continuously and AircraftSetupResult does not carry configuration, so the
    panel that displays the loadout is the panel that edits it, and an
    adapter that cannot control fuel/payload has no tab to feed.
    """
    ...
```

`AircraftSetup` gains:

```python
loadout: Loadout | None = Field(
    default=None,
    description="Per-tank fuel and per-station payload. Requires can_set_fuel_payload, "
    "the same flag as gross_weight_kg/fuel_kg. When both are set, loadout is authoritative.",
)
```

`apply_setup`'s existing docstring bullet — *"`gross_weight_kg` / `fuel_kg` —
`Capabilities.can_set_fuel_payload`"* — is extended to *"`gross_weight_kg` / `fuel_kg` /
`loadout` — `Capabilities.can_set_fuel_payload`. When `loadout` and the scalar fields are both
set, `loadout` is authoritative and the scalars are applied only when it is absent."*

Why one flag still covers all three fields, and why `loadout` rather than a second flag: they are
the same instructor intent (configure the aircraft's mass) at two levels of detail, and an adapter
implementing one can reasonably be expected to implement the other — exactly the "own capability
per group" reasoning that already put the autopilot behind its own flag, not a per-selector one.

### 5.2 What each adapter must do

**`FakeSimAdapter`** (full implementation, foundation commit):

- Constructor gains `loadout: LoadoutState | None = None`, defaulting to `DEFAULT_LOADOUT` — two
  tanks at 38.0 kg each, one occupied station (`Pilot`, `crew`, 90.0 kg) — the same "plausible,
  distinctive, constructor-settable" affordance as `airframe`.
- `get_loadout()` returns a deep copy of `self._loadout`.
- `apply_setup(setup)`, when `setup.loadout is not None`, replaces `self._loadout.tanks`/`.stations`
  wholesale for whichever of the two sub-fields is not `None` — the same special-case block the
  Fake already has for `lights` in `_merge_setup`, generalised from "merge fields" to "replace
  lists" (D10). This is a **new, separate** store from `self._setup` (the generic
  `applied_setup` affordance): `applied_setup.loadout` proves "the fake recorded exactly what was
  sent," `get_loadout()` proves "the fake's read reflects it" — the first dedicated-read/dedicated-
  write pair the Fake has needed since `get_aircraft_state`/`set_position`.
- `gross_weight_kg`/`fuel_kg` continue to round-trip through `self._setup`/`applied_setup` with
  **zero new code** — the generic `model_dump(exclude_none=True)` merge already carries any scalar
  field added to `AircraftSetup`, per `_merge_setup`'s own docstring.
- `AirframeInfo(mass_limits=...)` is constructor-settable on the fake's existing `airframe`
  parameter, unchanged shape; the default stays the honest all-`None`.

**`XPlaneSimAdapter`** (refusing stub in the foundation commit, D15): keeps
`can_set_fuel_payload=False`; the existing raise site becomes
`if setup.gross_weight_kg is not None or setup.fuel_kg is not None or setup.loadout is not None:
raise CapabilityNotSupported("xplane", "can_set_fuel_payload")` (one added condition); `get_loadout`
raises the same. The adapter track (§9) then implements §6 and flips the flag in the same PR that
passes the fuel/payload contract cases under `-m sim`.

### 5.3 Contract-suite additions

`tests/adapters/test_contract.py`:

```python
CAPABILITY_COVERAGE["can_set_fuel_payload"] = "test_set_loadout_round_trips"

CAPABILITY_GATED_SETUPS["can_set_fuel_payload"] = AircraftSetup(
    gross_weight_kg=60_000.0,
    loadout=Loadout(tanks=[TankFuel(tank_index=0, fuel_kg=100.0)]),
)
```

The second edit is additive — the existing fixture keeps its `gross_weight_kg` value and gains a
`loadout` alongside it, so `test_apply_setup_refuses_capability_gated_fields_it_cannot_honour`
(already written, already exercising this dict) proves in one pass that an adapter without the
flag refuses the **whole group**, scalars and nested field together, with no code change to that
test.

New cases, all skipping (never failing) on an adapter without the flag:

1. **`test_set_loadout_round_trips`** — apply a distinctive loadout (two tanks, two stations of
   different kinds); `get_loadout()` returns it within tolerance. The flag's coverage entry.
2. **`test_loadout_replaces_tanks_and_stations_wholesale`** — apply two tanks, then one, then
   `[]`; read back two, then one, then zero — the D10 semantics, pinned, mirroring the weather
   suite's equivalent cloud-layer case.
3. **`test_get_loadout_returns_a_valid_state`** — shape test: masses ≥ 0, `tank_index`/
   `station_index` unique within each list.
4. **`test_get_airframe_reports_mass_limits_when_known`** — a Fake constructed with
   `AirframeInfo(mass_limits=...)` returns it verbatim; the default Fake returns `None`. No live
   assertion of a *specific* number, mirroring `test_get_airframe_returns_a_model`.
5. **`test_loadout_methods_refuse_without_the_capability`** — on an adapter whose flag is `False`,
   `get_loadout()` and `apply_setup(AircraftSetup(loadout=...))` both raise `CapabilityNotSupported`
   naming `can_set_fuel_payload`.

Live-only tolerance: `LOADOUT_KG_TOLERANCE = {"fake": 0.01, "xplane": 1.0}` — a live simulator's
fuel-mass write/read round trip is not exact to the gram; the Fake's is.

---

## 6. Dataref mapping (X-Plane)

**This section describes `adapters/xplane/` only. No dataref name appears in `core/`.** No mode
forcing is involved (D11) — unlike weather, nothing in X-Plane continuously overwrites a manual
mass write.

### 6.1 Where the writes go — outside the freeze, and why that is not an assumption

`apply_setup` currently splits writes into `_write_configuration` (flaps, gear, trim, throttle,
radios, lights — outside `frozen_flight_model`, because "aircraft configuration... is not part of
the flight model's integration") and `_write_flight_model_state` (attitude, altitude, speed — the
fields a *running* flight model actively fights and reverts, per issue #37's measurements).

Mass belongs with the first group, and the reasoning is not "it looks like a switch" but a
distinction the existing adapter already draws: `_write_flight_model_state` exists because writing
into `sim/flightmodel/position/*` while the integration loop is live gets **overwritten by that
loop** — measured at 164° off for heading. Weight (`sim/flightmodel/weight/*`) is not integrated
that way: it is an *input* the physics reads each frame, the same relationship flaps and gear
already have to the flight model. A sudden weight change is a legitimate, physically-modelled
event — the aircraft reacts to it exactly as it reacts to a real fuel burn or a dropped load — and
nothing in X-Plane re-derives mass and overwrites a manual value the way `psi`/`theta`/`phi` are
re-derived. Loadout writes therefore go through `_write_configuration`, uncontested: **no freeze,
no pause, no settle time**, for a write that changes what the aeroplane weighs but not where it is
or what it thinks its own attitude is.

One consequence stated rather than hidden: applying a loadout mid-flight really does change the
aircraft's weight while it is flying, and the flight model will respond (a sudden weight drop
lightens the wing loading; a sudden gain does the opposite). This is not gated or warned about —
the same "the instructor is the one who can tell whether it matters" posture the hold's
magnetic-course note already established.

### 6.2 The mapping table

| Internal key | Dataref | Type / unit | Confidence |
|---|---|---|---|
| `fuel_tank_kg` | `sim/flightmodel/weight/m_fuel` | float array, kg, indexed write via the existing `_write(key, value, index=)` | **high** — a core flight-model dataref present on every aircraft, not an aircraft-specific failure-system quirk |
| `payload_station_kg` | `sim/flightmodel/weight/m_stations` | float array, kg, indexed write | **high** |
| `fixed_weight_kg` | `sim/flightmodel/weight/m_fixed` | float, kg | **medium** — fallback single-scalar payload write for an aircraft that reports zero configured stations; verify in spike whether it should ever be used *alongside* `m_stations` (it should not — double-counted mass) |
| `acf_empty_weight_kg` | `sim/aircraft/weight/acf_m_empty` | float, kg, read-only | medium/high |
| `acf_max_weight_kg` | `sim/aircraft/weight/acf_m_max` | float, kg, read-only | medium/high |
| fuel tank capacities | candidate `sim/aircraft/overflow/acf_tank_rat[]` (ratio × total) or a direct per-tank capacity array | — | **low — verify in spike** |
| station capacities | no known public dataref publishing a *maximum* per station, only the current mass | — | **low — likely table-only in practice, §11.1** |
| tank/station arms (moment arm from datum) | no known public dataref | — | **low — expect table-only, §11.1**, flagged as the design's largest unresolved item |
| current CG position | no known public dataref returning a usable structured value | — | **not attempted from the live sim** — CG is computed in `core/` from masses and arms, never read back as a single number (§6.3) |

`get_airframe()`'s `mass_limits` field is therefore expected, in practice for Phase 2, to come back
`None` from the live X-Plane adapter for most or all installs — `resolve_mass_limits`'s
table fallback (D6) is not a fallback for an edge case, it is expected to be the **primary** path
until the arm/capacity/envelope datarefs are confirmed or found absent. This is stated plainly
rather than implied, and is the subject of §11.1.

`get_loadout()` reads `fuel_tank_kg` and `payload_station_kg` as whole arrays (the Web API returns
the full array on a plain read) and slices them into `TankFuel`/`PayloadStation` lists in Python,
against a tank/station count read once at connect (candidate: `sim/aircraft/weight/acf_num_tanks`
/ an equivalent station count — **verify in spike**).

### 6.3 CG is computed, never read

`core.fuel_payload.mass_and_balance.compute_mass_and_balance` takes `LoadoutState` and
`AirframeMassLimits` and computes gross weight, fuel total and CG arm from masses × arms it already
has (§7) — it never asks the adapter for "the CG," because no reliable dataref for it is known to
exist. This is a deliberate design choice, not a gap: the arithmetic is `core/` and sim-agnostic,
which also makes it trivially unit-testable without any adapter (§9.1).

### 6.4 Adapter capability change and MSFS

`_CAPABILITIES` flips `can_set_fuel_payload=True` in the same PR that implements §6.1–6.2 and
passes the §5.3 cases under `-m sim` — never before, mirroring D15/§9.

MSFS (Phase 5 target): SimConnect's `FUEL TANK ... QUANTITY` simvars and `PAYLOAD STATION WEIGHT`
are both reasonably well documented and writable, so this manager is plausibly *easier* to reach
feature-parity on than Weather or Failures. Nothing here assumes it; noted so the Phase 5 adapter
has a target.

---

## 7. `core/` logic

New package `core/fuel_payload/` — models (§3.2), presets (§4), limits, and mass-and-balance
arithmetic. No HTTP, no dataref, no `NavdataProvider` import; fully unit-testable with no
simulator and no adapter.

```python
# core/fuel_payload/limits.py


class AircraftMassLimitsEntry(BaseModel):  # frozen
    icao_type: str
    limits: AirframeMassLimits
    source_note: str  # UI-facing disclaimer, always shown


AIRCRAFT_MASS_LIMITS_TABLE: Mapping[str, AircraftMassLimitsEntry]


class ResolvedMassLimits(BaseModel):  # frozen
    limits: AirframeMassLimits
    source: Literal["adapter", "table"]


def resolve_mass_limits(airframe: AirframeInfo) -> ResolvedMassLimits | None:
    """airframe.mass_limits when the adapter supplied it; else the table entry
    keyed by airframe.icao_type; else None. Pure, no I/O."""


# core/fuel_payload/mass_and_balance.py


def compute_mass_and_balance(
    state: LoadoutState, limits: ResolvedMassLimits | None
) -> MassAndBalanceResult:
    """gross_weight_kg = limits.empty_weight_kg + sum(fuel) + sum(stations);
    cg_arm_in = weighted average of (mass, arm) over empty + every tank + every
    station, using limits.fuel_tank_arms_in / payload_station_arms_in by
    index. Interpolates limits.cg_envelope linearly between the two bracketing
    weight points (clamped: a weight outside the published range is itself a
    violation, not extrapolated past). limits=None -> limits_source='unknown',
    cg_arm_in=None, within_envelope=None, violations=()."""


def resolve_request(
    request: FuelPayloadRequest,
    *,
    current: LoadoutState,
    limits: ResolvedMassLimits | None,
) -> tuple[LoadoutState, MassAndBalanceResult, tuple[str, ...]]:
    """Resolve a preset (core/fuel_payload/presets.py::resolve_preset) and/or
    request.loadout into a COMPLETE LoadoutState — unlike core.weather's
    resolver, this never returns a partial result: mass-and-balance is a
    whole-aircraft computation, so every tank/station in `current` is
    represented, its value replaced only where the preset or the overlay
    states one. Then compute_mass_and_balance() on the result.

    Raises ValueError when a preset is requested and limits is None (nothing
    to resolve capacity fractions against)."""
```

```python
# core/fuel_payload/presets.py
def resolve_preset(
    preset: FuelPayloadPreset,
    *,
    current: LoadoutState,
    limits: ResolvedMassLimits,
) -> LoadoutState:
    """tank.fuel_kg = preset.fuel_fraction * limits.fuel_tank_capacities_kg[i] for
    every known tank; station.weight_kg = preset.station_fraction *
    limits.payload_station_capacities_kg[i] for every known station."""
```

### 7.1 Worked reference values (the "computable by hand" table the test plan uses)

One illustrative `core/fuel_payload/limits.py` table entry, `AIRCRAFT_MASS_LIMITS_TABLE["C172"]`
(rounded, POH-derived, carrying the disclaimer *"Illustrative C172S figures — verify against your
aircraft's POH before a lesson depends on them."*):

| Field | Value |
|---|---|
| `empty_weight_kg` / `empty_cg_arm_in` | 743.0 / 39.0 |
| `max_takeoff_weight_kg` | 1157.0 |
| `max_zero_fuel_weight_kg` | `None` (not published for this class) |
| `max_fuel_kg` | 152.0 |
| tanks (capacities / arms) | (76.0, 76.0) kg / (48.0, 48.0) in |
| stations (capacities / arms) | (85.0, 85.0, 45.0) kg / (37.0, 73.0, 95.0) in — "Pilot/Front", "Rear seats", "Baggage" |
| `cg_envelope` | (700 kg: 34.0–41.0 in), (1000 kg: 35.0–40.5 in), (1157 kg: 35.5–40.0 in) |

Every preset resolved against this table, by hand:

| Preset | Tanks (kg) | Stations (kg) | Gross (kg) | CG arm (in) | Envelope at that weight | Verdict |
|---|---|---|---|---|---|---|
| `empty` | 0, 0 | 0, 0, 0 | 743.0 | 39.00 | 34.14 – 40.93 | **within** |
| `ferry` | 76, 76 | 0, 0, 0 | 895.0 | 40.53 | 34.65 – 40.68 | **within** (margin 0.15 in) |
| `training` | 38, 38 | 8.5, 8.5, 4.5 | 840.5 | 40.44 | 34.47 – 40.77 | **within** (margin 0.33 in) |
| `full` | 76, 76 | 85, 85, 45 | 1110.0 | 44.95 | 35.35 – 40.15 | **refused — 4.80 in aft of the aft limit** |

`full` is the deliberate, disclosed counter-example of D9: filling every seat, the baggage hold and
both tanks on a light trainer is not flyable in real life either, and the manager says so instead
of quietly allowing it. `training` and `ferry` are within envelope with a modest, realistic margin
— the everyday case works cleanly; the edge case is refused with a reason, exactly per the feature
spec.

---

## 8. UI panel outline

New tab of the Instructor Panel: `ui/src/features/fuel-payload/` — the folder name mirrors the
`/api/fuel-payload/*` prefix 1:1, unlike the single-word sibling folders (`position`, `weather`),
because there is no established multi-word convention yet and this keeps client/server trivially
correlated. Adding it adds files; no existing panel file is edited beyond the mount point.

**Mounting.** As of this design, `ui/src/App.tsx` mounts panels directly (`<PositionPanel />`,
`<AircraftControlPanel />` inside `app__workspace`) — there is no tab-bar abstraction in the
working tree today, and the Weather/Failures designs mount the same way (`docs/designs/
weather-manager.md` §8: *"exactly two shared-file edits: mounting WeatherPanel in App.tsx, and
nothing else"*). `FuelPayloadPanel` mounts the same way, as a third addition to `app__workspace`.
**If a tab system (e.g. `ui/src/store/uiSlice.ts`'s `TAB_IDS`, `ui/src/components/tabs.ts`, a
`TabBar`) lands before this manager is implemented** — plausible once Weather, Failures and this
manager are all competing for the same screen — the mount point becomes "register a tab" instead
of "add a JSX line," and that edit is shared with Training Profiles' own future tab addition: it
must be **sequenced, not parallelised**, against whichever manager gets there first (§11.5).

### 8.1 Server state — RTK Query (`fuelPayloadApi.ts`, D16)

| Endpoint | Kind | Notes |
|---|---|---|
| `getFuelPayloadManifest` | query | fetched on mount; drives the gate and the preset tiles |
| `getFuelPayload` | query, tag `FuelPayload` | current loadout + M&B, the editor's baseline |
| `previewFuelPayload` | **query** despite being `POST` — the `previewPlacement`/`previewWeather` precedent | keyed on the staged `FuelPayloadRequest` |
| `applyFuelPayload` | mutation, invalidates `FuelPayload` | the only call that touches the simulator |

All types come from the regenerated `ui/src/api/schema.d.ts`. Nothing is hand-written.

### 8.2 Client state — one slice (`fuelPayloadSlice.ts`)

```ts
interface FuelPayloadPanelState {
  selectedPresetId: FuelPayloadPresetId | null;
  overlay: Loadout; // sparse edits the tank/station editors accumulate
  overrideEnvelope: boolean; // surfaces only after a preview reports a violation
  staged: FuelPayloadRequest | null;
}
```

Server data never lands in the slice. Reducers: `presetSelected`, `tankEdited`, `stationEdited`,
`overrideToggled`, `staged`, `cleared`. Selecting a different preset **clears** `overrideEnvelope`
and any manual overlay for the same reason the Weather panel clears a staged preset on airport
change: a violation acknowledged for one loadout must not silently carry over to the next.

### 8.3 Components, top to bottom

1. **`PresetGrid`** — four large tiles (`Empty`, `Training`, `Full`, `Ferry`), each staging its
   `FuelPayloadRequest` on tap. Disabled with a reason when the manifest's `limits_source` is
   `"unknown"` — a preset genuinely cannot resolve without capacities (§2.2).
2. **`TankEditor`** — one row per known tank: capacity bar, kg input, `%` readout. "Fill" / "Drain"
   quick actions per row.
3. **`StationEditor`** — one row per known station: kind chip (crew/passenger/cargo/other, tap to
   relabel), kg input, capacity bar.
4. **`MassAndBalanceReadout`** — gross weight vs MTOW, fuel total, and a small SVG CG-vs-envelope
   graphic drawn directly from `AirframeMassLimits.cg_envelope` (no server-side schematic model
   needed — unlike the Position panel's `PlacementSchematic`, the envelope polygon *is* the wire
   data already) with the computed CG plotted as a dot; red when `within_envelope is False`, amber
   with a "cannot verify" label when `limits_source == "unknown"`.
5. **`FuelPayloadStagingBar`** — persistent, bottom: the preview's resolved loadout and M&B, `notes`
   underneath in tertiary text, an **Apply loadout** button. When the preview reports
   `within_envelope: false`, the button becomes secondary/disabled and an explicit **"Load anyway
   — I understand this is outside the envelope"** checkbox appears next to it (sets
   `overrideEnvelope`); ticking it re-enables Apply. Success reports the read-back
   (`FuelPayloadApplyResult.state`), never the request; failures render inline, never a modal.

### 8.4 Gating (`gate.ts`)

`fuelPayloadGate(manifest, isError)` — fails closed on loading, on error, and when `supported` is
false, the `position/gate.ts` pattern verbatim. The panel body stays visible with the reason so the
instructor can see *what* is unavailable and *why* (per the manifest, e.g. "the 'xplane' adapter
does not declare can_set_fuel_payload").

Tablet-first: 44 px+ touch targets on every row and chip, the preset grid above the fold, the CG
graphic sized to be legible on a tablet held in portrait, `tabular-nums` on every weight/kg
readout.

---

## 9. Test plan

Everything except §9.4 runs in CI against `FakeSimAdapter`. No navdata, no fixtures from any
simulator install (D17) — this manager needs neither.

### 9.1 `core/` unit tests — `tests/core/fuel_payload/`

The §7.1 table, asserted exactly (all four presets, all four verdicts, CG arms to two decimal
places, the `full` refusal's violation sentence naming the exact aft-limit excess):

- `compute_mass_and_balance`: the four worked numbers above; `limits=None` → `limits_source ==
  "unknown"`, `within_envelope is None`, `cg_arm_in is None`, `violations == ()`.
- CG-envelope interpolation at an exact table weight (1000 kg → 35.0/40.5, no interpolation
  needed) and at a bracketed weight (872.75 kg, `training`'s pre-adjustment gross — see the
  Training preset's derivation in §7.1) — both against the hand-computed numbers above.
- A weight above `max_takeoff_weight_kg` produces a distinct violation sentence
  (`"Gross weight ... exceeds MTOW ..."`) independent of and in addition to any CG violation —
  asserted with a fixture at, say, 1200 kg gross, all fuel, no baggage (CG stays forward, only the
  weight check fires) to prove the two checks are independent.
- `resolve_preset`: `full` against the §7.1 table resolves tank 0 to exactly 76.0 kg (100% of
  76.0), station 2 (baggage) to exactly 45.0 kg (100% of 45.0).
- `resolve_request`: a manual overlay touching only `tanks` leaves `current.stations` unchanged in
  the resolved result — the "seeded from current" half of D4/D9, pinned; an overlay with an
  unknown `tank_index` raises `ValueError` naming it.
- `resolve_mass_limits`: an `AirframeInfo(mass_limits=...)` wins over the table; an
  `AirframeInfo(icao_type="C172", mass_limits=None)` falls back to the table entry with
  `source="table"`; an unknown `icao_type` and no `mass_limits` → `None`.
- Model validation: `CgEnvelopePoint.aft_limit_in < fwd_limit_in` refused; `AirframeMassLimits`
  with mismatched tank capacity/arm tuple lengths refused; `FuelPayloadRequest` with neither
  `preset` nor `loadout` refused; an unknown extra field refused (`extra="forbid"`).

### 9.2 Contract tests — `tests/adapters/test_contract.py`

The five cases of §5.3, parametrised over `fake` (CI) and `xplane` (`-m sim`), plus
`test_every_capability_is_covered` retiring the `can_set_fuel_payload` `PENDING` entry, and
`test_apply_setup_refuses_capability_gated_fields_it_cannot_honour` picking up the extended
`CAPABILITY_GATED_SETUPS` entry automatically (no new test needed there — it is table-driven).

### 9.3 Server tests — `tests/server/test_fuel_payload_routes.py`

Against `TestClient` + `FakeSimAdapter`: every endpoint; every error row of §2.2; `preview` reads
`get_loadout()` but never `apply_setup` (`TestPreviewIsSideEffectFree`, the Position/Weather
pattern, adapted: assert `get_loadout()` unchanged across the preview call rather than
`get_aircraft_state()`); `apply` on the `full` preset (§7.1) returns 422 with the aft-CG sentence
and `override_envelope=True` on the same request succeeds; `apply` on `training` succeeds and the
response's `state.mass_and_balance` matches the recomputed (not the pre-write) numbers; the 501
sentences name the adapter and the flag; the manifest lists four presets and reports
`limits_source` correctly against a Fake constructed with and without `mass_limits`.

### 9.4 `@pytest.mark.sim` — `tests/sim/test_live_fuel_payload.py` (never in CI)

- The §6.2 dataref guesses, read/write, one round trip per tank/station — this validates or kills
  the "verify in spike" rows of §6.2 and §11.1 empirically.
- Whether `mass_limits` comes back populated at all on the user's aircraft — logged, not asserted,
  because the honest expectation (§6.2) is that it will not for most installs in Phase 2.
- Applying a loadout mid-flight and observing the aircraft's IAS/attitude are undisturbed
  immediately after the write (proving §6.1's "no freeze needed" reasoning empirically, not just
  by argument).
- Restores the aircraft's pre-test loadout in a `finally` — mass is state the live-suite rules
  require restoring, same as position.

### 9.5 UI tests (vitest)

`gate.test.ts` (fail-closed on loading/error/unsupported); `fuelPayloadSlice.test.ts` (preset
change clears the overlay and the override flag); `PresetGrid.test.tsx` (each tile stages the
exact `FuelPayloadRequest`, `toEqual`; disabled with the manifest's reason when
`limits_source === "unknown"`); `MassAndBalanceReadout.test.tsx` (renders the four §7.1 numbers
from a fixed prop, including the "cannot verify" state); `FuelPayloadStagingBar.test.tsx` against
stubbed `fetch` (a violated preview disables Apply until the override checkbox is ticked; Apply
sends the staged request verbatim including `override_envelope`; the confirmation reports the
read-back).

### 9.6 Fixtures

None beyond the §7.1 table, which lives in test code as a `FuelPayloadPresetId`-keyed dict of
expected `(gross_kg, cg_arm_in, within_envelope)` tuples — no navdata file, no simulator install
artefact, nothing hand-written that could be mistaken for redistributed data (hard rule 4 is not
even in play here).

---

## 10. Parallelisation

### 10.1 Across Phase 2

Weather ∥ Failures ∥ Fuel & Payload are three independent `feature/*` branches in separate git
worktrees, each with its own PR to `dev`. **All three managers' contract changes land together in
one `feature/phase2-contract` PR** (per the Phase 2 combined-foundation plan) — this design's §5
is merged there, not on a manager-specific branch, alongside Weather's §5 and Failures' §4. What is
forbidden is two agents editing `core/sim_adapter.py`, `core/models.py`, `adapters/fake/`, or
`tests/adapters/test_contract.py` concurrently; the three managers' foundation slices are made
serially against each other inside that one PR, in whatever order is agreed, before any of the
three backend/adapter/UI tracks branch off it.

### 10.2 Inside this manager, once the foundation PR has merged

| Track | What | Owns (disjoint) | May start |
|---|---|---|---|
| **Backend** | `core/fuel_payload/*` (models, presets, limits, mass_and_balance), `server/fuel_payload_routes.py` + the `include_router` line in `app.py`, `tests/core/fuel_payload/`, `tests/server/test_fuel_payload_routes.py` | `core/fuel_payload/`, `server/fuel_payload_routes.py`, `tests/core/fuel_payload/`, `tests/server/test_fuel_payload_routes.py` | immediately after the foundation PR |
| **X-Plane adapter** | the §6.2/§11.1 spike, then §6.1–6.3: dataref writes, tank/station count probing, flag flip, `tests/sim/test_live_fuel_payload.py` | `adapters/xplane/`, `spikes/fuel_payload_datarefs.py`, `tests/sim/` | immediately; **the spike first**, independent of the backend track |
| **UI panel** | `ui/src/features/fuel-payload/*`, the `App.tsx` mount, `schema.d.ts` regeneration | `ui/` | after the backend track's routes exist on the branch — the client is generated from the running server's OpenAPI schema (the Position doc's recorded constraint, §20 there) |

Backend and X-Plane adapter are dispatched **in a single message** once the foundation PR is
merged; UI follows backend within the branch. The tester writes §9.1–§9.3 against this document
without waiting for any implementation.

**Never parallelised, restated:** the foundation slice (§5, inside `feature/phase2-contract`);
any later change to `Loadout`/`LoadoutState`/`AirframeMassLimits` (contract vocabulary); merges to
`dev`/`main`; release tagging. If a tab-bar system's shared files (§8, `uiSlice.ts`/`tabs.ts`) land
before this manager's UI track starts, that edit is sequenced against Training Profiles' own tab
addition, not parallelised with it.

---

## 11. Open questions and risks

### 11.1 Whether X-Plane publishes tank/station capacities and arms at all — the largest unresolved item

§6.2 marks capacity and arm datarefs "low confidence" and CG readback "not attempted" for a
reason: unlike the failures catalogue's `rel_*` family (a well-documented, stable naming scheme),
X-Plane's per-aircraft moment-arm data may simply not be exposed over the public dataref surface —
it can be entirely internal to the `.acf` file. **What resolves it:** the spike
(`spikes/fuel_payload_datarefs.py`), first task of the X-Plane track: connect, enumerate everything
under `sim/aircraft/weight/` and `sim/flightmodel/weight/`, and record what is actually readable.
**If arms genuinely are not exposed, the design does not need to change** — `resolve_mass_limits`'s
table fallback (D6) already treats this as the expected path, not a degraded one; the practical
consequence is that `AIRCRAFT_MASS_LIMITS_TABLE` needs entries for every aircraft type an
instructor actually trains in, which is an open-ended, ongoing authoring task rather than a
one-time spike — flagged as ongoing maintenance, not a blocking defect.

### 11.2 The equal-fraction preset model can resolve out of envelope, by design (D9)

§7.1's worked `full` preset is the disclosed proof. This is presented as a feature (presets are
resolved then validated like everything else) but it is worth a user decision: should `Training` —
the preset an instructor is expected to reach for daily — ever be allowed to resolve out of
envelope for *some* real airframe's table entry, given it currently does not for the illustrative
C172 entry only by a 0.33 in margin that this design hand-tuned to pass? **What resolves it:** a
"loading priority" refinement (fill front seats before baggage) is a bounded `core/` addition if
instructors report the current model surprising them; not built here because it adds real
complexity (ordering, not just fractions) for a problem the preview-before-commit flow already
catches safely.

### 11.3 Wiring this manager into `Placement.to_setup()`

The feature spec states this manager "feeds the Position Manager's automatic setup, which sets
weight and fuel as part of every placement" as a forward-looking consequence, not as this
manager's own scope (§1.2). Doing so later reopens `position-manager.md` §9.3's dormant
whole-call-refusal gap: `to_setup()` currently emits only `can_set_aircraft_state` fields, so an
adapter without `can_set_fuel_payload` never sees a placement's `apply` fail on that account; the
day `to_setup()` starts emitting `loadout`, every placement on such an adapter would start failing
outright unless capability *filtering* (the position design's un-built §9.3 idea) is finally
built. **What resolves it:** a Position Manager decision, explicitly deferred, not a Fuel & Payload
one — this design only makes sure it is visible rather than silently inherited.

### 11.4 The all-or-nothing `mass_limits` model may be too strict

D5 refuses partial airframe knowledge (e.g. a live MTOW without a live CG envelope) rather than
representing it. This is the honest choice for Phase 2's binary "adapter vs table" resolution
chain, but it discards a real intermediate case — an adapter that can read weight limits live but
has no CG data would be forced to `None` and fall through to the table (or "unknown") rather than
combining live weight limits with table-sourced arms. **What resolves it:** if the X-Plane spike
(§11.1) finds weight limits readable but arms not, a follow-up "partial adapter + table-filled
rest" merge is a natural extension of `resolve_mass_limits` — not built here to avoid designing
around a hypothetical before the spike confirms it.

### 11.5 The tab-bar mount point

§8 designs the mount as a direct `App.tsx` addition, matching the sibling docs and today's actual
`App.tsx`, while flagging that a tab system may land first. This is stated as an open item rather
than resolved because the deciding fact (whether such a system exists by the time this manager's
UI track starts) is outside this design's control.

### 11.6 Architecture known risks touched

None of the five risks in `docs/architecture.md` are centrally this manager's — it introduces its
own new one, worth adding there when this design lands: **"per-aircraft mass-and-balance data may
not be available from the simulator at all, making a hand-authored table the primary rather than
fallback source of truth"** (§11.1), in the shape of risk 5 (MSFS subset)'s architectural
consequence: `Capabilities` and the manifest's `limits_source` field are exactly the mechanism for
disclosing it, and no code outside `core/fuel_payload/limits.py` changes as the table grows.

---

## 12. Verification

```bash
pytest                       # unit + contract, Fake only — must be green before any merge
pytest -m sim                # the X-Plane track's gate: §9.4 against a live simulator
ruff check . && ruff format --check .
mypy .                       # the protocol conformance assignment catches a missing get_loadout
cd ui && npm run lint && npm run typecheck && npm test && npm run build
```

Panel smoke (fake adapter + Vite dev server, one batched browser session): manifest loads with
four presets, `limits_source: "table"` shown with the C172 disclaimer → `Training` tile → preview
shows gross weight, fuel, CG within envelope → Apply → confirmation reports the read-back →
`Full` tile → preview shows the CG violation and a disabled Apply → tick "load anyway" → Apply
succeeds → console clean. No live simulator needed; the real-sim proof is `pytest -m sim` and the
`sim-validator`'s smoke, neither a merge gate.

---

## Design-time caveat: filesystem state at write time

This design was written against a working tree that, at read time, showed no tab-bar system and
no `weather`/`failures` UI folders — a consequence of the shared checkout being on a git branch
that did not yet carry the (separately landed) UI panel work at that moment, not a real absence.
§8 and §11.5 already flag the resulting mount-point uncertainty explicitly; confirm the actual
`App.tsx`/`tabs.ts` shape (now on `dev`) before implementing the UI track.
