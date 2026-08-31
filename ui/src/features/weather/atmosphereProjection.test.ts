import { describe, expect, it } from 'vitest';
import type { CloudLayer, WindLayer } from '../../api/models';
import {
  aglLabel,
  altitudeToY,
  computeAltitudeScale,
  moveCloudBase,
  moveCloudTops,
  moveWindAltitude,
  projectCloudLayers,
  projectWindLayers,
  snapAltitudeFt,
  terrainBand,
  tickAltitudes,
  windBarbPath,
  yToAltitude,
} from './atmosphereProjection';

function windLayer(overrides: Partial<WindLayer> = {}): WindLayer {
  return {
    altitude_ft: 2000,
    direction_deg: 270,
    speed_kt: 15,
    gust_increase_kt: 0,
    turbulence_ratio: 0,
    ...overrides,
  };
}

function cloudLayer(overrides: Partial<CloudLayer> = {}): CloudLayer {
  return {
    base_ft: 3000,
    tops_ft: 5000,
    coverage_ratio: 0.75,
    cloud_type: 'cumulus',
    ...overrides,
  };
}

describe('computeAltitudeScale', () => {
  it('defaults to the minimum scale top with no layers', () => {
    expect(computeAltitudeScale([], [])).toEqual({ topFt: 10000, bottomFt: 0 });
  });

  it('is driven by the highest cloud tops', () => {
    expect(computeAltitudeScale([], [cloudLayer({ tops_ft: 9500 })])).toEqual({
      topFt: 11500,
      bottomFt: 0,
    });
  });

  it('is driven by the highest wind altitude', () => {
    expect(computeAltitudeScale([windLayer({ altitude_ft: 12000 })], [])).toEqual({
      topFt: 14000,
      bottomFt: 0,
    });
  });

  it('takes the max across both lists', () => {
    const scale = computeAltitudeScale(
      [windLayer({ altitude_ft: 4000 })],
      [cloudLayer({ tops_ft: 9500 })],
    );
    expect(scale.topFt).toBe(11500);
  });
});

describe('altitudeToY / yToAltitude', () => {
  const scale = { topFt: 10000, bottomFt: 0 } as const;

  it('projects the design doc\'s pinned reference: 8 000 ft against a 10 000 ft top → y=96', () => {
    expect(altitudeToY(8000, scale, 480)).toBeCloseTo(96, 6);
  });

  it('puts 0 ft at the bottom of the viewBox', () => {
    expect(altitudeToY(0, scale, 480)).toBeCloseTo(480, 6);
  });

  it('puts the scale top at the top of the viewBox', () => {
    expect(altitudeToY(10000, scale, 480)).toBeCloseTo(0, 6);
  });

  it('is the exact inverse of yToAltitude', () => {
    for (const altitudeFt of [0, 1234, 5000, 8000, 10000]) {
      const y = altitudeToY(altitudeFt, scale, 480);
      expect(yToAltitude(y, scale, 480)).toBeCloseTo(altitudeFt, 6);
    }
  });
});

describe('snapAltitudeFt', () => {
  it('snaps down below the half-way point', () => {
    expect(snapAltitudeFt(2530)).toBe(2500);
  });

  it('snaps up above the half-way point', () => {
    expect(snapAltitudeFt(2551)).toBe(2600);
  });

  it('rounds the exact half-way point up', () => {
    expect(snapAltitudeFt(2550)).toBe(2600);
  });
});

describe('tickAltitudes', () => {
  it('generates every 2 000 ft step up to the last full tick below topFt', () => {
    expect(tickAltitudes({ topFt: 11500, bottomFt: 0 })).toEqual([
      0, 2000, 4000, 6000, 8000, 10000,
    ]);
  });

  it('includes an on-grid top exactly', () => {
    expect(tickAltitudes({ topFt: 10000, bottomFt: 0 })).toEqual([
      0, 2000, 4000, 6000, 8000, 10000,
    ]);
  });
});

describe('aglLabel', () => {
  it('formats a known field elevation', () => {
    expect(aglLabel(9000, 1000)).toBe('8,000 ft AGL');
  });

  it('is null with no field elevation', () => {
    expect(aglLabel(9000, null)).toBeNull();
  });

  it('is null for an underground tick', () => {
    expect(aglLabel(500, 1000)).toBeNull();
  });
});

