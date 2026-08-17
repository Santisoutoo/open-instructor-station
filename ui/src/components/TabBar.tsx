import type { KeyboardEvent } from 'react';
import { useAppDispatch, useAppSelector } from '../store';
import { tabSelected } from '../store/uiSlice';
import { TABS } from './tabs';

/**
 * The module tab bar — the shell's navigation. A proper tablist: arrow keys move and
 * select (roving focus), the amber underline marks the active module, and the whole
 * strip scrolls horizontally when a narrow tablet cannot fit eight modules.
 */
export function TabBar() {
  const dispatch = useAppDispatch();
  const activeTab = useAppSelector((state) => state.ui.activeTab);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = TABS.findIndex((tab) => tab.id === activeTab);
    let next: number | null = null;
    if (event.key === 'ArrowRight') {
      next = (index + 1) % TABS.length;
    } else if (event.key === 'ArrowLeft') {
      next = (index - 1 + TABS.length) % TABS.length;
    } else if (event.key === 'Home') {
      next = 0;
    } else if (event.key === 'End') {
      next = TABS.length - 1;
    }
    const target = next === null ? undefined : TABS[next];
    if (target !== undefined) {
      event.preventDefault();
      dispatch(tabSelected(target.id));
      document.getElementById(`tab-${target.id}`)?.focus();
    }
  };

  return (
    <div
      className="tabbar"
      role="tablist"
      aria-label="Instructor station modules"
      onKeyDown={onKeyDown}
    >
      {TABS.map((tab) => {
        const active = tab.id === activeTab;
        return (
          <button
            key={tab.id}
            id={`tab-${tab.id}`}
            className="tabbar__tab"
            role="tab"
            type="button"
            aria-selected={active}
            aria-controls={`tabpanel-${tab.id}`}
            tabIndex={active ? 0 : -1}
            onClick={() => dispatch(tabSelected(tab.id))}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
