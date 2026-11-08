/**
 * The transient edit state of one rotary control (issue #253, design §2).
 *
 * Plain `useState`, not the store: the draft is text tied to one widget's lifetime and
 * never survives a reload (see `cockpitSlice.ts`). `CockpitPanel` owns one handle for the
 * focused schematic slot and passes it down to the tray's `RotaryControl`; a
 * `RotaryControl` rendered without one owns its own. Every mutation carries its `spec`,
 * so a wheel notch on an unfocused knob starts that knob's draft and lands on it in the
 * same event — the maths all live in `rotary.ts`.
 */

import { useCallback, useMemo, useState } from 'react';
import type { CockpitControlSpec } from '../../../api/models';
import type { LayoutSlot } from '../layouts';
import {
  EMPTY_ROTARY_DRAFT,
  dialDraftValue,
  nudgeDial,
  nudgeEncoder,
  type RotaryDraft,
  type RotaryDraftHandle,
} from './rotary';

function rotaryKind(spec: CockpitControlSpec): RotaryDraft['kind'] {
  return spec.kind === 'dial' || spec.kind === 'encoder' ? spec.kind : null;
}

/** `current` if it already belongs to `spec`, else a fresh draft for `spec`. */
function forControl(current: RotaryDraft, spec: CockpitControlSpec): RotaryDraft {
  if (current.controlId === spec.control_id) {
    return current;
  }
  return { ...EMPTY_ROTARY_DRAFT, controlId: spec.control_id, kind: rotaryKind(spec) };
}

export function useRotaryDraft(): RotaryDraftHandle {
  const [draft, setDraft] = useState<RotaryDraft>(EMPTY_ROTARY_DRAFT);

  // The mutations use functional updates and never close over `draft`, so they are
  // stable for the widget's lifetime and safe to hand to timers and native listeners.
  const setText = useCallback((spec: CockpitControlSpec, text: string) => {
    setDraft((current) => ({ ...forControl(current, spec), text }));
  }, []);

  const nudge = useCallback(
    (
      spec: CockpitControlSpec,
      slot: LayoutSlot | undefined,
      confirmed: number | null,
      sign: 1 | -1,
      count = 1,
    ) => {
      setDraft((current) => {
        const own = forControl(current, spec);
        if (own.kind === 'encoder') {
          return {
            ...own,
            clicks: nudgeEncoder(own.clicks, sign, count, spec.max_delta ?? 1),
          };
        }
        const base =
          dialDraftValue(spec, slot, own.text) ?? confirmed ?? spec.min_value ?? 0;
        return { ...own, text: String(nudgeDial(spec, slot, base, sign, count)) };
      });
    },
    [],
  );

  const reset = useCallback((controlId?: string) => {
    setDraft((current) =>
      controlId === undefined || current.controlId === controlId
        ? EMPTY_ROTARY_DRAFT
        : current,
    );
  }, []);

  const isFor = useCallback(
    (controlId: string) => draft.controlId === controlId,
    [draft.controlId],
  );

  const body = useCallback(
    (spec: CockpitControlSpec, slot: LayoutSlot | undefined) => {
      if (draft.controlId !== spec.control_id) {
        return null;
      }
      if (draft.kind === 'encoder') {
        return draft.clicks !== 0 ? { delta: draft.clicks } : null;
      }
      const value = dialDraftValue(spec, slot, draft.text);
      return value === null ? null : { value };
    },
    [draft],
  );

  return useMemo(
    () => ({ draft, isFor, setText, nudge, reset, body }),
    [draft, isFor, setText, nudge, reset, body],
  );
}
