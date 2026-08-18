/**
 * The stub itself now has behaviour (handler recording, `trigger`, instance
 * registries), so it gets the same treatment as any other module with logic:
 * a direct unit test. Everything here is what a panel test relies on when it
 * fires a `dragend`/`click` by hand.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Map, Marker, resetMaplibreStub } from './maplibreStub';

beforeEach(() => {
  resetMaplibreStub();
});

describe('maplibreStub events', () => {
  it('on() records a handler and trigger() fires it with the payload', () => {
    const map = new Map();
    const onClick = vi.fn();
    map.on('click', onClick);

    map.trigger('click', { lngLat: { lng: -3.56, lat: 40.49 } });

    expect(onClick).toHaveBeenCalledTimes(1);
    expect(onClick).toHaveBeenCalledWith({ lngLat: { lng: -3.56, lat: 40.49 } });
  });

  it('handlers are keyed by event name — a different event does not fire them', () => {
    const marker = new Marker();
    const onDragEnd = vi.fn();
    marker.on('dragend', onDragEnd);

    marker.trigger('drag');

    expect(onDragEnd).not.toHaveBeenCalled();
  });

  it('nothing fires on its own: a registered load handler stays dormant', () => {
    const map = new Map();
    const onLoad = vi.fn();
    map.once('load', onLoad);

    expect(onLoad).not.toHaveBeenCalled();
  });

  it('once() handlers fire exactly once', () => {
    const map = new Map();
    const onLoad = vi.fn();
    map.once('load', onLoad);

    map.trigger('load');
    map.trigger('load');

    expect(onLoad).toHaveBeenCalledTimes(1);
  });

  it('off(event, handler) removes exactly that handler', () => {
    const map = new Map();
    const kept = vi.fn();
    const removed = vi.fn();
    map.on('click', kept);
    map.on('click', removed);

    map.off('click', removed);
    map.trigger('click');

    expect(kept).toHaveBeenCalledTimes(1);
    expect(removed).not.toHaveBeenCalled();
  });

  it('trigger() on an event with no handlers is a no-op', () => {
    expect(() => new Map().trigger('dragstart')).not.toThrow();
  });

  it('created instances are registered and resetMaplibreStub() clears them', () => {
    const map = new Map();
    const marker = new Marker();
    expect(Map.created).toEqual([map]);
    expect(Marker.created).toEqual([marker]);

    resetMaplibreStub();

    expect(Map.created).toEqual([]);
    expect(Marker.created).toEqual([]);
  });
});
