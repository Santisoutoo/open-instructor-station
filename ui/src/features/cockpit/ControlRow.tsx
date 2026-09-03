import type { CockpitActuation, CockpitControlSpec, CockpitValue } from '../../api/models';
import { DialControl } from './widgets/DialControl';
import { EncoderControl } from './widgets/EncoderControl';
import { PressControl } from './widgets/PressControl';
import { SelectorControl } from './widgets/SelectorControl';
import { ToggleControl } from './widgets/ToggleControl';

/** What one commit from any widget sends onward — the actuation body, minus the id. */
export type ActuationBody = Omit<CockpitActuation, 'control_id'>;

export interface ControlRowProps {
  spec: CockpitControlSpec;
  /** The confirmed value from the state snapshot, or `null`/`undefined` when unread. */
  value: CockpitValue | null | undefined;
  /** Client-computed, informational only — the server's 409 is the actual gate (§7.3). */
  hints: readonly string[];
  pending: boolean;
  onCommit: (body: ActuationBody) => void;
}

/**
 * One row of the catalog: label, the catalog's own `hint`, any unmet-precondition hints,
 * and the kind-appropriate widget. Never disabled by an unmet precondition — the row
 * stays live so an instructor mid-way through satisfying it can keep going (design §7.3).
 */
export function ControlRow({ spec, value, hints, pending, onCommit }: ControlRowProps) {
  return (
    <div className={`cockpit-row${hints.length > 0 ? ' cockpit-row--unmet' : ''}`}>
      <div className="cockpit-row__main">
        <span className="cockpit-row__label">{spec.label}</span>
        {spec.hint != null && <p className="cockpit-row__hint">{spec.hint}</p>}
        {hints.map((hint) => (
          <p key={hint} className="cockpit-row__unmet" role="note">
            {hint}
          </p>
        ))}
      </div>
      <div className="cockpit-row__widget">{renderWidget(spec, value, pending, onCommit)}</div>
    </div>
  );
}

function renderWidget(
  spec: CockpitControlSpec,
  value: CockpitValue | null | undefined,
  pending: boolean,
  onCommit: (body: ActuationBody) => void,
) {
  switch (spec.kind) {
    case 'toggle':
      return (
        <ToggleControl
          spec={spec}
          value={typeof value === 'boolean' ? value : null}
          pending={pending}
          onCommit={(next) => {
            onCommit({ value: next });
          }}
        />
      );
    case 'press':
      return (
        <PressControl
          pending={pending}
          onPress={() => {
            onCommit({});
          }}
        />
      );
    case 'dial':
      return (
        <DialControl
          spec={spec}
          value={typeof value === 'number' ? value : null}
          pending={pending}
          onCommit={(next) => {
            onCommit({ value: next });
          }}
        />
      );
    case 'encoder':
      return (
        <EncoderControl
          spec={spec}
          value={typeof value === 'number' ? value : null}
          pending={pending}
          onCommit={(delta) => {
            onCommit({ delta });
          }}
        />
      );
    case 'selector':
      return (
        <SelectorControl
          spec={spec}
          value={value ?? null}
          pending={pending}
          onCommit={(next) => {
            onCommit({ value: next });
          }}
        />
      );
    default: {
      // The closed union of `CockpitControlKind` (design §3.1) — a sixth kind fails to
      // compile here rather than silently rendering nothing.
      const exhaustive: never = spec.kind;
      throw new Error(`Unhandled cockpit control kind: ${String(exhaustive)}`);
    }
  }
}
