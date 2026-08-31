/**
 * The atmosphere profile: a vertical MSL scale with cloud bands and wind barbs, drag-editable.
 * Pure props → SVG, no store access — `CircuitDiagram`/`ProcedureDiagram`'s rule.
 *
 * Delivered exported but unmounted (#183); #185 wires it into `WeatherPanel.tsx`.
 *
 * Every draggable edge is drawn twice, `CircuitDiagram`'s dual-draw rule: an `aria-hidden` SVG
 * shape at its projected y, and a real, transparent `<button>` positioned in **container
 * percentages**, never viewBox pixels — `.atmo` scales down on a tablet, and a pixel-positioned
 * handle would drift off its visual target on any narrower viewport.
 *
 * No `setPointerCapture` — this codebase has no precedent for it and no jsdom polyfill
 * (`ui/src/test/setup.ts` has none). A drag's `pointermove`/`pointerup`/`pointercancel`
 * listeners live on `window` for the duration of the gesture instead, attached on pointerdown
 * and torn down on release, cancel, or unmount. The change callback fires exactly once, on
 * release, only when the snapped/clamped result actually differs from the original — never
 * during the drag itself, so a drag from 2 500 ft to 4 000 ft sends one command, not fifteen.
 */

import type { KeyboardEvent, PointerEvent } from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { CloudLayer, WeatherState, WindLayer } from '../../api/models';
import { coverageGroup, formatWind } from './format';
import {
  PLOT_X0,
  PLOT_X1,
  SNAP_FT,
  VIEWBOX_H,
  VIEWBOX_W,
  WIND_GUTTER_CX,
  aglLabel,
  altitudeToY,
  computeAltitudeScale,
  moveCloudBase,
  moveCloudTops,
  moveWindAltitude,
  projectCloudLayers,
  projectWindLayers,
  terrainBand,
  tickAltitudes,
  windBarbPath,
} from './atmosphereProjection';
import './atmosphereProfile.css';

export interface AtmosphereSelection {
  readonly kind: 'wind' | 'cloud';
  readonly index: number;
}

export interface AtmosphereProfileProps {
  readonly state: WeatherState;
  readonly fieldElevationFt: number | null;
  readonly selection: AtmosphereSelection | null;
  readonly readOnly: boolean;
  readonly onWindLayersChange: (layers: WindLayer[]) => void;
  readonly onCloudLayersChange: (layers: CloudLayer[]) => void;
  readonly onSelect: (selection: AtmosphereSelection | null) => void;
}

type DragKind = 'cloud-base' | 'cloud-tops' | 'wind';

interface DragState {
  readonly kind: DragKind;
  readonly index: number;
  readonly startClientY: number;
  readonly startAltFt: number;
  readonly ftPerPx: number;
  readonly draftAltFt: number;
  readonly moved: boolean;
}

const INTEGER = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });

const CLOUD_TYPE_GLYPH: Record<CloudLayer['cloud_type'], string> = {
  cirrus: 'Ci',
  stratus: 'St',
  cumulus: 'Cu',
  cumulonimbus: 'Cb',
};

function leftPercent(x: number): string {
  return `${String((x / VIEWBOX_W) * 100)}%`;
}
function widthPercent(width: number): string {
  return `${String((width / VIEWBOX_W) * 100)}%`;
}
function topPercent(y: number): string {
  return `${String((y / VIEWBOX_H) * 100)}%`;
}

