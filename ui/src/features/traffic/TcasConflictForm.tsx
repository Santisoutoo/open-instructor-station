/**
 * Spawn a TCAS conflict: an intruder converging on the user aircraft's own projected
 * position (design §7.1).
 *
 * The severity picker is segmented, and each preset carries the plain-language sentence
 * of what it means in seconds and feet — read off `TCAS_SEVERITY_PROFILES` in
 * `core/traffic.py` (design §6.1), so the instructor knows what they are about to do to
 * the student before they tap Spawn. Every field of the request body is sent explicitly:
 * no picker silently defaults a field (design §8.6).
 *
 * Emits the request through `onSpawn`; the RTK Query mutation arrives with the wiring
 * wave.
 */

import { useState } from 'react';
import { SEVERITY_LABELS, SEVERITY_SENTENCES } from './presets';
import type { TcasConflictSpawnRequest, TcasSeverity, TrafficKind } from './types.mock';

const SEVERITIES: TcasSeverity[] = ['head_on_ra', 'crossing_ra', 'ta_only'];
const KINDS: TrafficKind[] = ['aircraft', 'ground_vehicle', 'bird'];

interface TcasConflictFormProps {
  disabled: boolean;
  onSpawn: (request: TcasConflictSpawnRequest) => void;
}

export function TcasConflictForm({ disabled, onSpawn }: TcasConflictFormProps) {
  const [severity, setSeverity] = useState<TcasSeverity>('head_on_ra');
  const [bearing, setBearing] = useState('180');
  const [missSide, setMissSide] = useState<'left' | 'right'>('left');
  const [verticalOffset, setVerticalOffset] = useState<'above' | 'below'>('above');
  const [closureIas, setClosureIas] = useState('');
  const [kind, setKind] = useState<TrafficKind>('aircraft');
  const [callsign, setCallsign] = useState('TFC01');

  const bearingValue = Number(bearing);
  const ready =
    bearing.trim() !== '' &&
    Number.isFinite(bearingValue) &&
    bearingValue >= 0 &&
    bearingValue < 360 &&
    callsign.trim() !== '';

  return (
    <form
      className="traffic-form"
      aria-label="TCAS conflict"
      onSubmit={(event) => {
        event.preventDefault();
        onSpawn({
          type: 'tcas_conflict',
          severity,
          relative_bearing_deg: bearingValue,
          miss_side: missSide,
          vertical_offset: verticalOffset,
          closure_ias_kt: closureIas.trim() === '' ? null : Number(closureIas),
          kind,
          callsign: callsign.trim(),
        });
      }}
    >
      <fieldset className="traffic-seg" disabled={disabled}>
        <legend className="traffic-form__label">Severity</legend>
        {SEVERITIES.map((option) => (
          <button
            key={option}
            type="button"
            className="traffic-seg__option"
            aria-pressed={severity === option}
            onClick={() => {
              setSeverity(option);
            }}
          >
            {SEVERITY_LABELS[option]}
          </button>
        ))}
      </fieldset>
      <p className="traffic-form__sentence">{SEVERITY_SENTENCES[severity]}</p>

      <div className="traffic-form__row">
        <label className="traffic-form__field">
          <span>Relative bearing °</span>
          <input
            type="number"
            min={0}
            max={359.9}
            step="any"
            value={bearing}
            disabled={disabled}
            onChange={(event) => {
              setBearing(event.target.value);
            }}
          />
        </label>
        <label className="traffic-form__field">
          <span>Closure IAS kt</span>
          <input
            type="number"
            min={0}
            placeholder="250 (default)"
            value={closureIas}
            disabled={disabled}
            onChange={(event) => {
              setClosureIas(event.target.value);
            }}
          />
        </label>
        <label className="traffic-form__field">
          <span>Callsign</span>
          <input
            type="text"
            className="mono"
            maxLength={12}
            value={callsign}
            disabled={disabled}
            onChange={(event) => {
              setCallsign(event.target.value);
            }}
          />
        </label>
      </div>

      <fieldset className="traffic-seg" disabled={disabled}>
        <legend className="traffic-form__label">Miss side</legend>
        {(['left', 'right'] as const).map((option) => (
          <button
            key={option}
            type="button"
            className="traffic-seg__option"
            aria-pressed={missSide === option}
            onClick={() => {
              setMissSide(option);
            }}
          >
            {option}
          </button>
        ))}
      </fieldset>

      <fieldset className="traffic-seg" disabled={disabled}>
        <legend className="traffic-form__label">Vertical offset</legend>
        {(['above', 'below'] as const).map((option) => (
          <button
            key={option}
            type="button"
            className="traffic-seg__option"
            aria-pressed={verticalOffset === option}
            onClick={() => {
              setVerticalOffset(option);
            }}
          >
            {option}
          </button>
        ))}
      </fieldset>

      <fieldset className="traffic-seg" disabled={disabled}>
        <legend className="traffic-form__label">Kind</legend>
        {KINDS.map((option) => (
          <button
            key={option}
            type="button"
            className="traffic-seg__option"
            aria-pressed={kind === option}
            onClick={() => {
              setKind(option);
            }}
          >
            {option.replace('_', ' ')}
          </button>
        ))}
      </fieldset>

      <button type="submit" className="traffic-form__spawn" disabled={disabled || !ready}>
        Spawn TCAS conflict
      </button>
    </form>
  );
}
