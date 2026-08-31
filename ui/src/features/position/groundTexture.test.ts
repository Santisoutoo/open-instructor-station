/**
 * Pure tile/bbox math for the OSM ground texture (#178). Reference values are the design's
 * own hand-checkable ones (§4.7.3): at z = 11, lon 0 → x = 1024.0 and lat 0 → y = 1024.0
 * exactly; lon −3.56 → tile 1003, lat 40.5 → tile 771; a 30 NM span at lat 40.5° → z = 11;
 * a 5 NM circuit → z = 14.
 */

import { describe, expect, it } from 'vitest';
import {
  MAX_TILES,
  MAX_ZOOM,
  MIN_ZOOM,
  footprintBBox,
  mosaicCacheKey,
  mosaicFor,
  mosaicFromCacheKey,
  osmTileUrl,
  pickZoom,
  sceneOrigin,
  tileX,
  tileY,
  type GeoBBox,
} from './groundTexture';
import { groundPlaneFootprint, type SceneExtents } from './procedureScene';

const ARP = { latitude: 40.5, longitude: -3.5 };

/** A bbox centred on (40.5, −3.5) spanning `heightNm` N–S and `widthNm` E–W. */
function bboxAround(widthNm: number, heightNm: number): GeoBBox {
  const halfLat = heightNm / 2 / 60;
  const halfLon = widthNm / 2 / (60 * Math.cos((40.5 * Math.PI) / 180));
  return {
    west: -3.5 - halfLon,
    east: -3.5 + halfLon,
    south: 40.5 - halfLat,
    north: 40.5 + halfLat,
  };
}

function tileCountOf(bbox: GeoBBox, zoom: number): number {
  const m = mosaicFor(bbox, zoom);
  return (m.maxTileX - m.minTileX + 1) * (m.maxTileY - m.minTileY + 1);
}

describe('sceneOrigin', () => {
  it('recovers the drawn origin from the ARP and its true offset', () => {
    const origin = sceneOrigin(
      { anchor: 'runway', airport_x_nm: 1.2, airport_y_nm: 0.9 },
      ARP,
    );
    expect(origin).not.toBeNull();
    expect(origin?.latitude).toBeCloseTo(40.485, 6);
    expect(origin?.longitude).toBeCloseTo(-3.5263, 4);
  });

  it('is the ARP itself when the offset is zero', () => {
    const origin = sceneOrigin(
      { anchor: 'runway', airport_x_nm: 0, airport_y_nm: 0 },
      ARP,
    );
    expect(origin).toEqual(ARP);
  });

  it('refuses a last_fix layout — its ARP offset is a capped segment, not a true one', () => {
    expect(
      sceneOrigin({ anchor: 'last_fix', airport_x_nm: 1.2, airport_y_nm: 0.9 }, ARP),
    ).toBeNull();
  });
});

describe('slippy-map tile math', () => {
  it('maps lon 0 / lat 0 to exactly 1024.0 at z = 11', () => {
    expect(tileX(0, 11)).toBe(1024);
    expect(tileY(0, 11)).toBe(1024);
  });

  it('puts lon −3.56 in tile 1003 and lat 40.5 in tile 771 at z = 11', () => {
    expect(Math.floor(tileX(-3.56, 11))).toBe(1003);
    expect(Math.floor(tileY(40.5, 11))).toBe(771);
  });

  it('renders the exact OSM tile URL', () => {
    expect(osmTileUrl(11, 1003, 771)).toBe(
      'https://tile.openstreetmap.org/11/1003/771.png',
    );
  });
});

describe('mosaicFor', () => {
  const bbox: GeoBBox = { west: -3.56, south: 40.4, east: -3.3, north: 40.6 };

  it('covers the bbox with the tiles its corners fall in', () => {
    const mosaic = mosaicFor(bbox, 11);
    expect(mosaic.minTileX).toBe(Math.floor(tileX(bbox.west, 11)));
    expect(mosaic.maxTileX).toBe(Math.floor(tileX(bbox.east, 11)));
    // The north edge is the *smaller* tile y.
    expect(mosaic.minTileY).toBe(Math.floor(tileY(bbox.north, 11)));
    expect(mosaic.maxTileY).toBe(Math.floor(tileY(bbox.south, 11)));
    expect(mosaic.minTileX).toBeLessThanOrEqual(mosaic.maxTileX);
    expect(mosaic.minTileY).toBeLessThanOrEqual(mosaic.maxTileY);
  });

  it('crops the bbox rect out of the stitched grid: fractional edge · 256', () => {
    const mosaic = mosaicFor(bbox, 11);
    const xMin = tileX(bbox.west, 11);
    const yMin = tileY(bbox.north, 11);
    expect(mosaic.cropX).toBe(Math.round((xMin - Math.floor(xMin)) * 256));
    expect(mosaic.cropY).toBe(Math.round((yMin - Math.floor(yMin)) * 256));
    expect(mosaic.cropWidth).toBe(Math.round((tileX(bbox.east, 11) - xMin) * 256));
    expect(mosaic.cropHeight).toBe(Math.round((tileY(bbox.south, 11) - yMin) * 256));
    // And the crop never escapes the grid.
    const gridWidth = (mosaic.maxTileX - mosaic.minTileX + 1) * 256;
    const gridHeight = (mosaic.maxTileY - mosaic.minTileY + 1) * 256;
    expect(mosaic.cropX + mosaic.cropWidth).toBeLessThanOrEqual(gridWidth);
    expect(mosaic.cropY + mosaic.cropHeight).toBeLessThanOrEqual(gridHeight);
  });
});

