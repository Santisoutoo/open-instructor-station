/**
 * The preset surface: seven tiles, two-tap flow, no modals.
 *
 * The first tap **stages** the preset — the editors and the staging bar appear,
 * nothing changes in the simulator. The second tap on the same tile commits, the
 * same as the staging bar's Apply button. A relative preset whose runway is not
 * known yet is dimmed and disabled but never hidden, and always says why.
 */

import { useAppDispatch, useAppSelector } from '../../store';
import { presetGate } from './gate';
import { WEATHER_PRESETS } from './mock';
import { presetStaged } from './weatherSlice';

interface PresetGridProps {
  /** True while the weather gate is closed — every tile disables, none disappears. */
  disabled: boolean;
  selectedIcao: string | null;
  selectedRunwayIdent: string | null;
  /** The second tap on the staged tile commits through this. */
  onCommit: () => void;
}

export function PresetGrid({
  disabled,
  selectedIcao,
  selectedRunwayIdent,
  onCommit,
}: PresetGridProps) {
  const dispatch = useAppDispatch();
  const staged = useAppSelector((state) => state.weather.staged);
  const selectedPresetId = useAppSelector((state) => state.weather.selectedPresetId);

  return (
    <div className="weather-grid">
      {WEATHER_PRESETS.map((preset) => {
        const gate = presetGate(preset, selectedIcao, selectedRunwayIdent);
        const isStaged = staged && preset.id === selectedPresetId;
        return (
          <button
            key={preset.id}
            type="button"
            className={isStaged ? 'weather-tile weather-tile--staged' : 'weather-tile'}
            disabled={disabled || !gate.open}
            aria-pressed={isStaged}
            onClick={() => {
              if (isStaged) {
                onCommit();
              } else {
                dispatch(presetStaged(preset.id));
              }
            }}
          >
            <span className="weather-tile__label">{preset.label}</span>
            <span className="weather-tile__desc">{preset.description}</span>
            {!gate.open && <span className="weather-tile__reason">{gate.reason}</span>}
            {isStaged && <span className="weather-tile__hint">Tap again to apply</span>}
          </button>
        );
      })}
    </div>
  );
}
