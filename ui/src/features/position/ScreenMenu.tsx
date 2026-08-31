import type { RefObject } from 'react';
import { TABS } from '../../components/tabs';
import { useAppDispatch, useAppSelector } from '../../store';
import { tabSelected } from '../../store/uiSlice';
import { Popover } from './Popover';
import { screenMenuToggled } from './positionDesignSlice';

/** The header's screen-menu popover: every module tab, one click away. */
export function ScreenMenu({ triggerRef }: { readonly triggerRef: RefObject<HTMLElement | null> }) {
  const dispatch = useAppDispatch();
  const open = useAppSelector((state) => state.positionDesign.screenMenuOpen);

  return (
    <Popover
      id="pos-screen-menu"
      open={open}
      onClose={() => {
        dispatch(screenMenuToggled());
      }}
      triggerRef={triggerRef}
      className="pos-popover pos-screenmenu"
    >
      <ul className="pos-screenmenu__list" role="menu" aria-label="Modules">
        {TABS.map((tab) => (
          <li key={tab.id} role="none">
            <button
              type="button"
              role="menuitem"
              className="pos-screenmenu__item"
              onClick={() => {
                dispatch(tabSelected(tab.id));
                dispatch(screenMenuToggled());
              }}
            >
              {tab.label}
            </button>
          </li>
        ))}
      </ul>
    </Popover>
  );
}
