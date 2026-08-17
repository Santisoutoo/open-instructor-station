import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { describe, expect, it } from 'vitest';
import { setupStore } from '../store';
import { TabBar } from './TabBar';

function renderTabBar() {
  const store = setupStore();
  render(
    <Provider store={store}>
      <TabBar />
    </Provider>,
  );
  return store;
}

describe('<TabBar />', () => {
  it('lists the ten modules as a tablist with Position active by default', () => {
    renderTabBar();

    expect(screen.getByRole('tablist')).toBeInTheDocument();
    const tabs = screen.getAllByRole('tab');
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      'Position',
      'Scenarios',
      'Weather',
      'Failures',
      'Fuel & payload',
      'Profiles',
      'Map',
      'Aircraft',
      'Landing analysis',
      'Traffic',
    ]);
    expect(screen.getByRole('tab', { name: 'Position' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });

  it('clicking a tab selects it in the store', async () => {
    const user = userEvent.setup();
    const store = renderTabBar();

    await user.click(screen.getByRole('tab', { name: 'Weather' }));

    expect(store.getState().ui.activeTab).toBe('weather');
    expect(screen.getByRole('tab', { name: 'Weather' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(screen.getByRole('tab', { name: 'Position' })).toHaveAttribute(
      'aria-selected',
      'false',
    );
  });

  it('arrow keys move the selection', async () => {
    const user = userEvent.setup();
    const store = renderTabBar();

    screen.getByRole('tab', { name: 'Position' }).focus();
    await user.keyboard('{ArrowRight}');
    expect(store.getState().ui.activeTab).toBe('scenarios');

    await user.keyboard('{ArrowLeft}');
    expect(store.getState().ui.activeTab).toBe('position');

    await user.keyboard('{End}');
    expect(store.getState().ui.activeTab).toBe('traffic');

    await user.keyboard('{Home}');
    expect(store.getState().ui.activeTab).toBe('position');
  });
});
