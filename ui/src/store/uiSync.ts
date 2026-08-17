/**
 * Two-way sync between the ui slice and the world outside the store: the URL hash
 * (`#/weather`), the `data-theme` attribute + its localStorage key, and the demo-feed
 * preference. Called once from `main.tsx`; nothing else in the app touches these.
 *
 * This is the whole "router": deep-linking a tab is the only navigation feature the
 * shell needs, and a hash listener buys it for zero dependencies.
 */

import type { AppStore } from './index';
import { demoFeedSet, isTabId, tabSelected, themeSet, type TabId } from './uiSlice';

export const THEME_STORAGE_KEY = 'ois-theme';
export const DEMO_FEED_STORAGE_KEY = 'ois-demo-feed';

/** `#/weather` → `weather`; anything unrecognised → `null`. */
export function tabFromHash(hash: string): TabId | null {
  const candidate = hash.replace(/^#\/?/, '');
  return isTabId(candidate) ? candidate : null;
}

function readStorage(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage may be unavailable (private mode); the app still works, unpersisted */
  }
}

/** The theme-color meta must follow the theme or the browser chrome clashes with it. */
const THEME_COLOR: Record<'dark' | 'light', string> = {
  dark: '#16140f',
  light: '#f4f2ee',
};

export function initUiSync(store: AppStore): void {
  // --- boot: pull the outside world into the store ---------------------------------
  const bootTab = tabFromHash(window.location.hash);
  if (bootTab !== null) {
    store.dispatch(tabSelected(bootTab));
  }

  // The inline script in index.html already resolved the theme before first paint;
  // adopt its verdict rather than re-deriving it.
  const bootTheme = document.documentElement.dataset.theme;
  if (bootTheme === 'light' || bootTheme === 'dark') {
    store.dispatch(themeSet(bootTheme));
  }

  // Demo feed: explicit choice wins; otherwise on in dev builds (there is usually no
  // simulator behind `npm run dev`, and a dead screen demos nothing).
  const storedDemo = readStorage(DEMO_FEED_STORAGE_KEY);
  const demoFeed = storedDemo === null ? import.meta.env.DEV : storedDemo === 'on';
  store.dispatch(demoFeedSet(demoFeed));

  // --- back arrows and hand-edited hashes ------------------------------------------
  window.addEventListener('hashchange', () => {
    const tab = tabFromHash(window.location.hash);
    if (tab !== null && tab !== store.getState().ui.activeTab) {
      store.dispatch(tabSelected(tab));
    }
  });

  // --- store → world ---------------------------------------------------------------
  let last = store.getState().ui;
  store.subscribe(() => {
    const next = store.getState().ui;
    if (next === last) {
      return;
    }

    if (next.activeTab !== last.activeTab) {
      history.replaceState(null, '', `#/${next.activeTab}`);
    }
    if (next.theme !== last.theme) {
      document.documentElement.dataset.theme = next.theme;
      writeStorage(THEME_STORAGE_KEY, next.theme);
      document
        .querySelector('meta[name="theme-color"]')
        ?.setAttribute('content', THEME_COLOR[next.theme]);
    }
    if (next.demoFeed !== last.demoFeed) {
      writeStorage(DEMO_FEED_STORAGE_KEY, next.demoFeed ? 'on' : 'off');
    }

    last = next;
  });

  // Make the boot tab visible in the URL even when nothing was in the hash.
  history.replaceState(null, '', `#/${store.getState().ui.activeTab}`);
}
