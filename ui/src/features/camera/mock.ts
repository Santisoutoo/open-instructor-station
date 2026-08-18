/**
 * Mock fixtures for the Camera panel: the support manifest and a couple of saved
 * positions, deterministic so tests can assert exact values. Dies at backend
 * integration — the real manifest comes from `GET /api/camera/manifest` and the saved
 * positions from `GET /api/camera/positions` via RTK Query (`cameraApi.ts`).
 *
 * The fixture mirrors `FakeSimAdapter` (design §4.1): every view supported, custom
 * positions supported, no caveat — so the §11 demo flow (tap through the grid, save a
 * position from the drone view, apply it, delete it) works end to end. Tests build
 * their own degraded manifests to exercise the disabled-with-reason paths.
 */

import { CAMERA_VIEWS } from './catalogue';
import {
  type CameraManifest,
  type CameraOffset,
  type SavedCameraPosition,
} from './types.mock';

export function cameraManifestFixture(): CameraManifest {
  return {
    adapter: 'fake',
    caveat: null,
    views: CAMERA_VIEWS.map((view) => ({
      view_id: view.viewId,
      supported: true,
      reason: null,
    })),
    custom_positions_supported: true,
    custom_positions_reason: null,
  };
}

/** A three-quarter framing from the left, the design's canonical example (D4). */
const THREE_QUARTER_LEFT: CameraOffset = {
  forward_m: 30,
  right_m: -40,
  up_m: 15,
  look_offset_deg: 50,
  pitch_deg: -10,
  zoom_ratio: 1.0,
};

/** Level with the aircraft, well aft on the final approach course. */
const BASE_LEG_VIEW: CameraOffset = {
  forward_m: -200,
  right_m: 0,
  up_m: 40,
  look_offset_deg: 0,
  pitch_deg: -5,
  zoom_ratio: 1.5,
};

export function savedPositionsFixture(): SavedCameraPosition[] {
  return [
    {
      position_id: 'mock-pos-1',
      name: 'Three-quarter left',
      offset: THREE_QUARTER_LEFT,
      created_at: '2026-08-18T09:00:00Z',
    },
    {
      position_id: 'mock-pos-2',
      name: 'Base leg view',
      offset: BASE_LEG_VIEW,
      created_at: '2026-08-18T09:05:00Z',
    },
  ];
}
