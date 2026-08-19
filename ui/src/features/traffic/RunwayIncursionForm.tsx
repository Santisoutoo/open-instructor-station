/**
 * Spawn a runway incursion: a vehicle or aircraft crossing the runway, timed against
 * the user's own closing speed (design §7.1).
 *
 * The design asks this form to reuse the Position Manager's airport/runway selector;
 * that reuse needs the live navdata endpoints and belongs to the wiring wave, so for
 * the pure-logic slice the runway is named by plain ICAO + ident inputs — the exact
 * fields the request carries. Every field of the body is sent explicitly (design §8.6).
 */

import { useState } from 'react';
import type { RunwayIncursionSpawnRequest, TrafficKind } from './types.mock';

const KINDS: TrafficKind[] = ['ground_vehicle', 'aircraft'];

interface RunwayIncursionFormProps {
  disabled: boolean;
  onSpawn: (request: RunwayIncursionSpawnRequest) => void;
}

export function RunwayIncursionForm({ disabled, onSpawn }: RunwayIncursionFormProps) {
  const [icao, setIcao] = useState('');
  const [runwayIdent, setRunwayIdent] = useState('');
  const [crossAt, setCrossAt] = useState('0');
  const [leadTime, setLeadTime] = useState('8');
  const [fromSide, setFromSide] = useState<'left' | 'right'>('left');
  const [vehicleSpeed, setVehicleSpeed] = useState('');
  const [kind, setKind] = useState<TrafficKind>('ground_vehicle');
  const [callsign, setCallsign] = useState('GND01');

  const ready =
    icao.trim().length >= 2 &&
    runwayIdent.trim() !== '' &&
    Number.isFinite(Number(crossAt)) &&
    crossAt.trim() !== '' &&
    Number.isFinite(Number(leadTime)) &&
    leadTime.trim() !== '' &&
    callsign.trim() !== '';

  return (
    <form
      className="traffic-form"
      aria-label="Runway incursion"
      onSubmit={(event) => {
        event.preventDefault();
        onSpawn({
          type: 'runway_incursion',
          airport_icao: icao.trim().toUpperCase(),
          runway_ident: runwayIdent.trim().toUpperCase(),
          cross_at_along_track_nm: Number(crossAt),
          lead_time_before_user_arrival_s: Number(leadTime),
          from_side: fromSide,
          vehicle_speed_kt: vehicleSpeed.trim() === '' ? null : Number(vehicleSpeed),
          kind,
          callsign: callsign.trim(),
        });
      }}
    >
      <div className="traffic-form__row">
        <label className="traffic-form__field">
          <span>Airport ICAO</span>
          <input
            type="text"
            className="mono"
            placeholder="LEMD"
            maxLength={7}
            value={icao}
            disabled={disabled}
            onChange={(event) => {
              setIcao(event.target.value);
            }}
          />
        </label>
        <label className="traffic-form__field">
          <span>Runway</span>
          <input
            type="text"
            className="mono"
            placeholder="32L"
            maxLength={3}
            value={runwayIdent}
            disabled={disabled}
            onChange={(event) => {
              setRunwayIdent(event.target.value);
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

      <div className="traffic-form__row">
        <label className="traffic-form__field">
          <span>Crossing offset NM</span>
          <input
            type="number"
            step="any"
            value={crossAt}
            disabled={disabled}
            onChange={(event) => {
              setCrossAt(event.target.value);
            }}
          />
        </label>
        <label className="traffic-form__field">
          <span>Lead time s</span>
          <input
            type="number"
            step="any"
            value={leadTime}
            disabled={disabled}
            onChange={(event) => {
              setLeadTime(event.target.value);
            }}
          />
        </label>
        <label className="traffic-form__field">
          <span>Vehicle speed kt</span>
          <input
            type="number"
            min={0}
            placeholder="15 (default)"
            value={vehicleSpeed}
            disabled={disabled}
            onChange={(event) => {
              setVehicleSpeed(event.target.value);
            }}
          />
        </label>
      </div>
      <p className="traffic-form__sentence">
        The vehicle starts crossing the runway the stated number of seconds before you
        would reach the crossing point. A negative lead time means it is still crossing
        when you arrive — the worst case.
      </p>

      <fieldset className="traffic-seg" disabled={disabled}>
        <legend className="traffic-form__label">From side</legend>
        {(['left', 'right'] as const).map((option) => (
          <button
            key={option}
            type="button"
            className="traffic-seg__option"
            aria-pressed={fromSide === option}
            onClick={() => {
              setFromSide(option);
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
        Spawn runway incursion
      </button>
    </form>
  );
}
