/**
 * Editor for the up-to-three wind layers of the staged weather.
 *
 * Receives the **resolved** layers (preset + overrides, crosswind already aimed at
 * the runway) and reports every change as a whole new array — the slice stores it
 * as one sparse override, so an edited wind wins over the preset in a single move.
 */

import { NumberField } from './NumberField';
import type { WindLayer } from './types.mock';

/** X-Plane models wind as three indexed layers at most (feature-spec §3). */
const MAX_LAYERS = 3;

const NEW_LAYER: WindLayer = {
  base_ft_msl: 5000,
  direction_deg: 270,
  speed_kt: 15,
  gust_kt: 0,
};

interface WindLayerEditorProps {
  layers: WindLayer[];
  disabled: boolean;
  onChange: (layers: WindLayer[]) => void;
}

export function WindLayerEditor({ layers, disabled, onChange }: WindLayerEditorProps) {
  const patch = (index: number, change: Partial<WindLayer>) => {
    onChange(layers.map((layer, i) => (i === index ? { ...layer, ...change } : layer)));
  };

  return (
    <fieldset className="weather-group">
      <legend className="weather-group__title">Wind layers</legend>
      {layers.length === 0 && <p className="weather-group__empty">No wind — calm.</p>}
      {layers.map((layer, index) => (
        <div className="weather-row" key={index}>
          <NumberField
            label="Base"
            unit="ft"
            value={layer.base_ft_msl}
            min={0}
            max={40000}
            step={500}
            disabled={disabled}
            onChange={(value) => {
              patch(index, { base_ft_msl: value });
            }}
          />
          <NumberField
            label="From"
            unit="°"
            value={layer.direction_deg}
            min={0}
            max={359}
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
            max={99}
            step={1}
            disabled={disabled}
            onChange={(value) => {
              patch(index, { speed_kt: value });
            }}
          />
          <NumberField
            label="Gust"
            unit="kt"
            value={layer.gust_kt}
            min={0}
            max={99}
            step={1}
            disabled={disabled}
            onChange={(value) => {
              patch(index, { gust_kt: value });
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
          Add wind layer
        </button>
      )}
    </fieldset>
  );
}
