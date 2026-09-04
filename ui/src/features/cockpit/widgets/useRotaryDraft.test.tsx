import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { CockpitControlSpec } from '../../../api/models';
import { cockpitCatalogManifestFixture } from '../fixtures';
import type { LayoutSlot } from '../layouts';
import { EMPTY_ROTARY_DRAFT } from './rotary';
import { useRotaryDraft } from './useRotaryDraft';

function specFor(controlId: string): CockpitControlSpec {
  const spec = cockpitCatalogManifestFixture().controls.find(
    (control) => control.control_id === controlId,
  );
  if (spec === undefined) {
    throw new Error(`fixture is missing ${controlId}`);
  }
  return spec;
}

const altitude = specFor('mcp_alt'); // dial 0..50000, step 100
const heading = specFor('mcp_hdg'); // dial 0..360, step 1
const trim = specFor('stab_trim'); // encoder step 0.5, max_delta 20

const flapSlot: LayoutSlot = {
  control_id: 'mcp_alt',
  x: 0,
  y: 0,
  w: 1,
  h: 1,
  shape: 'lever',
  detents: [
    { value: 0, label: 'UP' },
    { value: 1000, label: '1' },
    { value: 5000, label: '5' },
  ],
};

describe('useRotaryDraft', () => {
  it('starts empty, with nothing to commit', () => {
    const { result } = renderHook(() => useRotaryDraft());

    expect(result.current.draft).toEqual(EMPTY_ROTARY_DRAFT);
    expect(result.current.isFor('mcp_alt')).toBe(false);
    expect(result.current.body(altitude, undefined)).toBeNull();
  });

  it('starts a fresh draft for a different control on every mutation', () => {
    const { result } = renderHook(() => useRotaryDraft());

    act(() => {
      result.current.setText(altitude, '4000');
    });
    expect(result.current.draft).toEqual({
      controlId: 'mcp_alt',
      kind: 'dial',
      text: '4000',
      clicks: 0,
    });
    expect(result.current.isFor('mcp_alt')).toBe(true);

    // A wheel notch on another knob lands on that knob, in the same event, from clean.
    act(() => {
      result.current.nudge(heading, undefined, 90, 1);
    });
    expect(result.current.draft).toEqual({
      controlId: 'mcp_hdg',
      kind: 'dial',
      text: '91',
      clicks: 0,
    });
    expect(result.current.isFor('mcp_alt')).toBe(false);

    act(() => {
      result.current.nudge(trim, undefined, 4, -1, 3);
    });
    expect(result.current.draft).toEqual({
      controlId: 'stab_trim',
      kind: 'encoder',
      text: '',
      clicks: -3,
    });
  });

  it('nudges a dial from the valid draft, else the confirmed value, else min', () => {
    const { result } = renderHook(() => useRotaryDraft());

    // No draft, nothing confirmed → from `min_value`.
    act(() => {
      result.current.nudge(altitude, undefined, null, 1);
    });
    expect(result.current.draft.text).toBe('100');

    // A valid draft is the base, even when a confirmed value exists.
    act(() => {
      result.current.nudge(altitude, undefined, 5000, 1, 2);
    });
    expect(result.current.draft.text).toBe('300');

    // An unparsable draft falls back to the confirmed value.
    act(() => {
      result.current.setText(altitude, 'abc');
      result.current.nudge(altitude, undefined, 5000, -1);
    });
    expect(result.current.draft.text).toBe('4900');

    // With detents the draft snaps to the next stop rather than stepping.
    act(() => {
      result.current.reset();
      result.current.nudge(altitude, flapSlot, 0, 1);
    });
    expect(result.current.draft.text).toBe('1000');
    act(() => {
      result.current.nudge(altitude, flapSlot, 0, 1);
    });
    expect(result.current.draft.text).toBe('5000');
  });

  it('accumulates encoder clicks and saturates at max_delta', () => {
    const { result } = renderHook(() => useRotaryDraft());

    act(() => {
      result.current.nudge(trim, undefined, 4, 1, 5);
    });
    expect(result.current.draft.clicks).toBe(5);
    expect(result.current.body(trim, undefined)).toEqual({ delta: 5 });

    act(() => {
      result.current.nudge(trim, undefined, 4, 1, 120);
    });
    expect(result.current.draft.clicks).toBe(20);

    act(() => {
      result.current.nudge(trim, undefined, 4, -1, 20);
    });
    expect(result.current.draft.clicks).toBe(0);
    expect(result.current.body(trim, undefined)).toBeNull();
  });

  it('body is null when clean, invalid, or for another control', () => {
    const { result } = renderHook(() => useRotaryDraft());

    act(() => {
      result.current.setText(altitude, '   ');
    });
    expect(result.current.body(altitude, undefined)).toBeNull();

    act(() => {
      result.current.setText(altitude, '4321');
    });
    expect(result.current.body(altitude, undefined)).toEqual({ value: 4300 });
    expect(result.current.body(heading, undefined)).toBeNull();
    expect(result.current.body(trim, undefined)).toBeNull();

    act(() => {
      result.current.reset();
    });
    expect(result.current.draft).toEqual(EMPTY_ROTARY_DRAFT);
    expect(result.current.body(altitude, undefined)).toBeNull();
  });

  it('keeps the mutators stable across renders', () => {
    const { result } = renderHook(() => useRotaryDraft());
    const { setText, nudge, reset } = result.current;

    act(() => {
      setText(altitude, '4000');
    });

    expect(result.current.setText).toBe(setText);
    expect(result.current.nudge).toBe(nudge);
    expect(result.current.reset).toBe(reset);
  });
});
