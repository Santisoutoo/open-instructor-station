/**
 * Scene-space geometry for the navigable 3D procedure view.
 *
 * A mirror of `procedureProjection.ts`, but for a free-orbiting camera instead of an
 * auto-fit SVG viewBox. **Geometry here stays in an unrotated, north-aligned world frame** —
 * `x_nm` is east, `-y_nm` is north (so a right-handed y-up scene has north along negative z).
 * `procedureProjection.ts` bakes `courseDeg` into every vertex because its auto-fit needs the
 * *rotated* extent to size a fixed viewBox; a free camera doesn't fit anything, so there is no
 * reason to rotate the scene at all — `courseDeg` only sets the camera's initial azimuth.
 * Keeping the scene north-aligned also protects a future OSM ground-texture overlay, which
 * needs the ground plane's x/z to line up with real-world tile coordinates.
 *
 * `VERTICAL_EXAGGERATION` is imported and re-exported from `procedureProjection.ts` rather
 * than duplicated, so both views provably share one factor. `FEET_PER_NAUTICAL_MILE` is
 * duplicated (it is module-private there, not part of that module's public contract either).
 *
 * The camera azimuth is **not** computed with `procedureProjection.ts`'s `rotate()` — that
 * function is a 2D screen-space mapping with a deliberate y-negation for SVG's downward-y
 * convention, and reusing it for a 3D offset would silently invert the camera's position.
 * The convention here instead: the camera starts on the back-course side of the scene's
 * centroid, looking along `courseDeg` toward it — matching the 2D course-up orientation
 * (i.e. flying `courseDeg` carries you from the camera's side toward the target).
 */

import type { LayoutNode, LayoutSegment, ProcedureLayout } from '../../api/models';
import { VERTICAL_EXAGGERATION } from './procedureProjection';

export { VERTICAL_EXAGGERATION };
export type { ProcedureLayout };

const FEET_PER_NAUTICAL_MILE = 6076.12;

/** A point in scene space: NM units, y-up. x = east, z = south (so -y_nm/north is negative z). */
export type Vec3 = readonly [number, number, number];

/** How much the ground-plane/camera fit pads past the tightest bounding sphere. */
const FIT_MARGIN_FACTOR = 1.15;

/** A floor so a single-node or empty layout never yields a zero-radius, degenerate fit. */
const MIN_RADIUS_NM = 0.5;

/** Vertical field of view used to fit the initial camera — reused by a future reset control. */
export const DEFAULT_FOV_DEG = 50;

/** Initial camera elevation above the ground plane, degrees above the horizon. */
export const DEFAULT_ELEVATION_DEG = 35;

export interface SceneNode {
  readonly node: LayoutNode;
  /** (x_nm, heightNm(altitude_ft), -y_nm) — the node's true drawn position. */
  readonly position: Vec3;
  /** (x_nm, 0, -y_nm) — its footprint at airport elevation, no altitude offset. */
  readonly ground: Vec3;
}

/**
 * One segment's curtain ribbon: the translucent wall between the flight path and its ground
 * footprint, generated per segment (not a shared-vertex ribbon across the whole procedure) so
 * a compressed or unpositioned segment can get its own material later. Adjacent quads share
 * exact node-derived edge coordinates, so there are no gaps despite not sharing vertex buffers.
 * Corners wind fromPath -> toPath -> toGround -> fromGround (a planar vertical quad);
 * triangulate consistently as (0,1,2) and (0,2,3).
 */
export interface SceneSegment {
  readonly segment: LayoutSegment;
  readonly from: SceneNode;
  readonly to: SceneNode;
  readonly curtain: readonly [Vec3, Vec3, Vec3, Vec3];
}

export interface SceneExtents {
  readonly minX: number;
  readonly maxX: number;
  readonly minZ: number;
  readonly maxZ: number;
  /**
   * Vertical bounds in scene space — needed because VERTICAL_EXAGGERATION=5 makes a
   * 10,000 ft climb ≈ 8.2 NM tall, comparable to a compact procedure's lateral span.
   * Fitting the camera from the XZ footprint alone risks clipping the flight path itself.
   */
  readonly minY: number;
  readonly maxY: number;
  readonly centerX: number;
  readonly centerZ: number;
  /** 3D bounding-sphere radius (over X/Y/Z, with padding) — NOT an XZ-only radius. */
  readonly radiusNm: number;
}

export interface CameraPose {
  readonly position: Vec3;
  readonly target: Vec3;
  /** Vertical field of view, degrees. The fit assumes viewport aspect >= 1 (three's `fov` is
   *  vertical, and this pure module has no viewport to consult) — a narrower viewport may
   *  need to re-fit. */
  readonly fov: number;
}

