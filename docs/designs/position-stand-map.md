# Position — stand/gate picker from the bottom bar, on a real map

Issue #166. Two changes, one feature: the "Start at" popover gains a second entry point in
the bottom bar, and its airport diagram becomes a zoomable MapLibre map with OpenStreetMap
raster tiles under the airport's own navdata.

## Two anchors, one popover

The instructor configuring the aircraft in the bottom bar (flaps, gear, overrides) should
not have to travel back to the header to change the parking spot. Instead of a second
surface to keep in sync, the **same `StartAtPopover` component is mounted twice** — once by
`PositionHeaderBar`, once by `BottomBar` — and `positionDesignSlice` decides which instance
renders:

- `startAtAnchor: 'header' | 'bottombar'` sits next to the existing `startAtOpen`.
- `startAtToggled(anchor)` toggles as before, with one twist: fired from the *other*
  trigger while open, it moves the popover instead of closing it.
- Each instance gets an anchor-suffixed id (`pos-startat-popover-header` / `-bottombar`),
  so each trigger's `aria-controls` points at its own dialog.
- The bottom-bar instance floats *above* its trigger (`.pos-startat--above`); the header's
  hangs below, unchanged.

`Popover`'s outside-close listens on **`pointerdown`, not `click`** — with `click`, the
outgoing popover's stale document listener and the other trigger's own handler fire on the
same event and cancel each other out, so the popover never actually moved. `pointerdown`
lands first: the old instance closes, then the trigger's `click` opens the new one.

## The diagram is a map now

`AirportDiagram` keeps its props (`stands`, `runways`, `selectedStand`, `onSelect`) and its
place in the popover, but renders a MapLibre map fitted to the airport's extent (stands +
runway thresholds), with wheel/drag/± navigation. `useMapLibre` — shared with the
Instructor Map — grew a construction-time options object (`bounds`, `fitPadding`,
`fitMaxZoom`, `navigation`, `compactAttribution`); options are read once, so a re-render
never tears the map down.

**Stands and runway labels are DOM overlays, not MapLibre markers or symbol layers**:

- The style has no glyph server — the app must run on a LAN with nothing but a tile cache —
  so a `symbol` layer could not draw "04L" at all. Runway idents and stand buttons are
  absolutely-positioned React elements, re-projected through `map.project()` on every
  camera `move`.
- A React `<button>` keeps the 44px tap target, `aria-pressed`, and the jsdom tests. In
  jsdom (and before the style loads) the map is `null` and the same elements fall back to
  the pure `standProjection.ts` fit, so the picker works with no tiles at all.
- The runway strips are the exception: one GeoJSON `line` layer, because a strip is a line
  on the ground and must stay glued to the tiles at every zoom.

The tiles are context, not data: aprons and terminals come from OSM (attribution kept,
compact), the clickable stands come from `apt.dat`, and only a stand *name* ever reaches
the server.

## Things learned the hard way

- **Real apt.dat parking names repeat.** LFMN publishes dozens of stands all named
  "Apron K parking". Keying the overlay buttons and list rows by name alone corrupted
  React's reconciliation (stale buttons stopped following the camera); keys are
  `name#index` now, and a test renders a duplicate-name fixture and fails on the
  duplicate-key console error.
- **A hidden tab freezes MapLibre entirely.** Everything after the constructor rides on
  `requestAnimationFrame`, so under an occluded dev window the map never fires `load` and
  the overlay sits on the fallback projection. That is the browser, not a bug — noted in
  `useMapLibre` so nobody "fixes" it.
- On a short viewport (1280×800 tablet) the bottom bar wraps taller and the popover's
  sidebar — the only column without its own height cap — pushed the top edge off-screen;
  a `max-height` + scroll on the sidebar under `max-height: 820px` keeps the 44px rows.
