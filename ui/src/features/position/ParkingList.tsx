/**
 * Gates, stands, tie-downs and hangars.
 *
 * One list rather than a "gates" tab and a "stands" tab, because `apt.dat` publishes one
 * record type with a `kind` field — splitting them in the UI would invent a distinction
 * the data does not make. The filter is the kind, and the search is the name, because a
 * large airport has several hundred of these.
 */

import { useState } from 'react';
import { useGetParkingQuery } from '../../api/instructorApi';
import type { ParkingKind } from '../../api/models';
import { useAppDispatch, useAppSelector } from '../../store';
import { placementStaged } from './positionSlice';

const KINDS: readonly { value: ParkingKind | 'all'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'gate', label: 'Gates' },
  { value: 'tie_down', label: 'Tie-downs' },
  { value: 'hangar', label: 'Hangars' },
  { value: 'misc', label: 'Other' },
];

export function ParkingList({ icao }: { icao: string }) {
  const dispatch = useAppDispatch();
  const staged = useAppSelector((state) => state.position.staged);
  const [kind, setKind] = useState<ParkingKind | 'all'>('all');
  const [filter, setFilter] = useState('');

  const { data: stands, isError } = useGetParkingQuery({
    icao,
    ...(kind === 'all' ? {} : { kind }),
  });

  if (isError) {
    return <p className="panel__error">The parking of {icao} could not be read.</p>;
  }
  if (stands === undefined) {
    return <p className="panel__empty">Reading parking…</p>;
  }

  const needle = filter.trim().toLowerCase();
  const shown =
    needle === ''
      ? stands
      : stands.filter((stand) => stand.name.toLowerCase().includes(needle));

  const stagedName =
    staged !== null && staged.type === 'parking' ? staged.stand_name : null;

  return (
    <div className="parking">
      <div className="parking__toolbar">
        {KINDS.map((option) => (
          <button
            key={option.value}
            type="button"
            className={`chip${kind === option.value ? ' chip--active' : ''}`}
            aria-pressed={kind === option.value}
            onClick={() => {
              setKind(option.value);
            }}
          >
            {option.label}
          </button>
        ))}
        <input
          type="search"
          className="parking__filter"
          placeholder="Filter by name"
          value={filter}
          onChange={(event) => {
            setFilter(event.target.value);
          }}
        />
      </div>

      {shown.length === 0 ? (
        <p className="panel__empty">
          {stands.length === 0
            ? `${icao} publishes no parking positions.`
            : 'No stand matches that filter.'}
        </p>
      ) : (
        <ul className="parking__list">
          {shown.map((stand) => (
            <li key={stand.name}>
              <button
                type="button"
                className={`stand${stagedName === stand.name ? ' stand--staged' : ''}`}
                aria-pressed={stagedName === stand.name}
                onClick={() => {
                  dispatch(
                    placementStaged({
                      type: 'parking',
                      airport_icao: icao,
                      stand_name: stand.name,
                    }),
                  );
                }}
              >
                <span className="mono">{stand.name}</span>
                <span className="stand__meta">{stand.kind.replace('_', ' ')}</span>
                <span className="stand__meta mono">
                  {Math.round(stand.heading_true_deg)}°
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
