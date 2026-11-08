import { useId, useRef, useState } from 'react';
/**
 * Editor for the up-to-three cloud layers of the staged weather.
 *
 * Coverage is picked on octa chips, 0 to 8, each labelled with its METAR group — the wire
 * value is a 0-1 ratio (`coverage_ratio`), converted at the edges only (`format.ts`). Base
 * and tops are MSL, not AGL: X-Plane 12 and the adapter model clouds absolutely, and the
 * AGL heights a preset states are already resolved into MSL by the server before this editor
 * ever sees them. Neighbor bounds keep bases in ascending order.
 */

import { coverageGroup, octasToRatio, ratioToOctas } from './format';
import { nextCloudLayer, cloudBaseBounds } from './layerOperations';
import { NumberField } from './NumberField';
import type { CloudLayer, CloudType } from '../../api/models';

const OCTAS = [0, 1, 2, 3, 4, 5, 6, 7, 8] as const;

const CLOUD_TYPES: readonly CloudType[] = [
  'cirrus',
  'stratus',
  'cumulus',
  'cumulonimbus',
];

interface CloudLayerEditorProps {
  layers: CloudLayer[];
  disabled: boolean;
  onChange: (layers: CloudLayer[]) => void;
  selectedIndex?: number | null;
  onSelect?: (index: number | null) => void;
}

export function CloudLayerEditor({
  layers,
  disabled,
  onChange,
  selectedIndex,
  onSelect,
}: CloudLayerEditorProps) {
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
  const patch = (index: number, change: Partial<CloudLayer>) => {
    onChange(layers.map((layer, i) => (i === index ? { ...layer, ...change } : layer)));
  };

  const addition = nextCloudLayer(layers);

  return (
    <fieldset className="weather-group">
      <legend className="weather-group__title">Cloud layers</legend>
      {layers.length === 0 && <p className="weather-group__empty">Sky clear.</p>}
      {onSelect !== undefined && (
        <div className="weather-layer-selector" aria-label="Select cloud layer">
          {layers.map((layer, index) => (
            <button
              type="button"
              key={keys[index]}
              data-layer-index={index}
              aria-pressed={selectedIndex === index}
              disabled={disabled}
              onClick={() => onSelect(index)}
            >
              Cloud {index + 1} - {Math.round(layer.base_ft)} ft
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
          <div className="weather-layer">
            <div className="weather-row">
              <NumberField
                label="Base"
                unit="ft MSL"
                value={layer.base_ft}
                min={cloudBaseBounds(layers, index).min}
                max={cloudBaseBounds(layers, index).max}
                exclusiveMax={cloudBaseBounds(layers, index).max === layer.tops_ft}
                step={100}
                disabled={disabled}
                onChange={(value) => {
                  patch(index, { base_ft: value });
                }}
              />
              <NumberField
                label="Tops"
                unit="ft MSL"
                value={layer.tops_ft}
                min={layer.base_ft}
                exclusiveMin
                max={Infinity}
                step={100}
                disabled={disabled}
                onChange={(value) => {
                  patch(index, { tops_ft: value });
                }}
              />
              <label className="weather-field">
                <span className="weather-field__label">Type</span>
                <select
                  className="weather-field__input weather-field__input--select"
                  value={layer.cloud_type}
                  disabled={disabled}
                  onChange={(event) => {
                    patch(index, { cloud_type: event.target.value as CloudType });
                  }}
                >
                  {CLOUD_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {type}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className="weather-row__remove"
                disabled={disabled}
                onClick={() => {
                  setKeys((previous) => previous.filter((_key, i) => i !== index));
                  onChange(layers.filter((_layer, i) => i !== index));
                  onSelect?.(
                    layers.length > 1 ? Math.min(index, layers.length - 2) : null,
                  );
                }}
              >
                Remove
              </button>
            </div>
            <div
              className="weather-chiprow"
              role="group"
              aria-label={`Layer ${String(index + 1)} coverage in octas`}
            >
              {OCTAS.map((octa) => (
                <button
                  key={octa}
                  type="button"
                  className="weather-chip"
                  aria-pressed={ratioToOctas(layer.coverage_ratio) === octa}
                  disabled={disabled}
                  onClick={() => {
                    patch(index, { coverage_ratio: octasToRatio(octa) });
                  }}
                >
                  {octa}
                </button>
              ))}
              <span className="weather-chiprow__group">
                {coverageGroup(layer.coverage_ratio)}
              </span>
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
              ? 'At most three cloud layers; no room for another layer.'
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
          Add cloud layer
        </button>
      }
      {addition === null && (
        <p className="weather-group__empty">At most three cloud layers.</p>
      )}
    </fieldset>
  );
}
