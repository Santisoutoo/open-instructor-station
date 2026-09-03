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

describe('labels are an HTML overlay, not SVG text', () => {
  it('renders every label class outside the <svg>', () => {
    // Altitude only renders for the selected node (it's hidden otherwise — see the "altitude"
    // describe block below) — select one so every label class has at least one instance.
    const { container } = renderDiagram(20);
    const svg = container.querySelector('svg');
    const labelSelectors = [
      '.pos-procdiagram__node-label',
      '.pos-procdiagram__node-altitude',
      '.pos-procdiagram__break-label',
      '.pos-procdiagram__airport-label',
      '.pos-procdiagram__legend',
    ];
    for (const selector of labelSelectors) {
      const labels = container.querySelectorAll(selector);
      expect(labels.length).toBeGreaterThan(0);
      for (const label of labels) {
        expect(svg?.contains(label)).toBe(false);
      }
    }
  });

  it('positions each node label in percentages of the container', () => {
    renderDiagram(20);
    const ident = screen.getByText('FAF', { selector: '.pos-procdiagram__node-label' });
    const altitude = screen.getByText('3247 ft', {
      selector: '.pos-procdiagram__node-altitude',
    });
    // Both labels share the same anchor point as the node's own button.
    const button = screen.getByRole('button', { name: 'FAF' });
    expect(ident.style.left).toBe(button.style.left);
    expect(ident.style.top).toBe(button.style.top);
    expect(altitude.style.left).toBe(button.style.left);
    expect(altitude.style.top).toBe(button.style.top);
  });

  it('shows a node’s altitude only while it is selected — every ident stays visible regardless', () => {
    // Confirmed live against a real, densely-packed procedure: with every node's altitude
    // always shown, ident and altitude labels collided extensively (measured — not just
    // eyeballed) in a tight cluster of waypoints. Showing altitude only for the selected node
    // halves the simultaneous label count there; the full detail for any node is one click
    // away in the leg table regardless.
    const { rerender } = render(
      <ProcedureDiagram
        layout={LAYOUT}
        courseDeg={320}
        selectedSequence={null}
        onSelectLeg={vi.fn()}
      />,
    );
    expect(screen.queryByText('3247 ft')).not.toBeInTheDocument();
    for (const ident of LAYOUT.nodes.map((n) => n.ident)) {
      expect(screen.getByText(ident, { selector: '.pos-procdiagram__node-label' })).toBeInTheDocument();
    }

    rerender(
      <ProcedureDiagram
        layout={LAYOUT}
        courseDeg={320}
        selectedSequence={20}
        onSelectLeg={vi.fn()}
      />,
    );
    expect(
      screen.getByText('3247 ft', { selector: '.pos-procdiagram__node-altitude' }),
    ).toBeInTheDocument();
  });

  it('gives the selected node’s ident label the prominent modifier, and no other', () => {
    renderDiagram(20);
    const selectedIdent = screen.getByText('FAF', {
      selector: '.pos-procdiagram__node-label',
    });
    expect(selectedIdent.className).toContain('pos-procdiagram__node-label--selected');

    const otherIdent = screen.getByText('NERAS', {
      selector: '.pos-procdiagram__node-label',
    });
    expect(otherIdent.className).not.toContain('pos-procdiagram__node-label--selected');
  });

  it('marks the break-length and legend labels aria-hidden — they carry no accessible name', () => {
    renderDiagram();
    expect(screen.getByText(/30\.0 NM/)).toHaveAttribute('aria-hidden', 'true');
    expect(screen.getByText(/vertical ×5/)).toHaveAttribute('aria-hidden', 'true');
  });
});
