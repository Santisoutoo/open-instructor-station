# Position Manager — approach-type breakdown and a to-scale procedure view

Design for issue [#168](https://github.com/Santisoutoo/open-instructor-station/issues/168).
Extends `position-manager.md` (§ SID/STAR tab) and `position-redesign-v3.md`. Status: **done** —
Part 1 merged as #172, Part 2 as the PR this branch opens. See the note at the end of §4 for
what changed between this design and the shipped code.

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
| D5 | **SVG oblique projection**, no 3D library. | Consistent with `CircuitDiagram`/`AirportDiagram`, testable in jsdom, no bundle growth, theme tokens apply. A dependency only earns its place if free camera orbit is ever asked for. *Superseded for the 3D view by §4.7 — free camera orbit was asked for (issues #175–178); this decision and its reasoning are unchanged for the 2D view, which stays the default.* |
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

### 4.6 What changed between this design and the shipped code

- **The gap this design left open**: `procedure_layout(procedure, airport)` had no way to
  anchor a SID, whose legs never touch a runway fix (confirmed against the `ZZZ1A` fixture —
  `CA → DF ZZALF → RF ZZARC → TF ZZBRA`, no `fix.kind == "runway"` anywhere). Resolved with a
  third `runway: Runway | None = None` parameter and a precedence: a leg's own runway fix wins
  when one exists; else the supplied `Runway`'s `threshold` becomes the origin *outside* the
  node list, walked outward from leg 0; else `last_fix`, unchanged. The server resolves
  `runway_ident` via the already-existing `NavdataProvider.get_runway`, ignoring it whenever
  the procedure resolves its own anchor.
- **`ident` on a `LayoutNode`** falls back through `fix.ident → fix_ref.ident → path_terminator`
  — not just `fix_ref → terminator` as first drafted — matching `SidStarTab.tsx`'s own
  `LegRow` convention (`leg.fix?.ident ?? leg.fix_ref?.ident ?? '—'`) exactly, so an unresolved
  `IF ZZMIS` reads "ZZMIS" in the diagram, not the uninformative "IF".
- **`altitude_source: "runway"` is not hollow.** A runway threshold's elevation is as real as a
  published constraint — only `"interpolated"`/`"unknown"` mean this diagram invented the
  number — `ProcedureDiagram.tsx`'s `isGuessedAltitude` reflects that.
- **Live-verified at LEMD**: `I32LW` (an ILS with a 30 NM enroute segment) drew runway-up with
  the break glyph and true-length label on the compressed segment; `BARD3B/RW14R` (a SID with
  no runway leg of its own) anchored via the supplied `Runway` with no crash; clicking a node
  updated the leg selection and facts row, exactly like the row list.

### 4.7 Amendment — a 3D procedure view was asked for (issues #175–178)

- D5 above chose SVG over a 3D library specifically because "a dependency only earns its place
  if free camera orbit is ever asked for." Free camera orbit has now been asked for.
- `three`, `@react-three/fiber` (**v9** — v8 targets React 18, this repo is on React 19) and
  `@react-three/drei` are added in #175. MapLibre is untouched — it remains the map library for
  the instructor map; the 3D procedure view is an unrelated, separate component.
- Alternatives considered and rejected: MapLibre + deck.gl (the camera stays map-locked, so it
  cannot free-orbit or look from below the horizon), CesiumJS (~3 MB, brings a terrain/imagery
  pipeline this view explicitly doesn't want).
- `ui/src/features/position/procedureScene.ts` (#175) mirrors `procedureProjection.ts`'s pure
  `ProcedureLayout → geometry` structure for 3D scene-space instead of an SVG viewBox, and
  re-exports `VERTICAL_EXAGGERATION` so both views declare the same factor. Unlike the 2D
  module, scene geometry stays in an unrotated, north-aligned world frame — `courseDeg` only
  sets the camera's initial azimuth, not vertex positions, since a free-orbiting camera has no
  auto-fit to rotate for, and a north-aligned ground plane is what a future OSM texture (#178)
  needs to line up with real-world tile coordinates.
- One forward-looking caveat for #178: nodes with `positioned: false` carry nominal, not real,
  coordinates (D10: "a nominal advance... flagged `positioned: false`"), so any OSM
  ground-texture alignment near those legs is inherently approximate — non-blocking today.
- Sequence: #175 (this module + the dependency stack), #176 (`ProcedureDiagram3D.tsx` + the
  2D/3D selector), #177 (visual polish + camera reset), #178 (optional OSM ground texture).

#### 4.7.1 Design — #176: `ProcedureDiagram3D.tsx` + the 2D/3D selector

**Component contract** — identical to the 2D `ProcedureDiagram`, read verbatim from
`ProcedureDiagram.tsx` on `dev`:

```ts
interface ProcedureDiagram3DProps {
  readonly layout: ProcedureLayout;
  readonly courseDeg: number;
  readonly selectedSequence: number | null;
  readonly onSelectLeg: (sequence: number) => void;
}
```

`runway?: Runway` is **not** added here — #177 adds it purely additively.

- `<Canvas>` framed from `scene.cameraPose` (`buildProcedureScene`'s own fit), `<OrbitControls
  makeDefault enableDamping>` with **no `minPolarAngle`/`maxPolarAngle` clamp** — the issue asks
  explicitly for looking from below the horizon.
- Lazy-loaded via a `React.lazy` boundary declared **inside `SidStarTab.tsx`** (not a new entry
  in `ui/src/components/tabs.ts` — that registry lazy-loads the eight top-level app tabs; the
  Position panel is already one of them, so this is a narrower, nested boundary):
  `const ProcedureDiagram3D = lazy(() => import('./ProcedureDiagram3D').then((m) => ({ default:
  m.ProcedureDiagram3D })));`, wrapped in `<Suspense fallback={...}>` only around the 3D branch.
- One node marker per `SceneNode` (`scene.nodes`), one path segment per `SceneSegment`
  (`scene.segments`), rendered from a per-segment `.map`, matching 2D's per-node/per-segment
  loop shape so #177 can drop curtain meshes into the same per-segment iteration later.
- Selection: an invisible hit-sphere mesh per `is_positionable` node (`raycast={() => null}` on
  the visual marker so it never competes with the hit sphere for the click — mirrors 2D's
  transparent 44×44 `<button>` over a purely visual `aria-hidden` dot), `onClick` calling
  `onSelectLeg(node.sequence)`, `onPointerOver`/`onPointerOut` driving local hover state (no
  `onSelectLeg` equivalent for hover — hover is component-internal, same as 2D has no hover
  state at all beyond CSS).

**Semantics parity with the 2D view — in scope for #176 itself** (the issue asks for this
directly; it is not #177's "visual polish," which is runway/ground/billboard-labels/curtain
color+theming/camera-reset — see #177's own issue text). Reuse the exact predicates 2D already
has, duplicated locally in `ProcedureDiagram3D.tsx` rather than cross-imported — the same
precedent `procedureScene.ts` itself sets by duplicating `FEET_PER_NAUTICAL_MILE` rather than
importing a private constant from `procedureProjection.ts`:

```ts
function segmentIsDashed(from: SceneNode, to: SceneNode): boolean {
  return !to.node.positioned || from.node.is_missed_approach || to.node.is_missed_approach;
}

function isGuessedAltitude(node: LayoutNode): boolean {
  return node.altitude_source === 'interpolated' || node.altitude_source === 'unknown';
}
```

- Dashed / de-emphasised segments: `segmentIsDashed(from, to)` selects a distinct material for
  that path line (drei `<Line>` supports `dashed`/`dashSize`/`gapSize` directly — use that
  rather than opacity, so the *meaning* — "not a resolved fix" or "missed approach" — stays
  visually distinct from #177's later curtain de-emphasis, which is a separate, opacity-based
  concern).
- Hollow altitude markers: `isGuessedAltitude(node.node)` swaps the node marker's material —
  e.g. a ring/wireframe sphere vs. a solid one — the 3D equivalent of 2D's
  `pos-procdiagram__node--hollow` CSS class swap. No CSS classes reach into WebGL materials, so
  this is a material/geometry choice made in the component, not a class name.
- Compressed segments visibly marked, with true length in NM (`layout.segments.filter((s) =>
  s.scale === 'compressed')`, identical to 2D's own filter):
  - the segment's line rendered in a distinct style (reuse the dashed mechanism or a third
    color — implementer's call, document the choice),
  - a text callout at the segment midpoint reading `↔ {segment.true_length_nm.toFixed(1)} NM`
    (`segment.true_length_nm`, same field 2D reads), via a drei `<Html>` positioned at the
    midpoint of the segment's two path vertices (`curtain[0]`/`curtain[1]`, averaged). This is
    the **one** place #176 needs `<Html>`-in-3D-space at all — node ident/altitude labels are
    #177's job (its own issue text: "Node ident labels as billboards"), so #176 does not render
    those. Establishing the `<Html>` pattern here for the compressed-segment callout gives #177
    a working precedent to extend for its billboard labels, rather than inventing it from
    scratch.
- Legend: plain HTML text under the canvas (not scene content — no `<Html>`-in-3D needed for
  this one), mirroring 2D's `pos-procdiagram__legend` string: `vertical ×{VERTICAL_EXAGGERATION}
  · not to scale`, class `pos-procdiagram3d__legend`.

**Selector — state.** `positionDesignSlice.ts` (screen chrome, not `positionSlice.ts`'s
server-intent shape, not local `useState` — a tab switch away and back must not lose the
choice). **Exact naming from the issue text** (the field is `diagramMode`, not
`procedureViewMode` — read the issue verbatim before implementing, it is authoritative):

```ts
export const DIAGRAM_MODES = ['2d', '3d'] as const;
export type DiagramMode = (typeof DIAGRAM_MODES)[number];
```

Add to `PositionDesignState`: `diagramMode: DiagramMode;`. Initial value in
`initialPositionDesignState`: `diagramMode: '2d'`.

```ts
diagramModeSelected(state, action: PayloadAction<DiagramMode>) {
  state.diagramMode = action.payload;
},
```

**Survival across resets is a real requirement — it is easy to get wrong by analogy with
other fields that do reset.** The issue states explicitly: *"It is a view preference, not
airport-scoped: it survives `clearAirportScopedState()` and `situationReset()`."*
- `clearAirportScopedState` already wouldn't touch it (it mutates specific fields in place;
  simply never add `diagramMode` to that function's body).
- `situationReset` **does** need an explicit carve-out, the same way it already keeps
  `icaoInput`/`loadedIcao`:
  ```ts
  situationReset(state) {
    return {
      ...initialPositionDesignState,
      icaoInput: state.icaoInput,
      loadedIcao: state.loadedIcao,
      diagramMode: state.diagramMode,
    };
  },
  ```
  Test this explicitly — it is the one place the naive "just spread initial state" pattern
  would silently violate the issue's own requirement.

**Selector — UI.** New `ProcedureViewToggle.tsx` (or inline in `SidStarTab.tsx` if small enough
— implementer's call), two `aria-pressed` buttons ("2D"/"3D"), `role="group"`, dispatching
`diagramModeSelected`. Mounted in `SidStarTab.tsx` directly above the diagram, inside
`.pos-sidstartab__diagram` (same column as the diagram itself, per §4.3's split-view layout, so
it stays reachable without scrolling past the leg list on a narrow viewport).

**Mount site — `SidStarTab.tsx`.** Both modes read `state.positionDesign.diagramMode` and
consume the *same* `layout`/`selection`/`runway`-derived `courseDeg` the 2D branch already
computes — no duplicated data fetching. Clicking a 3D node dispatches the same
`procedureLegSelected` the leg list and the 2D dots already use — bidirectional selection is
free, it is the same Redux action from a third dispatch site.

**Remount-on-toggle is deliberate** (the issue leaves this open, asking to "decide in the PR" —
this design picks remount and states why, so it isn't re-litigated per-PR): switching `2d → 3d
→ 2d` unmounts/remounts `ProcedureDiagram3D`, unlike `App.tsx`'s map panel (which stays mounted
across tab switches specifically to preserve a WebGL context that's expensive to reacquire and
holds live subscriptions). The procedure diagram has neither: `buildProcedureScene` is a pure,
cheap recompute, and remounting means the camera is always re-fit from `scene.cameraPose` on
the way back in — which is the right default and covers most of what a "reset camera" button
would do, ahead of #177 adding one for orbiting-without-leaving-3D.

**Test stub — `ui/src/test/threeStub.ts`.** Mirrors `maplibreStub.ts`'s role (jsdom has no
WebGL), but the mechanism differs: stub `Canvas` to a passthrough that renders `children`
through ordinary `ReactDOM`, **not** stub the r3f JSX intrinsics (`<mesh>`, `<group>`,
`<sphereGeometry>`, `<meshBasicMaterial>`, lights) at all — those are just lowercase tag names,
so once inside the stubbed `Canvas` they render as literal custom elements and their
`onClick`/`onPointerOver`/`onPointerOut` props wire through React's real synthetic-event system
like any other host component. Use a real `Object3D` property (`name`) as the query hook —
`data-testid` on an r3f element gets misinterpreted at real runtime as a nested prop path, so
never use it there even though the stub wouldn't itself object.

```ts
// ui/src/test/threeStub.ts
export const threeFiberStub = {
  Canvas: ({ children }: { children?: ReactNode }) => children,
  useThree: () => ({}),
  useFrame: () => {},
};

export const threeDreiStub = {
  OrbitControls: (props: Record<string, unknown>) => <orbit-controls-stub {...toStubAttrs(props)} />,
  Line: ({ points }: { points: readonly unknown[] }) => <line-stub data-point-count={points.length} />,
  Html: ({ children }: { children?: ReactNode }) => <html-stub>{children}</html-stub>,
};
```

(`toStubAttrs` keeps only primitive props as DOM attributes.) Each test file registers the
mocks itself via `vi.mock('@react-three/fiber', ...)` / `vi.mock('@react-three/drei', ...)` —
per-file, matching how `maplibre-gl` is mocked today, not a global `setup.ts` registration. The
stub is stateless for #176 (no ref registry, nothing to clear in `afterEach`); #177 extends it
with an instance registry (mirroring `maplibreStub`'s `Map.created`) only when it needs an
`OrbitControls` ref for its camera-reset button — not built here.

**Test plan:**
- `ProcedureDiagram3D.test.tsx`: one hit-mesh per `is_positionable` node, none for the others;
  clicking one calls `onSelectLeg` with its `sequence`; `selectedSequence` changes the selected
  node's rendered attributes; a dashed-segment case (`positioned: false` or
  `is_missed_approach: true`) renders the `dashed` line variant, a normal segment doesn't; a
  guessed-altitude node renders the hollow-marker variant; a `scale: 'compressed'` segment
  renders its `<Html>` true-length callout with the right NM text; `OrbitControls` mounts once
  with a `target` attribute present (not asserting its numeric value — that's #175's own,
  already-tested job).
- `ProcedureViewToggle.test.tsx` (or the inline equivalent's own assertions): `aria-pressed`
  matches `mode`, clicking the other button calls the change handler with it.
- `positionDesignSlice.test.ts`: `diagramModeSelected` sets the field; `situationReset`
  **preserves** `diagramMode` (load `'3d'`, reset, assert it is still `'3d'`) — this is the
  test that would catch the naive-reset mistake; a reducer test proving `airportLoaded` /
  `clearAirportScopedState` does not touch it either.
- `SidStarTab.test.tsx` (extend): mock `./ProcedureDiagram3D` to a `data-testid` stand-in (the
  `Suspense` boundary makes the switch asynchronous — use `await screen.findByTestId(...)`, a
  bare `getByTestId` will flake); toggling 2D→3D→2D renders the right branch each time; the
  mocked 3D component receives the same `selectedSequence` a leg-list click would produce.

**Files** — created: `ProcedureDiagram3D.tsx`, `ProcedureDiagram3D.test.tsx`,
`ProcedureViewToggle.tsx` + its test (if split out), `ui/src/test/threeStub.ts`. Modified:
`SidStarTab.tsx` (+ its test), `positionDesignSlice.ts` (+ its test), `position.css` (new
`.pos-procdiagram3d`, `.pos-procdiagram3d__canvas`, `.pos-sidstartab__view-toggle`,
`.pos-procdiagram3d__legend` rules, sized/aspect-ratio'd like `.pos-procdiagram` since a WebGL
canvas has no `viewBox` auto-scaling and an unset height collapses to 0). **Unmodified, stated
so nobody adds a speculative change**: `ui/package.json` (three/r3f/drei already dependencies
since #175), `ui/src/components/tabs.ts` (wrong lazy boundary — see above), `core/` (nothing
here touches sim-agnostic logic; `ProcedureLayout` is unchanged).

**Not parallel with #177** (which extends `ProcedureDiagram3D.tsx` and cannot start until this
merges — confirmed by the already-approved #177 implementation plan, which explicitly blocks on
this component existing). Inside #176 itself, the component+stub track and the
selector+slice+mount-site track touch disjoint files and can proceed in parallel once this
contract is fixed.

#### 4.7.2 Design — #177: runway, ground plane, labels, curtain, theming, camera reset

#176 shipped (PR #189, `ProcedureDiagram3D.tsx`): `ProcedureSceneContent` as the single child of
`<Canvas>`, rendering `SegmentLine` (top-edge `curtain[0]`/`curtain[1]` line, dashed/colored per
segment), `ProcedureNode3D` (visual marker + separate hit-sphere), `CompressedCallout` (drei
`<Html>`), a plain-HTML legend, and an `OrbitControls` `controlsRef` **already lifted out and
named exactly for this purpose** (`useRef<ComponentRef<typeof OrbitControls>>(null)`, comment:
*"Lifted out for #177's camera-reset button"*). Colors are hard-coded constants
(`PATH_COLOR`, `COMPRESSED_COLOR`, `SELECTED_COLOR`) — no theming yet. `courseDeg` is the only
prop threading orientation; `layout`/`selectedSequence`/`onSelectLeg` round out the contract.
This section is grounded in that real, merged code — not the pre-implementation sketch in
§4.7.1 — read `ProcedureDiagram3D.tsx` directly before starting; it is short and the attachment
points are commented in place.

**New prop — purely additive, no existing signature changes:**

```ts
readonly runway?: Runway;   // from '../../api/models' — already fetched in SidStarTab.tsx
                            // via useSelectedRunway() as `runway`, just needs threading through
```

`Runway` (from `ui/src/api/schema.d.ts`, generated — never hand-write this shape): fields used
here are `true_bearing_deg: number`, `length_m: number`, `width_m?: number | null`. Render the
quad only when **both** `runway` is defined and the layout has an `is_runway: true` node
(`LayoutNode.is_runway`) — a STAR anchored `last_fix` has neither.

**1. Runway quad — new pure geometry in `procedureScene.ts`:**

```ts
export function buildRunwayQuad(
  runwayNodePosition: Vec3,
  bearingDeg: number,
  lengthM: number,
  widthM: number,
): readonly [Vec3, Vec3, Vec3, Vec3] {
```

- bearing → direction `(sin θ, 0, -cos θ)` — the same north-aligned x/z convention
  `buildProcedureScene`/`fitCamera` already use; do **not** reuse `procedureProjection.ts`'s
  `rotate()`, which has a deliberate SVG y-negation that would silently invert this.
- metres → NM via `÷ 1852` (not `FEET_PER_NAUTICAL_MILE` — that constant converts feet, the
  runway record is metres).
- anchor at the scene position of the `is_runway` node — found via
  `scene.nodes.find((n) => n.node.is_runway)?.position`, done once in `ProcedureDiagram3D`, not
  inside this pure function (keeps `buildRunwayQuad` a plain geometry function, consistent with
  every other export in this module).
- `widthM` has no guaranteed source (`Runway.width_m` is optional) — pick and document a fixed
  nominal fallback in NM (e.g. `30 / 1852`, roughly a 30 m default pavement width) when absent.
- Unit-test in `procedureScene.test.ts`: a known bearing/length/width produces the four expected
  corners; verify against a cardinal bearing (0°/90°) by hand for a sanity-checkable case.

Render as a flat `<mesh>` with a two-triangle `BufferGeometry` from the quad's four vertices
(`(0,1,2)/(0,2,3)` winding, same convention `SceneSegment.curtain` documents), a neutral
`meshBasicMaterial`, as a sibling of `ProcedureSceneContent` inside `<Canvas>` — not nested
inside it, matching the design's own attachment-point note ("#177 adds `<RunwayMesh>`,
`<GroundPlane>` ... as *siblings*").

**2. Ground plane:** a single flat mesh sized from `scene.extents` (`minX`/`maxX`/`minZ`/`maxZ`),
padded by `FIT_MARGIN_FACTOR` (already exported from `procedureScene.ts`) or a dedicated,
slightly larger margin — implementer's call, document the choice. Neutral `meshBasicMaterial`
color (theming below), no texture (#178's job, explicitly out of scope).

**3. Node ident/altitude labels:** drei `<Billboard>` wrapping `<Html>` (the `<Html>` pattern
`CompressedCallout` already establishes — extend it, don't reinvent), positioned at each
`SceneNode.position`, two-line content `node.ident` / `${Math.round(node.altitude_ft)} ft`
(mirrors 2D's ident+altitude text pair). Hollow/solid altitude-source styling parity already
exists on the node **marker** (`ProcedureNode3D`'s `wireframe={hollow}`, from #176) — the new
label is a separate visual layer, not a re-implementation of that distinction; don't duplicate
`isGuessedAltitude` in a third place, either import it into a shared spot or keep the label
purely textual (ident + altitude number) and let the marker alone carry the hollow/solid cue,
as 2D itself does (2D's text labels aren't styled hollow either — only the dot is).

**4. Curtain fill:** `SceneSegment.curtain` is a full 4-vertex quad (`from.position`,
`to.position`, `to.ground`, `from.ground`) but #176 only draws its top edge
(`curtain[0]`/`curtain[1]`) as `SegmentLine`. Add a translucent filled mesh per segment using
all four vertices (`(0,1,2)/(0,2,3)` triangulation, per the type's own docstring), as a sibling
mesh alongside each `SegmentLine` in `ProcedureSceneContent`'s existing per-segment `.map` (the
named attachment point — extend that loop, don't add a second one). Reuse #176's own
`segmentIsDashed(from, to)` predicate (already defined in `ProcedureDiagram3D.tsx` — import it
if extracted, or keep the duplication local to this file, implementer's call) to lower the
curtain's opacity for unpositioned/missed-approach segments — this is a distinct, opacity-based
de-emphasis layered on top of #176's already-shipped dashed *line*, not a replacement for it.
Accent color: translucent blue (`rgba` or `meshBasicMaterial` with `transparent`/`opacity`),
matching the issue's "translucent blue altitude curtain" ask — a fixed blue constant is fine
even before the theming hook lands; theming (below) is what makes it follow light/dark, not
what makes it blue in the first place.

**5. Theming — `usePosThemePalette()`:** confirmed **zero** existing `getComputedStyle` usage
anywhere in `ui/src` — this is new ground, same as originally scoped. Read
`getComputedStyle(document.documentElement).getPropertyValue('--pos-hair' | '--pos-accent' |
'--pos-caution')` on mount (`position.css`: `--pos-hair` for the ground/hairline,
`--pos-accent` for path/curtain/selected, `--pos-caution` for the compressed-segment marker —
already used by `.pos-procdiagram__*` and now by #176's `PATH_COLOR`/`COMPRESSED_COLOR`/
`SELECTED_COLOR`, which this hook should come to replace). `oklch()` values need conversion to
a format `meshBasicMaterial`'s `color` prop accepts — either render into an offscreen canvas
`2d` context and read back `getImageData` (a real, if unusual, conversion path — no new
dependency), or use `THREE.Color`'s own constructor, which as of three r150+ accepts a CSS
color string directly including `oklch()` in browsers that support it (verify against the
`three` version actually pinned in `package.json`; fall back to the canvas trick if not).
React to a live theme toggle: `position.css` switches on `document.documentElement`'s
`data-theme` attribute, so re-read the tokens via a `MutationObserver` on that attribute,
scoped to the hook's own lifetime (cleaned up on unmount).

**6. Camera reset:** a button, class `pos-procdiagram3d__reset-camera`, calling into
`controlsRef.current` — #176's own `controlsRef` is already exactly what this needs, currently
unused for anything else. Drive it imperatively: `controlsRef.current.target.copy(new
THREE.Vector3(...scene.cameraPose.target))`, `camera.position.copy(...)` (via
`controlsRef.current.object`, drei's ref exposes the camera there), `controlsRef.current
.update()` — not a remount (remounting the whole `<Canvas>` would also discard everything else
mid-orbit, which the issue doesn't ask for; the mode-toggle remount in #176 is a different,
deliberate case for a different reason).

**7. HTML chrome:** every new DOM-visible class follows `pos-procdiagram3d__*`, added to
`position.css` immediately after the existing block (`.pos-procdiagram3d__break`, line ~898 on
this branch) — `.pos-procdiagram3d__reset-camera`, `.pos-procdiagram3d__label` (for the
ident/altitude `<Html>` labels), reusing `--pos-*` tokens directly for any HTML-rendered chrome
(not the theming hook — that's only for materials CSS can't reach).

**Test stub extension.** `ui/src/test/threeStub.ts` needs a `Billboard` stub (mirrors `Html`'s:
render children through the passthrough) and an instance registry for `OrbitControls` so a test
can assert the camera-reset button actually called `target.copy`/`update` on the *same* ref
instance the component holds — mirror `maplibreStub.ts`'s `Map.created` array pattern for this;
add a `resetThreeStub()` and register it in `ui/src/test/setup.ts`'s shared `afterEach`, since
this registry (unlike #176's stateless stub) needs clearing between tests.

**Files** — modified: `procedureScene.ts` (+`.test.ts`, `buildRunwayQuad`), `ProcedureDiagram3D.tsx`
(+`.test.tsx`, all six additions above), `SidStarTab.tsx` (thread `runway={runway}` through — the
value already exists there), `position.css`, `ui/src/test/threeStub.ts` (+`setup.ts`). No new
files required unless the implementer chooses to split `RunwayMesh`/`GroundPlane`/`NodeLabel`
into their own modules for readability — reasonable given `ProcedureDiagram3D.tsx` is about to
roughly double in size.

---

#### 4.7.3 Design — #178: OSM raster ground texture for the 3D view

Optional follow-up to #177 — the 3D view is complete without it (the issue's own words). One
static raster composite of OSM tiles, fetched once per airport/procedure extent, applied as
`GroundPlane`'s texture. No tile pipeline, no streaming, no zoom-dependent reloading. **No
`SimAdapter`/`Capabilities` change, no `core/` change, no `server/` change, no new endpoint,
no schema regeneration** — everything below is `ui/` only, and that is a deliberate outcome,
not an omission: the data needed to georeference the scene already reaches the browser.

**Where the compositing happens — client-side, directly from `tile.openstreetmap.org`.**
Decided, not open. The evidence is in-repo: `useMapLibre.ts`'s `OSM_STYLE` already has *this
browser* fetching `https://tile.openstreetmap.org/{z}/{x}/{y}.png` and uploading the tiles
into a WebGL texture — which only works because the tile server answers with
`Access-Control-Allow-Origin: *`, so the CORS question is settled by the running map panel,
not by recall. Same server, same attribution string, same Referer-based identification —
identical policy posture to what the app already does. A server-side compositor was rejected:
it would add internet-facing `server/` code plus a Python imaging dependency (Pillow) the
backend does not have, it breaks the natural offline story (the *client's* connectivity is
what decides whether the texture can exist), and it forfeits the browser HTTP cache already
warm with the very same tiles from the map panel. The one thing a proxy would buy — a
custom User-Agent — is not required of browser apps, which OSM's tile policy identifies by
Referer, exactly as the MapLibre map is identified today.

**Georeferencing — the gap, and how it closes without a backend change.** The scene frame is
local (NM, north-aligned, origin at the layout anchor) and `ProcedureLayout` carries no
lat/lon — but it does carry `anchor` and the ARP's *drawn* offset `airport_x_nm`/
`airport_y_nm`, and `useAirport()` (already in `usePositionData.ts`) carries the ARP's real
`GeoPosition`. Read `core/procedure_layout.py` before touching this: when `anchor === 'runway'`
the ARP offset is computed as "a short, uncompressed **true** offset" from the origin, so the
origin's lat/lon is recoverable exactly; when `anchor === 'last_fix'` that offset is one
further *capped* segment and the inverse is not trustworthy — **the texture is gated on
`layout.anchor === 'runway'`** and the plain plane renders otherwise. The inverse is
equirectangular (1 NM = 1 arcminute of latitude): `originLat = arpLat − airport_y_nm / 60`,
`originLon = arpLon − airport_x_nm / (60 · cos(originLat))` — the same planar approximation
the layout itself was built with (`_vector` in `core/procedure_layout.py`).

One honest framing, from §4.7's own forward-looking caveat: the texture is geographically
true **everywhere on the plane** — drawn (x, z) maps linearly to real ground. What floats
over the *wrong* ground is any node beyond a `compressed` segment or a `positioned: false`
nominal advance — exactly as those nodes already sit at deliberately wrong drawn positions,
and are already visibly marked (dashed lines, break callouts). Accepted; do not clip or
distort the imagery to chase them.

**1. Pure math — new `ui/src/features/position/groundTexture.ts`** (no DOM, no network —
fully unit-testable in jsdom):

```ts
export interface LatLon { readonly latitude: number; readonly longitude: number; } // degrees
export interface GeoBBox { readonly west: number; readonly south: number;
                           readonly east: number; readonly north: number; } // degrees
export interface TileMosaic {
  readonly zoom: number;
  readonly minTileX: number; readonly maxTileX: number;   // inclusive integer tile range
  readonly minTileY: number; readonly maxTileY: number;
  /** The bbox's exact pixel rect inside the stitched grid (256 px/tile) — the crop that
   *  makes the canvas correspond 1:1 to the ground plane's own footprint. */
  readonly cropX: number; readonly cropY: number;
  readonly cropWidth: number; readonly cropHeight: number;
}

/** Real-world position of drawn (0,0). Null unless layout.anchor === 'runway'. */
export function sceneOrigin(
  layout: Pick<ProcedureLayout, 'anchor' | 'airport_x_nm' | 'airport_y_nm'>,
  arp: LatLon,
): LatLon | null;

/** The lat/lon rectangle under the ground plane's exact footprint (scene z = −north). */
export function footprintBBox(
  footprint: GroundPlaneFootprint,  // from procedureScene.ts, item 2 below
  origin: LatLon,
): GeoBBox;

/** floor(log2(EARTH_CIRCUMFERENCE_M · cos(lat) · TARGET_TILES_ACROSS / spanM)), clamped to
 *  [MIN_ZOOM, MAX_ZOOM], then decremented while the mosaic would exceed MAX_TILES. */
export function pickZoom(bbox: GeoBBox): number;

/** Slippy-map fractional coordinates: x = (lon+180)/360 · 2^z,
 *  y = (1 − asinh(tan lat)/π)/2 · 2^z. */
export function tileX(lonDeg: number, zoom: number): number;
export function tileY(latDeg: number, zoom: number): number;
export function mosaicFor(bbox: GeoBBox, zoom: number): TileMosaic;
export function osmTileUrl(zoom: number, x: number, y: number): string;
/** Primitive string, e.g. "11/1003-1007/770-773" — the cache key AND the effect key. */
export function mosaicCacheKey(mosaic: TileMosaic): string;
```

Constants, in this module: `EARTH_CIRCUMFERENCE_M = 40075016.686`, `TILE_SIZE_PX = 256`,
`TARGET_TILES_ACROSS = 6`, `MIN_ZOOM = 10`, `MAX_ZOOM = 17`, `MAX_TILES = 64` (politeness
cap toward the OSM tile policy — one composite is a burst of at most 64 tile requests, once
per airport per session, comparable to one map-panel pan). Design-time worked examples the
tests pin down (formula-derived, hand-checkable): a 30 NM span at lat 40.5° → z = 11
(≈ 4–5 tiles across, ≤ ~25 total); a 5 NM circuit → z = 14. Reference values for the tile
math: at z = 11, lon 0 → x = 1024.0 and lat 0 → y = 1024.0 exactly; lon −3.56 → tile 1003,
lat 40.5 → tile 771.

Web-Mercator-vs-ENU linearity: the plane is linear in metres, the canvas in Mercator Y;
across a ~0.5° latitude span at mid-latitudes the N–S scale drifts ~0.7% — a few pixels at
the plane's edge. The tiles are *context*, not data (`AirportDiagram.tsx`'s own stance);
per-row resampling is rejected.

**2. Shared footprint — `procedureScene.ts` gains one pure function, and
`ProcedureDiagram3D.tsx` loses two constants.** The texture bbox and the rendered plane must
provably share one footprint, so `GROUND_MARGIN_FACTOR` (1.6) and `MIN_GROUND_SPAN_NM` (1)
**move** from `ProcedureDiagram3D.tsx` into `procedureScene.ts`:

```ts
export interface GroundPlaneFootprint {
  readonly centerX: number; readonly centerZ: number;   // NM, scene frame
  readonly widthNm: number; readonly depthNm: number;
}
export function groundPlaneFootprint(extents: SceneExtents): GroundPlaneFootprint;
```

`GroundPlane` consumes it for `planeGeometry`; `footprintBBox` consumes it for the fetch.

**3. The hook — new `ui/src/features/position/useGroundTexture.ts`:**

```ts
export type GroundTextureStatus = 'unavailable' | 'loading' | 'ready' | 'error';
export type CompositeLoader = (mosaic: TileMosaic) => Promise<HTMLCanvasElement>;

export function useGroundTexture(
  origin: LatLon | null,            // null → 'unavailable', nothing is ever fetched
  extents: SceneExtents,
  loadComposite?: CompositeLoader,  // defaults to loadOsmComposite; the test seam
): { readonly texture: CanvasTexture | null; readonly status: GroundTextureStatus };
```

- **The injectable seam is the whole fetch-and-stitch**, `loadOsmComposite(mosaic)`: for each
  tile in the range, `new Image()` with **`crossOrigin = 'anonymous'`** — mandatory, an
  un-CORS'd image taints the canvas and the WebGL texture upload then throws a
  `SecurityError`, which is a much worse failure than a missing texture — a per-tile
  timeout (10 s), `navigator.onLine === false` as an immediate reject (the cheap offline
  path), `Promise.all` all-or-nothing, then one `<canvas>` sized
  `cropWidth × cropHeight`, each tile drawn at
  `(x·256 − mosaicOriginPx − cropX, y·256 − … − cropY)` so the canvas corresponds exactly
  to the bbox. This function is *not executable in jsdom* (images never load;
  `getContext('2d')` returns `null` — `usePosThemePalette`'s docstring already records
  that), which is exactly why it is the injection point: everything above it is testable,
  and the function itself is covered by the pure tile math plus the mandatory live check.
- **Effects key on `mosaicCacheKey(...)` — a primitive — never on object identity.**
  `buildProcedureScene` runs unmemoized every render, so `extents` is a fresh object each
  time; keying on it would refire per render. (The cache would make refires harmless
  anyway; the string key makes them not happen. Do not "fix" this with a deep-compare.)
- **Cache**: module-level `Map<string, Promise<HTMLCanvasElement>>` keyed by
  `mosaicCacheKey`. One in-flight promise dedupes concurrent mounts; the canvas survives
  2D↔3D remounts and procedure switches for the whole session — "fetched once per
  airport/procedure extent". A **rejected promise is evicted on rejection**, so a later
  remount retries (connectivity may have returned). Unbounded across airports is accepted:
  a session touches a handful of airports, each composite a few MB of canvas. Persisting
  across sessions (disk/localStorage) is rejected as complexity without an ask — the
  browser HTTP cache already keeps the underlying tiles warm.
- The `CanvasTexture` is created per hook instance from the shared canvas (cheap), with
  `colorSpace = SRGBColorSpace` (three r150+ does not assume it for canvas textures), and
  disposed on unmount. `flipY` stays at its default `true`: canvas row 0 is north, and after
  `GroundPlane`'s `rotation={[-Math.PI/2, 0, 0]}` the plane's +v edge faces scene north
  (−z), so the default orientation is the aligned one — verified in the live check, where a
  coastline airport makes any flip/mirror unmissable.

**4. Component wiring — `ProcedureDiagram3D.tsx`.** New prop, mirroring #177's `runway`
verbatim (including the `exactOptionalPropertyTypes` note — `?: GeoPosition | undefined`,
threaded as `?? undefined`):

```ts
readonly airportPosition?: GeoPosition | undefined;  // ARP; from useAirport() in SidStarTab
```

`origin = airportPosition === undefined ? null : sceneOrigin(layout, airportPosition)`, the
hook runs beside `usePosThemePalette`, and `GroundPlane` gains
`texture?: CanvasTexture | null`: when set, `<meshBasicMaterial map={texture}
color="#ffffff" side={DoubleSide} />` and mesh name `procdiagram3d-ground--textured` (the
name-carries-state convention #176 set); when `null`, exactly today's neutral
`palette.hair` plane — **that plain plane is the fallback for all of `'unavailable'`,
`'loading'` and `'error'`**, so offline, mid-fetch and failed all render identically and
nothing ever throws into the canvas. If the live check shows the full-brightness map
glaring in the dark theme, a fixed dim multiplier on `color` is the implementer's visual
call — document it next to `RUNWAY_COLOR`'s own reasoning. `RunwayMesh`'s existing
`polygonOffset` already keeps the pavement above the (now textured) coplanar ground.

**5. Attribution — required whenever the texture is shown.** In the HTML chrome (not
`<Html>`-in-scene), rendered **only when `status === 'ready'`**, overlaid bottom-right of
the canvas, new class in `position.css` following #177's naming:

```tsx
<a className="pos-procdiagram3d__attribution"
   href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
  © OpenStreetMap contributors
</a>
```

The text matches `useMapLibre.ts`'s own attribution string character-for-character, and
links to the copyright page as OSM's attribution guidelines ask where the medium supports
links. When the plain plane renders, no OSM pixels are on screen and the credit is
correctly absent.

**Files** — created: `groundTexture.ts` (+ `.test.ts`), `useGroundTexture.ts`
(+ `.test.ts`). Modified: `procedureScene.ts` (+ `.test.ts`; `groundPlaneFootprint`, the two
moved constants), `ProcedureDiagram3D.tsx` (+ `.test.tsx`; new prop, textured `GroundPlane`,
attribution, `GROUND_MARGIN_FACTOR`/`MIN_GROUND_SPAN_NM` **deleted** here),
`SidStarTab.tsx` (+ `.test.tsx`; thread `airportPosition={airport?.position}` from the
`useAirport()` it can already call), `position.css` (`.pos-procdiagram3d__attribution`).
**Unmodified, stated so nobody adds a speculative change**: `core/`, `server/`,
`adapters/`, everything under `tests/` (no pytest surface at all, nothing
`@pytest.mark.sim`), `useMapLibre.ts`, `ui/src/test/threeStub.ts` (component tests mock
`./useGroundTexture` at its module boundary — no new drei/fiber surface to stub),
`ui/src/api/schema.d.ts` (nothing regenerates).

**Test plan:**
- `groundTexture.test.ts` (pure, reference values above): `sceneOrigin` — ARP (40.5, −3.5)
  with `airport_x_nm = 1.2`, `airport_y_nm = 0.9` → origin (40.485, ≈ −3.52630); `null` for
  `anchor === 'last_fix'`. Tile math — the z = 11 values above, `osmTileUrl` exact string,
  `mosaicFor` crop offsets (fractional edge · 256), `mosaicCacheKey` stability. `pickZoom` —
  the two worked examples, both clamps, and the `MAX_TILES` decrement. `footprintBBox` —
  north edge = smaller scene z (z = −north), spans match `groundPlaneFootprint`'s.
- `procedureScene.test.ts`: `groundPlaneFootprint` — margin factor applied, `MIN_GROUND_SPAN_NM`
  floor on a single-node layout.
- `useGroundTexture.test.ts` (injected fake `CompositeLoader`, resolving to a stub canvas
  object): `'ready'` with a `CanvasTexture` wrapping that canvas; two mounts with the same
  key call the loader **once** (module cache); a rejecting loader → `'error'` and the entry
  is evicted, so a remount calls the loader again; `origin === null` → `'unavailable'` and
  the loader is never called; unmount disposes the texture.
- `ProcedureDiagram3D.test.tsx` (`vi.mock('./useGroundTexture')`): `'ready'` → mesh named
  `procdiagram3d-ground--textured` and the attribution link with exact text and href;
  `'error'`/`'unavailable'` → today's plain ground name and **no** attribution element.
- `SidStarTab.test.tsx`: the mocked 3D component receives the loaded airport's `position`.
- Live check (§5's cloudflare-browser pass): a coastline airport's approach (orientation
  errors are unmissable against a shoreline), both themes, then DevTools-offline + reload →
  plain plane, no attribution, console clean.

**Out of scope** (the issue's own list, plus this design's): elevation/terrain meshes;
streaming or zoom-dependent tile loading; satellite imagery from non-open providers; a
texture for `anchor === 'last_fix'` layouts; cross-session composite persistence; Mercator
resampling.

**Parallelisation:** sequential after #177 (this extends `ProcedureDiagram3D.tsx`; same rule
that ordered #176 → #177). Inside #178, once this contract is fixed, the pure-math track
(`groundTexture.ts`, `procedureScene.ts`) and the component track (`useGroundTexture.ts`,
`ProcedureDiagram3D.tsx`, `SidStarTab.tsx`, CSS) touch disjoint files and can proceed in
parallel, with the tester writing both test files against the signatures above.

**Risks:** OSM tile policy tolerates this one-burst usage at the map panel's own scale, but
a classroom of tablets hammering one airport is the same multiplier the map already has —
if that ever becomes real, a caching proxy in `server/` is the escape hatch, not a client
change. `AirportSummary.position` and the `airport.position` the server built the layout
from come from the same navdata row, but they travel different queries — if they ever
diverge (a navdata refresh between calls), the texture shifts by the divergence; accepted,
same staleness class as every other paired query in this panel.

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
