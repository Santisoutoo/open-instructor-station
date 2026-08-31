/**
 * Loads the one static OSM raster composite under the 3D view's ground plane (#178) and
 * wraps it in a three.js `CanvasTexture`.
 *
 * The injectable seam is the whole fetch-and-stitch, `loadOsmComposite`: it cannot run in
 * jsdom (images never load; `getContext('2d')` returns `null` — `usePosThemePalette`'s
 * docstring already records that), so tests inject a fake `CompositeLoader` and everything
 * above the seam — status transitions, caching, eviction, disposal — is fully testable.
 * The function itself is covered by `groundTexture.ts`'s pure tile math plus the live
 * browser check.
 *
 * **Effects key on `mosaicCacheKey(...)` — a primitive — never on object identity.**
 * `buildProcedureScene` runs unmemoized every render, so `extents` is a fresh object each
 * time; keying on it would refire the effect per render. (The module cache would make
 * refires harmless anyway; the string key makes them not happen.)
 *
 * **Cache**: module-level `Map<string, Promise<HTMLCanvasElement>>`. One in-flight promise
 * dedupes concurrent mounts; the canvas survives 2D↔3D remounts and procedure switches for
 * the whole session — "fetched once per airport/procedure extent". A rejected promise is
 * evicted on rejection, so a later remount retries (connectivity may have returned).
 * Unbounded across airports is accepted: a session touches a handful of airports, each
 * composite a few MB of canvas. The browser HTTP cache keeps the underlying tiles warm
 * across sessions — the same tiles the map panel already fetches.
 */

import { useEffect, useState } from 'react';
import { CanvasTexture, SRGBColorSpace } from 'three';
import {
  TILE_SIZE_PX,
  footprintBBox,
  mosaicCacheKey,
  mosaicFor,
  mosaicFromCacheKey,
  osmTileUrl,
  pickZoom,
  type LatLon,
  type TileMosaic,
} from './groundTexture';
import { groundPlaneFootprint, type SceneExtents } from './procedureScene';

export type GroundTextureStatus = 'unavailable' | 'loading' | 'ready' | 'error';
export type CompositeLoader = (mosaic: TileMosaic) => Promise<HTMLCanvasElement>;

/** Per-tile budget: a hung request must not hold the whole composite open forever. */
const TILE_TIMEOUT_MS = 10_000;

/** One tile as an `Image`, CORS-enabled. `crossOrigin = 'anonymous'` is mandatory and must
 *  be set before `src`: an un-CORS'd image taints the canvas, and the WebGL texture upload
 *  then throws a `SecurityError` — a much worse failure than a missing texture. */
function loadTile(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.crossOrigin = 'anonymous';
    const timer = window.setTimeout(() => {
      reject(new Error(`OSM tile timed out: ${url}`));
    }, TILE_TIMEOUT_MS);
    image.onload = () => {
      window.clearTimeout(timer);
      resolve(image);
    };
    image.onerror = () => {
      window.clearTimeout(timer);
      reject(new Error(`OSM tile failed to load: ${url}`));
    };
    image.src = url;
  });
}

/**
 * The default `CompositeLoader`: fetches every tile in the mosaic (all-or-nothing) and
 * stitches them onto one canvas sized `cropWidth × cropHeight`, so the canvas corresponds
 * exactly to the ground plane's bbox. `navigator.onLine === false` is the cheap offline
 * path — an immediate reject instead of a burst of doomed requests (an *unknown* onLine
 * fails open and attempts the fetch).
 */
