# Zibo 737 MCP/autopilot dataref mapping — investigation

Live-verified findings for issue #214: does `_write_autopilot`
(`adapters/xplane/xplane_adapter.py:2529`) actually drive the Zibo 737's MCP, and what would a
correct per-aircraft mapping look like. Investigation only — no adapter code changed.

| | |
|---|---|
| Aircraft tested | Zibo Mod B737-800X, **version 4.05.33** (`Aircraft/B737-800X/b738.acf`, `version.txt`) |
| Comparison aircraft | Laminar Research stock Boeing 737-800 (`Aircraft/Laminar Research/Boeing 737-800/b738.acf`) |
| Simulator | X-Plane 12.4.3, Web API v2, on the ground, IRS aligned, electrical power on |
| Date | 2026-09-02 |
| Method | Live read-back of every write, via the same `GET/PATCH /api/v2/datarefs/{id}/value` and `POST /api/v2/command/{id}/activate` calls the adapter itself uses. Throwaway scripts, not committed. |

**Headline result: `_write_autopilot`'s generic-dataref writes are a complete no-op on Zibo.** The
altitude, heading and vertical-speed dials silently reject the generic write outright (read back
unchanged, reconfirmed under controlled retests that ruled out an unarmed-precondition
explanation); the airspeed dial accepts the generic write but Zibo's own dial ignores it; the
master/FD ladder dataref never moves at all; none of the three "on" lateral-mode commands ever
reach Zibo's mode logic. Every one of Zibo's own `laminar/B738/*` controls tested, by contrast,
worked and read back exactly as commanded.

---

## 1. Master switch / Flight director

`AircraftSetup.autopilot_master` / `.flight_director` → currently `sim/cockpit/autopilot/autopilot_mode` (0/1/2 ladder).

**Generic dataref: dead.** Writing 0, 1 and 2 to `autopilot_mode` each read back as `0`
immediately; Zibo's own `flight_director_pos`/`cmd_a_status`/`cmd_b_status` never moved in
response. Conversely, engaging Zibo's real FD (below) never moved `autopilot_mode` off `0` either.
Fully decoupled in both directions — this is not a timing issue, it never took at all.

**Correct mapping — commands, not a dataref write:**

| Field | Command | Read-back |
|---|---|---|
| Flight director (captain) | `laminar/B738/autopilot/flight_director_toggle` | `laminar/B738/autopilot/flight_director_pos` |
| Flight director (F/O) | `laminar/B738/autopilot/flight_director_fo_toggle` | `laminar/B738/autopilot/flight_director_fo_pos` |
| Master (CMD A) | `laminar/B738/autopilot/cmd_a_press` | `laminar/B738/autopilot/cmd_a_status` |
| Master (CMD B) | `laminar/B738/autopilot/cmd_b_press` | `laminar/B738/autopilot/cmd_b_status` |
| Disengage | `laminar/B738/autopilot/disconnect_button` (or `capt_disco_press`/`fo_disco_press`) | same status datarefs → `0` |

Confirmed live: `flight_director_toggle` → `flight_director_pos` `0→1`, and back to `0` on a
second press. `cmd_a_press` → `cmd_a_status` `0→1`; `disconnect_button` → back to `0`.

**Design consequence.** These are *momentary toggles*, not a settable value — `AircraftSetup`'s
boolean fields describe a target *state*, not an edge. Applying them on Zibo means reading the
status dataref first and pressing only if it disagrees with the requested state, the same
"only press if needed" shape `_write_autopilot` already uses nowhere today because the generic
dataref never needed it.

## 2. Lateral modes (HDG SEL / LNAV/NAV / APP)

`AircraftSetup.autopilot_hdg` / `.autopilot_nav` / `.autopilot_app` → currently
`_LATERAL_MODE_COMMANDS` (`sim/autopilot/heading`, `sim/autopilot/NAV`, `sim/autopilot/approach`),
neutral `sim/autopilot/wing_leveler`.

**All three generic "on" commands: dead, confirmed under a fair test.** The first pass fired these
with the Flight Director off — exactly the state that (see below) also makes Zibo's *own* press
commands inert, so a first result of "nothing changed" there wasn't a clean signal either way. A
second, controlled pass fired `sim/autopilot/heading`, `sim/autopilot/NAV` and
`sim/autopilot/approach` with FD **on** (the precondition that makes Zibo's real commands work —
see below): every one of Zibo's mode annunciators still read `0` afterward
(`hdg_sel_status`, `pfd_hdg_mode`, `lnav_status`, `ap/nav_status`, `ap/lnav_status`, `app_status`,
`ap/approach_status`). The generic "on" commands are confirmed dead, not merely untested.

