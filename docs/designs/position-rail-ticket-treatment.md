# Position rail: ticket/receipt visual treatment (issue #156)

## 1. Scope

This is a pure visual-polish change to one already-shipped panel: `ApplyRail` (`ui/src/features/position/ApplyRail.tsx`), the "Will be applied" right rail on the Position screen. It gives the rail a torn/perforated top and bottom edge, like a ticket stub or a receipt tear line, so the card reads as a physical object rather than a flat panel.

**Product decision already made (not re-litigated here):** ship directly. One CSS technique, documented as final. No runtime toggle, no feature-flag class, no dual old/new code paths, no spike component. Rejected alternatives are recorded below for the record, not left half-built in the tree.

**In scope:**
- The exact CSS technique for the perforation (repeating radial-gradient "bites"), with the spacing/radius math worked out to the pixel.
- The DOM/CSS restructuring needed so the perforation stays pinned to the card's physical edges while the rail's content scrolls underneath it.
- The colour contract for the punched-out area, for both themes.
- The minimal `ApplyRail.tsx` diff (one wrapper `<div>`, no renames, no new props, no new state).

**Explicitly out of scope:**
- Any change to what the rail shows, where its data comes from, or how it is computed. `applyRows`, `checks`, `errors`, `usePositionData` are untouched.
- Any change to `positionSlice`, RTK Query endpoints, or the OpenAPI schema.
- Any change to `core/`, `adapters/`, or `server/`.
- Reuse of this pattern elsewhere. It is scoped to `.pos-rail` only (see §7).

