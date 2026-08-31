import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ProcedureViewToggle } from './ProcedureViewToggle';

describe('ProcedureViewToggle', () => {
  it('aria-pressed matches the current mode', () => {
    render(<ProcedureViewToggle mode="2d" onSelect={vi.fn()} />);
    expect(screen.getByRole('button', { name: '2D' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByRole('button', { name: '3D' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });

  it('clicking the other button calls onSelect with it', async () => {
    const onSelect = vi.fn();
    render(<ProcedureViewToggle mode="2d" onSelect={onSelect} />);

    await userEvent.click(screen.getByRole('button', { name: '3D' }));

    expect(onSelect).toHaveBeenCalledWith('3d');
  });

  it('clicking the already-active button still reports it (idempotent)', async () => {
    const onSelect = vi.fn();
    render(<ProcedureViewToggle mode="3d" onSelect={onSelect} />);

    await userEvent.click(screen.getByRole('button', { name: '3D' }));

    expect(onSelect).toHaveBeenCalledWith('3d');
  });
});
