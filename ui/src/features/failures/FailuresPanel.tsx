/**
 * The Failures Manager panel: the active/armed strip on top, the searchable
 * catalogue accordion below.
 *
 * Search text, open category and the arm draft are client state (the slice); the
 * catalogue and the board are server state (RTK Query). `getFailuresStatus` is polled
 * every `STATUS_POLL_MS` while the tab is open and the gate lets it through — the
 * server's watcher task (`server/failure_routes.py`) is what actually evaluates armed
 * triggers and injects what fires, so the panel only ever needs to ask "what changed?".
 */

import { useGetCapabilitiesQuery } from '../../api/instructorApi';
import { useAppDispatch, useAppSelector } from '../../store';
import { ActiveStrip } from './ActiveStrip';
import { FailureCatalogue } from './FailureCatalogue';
import { useGetFailuresCatalogueQuery, useGetFailuresStatusQuery } from './failuresApi';
import { searchChanged } from './failuresSlice';
import { failuresGate } from './gate';
import './failures.css';

const EMPTY_STATUS = { active: [], armed: [] };

/** How often `/status` is re-read while the tab is mounted and the gate is open. */
const STATUS_POLL_MS = 2000;

export function FailuresPanel() {
  const dispatch = useAppDispatch();
  const searchText = useAppSelector((state) => state.failures.searchText);

  const capabilitiesQuery = useGetCapabilitiesQuery();
  const gate = failuresGate(capabilitiesQuery.data, capabilitiesQuery.isError);

  const catalogueQuery = useGetFailuresCatalogueQuery();
  const { data: status } = useGetFailuresStatusQuery(undefined, {
    skip: !gate.open,
    pollingInterval: STATUS_POLL_MS,
    skipPollingIfUnfocused: true,
  });

  return (
    <section className="panel failures-panel" aria-labelledby="failures-heading">
      <h2 id="failures-heading">Failures</h2>

      {!gate.open && <p className="panel__empty">{gate.reason}</p>}

      {gate.open && (
        <>
          {catalogueQuery.data?.caveat != null && (
            <p className="failures-caveat">{catalogueQuery.data.caveat}</p>
          )}

          <ActiveStrip
            status={status ?? EMPTY_STATUS}
            catalogue={catalogueQuery.data?.failures ?? []}
          />

          <input
            type="search"
            className="failures-search"
            aria-label="Search failures"
            placeholder="Search failures"
            value={searchText}
            onChange={(event) => {
              dispatch(searchChanged(event.target.value));
            }}
          />

          {catalogueQuery.isLoading && (
            <p className="panel__empty">Loading the failure catalogue…</p>
          )}
          {catalogueQuery.isError && (
            <p className="panel__error">The failure catalogue could not be loaded.</p>
          )}
          {catalogueQuery.data !== undefined && (
            <FailureCatalogue
              catalogue={catalogueQuery.data.failures}
              status={status ?? EMPTY_STATUS}
            />
          )}
        </>
      )}
    </section>
  );
}