export function AtmosphereProfile({
  state,
  fieldElevationFt,
  selection,
  readOnly,
  onWindLayersChange,
  onCloudLayersChange,
  onSelect,
}: AtmosphereProfileProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [drag, setDrag] = useState<DragState | null>(null);

  // Read by `commit` (below) so a listener attached at drag-start never acts on a stale
  // closure if props change mid-drag. Synced in an effect, not during render — refs are for
  // event handlers/effects, never for values read while rendering.
  const latestRef = useRef({ state, onWindLayersChange, onCloudLayersChange });
  useEffect(() => {
    latestRef.current = { state, onWindLayersChange, onCloudLayersChange };
  });

  const scale = computeAltitudeScale(state.wind_layers, state.cloud_layers);

  // The live drag preview and the eventual commit go through the same `moveX` helper with the
  // same value, so they never disagree.
  const effectiveCloudLayers =
    drag !== null && drag.kind !== 'wind'
      ? state.cloud_layers.map((layer, i) =>
          i === drag.index
            ? drag.kind === 'cloud-tops'
              ? moveCloudTops(layer, drag.draftAltFt)
              : moveCloudBase(layer, drag.draftAltFt)
            : layer,
        )
      : state.cloud_layers;

  const effectiveWindLayers =
    drag !== null && drag.kind === 'wind'
      ? state.wind_layers.map((layer, i) =>
          i === drag.index ? moveWindAltitude(layer, drag.draftAltFt) : layer,
        )
      : state.wind_layers;

  const projectedClouds = projectCloudLayers(effectiveCloudLayers, scale, VIEWBOX_H);
  const projectedWind = projectWindLayers(effectiveWindLayers, scale, VIEWBOX_H);
  const ticks = tickAltitudes(scale);
  const terrain = terrainBand(fieldElevationFt, scale, VIEWBOX_H);

  const commit = useCallback((finished: DragState) => {
    if (!finished.moved) {
      return;
    }
    const { state: latestState, onWindLayersChange: onWind, onCloudLayersChange: onCloud } =
      latestRef.current;

    if (finished.kind === 'wind') {
      const original = latestState.wind_layers[finished.index];
      if (original === undefined) {
        return;
      }
      const next = moveWindAltitude(original, finished.draftAltFt);
      if (next.altitude_ft === original.altitude_ft) {
        return;
      }
      onWind(latestState.wind_layers.map((layer, i) => (i === finished.index ? next : layer)));
      return;
    }

    const original = latestState.cloud_layers[finished.index];
    if (original === undefined) {
      return;
    }
    const next =
      finished.kind === 'cloud-tops'
        ? moveCloudTops(original, finished.draftAltFt)
        : moveCloudBase(original, finished.draftAltFt);
    const changed =
      finished.kind === 'cloud-tops'
        ? next.tops_ft !== original.tops_ft
        : next.base_ft !== original.base_ft;
    if (!changed) {
      return;
    }
    onCloud(latestState.cloud_layers.map((layer, i) => (i === finished.index ? next : layer)));
  }, []);

  const isDragging = drag !== null;
  useEffect(() => {
    if (!isDragging) {
      return;
    }
    const onMove = (event: globalThis.PointerEvent) => {
      setDrag((current) => {
        if (current === null) {
          return current;
        }
        const deltaFt = (current.startClientY - event.clientY) * current.ftPerPx;
        return { ...current, draftAltFt: current.startAltFt + deltaFt, moved: true };
      });
    };
    const onUp = () => {
      setDrag((current) => {
        if (current !== null) {
          commit(current);
        }
        return null;
      });
    };
    const onCancel = () => {
      setDrag(null);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onCancel);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onCancel);
    };
  }, [isDragging, commit]);

  const startDrag = (kind: DragKind, index: number, startAltFt: number, event: PointerEvent) => {
    event.preventDefault();
    onSelect({ kind: kind === 'wind' ? 'wind' : 'cloud', index });
    const rect = svgRef.current?.getBoundingClientRect();
    if (rect === undefined || rect.height <= 0) {
      return;
    }
    setDrag({
      kind,
      index,
      startClientY: event.clientY,
      startAltFt,
      ftPerPx: scale.topFt / rect.height,
      draftAltFt: startAltFt,
      moved: false,
    });
  };

  const handleKeyboard = (
    event: KeyboardEvent,
    kind: DragKind,
    index: number,
    currentAltFt: number,
  ) => {
    if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') {
      return;
    }
    event.preventDefault();
    const targetAltFt = currentAltFt + (event.key === 'ArrowUp' ? SNAP_FT : -SNAP_FT);
    if (kind === 'wind') {
      const original = state.wind_layers[index];
      if (original === undefined) {
        return;
      }
      const next = moveWindAltitude(original, targetAltFt);
      onWindLayersChange(state.wind_layers.map((layer, i) => (i === index ? next : layer)));
      return;
    }
    const original = state.cloud_layers[index];
    if (original === undefined) {
      return;
    }
    const next =
      kind === 'cloud-tops' ? moveCloudTops(original, targetAltFt) : moveCloudBase(original, targetAltFt);
    onCloudLayersChange(state.cloud_layers.map((layer, i) => (i === index ? next : layer)));
  };

  return (
    <div className="atmo">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${String(VIEWBOX_W)} ${String(VIEWBOX_H)}`}
        width={VIEWBOX_W}
        height={VIEWBOX_H}
        className="atmo__svg"
        role="img"
        aria-label="Atmosphere profile"
        onClick={(event) => {
          if (event.target === event.currentTarget) {
            onSelect(null);
          }
        }}
      >
        <g className="atmo__scale" aria-hidden="true">
          {ticks.map((tick) => {
            const y = altitudeToY(tick, scale, VIEWBOX_H);
            const agl = aglLabel(tick, fieldElevationFt);
            return (
              <g key={tick}>
                <line x1={PLOT_X0} y1={y} x2={PLOT_X1} y2={y} />
                <text x={PLOT_X0 - 6} y={y + 3} textAnchor="end">
                  {INTEGER.format(tick)}
                </text>
                {agl !== null && (
                  <text className="atmo__agl" x={PLOT_X1 + 6} y={y + 3} textAnchor="start">
                    {agl}
                  </text>
                )}
              </g>
            );
          })}
        </g>

        {terrain !== null && (
          <rect
            className="atmo__terrain"
            x={PLOT_X0}
            width={PLOT_X1 - PLOT_X0}
            y={terrain.y}
            height={terrain.height}
          />
        )}

        <g className="atmo__clouds" aria-hidden="true">
          {projectedClouds.map(({ layer, index, baseY, topsY }) => {
            const selected = selection?.kind === 'cloud' && selection.index === index;
            const classes = [
              'atmo__cloud-band',
              `atmo__cloud-band--${layer.cloud_type}`,
              `atmo__cloud-band--${coverageGroup(layer.coverage_ratio).toLowerCase()}`,
            ];
            if (selected) {
              classes.push('atmo__cloud-band--selected');
            }
            return (
              <g key={index}>
                <rect
                  className={classes.join(' ')}
                  x={PLOT_X0}
                  width={PLOT_X1 - PLOT_X0}
                  y={topsY}
                  height={baseY - topsY}
                  fillOpacity={0.25 + 0.6 * layer.coverage_ratio}
                />
                <text
                  className="atmo__cloud-glyph"
                  x={(PLOT_X0 + PLOT_X1) / 2}
                  y={(topsY + baseY) / 2}
                >
                  {CLOUD_TYPE_GLYPH[layer.cloud_type]}
                </text>
              </g>
            );
          })}
        </g>

        <g className="atmo__wind" aria-hidden="true">
          {projectedWind.map(({ layer, index, y }) => {
            const path = windBarbPath(layer.speed_kt);
            return (
              <g key={index}>
                {path === '' ? (
                  <circle className="atmo__barb-calm" cx={WIND_GUTTER_CX} cy={y} r={5} />
                ) : (
                  <g
                    transform={`rotate(${String(layer.direction_deg)} ${String(WIND_GUTTER_CX)} ${String(y)})`}
                    className="atmo__barb"
                  >
                    <path d={path} transform={`translate(${String(WIND_GUTTER_CX)} ${String(y)})`} />
                  </g>
                )}
                <text className="atmo__wind-label" x={WIND_GUTTER_CX} y={y + 16}>
                  {formatWind(layer)}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      {projectedClouds.map(({ layer, index, baseY, topsY }) => {
        const selected = selection?.kind === 'cloud' && selection.index === index;
        return (
          <div key={index}>
            <button
              type="button"
              className="atmo__select"
              style={{
                left: leftPercent(PLOT_X0),
                width: widthPercent(PLOT_X1 - PLOT_X0),
                top: topPercent((baseY + topsY) / 2),
              }}
              aria-pressed={selected}
              onClick={() => {
                onSelect({ kind: 'cloud', index });
              }}
            >
              <span className="atmo-sr-only">
                {`Cloud layer ${String(index + 1)}, base ${INTEGER.format(Math.round(layer.base_ft))} ft, tops ${INTEGER.format(Math.round(layer.tops_ft))} ft MSL`}
              </span>
            </button>
            {!readOnly && (
              <>
                <button
                  type="button"
                  className="atmo__handle atmo__handle--tops"
                  style={{
                    left: leftPercent(PLOT_X0),
                    width: widthPercent(PLOT_X1 - PLOT_X0),
                    top: topPercent(topsY),
                  }}
                  onPointerDown={(event) => {
                    startDrag('cloud-tops', index, layer.tops_ft, event);
                  }}
                  onKeyDown={(event) => {
                    handleKeyboard(event, 'cloud-tops', index, layer.tops_ft);
                  }}
                >
                  <span className="atmo-sr-only">
                    {`Cloud layer ${String(index + 1)} tops, ${INTEGER.format(Math.round(layer.tops_ft))} ft MSL`}
                  </span>
                </button>
                <button
                  type="button"
                  className="atmo__handle atmo__handle--base"
                  style={{
                    left: leftPercent(PLOT_X0),
                    width: widthPercent(PLOT_X1 - PLOT_X0),
                    top: topPercent(baseY),
                  }}
                  onPointerDown={(event) => {
                    startDrag('cloud-base', index, layer.base_ft, event);
                  }}
                  onKeyDown={(event) => {
                    handleKeyboard(event, 'cloud-base', index, layer.base_ft);
                  }}
                >
                  <span className="atmo-sr-only">
                    {`Cloud layer ${String(index + 1)} base, ${INTEGER.format(Math.round(layer.base_ft))} ft MSL`}
                  </span>
                </button>
              </>
            )}
          </div>
        );
      })}

      {projectedWind.map(({ layer, index, y }) => {
        const selected = selection?.kind === 'wind' && selection.index === index;
        return (
          <button
            key={index}
            type="button"
            className={readOnly ? 'atmo__select' : 'atmo__handle atmo__handle--wind'}
            style={{ left: leftPercent(WIND_GUTTER_CX), top: topPercent(y) }}
            aria-pressed={selected}
            onClick={() => {
              if (readOnly) {
                onSelect({ kind: 'wind', index });
              }
            }}
            onPointerDown={(event) => {
              if (!readOnly) {
                startDrag('wind', index, layer.altitude_ft, event);
              }
            }}
            onKeyDown={(event) => {
              if (!readOnly) {
                handleKeyboard(event, 'wind', index, layer.altitude_ft);
              }
            }}
          >
            <span className="atmo-sr-only">
              {`Wind layer ${String(index + 1)}, ${INTEGER.format(Math.round(layer.altitude_ft))} ft MSL, ${formatWind(layer)}`}
            </span>
          </button>
        );
      })}
    </div>
  );
}
