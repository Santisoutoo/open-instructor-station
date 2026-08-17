import { useAppDispatch, useAppSelector } from '../../store';
import { CATEGORY_LABELS, CATEGORY_ORDER } from './categories';
import { categoryToggled } from './failuresSlice';
import { FailureRow, type RowStatus } from './FailureRow';
import type { FailureCatalogueEntry, FailuresStatus } from '../../api/models';

interface FailureCatalogueProps {
  catalogue: FailureCatalogueEntry[];
  status: FailuresStatus;
}

/**
 * A row's status ignores engine index: an indexed failure active on one engine still
 * reads as "active" for the whole row, and the engine it hit is stated on the
 * `ActiveStrip` chip instead — the catalogue's job is "is this kind of failure doing
 * something right now", not per-engine bookkeeping.
 */
function rowStatus(status: FailuresStatus, failureId: string): RowStatus {
  if (status.active.some((entry) => entry.failure_id === failureId)) {
    return 'active';
  }
  if (status.armed.some((entry) => entry.failure_id === failureId)) {
    return 'armed';
  }
  return 'idle';
}

/**
 * The catalogue accordion, grouped by category. One group open at a time; while the
 * search field has text the accordion yields to a flat filtered view across all
 * groups, headers included, so a match is never hidden behind a closed group.
 */
export function FailureCatalogue({ catalogue, status }: FailureCatalogueProps) {
  const dispatch = useAppDispatch();
  const searchText = useAppSelector((state) => state.failures.searchText);
  const openCategory = useAppSelector((state) => state.failures.openCategory);
  const draft = useAppSelector((state) => state.failures.armDraft);

  const query = searchText.trim().toLowerCase();
  const searching = query !== '';
  const matches = searching
    ? catalogue.filter(
        (entry) =>
          entry.label.toLowerCase().includes(query) ||
          entry.description.toLowerCase().includes(query) ||
          CATEGORY_LABELS[entry.category].toLowerCase().includes(query),
      )
    : catalogue;

  if (searching && matches.length === 0) {
    return <p className="failures-empty">No failures match “{searchText.trim()}”.</p>;
  }

  return (
    <div className="failures-groups">
      {CATEGORY_ORDER.map((category) => {
        const group = matches.filter((entry) => entry.category === category);
        if (group.length === 0) {
          return null;
        }
        const open = searching || openCategory === category;
        return (
          <section key={category} className="failures-group">
            {searching ? (
              <h3 className="failures-group__title">{CATEGORY_LABELS[category]}</h3>
            ) : (
              <button
                type="button"
                className="failures-group__header"
                aria-expanded={open}
                onClick={() => {
                  dispatch(categoryToggled(category));
                }}
              >
                <span>{CATEGORY_LABELS[category]}</span>
                <span className="failures-group__count">{group.length}</span>
              </button>
            )}
            {open && (
              <ul className="failures-rows">
                {group.map((entry) => (
                  <FailureRow
                    key={entry.failure_id}
                    entry={entry}
                    status={rowStatus(status, entry.failure_id)}
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
