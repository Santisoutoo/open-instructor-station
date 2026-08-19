/**
 * Every live traffic contact, one row per entity, with **CLEAR ALL** at the top — the
 * list and the panic button sit first in the panel, thumb-reachable on a tablet
 * (design §7.1). Clear all takes the Failures panel's posture verbatim: destructive
 * styling, no confirmation — breaking is one tap, so is the fix.
 *
 * Presentational only: contacts come in as props (the WS-fed slice, once the wiring
 * wave connects it) and despawn intents go out as callbacks. Locale pinned to `en-US`
 * as in `features/telemetry/format.ts` — identical readouts on tablet, desktop and CI.
 */

import type { TrafficContact, TrafficKind } from '../../api/models';

const INTEGER = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });

/** Compact kind marker: a mono badge, readable at a glance, never colour-only. */
const KIND_BADGES: Record<TrafficKind, string> = {
  aircraft: 'ACFT',
  ground_vehicle: 'GND',
  bird: 'BIRD',
};

interface ContactListProps {
  contacts: TrafficContact[];
  /** True while the traffic gate is closed — despawning also needs the bridge. */
  disabled: boolean;
  /** True while the `/ws/traffic` stream is delivering frames. */
  connected: boolean;
  /**
   * The adapter's advertised slot count, or `null` when unknown or unbounded. Shown
   * beside the count because the limit is enforced as a transient 409 (design D6) — the
   * instructor gets to see it coming rather than to discover it by being refused.
   */
  capacity: number | null;
  onDespawn: (trafficId: string) => void;
  onClearAll: () => void;
}

export function ContactList({
  contacts,
  disabled,
  connected,
  capacity,
  onDespawn,
  onClearAll,
}: ContactListProps) {
  return (
    <div className="traffic-contacts">
      <div className="traffic-contacts__head">
        <span className="traffic-contacts__title">
          Active traffic
          <span className="traffic-contacts__count">
            {capacity === null
              ? contacts.length
              : `${String(contacts.length)} / ${String(capacity)}`}
          </span>
        </span>
        <button
          type="button"
          className="traffic-clear-all"
          disabled={disabled || contacts.length === 0}
          onClick={onClearAll}
        >
          Clear all
        </button>
      </div>

      {!connected && contacts.length > 0 && (
        <p className="traffic-contacts__stale">
          The traffic stream is not connected — this list may be stale.
        </p>
      )}

      {contacts.length === 0 ? (
        <p className="traffic-empty">No active traffic.</p>
      ) : (
        <ul className="traffic-list">
          {contacts.map((contact) => (
            <li key={contact.traffic_id} className="traffic-row">
              <span
                className={`traffic-row__kind traffic-row__kind--${contact.kind}`}
                title={contact.kind.replace('_', ' ')}
              >
                {KIND_BADGES[contact.kind]}
              </span>
              <span className="traffic-row__callsign">{contact.callsign}</span>
              <span className="traffic-row__readout">
                {INTEGER.format(Math.round(contact.altitude_ft))} ft ·{' '}
                {INTEGER.format(Math.round(contact.ground_speed_kt))} kt
              </span>
              <button
                type="button"
                className="traffic-row__despawn"
                aria-label={`Despawn ${contact.callsign}`}
                disabled={disabled}
                onClick={() => {
                  onDespawn(contact.traffic_id);
                }}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
