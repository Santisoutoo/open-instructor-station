import { fireEvent, render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { describe, expect, it } from 'vitest';
import { setupStore, type RootState } from '../../store';
import { PositionPanel } from './PositionPanel';

function renderPanel(preloadedState: Partial<RootState> = {}) {
  const store = setupStore(preloadedState);
  render(
    <Provider store={store}>
      <PositionPanel />
    </Provider>,
  );
  return store;
}

describe('PositionPanel', () => {
  it('renders the 4 real tabs with exactly one selected', () => {
    renderPanel();

    const tabs = screen.getAllByRole('tab', { name: /Approach training|SID & STAR|Airwork|Custom location/ });
    expect(tabs).toHaveLength(4);
    const selected = tabs.filter((tab) => tab.getAttribute('aria-selected') === 'true');
    expect(selected).toHaveLength(1);
    expect(selected[0]).toHaveTextContent('Approach training');
  });

  it('clicking a circuit marker updates the selected start position', () => {
    renderPanel();

    expect(screen.getByRole('heading', { name: '3 NM final' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '8 NM final' }));

    expect(screen.getByRole('heading', { name: '8 NM final' })).toBeInTheDocument();
  });

  it('picking a stand clears the runway tab selection', () => {
    const store = renderPanel();
    expect(store.getState().positionDesign.selectedRunway).toBe('04R');

    fireEvent.click(screen.getByRole('button', { name: /^Start at/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Stand A1' }));

    const state = store.getState();
    expect(state.positionDesign.selectedStand).toBe('A1');
    expect(state.positionDesign.selectedRunway).toBeNull();
    expect(screen.getByRole('tab', { name: '04R' })).toHaveAttribute(
      'aria-selected',
      'false',
    );
  });
});
