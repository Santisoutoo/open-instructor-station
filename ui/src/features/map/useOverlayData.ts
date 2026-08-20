/**
 * Viewport-driven overlay data (instructor-map.md §7.5): what is near the map's current
 * view, fetched debounced and zoom-gated, cached by RTK Query on its own params.
 *
 * The viewport lives in **local state**, never in Redux — it changes on every pan
 * frame, and the store's cross-component visibility buys nothing here (the same rule
 * as the MapLibre instance itself). Only this hook, `useMapOverlays` and `overlays.ts`
 * know the thresholds and radii exist; the panel component does not.
 *
 * The zoom thresholds and limits are first guesses, not measurements — flagged as
 * instructor-map.md §10.5, pending a tuning pass against a real install.
 */

import { type Map as MapLibreMap } from 'maplibre-gl';
import { skipToken } from '@reduxjs/toolkit/query';
import { useEffect, useState } from 'react';
import { instructorApi } from '../../api/instructorApi';
import type { AirportSummary, Fix, Navaid, Runway } from '../../api/models';
import { useAppDispatch } from '../../store';
import {
  useGetAirportsNearQuery,
  useGetFixesNearQuery,
  useGetNavaidsNearQuery,
} from './mapApi';
import { distanceNm, type LatLon } from './measure';

/** Below this zoom, no overlay data is fetched at all. */
export const AIRPORT_MIN_ZOOM = 9;

/** Runway rectangles and ILS feathers appear from here. */
export const RUNWAY_MIN_ZOOM = 10;

/** Fixes are far denser than navaids; drawing them any earlier is a starfield. */
export const FIXES_MIN_ZOOM = 11;

/** A pan is not a request: quiet time after `moveend` before the viewport updates. */
const MOVE_DEBOUNCE_MS = 400;

/** Runways are one request per airport; cap how many airports in view pay it. */
const RUNWAY_AIRPORT_LIMIT = 8;

/** Server-side bound on `radius_nm` (`Query(le=1000)`), respected here. */
const MAX_RADIUS_NM = 1000;

interface Viewport {
  centre: LatLon;
  zoom: number;
  radiusNm: number;
}

export interface OverlayData {
  airports: AirportSummary[];
  runways: Runway[];
  navaids: Navaid[];
  fixes: Fix[];
}

const NO_AIRPORTS: AirportSummary[] = [];
const NO_RUNWAYS: Runway[] = [];
const NO_NAVAIDS: Navaid[] = [];
const NO_FIXES: Fix[] = [];

function readViewport(map: MapLibreMap): Viewport {
  const centre = map.getCenter();
  const bounds = map.getBounds();
  const sw = bounds.getSouthWest();
  const ne = bounds.getNorthEast();
  const diagonalNm = distanceNm(
    { lat: sw.lat, lon: sw.lng },
    { lat: ne.lat, lon: ne.lng },
  );
  return {
    centre: { lat: centre.lat, lon: centre.lng },
    zoom: map.getZoom(),
    radiusNm: Math.min(MAX_RADIUS_NM, Math.max(1, diagonalNm / 2)),
  };
}

/**
 * What the map should draw around its current viewport. Pass `null` (no map yet, or
 * navdata not ready) and the hook idles: every query is skipped, every list empty.
 */
export function useOverlayData(map: MapLibreMap | null): OverlayData {
  const dispatch = useAppDispatch();

  // The viewport is remembered together with the map it was read from, so a stale
  // reading can never outlive its map: on a map change the derived value below is
  // `null` until the new map's own first read lands. No reset-in-effect needed.
  const [reading, setReading] = useState<{ map: MapLibreMap; view: Viewport } | null>(
    null,
  );
  const viewport = reading !== null && reading.map === map ? reading.view : null;

  // Track the viewport on a debounced `moveend` — not on every `move` frame. The
  // initial read is deferred a tick for the same reason the debounce exists at all:
  // an effect body must not set state synchronously.
  useEffect(() => {
    if (map === null) {
      return;
    }
    const update = (): void => {
      setReading({ map, view: readViewport(map) });
    };
    let handle: number = window.setTimeout(update, 0);
    const onMoveEnd = (): void => {
      window.clearTimeout(handle);
      handle = window.setTimeout(update, MOVE_DEBOUNCE_MS);
    };
    map.on('moveend', onMoveEnd);
    return () => {
      window.clearTimeout(handle);
      map.off('moveend', onMoveEnd);
    };
  }, [map]);

  const nearArgs =
    viewport !== null && viewport.zoom >= AIRPORT_MIN_ZOOM
      ? {
          lat: viewport.centre.lat,
          lon: viewport.centre.lon,
          radiusNm: viewport.radiusNm,
        }
      : null;

  const { data: airports } = useGetAirportsNearQuery(nearArgs ?? skipToken);
  const { data: navaids } = useGetNavaidsNearQuery(nearArgs ?? skipToken);
  const { data: fixes } = useGetFixesNearQuery(
    viewport !== null && viewport.zoom >= FIXES_MIN_ZOOM && nearArgs !== null
      ? nearArgs
      : skipToken,
  );

  // Runways: one existing `getRunways` cache entry per airport in view. Started
  // imperatively because the airport count varies; RTK Query still de-duplicates and
  // caches per ICAO, so panning back over seen ground re-uses the cache. The fetched
  // list is *derived* to empty when runways are not wanted (zoom-out, map gone) — the
  // effect never resets state, it only reports what it fetched.
  const [fetchedRunways, setFetchedRunways] = useState<Runway[]>(NO_RUNWAYS);
  const runwaysWanted =
    viewport !== null && viewport.zoom >= RUNWAY_MIN_ZOOM ? (airports ?? null) : null;
  useEffect(() => {
    if (runwaysWanted === null || runwaysWanted.length === 0) {
      return;
    }
    let cancelled = false;
    const subscriptions = runwaysWanted
      .slice(0, RUNWAY_AIRPORT_LIMIT)
      .map((airport) =>
        dispatch(instructorApi.endpoints.getRunways.initiate(airport.icao)),
      );
    void Promise.all(
      subscriptions.map((subscription) =>
        subscription.unwrap().catch(() => NO_RUNWAYS),
      ),
    ).then((lists) => {
      if (!cancelled) {
        setFetchedRunways(lists.flat());
      }
    });
    return () => {
      cancelled = true;
      for (const subscription of subscriptions) {
        subscription.unsubscribe();
      }
    };
  }, [dispatch, runwaysWanted]);

  return {
    airports: airports ?? NO_AIRPORTS,
    runways:
      runwaysWanted === null || runwaysWanted.length === 0 ? NO_RUNWAYS : fetchedRunways,
    navaids: navaids ?? NO_NAVAIDS,
    fixes: fixes ?? NO_FIXES,
  };
}
