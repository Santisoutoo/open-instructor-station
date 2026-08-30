/**
 * `usePosThemePalette` in jsdom, which has neither `position.css` loaded (so
 * `getComputedStyle(...).getPropertyValue('--pos-*')` always returns `""`) nor a 2D canvas
 * context (`getContext('2d')` returns `null` without the optional `canvas` npm package) — both
 * are the hook's own documented fallback paths, not error cases, so this test exercises exactly
 * that: every consumer gets a deterministic, defined palette in the test environment, with no
 * dependency on jsdom ever gaining real CSS/canvas support.
 */

import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { usePosThemePalette } from './usePosThemePalette';

describe('usePosThemePalette', () => {
  it('falls back to a defined palette when the scope element has no computed tokens', () => {
    const scopeElement = document.createElement('div');
    document.body.appendChild(scopeElement);
    const scopeRef = { current: scopeElement };

    const { result } = renderHook(() => usePosThemePalette(scopeRef));

    expect(result.current.hair).toMatch(/^#[0-9a-f]{6}$/i);
    expect(result.current.accent).toMatch(/^#[0-9a-f]{6}$/i);
    expect(result.current.caution).toMatch(/^#[0-9a-f]{6}$/i);
  });

  it('falls back to a defined palette when the scope ref has no element yet', () => {
    const scopeRef = { current: null };

    const { result } = renderHook(() => usePosThemePalette(scopeRef));

    expect(result.current.hair).toMatch(/^#[0-9a-f]{6}$/i);
    expect(result.current.accent).toMatch(/^#[0-9a-f]{6}$/i);
    expect(result.current.caution).toMatch(/^#[0-9a-f]{6}$/i);
  });
});
