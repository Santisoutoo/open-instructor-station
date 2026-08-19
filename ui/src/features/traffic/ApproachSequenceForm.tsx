/**
 * Spawn an approach sequence: `n` aircraft on the same final, at named distances —
 * the Position Manager's own glideslope maths, called once per distance (design D11).
 *
 * The distances are a repeatable list defaulting to `APPROACH_SEQUENCE_DEFAULT_
 * DISTANCES_NM` (12, 8, 4 — design §6.1), each row removable, capped at the request
 * model's own `max_length=8`. As with the incursion form, the runway picker reuse
 * waits for the wiring wave; plain ICAO + ident inputs carry the same fields.
 */

import { useRef, useState } from 'react';
import { DEFAULT_DISTANCES_NM, MAX_DISTANCES } from './presets';
import type { ApproachSequenceSpawnRequest, TrafficApproachCategory } from './types.mock';

const CATEGORIES: TrafficApproachCategory[] = ['A', 'B', 'C', 'D', 'E'];

interface ApproachSequenceFormProps {
  disabled: boolean;
  onSpawn: (request: ApproachSequenceSpawnRequest) => void;
}

interface DistanceRow {
  /** Render key only — rows have no natural identity while they are being edited. */
  id: number;
  value: string;
}

export function ApproachSequenceForm({ disabled, onSpawn }: ApproachSequenceFormProps) {
  const nextRowId = useRef(DEFAULT_DISTANCES_NM.length);
  const [icao, setIcao] = useState('');
  const [runwayIdent, setRunwayIdent] = useState('');
  const [distances, setDistances] = useState<DistanceRow[]>(
    DEFAULT_DISTANCES_NM.map((distance, id) => ({ id, value: String(distance) })),
  );
  const [ias, setIas] = useState('');
  const [category, setCategory] = useState<TrafficApproachCategory>('B');
  const [callsignPrefix, setCallsignPrefix] = useState('SEQ');

  const parsedDistances = distances.map((row) => Number(row.value));
  const distancesReady =
    distances.length >= 1 &&
    distances.every(
      (row, index) =>
        row.value.trim() !== '' &&
        Number.isFinite(parsedDistances[index]) &&
        (parsedDistances[index] ?? 0) > 0,
    );
  const ready =
    icao.trim().length >= 2 &&
    runwayIdent.trim() !== '' &&
    distancesReady &&
    callsignPrefix.trim() !== '';

  return (
    <form
      className="traffic-form"
      aria-label="Approach sequence"
      onSubmit={(event) => {
        event.preventDefault();
        onSpawn({
          type: 'approach_sequence',
          airport_icao: icao.trim().toUpperCase(),
          runway_ident: runwayIdent.trim().toUpperCase(),
          distances_nm: parsedDistances,
          ias_kt: ias.trim() === '' ? null : Number(ias),
          category,
          kind: 'aircraft',
          callsign_prefix: callsignPrefix.trim(),
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
          <span>Callsign prefix</span>
          <input
            type="text"
            className="mono"
            maxLength={8}
            value={callsignPrefix}
            disabled={disabled}
            onChange={(event) => {
              setCallsignPrefix(event.target.value);
            }}
          />
        </label>
      </div>

      <fieldset className="traffic-distances" disabled={disabled}>
        <legend className="traffic-form__label">Aircraft on final, NM out</legend>
        <ul className="traffic-distances__list">
          {distances.map((row, index) => (
            <li key={row.id} className="traffic-distances__row">
              <label className="traffic-form__field">
                <span>Distance {index + 1} NM</span>
                <input
                  type="number"
                  min={0}
                  step="any"
                  value={row.value}
                  onChange={(event) => {
                    setDistances((current) =>
                      current.map((candidate) =>
                        candidate.id === row.id
                          ? { ...candidate, value: event.target.value }
                          : candidate,
                      ),
                    );
                  }}
                />
              </label>
              <button
                type="button"
                className="traffic-distances__remove"
                aria-label={`Remove distance ${String(index + 1)}`}
                disabled={distances.length <= 1}
                onClick={() => {
                  setDistances((current) =>
                    current.filter((candidate) => candidate.id !== row.id),
                  );
                }}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
        <button
          type="button"
          className="traffic-distances__add"
          disabled={distances.length >= MAX_DISTANCES}
          onClick={() => {
            nextRowId.current += 1;
            setDistances((current) => [...current, { id: nextRowId.current, value: '' }]);
          }}
        >
          Add aircraft
        </button>
      </fieldset>

      <div className="traffic-form__row">
        <label className="traffic-form__field">
          <span>IAS kt</span>
          <input
            type="number"
            min={0}
            placeholder="category default"
            value={ias}
            disabled={disabled}
            onChange={(event) => {
              setIas(event.target.value);
            }}
          />
        </label>
      </div>

      <fieldset className="traffic-seg" disabled={disabled}>
        <legend className="traffic-form__label">Approach category</legend>
        {CATEGORIES.map((option) => (
          <button
            key={option}
            type="button"
            className="traffic-seg__option"
            aria-pressed={category === option}
            onClick={() => {
              setCategory(option);
            }}
          >
            {option}
          </button>
        ))}
      </fieldset>

      <button type="submit" className="traffic-form__spawn" disabled={disabled || !ready}>
        Spawn approach sequence
      </button>
    </form>
  );
}