**The neutral command is *not* dead** — `sim/autopilot/wing_leveler` (generic) reliably cleared
`hdg_sel_status` back to `0` in every cleanup step of this session. Worth noting as an asymmetry:
the "off" side of the generic lateral-mode surface reaches Zibo; the three "on" commands don't.

**Correct mapping — Zibo's own MCP button-press commands, all four now read-back confirmed:**

| Field | Command | Read-back |
|---|---|---|
| HDG SEL | `laminar/B738/autopilot/hdg_sel_press` | `laminar/B738/autopilot/hdg_sel_status`, `pfd_hdg_mode` |
| VOR/LOC | `laminar/B738/autopilot/vorloc_press` | `laminar/B738/ap/nav_status` (shared with LNAV's capture annunciator, not a separate `vorloc_status`) |
| LNAV | `laminar/B738/autopilot/lnav_press` | `laminar/B738/autopilot/lnav_status`, `laminar/B738/ap/lnav_status` |
| APP | `laminar/B738/autopilot/app_press` | `laminar/B738/autopilot/app_status`, `laminar/B738/ap/approach_status` |

**A precondition that is a real finding, not a mapping bug: these presses only register once a
Flight Director is on.** First attempt (FD off): `hdg_sel_press` left `hdg_sel_status` at `0`.
Immediately re-tried with FD on (`flight_director_toggle` first): the identical press set
`hdg_sel_status → 1` and `pfd_hdg_mode → [1, 1]` (both PFDs annunciate) on the very next read. The
same controlled pass (FD on) also confirmed `vorloc_press` (`ap/nav_status → [1, 1]`) and
`app_press` (`app_status → 1`, `ap/approach_status → [1, 1]`). This matches real 737 MCP logic — a
caller asking for `autopilot_hdg=True` without also asking for `flight_director=True` (or
`autopilot_master=True`) will silently do nothing on Zibo, and any implementation needs to apply
FD/master *before* lateral-mode presses, not just in field-declaration order.

`lnav_press` did **not** arm LNAV even with FD on, in either pass — there was no active FMC route
loaded on the test aircraft, and LNAV genuinely cannot capture without one, on the real aircraft
too. Treat this as an unmet precondition observed live, not a broken command; not re-tested with a
route loaded.

## 3. Altitude dial

`AircraftSetup.target_altitude_ft` → currently `sim/cockpit2/autopilot/altitude_dial_ft`.

**Generic write: silently rejected.** `3000 → 3500` commanded; read back `3000` on *both* the
generic dataref and `laminar/B738/autopilot/mcp_alt_dial` — Zibo re-asserts its own value over the
generic dataref every frame, the write never survives even one round trip.

**Zibo's own dial works, and syncs one-way into the generic dataref.** Writing
`laminar/B738/autopilot/mcp_alt_dial` (`3000 → 4000`) succeeded, and the generic
`altitude_dial_ft` read back `4000` too — Zibo pushes its own value into the generic dataref, but
the generic dataref cannot push back. **Write `mcp_alt_dial`; either dataref is fine to read back
from.**

## 4. Heading dial

`AircraftSetup.target_heading_deg` → currently `sim/cockpit2/autopilot/heading_dial_deg_mag_pilot`.

Identical pattern to altitude, confirmed live: generic write rejected (`236 → 276` attempted,
stayed `236` on both datarefs); writing `laminar/B738/autopilot/mcp_hdg_dial` directly succeeded
(`236 → 316`) and the generic dataref mirrored it. **Write `mcp_hdg_dial`.**

## 5. Airspeed dial (IAS/Mach)

`AircraftSetup.target_ias_kt` / the IAS/Mach toggle → currently
`sim/cockpit2/autopilot/airspeed_dial_kts_mach` + `sim/cockpit2/autopilot/airspeed_is_mach`.

**Different failure mode from altitude/heading: the generic write is accepted but ignored, not
rejected.** `100 → 140` commanded on the generic dataref: it *stuck* (read back `140`), but Zibo's
own `mcp_speed_dial_kts`/`mcp_speed_dial_kts2` never moved — Zibo simply never reads this dataref,
so an unprotected write to it just sits there doing nothing to the real MCP.

**Zibo's own dial works, and does *not* sync back to the generic dataref** (the reverse of
altitude/heading): writing `laminar/B738/autopilot/mcp_speed_dial_kts` (`100 → 160`) succeeded, but
the generic dataref stayed at whatever we'd last written into it (`140`) — no cross-sync either
direction here. **Write `mcp_speed_dial_kts`.**

