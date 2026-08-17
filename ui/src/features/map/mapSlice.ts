/**
 * Client state for the Instructor Map — and nothing else.
 *
 * What lives here is what the map *chrome* needs to survive a tab switch and what the
 * tests need to drive without WebGL: which overlays are showing, which interaction
 * mode is armed, the measure points, the staged reposition and the aircraft trail.
 * The MapLibre instance itself is imperative and lives in `useMapLibre`; it *reads*
 * this state, it is never mirrored into it.
 */

import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import type { LatLon } from './measure';

/** The toggleable mock overlays, one key per left-edge button. */
export type MapLayerKey = 'runways' | 'ils' | 'navaids' | 'trail';

/** What a map click means right now. */
export type MapMode = 'pan' | 'measure' | 'reposition';

/**
 * How many trail positions are kept. At the ~4 Hz telemetry feed this is about a
 * minute of flight — enough to see the last turn, cheap enough to rebuild per frame.
 */
export const TRAIL_LIMIT = 240;

export interface MapState {
  layers: Record<MapLayerKey, boolean>;
  /** Recenter on every telemetry frame while engaged. */
  follow: boolean;
  mode: MapMode;
  measureA: LatLon | null;
  measureB: LatLon | null;
  /** A reposition staged by a map click; `null` means no staging bar. */
  staged: LatLon | null;
  /** Recent aircraft positions, oldest first, capped at {@link TRAIL_LIMIT}. */
  trail: LatLon[];
}

export const initialMapState: MapState = {
  layers: { runways: true, ils: true, navaids: true, trail: true },
  follow: false,
  mode: 'pan',
  measureA: null,
  measureB: null,
  staged: null,
  trail: [],
};

const mapSlice = createSlice({
  name: 'map',
  initialState: initialMapState,
  reducers: {
    layerToggled(state, action: PayloadAction<MapLayerKey>) {
      state.layers[action.payload] = !state.layers[action.payload];
    },
    followToggled(state) {
      state.follow = !state.follow;
    },
    /**
     * Arm a mode. Selecting the armed mode again disarms it back to pan — the edge
     * buttons are toggles. Any mode change resets the measure points: entering the
     * measure mode starts a fresh measurement, leaving it discards the old one.
     */
    modeSelected(state, action: PayloadAction<MapMode>) {
      state.mode = state.mode === action.payload ? 'pan' : action.payload;
      state.measureA = null;
      state.measureB = null;
    },
    /** A measure-mode click: first sets A, second sets B, third restarts at A. */
    measurePointAdded(state, action: PayloadAction<LatLon>) {
      if (state.measureA === null) {
        state.measureA = action.payload;
      } else if (state.measureB === null) {
        state.measureB = action.payload;
      } else {
        state.measureA = action.payload;
        state.measureB = null;
      }
    },
    measureCleared(state) {
      state.measureA = null;
      state.measureB = null;
    },
    /** A reposition-mode click (or staged-marker drag). */
    repositionStaged(state, action: PayloadAction<LatLon>) {
      state.staged = action.payload;
    },
    stagedDiscarded(state) {
      state.staged = null;
    },
    /**
     * A telemetry frame's position. Consecutive duplicates are dropped so a paused
     * simulator does not flood the trail with one point.
     */
    trailPointAppended(state, action: PayloadAction<LatLon>) {
      const last = state.trail[state.trail.length - 1];
      if (last && last.lat === action.payload.lat && last.lon === action.payload.lon) {
        return;
      }
      state.trail.push(action.payload);
      if (state.trail.length > TRAIL_LIMIT) {
        state.trail.splice(0, state.trail.length - TRAIL_LIMIT);
      }
    },
    trailCleared(state) {
      state.trail = [];
    },
  },
});

export const {
  layerToggled,
  followToggled,
  modeSelected,
  measurePointAdded,
  measureCleared,
  repositionStaged,
  stagedDiscarded,
  trailPointAppended,
  trailCleared,
} = mapSlice.actions;

export default mapSlice.reducer;
