/**
 * Pure math for the 3D view's OSM ground texture (#178): recovering the scene origin's
 * lat/lon, the ground plane's geographic bounding box, a polite zoom level, and the exact
 * slippy-map tile mosaic (with its crop rect) that covers that bbox. No DOM, no network —
 * everything here runs and is tested under jsdom; the fetch-and-stitch that *uses* a
 * `TileMosaic` lives in `useGroundTexture.ts` behind an injectable seam.
 *
 * Geographic conventions match the layout this all georeferences
 * (`core/procedure_layout.py`): the scene frame is NM, north-aligned, origin at the layout
 * anchor, and the planar approximation is equirectangular — 1 NM = 1 arcminute of latitude,
 * 1 NM = 1/cos(lat) arcminutes of longitude. The tiles are *context*, not data (the stance
 * `AirportDiagram.tsx` already takes), so the ~0.7% Mercator-vs-linear N–S drift across a
 * half-degree span is accepted rather than resampled away.
 */

import type { ProcedureLayout } from '../../api/models';
import type { GroundPlaneFootprint } from './procedureScene';

export interface LatLon {
  readonly latitude: number; // degrees, WGS84, positive north
  readonly longitude: number; // degrees, WGS84, positive east
}

export interface GeoBBox {
  readonly west: number;
  readonly south: number;
  readonly east: number;
  readonly north: number; // degrees
}

export interface TileMosaic {
  readonly zoom: number;
  /** Inclusive integer tile ranges of the stitched grid. */
  readonly minTileX: number;
  readonly maxTileX: number;
  readonly minTileY: number;
  readonly maxTileY: number;
  /** The bbox's exact pixel rect inside the stitched grid (256 px/tile) — the crop that
   *  makes the canvas correspond 1:1 to the ground plane's own footprint. */
  readonly cropX: number;
  readonly cropY: number;
  readonly cropWidth: number;
  readonly cropHeight: number;
}

export const EARTH_CIRCUMFERENCE_M = 40075016.686;
export const TILE_SIZE_PX = 256;
/** How many tiles the bbox's larger span should roughly cover — the resolution target. */
export const TARGET_TILES_ACROSS = 6;
export const MIN_ZOOM = 10;
export const MAX_ZOOM = 17;
/**
 * Politeness cap toward the OSM tile policy — one composite is a burst of at most 64 tile
 * requests, once per airport per session, comparable to one map-panel pan. This cap wins
 * over `MIN_ZOOM` (a coarser-than-minimum picture beats an impolite burst).
 */
export const MAX_TILES = 64;

const METRES_PER_NM = 1852;
const NM_PER_DEGREE = 60;

/**
 * Real-world position of drawn (0, 0). `null` unless `layout.anchor === 'runway'`: only
 * then is `airport_x_nm`/`airport_y_nm` a short, uncompressed **true** offset from the
 * origin to the ARP (see `core/procedure_layout.py`), so the inverse is trustworthy. A
 * `last_fix` layout's ARP offset is one further *capped* segment — no texture for those.
 */
export function sceneOrigin(
  layout: Pick<ProcedureLayout, 'anchor' | 'airport_x_nm' | 'airport_y_nm'>,
  arp: LatLon,
): LatLon | null {
  if (layout.anchor !== 'runway') {
    return null;
  }
  const latitude = arp.latitude - layout.airport_y_nm / NM_PER_DEGREE;
  const longitude =
    arp.longitude -
    layout.airport_x_nm / (NM_PER_DEGREE * Math.cos((latitude * Math.PI) / 180));
  return { latitude, longitude };
}

/** The lat/lon rectangle under the ground plane's exact footprint (scene z = −north). */
export function footprintBBox(footprint: GroundPlaneFootprint, origin: LatLon): GeoBBox {
  const cosLat = Math.cos((origin.latitude * Math.PI) / 180);
  // Scene z is south-positive: the footprint's north edge is its *smaller* z.
  const north =
    origin.latitude + (footprint.depthNm / 2 - footprint.centerZ) / NM_PER_DEGREE;
  const south =
    origin.latitude - (footprint.centerZ + footprint.depthNm / 2) / NM_PER_DEGREE;
  const west =
    origin.longitude +
    (footprint.centerX - footprint.widthNm / 2) / (NM_PER_DEGREE * cosLat);
  const east =
    origin.longitude +
    (footprint.centerX + footprint.widthNm / 2) / (NM_PER_DEGREE * cosLat);
  return { west, south, east, north };
}

/** How many tiles `mosaicFor(bbox, zoom)` would fetch. */
function tileCount(bbox: GeoBBox, zoom: number): number {
  const mosaic = mosaicFor(bbox, zoom);
  return (
    (mosaic.maxTileX - mosaic.minTileX + 1) * (mosaic.maxTileY - mosaic.minTileY + 1)
  );
}

/**
 * `floor(log2(EARTH_CIRCUMFERENCE_M · cos(lat) · TARGET_TILES_ACROSS / spanM))`, clamped to
 * `[MIN_ZOOM, MAX_ZOOM]`, then decremented while the mosaic would exceed `MAX_TILES`.
 */
