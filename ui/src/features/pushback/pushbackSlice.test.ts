/**
 * The form reducer's one invariant, exercised from every edge: the form always
 * describes a request the backend's §3 validator would accept — angle 0 exactly when
 * straight, in (0, max] otherwise — and a staged request never outlives an edit.
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
    state = reducer(state, angleChanged(60));

    state = reducer(state, directionSelected('left'));

    expect(state.angleDeg).toBe(60);
  });

  it('zeroes the angle when returning to straight — 5° straight would be a 422', () => {
    let state = reducer(initialPushbackState, directionSelected('right'));
    state = reducer(state, angleChanged(60));

    state = reducer(state, directionSelected('straight'));

    expect(state.angleDeg).toBe(0);
  });

  it('clamps the distance into (0, 200] — a slider cannot show an error', () => {
    expect(reducer(initialPushbackState, distanceChanged(500)).distanceM).toBe(200);
    expect(reducer(initialPushbackState, distanceChanged(0)).distanceM).toBe(1);
    expect(reducer(initialPushbackState, distanceChanged(-5)).distanceM).toBe(1);
  });

  it('clamps the angle into (0, 180] on an arc and ignores writes while straight', () => {
    const arc = reducer(initialPushbackState, directionSelected('right'));

    expect(reducer(arc, angleChanged(999)).angleDeg).toBe(180);
    expect(reducer(arc, angleChanged(0)).angleDeg).toBe(1);
    // Straight: the disabled slider must not be able to smuggle an angle in.
    expect(reducer(initialPushbackState, angleChanged(30)).angleDeg).toBe(0);
  });

  it('stages the exact wire shape — snake_case keys, no extras (§3)', () => {
    let state = reducer(initialPushbackState, directionSelected('right'));
    state = reducer(state, distanceChanged(30));
    state = reducer(state, angleChanged(90));

    state = reducer(state, previewStaged());

    expect(state.staged).toEqual({ direction: 'right', distance_m: 30, angle_deg: 90 });
  });

  it('discards the staged request on ANY edit — a stale preview never executes', () => {
    const staged = reducer(
      reducer(initialPushbackState, directionSelected('right')),
      previewStaged(),
    );

    expect(reducer(staged, distanceChanged(40)).staged).toBeNull();
    expect(reducer(staged, angleChanged(30)).staged).toBeNull();
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