**Read-back gotcha:** `mcp_speed_dial_kts2` and `mcp_speed_dial_kts_mach` are *not* the fields to
read for a fast write confirmation — both are slow, separately-updating echoes (observed
`100 → 104` for `kts2` within 0.4 s of a 60‑kt change, full convergence only after ~0.8 s /two
settle windows for `kts_mach`), consistent with Zibo animating its physical dial drum rather than
snapping it. Read `mcp_speed_dial_kts` itself back immediately; if a UI-accurate "settled" value is
ever needed, poll the others with a longer settle window.

**IAS/Mach changeover: unresolved.** Firing `laminar/B738/autopilot/change_over_press` produced no
change in `sim/cockpit2/autopilot/airspeed_is_mach` or `laminar/B738/autopilot/airspeed_mach` in
this session. Not enough evidence to say the command is wrong — needs a retest, possibly at an
altitude/speed where a Mach changeover is operationally meaningful.

## 6. Vertical speed dial

`AircraftSetup.target_vertical_speed_fpm` → currently `sim/cockpit2/autopilot/vvi_dial_fpm`.

**Generic write: silently rejected**, same failure mode as altitude/heading (`0 → 1500`
commanded, read back `0`). This directly contradicts the issue's premise (sourced from unverified
community reports) that this one field "stays generic" — it does not.

Confirmed under a fair test, not just on a cold MCP: the first pass tried this with VS mode
unselected, which risked the same false-negative shape as §2 (a precondition gate, not a dead
dataref). A second pass armed the precondition properly first — FD on, CMD A on, then
`laminar/B738/autopilot/vs_press` fired and confirmed via `vs_status: 0 → 1` — and *then* wrote the
generic `vvi_dial_fpm` (`0 → 1500`). It still read back `0`. The rejection holds with VS mode
genuinely armed, not just with the MCP powered down.

**No verified way to set an absolute VS target on Zibo at all.** Every `laminar/B738/*vvi*`
dataref found (`vvi`, `ap_vvi_pos`, `vvi_dial_show`, `fms/vnav_vvi*`) is **read-only**, and no
`vs_up`/`vs_dn`-style repeat-press command exists — only `laminar/B738/autopilot/vs_press`, which
*selects* VS mode, not a value. The real 737's V/S wheel is a spun rotary encoder with no absolute
"set" position, and Zibo appears to model that faithfully: there may genuinely be no dataref path
to an exact commanded VS on this aircraft. This needs a dedicated follow-up (search for an
undiscovered encoder-repeat command, or accept the limitation) before any mapping can be written
for this one field.

## 7. Aircraft detection

- `sim/aircraft/view/acf_ICAO` reads `B738` for **both** the Zibo and the stock Laminar 737-800 —
  confirms the issue's premise that ICAO cannot distinguish them.
- `sim/aircraft/view/acf_relative_path` differs (`Aircraft/B737-800X/b738.acf` vs.
  `Aircraft/Laminar Research/Boeing 737-800/b738.acf` on this install) but is a path convention,
  not a contract — a renamed install folder would break it. Usable as a cheap first heuristic,
  not as the sole detection key.
- **Resolved live: `laminar/B738/*` datarefs are Zibo-specific, not shared by the whole 737
  family.** With the Zibo loaded, `search_datarefs` and a direct read of
  `laminar/B738/autopilot/mcp_alt_dial` both succeeded. After swapping the loaded aircraft to the
  stock Laminar 737-800 (no restart), a live read of the same dataref failed outright:
  `{"error_code": "invalid_dataref_id", "error_message": "Dataref id ... doesn't exist"}`. Reading
  a generic dataref (`altitude_dial_ft`) worked fine on the same connection at the same moment.
  Interpretation: Zibo registers these as custom plugin datarefs when its own aircraft-specific
  plugin loads, and they stop existing once that plugin unloads on an aircraft swap — they are not
  part of the stock 737-800 at all.
