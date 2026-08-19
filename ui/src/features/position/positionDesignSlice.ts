/**
 * Client state for the Position screen "v3" replica — and nothing else.
 *
 * This is deliberately a **separate** slice from `positionSlice.ts`. That slice's shape is
 * the server-intent contract three other features read (`features/map`, `features/weather`,
 * `features/profiles`); nothing here should collide with it, or force those consumers to
 * change. Everything the replica's own screen needs — which tab, which marker, which popover
 * is open, the sample-data-driven form fields — lives here instead, registered under
 * `state.positionDesign`.
 *
 * Popover open/close state (`screenMenuOpen`, `startAtOpen`, `procedureMenuOpen`) is kept in
 * this slice rather than component `useState` on purpose: `screenMenuOpen` and `startAtOpen`
 * close each other when one opens, which is easiest to guarantee from one reducer.
 */

import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

export const DESIGN_TAB_IDS = ['approach', 'sidstar', 'airwork', 'custom'] as const;
export type DesignTabId = (typeof DESIGN_TAB_IDS)[number];

export const RUNWAY_IDS = ['04R', '22L', '04L', '22R', 'HELI'] as const;
export type RunwayId = (typeof RUNWAY_IDS)[number];

export const PARKING_FILTERS = [
  'all',
  'gate-heavy',
  'gate-medium',
  'misc',
  'tie-down',
] as const;
export type ParkingFilter = (typeof PARKING_FILTERS)[number];

export const PROCEDURE_KINDS = ['sid', 'star', 'apptr', 'final'] as const;
export type ProcedureKind = (typeof PROCEDURE_KINDS)[number];

export const AIRWORK_LEVELS = ['FL300', 'FL200', 'FL100', 'FL050'] as const;
export type AirworkLevel = (typeof AIRWORK_LEVELS)[number];

export const CUSTOM_ORIGINS = ['runway-relative', 'coordinates'] as const;
export type CustomOrigin = (typeof CUSTOM_ORIGINS)[number];

export const MARKER_IDS = [
  'takeoff',
  'downwind-left',
  'downwind-right',
  'vectors-left',
  'vectors-right',
  'base-left',
  'base-right',
  'final-3nm',
  'final-8nm',
] as const;
export type MarkerId = (typeof MARKER_IDS)[number];

export interface CustomLocationState {
  altitudeFt: number;
  headingDeg: number;
  origin: CustomOrigin;
  bearingDeg: number;
  distanceNm: number;
  latitude: number;
  longitude: number;
}

export interface AircraftConfigState {
  iasKt: number;
  pitchDeg: number;
  gearDown: boolean;
  flapsOn: boolean;
  flapsPercent: number;
  altitudeOverride: boolean;
  altitudeOverrideFt: number;
}

export interface SendWithPositionState {
  heading: boolean;
  course: boolean;
  ilsFrequency: boolean;
}

export interface PositionDesignState {
  /** The header's editable ICAO text field. */
  icaoInput: string;
  /** What "Load" last committed. */
  loadedIcao: string;
  screenMenuOpen: boolean;
  startAtOpen: boolean;
  parkingFilter: ParkingFilter;
  /** Mutually exclusive with `selectedStand`. */
  selectedRunway: RunwayId | null;
  selectedStand: string | null;
  activeTab: DesignTabId;
  selectedMarker: MarkerId;
  procedureKind: ProcedureKind;
  procedureIdent: string;
  procedureMenuOpen: boolean;
  airworkLevel: AirworkLevel;
  custom: CustomLocationState;
  config: AircraftConfigState;
  send: SendWithPositionState;
}

export const initialPositionDesignState: PositionDesignState = {
  icaoInput: 'LFMN',
  loadedIcao: 'LFMN',
  screenMenuOpen: false,
  startAtOpen: false,
  parkingFilter: 'all',
  selectedRunway: '04R',
  selectedStand: null,
  activeTab: 'approach',
  selectedMarker: 'final-3nm',
  procedureKind: 'sid',
  procedureIdent: 'BADO8A.04B.BADOD',
  procedureMenuOpen: false,
  airworkLevel: 'FL100',
  custom: {
    altitudeFt: 0,
    headingDeg: 0,
    origin: 'runway-relative',
    bearingDeg: 0,
    distanceNm: 0,
    latitude: 0,
    longitude: 0,
  },
  config: {
    iasKt: 60,
    pitchDeg: 0,
    gearDown: false,
    flapsOn: true,
    flapsPercent: 25,
    altitudeOverride: false,
    altitudeOverrideFt: 0,
  },
  send: { heading: true, course: true, ilsFrequency: true },
};

