import { useCallback, useRef } from 'react';
import type { WeatherSetup, WeatherState } from '../../api/models';
import type { AtmosphereSelection } from './AtmosphereProfile';
import { AtmosphereForm } from './AtmosphereForm';
import { CloudLayerEditor } from './CloudLayerEditor';
import { WeatherValidationContext } from './weatherValidationContext';
import { WindLayerEditor } from './WindLayerEditor';

export interface StationEditorsProps {
  resolved: WeatherState;
  selection: AtmosphereSelection | null;
  disabled: boolean;
  onSelect: (selection: AtmosphereSelection | null) => void;
  onField: (field: keyof WeatherSetup, value: unknown) => void;
  onInvalidChange: (invalid: boolean) => void;
}

/** Presentational station controls; the container owns the draft and simulator requests. */
export function StationEditors({
  resolved,
  selection,
  disabled,
  onSelect,
  onField,
  onInvalidChange,
}: StationEditorsProps) {
  const invalidFields = useRef(new Set<string>());
  const reportInvalid = useCallback(
    (id: string, invalid: boolean) => {
      if (invalid) invalidFields.current.add(id);
      else invalidFields.current.delete(id);
      onInvalidChange(invalidFields.current.size > 0);
    },
    [onInvalidChange],
  );
  const active =
    selection ??
    (resolved.wind_layers.length > 0
      ? { kind: 'wind', index: 0 }
      : resolved.cloud_layers.length > 0
        ? { kind: 'cloud', index: 0 }
        : null);
  return (
    <WeatherValidationContext.Provider value={reportInvalid}>
      <div className="station-editors">
        <WindLayerEditor
          layers={resolved.wind_layers}
          disabled={disabled}
          selectedIndex={active?.kind === 'wind' ? active.index : null}
          onSelect={(index) => onSelect(index === null ? null : { kind: 'wind', index })}
          onChange={(layers) => onField('wind_layers', layers)}
        />
        <CloudLayerEditor
          layers={resolved.cloud_layers}
          disabled={disabled}
          selectedIndex={active?.kind === 'cloud' ? active.index : null}
          onSelect={(index) => onSelect(index === null ? null : { kind: 'cloud', index })}
          onChange={(layers) => onField('cloud_layers', layers)}
        />
        <AtmosphereForm
          resolved={resolved}
          disabled={disabled}
          onField={onField}
          onContamination={(value) => onField('runway_contamination', value)}
        />
      </div>
    </WeatherValidationContext.Provider>
  );
}
