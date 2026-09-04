import type { ComponentType } from 'react';
import type { TabId } from '../store/uiSlice';

/**
 * The module tab registry — the one shared file a new manager touches. Each entry maps
 * a tab id to its label and the dynamic import of its panel, so every panel is its own
 * chunk and the initial bundle carries none of them (the map chunk in particular owns
 * MapLibre).
 *
 * `load` is plain data rather than a `lazy()` component so this file exports no React
 * component at all (react-refresh wants component files pure); `App.tsx` wraps the
 * loaders exactly once.
 */
export interface TabDefinition {
  id: TabId;
  /** Sentence case — these are the eight module names on the tab bar. */
  label: string;
  /** Absent while the module's panel is still being built: the shell shows a stub. */
  load?: () => Promise<{ default: ComponentType }>;
  /**
   * Keep the panel mounted (hidden) after its first visit. Only the map wants this —
   * tearing down the WebGL context and re-fetching tiles on every tab switch is the
   * kind of pause an instructor notices mid-session.
   */
  keepMounted?: boolean;
  /**
   * Show `GateDelayedPanel` instead of the real panel, even though `load` is defined
   * and the module works. A deliberate, reversible release gate — not a stand-in for
   * unbuilt code (that's what an absent `load` is for). Drop the flag to lift the gate.
   */
  gated?: boolean;
}

export const TABS: readonly TabDefinition[] = [
  {
    id: 'position',
    label: 'Position',
    load: () =>
      import('../features/position/PositionPanel').then((m) => ({
        default: m.PositionPanel,
      })),
  },
  {
    id: 'scenarios',
    label: 'Scenarios',
    gated: true,
    load: () =>
      import('../features/scenarios/ScenariosPanel').then((m) => ({
        default: m.ScenariosPanel,
      })),
  },
  {
    id: 'weather',
    label: 'Weather',
    load: () =>
      import('../features/weather/WeatherPanel').then((m) => ({
        default: m.WeatherPanel,
      })),
  },
  {
    id: 'failures',
    label: 'Failures',
    gated: true,
    load: () =>
      import('../features/failures/FailuresPanel').then((m) => ({
        default: m.FailuresPanel,
      })),
  },
  {
    id: 'fuel-payload',
    label: 'Fuel & payload',
    gated: true,
    load: () =>
      import('../features/fuel-payload/FuelPayloadPanel').then((m) => ({
        default: m.FuelPayloadPanel,
      })),
  },
  {
    id: 'profiles',
    label: 'Profiles',
    gated: true,
    load: () =>
      import('../features/profiles/ProfilesPanel').then((m) => ({
        default: m.ProfilesPanel,
      })),
  },
  {
    id: 'map',
    label: 'Map',
    keepMounted: true,
    gated: true,
    load: () => import('../features/map/MapPanel').then((m) => ({ default: m.MapPanel })),
  },
  {
    id: 'aircraft',
    label: 'Aircraft',
    gated: true,
    load: () =>
      import('../features/aircraft/AircraftControlPanel').then((m) => ({
        default: m.AircraftControlPanel,
      })),
  },
  {
    id: 'landing',
    label: 'Landing analysis',
    gated: true,
    load: () =>
      import('../features/landing/LandingPanel').then((m) => ({
        default: m.LandingPanel,
      })),
  },
  {
    id: 'traffic',
    label: 'Traffic',
    gated: true,
    load: () =>
      import('../features/traffic/TrafficPanel').then((m) => ({
        default: m.TrafficPanel,
      })),
  },
  {
    id: 'camera',
    label: 'Camera',
    gated: true,
    load: () =>
      import('../features/camera/CameraPanel').then((m) => ({
        default: m.CameraPanel,
      })),
  },
  {
    id: 'pushback',
    label: 'Pushback',
    gated: true,
    load: () =>
      import('../features/pushback/PushbackPanel').then((m) => ({
        default: m.PushbackPanel,
      })),
  },
  {
    id: 'cockpit',
    label: 'Cockpit',
    load: () =>
      import('../features/cockpit/CockpitPanel').then((m) => ({
        default: m.CockpitPanel,
      })),
  },
];
