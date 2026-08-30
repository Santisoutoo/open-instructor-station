/**
 * Client state for the Position screen — and nothing else.
 *
 * This is deliberately a **separate** slice from `positionSlice.ts`. That slice's shape is
 * the server-intent contract three other features read (`features/map`, `features/weather`,
 * `features/profiles`); nothing here should collide with it, or force those consumers to
 * change. Everything the screen's own chrome needs — which tab, which marker, which popover
 * is open, the instructor's edits to the configuration — lives here instead, registered
 * under `state.positionDesign`.
 *
 * **Nothing here is navdata.** Runways, stands, procedures, wind and the placement geometry
 * are server state and live in RTK Query. What this slice stores about them is only the
 * *identity* of what the instructor picked: a runway ident string, a stand name, a
 * procedure ident. That is why `RunwayId` is a plain ident and not a closed union — the
 * closed union belonged to the frozen sample airport, and there is no such thing now.
 *
 * The configuration fields are `| null` on purpose: `null` means "whatever the server's
 * preview resolved", a number or a boolean means "the instructor overrode it". A placement
 * on a 10 NM final that shipped a hard-coded 60 kt would be the exact bug CLAUDE.md's
 * "a placement now commands its own speed" note exists to prevent, only from the other
 * direction.
 *
 * Popover open/close state (`screenMenuOpen`, `startAtOpen`, `procedureMenuOpen`,
 * `airportMenuOpen`) is kept here rather than in component `useState`: several of them
 * close each other when one opens, which is easiest to guarantee from one reducer.
 */

import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import type { ApproachType, ParkingKind } from '../../api/models';
import { DEFAULT_FINAL, type FinalPlacementName } from './finals';

export const DESIGN_TAB_IDS = ['approach', 'sidstar', 'airwork', 'custom'] as const;
export type DesignTabId = (typeof DESIGN_TAB_IDS)[number];

/**
 * A runway **end** ident exactly as navdata publishes it — `"04R"`, `"22L"`, `"18"`.
 *
 * An alias rather than a bare `string` so every site that means "a runway end" says so;
 * it is emphatically not a closed set, because which ends exist is the airport's business.
 */
export type RunwayId = string;

/** The parking sidebar's filter: the server's own `ParkingKind`s, plus "everything". */
export type ParkingFilter = 'all' | ParkingKind;

export const PARKING_FILTERS = [
  'all',
  'gate',
  'tie_down',
  'hangar',
  'misc',
] as const satisfies readonly ParkingFilter[];

/**
 * The four procedure chips the screen offers, which are **not** the server's three kinds.
 *
 * `sid` and `star` map one-to-one. The other two split the server's `approach` kind on
 * something the data really does publish: an approach with a named transition is an
 * approach transition (`apptr`), and one without is the common final route (`final`).
 * See `procedureFamilyMatches`.
 */
export const PROCEDURE_FAMILIES = ['sid', 'star', 'apptr', 'final'] as const;
export type ProcedureFamily = (typeof PROCEDURE_FAMILIES)[number];

/**
 * The approach chips' sub-filter: one of the server's own `ApproachType`s, or everything.
 * Only meaningful under `apptr` and `final`; the SID and STAR chips ignore it.
 */
export type ApproachFilter = 'all' | ApproachType;

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

/** Which procedure the SID & STAR tab has open, and which of its legs is the placement. */
export interface ProcedureSelection {
  readonly ident: string;
  readonly transition: string | null;
  /** The leg's own sequence number, or `null` before one is picked. */
  readonly sequence: number | null;
}

export interface CustomLocationState {
  /** `null` = fall back to the loaded airport's elevation. */
  altitudeFt: number | null;
  /** `null` = fall back to the selected runway's course. */
  headingDeg: number | null;
  origin: CustomOrigin;
  /** `null` = fall back to the loaded airport's own position. */
  latitude: number | null;
  longitude: number | null;
}

/**
 * The instructor's edits to the configuration the placement will be applied with.
 *
 * Every field is `null` until they touch it, and a `null` field is simply not sent — the
 * preview's own `setup` governs. `altitudeOverride` is the one exception: an altitude is
 * always resolved by the geometry, so overriding it is an explicit act with its own switch.
 */
export interface AircraftConfigState {
  iasKt: number | null;
  pitchDeg: number | null;
  gearDown: boolean | null;
  /** `null` = leave the preview's flap setting alone. */
  flapsPercent: number | null;
  altitudeOverride: boolean;
  altitudeOverrideFt: number;
}

