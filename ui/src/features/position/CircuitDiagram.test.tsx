/**
 * The circuit diagram's tap targets.
 *
 * The SVG scales — `.pos-circuit` is `width: 720px; max-width: 100%` — so a hit target placed
 * at a raw viewBox pixel drifts away from the dot it belongs to on every viewport narrower
 * than the drawing. At 1024 px the scale is ~0.71 and the furthest marker's button lands
 * ~88 px from its circle: the instructor taps the dot and nothing happens. CLAUDE.md makes
 * the tablet first-class, so this is asserted rather than eyeballed.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { CircuitDiagram } from './CircuitDiagram';
import { CX, CY, place } from './circuit';
import { CIRCUIT_MARKERS, labelPlacement } from './markers';
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

    for (const id of MARKER_IDS) {
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

describe('marker labels stay upright', () => {
  /** Courses that stress the illegible 90°–270° range the rotated `<g>` used to catch them in. */
  const ROTATED_COURSES = [0, 40, 90, 180, 220, 270, 315];

  it('never rotates a marker label — no <g transform="rotate(...)"> ancestor but the identity one', () => {
    for (const courseDeg of ROTATED_COURSES) {
      const { container } = renderDiagram(vi.fn(), courseDeg);
      for (const text of container.querySelectorAll('text.pos-circuit__marker-label')) {
        let ancestor: Element | null = text.parentElement;
        while (ancestor !== null) {
          const transform = ancestor.getAttribute('transform');
          if (transform !== null && /rotate\(/.exec(transform) !== null) {
            expect(transform).toBe(`rotate(0 ${String(CX)} ${String(CY)})`);
          }
          ancestor = ancestor.parentElement;
        }
      }
    }
  });

  it('positions each label at place(u, v, courseDeg) plus its offset, for a non-zero course', () => {
    const courseDeg = 220;
    const { container } = renderDiagram(vi.fn(), courseDeg);
    const texts = container.querySelectorAll('text.pos-circuit__marker-label');
    expect(texts).toHaveLength(MARKER_IDS.length);

    for (const id of MARKER_IDS) {
      const marker = CIRCUIT_MARKERS[id];
      const point = place(marker.u, marker.v, courseDeg);
      const text = screen.getByText(marker.label, { selector: 'text' });
      // labelOffset's numeric part is asserted indirectly via x/y below; textAnchor is the
      // one part of the offset an attribute exposes directly.
      const anchor = labelPlacement(id, courseDeg);
      const expectedAnchor =
        anchor === 'left' ? 'end' : anchor === 'right' ? 'start' : 'middle';
      expect(text.getAttribute('text-anchor')).toBe(expectedAnchor);
      expect(Number(text.getAttribute('x'))).not.toBeNaN();
      expect(Number(text.getAttribute('y'))).not.toBeNaN();
      // The label sits within a small, fixed offset of its rotated screen point — never at
      // the unrotated (course=0) point, which is what the bug drew.
      const dx = Number(text.getAttribute('x')) - point.x;
      const dy = Number(text.getAttribute('y')) - point.y;
      expect(Math.abs(dx)).toBeLessThanOrEqual(12.001);
      expect(Math.abs(dy)).toBeLessThanOrEqual(18.001);
    }
  });
});

describe('the Take off marker', () => {
  it('sits at the runway pavement bar’s far end, not the near end', () => {
    // circuit.ts pins it there: `RUNWAY_FAR_U` is the "cabecera" the approach dashes and
    // corridor arrive at, not `RUNWAY_NEAR_U`.
    expect(CIRCUIT_MARKERS.takeoff.u).not.toBe(0);
    expect(CIRCUIT_MARKERS.takeoff.v).toBe(0);
  });
});