export function pickZoom(bbox: GeoBBox): number {
  const midLatRad = (((bbox.north + bbox.south) / 2) * Math.PI) / 180;
  const cosLat = Math.cos(midLatRad);
  const widthM = (bbox.east - bbox.west) * NM_PER_DEGREE * METRES_PER_NM * cosLat;
  const heightM = (bbox.north - bbox.south) * NM_PER_DEGREE * METRES_PER_NM;
  const spanM = Math.max(widthM, heightM);
  const ideal = Math.floor(
    Math.log2((EARTH_CIRCUMFERENCE_M * cosLat * TARGET_TILES_ACROSS) / spanM),
  );
  let zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, ideal));
  while (zoom > 0 && tileCount(bbox, zoom) > MAX_TILES) {
    zoom -= 1;
  }
  return zoom;
}

/** Slippy-map fractional tile x: `(lon + 180) / 360 · 2^z`. */
export function tileX(lonDeg: number, zoom: number): number {
  return ((lonDeg + 180) / 360) * 2 ** zoom;
}

/** Slippy-map fractional tile y: `(1 − asinh(tan lat) / π) / 2 · 2^z`. */
export function tileY(latDeg: number, zoom: number): number {
  const latRad = (latDeg * Math.PI) / 180;
  return ((1 - Math.asinh(Math.tan(latRad)) / Math.PI) / 2) * 2 ** zoom;
}

/** The tile grid covering `bbox` at `zoom`, with the bbox's crop rect inside it. */
export function mosaicFor(bbox: GeoBBox, zoom: number): TileMosaic {
  const xMin = tileX(bbox.west, zoom);
  const xMax = tileX(bbox.east, zoom);
  const yMin = tileY(bbox.north, zoom); // north edge → smaller tile y
  const yMax = tileY(bbox.south, zoom);

  const minTileX = Math.floor(xMin);
  const maxTileX = Math.floor(xMax);
  const minTileY = Math.floor(yMin);
  const maxTileY = Math.floor(yMax);

  return {
    zoom,
    minTileX,
    maxTileX,
    minTileY,
    maxTileY,
    cropX: Math.round((xMin - minTileX) * TILE_SIZE_PX),
    cropY: Math.round((yMin - minTileY) * TILE_SIZE_PX),
    cropWidth: Math.max(1, Math.round((xMax - xMin) * TILE_SIZE_PX)),
    cropHeight: Math.max(1, Math.round((yMax - yMin) * TILE_SIZE_PX)),
  };
}

export function osmTileUrl(zoom: number, x: number, y: number): string {
  return `https://tile.openstreetmap.org/${String(zoom)}/${String(x)}/${String(y)}.png`;
}

/**
 * Primitive string — the module cache key AND the hook's effect key, so effects never key
 * on object identity (`buildProcedureScene` runs unmemoized every render).
 *
 * The crop rect is part of the key on purpose, one step past the design's
 * `"11/1003-1007/770-773"` example: two procedures at the same airport routinely share a
 * whole tile range (a z=11 tile is ~20 km) while differing in crop by pixels, and a bare
 * tile-range key would silently hand the second one the first one's cropped canvas — a
 * misaligned texture with no error anywhere.
 */
export function mosaicCacheKey(mosaic: TileMosaic): string {
  return (
    `${String(mosaic.zoom)}/${String(mosaic.minTileX)}-${String(mosaic.maxTileX)}` +
    `/${String(mosaic.minTileY)}-${String(mosaic.maxTileY)}` +
    `@${String(mosaic.cropX)},${String(mosaic.cropY)}` +
    `,${String(mosaic.cropWidth)}x${String(mosaic.cropHeight)}`
  );
}

const CACHE_KEY_PATTERN = /^(\d+)\/(\d+)-(\d+)\/(\d+)-(\d+)@(\d+),(\d+),(\d+)x(\d+)$/;

/**
 * The exact inverse of `mosaicCacheKey` — possible precisely because the crop rect is in
 * the key, which makes the key the mosaic's complete description. `useGroundTexture`'s
 * effect depends only on this primitive and re-derives the `TileMosaic` from it, instead of
 * closing over a per-render mosaic object (writing one into a ref during render is what
 * `react-hooks/refs` forbids).
 */
export function mosaicFromCacheKey(key: string): TileMosaic {
  const match = CACHE_KEY_PATTERN.exec(key);
  if (match === null) {
    throw new Error(`Not a mosaic cache key: ${key}`);
  }
  const [, zoom, minTileX, maxTileX, minTileY, maxTileY, cropX, cropY, cropWidth, cropHeight] =
    match;
  return {
    zoom: Number(zoom),
    minTileX: Number(minTileX),
    maxTileX: Number(maxTileX),
    minTileY: Number(minTileY),
    maxTileY: Number(maxTileY),
    cropX: Number(cropX),
    cropY: Number(cropY),
    cropWidth: Number(cropWidth),
    cropHeight: Number(cropHeight),
  };
}
