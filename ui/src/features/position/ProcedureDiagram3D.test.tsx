/**
 * `ProcedureDiagram3D` behind the `@react-three/fiber`/`@react-three/drei` stub
 * (`ui/src/test/threeStub.ts`) — chrome, selection wiring and semantics-parity flags, not
 * pixels. jsdom has no WebGL, so nothing here asserts actual rendered geometry; that is
 * `procedureScene.test.ts`'s job.
 *
 * Several assertions read a `name` attribute on a real (unstubbed) `<group>`/`<mesh>` element
 * rather than a prop on the stubbed `<Line>`: the stub necessarily flattens `<Line>` down to
 * a point count (see its own docstring), so state that would otherwise live on the line's own
 * `dashed`/`color` props is carried instead by the name of its enclosing group — see
 * `ProcedureDiagram3D.tsx`'s `SegmentLine`/`ProcedureNode3D` comments for why.
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CanvasTexture } from 'three';
import type {
  GeoPosition,
  LayoutNode,
  LayoutSegment,
  ProcedureLayout,
  Runway,
} from '../../api/models';
import { orbitControlsInstances } from '../../test/threeStub';
import { ProcedureDiagram3D } from './ProcedureDiagram3D';
import { buildProcedureScene } from './procedureScene';
import { useGroundTexture } from './useGroundTexture';

vi.mock('@react-three/fiber', async () => {
  const { threeFiberStub } = await import('../../test/threeStub');
  return threeFiberStub;
});
vi.mock('@react-three/drei', async () => {
  const { threeDreiStub } = await import('../../test/threeStub');
  return threeDreiStub;
});
// The hook's fetch cannot run in jsdom, so the component tests mock it at its module
// boundary (#178) — the hook's own behaviour is `useGroundTexture.test.ts`'s job.
vi.mock('./useGroundTexture', () => ({
  useGroundTexture: vi.fn(),
}));

const useGroundTextureMock = vi.mocked(useGroundTexture);

beforeEach(() => {
  // The default for every test that is not about the texture: the plain #177 plane.
  useGroundTextureMock.mockReturnValue({ texture: null, status: 'unavailable' });
});

const FLAGS = {
  altitude_source: 'published',
  positioned: true,
  is_positionable: true,
  is_missed_approach: false,
  is_runway: false,
} as const;

function node(
  overrides: Partial<LayoutNode> & Pick<LayoutNode, 'sequence' | 'ident'>,
): LayoutNode {
  return { x_nm: 0, y_nm: 0, altitude_ft: 2000, ...FLAGS, ...overrides };
}

function segment(overrides: Partial<LayoutSegment> = {}): LayoutSegment {
  return {
    from_sequence: 10,
    to_sequence: 20,
    true_length_nm: 5,
    drawn_length_nm: 5,
    scale: 'to_scale',
    bearing_deg: 0,
    ...overrides,
  };
}

/**
 * Four nodes: a normal published-altitude node (10), a guessed-altitude node (20), the
 * runway (30), and an unresolved-fix node (40, `is_positionable: false`). Three segments:
 * 10→20 plain, 20→30 compressed, 10→40 dashed (unresolved fix on its `to` end).
 */
const LAYOUT: ProcedureLayout = {
  airport_icao: 'ZZZZ',
  kind: 'approach',
  ident: 'I32L',
  transition: null,
  approach_type: 'ils',
  anchor: 'runway',
  airport_x_nm: 0,
  airport_y_nm: 0,
  airport_elevation_ft: 0,
  nodes: [
    node({ sequence: 10, ident: 'ALPHA', x_nm: 0, y_nm: -8, altitude_ft: 3000 }),
    node({
      sequence: 20,
      ident: 'BRAVO',
      x_nm: 0,
      y_nm: -4,
      altitude_ft: 2000,
      altitude_source: 'interpolated',
    }),
    node({
      sequence: 30,
      ident: 'RW32L',
      x_nm: 0,
      y_nm: 0,
      altitude_ft: 0,
      altitude_source: 'runway',
      is_runway: true,
    }),
    node({
      sequence: 40,
      ident: 'CHARLIE',
      x_nm: 2,
      y_nm: -10,
      altitude_ft: 4000,
      altitude_source: 'unknown',
      positioned: false,
      is_positionable: false,
    }),
  ],
  segments: [
    segment({
      from_sequence: 10,
      to_sequence: 20,
      true_length_nm: 4,
      drawn_length_nm: 4,
    }),
    segment({
      from_sequence: 20,
      to_sequence: 30,
      scale: 'compressed',
      true_length_nm: 12.4,
      drawn_length_nm: 4,
    }),
    segment({
      from_sequence: 10,
      to_sequence: 40,
      true_length_nm: 5,
      drawn_length_nm: 5,
    }),
  ],
  total_true_length_nm: 21.4,
  compressed_segment_count: 1,
  long_factor: 3.0,
  nominal_leg_nm: 2.0,
};

