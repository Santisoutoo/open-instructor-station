/**
 * Localizer and glideslope deviation against time, with the ±1-dot band shaded —
 * the "were we inside the tramlines" picture. Ends at touchdown: deviations on the
 * ground roll mean nothing.
 */

import { useId } from 'react';
import { linearScale, polylinePoints, ticks } from './scale';
import type { TraceSample } from './types.mock';

const WIDTH = 660;
const HEIGHT = 170;
const MARGIN = { top: 8, right: 8, bottom: 20, left: 44 };
const DOT_DOMAIN: readonly [number, number] = [-2, 2];

export function DeviationChart({
  samples,
  touchdownIndex,
}: {
  samples: readonly TraceSample[];
  touchdownIndex: number;
}) {
  const titleId = useId();
  const airborne = samples.slice(0, Math.max(2, touchdownIndex));
  const first = airborne[0];
  const last = airborne[airborne.length - 1];
  if (first === undefined || last === undefined) {
    return null;
  }

  const xScale = linearScale(
    [first.t_s, last.t_s],
    [MARGIN.left, WIDTH - MARGIN.right],
  );
  const yScale = linearScale(DOT_DOMAIN, [HEIGHT - MARGIN.bottom, MARGIN.top]);
  const xTicks = ticks(first.t_s, last.t_s, 6);

  return (
    <figure className="trace-chart trace-chart--wide" role="img" aria-labelledby={titleId}>
      <figcaption id={titleId} className="trace-chart__title">
        LOC / GS deviation <span className="trace-chart__unit">(dots)</span>
        <span className="trace-chart__legend"> — dashed: glideslope</span>
      </figcaption>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="trace-chart__svg">
        <rect
          className="trace-chart__band"
          x={MARGIN.left}
          width={WIDTH - MARGIN.left - MARGIN.right}
          y={yScale(1)}
          height={yScale(-1) - yScale(1)}
        />
        {[-2, -1, 0, 1, 2].map((tick) => (
          <g key={tick}>
            <line
              className={
                tick === 0 ? 'trace-chart__grid trace-chart__grid--zero' : 'trace-chart__grid'
              }
              x1={MARGIN.left}
              x2={WIDTH - MARGIN.right}
              y1={yScale(tick)}
              y2={yScale(tick)}
            />
            <text
              className="trace-chart__tick"
              x={MARGIN.left - 6}
              y={yScale(tick)}
              textAnchor="end"
              dominantBaseline="middle"
            >
              {tick}
            </text>
          </g>
        ))}
        {xTicks.map((tick) => (
          <text
            key={`x${tick}`}
            className="trace-chart__tick"
            x={xScale(tick)}
            y={HEIGHT - 6}
            textAnchor="middle"
          >
            {tick}s
          </text>
        ))}
        <polyline
          className="trace-chart__line"
          points={polylinePoints(airborne, (s) => s.t_s, (s) => s.loc_dev_dot, xScale, yScale)}
        />
        <polyline
          className="trace-chart__line trace-chart__line--secondary"
          points={polylinePoints(airborne, (s) => s.t_s, (s) => s.gs_dev_dot, xScale, yScale)}
        />
      </svg>
    </figure>
  );
}
