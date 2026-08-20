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
import { place } from './circuit';
import { CIRCUIT_MARKERS } from './markers';
import { MARKER_IDS } from './positionDesignSlice';

const COURSE_DEG = 40;

function renderDiagram(onSelectMarker = vi.fn()) {
  render(
    <CircuitDiagram
      courseDeg={COURSE_DEG}
      runwayIdent="04R"
      windDeg={240}
      windKt={12}
      selectedMarker="final-3nm"
      onSelectMarker={onSelectMarker}
    />,
  );
  return onSelectMarker;
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
    const onSelectMarker = renderDiagram();

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
