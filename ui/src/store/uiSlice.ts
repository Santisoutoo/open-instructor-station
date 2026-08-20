import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

/**
 * The closed set of module tabs. One entry per manager the shell can show; the tab
 * registry in `components/tabs.ts` maps each id to its label and panel module.
 */
export const TAB_IDS = [
  'position',
  'scenarios',
  'weather',
  'failures',
  'fuel-payload',
  'profiles',
  'map',
  'aircraft',
  'landing',
  'traffic',
  'pushback',
] as const;

export type TabId = (typeof TAB_IDS)[number];

export function isTabId(value: unknown): value is TabId {
  return typeof value === 'string' && (TAB_IDS as readonly string[]).includes(value);
}

export type ThemeName = 'dark' | 'light';

export interface UiState {
  /** Which module tab is showing. Mirrored into the URL hash by uiSync. */
  activeTab: TabId;
  /**
   * Every tab opened so far this session, in first-visit order. The shell uses this to
   * keep `keepMounted` panels (the map) alive after their first visit.
   */
  visitedTabs: TabId[];
  /** Dark is the default — sim rooms are dim. Persisted by uiSync. */
  theme: ThemeName;
  /** The telemetry/capabilities context drawer on the right edge. */
  drawerOpen: boolean;
  /**
   * The deterministic demo telemetry feed. Only ever a stand-in: the real WebSocket
   * always wins (`useMockTelemetryFeed` is inert while the sim link is connected), and
   * the status bar shows a persistent "Demo data" chip whenever it is what the screens
   * are showing.
   */
  demoFeed: boolean;
}

export const initialUiState: UiState = {
  activeTab: 'position',
  visitedTabs: ['position'],
  theme: 'dark',
  drawerOpen: false,
  demoFeed: false,
};

const uiSlice = createSlice({
  name: 'ui',
  initialState: initialUiState,
  reducers: {
    tabSelected(state, action: PayloadAction<TabId>) {
      state.activeTab = action.payload;
      if (!state.visitedTabs.includes(action.payload)) {
        state.visitedTabs.push(action.payload);
      }
    },
    themeSet(state, action: PayloadAction<ThemeName>) {
      state.theme = action.payload;
    },
    themeToggled(state) {
      state.theme = state.theme === 'dark' ? 'light' : 'dark';
    },
    drawerToggled(state) {
      state.drawerOpen = !state.drawerOpen;
    },
    demoFeedSet(state, action: PayloadAction<boolean>) {
      state.demoFeed = action.payload;
    },
    demoFeedToggled(state) {
      state.demoFeed = !state.demoFeed;
    },
  },
});

export const {
  tabSelected,
  themeSet,
  themeToggled,
  drawerToggled,
  demoFeedSet,
  demoFeedToggled,
} = uiSlice.actions;

export default uiSlice.reducer;