export interface ProcedureScene {
  readonly nodes: readonly SceneNode[];
  readonly segments: readonly SceneSegment[];
  /** Ground-footprint polyline vertices, in node order, airport appended last. */
  readonly groundPolyline: readonly Vec3[];
  readonly airport: Vec3;
  readonly extents: SceneExtents;
  readonly cameraPose: CameraPose;
}

function distance3(a: Vec3, b: Vec3): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

/**
 * Builds the full 3D scene for a procedure. Geometry is invariant under `courseDeg` — only
 * `cameraPose` depends on it.
 */
export function buildProcedureScene(
  layout: ProcedureLayout,
  courseDeg: number,
): ProcedureScene {
  const referenceFt = layout.airport_elevation_ft;
  const heightNm = (altitudeFt: number): number =>
    ((altitudeFt - referenceFt) / FEET_PER_NAUTICAL_MILE) * VERTICAL_EXAGGERATION;

  const sceneNodes: SceneNode[] = layout.nodes.map((node) => {
    const ground: Vec3 = [node.x_nm, 0, -node.y_nm];
    const position: Vec3 = [node.x_nm, heightNm(node.altitude_ft), -node.y_nm];
    return { node, position, ground };
  });
  const bySequence = new Map(sceneNodes.map((entry) => [entry.node.sequence, entry]));

  const sceneSegments: SceneSegment[] = [];
  for (const segment of layout.segments) {
    const from = bySequence.get(segment.from_sequence);
    const to = bySequence.get(segment.to_sequence);
    if (from === undefined || to === undefined) {
      continue;
    }
    sceneSegments.push({
      segment,
      from,
      to,
      curtain: [from.position, to.position, to.ground, from.ground],
    });
  }

  const airport: Vec3 = [layout.airport_x_nm, 0, -layout.airport_y_nm];
  const groundPolyline: Vec3[] = [...sceneNodes.map((n) => n.ground), airport];

  const extents = computeExtents(sceneNodes, airport);
  const cameraPose = fitCamera(extents, courseDeg);

  return {
    nodes: sceneNodes,
    segments: sceneSegments,
    groundPolyline,
    airport,
    extents,
    cameraPose,
  };
}

function computeExtents(nodes: readonly SceneNode[], airport: Vec3): SceneExtents {
  const groundPoints = nodes.map((n) => n.ground).concat([airport]);
  const allPoints = nodes.flatMap((n) => [n.position, n.ground]).concat([airport]);

  const xs = groundPoints.map((p) => p[0]);
  const zs = groundPoints.map((p) => p[2]);
  const ys = allPoints.map((p) => p[1]);

  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minZ = Math.min(...zs);
  const maxZ = Math.max(...zs);
  const minY = Math.min(0, ...ys);
  const maxY = Math.max(0, ...ys);

  const centerX = (minX + maxX) / 2;
  const centerZ = (minZ + maxZ) / 2;
  const centerY = (minY + maxY) / 2;
  const center: Vec3 = [centerX, centerY, centerZ];

  const rawRadius = Math.max(...allPoints.map((p) => distance3(p, center)));
  const radiusNm = Math.max(MIN_RADIUS_NM, rawRadius * FIT_MARGIN_FACTOR);

  return { minX, maxX, minZ, maxZ, minY, maxY, centerX, centerZ, radiusNm };
}

function fitCamera(extents: SceneExtents, courseDeg: number): CameraPose {
  const centerY = (extents.minY + extents.maxY) / 2;
  const target: Vec3 = [extents.centerX, centerY, extents.centerZ];

  const fovRad = (DEFAULT_FOV_DEG * Math.PI) / 180;
  const distance = extents.radiusNm / Math.sin(fovRad / 2);

  const elevationRad = (DEFAULT_ELEVATION_DEG * Math.PI) / 180;
  const courseRad = (courseDeg * Math.PI) / 180;

  // The camera sits on the back-course side of the target, looking along courseDeg toward
  // it: back off along -courseDeg's horizontal direction, then rise by the elevation angle.
  const horizontal = distance * Math.cos(elevationRad);
  const height = distance * Math.sin(elevationRad);
  const offsetX = -horizontal * Math.sin(courseRad);
  const offsetZ = horizontal * Math.cos(courseRad);

  const position: Vec3 = [target[0] + offsetX, target[1] + height, target[2] + offsetZ];

  return { position, target, fov: DEFAULT_FOV_DEG };
}
