/**
 * Client state of the Camera panel. The property that matters is D6: the highlight is
 * the last view *requested*, optimistic and client-only — so the reducers, not a server
 * read, are the whole truth about it and must get every transition right.
 */

import { describe, expect, it } from 'vitest';
import reducer, {
  initialCameraUiState,
  positionApplied,
  positionDeleted,
  saveDraftCleared,
  saveDraftNameChanged,
  viewRequested,
} from './cameraSlice';

describe('initial state', () => {
  it('starts with no view requested, no selection and an empty draft', () => {
    expect(initialCameraUiState).toEqual({
      lastRequestedView: null,
      selectedPositionId: null,
      saveDraftName: '',
    });
  });
});

describe('viewRequested', () => {
  it('remembers the last view tapped as the optimistic highlight', () => {
    const state = reducer(undefined, viewRequested('chase'));
    expect(state.lastRequestedView).toBe('chase');
  });

  it('replaces a previous request rather than accumulating', () => {
    const chase = reducer(undefined, viewRequested('chase'));
    expect(reducer(chase, viewRequested('tower')).lastRequestedView).toBe('tower');
  });

  it('drops the selected saved position — a named view does not imply one', () => {
    const applied = reducer(undefined, positionApplied('pos-1'));
    const state = reducer(applied, viewRequested('cockpit'));

    expect(state.selectedPositionId).toBeNull();
    expect(state.lastRequestedView).toBe('cockpit');
  });
});

describe('positionApplied', () => {
  it('selects the position and moves the highlight to the drone view', () => {
    const state = reducer(undefined, positionApplied('pos-1'));

    expect(state.selectedPositionId).toBe('pos-1');
    expect(state.lastRequestedView).toBe('drone');
  });
});

describe('positionDeleted', () => {
  it('forgets the selection when the deleted position was the selected one', () => {
    const applied = reducer(undefined, positionApplied('pos-1'));
    expect(reducer(applied, positionDeleted('pos-1')).selectedPositionId).toBeNull();
  });

  it('keeps the selection when some other position was deleted', () => {
    const applied = reducer(undefined, positionApplied('pos-1'));
    expect(reducer(applied, positionDeleted('pos-2')).selectedPositionId).toBe('pos-1');
  });
});

describe('the save draft', () => {
  it('holds the typed name', () => {
    const state = reducer(undefined, saveDraftNameChanged('Base leg view'));
    expect(state.saveDraftName).toBe('Base leg view');
  });

  it('resets on clear', () => {
    const typed = reducer(undefined, saveDraftNameChanged('Base leg view'));
    expect(reducer(typed, saveDraftCleared()).saveDraftName).toBe('');
  });
});
