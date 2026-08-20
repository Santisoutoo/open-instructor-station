/**
 * The form reducer's one invariant, exercised from every edge: the form always
 * describes a request the backend's §3 validator would accept — angle 0 exactly when
 * straight, in (0, max] otherwise — and a staged request never outlives an edit.
 *
 * The ceiling arrives *on the action*, from `GET /api/pushback/manifest`, and these tests
 * pass it explicitly: the reducer must clamp against whatever the server said, never
 * against a constant of its own. `MANIFEST_MAX_*` are the values `core.pushback`
 * publishes today; the point of the "different ceiling" case is that another pair would
 * be honoured just as faithfully, with no UI change.
 */

import { describe, expect, it } from 'vitest';
import reducer, {
  PUSHBACK_DEFAULT_ARC_ANGLE_DEG,
  PUSHBACK_DEFAULT_DISTANCE_M,
  angleChanged,
  directionSelected,
  distanceChanged,
  initialPushbackState,
  previewStaged,
  stagedDiscarded,
  toRequest,
} from './pushbackSlice';

/** What `GET /api/pushback/manifest` states today. The reducer is told; it never assumes. */
const MANIFEST_MAX_DISTANCE_M = 200;
const MANIFEST_MAX_ANGLE_DEG = 180;

/** The panel always passes the manifest's bound alongside the slider's new value. */
function distanceEdit(value: number, max: number | undefined = MANIFEST_MAX_DISTANCE_M) {
  return distanceChanged({ value, max });
}

function angleEdit(value: number, max: number | undefined = MANIFEST_MAX_ANGLE_DEG) {
  return angleChanged({ value, max });
}

describe('pushbackSlice', () => {
  it("starts at the design's one-tap default: straight back, 20 m, nothing staged", () => {
    expect(reducer(undefined, { type: '@@INIT' })).toEqual({
      direction: 'straight',
      distanceM: PUSHBACK_DEFAULT_DISTANCE_M,
      angleDeg: 0,
      staged: null,
    });
  });

  it('seeds the default arc angle when leaving straight with the angle still 0', () => {
    const state = reducer(initialPushbackState, directionSelected('right'));

    expect(state.direction).toBe('right');
    expect(state.angleDeg).toBe(PUSHBACK_DEFAULT_ARC_ANGLE_DEG);
  });

  it('keeps a deliberately chosen angle when switching between left and right', () => {
    let state = reducer(initialPushbackState, directionSelected('right'));
    state = reducer(state, angleEdit(60));

    state = reducer(state, directionSelected('left'));

    expect(state.angleDeg).toBe(60);
  });

  it('zeroes the angle when returning to straight — 5° straight would be a 422', () => {
    let state = reducer(initialPushbackState, directionSelected('right'));
    state = reducer(state, angleEdit(60));

    state = reducer(state, directionSelected('straight'));

    expect(state.angleDeg).toBe(0);
  });

  it("clamps the distance to the manifest's ceiling — a slider cannot show an error", () => {
    expect(reducer(initialPushbackState, distanceEdit(500)).distanceM).toBe(
      MANIFEST_MAX_DISTANCE_M,
    );
    expect(reducer(initialPushbackState, distanceEdit(0)).distanceM).toBe(1);
    expect(reducer(initialPushbackState, distanceEdit(-5)).distanceM).toBe(1);
  });

  it("clamps the angle to the manifest's ceiling on an arc, ignoring writes while straight", () => {
    const arc = reducer(initialPushbackState, directionSelected('right'));

    expect(reducer(arc, angleEdit(999)).angleDeg).toBe(MANIFEST_MAX_ANGLE_DEG);
    expect(reducer(arc, angleEdit(0)).angleDeg).toBe(1);
    // Straight: the disabled slider must not be able to smuggle an angle in.
    expect(reducer(initialPushbackState, angleEdit(30)).angleDeg).toBe(0);
  });

  it('honours a ceiling that is not the shipped one — the bound is the server\'s', () => {
    expect(reducer(initialPushbackState, distanceEdit(500, 50)).distanceM).toBe(50);

    const arc = reducer(initialPushbackState, directionSelected('right'));
    expect(reducer(arc, angleEdit(500, 90)).angleDeg).toBe(90);
  });

  it('leaves the top open until a bound is stated — the gate has the panel closed then', () => {
    // Dispatched directly: `distanceEdit`'s default would turn an explicit `undefined`
    // back into the shipped ceiling, which is the opposite of what this pins.
    const edit = distanceChanged({ value: 500, max: undefined });

    expect(reducer(initialPushbackState, edit).distanceM).toBe(500);
  });

  it('stages the exact wire shape — snake_case keys, no extras (§3)', () => {
    let state = reducer(initialPushbackState, directionSelected('right'));
    state = reducer(state, distanceEdit(30));
    state = reducer(state, angleEdit(90));

    state = reducer(state, previewStaged());

    expect(state.staged).toEqual({ direction: 'right', distance_m: 30, angle_deg: 90 });
  });

  it('discards the staged request on ANY edit — a stale preview never executes', () => {
    const staged = reducer(
      reducer(initialPushbackState, directionSelected('right')),
      previewStaged(),
    );

    expect(reducer(staged, distanceEdit(40)).staged).toBeNull();
    expect(reducer(staged, angleEdit(30)).staged).toBeNull();
    expect(reducer(staged, directionSelected('left')).staged).toBeNull();
    expect(reducer(staged, stagedDiscarded()).staged).toBeNull();
  });

  it('toRequest emits the exact request shape from the form', () => {
    expect(toRequest(initialPushbackState)).toEqual({
      direction: 'straight',
      distance_m: PUSHBACK_DEFAULT_DISTANCE_M,
      angle_deg: 0,
    });
  });
});
