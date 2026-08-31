/**
 * Read-only selectors into `positionSlice` and `weatherSlice`'s already-public staged
 * state (D11 of `docs/designs/training-profiles.md`). This is the one place the Profiles
 * manager reaches across a feature boundary, and it does so read-only: no existing slice
 * file is edited, and nothing here ever dispatches. A Phase 2 stopgap — once the Scenario
 * Generator grows its own staging area, `SaveProfileForm.tsx` is expected to shrink to
 * "attach a name to what it already built" and these selectors are deleted, not extended
 * (design §10.4).
 */

import type { RootState } from '../../store';

/** The staged placement in the Position panel, or `null` when nothing is staged. */
export function selectStagedPlacement(state: RootState) {
  return state.position.staged;
}

/** The instructor's edits on top of the staged placement's own derived setup. Sparse. */
export function selectPositionSetupOverrides(state: RootState) {
  return state.position.setupOverrides;
}

/** True while a weather preset is staged in the Weather panel. */
export function selectWeatherIsStaged(state: RootState) {
  return state.weather.staged;
}

/** The staged preset id, or `null` when nothing is staged. */
export function selectStagedWeatherPresetId(state: RootState) {
  return state.weather.selectedPresetId;
}

/** The instructor's edits on top of the staged preset. Sparse. */
export function selectWeatherOverrides(state: RootState) {
  return state.weather.overrides;
}

/** The Position panel's selected airport — weather presets resolve relative to it. */
export function selectSelectedIcao(state: RootState) {
  return state.position.selectedIcao;
}

/** The Position panel's selected runway end — runway-relative weather presets need it. */
export function selectSelectedRunwayIdent(state: RootState) {
  return state.position.selectedRunwayIdent;
}
