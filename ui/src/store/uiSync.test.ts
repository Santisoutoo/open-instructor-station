import { describe, expect, it } from 'vitest';
import { tabFromHash } from './uiSync';

describe('tabFromHash', () => {
  it('reads the shell hash forms', () => {
    expect(tabFromHash('#/weather')).toBe('weather');
    expect(tabFromHash('#/landing')).toBe('landing');
    expect(tabFromHash('#position')).toBe('position');
  });

  it('rejects anything that is not a module tab', () => {
    expect(tabFromHash('')).toBeNull();
    expect(tabFromHash('#/')).toBeNull();
    expect(tabFromHash('#/settings')).toBeNull();
    expect(tabFromHash('#/WEATHER')).toBeNull();
  });
});
