/**
 * The selected procedure, drawn to scale in a navigable 3D scene. Same props contract as the
 * 2D `ProcedureDiagram` plus an additive `runway` prop (#177) — see that file's docstring for
 * the semantics this view mirrors (hollow altitude markers, dashed unpositioned/missed-approach
 * segments, compressed-segment true-length callouts). Geometry comes from `buildProcedureScene`
 * (#175); this file turns that pure scene description into r3f/drei primitives and wires
 * selection.
 *
 * **#177 visual polish, on top of #176's shipped skeleton** (`ProcedureSceneContent`,
 * `SegmentLine`, `ProcedureNode3D`, `CompressedCallout`, `controlsRef`):
 * - `RunwayMesh` / `GroundPlane`: siblings of `ProcedureSceneContent` inside `<Canvas>`, not
 *   nested inside it.
 * - `CurtainFill`: a filled mesh added into `ProcedureSceneContent`'s existing per-segment
 *   `.map`, alongside `SegmentLine` (extends that loop rather than adding a second one).
 * - `NodeLabel`: a `<Billboard>`-wrapped `<Html>` per node, extending the `<Html>` pattern
 *   `CompressedCallout` already established.
 * - `usePosThemePalette`: replaces the hard-coded `PATH_COLOR`/`COMPRESSED_COLOR` for the path
 *   line, the node markers and the compressed-segment color. `SELECTED_COLOR`, the runway's
 *   pavement gray and the curtain's blue stay fixed constants — see their own comments for why
 *   the theming hook does not reach them.
 * - `controlsRef` (lifted out by #176 for exactly this) now drives a camera-reset button.
 *
 * No lights are added: every material here is `meshBasicMaterial`, which ignores lighting by
 * design — the simplest way to keep colors legible from any orbit angle (including from below
 * the horizon, which the issue asks for explicitly) without a lighting rig that has nothing
 * else to do in this view yet.
 */

import { useMemo, useRef, useState, type ComponentRef } from 'react';
import { Canvas, type ThreeEvent } from '@react-three/fiber';
import { Billboard, Html, Line, OrbitControls } from '@react-three/drei';
import { DoubleSide, Vector3, type CanvasTexture } from 'three';
import type { GeoPosition, LayoutNode, Runway } from '../../api/models';
import { sceneOrigin } from './groundTexture';
import { useGroundTexture } from './useGroundTexture';
import { usePosThemePalette, type PosThemePalette } from './usePosThemePalette';
import {
  NOMINAL_RUNWAY_WIDTH_M,
  VERTICAL_EXAGGERATION,
  buildProcedureScene,
  buildRunwayQuad,
  groundPlaneFootprint,
  type ProcedureLayout,
  type ProcedureScene,
  type SceneExtents,
  type SceneNode,
  type SceneSegment,
  type Vec3,
} from './procedureScene';

function segmentIsDashed(from: SceneNode, to: SceneNode): boolean {
  return (
    !to.node.positioned || from.node.is_missed_approach || to.node.is_missed_approach
  );
}

/**
 * Whether a node's altitude was invented by this diagram rather than read off the chart or
 * the runway record — both `'published'` and `'runway'` are real, sourced numbers. Duplicated
 * from `ProcedureDiagram.tsx` rather than imported: the same precedent `procedureScene.ts`
 * itself sets for `FEET_PER_NAUTICAL_MILE`.
 */
function isGuessedAltitude(node: LayoutNode): boolean {
  return node.altitude_source === 'interpolated' || node.altitude_source === 'unknown';
}

/**
 * The selection highlight stays a fixed color rather than following `usePosThemePalette`: once
 * the path line and node markers are themed to `--pos-accent` (below), mapping "selected" to
 * that same token would make a selected node blend into every unselected one instead of
 * standing out from them.
 */
const SELECTED_COLOR = '#ffd166';

/**
 * The runway pavement's color is fixed rather than themed: `usePosThemePalette` only wires up
 * the three tokens `position.css` already uses for this view (`--pos-hair`/`--pos-accent`/
 * `--pos-caution`), none of which reads as "pavement" — `--pos-hair` colors the ground plane
 * itself, so reusing it here would make the runway disappear into the ground in both themes.
 */
const RUNWAY_COLOR = '#6b7280';

