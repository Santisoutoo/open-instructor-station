/**
 * Deterministic camera fixtures — **test-only** since the backend landed.
 *
 * Until `/api/camera/*` existed these stood in for the server (the file was `mock.ts`,
 * typed against a hand-written `types.mock.ts`). Both are gone: the panel renders from
 * RTK Query and the types come from the generated `schema.d.ts`. What survives is the
 * fixture *bodies* — the manifest and the saved-position list `testApi.ts` answers with,
 * shared by the component tests so the same wire payload is exercised everywhere.
 *
 * The fixture mirrors `FakeSimAdapter` (design §4.1): every view supported, custom
 * positions supported, no caveat. Tests build their own degraded manifests from it to
 * exercise the disabled-with-reason paths.
 */

import {
  type CameraManifest,
  type CameraOffset,
  type SavedCameraPosition,
} from '../../api/models';
import { CAMERA_VIEWS } from './catalogue';

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
      position_id: 'pos-1',
      name: 'Three-quarter left',
      offset: THREE_QUARTER_LEFT,
      created_at: '2026-08-18T09:00:00Z',
    },
    {
      position_id: 'pos-2',
      name: 'Base leg view',
      offset: BASE_LEG_VIEW,
      created_at: '2026-08-18T09:05:00Z',
    },
  ];
}
