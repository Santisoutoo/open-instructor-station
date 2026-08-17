/**
 * Editor for the up-to-three cloud layers of the staged weather.
 *
 * Coverage is picked on octa chips, 0 to 8, each labelled with its METAR group.
 * Base and tops keep their invariant at write time: raising the base past the tops
 * carries the tops with it, and vice versa — a layer can never be inside out.
 */

import { coverageGroup } from './format';
import { NumberField } from './NumberField';
import type { CloudLayer } from './types.mock';

/** X-Plane models three cloud layers at most (feature-spec §3). */
const MAX_LAYERS = 3;

const OCTAS = [0, 1, 2, 3, 4, 5, 6, 7, 8] as const;

const NEW_LAYER: CloudLayer = { base_ft_agl: 3000, tops_ft_agl: 5000, coverage_octas: 4 };

interface CloudLayerEditorProps {
  layers: CloudLayer[];
  disabled: boolean;
  onChange: (layers: CloudLayer[]) => void;
}

export function CloudLayerEditor({ layers, disabled, onChange }: CloudLayerEditorProps) {
  const patch = (index: number, change: Partial<CloudLayer>) => {
    onChange(layers.map((layer, i) => (i === index ? { ...layer, ...change } : layer)));
  };

  return (
    <fieldset className="weather-group">
      <legend className="weather-group__title">Cloud layers</legend>
      {layers.length === 0 && <p className="weather-group__empty">Sky clear.</p>}
      {layers.map((layer, index) => (
        <div className="weather-layer" key={index}>
          <div className="weather-row">
            <NumberField
              label="Base"
              unit="ft AGL"
              value={layer.base_ft_agl}
              min={0}
              max={40000}
              step={100}
              disabled={disabled}
              onChange={(value) => {
                patch(index, {
                  base_ft_agl: value,
                  tops_ft_agl: Math.max(layer.tops_ft_agl, value),
                });
              }}
            />
            <NumberField
              label="Tops"
              unit="ft AGL"
              value={layer.tops_ft_agl}
              min={0}
              max={45000}
              step={100}
              disabled={disabled}
              onChange={(value) => {
                patch(index, {
                  tops_ft_agl: value,
                  base_ft_agl: Math.min(layer.base_ft_agl, value),
                });
              }}
            />
            <button
              type="button"
              className="weather-row__remove"
              disabled={disabled}
              onClick={() => {
                onChange(layers.filter((_layer, i) => i !== index));
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
                aria-pressed={layer.coverage_octas === octa}
                disabled={disabled}
                onClick={() => {
                  patch(index, { coverage_octas: octa });
                }}
              >
                {octa}
              </button>
            ))}
            <span className="weather-chiprow__group">
              {coverageGroup(layer.coverage_octas)}
            </span>
          </div>
        </div>
      ))}
      {layers.length < MAX_LAYERS && (
        <button
          type="button"
          className="weather-group__add"
          disabled={disabled}
          onClick={() => {
            onChange([...layers, { ...NEW_LAYER }]);
          }}
        >
          Add cloud layer
        </button>
      )}
    </fieldset>
  );
}
