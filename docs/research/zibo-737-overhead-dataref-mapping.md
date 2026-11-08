# Zibo 737 overhead panel dataref mapping — candidate discovery (Phase 1)

Candidate discovery for issue #223 (Wave 2 of the cockpit control catalog epic, #225): map the
Zibo 737's **overhead panel** — electrical, fuel, hydraulics, anti-ice, pneumatics, IRS mode
selectors. Companion document to
[`zibo-737-autopilot-dataref-mapping.md`](zibo-737-autopilot-dataref-mapping.md) (the MCP/autopilot
research, #222) — same method, same rigor, **one phase behind**: this pass is discovery only, no
live sim was touched.

> **Phase 2 update (2026-09-03, live-verified against X-Plane 12.4.3 + Zibo at LEMD):** every
> candidate below has now been resolved one way or the other. **The authoritative result lives in
> `adapters/xplane/cockpit_catalogs/zibo-b738/overhead.yaml`** (`controls:` for the 32 confirmed
> entries, `parked:` for the 7 identified-but-not-actuated or confirmed-absent ones) — this
> document is kept as the discovery record, not rewritten into a duplicate of the YAML. Three
> findings worth flagging for anyone reading this Phase 1 text literally:
> 1. The biggest Phase 1 gap — battery/standby power/generators/GEN drive/external power having
>    **no candidate at all** in the vendor's static reference files — turned out to be a
>    documentation gap, not a missing feature. Live discovery (grepping the connected sim's own
>    full dataref/command index) found a `laminar/B738/electrical/*` namespace (generators, APU
>    generators, GPU) and a `laminar/B738/electric/*` namespace (battery, standby power) that
>    `B738_Datarefs.txt`/`B738_Commands.txt` never mention.
> 2. Every `*_up`/`*_dn` command hypothesis in §1 and §5 below (generators, APU generators, GPU,
>    isolation valve, both packs) turned out to **resolve live but not move the switch at all**
>    (confirmed with a live poll); the real write path is a **direct write to the position
>    dataref**, the exact `mcp_alt_dial`/`mcp_hdg_dial` pattern the MCP research already
>    documented for the autopilot dials. `overhead.yaml` uses `write`, not `inc`/`dec`, for all
>    six.
> 3. Live verification also found and fixed two real bugs in `core/cockpit/actuation.py`
>    (`selector_index` and a duplicate `_selector_matches`) that had never been exercised before,
>    because no catalog had a live `selector` control until this panel: X-Plane's Web API reports
>    every numeric dataref as a JSON float, and the old strict-type match never matched a
>    `value: 0` option against a live `0.0`. The identical disease #247 had already fixed for
>    `core/cockpit/preconditions.py`.
>
> Battery, standby power, both generator drive disconnects, and both IRS mode selectors were
> **deliberately not actuated** even where a real binding was found live — see `overhead.yaml`'s
> `parked:` entries for the exact reason on each (destructive/hard-to-recover risk to a shared live
> session). Bus transfer remains a confirmed-absent gap, now checked against the live index too,
> not just the static files.

| | |
|---|---|
| Aircraft | Zibo Mod B737-800X |
| Simulator | **None used.** No X-Plane instance was started, connected to, or queried. |
| Source | The add-on's own bundled reference files, read directly off disk: `C:\X-Plane 12\Aircraft\B737-800X\B738_Datarefs.txt` (368 lines, "Last update - Release 2.35") and `B738_Commands.txt` (521 lines, "Last update - Release 3.05y"). No `xplane-datarefs` MCP call, no Web API request. |
| Date | 2026-09-03 |
| Method | Grep both reference files for every `laminar/B738/*` (and adjacent `sim/*`) name plausibly matching the overhead panel's electrical/fuel/hydraulic/anti-ice/pneumatic/IRS subsystems; classify each candidate's likely control kind and read/write shape from its name and the reference file's own description; cross-check for a matching pair (a `toggle_switch/X` command against a `toggle_switch/X_pos` dataref, or an `X_up`/`X_dn` command pair against a multi-position `X_pos` dataref) the same way the autopilot research paired `flight_director_toggle` with `flight_director_pos`. **No write, no read-back, no verification of any kind was performed** — every entry below is a name-matching hypothesis, not a confirmed mapping. |

**Every single entry in this document is UNVERIFIED — pending live read-back confirmation.** None
of it should be read as "this works"; it is the candidate list issue #223's live-verification pass
(sibling issue #222 has the sim slot first) will work through, confirming, correcting or parking
each row the way `zibo-737-autopilot-dataref-mapping.md` did for the MCP panel.

---

## How to read each row

- **Dataref/command** — the exact `laminar/B738/...` path, taken verbatim from the reference file.
- **Description** — the reference file's own text for that name (typos preserved where the vendor
  file has them, called out inline).
- **Best-guess kind** — one of the catalog's five kinds (`toggle`, `press`, `dial`, `encoder`,
  `selector`), inferred from the name/description only, per the classification rule below.
