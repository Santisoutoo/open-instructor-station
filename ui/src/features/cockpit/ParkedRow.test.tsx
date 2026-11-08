import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ParkedRow } from './ParkedRow';
import { cockpitCatalogManifestFixture } from './fixtures';

describe('ParkedRow', () => {
  it('shows the label and the reason inline, disabled, with no click handler', () => {
    const [entry] = cockpitCatalogManifestFixture().parked;
    if (entry === undefined) {
      throw new Error('fixture has no parked entries');
    }

    render(<ParkedRow entry={entry} />);

    expect(screen.getByText('V/S')).toBeInTheDocument();
    expect(
      screen.getByText(
        'No settable vertical-speed dataref exists on the reference aircraft (research §6).',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText('V/S').closest('[aria-disabled="true"]')).not.toBeNull();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