/**
 * The curtain's own blue, independent of `--pos-accent`. An earlier draft of this design read
 * "accent for path/curtain/selected," on the assumption `--pos-accent` was blue — it measures
 * as `oklch(0.72 0.16 145)` (hue 145 = green, the exact `#3ecf7a` #176 already used for the
 * path line), not blue. The issue's own text asks for a "translucent blue altitude curtain"
 * with "a distinct edge line on the flight path itself" — mapping the curtain to the
 * (green) accent token would both miss "blue" and erase that distinctness from the path line
 * it is supposed to sit apart from. A fixed blue constant satisfies both; see this file's own
 * design doc section (§4.7.2, item 4) for the "a fixed blue constant is fine" fallback this
 * takes.
 */
const CURTAIN_COLOR = '#3b82f6';
const CURTAIN_OPACITY = 0.28;
/** Applied instead of `CURTAIN_OPACITY` for a `segmentIsDashed` segment — opacity-based
 *  de-emphasis, layered on top of #176's dashed *line*, not a replacement for it. */
const CURTAIN_OPACITY_DIMMED = 0.12;

/** Node marker radius, as a fraction of the scene's own fit radius — so it stays legible at
 *  any procedure's scale instead of looking huge on a tight circuit and tiny on a long STAR. */
const NODE_RADIUS_FRACTION = 0.025;
/** The invisible hit-sphere is bigger than the visible marker — an easier target to click,
 *  the 3D equivalent of 2D's 44x44 transparent `<button>` over a 5px dot. */
const HIT_RADIUS_FACTOR = 3;
const DASH_SIZE_NM = 0.15;
const GAP_SIZE_NM = 0.1;

function midpoint(a: Vec3, b: Vec3): Vec3 {
  return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2];
}

/** Expands a planar quad (wound `(0,1,2)/(0,2,3)`, per `SceneSegment.curtain`'s own docstring)
 *  into 6 unindexed vertices for a `<bufferGeometry>` `position` attribute. */
function quadToTriangleVertices(quad: readonly [Vec3, Vec3, Vec3, Vec3]): Float32Array {
  const [a, b, c, d] = quad;
  return new Float32Array([...a, ...b, ...c, ...a, ...c, ...d]);
}

/**
 * The `dashed`/`color` material choice lives on drei's `<Line>`, which the jsdom stub
 * necessarily flattens to a point count (it wraps a real `Line2`/`LineMaterial`, not a plain
 * Three.js primitive, so the stub cannot let it through unstubbed the way `<mesh>` passes
 * through). The enclosing `<group>`'s `name` carries the same dashed/compressed state as a
 * plain string, so a test can read it off a real (unstubbed) element instead.
 */
function SegmentLine({
  sceneSegment,
  pathColor,
  compressedColor,
}: {
  readonly sceneSegment: SceneSegment;
  readonly pathColor: string;
  readonly compressedColor: string;
}) {
  const { segment, from, to, curtain } = sceneSegment;
  const dashed = segmentIsDashed(from, to);
  const compressed = segment.scale === 'compressed';
  const name = [
    `procdiagram3d-segment-${String(segment.from_sequence)}-${String(segment.to_sequence)}`,
    dashed ? 'dashed' : null,
    compressed ? 'compressed' : null,
  ]
    .filter((part) => part !== null)
    .join('--');

  return (
    <group name={name}>
      <Line
        points={[curtain[0], curtain[1]]}
        color={compressed ? compressedColor : pathColor}
        lineWidth={2}
        dashed={dashed}
        {...(dashed ? { dashSize: DASH_SIZE_NM, gapSize: GAP_SIZE_NM } : {})}
      />
    </group>
  );
}

/**
 * The translucent wall between the flight path and its ground footprint (#177) — the full
 * 4-vertex `SceneSegment.curtain` quad, not just the top edge `SegmentLine` already draws.
 * `depthWrite={false}` avoids a translucent quad occluding the quads behind it depending on
 * draw order; `side={DoubleSide}` keeps it visible from an orbit below the horizon (#176
 * removed the polar-angle clamp specifically so that works).
 */
function CurtainFill({ sceneSegment }: { readonly sceneSegment: SceneSegment }) {
  const { curtain, from, to } = sceneSegment;
  const dashed = segmentIsDashed(from, to);
  const positions = useMemo(() => quadToTriangleVertices(curtain), [curtain]);
  const name = [
    `procdiagram3d-curtain-${String(from.node.sequence)}-${String(to.node.sequence)}`,
    dashed ? 'dimmed' : null,
  ]
    .filter((part) => part !== null)
    .join('--');

  return (
    <mesh name={name}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <meshBasicMaterial
        color={CURTAIN_COLOR}
        transparent
        opacity={dashed ? CURTAIN_OPACITY_DIMMED : CURTAIN_OPACITY}
        side={DoubleSide}
        depthWrite={false}
      />
    </mesh>
  );
}

