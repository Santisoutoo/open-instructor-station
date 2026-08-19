# Position screen — replicate the "v3" redesign (static phase)

Status: the static phase described below is **done and superseded**. Commit 22b8d8d landed
the replica; the commit after it wired the screen to the real backend, so everything this
doc says about sample data, local-only state and an inert "Set position" button is now
history. What survives is the **visual system and the screen's structure** (sections
"Visual system", "Layout, top to bottom", the `positionSlice` constraint and the full-bleed
`App.tsx` shell) — those are still the spec.

What the wiring phase changed, against this document:

| This doc says | Now |
|---|---|
| `sampleData.ts` holds LFMN's runways, stands, procedures, wind, QNH, METAR, AIRAC | Deleted. Everything comes from `navdata`/`weather` through RTK Query. |
| `RunwayId` is `'04R'｜'22L'｜'04L'｜'22R'｜'HELI'` | A runway **ident string** from navdata. The `HELI` pseudo-runway is gone — the runways endpoint publishes runway ends, not helipads. |
| `RECIPROCAL_RUNWAY` is a hard-coded map | `Runway.opposite_ident`, from navdata. |
| The 9 circuit markers carry an altitude and a heading | They carry `(u, v)` and nothing else. Altitude, heading and speed are the preview's. |
| The final markers are fixed at 3 NM and 8 NM | The final marker gains a **distance selector** over the server's seven finals, driven by the generated enum. The dots stay as illustration. |
| The parking filter is "gate heavy / gate medium / misc / tie-down" | The server's own `ParkingKind`: gates, tie-downs, hangars, other. `apt.dat` makes no heavy/medium distinction. |
| The airport diagram places stands at hand-picked `x/y` | A pure, tested projection of real stand and threshold coordinates (`standProjection.ts`). The three terminal blocks are gone: `apt.dat` publishes no buildings. |
| Check 7, "Position inside the LFMN CTR", always passes | Deleted. There is no airspace source; a check that always passes teaches an instructor to stop reading the list. |
| "Set position" is inert and `state.position.staged` stays `null` | The button applies, and the resolved placement is mirrored onto `positionSlice` so the Map hand-off and Profiles' Save work again. |
| The Custom tab offers "relative to the runway landing point" | Offered and **disabled with the reason**: the placement union has no bearing-and-distance member, and resolving one here would be geodesy in the browser. |

This doc supersedes §15 of `docs/designs/position-manager.md` for everything about the
**panel's UI**; §15's API/model sections (endpoints, `PlacementRequest`, `AircraftSetup`,
gating) are correct and are what the wiring phase consumes.

## Scope

This is a **static visual replica** of an approved design ("POSITION Rediseño v3", a Claude
Design canvas mockup). Only the Position screen changes. All nine other panels
(Scenarios, Weather, Failures, Fuel & payload, Profiles, Map, Aircraft, Landing analysis,
Traffic) are untouched.

"Static" means: sample data (airport LFMN, wind 240°/12 kt, QNH 1013 hPa, a METAR line, AIRAC
2508) and **local design state** (which tab, which runway, which circuit marker, checkbox
values…). It is **not** wired to RTK Query / the real backend in this phase — that is an
explicit later phase. The existing generated API client (`ui/src/api/**`) is not touched.

