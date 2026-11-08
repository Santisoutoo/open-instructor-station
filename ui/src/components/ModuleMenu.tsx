import { useEffect, useRef, type KeyboardEvent } from 'react';
import { useAppDispatch, useAppSelector } from '../store';
import { moduleMenuClosed, moduleMenuToggled, tabSelected } from '../store/uiSlice';
import { Popover } from './Popover';
import { TABS } from './tabs';
import './ModuleMenu.css';

/**
 * The module navigation: a `<Current module> ▾` trigger and a dropdown listing every
 * module, one click away. The same component sits in the shell header and in Position's
 * full-bleed header, so every screen navigates the same way. It anchors its own popover
 * (`.modulemenu` is the positioning context), so it works in any header height.
 *
 * Keyboard follows the ARIA menu-button pattern, keeping what the old tab bar's arrow keys
 * offered: opening focuses the current module, ↑/↓ move with wrap-around, Home/End jump
 * to the ends. Escape and the focus return to the trigger come from `Popover`.
 */
export function ModuleMenu() {
  const dispatch = useAppDispatch();
  const activeTab = useAppSelector((state) => state.ui.activeTab);
  const open = useAppSelector((state) => state.ui.moduleMenuOpen);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    if (open) {
      listRef.current?.querySelector<HTMLElement>('[aria-current="page"]')?.focus();
    }
  }, [open]);

  const onListKeyDown = (event: KeyboardEvent<HTMLUListElement>) => {
    const items = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    );
    const index = items.indexOf(document.activeElement as HTMLElement);
    let next: number | null = null;
    if (event.key === 'ArrowDown') {
      next = (index + 1) % items.length;
    } else if (event.key === 'ArrowUp') {
      next = (index - 1 + items.length) % items.length;
    } else if (event.key === 'Home') {
      next = 0;
    } else if (event.key === 'End') {
      next = items.length - 1;
    }
    if (next !== null) {
      event.preventDefault();
      items[next]?.focus();
    }
  };

  const activeLabel = TABS.find((tab) => tab.id === activeTab)?.label ?? 'Modules';

  return (
    <div className="modulemenu">
      <button
        ref={triggerRef}
        type="button"
        className="modulemenu__trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls="module-menu"
        onClick={() => {
          dispatch(moduleMenuToggled());
        }}
      >
        {activeLabel} <span aria-hidden="true">▾</span>
      </button>
      <Popover
        id="module-menu"
        open={open}
        onClose={() => {
          dispatch(moduleMenuClosed());
        }}
        triggerRef={triggerRef}
        className="modulemenu__popover"
      >
        <ul
          ref={listRef}
          className="modulemenu__list"
          role="menu"
          aria-label="Modules"
          onKeyDown={onListKeyDown}
        >
          {TABS.map((tab) => (
            <li key={tab.id} role="none">
              <button
                type="button"
                role="menuitem"
                className="modulemenu__item"
                aria-current={tab.id === activeTab ? 'page' : undefined}
                onClick={() => {
                  dispatch(tabSelected(tab.id));
                }}
              >
                {tab.label}
              </button>
            </li>
          ))}
        </ul>
      </Popover>
    </div>
  );
}
