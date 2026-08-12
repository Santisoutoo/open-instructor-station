/**
 * Client state for the Position panel — and nothing else.
 *
 * Airports, runways, procedures and previews are **server state** and live in RTK Query
 * (CLAUDE.md). What is here is only what the server cannot know: which airport the
 * instructor picked, which runway end, which tab is open, what is staged, and the edits
 * they have made to the staged setup.
 *
 * The staged placement is kept as the `PlacementRequest` itself rather than as a resolved
 * `Placement`. That is deliberate: the request is the *intent*, the preview is the
 * server's answer to it, and keeping the intent means an edit re-asks the server instead
 * of the panel recomputing geometry it has no business knowing.
 */

import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import type { AircraftSetup, PlacementRequest } from '../../api/models';

/** Which placement family the panel is showing. */
export type PositionTab = 'pattern' | 'procedures' | 'parking' | 'coordinate';

/** How many airports the "recent" list remembers. */
export const RECENT_AIRPORT_LIMIT = 5;

export interface PositionState {
  /** ICAO of the selected airport, or `null` before one is chosen. */
  selectedIcao: string | null;
  /** The selected runway **end** ident, e.g. `"32L"`. */
  selectedRunwayIdent: string | null;
  activeTab: PositionTab;
  /** The procedure currently expanded in the procedures tab. */
  openProcedure: { kind: string; ident: string; transition: string | null } | null;
  /** What is staged in the commit bar. `null` means the bar is not shown. */
  staged: PlacementRequest | null;
  /**
   * The instructor's edits to the staged setup, merged over the preview's server-side.
   * Only the fields they actually touched — an untouched field must keep the geometry's
   * value, so this is a sparse overlay and never a full copy of the setup.
   */
  setupOverrides: AircraftSetup;
  /** Most recently used airports, newest first. */
  recentIcaos: string[];
}

const initialState: PositionState = {
  selectedIcao: null,
  selectedRunwayIdent: null,
  activeTab: 'pattern',
  openProcedure: null,
  staged: null,
  setupOverrides: {},
  recentIcaos: [],
};

const positionSlice = createSlice({
  name: 'position',
  initialState,
  reducers: {
    /**
     * Choose an airport. Clears everything downstream of it: a runway, a staged
     * placement or an open procedure from the previous airport are all meaningless here,
     * and leaving them would let an instructor commit a placement at the wrong field.
     */
    airportSelected(state, action: PayloadAction<string>) {
      const icao = action.payload.toUpperCase();
      state.selectedIcao = icao;
      state.selectedRunwayIdent = null;
      state.openProcedure = null;
      state.staged = null;
      state.setupOverrides = {};
      state.recentIcaos = [
        icao,
        ...state.recentIcaos.filter((entry) => entry !== icao),
      ].slice(0, RECENT_AIRPORT_LIMIT);
    },
    runwaySelected(state, action: PayloadAction<string>) {
      state.selectedRunwayIdent = action.payload;
      // The staged placement was relative to the previous runway end.
      state.staged = null;
      state.setupOverrides = {};
    },
    tabSelected(state, action: PayloadAction<PositionTab>) {
      state.activeTab = action.payload;
    },
    procedureOpened(state, action: PayloadAction<PositionState['openProcedure']>) {
      state.openProcedure = action.payload;
    },
    /** Stage a placement. Always clears previous edits: they belonged to another point. */
    placementStaged(state, action: PayloadAction<PlacementRequest>) {
      state.staged = action.payload;
      state.setupOverrides = {};
    },
    /** One field of the staging bar changed. `null` removes the override. */
    setupOverridden(
      state,
      action: PayloadAction<{ field: keyof AircraftSetup; value: unknown }>,
    ) {
      const { field, value } = action.payload;
      if (value === null || value === undefined) {
        delete state.setupOverrides[field];
      } else {
        Object.assign(state.setupOverrides, { [field]: value });
      }
    },
    staleCleared(state) {
      state.staged = null;
      state.setupOverrides = {};
    },
  },
});

export const {
  airportSelected,
  runwaySelected,
  tabSelected,
  procedureOpened,
  placementStaged,
  setupOverridden,
  staleCleared,
} = positionSlice.actions;

export default positionSlice.reducer;
