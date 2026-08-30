import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { LayoutNode, LayoutSegment, ProcedureLayout } from '../../api/models';
import { ProcedureDiagram } from './ProcedureDiagram';

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

function segment(overrides: Partial<LayoutSegment>): LayoutSegment {
  return {
    from_sequence: 10,
    to_sequence: 20,
    true_length_nm: 3,
    drawn_length_nm: 3,
    scale: 'to_scale',
    bearing_deg: 0,
    ...overrides,
  };
}

/**
 * IF NERAS (positioned, positionable) -> CF FAF (positioned) -> TF RW32L (runway, positioned)
 * -> CA (fix-less, unpositionable, missed approach) -> HM HLD (fixed, unpositionable, drawn
 * but not clickable) -- one procedure exercising every case the diagram has to render.
 */
const LAYOUT: ProcedureLayout = {
  airport_icao: 'ZZZZ',
  kind: 'approach',
  ident: 'I32L',
  transition: null,
  approach_type: 'ils',
  anchor: 'runway',
  airport_x_nm: 0.1,
  airport_y_nm: -0.2,
  airport_elevation_ft: 2040,
  nodes: [
    node({
      sequence: 10,
      ident: 'NERAS',
      x_nm: 0,
      y_nm: -18,
      altitude_ft: 7000,
      altitude_source: 'published',
    }),
    node({
      sequence: 20,
      ident: 'FAF',
      x_nm: 0,
      y_nm: -5,
      altitude_ft: 3247,
      altitude_source: 'published',
    }),
    node({
      sequence: 30,
      ident: 'RW32L',
      x_nm: 0,
      y_nm: 0,
      altitude_ft: 2040,
      altitude_source: 'runway',
      is_runway: true,
    }),
    node({
      sequence: 40,
      ident: 'CA',
      x_nm: 0.3,
      y_nm: 0.5,
      altitude_ft: 4000,
      altitude_source: 'interpolated',
      positioned: false,
      is_positionable: false,
      is_missed_approach: true,
    }),
    node({
      sequence: 50,
      ident: 'HLD',
      x_nm: 0.6,
      y_nm: 1.5,
      altitude_ft: 4000,
      altitude_source: 'interpolated',
      is_positionable: false,
    }),
  ],
  segments: [
    segment({
      from_sequence: 10,
      to_sequence: 20,
      true_length_nm: 30,
      drawn_length_nm: 6,
      scale: 'compressed',
    }),
    segment({
      from_sequence: 20,
      to_sequence: 30,
      true_length_nm: 5,
      drawn_length_nm: 5,
    }),
    segment({
      from_sequence: 30,
      to_sequence: 40,
      true_length_nm: 2,
      drawn_length_nm: 2,
    }),
    segment({
      from_sequence: 40,
      to_sequence: 50,
      true_length_nm: 1,
      drawn_length_nm: 1,
    }),
  ],
  total_true_length_nm: 38,
  compressed_segment_count: 1,
  long_factor: 3.0,
  nominal_leg_nm: 2.0,
};

function renderDiagram(selectedSequence: number | null = null, onSelectLeg = vi.fn()) {
  const { container } = render(
    <ProcedureDiagram
      layout={LAYOUT}
      courseDeg={320}
      selectedSequence={selectedSequence}
      onSelectLeg={onSelectLeg}
    />,
  );
  return { onSelectLeg, container };
}

describe('node buttons', () => {
  it('gives a button only to positionable nodes', () => {
    renderDiagram();
    const positionableIdents = LAYOUT.nodes
      .filter((n) => n.is_positionable)
      .map((n) => n.ident);
    for (const ident of positionableIdents) {
      expect(screen.getByRole('button', { name: ident })).toBeInTheDocument();
    }
    // CA and HLD are not positionable — no button carries their name.
    expect(screen.queryByRole('button', { name: 'CA' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'HLD' })).not.toBeInTheDocument();
  });

  it('reports the sequence it was clicked with', async () => {
    const { onSelectLeg } = renderDiagram();
    await userEvent.click(screen.getByRole('button', { name: 'FAF' }));
    expect(onSelectLeg).toHaveBeenCalledWith(20);
  });

  it('marks the selected node aria-pressed and no other', () => {
    renderDiagram(20);
    expect(screen.getByRole('button', { name: 'FAF' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByRole('button', { name: 'NERAS' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });
});

describe('compressed segments', () => {
  it('draws exactly one break glyph, for the one compressed segment', () => {
    const { container } = renderDiagram();
    expect(container.querySelectorAll('.pos-procdiagram__break')).toHaveLength(1);
  });

  it('labels the break with the true length, not the drawn one', () => {
    renderDiagram();
    expect(screen.getByText(/30\.0 NM/)).toBeInTheDocument();
    expect(screen.queryByText(/6\.0 NM/)).not.toBeInTheDocument();
  });
});

describe('dashed segments', () => {
  it('dashes a segment into an unpositioned node or a missed-approach node', () => {
    const { container } = renderDiagram();
    const paths = [...container.querySelectorAll('.pos-procdiagram__path')];
    const dashed = paths.filter((p) =>
      p.classList.contains('pos-procdiagram__path--dashed'),
    );
    // 30->40 (into the fix-less, missed-approach CA) must be dashed.
    expect(dashed).toHaveLength(2); // 30->40 and 40->50 (from a missed-approach node too)
  });

  it('does not dash an ordinary positioned-to-positioned segment', () => {
    const { container } = renderDiagram();
    const paths = [...container.querySelectorAll('.pos-procdiagram__path')];
    expect(paths).toHaveLength(4);
    expect(paths[0]).not.toHaveClass('pos-procdiagram__path--dashed'); // 10->20
    expect(paths[1]).not.toHaveClass('pos-procdiagram__path--dashed'); // 20->30
  });
});

describe('node styling', () => {
  it('draws a hollow node for anything but a published altitude', () => {
    const { container } = renderDiagram();
    const hollow = container.querySelectorAll('.pos-procdiagram__node--hollow');
    // CA and HLD are both "interpolated" — two hollow nodes.
    expect(hollow).toHaveLength(2);
  });
});

it('names the airport and the procedure ident in the accessible label', () => {
  renderDiagram();
  expect(
    screen.getByRole('img', { name: 'Procedure diagram for I32L' }),
  ).toBeInTheDocument();
});

it('prints the exaggeration factor and the not-to-scale mark in the legend', () => {
  renderDiagram();
  expect(screen.getByText(/vertical ×5/)).toBeInTheDocument();
  expect(screen.getByText(/not to scale/)).toBeInTheDocument();
});