Do not add features, polish, or "while I'm here" fixes beyond what is specified below. Do not
weaken `ui/tsconfig.app.json` (it says "do not weaken" in a comment — strict,
`noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `verbatimModuleSyntax`,
`erasableSyntaxOnly`, `noUnusedLocals`, `noUnusedParameters`).

## The hard constraint: `positionSlice.ts` is shared, do not touch it

`ui/src/features/position/positionSlice.ts` is read by code **outside** the position feature:

| Consumer | What it uses |
|---|---|
| `ui/src/features/map/MapStagingBar.tsx` | dispatches `placementStaged`, `tabSelected` |
| `ui/src/features/weather/weatherSlice.ts` | imports `airportSelected` (its `extraReducers` resets the weather UI when it fires) |
| `ui/src/features/weather/WeatherPanel.tsx` | reads `state.position.selectedIcao`, `state.position.selectedRunwayIdent` |
| `ui/src/features/profiles/selectors.ts` | reads `state.position.staged`, `.setupOverrides`, `.selectedIcao`, `.selectedRunwayIdent` |
| `ui/src/features/map/MapPanel.test.tsx` | asserts `state.position.staged` and `state.position.activeTab === 'coordinate'` |

**Do not rename, extend, or repurpose any field or action on this slice.** Its current shape
(verbatim):

```ts
export type PositionTab = 'pattern' | 'procedures' | 'parking' | 'coordinate';
export const RECENT_AIRPORT_LIMIT = 5;

export interface PositionState {
  selectedIcao: string | null;
  selectedRunwayIdent: string | null;
  activeTab: PositionTab;
  openProcedure: { kind: string; ident: string; transition: string | null } | null;
  staged: PlacementRequest | null;
  setupOverrides: AircraftSetup;
  recentIcaos: string[];
}
```

Actions: `airportSelected(icao: string)` (upper-cases, clears runway/procedure/staged/overrides,
pushes to `recentIcaos`), `runwaySelected(ident: string)` (clears staged+overrides),
`tabSelected(PositionTab)`, `procedureOpened(...)`, `placementStaged(PlacementRequest)`,
`setupOverridden({ field, value })`, `staleCleared()`.

**The replica must mirror two of these for real**, so Weather and Map keep working with zero
change on their side:
- The header's "Load" action dispatches `airportSelected(icao)` — **but only when the ICAO
  actually changed** (compare against `state.position.selectedIcao` first). `airportSelected`
  is destructive (wipes staged placement, overrides, open procedure) and also resets the
  entire Weather panel via its `extraReducers`. Re-clicking Load with the same ICAO must be a
  no-op dispatch-wise.
- Selecting a runway tab in the runway strip dispatches `runwaySelected(ident)` (same
  same-value guard).

Nothing else on `positionSlice` is touched by this phase. `staged` stays `null` throughout —
that is a known, accepted gap (see "Known gaps" below), not a bug to work around.

## New slice: `positionDesignSlice.ts`

All of the replica's own state — everything the old `positionSlice` doesn't already cover —
goes in a **new** slice, `ui/src/features/position/positionDesignSlice.ts`, registered as
`positionDesign` in `ui/src/store/index.ts`'s `reducerMap` (one import + one key, next to the
existing `position: positionReducer,` line). This keeps `state.position` meaning exactly what
its docstring says (server intent) and gives the replica a field, `activeTab`, that doesn't
collide with `PositionTab`.

```ts
export type DesignTabId   = 'approach' | 'sidstar' | 'airwork' | 'custom';
export type RunwayId      = '04R' | '22L' | '04L' | '22R' | 'HELI';
export type ParkingFilter = 'all' | 'gate-heavy' | 'gate-medium' | 'misc' | 'tie-down';
export type ProcedureKind = 'sid' | 'star' | 'apptr' | 'final';
export type AirworkLevel  = 'FL300' | 'FL200' | 'FL100' | 'FL050';
export type CustomOrigin  = 'runway-relative' | 'coordinates';
export type MarkerId =
  | 'takeoff' | 'downwind-left' | 'downwind-right'
  | 'vectors-left' | 'vectors-right' | 'base-left' | 'base-right'
  | 'final-3nm' | 'final-8nm';

export interface PositionDesignState {
  icaoInput: string;                 // 'LFMN' — the header's editable text field
  loadedIcao: string;                // 'LFMN' — what Load last committed
  screenMenuOpen: boolean;
  startAtOpen: boolean;
  parkingFilter: ParkingFilter;
  selectedRunway: RunwayId | null;   // mutually exclusive with selectedStand
  selectedStand: string | null;
  activeTab: DesignTabId;
  selectedMarker: MarkerId;
  procedureKind: ProcedureKind;
  procedureIdent: string;
  procedureMenuOpen: boolean;
  airworkLevel: AirworkLevel;
  custom: {
    altitudeFt: number; headingDeg: number; origin: CustomOrigin;
    bearingDeg: number; distanceNm: number; latitude: number; longitude: number;
  };
  config: {
    iasKt: number; pitchDeg: number; gearDown: boolean;
    flapsOn: boolean; flapsPercent: number;
    altitudeOverride: boolean; altitudeOverrideFt: number;
  };
  send: { heading: boolean; course: boolean; ilsFrequency: boolean };
}
```

Export `initialPositionDesignState` (same convention as `uiSlice.initialUiState`,
`connectionSlice.initialConnectionState`). Initial values match the design's sample defaults:
`icaoInput`/`loadedIcao`: `'LFMN'`, `selectedRunway: '04R'`, `activeTab: 'approach'`,
`selectedMarker: 'final-3nm'`, `procedureKind: 'sid'`,
`procedureIdent: 'BADO8A.04B.BADOD'`, `airworkLevel: 'FL100'`, `custom.origin:
'runway-relative'`, `config.iasKt: 60`, `config.flapsOn: true`, `config.flapsPercent: 25`,
`send: { heading: true, course: true, ilsFrequency: true }`, everything else `false`/`0`.

Action creators (name them exactly this so no import site needs an alias):
`icaoTyped(string)`, `airportLoaded(string)` *(the mirrored dispatch happens in the component,
not here — this action just updates `loadedIcao`)*, `screenMenuToggled()`,
`startAtToggled()`, `parkingFilterSelected(ParkingFilter)`,
`startRunwaySelected(RunwayId)` *(sets runway, clears `selectedStand`)*,
`startStandSelected(string)` *(sets stand, clears `selectedRunway`)*,
`designTabSelected(DesignTabId)`, `markerSelected(MarkerId)`,
`procedureKindSelected(ProcedureKind)`, `procedureIdentSelected(string)`,
`procedureMenuToggled()`, `airworkLevelSelected(AirworkLevel)`,
`customOriginSelected(CustomOrigin)`,
`customFieldChanged({ field: keyof PositionDesignState['custom']; value: number })`,
`configChanged({ field: keyof PositionDesignState['config']; value: number | boolean })`,
`sendToggled(key: keyof PositionDesignState['send'])`,
`situationReset()` (resets to `initialPositionDesignState`, used by "Reset situation").

Popover open/close state that is purely transient UI (the nav dropdown, Start-at popover,
procedure-ident dropdown) is deliberately **in this slice, not local `useState`**, to match
what the v3 source does (it's part of one component's state object) and because
`screenMenuOpen`/`startAtOpen` need to close each other (opening one closes the other, same as
today's `navOpen`/`gateOpen` pattern in `PositionPanel.tsx`).

## Files

Everything below is in `ui/src/features/position/` unless stated otherwise.

### Delete

`AirportSearch.tsx` + test, `RunwaySelector.tsx` + test, `PatternGrid.tsx` + test,
`ProcedureList.tsx` + test, `ParkingList.tsx` + test, `CoordinateForm.tsx` + test,
`StagingBar.tsx` + test, `Schematic.tsx` + test, `projection.ts` + test, `placements.ts` + test.

`projection.ts` is **not reusable**: it auto-fits an arbitrary point set into a 320×180 box
with a derived scale; the v3 diagram uses a **fixed** 40 px/NM scale in a 720×520 box rotated
by runway course. Different maths for a different job — don't try to share it.

`placements.ts`'s tile tables are superseded, but **lift these four formatters verbatim into
the new `format.ts`**: `formatAltitudeFt`, `formatSpeedKt`, `formatRunwayLength`,
`formatIlsFrequency`. Port their existing test cases from `placements.test.ts` into
`format.test.ts` rather than re-deriving them.

### Keep, untouched

- `positionSlice.ts` + `positionSlice.test.ts` — see above, not one line changes.
- `gate.ts` + `gate.test.ts` — `navdataGate`/`commitGate`/`airacLabel`, typed against the
  generated schema. Unused by this phase (nothing here calls the real navdata API yet) but
  kept as-is: it's the exact "fail closed" contract the wiring phase must reinstate, and
  deleting it means rewriting it later for free.
- `errors.ts` + `errors.test.ts` — near-identical modules already exist in
  `features/weather/errors.ts` and `features/fuel-payload/errors.ts`, both citing this one by
  name. Deleting it makes Position the odd one out.

### Keep, trimmed

- `testApi.ts` — **must not be deleted wholesale**:
  `ui/src/features/fuel-payload/FuelPayloadStagingBar.test.tsx` imports
  `{ type Answer, callsTo, stubApi }` from `'../position/testApi'`. Keep `ApiCall`, `Answer`,
  `stubApi`, `callsTo`. Delete only the `positionState()` helper (it hardcodes the old
  `PositionState`'s field list and its only callers are the tests being deleted).

### New — pure `.ts` modules (no JSX; `react-refresh/only-export-components` is `error`,
### so any function-exporting file must NOT also export a component)

| File | Role |
|---|---|
| `positionDesignSlice.ts` | State + actions, as specified above. |
| `sampleData.ts` | Frozen LFMN sample data (below). `as const`, no React. |
| `wind.ts` | `windComponents(windDeg, windKt, courseDeg)` and `runwayWind(runway, windDeg, windKt)` — head/cross/tail decomposition, see formulas below. |
| `circuit.ts` | `place(u, v, courseDeg)` fixed-scale projection, tick generator, wind/north arrow rotation — see formulas below. |
| `markers.ts` | The 9 circuit marker table (id, label, sub-line template, `(u,v)`, meta) + `labelPlacement`. |
| `applyRows.ts` | Derives the right rail's rows from design state + sample data. |
| `checks.ts` | The checks rule list. |
| `format.ts` | The 4 lifted formatters + `formatFlightLevel`, `formatDistanceNm`, `formatHeadingM`. |

### New — components

| File | Role |
|---|---|
| `PositionPanel.tsx` | **Rewritten in place** (keep the exported name `PositionPanel` — `ui/src/components/tabs.ts` imports `m.PositionPanel`). The screen root: composes the 5 bands, applies the `.pos` scope class and `data-theme` follow-through. |
| `PositionHeaderBar.tsx` | 64px header: screen-menu trigger, ICAO input + airport name + Load/Search/Random, Start-at trigger, connection dot, theme toggle. |
| `ScreenMenu.tsx` | Popover listing `TABS` from `ui/src/components/tabs.ts`, dispatching `tabSelected` from `ui/src/store/uiSlice`. |
| `StartAtPopover.tsx` | 716px popover: sidebar (runway/helipad list + parking-type list) + `AirportDiagram` + stand list with "N of M". |
| `AirportDiagram.tsx` | 340×262 SVG (two runway strips, taxiway lines, 3 terminal blocks) + absolutely-positioned stand markers. |
| `RunwayStrip.tsx` | Runway tabs with per-runway wind, facts row, Wind + QNH readouts. |
| `PositionTabs.tsx` | The `role="tablist"` strip: Approach training / SID & STAR / Airwork / Custom location. |
| `ApproachTrainingTab.tsx` | `CircuitDiagram` + "Selected start position" column + footnote. |
| `CircuitDiagram.tsx` | The 720×520 SVG. Pure props → SVG, no store access. |
| `SidStarTab.tsx` | Procedure-type selector, ident dropdown, breadcrumb, facts. |
| `AirworkTab.tsx` | Level ladder + fact rows. |
| `CustomLocationTab.tsx` | Altitude/Heading inputs, the two radio groups, fact rows. |
| `ApplyRail.tsx` | 480px rail: "Will be applied" rows, Checks, METAR/AIRAC footer. |
| `BottomBar.tsx` | Aircraft configuration group, "Sent with the position" group, Set position / Reset situation. |
| `FactRow.tsx` | Shared `label | mono value | optional tag` row (used by 4 tabs + the rail). |
| `Popover.tsx` | Shared anchored popover: outside-click + Escape close, focus return, `aria-expanded`/`aria-controls`. **Do not use the native `[popover]` attribute or `<dialog>`** — jsdom doesn't implement the Popover API and tests need to open these programmatically. |
| `position.css` | Rewritten, all rules scoped under a `.pos` root class. |

### New tests

`wind.test.ts`, `circuit.test.ts`, `markers.test.ts`, `checks.test.ts`, `applyRows.test.ts`,
`format.test.ts`, `positionDesignSlice.test.ts`, `PositionPanel.test.tsx`,
`PositionHeaderBar.test.tsx`, `StartAtPopover.test.tsx`, `BottomBar.test.tsx`, and a new
`ui/src/App.test.tsx` (nothing renders `App` today — this is the first).

### Edited outside the feature

- `ui/src/components/tabs.ts` — no change needed to the loader itself (`PositionPanel` keeps
  its name), but double check the import still resolves.
- `ui/src/store/index.ts` — add `positionDesign: positionDesignReducer` to `reducerMap` + the
  import.
- `ui/src/App.tsx` — full-bleed, see below.
- `ui/src/index.css` — add the `.app--fullbleed` rules only (below). Do not touch the token
  blocks.
- `ui/src/main.tsx` — import the two new font packages, same pattern as the existing
  `@fontsource/ibm-plex-*` imports.
- `ui/package.json` — add `@fontsource/schibsted-grotesk` and `@fontsource/spline-sans-mono`,
  version `^5.3.0` (confirmed on npm, same major as the IBM Plex packages already used — do not
  guess a different version).
- `docs/designs/position-manager.md` — add a short note at the top of §15 pointing here for the
  current panel design; do not rewrite §15's API sections, they're still accurate.

## Full-bleed `App.tsx`

The map tab is `keepMounted` — do **not** early-return out of the `TABS.map(...)` render, only
make the chrome around it conditional:

```tsx
const activeTab = useAppSelector((state) => state.ui.activeTab); // already there
const fullBleed = activeTab === 'position';

<div className={fullBleed ? 'app app--fullbleed' : 'app'}>
  {!fullBleed && <header className="app__header">…unchanged…</header>}
  <div className="app__body">
    <main className="app__panelhost">
      {TABS.map((tab) => {
        // unchanged, EXCEPT:
        // aria-labelledby={fullBleed && active ? undefined : `tab-${tab.id}`}
        // (TabBar renders id="tab-position" only when the header exists)
      })}
    </main>
    {!fullBleed && drawerOpen && <ContextDrawer />}
  </div>
  {!fullBleed && <StatusBar />}
</div>
```

In `index.css`, add (do **not** set `display` in these rules — `.app__tabpanel[hidden] {
display: none }` already exists and any `display:` here would out-specificity-tie it and
un-hide the still-mounted map panel):

```css
.app--fullbleed .app__panelhost { padding: 0; overflow: hidden; }
.app--fullbleed .app__tabpanel  { max-width: none; margin: 0; gap: 0; align-items: stretch; height: 100%; }
```

Two invariants this drops — call them out explicitly in the PR description, don't silently
break them:
- `index.css` states synthetic telemetry must never pass for the simulator (`demoFeed` shows a
  chip in the status bar). Full-bleed hides the status bar. Put a small "Demo data" indicator
  in `PositionHeaderBar` next to the connection dot, gated on `state.ui.demoFeed`.
- A running scenario is normally visible from every module via the status bar. Also hidden by
  full-bleed. Acceptable for this phase — note it in the PR, don't try to fix it now.

## Visual system — exact values from the v3 source

### Fonts

`'Schibsted Grotesk'` for all labels/prose, `'Spline Sans Mono'` for **every** aviation value:
runway idents, distances, altitudes, headings, frequencies, the METAR line, FL labels. Weights
used: Schibsted Grotesk 400/500/600; Spline Sans Mono 400/500/600. Self-hosted via
`@fontsource/schibsted-grotesk` and `@fontsource/spline-sans-mono`, imported in `main.tsx`
(not chunked into the lazy position bundle — `position` is the app's default boot tab, so it
loads at boot either way).

### Colour tokens (scope under `.pos`, do not touch global `index.css` palette)

Dark (default):
```
--pos-bg: oklch(0.155 0.012 250);      --pos-panel: oklch(0.19 0.013 250);
--pos-rail: oklch(0.215 0.014 250);    --pos-line: oklch(0.31 0.012 250);
--pos-hair: oklch(0.26 0.012 250);     --pos-t1: oklch(0.97 0.005 250);
--pos-t2: oklch(0.76 0.008 250);       --pos-t3: oklch(0.58 0.010 250);
--pos-hover: oklch(0.25 0.013 250);    --pos-accent: oklch(0.72 0.16 145);
--pos-on-accent: oklch(0.17 0.03 145); --pos-caution: oklch(0.80 0.13 78);
--pos-alert: oklch(0.68 0.17 25);
```
Light (`[data-theme='light'] .pos { … }`):
```
--pos-bg: oklch(0.96 0.004 250);       --pos-panel: oklch(0.995 0.002 250);
--pos-rail: oklch(0.975 0.003 250);    --pos-line: oklch(0.84 0.006 250);
--pos-hair: oklch(0.90 0.005 250);     --pos-t1: oklch(0.22 0.012 250);
--pos-t2: oklch(0.38 0.012 250);       --pos-t3: oklch(0.53 0.012 250);
--pos-hover: oklch(0.94 0.005 250);    --pos-accent: oklch(0.50 0.13 145);
--pos-on-accent: oklch(0.99 0.005 145);--pos-caution: oklch(0.56 0.14 65);
--pos-alert: oklch(0.50 0.18 25);
```
`document.documentElement.dataset.theme` (already maintained by `ui/src/store/uiSync.ts`) is
what drives the swap — no new theme logic needed. Accent green is used **strictly** for
selection/confirmation states; never as a generic brand colour. Caution amber for operational
warnings (tailwind, gear-up, low IAS). Grey/dim for unavailable/not-in-navdata. Give the
Position screen its own `--pos-focus: var(--pos-accent)` for `:focus-visible` rings — do not
reuse the app-wide `--focus` (amber), which would look wrong against the green accent.

### Layout, top to bottom

1. **Header (64px)** — screen-menu trigger ("Position ▼"); ICAO input (mono, 24px, editable,
   uppercase) + airport display name ("Nice / Côte d'Azur" for LFMN) + accent "Load" button +
   "Search"/"Random" text actions; "Start at" trigger showing `Runway 04R` or `Stand A3`;
   flex spacer; a blinking caution dot + "X-Plane connecting" text (bind the dot's blink to
   `state.connection.status !== 'connected'`, wrap the animation in
   `@media (prefers-reduced-motion: reduce) { animation: none }`); theme toggle text
   ("Dark"/"Light", dispatches `themeToggled` from `uiSlice`).

   **Start-at popover** (716px wide, opens below the trigger): left sidebar 186px — "Runways
   and helipads" list (04R·ILS, 22L, 04L·ILS, 22R, Heli) then "Parking type" list (All / Gate
   heavy / Gate medium / Miscellaneous / Tie-down). Right side: a 340×262 SVG airport diagram
   (two parallel runway strips near the right edge with idents "04L"/"04R" labelled, a
   taxiway line, three shaded terminal blocks labelled "Terminal 1", "Terminal 2", "General
   aviation") with absolutely-positioned clickable stand squares (12×12px, 2px corner radius);
   beside it, a "Stands" column with a "{shown} of {total}" count and a scrollable list of
   stand rows (id + type), filtered by the selected parking type. Selecting a stand clears the
   runway selection; selecting a runway clears the stand.

2. **Runway strip** — one tab per runway end (04R, 22L, 04L, 22R, Heli), each showing its own
   computed wind ("7 kt head" in dim text, or "5 kt tail" in caution colour when tail);
   facts row below the selected runway: non-Heli → Length / Surface / Elevation / Course / ILS
   (ILS shows "not available" dimmed when the runway has none); Heli → Type / Elevation only.
   Then Wind ("240° 12 kt") and QNH ("1013 hPa") readouts, both mono.

3. **Tab strip** — Approach training / SID & STAR / Airwork / Custom location, real
   `role="tablist"`/`role="tab"`/`aria-selected`.

   - **Approach training**: `CircuitDiagram` (720×520 SVG, geometry below) on the left, a
     "Selected start position" column on the right: big name (from the selected marker's
     `label`), rows Distance / Altitude / Heading / Wind / Runway, and a footnote: "Ticks
     every 2 NM from the threshold. Altitudes from a 3° path, 300 ft/NM, pattern 1,500 ft
     AAL."

   - **SID & STAR**: procedure-type row (Departure "SID" / Arrival "STAR" / Approach
     transition "APPTR" / Final approach "FINAL"); an ident dropdown (mono, 20px) showing
     the count "N in navdata" and, when open, the 8 sample idents with their via-waypoint;
     a 3-node breadcrumb `LFMN/{runway}` → procedure-short → first-waypoint; facts row
     Transition / First waypoint / Altitude restriction (always "not in navdata", dimmed).

   - **Airwork**: a level ladder — FL300/FL200/FL100/FL050, each row a tick bar (width scales
     with the level: FL300→58px, FL200→44px, FL100→30px, FL050→18px) + mono FL + feet on the
     right; fact rows Position ("Overhead LFMN · 43°39′N 007°12′E"), Level, IAS (caution
     colour if < 150 kt), Heading (= current runway course).

   - **Custom location**: Altitude (ft MSL) and Heading (°M) number inputs; radio "Relative to
     the runway landing point" with Bearing (°) / Distance (NM) inputs; radio "At
     coordinates" with Latitude / Longitude text inputs (format `43° 39' 35.27" N`); fact rows
     Resolved position / Altitude / Heading / Airspace ("inside LFMN CTR", accent colour).

4. **Right rail (480px fixed)** — "Will be applied" heading + "sample data" tag. Rows (label |
   mono value | provenance tag), see `applyRows.ts` spec below. Then "Checks": a coloured dot +
   text + note per check, see `checks.ts` spec below. Footer: METAR line (mono,
   `LFMN 171730Z 24012KT 9999 FEW035 26/18 Q1013 NOSIG`) + "Navdata X-Plane 12 · AIRAC 2508 ·
   METAR 6 min old".

5. **Bottom bar** — left: "Aircraft configuration · editable" — IAS (kt) input, Pitch (°)
   input, "Gear down" checkbox, "Flaps" checkbox + % input, "Override altitude" checkbox + ft
   input. Divider. Middle: "Sent with the position" — three checkboxes with mono values:
   Heading, Course, ILS frequency (this one `disabled` with `cursor: not-allowed` and shows
   "n/a" in caution colour when the selected runway has no ILS). Spacer. Right: "Show on map" /
   "Full METAR" text actions (inert in this phase — no map/METAR modal yet, just present),
   a big accent "Set position" button with sub-line "Moves the aircraft now · sim stays
   paused" (inert — no backend call this phase), "Reset situation" text action (turns to
   `--pos-alert` on hover, dispatches `situationReset`).

