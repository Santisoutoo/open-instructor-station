import { describe, expect, it } from 'vitest';
import reducer, {
  demoFeedSet,
  demoFeedToggled,
  drawerToggled,
  initialUiState,
  isTabId,
  tabSelected,
  themeSet,
  themeToggled,
} from './uiSlice';

describe('uiSlice', () => {
  it('starts on the Position tab, dark, drawer closed, demo feed off', () => {
    expect(initialUiState).toEqual({
      activeTab: 'position',
      visitedTabs: ['position'],
      theme: 'dark',
      drawerOpen: false,
      demoFeed: false,
    });
  });

  it('selects tabs and remembers every tab visited once', () => {
    const weather = reducer(initialUiState, tabSelected('weather'));
    expect(weather.activeTab).toBe('weather');
    expect(weather.visitedTabs).toEqual(['position', 'weather']);

    const backAndForth = reducer(
      reducer(weather, tabSelected('position')),
      tabSelected('weather'),
    );
    expect(backAndForth.visitedTabs).toEqual(['position', 'weather']);
  });

  it('toggles the theme both ways and accepts an explicit set', () => {
    const light = reducer(initialUiState, themeToggled());
    expect(light.theme).toBe('light');
    expect(reducer(light, themeToggled()).theme).toBe('dark');
    expect(reducer(light, themeSet('dark')).theme).toBe('dark');
  });

  it('toggles the drawer and the demo feed', () => {
    const open = reducer(initialUiState, drawerToggled());
    expect(open.drawerOpen).toBe(true);
    const demoOn = reducer(open, demoFeedToggled());
    expect(demoOn.demoFeed).toBe(true);
    expect(reducer(demoOn, demoFeedSet(false)).demoFeed).toBe(false);
  });

  it('recognises exactly the nine tab ids', () => {
    for (const id of [
      'position',
      'scenarios',
      'weather',
      'failures',
      'fuel-payload',
      'map',
      'aircraft',
      'landing',
      'traffic',
    ]) {
      expect(isTabId(id)).toBe(true);
    }
    expect(isTabId('settings')).toBe(false);
    expect(isTabId('')).toBe(false);
    expect(isTabId(7)).toBe(false);
  });
});
