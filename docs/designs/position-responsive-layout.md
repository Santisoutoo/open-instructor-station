# Position panel — responsive tab layout and apply-rail width

**Issues:** [#202] (tab content does not scale with the viewport — dead space against the apply rail), [#203] (fixed 480 px apply rail; width left as a design decision).
**Scope:** `ui/` only. Verified against `origin/dev` @ `91aa9cc`; all file:line references below are to that commit.

**Amendment (post-live-verification, same day):** live-tested on 2026-09-01 and found correct
per this document (diagram capped at 48rem, leg list absorbing surplus — see the memory record
`issues-202-203-position-responsive-layout` for the verification data). The user then asked for
the opposite distribution: the diagram (the "representation") should be the one that grows into
the surplus width, and the leg list should stay compact, with the two blocks centered on each
other's cross axis. §3, §4.1 and §6's SID & STAR rows below are superseded by this: the split's
`grid-template-columns` swaps which track is `1fr` — `minmax(24rem, 1fr) minmax(20rem, 32rem)`
(diagram flexible, leg list capped at 32rem instead of the diagram capping at 48rem) — and
`align-items` changes from `start` to `center`. The underlying grid mechanics (CSS Grid
maximizes every non-flexible track before handing surplus to a flexible one — see the code
comment on `.pos-sidstartab__split`) are unchanged; only which track carries `1fr` and which
carries the fixed cap flipped. The 24rem legibility floor on the diagram and the container-query
breakpoint (52rem) are unchanged.

## 1. Scope

Make the Position manager's four tab bodies (SID & STAR, Approach Training, Airwork, Custom Location) and the apply rail grow **and** shrink with the viewport, so there is no dead gap between the tab content and the rail on wide screens, and no cramping on a 1280×800 tablet (a first-class scenario per `CLAUDE.md`).

Explicitly **not** in scope:

- No `core/`, `server/`, `adapters/` changes. **No `SimAdapter`/`Capabilities` additions, no endpoint or Pydantic model changes, no OpenAPI regeneration — this design changes zero contract surface.** That is the good outcome §4 of the planner template asks to state plainly.
- No change to the OSM ground-texture resolution (see §4.3 — measured out of scope, not assumed).
- No change to the 3D toolbar-height asymmetry between the 2D and 3D footprints (the toolbar already adds ~30 px below the canvas today; pre-existing, orthogonal).
- No redesign of the header, runway strip, tab strip, bottom bar, or the `.pos-startat` popover (verified unaffected, §7).

## 2. Current state (verified)

Layout chain: `PositionPanel.tsx:123–131` renders `.pos-body` (flex row, `position.css:565`) → `.pos-main` (`flex: 1; min-width: 0; overflow: auto; padding: 1rem`, `position.css:572`) containing the active tab, then `ApplyRail` (`.pos-rail`, `flex: none; width: 480px`, `position.css:1211–1214`).

The fixed dimensions that cause the dead space:

| Selector | Rule | Location |
|---|---|---|
| `.pos-sidstartab` | `max-width: 68rem` | position.css:993 |
| `.pos-sidstartab__split` | `repeat(auto-fit, minmax(24rem, 1fr))` — symmetric columns, collapses to one when narrow | position.css:1003–1008 |
| `.pos-sidstartab__legs .pos-legs` | `max-height: 22rem` regardless of viewport height | position.css:1021–1024 |
| `.pos-procdiagram` | `width: 600px; max-width: 100%` | position.css:765–769 |
| `.pos-procdiagram3d` | `width: 600px; max-width: 100%` | position.css:877–881 |
| `.pos-procdiagram3d__canvas` | `aspect-ratio: 600 / 380` | position.css:889–893 |
| `.pos-circuit` | `width: 720px; max-width: 100%` | position.css:681–685 |
| `.pos-airworktab` | `max-width: 480px` | position.css:1143–1148 |
| `.pos-customtab` | `max-width: 480px` | position.css:1191–1196 |
| `.pos-rail` | `width: 480px` | position.css:1211–1214 |

Facts that constrain the fix, each verified in code:

- **Both SVG diagrams are already scale-safe in both directions.** `ProcedureDiagram.tsx:63–65` and `CircuitDiagram.tsx:89–91` set `viewBox` plus fallback `width`/`height` attributes, which `.pos-procdiagram__svg` / `.pos-circuit__svg` (`width: 100%; height: auto`) override. Their overlay buttons are positioned in **percentages of the container, never viewBox pixels** — `CircuitDiagram.tsx:17–19` documents this deliberately, and `ProcedureDiagram.tsx:184–185` does the same. Scaling the container scales everything coherently. The consequence: the only thing stopping the 2D views from growing/shrinking is the CSS width caps, but an *uncapped* column renders the 600-unit viewBox's 10 px node labels (`position.css:833–837`) at `10 × width/600` px — comically large at ~1600 px. Surplus width must go somewhere deliberate (§4.1).
- **The 3D camera fit is valid at any aspect ≥ 1.** `procedureScene.ts:96–99` (`CameraPose.fov`): *"The fit assumes viewport aspect >= 1 … a narrower viewport may need to re-fit."* The fit is a bounding-**sphere** fit against the vertical FOV (`fitCamera`, procedureScene.ts:192–212): `distance = radiusNm / sin(fov/2)`. A sphere that fits the vertical frustum fits every wider one, so **any fixed aspect ratio ≥ 1 at any pixel width needs no re-fit**. This is the entire argument for fluid-width/fixed-aspect over fluid aspect (§8, R3). @react-three/fiber resizes the renderer and updates the default camera's aspect with its container automatically; `ProcedureDiagram3D.tsx:497–499` passes only `position` and `fov`, both aspect-independent.
- **The OSM ground texture's resolution is span-driven, not canvas-driven.** `groundTexture.ts:48–49`: `TARGET_TILES_ACROSS = 6` sizes the mosaic to ≈ 6 × 256 = ~1536 px across the ground plane's larger geographic span, whatever the canvas size; `pickZoom` (groundTexture.ts:111–125) never consults the viewport. A canvas growing from 600 px to ~770 px (the cap chosen in §4.1) changes the on-screen texel density by ×1.28 — the same class of change as orbiting slightly closer, which users do today. **Not visibly soft; out of scope.** (Bumping `TARGET_TILES_ACROSS` would fight the `MAX_TILES = 64` politeness cap, groundTexture.ts:52–57, for marginal gain.)
- **The rail's perforation does not depend on its width.** The `.pos-rail::before/::after` punch band (`position.css:1267–1304`) is a left-anchored `repeat-x` radial-gradient tile (`background-size: 30px 30px`); the long comment's sum-to-D math (position.css:1241–1246) constrains the *tile*, not the element width. At today's 481 px painted span (480 + the `left: -1px` border compensation, position.css:1271), 481/30 = 16.03 tiles — **the rightmost bite is already clipped today**. Width was never load-bearing for the punch math; a clamp is safe. Only the comment's "spans exactly 480px" wording needs updating.
- **Popovers survive the change.** `Popover.tsx:77–81` renders in place (no portal, no `position: fixed`); `.pos-popover` is `position: absolute` (position.css:233). The SID & STAR ident menu anchors to `.pos-sidstartab__ident { position: relative }` (position.css:1080–1085) — below `.pos-main` in the tree, so making `.pos-main` a CSS container (§4.1) cannot change its containing block. `.pos-startat` (`left: 12rem; width: 716px`, position.css:272–278) anchors to `.pos-header { position: relative }` (position.css:126–136), and `.pos-startat--above` to `.pos-bottombar { position: relative }` (position.css:1419) — both **outside** `.pos-main`, unaffected by anything here.
- **The no-layout collapse is a trap.** The `auto-fit` grid comment (position.css:996–1002) documents that when no layout has loaded, the diagram column's empty track collapses and the leg list takes full width by itself. `SidStarTab.tsx:379–427` renders the diagram `<div>` only when `layout !== undefined`. Any explicit asymmetric two-column template must reproduce this collapse or it regresses (§4.1, §7).
- **A second render path exists for Custom Location.** `PositionPanel.tsx:136–150` (coordinate handed over from the Map, no airport loaded) renders `CustomLocationTab` inside the same `.pos-main` + `ApplyRail` row; it inherits the same CSS changes automatically.

## 3. Layout strategy — summary

| Area | Strategy |
|---|---|
| SID & STAR split | Container query on `.pos-main`: single column by default; at ≥ 52rem container width, explicit asymmetric columns `minmax(24rem, 48rem)` (diagram) + `minmax(24rem, 1fr)` (legs). **Diagram grows to a readable cap; the leg list absorbs all remaining surplus.** A `--legs-only` modifier (TSX, one conditional class) reproduces the empty-track collapse. |
| Leg list height | Viewport-relative clamp: `clamp(22rem, 100dvh − 30rem, 44rem)`. The 22rem floor **equals today's cap**, so 1280×800 is provably no-regression; taller viewports gain rows. |
| 2D / 3D diagram | `width: 100%` of the capped column. 3D keeps the fixed `aspect-ratio: 600/380` (≈1.58 ≥ 1 ⇒ camera fit stays valid, no scene-code change). 2D/3D footprint parity is preserved structurally: both are 100% of the same column and share the 600:380 intrinsic ratio, so the toggle still doesn't jump the layout. |
| Approach Training | `.pos-circuit` becomes a flex-grow item: `flex: 1 1 45rem` with a `56rem` readability cap; the facts column keeps `flex: 1` and takes the rest. |
| Airwork / Custom Location | Forms — full-bleed inputs are worse UX. Viewport-relative cap: `max-width: clamp(30rem, 55%, 44rem)`. Grows modestly into the gap, never absurd line lengths. |
| Apply rail (#203) | `width: 480px` → `width: clamp(22.5rem, 30vw, 30rem)` (360–480 px; ~384 px on a 1280-wide tablet). Perforation verified width-independent (§2). |

## 4. Exact changes

### 4.1 `ui/src/features/position/position.css`

**`.pos-main` (position.css:572)** — add:

```css
container: pos-main / inline-size;
```

`.pos-main`'s width is set by flexbox (not by its contents), so `inline-size` containment is safe; height is unaffected. This is the query root every tab can use. Verified safe for popovers (§2).

**`.pos-sidstartab` (position.css:989–994)** — delete `max-width: 68rem`. The split's own caps now govern distribution; the chip/ident/breadcrumb rows are left-aligned wrap rows and don't stretch.

**`.pos-sidstartab__split` (position.css:1003–1008)** — replace the `auto-fit` template and rewrite the accompanying comment (position.css:996–1002):

```css
.pos-sidstartab__split {
  display: grid;
  grid-template-columns: minmax(min(24rem, 100%), 1fr); /* single column default */
  gap: 1rem;
  align-items: start;
}

@container pos-main (min-width: 52rem) {
  .pos-sidstartab__split:not(.pos-sidstartab__split--legs-only) {
    /* Diagram column capped at 48rem; the leg list absorbs all surplus. */
    grid-template-columns: minmax(24rem, 48rem) minmax(24rem, 1fr);
  }
}
```

The new comment must carry forward the **24rem legibility floor and its rationale verbatim in spirit** (the SVG scales its 600-unit viewBox to the column; below 24rem the 10 px node labels drop under reading size — better one wide column than two unreadable ones) and add the cap's rationale: at 48rem (768 px) the labels render at 10 × 768/600 ≈ **12.8 px**, an upper bound chosen for the same legibility reason in the other direction. The container query replaces the auto-fit hack for the same underlying reason the old comment gives — the deciding width is the *container's*, which a viewport media query cannot see because `ApplyRail` shares the row; container queries answer exactly that question directly. 52rem breakpoint ≥ the 49rem two-column minimum (24 + 24 + 1 gap), with slack. Keep `.pos-sidstartab__split > * { min-width: 0 }` (position.css:1011–1013) unchanged — it is still what lets the diagram shrink.

Browsers without container-query support get the default single-column template — degraded (stacked at every width), never broken. This project already ships `@supports`-gated modern CSS (position.css:1286).

**`.pos-sidstartab__legs .pos-legs` (position.css:1021–1024)** — replace `max-height: 22rem`:

```css
max-height: clamp(22rem, calc(100vh - 30rem), 44rem);
max-height: clamp(22rem, calc(100dvh - 30rem), 44rem);
```

(`vh` line as fallback for engines without `dvh`.) The **30rem chrome estimate** approximates header (64 px) + runway strip + tab strip + chip rows + ident row + breadcrumb + paddings + bottom bar ≈ 480 px; it is a judgment number, flagged live-tunable (§10). Arithmetic: at 800 px viewport height → 320 px < 22rem floor → exactly today's behaviour; at 1080 → 600 px (~37.5rem) of legs; at ≥1184 → 44rem ceiling so a 40-leg procedure can't blow the page out. Base `.pos-legs { max-height: 16rem }` (position.css:1696) stays — it serves other contexts.

**`.pos-procdiagram` (position.css:765–769)** — `width: 600px; max-width: 100%` → `width: 100%`.

**`.pos-procdiagram3d` (position.css:877–881)** — `width: 600px; max-width: 100%` → `width: 100%`. Rewrite the comment above it (position.css:874–876): the footprint-parity guarantee is now structural — *both views are 100% of the same capped column and share the 600:380 intrinsic ratio (2D via `viewBox` + `height: auto`, 3D via `aspect-ratio`), so the 2D/3D toggle still cannot jump the layout*. `.pos-procdiagram3d__canvas` and its `aspect-ratio: 600 / 380` are **unchanged**.

**`.pos-circuit` (position.css:681–685)** — replace `width: 720px; max-width: 100%`:

```css
flex: 1 1 45rem;
min-width: min(100%, 24rem);
max-width: 56rem;
```

Basis 45rem = today's 720 px, so wrap behaviour in `.pos-approachtab` (flex row, `flex-wrap: wrap`, position.css:656–660) is preserved; the cap 56rem (896 px) keeps the circuit's 11 px viewBox labels ≤ 11 × 896/720 ≈ **13.7 px**. Marker buttons are percentage-positioned (§2) so both growth and shrink are safe. `.pos-approachtab__selected` (`flex: 1; min-width: 240px`, position.css:662–665) is unchanged and takes the remainder.

**`.pos-airworktab` (position.css:1143–1148) and `.pos-customtab` (position.css:1191–1196)** — `max-width: 480px` → `max-width: clamp(30rem, 55%, 44rem)` on both. The percentage resolves against `.pos-main`'s content box: ≈ today's 480 px on a 1280 tablet, ~704 px (the 44rem cap) at 1920. Block elements never overflow a container narrower than the clamp floor (max-width only caps; auto width still fits), so no `min()` guard is needed. Airwork's ladder ticks are fixed inline px widths (`AirworkTab.tsx:63–66`) — decorative, left-anchored, unaffected; the `margin-left: auto` feet column absorbs the extra width.

**`.pos-rail` (position.css:1211–1223)** — `width: 480px` → `width: clamp(22.5rem, 30vw, 30rem)` (360 px floor / 480 px ceiling; ~384 px at 1280 viewport width). This resolves #203's open decision: the rail keeps its ceiling on desktop and returns ~100 px to the tab content on a tablet. Internal fixed widths survive the floor: `.pos-rail__row-label { width: 8rem }` + flexed value fits in 360 px. Update the `left: -1px` comment's "spans exactly 480px" wording (position.css:1271) to "spans the rail's full width edge-to-edge"; record in the perforation comment that the tile pattern is width-independent (left-anchored `repeat-x`; the rightmost bite is clipped at most widths, including at the old fixed 480 px).

Untouched on purpose: `.pos-body`, `.pos-main`'s padding/overflow, the `@media (max-height: 820px)` start-at rule (position.css:294–299), all popover geometry, `.pos-navdata` / `.pos-empty` (margin-auto centred, width-capped — correct for empty states), the bottom bar, both SVGs' fallback `width`/`height` attributes (harmless, CSS overrides them).

### 4.2 `ui/src/features/position/SidStarTab.tsx`

One structural change, at line 379: the split `<div>`'s class becomes conditional —

```tsx
<div
  className={
    layout !== undefined
      ? 'pos-sidstartab__split'
      : 'pos-sidstartab__split pos-sidstartab__split--legs-only'
  }
>
```

This reproduces the old auto-fit empty-track collapse: with no layout (still loading, or the query skipped), the leg list takes the full width in one column at every container width. A CSS-only `:has(> :only-child)` variant was rejected (§8, R6) because the modifier class is the one piece of this whole change jsdom can actually assert.

No other TSX changes. No component props change, no slice/RTK changes, no generated-API surface touched.

## 5. Rejected alternatives

- **R1 — Delete every `max-width` and let everything stretch.** The 2D SVGs scale their viewBox to the column: an uncapped ~1600 px column renders 10 px labels at ~27 px. Surplus must be routed deliberately; here it goes to the leg list (data rows, which tolerate width) after the diagram reaches its readable cap.
- **R2 — Keep symmetric `auto-fit` columns, cap the diagram *element* inside its column.** Leaves a local dead gap inside the diagram column — the exact complaint of #202, relocated one level down.
- **R3 — Fluid canvas aspect ratio for the 3D view.** Would require re-deriving the fit for aspect < 1 or adding a resize-driven re-fit (`procedureScene.ts:96–99` warns precisely about this), plus re-checking `LABEL_STACK_Y_FRACTION`'s derivation (procedureScene.ts:277–286: "~28 px of a 380 px canvas"), for no user-visible gain over a wider canvas at the same 1.58 ratio. Fixed aspect keeps `procedureScene.ts` — and its tests — untouched.
- **R4 — Full flex-chain height fill** (`.pos-sidstartab` fills `.pos-main`, legs `flex: 1; min-height: 0`). Interacts badly with the grid split (stretch vs. `align-items: start`, weird implicit-row distribution in the single-column collapse), risks double scrollbars against `.pos-main`'s own `overflow: auto`, still needs a ceiling for 40-leg procedures — three new failure modes to buy what the one-line `clamp()` already delivers, and none of it visible to jsdom. The boring option wins.
- **R5 — Viewport media queries instead of a container query.** The deciding width is the grid's own container, which a viewport query cannot see because `ApplyRail` shares the row — the existing comment at position.css:996–1002 already worked this out; the container query is the direct answer.
- **R6 — `:has(> :only-child)` for the legs-only collapse.** Works, but is invisible to unit tests; the modifier class costs one ternary and is assertable (§9).
- **R7 — Rethinking the rail as collapsible/overlay on tablets.** Far past both issues' scope; the clamp achieves the stated goal (less rail on 1280, unchanged on desktop) with zero interaction changes.
- **R8 — Bumping `TARGET_TILES_ACROSS` for sharper ground textures at wider canvases.** Measured unnecessary (§2) and it fights the `MAX_TILES` politeness cap.

## 6. Where the surplus goes (the deliberate decision, per tab)

- **SID & STAR:** diagram column grows 600 → 768 px (labels 10 → ≤12.8 px), then the **leg list absorbs everything else**, without bound. On ultrawide the leg rows get long, but they are fixed-start columns (`3rem 3rem 6rem 1fr`, position.css:1719–1733) with left-aligned text — wide is harmless there, whereas a wide diagram is not.
- **Approach Training:** circuit grows 720 → 896 px (labels 11 → ≤13.7 px), then the facts column absorbs the rest via its existing `flex: 1`.
- **Airwork / Custom Location:** grow to 44rem, then stop — remaining space is intentional margin, not a "dead gap": these are forms, and the requirement is bounded line length, recorded here as the chosen treatment.
- **Vertically:** the leg list is the only fixed-height offender; it becomes viewport-relative (22rem floor = today, 44rem ceiling). The diagrams gain height automatically with width via their intrinsic/declared ratios.

## 7. Edge cases

- **No layout loaded (SID & STAR):** `--legs-only` modifier forces one full-width column — same behaviour as today's collapsed empty track. Brief legs-only flash while the layout query resolves is identical to today's auto-fit behaviour.
- **No procedure chosen:** `.pos-sidstartab__empty` renders instead of the split (SidStarTab.tsx:373–377); margin-auto centred, unaffected.
- **Coordinate-without-airport path** (PositionPanel.tsx:136–150): renders `CustomLocationTab` in the same `.pos-main`; inherits the clamp with no extra work.
- **Popovers:** `.pos-startat` / `.pos-startat--above` anchor to the header / bottom bar, outside `.pos-main` — unaffected by the container or the rail clamp (at 1280 wide, 12rem + 716 px = 908 px still fits). The ident menu anchors to its own relative row inside the tab. Verified in §2; re-checked in the live pass anyway.
- **`@media (max-height: 820px)`** start-at rule: untouched, still applies.
- **Single-column split on a narrow container** (e.g. 1280 tablet with the rail at 384 px: container ≈ 848 px content ≈ 53rem — just above the 52rem breakpoint, two columns of ~24.5rem/~27rem; at anything narrower, one column). Both states must be walked in the live pass since the breakpoint sits close to the tablet case — this is a deliberate tunable (§10).
- **Ultrawide (≥2560):** diagram capped, legs wide (accepted, §6), forms capped, rail at ceiling.

## 8. Test plan

**What jsdom can honestly cover (and nothing more):**

- `SidStarTab.test.tsx` — extend: the split renders with `pos-sidstartab__split--legs-only` when the layout query has no data, and without it when a layout is present. This is a real structural contract (it drives the collapse), not a fake layout assertion.
- Existing suites are unaffected by design: `ProcedureDiagram.test.tsx` / `procedureProjection.test.ts` (viewBox constants unchanged), `CircuitDiagram.test.tsx` (percentage-positioned buttons unchanged), `ProcedureDiagram3D.test.tsx` / `procedureScene.test.ts` (no scene-code change — that is the point of fixed aspect). A run of `cd ui && npm run lint && npm run typecheck && npm test && npm run build` must stay green with no test edits beyond the one extension above.
- **Stated plainly: jsdom cannot see layout.** There are no meaningful unit assertions for the CSS itself — no invented `getBoundingClientRect` fixtures, no snapshotting computed styles jsdom doesn't compute. Verification of the actual responsive behaviour is the live pass below, and only that.

**No contract tests, no `@pytest.mark.sim` tests, no fixtures** — nothing behind the UI changes; the Python suites are untouched by construction.

**Live browser verification checklist** (the real acceptance test):

For each of ~1280×800, ~1440×900, ~1920×1080 (and one ultrawide spot-check if available), in **both themes**:

1. **SID & STAR:** no dead gap between legs column and rail; two columns at desktop widths, single column when the container is narrow; diagram column never exceeds ~768 px; node labels legible at both extremes; leg list fills tall viewports (more than today's 22rem at 1080p) and still scrolls internally on 800 px height; 2D↔3D toggle does not jump the layout at any width; 3D canvas fills its column at 600:380, orbit + node click + reset camera work after a resize; OSM texture not visibly degraded vs. dev; compressed-segment callouts and node labels still track their anchors after resize.
2. **SID & STAR, no layout:** legs-only single wide column, no empty left track.
3. **Approach Training:** circuit grows into the gap up to its cap, facts column takes the rest; marker buttons still sit on their dots at every width (percentage-positioning check); wraps cleanly when narrow.
4. **Airwork / Custom Location:** forms widen modestly, no full-bleed inputs, no gap complaint at 1920 (bounded margin is the recorded intent).
5. **Rail:** ~384 px at 1280, 480 px at ≥1600; perforation bites render correctly at both widths, top and bottom, both themes; "Will be applied" rows and checks uncramped at the floor.
6. **Popovers:** Start-at (header and bottom-bar anchors) and the procedure ident menu open in place at 1280 and 1920.
7. **Gates/empty states:** navdata card and the three `pos-empty` states still centre.

## 9. Parallelisation

This is one small, single-branch UI fix — the honest dispatch is **one implementer track** owning `ui/src/features/position/` (touching exactly `position.css` and `SidStarTab.tsx` + its test), followed by the live resize pass. There is no backend track, and splitting CSS from the one-line TSX change would put two agents in the same directory for no gain — the dispatch rule requires disjoint directory sets, so no split. The tester's only pre-implementation deliverable (the `--legs-only` assertion) is small enough to fold into the same branch. Nothing here touches the never-parallelise list (no contract, no schema, no merges).

## 10. Open questions and risks

Judgment numbers — **all live-tunable in the resize pass, recorded with rationale rather than measured as facts**:

1. **48rem diagram cap** (labels ≤12.8 px) and **56rem circuit cap** (≤13.7 px): nudge if labels read wrong at 1920.
2. **52rem breakpoint**: sits just under the 1280-tablet container width (~53rem with the rail at its 30vw point), so the tablet lands barely in two-column mode; if those columns feel tight live, raise the breakpoint to ~56rem and accept single-column on the tablet.
3. **30rem chrome estimate** in the legs clamp: approximate by construction (the runway strip wraps); the 22rem floor bounds the failure at "exactly today", so the worst case of a wrong estimate is no regression, only under-use of tall viewports.
4. **Rail `30vw` / 22.5rem floor**: confirm the checks list and METAR footer at 360 px live.
5. **Container-query support** is assumed (all target browsers ≥2023); the fallback is single-column stacking, degraded not broken.
6. Known environmental risk for the verifier, not the design: remote-browser screenshots can show fast-repainting layers colour-inverted (recorded workspace memory) — check computed styles before "fixing" any colour oddity seen only in captures.

Key files verified for this design (all under the worktree root):
- `ui/src/features/position/position.css` — every fixed dimension and the perforation math
- `ui/src/features/position/PositionPanel.tsx` — both `.pos-main` render paths
- `ui/src/features/position/SidStarTab.tsx` — the conditional diagram branch (line 379), the one TSX change site
- `ui/src/features/position/procedureScene.ts` — camera-fit aspect assumption (lines 96–99, 192–212)
- `ui/src/features/position/groundTexture.ts` / `useGroundTexture.ts` — span-driven texture resolution
- `ui/src/features/position/ProcedureDiagram3D.tsx`, `ProcedureDiagram.tsx`, `CircuitDiagram.tsx`, `Popover.tsx` — scaling and anchoring behaviour