const RUNWAY: Runway = {
  airport_icao: 'ZZZZ',
  ident: '32L',
  threshold: { latitude: 0, longitude: 0, altitude_ft: 0 },
  true_bearing_deg: 320,
  length_m: 3000,
  elevation_ft: 0,
  displaced_threshold_m: 0,
};

function renderDiagram(
  overrides: Partial<{
    selectedSequence: number | null;
    onSelectLeg: (sequence: number) => void;
    runway: Runway | undefined;
    airportPosition: GeoPosition | undefined;
  }> = {},
) {
  const onSelectLeg = overrides.onSelectLeg ?? vi.fn();
  const utils = render(
    <ProcedureDiagram3D
      layout={LAYOUT}
      courseDeg={0}
      selectedSequence={overrides.selectedSequence ?? null}
      onSelectLeg={onSelectLeg}
      runway={overrides.runway}
      airportPosition={overrides.airportPosition}
    />,
  );
  return { ...utils, onSelectLeg };
}

function hitMesh(sequence: number): Element | null {
  return document.querySelector(`mesh[name="procdiagram3d-hit-${String(sequence)}"]`);
}

function visualMesh(sequence: number): Element | null {
  return document.querySelector(`mesh[name^="procdiagram3d-node-${String(sequence)}"]`);
}

function curtainMesh(fromSequence: number, toSequence: number): Element | null {
  return document.querySelector(
    `mesh[name^="procdiagram3d-curtain-${String(fromSequence)}-${String(toSequence)}"]`,
  );
}

describe('node hit targets', () => {
  it('has one hit-mesh per is_positionable node, none for the others', () => {
    renderDiagram();
    expect(document.querySelectorAll('mesh[name^="procdiagram3d-hit-"]')).toHaveLength(3);
    expect(hitMesh(10)).not.toBeNull();
    expect(hitMesh(20)).not.toBeNull();
    expect(hitMesh(30)).not.toBeNull();
    expect(hitMesh(40)).toBeNull();
  });

  it('clicking a hit-mesh calls onSelectLeg with its sequence', () => {
    const onSelectLeg = vi.fn();
    renderDiagram({ onSelectLeg });

    fireEvent.click(hitMesh(20)!);

    expect(onSelectLeg).toHaveBeenCalledWith(20);
  });
});

describe('selection', () => {
  it("changes the selected node's rendered name", () => {
    const { rerender } = renderDiagram({ selectedSequence: null });
    expect(visualMesh(10)?.getAttribute('name')).not.toContain('selected');

    rerender(
      <ProcedureDiagram3D
        layout={LAYOUT}
        courseDeg={0}
        selectedSequence={10}
        onSelectLeg={vi.fn()}
      />,
    );

    expect(visualMesh(10)?.getAttribute('name')).toContain('selected');
    // Only the selected node carries it.
    expect(visualMesh(20)?.getAttribute('name')).not.toContain('selected');
  });
});

describe('semantics parity with the 2D view', () => {
  it('flags a segment with an unresolved-fix end as dashed, a to-scale one as not', () => {
    renderDiagram();
    const dashedSegment = document.querySelector('group[name*="segment-10-40"]');
    const plainSegment = document.querySelector('group[name*="segment-10-20"]');

    expect(dashedSegment?.getAttribute('name')).toContain('dashed');
    expect(plainSegment?.getAttribute('name')).not.toContain('dashed');
  });

  it('flags a guessed-altitude node as hollow, a published one as not', () => {
    renderDiagram();
    expect(visualMesh(20)?.getAttribute('name')).toContain('hollow');
    expect(visualMesh(10)?.getAttribute('name')).not.toContain('hollow');
  });

  it('marks a compressed segment and renders its true-length callout', () => {
    renderDiagram();
    const compressedSegment = document.querySelector('group[name*="segment-20-30"]');
    expect(compressedSegment?.getAttribute('name')).toContain('compressed');
    expect(screen.getByText('↔ 12.4 NM')).toBeInTheDocument();
  });
});

describe('OrbitControls', () => {
  it('mounts exactly once with a target present (not asserting its numeric value)', () => {
    renderDiagram();
    const controls = document.querySelectorAll('orbit-controls-stub');
    expect(controls).toHaveLength(1);
    expect(controls[0]?.hasAttribute('target')).toBe(true);
  });
});

describe('legend', () => {
  it('states the vertical exaggeration factor', () => {
    renderDiagram();
    expect(screen.getByText(/vertical ×5/)).toBeInTheDocument();
  });
});

