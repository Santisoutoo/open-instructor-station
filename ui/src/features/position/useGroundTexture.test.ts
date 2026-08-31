/**
 * The hook above the injectable fetch-and-stitch seam (#178): status transitions, the
 * module-level promise cache (dedupe + rejected-entry eviction) and texture disposal, all
 * against a fake `CompositeLoader` — `loadOsmComposite` itself cannot run in jsdom (images
 * never load, no 2D canvas context) and is covered by `groundTexture.test.ts`'s tile math
 * plus the live browser check.
 *
 * The module cache deliberately survives for the whole session, so each test block uses its
 * own origin (≈ its own mosaic key) instead of a cache-reset hook the production API does
 * not have. Loader fakes are stable consts, so a re-render never changes the effect's
 * `loadComposite` dependency mid-test.
 */

import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CanvasTexture } from 'three';
import type { LatLon } from './groundTexture';
import type { SceneExtents } from './procedureScene';
import { useGroundTexture, type CompositeLoader } from './useGroundTexture';

const EXTENTS: SceneExtents = {
  minX: -5,
  maxX: 5,
  minZ: -10,
  maxZ: 0,
  minY: 0,
  maxY: 1,
  centerX: 0,
  centerZ: -5,
  radiusNm: 8,
};

/** Each caller gets a distinct origin → a distinct mosaic key → an isolated cache slot. */
let nextLatitude = 10;
function freshOrigin(): LatLon {
  nextLatitude += 2;
  return { latitude: nextLatitude, longitude: -3.5 };
}

const FAKE_CANVAS = { width: 64, height: 64 } as unknown as HTMLCanvasElement;

describe('useGroundTexture', () => {
  it('resolves to ready with a CanvasTexture wrapping the loaded canvas', async () => {
    const origin = freshOrigin();
    const loader: CompositeLoader = vi.fn(() => Promise.resolve(FAKE_CANVAS));

    const { result } = renderHook(() => useGroundTexture(origin, EXTENTS, loader));

    await waitFor(() => {
      expect(result.current.status).toBe('ready');
    });
    expect(result.current.texture).toBeInstanceOf(CanvasTexture);
    expect(result.current.texture?.image).toBe(FAKE_CANVAS);
    expect(result.current.texture?.colorSpace).toBe('srgb');
  });

  it('loads once for one mosaic key — the second mount reuses the cached composite', async () => {
    const origin = freshOrigin();
    const loader: CompositeLoader = vi.fn(() => Promise.resolve(FAKE_CANVAS));

    const first = renderHook(() => useGroundTexture(origin, EXTENTS, loader));
    await waitFor(() => {
      expect(first.result.current.status).toBe('ready');
    });
    first.unmount();

    const second = renderHook(() => useGroundTexture(origin, EXTENTS, loader));
    await waitFor(() => {
      expect(second.result.current.status).toBe('ready');
    });

    expect(loader).toHaveBeenCalledTimes(1);
  });

  it('reports error on a rejecting loader and evicts the entry, so a remount retries', async () => {
    const origin = freshOrigin();
    const loader: CompositeLoader = vi.fn(() => Promise.reject(new Error('offline')));

    const first = renderHook(() => useGroundTexture(origin, EXTENTS, loader));
    await waitFor(() => {
      expect(first.result.current.status).toBe('error');
    });
    expect(first.result.current.texture).toBeNull();
    first.unmount();

    const second = renderHook(() => useGroundTexture(origin, EXTENTS, loader));
    await waitFor(() => {
      expect(second.result.current.status).toBe('error');
    });

    // Two calls, not one: the rejected promise was evicted, not replayed.
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it('is unavailable with a null origin and never calls the loader', () => {
    const loader: CompositeLoader = vi.fn(() => Promise.resolve(FAKE_CANVAS));

    const { result } = renderHook(() => useGroundTexture(null, EXTENTS, loader));

    expect(result.current).toEqual({ texture: null, status: 'unavailable' });
    expect(loader).not.toHaveBeenCalled();
  });

  it('disposes the texture on unmount', async () => {
    const origin = freshOrigin();
    const loader: CompositeLoader = () => Promise.resolve(FAKE_CANVAS);

    const { result, unmount } = renderHook(() =>
      useGroundTexture(origin, EXTENTS, loader),
    );
    await waitFor(() => {
      expect(result.current.status).toBe('ready');
    });
    const texture = result.current.texture;
    expect(texture).not.toBeNull();
    const dispose = vi.spyOn(texture!, 'dispose');

    unmount();

    expect(dispose).toHaveBeenCalledTimes(1);
  });
});
