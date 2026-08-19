/**
 * The saved-positions list. What matters: "Save current" is disabled WITH a stated
 * reason when the adapter cannot position a free camera or when the drone view is not
 * the last one requested (the client-side mirror of the server's 409, design §7.1),
 * and Apply/Delete emit exactly one intent each with the exact position id.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { savedPositionsFixture } from './mock';
import { SavedPositions } from './SavedPositions';

const BRIDGE_REASON =
  'Free-camera positioning needs the optional in-sim bridge on this X-Plane build.';

function renderList(overrides: Partial<Parameters<typeof SavedPositions>[0]> = {}) {
  const handlers = {
    onDraftNameChanged: vi.fn(),
    onSaveCurrent: vi.fn(),
    onApply: vi.fn(),
    onDelete: vi.fn(),
  };
  render(
    <SavedPositions
      positions={savedPositionsFixture()}
      selectedPositionId={null}
      customPositionsSupported={true}
      customPositionsReason={null}
      droneActive={true}
      disabled={false}
      draftName=""
      {...handlers}
      {...overrides}
    />,
  );
  return handlers;
}

describe('SavedPositions', () => {
  it('lists every saved position with an Apply and a delete action', () => {
    renderList();

    expect(
      screen.getByRole('button', { name: 'Apply Three-quarter left' }),
    ).toBeEnabled();
    expect(
      screen.getByRole('button', { name: 'Delete Three-quarter left' }),
    ).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Apply Base leg view' })).toBeEnabled();
  });

  it('states the empty case instead of showing a bare list', () => {
    renderList({ positions: [] });

    expect(screen.getByText('No saved positions yet.')).toBeInTheDocument();
  });

  it('emits exactly one apply intent with the exact position id', async () => {
    const user = userEvent.setup();
    const handlers = renderList();

    await user.click(screen.getByRole('button', { name: 'Apply Base leg view' }));

    expect(handlers.onApply).toHaveBeenCalledTimes(1);
    expect(handlers.onApply).toHaveBeenCalledWith('mock-pos-2');
    expect(handlers.onDelete).not.toHaveBeenCalled();
  });

  it('emits exactly one delete intent with the exact position id', async () => {
    const user = userEvent.setup();
    const handlers = renderList();

    await user.click(screen.getByRole('button', { name: 'Delete Three-quarter left' }));

    expect(handlers.onDelete).toHaveBeenCalledTimes(1);
    expect(handlers.onDelete).toHaveBeenCalledWith('mock-pos-1');
    expect(handlers.onApply).not.toHaveBeenCalled();
  });

  it('marks the selected position and no other', () => {
    renderList({ selectedPositionId: 'mock-pos-2' });

    const rows = screen.getAllByRole('listitem');
    expect(rows[1]).toHaveAttribute('aria-current', 'true');
    expect(rows[0]).not.toHaveAttribute('aria-current');
  });

  it('submits the trimmed draft name as the save intent', async () => {
    const user = userEvent.setup();
    const handlers = renderList({ draftName: '  Base leg view  ' });

    await user.click(screen.getByRole('button', { name: 'Save current' }));

    expect(handlers.onSaveCurrent).toHaveBeenCalledTimes(1);
    expect(handlers.onSaveCurrent).toHaveBeenCalledWith('Base leg view');
  });

  it('refuses to save an empty name', () => {
    renderList({ draftName: '   ' });

    expect(screen.getByRole('button', { name: 'Save current' })).toBeDisabled();
  });

  it('disables saving with the manifest reason when custom positions are unsupported', () => {
    renderList({
      customPositionsSupported: false,
      customPositionsReason: BRIDGE_REASON,
      draftName: 'Base leg view',
    });

    expect(screen.getByRole('button', { name: 'Save current' })).toBeDisabled();
    expect(screen.getByText(BRIDGE_REASON)).toBeInTheDocument();
    // Apply needs the same adapter support saving does; Delete is local storage.
    expect(screen.getByRole('button', { name: 'Apply Base leg view' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Delete Base leg view' })).toBeEnabled();
  });

  it('disables saving with a stated reason until the drone view is the last requested', () => {
    renderList({ droneActive: false, draftName: 'Base leg view' });

    expect(screen.getByRole('button', { name: 'Save current' })).toBeDisabled();
    expect(
      screen.getByText('Switch to the drone/free camera to save the current position.'),
    ).toBeInTheDocument();
    // The precondition blocks only the save; recalling a position is unaffected.
    expect(screen.getByRole('button', { name: 'Apply Base leg view' })).toBeEnabled();
  });

  it('forwards typing to the draft callback', async () => {
    const user = userEvent.setup();
    const handlers = renderList();

    await user.type(screen.getByRole('textbox', { name: 'Position name' }), 'B');

    expect(handlers.onDraftNameChanged).toHaveBeenCalledWith('B');
  });
});