/**
 * The "sent with the position" switches.
 *
 * They **add** to what the placement already carries; they cannot subtract from it. The
 * server merges an override over the preview's setup field by field with `exclude_none`,
 * so there is no way to say "unset this" on the wire, and pretending otherwise would put a
 * lie on screen. Off therefore means "do not add it"; the rail shows the merged result.
 *
 * There is no `heading` switch, and there was never anything one could have done.
 * `Placement.to_setup()` sets `heading_deg` on every placement and `execute_placement`
 * writes it whatever the client sends, so the switch could only ever copy the preview's own
 * heading back over itself — while tagging the rail's Heading row "overridden" on a screen
 * where nothing had been overridden.
 */
export interface SendWithPositionState {
  course: boolean;
  ilsFrequency: boolean;
}

/**
 * The header's "Start at" and the bottom bar's "Pick stand / gate" share one popover and
 * one open flag; the anchor says which of the two mounted instances renders it.
 */
export type StartAtAnchor = 'header' | 'bottombar';

export interface PositionDesignState {
  /** The header's editable ICAO text field. */
  icaoInput: string;
  /** What "Load" last committed. Empty before the first load. */
  loadedIcao: string;
  screenMenuOpen: boolean;
  startAtOpen: boolean;
  startAtAnchor: StartAtAnchor;
  airportMenuOpen: boolean;
  parkingFilter: ParkingFilter;
  /** Mutually exclusive with `selectedStand`. */
  selectedRunway: RunwayId | null;
  selectedStand: string | null;
  activeTab: DesignTabId;
  selectedMarker: MarkerId;
  /** Which of the server's seven finals the two final markers place on. */
  finalPlacement: FinalPlacementName;
  procedureFamily: ProcedureFamily;
  approachFilter: ApproachFilter;
  procedure: ProcedureSelection | null;
  procedureMenuOpen: boolean;
  airworkLevel: AirworkLevel;
  custom: CustomLocationState;
  config: AircraftConfigState;
  send: SendWithPositionState;
}

const initialCustom: CustomLocationState = {
  altitudeFt: null,
  headingDeg: null,
  origin: 'coordinates',
  latitude: null,
  longitude: null,
};

const initialConfig: AircraftConfigState = {
  iasKt: null,
  pitchDeg: null,
  gearDown: null,
  flapsPercent: null,
  altitudeOverride: false,
  altitudeOverrideFt: 0,
};

export const initialPositionDesignState: PositionDesignState = {
  icaoInput: '',
  loadedIcao: '',
  screenMenuOpen: false,
  startAtOpen: false,
  startAtAnchor: 'header',
  airportMenuOpen: false,
  parkingFilter: 'all',
  selectedRunway: null,
  selectedStand: null,
  activeTab: 'approach',
  selectedMarker: 'final-3nm',
  finalPlacement: DEFAULT_FINAL,
  procedureFamily: 'sid',
  approachFilter: 'all',
  procedure: null,
  procedureMenuOpen: false,
  airworkLevel: 'FL100',
  custom: initialCustom,
  config: initialConfig,
  send: { course: true, ilsFrequency: true },
};

/** Everything that is only meaningful at one airport, cleared when another is loaded. */
function clearAirportScopedState(state: PositionDesignState) {
  state.selectedRunway = null;
  state.selectedStand = null;
  state.procedure = null;
  // The chips are derived from what the airport publishes; a type the last airport had
  // may not exist here, and a filter nothing matches would look like "no approaches".
  state.approachFilter = 'all';
  state.custom = initialCustom;
  state.config = initialConfig;
}