All checkboxes and the diagram's circuit markers must have a **≥44px** touch target (CLAUDE.md:
tablet is first-class — "where density and the tablet disagree, the tablet wins"). Use real
`<input type="checkbox">` / `<button>` elements sized/padded to 44px, not the v3's raw 15px
inline div with a manual checkmark — keep the visual (15px box, ✓ glyph) but wrap it in a
44px hit target.

### Derived logic — port these formulas exactly

**Wind components** (`wind.ts`), for a runway of true course `courseDeg`:
```
relative = ((windDeg - courseDeg + 540) % 360) - 180        // -180..180
head  = round(windKt * cos(relative * PI/180))               // positive = headwind
cross = round(abs(windKt * sin(relative * PI/180)))
tail  = head < 0 ? -head : 0
```
Per-runway tab wind text: if `head < 0` → `"{-head} kt tail"` (caution colour); else →
`"{head} kt head"` (dim colour). The Approach-tab compound text is
`(tail ? tail + ' kt tail' : head + ' kt head') + ' · ' + cross + ' kt cross'`.

**Circuit geometry** (`circuit.ts`), constants `K = 40` (px/NM), centre `CX = 360, CY = 252`,
mid-offset `UMID = -3.2` (NM, along-track):
```
rad = courseDeg * PI/180
place(u, v) = {
  dx = v * K, dy = -(u - UMID) * K
  x = CX + dx*cos(rad) - dy*sin(rad)
  y = CY + dx*sin(rad) + dy*cos(rad)
}
```
where `u` = along-track NM (negative = before the threshold, i.e. on approach) and `v` =
cross-track NM (negative = left of centreline). Runway rectangle + threshold bar, extended
centreline with 2 NM tick marks, dashed downwind/base legs are all drawn in the SVG's rotated
`<g transform="rotate({{courseDeg}} 360 252)">` group — draw them unrotated in local
coordinates and let the `<g>` rotation handle the runway orientation, exactly like the source.
Wind arrow rotates by `(windDeg + 180) % 360` around its own anchor (664, 74); the north arrow
is fixed, unrotated, near the bottom-left.

