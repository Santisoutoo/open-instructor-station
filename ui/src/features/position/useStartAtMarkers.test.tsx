/**
 * The Start-at map's marker wiring, exercised for real through the maplibre stub's
 * registries — modelled directly on `useAircraftMarker.test.tsx`'s `Harness` pattern, which
 * bypasses `useMapLibre`'s `'load'` gate by constructing `new StubMap()` directly and
 * passing it straight into the hook under test.
 *
 * This is the real, non-vacuous proof that a map click behaves exactly like a list click: a
 * full `StartAtPopover` render never gets here, because jsdom's `maplibre-gl` stub never
 * fires `'load'`, so `useMapLibre`'s `map` state never leaves `null` there (see
 * `StartAtPopover.test.tsx`'s comment on the same limitation).
 */

import { fireEvent, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Map as MapLibreMap } from 'maplibre-gl';
import type { ParkingStand, Runway } from '../../api/models';
import {
  Map as StubMap,
  Marker as StubMarker,
  resetMaplibreStub,
} from '../../test/maplibreStub';
import { RUNWAY_04R, RUNWAY_22L, STANDS } from './testFixtures';
import { useStartAtMarkers } from './useStartAtMarkers';

vi.mock('maplibre-gl', () => import('../../test/maplibreStub'));

const RUNWAYS: readonly Runway[] = [RUNWAY_04R, RUNWAY_22L];

function Harness({
  map,
  runways = RUNWAYS,
  stands = STANDS,
  selectedRunway = null,
  selectedStand = null,
  onSelectRunway = () => {},
  onSelectStand = () => {},
}: {
  readonly map: MapLibreMap;
  readonly runways?: readonly Runway[];
  readonly stands?: readonly ParkingStand[];
  readonly selectedRunway?: string | null;
  readonly selectedStand?: string | null;
  readonly onSelectRunway?: (ident: string) => void;
  readonly onSelectStand?: (name: string) => void;
}) {
  useStartAtMarkers(
    map,
    runways,
    stands,
    selectedRunway,
    selectedStand,
    onSelectRunway,
    onSelectStand,
  );
  return null;
}

function elementOf(marker: StubMarker): HTMLElement {
  const element = marker.options.element;
  if (element === undefined) {
    throw new Error('Marker was built without an element');
  }
  return element;
}

function markerLabelled(name: string): HTMLElement {
  const marker = StubMarker.created.find(
    (candidate) => elementOf(candidate).getAttribute('aria-label') === `Stand ${name}`,
  );
  if (marker === undefined) {
    throw new Error(`No marker for stand ${name}`);
  }
  return elementOf(marker);
}

/** `04R` badges as `"04R·ILS"` on its element when the runway has one — match the prefix. */
function markerFor(ident: string): HTMLElement {
  const marker = StubMarker.created.find((candidate) =>
    elementOf(candidate).textContent?.startsWith(ident),
  );
  if (marker === undefined) {
    throw new Error(`No marker for runway ${ident}`);
  }
  return elementOf(marker);
}

afterEach(() => {
  resetMaplibreStub();
  vi.unstubAllGlobals();
});

