import { useAppDispatch, useAppSelector } from '../../store';
import { SPAWN_TEMPLATES } from './mock';
import { useSpawnTrafficMutation } from './trafficApi';
import {
  COUNT_MAX,
  COUNT_MIN,
  DISTANCE_MAX_NM,
  DISTANCE_MIN_NM,
  countChanged,
  distanceChanged,
  spawnKindSelected,
} from './trafficSlice';
import type { SpawnTemplateId } from './types.mock';

interface SpawnGridProps {
  /** True while the traffic gate is closed — every control disables, none disappears. */
  disabled: boolean;
}

/**
 * The spawn surface: a short parameter row, then one-tap cards for the three kinds and
 * the four scenario shapes. Tapping a card spawns immediately — an instructor mid-lesson
 * gets traffic on the first touch, and anything spawned is one tap from despawned, so a
 * confirm step would only cost time.
 *
 * Design note: this panel's "primary action" is plural — seven equal cards — so none of
 * them takes the one solid-amber slot a panel normally gives its primary action. This is
 * a sanctioned exception: cards stay neutral with a hover border, and amber appears only
 * on focus rings.
 */
export function SpawnGrid({ disabled }: SpawnGridProps) {
  const dispatch = useAppDispatch();
  const params = useAppSelector((state) => state.traffic.params);
  const lastUsed = useAppSelector((state) => state.traffic.selectedSpawnKind);
  const latest = useAppSelector((state) => state.telemetry.latest);
  const [spawnTraffic] = useSpawnTrafficMutation();

  const spawn = (template: SpawnTemplateId) => {
    dispatch(spawnKindSelected(template));
    void spawnTraffic({
      template,
      count: params.count,
      distanceNm: params.distanceNm,
      own:
        latest === null
          ? null
          : {
              position: { lat: latest.latitude, lon: latest.longitude },
              altitude_ft: latest.altitude_ft,
              heading_deg: latest.heading_deg,
            },
    });
  };

  return (
    <div className="traffic-spawn">
      <div className="traffic-params">
        <Stepper
          label="Count"
          value={params.count}
          unit=""
          min={COUNT_MIN}
          max={COUNT_MAX}
          step={1}
          disabled={disabled}
          onChange={(value) => dispatch(countChanged(value))}
        />
        <Stepper
          label="Distance"
          value={params.distanceNm}
          unit=" NM"
          min={DISTANCE_MIN_NM}
          max={DISTANCE_MAX_NM}
          step={2}
          disabled={disabled}
          onChange={(value) => dispatch(distanceChanged(value))}
        />
      </div>

      <div className="traffic-grid">
        {SPAWN_TEMPLATES.map((template) => (
          <button
            key={template.id}
            type="button"
            className={
              template.id === lastUsed
                ? 'traffic-card traffic-card--last'
                : 'traffic-card'
            }
            disabled={disabled}
            onClick={() => spawn(template.id)}
          >
            <span className="traffic-card-label">{template.label}</span>
            <span className="traffic-card-desc">{template.description}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

interface StepperProps {
  label: string;
  value: number;
  unit: string;
  min: number;
  max: number;
  step: number;
  disabled: boolean;
  onChange: (value: number) => void;
}

/** A touch stepper: −/+ around a mono readout. The slice clamps, so edges just stop. */
function Stepper({ label, value, unit, min, max, step, disabled, onChange }: StepperProps) {
  return (
    <div className="traffic-stepper">
      <span className="traffic-stepper-label">{label}</span>
      <div className="traffic-stepper-row" role="group" aria-label={label}>
        <button
          type="button"
          className="traffic-stepper-button"
          aria-label={`Decrease ${label.toLowerCase()}`}
          disabled={disabled || value <= min}
          onClick={() => onChange(value - step)}
        >
          −
        </button>
        <span className="traffic-stepper-value">
          {value}
          {unit}
        </span>
        <button
          type="button"
          className="traffic-stepper-button"
          aria-label={`Increase ${label.toLowerCase()}`}
          disabled={disabled || value >= max}
          onClick={() => onChange(value + step)}
        >
          +
        </button>
      </div>
    </div>
  );
}
