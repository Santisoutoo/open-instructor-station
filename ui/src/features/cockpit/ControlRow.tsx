import type {
  CockpitActuation,
  CockpitControlSpec,
  CockpitValue,
} from '../../api/models';
import type { LayoutSlot } from './layouts';
import { PressControl } from './widgets/PressControl';
import type { RotaryDraftHandle } from './widgets/rotary';
import { RotaryControl } from './widgets/RotaryControl';
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
  /** May report the write's outcome, which the rotary widget uses to keep or clear its draft. */
  onCommit: (body: ActuationBody) => void | Promise<boolean>;
  /** Dial/encoder only: a parent-owned draft (the schematic tray passes `CockpitPanel`'s). */
  draft?: RotaryDraftHandle;
  /** Dial/encoder only: the slot's `wrap` / `detents` / `format` hints. */
  layout?: LayoutSlot;
}

/**
 * One row of the catalog: label, the catalog's own `hint`, any unmet-precondition hints,
 * and the kind-appropriate widget. Never disabled by an unmet precondition — the row
 * stays live so an instructor mid-way through satisfying it can keep going (design §7.3).
 */
export function ControlRow({
  spec,
  value,
  hints,
  pending,
  onCommit,
  draft,
  layout,
}: ControlRowProps) {
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
      <div className="cockpit-row__widget">
        {renderWidget(spec, value, pending, onCommit, draft, layout)}
      </div>
    </div>
  );
}

function renderWidget(
  spec: CockpitControlSpec,
  value: CockpitValue | null | undefined,
  pending: boolean,
  onCommit: (body: ActuationBody) => void | Promise<boolean>,
  draft: RotaryDraftHandle | undefined,
  layout: LayoutSlot | undefined,
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
    case 'encoder':
      // `RotaryControl` already speaks in bodies (`{ value }` / `{ delta }`), so they go
      // onward as they are.
      return (
        <RotaryControl
          spec={spec}
          value={typeof value === 'number' ? value : null}
          pending={pending}
          onCommit={onCommit}
          {...(draft !== undefined ? { draft } : {})}
          {...(layout !== undefined ? { layout } : {})}
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
