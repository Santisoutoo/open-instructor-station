# Zibo 737 pedestal / throttle quadrant / lights dataref mapping — candidate discovery

Phase 1 (candidate discovery only) for issue #224, Wave 2 of the cockpit-control-catalog epic
(#225). **No live simulator was touched to produce this document.** Every dataref and command
name below comes from the Zibo addon's own shipped reference files:

| | |
|---|---|
| Sources | `C:\X-Plane 12\Aircraft\B737-800X\B738_Datarefs.txt` (368 lines, "Release 2.35") and `C:\X-Plane 12\Aircraft\B737-800X\B738_Commands.txt` (521 lines, "Release 3.05y") |
| Method this phase | Read both files in full; matched names against the scope in issue #224 (throttle quadrant, pedestal, lights); classified each candidate's likely `CockpitControlKind` (`docs/designs/cockpit-control-catalog.md` §3.1/§3.2) from its name and description alone |
| Method **not** used this phase | No live read, no live write, no read-back, no `xplane-datarefs` MCP tool, no `pytest -m sim`. Nothing below has been operationally verified in the sense `adapters/xplane/cockpit_catalogs/README.md` requires for a `verified_on` date. |
| Precedent | `docs/research/zibo-737-autopilot-dataref-mapping.md` (#214/#222) — same standard: discover, then verify live, then park what's inconclusive, never guess. This document stops at "discover" and states everywhere it has not gone further. |
| Scope boundary | Overhead panel electrical/fuel/hydraulic/anti-ice/pneumatic/IRS items are explicitly **out of scope** here — that is #223, running in parallel in a different worktree. Anything in this document that turned out to live on the overhead panel (e.g. the engine start **selector**, as opposed to the start **levers**) has been excluded, not silently annexed. |

**Every entry below is marked `UNVERIFIED`. None of it has been read back against a running
X-Plane. This is deliberate — Phase 1 of #224 is candidate discovery only; live verification is a
separate, later message once the shared "sim slot" (D15) is this issue's turn.**

The reference files are themselves a weaker source than the live per-name probe the autopilot
research used (§7 of that document): they are a static text dump the addon ships, not something
read from a running sim. A name appearing there is a strong hint a dataref/command *exists*, but
says nothing about whether the Zibo's own systems actually *honour* it — the entire headline
finding of the autopilot research (MCP dials silently rejecting the generic write while accepting
Zibo's own dial write) is exactly the kind of behaviour no static reference file could reveal. Treat
every "candidate" below as "plausible name, unknown behaviour."

---

## Phase 2 — live verification (2026-09-03)

Live-verified against X-Plane 12.4.3 + Zibo 4.05.33 at LEMD (engines running, N1 ~20% both, ground
idle), through the real adapter code path (`CockpitRuntime`'s binding resolver) for every confirmed
binding, and raw HTTP against `/api/v2/datarefs`/`/api/v2/commands` for **discovery** only (the
`#223` technique: dumping the connected sim's own full index, not merely probing hypotheses one at
a time). Full per-control detail lives in `adapters/xplane/cockpit_catalogs/zibo-b738/pedestal.yaml`
and `lights.yaml` as comments beside each entry; this section is the summary.

**The Phase 1 static reference files (`B738_Datarefs.txt`/`B738_Commands.txt`) turned out to be
substantially incomplete** — three entire subsystems Phase 1 flagged as hard gaps (stab trim cutout
switches, the flap lever, and every light's directly-writable position dataref) were invisible to
those files and only surfaced by dumping the live index, exactly #223's overhead-panel finding
repeating itself here.

| Phase 1 gap | Phase 2 resolution |
|---|---|
| Stab trim cutout switches — zero candidate at all | Found live: `laminar/B738/toggle_switch/el_trim_w_guard_off/_on` (MAIN ELECTRIC) and `ap_trim_w_guard_off/_on` (AUTOPILOT), both confirmed 0<->1. The bare `el_trim`/`ap_trim` commands (no `_w_guard`) are a confirmed dead end — 3 presses, no movement. |
| Flaps lever detents — only a dead generic `flap_ratio` guess | Found live: `laminar/B738/flt_ctrls/flap_lever`, directly writable, live-mapped to all 9 real detents (UP,1,2,5,10,15,25,30,40 -> ratio 0/.125/.25/.375/.5/.625/.75/.875/1.0) by pressing every `push_button/flaps_<N>` command and reading the position back. |
| Parking brake — read-only annunciator only | Found live: `laminar/B738/parking_brake_pos` (writable) + `push_button/park_brake_on_off` (clean toggle command), confirmed 1<->0. |
| Speedbrake ARM — no candidate | Found live: `laminar/B738/flt_ctrls/speedbrake_arm`, directly writable, confirmed 0<->1. |
| Transponder mode — no read candidate, `selector` couldn't load | Found live: `laminar/B738/knob/transponder_pos` (read) plus 6 absolute-set commands (`transponder_stby`/`_test`/`_altoff`/`_alton`/`_ta`/`_tara`) used to live-map values 1-5 to STBY/ALT OFF/ALT ON/TA ONLY/TA-RA (floor/ceiling confirmed by stepping past both ends). |
| Rudder/aileron trim — Phase 1's guessed read dataref never moved | Confirmed the guessed `laminar/B738/flt_ctrls/*/switch_pos`/`sel_dial_pos` datarefs are dead ends; the **generic** (stock) `sim/cockpit2/controls/rudder_trim`/`aileron_trim` are the correct, live-confirmed reads — the one subsystem in this file where "generic" turned out right, not a no-op. |
| Every light's `_up`/`_dn`/`_on`/`_off` command pair (landing/rwy/logo/wing/wheel/taxi/position/dome) | Every one turned out to have a companion directly-writable position dataref live (`land_lights_left_pos`, `toggle_switch/rwy_light_left`, `logo_light`, `wing_light`, `wheel_light`) or a live-mappable multi-state range via the command pair (`taxi_light_brightness_pos` 0/1/2, `position_light_pos` -1/0/1) — confirmed by direct read-back, not assumed from the static docs. |

**Genuinely new findings beyond anything Phase 1 could have anticipated:**

- **`taxi_light_brightness_pos_up`/`_dn` are reversed from their names**: `_up` moves the read value
  DOWN and `_dn` moves it UP — verified by stepping both directions twice and observing the actual
  effect, not assumed. The catalog's `inc`/`dec` bindings match the observed direction, not the
  command names.
- **The `LightsSetup` generic-vs-override question is answered per field, definitively, and every
  field needed a different answer**: `landing`/`nav`/`strobe` REJECTED outright (the generic dataref
  write does not even persist); `taxi` ACCEPTED at the generic-dataref level but Zibo's own switch
  never follows it (the MCP airspeed dial's "accepted but ignored" shape, confirmed via an isolated
  `apply_setup` call with a clean Zibo-side echo check); `beacon` ACCEPTED and reversible, but no
  Zibo-specific dataref of any kind exists anywhere in the live index to independently confirm the
  physical light responds — "confirmed accepted", not "confirmed working", stated as such.
- **`setup_overrides` cannot express the `LightsSetup` fix even though every field now has an
  answer**: `core.cockpit.actuation.plan_setup_actuations`/`_actuation_value` requires an overridden
  field's value to be a bool or a float; `lights: LightsSetup | None` is a nested object, so no
  single `control_id` can absorb it through the existing mechanism. A design gap Wave 1 (D11, scoped
  to flat autopilot fields) never anticipated — flagged for a follow-up design note, not fixed here
  (out of this issue's stated scope: "pure catalog data + live validation — no new machinery").
  `flaps_ratio`/`speedbrake_ratio`/`elevator_trim_ratio` hit a related but different wall: all three
  generic writes are confirmed no-ops, but none of their working replacements can be targeted either
  — `flaps_lever`'s live-confirmed shape is 9 real detents (a float dial that quantizes off-detent
  values, not one a naive `dial` override could drive safely), and `stab_trim` is correctly an
  encoder, which the override rule's "float -> `dial`" constraint excludes by construction.
- **The generic sweep's `press` branch never restores anything** (`tests/sim/test_live_cockpit_catalog.py`'s
  `_do`/kind-branch code: a `press` fires once and asserts `actions_taken == 1`, with no before/after
  state model at all — correct for a one-way action like `ap_disconnect`, but a live, hands-on
  discovery here: `nav1_swap`/`nav2_swap` are genuinely reversible (SWAP is its own inverse), yet
  running the sweep once leaves the frequency swapped, because nothing presses it a second time. A
  full-suite run during this session left NAV2's active/standby genuinely swapped afterward — caught
  by an independent final-state check, fixed live, and both entries corrected to
  `live_sweep: false` (the same risk class as the COM swap entries, which were marked that way from
  the start).
- **Real, not merely theoretical, dataref quantization**: `laminar/B738/flt_ctrls/speedbrake_lever`
  writes 0/0.25/0.5/0.75/1.0 exactly but silently snaps an off-quarter value (0.125 wrote, read back
  0.0889) — caught by the live sweep's own dial round-trip assertion, not assumed; `step` was
  corrected from 0.125 to the live-confirmed-safe 0.25.
- **Stab trim IS a working encoder** (issue #224's explicit ask): `laminar/B738/flight_controls/
  pitch_trim_up`/`pitch_trim_down` (Zibo-specific commands absent from both Phase 1 static files —
  found live only) move `laminar/B738/flight_model/stab_trim_units` by a small but real, signed
  amount per single command activation (~0.004 units) — confirmed by a dedicated test
  (`test_zibo_stab_trim_encoder_actually_moves_the_authoritative_dataref`), not just the generic
  sweep's "resolves without erroring" check.

**Confirmed live and promoted to `controls:`** (30 total: 19 pedestal + 11 lights) — see the two
YAML files for the full list with bindings and hints.

**Parked with a Phase-2-observed reason, not a Phase-1 guess** (10 total: 9 pedestal + 1 lights):

- `start_lever_1`/`start_lever_2` — real binding found (`mixture1/2_toggle`, `mixture_ratio1/2`) but
  NOT actuated: both engines were running this session; CUTOFF shuts an engine down and RUN cannot
  restart it.
- `toga_left`/`toga_right`, `at_disconnect_left`/`at_disconnect_right` — real bindings found and
  resolve, but no observable side effect was checked this session (autothrottle was off) — a press
  with no read-back and no observable confirmation is a guess, not a verification.
- `horn_cutout` — Phase 1's semantic ambiguity (MCP altitude alert vs. pedestal config-warning horn)
  was not resolved: no alert was sounding to silence.
- `weather_radar_wxr` — activates without error but is a display-overlay press with no dataref
  read-back at all; no way to confirm visually from a dataref-only session.
- `com_rtp_panel` — resolved to a different, real subsystem (the Audio Selector Panel), not COM
  frequency standby+swap as Phase 1 speculated.
- `strobe_light` — confirmed dead in isolation (not just inferred from the combined `LightsSetup`
  test): no Zibo-specific candidate exists anywhere, and the generic write is rejected outright.

**Squawk code and COM1/COM2 standby+swap** were promoted using the generic (stock) dataref/command
path — no `laminar/B738/*` candidate of any kind exists for either — confirmed to accept and
round-trip a write, with the same caveat as `beacon`: no independent Zibo-side signal exists to
confirm the physical display/radio follows it, only that the simulator's own state does.

---

## 1. Throttle quadrant

| Item (issue #224 checklist) | Candidate(s) | Kind (best guess) | Read/write shape | Notes |
|---|---|---|---|---|
| Flaps lever detents | **No Zibo-specific dataref/command found in either reference file.** Only tangential entries: `laminar/B738/toggle_switch/alt_flaps_ctrl` (ALTERNATE FLAPS CONTROL selector, `-1/0/1`, `B738_Datarefs.txt` line 132) and `laminar/B738/push_button/flaps_test` (FLAPS test button, `B738_Commands.txt` line 132) — neither is the main flap lever. The only plausible write path is the **generic** `sim/cockpit2/controls/flap_ratio` dataref, which `adapters/xplane/xplane_adapter.py` already writes for `AircraftSetup.flaps_ratio` (key `"flap_ratio"` → `sim/cockpit2/controls/flap_ratio`, line 226). | `selector` (discrete detents: 0/1/2/5/10/15/25/30/40, not a continuous dial) if the generic write works; otherwise unknown | write a target ratio, read back the same dataref | UNVERIFIED — pending live read-back confirmation. **Weak evidence only**: the generic dataref's *absence* from Zibo's own override files is not proof it isn't intercepted the same way the MCP altitude dial was (that dataref is also absent from any list a static doc would call an "override" — the override happens in compiled Lua the reference files don't describe). The detent→ratio mapping (which float value each of 1/2/5/10/15/25/30/40 corresponds to) is itself unknown and cannot be invented; a live sweep must read the ratio at each physical detent position, or find a Zibo-specific detent dataref that a live `xplane-datarefs` search (not attempted this phase) might surface. **Candidate for parking if the generic write turns out dead, pending a live search for a Zibo-specific alternative.** |
| Speedbrake lever incl. ARM | No lever-position dataref/command found. Two **read-only** annunciators exist: `laminar/B738/annunciator/speedbrake_armed` and `laminar/B738/annunciator/speedbrake_extend` (`B738_Datarefs.txt` lines 245–246, brightness 0–1, confirm state but do not set it). The only write candidate is the **generic** `sim/cockpit2/controls/speedbrake_ratio`, already written by the adapter for `AircraftSetup.speedbrake_ratio` (line 227). | `dial` (0.0 retracted .. 1.0+ deployed; the 737's real lever has a distinct ARM detent, likely a specific ratio value e.g. `-0.5` or similar X-Plane convention) | write ratio, read back `speedbrake_ratio`; ARM could be a specific out-of-range value (X-Plane's stock convention uses a negative ratio for "armed" on some aircraft) or could need its own selector | UNVERIFIED. The ARM position specifically is a total unknown from these files — no armed-state write path was found at all, only the read-only annunciator. **Flag as a probable park candidate for the ARM sub-state** unless a live probe finds a distinct write value; the deploy/retract axis alone is a weaker but plausible `dial` candidate. |
| Parking brake | No Zibo-specific write dataref/command found. One **read-only** annunciator: `laminar/B738/annunciator/parking_brake` (`B738_Datarefs.txt` line 164, brightness 0–1). `AircraftSetup` has no typed parking-brake field at all (only `autobrake_level`, checked against `core/models.py`), and the DATAREFS table in the adapter has no `parking_brake` key either — this would be new adapter surface if the generic X-Plane dataref (`sim/flightmodel/controls/parkbrake`, the well-known stock path, **not confirmed present in the Zibo reference files** because it is a stock X-Plane dataref, not a `laminar/B738/*` one) turns out to work. | `toggle` (on/off) if a working generic dataref is found; `selector`/`dial` if the ratio matters | unknown — no `press`/`toggle_switch` command found either | UNVERIFIED, and genuinely under-evidenced: the only lever-adjacent commands found for the "OTHERS" and "systems.lua" sections are unrelated (toe brakes, `brakes_max`/`brakes_regular`/`brakes_toggle_max` in the "Rewrite default commands" section, `B738_Commands.txt` lines 510–513, which are the **wheel brakes**, not the parking brake handle). **This is a real gap** — no plausible Zibo-specific parking-brake write candidate exists in either file. A live search (not attempted this phase) is needed before this can even be drafted with confidence; may need to park from the start if nothing surfaces. |
| Stab trim cutout switches | **No candidate found in either reference file at all.** Neither "cutout" nor "stab" nor "stabilizer" appears anywhere in `B738_Datarefs.txt` or `B738_Commands.txt`. | unknown | unknown | **Gap, not a draft entry.** This item may need to be parked from the very start of live verification — the reference files simply do not document it. A live `xplane-datarefs` search once Phase 2 starts is the only way to find (or rule out) a binding; possible guesses like `laminar/B738/switches/stab_trim_cutout_main` or `..._ap` were **not** invented for the draft catalog, per the "park, don't guess" rule — inventing a plausible-sounding name with no evidence at all would be worse than an honest gap. |
| Start levers | `laminar/B738/engine/mixture1_cutoff`, `mixture1_idle`, `mixture1_toggle` and the engine-2 equivalents (`mixture2_cutoff`/`mixture2_idle`/`mixture2_toggle`), `B738_Commands.txt` lines 497–502 ("-- calc.lua"). Read/status candidate: `laminar/B738/engine/mixture_ratio1`/`mixture_ratio2`, listed read/write, `B738_Datarefs.txt` line 92–93. | `toggle` (CUTOFF vs RUN, guarded press-if-different, the autopilot research's "these are edges, not sets" shape) | press `mixture1_toggle` (or the explicit `_cutoff`/`_idle` commands), read `mixture_ratio1` (hypothesis: `>0.5` reads as RUN/idle, `<0.5` as CUTOFF) | UNVERIFIED. Reasoning for this being the right subsystem, not a guess: on the real 737 and in X-Plane's engine model generally, the "start levers" (fuel control switches marked CUTOFF/RUN on the pedestal) are implemented through the mixture-lever position, not a separate fuel-valve dataref — this is a domain-knowledge inference, not something read off the file, so it is flagged accordingly and must be confirmed live before it is trusted. The threshold interpretation of `mixture_ratio1` (what value means "RUN" vs "CUTOFF" — likely `0.0`/`1.0` rather than a fractional threshold, since read/write range is stated as `0 .. 1`) also needs a live read at each lever position. **Not to be confused with the ENGINE START selector** (`laminar/B738/engine/starter1_pos`/`starter2_pos`, GRD/AUTO/CNT/FLT, and the `knob/eng1_start_left/right` rotate commands) — that is the overhead start panel and belongs to #223's scope, excluded here. |
| TO/GA + A/T disconnect (press controls) | `laminar/B738/autopilot/left_toga_press`, `right_toga_press`, `laminar/B738/autopilot/left_at_dis_press`, `right_at_dis_press` (`B738_Commands.txt` lines 259–262). Generic alternative also present: `sim/autopilot/take_off_go_around`, `sim/engines/TOGA_power` (`B738_Commands.txt` lines 508–509, "Rewrite default commands" — Zibo explicitly rewrites the stock TOGA command, meaning the *generic* command is also live on this aircraft, not dead). | `press` (no state) | activate only, no read-back (matches the design's `press` kind exactly) | UNVERIFIED but high confidence on the shape: this mirrors `ap_disconnect` in the already-shipped `mcp.yaml` worked example (§5.7 of the design doc) almost exactly — a bare command with no status dataref. `left_toga_press`/`right_toga_press` (captain/F/O throttle-lever-mounted switches) and `left_at_dis_press`/`right_at_dis_press` are the four candidates; the generic `take_off_go_around` is a fallback worth live-testing too since Zibo's own commands file lists it as rewritten (working), unlike the dead generic autopilot-mode ladder the MCP research found. |
| Horn cutout | `laminar/B738/alert/alt_horn_cutout` ("Alt Horn Cutout", `B738_Commands.txt` line 136). | `press` (a momentary silence action) or `toggle` if it has a latched state — unclear from the name alone | activate `alt_horn_cutout`; no read-back candidate found | UNVERIFIED, and the semantics are genuinely ambiguous from the name alone: "Alt Horn" most likely refers to the **altitude alert horn** (the MCP altitude-deviation warning), not the takeoff-configuration warning horn that sits physically on the pedestal quadrant near the flap lever on a real 737. If live testing confirms this only silences the altitude alert, it may belong on the `mcp` panel (owned by #222) rather than `pedestal`/throttle-quadrant — flagged here rather than silently reassigned, since #224's issue text explicitly lists "horn cutout" under the throttle-quadrant scope. No separate takeoff-config-warning-horn-cutout command was found in either file; if the two are in fact the same physical switch, this resolves itself; if not, the config-horn-cutout candidate is a further gap alongside stab trim cutout. |

## 2. Pedestal

| Item | Candidate(s) | Kind (best guess) | Read/write shape | Notes |
|---|---|---|---|---|
| Stabilizer trim (**encoder** — issue #224 explicitly calls this out) | **No `laminar/B738/*` pitch-trim dataref or command found in either file.** The only trim-related entries in `B738_Commands.txt` are under a section literally headed `-- trim.lua` (line 405) and list **only** `sim/flight_controls/rudder_trim_left`/`_right` and `sim/flight_controls/aileron_trim_left`/`_right` — both **stock** X-Plane command names, not `laminar/B738/*` ones. Pitch/stab trim is conspicuously absent from that section. | `encoder` (per the issue's explicit call-out; matches the repeat-press/no-absolute-set shape the fake catalog's `stab_trim` fixture and the design's §3.1 D2 already model) | inc/dec repeat commands, read a position dataref | UNVERIFIED, and this is the most consequential hypothesis in this document. **Working theory:** since `trim.lua`'s job appears to be intercepting the stock rudder/aileron trim commands so Zibo can drive its own trim-wheel animation, and pitch trim is *not* in that interception list, stab trim is plausibly left on the **stock, generic** X-Plane commands `sim/flight_controls/pitch_trim_up`/`sim/flight_controls/pitch_trim_down` (well-known default X-Plane command names, not found written out in either Zibo file because they are not Zibo-specific — this is an inference from the file's structure, not a name actually present in the text). The read-back candidate would then be the same generic dataref the adapter already writes for `AircraftSetup.elevator_trim_ratio` — `sim/cockpit2/controls/elevator_trim` (`xplane_adapter.py` line 228, range −1..+1). **This is the opposite failure mode from the MCP research's headline result** (there, generic writes were dead; here, the hypothesis is that generic *is* the correct, live path) — which is precisely why it must not be asserted without a live read-back: the MCP research's whole point was that "looks generic, should work" was wrong three times out of five fields tested. Flagging this prominently for Phase 2's first live check. |
| Rudder trim | `sim/flight_controls/rudder_trim_left`, `sim/flight_controls/rudder_trim_right` (`B738_Commands.txt` lines 406–407, `-- trim.lua`). | `encoder` (repeat left/right, matching the real rudder trim wheel) | inc(`_right`)/dec(`_left`) repeat commands; read-back candidate `sim/cockpit2/controls/artstab_rud_ratio` or `sim/flightmodel2/controls/rudder_trim` (**both guessed from general X-Plane dataref naming conventions, neither confirmed present anywhere in the Zibo reference files** — read binding is the weakest part of this candidate) | UNVERIFIED. These are stock command *names*, but their presence in Zibo's own `trim.lua` section is direct evidence Zibo's Lua intercepts and drives its own rudder-trim indicator off them — stronger evidence than the stab-trim hypothesis above, which has no textual evidence at all, only structural inference. The read binding is the open question; a live sweep must find what dataref actually reports the current trim position. |
| Aileron trim | `sim/flight_controls/aileron_trim_left`, `sim/flight_controls/aileron_trim_right` (`B738_Commands.txt` lines 408–409, `-- trim.lua`). | `encoder` | inc/dec repeat commands; read-back dataref unconfirmed, same caveat as rudder trim | UNVERIFIED, same evidence class as rudder trim (present in the same explicit interception list). |
| Transponder mode | `laminar/B738/knob/transponder_mode_up`, `laminar/B738/knob/transponder_mode_dn` (`B738_Commands.txt` lines 44–45); `laminar/B738/push_button/transponder_ident_dn` (IDENT, line 46). | `selector` (OFF/STBY/TA-only/TA-RA, stepped via inc/dec — matches the up/dn command-pair pattern seen repeatedly in this addon) | inc(`_up`)/dec(`_dn`) stepped selector; read-back candidate unknown — `B738_Datarefs.txt` has no transponder mode/state entry at all, only `TRANSPONDER FAIL laminar/B738/transponder/indicators/xpond_fail` (line 282, a failure annunciator, not the mode) | UNVERIFIED. No read binding candidate was found for the current mode — this makes the control's `readable` flag doubtful; per the loader's own derivation rule (`core/cockpit/catalog.py::_derive_readable`), a `selector` requires a `read` binding to load at all (§3.2's binding table: `selector` requires `read`, and *exactly one of* `{write}` or `{inc, dec}`). **Without a live-found read dataref this cannot become a `controls:` entry as drafted — it is either parked, or the read binding is found live in Phase 2.** IDENT (`transponder_ident_dn`) is a clean separate `press` candidate, no such problem. |
| Transponder code (squawk) | **No candidate found in either file.** No digit-entry command, no code-readback dataref. | unknown | unknown | **Gap.** The Zibo transponder is very likely a custom-rendered 3D popup (click-drag or click-through digits), the same category of UI as the FMC keypad (which *is* documented, extensively, as individual button-press commands — see `fmc1_0`..`fmc1_9` etc., `B738_Commands.txt` lines 437–446). If the transponder code entry follows the same pattern, it would need per-digit press commands that simply aren't in this reference dump; a live `xplane-datarefs` search (not attempted) is the only way to find them, or confirm there is no dataref path to setting a code at all (in which case: park). |
| Radio panels — COM/NAV standby + swap | Two candidate families, **not obviously the same thing**: (a) `laminar/B738/push_button/switch_freq_nav1_press`, `switch_freq_nav2_press` (`B738_Commands.txt` lines 47–48) — plausible NAV1/NAV2 standby↔active swap buttons; (b) the whole `rtp_L`/`rtp_R` family (`B738_Commands.txt` lines 328–351, `-- comms.lua`): `off_switch`, `vhf_1/sel_switch`, `vhf_2/sel_switch`, `vhf_3/sel_switch`, `hf_1/sel_switch`, `hf_2/sel_switch`, `am/sel_switch`, `freq_txfr/sel_switch`, `freq_MHz/sel_dial_up`/`_dn`, `freq_khz/sel_dial_up`/`_dn`, both L and R. No `com1`/`com2` swap command was found by name at all. | (a) `press` (swap); (b) `freq_txfr/sel_switch` as `press` (swap), `freq_MHz`/`freq_khz` dial pairs as `encoder`, `vhf_n/sel_switch`/`hf_n/sel_switch`/`am/sel_switch`/`off_switch` as a source `selector` | unclear — no read-back candidates identified for either family | UNVERIFIED, and the two families need disambiguating live, not assumed: `rtp_L`/`rtp_R` ("Radio Tuning Panel Left/Right") reads like Zibo's model of a **specific physical panel** — plausibly the alternate/backup tuning panel used when normal COM radios fail, not the everyday COM1/COM2 heads — while `switch_freq_nav1/2_press` reads like the ordinary NAV radio swap button. Coordinating with `AircraftSetup`'s existing typed `nav1_freq_khz`/`nav2_freq_khz`/`obs1_deg`/`obs2_deg` fields (issue #224 explicitly asks for this): those fields already write generic datarefs (`sim/cockpit/radios/nav1_freq_hz` etc., `xplane_adapter.py` lines 272–275) that the autopilot research never tested for aliveness on Zibo — an open question shared with, not unique to, this catalog work. **No COM1/COM2 frequency write/swap dataref of any kind (Zibo-specific or generic) was identified in either reference file** — this is the weakest-evidenced item in the whole radio family and a strong parking candidate unless a live search turns something up. |
| Weather radar basics | `laminar/B738/EFIS_control/capt/push_button/wxr_press`, `laminar/B738/EFIS_control/fo/push_button/wxr_press` (`B738_Commands.txt` lines 179, 198). | `toggle` (WXR overlay on/off on the Navigation Display) | press, no read-back candidate identified | UNVERIFIED, and narrower than "weather radar basics" implies: this is the **EFIS control panel's WXR display toggle** (show/hide the weather overlay on the ND), not the radar system itself — no gain, tilt, or mode (WX/MAP/TEST) dataref or command was found anywhere in either file. If "basics" in the issue means "can turn the overlay on", this one candidate covers it; gain/tilt/mode are a further gap with no candidate at all in these files. |

## 3. Lights

A structural finding applies to the whole panel before the per-light table: the currently-shipped
`LightsSetup` (`core/models.py` lines 228–235) has exactly five boolean fields — `landing`,
`taxi`, `nav`, `beacon`, `strobe` — and the adapter writes them to five "classic" X-Plane
datarefs (`xplane_adapter.py` lines 265–270). **Runway turnoff, position/strobe-selector (as
opposed to a bare strobe on/off), wing, logo and dome lights have no `LightsSetup` field at all**,
regardless of what this investigation finds about whether Zibo honours the classic datarefs — those
five items are necessarily catalog-only entries; there is nothing for a `setup_overrides` mapping
to target for them, because there is no `AircraftSetup` field to override in the first place.

| Item | Candidate(s) | Kind (best guess) | Read/write shape | Notes |
|---|---|---|---|---|
| Landing lights | `laminar/B738/switch/land_lights_ret_left_up`/`_dn`, `land_lights_ret_right_up`/`_dn` (`B738_Commands.txt` lines 375–378) — separate left/right retractable-light switches, each an up/dn command pair, not a single flip. Also `laminar/B738/spring_switch/landing_lights_all` (line 387, a spring-loaded "all landing lights on" momentary switch). **Separately, and importantly**: `sim/lights/landing_lights_on`, `sim/lights/landing_lights_off`, `sim/lights/landing_lights_toggle` appear in the explicit **"Rewrite default commands"** section (`B738_Commands.txt` lines 504, 520–522) — Zibo names these stock commands itself, meaning it actively intercepts and handles them (unlike the dead generic autopilot commands the MCP research found, which were never mentioned in any Zibo file at all). | Left/right retractable lights: `selector` with 2 options (up=on/dn=off) via inc/dec, one control per side. `landing_lights_all`/generic toggle: `press` (spring-loaded, momentary) or `toggle` if `sim/cockpit2/switches/landing_lights_on` reads its state correctly | left/right: `inc`=`_up`, `dec`=`_dn`; generic: activate `sim/lights/landing_lights_toggle`, read `sim/cockpit2/switches/landing_lights_on` (the same dataref the adapter's `LightsSetup.landing` already writes) | UNVERIFIED, but this is the **strongest positive lead in the whole document** for the §3 "LightsSetup generic-vs-override question" the issue asks about — see the dedicated subsection below. |
| Runway turnoff | `laminar/B738/switch/rwy_light_left_on`/`_off`, `rwy_light_right_on`/`_off` (`B738_Commands.txt` lines 394–397). | `selector`, 2 options (on/off), via inc(`_on`)/dec(`_off`) per side — same up/dn-pair idiom as the retractable landing lights, not a real "toggle" binding shape | inc/dec, no read-back candidate identified | UNVERIFIED. No `LightsSetup` equivalent exists (see structural note above) — necessarily a catalog-only entry, never a `setup_overrides` target. |
| Taxi | No dedicated taxi-light on/off command found; the only taxi-light entry is `laminar/B738/toggle_switch/taxi_light_brightness_pos_up`/`_dn` (`B738_Commands.txt` lines 385–386) — a **brightness** adjustment, not clearly the same as switching the light on vs. off (could be a 3-position OFF/DIM/BRT switch, common on the real 737 taxi light, in which case "up" all the way *is* how you turn it on). | `selector` if it is in fact the OFF/DIM/BRT switch modelled as steps; unclear otherwise | inc(`_up`)/dec(`_dn`), read-back unknown | UNVERIFIED and the semantics are genuinely unclear from the name alone — needs live testing to confirm whether stepping this fully down reaches "off" or only "dim". The existing `LightsSetup.taxi` field already writes the generic `sim/cockpit2/switches/taxi_light_on` — untested for aliveness on Zibo, same open question as landing lights. |
| Position (nav) / strobe selector | No single "selector" dataref/command combining position and strobe was found (the real 737 has one three-position switch: OFF/POSITION/STROBE-POSITION). Only `laminar/B738/toggle_switch/position_light_up`/`_down` (`B738_Commands.txt` lines 379–380) was found — a single switch, up/dn pair, name suggests it may cover only the position (nav) lights, not a combined position+strobe selector. No separate `laminar/B738/*` strobe command was found at all — `LightsSetup.strobe` writes the generic `sim/cockpit2/switches/strobe_lights_on`, again untested. | `selector`, 2–3 options depending on what live testing reveals about whether `position_light_up`/`_down` is a 2-state or reaches a 3rd (strobe) state | inc/dec, read-back unknown | UNVERIFIED. The mapping between "position/strobe selector" (issue's wording, real-737 terminology) and this single found command pair is not confirmed — this may turn out to be only the nav/position half, with strobe living entirely on the generic dataref, or the single switch may in fact combine both (matching the real switch). A live test is required before drafting a confident binding; the draft below treats it as position-light-only and leaves strobe on the "generic, unverified" side pending Phase 2. |
| Anti-collision (beacon) | No `laminar/B738/*` beacon-specific command was found in either file. `LightsSetup.beacon` writes the generic `sim/cockpit2/switches/beacon_on` (`xplane_adapter.py` line 269). | unknown pending the generic-vs-override finding | unknown | UNVERIFIED, no Zibo-specific candidate at all — either the generic dataref works (favourable case) or this is a further gap needing a live search. |
| Wing | `laminar/B738/switch/wing_light_on`, `wing_light_off` (`B738_Commands.txt` lines 400–401). | `toggle` semantics via 2-option `selector` (on/off commands, not a flip) — same idiom as runway turnoff | activate `wing_light_on` or `wing_light_off` depending on target; read-back unknown | UNVERIFIED. No `LightsSetup` equivalent (structural note above) — catalog-only. |
| Logo | `laminar/B738/switch/logo_light_on`, `logo_light_off` (`B738_Commands.txt` lines 398–399). | same idiom as wing light | same shape as wing light | UNVERIFIED. No `LightsSetup` equivalent — catalog-only. |
| Dome | `laminar/B738/toggle_switch/cockpit_dome_up`, `cockpit_dome_dn` (`B738_Commands.txt` lines 383–384). | `selector` (brightness-style up/dn stepping, same idiom) | inc(`_up`)/dec(`_dn`), read-back unknown | UNVERIFIED. No `LightsSetup` equivalent — catalog-only. Note there is also `laminar/B738/switch/wheel_light_on`/`_off` (lines 402–403, wheel-well light) found adjacent to these in the same `lighting.lua` section — not in the issue's explicit list, but flagged here as a low-cost extra candidate the issue's author may want to fold in during Phase 2, since it was found "for free" while researching dome/logo/wing. |

---

## `LightsSetup` generic-vs-override question (issue #224's explicit ask)

**Hypothesis, unverified, pending Phase 2's first live check:** landing lights are the one item in
this entire document with direct textual evidence either way, and the evidence points toward
**generic datarefs/commands working on the Zibo for at least some lights** — the opposite of the
autopilot research's headline result for the MCP dials. The basis for this hypothesis:

- `B738_Commands.txt`'s "Rewrite default commands" section (lines 504–522) is an explicit list of
  **stock X-Plane commands Zibo's own Lua intercepts and re-implements**. It includes
  `sim/lights/landing_lights_on`, `sim/lights/landing_lights_off`, `sim/lights/landing_lights_toggle`
  by name. The same section also lists `sim/flight_controls/landing_gear_toggle`/`_down`/`_up`,
  `sim/autopilot/take_off_go_around`, `sim/engines/TOGA_power`, and the brake and MCP-altitude-dial
  *command* pairs (`sim/autopilot/altitude_up`/`_down` — note: the **command**, not the *dial write*
  the MCP research found dead; commands and raw dataref writes are a different mechanism and this
  document does not assume they behave the same way).
- This is structurally different from the MCP research's dead datarefs, which never appeared in
  *any* Zibo file — a positive absence, not a rewrite. A "rewrite" entry means Zibo's own code path
  is reached when that generic surface is used; a name simply missing from either file means
  nothing either way (as the stab-trim gap above shows).
- **This is still only a hint about generic *commands*, not about the generic *dataref writes*
  `LightsSetup` actually performs.** The adapter's `_write_autopilot` writes `LightsSetup` fields as
  raw `PATCH /api/v2/datarefs/{id}/value` calls against `sim/cockpit2/switches/landing_lights_on`
  etc. (`xplane_adapter.py` lines 2523–2533) — a **dataref write**, not a `POST
  /api/v2/command/{id}/activate` against `sim/lights/landing_lights_toggle`. The rewrite list only
  proves the *command* path is live; it says nothing about whether Zibo's systems also read that
  same boolean dataref when it is patched directly, the way the MCP altitude dial's *own* dial
  dataref accepted a direct write but the *generic* one didn't (research §3) — the two mechanisms
  need to be tested **separately** in Phase 2, not assumed to share a verdict.
- The remaining four `LightsSetup` fields (taxi, nav, beacon, strobe) have **no** textual evidence
  either way — no Zibo-specific command mentioning them was found in the "Rewrite default commands"
  section or anywhere else, so no hypothesis is offered for them beyond "unknown, needs a live
  check", consistent with the "park, don't guess" standard.

**What Phase 2 needs to settle, per field, before any `setup_overrides` entry for `lights` can be
written:**

1. Does writing `sim/cockpit2/switches/landing_lights_on` directly (the dataref `LightsSetup`
   actually patches) move Zibo's landing-light animation and read back changed? If yes, `landing`
   can likely stay on the generic path with **no override needed** — the first field in this whole
   epic, across both MCP and pedestal/lights research, that might turn out to need none.
2. Do the four other classic datarefs (`taxi_light_on`, `navigation_lights_on`, `beacon_on`,
   `strobe_lights_on`) behave the same way, independently — no field may be assumed from another's
   result, exactly the lesson of the MCP research where altitude/heading/airspeed each failed
   differently (rejected vs. accepted-but-ignored).
3. If any of the five is dead on the direct dataref write, the corresponding Zibo-specific
   command pair found above (e.g. `land_lights_ret_left_up`/`_dn` for landing, `position_light_up`/
   `_down` for nav) becomes the catalog override candidate, exactly the autopilot research's
   resolution pattern for the MCP dials.

---

## Candidate count and checklist gaps

| Subsystem | Candidates found (rows in the tables above) | Fully open gaps (no plausible candidate at all) |
|---|---|---|
| Throttle quadrant | 7 items addressed (flaps, speedbrake, parking brake, start levers, TO/GA, A/T disco, horn cutout) | **Stab trim cutout switches** — zero evidence, not drafted at all. Parking brake has only a read-only annunciator, no write candidate — likely parks too. |
| Pedestal | 6 items addressed (stab trim, rudder trim, aileron trim, transponder mode, radio panels, weather radar) | **Transponder code (squawk) entry** — zero evidence. Transponder mode has no read-back candidate at all, so as drafted it cannot pass the loader's `selector` binding rule (`read` required) without a live-found dataref. COM1/COM2 standby+swap has no candidate at all, only NAV. |
| Lights | 8 items addressed (landing, runway turnoff, taxi, position/strobe selector, anti-collision, wing, logo, dome) + 1 bonus (wheel-well, found unsolicited) | No item has zero candidates, but **every read-back binding in this panel is unconfirmed** — every light entry drafted below uses a placeholder/omitted `read` pending Phase 2, which the loader may reject for kinds that require one (`selector` requires `read`, per §3.2's binding table) — flagged explicitly in the draft file's own comments. |

**Total candidates discovered:** 7 throttle-quadrant rows, 6 pedestal rows, 9 lights rows (22
distinct control candidates, several representing 2 physical controls each — e.g. left/right
retractable landing lights, left/right runway turnoff — so more like ~28 individual bindings before
live testing prunes them). Two items (stab trim cutout, transponder code) have **no candidate at
all** and are not present in the draft catalog files — inventing a plausible-looking name for either
would violate "park, don't guess" at the discovery stage, before any live check has even had the
chance to confirm or refute it.