**The 9 circuit markers** (`markers.ts`), `(u, v)` in NM and the label/sub template
(`{dist}` fills from the marker's own distance, `{hdg}` from `courseDeg` zero-padded to 3
digits, `{recip}` doesn't apply here):

| id | label | u | v | sub | note |
|---|---|---|---|---|---|
| `takeoff` | Take off | 0 | 0 | "on threshold · 12 ft" | dist 0.0 NM, alt 12 ft MSL, hdg = course, "Lined up on the runway, brakes set" |
| `downwind-left` | Downwind left | -1 | -4 | "4 NM abeam · 1,500 ft" | dist 4.0 NM abeam, alt 1,500 ft AAL, hdg = (course+180)%360, "Left-hand pattern, 1 NM behind the threshold" |
| `downwind-right` | Downwind right | -1 | 4 | "4 NM abeam · 1,500 ft" | same as left, hdg = (course+180)%360, "Right-hand pattern, 1 NM behind the threshold" |
| `vectors-left` | Vectors left | -6 | -2 | "2 NM offset · 1,800 ft" | dist 6.0 NM final, alt 1,800 ft AAL, hdg = (course+90)%360, "2 NM left of the centerline, intercept heading" |
| `vectors-right` | Vectors right | -6 | 2 | "2 NM offset · 1,800 ft" | hdg = (course+270)%360, "2 NM right of the centerline, intercept heading" |
| `base-left` | Base left | -6 | -4 | "6 NM final · 1,800 ft" | dist 6.0 NM final, alt 1,800 ft AAL, hdg = (course+90)%360, "Turning base from the left" |
| `base-right` | Base right | -6 | 4 | "6 NM final · 1,800 ft" | hdg = (course+270)%360, "Turning base from the right" |
| `final-3nm` | 3 NM final | -3 | 0 | "900 ft · on path" | dist 3.0 NM, alt 900 ft AAL, hdg = course, "Established on the 3° path" |
| `final-8nm` | 8 NM final | -8 | 0 | "2,400 ft · on path" | dist 8.0 NM, alt 2,400 ft AAL, hdg = course, "Established on the 3° path" |

The selected marker gets the accent ring colour + a `0 0 0 5px {accent at 15-17% alpha}` glow
on its dot; all others use the dim colour. Label placement (`labelPlacement`, in
`markers.ts`): compute a unit vector from the marker's screen position; `takeoff` uses
`(cos(rad), sin(rad))`, `final-3nm` uses `(-cos(rad), -sin(rad))`, `vectors-left`/`-right` use
`(-sin(rad), cos(rad))` with the label always centred below; everything else derives its unit
vector from `(point - centre)/|point - centre|`. If `|ux| > 0.6` the label sits beside the dot
(anchored left/right depending on sign of `ux`, vertically centred); otherwise it sits
centred above/below.

**Right rail rows** (`applyRows.ts`) — 7 rows, `{ label, value, colour, tag }`:

| Label | Value | Tag |
|---|---|---|
| Start position | selected stand name, or the active tab's resolved name (marker label / procedure ident / "Overhead LFMN" / "Relative to threshold" or "Coordinates") | `navdata` |
| Altitude | the resolved altitude, or "override" text when the override checkbox is on | `overridden` (caution colour) when override is on, else `computed` |
| Heading | resolved heading | `computed` |
| IAS | `config.iasKt + ' kt'` | `editable` |
| Landing gear | "down"/"up" (caution colour when up) | `editable` |
| Flaps | `config.flapsPercent + ' %'` when `flapsOn`, else "unchanged" (dim) | `editable` |
| Nav radios | `'ILS ' + freq + ' · CRS ' + course` when the runway has ILS and the ILS toggle is on; "not available" (dim) when no ILS; "not sent" when the toggle is off | `from navdata` (dim) or `unavailable` (caution) |

**Checks** (`checks.ts`), evaluated in this exact order, each `{ dot, text, note }`:
1. If `tail >= 3` on the selected runway and no stand selected: caution, "Tailwind {tail} kt on
   {runway}", note names the reciprocal runway as favoured (or a generic "check the wind"
   note if no reciprocal is known, e.g. for Heli).