describe('ground plane (#177)', () => {
  it('always renders one ground mesh', () => {
    renderDiagram();
    expect(document.querySelectorAll('mesh[name="procdiagram3d-ground"]')).toHaveLength(
      1,
    );
  });
});

describe('runway quad (#177)', () => {
  it('renders when both a runway and an is_runway layout node exist', () => {
    renderDiagram({ runway: RUNWAY });
    expect(document.querySelectorAll('mesh[name="procdiagram3d-runway"]')).toHaveLength(
      1,
    );
  });

  it('does not render when no runway prop is passed', () => {
    renderDiagram();
    expect(document.querySelectorAll('mesh[name="procdiagram3d-runway"]')).toHaveLength(
      0,
    );
  });

  it('does not render when the layout has no is_runway node, even with a runway prop', () => {
    const noRunwayNode: ProcedureLayout = {
      ...LAYOUT,
      nodes: LAYOUT.nodes.map((n) => ({ ...n, is_runway: false })),
    };
    render(
      <ProcedureDiagram3D
        layout={noRunwayNode}
        courseDeg={0}
        selectedSequence={null}
        onSelectLeg={vi.fn()}
        runway={RUNWAY}
      />,
    );
    expect(document.querySelectorAll('mesh[name="procdiagram3d-runway"]')).toHaveLength(
      0,
    );
  });
});

describe('curtain fill (#177)', () => {
  it('renders one filled mesh per segment', () => {
    renderDiagram();
    expect(
      document.querySelectorAll('mesh[name^="procdiagram3d-curtain-"]'),
    ).toHaveLength(3);
  });

  it('marks the curtain of a dashed (unresolved-fix) segment as dimmed, a plain one not', () => {
    renderDiagram();
    expect(curtainMesh(10, 40)?.getAttribute('name')).toContain('dimmed');
    expect(curtainMesh(10, 20)?.getAttribute('name')).not.toContain('dimmed');
  });
});

describe('node ident/altitude labels (#177)', () => {
  it('renders each node ident with its rounded altitude', () => {
    renderDiagram();
    expect(screen.getByText('ALPHA')).toBeInTheDocument();
    expect(screen.getByText('3000 ft')).toBeInTheDocument();
    expect(screen.getByText('BRAVO')).toBeInTheDocument();
    expect(screen.getByText('2000 ft')).toBeInTheDocument();
  });
});

/**
 * IF ROFIX (positioned, positionable, 5000 ft) -> TF RW18L (runway) -> HM ROFIX (the hold
 * repeat: fixed, unpositionable, drawn but not clickable — mirroring
 * `ProcedureDiagram.test.tsx`'s `HM HLD` fixture) back at the arriving leg's own coordinates,
 * 200 ft above it. That Δaltitude sits *inside* the vertical gate (fit radius ≈ 4.3 NM ⇒ gate
 * ≈ 780 ft), so the repeat's label is the suppressed one — and, being different text from the
 * survivor's, lets the DOM pin keep-first (#199).
 */
const HOLD_LAYOUT: ProcedureLayout = {
  airport_icao: 'ZZZZ',
  kind: 'approach',
  ident: 'I18LY',
  transition: null,
  approach_type: 'ils',
  anchor: 'runway',
  airport_x_nm: 0,
  airport_y_nm: 0,
  airport_elevation_ft: 0,
  nodes: [
    node({ sequence: 10, ident: 'ROFIX', x_nm: 1, y_nm: -6, altitude_ft: 5000 }),
    node({
      sequence: 20,
      ident: 'RW18L',
      x_nm: 0,
      y_nm: 0,
      altitude_ft: 0,
      altitude_source: 'runway',
      is_runway: true,
    }),
    node({
      sequence: 30,
      ident: 'ROFIX',
      x_nm: 1,
      y_nm: -6,
      altitude_ft: 5200,
      altitude_source: 'interpolated',
      is_positionable: false,
      is_missed_approach: true,
    }),
  ],
  segments: [
    segment({ from_sequence: 10, to_sequence: 20, true_length_nm: 6.1 }),
    segment({ from_sequence: 20, to_sequence: 30, true_length_nm: 6.1 }),
  ],
  total_true_length_nm: 12.2,
  compressed_segment_count: 0,
  long_factor: 3.0,
  nominal_leg_nm: 2.0,
};

