/**
 * One small-multiple trace: a titled SVG line of a single channel against time,
 * with a marker at the touchdown instant. Layout, scales and ticks come from the
 * pure modules; this file is markup only.
 */

import { useId } from 'react';
import { linearScale, paddedExtent, polylinePoints, ticks } from './scale';
import type { TraceSample } from './types.mock';

const WIDTH = 320;
const HEIGHT = 150;
const MARGIN = { top: 8, right: 8, bottom: 20, left: 44 };

export interface TraceChartProps {
  title: string;
  unit: string;
  samples: readonly TraceSample[];
  y: (sample: TraceSample) => number;
  touchdownIndex: number;
  /** A second series drawn dashed on the same axes (pitch + roll share a chart). */
  y2?: (sample: TraceSample) => number;
  y2Label?: string;
}

export function TraceChart({
  title,
  unit,
  samples,
  y,
  touchdownIndex,
  y2,
  y2Label,
}: TraceChartProps) {
  const titleId = useId();
  const first = samples[0];
  const last = samples[samples.length - 1];
  const touchdown = samples[touchdownIndex];
  if (first === undefined || last === undefined) {
    return null;
  }

  const values = samples.map(y);
  const allValues = y2 === undefined ? values : [...values, ...samples.map(y2)];
  const xScale = linearScale(
    [first.t_s, last.t_s],
    [MARGIN.left, WIDTH - MARGIN.right],
  );
  const yScale = linearScale(paddedExtent(allValues), [
    HEIGHT - MARGIN.bottom,
    MARGIN.top,
  ]);

  const yTicks = ticks(yScale.domainMin, yScale.domainMax, 3);
  const xTicks = ticks(first.t_s, last.t_s, 4);

  return (
    <figure className="trace-chart" role="img" aria-labelledby={titleId}>
      <figcaption id={titleId} className="trace-chart__title">
        {title} <span className="trace-chart__unit">({unit})</span>
        {y2Label !== undefined && (
          <span className="trace-chart__legend"> — dashed: {y2Label}</span>
        )}
      </figcaption>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="trace-chart__svg">
        {yTicks.map((tick) => (
          <g key={`y${tick}`}>
            <line
              className="trace-chart__grid"
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
        {touchdown !== undefined && (
          <line
            className="trace-chart__touchdown"
            x1={xScale(touchdown.t_s)}
            x2={xScale(touchdown.t_s)}
            y1={MARGIN.top}
            y2={HEIGHT - MARGIN.bottom}
          />
        )}
        <polyline
          className="trace-chart__line"
          points={polylinePoints(samples, (s) => s.t_s, y, xScale, yScale)}
        />
        {y2 !== undefined && (
          <polyline
            className="trace-chart__line trace-chart__line--secondary"
            points={polylinePoints(samples, (s) => s.t_s, y2, xScale, yScale)}
          />
        )}
      </svg>
    </figure>
  );
}