const positionDesignSlice = createSlice({
  name: 'positionDesign',
  initialState: initialPositionDesignState,
  reducers: {
    icaoTyped(state, action: PayloadAction<string>) {
      state.icaoInput = action.payload;
    },
    /** Only updates `loadedIcao` — mirroring `airportSelected` onto `positionSlice` is the
     * calling component's job, so the same-ICAO no-op guard lives at the one place that
     * knows about both slices. */
    airportLoaded(state, action: PayloadAction<string>) {
      state.loadedIcao = action.payload.toUpperCase();
    },
    screenMenuToggled(state) {
      state.screenMenuOpen = !state.screenMenuOpen;
      if (state.screenMenuOpen) {
        state.startAtOpen = false;
      }
    },
    startAtToggled(state) {
      state.startAtOpen = !state.startAtOpen;
      if (state.startAtOpen) {
        state.screenMenuOpen = false;
      }
    },
    parkingFilterSelected(state, action: PayloadAction<ParkingFilter>) {
      state.parkingFilter = action.payload;
    },
    startRunwaySelected(state, action: PayloadAction<RunwayId>) {
      state.selectedRunway = action.payload;
      state.selectedStand = null;
    },
    startStandSelected(state, action: PayloadAction<string>) {
      state.selectedStand = action.payload;
      state.selectedRunway = null;
    },
    designTabSelected(state, action: PayloadAction<DesignTabId>) {
      state.activeTab = action.payload;
    },
    markerSelected(state, action: PayloadAction<MarkerId>) {
      state.selectedMarker = action.payload;
    },
    procedureKindSelected(state, action: PayloadAction<ProcedureKind>) {
      state.procedureKind = action.payload;
    },
    procedureIdentSelected(state, action: PayloadAction<string>) {
      state.procedureIdent = action.payload;
      state.procedureMenuOpen = false;
    },
    procedureMenuToggled(state) {
      state.procedureMenuOpen = !state.procedureMenuOpen;
    },
    airworkLevelSelected(state, action: PayloadAction<AirworkLevel>) {
      state.airworkLevel = action.payload;
    },
    customOriginSelected(state, action: PayloadAction<CustomOrigin>) {
      state.custom.origin = action.payload;
    },
    /**
     * `field` covers every key of `custom`, including `origin` — but `origin` is switched
     * by `customOriginSelected`, never by a numeric field edit, so this reducer never
     * actually receives it. `Object.assign` (the same idiom `setupOverridden` and
     * `overrideSet` use) writes the one field without needing a heterogeneous indexed
     * assignment to type-check.
     */
    customFieldChanged(
      state,
      action: PayloadAction<{ field: keyof CustomLocationState; value: number }>,
    ) {
      const { field, value } = action.payload;
      Object.assign(state.custom, { [field]: value });
    },
    configChanged(
      state,
      action: PayloadAction<{ field: keyof AircraftConfigState; value: number | boolean }>,
    ) {
      const { field, value } = action.payload;
      Object.assign(state.config, { [field]: value });
    },
    sendToggled(state, action: PayloadAction<keyof SendWithPositionState>) {
      state.send[action.payload] = !state.send[action.payload];
    },
    situationReset() {
      return initialPositionDesignState;
    },
  },
});

export const {
  icaoTyped,
  airportLoaded,
  screenMenuToggled,
  startAtToggled,
  parkingFilterSelected,
  startRunwaySelected,
  startStandSelected,
  designTabSelected,
  markerSelected,
  procedureKindSelected,
  procedureIdentSelected,
  procedureMenuToggled,
  airworkLevelSelected,
  customOriginSelected,
  customFieldChanged,
  configChanged,
  sendToggled,
  situationReset,
} = positionDesignSlice.actions;

export default positionDesignSlice.reducer;