describe('duplicate label suppression (#199)', () => {
  function renderHoldDiagram(layout: ProcedureLayout) {
    return render(
      <ProcedureDiagram3D
        layout={layout}
        courseDeg={0}
        selectedSequence={null}
        onSelectLeg={vi.fn()}
      />,
    );
  }

  it('renders the repeated ident exactly once, keeping the first occurrence', () => {
    renderHoldDiagram(HOLD_LAYOUT);
    expect(screen.getAllByText('ROFIX')).toHaveLength(1);
    // Keep-first: the arriving leg's altitude survives, the hold repeat's does not.
    expect(screen.getByText('5000 ft')).toBeInTheDocument();
    expect(screen.queryByText('5200 ft')).not.toBeInTheDocument();
  });

  it('still renders both nodes as visual markers — only the label is suppressed', () => {
    renderHoldDiagram(HOLD_LAYOUT);
    expect(visualMesh(10)).not.toBeNull();
    expect(visualMesh(30)).not.toBeNull();
  });

  it('keeps both labels when the repeat is beyond the vertical gate (climb-in-hold)', () => {
    const climbInHold: ProcedureLayout = {
      ...HOLD_LAYOUT,
      nodes: HOLD_LAYOUT.nodes.map((n) =>
        n.sequence === 30 ? { ...n, altitude_ft: 8000 } : n,
      ),
    };
    renderHoldDiagram(climbInHold);
    expect(screen.getAllByText('ROFIX')).toHaveLength(2);
    expect(screen.getByText('5000 ft')).toBeInTheDocument();
    expect(screen.getByText('8000 ft')).toBeInTheDocument();
  });
});

describe('OSM ground texture (#178)', () => {
  it('renders the textured ground mesh and the attribution link when ready', () => {
    useGroundTextureMock.mockReturnValue({
      texture: new CanvasTexture({} as unknown as HTMLCanvasElement),
      status: 'ready',
    });
    renderDiagram();

    expect(
      document.querySelectorAll('mesh[name="procdiagram3d-ground--textured"]'),
    ).toHaveLength(1);
    expect(document.querySelectorAll('mesh[name="procdiagram3d-ground"]')).toHaveLength(
      0,
    );
    const attribution = screen.getByRole('link', {
      name: '© OpenStreetMap contributors',
    });
    expect(attribution).toHaveAttribute(
      'href',
      'https://www.openstreetmap.org/copyright',
    );
  });

  it("renders today's plain plane and no attribution on error", () => {
    useGroundTextureMock.mockReturnValue({ texture: null, status: 'error' });
    renderDiagram();

    expect(document.querySelectorAll('mesh[name="procdiagram3d-ground"]')).toHaveLength(
      1,
    );
    expect(
      document.querySelectorAll('mesh[name="procdiagram3d-ground--textured"]'),
    ).toHaveLength(0);
    expect(screen.queryByRole('link', { name: /OpenStreetMap/ })).not.toBeInTheDocument();
  });

  it("renders today's plain plane and no attribution when unavailable", () => {
    renderDiagram();

    expect(document.querySelectorAll('mesh[name="procdiagram3d-ground"]')).toHaveLength(
      1,
    );
    expect(screen.queryByRole('link', { name: /OpenStreetMap/ })).not.toBeInTheDocument();
  });

  it('hands the hook a null origin without an ARP, the recovered origin with one', () => {
    renderDiagram();
    expect(useGroundTextureMock).toHaveBeenLastCalledWith(null, expect.anything());

    // LAYOUT is runway-anchored with a zero ARP offset, so the origin is the ARP itself.
    renderDiagram({
      airportPosition: { latitude: 40.5, longitude: -3.5, altitude_ft: 0 },
    });
    expect(useGroundTextureMock).toHaveBeenLastCalledWith(
      { latitude: 40.5, longitude: -3.5 },
      expect.anything(),
    );
  });
});

describe('camera reset (#177)', () => {
  it('drives the same OrbitControls ref instance back to the fitted default pose', () => {
    renderDiagram();
    const scene = buildProcedureScene(LAYOUT, 0);
    expect(orbitControlsInstances).toHaveLength(1);
    const controls = orbitControlsInstances[0]!;

    // Simulate an orbit: move the ref's target/position/update-count away from the default.
    controls.target.set(999, 999, 999);
    controls.object.position.set(999, 999, 999);

    fireEvent.click(screen.getByRole('button', { name: /reset camera/i }));

    expect(controls.target.x).toBeCloseTo(scene.cameraPose.target[0], 6);
    expect(controls.target.y).toBeCloseTo(scene.cameraPose.target[1], 6);
    expect(controls.target.z).toBeCloseTo(scene.cameraPose.target[2], 6);
    expect(controls.object.position.x).toBeCloseTo(scene.cameraPose.position[0], 6);
    expect(controls.object.position.y).toBeCloseTo(scene.cameraPose.position[1], 6);
    expect(controls.object.position.z).toBeCloseTo(scene.cameraPose.position[2], 6);
    expect(controls.updateCallCount).toBe(1);
  });
});
