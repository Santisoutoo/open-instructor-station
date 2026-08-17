/**
 * Client state for the Fuel & Payload panel — and nothing else.
 *
 * The current loadout, the preview and its mass-and-balance verdict are all **server
 * state** and live in RTK Query (`fuelPayloadApi.ts`). What is here is only what the
 * server cannot know: which preset the instructor tapped, the edits they made to the
 * tank/station editors, whether they have acknowledged an out-of-envelope loadout, and
 * the resulting `FuelPayloadRequest` the staging bar previews and applies.
 *
 * `staged` is kept derived rather than set independently: every reducer that touches
 * `selectedPresetId`, `overlay` or `overrideEnvelope` recomputes it, so the staging
 * bar's `usePreviewFuelPayloadQuery(staged)` re-runs on every edit — the design's whole
 * point, since mass-and-balance is a whole-aircraft computation that has to be revalidated
 * live (D4 of the design).
 *
 * `overlay` is a `Loadout`, not a sparse per-field map like `positionSlice.setupOverrides`:
 * `Loadout.tanks`/`.stations` replace their whole list on the wire (D10), so an edit to
 * one tank has to carry every other known tank's current value along with it — the
 * editors build that complete array themselves (they render from the live preview/current
 * loadout) and dispatch it whole.
 */

import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import type {
  FuelPayloadPresetId,
  FuelPayloadRequest,
  Loadout,
  PayloadStation,
  TankFuel,
} from '../../api/models';

export interface FuelPayloadPanelState {
  /** The staged preset, or `null` when nothing is staged from the preset grid. */
  selectedPresetId: FuelPayloadPresetId | null;
  /** The instructor's tank/station edits, layered over the preset (or the current loadout). */
  overlay: Loadout;
  /** Set once a violated preview is explicitly acknowledged. Cleared by any preset change. */
  overrideEnvelope: boolean;
  /** The request the staging bar previews and applies. `null` means nothing is staged. */
  staged: FuelPayloadRequest | null;
}

export const initialFuelPayloadState: FuelPayloadPanelState = {
  selectedPresetId: null,
  overlay: {},
  overrideEnvelope: false,
  staged: null,
};

/**
 * The `FuelPayloadRequest` implied by the current preset/overlay/override, or `null`
 * when neither a preset nor an overlay is staged — mirroring
 * `core.fuel_payload.models.FuelPayloadRequest`'s own "at least one of preset/loadout"
 * validator: there is nothing meaningful to preview with neither.
 */
function deriveStaged(state: FuelPayloadPanelState): FuelPayloadRequest | null {
  const hasOverlay = state.overlay.tanks !== undefined || state.overlay.stations !== undefined;
  if (state.selectedPresetId === null && !hasOverlay) {
    return null;
  }
  return {
    preset: state.selectedPresetId,
    loadout: hasOverlay ? state.overlay : null,
    override_envelope: state.overrideEnvelope,
  };
}

const fuelPayloadSlice = createSlice({
  name: 'fuelPayload',
  initialState: initialFuelPayloadState,
  reducers: {
    /**
     * Stage a preset. Always clears the previous overlay and override: a violation
     * acknowledged for one loadout must not silently carry over to the next (§8.2 of
     * the design), the same reasoning as the Weather panel clearing a staged preset on
     * airport change.
     */
    presetSelected(state, action: PayloadAction<FuelPayloadPresetId>) {
      state.selectedPresetId = action.payload;
      state.overlay = {};
      state.overrideEnvelope = false;
      state.staged = deriveStaged(state);
    },
    /** The tank editor's whole replacement array — `Loadout.tanks` replaces wholesale. */
    tankEdited(state, action: PayloadAction<TankFuel[]>) {
      state.overlay.tanks = action.payload;
      state.staged = deriveStaged(state);
    },
    /** The station editor's whole replacement array — `Loadout.stations` replaces wholesale. */
    stationEdited(state, action: PayloadAction<PayloadStation[]>) {
      state.overlay.stations = action.payload;
      state.staged = deriveStaged(state);
    },
    /** "Load anyway" toggled on the staging bar, once a preview reports a violation. */
    overrideToggled(state) {
      state.overrideEnvelope = !state.overrideEnvelope;
      state.staged = deriveStaged(state);
    },
    /** Applied, or dismissed: either way the staging surface goes away whole. */
    cleared() {
      return initialFuelPayloadState;
    },
  },
});

export const { presetSelected, tankEdited, stationEdited, overrideToggled, cleared } =
  fuelPayloadSlice.actions;

export default fuelPayloadSlice.reducer;