describe('useStartAtMarkers', () => {
  it('builds one marker per runway end and one per stand', () => {
    const map = new StubMap() as unknown as MapLibreMap;
    render(<Harness map={map} />);

    expect(StubMarker.created).toHaveLength(6);
  });

  it('a click on a stand marker calls onSelectStand with the stand name', () => {
    const map = new StubMap() as unknown as MapLibreMap;
    const onSelectStand = vi.fn();
    render(<Harness map={map} onSelectStand={onSelectStand} />);

    fireEvent.click(markerLabelled('A1'));

    expect(onSelectStand).toHaveBeenCalledWith('A1');
  });

  it('a click on a runway marker calls onSelectRunway with the runway ident', () => {
    const map = new StubMap() as unknown as MapLibreMap;
    const onSelectRunway = vi.fn();
    render(<Harness map={map} onSelectRunway={onSelectRunway} />);

    fireEvent.click(markerFor('04R'));

    expect(onSelectRunway).toHaveBeenCalledWith('04R');
  });

  it('restyles the selected marker without rebuilding the marker set', () => {
    const map = new StubMap() as unknown as MapLibreMap;
    const { rerender } = render(<Harness map={map} />);
    expect(StubMarker.created).toHaveLength(6);

    rerender(<Harness map={map} selectedStand="A1" />);

    expect(markerLabelled('A1')).toHaveAttribute('aria-pressed', 'true');
    expect(StubMarker.created).toHaveLength(6);
  });

  it('rebuilds the marker set when the stands change, removing the old markers', () => {
    const map = new StubMap() as unknown as MapLibreMap;
    const { rerender } = render(<Harness map={map} />);
    const before = [...StubMarker.created];
    const removeSpies = before.map((marker) => vi.spyOn(marker, 'remove'));

    rerender(<Harness map={map} stands={STANDS.slice(0, 1)} />);

    for (const spy of removeSpies) {
      expect(spy).toHaveBeenCalled();
    }
    // 2 runway markers + 1 remaining stand marker survive the rebuild — `Marker.created`
    // itself only ever grows (it is a since-reset accumulator, not a live set), so the
    // rebuilt set is whatever was constructed after `before` was snapshotted.
    const after = StubMarker.created.filter((marker) => !before.includes(marker));
    expect(after).toHaveLength(3);
  });

  it('calls the LATEST onSelectStand after a rerender that changes it without rebuilding markers', () => {
    // Regression for the stale-closure bug: because the marker-build effect deliberately
    // does not rebuild on every render (see effect §2's own comment), a marker's click
    // listener must not keep calling whichever `onSelectStand` closure existed when the
    // marker was built.
    const map = new StubMap() as unknown as MapLibreMap;
    const firstOnSelectStand = vi.fn();
    const { rerender } = render(<Harness map={map} onSelectStand={firstOnSelectStand} />);
    const before = StubMarker.created.length;

    const secondOnSelectStand = vi.fn();
    // An unrelated selection change plus a fresh callback identity — exactly the shape of a
    // re-render caused by e.g. selecting a different runway elsewhere on the screen — must
    // not rebuild the marker set.
    rerender(
      <Harness map={map} onSelectStand={secondOnSelectStand} selectedRunway="04R" />,
    );
    expect(StubMarker.created).toHaveLength(before);

    fireEvent.click(markerLabelled('A1'));

    expect(firstOnSelectStand).not.toHaveBeenCalled();
    expect(secondOnSelectStand).toHaveBeenCalledWith('A1');
  });

  it('calls the LATEST onSelectRunway after a rerender that changes it without rebuilding markers', () => {
    const map = new StubMap() as unknown as MapLibreMap;
    const firstOnSelectRunway = vi.fn();
    const { rerender } = render(<Harness map={map} onSelectRunway={firstOnSelectRunway} />);
    const before = StubMarker.created.length;

    const secondOnSelectRunway = vi.fn();
    rerender(
      <Harness map={map} onSelectRunway={secondOnSelectRunway} selectedStand="A1" />,
    );
    expect(StubMarker.created).toHaveLength(before);

    fireEvent.click(markerFor('04R'));

    expect(firstOnSelectRunway).not.toHaveBeenCalled();
    expect(secondOnSelectRunway).toHaveBeenCalledWith('04R');
  });

  it('adds the pavement source and layer once when the map is non-null', () => {
    const map = new StubMap() as unknown as MapLibreMap;
    const addSource = vi.spyOn(map, 'addSource');
    const addLayer = vi.spyOn(map, 'addLayer');
    const { rerender } = render(<Harness map={map} />);

    rerender(<Harness map={map} runways={[RUNWAY_04R]} />);

    expect(addSource).toHaveBeenCalledTimes(1);
    expect(addLayer).toHaveBeenCalledTimes(1);
  });

  it('builds no markers and never fits bounds when there is nothing to draw', () => {
    const map = new StubMap() as unknown as MapLibreMap;
    const fitBounds = vi.spyOn(map, 'fitBounds');
    render(<Harness map={map} runways={[]} stands={[]} />);

    expect(StubMarker.created).toHaveLength(0);
    expect(fitBounds).not.toHaveBeenCalled();
  });
});
