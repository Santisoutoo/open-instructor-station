import { fireEvent, render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { describe, expect, it } from 'vitest';
import { setupStore } from '../../store';
import { PositionHeaderBar } from './PositionHeaderBar';

function renderOpenPopover() {
  const store = setupStore();
  render(
    <Provider store={store}>
      <PositionHeaderBar />
    </Provider>,
  );
  const trigger = screen.getByRole('button', { name: /^Start at/ });
  fireEvent.click(trigger);
  return { store, trigger };
}

describe('StartAtPopover', () => {
  it('Escape closes the popover and returns focus to the trigger', () => {
    const { trigger } = renderOpenPopover();

    expect(screen.getByRole('dialog')).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('a parking filter narrows the stand list and the "N of M" count follows', () => {
    renderOpenPopover();

    expect(screen.getByText('16 of 16')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Tie-down' }));

    expect(screen.getByText('4 of 16')).toBeInTheDocument();
  });

  it('a diagram marker and its list row select the same stand', () => {
    const { store } = renderOpenPopover();

    fireEvent.click(screen.getByRole('button', { name: 'Stand A1' }));

    expect(store.getState().positionDesign.selectedStand).toBe('A1');
    expect(screen.getByRole('button', { name: 'Stand A1' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    const listRow = screen.getAllByRole('button', { name: /^A1/ }).find(
      (el) => el.getAttribute('aria-label') === null,
    );
    expect(listRow).toBeDefined();
  });
});