const positionDesignSlice = createSlice({
  name: 'positionDesign',
  initialState: initialPositionDesignState,
  reducers: {
    icaoTyped(state, action: PayloadAction<string>) {
      state.icaoInput = action.payload;
    },
    /**
     * Commit the typed ICAO. Mirroring `airportSelected` onto `positionSlice` is the
     * calling component's job, so the same-ICAO no-op guard lives at the one place that
     * knows about both slices.
     */
    airportLoaded(state, action: PayloadAction<string>) {
      const icao = action.payload.toUpperCase();
      state.icaoInput = icao;
      state.airportMenuOpen = false;
      if (icao === state.loadedIcao) {
        return;
      }
      state.loadedIcao = icao;
      clearAirportScopedState(state);
    },
    airportMenuOpened(state) {
      state.airportMenuOpen = true;
      state.screenMenuOpen = false;
      state.startAtOpen = false;
    },
    airportMenuClosed(state) {
      state.airportMenuOpen = false;
    },
    screenMenuToggled(state) {
      state.screenMenuOpen = !state.screenMenuOpen;
      if (state.screenMenuOpen) {
        state.startAtOpen = false;
        state.airportMenuOpen = false;
      }
    },
    startAtToggled(state, action: PayloadAction<StartAtAnchor>) {
      // Pressing the *other* trigger while open moves the popover rather than closing it:
      // the instructor asked for the picker, not for nothing.
      if (state.startAtOpen && state.startAtAnchor !== action.payload) {
        state.startAtAnchor = action.payload;
        return;
      }
      state.startAtAnchor = action.payload;
      state.startAtOpen = !state.startAtOpen;
      if (state.startAtOpen) {
        state.screenMenuOpen = false;
        state.airportMenuOpen = false;
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
    finalPlacementSelected(state, action: PayloadAction<FinalPlacementName>) {
      state.finalPlacement = action.payload;
    },
    procedureFamilySelected(state, action: PayloadAction<ProcedureFamily>) {
      state.procedureFamily = action.payload;
      state.procedure = null;
      state.approachFilter = 'all';
    },
    /** Narrow the approach chips by type. The open procedure may no longer be listed. */
    approachFilterSelected(state, action: PayloadAction<ApproachFilter>) {
      state.approachFilter = action.payload;
      state.procedure = null;
    },
    /** Open a procedure. Its leg is not chosen yet — `sequence` starts `null`. */
    procedureSelected(
      state,
      action: PayloadAction<{ ident: string; transition: string | null }>,
    ) {
      state.procedure = { ...action.payload, sequence: null };
      state.procedureMenuOpen = false;
    },
    /** Pick the leg to place on. Only legs the server marks positionable get here. */
    procedureLegSelected(state, action: PayloadAction<number>) {
      if (state.procedure !== null) {
        state.procedure = { ...state.procedure, sequence: action.payload };
      }
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
     * actually receives it. `Object.assign` (the same idiom `setupOverridden` uses) writes
     * the one field without needing a heterogeneous indexed assignment to type-check.
     */
    customFieldChanged(
      state,
      action: PayloadAction<{ field: keyof CustomLocationState; value: number | null }>,
    ) {
      const { field, value } = action.payload;
      Object.assign(state.custom, { [field]: value });
    },
    /**
     * A coordinate handed off by another manager — today only the Map's "Send to Position
     * tab" (`docs/designs/instructor-map.md` D5).
     *
     * The coordinate is **adopted**, not merely displayed: it becomes the Custom location
     * tab's own state and that tab is opened on it. That is what makes the hand-off
     * committable, and it is also what stops the bottom bar's mirror onto `positionSlice`
     * from overwriting it — the placement the screen resolves to *is* the handed-off point,
     * so the mirror writes the same thing back instead of something else.
     *
     * It needs no loaded airport: a latitude and a longitude are a whole
     * `CoordinatePlacementRequest`.
     */
    coordinateHandoffReceived(
      state,
      action: PayloadAction<{
        latitude: number;
        longitude: number;
        altitudeFt: number;
        headingDeg: number | null;
      }>,
    ) {
      const { latitude, longitude, altitudeFt, headingDeg } = action.payload;
      state.custom = {
        origin: 'coordinates',
        latitude,
        longitude,
        altitudeFt,
        headingDeg,
      };
      state.activeTab = 'custom';
      // A selected stand wins over every tab in `buildPlacementRequest`; a hand-off that
      // arrived while one was selected would otherwise be staged and never placed.
      state.selectedStand = null;
    },
    configChanged(
      state,
      action: PayloadAction<{
        field: keyof AircraftConfigState;
        value: number | boolean | null;
      }>,
    ) {
      const { field, value } = action.payload;
      Object.assign(state.config, { [field]: value });
    },
    sendToggled(state, action: PayloadAction<keyof SendWithPositionState>) {
      state.send[action.payload] = !state.send[action.payload];
    },
    /** "Reset situation": back to a blank screen, keeping the loaded airport. */
    situationReset(state) {
      return {
        ...initialPositionDesignState,
        icaoInput: state.icaoInput,
        loadedIcao: state.loadedIcao,
      };
    },
  },
});

export const {
  icaoTyped,
  airportLoaded,
  airportMenuOpened,
  airportMenuClosed,
  screenMenuToggled,
  startAtToggled,
  parkingFilterSelected,
  startRunwaySelected,
  startStandSelected,
  designTabSelected,
  markerSelected,
  finalPlacementSelected,
  procedureFamilySelected,
  approachFilterSelected,
  procedureSelected,
  procedureLegSelected,
  procedureMenuToggled,
  airworkLevelSelected,
  customOriginSelected,
  customFieldChanged,
  coordinateHandoffReceived,
  configChanged,
  sendToggled,
  situationReset,
} = positionDesignSlice.actions;

export default positionDesignSlice.reducer;
