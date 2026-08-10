/**
 * The staging bar's diagram.
 *
 * `projection.test.ts` already pins the scaling. What is left here, and untested until now,
 * is the part that is easy to get subtly and invisibly wrong: the **heading vector**, drawn
 * relative to the runway axis rather than to the screen. A sign error there points an
 * aeroplane on a downwind leg at the runway it is meant to be flying away from, and the
 * diagram still looks perfectly reasonable.
 *
 * The numbers below are computed by hand from `projection.ts` rather than read back off the
 * component, so a change to the projection has to be a deliberate one.
 */

import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { PlacementSchematic, SchematicPoint } from '../../api/models';
import { Schematic } from './Schematic';

const AT = (
  latitude: number,
): { latitude: number; longitude: number; altitude_ft: number } => ({
  latitude,
  longitude: -3,
  altitude_ft: 2000,
});

function point(
  role: SchematicPoint['role'],
  x_nm: number,
  y_nm: number,
  label: string = role,
): SchematicPoint {
  return { label, position: AT(40), x_nm, y_nm, role };
}

/**
 * A 10 NM final on a 1.62 NM (3,000 m) runway, the case the whole panel exists for.
 *
 * Runway 36, so the true bearing is 0° and "relative to the axis" and "true" coincide —
 * which is exactly why the reciprocal case below uses a heading of 180° and not 0°.
 */
function finalSchematic(overrides: Partial<PlacementSchematic> = {}): PlacementSchematic {
  return {
    runway_ident: '36',
    runway_true_bearing_deg: 0,
    runway_length_m: 3000,
    glidepath_deg: 3,
    points: [
      point('threshold', 0, 0, '36'),
      point('runway_end', 1.62, 0, '18'),
      point('placement', -10, 0, 'ZZZZ 36 10 NM final'),
    ],
    ...overrides,
  };
}

function draw(schematic: PlacementSchematic, headingDeg: number) {
  const { container } = render(
    <Schematic schematic={schematic} headingDeg={headingDeg} />,
  );
  const select = (selector: string): SVGElement => {
    const element = container.querySelector(selector);
    if (element === null) {
      throw new Error(`No ${selector} in the diagram`);
    }
    return element as SVGElement;
  };
  const number = (element: SVGElement, attribute: string): number =>
    Number(element.getAttribute(attribute));
  return {
    container,
    aircraft: select('.schematic__aircraft'),
    heading: select('.schematic__heading'),
    runway: select('.schematic__runway'),
    number,
  };
}

describe('<Schematic />', () => {
  it('draws nothing for a placement with no runway behind it', () => {
    // A stand, a bare coordinate or a fix. Rendering an empty box would imply a runway
    // relationship that does not exist; the numbers beside it still say everything.
    const { container } = render(<Schematic schematic={{ points: [] }} headingDeg={0} />);

    expect(container.querySelector('svg')).toBeNull();
  });

  it('draws nothing when the server sent a runway but no placement point', () => {
    const { container } = render(
      <Schematic
        schematic={finalSchematic({
          points: [point('threshold', 0, 0), point('runway_end', 1.62, 0)],
        })}
        headingDeg={0}
      />,
    );

    expect(container.querySelector('svg')).toBeNull();
  });

  it('names the runway it is drawing, for a screen reader and for the instructor', () => {
    const { container } = render(
      <Schematic schematic={finalSchematic()} headingDeg={0} />,
    );

    expect(container.querySelector('svg')).toHaveAttribute(
      'aria-label',
      'Placement diagram for runway 36',
    );
  });

  it('puts the aeroplane below the threshold on a final, chart-style', () => {
    const { aircraft, runway, number } = draw(finalSchematic(), 0);

    // Hand-computed: the frame spans x_nm -10 … 1.62, widened 10 % about its midpoint of
    // -4.19, so the scale is 136 / 12.782 = 10.6400 user units per NM.
    expect(number(aircraft, 'cx')).toBeCloseTo(160, 6);
    expect(number(aircraft, 'cy')).toBeCloseTo(151.818, 3);
    // The threshold end of the runway line, 45.42, is above the aeroplane on screen.
    expect(number(runway, 'y1')).toBeCloseTo(45.419, 3);
    expect(number(runway, 'y1')).toBeLessThan(number(aircraft, 'cy'));
  });

  it('points the heading vector up the diagram when the aircraft faces down the runway', () => {
    const { aircraft, heading, number } = draw(finalSchematic(), 0);

    expect(number(heading, 'x1')).toBeCloseTo(number(aircraft, 'cx'), 6);
    expect(number(heading, 'x2')).toBeCloseTo(160, 6);
    // 18 user units towards the threshold: a smaller SVG y is higher on screen.
    expect(number(heading, 'y2')).toBeCloseTo(151.818 - 18, 3);
  });

  it('points it back down the diagram on a downwind leg', () => {
    // The reciprocal of the runway heading. Getting the sign wrong here draws an aircraft
    // on downwind pointing at the runway it is flying away from.
    const { aircraft, heading, number } = draw(finalSchematic(), 180);

    expect(number(heading, 'x2')).toBeCloseTo(160, 6);
    expect(number(heading, 'y2')).toBeCloseTo(number(aircraft, 'cy') + 18, 3);
  });

  it('points it to the right of the diagram on a right base', () => {
    const { aircraft, heading, number } = draw(finalSchematic(), 90);

    expect(number(heading, 'x2')).toBeCloseTo(number(aircraft, 'cx') + 18, 3);
    expect(number(heading, 'y2')).toBeCloseTo(number(aircraft, 'cy'), 3);
  });

  it('measures the heading against the runway axis, not against the screen', () => {
    // Runway 09: bearing 090° true. An aircraft on final for it flies 090°, and the vector
    // must still point up the diagram — the whole picture is drawn in the runway's frame.
    const { aircraft, heading, number } = draw(
      finalSchematic({ runway_ident: '09', runway_true_bearing_deg: 90 }),
      90,
    );

    expect(number(heading, 'x2')).toBeCloseTo(number(aircraft, 'cx'), 6);
    expect(number(heading, 'y2')).toBeCloseTo(number(aircraft, 'cy') - 18, 3);
  });
});
