# Position Manager — approach-type breakdown and a to-scale procedure view

Design for issue [#168](https://github.com/Santisoutoo/open-instructor-station/issues/168).
Extends `position-manager.md` (§ SID/STAR tab) and `position-redesign-v3.md`. Status: **proposed**.

---

## 0. Prerequisite — the branch is stale

`Santisoutoo/feat-position-approach-type-breakdown-ils-rnp-vo` was cut from old `main`
(`fa60418`) and is **217 commits behind `origin/dev`**. Every file this design names
(`SidStarTab.tsx`, `positionDesignSlice.ts`, `usePositionData.ts`, `CircuitDiagram.tsx`,
`circuit.ts`, `core/navdata/models.py::ApproachType`) exists only on `dev`. The branch's single
own commit is old `main`'s merge of `dev` — zero unique work, nothing to keep — so the fix is:

```
git reset --hard origin/dev      # run from the worktree; keeps this untracked doc
```

(The reset was refused by the agent's permission classifier; it needs to be run by hand.)

---

## 1. Context

The SID/STAR tab lists approaches under two chips, *Approach transition* and *Final approach*,
split only on whether the procedure has a named transition. An instructor who wants "the ILS to
32L" has to scan every ident (`I32L`, `R32L`, `D32L`, `V32L`…) and decode the ARINC leading
letter themself. And the leg list is a table: nothing shows how long the enroute part is
versus how short and steep the final is.

**What already exists (verified on `origin/dev`):**

- The server **already classifies approaches**. `core/navdata/models.py:296` defines
  `ApproachType = Literal["ils","loc","rnav","gps","vor","vor_dme","ndb","ndb_dme","lda","sdf",
  "gls","mls","igs","unknown"]`; `core/navdata/xplane_native/cifp.py:121` maps ARINC route-type
  letters onto it (`I→ils`, `R/F/H→rnav`, `P→gps`, `V/S→vor`, `D→vor_dme`, `N→ndb`, `Q→ndb_dme`,
  `L/B→loc`, …); `ProcedureSummary.approach_type` and `Procedure.approach_type` carry it and
  `ui/src/api/schema.d.ts` on `dev` already contains it. **Part 1 is UI-only.**
- Every leg carries `fix: Waypoint | None` (with `position: GeoPosition`), `altitude:
  AltitudeConstraint` (`min_ft`/`max_ft`/`suggested_ft`), `outbound_course_mag_deg`,
  `distance_nm`, `is_positionable`, and the `is_missed_approach_*` flags — enough to lay a
  procedure out laterally and vertically without parsing anything new.
- `core/geodesy.py:624 distance_and_bearing(a, b)` (geographiclib inverse) is the only geodesy
  a layout needs. `Airport.position` / `Airport.elevation_ft` (`models.py:107`) is the anchor.
- The diagram pattern to follow is `ui/src/features/position/CircuitDiagram.tsx` +
  `circuit.ts` + `markers.ts`: pure props → SVG, geometry in a tested `.ts` module, 44 px
  transparent `<button>`s positioned in percentages over the SVG dots. `ui/package.json`
  has **no 3D library**; MapLibre is the map only.

**Outcome:** an instructor picks *Final approach → ILS* and sees only the ILS idents; picking one
draws the whole procedure from the first fix to the runway, in an oblique 3D projection whose
distances and altitudes are proportional to the real ones, and any leg that had to be
compressed to fit is visibly marked as such.

---

## 2. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | **Two PRs**: Part 1 (filter, UI-only) and Part 2 (layout + endpoint + diagram). | Independent; Part 1 ships in a day, Part 2 is contract-first and parallelises backend ∥ UI. |
| D2 | Approach type is a **sub-filter that appears under the two approach chips**, not a fifth top-level chip and not a rewrite of `ProcedureFamily`. | A transition to an ILS is still an ILS; the family split (transition vs common route) stays meaningful. `PROCEDURE_FAMILIES` and `procedureKindOf` are untouched. |
| D3 | The type filter is **client-side**, and its chips are **derived from the data** (only types the airport publishes appear, plus *All*). | Unlike `ParkingList`'s server `kind` param, the chip row itself needs the unfiltered list; an airport with only RNAV must not offer an empty ILS chip. No server change. |
| D4 | The 3D view is an **expansion of the SID/STAR tab**, drawn above the leg list, like `CircuitDiagram` sits above the finals in `ApproachTrainingTab`. | Clicking a node selects the leg (`procedureLegSelected`) — same interaction as the marker dots. A separate tab would split "pick a leg" across two places. |
| D5 | **SVG oblique projection**, no 3D library. | Consistent with `CircuitDiagram`/`AirportDiagram`, testable in jsdom, no bundle growth, theme tokens apply. A dependency only earns its place if free camera orbit is ever asked for. |
| D6 | **Layout math lives in `core/`** (`core/procedure_layout.py`), served by one new endpoint; the UI only projects and draws. | Sim-agnostic, pytest-covered without a browser, follows `core/camera/geometry.py`. Compression decisions are policy, and policy belongs where it can be unit-tested. |
| D7 | Lateral layout is a **chain walk**: each segment keeps its **true bearing** but gets a **capped drawn length**; the chain is anchored at the runway (approach/SID) or at the last fix with the airport drawn at its true bearing (STAR). | Keeps every turn's real geometry; compression only ever shortens a straight run. Anchoring at the runway keeps the "from the airport" framing the issue asks for. |
| D8 | A segment is compressed when longer than `LONG_FACTOR × median(segment lengths)` (`LONG_FACTOR = 3`), drawn at that cap, and flagged `scale: "compressed"` with its true length. Nothing is ever stretched or clipped. | Median is robust to one 40 NM enroute transition. Short legs are not a scale problem — they are a label-fit problem the UI solves with a minimum pixel length **and the same break glyph** so a stretched leg is marked too. |
| D9 | Vertical scale is **uniform exaggeration**, factor printed in the legend (`VERTICAL_EXAGGERATION = 5`). | At 1:1 a 7 000 ft descent over 20 NM is 1.15 NM tall — a flat line. Proportional-to-each-other altitudes with a declared factor is the honest reading of "to scale". |
| D10 | Legs **without a resolved fix** (CA/VA/FM/VM…) are laid out by advancing a nominal `NOMINAL_LEG_NM = 2` along the leg's `outbound_course` (else the previous bearing) and flagged `positioned: false`; drawn dashed, unclickable. Legs **with a fix but not positionable** (HM holds) get their real position and are drawn but unclickable. | Discriminator is `leg.fix is not None`, not `is_positionable` — the ZZZZ fixture's `I32L` has both cases. Continuity without pretending a coordinate exists. |
| D11 | Missed-approach legs (`is_missed_approach_leg`) are drawn as a **de-emphasised dashed continuation past the MAP** and never move the runway anchor. | They are part of the chart; they are not part of "first fix to touchdown". |
| D12 | Altitude of a node: `altitude.suggested_ft`; runway-threshold fixes use the threshold/airport elevation; nodes with neither are **linearly interpolated between the nearest known neighbours** and flagged `altitude_source: "interpolated"`; if none is known the profile is drawn flat at airport elevation with `"unknown"`. | The vertical picture must not silently invent a 3° slope. The flag lets the UI hollow the node. |

Follow-up, **not in scope**: filter approaches by the selected runway via `runway_idents`
("the ILS to *this runway*"). Cheap once Part 1 exists; file it as its own issue.

---

## 3. Part 1 — approach-type filter (UI only)

### 3.1 Types

`ui/src/api/models.ts`: add
```ts
export type ApproachType = NonNullable<ProcedureSummary['approach_type']>;
```
(No hand-written API types; no schema regen — `approach_type` is already in `schema.d.ts`.)

### 3.2 State — `positionDesignSlice.ts`

- `approachType: ApproachType | 'all'` (initial `'all'`) next to `procedureFamily`.
- New reducer `approachTypeSelected(state, action: PayloadAction<ApproachType | 'all'>)`:
  sets it and clears `state.procedure` (the selected ident may no longer be listed).
- `procedureFamilySelected` and the airport-change reducer also reset `approachType` to `'all'`.

### 3.3 Matching — `usePositionData.ts`

Add beside `procedureFamilyMatches`:
```ts
export function approachTypeMatches(
  family: ProcedureFamily, wanted: ApproachType | 'all', actual: ApproachType | null | undefined,
): boolean  // true for sid/star always; true when wanted === 'all'; else wanted === (actual ?? 'unknown')
export function approachTypesIn(summaries: readonly ProcedureSummary[]): readonly ApproachType[]
  // distinct, in APPROACH_TYPE_ORDER order, null → 'unknown'
```
`APPROACH_TYPE_ORDER`/`APPROACH_TYPE_LABEL` (`Record<ApproachType, string>` — compile-time
exhaustive, the `EVERY_KIND` trick from `ParkingList.test.tsx`): ILS, LOC, RNAV/RNP, GPS, VOR,
VOR/DME, NDB, NDB/DME, LDA, SDF, GLS, MLS, IGS, Other.

**Transitions inherit their common route's type** (`commonApproachTypes`, decided during
implementation): ARINC 424 gives a named approach transition its own route type (`A`), so the
provider honestly publishes `"unknown"` for every one of them — measured at LEMD, all 49
transitions were `unknown` while the 24 common routes carried `ils`/`loc`/`rnav`/`vor_dme`.
The filter therefore resolves a transition's type by looking up the common route with the same
ident; a summary's own real type always wins, and `"unknown"` remains only for approaches whose
common route is unclassified too. Client-side on purpose — the honest server-side fix (propagate
in the CIFP parser) can replace it later without changing the UI contract.

### 3.4 UI — `SidStarTab.tsx`

- Under `.pos-sidstartab__kind`, when `family` is `apptr` or `final` **and**
  `approachTypesIn(procedures).length > 1`, render a second `role="radiogroup"`
  (`aria-label="Approach type"`, class `pos-sidstartab__type`) of `pos-chip`s: *All* + one per
  type present, each showing its count. Same markup as the family row.
- `matching` becomes `procedures.filter(p => procedureFamilyMatches(...) && approachTypeMatches(...))`.
- Each ident option in the popover gets a small `pos-sidstartab__ident-type` badge
  (`APPROACH_TYPE_LABEL`) for approaches; the breadcrumb/facts add an *Approach type* `FactRow`
  when `procedure.approach_type` is set.
- Empty state text distinguishes "no procedure of this type" from "no {ILS} at this airport".

### 3.5 CSS — `position.css`

`.pos-sidstartab__type` (same flex-wrap as `__kind`, `gap .35rem`, slightly smaller chips),
`.pos-sidstartab__ident-type` (mono, `--pos-t3`, uppercase). Tokens only; no new colours.

### 3.6 Tests

- `positionDesignSlice.test.ts`: `approachTypeSelected` clears the procedure; family change and
  airport change reset the type.
- `usePositionData.test.ts` (or new `procedureFilters.test.ts`): `approachTypeMatches` truth
  table; `approachTypesIn` dedupes, orders, maps `null → unknown`.
- **New `SidStarTab.test.tsx`** (none exists on `dev`; scaffold from `StartAtPopover.test.tsx`:
  `setupStore(initialPositionDesignState)`, `stubApi(positionRoutes())`, `testFixtures.ts`):
  no type row on SID; type row appears on Final with only the published types; picking *ILS*
  lists `I32L` and not `R32L`; picking a type clears the open procedure; option badge text.
  Extend `testFixtures.ts` procedure summaries with `approach_type` values covering ≥ 3 types
  and one `null`.

---

## 4. Part 2 — to-scale procedure view

### 4.1 Contract (fixed first; everything else parallelises against it)

`core/navdata/models.py` (or `core/procedure_layout.py`, re-exported from `core.navdata.models`
for the OpenAPI schema):

```python
LayoutScale = Literal["to_scale", "compressed"]
AltitudeSource = Literal["published", "runway", "interpolated", "unknown"]


class LayoutNode(BaseModel):
    sequence: int
    ident: str  # fix ident, or the terminator ("CA") when there is no fix
    x_nm: float  # east of the anchor, drawn (post-compression) frame
    y_nm: float  # north of the anchor
    altitude_ft: float
    altitude_source: AltitudeSource
    positioned: bool  # False for fix-less legs (D10)
    is_positionable: bool  # clickable
    is_missed_approach: bool
    is_runway: bool


class LayoutSegment(BaseModel):
    from_sequence: int
    to_sequence: int
    true_length_nm: float
    drawn_length_nm: float
    scale: LayoutScale
    bearing_deg: float  # true


class ProcedureLayout(BaseModel):
    airport_icao: str
    kind: ProcedureKind
    ident: str
    transition: str | None
    approach_type: ApproachType | None
    anchor: Literal["runway", "last_fix"]
    airport_x_nm: float
    airport_y_nm: float
    airport_elevation_ft: float  # (0,0) unless STAR
    nodes: tuple[LayoutNode, ...]
    segments: tuple[LayoutSegment, ...]
    total_true_length_nm: float
    compressed_segment_count: int
    long_factor: float = 3.0
    nominal_leg_nm: float = 2.0
```

Endpoint, `server/navdata_routes.py`, beside `get_procedure` (`:238`):

```
GET /api/navdata/airports/{icao}/procedures/{kind}/{ident}/layout?transition=
  → ProcedureLayout   (404 via _found, same message shape as get_procedure)
```

Pure: `procedure_layout(procedure: Procedure, airport: Airport) -> ProcedureLayout`.

### 4.2 Core algorithm — `core/procedure_layout.py`

1. **Nodes in true space.** For each leg with `fix`: `(d, brg) = distance_and_bearing(airport.position, fix.position)`; `x = d·sin(brg)`, `y = d·cos(brg)` (azimuthal-equidistant about the ARP — exact in range, direction-true, good to < 0.1 % inside 100 NM). Altitude per D12.
2. **Segments in true space** between consecutive fixed nodes: `distance_and_bearing(fix_i, fix_j)`.
3. **Compression.** `median` of true lengths; `cap = LONG_FACTOR × median`; `drawn = min(true, cap)`; `scale = "compressed"` iff clamped. With < 3 segments nothing is compressed.
4. **Fix-less legs** (D10) are inserted where they sit in sequence with `drawn = NOMINAL_LEG_NM`, `true_length = leg.distance_nm or 0`, bearing = `outbound_course_mag_deg` converted with `true_from_magnetic` (`geodesy.py:949`) when the fix's variation is known, else the previous segment's bearing.
5. **Chain walk** from the anchor. The anchor is a point at `(0,0)` that is **not necessarily a leg**:
   - **Approach with a runway-threshold fix** (`I32L`'s `TF RW32L`): `anchor = "runway"`; walk
     **backwards** from that node so the runway is `(0,0)`.
   - **Approach without one** (a circling `VDM-A` ends at a fix or a fix-less leg):
     `anchor = "last_fix"`; walk forwards from the first fixed node and place the airport
     symbol at its true bearing from the last fixed node, `drawn = min(true, cap)`.
   - **SID**: legs never contain the runway — the ZZZZ fixture's `ZZ1A` starts with a fix-less
     `CA`. `anchor = "runway"` is the **departure threshold** (the selected runway when it is in
     `runway_idents`, else the ARP) at `(0,0)` *outside* the node list; the first leg advances
     from it (a fix-less first leg by `NOMINAL_LEG_NM` along its course, a fixed one by its
     true distance, capped).
   - **STAR**: `anchor = "last_fix"`, handled exactly like the circling approach.
6. Missed-approach legs (D11) continue the chain past the runway; they are walked forwards and never re-anchor.

Invariants asserted in tests: the runway node is at the origin for approaches that carry one,
and the chain starts at the origin for SIDs; `drawn_length ≤ true_length` for every segment;
segment bearings equal the true ones; the number of nodes equals the number of legs; sequence
order is preserved.

### 4.3 UI — `ui/src/features/position/`

- `procedureProjection.ts` (pure, tested): `project(x_nm, y_nm, alt_ft, view) → {x, y}` with an
  oblique view (`rotation = runway course` so the runway points up, `pitch` flattening `y` by
  0.5, `VERTICAL_EXAGGERATION = 5`, feet→NM via 6076.12), an **auto-fit** to a fixed
  `viewBox` (unlike `circuit.ts`'s fixed `K` — a SID can be 60 NM and an approach 12), and
  `breakGlyph(p, q)` returning the zig-zag path for a marked segment.
- `ProcedureDiagram.tsx` (pure props → SVG, `aria-label` names procedure and legend). Layers:
  ground footprint polyline at airport elevation (`--pos-t3`), vertical drop lines per node
  (`--pos-hair`), the 3D path (`--pos-accent`, dashed for `positioned:false` and missed
  approach), break glyph + `↔ 42 NM` label on compressed segments and on segments the fit
  stretched below `MIN_DRAWN_PX`, node dots (hollow when `altitude_source ≠ published`),
  ident + altitude labels, runway symbol at the anchor, north arrow, legend
  ("vertical ×5 · ⌇ not to scale"). Positionable nodes get the 44 px transparent
  `<button>` in container percentages, exactly the `CircuitDiagram` pattern, calling
  `onSelectLeg(sequence)`; the selected one gets the ring.
- `instructorApi.ts`: `getProcedureLayout` query mirroring `getProcedure`'s args.
- `SidStarTab.tsx`: render `<ProcedureDiagram>` above `ProcedureBody` when a procedure is
  selected; its click dispatches `procedureLegSelected` (same reducer the leg rows use).
- `position.css`: `.pos-procdiagram` mirrors `.pos-circuit` (`:621`) — `width: 720px;
  max-width: 100%; position: relative`, tokens only.

### 4.4 Tests

- `tests/core/test_procedure_layout.py` against the ZZZZ fixture (`I32L` common route:
  IF ZZMIS → CF ZZFAF → TF RW32L → CA → HM covers published/runway altitude, a fix-less leg,
  a hold with a fix, and missed approach) plus synthetic `Procedure`s: compression on a
  40 NM/3 NM/3 NM chain, no compression with 2 segments, STAR anchoring, a circling approach
  with no runway fix (`anchor = "last_fix"`), the SID `ZZ1A` starting from the threshold with
  its fix-less `CA`, interpolation, the invariants above.
- `tests/server/test_navdata_routes.py`: 200 shape, 404 for an unknown ident/transition, the
  `transition` param pinned by name (as `get_procedure`'s is).
- `procedureProjection.test.ts`: fit keeps every point inside the viewBox; exaggeration
  factor; break glyph only for marked segments.
- `ProcedureDiagram.test.tsx`: one button per positionable node and none for the others;
  compressed segment renders the glyph and true-length label; selected node has
  `aria-pressed`; dashed class on fix-less and missed-approach segments.
- `SidStarTab.test.tsx`: the diagram appears once a procedure is open and clicking a node
  selects that leg (the facts row updates).

### 4.5 Implementation steps and parallelisation

```
step 0  reset the branch onto origin/dev (§0)                                   — user
PR 1    Part 1 (§3): one implementer, one tester (SidStarTab.test.tsx)          — parallel
PR 2    a. contract: models + empty endpoint returning the model (fixes OpenAPI)  — first, alone
        b. core/procedure_layout.py + tests/core     ┐
        c. procedureProjection.ts + ProcedureDiagram  ├ three agents, disjoint dirs, launched
           against a hand-written ProcedureLayout    │ in one message after (a)
        d. server route + tests/server               ┘
        e. start the backend, `cd ui && npm run generate:api` (hits :8000 live),
           wire getProcedureLayout + SidStarTab, run everything
```

---

## 5. Verification

- `ruff check . && ruff format --check . && mypy . && pytest` — core layout tests pass
  against the fixture; `tests/core/navdata/test_core_boundaries.py` still passes (nothing in
  `core/` imports the server or an adapter).
- `cd ui && npm run lint && npm run typecheck && npm test && npm run build`.
- Live UI pass (per global CLAUDE.md, `cloudflare-browser` over a `cloudflared` tunnel,
  `/ui-fake`): load an airport with several approach types, confirm the type row appears
  only on the approach chips and lists only published types; open an ILS, confirm the diagram
  draws runway-up, the long transition carries the break glyph and its true length, the
  final is visibly steeper, and clicking a node updates the facts row. Screenshot + console
  clean, then `close_page`.
- CI must be green (`lint-py`, `test-py`, `lint-ui`, `test-ui`) on each PR before merge to `dev`.
