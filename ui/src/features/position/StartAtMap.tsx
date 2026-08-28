/**
 * The Start-at popover's map: replaces the hand-drawn `AirportDiagram.tsx` with the same
 * MapLibre stack the Instructor Map tab uses (`features/map/`) — OSM tiles, the airport's
 * real pavement footprint, and a clickable marker per runway threshold and parking stand.
 * Pure props in, no direct store access, same posture as `MapPanel.tsx`/hook split: the
 * imperative map lifecycle lives in `useMapLibre`, the marker lifecycle in
 * `useStartAtMarkers`, and this component is layout.
 *
 * `Popover.tsx` renders `null` outright when closed and mounts its children only once
 * `open` flips `true`, at the popover's **final** grid-determined size — there is no
 * width/opacity transition to race, so `maplibre-gl`'s `Map` constructor measures the
 * final container size on the very first paint and no explicit resize kick is needed at
 * open-time. If a future change ever wraps this popover in an opening transition, THAT
 * change must add a `requestAnimationFrame` + `map.resize()` kick here.
 *
 * Consequence of `Popover` unmounting on close: `useMapLibre`'s mount effect tears the map
 * down on every close and builds a fresh one on every re-open. Accepted as the boring
 * option — the browser's tile cache makes a re-open cheap, and keeping the instance alive
 * across close would mean lifting it out of `Popover`'s conditional render, which is not
 * worth the structural change for one map re-init.
 */

import type { ParkingStand, Runway } from '../../api/models';
import { useMapLibre } from '../map/useMapLibre';
import { useStartAtMarkers } from './useStartAtMarkers';

export function StartAtMap({
  runways,
  stands,
  selectedRunway,
  selectedStand,
  onSelectRunway,
  onSelectStand,
  centerHint,
}: {
  readonly runways: readonly Runway[];
  readonly stands: readonly ParkingStand[];
  readonly selectedRunway: string | null;
  readonly selectedStand: string | null;
  readonly onSelectRunway: (ident: string) => void;
  readonly onSelectStand: (name: string) => void;
  /** The loaded airport's own position, so the first frame is already near it instead of
   * flashing Madrid (`MAP_HOME`) before the fit-to-content effect corrects it. */
  readonly centerHint: { readonly latitude: number; readonly longitude: number } | null;
}) {
  const { containerRef, map } = useMapLibre(
    centerHint === null
      ? {}
      : { center: [centerHint.longitude, centerHint.latitude], zoom: 13 },
  );
  useStartAtMarkers(
    map,
    runways,
    stands,
    selectedRunway,
    selectedStand,
    onSelectRunway,
    onSelectStand,
  );

  return <div ref={containerRef} className="pos-startat__map" />;
}
