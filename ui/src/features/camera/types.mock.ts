/**
 * PROVISIONAL mock-only view models — replace with generated schema.d.ts types at
 * backend integration; never import outside this feature.
 *
 * These mirror docs/designs/camera-manager.md §3: the closed five-view catalogue (D1),
 * the per-view support manifest (D2/D3) and the aircraft-relative saved-position model
 * (D4/D5). Once the camera server track lands, `npm run generate:api` produces the real
 * types and this file dies.
 */

/** The closed five-view catalogue (design D1). */
export type CameraViewId = 'cockpit' | 'chase' | 'tower' | 'wing' | 'drone';

/** Per-view adapter support — a reason, not just a bool (design D2). */
export interface CameraViewSupport {
  view_id: CameraViewId;
  supported: boolean;
  /** Shown to the instructor verbatim when `supported` is false. `null` when supported. */
  reason: string | null;
}

/** What `GET /api/camera/manifest` will answer. */
export interface CameraManifest {
  adapter: string;
  caveat: string | null;
  /** Exactly one entry per `CameraViewId`, in catalogue order. */
  views: readonly CameraViewSupport[];
  /**
   * Free/drone positioning is a separate reliability tier from named-view switching on
   * the same adapter (design D3) — it may need the optional in-sim bridge on X-Plane.
   */
  custom_positions_supported: boolean;
  /** The stated sentence behind a `false` above. `null` when supported. */
  custom_positions_reason: string | null;
}

/**
 * A free/drone camera pose relative to the aircraft's own reference point and CURRENT
 * heading — never a world-frame coordinate, so a saved "three-quarter view from the
 * left" stays that view as the aircraft moves (design D4). Pitch is world-frame
 * (positive = looking toward the sky); the look offset is aircraft-heading-relative
 * (design D5).
 */
export interface CameraOffset {
  /** Metres forward of the aircraft's reference point along its heading; negative is aft. */
  forward_m: number;
  /** Metres to the right of the reference point; negative is left. */
  right_m: number;
  /** Metres above the reference point. */
  up_m: number;
  /** Camera yaw relative to the aircraft's CURRENT heading, −180…180 (design D5). */
  look_offset_deg: number;
  /** Camera pitch, WORLD frame, −90…90, positive looking up (design D5). */
  pitch_deg: number;
  /** Field-of-view zoom multiplier; 1.0 is the adapter's default FOV. */
  zoom_ratio: number;
}

/** One record of `GET /api/camera/positions`, in creation order. */
export interface SavedCameraPosition {
  /** Server-assigned opaque id (uuid4 hex). */
  position_id: string;
  name: string;
  offset: CameraOffset;
  /** ISO 8601 UTC timestamp. */
  created_at: string;
}
