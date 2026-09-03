/**
 * `ControlRow` is a pure prop-in/callback-out component (`CockpitPanel` owns the one
 * `actuateCockpitControl` mutation and passes `onCommit` down) — so "does a tap issue the
 * right body" is a callback assertion here, and "does the panel show the confirmed value,
 * not the optimistic click" lives one level up: `value` is always whatever the caller
 * passes, and the caller only ever passes the confirmed snapshot (never a locally-clicked
 * draft), so there is no optimistic value in this component to reconcile away.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { cockpitCatalogManifestFixture } from './fixtures';
import { ControlRow } from './ControlRow';
import type { CockpitControlSpec } from '../../api/models';

function specFor(controlId: string): CockpitControlSpec {
  const spec = cockpitCatalogManifestFixture().controls.find(
    (control) => control.control_id === controlId,
  );
  if (spec === undefined) {
    throw new Error(`fixture is missing ${controlId}`);
  }
  return spec;
}

describe('ControlRow', () => {
  it('toggle: shows the confirmed value and commits the flipped one', async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(
      <ControlRow
        spec={specFor('fd_capt')}
        value={false}
        hints={[]}
        pending={false}
        onCommit={onCommit}
      />,
    );

    expect(screen.getByRole('button', { name: 'Off' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Off' }));

    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith({ value: true });
  });

  it('toggle: reads "Unknown" rather than guessing a side when nothing has been read yet', () => {
    render(
      <ControlRow
        spec={specFor('fd_capt')}
        value={null}
        hints={[]}
        pending={false}
        onCommit={vi.fn()}
      />,
    );

    expect(screen.getByRole('button')).toHaveTextContent('Unknown');
  });

  it('toggle: locks and says so while a write is in flight', () => {
    render(
      <ControlRow
        spec={specFor('fd_capt')}
        value={false}
        hints={[]}
        pending={true}
        onCommit={vi.fn()}
      />,
    );

    const button = screen.getByRole('button');
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent('Setting…');
  });

  it('press: commits with neither value nor delta set', async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(
      <ControlRow
        spec={specFor('chime_test')}
        value={null}
        hints={[]}
        pending={false}
        onCommit={onCommit}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Press' }));

    expect(onCommit).toHaveBeenCalledWith({});
  });

  it('dial: "Set" issues exactly one commit with the typed value', async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(
      <ControlRow
        spec={specFor('mcp_alt')}
        value={5000}
        hints={[]}
        pending={false}
        onCommit={onCommit}
      />,
    );

    await user.type(screen.getByRole('spinbutton'), '4000');
    await user.click(screen.getByRole('button', { name: 'Set' }));

    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith({ value: 4000 });
  });

  it('encoder: a tap on "+" commits delta: 1', async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(
      <ControlRow
        spec={specFor('stab_trim')}
        value={4}
        hints={[]}
        pending={false}
        onCommit={onCommit}
      />,
    );

    await user.click(screen.getByRole('button', { name: '+' }));

    expect(onCommit).toHaveBeenCalledWith({ delta: 1 });
  });

  it('selector: tapping an option commits its value', async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(
      <ControlRow
        spec={specFor('irs_l')}
        value={0}
        hints={[]}
        pending={false}
        onCommit={onCommit}
      />,
    );

    expect(screen.getByRole('button', { name: 'OFF' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );

    await user.click(screen.getByRole('button', { name: 'NAV' }));

    expect(onCommit).toHaveBeenCalledWith({ value: 2 });
  });

  it('renders unmet-precondition hints inline, informational only (row stays enabled)', () => {
    render(
      <ControlRow
        spec={specFor('hdg_sel')}
        value={false}
        hints={['HDG SEL needs a flight director or CMD A engaged.']}
        pending={false}
        onCommit={vi.fn()}
      />,
    );

    expect(
      screen.getByText('HDG SEL needs a flight director or CMD A engaged.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button')).toBeEnabled();
  });
});
