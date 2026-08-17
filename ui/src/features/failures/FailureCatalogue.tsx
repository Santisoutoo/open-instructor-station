import { useAppDispatch, useAppSelector } from '../../store';
import { systemToggled } from './failuresSlice';
import { FailureRow, type RowStatus } from './FailureRow';
import { SYSTEM_LABELS, SYSTEM_ORDER } from './mock';
import type { FailureDefinition, FailuresBoard } from './types.mock';

interface FailureCatalogueProps {
  catalogue: FailureDefinition[];
  board: FailuresBoard;
}

function rowStatus(board: FailuresBoard, failureId: string): RowStatus {
  if (board.active.some((entry) => entry.failureId === failureId)) {
    return 'active';
  }
  if (board.armed.some((entry) => entry.failureId === failureId)) {
    return 'armed';
  }
  return 'idle';
}

/**
 * The catalogue accordion, grouped by system. One group open at a time; while the
 * search field has text the accordion yields to a flat filtered view across all
 * groups, headers included, so a match is never hidden behind a closed group.
 */
export function FailureCatalogue({ catalogue, board }: FailureCatalogueProps) {
  const dispatch = useAppDispatch();
  const searchText = useAppSelector((state) => state.failures.searchText);
  const openSystem = useAppSelector((state) => state.failures.openSystem);
  const draft = useAppSelector((state) => state.failures.armDraft);

  const query = searchText.trim().toLowerCase();
  const searching = query !== '';
  const matches = searching
    ? catalogue.filter(
        (definition) =>
          definition.label.toLowerCase().includes(query) ||
          definition.description.toLowerCase().includes(query) ||
          SYSTEM_LABELS[definition.system].toLowerCase().includes(query),
      )
    : catalogue;

  if (searching && matches.length === 0) {
    return <p className="failures-empty">No failures match “{searchText.trim()}”.</p>;
  }

  return (
    <div className="failures-groups">
      {SYSTEM_ORDER.map((system) => {
        const group = matches.filter((definition) => definition.system === system);
        if (group.length === 0) {
          return null;
        }
        const open = searching || openSystem === system;
        return (
          <section key={system} className="failures-group">
            {searching ? (
              <h3 className="failures-group__title">{SYSTEM_LABELS[system]}</h3>
            ) : (
              <button
                type="button"
                className="failures-group__header"
                aria-expanded={open}
                onClick={() => {
                  dispatch(systemToggled(system));
                }}
              >
                <span>{SYSTEM_LABELS[system]}</span>
                <span className="failures-group__count">{group.length}</span>
              </button>
            )}
            {open && (
              <ul className="failures-rows">
                {group.map((definition) => (
                  <FailureRow
                    key={definition.id}
                    definition={definition}
                    status={rowStatus(board, definition.id)}
                    draft={draft}
                  />
                ))}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}
