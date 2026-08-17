/**
 * jsdom stand-in for `maplibre-gl`, for `vi.mock('maplibre-gl', …)` in panel tests.
 *
 * The real library needs WebGL, which jsdom does not have. The stub's `Map` accepts
 * every call the hooks make and — deliberately — never fires `load`: `useMapLibre`
 * then keeps its `map` state at `null`, so every imperative consumer (overlays,
 * marker, interactions) stays dormant by construction and the tests exercise only
 * the chrome and the Redux dispatches, which is where the panel's logic lives.
 */

export class Map {
  once(): void {}
  on(): void {}
  off(): void {}
  remove(): void {}
  resize(): void {}
  addSource(): void {}
  addLayer(): void {}
  getSource(): undefined {
    return undefined;
  }
  setLayoutProperty(): void {}
  zoomIn(): void {}
  zoomOut(): void {}
  easeTo(): void {}
}

export class Marker {
  setLngLat(): this {
    return this;
  }

  setRotation(): this {
    return this;
  }

  addTo(): this {
    return this;
  }

  remove(): void {}
}

export default { Map, Marker };
