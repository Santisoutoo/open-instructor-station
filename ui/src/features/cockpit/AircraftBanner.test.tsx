import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { AircraftBanner } from './AircraftBanner';
import { cockpitCatalogManifestFixture } from './fixtures';

describe('AircraftBanner', () => {
  it('shows the aircraft label and the detection note when a catalog is active', () => {
    render(
      <AircraftBanner
        manifest={cockpitCatalogManifestFixture()}
        stale={false}
        refreshing={false}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByText('Fake trainer')).toBeInTheDocument();
    expect(screen.getByText('Synthetic catalog; nothing was probed.')).toBeInTheDocument();
  });

  it('shows the manifest reason, never a throw, when no aircraft is detected', () => {
    const manifest = {
      ...cockpitCatalogManifestFixture(),
      aircraft: null,
      reason: 'No cockpit catalog matched the loaded aircraft.',
      detection_note: null,
    };

    render(
      <AircraftBanner manifest={manifest} stale={false} refreshing={false} onRefresh={vi.fn()} />,
    );

    expect(
      screen.getByText('No cockpit catalog matched the loaded aircraft.'),
    ).toBeInTheDocument();
    expect(screen.queryByText('Fake trainer')).not.toBeInTheDocument();
  });

  it('the re-detect button issues exactly one refresh', async () => {
    const user = userEvent.setup();
    const onRefresh = vi.fn();
    render(
      <AircraftBanner
        manifest={cockpitCatalogManifestFixture()}
        stale={false}
        refreshing={false}
        onRefresh={onRefresh}
      />,
    );

    await user.click(screen.getByRole('button', { name: /re-detect aircraft/i }));

    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it('disables the button and says so while a refresh is in flight', () => {
    render(
      <AircraftBanner
        manifest={cockpitCatalogManifestFixture()}
        stale={false}
        refreshing={true}
        onRefresh={vi.fn()}
      />,
    );

    const button = screen.getByRole('button');
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent(/re-detecting/i);
  });

  it('shows a stale indicator when the snapshot revision disagrees with the catalog', () => {
    render(
      <AircraftBanner
        manifest={cockpitCatalogManifestFixture()}
        stale={true}
        refreshing={false}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByText(/refreshing/i)).toBeInTheDocument();
  });
});