describe('mosaicCacheKey', () => {
  it('is a stable primitive carrying the tile range AND the crop rect', () => {
    const mosaic = mosaicFor({ west: -3.56, south: 40.4, east: -3.3, north: 40.6 }, 11);
    const key = mosaicCacheKey(mosaic);
    expect(key).toBe(mosaicCacheKey({ ...mosaic }));
    expect(key).toContain('11/');
    expect(key).toContain(`${String(mosaic.minTileX)}-${String(mosaic.maxTileX)}`);
    // Two bboxes sharing a tile range but cropped differently must not share a key —
    // they are different canvases (a deliberate step past the design's bare-range example).
    const shifted = { ...mosaic, cropX: mosaic.cropX + 1 };
    expect(mosaicCacheKey(shifted)).not.toBe(key);
  });

  it('round-trips through mosaicFromCacheKey — the key is the complete mosaic', () => {
    const mosaic = mosaicFor({ west: -3.56, south: 40.4, east: -3.3, north: 40.6 }, 11);
    expect(mosaicFromCacheKey(mosaicCacheKey(mosaic))).toEqual(mosaic);
  });

  it('mosaicFromCacheKey rejects a string that is not a key', () => {
    expect(() => mosaicFromCacheKey('11/1003-1007/770-773')).toThrow(/Not a mosaic/);
  });
});

describe('pickZoom', () => {
  it('gives a 30 NM approach at lat 40.5 z = 11', () => {
    expect(pickZoom(bboxAround(20, 30))).toBe(11);
  });

  it('gives a 5 NM circuit z = 14', () => {
    expect(pickZoom(bboxAround(5, 5))).toBe(14);
  });

  it('clamps a tiny bbox to MAX_ZOOM', () => {
    expect(pickZoom(bboxAround(0.1, 0.1))).toBe(MAX_ZOOM);
  });

  it('clamps a huge bbox to MIN_ZOOM while the tile budget still fits', () => {
    // 100 NM: the ideal zoom is below MIN_ZOOM, but at MIN_ZOOM the mosaic is still
    // comfortably under MAX_TILES, so the clamp is what decides.
    const bbox = bboxAround(100, 100);
    expect(pickZoom(bbox)).toBe(MIN_ZOOM);
    expect(tileCountOf(bbox, MIN_ZOOM)).toBeLessThanOrEqual(MAX_TILES);
  });

  it('decrements below MIN_ZOOM rather than exceed MAX_TILES — politeness wins', () => {
    const bbox = bboxAround(300, 300);
    const zoom = pickZoom(bbox);
    expect(zoom).toBeLessThan(MIN_ZOOM);
    expect(tileCountOf(bbox, zoom)).toBeLessThanOrEqual(MAX_TILES);
    expect(tileCountOf(bbox, zoom + 1)).toBeGreaterThan(MAX_TILES);
  });
});

describe('footprintBBox', () => {
  const extents: SceneExtents = {
    minX: -3,
    maxX: 7,
    minZ: -6,
    maxZ: 0,
    minY: 0,
    maxY: 1,
    centerX: 2,
    centerZ: -3,
    radiusNm: 8,
  };
  const origin = { latitude: 40, longitude: -3 };

  it('puts the north edge under the smaller scene z (z = −north)', () => {
    const footprint = groundPlaneFootprint(extents);
    const bbox = footprintBBox(footprint, origin);
    // centerZ = −3 is 3 NM *north* of the origin, so the whole box sits north of it.
    expect(bbox.north).toBeGreaterThan(bbox.south);
    const northOfOriginNm = (bbox.north - origin.latitude) * 60;
    expect(northOfOriginNm).toBeCloseTo(-(footprint.centerZ - footprint.depthNm / 2), 6);
  });

  it("spans exactly the ground plane's own footprint", () => {
    const footprint = groundPlaneFootprint(extents);
    const bbox = footprintBBox(footprint, origin);
    expect((bbox.north - bbox.south) * 60).toBeCloseTo(footprint.depthNm, 6);
    const cosLat = Math.cos((origin.latitude * Math.PI) / 180);
    expect((bbox.east - bbox.west) * 60 * cosLat).toBeCloseTo(footprint.widthNm, 6);
    // Centred where the footprint is centred.
    expect(((bbox.east + bbox.west) / 2 - origin.longitude) * 60 * cosLat).toBeCloseTo(
      footprint.centerX,
      6,
    );
  });
});
