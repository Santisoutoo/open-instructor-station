/**
 * `useMapLibre`'s own parameterization — added by the Start-at map (issue #155), which is
 * the hook's second consumer and the first thing to actually pass `center`/`zoom`.
 *
 * The one test that matters here is the last one: options must be read once, via a ref,
 * never listed in the mount effect's dependency array — otherwise a fresh options object
 * literal on every re-render (which `StartAtMap` produces on every Redux dispatch) would
 * tear down and rebuild the `maplibre-gl` `Map`, re-fetching every tile.
 */

import { render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Map as StubMap, resetMaplibreStub } from '../../test/maplibreStub';
import { MAP_HOME, MAP_HOME_ZOOM } from './mock';
import { useMapLibre, type MapLibreOptions } from './useMapLibre';

vi.mock('maplibre-gl', () => import('../../test/maplibreStub'));

function Harness({ options }: { options?: MapLibreOptions }) {
  const { containerRef } = useMapLibre(options);
  return <div ref={containerRef} />;
}

afterEach(() => {
  resetMaplibreStub();
  vi.unstubAllGlobals();
});

describe('useMapLibre', () => {
  it('defaults to MAP_HOME and MAP_HOME_ZOOM when no options are given', () => {
    render(<Harness />);

    expect(StubMap.created).toHaveLength(1);
    expect(StubMap.created[0]?.options).toMatchObject({
      center: [MAP_HOME.lon, MAP_HOME.lat],
      zoom: MAP_HOME_ZOOM,
    });
  });

  it('passes an explicit center and zoom straight to the constructor', () => {
    render(<Harness options={{ center: [7.21, 43.65], zoom: 13 }} />);

    expect(StubMap.created[0]?.options).toMatchObject({
      center: [7.21, 43.65],
      zoom: 13,
    });
  });

  it('does not construct a second Map when re-rendered with a fresh options object', () => {
    const { rerender } = render(<Harness options={{ center: [7.21, 43.65], zoom: 13 }} />);
    expect(StubMap.created).toHaveLength(1);

    // A brand-new object literal every time, exactly like a fresh render of StartAtMap.
    rerender(<Harness options={{ center: [7.21, 43.65], zoom: 13 }} />);
    rerender(<Harness options={{ center: [1, 2], zoom: 5 }} />);

    expect(StubMap.created).toHaveLength(1);
  });
});
