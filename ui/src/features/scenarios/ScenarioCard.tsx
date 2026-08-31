/**
 * One scenario in the catalogue grid.
 *
 * Two-tap run, no modals: the first tap selects the card (accent border) and reveals the
 * inline Run button — the one solid-accent primary in the view; the second tap starts the
 * run. An unavailable scenario is dimmed and disabled but never hidden, and always says
 * why (design §3.1: the 501 sentence naming every missing capability, surfaced verbatim
 * as `reason`).
 */

import type { ScenarioSummary } from '../../api/models';

export function ScenarioCard({
  scenario,
  selected,
  runDisabled,
  onSelect,
  onRun,
}: {
  scenario: ScenarioSummary;
  selected: boolean;
  /** True while another scenario is running — the server only runs one at a time. */
  runDisabled: boolean;
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
        <p className="scenarios-card__nature">{scenario.description}</p>
        <span className="scenarios-card__chips">
          {scenario.tags.map((tag) => (
            <span key={tag} className="scenarios-card__chip">
              {tag}
            </span>
          ))}
        </span>
        {scenario.reason != null && (
          <p className="scenarios-card__reason">{scenario.reason}</p>
        )}
      </button>
      {selected && scenario.available && (
        <button
          type="button"
          className="scenarios-card__run"
          disabled={runDisabled}
          onClick={onRun}
        >
          {runDisabled ? 'A scenario is running…' : 'Run scenario'}
        </button>
      )}
    </article>
  );
}
