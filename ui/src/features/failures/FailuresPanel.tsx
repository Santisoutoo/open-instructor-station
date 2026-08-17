/**
 * The Failures Manager panel: the active/armed strip on top, the searchable
 * catalogue accordion below, and the armed-trigger evaluator ticking against the
 * telemetry feed while anything is armed.
 *
 * Search text, open group and the arm draft are client state (the slice); the
 * catalogue and the board are server state (RTK Query). Failing, arming and clearing
 * go through mutations that persist into the board cache, exactly as they will once
 * the server owns the board.
 */

import { useAppDispatch, useAppSelector } from '../../store';
import { ActiveStrip } from './ActiveStrip';
import { FailureCatalogue } from './FailureCatalogue';
import {
  useGetFailureBoardQuery,
  useGetFailureCatalogueQuery,
  useGetFailuresManifestQuery,
} from './failuresApi';
import { searchChanged } from './failuresSlice';
import { failuresGate } from './gate';
import { useArmedTriggers } from './useArmedTriggers';
import './failures.css';

const EMPTY_BOARD = { active: [], armed: [] };

export function FailuresPanel() {
  const dispatch = useAppDispatch();
  const searchText = useAppSelector((state) => state.failures.searchText);

  const manifestQuery = useGetFailuresManifestQuery();
  const gate = failuresGate(manifestQuery.data, manifestQuery.isError);

  const catalogueQuery = useGetFailureCatalogueQuery();
  const { data: board } = useGetFailureBoardQuery();

  useArmedTriggers(gate.open && (board?.armed.length ?? 0) > 0);

  return (
    <section className="panel failures-panel" aria-labelledby="failures-heading">
      <h2 id="failures-heading">Failures</h2>

      {!gate.open && <p className="panel__empty">{gate.reason}</p>}

      {gate.open && (
        <>
          <ActiveStrip
            board={board ?? EMPTY_BOARD}
            catalogue={catalogueQuery.data ?? []}
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
              catalogue={catalogueQuery.data}
              board={board ?? EMPTY_BOARD}
            />
          )}
        </>
      )}
    </section>
  );
}
