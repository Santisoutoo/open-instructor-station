# Position — replace the screen-menu dropdown with the shared TabBar

GitHub issue: #154
Type: UI-only refactor. No backend, no `SimAdapter`, no new endpoints, no new Pydantic models.

## 1. Scope

**Problem.** The Position screen is full-bleed (`App.tsx`'s `fullBleed = activeTab === 'position'`)
and hides the shell's `<TabBar />` entirely. In its place, `PositionHeaderBar` shows a
`Position ▾` button that opens `ScreenMenu`, a `Popover` listing the same 12 `TABS` entries as a
`role="menu"`. Every other screen shows all 12 modules as a horizontal `role="tablist"` with
scroll-snap. Position is the one screen that costs an extra click to reach another module.

**What this design does.** Replaces the `Position ▾` trigger + `ScreenMenu` popover inside
`PositionHeaderBar` with the shared `<TabBar />` component, embedded directly in the Position
screen's own 64px header — not by un-setting `fullBleed` and not by changing `App.tsx`'s shell
header. Deletes the now-dead `screenMenuOpen` popover-exclusivity member and the `ScreenMenu`
component. Adds a small, scoped set of CSS overrides so the shell's tab strip reads correctly
inside the Position screen's independent (`--pos-*`) visual system.

**What this design explicitly does not do:**
- No change to `TabBar.tsx`, `components/tabs.ts`, or `index.css`'s `.tabbar`/`.tabbar__tab`
  rules — those are shared files every manager depends on, and this is a single-manager change.
- No change to which 12 modules exist, their order, or their lazy-loading.
- No change to `App.tsx`'s full-bleed mechanism, the drawer, or the status bar — Position keeps
  no shell header, no drawer, no status bar. Only the *content* of Position's own header changes.
- No visual redesign of the rest of `PositionHeaderBar` (ICAO cluster, Start-at popover,
  connection dot, theme toggle) beyond the flex adjustments this change forces.
- No feature-spec item is added or removed; this does not touch Manager 1's functional scope
  (`docs/feature-spec.md` §1, Position Manager) — it is pure navigation chrome. Phase: this
  manager shipped in **Phase 1 (complete)** per `docs/roadmap.md`; this change does not reopen
  Phase 1's exit criteria, it only touches the screen's chrome that was added later in the v3
  redesign (`docs/designs/position-redesign-v3.md`, PR #143). That document's header description
  ("screen-menu trigger") is superseded by this one for navigation only; it is not edited, since
  it remains the reference for colour tokens, typography and the rest of the layout.

## 2. REST endpoints

N/A — UI-only change, no backend surface.

## 3. Pydantic models

N/A — UI-only change, no backend surface.

## 4. `SimAdapter` / `Capabilities` additions

N/A — UI-only change, no backend surface. No capability flag is touched; the TabBar's own
gating (`ComingSoonPanel` for tabs with no `load`) is unchanged and already handles modules
that are not yet built.

## 5. Dataref mapping (X-Plane)

N/A — UI-only change, no backend surface, no `adapters/xplane/` file is touched.

## 6. `core/` logic

N/A — UI-only change. No sim-agnostic algorithm is added, changed, or removed.

## 7. UI panel outline

### 7.1 Component change

`PositionHeaderBar.tsx` currently renders, in order: `Position ▾` trigger button → `<ScreenMenu>`
→ airport cluster → `Start-at` trigger → `<StartAtPopover>` → spacer → demo badge → connection
status → theme toggle.

After this change: `<TabBar />` → airport cluster → `Start-at` trigger → `<StartAtPopover>` →
spacer → demo badge → connection status → theme toggle. `TabBar` is rendered with no props (it
is self-contained per its own doc comment) and reads `state.ui.activeTab` / dispatches
`tabSelected` on `uiSlice` exactly as it does in the shell header — this manager makes zero
changes to that contract.

**Single-tablist invariant.** `App.tsx` renders the shell's `<TabBar />` iff `!fullBleed`, and
`fullBleed` is `true` iff `activeTab === 'position'`. The Position screen renders its own
embedded `<TabBar />` iff `PositionPanel` is mounted, which only happens when
`activeTab === 'position'`. The two are therefore mutually exclusive by construction: exactly one
`role="tablist"` with `aria-label="Instructor station modules"` exists in the DOM at any time, so
the roving-tabindex focus management in `TabBar.tsx` (`document.getElementById('tab-' + id)`) and
the `id="tab-${id}"` / `aria-controls="tabpanel-${id}"` pairing never collide between the two
render sites.

### 7.2 Exact edit list

**`ui/src/features/position/PositionHeaderBar.tsx`**
- Delete the header doc comment's first line describing "screen-menu trigger" (lines 1-9) and
  replace with a description naming the embedded `TabBar`.
- Remove `import { useRef } from 'react'` usage for `screenMenuTriggerRef` — keep `useRef` import
  only if `startAtTriggerRef`/`icaoInputRef` still need it (they do).
- Remove `import { ScreenMenu } from './ScreenMenu';`.
- Add `import { TabBar } from '../../components/TabBar';`.
- Remove `screenMenuToggled` from the `positionDesignSlice` import list (keep `airportMenuOpened`,
  `airportLoaded`, `icaoTyped`, `startAtToggled`).
- Remove the line `const screenMenuOpen = useAppSelector((state) => state.positionDesign.screenMenuOpen);`.
- Remove the line `const screenMenuTriggerRef = useRef<HTMLButtonElement>(null);`.
- Remove the whole JSX block:
  ```tsx
  <button
    ref={screenMenuTriggerRef}
    type="button"
    className="pos-header__menu-trigger"
    aria-haspopup="menu"
    aria-expanded={screenMenuOpen}
    aria-controls="pos-screen-menu"
    onClick={() => {
      dispatch(screenMenuToggled());
    }}
  >
    Position ▾
  </button>
  <ScreenMenu triggerRef={screenMenuTriggerRef} />
  ```
  and replace it with `<TabBar />`.

**`ui/src/features/position/ScreenMenu.tsx`**
- Delete the file outright. Confirmed sole importer is `PositionHeaderBar.tsx` (repo-wide grep for
  `ScreenMenu` returns only `ScreenMenu.tsx` itself, `PositionHeaderBar.tsx`, and the read-only
  reference `docs/designs/position-redesign-v3.md`). `Popover.tsx`, which `ScreenMenu` used, keeps
  its other two consumers (`AirportMenu`, `StartAtPopover`) untouched.

**`ui/src/features/position/positionDesignSlice.ts`**
- Doc comment at line 23: `screenMenuOpen`, `startAtOpen`, `procedureMenuOpen`,
  `airportMenuOpen`) → drop `screenMenuOpen` from that list, leaving the other three named.
- `PositionDesignState` interface, line 144: delete `screenMenuOpen: boolean;`.
- `initialPositionDesignState`, line 184: delete `screenMenuOpen: false,`.
- `airportMenuOpened` reducer, line 235: delete `state.screenMenuOpen = false;`, leaving
  `state.airportMenuOpen = true; state.startAtOpen = false;` — the two-member exclusivity pair.
- `screenMenuToggled` reducer, lines 241-247: delete the whole reducer.
- `startAtToggled` reducer, line 251: delete `state.screenMenuOpen = false;`, leaving
  `state.startAtOpen = !state.startAtOpen; if (state.startAtOpen) { state.airportMenuOpen = false; }`.
- Export list, line 379: delete `screenMenuToggled,`.

**`ui/src/features/position/position.css`**
- Delete the whole `.pos-header__menu-trigger { ... }` rule (lines 138-147).
- Delete `.pos-screenmenu { ... }` (lines 244-247), `.pos-screenmenu__list { ... }` (249-255), and
  `.pos-screenmenu__item` / `:hover` (257-270). Leave `.pos-popover` (233-242, shared with
  `AirportMenu` and `StartAtPopover`) and `.pos-startat` (272-278) untouched.
- Add the scoped override block described in §7.3.

**`ui/src/features/position/positionDesignSlice.test.ts`**
- Remove `screenMenuToggled` from the import at line 13.
- Rewrite the `describe('screenMenuToggled / startAtToggled', ...)` block (lines 77-84). It
  currently asserts opening the screen menu closes `startAtOpen`/`airportMenuOpen` and vice versa.
  Replace with a `describe('airportMenuOpened / startAtToggled', ...)` pair asserting the
  remaining two-member exclusivity: `airportMenuOpened()` sets `airportMenuOpen: true,
  startAtOpen: false`; `startAtToggled()` toggles `startAtOpen` and, when opening, sets
  `airportMenuOpen: false`.

**`ui/src/features/position/PositionHeaderBar.test.tsx`**
- Remove the `import { TABS } from '../../components/tabs';` if it becomes otherwise unused
  (it is still needed for the rewritten assertions below, so keep it).
- Rewrite `describe('the screen menu', ...)` (lines 26-47). It currently opens the popover via
  `getByRole('button', { name: /^Position/ })` then asserts `menuitem` entries. Replace with a
  `describe('the module tab bar', ...)` block:
  - "renders every module as a tab": assert `screen.getAllByRole('tab')` has length
    `TABS.length` (12), and that each `tab.label` is present via
    `getByRole('tab', { name: tab.label })`.
  - "switches the module tab — it is the only way off a full-bleed screen": click
    `getByRole('tab', { name: 'Weather' })` directly (no popover open step) and assert
    `store.getState().ui.activeTab === 'weather'`.

**`ui/src/App.test.tsx`** (the important one — a repo-wide grep for `ScreenMenu`/`screenMenu`
does **not** find this file, because it never names the popover; it only asserts the tablist's
*absence*, which this change inverts)
- Update the file's top docstring (lines 1-5): it currently says "no header/tabbar, no status
  bar" for full-bleed Position. Correct it to say the *shell's* header/tabbar and status bar are
  hidden, but the Position screen embeds its own copy of the same tab bar.
- In `'hides the module tab bar and the status bar while Position is active'` (lines 17-29): the
  assertion `expect(screen.queryByRole('tablist', { name: 'Instructor station modules' }))
  .not.toBeInTheDocument()` must become a **positive** assertion, and must be awaited because
  `PositionPanel` is a lazy chunk (`React.lazy` + `Suspense`) — a synchronous `queryByRole` would
  pass trivially before the chunk resolves, whether or not the change worked. Replace with:
  ```ts
  expect(
    await screen.findByRole('tablist', { name: 'Instructor station modules' }),
  ).toBeInTheDocument();
  ```
  Rename the test to something like `'embeds the module tab bar and hides the status bar while
  Position is active'`. The `status` role assertion (line 28) is unaffected and stays as-is.
- The second test (`'keeps the map tabpanel mounted...'`, lines 31-50) is unaffected — it drives
  `tabSelected` directly via the store, not through either tab bar's DOM, so its mechanism is
  untouched. No change needed there beyond what the file-level docstring fix already covers.

**Files confirmed untouched** (shared foundation — this is a single-manager, single-branch
change and none of these are edited): `ui/src/components/TabBar.tsx`, `ui/src/components/tabs.ts`,
`ui/src/index.css`, `ui/src/store/uiSlice.ts`, `ui/src/App.tsx`. The one line in `App.tsx` worth
naming explicitly rather than silently leaving alone: line 91,
`aria-labelledby={fullBleed && active ? undefined : \`tab-${tab.id}\`}`. That branch exists
because `tab-position` did not exist in the DOM while full-bleed (the shell's `TabBar` was the
only place `tab-${id}` ids were rendered). After this change, `tab-position` *does* exist — the
Position screen's own embedded `TabBar` renders `id="tab-position"` whenever Position is active.
The special case is therefore vestigial: the active Position tabpanel would end up correctly
labelled either way. **Decision: leave `App.tsx` untouched.** Simplifying the branch is a
correct, in-scope micro-cleanup but touches the shared shell file for a change that is not
required to close #154; folding it in either muddies a single-manager PR with a shell-file edit
or requires the reviewer to separately verify a shell-wide invariant. If the implementer wants it,
it should be a one-line follow-up PR against `App.tsx` alone, reviewed as a shell change, not
bundled here.

### 7.3 CSS overrides — exact blocks

Two problems, both established by reading the actual CSS rather than assuming:

**(a) Two competing `flex: 1` elements.** `.pos-header` is `display:flex; align-items:center;
gap:0.75rem` with no wrap. `.pos-header__spacer` is `flex: 1` and is what currently pushes the
demo badge / connection dot / theme toggle to the right edge. `.tabbar` (shared, `index.css:180`)
is *also* `flex: 1; min-width: 0`. Embedding it verbatim gives two greedy elements splitting the
header's extra space, which is not what either was designed to do alone. **Decision:** scope an
override so the embedded tab bar does not compete with the spacer:
```css
.pos-header .tabbar {
  flex: 0 1 auto;
}
```
`min-width: 0` and `overflow-x: auto` are inherited from the shared `.tabbar` rule unchanged, so
the strip still shrinks below its content width and scrolls internally rather than forcing the
header to overflow or wrap.

**(b) Every other header sibling defaults to `flex-shrink: 1`.** Nothing in `.pos-header__airport`,
`.pos-header__startat-trigger`, or `.pos-header__connection` sets `flex-shrink: 0` today — that
was safe when the only leading element was a fixed-width button, but a shrinkable 12-tab strip
next to them means the airport-name text and the connection-status text would shrink and wrap/clip
before the tab strip gives up any space, which is backwards: the tab strip is the one element with
its own internal scroll mechanism built for exactly this. **Decision:** pin the other clusters so
the tab bar is the *only* element that yields width:
```css
.pos-header__airport,
.pos-header__startat-trigger,
.pos-header__connection {
  flex: none;
}
```

**(c) Colour/token mismatch.** The shared `.tabbar__tab` rule (`index.css:190-213`) is styled with
the app shell's global tokens — `--text`, `--text-dim`, `--accent` (`#e8a33d`, amber), `--border`,
`--focus`. The Position screen is a deliberately separate visual system scoped under `.pos`
(`position.css:1-7`): its own green accent (`--pos-accent`, `oklch(0.72 0.16 145)` dark /
`oklch(0.5 0.13 145)` light), its own text tones (`--pos-t1`/`--pos-t2`), its own focus colour
(`--pos-focus`). `PositionHeaderBar` renders inside the `.pos` scope (`PositionPanel.tsx` wraps it
in `<div className="pos">`), so the global tokens the shared rule references are still resolvable
(they're defined at `:root`/`[data-theme]`) — the strip would render, but in the shell's amber
instead of Position's green, which is the exact inconsistency the v3 redesign's "own tokens"
rule exists to prevent. **Decision:** remap, scoped, without touching the shared rule or file:
```css
.pos-header .tabbar__tab {
  color: var(--pos-t2);
}

.pos-header .tabbar__tab:hover {
  color: var(--pos-t1);
}

.pos-header .tabbar__tab[aria-selected='true'] {
  color: var(--pos-t1);
  border-bottom-color: var(--pos-accent);
}

.pos-header .tabbar__tab:focus-visible {
  outline-color: var(--pos-focus);
}
```
Font family needs no override: `.pos` sets `font-family: 'Schibsted Grotesk', ...` at the
container level and `.tabbar__tab` does not set its own, so it inherits correctly already.
Touch-target height (`min-height: 44px` on `.tabbar__tab`, `index.css:191`) already matches the
44px convention used throughout `position.css` and fits inside the 64px `.pos-header` — no
override needed there.

All four blocks above go in `position.css`, appended near the existing `.pos-header*` rules
(replacing the deleted `.pos-header__menu-trigger` block's former location is a reasonable spot),
so the file that owns the Position screen's chrome is the only file touched for styling — nothing
in `index.css` changes.

### 7.4 Layout verdict (issue decision #1)

Explicitly: **the tab bar does not fit unscrolled next to the airport/start-at/connection
cluster, at any width this app targets, and that is fine.** A rough budget: 12 labels including
"Landing analysis" and "Fuel & payload" at the shared rule's `padding: 0 1rem` plus `gap: 2px`
sums to roughly 1150-1250px of natural content width before a single pixel of the airport cluster,
start-at trigger, or connection/theme cluster (together another ~500-650px) is counted. No wrap is
used — `.pos-header` stays a single non-wrapping flex row, matching how every other screen's shell
`TabBar` behaves. The existing `overflow-x: auto; scroll-snap-type: x proximity` on `.tabbar`
(unmodified, shared) is therefore the **normal** operating mode on Position, not a rare tablet
fallback: expect the strip to be scrolled on both tablet and most desktop widths. This is
consistent with the issue's own framing ("shared horizontal TabBar with scroll-snap for tablet
widths") and requires no new scroll affordance beyond what `TabBar.tsx` already implements.

### 7.5 State — no new slice, no new fields beyond the removals above

This change adds no Redux state. It removes one field (`screenMenuOpen`) from the existing
`positionDesign` slice (state shape and reducers listed in the edit list, §7.2). `TabBar`'s own
state dependency (`state.ui.activeTab`, `tabSelected` on `uiSlice`) is unchanged and already
exercised by every non-Position screen.

### 7.6 Capability gating

None of `TABS`' 12 entries are gated by an adapter capability flag — the tab bar shows every
module regardless of the connected adapter's `Capabilities` (unsupported *actions inside* a panel
are what get disabled, per `ComingSoonPanel` for panels with no `load` yet, and per-control
capability gates inside each panel). This change does not alter that: it changes only which
DOM element renders the same always-visible tab list, not which tabs are shown.

## 8. Test plan

### 8.1 `core/` unit tests

N/A — UI-only change, no backend surface, no `core/` module touched.

### 8.2 Contract tests

N/A — no `SimAdapter`/`Capabilities` change, so `tests/adapters/test_contract.py` is untouched.

### 8.3 `@pytest.mark.sim`

N/A — no Python code is touched by this design; nothing here can affect a live-sim marked test.

### 8.4 UI test plan (the real test plan for this issue)

Run with `cd ui && npm run lint && npm run typecheck && npm test && npm run build`. Concretely:

- **`positionDesignSlice.test.ts`** — updated per §7.2: `airportMenuOpened` still closes
  `startAtOpen`; `startAtToggled` still closes `airportMenuOpen` on open. No assertion should
  reference `screenMenuOpen` or `screenMenuToggled` after the edit — a residual reference would
  fail `typecheck` immediately since the export no longer exists, which is the tightest possible
  check that the removal is complete.
- **`PositionHeaderBar.test.tsx`** — updated per §7.2: 12 tabs render with the correct labels
  (`getAllByRole('tab')` length assertion pins the count so a future `tabs.ts` edit that silently
  drops one is caught here too, incidentally); clicking a tab sets `ui.activeTab` with no popover
  step. The airport-loading and theme-toggle `describe` blocks in the same file are unaffected —
  they exercise other parts of `PositionHeaderBar` and should be left as-is; re-run them to
  confirm no incidental breakage from the removed `useRef`/import.
- **`App.test.tsx`** — updated per §7.2: the full-bleed test now asserts the tablist *is* present
  (via `findByRole`, awaited past the lazy chunk) while `status` remains absent. This is the one
  test in the repo whose entire premise inverts under this change, and it is not discoverable by
  grepping for `ScreenMenu` — treat it as a required edit, not an optional follow-up.
- **Manual/visual check** (per the user's own global instruction to verify web UI work with the
  `cloudflare-browser` MCP before calling the change done): load the Position screen at a real
  ICAO, confirm the 12-tab strip renders in Position's green accent (not shell amber), confirm it
  scrolls horizontally without breaking the header's 64px height or displacing the connection/
  theme cluster, click a tab and confirm the corresponding panel mounts, click back to the
  `Position` tab and confirm the screen returns full-bleed with its own tab bar still visible.
  Check the browser console for any React key/duplicate-id warnings from having two `TabBar`
  mount points across a session (there is never more than one in the DOM at once per §7.1, but a
  fast tab-switch during a lazy-chunk transition is the one edge worth eyeballing).
- No `screen.getByRole('menu')`/`menuitem` query should remain anywhere in `ui/src` after this
  change — a `grep -R "ScreenMenu\|screenMenuOpen\|pos-screenmenu" ui/src` returning empty is the
  acceptance check for the removal being complete.

### 8.5 Fixture strategy

N/A — no navdata, no fixtures beyond the existing `testFixtures.ts`/`testApi.ts` already used by
`PositionHeaderBar.test.tsx`, which are reused unchanged.

## 9. Parallelisation

This is a **single, small, single-manager change** confined to `ui/src/features/position/*` plus
one shared-but-read-only import (`TabBar` from `ui/src/components/`, not modified). There is no
backend/UI split to parallelise (§2-6 are all N/A) and no independent sub-track worth splitting
across agents — one implementer, one branch, one PR.

- **Branch:** already on `feature/position-tabbar-header` per the worktree this design was
  written in.
- **Owns (edits):** `ui/src/features/position/PositionHeaderBar.tsx`,
  `ui/src/features/position/ScreenMenu.tsx` (delete),
  `ui/src/features/position/positionDesignSlice.ts`,
  `ui/src/features/position/position.css`,
  `ui/src/features/position/positionDesignSlice.test.ts`,
  `ui/src/features/position/PositionHeaderBar.test.tsx`,
  `ui/src/App.test.tsx`.
- **Reads only, never edits:** `ui/src/components/TabBar.tsx`, `ui/src/components/tabs.ts`,
  `ui/src/index.css`, `ui/src/App.tsx`, `ui/src/store/uiSlice.ts`,
  `docs/designs/position-redesign-v3.md`.
- **Never parallelise:** N/A here — there is no `SimAdapter`/`Capabilities` change, no navdata
  schema migration, and no reason to split this into concurrent workers. If a tester wants to
  write the updated test files while the implementer edits the components, that is safe to do
  concurrently since the edit list in §7.2/§8.4 fully specifies both sides — but given the size
  of this change, doing it as one pass is more efficient than coordinating a two-agent handoff.

## 10. Open questions and risks

1. **`App.tsx:91`'s vestigial branch.** Documented as "leave untouched" in §7.2 with the
   reasoning; flagging again here because it is a judgement call, not a fact — a reviewer could
   reasonably prefer the one-line simplification bundled into this PR instead of a follow-up.
   Resolves by: implementer's/reviewer's call at PR time; either answer is safe, neither changes
   behaviour observably.
2. **Exact pixel width before the tab strip needs to scroll.** §7.4's ~1150-1250px estimate is
   arithmetic from `padding`/`gap`/label-length, not a measurement in a rendered browser. It is
   enough to confirm the *decision* (rely on scroll, do not attempt to fit unscrolled) but not
   precise enough to promise a specific breakpoint where scrolling starts. Resolves by: the
   manual visual check in §8.4 (cloudflare-browser at a couple of viewport widths, e.g. 1280px and
   1920px) during implementation, not by more arithmetic here.
3. **Whether Position's tab bar should default-scroll to keep the `position` tab itself visible
   on load**, given `scroll-snap-type: x proximity` and `TabBar.tsx` doing no explicit
   `scrollIntoView` on mount. This is an existing property of the shared `TabBar` component (not
   introduced by this change) but it will be *newly visible* on the one screen where the active
   tab is always the leftmost item (`position` is `TABS[0]`), so it is very likely never an issue
   here specifically — flagging only because it was not verified empirically against a live
   render. Resolves by: the same manual check in §8.4; if it turns out to be a real problem it is
   a `TabBar.tsx` change and therefore out of scope for this manager (shared file, would need its
   own small design note since every screen's tab bar would be affected, not just Position's).
4. **Known architecture risk this manager touches:** none of the risks listed in
   `docs/architecture.md` (navdata pipeline, dataref resolution, sim lifecycle) apply — this
   change has no reachable path to any of them.
