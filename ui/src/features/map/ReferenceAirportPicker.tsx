/**
 * The reference airport and its procedures (instructor-map.md D4, §7.6): procedures are
 * picker-driven, never viewport-driven — an airport can publish 100+ of them, and
 * drawing all of them unasked is noise, not situational awareness.
 *
 * The search reuses the existing `searchAirports` endpoint; the procedure list reuses
 * `getProcedures`. Toggling a procedure ON only records it in the map slice — the legs
 * are fetched (and drawn) by `useMapOverlays`, so this component stays chrome.
 */

import { type Map as MapLibreMap } from 'maplibre-gl';
import { useEffect, useId, useState } from 'react';
import { useGetProceduresQuery, useSearchAirportsQuery } from '../../api/instructorApi';
import type { AirportSummary, ProcedureKind } from '../../api/models';
import { useAppDispatch, useAppSelector } from '../../store';
import {
  isProcedureOpen,
  procedureLayerToggled,
  referenceAirportSelected,
} from './mapSlice';

/** A keystroke is not a request — same debounce the Position search uses. */
const DEBOUNCE_MS = 250;

/** Below this, a query matches too much to be worth asking about. */
const MIN_QUERY_LENGTH = 2;

/** Close enough to see the whole terminal area of the chosen airport. */
const REFERENCE_AIRPORT_ZOOM = 11;

const KINDS: readonly { kind: ProcedureKind; label: string }[] = [
  { kind: 'sid', label: 'SID' },
  { kind: 'star', label: 'STAR' },
  { kind: 'approach', label: 'Approach' },
];

function ProcedureToggles({ icao }: { icao: string }) {
  const dispatch = useAppDispatch();
  const open = useAppSelector((state) => state.map.openProcedures);
  const { data: procedures, isError } = useGetProceduresQuery({ icao });

  if (isError) {
    return <p className="panel__error">The procedures of {icao} could not be read.</p>;
  }
  if (procedures === undefined) {
    return <p className="panel__empty">Reading procedures…</p>;
  }
  if (procedures.length === 0) {
    return (
      <p className="panel__empty">
        {icao} has no published procedures in this navigation data.
      </p>
    );
  }

  return (
    <div className="map-ref__procedures">
      {KINDS.map(({ kind, label }) => {
        const ofKind = procedures.filter((procedure) => procedure.kind === kind);
        if (ofKind.length === 0) {
          return null;
        }
        return (
          <section key={kind} className="map-ref__group">
            <h4 className="map-ref__group-title">{label}</h4>
            <ul className="map-ref__list" aria-label={`${label} procedures`}>
              {ofKind.map((procedure) => {
                const entry = {
                  kind,
                  ident: procedure.ident,
                  transition: procedure.transition ?? null,
                };
                const isOn = isProcedureOpen(open, entry);
                return (
                  <li key={`${procedure.ident}-${procedure.transition ?? ''}`}>
                    <button
                      type="button"
                      className="map-ref__procedure"
                      aria-pressed={isOn}
                      onClick={() => {
                        dispatch(procedureLayerToggled(entry));
                      }}
                    >
                      <span className="map-ref__dot" aria-hidden="true" />
                      <span className="mono">{procedure.ident}</span>
                      {procedure.transition != null && (
                        <span className="map-ref__transition mono">
                          {procedure.transition}
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

export function ReferenceAirportPicker({ map }: { map: MapLibreMap | null }) {
  const dispatch = useAppDispatch();
  const referenceIcao = useAppSelector((state) => state.map.referenceIcao);

  const [text, setText] = useState('');
  const [debounced, setDebounced] = useState('');
  const inputId = useId();

  useEffect(() => {
    const handle = window.setTimeout(() => {
      setDebounced(text.trim());
    }, DEBOUNCE_MS);
    return () => {
      window.clearTimeout(handle);
    };
  }, [text]);

  const shouldSearch = debounced.length >= MIN_QUERY_LENGTH;
  const {
    data: results,
    isFetching,
    isError,
  } = useSearchAirportsQuery({ query: debounced }, { skip: !shouldSearch });

  function choose(airport: AirportSummary) {
    dispatch(referenceAirportSelected(airport.icao));
    setText('');
    setDebounced('');
    map?.easeTo({
      center: [airport.position.longitude, airport.position.latitude],
      zoom: REFERENCE_AIRPORT_ZOOM,
    });
  }

  return (
    <div className="map-ref">
      <label className="map-ref__label" htmlFor={inputId}>
        Reference airport
      </label>
      {referenceIcao !== null && (
        <div className="map-ref__selected">
          <span className="mono">{referenceIcao}</span>
          <button
            type="button"
            className="ghost-button"
            aria-label="Clear reference airport"
            onClick={() => {
              dispatch(referenceAirportSelected(null));
            }}
          >
            Clear
          </button>
        </div>
      )}
      <input
        id={inputId}
        className="map-ref__input"
        type="search"
        autoComplete="off"
        placeholder="ICAO, IATA or name"
        value={text}
        onChange={(event) => {
          setText(event.target.value);
        }}
      />

      {shouldSearch && isError && (
        <p className="panel__error">
          The airport index could not be searched. Check the connection to the station.
        </p>
      )}

      {shouldSearch && !isError && (
        <ul className="map-ref__results" aria-label="Reference airport search results">
          {results?.length === 0 && !isFetching && (
            <li className="panel__empty">No airport matches “{debounced}”.</li>
          )}
          {results?.map((airport) => (
            <li key={airport.icao}>
              <button
                type="button"
                className="map-ref__result"
                onClick={() => {
                  choose(airport);
                }}
              >
                <span className="mono">{airport.icao}</span>
                <span className="map-ref__result-name">{airport.name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {referenceIcao !== null && <ProcedureToggles icao={referenceIcao} />}
    </div>
  );
}