2. If on the Approach tab, no stand selected, gear is up, and the selected marker is one of
   `final-3nm`/`final-8nm`/`base-left`/`base-right`/`vectors-left`/`vectors-right`: caution,
   "Gear up {marker.dist} from the threshold", note "Tick \"Gear down\" to spawn configured
   for landing".
3. If the ILS toggle is on but the selected runway has no ILS: dim/info, "No ILS on {runway}",
   note "The frequency will be skipped when the position is set".
4. If on the Airwork tab and `config.iasKt < 150`: caution, "{iasKt} kt IAS at {level}", note
   "Below a sustainable speed at that level for most aircraft".
5. If the altitude-override checkbox is on: caution, "Altitude override active", note
   "Replaces the computed {resolved altitude for the current mode}".
6. If a stand is selected: dim/info, "Starting from stand {stand}", note "Circuit and
   procedure positions are ignored while a stand is selected".
7. Always last, always passing: accent colour, "Position inside the LFMN CTR", note "Terrain
   and airspace check passed with sample data".

## Sample data (`sampleData.ts`)

- Airport: `LFMN`, "Nice / Côte d'Azur".
- Runways (`Record<RunwayId, Runway>` — use a `Record` over the finite union, not an array, so
  `noUncheckedIndexedAccess` doesn't force `| undefined` everywhere): `04R` course 40°, ILS
  110.70; `22L` course 220°, no ILS; `04L` course 40°, ILS 110.70; `22R` course 220°, no ILS;
  `HELI` (helipad, no course/ILS). Shared facts for the non-Heli runways: length 9,710 ft,
  surface Asphalt, elevation 12 ft. Heli: type Helipad, elevation 12 ft.
- Wind: 240°, 12 kt. QNH: 1013 hPa.
- Stands (16, `id, type, x, y` in the 340×262 diagram's coordinate space):
  A1–A6 "Gate heavy"/"Gate medium" around (44–164, 104), B1–B5 "Gate medium" around
  (44–140, 176), T1–T4 "Tie-down" around (44–104, 230), M1 "Miscellaneous" at (196, 150) —
  match the exact x/y from the source table below so the diagram matches the mockup:
  ```
  A1 Gate heavy 44,104   A2 Gate heavy 68,104   A3 Gate heavy 92,104
  A4 Gate medium 116,104 A5 Gate medium 140,104 A6 Gate medium 164,104
  B1 Gate medium 44,176  B2 Gate medium 68,176  B3 Gate medium 92,176
  B4 Gate medium 116,176 B5 Gate medium 140,176
  T1 Tie-down 44,230 T2 Tie-down 64,230 T3 Tie-down 84,230 T4 Tie-down 104,230
  M1 Miscellaneous 196,150
  ```
- Procedure idents (8, `ident, via`):
  `BADO8A.04B.BADOD→BADOD`, `BADO8C.04B.BADOD→BADOD`, `BASI8A.04B.BASIP→BASIP`,
  `BODR8A.04B.BODRU→BODRU`, `EPOL8A.04B.EPOLO→EPOLO`, `EPOL8B.04B.EPOLO→EPOLO`,
  `IRMA8A.04B.IRMAR→IRMAR`, `IRMA8C.04B.IRMAR→IRMAR`. Each ident splits on `.` into
  `[procedureShort, transition, waypoint]` for the breadcrumb.
- Airwork levels: FL300/30,000 ft, FL200/20,000 ft, FL100/10,000 ft, FL050/5,000 ft.
- METAR: `LFMN 171730Z 24012KT 9999 FEW035 26/18 Q1013 NOSIG`. Footer: "Navdata X-Plane 12 ·
  AIRAC 2508 · METAR 6 min old".

## Type-strictness notes (read before writing `sampleData.ts` / `markers.ts`)

- `erasableSyntaxOnly` **bans `enum`** — every closed set above must be a `readonly [...] as
  const` array + `(typeof X)[number]` union, exactly like `uiSlice.ts`'s `TAB_IDS`/`TabId`.
- Model lookup tables as `Record<FiniteUnion, T>`, never `Array` + `.find()` or a loosely-typed
  `Record<string, T>` — `noUncheckedIndexedAccess` doesn't add `| undefined` to indexing a
  `Record` by a finite union key, but does to everything else.
- Model an absent ILS as `ils: IlsInfo | null`, never `ils?: IlsInfo` —
  `exactOptionalPropertyTypes` treats "optional" and "present but undefined" as different
  things and this repo standardises on explicit `| null`.
- Build the 2 NM tick marks with `Array.from({ length: n }, (_, i) => …)`, not a `for` loop
  indexing into an array.

## Test plan

Delete the 11 old position tests with their components (`positionSlice.test.ts`,
`gate.test.ts`, `errors.test.ts` survive). Write:

- **`wind.test.ts`** — headwind on the nose, zero cross abeam, pure tailwind at 180° off, wrap
  at 350°/010°; the 5-runway table against sample wind 240/12 must produce the tab strings
  exactly ("7 kt head" for 04R/04L, tailwind for 22L/22R). Head and tail must be mutually
  exclusive.
- **`circuit.test.ts`** — `place(0,0,course)` at the documented centre offset;
  `place(-2,0,course)` and `place(-4,0,course)` are exactly 80px apart (proves the fixed
  `K=40`); a 90° course rotates along-track onto the screen x-axis; tick count/spacing over
  the centreline; wind/north arrow rotation math.
- **`markers.test.ts`** — 9 unique ids, defined `(u,v)` for each; `labelPlacement` picks the
  outboard side for a cross-track-dominant marker and above/below for an along-track-dominant
  one; no two markers collide in screen space for any of the 5 runway courses.
- **`checks.test.ts`** — **highest value suite.** One test per rule firing and one per
  *not* firing, in the order above; assert the full ordered array, not membership (the rail
  renders in order).
- **`applyRows.test.ts`** — the 7 rows in order with exact tags; Altitude flips
  computed→overridden; Nav radios flips from-navdata→unavailable/not-sent.
- **`format.test.ts`** — the 4 lifted formatters keep prior behaviour (port cases from the old
  `placements.test.ts`); new FL/distance/heading formatters incl. zero-padding.
- **`positionDesignSlice.test.ts`** — `startStandSelected` clears `selectedRunway` and vice
  versa; `situationReset()` returns deep-equal to `initialPositionDesignState`;
  `airportLoaded` upper-cases; `designTabSelected` doesn't disturb `selectedMarker`.
- **`PositionPanel.test.tsx`** — full render with `setupStore()`; 4 real tabs, exactly one
  `aria-selected="true"`; clicking a circuit marker updates "Selected start position"; picking
  a stand clears the runway tab's selected state.
- **`PositionHeaderBar.test.tsx`** — opening the screen menu lists all 10 `TABS` labels;
  clicking "Weather" sets `store.getState().ui.activeTab === 'weather'`; the theme toggle
  flips `store.getState().ui.theme`; Load with a changed ICAO sets
  `store.getState().position.selectedIcao`; Load with the **same** ICAO does not re-dispatch
  (no reset of `staged`/overrides — write this as: stage something via a direct dispatch, click
  Load with the same ICAO, assert `staged` is unchanged).
- **`StartAtPopover.test.tsx`** — Escape closes and returns focus to the trigger; parking
  filter narrows the stand list and the "N of M" count follows; a diagram marker and its list
  row select the same stand.
- **`BottomBar.test.tsx`** — ILS-frequency checkbox `disabled` + "n/a" caution text on a
  no-ILS runway, enabled on 04R/04L; every checkbox reachable via `getByLabelText`.
- **`ui/src/App.test.tsx`** (new) — with `activeTab: 'position'`,
  `queryByRole('tablist', { name: 'Instructor station modules' })` is null and the status bar
  is absent; after dispatching `tabSelected('map')` then `tabSelected('position')`, the map's
  `<section id="tabpanel-map">` is **still in the document** with `hidden` (the `keepMounted`
  regression guard). Mock `maplibre-gl` with the existing `ui/src/test/maplibreStub.ts`.

Regression guards — must still pass unmodified: `map/MapPanel.test.tsx`,
`weather/weatherSlice.test.ts`, `fuel-payload/FuelPayloadStagingBar.test.tsx`.

No `skip`/`xfail` anywhere. If something doesn't pass, fix the code or report it — never
weaken a test or the tsconfig to get green.

## Known gaps (accept, don't silently fix, don't silently break further)

- `state.position.staged` stays `null` all through this phase — the "Set position" button is
  inert (no backend call). `profiles/SaveProfileForm.tsx` disables Save unless `staged !==
  null`; saving a profile from Position is temporarily unreachable except via Map → "Send to
  Position tab" (`MapStagingBar.tsx`, untouched). Note this in the PR description.
- The v3 canvas's own Spanish-language "brief" section (why-this-redesign prose, the 8 rule
  cards, "Siguientes pasos") is **not** part of the screen — it's design documentation for the
  author, not application UI. Don't replicate it.
- METAR/wind/QNH/AIRAC are frozen sample values, visibly tagged "sample data" in the rail, per
  the source design's own label.

## Verification

```bash
cd ui && npm install               # picks up the two new font packages
npm run lint && npm run typecheck && npm test && npm run build
```
Python side is untouched — no expected change to `pytest`/`ruff`/`mypy`.

Visual verification: a Lightpanda MCP browser is being set up separately (WSL2) to check this
against the local dev server without spending the Cloudflare remote-browser daily budget. If
it isn't ready yet when this is implemented, leave `npm run dev` running and say so — do not
fall back to the Cloudflare browser without asking (it cannot reach `localhost` from this
machine, confirmed).

## Branch / commit

Already on `feature/position-redesign` (created from `origin/dev`). One or more commits,
Conventional Commits style, e.g. `feat(ui): replicate the Position screen v3 redesign`.
**No AI attribution trailers** (no `Co-Authored-By`, no `Claude-Session`) — contributor
attribution on this repo shows only Santiago. Leave a PR to `dev` ready; do not merge.