describe('terrainBand', () => {
  const scale = { topFt: 10000, bottomFt: 0 } as const;

  it('computes the band geometry for a known field elevation', () => {
    expect(terrainBand(1000, scale, 480)).toEqual({ y: 432, height: 48 });
  });

  it('is null with no field elevation', () => {
    expect(terrainBand(null, scale, 480)).toBeNull();
  });

  it('is null at sea level', () => {
    expect(terrainBand(0, scale, 480)).toBeNull();
  });

  it('clamps into the viewBox when the field sits above the scale top', () => {
    expect(terrainBand(12000, scale, 480)).toEqual({ y: 0, height: 480 });
  });
});

describe('projectCloudLayers / projectWindLayers', () => {
  const scale = { topFt: 10000, bottomFt: 0 } as const;

  it('projects each layer to its screen y, preserving list order as index', () => {
    const layers = [cloudLayer({ base_ft: 3000, tops_ft: 5000 }), cloudLayer({ base_ft: 7000, tops_ft: 8000 })];
    const projected = projectCloudLayers(layers, scale, 480);
    expect(projected).toHaveLength(2);
    expect(projected[0]?.index).toBe(0);
    expect(projected[0]?.baseY).toBeCloseTo(altitudeToY(3000, scale, 480), 6);
    expect(projected[0]?.topsY).toBeCloseTo(altitudeToY(5000, scale, 480), 6);
    expect(projected[1]?.index).toBe(1);
  });

  it('projects wind layers to their screen y', () => {
    const layers = [windLayer({ altitude_ft: 2000 }), windLayer({ altitude_ft: 6000 })];
    const projected = projectWindLayers(layers, scale, 480);
    expect(projected).toHaveLength(2);
    expect(projected[0]?.y).toBeCloseTo(altitudeToY(2000, scale, 480), 6);
    expect(projected[1]?.index).toBe(1);
  });
});

describe('moveCloudTops', () => {
  it('clamps to base + MIN_CLOUD_THICKNESS_FT when dragged below it', () => {
    const layer = cloudLayer({ base_ft: 3000, tops_ft: 5000 });
    const moved = moveCloudTops(layer, 2800);
    expect(moved.tops_ft).toBe(3100);
    expect(moved.base_ft).toBe(3000);
  });

  it('snaps to the nearest 100 ft', () => {
    const layer = cloudLayer({ base_ft: 3000, tops_ft: 5000 });
    expect(moveCloudTops(layer, 6049).tops_ft).toBe(6000);
  });
});

describe('moveCloudBase', () => {
  it('clamps at 0 ft', () => {
    const layer = cloudLayer({ base_ft: 3000, tops_ft: 5000 });
    expect(moveCloudBase(layer, -200).base_ft).toBe(0);
  });

  it('clamps to tops - MIN_CLOUD_THICKNESS_FT when dragged above it', () => {
    const layer = cloudLayer({ base_ft: 3000, tops_ft: 5000 });
    expect(moveCloudBase(layer, 4990).base_ft).toBe(4900);
  });
});

describe('moveWindAltitude', () => {
  it('clamps at 0 ft', () => {
    const layer = windLayer({ altitude_ft: 2000 });
    expect(moveWindAltitude(layer, -50).altitude_ft).toBe(0);
  });

  it('snaps to the nearest 100 ft', () => {
    const layer = windLayer({ altitude_ft: 2000 });
    expect(moveWindAltitude(layer, 3049).altitude_ft).toBe(3000);
  });
});

describe('windBarbPath', () => {
  it('is empty for calm', () => {
    expect(windBarbPath(0)).toBe('');
    expect(windBarbPath(2)).toBe('');
  });

  it('draws one half feather for 5 kt', () => {
    const path = windBarbPath(5);
    expect(path).toContain('M 0 0 L 0 -36');
    expect((path.match(/Z/g) ?? []).length).toBe(0);
    expect(path.split('M').length - 1).toBe(2); // staff + one half-feather segment
  });

  it('draws two full feathers plus a half feather for 25 kt', () => {
    const path = windBarbPath(25);
    expect(path.split('M').length - 1).toBe(4); // staff + two full-feather segments + one half
    expect((path.match(/Z/g) ?? []).length).toBe(0);
  });

  it('draws a pennant for 50 kt', () => {
    const path = windBarbPath(50);
    expect((path.match(/Z/g) ?? []).length).toBe(1);
  });

  it('rounds to the nearest 5 kt', () => {
    expect(windBarbPath(23)).toBe(windBarbPath(25));
  });
});
