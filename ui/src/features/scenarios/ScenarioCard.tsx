/**
 * One scenario in the catalogue grid.
 *
 * Two-tap run, no modals: the first tap selects the card (amber border) and reveals the
 * inline Run button — the one solid-accent primary in the view; the second tap starts
 * the run. An unavailable scenario is dimmed and disabled but never hidden, and always
 * says why (feature-spec §2: unavailable with the reason, never offered then failed).
 */

import type { Scenario } from './mock';

export function ScenarioCard({
  scenario,
  selected,
  onSelect,
  onRun,
}: {
  scenario: Scenario;
  selected: boolean;
  onSelect: () => void;
  onRun: () => void;
}) {
  const modifiers = [
    scenario.available ? ' scenarios-card--available' : ' scenarios-card--unavailable',
    selected ? ' scenarios-card--selected' : '',
  ].join('');

  return (
    <article className={`scenarios-card${modifiers}`}>
      <button
        type="button"
        className="scenarios-card__body"
        disabled={!scenario.available}
        aria-pressed={selected}
        onClick={onSelect}
      >
        <h3 className="scenarios-card__name">{scenario.name}</h3>
        <p className="scenarios-card__nature">{scenario.nature}</p>
        <span className="scenarios-card__chips">
          {scenario.blocks.map((block) => (
            <span key={block} className="scenarios-card__chip">
              {block}
            </span>
          ))}
        </span>
        {scenario.unavailableReason !== null && (
          <p className="scenarios-card__reason">{scenario.unavailableReason}</p>
        )}
      </button>
      {selected && scenario.available && (
        <button type="button" className="scenarios-card__run" onClick={onRun}>
          Run scenario
        </button>
      )}
    </article>
  );
}
