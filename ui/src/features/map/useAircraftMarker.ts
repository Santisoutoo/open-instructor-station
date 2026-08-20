/**
 * The live aircraft on the map: a rotated glyph Marker, the follow camera, the
 * trail append — and the drag handle that stages a reposition.
 *
 * Driven by a `store.subscribe` inside one mount effect rather than by a selector
 * effect: the marker moves at the ~4 Hz telemetry cadence and appending to the trail
 * dispatches, and doing that from a bare effect reacting to state is exactly what the
 * hooks lint (rightly) objects to. The subscription callback is an event handler in
 * spirit — and the `receivedAt` guard makes its own dispatch a no-op re-entry instead
 * of a loop.
 *
 * Dragging is hard rule 3 applied at the DOM level (map design D8): the marker is
 * simply not draggable unless `commitGate` — imported from the Position Manager,
 * never reimplemented — is open, so an adapter that cannot reposition offers no
 * handle to pull. A finished drag stages through the *existing* `repositionStaged`
 * action; committing is the staging bar's job, never this hook's.
 */

import { Marker, type Map as MapLibreMap } from 'maplibre-gl';
import { useEffect } from 'react';
import { useGetCapabilitiesQuery } from '../../api/instructorApi';
import { useAppDispatch, useAppStore } from '../../store';
import { commitGate } from '../position/gate';
import { repositionStaged, trailPointAppended } from './mapSlice';

/** Points north at rotation 0; `rotationAlignment: 'map'` turns it with the heading. */
const AIRCRAFT_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="30" height="30" aria-hidden="true">' +
  '<path d="M12 1.5 L14 9 L22 12.5 L22 14.5 L13.7 12.6 L13.3 17.6 L16 19.8 L16 21.5 ' +
  'L12 20.2 L8 21.5 L8 19.8 L10.7 17.6 L10.3 12.6 L2 14.5 L2 12.5 L10 9 Z" ' +
  'fill="#ece6d9" stroke="#16140f" stroke-width="1.2" stroke-linejoin="round"/></svg>';

export function useAircraftMarker(map: MapLibreMap | null): void {
  const store = useAppStore();
  const dispatch = useAppDispatch();
  const { data: capabilities, isError: capabilitiesFailed } = useGetCapabilitiesQuery();
  // Draggability is a constructor option, so the effect keys on the gate's verdict:
  // the marker is rebuilt when the capabilities answer arrives — once, in practice.
  const draggable = commitGate(capabilities, capabilitiesFailed).open;

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
      draggable,
    });
    let added = false;
    let lastReceivedAt: number | null = null;
    let lastFollow = false;
    // While the instructor holds the marker, telemetry must not snap it back to the
    // aircraft's real position mid-gesture — the sync pauses until the drag ends.
    let dragging = false;

    marker.on('dragstart', () => {
      dragging = true;
    });
    marker.on('dragend', () => {
      dragging = false;
      const { lat, lng } = marker.getLngLat();
      dispatch(repositionStaged({ lat, lon: lng }));
    });

    const sync = (): void => {
      if (dragging) {
        return;
      }
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
  }, [map, store, dispatch, draggable]);
}