export async function loadOsmComposite(mosaic: TileMosaic): Promise<HTMLCanvasElement> {
  if (navigator.onLine === false) {
    throw new Error('Offline — no OSM composite.');
  }
  const loads: Promise<{ x: number; y: number; image: HTMLImageElement }>[] = [];
  for (let x = mosaic.minTileX; x <= mosaic.maxTileX; x += 1) {
    for (let y = mosaic.minTileY; y <= mosaic.maxTileY; y += 1) {
      loads.push(
        loadTile(osmTileUrl(mosaic.zoom, x, y)).then((image) => ({ x, y, image })),
      );
    }
  }
  const tiles = await Promise.all(loads);

  const canvas = document.createElement('canvas');
  canvas.width = mosaic.cropWidth;
  canvas.height = mosaic.cropHeight;
  const context = canvas.getContext('2d');
  if (context === null) {
    throw new Error('No 2D canvas context for the OSM composite.');
  }
  for (const { x, y, image } of tiles) {
    context.drawImage(
      image,
      (x - mosaic.minTileX) * TILE_SIZE_PX - mosaic.cropX,
      (y - mosaic.minTileY) * TILE_SIZE_PX - mosaic.cropY,
    );
  }
  return canvas;
}

const compositeCache = new Map<string, Promise<HTMLCanvasElement>>();

/** The cached composite for `key`, starting (and registering) the load on a miss. A
 *  rejected entry evicts itself, so the next mount retries instead of replaying failure. */
function cachedComposite(
  key: string,
  mosaic: TileMosaic,
  loadComposite: CompositeLoader,
): Promise<HTMLCanvasElement> {
  const existing = compositeCache.get(key);
  if (existing !== undefined) {
    return existing;
  }
  const promise = loadComposite(mosaic);
  compositeCache.set(key, promise);
  promise.catch(() => {
    if (compositeCache.get(key) === promise) {
      compositeCache.delete(key);
    }
  });
  return promise;
}

export function useGroundTexture(
  origin: LatLon | null,
  extents: SceneExtents,
  loadComposite: CompositeLoader = loadOsmComposite,
): { readonly texture: CanvasTexture | null; readonly status: GroundTextureStatus } {
  let key: string | null = null;
  if (origin !== null) {
    const bbox = footprintBBox(groundPlaneFootprint(extents), origin);
    key = mosaicCacheKey(mosaicFor(bbox, pickZoom(bbox)));
  }

  // Only the *outcome* lives in state, tagged with the key it answers — everything else
  // ('unavailable', 'loading', and discarding an outcome that belongs to a previous key)
  // is derived at render time below, so the effect never calls setState synchronously
  // (`react-hooks/set-state-in-effect`) and never needs to reset anything on a key change.
  const [resolved, setResolved] = useState<{
    readonly key: string;
    readonly texture: CanvasTexture | null;
    readonly status: 'ready' | 'error';
  } | null>(null);

  // The effect depends only on the primitive `key` (never on the per-render mosaic
  // object) and re-derives the mosaic from it — the key is the mosaic's complete
  // description, crop rect included.
  useEffect(() => {
    if (key === null) {
      return;
    }

    let cancelled = false;
    let texture: CanvasTexture | null = null;

    cachedComposite(key, mosaicFromCacheKey(key), loadComposite)
      .then((canvas) => {
        if (cancelled) {
          return;
        }
        texture = new CanvasTexture(canvas);
        // three r150+ does not assume sRGB for canvas textures; without this the map
        // renders visibly washed out. `flipY` stays at its default `true`: canvas row 0 is
        // north, and after `GroundPlane`'s -90° X rotation the plane's +v edge faces scene
        // north (-z), so the default orientation is the aligned one.
        texture.colorSpace = SRGBColorSpace;
        setResolved({ key, texture, status: 'ready' });
      })
      .catch(() => {
        if (!cancelled) {
          setResolved({ key, texture: null, status: 'error' });
        }
      });

    return () => {
      cancelled = true;
      texture?.dispose();
    };
  }, [key, loadComposite]);

  if (key === null) {
    return { texture: null, status: 'unavailable' };
  }
  if (resolved !== null && resolved.key === key) {
    return { texture: resolved.texture, status: resolved.status };
  }
  return { texture: null, status: 'loading' };
}
