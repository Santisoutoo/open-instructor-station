import { useMemo, useState } from 'react';
import { useAppDispatch } from '../store';
import { tabSelected } from '../store/uiSlice';
import { TABS } from './tabs';
import './GateDelayedPanel.css';

/**
 * Stand-in body for a module that is built but deliberately not shown yet — an
 * airport-departures-board "DELAYED" screen, distinct from `ComingSoonPanel` (which is
 * for panels that genuinely have no code behind them). Every tab with `gated: true` in
 * `tabs.ts` renders this instead of its real panel; removing the flag is the whole
 * revert.
 */
export function GateDelayedPanel({ label }: { label: string }) {
  const dispatch = useAppDispatch();
  const [manifestOpen, setManifestOpen] = useState(false);

  const gate = useMemo(() => gateCode(label), [label]);
  const flight = useMemo(() => flightCode(label), [label]);
  const clock = useMemo(() => formatClock(new Date()), []);
  const title = `${label.toUpperCase()} DELAYED`;

  const otherGated = TABS.filter((tab) => tab.gated && tab.label !== label);

  return (
    <section className="gate-panel" aria-label={label}>
      <div className="gate-panel__tag">
        <span className="gate-panel__tag-gate">
          Gate <strong>{gate}</strong>
        </span>
        <span className="gate-panel__tag-status">Delayed</span>
      </div>

      <div className="gate-panel__board">
        <header className="gate-panel__head">
          <span className="gate-panel__clock">{clock} LT</span>
          <span className="gate-panel__terminal">
            <span className="gate-panel__warn" aria-hidden>
              !
            </span>
            Terminal T1
          </span>
          <span className="gate-panel__section">Departures</span>
        </header>

        <p className="gate-panel__caption">Gate information · {gate}</p>

        <h2 className="gate-panel__flaps" aria-label={title}>
          {[...title].map((char, index) =>
            char === ' ' ? (
              <span key={index} className="gate-panel__flap-gap" aria-hidden />
            ) : (
              <span key={index} className="gate-panel__flap" aria-hidden>
                {char}
              </span>
            ),
          )}
        </h2>

        <dl className="gate-panel__rows">
          <div className="gate-panel__row">
            <dt>Status</dt>
            <dd className="gate-panel__value gate-panel__value--danger">Delayed</dd>
          </div>
          <div className="gate-panel__row">
            <dt>Flight</dt>
            <dd className="gate-panel__value">{flight}</dd>
          </div>
          <div className="gate-panel__row">
            <dt>Gate</dt>
            <dd className="gate-panel__value">{gate}</dd>
          </div>
          <div className="gate-panel__row">
            <dt>Info</dt>
            <dd className="gate-panel__value">
              Module not yet released in this build · check back later
            </dd>
          </div>
        </dl>

        <div className="gate-panel__actions">
          <button
            type="button"
            className="gate-panel__button gate-panel__button--primary"
            onClick={() => dispatch(tabSelected('position'))}
          >
            ← Back to home
          </button>
          <button
            type="button"
            className="gate-panel__button gate-panel__button--secondary"
            aria-expanded={manifestOpen}
            onClick={() => setManifestOpen((open) => !open)}
          >
            View departures
          </button>
        </div>

        {manifestOpen && (
          <ul className="gate-panel__manifest">
            {otherGated.map((tab) => (
              <li key={tab.id}>
                <span>{tab.label}</span>
                <span className="gate-panel__value--danger">Delayed</span>
              </li>
            ))}
          </ul>
        )}

        <footer className="gate-panel__pa">
          PA · Attention · Flight {flight} is delayed
        </footer>
      </div>
    </section>
  );
}

/** Two letters from the label, ignoring separators — "Fuel & payload" → "FP". */
function gateCode(label: string): string {
  const initials = label
    .split(/[^a-zA-Z]+/)
    .filter(Boolean)
    .map((word) => word[0])
    .join('')
    .toUpperCase();
  return (initials.length >= 2 ? initials : label.slice(0, 2).toUpperCase()).slice(0, 3);
}

/** Deterministic 4-digit flavour number so a given tab always shows the same "flight". */
function flightCode(label: string): string {
  let hash = 0;
  for (let i = 0; i < label.length; i += 1) {
    hash = (hash * 31 + label.charCodeAt(i)) >>> 0;
  }
  return `OIS ${(hash % 9000) + 1000}`;
}

function formatClock(date: Date): string {
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${hours}:${minutes}`;
}
