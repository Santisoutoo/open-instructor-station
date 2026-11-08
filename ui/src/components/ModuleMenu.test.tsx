import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { describe, expect, it } from 'vitest';
import { setupStore } from '../store';
import { tabSelected } from '../store/uiSlice';
import { ModuleMenu } from './ModuleMenu';
import { TABS } from './tabs';

/**
 * Renders the menu against a real store, next to an unrelated button that stands in for
 * "anywhere else on the page" for the outside-click tests.
 */
function renderModuleMenu() {
  const store = setupStore();
  render(
    <Provider store={store}>
      <ModuleMenu />
      <button type="button">Outside</button>
    </Provider>,
  );
  return { store, user: userEvent.setup() };
}

/** The trigger is the menu's `aria-haspopup` button; the outside button has none. */
function trigger(): HTMLElement {
  const triggers = screen
    .getAllByRole('button')
    .filter((button) => button.getAttribute('aria-haspopup') === 'menu');
  const [only] = triggers;
  if (triggers.length !== 1 || only === undefined) {
    throw new Error(
      `expected exactly one module-menu trigger, found ${String(triggers.length)}`,
    );
  }
  return only;
}

describe('<ModuleMenu />', () => {
  it('labels the closed trigger with the active module, Position by default', () => {
    renderModuleMenu();

    expect(trigger()).toHaveAccessibleName('Position');
    expect(trigger()).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('relabels the trigger when the active module changes in the store', () => {
    const { store } = renderModuleMenu();

    act(() => {
      store.dispatch(tabSelected('weather'));
    });

    expect(trigger()).toHaveAccessibleName('Weather');
  });

  it('opens a "Modules" menu listing every registered module in registry order', async () => {
    const { store, user } = renderModuleMenu();

    await user.click(trigger());

    expect(trigger()).toHaveAttribute('aria-expanded', 'true');
    expect(store.getState().ui.moduleMenuOpen).toBe(true);
    const menu = screen.getByRole('menu', { name: 'Modules' });
    const items = within(menu).getAllByRole('menuitem');
    expect(items.map((item) => item.textContent)).toEqual(TABS.map((tab) => tab.label));
    expect(within(menu).getByRole('menuitem', { name: 'Cockpit' })).toBeInTheDocument();
  });

  it('points the trigger at the popover it opens', async () => {
    const { user } = renderModuleMenu();

    await user.click(trigger());

    const controlled = trigger().getAttribute('aria-controls');
    expect(controlled).not.toBeNull();
    expect(document.getElementById(controlled ?? '')).toContainElement(
      screen.getByRole('menu', { name: 'Modules' }),
    );
  });

  it('marks only the active module with aria-current="page"', async () => {
    const { store, user } = renderModuleMenu();
    act(() => {
      store.dispatch(tabSelected('failures'));
    });

    await user.click(trigger());

    const current = screen
      .getAllByRole('menuitem')
      .filter((item) => item.hasAttribute('aria-current'));
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveAccessibleName('Failures');
    expect(current[0]).toHaveAttribute('aria-current', 'page');
  });

  it('selects a module: sets ui.activeTab, closes the menu and relabels the trigger', async () => {
    const { store, user } = renderModuleMenu();

    await user.click(trigger());
    await user.click(screen.getByRole('menuitem', { name: 'Fuel & payload' }));

    expect(store.getState().ui.activeTab).toBe('fuel-payload');
    expect(store.getState().ui.moduleMenuOpen).toBe(false);
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(trigger()).toHaveAccessibleName('Fuel & payload');
    expect(trigger()).toHaveAttribute('aria-expanded', 'false');
    expect(trigger()).toHaveFocus();
  });

  it('closes on Escape and returns focus to the trigger', async () => {
    const { store, user } = renderModuleMenu();

    await user.click(trigger());
    // Move focus into the menu first, so "focus returns" is a real move, not a no-op.
    screen.getByRole('menuitem', { name: 'Map' }).focus();
    expect(trigger()).not.toHaveFocus();

    await user.keyboard('{Escape}');

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(store.getState().ui.moduleMenuOpen).toBe(false);
    expect(store.getState().ui.activeTab).toBe('position');
    expect(trigger()).toHaveAttribute('aria-expanded', 'false');
    expect(trigger()).toHaveFocus();
  });

  it('closes on a pointerdown outside the menu without changing the module', async () => {
    const { store, user } = renderModuleMenu();

    await user.click(trigger());
    await user.pointer({
      keys: '[MouseLeft>]',
      target: screen.getByRole('button', { name: 'Outside' }),
    });

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(store.getState().ui.moduleMenuOpen).toBe(false);
    expect(store.getState().ui.activeTab).toBe('position');
    expect(trigger()).toHaveAttribute('aria-expanded', 'false');
  });

  it('stays open on a pointerdown inside the menu', async () => {
    const { user } = renderModuleMenu();

    await user.click(trigger());
    await user.pointer({
      keys: '[MouseLeft>]',
      target: screen.getByRole('menu', { name: 'Modules' }),
    });

    expect(screen.getByRole('menu', { name: 'Modules' })).toBeInTheDocument();
  });

  it('toggles closed when the trigger is clicked again, keeping focus on it', async () => {
    const { store, user } = renderModuleMenu();

    await user.click(trigger());
    expect(screen.getByRole('menu', { name: 'Modules' })).toBeInTheDocument();

    await user.click(trigger());

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(store.getState().ui.moduleMenuOpen).toBe(false);
    expect(trigger()).toHaveAttribute('aria-expanded', 'false');
    expect(trigger()).toHaveFocus();
  });

  it('focuses the current module on open and moves with the arrow, Home and End keys', async () => {
    const { store, user } = renderModuleMenu();
    act(() => {
      store.dispatch(tabSelected('weather'));
    });

    await user.click(trigger());
    const menu = screen.getByRole('menu', { name: 'Modules' });
    const item = (name: string) => within(menu).getByRole('menuitem', { name });
    expect(item('Weather')).toHaveFocus();

    await user.keyboard('{ArrowDown}');
    expect(item('Failures')).toHaveFocus();
    await user.keyboard('{ArrowUp}{ArrowUp}');
    expect(item('Scenarios')).toHaveFocus();
    await user.keyboard('{End}');
    expect(item(TABS[TABS.length - 1]?.label ?? '')).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(item('Position')).toHaveFocus();
    await user.keyboard('{ArrowUp}');
    expect(item(TABS[TABS.length - 1]?.label ?? '')).toHaveFocus();
    await user.keyboard('{Home}');
    expect(item('Position')).toHaveFocus();

    await user.keyboard('{ArrowDown}{Enter}');
    expect(store.getState().ui.activeTab).toBe('scenarios');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('closes when Tab moves focus out of the menu, leaving focus where it went', async () => {
    const { store, user } = renderModuleMenu();

    await user.click(trigger());
    await user.keyboard('{End}');
    await user.tab();

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(store.getState().ui.moduleMenuOpen).toBe(false);
    expect(screen.getByRole('button', { name: 'Outside' })).toHaveFocus();
  });
});