function CompressedCallout({ sceneSegment }: { readonly sceneSegment: SceneSegment }) {
  const at = midpoint(sceneSegment.curtain[0], sceneSegment.curtain[1]);
  return (
    <Html position={at} center pointerEvents="none">
      <span className="pos-procdiagram3d__break">
        ↔ {sceneSegment.segment.true_length_nm.toFixed(1)} NM
      </span>
    </Html>
  );
}

/** Ident + rounded altitude, billboarded at the node's own position (#177). Purely textual —
 *  the hollow/solid altitude-source distinction already lives on the node marker below, and 2D
 *  itself doesn't style its text labels hollow either, only the dot. */
function NodeLabel({ sceneNode }: { readonly sceneNode: SceneNode }) {
  const { node, position } = sceneNode;
  return (
    <Billboard position={position}>
      <Html center pointerEvents="none">
        <div className="pos-procdiagram3d__label">
          <span className="pos-procdiagram3d__label-ident">{node.ident}</span>
          <span className="pos-procdiagram3d__label-altitude">
            {String(Math.round(node.altitude_ft))} ft
          </span>
        </div>
      </Html>
    </Billboard>
  );
}

function ProcedureNode3D({
  sceneNode,
  radiusNm,
  selected,
  hovered,
  pathColor,
  onSelect,
  onHoverChange,
}: {
  readonly sceneNode: SceneNode;
  /** `scene.extents.radiusNm` — the whole scene's own fit radius, sizing this one marker. */
  readonly radiusNm: number;
  readonly selected: boolean;
  readonly hovered: boolean;
  readonly pathColor: string;
  readonly onSelect: (sequence: number) => void;
  readonly onHoverChange: (sequence: number | null) => void;
}) {
  const { node, position } = sceneNode;
  const hollow = isGuessedAltitude(node);
  const baseRadius = radiusNm * NODE_RADIUS_FRACTION;
  const visualRadius = baseRadius * (selected ? 1.4 : hovered ? 1.15 : 1);
  const hitRadius = baseRadius * HIT_RADIUS_FACTOR;
  const color = selected ? SELECTED_COLOR : pathColor;
  // Same reasoning as SegmentLine's name: `wireframe`/`color` live on `meshBasicMaterial`,
  // whose exact DOM-attribute rendering for object/boolean props on an unstubbed custom
  // element is an implementation detail of the stub environment, not a contract worth
  // depending on — the visual mesh's own `name` carries the same state as a plain string.
  const nodeName = [
    `procdiagram3d-node-${String(node.sequence)}`,
    hollow ? 'hollow' : null,
    selected ? 'selected' : null,
  ]
    .filter((part) => part !== null)
    .join('--');

  return (
    <group>
      {/* Purely visual — never raycast, so it can never compete with the hit sphere below
          for a click. Mirrors 2D's aria-hidden dot under a transparent 44x44 button. */}
      <mesh position={position} raycast={() => null} name={nodeName}>
        <sphereGeometry args={[visualRadius, 16, 16]} />
        <meshBasicMaterial color={color} wireframe={hollow} />
      </mesh>
      {node.is_positionable && (
        <mesh
          position={position}
          name={`procdiagram3d-hit-${String(node.sequence)}`}
          onClick={(event: ThreeEvent<MouseEvent>) => {
            event.stopPropagation();
            onSelect(node.sequence);
          }}
          onPointerOver={(event: ThreeEvent<PointerEvent>) => {
            event.stopPropagation();
            onHoverChange(node.sequence);
          }}
          onPointerOut={() => {
            // Guard on this node's own hover flag: an overlapping neighbour's pointerOut
            // firing after this node's pointerOver must not clear the wrong node's hover.
            if (hovered) {
              onHoverChange(null);
            }
          }}
        >
          <sphereGeometry args={[hitRadius, 12, 12]} />
          <meshBasicMaterial transparent opacity={0} depthWrite={false} />
        </mesh>
      )}
    </group>
  );
}

/**
 * A flat mesh sized from `groundPlaneFootprint(scene.extents)` — the *same* footprint
 * `useGroundTexture` fetches OSM tiles for (#178), so texture and geometry provably cover
 * one rect. With a `texture`, the composite renders at full brightness (`color` on a mapped
 * `meshBasicMaterial` is a tint *multiplier*, so `#ffffff` means "the map as-is"); without
 * one — `'unavailable'`, `'loading'` and `'error'` alike — exactly the #177 neutral
 * `palette.hair` plane, so offline, mid-fetch and failed all render identically and nothing
 * ever throws into the canvas. The mesh `name` carries the textured/plain state (#176's
 * name-carries-state convention). `side={DoubleSide}` so it still reads from an orbit below
 * the horizon.
 */
