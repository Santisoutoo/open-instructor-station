/**
 * Reads `--pos-hair`/`--pos-accent`/`--pos-caution` off the DOM for use in WebGL materials,
 * which cannot consult a CSS custom property directly (#177).
 *
 * **Read location — a deliberate departure from an earlier draft of this design, which said
 * `getComputedStyle(document.documentElement)`.** `position.css` only declares these three
 * tokens under `.pos` and `[data-theme='light'] .pos` (see `PositionPanel.tsx`'s
 * `<div className="pos">`) — never at `:root`. A CSS custom property is visible only to the
 * element it is declared on and that element's *descendants*; `<html>` is an *ancestor* of the
 * `.pos` div, so reading it there always returns `""`. `scopeRef` must therefore point at a DOM
 * node inside the `.pos` subtree — in practice, this view's own container. The theme *toggle*
 * itself genuinely is on `<html>` (`data-theme`, maintained by `uiSync`), so the
 * `MutationObserver` below still watches `document.documentElement` — only the palette *read*
 * moves to `scopeRef`.
 *
 * **oklch conversion.** The tokens are `oklch()` strings. `three@0.185.1`'s own
 * `Color.setStyle` (`node_modules/three/src/math/Color.js`) only parses `rgb()`/`hsl()`/hex/
 * named forms — its `oklch` support does not exist in this pinned version — so a
 * `meshBasicMaterial`'s `color` prop cannot take the token string as-is. Converted instead via
 * an offscreen `<canvas>` 2D context round-trip: the canvas *can* resolve any CSS color the
 * browser understands (including `oklch()`), and reading a pixel back out of it yields plain
 * RGB, `#rrggbb`, which `THREE.Color` always accepts.
 *
 * jsdom (the test environment) has no `position.css` loaded and implements `<canvas>` without a
 * 2D context, so both `getPropertyValue` and `getContext('2d')` come back empty/`null` in every
 * component test — the expected path there, not an error one. `FALLBACK_PALETTE` (this file's
 * own copy of #176's hard-coded `PATH_COLOR`/`COMPRESSED_COLOR` and `position.css`'s dark-theme
 * `--pos-hair`) covers that case and the brief window before the first live read on mount.
 */

import { useEffect, useState, type RefObject } from 'react';

export interface PosThemePalette {
  readonly hair: string;
  readonly accent: string;
  readonly caution: string;
}

const FALLBACK_PALETTE: PosThemePalette = {
  hair: '#3a4046',
  accent: '#3ecf7a',
  caution: '#e0a83c',
};

/**
 * Resolves a CSS color string — including one three.js's own `Color.setStyle` cannot parse,
 * such as `oklch()` — to `#rrggbb` via a 1x1 offscreen canvas. Returns `null` for an empty
 * token or an environment with no 2D canvas context (jsdom), rather than throwing.
 */
function resolveCssColor(cssColor: string): string | null {
  if (cssColor === '') {
    return null;
  }
  const canvas = document.createElement('canvas');
  canvas.width = 1;
  canvas.height = 1;
  const ctx = canvas.getContext('2d');
  if (ctx === null) {
    return null;
  }
  ctx.fillStyle = cssColor;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
  return `#${[r ?? 0, g ?? 0, b ?? 0].map((c) => c.toString(16).padStart(2, '0')).join('')}`;
}

function readPalette(scopeElement: HTMLElement | null): PosThemePalette {
  if (scopeElement === null) {
    return FALLBACK_PALETTE;
  }
  const computed = getComputedStyle(scopeElement);
  const hair = resolveCssColor(computed.getPropertyValue('--pos-hair').trim());
  const accent = resolveCssColor(computed.getPropertyValue('--pos-accent').trim());
  const caution = resolveCssColor(computed.getPropertyValue('--pos-caution').trim());
  return {
    hair: hair ?? FALLBACK_PALETTE.hair,
    accent: accent ?? FALLBACK_PALETTE.accent,
    caution: caution ?? FALLBACK_PALETTE.caution,
  };
}

/**
 * `scopeRef` must point at an element inside the `.pos` subtree (see this file's own docstring
 * for why `document.documentElement` cannot be used here). Re-reads on every `data-theme`
 * mutation on `<html>`, cleaned up on unmount.
 */
export function usePosThemePalette(scopeRef: RefObject<HTMLElement | null>): PosThemePalette {
  const [palette, setPalette] = useState<PosThemePalette>(FALLBACK_PALETTE);

  useEffect(() => {
    setPalette(readPalette(scopeRef.current));

    const observer = new MutationObserver(() => {
      setPalette(readPalette(scopeRef.current));
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    });

    return () => {
      observer.disconnect();
    };
  }, [scopeRef]);

  return palette;
}
