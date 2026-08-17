/**
 * The live aircraft on the map: a rotated glyph Marker, the follow camera, and the
 * trail append.
 *
 * Driven by a `store.subscribe` inside one mount effect rather than by a selector
 * effect: the marker moves at the ~4 Hz telemetry cadence and appending to the trail
 * dispatches, and doing that from a bare effect reacting to state is exactly what the
 * hooks lint (rightly) objects to. The subscription callback is an event handler in
 * spirit — and the `receivedAt` guard makes its own dispatch a no-op re-entry instead
 * of a loop.
 */

import { Marker, type Map as MapLibreMap } from 'maplibre-gl';
import { useEffect } from 'react';
import { useAppDispatch, useAppStore } from '../../store';
import { trailPointAppended } from './mapSlice';

/** Points north at rotation 0; `rotationAlignment: 'map'` turns it with the heading. */
const AIRCRAFT_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="30" height="30" aria-hidden="true">' +
  '<path d="M12 1.5 L14 9 L22 12.5 L22 14.5 L13.7 12.6 L13.3 17.6 L16 19.8 L16 21.5 ' +
  'L12 20.2 L8 21.5 L8 19.8 L10.7 17.6 L10.3 12.6 L2 14.5 L2 12.5 L10 9 Z" ' +
  'fill="#ece6d9" stroke="#16140f" stroke-width="1.2" stroke-linejoin="round"/></svg>';

export function useAircraftMarker(map: MapLibreMap | null): void {
  const store = useAppStore();
  const dispatch = useAppDispatch();

  useEffect(() => {
    if (map === null) {
      return;
    }
    const element = document.createElement('div');
    element.className = 'map-aircraft';
    element.innerHTML = AIRCRAFT_SVG;
    const marker = new Marker({
      element,
      rotationAlignment: 'map',
      pitchAlignment: 'map',
    });
    let added = false;
    let lastReceivedAt: number | null = null;
    let lastFollow = false;

    const sync = (): void => {
      const state = store.getState();
      const frame = state.telemetry.latest;
      // Engaging follow recenters immediately, without waiting for the next frame.
      const followEngaged = state.map.follow && !lastFollow;
      lastFollow = state.map.follow;
      if (frame === null) {
        // Telemetry lost: no marker is honest, a frozen one looks live.
        if (added) {
          marker.remove();
          added = false;
        }
        lastReceivedAt = null;
        return;
      }
      const isNewFrame = state.telemetry.receivedAt !== lastReceivedAt;
      if (!isNewFrame && !followEngaged) {
        return;
      }
      marker.setLngLat([frame.longitude, frame.latitude]);
      marker.setRotation(frame.heading_deg);
      if (!added) {
        marker.addTo(map);
        added = true;
      }
      if (isNewFrame) {
        lastReceivedAt = state.telemetry.receivedAt;
        dispatch(trailPointAppended({ lat: frame.latitude, lon: frame.longitude }));
      }
      if (state.map.follow) {
        map.easeTo({ center: [frame.longitude, frame.latitude], duration: 200 });
      }
    };

    sync();
    const unsubscribe = store.subscribe(sync);
    return () => {
      unsubscribe();
      marker.remove();
    };
  }, [map, store, dispatch]);
}