function GroundPlane({
  extents,
  color,
  texture,
}: {
  readonly extents: SceneExtents;
  readonly color: string;
  readonly texture?: CanvasTexture | null;
}) {
  const footprint = groundPlaneFootprint(extents);

  return (
    <mesh
      name={texture != null ? 'procdiagram3d-ground--textured' : 'procdiagram3d-ground'}
      position={[footprint.centerX, 0, footprint.centerZ]}
      rotation={[-Math.PI / 2, 0, 0]}
    >
      <planeGeometry args={[footprint.widthNm, footprint.depthNm]} />
      {texture != null ? (
        <meshBasicMaterial map={texture} color="#ffffff" side={DoubleSide} />
      ) : (
        <meshBasicMaterial color={color} side={DoubleSide} />
      )}
    </mesh>
  );
}

/**
 * The runway pavement, at its true position and orientation (#177). Only rendered when both a
 * `Runway` record and an `is_runway` layout node exist — a STAR anchored on `last_fix` has
 * neither. `polygonOffset` keeps the coplanar-at-y=0 pavement from z-fighting/shimmering
 * against `GroundPlane` during an orbit, without lifting `buildRunwayQuad`'s own geometry (its
 * tests assert the exact anchor height).
 */
function RunwayMesh({
  runwayNode,
  runway,
}: {
  readonly runwayNode: SceneNode;
  readonly runway: Runway;
}) {
  const positions = useMemo(() => {
    const quad = buildRunwayQuad(
      runwayNode.position,
      runway.true_bearing_deg,
      runway.length_m,
      runway.width_m ?? NOMINAL_RUNWAY_WIDTH_M,
    );
    return quadToTriangleVertices(quad);
  }, [runwayNode.position, runway.true_bearing_deg, runway.length_m, runway.width_m]);

  return (
    <mesh name="procdiagram3d-runway">
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <meshBasicMaterial
        color={RUNWAY_COLOR}
        side={DoubleSide}
        polygonOffset
        polygonOffsetFactor={-4}
        polygonOffsetUnits={-4}
      />
    </mesh>
  );
}

/**
 * The scene's own content — segments, nodes, callouts. `RunwayMesh`/`GroundPlane` are added as
 * *siblings* of this component inside `<Canvas>` (#177), not nested inside it.
 */
function ProcedureSceneContent({
  scene,
  selectedSequence,
  hoveredSequence,
  palette,
  onHoverChange,
  onSelectLeg,
}: {
  readonly scene: ProcedureScene;
  readonly selectedSequence: number | null;
  readonly hoveredSequence: number | null;
  readonly palette: PosThemePalette;
  readonly onHoverChange: (sequence: number | null) => void;
  readonly onSelectLeg: (sequence: number) => void;
}) {
  const compressedSegments = scene.segments.filter(
    (entry) => entry.segment.scale === 'compressed',
  );

  return (
    <group name="procdiagram3d-scene">
      {scene.segments.map((sceneSegment) => {
        const key = `${String(sceneSegment.segment.from_sequence)}-${String(sceneSegment.segment.to_sequence)}`;
        return (
          <group key={key}>
            <SegmentLine
              sceneSegment={sceneSegment}
              pathColor={palette.accent}
              compressedColor={palette.caution}
            />
            <CurtainFill sceneSegment={sceneSegment} />
          </group>
        );
      })}
      {scene.nodes.map((sceneNode) => (
        <group key={`node-${String(sceneNode.node.sequence)}`}>
          <ProcedureNode3D
            sceneNode={sceneNode}
            radiusNm={scene.extents.radiusNm}
            selected={sceneNode.node.sequence === selectedSequence}
            hovered={sceneNode.node.sequence === hoveredSequence}
            pathColor={palette.accent}
            onSelect={onSelectLeg}
            onHoverChange={onHoverChange}
          />
          <NodeLabel sceneNode={sceneNode} />
        </group>
      ))}
      {compressedSegments.map((sceneSegment) => (
        <CompressedCallout
          key={`break-${String(sceneSegment.segment.from_sequence)}-${String(sceneSegment.segment.to_sequence)}`}
          sceneSegment={sceneSegment}
        />
      ))}
    </group>
  );
}

