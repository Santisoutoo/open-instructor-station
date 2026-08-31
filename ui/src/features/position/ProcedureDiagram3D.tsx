/**
 * The selected procedure, drawn to scale in a navigable 3D scene. Same props contract as the
 * 2D `ProcedureDiagram` — see that file's docstring for the semantics this view mirrors
 * (hollow altitude markers, dashed unpositioned/missed-approach segments, compressed-segment
 * true-length callouts). Geometry comes from `buildProcedureScene` (#175); this file only
 * turns that pure scene description into r3f/drei primitives and wires selection.
 *
 * **Deliberately out of scope here** (left as clean attachment points for #177, which extends
 * this file — see its own issue and docs/designs/procedure-approach-types-and-profile-view.md
 * §4.7.1): the runway quad, a ground plane, node ident/altitude billboard labels, curtain fill
 * (the quads already exist per segment on `SceneSegment.curtain`, unused here — only the top
 * edge, `curtain[0]`/`curtain[1]`, is drawn as a line), reading `--pos-*` theme tokens into
 * scene materials, and a camera-reset control. `ProcedureSceneContent` is the single child
 * `#177` adds siblings to; the per-segment `.map` in it is the loop `#177` extends with
 * curtain meshes; `controlsRef` is the `OrbitControls` ref `#177` will need to lift out for a
 * reset button.
 *
 * Colors are hard-coded rather than read from CSS custom properties: a WebGL material cannot
 * consult a CSS variable, and wiring the two together (`usePosThemePalette`) is #177's job.
 *
 * No lights are added: every material here is `meshBasicMaterial`, which ignores lighting by
 * design — the simplest way to keep node/path colors legible from any orbit angle without a
 * lighting rig that has nothing else to do in this view yet.
 */

import { useRef, useState, type ComponentRef } from 'react';
import { Canvas, type ThreeEvent } from '@react-three/fiber';
import { Html, Line, OrbitControls } from '@react-three/drei';
import type { LayoutNode } from '../../api/models';
import {
  VERTICAL_EXAGGERATION,
  buildProcedureScene,
  type ProcedureLayout,
  type ProcedureScene,
  type SceneNode,
  type SceneSegment,
  type Vec3,
} from './procedureScene';

function segmentIsDashed(from: SceneNode, to: SceneNode): boolean {
  return !to.node.positioned || from.node.is_missed_approach || to.node.is_missed_approach;
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

const PATH_COLOR = '#3ecf7a';
const COMPRESSED_COLOR = '#e0a83c';
const SELECTED_COLOR = '#ffd166';

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

/**
 * The `dashed`/`color` material choice lives on drei's `<Line>`, which the jsdom stub
 * necessarily flattens to a point count (it wraps a real `Line2`/`LineMaterial`, not a plain
 * Three.js primitive, so the stub cannot let it through unstubbed the way `<mesh>` passes
 * through). The enclosing `<group>`'s `name` carries the same dashed/compressed state as a
 * plain string, so a test can read it off a real (unstubbed) element instead.
 */
function SegmentLine({ sceneSegment }: { readonly sceneSegment: SceneSegment }) {
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
        color={compressed ? COMPRESSED_COLOR : PATH_COLOR}
        lineWidth={2}
        dashed={dashed}
        {...(dashed ? { dashSize: DASH_SIZE_NM, gapSize: GAP_SIZE_NM } : {})}
      />
    </group>
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

function ProcedureNode3D({
  sceneNode,
  radiusNm,
  selected,
  hovered,
  onSelect,
  onHoverChange,
}: {
  readonly sceneNode: SceneNode;
  /** `scene.extents.radiusNm` — the whole scene's own fit radius, sizing this one marker. */
  readonly radiusNm: number;
  readonly selected: boolean;
  readonly hovered: boolean;
  readonly onSelect: (sequence: number) => void;
  readonly onHoverChange: (sequence: number | null) => void;
}) {
  const { node, position } = sceneNode;
  const hollow = isGuessedAltitude(node);
  const baseRadius = radiusNm * NODE_RADIUS_FRACTION;
  const visualRadius = baseRadius * (selected ? 1.4 : hovered ? 1.15 : 1);
  const hitRadius = baseRadius * HIT_RADIUS_FACTOR;
  const color = selected ? SELECTED_COLOR : PATH_COLOR;
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
 * The scene's own content, as the single child `#177` adds siblings to (a ground plane, a
 * runway quad, billboard labels) inside the same `<Canvas>`.
 */
function ProcedureSceneContent({
  scene,
  selectedSequence,
  hoveredSequence,
  onHoverChange,
  onSelectLeg,
}: {
  readonly scene: ProcedureScene;
  readonly selectedSequence: number | null;
  readonly hoveredSequence: number | null;
  readonly onHoverChange: (sequence: number | null) => void;
  readonly onSelectLeg: (sequence: number) => void;
}) {
  const compressedSegments = scene.segments.filter(
    (entry) => entry.segment.scale === 'compressed',
  );

  return (
    <group name="procdiagram3d-scene">
      {scene.segments.map((sceneSegment) => (
        <SegmentLine
          key={`${String(sceneSegment.segment.from_sequence)}-${String(sceneSegment.segment.to_sequence)}`}
          sceneSegment={sceneSegment}
        />
      ))}
      {scene.nodes.map((sceneNode) => (
        <ProcedureNode3D
          key={sceneNode.node.sequence}
          sceneNode={sceneNode}
          radiusNm={scene.extents.radiusNm}
          selected={sceneNode.node.sequence === selectedSequence}
          hovered={sceneNode.node.sequence === hoveredSequence}
          onSelect={onSelectLeg}
          onHoverChange={onHoverChange}
        />
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
}: {
  readonly layout: ProcedureLayout;
  /** The orienting course — the runway's, when one is known; 0 (north-up) otherwise. Only
   *  sets the camera's initial azimuth; the scene geometry itself is north-aligned. */
  readonly courseDeg: number;
  readonly selectedSequence: number | null;
  readonly onSelectLeg: (sequence: number) => void;
}) {
  const [hoveredSequence, setHoveredSequence] = useState<number | null>(null);
  const scene = buildProcedureScene(layout, courseDeg);
  // Lifted out for #177's camera-reset button; unused for anything else in this view.
  const controlsRef = useRef<ComponentRef<typeof OrbitControls>>(null);

  return (
    <div className="pos-procdiagram3d">
      <Canvas
        className="pos-procdiagram3d__canvas"
        camera={{ position: scene.cameraPose.position, fov: scene.cameraPose.fov }}
      >
        <ProcedureSceneContent
          scene={scene}
          selectedSequence={selectedSequence}
          hoveredSequence={hoveredSequence}
          onHoverChange={setHoveredSequence}
          onSelectLeg={onSelectLeg}
        />
        {/* No minPolarAngle/maxPolarAngle: looking at the procedure from below the horizon
            must work, per the issue. */}
        <OrbitControls ref={controlsRef} makeDefault enableDamping target={scene.cameraPose.target} />
      </Canvas>
      <p className="pos-procdiagram3d__legend">
        vertical ×{String(VERTICAL_EXAGGERATION)} · not to scale
      </p>
    </div>
  );
}
