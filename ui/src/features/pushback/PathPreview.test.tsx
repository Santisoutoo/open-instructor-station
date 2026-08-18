/**
 * The schematic must draw exactly the points the preview geometry returns (§8.5) —
 * PUSHBACK_PATH_PREVIEW_POINTS + 1 of them — and a straight push must come out as a
 * vertical line: the aircraft backs straight down the screen, nose up.
 */

import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PathPreview } from './PathPreview';
import { PUSHBACK_PATH_PREVIEW_POINTS } from './types.mock';

function polylinePoints(container: HTMLElement): [number, number][] {
  const polyline = container.querySelector('polyline');
  expect(polyline).not.toBeNull();
  const points = polyline?.getAttribute('points') ?? '';
  return points.split(' ').map((pair) => {
    const [x, y] = pair.split(',');
    return [Number(x), Number(y)];
  });
}

describe('PathPreview', () => {
  it('draws PUSHBACK_PATH_PREVIEW_POINTS + 1 points for an arc', () => {
    const { container } = render(
      <PathPreview direction="right" distanceM={30} angleDeg={90} />,
    );

    expect(polylinePoints(container)).toHaveLength(PUSHBACK_PATH_PREVIEW_POINTS + 1);
  });

  it('draws a straight push as a vertical line, start above end', () => {
    const { container } = render(
      <PathPreview direction="straight" distanceM={20} angleDeg={0} />,
    );
    const points = polylinePoints(container);

    expect(points).toHaveLength(PUSHBACK_PATH_PREVIEW_POINTS + 1);
    const xs = new Set(points.map(([x]) => x));
    expect(xs.size).toBe(1);
    // Screen y grows downward; backing up means the path descends the screen.
    const ys = points.map(([, y]) => y);
    expect(ys.at(0)).toBeLessThan(ys.at(-1) ?? Number.NaN);
  });

  it('marks both noses and rotates only the target one', () => {
    const { container } = render(
      <PathPreview direction="right" distanceM={30} angleDeg={90} />,
    );

    const start = container.querySelector('.pushback-preview__nose--start');
    const end = container.querySelector('.pushback-preview__nose--end');
    expect(start?.getAttribute('transform')).not.toContain('rotate');
    // D5 on screen: a right push rotates the target nose marker clockwise (+90).
    expect(end?.getAttribute('transform')).toContain('rotate(90.0)');
  });

  it('names the direction for assistive tech', () => {
    const { container } = render(
      <PathPreview direction="left" distanceM={30} angleDeg={45} />,
    );

    expect(container.querySelector('svg')?.getAttribute('aria-label')).toContain(
      'nose left',
    );
  });
});
