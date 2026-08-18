/**
 * Spawn taxi traffic: an entity ground-taxiing an explicit ordered route (design §7.1).
 *
 * The design's target affordance is the Instructor Map's click-to-add-point; until that
 * component exists on this branch, a plain lat/lon list editor exercises the same
 * request — the route is an ordered point list either way (design D12: no routing is
 * invented, the caller supplies the path). Points are ground points: `altitude_ft` is
 * sent as 0 and the server puts the entity on the surface.
 */

import { useRef, useState } from 'react';
import { MAX_ROUTE_POINTS, MIN_ROUTE_POINTS } from './presets';
import type { TaxiTrafficSpawnRequest, TrafficKind } from './types.mock';

const KINDS: TrafficKind[] = ['aircraft', 'ground_vehicle'];

interface RoutePointRow {
  /** Render key only — rows have no natural identity while they are being edited. */
  id: number;
  lat: string;
  lon: string;
}

interface TaxiTrafficFormProps {
  disabled: boolean;
  onSpawn: (request: TaxiTrafficSpawnRequest) => void;
}

function validPoint(row: RoutePointRow): boolean {
  const lat = Number(row.lat);
  const lon = Number(row.lon);
  return (
    row.lat.trim() !== '' &&
    row.lon.trim() !== '' &&
    Number.isFinite(lat) &&
    Number.isFinite(lon) &&
    lat >= -90 &&
    lat <= 90 &&
    lon >= -180 &&
    lon <= 180
  );
}

export function TaxiTrafficForm({ disabled, onSpawn }: TaxiTrafficFormProps) {
  const nextRowId = useRef(1);
  const [route, setRoute] = useState<RoutePointRow[]>([
    { id: 0, lat: '', lon: '' },
    { id: 1, lat: '', lon: '' },
  ]);
  const [speed, setSpeed] = useState('');
  const [kind, setKind] = useState<TrafficKind>('aircraft');
  const [callsign, setCallsign] = useState('TAXI01');

  const ready =
    route.length >= MIN_ROUTE_POINTS && route.every(validPoint) && callsign.trim() !== '';

  const setPoint = (id: number, field: 'lat' | 'lon', value: string) => {
    setRoute((current) =>
      current.map((row) => (row.id === id ? { ...row, [field]: value } : row)),
    );
  };

  return (
    <form
      className="traffic-form"
      aria-label="Taxi traffic"
      onSubmit={(event) => {
        event.preventDefault();
        onSpawn({
          type: 'taxi_traffic',
          route: route.map((row) => ({
            latitude: Number(row.lat),
            longitude: Number(row.lon),
            altitude_ft: 0,
          })),
          speed_kt: speed.trim() === '' ? null : Number(speed),
          kind,
          callsign: callsign.trim(),
        });
      }}
    >
      <fieldset className="traffic-route" disabled={disabled}>
        <legend className="traffic-form__label">Route points, in order</legend>
        <ul className="traffic-route__list">
          {route.map((row, index) => (
            <li key={row.id} className="traffic-route__row">
              <label className="traffic-form__field">
                <span>Point {index + 1} latitude</span>
                <input
                  type="number"
                  step="any"
                  min={-90}
                  max={90}
                  value={row.lat}
                  onChange={(event) => {
                    setPoint(row.id, 'lat', event.target.value);
                  }}
                />
              </label>
              <label className="traffic-form__field">
                <span>Point {index + 1} longitude</span>
                <input
                  type="number"
                  step="any"
                  min={-180}
                  max={180}
                  value={row.lon}
                  onChange={(event) => {
                    setPoint(row.id, 'lon', event.target.value);
                  }}
                />
              </label>
              <button
                type="button"
                className="traffic-route__remove"
                aria-label={`Remove point ${String(index + 1)}`}
                disabled={route.length <= MIN_ROUTE_POINTS}
                onClick={() => {
                  setRoute((current) => current.filter((point) => point.id !== row.id));
                }}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
        <button
          type="button"
          className="traffic-route__add"
          disabled={route.length >= MAX_ROUTE_POINTS}
          onClick={() => {
            nextRowId.current += 1;
            setRoute((current) => [...current, { id: nextRowId.current, lat: '', lon: '' }]);
          }}
        >
          Add point
        </button>
      </fieldset>

      <div className="traffic-form__row">
        <label className="traffic-form__field">
          <span>Taxi speed kt</span>
          <input
            type="number"
            min={0}
            placeholder="12 (default)"
            value={speed}
            disabled={disabled}
            onChange={(event) => {
              setSpeed(event.target.value);
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
        Spawn taxi traffic
      </button>
    </form>
  );
}