**Roadmap linkage:** the Position Manager is Phase 1 of `docs/roadmap.md`, marked **Complete** (PR #143 landed the v3 rebuild this rail belongs to). This issue is not a `docs/feature-spec.md` line item — it is a post-completion visual refinement of an already-delivered manager, filed as its own GitHub issue. There is no exit criterion this design needs to satisfy beyond "does not regress the shipped Position screen's behaviour or its CI gates."

## 2. REST endpoints

N/A — pure CSS visual treatment, no data-flow change.

## 3. Pydantic models

N/A — pure CSS visual treatment, no data-flow change.

## 4. `SimAdapter` / `Capabilities` additions

N/A — pure CSS visual treatment, no data-flow change. No contract-test additions follow from this design.

## 5. Dataref mapping (X-Plane)

N/A — pure CSS visual treatment, no data-flow change. No dataref, adapter, or Web API surface is touched.

## 6. `core/` logic

N/A — pure CSS visual treatment, no data-flow change. No new or modified `core/` module.

## 7. UI panel outline

This is where all the real content of this design lives.

### 7.1 Current state (verified against this worktree)

- `ApplyRail.tsx` is 146 lines. Its root is `<aside className="pos-rail" aria-label="Will be applied">` at line 61, with no props and no local state — everything it renders comes from `usePositionData` hooks and the `checks`/`applyRows` pure functions.
- `.pos-rail` (`position.css` lines 848–858) today: `flex: none; width: 480px; overflow-y: auto; padding: 1rem; background: var(--pos-rail); border-left: 1px solid var(--pos-hair); display: flex; flex-direction: column; gap: 1rem;`. No `border-radius`, no `box-shadow` anywhere in the block — the card is flush and rectangular.
- `.pos-rail` sits inside `.pos-body` (`flex: 1; min-height: 0; display: flex; overflow: hidden;`) as a sibling of `.pos-main` (`flex: 1; min-width: 0; overflow: auto; padding: 1rem;` — no background of its own).
- Global reset: `* { box-sizing: border-box; }` (`ui/src/index.css:73-75`). This matters for the border-compensation math below.
- Colour tokens, scoped under `.pos` / `[data-theme='light'] .pos`, cross-checked against `docs/designs/position-redesign-v3.md`'s "Visual system" section:

  | token | dark | light |
  |---|---|---|
  | `--pos-bg` | `oklch(0.155 0.012 250)` | `oklch(0.96 0.004 250)` |
  | `--pos-panel` | `oklch(0.19 0.013 250)` | `oklch(0.995 0.002 250)` |
  | `--pos-rail` | `oklch(0.215 0.014 250)` | `oklch(0.975 0.003 250)` |
  | `--pos-hair` | `oklch(0.26 0.012 250)` | `oklch(0.9 0.005 250)` |

  `--pos-rail` and `--pos-panel` are separate tokens with separate values — not to be conflated.
- Zero existing uses anywhere in `ui/` of `clip-path`, `mask-image`, `repeating-radial-gradient`, or `repeating-linear-gradient` (confirmed by full-tree grep). This is a genuinely new visual technique for the codebase.
- What is adjacent to `.pos-rail` in the DOM, and its background, per `PositionPanel.tsx`:

  | edge | neighbour (both render branches that show `ApplyRail`) | background |
  |---|---|---|
  | left/beside | `.pos-main` (no own background) → inherits `.pos { background: var(--pos-bg) }` | `--pos-bg` |
  | above, primary layout (`loadedIcao !== ''`) | `.pos-tabs` (`background: var(--pos-panel)`) | `--pos-panel` |
  | above, coordinate-handover layout (`loadedIcao === '' && hasCoordinate`) | `.pos-empty` (no own background) → `--pos-bg` | `--pos-bg` |
  | below, both layouts | `.pos-bottombar` (`background: var(--pos-panel)`) | `--pos-panel` |

  So the rail's literal neighbours are **not** uniformly `--pos-bg` — the tabs strip above it and the bottom bar below it are `--pos-panel`. §7.3 explains why the punch colour is still `--pos-bg` regardless.
- No existing test file references `.pos-rail`, `ApplyRail`, or `"Will be applied"` other than `ApplyRail.tsx`, `PositionPanel.tsx`, and `position.css` themselves (confirmed by grep) — there is no test coupled to the current single-`<aside>` structure.

### 7.2 CSS technique — chosen: painted repeating radial-gradient bites

**Chosen technique:** a row of tangent circular "bites," each painted in the solid colour of what sits behind the card (`--pos-bg`), on a thin non-scrolling pseudo-element strip pinned to the card's own top and bottom padding band. No `clip-path`, no `mask-image` — a `radial-gradient` tiled with `background-size`/`background-repeat`, painting solid colour rather than compositing transparency.

**Exact CSS** (to replace `position.css` lines 848–858 and to be inserted immediately after):

```css
.pos-rail {
  flex: none;
  width: 480px;
  min-height: 0;
  padding: 8px 0;
  background: var(--pos-rail);
  border-left: 1px solid var(--pos-hair);
  display: flex;
  flex-direction: column;
  position: relative;
}

.pos-rail__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0.5rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* Ticket-stub perforation: a row of tangent half-circle bites, painted in the page's own
   background colour, cut into the card's top and bottom padding band. Scoped to .pos-rail —
   see §7.5 for why this is not a shared utility class yet. */
.pos-rail::before,
.pos-rail::after {
  content: '';
  position: absolute;
  left: -1px; /* compensates the 1px border-left so the strip spans exactly 480px, see below */
  right: 0;
  height: 8px;
  background-image: radial-gradient(circle at 8px 0, var(--pos-bg) 7.5px, transparent 8.5px);
  background-size: 16px 16px;
  background-repeat: repeat-x;
  pointer-events: none;
  z-index: 1;
}

.pos-rail::before {
  top: 0;
}

.pos-rail::after {
  bottom: 0;
  transform: scaleY(-1);
}
```

**The math, worked out:**

- **Tooth diameter D = 16px, radius R = 8px, tangent (no gap, no overlap).** `background-size: 16px 16px` tiles a 16×16 box horizontally (`repeat-x`); the circle inside each tile is centred at `x = 8px` (half the tile width), so adjacent tile centres are 16px apart — exactly `2R` — meaning consecutive circles touch at a single point with neither a gap (a "perforated dotted line" look) nor an overlap (a doubled-paint seam). This produces the classic continuous postage-stamp/ticket scallop rather than sparse perforation dots.
- **480px rail width ÷ 16px tile = 30 exactly.** `.pos-rail` has a fixed `width: 480px` (`flex: none`, not fluid), so the tiling divides the card's width into 30 whole tiles with **no partial/clipped circle at either edge**. This is a deliberate choice of `D = 16` over other tangency-preserving sizes (20, 24, …) specifically because it is the finer of the round numbers that divides 480 evenly, and a finer perforation reads more like a receipt tear than a chunky movie-ticket notch, which suits a 480px-wide instrument rail rather than a physically large ticket.
- **`left: -1px` compensates the global `box-sizing: border-box` + `border-left: 1px`.** With `border-box`, `.pos-rail`'s content/padding box is `480 - 1(border-left) - 0(border-right) = 479px` wide. The pseudo-elements' containing block is that padding box. `left: -1px; right: 0` extends the strip's own box by 1px on the left, giving it an effective width of `479 + 1 = 480px` — exactly the tile math above, with the perforation starting flush with the card's outer visual edge (under the hairline border) rather than 1px inside it. Accepted cosmetic trade-off: for the 8px band at each end, the hairline border is visually replaced by the strip's own paint (`--pos-bg` circle or transparent-revealing-card-colour gap) rather than the `--pos-hair` colour — a sub-pixel-scale detail, not a visible defect, and arguably reads as the tear extending slightly past the seam.
- **Soft edge, 7.5px/8.5px stops.** A hard two-stop gradient (`var(--pos-bg) 0 8px, transparent 8px`) renders a jagged, aliased circle boundary at 1x DPI. The chosen stops (`var(--pos-bg) 7.5px, transparent 8.5px`) feather a 1px band symmetrically around the nominal `R = 8px`, and — because `7.5 + 8.5 = 16 = D` — the soft edges of two adjacent circles meet exactly at their shared tangent point with no visible seam and no double-coverage. This is the only place the design deliberately departs from "hard geometric radius" in favour of render quality; it does not change the spacing math above.
- **No explicit `background-color` on the pseudo-elements.** `.pos-rail` itself already paints `background: var(--pos-rail)` across its whole box, including the 8px padding band the strips occupy. The pseudo-element's `background-image` only needs to paint the bite (`--pos-bg`) on top; everywhere the gradient is `transparent`, the card's own already-correct `--pos-rail` colour shows through underneath. One fewer property, and it can never drift out of sync with the card's own background if that token changes.
- **`::after` uses `transform: scaleY(-1)` rather than a re-derived gradient.** Recomputing the gradient's circle-position for the bottom edge (moving the centre to the strip's bottom instead of its top) would require a second, slightly different `background-image` value and break the shared rule the two pseudo-elements currently share. Flipping the whole 8px strip vertically is one line, keeps `::before`/`::after` on one shared declaration block, and is visually identical (the gradient is radially symmetric, so a vertical flip of "the bottom half of a circle sitting at y=0" is exactly "the top half of a circle sitting at y=8," which is what the bottom edge needs).

