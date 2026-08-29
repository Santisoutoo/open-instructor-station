/**
 * Editor for the up-to-three cloud layers of the staged weather.
 *
 * Coverage is picked on octa chips, 0 to 8, each labelled with its METAR group — the wire
 * value is a 0-1 ratio (`coverage_ratio`), converted at the edges only (`format.ts`). Base
 * and tops are MSL, not AGL: X-Plane 12 and the adapter model clouds absolutely, and the
 * AGL heights a preset states are already resolved into MSL by the server before this editor
 * ever sees them. Base and tops keep their invariant at write time: raising the base past the
 * tops carries the tops with it, and vice versa — a layer can never be inside out.
 */

import { coverageGroup, octasToRatio, ratioToOctas } from './format';
import { NumberField } from './NumberField';
import type { CloudLayer, CloudType } from '../../api/models';

/** X-Plane models three cloud layers at most (feature-spec §3). */
const MAX_LAYERS = 3;

const OCTAS = [0, 1, 2, 3, 4, 5, 6, 7, 8] as const;

const CLOUD_TYPES: readonly CloudType[] = ['cirrus', 'stratus', 'cumulus', 'cumulonimbus'];

const NEW_LAYER: CloudLayer = {
  base_ft: 3000,
  tops_ft: 5000,
  coverage_ratio: 0.5,
  cloud_type: 'cumulus',
};

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
              unit="ft MSL"
              value={layer.base_ft}
              min={0}
              max={40000}
              step={100}
              disabled={disabled}
              onChange={(value) => {
                patch(index, { base_ft: value, tops_ft: Math.max(layer.tops_ft, value + 100) });
              }}
            />
            <NumberField
              label="Tops"
              unit="ft MSL"
              value={layer.tops_ft}
              min={100}
              max={45000}
              step={100}
              disabled={disabled}
              onChange={(value) => {
                patch(index, { tops_ft: value, base_ft: Math.min(layer.base_ft, value - 100) });
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
                aria-pressed={ratioToOctas(layer.coverage_ratio) === octa}
                disabled={disabled}
                onClick={() => {
                  patch(index, { coverage_ratio: octasToRatio(octa) });
                }}
              >
                {octa}
              </button>
            ))}
            <span className="weather-chiprow__group">{coverageGroup(layer.coverage_ratio)}</span>
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
