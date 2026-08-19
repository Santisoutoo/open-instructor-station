/**
 * The view grid: five named views as touch targets, disabled per-entry WITH the
 * manifest's reason (hard rule 3 — disabled, never throwing), and the D6 optimistic
 * highlight — a tap emits the exact view id and the highlight follows the *request*,
 * driven by the camera slice, never by a server read.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useReducer } from 'react';
import { describe, expect, it, vi } from 'vitest';
import cameraReducer, { initialCameraUiState, viewRequested } from './cameraSlice';
import { cameraManifestFixture } from './mock';
import { type CameraViewSupport } from './types.mock';
import { ViewGrid } from './ViewGrid';

const WING_REASON =
  'No X-Plane command for a wing view was found on this install, so the wing view is unavailable.';

/** The all-supported fixture with the wing entry degraded, the §10.4 honest outcome. */
function viewsWithWingUnsupported(): readonly CameraViewSupport[] {
  return cameraManifestFixture().views.map((entry) =>
    entry.view_id === 'wing'
      ? { ...entry, supported: false, reason: WING_REASON }
      : entry,
  );
}

/** The slice wired straight to the grid, exactly as the panel will wire it (D6). */
function Harness({ views }: { views: readonly CameraViewSupport[] }) {
  const [state, dispatch] = useReducer(cameraReducer, initialCameraUiState);
  return (
    <ViewGrid
      views={views}
      activeViewId={state.lastRequestedView}
      disabled={false}
      onSelectView={(viewId) => {
        dispatch(viewRequested(viewId));
      }}
    />
  );
}

describe('ViewGrid', () => {
  it('renders the five named views as buttons, in catalogue order', () => {
    render(
      <ViewGrid
        views={cameraManifestFixture().views}
        activeViewId={null}
        disabled={false}
        onSelectView={() => undefined}
      />,
    );

    const labels = screen
      .getAllByRole('button')
      .map((button) => button.querySelector('.camera-view-card__label')?.textContent);
    expect(labels).toEqual(['Cockpit', 'Chase', 'Tower', 'Wing', 'Drone / free']);
  });

  it('renders an unsupported view disabled, with its reason inline', () => {
    render(
      <ViewGrid
        views={viewsWithWingUnsupported()}
        activeViewId={null}
        disabled={false}
        onSelectView={() => undefined}
      />,
    );

    expect(screen.getByRole('button', { name: /Wing/ })).toBeDisabled();
    expect(screen.getByText(WING_REASON)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Chase/ })).toBeEnabled();
  });

  it('emits exactly the tapped view id', async () => {
    const user = userEvent.setup();
    const onSelectView = vi.fn();
    render(
      <ViewGrid
        views={cameraManifestFixture().views}
        activeViewId={null}
        disabled={false}
        onSelectView={onSelectView}
      />,
    );

    await user.click(screen.getByRole('button', { name: /Chase/ }));

    expect(onSelectView).toHaveBeenCalledTimes(1);
    expect(onSelectView).toHaveBeenCalledWith('chase');
  });

  it('moves the optimistic highlight to the last view requested (D6)', async () => {
    const user = userEvent.setup();
    render(<Harness views={cameraManifestFixture().views} />);

    // Before any tap, nothing claims to be current.
    expect(screen.getByRole('button', { name: /Chase/ })).toHaveAttribute(
      'aria-pressed',
      'false',
    );

    await user.click(screen.getByRole('button', { name: /Chase/ }));
    expect(screen.getByRole('button', { name: /Chase/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    );

    await user.click(screen.getByRole('button', { name: /Tower/ }));
    expect(screen.getByRole('button', { name: /Tower/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByRole('button', { name: /Chase/ })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });

  it('disables every view, none disappearing, while the gate is closed', () => {
    render(
      <ViewGrid
        views={cameraManifestFixture().views}
        activeViewId={null}
        disabled={true}
        onSelectView={() => undefined}
      />,
    );

    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(5);
    for (const button of buttons) {
      expect(button).toBeDisabled();
    }
  });
});