export function ProcedureDiagram3D({
  layout,
  courseDeg,
  selectedSequence,
  onSelectLeg,
  runway,
  airportPosition,
}: {
  readonly layout: ProcedureLayout;
  /** The orienting course — the runway's, when one is known; 0 (north-up) otherwise. Only
   *  sets the camera's initial azimuth; the scene geometry itself is north-aligned. */
  readonly courseDeg: number;
  readonly selectedSequence: number | null;
  readonly onSelectLeg: (sequence: number) => void;
  /** Purely additive (#177) — already fetched in `SidStarTab.tsx` via `useSelectedRunway()`
   *  as `Runway | null`, passed through as `?? undefined`. `| undefined` (not just `?:`) is
   *  needed under this project's `exactOptionalPropertyTypes`, which otherwise forbids an
   *  explicit `undefined` on an optional prop. The runway quad only renders when this AND an
   *  `is_runway` layout node both exist. */
  readonly runway?: Runway | undefined;
  /** The ARP, from `useAirport()` in `SidStarTab` (#178) — georeferences the ground plane
   *  for the OSM texture. Same `?: X | undefined` shape as `runway` above, and the same
   *  `exactOptionalPropertyTypes` reasoning. Without it (or on a `last_fix` layout, whose
   *  inverse is not trustworthy — see `sceneOrigin`) the plain ground plane renders. */
  readonly airportPosition?: GeoPosition | undefined;
}) {
  const [hoveredSequence, setHoveredSequence] = useState<number | null>(null);
  const scene = buildProcedureScene(layout, courseDeg);
  // Lifted out by #176 for this button.
  const controlsRef = useRef<ComponentRef<typeof OrbitControls>>(null);
  // Theme tokens (`--pos-hair`/`--pos-accent`/`--pos-caution`) only exist on this element's own
  // subtree (see usePosThemePalette's docstring for why document.documentElement can't be used).
  const containerRef = useRef<HTMLDivElement>(null);
  const palette = usePosThemePalette(containerRef);
  const origin =
    airportPosition === undefined ? null : sceneOrigin(layout, airportPosition);
  const { texture, status: textureStatus } = useGroundTexture(origin, scene.extents);

  const runwayNode = scene.nodes.find((sceneNode) => sceneNode.node.is_runway);

  function resetCamera(): void {
    const controls = controlsRef.current;
    if (controls === null) {
      return;
    }
    controls.target.copy(new Vector3(...scene.cameraPose.target));
    controls.object.position.copy(new Vector3(...scene.cameraPose.position));
    controls.update();
  }

  return (
    <div className="pos-procdiagram3d" ref={containerRef}>
      {/* The stage wrapper anchors the OSM attribution to the canvas itself rather than to
          the whole component (whose bottom edge is the toolbar below the canvas). */}
      <div className="pos-procdiagram3d__stage">
        <Canvas
          className="pos-procdiagram3d__canvas"
          camera={{ position: scene.cameraPose.position, fov: scene.cameraPose.fov }}
        >
          <GroundPlane extents={scene.extents} color={palette.hair} texture={texture} />
          {runway !== undefined && runwayNode !== undefined && (
            <RunwayMesh runwayNode={runwayNode} runway={runway} />
          )}
          <ProcedureSceneContent
            scene={scene}
            selectedSequence={selectedSequence}
            hoveredSequence={hoveredSequence}
            palette={palette}
            onHoverChange={setHoveredSequence}
            onSelectLeg={onSelectLeg}
          />
          {/* No minPolarAngle/maxPolarAngle: looking at the procedure from below the horizon
            must work, per the issue. */}
          <OrbitControls
            ref={controlsRef}
            makeDefault
            enableDamping
            target={scene.cameraPose.target}
          />
        </Canvas>
        {/* Required whenever OSM pixels are on screen — and only then: for every non-ready
          status the plain plane renders and the credit is correctly absent. The text
          matches useMapLibre.ts's attribution string character-for-character. */}
        {textureStatus === 'ready' && (
          <a
            className="pos-procdiagram3d__attribution"
            href="https://www.openstreetmap.org/copyright"
            target="_blank"
            rel="noreferrer"
          >
            © OpenStreetMap contributors
          </a>
        )}
      </div>
      <div className="pos-procdiagram3d__toolbar">
        <button
          type="button"
          className="pos-procdiagram3d__reset-camera"
          onClick={resetCamera}
        >
          Reset camera
        </button>
        <p className="pos-procdiagram3d__legend">
          vertical ×{String(VERTICAL_EXAGGERATION)} · not to scale
        </p>
      </div>
    </div>
  );
}
