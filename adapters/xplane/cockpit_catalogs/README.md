# X-Plane cockpit control catalogs

One directory per aircraft, loaded by `core.cockpit.catalog.load_all_catalogs`
and executed by `adapters/xplane/cockpit_controls.py`. The full schema, the
detection model and the per-kind execution rules are specified in
[`docs/designs/cockpit-control-catalog.md`](../../../docs/designs/cockpit-control-catalog.md)
— this file is the short, local version an author reaches for while writing a
YAML file, not a replacement for it.

## Directory layout (D4)

```
cockpit_catalogs/
  <catalog-id>/            # kebab-case, e.g. zibo-b738
    aircraft.yaml           # REQUIRED: aircraft, detect, panels
    <panel>.yaml             # any name, any number of files: controls / parked / setup_overrides
```

- `aircraft.yaml` is the only required file, and the only place `aircraft`,
  `detect` and `panels` may be declared. Everything else — `controls`,
  `parked`, `setup_overrides` — may be spread across any number of sibling
  `*.yaml`/`*.yml` files, merged by the loader in filename order.
- A `control_id` (or `setup_overrides` key) repeated across files is a load
  error, not a silent override.
- The directory name must equal `aircraft.catalog_id`.
- `readable` is never written in a file — the loader derives it from the
  binding (always `True` for toggle/dial/selector, always `False` for press,
  binding-dependent for encoder).

This split exists so several aircraft-data PRs can be authored in parallel
without ever touching the same file (`docs/designs/cockpit-control-catalog.md`
§9.3): one issue owns `mcp.yaml`, another owns `overhead.yaml`, and so on.

## Detection (D5)

`detect.dataref_exists` is probed live, by name, against
`GET /api/v2/datarefs?filter[name]=<path>` — **never** `acf_ICAO` (two
different 737 add-ons can both report `B738`) and never the cached full
dataref index (proven stale across an aircraft swap). Pick a dataref that:

- exists only on the target aircraft, not on the stock aircraft it is based
  on;
- is confirmed **both present and absent** against a live sim — present with
  the aircraft loaded, a bare 404 with a different aircraft loaded. Confirming
  only "present" leaves the false-positive case (a different aircraft that
  happens to share the name) completely unchecked.

## Verification method — "operationally verified", not read off documentation

Every `verified_on` date on a control means: **this exact binding was written
and read back against a live, running X-Plane**, the same standard
`docs/research/zibo-737-autopilot-dataref-mapping.md` sets and that this
project's `CLAUDE.md` "Known gotchas" repeats — a dataref name that looks
right from a forum post or an old X-Plane 11 reference is not verified. Concretely, for each control:

1. Read the `read` binding (or `write`, for a dial with no separate read) and
   record the current value.
2. Actuate it: `POST /api/v2/command/{id}/activate` for a `press`/`toggle`,
   `PATCH /api/v2/datarefs/{id}/value` for a `write`.
3. Read the binding back and confirm the value moved the way the control
   claims — a toggle's status flipped, a dial's read-back is within
   `readback_tolerance` of what was written.
4. Restore the original value before moving to the next control.

A binding that does not confirm this way is not "close enough" — see
"Park, don't guess" below.

## The sweep flags (`live_sweep` / `live_sweep_note`)

`live_sweep: true` (the default) marks a control the automated live sweep
(`tests/sim/test_live_cockpit_catalog.py`, run once per Wave 2 PR by the
`sim-validator` agent) is allowed to actuate and restore unattended — flip it,
read it back, flip it back.

Set `live_sweep: false` — with a required `live_sweep_note` explaining why —
for anything the sweep must never touch on its own: battery/master switches
(cuts power to every later read-back in the same run), start levers, TO/GA,
or anything else whose *side effect* matters more than its confirmed state.
When in doubt, **default to `live_sweep: false`** — a control the sweep never
exercises is inconvenient; a control the sweep flips at the wrong moment can
end a training session or damage the simulated aircraft. `docs/architecture.md`
records this as a named risk this catalog format has to live with, not one it
eliminates.

## Park, don't guess (D10)

A control that exists on the real aircraft but has no dataref that confirms
step 3 above — a read-only vertical-speed indicator, a mode-select command
that produced no observable change in a session, a control that needs
preconditions (an FMC route, a specific phase of flight) nobody set up during
verification — goes in `parked:`, never in `controls:` with a binding that
"should" work:

```yaml
parked:
  - control_id: mcp_vs
    label: Vertical speed
    panel_id: mcp
    since: 2026-09-02
    reason: >
      No settable vertical-speed dataref exists on this aircraft; every
      *vvi* dataref found is read-only.
```

The UI renders a parked control disabled, with its reason inline — never
hidden. A future PR that finds a working binding removes the entry from
`parked:` and adds it to `controls:` in the same change; it never keeps both.

## `setup_overrides` (D11)

Maps an `AircraftSetup` autopilot field name to a `control_id` in this
catalog, so `apply_setup()` routes that field through the catalog's own
verified binding instead of the stock, often-dead, generic dataref. A bool
field (`flight_director`, `autopilot_master`, `autopilot_hdg`, …) must map to
a `toggle` control; a float field (`target_altitude_ft`, `target_ias_kt`, …)
must map to a `dial`. Omit a field entirely rather than mapping it to a
control with no verified binding — an absent key means "the generic path
handles this field", which is honest when that path is itself a no-op on this
aircraft (the vertical-speed case above).

## Zibo B737-800X (`zibo-b738/`)

`aircraft.yaml` — identity, detection and the four panels — ships with Wave 1
Track B. The panel data files (`mcp.yaml`, `overhead.yaml`, `pedestal.yaml`,
`lights.yaml`) are Wave 2, one issue each: #222, #223, #224. Every row's
worked example, and the live findings behind it, are in
`docs/designs/cockpit-control-catalog.md` §5.7 and
`docs/research/zibo-737-autopilot-dataref-mapping.md`.
