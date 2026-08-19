/**
 * The controls are dumb — values in, callbacks out — so the tests are about what
 * they emit and what they refuse to offer: the angle slider must be dead while the
 * direction is straight (design §7.1), and the segment labels must speak D5's nose
 * convention out loud.
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PushbackControls } from './PushbackControls';
import type { PushbackDirection } from '../../api/models';

function renderControls(
  overrides: Partial<{
    direction: PushbackDirection;
    angleDeg: number;
    disabled: boolean;
  }> = {},
) {
  const onDirectionSelected = vi.fn();
  const onDistanceChanged = vi.fn();
  const onAngleChanged = vi.fn();
  render(
    <PushbackControls
      direction={overrides.direction ?? 'straight'}
      distanceM={20}
      angleDeg={overrides.angleDeg ?? 0}
      maxDistanceM={200}
      maxAngleDeg={180}
      disabled={overrides.disabled ?? false}
      onDirectionSelected={onDirectionSelected}
      onDistanceChanged={onDistanceChanged}
      onAngleChanged={onAngleChanged}
    />,
  );
  return { onDirectionSelected, onDistanceChanged, onAngleChanged };
}

describe('PushbackControls', () => {
  it('labels the segments with where the NOSE goes (D5), marking the active one', () => {
    renderControls({ direction: 'right', angleDeg: 45 });

    expect(screen.getByRole('button', { name: 'Nose left' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    expect(screen.getByRole('button', { name: 'Straight' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    expect(screen.getByRole('button', { name: 'Nose right' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('emits the tapped direction', () => {
    const { onDirectionSelected } = renderControls();

    fireEvent.click(screen.getByRole('button', { name: 'Nose left' }));

    expect(onDirectionSelected).toHaveBeenCalledWith('left');
  });

  it('emits slider edits as numbers', () => {
    const { onDistanceChanged, onAngleChanged } = renderControls({
      direction: 'right',
      angleDeg: 45,
    });

    fireEvent.change(screen.getByRole('slider', { name: 'Pushback distance' }), {
      target: { value: '30' },
    });
    fireEvent.change(screen.getByRole('slider', { name: 'Pushback turn angle' }), {
      target: { value: '60' },
    });

    expect(onDistanceChanged).toHaveBeenCalledWith(30);
    expect(onAngleChanged).toHaveBeenCalledWith(60);
  });

  it('disables the angle slider while the direction is straight', () => {
    renderControls({ direction: 'straight' });

    expect(screen.getByRole('slider', { name: 'Pushback turn angle' })).toBeDisabled();
    expect(screen.getByRole('slider', { name: 'Pushback distance' })).toBeEnabled();
  });

  it('disables everything when the gate is closed — nothing disappears', () => {
    renderControls({ direction: 'right', angleDeg: 45, disabled: true });

    expect(screen.getByRole('button', { name: 'Nose right' })).toBeDisabled();
    expect(screen.getByRole('slider', { name: 'Pushback distance' })).toBeDisabled();
    expect(screen.getByRole('slider', { name: 'Pushback turn angle' })).toBeDisabled();
  });
});
