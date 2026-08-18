/**
 * jsdom stand-in for `maplibre-gl`, for `vi.mock('maplibre-gl', …)` in panel tests.
 *
 * The real library needs WebGL, which jsdom does not have. The stub's `Map` accepts
 * every call the hooks make and — deliberately — never fires an event on its own:
 * `useMapLibre` then keeps its `map` state at `null`, so every imperative consumer
 * (overlays, marker, interactions) stays dormant by construction and the tests
 * exercise only the chrome and the Redux dispatches, which is where the panel's
 * logic lives.
 *
 * `on`/`once` do, however, *record* their handlers, and the test-only
 * `trigger(event, payload)` fires them — so a test that wants to exercise the
 * drag/click wiring itself (a `dragend` on the aircraft marker, a `click` on the
 * canvas) can reach the constructed instance through `Map.created` /
 * `Marker.created` and fire the event by hand. The registries are cleared
 * automatically by the shared `afterEach` in `setup.ts`.
 */

/** A handler registered through the stub's `on`/`once`. */
type StubListener = (payload?: unknown) => void;

interface Registration {
  listener: StubListener;
  once: boolean;
}

/**
 * Shared event recording for the stub's `Map` and `Marker`.
 *
 * Handlers are keyed by event name and never fired by the stub itself —
 * `trigger` is the test's explicit hand on the wheel, not part of maplibre's API.
 */
class StubEvented {
  private registrations: Record<string, Registration[]> = {};

  on(event: string, listener: StubListener): this {
    this.register(event, listener, false);
    return this;
  }

  once(event: string, listener: StubListener): this {
    this.register(event, listener, true);
    return this;
  }

  off(event: string, listener: StubListener): this {
    this.registrations[event] = (this.registrations[event] ?? []).filter(
      (registration) => registration.listener !== listener,
    );
    return this;
  }

  /**
   * Test helper — NOT part of maplibre's API. Fires every handler recorded for
   * `event`, in registration order, passing `payload` to each. `once` handlers
   * are dropped before they run, matching the real library's semantics.
   */
  trigger(event: string, payload?: unknown): void {
    const fired = this.registrations[event] ?? [];
    this.registrations[event] = fired.filter((registration) => !registration.once);
    for (const { listener } of fired) {
      listener(payload);
    }
  }

  private register(event: string, listener: StubListener, once: boolean): void {
    (this.registrations[event] ??= []).push({ listener, once });
  }
}

export class Map extends StubEvented {
  /** Every instance constructed since the last `resetMaplibreStub()`. */
  static created: Map[] = [];

  constructor() {
    super();
    Map.created.push(this);
  }

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

export class Marker extends StubEvented {
  /** Every instance constructed since the last `resetMaplibreStub()`. */
  static created: Marker[] = [];

  constructor() {
    super();
    Marker.created.push(this);
  }

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

/** Clear both instance registries. Call in `beforeEach` when a test reads them. */
export function resetMaplibreStub(): void {
  Map.created.length = 0;
  Marker.created.length = 0;
}

export default { Map, Marker };
