/**
 * The manoeuvre controls: a straight/left/right segmented picker and the two
 * sliders (distance, angle) with numeric readouts — instructors trust a number over
 * a slider position at a glance. Tablet-first: every target is at least 44 px.
 *
 * D5 in the copy: the segment labels say where the NOSE ends up ("Nose right" turns
 * the final heading clockwise), because the opposite tail-swing reading is equally
 * defensible and this is where the convention meets the instructor.
 *
 * Dumb on purpose: form values and bounds come in as props, edits go out as
 * callbacks. The panel owns the reducer today and the store owns it after the
 * wiring wave — either way this component never knows.
 */

import type { PushbackDirection } from '../../api/models';
import { PUSHBACK_ANGLE_MIN_DEG, PUSHBACK_DISTANCE_MIN_M } from './pushbackSlice';

const SEGMENTS: { direction: PushbackDirection; label: string }[] = [
  { direction: 'left', label: 'Nose left' },
  { direction: 'straight', label: 'Straight' },
  { direction: 'right', label: 'Nose right' },
];

interface PushbackControlsProps {
  direction: PushbackDirection;
  distanceM: number;
  angleDeg: number;
  /**
   * Straight from `GET /api/pushback/manifest`, so the sliders hold no second copy of
   * `PushbackRequest`'s field constraints. `undefined` only while the gate is closed.
   */
  maxDistanceM: number | undefined;
  maxAngleDeg: number | undefined;
  /** True while the pushback gate is closed — every control disables, none disappears. */
  disabled: boolean;
  onDirectionSelected: (direction: PushbackDirection) => void;
  onDistanceChanged: (distanceM: number) => void;
  onAngleChanged: (angleDeg: number) => void;
}

export function PushbackControls({
  direction,
  distanceM,
  angleDeg,
  maxDistanceM,
  maxAngleDeg,
  disabled,
  onDirectionSelected,
  onDistanceChanged,
  onAngleChanged,
}: PushbackControlsProps) {
  const straight = direction === 'straight';

  return (
    <div className="pushback-controls">
      <div className="pushback-direction" role="group" aria-label="Pushback direction">
        {SEGMENTS.map((segment) => (
          <button
            key={segment.direction}
            type="button"
            className={
              segment.direction === direction
                ? 'pushback-direction__button pushback-direction__button--active'
                : 'pushback-direction__button'
            }
            aria-pressed={segment.direction === direction}
            disabled={disabled}
            onClick={() => onDirectionSelected(segment.direction)}
          >
            {segment.label}
          </button>
        ))}
      </div>

      <label className="pushback-slider">
        <span className="pushback-slider__label">Distance</span>
        <input
          type="range"
          min={PUSHBACK_DISTANCE_MIN_M}
          max={maxDistanceM}
          step={1}
          value={distanceM}
          disabled={disabled}
          aria-label="Pushback distance"
          onChange={(event) => onDistanceChanged(Number(event.target.value))}
        />
        <span className="pushback-slider__readout">{String(distanceM)} m</span>
      </label>

      <label className="pushback-slider">
        <span className="pushback-slider__label">Turn angle</span>
        <input
          type="range"
          min={PUSHBACK_ANGLE_MIN_DEG}
          max={maxAngleDeg}
          step={1}
          // The reducer zeroes the angle on 'straight'; the disabled slider shows it.
          value={straight ? 0 : angleDeg}
          disabled={disabled || straight}
          aria-label="Pushback turn angle"
          onChange={(event) => onAngleChanged(Number(event.target.value))}
        />
        <span className="pushback-slider__readout">
          {straight ? '—' : `${String(angleDeg)}°`}
        </span>
      </label>
    </div>
  );
}
