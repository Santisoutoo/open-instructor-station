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
 * Only `OrbitControls`, `Line`, `Html` and (since #177) `Billboard` — imported from
 * `@react-three/drei` — need one, because they are real components with real (non-Three-
 * primitive) internals that would themselves try to reach into a WebGL context.
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
 *
 * **`OrbitControls` instance registry (#177).** `three` itself is real in tests — only
 * `@react-three/fiber`/`@react-three/drei` are mocked — so this stub exposes a real
 * `THREE.Vector3`-backed handle (`target`, `object.position`, `update`) through the forwarded
 * ref, letting a test drive the camera-reset button and then read back the *same* ref instance
 * `ProcedureDiagram3D`'s `controlsRef` holds — mirroring `maplibreStub.ts`'s `Map.created`
 * array. Unlike #176's stub, this registry is stateful across renders within a test, so it
 * needs clearing between tests: `resetThreeStub()` is registered in `setup.ts`'s shared
 * `afterEach`.
 */

import {
  createElement,
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  type ReactNode,
} from 'react';
import { Vector3 } from 'three';

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
    // Intentionally empty: nothing in #176/#177 drives per-frame updates.
  },
};

/** What a test can read/drive through `controlsRef.current` — real `THREE.Vector3`s so
 *  `.copy()`/`.update()` behave exactly as drei's real ref surface does. */
export interface OrbitControlsStubHandle {
  readonly target: Vector3;
  readonly object: { readonly position: Vector3 };
  update: () => void;
  /** How many times `update()` has been called — a plain counter stands in for a spy so this
   *  infra file has no dependency on vitest's `vi`. */
  updateCallCount: number;
}

/** Every `OrbitControls` stub instance constructed since the last `resetThreeStub()`. */
export const orbitControlsInstances: OrbitControlsStubHandle[] = [];

const OrbitControlsStub = forwardRef<OrbitControlsStubHandle, Record<string, unknown>>(
  function OrbitControlsStub(props, ref) {
    const handleRef = useRef<OrbitControlsStubHandle | null>(null);
    if (handleRef.current === null) {
      const handle = {
        target: new Vector3(),
        object: { position: new Vector3() },
        update: () => {},
        updateCallCount: 0,
      } as OrbitControlsStubHandle;
      handle.update = () => {
        handle.updateCallCount += 1;
      };
      handleRef.current = handle;
    }
    const handle = handleRef.current;

    useEffect(() => {
      orbitControlsInstances.push(handle);
    }, [handle]);

    useImperativeHandle(ref, () => handle, [handle]);

    return createElement('orbit-controls-stub', toStubAttrs(props));
  },
);

export const threeDreiStub = {
  OrbitControls: OrbitControlsStub,
  Line: ({ points }: { points: readonly unknown[] }) =>
    createElement('line-stub', { 'data-point-count': points.length }),
  Html: ({ children }: { children?: ReactNode }) => createElement('html-stub', null, children),
  Billboard: ({ children }: { children?: ReactNode }) =>
    createElement('billboard-stub', null, children),
};

/** Clears the `OrbitControls` instance registry. Call in `afterEach` — see `setup.ts`. */
export function resetThreeStub(): void {
  orbitControlsInstances.length = 0;
}