**No `border-radius` interaction to worry about.** `.pos-rail` has no `border-radius` today, so there is no corner-rounding vs. overflow-clipping conflict of the kind that plagues some CSS ticket tutorials — confirmed by grep across the block, not assumed.

### 7.3 Where the perforation renders relative to scrolling

`.pos-rail` has `overflow-y: auto` today, and the whole rail's content (head, rows, notes, checks, footer) is a direct child of that scrolling element. **A `position: absolute` pseudo-element whose containing block is a scrolling ancestor scrolls with that ancestor's content** — this is standard CSS behaviour (the containing block is the padding box of the positioned ancestor, and that box's content, including absolutely-positioned descendants anchored to it, moves together with the scroll offset unless `position: sticky`/`fixed` is used). Pinning `::before`/`::after` directly to today's `.pos-rail` would therefore make the "torn edge" scroll away as soon as the instructor scrolls the checks list — exactly the wrong effect for something that should look torn into the card's physical top/bottom.

**Resolution: split the box model into a non-scrolling shell and a scrolling inner element.**

- `.pos-rail` (the existing `<aside>`, class name **unchanged** — it stays the BEM block, its children keep the `.pos-rail__*` element names they already have) becomes the non-scrolling shell: fixed width, background, border, and now `position: relative` (the containing block for the pseudo-elements) plus `min-height: 0` (see below). It carries **only** the top/bottom padding band (`padding: 8px 0`) that the perforation strips live in.
- A new `.pos-rail__scroll` `<div>`, added as the aside's single child, is the actual scroll container: `overflow-y: auto`, the remaining padding (`0.5rem 1rem` — i.e. 8px top/bottom to make the total inset from the card edge to the first row `8px (shell) + 8px (inner) = 16px = 1rem`, unchanged from today's single `padding: 1rem`; and 16px left/right, also unchanged), and the `gap: 1rem` that used to live on `.pos-rail` directly.
- All existing content (`pos-rail__head`, `pos-rail__error`, `pos-rail__rows`, `pos-rail__notes`, `pos-rail__checks`, `pos-rail__footer`) moves one level deeper, inside `.pos-rail__scroll`, with **zero** changes to their own selectors — none of the `.pos-rail__*` rules is a descendant selector keyed off `.pos-rail` (confirmed by grep: `.pos-rail` appears exactly once in `position.css`, as its own rule), so nesting them one `<div>` deeper changes nothing about how they render.
- **No overlap by construction, not by luck:** because the perforation strips (`height: 8px`, positioned at the shell's own `top: 0`/`bottom: 0`) exactly fill the shell's own `8px` top/bottom padding band, and `.pos-rail__scroll`'s box begins exactly where that band ends, the strip and the scrollable content's box never occupy the same pixels — at any scroll position, including scrolled fully to the top or bottom. There is nothing to clip and no z-index race to reason about beyond the one below.
- **`min-height: 0` on `.pos-rail` is required, not optional.** Before this change, `overflow-y: auto` lived directly on the flex item (`.pos-rail`) that sits inside `.pos-body`, and CSS's automatic-minimum-size override for scroll containers made that item shrink correctly inside `.pos-body`'s `flex: 1; min-height: 0`. After the split, `.pos-rail` itself no longer has `overflow` other than `visible`, so it loses that automatic override and would refuse to shrink below its content's natural height on a short viewport, potentially breaking `.pos-body`'s (`overflow: hidden`) layout. Setting `.pos-rail { min-height: 0; }` explicitly restores the old shrink behaviour, and `.pos-rail__scroll`'s own `min-height: 0` (needed for the same reason, one level down, as an `flex: 1` item inside the now-flex `.pos-rail`) completes the chain.
- **Stacking order needs no explicit help beyond the defensive `z-index: 1` already in the rule above.** `.pos-rail::before`/`::after` are `position: absolute` (auto z-index, generated as the shell's first/last box respectively); `.pos-rail__scroll` is an ordinary in-flow, non-positioned child. Per CSS's painting order, positioned descendants (even at `z-index: auto`) always paint above in-flow non-positioned content within the same stacking context, so the strips already paint over the scroll div without any `z-index` — it is kept anyway as cheap insurance against a future rule that accidentally establishes a stacking context with a higher default.

### 7.4 `ApplyRail.tsx` diff — minimal, no renames

```tsx
return (
  <aside className="pos-rail" aria-label="Will be applied">
    <div className="pos-rail__scroll">
      {/* everything that is currently the aside's direct children, unchanged: */}
      <div className="pos-rail__head">…</div>
      {isError && <p className="pos-rail__error">…</p>}
      <ul className="pos-rail__rows">…</ul>
      {preview !== undefined && preview.notes.length > 0 && (
        <ul className="pos-rail__notes">…</ul>
      )}
      <div className="pos-rail__checks">…</div>
      <div className="pos-rail__footer">…</div>
    </div>
  </aside>
);
```

That is the entire component diff: one wrapper `<div className="pos-rail__scroll">` opened right after `<aside>` and closed right before `</aside>`, and re-indentation of the existing JSX one level deeper. No className renamed, no prop added, no new state, no new hook, no change to `aria-label` (it stays on the `<aside>`, so the rail's accessible name and landmark role are unchanged).

### 7.5 Colour contract for both themes

**Punch colour: `--pos-bg`, in both themes, for both edges — not `--pos-panel`, and not keyed to whichever chrome bar happens to be adjacent in the layout.**

Reasoning: a bite in a card exposes whatever is physically *behind* it, not whatever is beside it in the page's normal flow. `.pos-tabs` (above) and `.pos-bottombar` (below) are peer panels laid out next to `.pos-rail` in the document — they are not behind it in z-order, so a torn card wouldn't reveal their colour any more than tearing a real ticket reveals the colour of the counter next to it. The one thing that is uniformly "behind" the whole `.pos` scope, in every layout branch that renders `ApplyRail`, is the screen's own base surface: `--pos-bg`.

This also happens to be the value already confirmed adjacent to the rail on its left (`.pos-main`) and, in the coordinate-handover layout, above it too (`.pos-empty`) — so `--pos-bg` is not an invented value, it is the one colour that is honestly "what's behind/around this card" everywhere the card appears.

It also produces the right *read* in both themes: `--pos-bg` is measurably darker/more saturated toward mid-tone than both `--pos-panel` and `--pos-rail` in both palettes —

| | `--pos-bg` L | `--pos-panel` L | `--pos-rail` L |
|---|---|---|---|
| dark | 0.155 | 0.19 | 0.215 |
| light | 0.96 | 0.995 | 0.975 |

— so the punched circles read as a recess/hole cut down into the card, not as a colour mismatch against whatever happens to be adjacent, in either theme. No separate light/dark rule is needed for the perforation itself: `var(--pos-bg)` inside `.pos-rail::before`/`::after` resolves automatically through the existing `[data-theme='light'] .pos { --pos-bg: … }` override, the same mechanism every other rule in this file already relies on.

### 7.6 Accessibility

`::before`/`::after` with `content: ''` generate no accessible-tree node at all in any current browser — they are not DOM elements, carry no implicit role, are never focusable, and are never announced by a screen reader in its default configuration. `aria-hidden` is an attribute on real elements and has nothing to attach to here; adding it to `.pos-rail` itself would be wrong (it would hide the whole "Will be applied" landmark, which is very much not decorative). **Conclusion: no accessibility change is needed.** The only accessibility-relevant existing attribute, `aria-label="Will be applied"` on the `<aside>`, is untouched by this design (see §7.4).

### 7.7 Reuse scope

Scoped strictly to `.pos-rail`. There is no second consumer of a ticket/perforated edge in the codebase today, so no shared utility class or custom-property abstraction (e.g. `--ticket-tooth-d`/`--ticket-tooth-r`) is introduced now, per the issue's own default guidance. If a second panel wants the same treatment later, that is the point to extract the shared pieces (the `::before`/`::after` rule shape and the two magic numbers, 16 and 8) into a reusable class — not before, and not speculatively in this PR.

### 7.8 Tablet-first layout note

No layout-shape change: `.pos-rail`'s width (480px), position in the flex row, and its role as a fixed-width sidebar next to `.pos-main` are all unchanged. The perforation is a decorative overlay within the existing box and does not affect touch-target sizing, scroll behaviour (still native `overflow-y: auto`, still touch-scrollable), or any breakpoint. No RTK slice, no RTK Query endpoint, no new controls, and therefore no new capability-flag gating — this section of the template does not apply beyond what is already stated.

## 8. Test plan

There is no visual-regression tooling in this repository (`ui/package.json` confirms `"test": "vitest run"` with `@testing-library/jest-dom` only — no Playwright, no Chromatic, no screenshot-diff harness), and no existing unit test references `.pos-rail`, `ApplyRail`, or `"Will be applied"` (confirmed by grep) that the added wrapper `<div>` could break. This is therefore, honestly, not something the automated suite can assert pixel-for-pixel — the verification is the standard toolchain plus a manual visual pass:

- `ruff check . && ruff format --check .` and `mypy .` — unaffected (no Python touched), run anyway as the standing gate.
- `cd ui && npm run lint && npm run typecheck` — must pass with the new `.pos-rail__scroll` div; no new TypeScript surface is introduced (no new props, no new component file), so this is a structural sanity check, not a real risk area.
- `cd ui && npm test` — the existing suite has nothing keyed to `ApplyRail`'s DOM shape, so this should pass unchanged; if the implementer discovers a snapshot or a `container.querySelector` test elsewhere that does depend on `.pos-rail`'s children being direct children of the `<aside>`, that test needs a one-line update to look inside `.pos-rail__scroll` instead — call this out explicitly in the PR rather than silently patching it.
- `cd ui && npm run build` — must succeed; no code-splitting or bundling implication (CSS-only + one wrapper element).
- **Manual/visual verification (not a `pytest`/`npm` command, but part of "done"):** the implementer should check the rendered rail in both `data-theme` values — dark and light — confirming (a) the perforation is visible and reads as a clean tangent scallop with no visible seam or gap, (b) scrolling the rail's content (e.g. with enough `checks` to overflow) leaves the top/bottom perforation strip visually static while the rows scroll underneath it, and (c) the 1px border-left compensation does not leave a visible notch or overhang at the card's left edge. Per this project's own web-verification convention, that is a `cloudflare-browser` MCP screenshot pass against the local dev server (through a `cloudflared` quick tunnel), not a repo test command — it belongs to the implementer/tester step, not to this design document, and is noted here so it isn't silently skipped.
- No `@pytest.mark.sim` tests apply — this change touches no adapter, no simulator, no Python.
- No navdata fixture concerns — no navdata is read, parsed, or displayed differently.
- No OpenAPI schema regeneration needed — no route is added, changed, or removed, so `ui/src/api/schema.d.ts` is untouched by this PR.

## 9. Parallelisation

Single track. This is a self-contained visual change confined to `ui/src/features/position/ApplyRail.tsx` and `ui/src/features/position/position.css` — no shared-foundation change (§4 is N/A), no new endpoint, no new model, nothing that another manager's branch could conflict with structurally. There is nothing to split into concurrent tracks inside this issue: the CSS technique (§7.2–7.3) and the one-line component diff (§7.4) are small enough, and mutually dependent enough (the wrapper div only exists to give the CSS split something to attach to), that a single implementer pass covers both. Dispatch one `feature/position-rail-ticket-treatment` branch, one implementer pass, one PR to `dev`; CI on that PR (`lint-ui`, `test-ui`) is the integration barrier, same as any other change.

## 10. Open questions and risks

- **No automated way to catch a regression in the perforation's own rendering.** As noted in §8, there is no visual-regression harness in this repo. If this pattern gets reused on a second panel later (§7.7), that would be a reasonable point to also ask whether a lightweight visual-diff tool is worth adding — out of scope for this issue, flagged here so it isn't forgotten the next time a "does this pixel-perfect CSS trick still look right" question comes up.
- **The `left: -1px` border compensation is exact only because `.pos-rail`'s `border-left` is exactly `1px` and its width is exactly `480px` today.** If either of those two literal values ever changes (e.g. the rail becomes resizable, or the border grows to 2px for a future high-contrast mode), the tiling math (480/16 = 30 exact tiles, and the −1px offset) must be re-derived — it is not expressed as a `calc()` off the actual computed values, by design, to keep the rule simple and pasteable. This is a reasonable trade-off for a fixed-width, non-resizable sidebar, but it is worth a one-line code comment (already included in the CSS block in §7.2) so a future width change doesn't silently reintroduce a partial circle at the edge.
- **No live-sim or backend risk whatsoever** — this design touches none of the known risks catalogued in `docs/architecture.md` (all of which are about the sim connection, navdata, or geodesy). Nothing here needs a spike, a user decision, or a live measurement beyond the manual screenshot pass in §8.
