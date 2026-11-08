import { useId, useRef, useState } from 'react';
/**
 * Editor for the up-to-three wind layers of the staged weather.
 *
 * Receives the **resolved** layers (current weather with the staged setup's fields replacing
 * it) and reports every change as a whole new array — the slice stores it as one sparse
 * override, so an edited wind wins over the preset in a single move (weather-manager.md D3:
 * a layer list REPLACES the whole set, no per-layer merge).
 */

import { nextWindLayer, windAltitudeBounds } from './layerOperations';
import { NumberField } from './NumberField';
import type { WindLayer } from '../../api/models';

interface WindLayerEditorProps {
  layers: WindLayer[];
  disabled: boolean;
  onChange: (layers: WindLayer[]) => void;
  selectedIndex?: number | null;
  onSelect?: (index: number | null) => void;
}

export function WindLayerEditor({
  layers,
  disabled,
  onChange,
  selectedIndex,
  onSelect,
}: WindLayerEditorProps) {
  const prefix = useId();
  const nextKey = useRef(layers.length);
  const [keys, setKeys] = useState(() =>
    layers.map((_layer, index) => `${prefix}-${String(index)}`),
  );
  if (keys.length !== layers.length) {
    setKeys((previous) =>
      layers.map(
        (_layer, index) => previous[index] ?? `${prefix}-external-${String(index)}`,
      ),
    );
  }
  const patch = (index: number, change: Partial<WindLayer>) => {
    onChange(layers.map((layer, i) => (i === index ? { ...layer, ...change } : layer)));
  };

  const addition = nextWindLayer(layers);

  return (
    <fieldset className="weather-group">
      <legend className="weather-group__title">Wind layers</legend>
      {layers.length === 0 && <p className="weather-group__empty">No wind — calm.</p>}
      {onSelect !== undefined && (
        <div className="weather-layer-selector" aria-label="Select wind layer">
          {layers.map((layer, index) => (
            <button
              type="button"
              key={keys[index]}
              data-layer-index={index}
              aria-pressed={selectedIndex === index}
              disabled={disabled}
              onClick={() => onSelect(index)}
            >
              Wind {index + 1} - {Math.round(layer.altitude_ft)} ft
            </button>
          ))}
        </div>
      )}
      {layers.map((layer, index) => (
        <div
          key={keys[index]}
          data-layer-index={index}
          hidden={selectedIndex !== undefined && selectedIndex !== index}
        >
          <div className="weather-row">
            <NumberField
              label="Altitude"
              unit="ft MSL"
              value={layer.altitude_ft}
              min={windAltitudeBounds(layers, index).min}
              max={windAltitudeBounds(layers, index).max}
              step={500}
              disabled={disabled}
              onChange={(value) => {
                patch(index, { altitude_ft: value });
              }}
            />
            <NumberField
              label="From"
              unit="° true"
              value={layer.direction_deg}
              min={0}
              max={360}
              step={10}
              disabled={disabled}
              onChange={(value) => {
                patch(index, { direction_deg: value });
              }}
            />
            <NumberField
              label="Speed"
              unit="kt"
              value={layer.speed_kt}
              min={0}
              max={Infinity}
              step={1}
              disabled={disabled}
              onChange={(value) => {
                patch(index, { speed_kt: value });
              }}
            />
            <NumberField
              label="Gust +"
              unit="kt"
              value={layer.gust_increase_kt}
              min={0}
              max={Infinity}
              step={1}
              disabled={disabled}
              onChange={(value) => {
                patch(index, { gust_increase_kt: value });
              }}
            />
            <NumberField
              label="Turbulence"
              unit="%"
              value={layer.turbulence_ratio * 100}
              min={0}
              max={100}
              step={5}
              disabled={disabled}
              onChange={(value) => {
                patch(index, { turbulence_ratio: value / 100 });
              }}
            />
            <button
              type="button"
              className="weather-row__remove"
              disabled={disabled}
              onClick={() => {
                setKeys((previous) => previous.filter((_key, i) => i !== index));
                onChange(layers.filter((_layer, i) => i !== index));
                onSelect?.(layers.length > 1 ? Math.min(index, layers.length - 2) : null);
              }}
            >
              Remove
            </button>
            <div
              className="weather-compass"
              aria-label={`Wind from ${String(layer.direction_deg)} degrees true`}
            >
              <svg viewBox="0 0 120 120" aria-hidden="true">
                <circle cx="60" cy="60" r="40" />
                <text x="60" y="14">
                  N
                </text>
                <text x="109" y="64">
                  E
                </text>
                <text x="60" y="116">
                  S
                </text>
                <text x="10" y="64">
                  W
                </text>
                <path
                  d="M 60 88 L 60 32 M 52 42 L 60 32 L 68 42"
                  transform={`rotate(${String(layer.direction_deg)} 60 60)`}
                />
              </svg>
              <input
                aria-label="Wind direction compass"
                type="range"
                min="0"
                max="360"
                step="1"
                value={layer.direction_deg}
                disabled={disabled}
                onChange={(event) =>
                  patch(index, { direction_deg: Number(event.target.value) })
                }
              />
            </div>
          </div>
        </div>
      ))}
      {
        <button
          type="button"
          className="weather-group__add"
          disabled={disabled || addition === null}
          title={
            addition === null
              ? 'At most three wind layers; no room for another layer.'
              : undefined
          }
          onClick={() => {
            if (addition !== null) {
              setKeys((previous) => [
                ...previous,
                `${prefix}-${String(nextKey.current++)}`,
              ]);
              onChange([...layers, addition]);
              onSelect?.(layers.length);
            }
          }}
        >
          Add wind layer
        </button>
      }
      {addition === null && (
        <p className="weather-group__empty">At most three wind layers.</p>
      )}
    </fieldset>
  );
}