- **Conclusion: this does *not* extend to "the whole 737-family, no Zibo-specific detection
  needed."** The issue's other branch applies — detect by probing whether a known Zibo-only
  dataref actually resolves.
- **The exact probe mechanism matters, and was checked directly against the raw Web API, not just
  through the adapter.** Post-swap, X-Plane's own **full** dataref index
  (`GET /api/v2/datarefs`, the same endpoint `connect()` scans at
  `xplane_adapter.py:901`) **still lists `laminar/B738/autopilot/mcp_alt_dial` by name, with an
  id** — that endpoint is stale after an aircraft change and cannot be used to detect absence. The
  **per-name lookup** (`GET /api/v2/datarefs?filter[name]=<name>`), the exact shape
  `_lookup_command_id` (`xplane_adapter.py:987`) already uses for commands, correctly 404s
  (`"invalid_dataref_name"`) once Zibo is gone. So does reading a stale id directly
  (`"invalid_dataref_id"`). **The detection probe must use the `filter[name]` lookup (or a direct
  value read caught for 404), never a scan of the cached full index** — reusing `connect()`'s
  existing full-index-scan pattern for this would silently resolve a dead id after any aircraft
  swap.

## 8. Dataref lifecycle (not live-tested; a design read of the existing code)

`connect()` (`xplane_adapter.py:890`) resolves every id in `DATAREFS`/`OPTIONAL_DATAREFS` **once**,
from a single index scan at connect time. Finding #7 means this is not sufficient once a
per-aircraft override exists: `laminar/B738/*` ids only exist while Zibo is the loaded aircraft,
they will not appear in the index resolved before Zibo is selected, and (per the same finding)
they stop resolving the moment the aircraft changes away from Zibo — mid-session, with no
reconnect. A Zibo-aware override therefore needs its own resolve step that runs **on aircraft
change**, not only inside `connect()`. This adapter has no aircraft-change hook today (nothing
polls `acf_relative_path`/`acf_tailnum` after the initial connect) — that hook is new surface, not
something an override table can reuse from elsewhere. And per §7, that resolve step cannot reuse
`connect()`'s own full-index-scan approach for the Zibo-specific ids — the full index is exactly
the endpoint proven stale after a swap; it needs the same per-name `filter[name]` lookup the
detection probe uses.

---

## Recommendation

**Implement now, narrowly scoped — every item below is read-back confirmed, including under a
controlled retest that ruled out the "was it just an unarmed precondition?" alternative
explanation:**

- A small aircraft-specific override table (per `docs/feature-spec.md` §6 / the existing
  "per-aircraft override layer" discussion — not a new abstraction layer), keyed by probing
  **`GET /api/v2/datarefs?filter[name]=laminar/B738/autopilot/mcp_alt_dial`** for a live resolve
  (not ICAO, and not the plain full-index scan `connect()` already does — §7 shows that scan is
  stale after an aircraft swap).
- Override altitude → `mcp_alt_dial`, heading → `mcp_hdg_dial`, airspeed → `mcp_speed_dial_kts`
  (all three read-back confirmed).
- Override master/FD/lateral-mode writes to fire Zibo's press/toggle commands
  (`flight_director_toggle`, `cmd_a_press`/`cmd_b_press`, `hdg_sel_press`/`vorloc_press`/
  `lnav_press`/`app_press`, `disconnect_button`) instead of the dead generic ladder and commands —
  each guarded by a read-back-and-compare instead of an unconditional press, since these are
  toggles, not sets. Apply FD/master *before* any lateral-mode press (§2's precondition).
- Add the aircraft-change detection hook this needs (§8), resolving Zibo-specific ids via the same
  `filter[name]` lookup as the detection probe, never via `connect()`'s cached full-index scan.

**Park, don't guess:**

- Vertical speed — no verified settable dataref exists on Zibo at all (§6), and the generic
  dataref's rejection was reconfirmed with VS mode genuinely armed, not just inferred from a cold
  MCP. Shipping a mapping here would be inventing a control, not verifying one.
- The IAS/Mach changeover command — one inconclusive result (§5), unrelated to the precondition
  issue that affected §2/§6, still needs a retest before it goes in a mapping table.
- `lnav_press` needs a retest with an active FMC route loaded before LNAV goes in the override
  table as "working" — confirmed a real precondition (not a broken command) but not exercised
  end-to-end in this session.
