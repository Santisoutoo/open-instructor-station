/**
 * The circuit diagram's tap targets and labels.
 *
 * The SVG scales — `.pos-circuit` is always sized to the diagram's own 720:520 box, at
 * whatever size its grid cell has room for — so a hit target placed at a raw viewBox pixel
 * drifts away from the dot it belongs to at any size other than exactly 720×520. CLAUDE.md
 * makes the tablet first-class, so this is asserted rather than eyeballed.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { CircuitDiagram } from './CircuitDiagram';
import { place } from './circuit';
import { CIRCUIT_MARKERS, DRAWN_MARKER_IDS, labelPlacement } from './markers';
import { MARKER_IDS } from './positionDesignSlice';

const COURSE_DEG = 40;

function renderDiagram(onSelectMarker = vi.fn(), courseDeg = COURSE_DEG) {
  const result = render(
    <CircuitDiagram
      courseDeg={courseDeg}
      runwayIdent="04R"
      windDeg={240}
      windKt={12}
      selectedMarker="final-3nm"
      onSelectMarker={onSelectMarker}
    />,
  );
  return { onSelectMarker, container: result.container };
}

describe('the marker hit targets', () => {
  it('positions every one in percentages of the container, not viewBox pixels', () => {
    renderDiagram();

    for (const id of DRAWN_MARKER_IDS) {
      const marker = CIRCUIT_MARKERS[id];
      const point = place(marker.u, marker.v, COURSE_DEG);
      const button = screen.getByRole('button', { name: marker.label });
      // A percentage tracks the scale for free; a pixel value only lines up at 1:1.
      expect(button.style.left).toBe(`${String((point.x / 720) * 100)}%`);
      expect(button.style.top).toBe(`${String((point.y / 520) * 100)}%`);
    }
  });

  it('gives every marker a button that reports its own id', async () => {
    const { onSelectMarker } = renderDiagram();

    await userEvent.click(screen.getByRole('button', { name: 'Downwind left' }));
    expect(onSelectMarker).toHaveBeenCalledWith('downwind-left');
  });

  it('draws no dot, label or button for the redundant 8 NM final — the chip menu covers it', () => {
    renderDiagram();

    expect(screen.queryByRole('button', { name: '8 NM final' })).toBeNull();
    expect(screen.queryByText('8 NM final')).toBeNull();
    expect(DRAWN_MARKER_IDS).not.toContain('final-8nm');
    // The underlying marker/geometry data is untouched — only its diagram presence is gone.
    expect(MARKER_IDS).toContain('final-8nm');
  });

  it('keeps the whole drawing inside the viewBox at every runway course', () => {
    // The picture rotates about (360, 252), so the far end of the centreline traces a circle
    // around that centre. At 10 NM its radius was 272 px and the last tick fell outside a
    // 520-tall box for any runway pointing roughly north or south.
    for (const courseDeg of [0, 40, 90, 180, 220, 350]) {
      for (const id of MARKER_IDS) {
        const marker = CIRCUIT_MARKERS[id];
        const point = place(marker.u, marker.v, courseDeg);
        expect(point.x).toBeGreaterThanOrEqual(0);
        expect(point.x).toBeLessThanOrEqual(720);
        expect(point.y).toBeGreaterThanOrEqual(0);
        expect(point.y).toBeLessThanOrEqual(520);
      }
      const centrelineEnd = place(-8, 0, courseDeg);
      expect(centrelineEnd.y).toBeGreaterThanOrEqual(0);
      expect(centrelineEnd.y).toBeLessThanOrEqual(520);
    }
  });
});

describe('marker labels', () => {
  it('renders every label as an HTML overlay element, never inside the SVG', () => {
    // A label sitting inside the SVG would be re-scaled (and re-rotated) by its ancestor
    // transforms along with the geometry — see the module docstring for why that broke
    // legibility on a squeezed layout. Every label must sit outside the <svg> entirely.
    const { container } = renderDiagram();
    const svg = container.querySelector('svg');
    for (const label of container.querySelectorAll('.pos-circuit__marker-label')) {
      expect(svg?.contains(label)).toBe(false);
    }
    expect(container.querySelectorAll('.pos-circuit__marker-label')).toHaveLength(
      DRAWN_MARKER_IDS.length,
    );
  });

  it('positions each label at its marker’s fully-resolved screen point, in percentages', () => {
    const courseDeg = 220;
    renderDiagram(vi.fn(), courseDeg);

    for (const id of DRAWN_MARKER_IDS) {
      const marker = CIRCUIT_MARKERS[id];
      const point = place(marker.u, marker.v, courseDeg);
      const label = screen.getByText(marker.label, { selector: '.pos-circuit__marker-label' });
      expect(label.style.left).toBe(`${String((point.x / 720) * 100)}%`);
      expect(label.style.top).toBe(`${String((point.y / 520) * 100)}%`);
      // The label carries a modifier class naming which side of its dot it sits on, per
      // labelPlacement — never at the unrotated (course=0) point, which is what the old bug
      // this suite guards against drew.
      const anchor = labelPlacement(id, courseDeg);
      expect(label.className).toContain(`pos-circuit__marker-label--${anchor}`);
    }
  });

  it('gives the selected marker’s label the prominent modifier class, and no other', () => {
    renderDiagram(vi.fn(), COURSE_DEG);

    const selectedLabel = screen.getByText('Final', {
      selector: '.pos-circuit__marker-label',
    });
    expect(selectedLabel.className).toContain('pos-circuit__marker-label--selected');

    const otherLabel = screen.getByText('Take off', {
      selector: '.pos-circuit__marker-label',
    });
    expect(otherLabel.className).not.toContain('pos-circuit__marker-label--selected');
  });
});