- **Read/write shape** — which binding fields (`press`/`read`/`write`/`inc`/`dec`) the candidate
  would need, and whether a matching counterpart was actually found in the reference files or is a
  naming-convention guess.
- Every row carries **UNVERIFIED**.

### The classification rule used throughout

Scanning the reference files shows three recurring shapes, and the guessed kind follows the shape,
not the subsystem:

1. **A single `toggle_switch/X` command paired with an `X_pos` (or `..._pos`) read/write dataref**,
   described as "toggle (on/off)" — one command flips the state. Guessed kind: **`toggle`**
   (`press` = the command, `read` = the `_pos` dataref), mirroring `wing_heat` /
   `wing_heat_pos` and every `laminar/B738/autopilot/*_press` / `*_status` pair in the MCP research.
2. **A command *pair*, `X_up` / `X_dn`, against a multi-position (or two-position) `X_pos`
   dataref** — a spring-loaded or rotary switch that must be driven one detent at a time, described
   with more than two states (e.g. `0-off, 1-auto, 2-open`) or with no single flip command at all.
   Guessed kind: **`selector`** (`inc` = the `_up` command, `dec` = the `_dn` command, `read` = the
   position dataref).
3. **A dataref that is documented read/write with no command at all** (e.g. `laminar/B738/switches/
   apu_start`, `laminar/B738/knobs/cross_feed_pos`) — the MCP research's altitude/heading/speed dial
   precedent: write the dataref directly. Guessed kind: **`selector`** with a `write` binding
   (options enumerated from the description's `0-x, 1-y, ...` list) rather than `dial`, because
   every candidate found this way is a small closed set of discrete positions, not a continuous
   range.

A fourth shape — **a command/dataref pair found in the reference files but with NO plausible
counterpart for the other half** (a command with no discoverable read, or vice versa) — is flagged
explicitly per row rather than silently guessed.

---

## 1. Electrical

Issue scope: *battery, standby power, generators/GEN drive, APU start/bleed, bus transfer,
external power.*

**This subsystem has the largest gap of the whole panel.** Three of the six named items have no
plausible candidate anywhere in either reference file — see [§7 Gaps](#7-gaps--no-candidate-found)
— and even the items that do have a write path mostly lack a discoverable *read*.

| Candidate | Dataref/command found | Description (verbatim) | Best-guess kind | Read/write shape | Notes |
|---|---|---|---|---|---|
| Generator 1 | `laminar/B738/toggle_switch/gen1_up` / `gen1_dn` (commands) | "Generator1 up" / "Generator1 dn" | `selector`, 2 options (OFF/ON) | `inc`=`gen1_up`, `dec`=`gen1_dn`, `read` = **not found**. Hypothesis only: `laminar/B738/toggle_switch/gen1_pos`, by strict analogy with every other `toggle_switch/X` + `toggle_switch/X_pos` pair in the file — **this exact name does not appear in either reference file** and must not be treated as more than a guess. | UNVERIFIED |
| Generator 2 | `gen2_up` / `gen2_dn` | "Generator2 up" / "Generator2 dn" | `selector`, 2 options | Same shape and same read gap as GEN 1; hypothesis `toggle_switch/gen2_pos`. | UNVERIFIED |
| APU generator (bus 1 side) | `apu_gen1_up` / `apu_gen1_dn` | "APU generator1 up" / "APU generator1 dn" | `selector`, 2 options | `inc`/`dec` found; `read` not found, hypothesis `toggle_switch/apu_gen1_pos`. **Naming ambiguity**: the real 737 has one APU generator, not two — "generator1"/"generator2" here may mean "APU power to bus 1" and "to bus 2" rather than two physical APU generators. Needs a live check of what the switch actually looks like/does before the label is finalised. | UNVERIFIED |
| APU generator (bus 2 side) | `apu_gen2_up` / `apu_gen2_dn` | "APU generator2 up" / "APU generator2 dn" | `selector`, 2 options | Same shape and same gaps as above. | UNVERIFIED |
| Generator drive disconnect 1 | `laminar/B738/one_way_switch/drive_disconnect1` and `drive_disconnect1_off` | "Drive disconnect 1 on" / "Drive disconnect 1 off" | **Kind uncertain** — guessing `selector` (2 options NORM/DISC) but the `one_way_switch` prefix (distinct from `toggle_switch` used everywhere else) suggests this may not be freely reversible in the sim the way a normal switch is; could instead be two independent `press`-style actions. | `inc`≈`drive_disconnect1`, `dec`≈`drive_disconnect1_off` as a guess only. `read`: **not found** — the only nearby dataref is `laminar/B738/annunciator/drive1` ("GENERATOR FAIL DRIVE 1"), which is a **fail annunciator**, not a switch-position readback, and must not be used as one without live confirmation that it actually tracks the switch. | UNVERIFIED — also flag for `live_sweep: false` regardless of final kind: disconnecting a generator drive is not something an automated sweep should flip. |
| Generator drive disconnect 2 | `drive_disconnect2` / `drive_disconnect2_off` | "Drive disconnect 2 on" / "Drive disconnect 2 off" | Same as above | Same gaps as above; proxy annunciator `laminar/B738/annunciator/drive2`. | UNVERIFIED |
| APU master switch (OFF/ON/START) | `laminar/B738/switches/apu_start` (dataref, read/write) | "APU 0-off, 1-on, 2-start" | `selector`, 3 options (OFF/ON/START) | **Highest-confidence candidate in this subsystem** — a single read/write dataref, no command needed: `read`/`write` = `laminar/B738/switches/apu_start`. Alternate binding via the spring-toggle commands `laminar/B738/spring_toggle_switch/APU_start_pos_up` / `_dn` also exists if the direct write turns out not to stick (the MCP research's precedent for "some writes are ignored, use the command instead"). | UNVERIFIED |
| APU bleed | `laminar/B738/toggle_switch/bleed_air_apu` (command) / `laminar/B738/toggle_switch/bleed_air_apu_pos` (dataref) | Command: "Bleed air APU toggle (on/off)". Dataref: "AIR BLEED APU 0-off, 1-on" | `toggle` | `press` = `bleed_air_apu`, `read` = `bleed_air_apu_pos` — clean pair, both halves confirmed present in the reference files (though the write/read-back itself is still unverified). Cross-referenced under [Pneumatics §5](#5-pneumatics) too since it is physically a bleed valve; the issue's own bullet places "APU start/bleed" under Electrical, so it is listed here as the primary entry. | UNVERIFIED |
| External power (GPU) | `laminar/B738/toggle_switch/gpu_up` / `gpu_dn` (commands) | "GPU up" / "GPU down" | `selector`, 2 options (DISCONNECT/CONNECT) | `inc`=`gpu_up`, `dec`=`gpu_dn`. `read`: **not found** as a switch position. The closest dataref is `laminar/B738/annunciator/ground_power_avail` ("GROUND POWER AVAILABLE") — that is an *availability* light (is a GPU plugged in / providing power), not the switch's own commanded position, and conflating the two would be guessing, not verifying. | UNVERIFIED |

Battery, standby power and bus transfer have **no candidate at all** — see §7.

---

## 2. Fuel

Issue scope: *pumps (all six), crossfeed.* This is the cleanest subsystem in the whole panel — six
symmetric toggle pairs plus one selector, every half of every pair present in the reference files.

| Candidate | Dataref/command found | Description | Best-guess kind | Read/write shape | Notes |
|---|---|---|---|---|---|
| Fuel pump — left tank 1 | `laminar/B738/toggle_switch/fuel_pump_lft1` (command) / `laminar/B738/fuel/fuel_tank_pos_lft1` (dataref) | Command: "Fuel pump left1 toggle". Dataref: "LEFT TANK 1 0-Off, 1-on" | `toggle` | `press`=`fuel_pump_lft1`, `read`=`fuel_tank_pos_lft1` | UNVERIFIED |
| Fuel pump — left tank 2 | `fuel_pump_lft2` / `fuel_tank_pos_lft2` | "Fuel pump left2 toggle" / "LEFT TANK 2" | `toggle` | Same shape | UNVERIFIED |
| Fuel pump — right tank 1 | `fuel_pump_rgt1` / `fuel_tank_pos_rgt1` | "Fuel pump right1 toggle" / "RIGHT TANK 1" | `toggle` | Same shape | UNVERIFIED |
| Fuel pump — right tank 2 | `fuel_pump_rgt2` / `fuel_tank_pos_rgt2` | "Fuel pump right2 toggle" / "RIGHT TANK 2" | `toggle` | Same shape | UNVERIFIED |
| Fuel pump — center tank 1 | `fuel_pump_ctr1` / `fuel_tank_pos_ctr1` | "Fuel pump center1 toggle" / "CENTER TANK 1" | `toggle` | Same shape | UNVERIFIED |
| Fuel pump — center tank 2 | `fuel_pump_ctr2` / `fuel_tank_pos_ctr2` | "Fuel pump center2 toggle" / "CEBTER TANK 2" (typo in the reference file: "CEBTER") | `toggle` | Same shape | UNVERIFIED |
| Crossfeed | `laminar/B738/knobs/cross_feed_pos` (dataref, read/write) | "CROSS FEED 0-Off, 1-on" | `selector`, 2 options (OFF/ON) via `write` | `read`/`write` = `cross_feed_pos` directly, per the shape-3 rule — there is no single toggle command, only two one-way commands `laminar/B738/toggle_switch/crossfeed_valve_on` / `crossfeed_valve_off` ("Fuel crossfeed on" / "Fuel crosfeed off", typo: "crosfeed"). Either binding is plausible; writing the dataref directly is the simpler one and mirrors the MCP research's altitude/heading dial precedent (write the dataref, not a command, when a direct read/write dataref is confirmed present). The two named commands are noted as an alternate binding to try if the direct write turns out inert. | UNVERIFIED |

---

## 3. Hydraulics

Issue scope: *engine + electric pumps.* Fully symmetric, both halves of all four pairs present.

| Candidate | Dataref/command found | Description | Best-guess kind | Read/write shape | Notes |
|---|---|---|---|---|---|
| Engine 1 hydraulic pump | `laminar/B738/toggle_switch/hydro_pumps1` (command) / `laminar/B738/toggle_switch/hydro_pumps1_pos` (dataref) | Command: "Engine hydraulic pumps 1 - toggle (on/off)". Dataref: "ENGINE 1 HYDRO PUMP 0-off, 1-on" | `toggle` | `press`=`hydro_pumps1`, `read`=`hydro_pumps1_pos` | UNVERIFIED |
| Engine 2 hydraulic pump | `hydro_pumps2` / `hydro_pumps2_pos` | "Engine hydraulic pumps 2 - toggle" / "ENGINE 2 HYDRO PUMP" | `toggle` | Same shape | UNVERIFIED |
| Electric hydraulic pump 1 | `electric_hydro_pumps1` / `electric_hydro_pumps1_pos` | "Electric hydraulic pumps 1 - toggle" / "ENGINE 1 ELECTRIC HYDRO PUMP" | `toggle` | Same shape | UNVERIFIED |
| Electric hydraulic pump 2 | `electric_hydro_pumps2` / `electric_hydro_pumps2_pos` | "Electric hydraulic pumps 2 - toggle" / "ENGINE 2 ELECTRIC HYDRO PUMP" | `toggle` | Same shape | UNVERIFIED |

Pressure-low annunciators (`laminar/B738/annunciator/hyd_press_a`/`_b`,
`hyd_el_press_a`/`_b`) exist but are diagnostic lights, not pump switch state — not used as a read
binding for any of the four rows above.

---

## 4. Anti-ice

Issue scope: *window heat, probe heat, wing/engine anti-ice.*

| Candidate | Dataref/command found | Description | Best-guess kind | Read/write shape | Notes |
|---|---|---|---|---|---|
| Window heat — L side | `laminar/B738/toggle_switch/window_heat_l_side` (command) / `laminar/B738/ice/window_heat_l_side_pos` (dataref) | Command: "Window left side heat toggle (on/off)". Dataref: "WINDOW HEAT L SIDE 0-off, 1-on" | `toggle` | `press`=`window_heat_l_side`, `read`=`window_heat_l_side_pos` | UNVERIFIED |
| Window heat — L fwd | `window_heat_l_fwd` / `window_heat_l_fwd_pos` | "Window left forward heat toggle" / "WINDOW HEAT L FWD" | `toggle` | Same shape | UNVERIFIED |
| Window heat — R side | `window_heat_r_side` / `window_heat_r_side_pos` | "Windows right side heat toggle" / "WINDOW HEAT R SIDE" | `toggle` | Same shape | UNVERIFIED |
| Window heat — R fwd | `window_heat_r_fwd` / `window_heat_r_fwd_pos` | "Window right forward heat toggle" / "WINDOW HEAT R FWD" | `toggle` | Same shape | UNVERIFIED |
| Probe heat — captain | Dataref `laminar/B738/toggle_switch/capt_probes_pos` (read/write, "PROBES ANTI ICE CAPTAIN 0-off, 1-on"). Command listed as `laminar/B738/toggle_switch/capt_probes_pos`, "Probe heat A toggle (on/off)". | See notes | `toggle` | **Path collision flagged, not resolved.** The commands reference lists the *exact same path* (`.../capt_probes_pos`, including the `_pos` suffix) as both a dataref name and a command name — almost certainly a copy-paste artefact in the vendor's own file, since every other pair in this document follows `toggle_switch/X` (command, no suffix) + `toggle_switch/X_pos` (dataref). Best guess: the real command is `laminar/B738/toggle_switch/capt_probes` (no `_pos`), by analogy with `wing_heat`/`wing_heat_pos` and `eng1_heat`/`eng1_heat_pos` below — but this is a guess about the vendor's documentation error, not a verified path, and must be checked both ways live. | UNVERIFIED, path ambiguous |
| Probe heat — F/O | Dataref `laminar/B738/toggle_switch/fo_probes_pos` ("PROBES ANTI ICE F/O 0-off, 1-on"). Command listed identically: `laminar/B738/toggle_switch/fo_probes_pos`, "Prebe heat B toggle (on/off)" (typo: "Prebe"). | See notes | `toggle` | Same path-collision issue as captain-side; guessed real command `laminar/B738/toggle_switch/fo_probes`. | UNVERIFIED, path ambiguous |
| Wing anti-ice | `laminar/B738/toggle_switch/wing_heat` (command) / `laminar/B738/ice/wing_heat_pos` (dataref) | Command: "Wing anti ice toggle (on/off)". Dataref: "WING ANTI ICE 0-off, 1-on" | `toggle` | `press`=`wing_heat`, `read`=`wing_heat_pos` — clean pair, no ambiguity. | UNVERIFIED |
| Engine 1 anti-ice | `laminar/B738/toggle_switch/eng1_heat` (command) / `laminar/B738/ice/eng1_heat_pos` (dataref) | "Engine 1 anti ice toggle (on/off)" / "ENGINE 1 ANTI ICE 0-off, 1-on" | `toggle` | `press`=`eng1_heat`, `read`=`eng1_heat_pos` | UNVERIFIED |
| Engine 2 anti-ice | `eng2_heat` / `eng2_heat_pos` | "Engine 2 anti ice toggle" / "ENGINE 2 ANTI ICE" | `toggle` | `press`=`eng2_heat`, `read`=`eng2_heat_pos` | UNVERIFIED |

Not mapped, out of the issue's named scope but seen nearby: the window-heat overheat TEST switch
(`laminar/B738/toggle_switch/window_ovht_test`, commands `window_ovht_test_up`/`_dn`) is a
diagnostic test switch, not a heat control — left out deliberately, noted here so its absence is a
choice, not an oversight.

---

## 5. Pneumatics

Issue scope: *bleeds, isolation valve, packs.*

| Candidate | Dataref/command found | Description | Best-guess kind | Read/write shape | Notes |
|---|---|---|---|---|---|
| Engine 1 bleed | `laminar/B738/toggle_switch/bleed_air_1` (command) / `laminar/B738/toggle_switch/bleed_air_1_pos` (dataref) | "Bleed air engine 1 toggle (on/off)" / "AIR BLEED ENG1 0-off, 1-on" | `toggle` | `press`=`bleed_air_1`, `read`=`bleed_air_1_pos` | UNVERIFIED |
| Engine 2 bleed | `bleed_air_2` / `bleed_air_2_pos` | "Bleed air engine 2 toggle" / "AIR BLEED ENG2" | `toggle` | Same shape | UNVERIFIED |
| APU bleed | *(listed once, under [Electrical §1](#1-electrical) — the issue's own bullet places it there. Same candidate, cross-referenced here since it is physically a bleed valve.)* | — | `toggle` | — | UNVERIFIED |
| Isolation valve | `laminar/B738/toggle_switch/iso_valve_up` / `iso_valve_dn` (commands) / `laminar/B738/air/isolation_valve_pos` (dataref) | Commands: "ISOLATION VALVE up" / "down". Dataref: "ISOLATION VALVE 0-close, 1-auto, 2-open" | `selector`, 3 options (CLOSE/AUTO/OPEN) | `inc`=`iso_valve_up`, `dec`=`iso_valve_dn`, `read`=`isolation_valve_pos` — clean 3-position pair, both halves present. | UNVERIFIED |
| Left pack | `laminar/B738/toggle_switch/l_pack_up` / `l_pack_dn` (commands) / `laminar/B738/air/l_pack_pos` (dataref) | Commands: "L PACK up" / "down". Dataref: "LEFT PACK 0-off, 1-auto, 2-open" | `selector`, 3 options (OFF/AUTO/OPEN) | `inc`=`l_pack_up`, `dec`=`l_pack_dn`, `read`=`l_pack_pos` | UNVERIFIED |
| Right pack | `r_pack_up` / `r_pack_dn` / `r_pack_pos` | "R PACK up" / "down" / "RIGHT PACK" | `selector`, 3 options | Same shape | UNVERIFIED |

### Adjacent candidates — same subsystem area, not named in the issue's checklist

Found immediately alongside the above and structurally identical, but **not** in issue #223's
named list (*bleeds, isolation valve, packs*) — flagged for a scope decision rather than silently
included:

| Candidate | Dataref/command | Description | Best-guess kind |
|---|---|---|---|
| Left recirculation fan | `laminar/B738/toggle_switch/l_recirc_fan` / `laminar/B738/air/l_recirc_fan_pos` | "Left RECIRC toggle (on/off)" / "LEFT RECIRC 0-off, 1-on" | `toggle` |
| Right recirculation fan | `r_recirc_fan` / `r_recirc_fan_pos` | "Right RECIRC toggle" / "RIGHT RECIRC" | `toggle` |
| Trim air | `laminar/B738/toggle_switch/trim_air` / `laminar/B738/air/trim_air_pos` | "Trim air on toggle (on/off)" / "TRIM AIR 0-off, 1-on" | `toggle` |
| Bleed trip reset | `laminar/B738/push_button/bleed_trip_reset` | "Bleed air trip reset" | `press` |

---

## 6. IRS mode selectors L/R

Issue scope: *IRS mode selectors L/R.*

**No candidate found.** This is the sharpest gap in the panel. The reference files contain an
`IRS DISPLAY` section and an `IRS ANNUNCIATORS` section (`laminar/B738/latitude_deg`,
`laminar/B738/irs_left1`/`irs_left2`/`irs_right1`/`irs_right2`, `laminar/B738/annunciator/
irs_align_left`/`irs_align_right`/`irs_align_fail_left`/`irs_align_fail_right`/
`irs_dc_fail_left`/`irs_dc_fail_right`, all **read-only**) and an `LATLON.lua` command block
(`laminar/B738/toggle_switch/irs_source_left`/`_right`, `irs_L_left`/`_right`, `irs_R_left`/`_right`,
`irs_sys_dspl`, `irs_dspl_sel_left`/`_right`, `irs_dspl_sel_brt_left`/`_right`).

Every one of those commands, read closely, belongs to the small **IRS DISPLAY UNIT** — the
lat/long readout panel with its own L/R source-select knob — not the big rotary **IRS mode
selector** (OFF / ALIGN / NAV / ATT) that actually controls each inertial reference unit's power
and alignment state. That control is a real, physical part of the overhead panel and the issue
explicitly asks for it, but **no dataref or command resembling an IRS mode/power selector appears
in either reference file.**

This is exactly the situation `core/cockpit/`'s "park, don't guess" rule exists for (design §D10,
README's "Park, don't guess" section) — except one phase earlier: this document is not asserting
"verified absent", because no live probe was ever run against this aircraft; it is asserting "not
in the static reference the vendor ships", which is weaker and must not be silently upgraded to a
`parked:` entry with a live-sounding reason. The design's own Fake fixture (`irs_l`, four options
OFF/ALIGN/NAV/ATT) is a **synthetic example for the contract suite**, not evidence of a real Zibo
binding — it should not be mistaken for one.

**Recommendation for Phase 2:** search live (via the `xplane-datarefs` MCP or `search_datarefs`) for
`laminar/B738/*irs*mode*`, `laminar/B738/*irs*align*` (writable, not just the read-only
annunciators above), `laminar/B738/*irs*sel*` outside the `LATLON.lua`/display block, or a rotary
under a different prefix entirely (e.g. `laminar/B738/knob/*`, `laminar/B738/rotary/*` — the file's
own convention for other rotaries like `bank_angle`). If nothing turns up, this becomes a formal
`parked:` entry with that live-negative result as the reason, per the design's rule.

---

## 7. Gaps — no candidate found

Named in issue #223's checklist, searched for in both reference files, no plausible dataref or
command found at all — not even a hypothesis by naming-convention analogy. Listed here rather than
guessed at, and rather than pre-emptively written into `parked:` (parking is a claim that the
control was live-verified absent, which nothing in this document is):

| Item | Where it was expected | What was found instead |
|---|---|---|
| **Battery switch** | Electrical | Nothing. The only related dataref is `laminar/B738/annunciator/bat_discharge` ("BATT DISCHARGE") — an annunciator light implying a battery system exists, not a switch. |
| **Standby power switch** | Electrical | Nothing. Only `laminar/B738/annunciator/standby_pwr_off` ("STANDBY POWER OFF") — again an annunciator, not a switch. |
| **Bus transfer switch** | Electrical | Nothing. Only `laminar/B738/annunciator/trans_bus_off1` / `trans_bus_off2` ("TRANSFER BUS 1/2 OFF") — annunciator lights, not a manual control. It is also worth flagging for the user: the real 737NG's bus transfer logic is largely automatic (no dedicated instructor-actuable "bus transfer" switch on the real aircraft either), so this item in the issue's checklist may need a definitional check before Phase 2 spends time searching for it. |
| **IRS mode selector L** | IRS | See [§6](#6-irs-mode-selectors-lr) — only the display-unit's L/R *source* selector was found, not the mode/power selector. |
| **IRS mode selector R** | IRS | Same as above. |

Also genuinely missing but **not** a hard gap because a write path exists — listed here for
visibility, detailed in §1: no discoverable **read** binding for any of the four generator
switches (`gen1`, `gen2`, `apu_gen1`, `apu_gen2`) or the two generator drive disconnects. These
have a plausible write path (the `_up`/`_dn` commands) and are not being parked, but they cannot be
verified — let alone shipped — without a read binding, so Phase 2's live pass needs to either find
the missing `_pos` dataref or determine there isn't one.

Adjacent items seen in the source files near this panel's subsystems but **deliberately left out**
because they fall outside issue #223's named scope (not because no candidate exists) — flagged so
the omission reads as a choice, not a miss, and so a future issue can claim them explicitly:

- Equipment cooling exhaust/supply, flight deck door, service interphone, ELT, display-panel
  source selectors, GPWS inhibit switches, alternate flaps control — all real overhead-panel
  switches, all with plausible command/dataref pairs in the reference files, none named in this
  issue's checklist.
- Engine start selectors (`starter1_pos`/`starter2_pos`, `eng_start_source`) and the fuel-flow
  selector (`fuel_flow_pos`) — adjacent to the fuel/APU-start section textually, but the issue
  names "APU start/bleed" specifically, not engine start; left unclaimed.
- `laminar/B738/knob/ac_power_up`/`dn` and `dc_power_up`/`dn` — read as the AC/DC volt-amp meter's
  *display source* selector knob, not a power switch; excluded as instrumentation, not a control.

---

## Summary counts

| Subsystem | Candidates found | Hard gaps (no candidate at all) |
|---|---|---|
| Electrical | 9 (4 generator/APU-gen switches with write-only confidence, 2 gen-drive disconnects with kind uncertain, APU master, APU bleed, external power) | 3 (battery, standby power, bus transfer) |
| Fuel | 7 (6 pumps + crossfeed) | 0 |
| Hydraulics | 4 (all four pumps, clean pairs) | 0 |
| Anti-ice | 9 (4 window heat + 2 probe heat [path-ambiguous] + wing + 2 engine) | 0 |
| Pneumatics | 5 core (2 engine bleeds + isolation valve + 2 packs; APU bleed cross-referenced under Electrical) + 4 adjacent/out-of-scope candidates noted | 0 |
| IRS mode selectors L/R | 0 | 2 (both sides) |
| **Total** | **34 core candidates** (+4 adjacent, not drafted) | **5 hard gaps** |

Every one of the 34 core candidates is UNVERIFIED. None has been written, read, or read back
against a live simulator. The draft catalog file
(`adapters/xplane/cockpit_catalogs/zibo-b738/overhead.yaml.draft`) mirrors this document's
candidates in the catalog's YAML shape, for the live-verification pass to work through directly —
it is not a `.yaml` file and is not loadable by `core.cockpit.catalog.load_all_catalogs` (no
`verified_on` values are set, and the `.draft` suffix keeps it out of the loader's `*.yaml`/`*.yml`
glob entirely).
