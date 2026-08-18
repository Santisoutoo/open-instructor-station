/**
 * The mock manifest must keep the shape the contract suite pins on the server side
 * (design §4.2): exactly one support entry per catalogue view, in catalogue order —
 * otherwise the panel demos a manifest the backend will never serve.
 */

import { describe, expect, it } from 'vitest';
import { CAMERA_VIEWS } from './catalogue';
import { cameraManifestFixture, savedPositionsFixture } from './mock';

describe('cameraManifestFixture', () => {
  it('serves exactly one support entry per catalogue view, in catalogue order', () => {
    const manifest = cameraManifestFixture();

    expect(manifest.views.map((entry) => entry.view_id)).toEqual(
      CAMERA_VIEWS.map((view) => view.viewId),
    );
  });

  it('mirrors the Fake adapter: everything supported, no reasons, no caveat', () => {
    const manifest = cameraManifestFixture();

    expect(
      manifest.views.every((entry) => entry.supported && entry.reason === null),
    ).toBe(true);
    expect(manifest.custom_positions_supported).toBe(true);
    expect(manifest.custom_positions_reason).toBeNull();
    expect(manifest.caveat).toBeNull();
  });
});

describe('savedPositionsFixture', () => {
  it('is deterministic, with unique ids and in-bound offsets', () => {
    const positions = savedPositionsFixture();

    expect(positions).toEqual(savedPositionsFixture());
    expect(new Set(positions.map((position) => position.position_id)).size).toBe(
      positions.length,
    );
    for (const { offset } of positions) {
      expect(Math.abs(offset.forward_m)).toBeLessThanOrEqual(500);
      expect(Math.abs(offset.right_m)).toBeLessThanOrEqual(500);
      expect(Math.abs(offset.up_m)).toBeLessThanOrEqual(500);
      expect(Math.abs(offset.look_offset_deg)).toBeLessThanOrEqual(180);
      expect(Math.abs(offset.pitch_deg)).toBeLessThanOrEqual(90);
      expect(offset.zoom_ratio).toBeGreaterThan(0);
      expect(offset.zoom_ratio).toBeLessThanOrEqual(10);
    }
  });
});
