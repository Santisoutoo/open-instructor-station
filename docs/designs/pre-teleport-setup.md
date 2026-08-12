# Full pre-teleport aircraft setup

Issues #8, #81, #82. The part of the Position Manager that makes a placement *flyable*
rather than just geometrically correct.

The Phase 1 live validation (`reports/sim-validation-2026-08-10-1321.md`) placed a C172 on
a 10 NM ILS final with sub-metre geometry and still delivered an unflyable aeroplane:
elevator trim at the parked 0.07, throttle drifting uncommanded to 0.783, no descent rate,
and a divergent phugoid of ±2400 fpm and ±15° of pitch within 20 s (#81) — at 120 kt,
because the approach category was assumed to be B when the airframe is category A (#82).
Speed alone is not a stabilised approach; this design delivers the rest of it (#8).

## The shape of the change

Three PRs. The first is a `SimAdapter` contract change and therefore lands **alone**, per
the never-parallelise rule; the other two build on it and run in parallel with the rest of
the Phase 1 close-out.

| PR | Branch | Contents |
|---|---|---|
| 0 | `feature/setup-contract` | This document. `AircraftSetup.throttle_ratio`. `AirframeInfo` + `SimAdapter.get_airframe()`. `set_position(..., vertical_speed_fpm=)`. Optional-dataref handling in the X-Plane adapter. `ils_freq_khz` routed to NAV1. Contract-suite coverage. |
| A1 | `feature/pre-teleport-profiles` | Placement profiles: `Placement.profile/ils/glideslope_deg/pattern_leg`, `to_setup()` emitting the full configuration, descent delivery through the apply flow. |
| A2 | `feature/airframe-category` | Approach category derived from the loaded airframe instead of assumed. |

## PR 0 — the contract

### `AircraftSetup.throttle_ratio`

`float | None`, `0.0 ≤ x ≤ 1.0`, `None` = leave the levers alone. Gated under the existing
`can_set_aircraft_state` — throttle is aircraft state exactly like `flaps_ratio`, so no new
capability flag and no new `CAPABILITY_COVERAGE` entry.

X-Plane write path: `sim/cockpit2/engine/actuators/throttle_ratio_all`, which fans one
value out to every engine. The contract is **commanded at placement, not held**: a
study-level aircraft whose own systems move the levers afterwards is expected behaviour,
the same posture as every other switch in the setup.

### `AirframeInfo` and `get_airframe()`

```python
class AirframeInfo(BaseModel):  # frozen
    icao_type: str | None  # e.g. "C172"
    vso_kias: float | None  # stall speed, landing configuration, KIAS
```

`SimAdapter.get_airframe() -> AirframeInfo` is a **capability-free read**, the same
standing as `get_aircraft_state`: reads never need flags, they degrade. The all-`None`
model is the honest "this adapter cannot know" answer, never an exception.

The X-Plane source datarefs are the first **optional** datarefs in the adapter:
`sim/aircraft/view/acf_ICAO` (byte array) and `sim/aircraft/overflow/acf_Vso`. Their
availability over the Web API is unverified against a live 12.x build, so `connect()`
indexes them *if present* and hard-fails only on the required set, exactly as before. A
missing optional dataref degrades the corresponding field to `None`; nothing else changes.
`core/` never reads them — the airframe arrives as an input (hard rule 2), which is what
A2 builds on.

### `set_position(..., *, vertical_speed_fpm: float | None = None)`

`_write_velocity_vector` wrote `local_vy = 0.0` unconditionally: **every teleport arrived
level**, so any descent rate `apply_setup` had commanded was destroyed one call later.
This is issue #39's lesson — a value written into one call is not delivered until the
other end carries it too — repeating for the vertical axis, and it is why the parameter
exists at the contract level rather than as an adapter detail.

`None` keeps today's behaviour (arrive level). A value becomes the vertical component of
the velocity vector. The horizontal component stays the full TAS along the heading: at a
3° glide the cosine correction is 0.14 % — noise against the 15 kt live tolerance — and
dropping it keeps the still-air groundspeed identity that #42 will revisit with the wind
datarefs.

### `ils_freq_khz` routed to NAV1

The `NotImplementedError` goes away. X-Plane's ILS receiver **is** the NAV1 radio, so
`ils_freq_khz` writes `nav1_freq` (and nothing else). Precedence when a setup carries
both: **`nav1_freq_khz` wins** — the explicit radio field beats its alias. Pinned by a
mapping-layer unit test.

### Contract-suite coverage

- `test_apply_setup_records_throttle` — throttle propagates and `None` leaves it alone
  (Fake read-back via `applied_setup`; live acceptance is the write not erroring, same
  posture as the autopilot selectors).
- `test_get_airframe_returns_a_model` — both adapters return an `AirframeInfo`;
  `vso_kias`, when known, is positive. Never asserts a specific airframe on a live sim.
- `test_set_position_delivers_the_vertical_speed` — Fake exact; live reads `vh_ind_fpm`
  back inside one freeze with a generous tolerance.

## PR A1 — placement profiles (#8 + #81)

### Where the profile knowledge lives

`Placement` today carries position/heading/ias and nothing that distinguishes a short
final from a hold. The knowledge exists only in the constructor that built the placement,
so that is where it is captured — four new fields on the frozen model, all assigned by the
constructors, none guessed:

- `profile: Literal["final", "circuit", "airborne", "ground"]` — **required, no
  default**, the same philosophy as `ias_kt`: a new placement type cannot be written
  without answering the question. `final_placement` → `"final"`; `pattern_placement` →
  `"circuit"`; waypoint/hold/hold-entry/procedure legs → `"airborne"`;
  `coordinate_placement` → `"ground"` when `ias_kt == 0`, `"airborne"` otherwise (0 kt is
  definitionally not flying); parking stands go through `coordinate_placement` and are
  ground.
- `ils: Ils | None` — `final_placement` grows an `ils` parameter and the server passes
  `runway.ils`, which it already holds. Tuning arrives with the placement, so no caller
  can place an aircraft on an approach while forgetting the radios (the same argument
  that put `Ils` on `Runway`).
- `glideslope_deg: float | None` — finals only; the descent rate follows from it.
- `pattern_leg: PatternLeg | None` — circuit only; gear and flaps differ per leg.

`to_setup()` keeps its three geometry fields and gains the profile configuration —
*extending* the method, as its docstring promised.

### What each profile emits

| profile | gear | flaps | throttle | trim | roll | vertical speed | radios / lights |
|---|---|---|---|---|---|---|---|
| `final` | down | 0.5 | 0.30 | +0.10 | 0.0 | −(ias_kt · 101.269 · tan gs) / 60 fpm | NAV1 + OBS1 from `ils` when present; landing light on |
| `circuit` | down on downwind/base, up on upwind/crosswind | 0.25 on base, else 0.0 | 0.50 | 0.0 | 0.0 | 0.0 | — |
| `airborne` | up | 0.0 | 0.60 | 0.0 | 0.0 | 0.0 | — |
| `ground` | down | 0.0 | 0.0 | 0.0 | — | — | — |

The descent-rate arithmetic: ground speed ≈ IAS at approach altitudes, one knot is
101.269 ft/min of horizontal travel, so a 3° slope at 90 kt is −478 fpm.

**The trim and throttle values are a hand-off state for a pilot, not a flight model.**
They are fixed, airframe-generic constants — approach power and a touch of nose-up trim
for a 3° descent in landing configuration — deliberately of the same honesty class as the
category speed tables: named constants in `core/geodesy.py`, disclosed verbatim in the
preview notes, always overridable by the instructor's sparse setup overlay, which wins by
the existing merge order. Flaps are 0.5 rather than full because full landing flap at a
category-table speed exceeds a jet's Vfe; a mid-setting is survivable everywhere. Per-
airframe trim curves are explicitly out of scope — #81's own framing is that a pilot is at
the controls in a real session; the profile only has to hand over an aeroplane that is
*near* its trimmed state instead of diverging away from it.

### Delivering the descent

`apply_placement` passes `vertical_speed_fpm=setup.vertical_speed_fpm` into
`set_position` next to `ias_kt`, with the same justification: the flight model is
released between the two calls and anything not re-delivered decays.

## PR A2 — airframe-derived category (#82)

Pure function in `core/geodesy.py`:

```python
VAT_FROM_VSO = 1.3                                   # ICAO PANS-OPS
def category_for_vat(vat_kt: float) -> ApproachCategory   # A <91, B <121, C <141, D <166, E ≤210
```

Vso arrives as an input — core never reads a simulator. The server caches `AirframeInfo`
once at adapter connect (`server/deps.py`); `preview_placement` is deliberately sync and
never awaits the sim, so it reads the cache. Staleness (the user swapping aircraft
mid-session) is accepted and documented; the failure mode is the pre-#82 status quo — a
wrong but disclosed default — and a lazy TTL re-read is the noted follow-up.

`request_category` becomes a fallback chain:

1. the category stated in the request (the instructor's word is final);
2. derived from the cached airframe — `Vso → 1.3·Vso → band`, disclosed as
   *"Category A — derived from the loaded airframe (Vso 48 kt, V_AT 62 kt)"*;
3. today's category B default with today's honest note.

Using 1.3·Vso directly as the approach speed (rather than the top of the derived band) is
a follow-up, not built here: the issue's stated ask is the category.

## Deferred, with rationale

- **`gross_weight_kg` / `fuel_kg` (`can_set_fuel_payload`)** — declaring the flag means
  fuel-tank arrays, payload stations, contract coverage and UI gating: that is the Fuel &
  Payload Manager (#16, Phase 2) whole. Mass does not gate a stabilised placement. The
  fields keep raising `CapabilityNotSupported`; #8 closes with that item split off to #16.
- **Wind in the velocity vector** — #42, Phase 2 with the Weather Manager's datarefs.
- **Merging the `apply_setup` + `set_position` freezes** — each pays its own ~1 s release
  settle and the measured apply latency was 3.3–4.1 s against the 5 s criterion. Halving
  that is an adapter-internal optimisation; filed as a follow-up after #12 measures the
  margin again.
- **Per-airframe approach speed (1.3·Vso as the number, not the band)** — follow-up to A2.
