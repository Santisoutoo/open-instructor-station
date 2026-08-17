/**
 * What map gestures mean: a click by the armed mode, a drag breaking follow.
 *
 * The mode is read from the store *inside* the handlers rather than closed over, so
 * the click listener is attached once per map and never chases the mode through
 * re-subscription.
 */

import { type Map as MapLibreMap, type MapMouseEvent } from 'maplibre-gl';
import { useEffect } from 'react';
import { useAppDispatch, useAppStore } from '../../store';
import { followToggled, measurePointAdded, repositionStaged } from './mapSlice';

export function useMapInteractions(map: MapLibreMap | null): void {
  const store = useAppStore();
  const dispatch = useAppDispatch();

  useEffect(() => {
    if (map === null) {
      return;
    }
    const onClick = (event: MapMouseEvent): void => {
      const { mode } = store.getState().map;
      const point = { lat: event.lngLat.lat, lon: event.lngLat.lng };
      if (mode === 'measure') {
        dispatch(measurePointAdded(point));
      } else if (mode === 'reposition') {
        dispatch(repositionStaged(point));
      }
    };
    // Dragging the map away is how an instructor says "stop following".
    const onDragStart = (): void => {
      if (store.getState().map.follow) {
        dispatch(followToggled());
      }
    };
    map.on('click', onClick);
    map.on('dragstart', onDragStart);
    return () => {
      map.off('click', onClick);
      map.off('dragstart', onDragStart);
    };
  }, [map, store, dispatch]);
}
