/**
 * jsdom stand-in for `@react-three/fiber` and `@react-three/drei`, for
 * `vi.mock('@react-three/fiber', …)` / `vi.mock('@react-three/drei', …)` in `ProcedureDiagram3D`
 * tests. Mirrors `maplibreStub.ts`'s role — jsdom has no WebGL — with a different mechanism.
 *
 * `Canvas` is stubbed to a passthrough that renders `children` through React's own reconciler,
 * **not** the r3f custom renderer. That is the whole trick: everything r3f normally mounts
 * onto Three.js objects (`<mesh>`, `<group>`, `<sphereGeometry>`, `<meshBasicMaterial>`) is
 * just a lowercase JSX tag name, so once it is inside the stubbed `Canvas` it renders as an
 * ordinary, unrecognized host element, and its `onClick`/`onPointerOver`/`onPointerOut` props
 * wire through React DOM's real synthetic-event system exactly like any other host component.
 * None of those tags need a stub of their own.
 *
 * Only `OrbitControls`, `Line` and `Html` (imported from `@react-three/drei`) need one, because
 * they are real components with real (non-Three-primitive) internals that would themselves try
 * to reach into a WebGL context.
 *
 * Written with `createElement` rather than JSX: this file is `.ts`, not `.tsx` — matching
 * `ProcedureDiagram3D.test.tsx`'s own import path for it — and a `.ts` file cannot contain JSX
 * syntax (TypeScript only parses `<Tag>` as JSX inside a `.tsx` file; in a `.ts` file it is a
 * type-assertion token and fails to parse). The two are otherwise the exact same tree.
 *
 * Use a real Object3D property (`name`) as the query hook on `<mesh>`/`<group>` elements —
 * `data-testid` on an r3f element gets misinterpreted at real runtime as a nested prop path
 * (`data-testid` looks like `data.testid` to r3f's dot-path prop resolution), so it is never
 * used there even though the stub itself would not object to it.
 */

import { createElement, type ReactNode } from 'react';

/** Keeps primitive props (and arrays of them, e.g. a Vec3 `target`) as DOM attributes on the
 *  stub elements; functions, refs and other objects are dropped rather than stringified into
 *  `"[object Object]"`. */
function toStubAttrs(props: Record<string, unknown>): Record<string, string> {
  const attrs: Record<string, string> = {};
  for (const [key, value] of Object.entries(props)) {
    if (key === 'children') {
      continue;
    }
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      attrs[key] = String(value);
    } else if (Array.isArray(value)) {
      attrs[key] = JSON.stringify(value);
    }
  }
  return attrs;
}

export const threeFiberStub = {
  Canvas: ({ children }: { children?: ReactNode }) => children,
  useThree: () => ({}),
  useFrame: () => {
    // Intentionally empty: nothing in #176 drives per-frame updates.
  },
};

export const threeDreiStub = {
  OrbitControls: (props: Record<string, unknown>) =>
    createElement('orbit-controls-stub', toStubAttrs(props)),
  Line: ({ points }: { points: readonly unknown[] }) =>
    createElement('line-stub', { 'data-point-count': points.length }),
  Html: ({ children }: { children?: ReactNode }) => createElement('html-stub', null, children),
};
